"""What a model is shown of an attached image (spec 2026-10-30 §3.6).

PNG, JPEG, WebP and GIF are shown as they are. HEIC/HEIF, AVIF, TIFF, BMP and ICO — formats vision
models do not take — are shown as a PNG copy; the original file is never changed. SVG is a
drawing in text: it is never sent as a picture, it is opened as a file.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from clue_agents.attachment_images import (
    CONVERTIBLE_IMAGE_TYPES,
    MODEL_NATIVE_IMAGE_TYPES,
    is_shown_as_picture,
    viewable_image,
)

HEIC = (Path(__file__).parent / "fixtures" / "one-pixel.heic").read_bytes()


def _encoded(fmt: str, size: tuple[int, int] = (5, 3)) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGBA" if fmt == "ICO" else "RGB", size, (10, 120, 200))
    image.save(buffer, format=fmt, **({"sizes": [size]} if fmt == "ICO" else {}))
    return buffer.getvalue()


def test_model_native_images_are_shown_unchanged() -> None:
    png = _encoded("PNG")
    assert viewable_image(png, "image/png") == (png, "image/png")
    assert frozenset(
        {"image/png", "image/jpeg", "image/webp", "image/gif"}
    ) == MODEL_NATIVE_IMAGE_TYPES


@pytest.mark.parametrize(
    ("media_type", "data", "size"),
    [
        ("image/tiff", _encoded("TIFF"), (5, 3)),
        ("image/bmp", _encoded("BMP"), (5, 3)),
        ("image/x-icon", _encoded("ICO", (16, 16)), (16, 16)),
        ("image/avif", _encoded("AVIF", (8, 8)), (8, 8)),
        ("image/heic", HEIC, (3, 2)),
        ("image/heif", HEIC, (3, 2)),
    ],
)
def test_other_image_formats_are_shown_as_a_png_copy(
    media_type: str, data: bytes, size: tuple[int, int]
) -> None:
    assert media_type in CONVERTIBLE_IMAGE_TYPES
    shown = viewable_image(data, media_type)
    assert shown is not None
    png, shown_type = shown
    assert shown_type == "image/png"
    assert Image.open(io.BytesIO(png)).size == size


def test_svg_is_never_shown_as_a_picture() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>'
    assert viewable_image(svg, "image/svg+xml") is None
    assert not is_shown_as_picture("image/svg+xml")
    assert is_shown_as_picture("image/heic")
    assert is_shown_as_picture("IMAGE/PNG")


def test_bytes_that_do_not_decode_are_not_shown() -> None:
    assert viewable_image(b"not a tiff", "image/tiff") is None


def test_an_image_too_large_to_decode_safely_is_not_shown() -> None:
    """Review I-3: a 12 KB TIFF can claim 196 million pixels; Pillow refuses it with a
    DecompressionBombError, which must mean "not shown", never a failed turn."""

    buffer = io.BytesIO()
    Image.new("1", (14000, 14000), 1).save(buffer, format="TIFF", compression="group4")
    assert len(buffer.getvalue()) < 100_000
    assert viewable_image(buffer.getvalue(), "image/tiff") is None
