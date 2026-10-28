"""A local web UI: pick a template, fill it in, preview it, print it.

Any web page can send requests to localhost, so every API call must be JSON
(which forces a CORS preflight this server never approves), must address this
server by its own host name (no DNS rebinding), and must not come from another
origin.
"""

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import urlsplit

from slipprinter.connection import PortNotFoundError
from slipprinter.device import NoSlipError, PrinterNotReadyError, SlipPrinter
from slipprinter.library import all_templates, get_template
from slipprinter.status import StatusError
from slipprinter.template import FillError, Template, TemplateError, preview, render

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 64 * 1024
PRINTER_ERRORS = (NoSlipError, PrinterNotReadyError, StatusError, PortNotFoundError, OSError)


class RequestError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Job:
    state: str = "idle"  # idle | printing | done | failed
    message: str = ""


class PrintService:
    """Owns the printer: one job at a time, status served from the job while it runs."""

    def __init__(self, open_printer: Callable[[], SlipPrinter]):
        self.open_printer = open_printer
        self.lock = threading.Lock()
        self.job = Job()
        self.thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self.job.state == "printing"

    def status(self) -> dict[str, Any]:
        if self.busy:
            return {"busy": True, "ready": False, "slip": True, "problems": [], "message": "Printing…"}
        try:
            with self.lock, self.open_printer() as printer:
                status = printer.status()
        except PRINTER_ERRORS as e:
            return {"busy": False, "ready": False, "slip": False, "problems": [str(e)], "message": str(e)}
        problems = status.problems()
        if status.waiting_for_slip:
            problems.append("a job is waiting in the printer's buffer: power-cycle the printer to clear it")
        return {
            "busy": False,
            "ready": not problems,
            "slip": status.slip_present,
            "problems": problems,
            "message": "; ".join(problems) or ("Slip inserted" if status.slip_present else "Insert a slip"),
        }

    def start(self, job: bytes) -> None:
        with self.lock:
            if self.busy:
                raise RequestError(HTTPStatus.CONFLICT, "Another job is printing")
            try:
                printer = self.open_printer()
            except PRINTER_ERRORS as e:
                raise RequestError(HTTPStatus.SERVICE_UNAVAILABLE, str(e)) from None
            try:
                status = printer.status()
                printer.check_ready(status)
                if not status.slip_present:
                    raise NoSlipError("No slip inserted")
            except PRINTER_ERRORS as e:
                printer.close()
                raise RequestError(HTTPStatus.CONFLICT, str(e)) from None
            self.job = Job("printing", "Printing…")
            self.thread = threading.Thread(target=self._run, args=(printer, job), daemon=True)
            self.thread.start()

    def _run(self, printer: SlipPrinter, job: bytes) -> None:
        try:
            with printer:
                printer.print_job(job)
            self.job = Job("done", "Printed and ejected")
        except PRINTER_ERRORS as e:
            self.job = Job("failed", str(e))


def template_json(t: Template) -> dict[str, Any]:
    return {
        "name": t.name,
        "description": t.description,
        "insert": t.insert,
        "fields": [
            {"key": f.key, "label": f.label, "type": f.type, "required": f.required and f.type != "words",
             "default": f.default, "source": f.source, "height": f.height}
            for f in t.fields
        ],
    }  # fmt: skip


def parse_fill_request(body: Any) -> tuple[Template, dict[str, str]]:
    if not isinstance(body, dict):
        raise RequestError(HTTPStatus.BAD_REQUEST, "Expected a JSON object")
    name, values = body.get("template"), body.get("values", {})
    if not isinstance(name, str):
        raise RequestError(HTTPStatus.BAD_REQUEST, "'template' must be a string")
    if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
        raise RequestError(HTTPStatus.BAD_REQUEST, "'values' must map field names to strings")
    try:
        return get_template(name), values
    except TemplateError as e:
        raise RequestError(HTTPStatus.NOT_FOUND, str(e)) from None


def _local(url: str, port: int) -> bool:
    try:
        parts = urlsplit(url)
        return parts.hostname in LOCAL_HOSTS and parts.port in (None, port) if "//" in url else False
    except ValueError:
        return False


def check_request(method: str, headers: Any, server_port: int) -> None:
    """Refuse anything a cross-site page or DNS rebinding could send."""
    if not _local("//" + headers.get("Host", ""), server_port):
        raise RequestError(HTTPStatus.FORBIDDEN, "Requests must address this server as localhost")
    origin = headers.get("Origin")
    if origin is not None and not (origin.startswith("http://") and _local(origin, server_port)):
        raise RequestError(HTTPStatus.FORBIDDEN, "Cross-origin requests are not allowed")
    if method == "POST" and headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
        raise RequestError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "POST bodies must be application/json")


class Handler(BaseHTTPRequestHandler):
    server: "SlipServer"

    def log_message(self, format: str, *args: Any) -> None:  # keep the terminal quiet
        pass

    def send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large")
        try:
            return json.loads(self.rfile.read(length) or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RequestError(HTTPStatus.BAD_REQUEST, "Body is not valid JSON") from None

    def handle_request(self, method: str) -> None:
        try:
            check_request(method, self.headers, self.server.server_port)
            route = (method, self.path.split("?")[0])
            if route == ("GET", "/"):
                page = resources.files("slipprinter").joinpath("web/index.html").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; "
                                 "script-src 'unsafe-inline'; frame-ancestors 'none'")  # fmt: skip
                self.end_headers()
                self.wfile.write(page)
            elif route == ("GET", "/api/templates"):
                templates, errors = all_templates()
                self.send_json(HTTPStatus.OK, {"templates": [template_json(t) for t in templates], "errors": errors})
            elif route == ("GET", "/api/status"):
                self.send_json(HTTPStatus.OK, self.server.service.status())
            elif route == ("GET", "/api/job"):
                job = self.server.service.job
                self.send_json(HTTPStatus.OK, {"state": job.state, "message": job.message})
            elif route == ("POST", "/api/preview"):
                template, values = parse_fill_request(self.read_json())
                self.send_json(HTTPStatus.OK, {"preview": self.fill(preview, template, values)})
            elif route == ("POST", "/api/print"):
                template, values = parse_fill_request(self.read_json())
                job = self.fill(render, template, values)
                self.server.service.start(job)
                self.send_json(HTTPStatus.ACCEPTED, {"state": "printing"})
            else:
                raise RequestError(HTTPStatus.NOT_FOUND, "Not found")
        except RequestError as e:
            self.send_json(e.status, {"error": str(e)})

    @staticmethod
    def fill(func: Callable, template: Template, values: dict[str, str]) -> Any:
        try:
            return func(template, values)
        except FillError as e:
            raise RequestError(HTTPStatus.UNPROCESSABLE_ENTITY, str(e)) from None

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")


class SlipServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: PrintService):
        super().__init__(address, Handler)
        self.service = service


def serve(port: int, open_printer: Callable[[], SlipPrinter]) -> SlipServer:
    """A server on 127.0.0.1 only. Port 0 picks a free one."""
    return SlipServer(("127.0.0.1", port), PrintService(open_printer))
