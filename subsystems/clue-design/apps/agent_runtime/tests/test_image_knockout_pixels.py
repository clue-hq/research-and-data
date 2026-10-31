"""The background knock-out on raw pixels: a plain tile becomes transparent, exactly.

No model, no engine: the pure function `knock_out_plain_background` on small hand-built PNGs.
"""

from __future__ import annotations

import hashlib
import io

import pytest
from lumen_agent.image_knockout import ImageKnockOutError, knock_out_plain_background
from PIL import Image

BLACK, WHITE = (0, 0, 0, 255), (255, 255, 255, 255)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _tile(background, mark, *, size=(20, 20), box=(6, 8, 14, 12), edge=None):
    """A `size` tile of `background` with a `mark` rectangle; `edge` paints one anti-aliased
    column just right of the mark."""
    image = Image.new("RGBA", size, background)
    for x in range(box[0], box[2]):
        for y in range(box[1], box[3]):
            image.putpixel((x, y), mark)
    if edge is not None:
        for y in range(box[1], box[3]):
            image.putpixel((box[2], y), edge)
    return image


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


def test_a_white_mark_on_a_black_tile_keeps_the_mark_and_loses_the_tile():
    source = _png(_tile(BLACK, WHITE))
    result = knock_out_plain_background(source, mime_type="image/png", source_asset_id="logo")
    out = _decode(result.png_bytes)
    # Trimmed to the mark: 8 x 4, every pixel opaque white.
    assert out.size == (8, 4)
    assert set(out.getdata()) == {WHITE}
    receipt = result.receipt
    assert receipt["operation"] == "knock_out_background"
    assert receipt["background_rgb"] == [0, 0, 0]
    assert receipt["source_asset_id"] == "logo"
    assert receipt["source_digest"] == hashlib.sha256(source).hexdigest()
    assert receipt["output_digest"] == hashlib.sha256(result.png_bytes).hexdigest()
    assert receipt["source_dimensions"] == {"width": 20, "height": 20}
    assert receipt["output_dimensions"] == {"width": 8, "height": 4}


def test_a_dark_mark_on_a_white_tile_works_the_other_way_round():
    out = _decode(
        knock_out_plain_background(
            _png(_tile(WHITE, BLACK)), mime_type="image/png", source_asset_id="logo"
        ).png_bytes
    )
    assert out.size == (8, 4) and set(out.getdata()) == {BLACK}


def test_a_soft_edge_keeps_partial_transparency_without_a_dark_halo():
    """A grey anti-aliased pixel between a white mark and a black tile is half white over black:
    it becomes white at about half opacity — not a grey pixel, which would show as a dark rim."""
    out = _decode(
        knock_out_plain_background(
            _png(_tile(BLACK, WHITE, edge=(128, 128, 128, 255))),
            mime_type="image/png",
            source_asset_id="logo",
        ).png_bytes
    )
    assert out.size == (9, 4)
    r, g, b, a = out.getpixel((8, 1))
    assert 100 <= a <= 160
    assert min(r, g, b) >= 245


def test_a_photo_background_is_refused():
    image = Image.new("RGBA", (20, 20))
    image.putdata([((x * 37) % 256, (x * 91) % 256, (x * 13) % 256, 255) for x in range(400)])
    with pytest.raises(ImageKnockOutError) as refused:
        knock_out_plain_background(_png(image), mime_type="image/png", source_asset_id="photo")
    assert refused.value.code == "asset.knockout_background_not_plain"


def test_an_already_transparent_image_is_refused():
    image = _tile((0, 0, 0, 0), WHITE)
    with pytest.raises(ImageKnockOutError) as refused:
        knock_out_plain_background(_png(image), mime_type="image/png", source_asset_id="logo")
    assert refused.value.code == "asset.knockout_already_transparent"


def test_a_tile_with_nothing_on_it_is_refused():
    with pytest.raises(ImageKnockOutError) as refused:
        knock_out_plain_background(
            _png(Image.new("RGBA", (10, 10), BLACK)), mime_type="image/png", source_asset_id="x"
        )
    assert refused.value.code == "asset.knockout_nothing_left"


def test_an_svg_is_refused_before_decoding():
    with pytest.raises(ImageKnockOutError) as refused:
        knock_out_plain_background(b"<svg/>", mime_type="image/svg+xml", source_asset_id="logo")
    assert refused.value.code == "asset.knockout_unsupported_format"
