"""The `slip` command line."""

import argparse
import sys
import webbrowser
from collections.abc import Callable

from slipprinter import __version__, profile
from slipprinter.connection import PORT_ENV, PortNotFoundError, candidate_ports, find_port
from slipprinter.device import NoSlipError, PrinterNotReadyError, SlipPrinter
from slipprinter.library import all_templates, get_template, user_dir
from slipprinter.status import PrinterStatus, StatusError
from slipprinter.template import FillError, Template, TemplateError, preview, render

# Swapped out in tests for a printer on a fake transport.
open_printer: Callable[[], SlipPrinter] = SlipPrinter.open


def cmd_ports(args: argparse.Namespace) -> int:
    ports = candidate_ports()
    if not ports:
        print("No USB-serial ports found.")
        return 1
    try:
        selected = find_port()
    except PortNotFoundError:
        selected = None
    for port in ports:
        print(f"{'*' if port == selected else ' '} {port}")
    if selected is None:
        print(f"Several candidates: set {PORT_ENV} to pick one.")
    return 0


def describe(status: PrinterStatus) -> str:
    problems = status.problems()
    state = "not ready: " + "; ".join(problems) if problems else "ready"
    slip = "slip inserted" if status.slip_present else "no slip"
    queued = ", a job is waiting in the printer's buffer" if status.waiting_for_slip else ""
    return f"Printer {state} ({slip}{queued})"


def cmd_status(args: argparse.Namespace) -> int:
    with open_printer() as printer:
        status = printer.status()
    print(describe(status))
    return 0 if not status.problems() else 1


def cmd_templates(args: argparse.Namespace) -> int:
    templates, errors = all_templates()
    for t in templates:
        print(f"{t.name}: {t.description}")
        for f in t.fields:
            required = "" if f.required or f.type == "words" else " (optional)"
            derived = f" (from {f.source})" if f.source else ""
            print(f"  {f.key:<16} {f.label}, {f.type}{required}{derived}")
    for error in errors:
        print(f"! {error}")
    print(f"\nPersonal templates go in {user_dir()}")
    return 1 if errors else 0


def parse_sets(pairs: list[str]) -> dict[str, str]:
    values = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise FillError(f"--set needs field=value, got '{pair}'")
        values[key] = value
    return values


def prompt_missing(template: Template, values: dict[str, str]) -> dict[str, str]:
    """Ask for required fields that have no value or default."""
    for f in template.fields:
        if f.required and f.type != "words" and not values.get(f.key) and f.default is None:
            values[f.key] = input(f"{f.label}: ").strip()
    return values


def cmd_preview(args: argparse.Namespace) -> int:
    template = get_template(args.template)
    values = parse_sets(args.set)
    if sys.stdin.isatty() and not args.no_input:
        values = prompt_missing(template, values)
    print(preview(template, values))
    return 0


def cmd_print(args: argparse.Namespace) -> int:
    template = get_template(args.template)
    values = parse_sets(args.set)
    if sys.stdin.isatty() and not args.no_input:
        values = prompt_missing(template, values)
    job = render(template, values)  # validate everything before touching the printer
    print(preview(template, values))
    if not args.yes and input("Print this? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Not printed.")
        return 1
    print(template.insert)
    with open_printer() as printer:
        printer.print_job(job, slip_timeout=args.timeout)
    print("Printed and ejected.")
    return 0


def ruler_job(font: str) -> bytes:
    columns = profile.COLUMNS[font]
    tens = "".join(str(i // 10) for i in range(1, columns + 1))
    ones = "".join(str(i % 10) for i in range(1, columns + 1))
    lines = [tens, ones] + [f"{n:02d}" for n in range(2, 20)]
    return profile.select_print_mode(font) + "\n".join(lines).encode() + b"\n"


def cmd_ruler(args: argparse.Namespace) -> int:
    print("Insert a slip face up.")
    with open_printer() as printer:
        printer.print_job(ruler_job(args.font), slip_timeout=args.timeout)
    print("Printed and ejected.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from slipprinter.web import serve

    server = serve(args.port, lambda: open_printer())
    url = f"http://localhost:{server.server_port}/"
    print(f"Slip printer UI at {url} (Ctrl-C to stop)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slip", description="Configurable slip printing for the Epson TM-U295.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list USB-serial ports (* marks the one that will be used)").set_defaults(
        func=cmd_ports
    )
    sub.add_parser("status", help="show whether the printer is ready and a slip is in").set_defaults(func=cmd_status)
    sub.add_parser("templates", help="list templates and their fields").set_defaults(func=cmd_templates)

    for name, func, help_text in (
        ("preview", cmd_preview, "show a template filled in, without printing"),
        ("print", cmd_print, "fill in a template and print it"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("template")
        p.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="a field value (repeatable)")
        p.add_argument("--no-input", action="store_true", help="never prompt for missing fields")
        if name == "print":
            p.add_argument("--yes", "-y", action="store_true", help="print without asking for confirmation")
            p.add_argument("--timeout", type=float, default=120, help="seconds to wait for a slip (default 120)")
        p.set_defaults(func=func)

    p = sub.add_parser("ruler", help="print a column/line ruler for measuring layouts")
    p.add_argument("--font", choices=sorted(profile.FONTS), default="5x7")
    p.add_argument("--timeout", type=float, default=120, help="seconds to wait for a slip (default 120)")
    p.set_defaults(func=cmd_ruler)

    p = sub.add_parser("serve", help="run the web UI on localhost")
    p.add_argument("--port", type=int, default=8295, help="port on 127.0.0.1 (default 8295; 0 picks a free one)")
    p.add_argument("--open", action="store_true", help="open it in the browser")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (TemplateError, FillError, NoSlipError, PrinterNotReadyError, StatusError, PortNotFoundError) as e:
        print(f"slip: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nslip: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
