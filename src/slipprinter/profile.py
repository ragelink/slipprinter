"""ESC/POS commands for the Epson TM-U295, per its specification.

Only commands the printer documents are here. Notably absent because the
TM-U295 doesn't support them: ESC E / ESC G (emphasis), GS ! (sizes), ESC a
(justification), absolute positioning, GS V (cut), barcodes and raster images.
"""

ESC = b"\x1b"
LF = b"\n"
FF = b"\x0c"

FONTS = {"5x7": 0x00, "7x7": 0x01}  # ESC ! bit 0
COLUMNS = {"5x7": 35, "7x7": 42}  # across the 65.8 mm print band

# ESC ! bits. "bold" isn't one: the printer has no emphasis, so it's done by
# striking the line twice (see OVERSTRIKE).
STYLE_BITS = {"double_height": 0x10, "double_width": 0x20, "underline": 0x80}
STYLES = (*STYLE_BITS, "bold")
NOT_IN_PAGE_MODE = {"underline", "bold"}  # underline is ignored and reverse feed refused in page mode

# ESC t n, with the matching Python codec.
CODEPAGES = {"pc437": (0, "cp437"), "pc850": (2, "cp850"), "pc858": (19, "cp858")}

LINE_SPACING = 10  # 1/6" in the printer's 1/60" units (the power-on default)

# Back up one line to strike it again. Tuned on hardware in #9.
OVERSTRIKE = ESC + b"e\x01"

PAGE_WIDTH_MAX = 210  # dots, across the band
PAGE_HEIGHT_MAX = 480  # dots, along the slip


def select_print_mode(font: str, styles: frozenset[str] = frozenset()) -> bytes:
    n = FONTS[font]
    for style in styles:
        n |= STYLE_BITS.get(style, 0)
    return ESC + b"!" + bytes([n])


def select_codepage(name: str) -> bytes:
    return ESC + b"t" + bytes([CODEPAGES[name][0]])


def feed(units: int) -> bytes:
    """Print the line and feed `units`/60 inch (ESC J)."""
    return ESC + b"J" + bytes([units])


def enter_page_mode(width: int, height: int, direction: int) -> bytes:
    """ESC L, then a print area of width × height dots at the origin, then ESC T direction."""
    area = bytes([0, 0, 0, 0, width & 0xFF, width >> 8, height & 0xFF, height >> 8])
    return ESC + b"L" + ESC + b"W" + area + ESC + b"T" + bytes([direction])
