"""The `slip` command line."""

import argparse
import sys

from slipprinter import __version__
from slipprinter.connection import PORT_ENV, PortNotFoundError, candidate_ports, find_port


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slip", description="Configurable slip printing for the Epson TM-U295.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ports", help="list USB-serial ports (* marks the one that will be used)").set_defaults(
        func=cmd_ports
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
