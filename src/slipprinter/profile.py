"""The Epson TM-U295's command set, per its specification (Rev. I).

COMMANDS lists every command the printer documents, with parameter ranges.
UNSUPPORTED lists common ESC/POS commands it doesn't have, and what to use
instead. docs/capabilities.md says where each one is exposed.
"""

from dataclasses import dataclass

ESC = b"\x1b"
GS = b"\x1d"
DLE = b"\x10"
LF = b"\n"
FF = b"\x0c"

FONTS = {"5x7": 0x00, "7x7": 0x01}  # ESC ! bit 0
COLUMNS = {"5x7": 35, "7x7": 42}  # across the 65.8 mm print band, with no extra character spacing
CELL_HALF_DOTS = {"5x7": 12, "7x7": 10}  # width of one column; the band is 420 half-dots (210 dots)
BAND_HALF_DOTS = 420

# ESC ! bits. "bold" isn't one: the printer has no emphasis, so it's done by
# striking the line twice (see OVERSTRIKE).
STYLE_BITS = {"double_height": 0x10, "double_width": 0x20, "underline": 0x80}
STYLES = (*STYLE_BITS, "bold")
NOT_IN_PAGE_MODE = {"underline", "bold"}  # underline is ignored and reverse feed refused in page mode

# ESC t n, with the matching Python codec ("katakana" is handled specially).
CODEPAGES = {"pc437": (0, "cp437"), "katakana": (1, "katakana"), "pc850": (2, "cp850"), "pc858": (19, "cp858")}

# ESC R n. Each set swaps these twelve ASCII positions for national characters.
INTERNATIONAL_POSITIONS = "#$@[\\]^`{|}~"
INTERNATIONAL = {
    "usa": (0, "#$@[\\]^`{|}~"),
    "france": (1, "#$à°ç§^`éùè¨"),
    "germany": (2, "#$§ÄÖÜ^`äöüß"),
    "uk": (3, "£$@[\\]^`{|}~"),
    "denmark1": (4, "#$@ÆØÅ^`æøå~"),
    "sweden": (5, "#¤ÉÄÖÅÜéäöåü"),
    "italy": (6, "#$@°\\é^ùàòèì"),
    "spain": (7, "₧$@¡Ñ¿^`¨ñ}~"),
    "japan": (8, "#$@[¥]^`{|}~"),
    "norway": (9, "#¤ÉÆØÅÜéæøåü"),
    "denmark2": (10, "#$ÉÆØÅÜéæøåü"),
}

LINE_SPACING = 10  # 1/6" in the printer's 1/60" units (the power-on default)
MIN_FEED = 8  # the shuttle head can't feed less than 8/60" per line

# Back up one line to strike it again. Tuned on hardware in #9.
OVERSTRIKE = ESC + b"e\x01"

PAGE_WIDTH_MAX = 210  # dots, across the band
PAGE_HEIGHT_MAX = 480  # dots, along the slip
IMAGE_WIDTH_MAX = {"single": 210, "double": 420}  # ESC * 8-dot single (80 dpi) / double (160 dpi) density


@dataclass(frozen=True)
class Command:
    mnemonic: str
    prefix: bytes
    params: tuple[tuple[str, frozenset[int]], ...] = ()
    variable: str | None = None  # how trailing data is read: tabs, characters, image
    summary: str = ""


def r(lo: int, hi: int) -> frozenset[int]:
    return frozenset(range(lo, hi + 1))


ANY = r(0, 255)

