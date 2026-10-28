"""Slip layouts as data: load, validate, fill in, render to bytes, preview as text.

A template is a grid of lines × columns. The printer has no absolute
positioning, so rendering is spaces and line feeds.
"""

import datetime as dt
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from slipprinter import profile
from slipprinter.images import Image, ImageError, grid_size, load_bands, render_image
from slipprinter.options import OPTION_KEYS, OptionError, Options, parse_options, setup
from slipprinter.options import finish as finish_options
from slipprinter.words import AmountError, amount_in_words, format_money, parse_amount

TYPES = ("text", "multiline", "date", "money", "words")
FIELD_KEYS = {"label", "line", "col", "width", "height", "type", "required", "default", "format", "source", "fill",
              "align", "style"}  # fmt: skip
TEMPLATE_KEYS = {"name", "description", "insert", "orientation", "font", "codepage", "size", "page", "fields", "text",
                 "images"} | OPTION_KEYS  # fmt: skip
IMAGE_KEYS = {"line", "col", "path", "density", "threshold", "width", "dither", "aspect"}


class TemplateError(ValueError):
    """The template itself is wrong."""


class FillError(ValueError):
    """A value doesn't fit the template."""


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    line: int
    col: int
    width: int
    height: int = 1
    type: str = "text"
    required: bool = True
    default: str | None = None
    format: str = "%m/%d/%Y"
    source: str | None = None
    fill: str = ""
    align: str = "left"
    style: frozenset[str] = frozenset()

    @property
    def capacity(self) -> int:
        """Characters that fit across the field (double width takes two columns each)."""
        return self.width // 2 if "double_width" in self.style else self.width

    @property
    def rows(self) -> int:
        """Grid lines the field occupies (double height takes two)."""
        return self.height * 2 if "double_height" in self.style else self.height


@dataclass(frozen=True)
class StaticText:
    line: int
    col: int
    text: str
    style: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Template:
    name: str
    description: str
    insert: str
    orientation: str
    font: str
    codepage: str
    lines: int
    columns: int
    page: dict[str, int] | None
    fields: tuple[Field, ...]
    static: tuple[StaticText, ...] = field(default=())
    options: Options = Options()
    images: tuple[Image, ...] = ()

    def field(self, key: str) -> Field:
        return next(f for f in self.fields if f.key == key)


# ---------------------------------------------------------------- loading


def _require(cond: bool, where: str, message: str) -> None:
    if not cond:
        raise TemplateError(f"{where}: {message}")


def _int(raw: dict, key: str, where: str, *, minimum: int = 0, default: int | None = None) -> int:
    value = raw.get(key, default)
    _require(isinstance(value, int) and not isinstance(value, bool), where, f"'{key}' must be a whole number")
    _require(value >= minimum, where, f"'{key}' must be at least {minimum}")
    return value


def _styles(raw: Any, where: str, orientation: str) -> frozenset[str]:
    styles = [raw] if isinstance(raw, str) else list(raw or [])
    for style in styles:
        _require(style in profile.STYLES, where, f"unknown style '{style}' (choose from {', '.join(profile.STYLES)})")
        _require(
            not (orientation == "rotated" and style in profile.NOT_IN_PAGE_MODE),
            where,
            f"style '{style}' isn't possible in rotated (page mode) layouts",
        )
    return frozenset(styles)


