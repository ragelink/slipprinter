import pytest

from slipprinter.profile import COMMANDS, UNSUPPORTED
from slipprinter.raw import RawCommandError, parse, validate

pytestmark = pytest.mark.always


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('ESC "@"', b"\x1b@"),
        ("ESC @", b"\x1b@"),
        ("0x1B 0x40", b"\x1b@"),
        ("esc @", b"\x1b@"),
        ("ESC p 0 25 250", b"\x1bp\x00\x19\xfa"),
        ("ESC c 4 0x30", b"\x1bc40"),  # the '4' in a mnemonic is ASCII, as in Epson's manuals
        ('"Hello" LF', b"Hello\n"),
        ('ESC t 19 "10" LF', b"\x1bt\x1310\n"),  # quoted digits stay text
        ("DLE EOT 5", b"\x10\x04\x05"),
        ("ESC D 9 17 25 NUL HT", b"\x1bD\t\x11\x19\x00\t"),
        ("ESC & 1 65 65 2 0x7F 0x41", b"\x1b&\x01AA\x02\x7fA"),
        ("ESC * 0 2 0 0xFF 0x81", b"\x1b*\x00\x02\x00\xff\x81"),
        ("GS I 1", b"\x1dI\x01"),
    ],
)
def test_parses_epson_notation(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("GS V 66 0", "no cutter"),
        ("ESC E 1", "use the 'bold' style"),
        ("ESC a 1", "no justification"),
        ("GS k 4", "no barcodes"),
        ("ESC R 11", "n=11 is out of range"),
        ("ESC t 3", "n=3 is out of range"),
        ("ESC f 1 10", "t1=1 is out of range"),
        ("ESC p 0 25", "missing parameters"),
        ("ESC D 17 9 NUL", "increasing order"),
        ("ESC D 9", "missing parameters"),
        ("ESC & 1 31 31 1 0", "32 <= c1"),
        ("ESC * 0 0xD3 0", "up to 210"),
        ("ESC x", "unknown command"),
        ("0x07", "unknown command"),
        ("300", "doesn't fit in a byte"),
        ("ESC bogus", "isn't a command, name, number"),
        ('"unterminated', "can't parse"),
    ],
)
def test_rejects_unsupported_or_malformed(text, match):
    with pytest.raises(RawCommandError, match=match):
        parse(text)


@pytest.mark.parametrize(
    ("data", "uses_paper"),
    [(b"\x1b@", False), (b"\x1bp\x00\x19\xfa", False), (b"hi", True), (b"\n", True), (b"\x1bq", True)],
)
def test_validate_reports_paper_use(data, uses_paper):
    assert validate(data) is uses_paper


def test_every_command_has_a_unique_prefix_and_summary():
    prefixes = [c.prefix for c in COMMANDS]
    assert len(prefixes) == len(set(prefixes))
    assert all(c.summary for c in COMMANDS)
    assert not set(prefixes) & set(UNSUPPORTED)
