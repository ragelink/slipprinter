"""The Rust core (slipd/slip-core) must emit the same bytes as this package.

Both sides render the same formula-generated image and compare against shared
fixture files. To change the output on purpose, regenerate the fixtures with
`uv run python -m tests.test_rust_fixtures` and update both implementations.
"""

from pathlib import Path

import pytest
from PIL import Image as PILImage

from slipprinter.images import bands_of, image_job

pytestmark = pytest.mark.always

FIXTURES = Path(__file__).parent.parent / "slipd" / "slip-core" / "tests" / "fixtures"
WIDTH, HEIGHT = 45, 20  # 20 rows: two full bands and a partial one


def pattern() -> PILImage.Image:
    """Diagonal stripes plus a diagonal line; the same formula is in the Rust test."""
    img = PILImage.new("1", (WIDTH, HEIGHT), 1)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if (x * 3 + y * 5) % 7 < 3 or x == y:
                img.putpixel((x, y), 0)
    return img


def expected() -> dict[str, bytes]:
    bands = bands_of(pattern())
    return {f"pattern-{density}.bin": image_job(bands, density) for density in ("single", "double")}


@pytest.mark.parametrize("name", sorted(expected()))
def test_fixture_matches_python(name):
    assert (FIXTURES / name).read_bytes() == expected()[name]


if __name__ == "__main__":
    for name, data in expected().items():
        (FIXTURES / name).write_bytes(data)
        print(f"wrote {name} ({len(data)} bytes)")