def _parse_field(key: str, raw: Any, orientation: str) -> Field:
    where = f"field '{key}'"
    _require(isinstance(raw, dict), where, "must be a mapping")
    unknown = set(raw) - FIELD_KEYS
    _require(not unknown, where, f"unknown keys: {', '.join(sorted(unknown))}")
    kind = raw.get("type", "text")
    _require(kind in TYPES, where, f"unknown type '{kind}' (choose from {', '.join(TYPES)})")
    align = raw.get("align", "right" if kind == "money" else "left")
    _require(align in ("left", "right"), where, "'align' must be left or right")
    fill = str(raw.get("fill", ""))
    _require(len(fill) <= 1, where, "'fill' must be a single character")
    result = Field(
        key=key,
        label=str(raw.get("label", key.replace("_", " ").title())),
        line=_int(raw, "line", where),
        col=_int(raw, "col", where),
        width=_int(raw, "width", where, minimum=1),
        height=_int(raw, "height", where, minimum=1, default=1),
        type=kind,
        required=bool(raw.get("required", kind not in ("words",))),
        default=None if raw.get("default") is None else str(raw["default"]),
        format=str(raw.get("format", "%m/%d/%Y")),
        source=raw.get("source"),
        fill=fill,
        align=align,
        style=_styles(raw.get("style"), where, orientation),
    )
    _require(result.capacity >= 1, where, "too narrow for its style")
    _require(result.height == 1 or kind == "multiline", where, "only multiline fields can be taller than one line")
    _require(kind != "words" or result.source, where, "words fields need a 'source' money field")
    _require(not ("bold" in result.style and "double_height" in result.style), where, "bold can't be double height")
    return result


def _cells(line: int, col: int, columns: int, rows: int) -> set[tuple[int, int]]:
    return {(r, c) for r in range(line, line + rows) for c in range(col, col + columns)}


def _parse_images(raw: Any, base_dir: Path | None, orientation: str, upside_down: bool) -> tuple[Image, ...]:
    images = []
    for i, item in enumerate(raw or []):
        where = f"image #{i + 1}"
        _require(isinstance(item, dict) and isinstance(item.get("path"), str), where, "needs 'path', 'line', 'col'")
        unknown = set(item) - IMAGE_KEYS
        _require(not unknown, where, f"unknown keys: {', '.join(sorted(unknown))}")
        _require(orientation == "normal", where, "images are only possible in normal layouts")
        _require(not upside_down, where, "images can't be printed upside down")
        _require(base_dir is not None, where, "image paths are relative to the template file")
        _require(not Path(item["path"]).is_absolute(), where, "'path' must be relative to the template file")
        density = item.get("density", "single")
        _require(density in profile.IMAGE_WIDTH_MAX, where, "'density' must be single or double")
        threshold = _int(item, "threshold", where, minimum=1, default=128)
        _require(threshold <= 255, where, "'threshold' is at most 255")
        try:
            width, bands = load_bands(
                base_dir / item["path"], density, threshold,
                width=item.get("width"), dither=bool(item.get("dither", False)), aspect=bool(item.get("aspect", True)),
            )  # fmt: skip
        except ImageError as e:
            raise TemplateError(f"{where}: {e}") from None
        images.append(Image(_int(item, "line", where), _int(item, "col", where), item["path"], density, width, bands))
    return tuple(images)


