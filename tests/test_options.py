import pytest
import yaml
from PIL import Image as PILImage

from slipprinter.options import finish, glyph_columns, setup
from slipprinter.template import FillError, TemplateError, parse_template, preview, render

pytestmark = pytest.mark.always
ESC = b"\x1b"


def tpl(text: str, base_dir=None):
    return parse_template(yaml.safe_load(text), base_dir=base_dir)


def body(extra: str = "") -> str:
    return "name: t\nfields:\n  a: {line: 0, col: 0, width: 5}\n" + extra


# ---------------------------------------------------------------- setup and finish bytes


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ("", b""),
        ("line_spacing: 12\n", ESC + b"3\x0c"),
        ("line_spacing: 10\n", b""),
        ("char_spacing: 4\n", ESC + b" \x04"),
        ("international: germany\n", ESC + b"R\x02"),
        ("insert_delay: 0.5\n", ESC + b"f\x00\x05"),
        ("eject: {length: 3}\n", ESC + b"C\x03"),
        ("eject: {reverse: true}\n", ESC + b"F\x01"),
        ("upside_down: true\n", ESC + b"{\x01"),
    ],
)
def test_options_become_setup_commands(extra, expected):
    assert setup(tpl(body(extra)).options) == expected


def test_setup_follows_codepage_and_mode_in_the_job():
    out = render(tpl(body("line_spacing: 12\n")), {"a": "x"})
    assert out.startswith(ESC + b"t\x00" + ESC + b"!\x00" + ESC + b"3\x0c")


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ("", b"\x0c"),
        ("finish: release\n", ESC + b"q"),
        ("drawer: {pin: 5, on_ms: 50, off_ms: 250}\n", b"\x0c" + ESC + b"p\x01\x19\x7d"),
        ("drawer: {pin: 2}\n", b"\x0c" + ESC + b"p\x00\x32\xfa"),
    ],
)
def test_finish(extra, expected):
    assert finish(tpl(body(extra)).options) == expected


def test_char_spacing_reduces_columns():
    assert tpl(body("char_spacing: 2\n")).columns == 420 // 14
    with pytest.raises(TemplateError, match="at most 30 columns"):
        tpl("name: t\nchar_spacing: 2\nsize: {columns: 35}\n")


@pytest.mark.parametrize(
    ("extra", "match"),
    [
        ("line_spacing: 7\n", "line_spacing"),
        ("char_spacing: 33\n", "char_spacing"),
        ("international: mars\n", "'international' must be one of"),
        ("insert_delay: 7\n", "insert_delay"),
        ("eject: {length: 200}\n", "eject.length"),
        ("eject: {speed: 1}\n", "takes 'length' and 'reverse'"),
        ("finish: shred\n", "eject or release"),
        ("drawer: {pin: 3}\n", "pin' must be 2 or 5"),
        ("drawer: {pin: 2, on_ms: 600}\n", "drawer.on_ms"),
        ("characters: {'~': ['#']}\n", "7 rows of 5"),
        ("characters: {'é': ['.....', '.....', '.....', '.....', '.....', '.....', '.....']}\n", "printable ASCII"),
        ("font: 7x7\ncharacters: {'~': ['#####', '#####', '#####', '#####', '#####', '#####', '#####']}\n", "5x7"),
    ],
)
def test_invalid_options(extra, match):
    with pytest.raises(TemplateError, match=match):
        tpl(body(extra))


def test_upside_down_not_in_page_mode():
    with pytest.raises(TemplateError, match="upside_down"):
        tpl("name: t\norientation: rotated\npage: {width: 10, height: 10}\nsize: {lines: 1, columns: 5}\n"
            "upside_down: true\n")  # fmt: skip


# ---------------------------------------------------------------- custom characters


ARROW = [".....", "..#..", "...#.", "#####", "...#.", "..#..", "....."]


def test_glyph_rows_become_column_bytes_top_dot_in_msb():
    # row r sets bit 7 - r: column 2 has rows 1, 3, 5 (0x40 | 0x10 | 0x04)
    assert glyph_columns(ARROW, "~") == (0x10, 0x10, 0x54, 0x38, 0x10)


