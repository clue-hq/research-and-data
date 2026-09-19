"""Source-format edge cases for the pure lossless crop, without engine fixtures."""

import io
import struct
import zlib

import pytest
from lumen_agent.image_crop import ImageCropError, crop_source_pixels
from PIL import Image, PngImagePlugin


def _crop(data, mime="image/png", rect=None):
    return crop_source_pixels(
        data, source_asset_id="original", mime_type=mime, rect=rect or [0, 0, 2, 1]
    )


def rgb16_png(*, alpha=False):
    """A real 16-bit PNG with low-byte information Pillow RGB(A) discards."""

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    channels = 4 if alpha else 3
    pixel = (0x1234, 0x5678, 0x9ABC, 0xDE01)[:channels]
    row = b"\x00" + struct.pack(">" + "H" * channels * 3, *(pixel * 3))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 3, 2, 16, 6 if alpha else 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * 2))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("alpha", [False, True])
def test_rgb16_png_refuses_before_pillow_can_discard_low_sample_bytes(alpha):
    source = rgb16_png(alpha=alpha)
    # This is the dangerous format: unlike grayscale16, mode alone hides depth.
    with Image.open(io.BytesIO(source)) as image:
        assert image.mode == ("RGBA" if alpha else "RGB")
        assert image.getpixel((0, 0))[0] == 0x12  # original sample was 0x1234
    with pytest.raises(ImageCropError, match="16-bit") as error:
        _crop(source)
    assert error.value.code == "asset.crop_unsupported"


def test_png_color_interpretation_and_alpha_are_retained():
    source = Image.new("RGBA", (3, 2), (51, 23, 174, 95))
    metadata = PngImagePlugin.PngInfo()
    metadata.add(b"gAMA", struct.pack(">I", 45455))
    metadata.add(b"sRGB", b"\x00")
    buffer = io.BytesIO()
    source.save(buffer, format="PNG", pnginfo=metadata)
    cropped = _crop(buffer.getvalue())
    with Image.open(io.BytesIO(cropped.png_bytes)) as image:
        assert image.info.get("gamma") == 0.45455
        assert image.info.get("srgb") == 0
        assert image.getpixel((1, 0)) == (51, 23, 174, 95)


def test_palette_transparency_is_not_flattened_or_requantized():
    source = Image.new("P", (3, 2))
    source.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * 759)
    source.putdata([0, 1, 2, 2, 1, 0])
    buffer = io.BytesIO()
    source.save(buffer, format="PNG", transparency=bytes([0, 127, 255]))
    cropped = _crop(buffer.getvalue(), rect=[1, 0, 3, 2])
    with Image.open(io.BytesIO(cropped.png_bytes)) as image:
        assert list(image.convert("RGBA").getdata()) == [
            (0, 255, 0, 127),
            (0, 0, 255, 255),
            (0, 255, 0, 127),
            (255, 0, 0, 0),
        ]


def test_jpeg_is_decoded_once_then_losslessly_stored_without_second_jpeg_loss():
    source = Image.new("RGB", (4, 3))
    source.putdata([(x * 43, y * 72, (x + y) * 30) for y in range(3) for x in range(4)])
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", quality=78)
    data = buffer.getvalue()
    cropped = _crop(data, "image/jpeg", [1, 1, 4, 3])
    with (
        Image.open(io.BytesIO(data)) as original,
        Image.open(io.BytesIO(cropped.png_bytes)) as image,
    ):
        assert image.format == "PNG"
        assert list(image.getdata()) == [
            original.getpixel((x, y)) for y in (1, 2) for x in (1, 2, 3)
        ]


@pytest.mark.parametrize("mode", ["LA", "RGB"])
def test_crop_preserves_icc_and_identity_orientation(mode):
    source = Image.new(mode, (3, 2))
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 1
    profile = b"profile bytes retained without color conversion"
    source.save(buffer, format="PNG", icc_profile=profile, exif=exif)
    cropped = _crop(buffer.getvalue())
    with Image.open(io.BytesIO(cropped.png_bytes)) as image:
        assert image.mode == mode
        assert image.info["icc_profile"] == profile
        assert image.getexif().get(274, 1) == 1


@pytest.mark.parametrize("kind", ["animated", "cmyk", "sixteen_bit", "wrong_mime", "invalid"])
def test_crop_refuses_formats_that_need_frame_choice_or_color_conversion(kind):
    buffer = io.BytesIO()
    mime = "image/png"
    if kind == "animated":
        Image.new("RGB", (3, 2), "red").save(
            buffer, format="GIF", save_all=True, append_images=[Image.new("RGB", (3, 2), "blue")]
        )
        mime = "image/gif"
    elif kind == "cmyk":
        Image.new("CMYK", (3, 2)).save(buffer, format="JPEG")
        mime = "image/jpeg"
    elif kind == "sixteen_bit":
        Image.new("I;16", (3, 2)).save(buffer, format="PNG")
    elif kind == "wrong_mime":
        Image.new("RGB", (3, 2)).save(buffer, format="PNG")
        mime = "image/jpeg"
    else:
        buffer.write(b"not an image")
    with pytest.raises(ImageCropError):
        _crop(buffer.getvalue(), mime)