def parse_template(raw: Any, origin: str = "template", base_dir: Path | None = None) -> Template:
    _require(isinstance(raw, dict), origin, "must be a mapping")
    unknown = set(raw) - TEMPLATE_KEYS
    _require(not unknown, origin, f"unknown keys: {', '.join(sorted(unknown))}")
    _require(isinstance(raw.get("name"), str) and raw["name"], origin, "needs a 'name'")
    orientation = raw.get("orientation", "normal")
    _require(orientation in ("normal", "rotated"), origin, "'orientation' must be normal or rotated")
    font = raw.get("font", "5x7")
    _require(font in profile.FONTS, origin, f"'font' must be one of {', '.join(profile.FONTS)}")
    codepage = raw.get("codepage", "pc437")
    _require(codepage in profile.CODEPAGES, origin, f"'codepage' must be one of {', '.join(profile.CODEPAGES)}")
    size = raw.get("size") or {}
    _require(isinstance(size, dict), origin, "'size' must be a mapping")
    try:
        options = parse_options(raw, font, orientation)
    except OptionError as e:
        raise TemplateError(f"{origin}: {e}") from None

    page = None
    if orientation == "rotated":
        _require(font == "5x7", origin, "rotated layouts must use the 5x7 font")
        raw_page = raw.get("page")
        _require(isinstance(raw_page, dict), origin, "rotated layouts need 'page: {width, height, direction}' in dots")
        page = {
            "width": _int(raw_page, "width", "page", minimum=1),
            "height": _int(raw_page, "height", "page", minimum=1),
            "direction": _int(raw_page, "direction", "page", default=1),
        }
        _require(page["width"] <= profile.PAGE_WIDTH_MAX, "page", f"width is at most {profile.PAGE_WIDTH_MAX} dots")
        _require(page["height"] <= profile.PAGE_HEIGHT_MAX, "page", f"height is at most {profile.PAGE_HEIGHT_MAX} dots")
        _require(page["direction"] in (0, 1, 2, 3), "page", "direction must be 0-3")
        _require("lines" in size, origin, "rotated layouts need 'size: {lines}'")
        most = profile.rotated_columns(page["height"], font, options.char_spacing)
        columns = _int(size, "columns", "size", minimum=1, default=most)
        _require(columns <= most, "size", f"a {page['height']}-dot rotated page fits at most {most} columns")
    else:
        most = profile.columns_for(font, options.char_spacing)
        columns = _int(size, "columns", "size", minimum=1, default=most)
        _require(columns <= most, "size", f"the {font} font fits at most {most} columns")

    raw_fields = raw.get("fields") or {}
    _require(isinstance(raw_fields, dict), origin, "'fields' must be a mapping of name → field")
    fields = tuple(_parse_field(str(k), v, orientation) for k, v in raw_fields.items())
    static = []
    for i, item in enumerate(raw.get("text") or []):
        where = f"text #{i + 1}"
        _require(isinstance(item, dict) and isinstance(item.get("text"), str), where, "needs 'text', 'line', 'col'")
        static.append(
            StaticText(
                line=_int(item, "line", where),
                col=_int(item, "col", where),
                text=item["text"],
                style=_styles(item.get("style"), where, orientation),
            )
        )

    images = _parse_images(raw.get("images"), base_dir, orientation, options.upside_down)
    image_boxes = []
    for img in images:
        img_columns, img_lines = grid_size(img, font, options.char_spacing, options.line_spacing)
        _require(img.col + img_columns <= columns, f"image '{img.path}'", f"runs past the last column ({columns})")
        image_boxes.append((f"image '{img.path}'", img.line, 0, columns, img_lines))  # images own whole lines

    lowest = max([f.line + f.rows for f in fields] + [s.line + 1 for s in static] + [b[1] + b[4] for b in image_boxes]
                 + [1])  # fmt: skip
    lines = _int(size, "lines", "size", minimum=1, default=lowest)

    keys = {f.key for f in fields}
    taken: dict[tuple[int, int], str] = {}
    boxes = [(f"field '{f.key}'", f.line, f.col, f.width, f.rows) for f in fields]
    boxes += [(f"text '{s.text}'", s.line, s.col, _span(s.text, s.style), _rows(s.style)) for s in static]
    boxes += image_boxes
    for name, line, col, width, rows in boxes:
        _require(line + rows <= lines, name, f"runs past the last line ({lines})")
        _require(col + width <= columns, name, f"runs past the last column ({columns})")
        for cell in _cells(line, col, width, rows):
            _require(cell not in taken, name, f"overlaps {taken.get(cell)}")
            taken[cell] = name
    for f in fields:
        if f.source is not None:
            _require(f.source in keys, f"field '{f.key}'", f"source '{f.source}' isn't a field")
            _require(f.source != f.key, f"field '{f.key}'", "can't be its own source")
            _require(next(g for g in fields if g.key == f.source).type == "money", f"field '{f.key}'",
                     f"source '{f.source}' must be a money field")  # fmt: skip

    template = Template(
        name=raw["name"],
        description=str(raw.get("description", "")),
        insert=str(raw.get("insert", "Insert the slip face up.")),
        orientation=orientation,
        font=font,
        codepage=codepage,
        lines=lines,
        columns=columns,
        page=page,
        fields=fields,
        static=tuple(static),
        options=options,
        images=images,
    )
    for s in static:
        _encode(s.text, template, f"text '{s.text}'")
    return template


def load_template(path: Path) -> Template:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise TemplateError(f"{path.name}: not valid YAML ({e})") from None
    try:
        return parse_template(raw, path.name, path.parent)
    except (TemplateError, FillError) as e:
        if str(e).startswith(path.name):
            raise
        raise TemplateError(f"{path.name}: {e}") from None


