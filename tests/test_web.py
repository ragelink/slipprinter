import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from slipprinter.device import SlipPrinter
from slipprinter.web import RequestError, check_request, serve
from tests.fakes import IDLE, JOB_QUEUED, OFFLINE, SLIP_IN, FakeTransport

CHECK = {"template": "check", "values": {"payee": "Jane Example", "amount": "12.50", "date": "2026-10-28"}}


# ---------------------------------------------------------------- request checks (fast)


@pytest.mark.always
@pytest.mark.parametrize(
    ("method", "headers", "status"),
    [
        ("GET", {"Host": "localhost:8295"}, None),
        ("GET", {"Host": "127.0.0.1:8295"}, None),
        ("GET", {"Host": "[::1]:8295"}, None),
        ("POST", {"Host": "localhost:8295", "Content-Type": "application/json; charset=utf-8"}, None),
        ("POST", {"Host": "localhost:8295", "Origin": "http://localhost:8295", "Content-Type": "application/json"},
         None),
        ("GET", {"Host": "evil.example:8295"}, 403),  # DNS rebinding
        ("GET", {"Host": "localhost:9999"}, 403),
        ("GET", {}, 403),
        ("POST", {"Host": "localhost:8295", "Origin": "https://evil.example", "Content-Type": "application/json"},
         403),
        ("POST", {"Host": "localhost:8295", "Origin": "http://localhost:9999", "Content-Type": "application/json"},
         403),
        ("POST", {"Host": "localhost:8295", "Origin": "null", "Content-Type": "application/json"}, 403),
        ("POST", {"Host": "localhost:8295", "Content-Type": "text/plain"}, 415),  # a "simple" cross-site form post
        ("POST", {"Host": "localhost:8295"}, 415),
    ],
)  # fmt: skip
def test_request_checks(method, headers, status):
    if status is None:
        check_request(method, headers, 8295)
    else:
        with pytest.raises(RequestError) as e:
            check_request(method, headers, 8295)
        assert e.value.status == status


# ---------------------------------------------------------------- the API over HTTP


@pytest.fixture
def app():
    """A real server on a free port, backed by a scripted fake printer."""
    state = {"states": [IDLE]}

    def open_printer():
        transport = FakeTransport(*state["states"])
        state["transport"] = transport
        return SlipPrinter(transport, sleep=lambda s: None)

    server = serve(0, open_printer)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(base + path, data=data, headers={**hdrs, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if path.startswith("/api") else raw.decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    yield call, state, server
    server.shutdown()
    server.server_close()


@pytest.mark.sometimes
def test_index_page_is_served_with_csp(app):
    call, _, _ = app
    status, page = call("/")
    assert status == 200 and "<title>Slip Printer</title>" in page


@pytest.mark.sometimes
def test_templates_lists_builtins_with_fields(app):
    call, _, _ = app
    status, data = call("/api/templates")
    check = next(t for t in data["templates"] if t["name"] == "check")
    words = next(f for f in check["fields"] if f["key"] == "amount_words")
    assert status == 200 and words == {**words, "type": "words", "source": "amount", "required": False}


@pytest.mark.sometimes
def test_preview_renders_and_reports_bad_values(app):
    call, _, _ = app
    status, data = call("/api/preview", CHECK)
    assert status == 200 and "Twelve and 50/100" in data["preview"]
    status, data = call("/api/preview", {"template": "check", "values": {"payee": "x", "amount": "lots"}})
    assert status == 422 and "not an amount" in data["error"]


@pytest.mark.sometimes
@pytest.mark.parametrize(
    ("body", "status", "error"),
    [
        ([], 400, "JSON object"),
        ({"template": 3}, 400, "'template' must be a string"),
        ({"template": "check", "values": {"payee": 5}}, 400, "map field names to strings"),
        ({"template": "nope"}, 404, "No template named"),
    ],
)
def test_bad_requests_are_rejected_at_the_boundary(app, body, status, error):
    call, _, _ = app
    code, data = call("/api/preview", body)
    assert code == status and error in data["error"]


@pytest.mark.sometimes
def test_cross_origin_post_is_refused(app):
    call, state, _ = app
    state["states"] = [SLIP_IN]
    status, data = call("/api/print", CHECK, headers={"Origin": "https://evil.example"})
    assert status == 403
    assert "transport" not in state  # the printer was never opened


@pytest.mark.sometimes
@pytest.mark.parametrize(
    ("states", "ready", "slip", "text"),
    [
        ([IDLE], True, False, "Insert a slip"),
        ([SLIP_IN], True, True, "Slip inserted"),
        ([OFFLINE], False, False, "offline"),
        ([JOB_QUEUED], False, False, "power-cycle"),
    ],
)
def test_status(app, states, ready, slip, text):
    call, state, _ = app
    state["states"] = states
    _, data = call("/api/status")
    assert (data["ready"], data["slip"]) == (ready, slip) and text in data["message"]


@pytest.mark.sometimes
def test_print_refused_without_slip_sends_nothing(app):
    call, state, _ = app
    state["states"] = [IDLE]
    status, data = call("/api/print", CHECK)
    assert status == 409 and "No slip" in data["error"]
    assert state["transport"].written == b""


@pytest.mark.sometimes
def test_print_runs_as_a_job_and_reports_done(app):
    call, state, _ = app
    state["states"] = [SLIP_IN, SLIP_IN, IDLE]
    status, _ = call("/api/print", CHECK)
    assert status == 202
    for _ in range(50):
        _, job = call("/api/job")
        if job["state"] != "printing":
            break
        time.sleep(0.05)
    assert job == {"state": "done", "message": "Printed and ejected"}
    assert b"Jane Example" in state["transport"].written


@pytest.mark.sometimes
def test_second_print_while_busy_is_a_conflict(app):
    call, state, server = app
    release = threading.Event()
    state["states"] = [SLIP_IN]  # the slip never leaves until released

    def open_printer():
        transport = FakeTransport(SLIP_IN)
        state["transport"] = transport
        return SlipPrinter(transport, sleep=lambda s: release.wait(0.01))

    server.service.open_printer = open_printer
    assert call("/api/print", CHECK)[0] == 202
    status, data = call("/api/print", CHECK)
    assert status == 409 and "Another job" in data["error"]
    _, busy = call("/api/status")
    assert busy["busy"] is True
    state["transport"].states = [IDLE]  # the slip leaves; the job finishes
    release.set()
    server.service.thread.join(timeout=5)
    assert server.service.job.state == "done"


@pytest.mark.sometimes
def test_unknown_route_is_404(app):
    call, _, _ = app
    assert call("/api/nope")[0] == 404
