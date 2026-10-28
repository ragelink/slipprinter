"""Bit images (ESC *) from image files: logos, stamps, signatures.

Each 8-dot band prints at 80 dpi (single density) or 160 dpi (double) across,
and 60 dpi down. Keep images with personal content (like a signature) in your
personal template folder, never in the repo.
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from slipprinter import profile


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


def load_bands(path: Path, density: str, threshold: int) -> tuple[int, tuple[tuple[int, ...], ...]]:
    try:
        with PILImage.open(path) as img:
            gray = img.convert("L")
    except (OSError, UnidentifiedImageError) as e:
        raise ImageError(f"can't read image {path.name}: {e}") from None
    width, height = gray.size
    if width > profile.IMAGE_WIDTH_MAX[density]:
        raise ImageError(f"{path.name} is {width} dots wide; {density} density fits {profile.IMAGE_WIDTH_MAX[density]}")
    pixels = gray.load()
    bands = []
    for top in range(0, height, 8):
        columns = []
        for x in range(width):
            byte = 0
            for bit in range(8):
                y = top + bit
                if y < height and pixels[x, y] < threshold:
                    byte |= 1 << (7 - bit)
            columns.append(byte)
        bands.append(tuple(columns))
    return width, tuple(bands)


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
    """Print each band and feed exactly 8/60", then feed to the next grid line."""
    pad = [0] * (image.col * dots_per_column(font, image.density, char_spacing))
    out = bytearray()
    for band in image.bands:
        out += profile.bit_image(pad + list(band), image.density) + profile.feed(8)
    _, lines = grid_size(image, font, char_spacing, line_spacing)
    remainder = lines * line_spacing - len(image.bands) * 8
    if remainder:
        out += profile.feed(remainder)
    return bytes(out)