COMMANDS = (
    Command("HT", b"\x09", summary="move to the next tab stop"),
    Command("LF", b"\x0a", summary="print and feed one line"),
    Command("CR", b"\x0d", summary="ignored by the serial model"),
    Command("FF", b"\x0c", summary="print and eject the slip; in page mode, print the page"),
    Command("CAN", b"\x18", summary="clear the page-mode print area"),
    Command("DLE EOT", DLE + b"\x04", (("n", frozenset({1, 2, 3, 5})),), summary="real-time status"),
    Command("ESC SP", ESC + b" ", (("n", r(0, 32)),), summary="extra space after each character, in half-dots"),
    Command("ESC !", ESC + b"!", (("n", ANY),), summary="font, double height/width, underline"),
    Command("ESC %", ESC + b"%", (("n", ANY),), summary="select/cancel user-defined characters"),
    Command("ESC &", ESC + b"&", variable="characters", summary="define user-defined characters"),
    Command("ESC *", ESC + b"*", variable="image", summary="8-dot bit image, single or double density"),
    Command("ESC 2", ESC + b"2", summary="line spacing 1/6 inch"),
    Command("ESC 3", ESC + b"3", (("n", ANY),), summary="line spacing n/60 inch"),
    Command("ESC =", ESC + b"=", (("n", ANY),), summary="enable/disable the printer"),
    Command("ESC @", ESC + b"@", summary="initialize"),
    Command("ESC C", ESC + b"C", (("n", r(0, 127)),), summary="eject length in lines (0 = all the way)"),
    Command("ESC D", ESC + b"D", variable="tabs", summary="set tab stops"),
    Command("ESC F", ESC + b"F", (("n", ANY),), summary="eject direction (LSB 1 = reverse)"),
    Command("ESC J", ESC + b"J", (("n", ANY),), summary="print and feed n/60 inch"),
    Command("ESC K", ESC + b"K", (("n", ANY),), summary="print and reverse feed n/60 inch"),
    Command("ESC L", ESC + b"L", summary="enter page mode"),
    Command("ESC R", ESC + b"R", (("n", r(0, 10)),), summary="international character set"),
    Command("ESC T", ESC + b"T", (("n", frozenset({0, 1, 2, 3, 48, 49, 50, 51})),), summary="page-mode direction"),
    Command(
        "ESC W",
        ESC + b"W",
        tuple((p, ANY) for p in ("xL", "xH", "yL", "yH", "dxL", "dxH", "dyL", "dyH")),
        summary="page-mode print area",
    ),  # fmt: skip
    Command("ESC c 3", ESC + b"c3", (("n", ANY),), summary="paper-end signal sensors (ignored by the serial model)"),
    Command("ESC c 4", ESC + b"c4", (("n", ANY),), summary="sensors that stop printing at paper end"),
    Command("ESC c 5", ESC + b"c5", (("n", ANY),), summary="enable/disable panel buttons"),
    Command("ESC d", ESC + b"d", (("n", ANY),), summary="print and feed n lines"),
    Command("ESC e", ESC + b"e", (("n", ANY),), summary="print and reverse feed n lines"),
    Command(
        "ESC f",
        ESC + b"f",
        (("t1", frozenset({0})), ("t2", r(0, 64))),
        summary="delay after slip insertion, t2 x 0.1 s",
    ),  # fmt: skip
    Command(
        "ESC p", ESC + b"p", (("m", frozenset({0, 1, 48, 49})), ("t1", ANY), ("t2", ANY)), summary="cash drawer pulse"
    ),  # fmt: skip
    Command("ESC q", ESC + b"q", summary="release the slip"),
    Command("ESC t", ESC + b"t", (("n", frozenset({0, 1, 2, 19})),), summary="code page"),
    Command("ESC u", ESC + b"u", (("n", frozenset({0, 48})),), summary="transmit drawer status"),
    Command("ESC v", ESC + b"v", summary="transmit paper sensor status"),
    Command("ESC {", ESC + b"{", (("n", ANY),), summary="upside-down printing"),
    Command("GS I", GS + b"I", (("n", frozenset({1, 2, 3, 49, 50, 51})),), summary="transmit printer ID"),
    Command("GS a", GS + b"a", (("n", ANY),), summary="automatic status back"),
    Command("GS r", GS + b"r", (("n", frozenset({1, 2, 49, 50})),), summary="transmit status"),
)