def _span(text: str, style: frozenset[str]) -> int:
    return len(text) * (2 if "double_width" in style else 1)


def _rows(style: frozenset[str]) -> int:
    return 2 if "double_height" in style else 1


def _encode(text: str, template: Template, where: str) -> bytes:
    national = template.options.international
    if national != "usa":
        # National characters print from the twelve ASCII positions they replace,
        # so the ASCII characters at those positions can't be printed.
        pairs = zip(profile.INTERNATIONAL_POSITIONS, profile.INTERNATIONAL[national][1], strict=True)
        swaps = {n: a for a, n in pairs if a != n}
        blocked = next((ch for ch in text if ch in swaps.values()), None)
        if blocked:
            raise FillError(f"{where}: '{blocked}' can't be printed with the {national} character set")
        text = "".join(swaps.get(ch, ch) for ch in text)
    codec = profile.CODEPAGES[template.codepage][1]
    out = bytearray()
    for ch in text:
        try:
            encoded = _encode_katakana(ch) if codec == "katakana" else ch.encode(codec)
        except UnicodeEncodeError:
            raise FillError(f"{where}: '{ch}' can't be printed in code page {template.codepage}") from None
        out += encoded
    return bytes(out)


def _encode_katakana(ch: str) -> bytes:
    """ASCII, plus half-width katakana at 0xA1-0xDF (JIS X 0201)."""
    encoded = ch.encode("shift_jis")
    if len(encoded) != 1:
        raise UnicodeEncodeError("katakana", ch, 0, 1, "not a single-byte character")
    return encoded


# ---------------------------------------------------------------- filling in


def resolve(
    template: Template, values: dict[str, Any], today: dt.date | None = None, *, partial: bool = False
) -> dict[str, list[str]]:
    """Each field's printed lines, after defaults, formatting and fill. Raises FillError on bad input.

    With partial=True, missing required fields are left blank instead (for previewing a form in progress).
    """
    unknown = set(values) - {f.key for f in template.fields}
    if unknown:
        raise FillError(f"unknown fields: {', '.join(sorted(unknown))}")
    today = today or dt.date.today()
    raw = {}
    for f in template.fields:
        value = values.get(f.key)
        value = f.default if value in (None, "") else value
        raw[f.key] = None if value in (None, "") else str(value)

    resolved = {}
    for f in template.fields:
        value = raw[f.key]
        where = f"{f.label}"
        if f.type == "words":
            source = raw[f.source]
            value = None if source is None else _amount(amount_in_words, source, where)
        if value is None:
            if f.required and not partial:
                raise FillError(f"{where} is required")
            resolved[f.key] = []
            continue
        if f.type == "date":
            value = _date(value, f, today)
        elif f.type == "money":
            value = _amount(format_money, value, where)
        lines = _wrap(value, f, where)
        for line in lines:
            _encode(line, template, where)
        resolved[f.key] = lines
    return resolved


def _amount(convert, value: str, where: str) -> str:
    try:
        parse_amount(value)
        return convert(value)
    except AmountError as e:
        raise FillError(f"{where}: {e}") from None


