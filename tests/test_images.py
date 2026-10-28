import pytest
from PIL import Image as PILImage

from slipprinter.images import ImageError, bands_of, image_job, prepare, preview_image

pytestmark = pytest.mark.always


@pytest.fixture
def square(tmp_path):
    """An 80 x 80 image: a black square on white."""
    img = PILImage.new("L", (80, 80), 255)
    img.paste(0, (20, 20, 60, 60))
    path = tmp_path / "square.png"
    img.save(path)
    return path


@pytest.mark.parametrize(
    ("density", "aspect", "size"),
    [
        ("single", True, (80, 60)),  # 80 dpi across, 60 down: squash to 3/4 height
        ("double", True, (80, 30)),  # 160 dpi across: squash to 3/8
        ("single", False, (80, 80)),
    ],
)
def test_aspect_correction(square, density, aspect, size):
    assert prepare(square, density, aspect=aspect).size == size


def test_width_scales_proportionally(square):
    assert prepare(square, "single", width=40).size == (40, 30)


def test_preview_restores_true_proportions(square):
    img = prepare(square, "single")
    assert preview_image(img, "single").size == (80, 80)


def test_dither_produces_mixed_dots_for_gray(tmp_path):
    PILImage.new("L", (40, 16), 128).save(tmp_path / "gray.png")
    dithered = prepare(tmp_path / "gray.png", dither=True, aspect=False)
    thresholded = prepare(tmp_path / "gray.png", threshold=100, aspect=False)
    black = sum(1 for p in dithered.get_flattened_data() if not p)
    assert 0.3 < black / (40 * 16) < 0.7  # roughly half the dots
    assert all(thresholded.get_flattened_data())  # 128 >= 100: all paper


def test_transparent_pixels_print_as_paper(tmp_path):
    img = PILImage.new("RGBA", (8, 8), (0, 0, 0, 0))
    img.putpixel((0, 0), (0, 0, 0, 255))
    img.save(tmp_path / "t.png")
    bands = bands_of(prepare(tmp_path / "t.png", aspect=False))
    assert bands == ((0x80, 0, 0, 0, 0, 0, 0, 0),)


def test_image_job_pads_and_feeds_each_band():
    out = image_job(((0xFF, 0x01),), "double", pad=2)
    assert out == b"\x1b*\x01\x04\x00" + bytes([0, 0, 0xFF, 0x01]) + b"\x1bJ\x08"


@pytest.mark.parametrize(("width", "match"), [(0, "1 to 210"), (211, "1 to 210")])
def test_bad_width(square, width, match):
    with pytest.raises(ImageError, match=match):
        prepare(square, width=width)


def test_unreadable_file(tmp_path):
    (tmp_path / "x.png").write_text("not an image")
    with pytest.raises(ImageError, match="can't read image"):
        prepare(tmp_path / "x.png")