UNSUPPORTED = {
    GS + b"V": ("GS V", "the TM-U295 has no cutter; slips are ejected with FF"),
    ESC + b"i": ("ESC i", "the TM-U295 has no cutter; slips are ejected with FF"),
    ESC + b"m": ("ESC m", "the TM-U295 has no cutter; slips are ejected with FF"),
    ESC + b"E": ("ESC E", "no emphasized mode; use the 'bold' style (an overstrike)"),
    ESC + b"G": ("ESC G", "no double-strike mode; use the 'bold' style (an overstrike)"),
    ESC + b"-": ("ESC -", "underline is ESC ! bit 7 (the 'underline' style)"),
    ESC + b"M": ("ESC M", "the font is ESC ! bit 0 ('font: 7x7')"),
    GS + b"!": ("GS !", "sizes are ESC ! bits 4-5 ('double_width', 'double_height')"),
    ESC + b"a": ("ESC a", "no justification; position with 'col' or 'align: right'"),
    ESC + b"$": ("ESC $", "no absolute positioning; templates use a line x column grid"),
    ESC + b"\\": ("ESC \\", "no relative positioning; templates use a line x column grid"),
    ESC + b"V": ("ESC V", "no 90-degree rotation; use 'orientation: rotated' (page mode)"),
    GS + b"k": ("GS k", "no barcodes"),
    GS + b"v": ("GS v 0", "no raster images; use template 'images' (ESC * bit images)"),
    GS + b"(": ("GS (", "no extended GS ( functions"),
    GS + b"*": ("GS *", "no downloaded bit images; use template 'images' (ESC *)"),
    GS + b"/": ("GS /", "no downloaded bit images; use template 'images' (ESC *)"),
    ESC + b"r": ("ESC r", "single-color ribbon"),
    DLE + b"\x05": ("DLE ENQ", "not supported; use DLE EOT for status"),
    DLE + b"\x14": ("DLE DC4", "not supported; use 'slip drawer' (ESC p) for the drawer"),
}


def columns_for(font: str, char_spacing: int = 0) -> int:
    """Columns across the band, given extra character spacing in half-dots (ESC SP)."""
    return BAND_HALF_DOTS // (CELL_HALF_DOTS[font] + char_spacing)


def select_print_mode(font: str, styles: frozenset[str] = frozenset()) -> bytes:
    n = FONTS[font]
    for style in styles:
        n |= STYLE_BITS.get(style, 0)
    return ESC + b"!" + bytes([n])


def select_codepage(name: str) -> bytes:
    return ESC + b"t" + bytes([CODEPAGES[name][0]])


def select_international(name: str) -> bytes:
    return ESC + b"R" + bytes([INTERNATIONAL[name][0]])


def feed(units: int) -> bytes:
    """Print the line and feed `units`/60 inch (ESC J)."""
    return ESC + b"J" + bytes([units])


def line_spacing(units: int) -> bytes:
    return ESC + b"2" if units == LINE_SPACING else ESC + b"3" + bytes([units])


def enter_page_mode(width: int, height: int, direction: int) -> bytes:
    """ESC L, then a print area of width × height dots at the origin, then ESC T direction."""
    area = bytes([0, 0, 0, 0, width & 0xFF, width >> 8, height & 0xFF, height >> 8])
    return ESC + b"L" + ESC + b"W" + area + ESC + b"T" + bytes([direction])


def drawer_pulse(pin: int, on_ms: int, off_ms: int) -> bytes:
    """ESC p: pulse drawer kick-out pin 2 or 5; times in ms, in 2 ms steps up to 510."""
    return ESC + b"p" + bytes([0 if pin == 2 else 1, on_ms // 2, off_ms // 2])


def bit_image(columns: list[int], density: str) -> bytes:
    """ESC * for one 8-dot band; each column byte has its top dot in the MSB."""
    n = len(columns)
    return ESC + b"*" + bytes([0 if density == "single" else 1, n & 0xFF, n >> 8]) + bytes(columns)


def define_characters(glyphs: dict[str, list[int]]) -> bytes:
    """ESC & for 5x7 user-defined characters: each glyph is 5 column bytes, top dot in the MSB."""
    out = bytearray()
    for char in sorted(glyphs):
        code = ord(char)
        out += ESC + b"&" + bytes([1, code, code, 5]) + bytes(glyphs[char])
    return bytes(out)