def _date(value: str, f: Field, today: dt.date) -> str:
    if value == "today":
        return today.strftime(f.format)
    for fmt in (f.format, "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).strftime(f.format)
        except ValueError:
            continue
    raise FillError(f"{f.label}: '{value}' isn't a date (use {f.format}, YYYY-MM-DD or 'today')")


def _wrap(value: str, f: Field, where: str) -> list[str]:
    if f.type == "multiline":
        lines = []
        for paragraph in value.splitlines() or [""]:
            lines += textwrap.wrap(paragraph, f.capacity) or [""]
        if len(lines) > f.height:
            raise FillError(f"{where}: needs {len(lines)} lines but has room for {f.height}")
    else:
        if "\n" in value:
            raise FillError(f"{where}: must be a single line")
        lines = [value]
    for line in lines:
        if len(line) > f.capacity:
            raise FillError(f"{where}: '{line}' is {len(line)} characters; it has room for {f.capacity}")
    if f.fill:
        lines = [line.rjust(f.capacity, f.fill) if f.align == "right" else line.ljust(f.capacity, f.fill)
                 for line in lines]  # fmt: skip
    elif f.align == "right":
        lines = [line.rjust(f.capacity) for line in lines]
    return lines


# ---------------------------------------------------------------- output


@dataclass(frozen=True)
class Segment:
    col: int
    text: str
    style: frozenset[str]


def _segments(template: Template, resolved: dict[str, list[str]]) -> dict[int, list[Segment]]:
    rows: dict[int, list[Segment]] = {}
    for s in template.static:
        rows.setdefault(s.line, []).append(Segment(s.col, s.text, s.style))
    for f in template.fields:
        step = 2 if "double_height" in f.style else 1
        for i, text in enumerate(resolved[f.key]):
            rows.setdefault(f.line + i * step, []).append(Segment(f.col, text, f.style))
    return {line: sorted(segs, key=lambda s: s.col) for line, segs in rows.items()}


def _emit_line(template: Template, segments: list[Segment]) -> bytes:
    base = profile.select_print_mode(template.font)
    out, cursor = bytearray(), 0
    for seg in segments:
        out += b" " * (seg.col - cursor)
        out += profile.select_print_mode(template.font, seg.style) + _encode(seg.text, template, "text") + base
        cursor = seg.col + _span(seg.text, seg.style)
    return bytes(out)


def render(template: Template, values: dict[str, Any], today: dt.date | None = None) -> bytes:
    """The job for the printer, without init or the finish (the device layer adds those; see finish())."""
    rows = _segments(template, resolve(template, values, today))
    opts = template.options
    out = bytearray(profile.select_codepage(template.codepage) + profile.select_print_mode(template.font))
    out += setup(opts)
    if template.orientation == "rotated":
        page = template.page
        out += profile.enter_page_mode(page["width"], page["height"], page["direction"])
    images = {img.line: img for img in template.images}
    last = max([*rows, *(img.line for img in template.images)], default=-1)
    chunks = []  # one per printed line (or image), so upside-down can reverse them
    line = 0
    while line <= last:
        if line in images:
            img = images[line]
            chunks.append(render_image(img, template.font, opts.char_spacing, opts.line_spacing))
            line += grid_size(img, template.font, opts.char_spacing, opts.line_spacing)[1]
            continue
        segments = rows.get(line, [])
        chunk = _emit_line(template, segments)
        if any("double_height" in s.style for s in segments):
            chunks.append(chunk + profile.feed(2 * opts.line_spacing))
            line += 2
            continue
        chunk += profile.LF
        bold = [s for s in segments if "bold" in s.style]
        if bold:
            chunk += profile.overstrike(opts.line_spacing) + _emit_line(template, bold) + profile.LF
        chunks.append(chunk)
        line += 1
    if opts.upside_down:
        chunks.reverse()  # each line prints rotated 180°, so the slip reads correctly turned around
    out += b"".join(chunks)
    if template.orientation == "rotated":
        out += profile.FF  # print the page and return to standard mode
    return bytes(out)


def finish(template: Template) -> bytes:
    """What follows the job: eject or release the slip, and the drawer pulse if any."""
    return finish_options(template.options)


def preview(template: Template, values: dict[str, Any], today: dt.date | None = None, *, partial: bool = False) -> str:
    """The layout as text: one character per column, double width shown spaced out."""
    grid = [[" "] * template.columns for _ in range(template.lines)]
    for line, segments in _segments(template, resolve(template, values, today, partial=partial)).items():
        for seg in segments:
            text = " ".join(seg.text) + " " if "double_width" in seg.style else seg.text
            for i, ch in enumerate(text[: template.columns - seg.col]):
                grid[line][seg.col + i] = ch
    opts = template.options
    for img in template.images:
        img_columns, img_lines = grid_size(img, template.font, opts.char_spacing, opts.line_spacing)
        for line in range(img.line, img.line + img_lines):
            grid[line][img.col : img.col + img_columns] = "#" * img_columns
    if opts.upside_down:
        grid.reverse()
    border = "+" + "-" * template.columns + "+"
    return "\n".join([border, *("|" + "".join(row) + "|" for row in grid), border])
