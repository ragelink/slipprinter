"""The `slip` command line."""

import argparse
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from slipprinter import __version__, profile
from slipprinter.connection import PORT_ENV, PortNotFoundError, candidate_ports, find_port
from slipprinter.device import NoSlipError, PrinterNotReadyError, SlipPrinter
from slipprinter.images import ImageError, bands_of, image_job, prepare, preview_image
from slipprinter.library import all_templates, get_template, user_dir
from slipprinter.raw import RawCommandError, validate
from slipprinter.raw import parse as parse_raw
from slipprinter.status import PrinterStatus, StatusError
from slipprinter.template import FillError, Template, TemplateError, finish, preview, render

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
        printer.print_job(job, finish=finish(template), slip_timeout=args.timeout)
    print("Printed and released." if template.options.finish == "release" else "Printed and ejected.")
    return 0


def ruler_job(font: str, rotated_height: int | None = None) -> bytes:
    """Column digits (tens over ones), then numbered lines. Rotated: the same, in page mode."""
    if rotated_height is None:
        columns, line_count = profile.COLUMNS[font], 20
    else:
        columns, line_count = profile.rotated_columns(rotated_height, font), 16
    tens = "".join(str(i // 10) for i in range(1, columns + 1))
    ones = "".join(str(i % 10) for i in range(1, columns + 1))
    lines = [tens, ones] + [f"{n:02d}" for n in range(2, line_count)]
    body = profile.select_print_mode(font) + "\n".join(lines).encode() + b"\n"
    if rotated_height is None:
        return body
    page = profile.enter_page_mode(profile.PAGE_WIDTH_MAX, rotated_height, 1)
    return profile.select_print_mode(font) + page + body + profile.FF


def cmd_ruler(args: argparse.Namespace) -> int:
    print("Insert a slip face up.")
    with open_printer() as printer:
        printer.print_job(ruler_job(args.font, args.rotated), slip_timeout=args.timeout)
    print("Printed and ejected.")
    return 0


def cmd_image(args: argparse.Namespace) -> int:
    path = Path(args.file)
    width = args.width
    if width is None:
        try:
            with PILImage.open(path) as img:
                native = img.width
        except (OSError, UnidentifiedImageError) as e:
            raise ImageError(f"can't read image {path.name}: {e}") from None
        width = min(native, profile.IMAGE_WIDTH_MAX[args.density])  # shrink to fit the band, never enlarge
    dots = prepare(path, args.density, width=width, dither=args.dither, threshold=args.threshold,
                   aspect=not args.no_aspect)  # fmt: skip
    if args.preview:
        preview_image(dots, args.density).save(args.preview)
        print(f"Saved a preview of the printed dots to {args.preview} ({dots.width} x {dots.height} dots)")
        return 0
    print(f"{dots.width} x {dots.height} dots. Insert a slip face up.")
    with open_printer() as printer:
        printer.print_job(image_job(bands_of(dots), args.density), slip_timeout=args.timeout)
    print("Printed and ejected.")
    return 0


MODELS = {0x02: "TM-U295"}


def cmd_info(args: argparse.Namespace) -> int:
    with open_printer() as printer:
        info = printer.identify()
    print(f"Model: {MODELS.get(info['model'], 'unknown')} (ID 0x{info['model']:02x})")
    print(f"Type: 0x{info['type']:02x} ({'no cutter' if not info['type'] & 0x02 else 'cutter'})")
    print(f"ROM version: 0x{info['rom']:02x}")
    return 0


def send_checked(data: bytes, *, needs_slip: bool, force: bool = False) -> None:
    with open_printer() as printer:
        status = printer.status()
        printer.check_ready(status)
        if needs_slip and not status.slip_present and not force:
            raise NoSlipError(
                "No slip inserted, so this would wait in the printer's buffer (use --force to send anyway)"
            )
        printer.send(data)


def cmd_eject(args: argparse.Namespace) -> int:
    send_checked(profile.FF, needs_slip=True)
    print("Ejected.")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    send_checked(profile.ESC + b"q", needs_slip=True)
    print("Released.")
    return 0


def cmd_drawer(args: argparse.Namespace) -> int:
    if not (2 <= args.on <= 510 and 2 <= args.off <= 510):
        raise FillError("--on and --off are 2 to 510 ms")
    send_checked(profile.drawer_pulse(args.pin, args.on, args.off), needs_slip=False)
    print(f"Pulsed drawer pin {args.pin}.")
    return 0


def cmd_buttons(args: argparse.Namespace) -> int:
    send_checked(profile.ESC + b"c5" + (b"\x00" if args.state == "enable" else b"\x01"), needs_slip=False)
    print(f"Panel buttons {args.state}d.")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    data = parse_raw(" ".join(args.command))
    send_checked(data, needs_slip=validate(data), force=args.force)
    print(f"Sent {len(data)} bytes.")
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
    p.add_argument("--rotated", type=int, nargs="?", const=360, metavar="HEIGHT",
                   help="rotated (page mode) ruler for layouts like the check front; page height in dots, "
                        "default 360 (6 in)")  # fmt: skip
    p.add_argument("--timeout", type=float, default=120, help="seconds to wait for a slip (default 120)")
    p.set_defaults(func=cmd_ruler)

    p = sub.add_parser("image", help="print an image (PNG, JPEG, ...) on the slip")
    p.add_argument("file")
    p.add_argument("--density", choices=("single", "double"), default="single",
                   help="80 dpi (up to 210 dots wide) or 160 dpi (up to 420) across; default single")  # fmt: skip
    p.add_argument("--width", type=int, help="width in dots (default: the image's own, shrunk to fit the band)")
    p.add_argument("--dither", action="store_true", help="dither shades of gray (for photos)")
    p.add_argument("--threshold", type=int, default=128, help="gray level that prints as black, 1-255 (default 128)")
    p.add_argument("--no-aspect", action="store_true", help="don't correct for the printer's non-square dots")
    p.add_argument("--preview", metavar="OUT.png", help="save the printed dots as an image instead of printing")
    p.add_argument("--timeout", type=float, default=120, help="seconds to wait for a slip (default 120)")
    p.set_defaults(func=cmd_image)
    sub.add_parser("info", help="show the printer's model, type and ROM version").set_defaults(func=cmd_info)
    sub.add_parser("eject", help="eject the slip (FF)").set_defaults(func=cmd_eject)
    sub.add_parser("release", help="release the slip without ejecting it (ESC q)").set_defaults(func=cmd_release)
    p = sub.add_parser("drawer", help="pulse the cash drawer kick-out (ESC p)")
    p.add_argument("--pin", type=int, choices=(2, 5), default=2)
    p.add_argument("--on", type=int, default=100, help="pulse on time in ms (2-510, default 100)")
    p.add_argument("--off", type=int, default=500, help="pulse off time in ms (2-510, default 500)")
    p.set_defaults(func=cmd_drawer)
    p = sub.add_parser("buttons", help="enable or disable the printer's panel buttons (ESC c 5)")
    p.add_argument("state", choices=("enable", "disable"))
    p.set_defaults(func=cmd_buttons)
    p = sub.add_parser("send", help="send raw commands in Epson notation, e.g. slip send ESC p 0 50 250")
    p.add_argument("command", nargs="+", help='e.g. ESC "@" or "Hello" LF or 0x1B 0x40')
    p.add_argument("--force", action="store_true", help="send printing commands even with no slip inserted")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("serve", help="run the web UI on localhost")
    p.add_argument("--port", type=int, default=8295, help="port on 127.0.0.1 (default 8295; 0 picks a free one)")
    p.add_argument("--open", action="store_true", help="open it in the browser")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (TemplateError, FillError, RawCommandError, ImageError, NoSlipError, PrinterNotReadyError, StatusError,
            PortNotFoundError) as e:  # fmt: skip
        print(f"slip: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nslip: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
