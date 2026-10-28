import datetime as dt

import pytest
import yaml

from slipprinter.library import all_templates, get_template
from slipprinter.template import FillError, TemplateError, parse_template, preview, render, resolve

pytestmark = pytest.mark.always

TODAY = dt.date(2026, 10, 28)
ESC = b"\x1b"
MODE = ESC + b"!\x00"  # 5x7, no styles
CP437 = ESC + b"t\x00"


def tpl(text: str):
    return parse_template(yaml.safe_load(text))


SIMPLE = """
name: simple
size: {columns: 20}
fields:
  who: {line: 0, col: 2, width: 10}
  amt: {line: 1, col: 10, width: 10, type: money}
"""


# ---------------------------------------------------------------- golden bytes


def test_render_simple_layout_exact_bytes():
    out = render(tpl(SIMPLE), {"who": "Jane", "amt": "12.5"})
    assert out == (
        CP437 + MODE
        + b"  " + MODE + b"Jane" + MODE + b"\n"
        + b" " * 10 + MODE + b"    $12.50" + MODE + b"\n"
    )  # fmt: skip


def test_blank_lines_between_fields_are_line_feeds():
    t = tpl("name: t\nfields:\n  a: {line: 0, col: 0, width: 1}\n  b: {line: 3, col: 0, width: 1}\n")
    assert render(t, {"a": "A", "b": "B"}) == CP437 + MODE + MODE + b"A" + MODE + b"\n\n\n" + MODE + b"B" + MODE + b"\n"


def test_styles_map_to_print_mode_bits():
    t = tpl("""
name: t
fields:
  u: {line: 0, col: 0, width: 4, style: underline}
  w: {line: 1, col: 0, width: 4, style: [double_width]}
""")
    out = render(t, {"u": "ab", "w": "cd"})
    assert ESC + b"!\x80ab" in out
    assert ESC + b"!\x20cd" in out


def test_bold_is_an_overstrike_of_just_the_bold_segments():
    t = tpl("""
name: t
fields:
  plain: {line: 0, col: 0, width: 5}
  strong: {line: 0, col: 6, width: 5, style: bold}
""")
    out = render(t, {"plain": "aa", "strong": "BB"})
    first = MODE + b"aa" + MODE + b"    " + MODE + b"BB" + MODE + b"\n"
    second = ESC + b"e\x01" + b" " * 6 + MODE + b"BB" + MODE + b"\n"
    assert out == CP437 + MODE + first + second


def test_double_height_feeds_two_lines_and_reserves_the_next():
    t = tpl("""
name: t
fields:
  big: {line: 0, col: 0, width: 4, style: double_height}
  after: {line: 2, col: 0, width: 4}
""")
    out = render(t, {"big": "X", "after": "Y"})
    assert out == CP437 + MODE + ESC + b"!\x10X" + MODE + ESC + b"J\x14" + MODE + b"Y" + MODE + b"\n"


def test_rotated_layout_wraps_content_in_page_mode():
    t = tpl("""
name: t
orientation: rotated
page: {width: 210, height: 360, direction: 1}
size: {lines: 2, columns: 30}
fields:
  a: {line: 0, col: 0, width: 5}
""")
    out = render(t, {"a": "hi"})
    page = ESC + b"L" + ESC + b"W\x00\x00\x00\x00\xd2\x00\x68\x01" + ESC + b"T\x01"
    assert out == CP437 + MODE + page + MODE + b"hi" + MODE + b"\n" + b"\x0c"


def test_codepage_is_selected_and_text_encoded():
    t = tpl("name: t\ncodepage: pc858\nfields:\n  a: {line: 0, col: 0, width: 5}\n")
    out = render(t, {"a": "5€"})
    assert out.startswith(ESC + b"t\x13")
    assert b"5\xd5" in out


# ---------------------------------------------------------------- filling in


def test_money_is_formatted_right_aligned_with_protection_fill():
    t = tpl("name: t\nfields:\n  amt: {line: 0, col: 0, width: 12, type: money, fill: '*'}\n")
    assert resolve(t, {"amt": "1234.5"}) == {"amt": ["***$1,234.50"]}


def test_words_follow_their_money_source():
    t = tpl("""
name: t
fields:
  amt: {line: 0, col: 0, width: 10, type: money}
  words: {line: 1, col: 0, width: 35, type: words, source: amt, fill: '-'}
""")
    assert resolve(t, {"amt": "21.01"})["words"] == ["Twenty-One and 01/100".ljust(35, "-")]


def test_date_today_default_and_formats():
    t = tpl("name: t\nfields:\n  d: {line: 0, col: 0, width: 10, type: date, default: today}\n")
    assert resolve(t, {}, TODAY) == {"d": ["10/28/2026"]}
    assert resolve(t, {"d": "2026-01-02"}, TODAY) == {"d": ["01/02/2026"]}
    assert resolve(t, {"d": "01/02/2026"}, TODAY) == {"d": ["01/02/2026"]}
    with pytest.raises(FillError, match="isn't a date"):
        resolve(t, {"d": "tomorrow"}, TODAY)


