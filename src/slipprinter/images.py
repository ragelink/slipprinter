"""Bit images (ESC *) from image files: logos, stamps, signatures, photos.

Each 8-dot band prints at 80 dpi (single density) or 160 dpi (double) across,
but only 60 dpi down, so dots aren't square. Images are squashed vertically to
compensate unless told otherwise. Keep images with personal content (like a
signature) in your personal template folder, never in the repo.
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from slipprinter import profile

DPI_ACROSS = {"single": 80, "double": 160}
DPI_DOWN = 60


class ImageError(ValueError):
    pass


@dataclass(frozen=True)
class Image:
    line: int
    col: int
    path: str
    density: str
    width: int  # dots, in this density's units
    bands: tuple[tuple[int, ...], ...]  # 8-dot bands, column bytes top dot in the MSB


def prepare(
    path: Path,
    density: str = "single",
    *,
    width: int | None = None,
    dither: bool = False,
    threshold: int = 128,
    aspect: bool = True,
) -> PILImage.Image:
    """The image as printer dots: scaled, aspect-corrected, and reduced to 1 bit."""
    try:
        with PILImage.open(path) as img:
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                background = PILImage.new("RGBA", img.size, "white")
                img = PILImage.alpha_composite(background, img)  # transparent prints as paper
            gray = img.convert("L")
    except (OSError, UnidentifiedImageError) as e:
        raise ImageError(f"can't read image {path.name}: {e}") from None
    most = profile.IMAGE_WIDTH_MAX[density]
    if width is not None and not 1 <= width <= most:
        raise ImageError(f"width must be 1 to {most} dots in {density} density")
    target_width = width or gray.width
    if target_width > most:
        raise ImageError(f"{path.name} is {gray.width} dots wide; {density} density fits {most} (set a width)")
    height = gray.height * target_width / gray.width
    if aspect:
        height *= DPI_DOWN / DPI_ACROSS[density]
    size = (target_width, max(1, round(height)))
    if size != gray.size:
        gray = gray.resize(size, PILImage.Resampling.LANCZOS)
    if dither:
        return gray.convert("1")  # Floyd–Steinberg
    return gray.point(lambda v: 255 if v >= threshold else 0, mode="1")


def bands_of(img: PILImage.Image) -> tuple[tuple[int, ...], ...]:
    """8-dot bands of a 1-bit image; black is a printed dot, top dot in the MSB."""
    pixels = img.load()
    bands = []
    for top in range(0, img.height, 8):
        columns = []
        for x in range(img.width):
            byte = 0
            for bit in range(8):
                y = top + bit
                if y < img.height and not pixels[x, y]:
                    byte |= 1 << (7 - bit)
            columns.append(byte)
        bands.append(tuple(columns))
    return tuple(bands)


def load_bands(
    path: Path, density: str, threshold: int = 128, *, width: int | None = None, dither: bool = False,
    aspect: bool = True,
) -> tuple[int, tuple[tuple[int, ...], ...]]:  # fmt: skip
    img = prepare(path, density, width=width, dither=dither, threshold=threshold, aspect=aspect)
    return img.width, bands_of(img)


def preview_image(img: PILImage.Image, density: str) -> PILImage.Image:
    """How the dots will look on paper: stretched back to true proportions."""
    height = round(img.height * DPI_ACROSS[density] / DPI_DOWN)
    return img.convert("L").resize((img.width, height), PILImage.Resampling.NEAREST)


def image_job(bands: tuple[tuple[int, ...], ...], density: str, pad: int = 0) -> bytes:
    """Each band, then an exact 8/60" feed so the bands touch."""
    out = bytearray()
    for band in bands:
        out += profile.bit_image([0] * pad + list(band), density) + profile.feed(8)
    return bytes(out)


def dots_per_column(font: str, density: str, char_spacing: int) -> int:
    """How many image dots one text column spans."""
    half_dots = profile.CELL_HALF_DOTS[font] + char_spacing
    return half_dots if density == "double" else half_dots // 2


def grid_size(image: Image, font: str, char_spacing: int, line_spacing: int) -> tuple[int, int]:
    """(columns, lines) the image occupies on the text grid."""
    per_col = dots_per_column(font, image.density, char_spacing)
    columns = -(-image.width // per_col)
    lines = -(-len(image.bands) * 8 // line_spacing)
    if 0 < lines * line_spacing - len(image.bands) * 8 < profile.MIN_FEED:
        lines += 1  # the head can't feed less than 8/60", so leave room for a full feed
    return columns, lines


def render_image(image: Image, font: str, char_spacing: int, line_spacing: int) -> bytes:
    """Print the bands at the image's column, then feed to the next grid line."""
    pad = image.col * dots_per_column(font, image.density, char_spacing)
    out = bytearray(image_job(image.bands, image.density, pad))
    _, lines = grid_size(image, font, char_spacing, line_spacing)
    remainder = lines * line_spacing - len(image.bands) * 8
    if remainder:
        out += profile.feed(remainder)
    return bytes(out)