def test_custom_characters_are_defined_and_selected():
    out = setup(tpl(body(f"characters: {{'~': {ARROW}}}\n")).options)
    assert out == ESC + b"&\x01~~\x05" + bytes([0x10, 0x10, 0x54, 0x38, 0x10]) + ESC + b"%\x01"


# ---------------------------------------------------------------- character sets


def test_international_set_prints_national_characters_from_ascii_positions():
    t = tpl(body("international: germany\n"))
    assert b"Gr}n" in render(t, {"a": "Grün"})  # ü replaces '}' (0x7D) in the German set


def test_international_set_blocks_the_ascii_it_replaces():
    with pytest.raises(FillError, match="'\\[' can't be printed with the germany character set"):
        render(tpl(body("international: germany\n")), {"a": "[x]"})


def test_katakana_codepage():
    t = tpl(body("codepage: katakana\n"))
    out = render(t, {"a": "ｱｲ A"})
    assert out.startswith(ESC + b"t\x01") and b"\xb1\xb2 A" in out
    with pytest.raises(FillError, match="code page katakana"):
        render(t, {"a": "漢"})


# ---------------------------------------------------------------- upside down


def test_upside_down_reverses_line_order():
    t = tpl("name: t\nupside_down: true\nfields:\n  a: {line: 0, col: 0, width: 3}\n  b: {line: 1, col: 0, width: 3}\n")
    out = render(t, {"a": "one", "b": "two"})
    assert out.index(b"two") < out.index(b"one")
    lines = preview(t, {"a": "one", "b": "two"}).splitlines()
    assert lines[1].startswith("|two") and lines[2].startswith("|one")


# ---------------------------------------------------------------- images


@pytest.fixture
def logo(tmp_path):
    """A 10 x 10 image: black left half, white right half."""
    img = PILImage.new("L", (10, 10), 255)
    for x in range(5):
        for y in range(10):
            img.putpixel((x, y), 0)
    img.save(tmp_path / "logo.png")
    return tmp_path


def test_image_renders_as_bit_image_bands_with_exact_feeds(logo):
    t = tpl("name: t\nimages: [{line: 0, col: 1, path: logo.png, aspect: false}]\n", base_dir=logo)
    out = render(t, {})
    pad = bytes(6)  # one 5x7 column is 6 dots at single density
    band1 = ESC + b"*\x00\x10\x00" + pad + bytes([0xFF] * 5 + [0] * 5) + ESC + b"J\x08"
    band2 = ESC + b"*\x00\x10\x00" + pad + bytes([0xC0] * 5 + [0] * 5) + ESC + b"J\x08"
    # 2 bands = 16/60"; two grid lines are 20/60", but a 4/60" feed is under the 8/60" minimum,
    # so the image takes three lines and feeds the remaining 14/60"
    assert out.endswith(band1 + band2 + ESC + b"J\x0e")


def test_image_occupies_whole_lines_on_the_grid(logo):
    with pytest.raises(TemplateError, match="image .logo.png.: overlaps field .a."):
        tpl("name: t\nimages: [{line: 0, col: 20, path: logo.png}]\nfields:\n  a: {line: 1, col: 0, width: 5}\n",
            base_dir=logo)  # fmt: skip
    assert "#" * 2 in preview(tpl("name: t\nimages: [{line: 0, col: 1, path: logo.png}]\n", base_dir=logo), {})


@pytest.mark.parametrize(
    ("image", "match"),
    [
        ("{line: 0, col: 0, path: missing.png}", "can't read image"),
        ("{line: 0, col: 0, path: /abs/logo.png}", "relative to the template"),
        ("{line: 0, col: 0, path: logo.png, density: triple}", "single or double"),
        ("{line: 0, col: 34, path: logo.png}", "runs past the last column"),
        ("{line: 0, col: 0, path: logo.png, size: 3}", "unknown keys: size"),
    ],
)
def test_invalid_images(logo, image, match):
    with pytest.raises(TemplateError, match=match):
        tpl(f"name: t\nimages: [{image}]\n", base_dir=logo)


def test_too_wide_image_is_rejected(tmp_path):
    PILImage.new("L", (211, 8), 0).save(tmp_path / "wide.png")
    with pytest.raises(TemplateError, match="fits 210 .set a width"):
        tpl("name: t\nimages: [{line: 0, col: 0, path: wide.png}]\n", base_dir=tmp_path)