def test_multiline_wraps_and_respects_height():
    t = tpl("name: t\nfields:\n  b: {line: 0, col: 0, width: 10, height: 2, type: multiline}\n")
    assert resolve(t, {"b": "one two three"}) == {"b": ["one two", "three"]}
    with pytest.raises(FillError, match="room for 2"):
        resolve(t, {"b": "one two three four five six"})


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"amt": "1"}, "Who is required"),
        ({"who": "x" * 11, "amt": "1"}, "room for 10"),
        ({"who": "a\nb", "amt": "1"}, "single line"),
        ({"who": "x", "amt": "lots"}, "not an amount"),
        ({"who": "x", "amt": "1", "extra": "y"}, "unknown fields: extra"),
        ({"who": "x", "amt": "99999999"}, "room for 10"),
        ({"who": "ü→", "amt": "1"}, "can't be printed"),
    ],
)
def test_bad_values_are_rejected_not_truncated(values, match):
    with pytest.raises(FillError, match=match):
        resolve(tpl(SIMPLE), values)


def test_partial_preview_leaves_missing_required_fields_blank():
    t = tpl(SIMPLE)
    assert "$12.00" in preview(t, {"amt": "12"}, partial=True)
    with pytest.raises(FillError, match="Who is required"):
        preview(t, {"amt": "12"})
    with pytest.raises(FillError, match="not an amount"):
        preview(t, {"amt": "lots"}, partial=True)  # bad values are still errors


def test_optional_field_left_blank_prints_nothing():
    t = tpl("name: t\nfields:\n  a: {line: 0, col: 0, width: 3, required: false}\n")
    assert render(t, {}) == CP437 + MODE


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("fields: {a: {line: 0, col: 0, width: 1}}", "needs a 'name'"),
        ("name: t\nbogus: 1", "unknown keys: bogus"),
        ("name: t\nfont: 9x9", "'font' must be one of"),
        ("name: t\nsize: {columns: 36}", "at most 35 columns"),
        ("name: t\nfont: 7x7\nsize: {columns: 43}", "at most 42 columns"),
        ("name: t\nfields: {a: {line: 0, col: 30, width: 6}}", "runs past the last column"),
        ("name: t\nsize: {lines: 2}\nfields: {a: {line: 2, col: 0, width: 1}}", "runs past the last line"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 5}, b: {line: 0, col: 4, width: 2}}", "overlaps field 'a'"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 4, style: double_height}, b: {line: 1, col: 0, width: 1}}",
         "overlaps field 'a'"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 1, type: blob}}", "unknown type 'blob'"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 1, style: blink}}", "unknown style 'blink'"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 1, style: double_width}}", "too narrow"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 5, height: 2}}", "only multiline"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 5, type: words}}", "need a 'source'"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 5, type: words, source: b}}", "isn't a field"),
        ("name: t\nfields: {b: {line: 1, col: 0, width: 5}, a: {line: 0, col: 0, width: 5, type: words, source: b}}",
         "must be a money field"),
        ("name: t\nfields: {a: {line: -1, col: 0, width: 1}}", "at least 0"),
        ("name: t\nfields: {a: {line: 0, col: 0, width: 1, fill: '**'}}", "single character"),
        ("name: t\norientation: rotated", "need 'page"),
        ("name: t\norientation: rotated\npage: {width: 211, height: 10}\nsize: {lines: 1, columns: 5}",
         "at most 210"),
        ("name: t\norientation: rotated\npage: {width: 10, height: 10}\nsize: {lines: 1, columns: 5}\n"
         "fields: {a: {line: 0, col: 0, width: 1, style: underline}}", "isn't possible in rotated"),
        ("name: t\norientation: rotated\npage: {width: 10, height: 10}\nsize: {lines: 1, columns: 5}\n"
         "fields: {a: {line: 0, col: 0, width: 1, style: bold}}", "isn't possible in rotated"),
        ("name: t\ntext: [{line: 0, col: 0, text: '→'}]", "can't be printed"),
    ],
)  # fmt: skip
def test_invalid_templates_are_rejected_with_a_reason(body, match):
    with pytest.raises((TemplateError, FillError), match=match):
        tpl(body)


# ---------------------------------------------------------------- built-ins


def test_builtin_templates_all_load():
    templates, errors = all_templates()
    assert errors == []
    assert {"check", "endorse", "note"} <= {t.name for t in templates}


def test_check_preview_places_every_field():
    text = preview(get_template("check"), {"payee": "Jane Example", "amount": "1234.56", "memo": "Rent"}, TODAY)
    assert "10/28/2026" in text
    assert "Jane Example" in text
    assert "*****$1,234.56" in text
    assert "One Thousand Two Hundred Thirty-Four and 56/100***" in text
    assert "Rent" in text


def test_user_templates_override_builtins(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIP_TEMPLATES", str(tmp_path))
    (tmp_path / "note.yaml").write_text("name: note\ndescription: mine\nfields: {a: {line: 0, col: 0, width: 3}}\n")
    assert get_template("note").description == "mine"


def test_template_name_must_match_its_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIP_TEMPLATES", str(tmp_path))
    (tmp_path / "mine.yaml").write_text("name: other\n")
    with pytest.raises(TemplateError, match="named 'mine'"):
        get_template("mine")
    assert any("named 'mine'" in e for e in all_templates()[1])


def test_unknown_template_lists_available():
    with pytest.raises(TemplateError, match="Available: .*check"):
        get_template("nope")
