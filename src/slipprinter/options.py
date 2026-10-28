"""Template-wide printer options: spacing, character sets, custom characters, and slip handling."""

from dataclasses import dataclass
from typing import Any

from slipprinter import profile

OPTION_KEYS = {"line_spacing", "char_spacing", "international", "upside_down", "insert_delay", "eject", "finish",
               "drawer", "characters"}  # fmt: skip
GLYPH_ROWS, GLYPH_COLUMNS = 7, 5


class OptionError(ValueError):
    pass


@dataclass(frozen=True)
class Options:
    line_spacing: int = profile.LINE_SPACING
    char_spacing: int = 0
    international: str = "usa"
    upside_down: bool = False
    insert_delay: float | None = None
    eject_length: int = 0
    eject_reverse: bool = False
    finish: str = "eject"
    drawer: tuple[int, int, int] | None = None  # pin, on ms, off ms
    characters: tuple[tuple[str, tuple[int, ...]], ...] = ()


def _check(cond: bool, message: str) -> None:
    if not cond:
        raise OptionError(message)


def _whole(value: Any, name: str, lo: int, hi: int) -> int:
    _check(isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi,
           f"'{name}' must be a whole number from {lo} to {hi}")  # fmt: skip
    return value


def glyph_columns(rows: Any, char: str) -> tuple[int, ...]:
    """7 rows of 5 '#'/'.' characters → 5 column bytes, top dot in the MSB."""
    _check(
        isinstance(rows, list) and len(rows) == GLYPH_ROWS
        and all(isinstance(r, str) and len(r) == GLYPH_COLUMNS and set(r) <= {"#", "."} for r in rows),
        f"character '{char}' must be {GLYPH_ROWS} rows of {GLYPH_COLUMNS} '#' or '.'",
    )  # fmt: skip
    return tuple(
        sum(1 << (7 - row) for row in range(GLYPH_ROWS) if rows[row][col] == "#") for col in range(GLYPH_COLUMNS)
    )


def parse_options(raw: dict, font: str, orientation: str) -> Options:
    kwargs: dict[str, Any] = {}
    if "line_spacing" in raw:
        kwargs["line_spacing"] = _whole(raw["line_spacing"], "line_spacing", profile.MIN_FEED, 255)
    if "char_spacing" in raw:
        kwargs["char_spacing"] = _whole(raw["char_spacing"], "char_spacing", 0, 32)
    if "international" in raw:
        name = raw["international"]
        _check(name in profile.INTERNATIONAL, f"'international' must be one of {', '.join(profile.INTERNATIONAL)}")
        kwargs["international"] = name
    if raw.get("upside_down"):
        _check(orientation == "normal", "upside_down isn't possible in rotated (page mode) layouts")
        kwargs["upside_down"] = True
    if "insert_delay" in raw:
        delay = raw["insert_delay"]
        _check(isinstance(delay, int | float) and 0 <= delay <= 6.4, "'insert_delay' must be 0 to 6.4 seconds")
        kwargs["insert_delay"] = float(delay)
    eject = raw.get("eject") or {}
    _check(isinstance(eject, dict) and set(eject) <= {"length", "reverse"}, "'eject' takes 'length' and 'reverse'")
    if "length" in eject:
        kwargs["eject_length"] = _whole(eject["length"], "eject.length", 0, 127)
    kwargs["eject_reverse"] = bool(eject.get("reverse", False))
    if "finish" in raw:
        _check(raw["finish"] in ("eject", "release"), "'finish' must be eject or release")
        kwargs["finish"] = raw["finish"]
    if "drawer" in raw:
        drawer = raw["drawer"]
        allowed = {"pin", "on_ms", "off_ms"}
        _check(isinstance(drawer, dict) and set(drawer) <= allowed, "'drawer' takes pin, on_ms, off_ms")
        _check(drawer.get("pin") in (2, 5), "'drawer.pin' must be 2 or 5")
        kwargs["drawer"] = (
            drawer["pin"],
            _whole(drawer.get("on_ms", 100), "drawer.on_ms", 2, 510),
            _whole(drawer.get("off_ms", 500), "drawer.off_ms", 2, 510),
        )
    if "characters" in raw:
        chars = raw["characters"]
        _check(font == "5x7", "custom 'characters' need the 5x7 font")
        _check(isinstance(chars, dict) and chars, "'characters' maps a character to its 7 rows")
        glyphs = []
        for char, rows in chars.items():
            _check(isinstance(char, str) and len(char) == 1 and 32 <= ord(char) <= 126,
                   f"custom character '{char}' must be one printable ASCII character")  # fmt: skip
            glyphs.append((char, glyph_columns(rows, char)))
        kwargs["characters"] = tuple(sorted(glyphs))
    return Options(**kwargs)


def setup(options: Options) -> bytes:
    """Commands that apply the options at the start of a job (after ESC @ resets everything)."""
    out = bytearray()
    if options.line_spacing != profile.LINE_SPACING:
        out += profile.line_spacing(options.line_spacing)
    if options.char_spacing:
        out += profile.ESC + b" " + bytes([options.char_spacing])
    if options.international != "usa":
        out += profile.select_international(options.international)
    if options.insert_delay is not None:
        out += profile.ESC + b"f\x00" + bytes([round(options.insert_delay * 10)])
    if options.eject_length:
        out += profile.ESC + b"C" + bytes([options.eject_length])
    if options.eject_reverse:
        out += profile.ESC + b"F\x01"
    if options.characters:
        out += profile.define_characters(dict(options.characters)) + profile.ESC + b"%\x01"
    if options.upside_down:
        out += profile.ESC + b"{\x01"
    return bytes(out)


def finish(options: Options) -> bytes:
    """What follows the job: eject or release the slip, then pulse the drawer if asked."""
    out = profile.FF if options.finish == "eject" else profile.ESC + b"q"
    if options.drawer:
        out += profile.drawer_pulse(*options.drawer)
    return out
