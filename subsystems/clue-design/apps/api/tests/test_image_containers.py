"""AVIF and ICO are converted to PNG where bytes enter the store (2026-10-18).

The engine's sniffer reads PNG, JPEG, GIF, WebP, SVG and PDF. An AVIF or ICO payload used to be
stored as `application/octet-stream` with no thumbnail, so the agent could not view it and the
renderer could not paint it (Atrium's logo, Garner's reversed logo and 21 Garner site images on
the dev store). These tests pin the conversion itself; the chokepoint and the real-helper record
are pinned in `test_core_ingest_image_normalization.py`.
"""

from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image

from lumen_api.image_containers import (
    INGEST_IMAGE_CONVERT_FAILED,
    ImageContainerError,
    convert_to_png,
    normalize_ingest_image,
    png_filename,
    sniff_image_container,
)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def encode(image: Image.Image, fmt: str, **params) -> bytes:
    out = BytesIO()
    image.save(out, format=fmt, **params)
    return out.getvalue()


def half_transparent() -> Image.Image:
    """Left half opaque red, right half fully transparent."""
    image = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
    for x in range(16):
        for y in range(16):
            image.putpixel((x, y), (220, 30, 30, 255))
    return image


@pytest.fixture(scope="module")
def avif_with_alpha() -> bytes:
    return encode(half_transparent(), "AVIF", quality=95)


@pytest.fixture(scope="module")
def avif_opaque() -> bytes:
    return encode(Image.new("RGB", (40, 20), (12, 80, 160)), "AVIF", quality=95)


@pytest.fixture(scope="module")
def ico_two_sizes() -> bytes:
    return encode(Image.new("RGBA", (64, 64), (10, 20, 30, 255)), "ICO", sizes=[(16, 16), (48, 48)])


# --- sniff -------------------------------------------------------------------------------------


def test_sniff_names_avif_and_ico(avif_with_alpha: bytes, ico_two_sizes: bytes) -> None:
    assert sniff_image_container(avif_with_alpha) == "avif"
    assert sniff_image_container(ico_two_sizes) == "ico"


def test_sniff_leaves_formats_the_engine_reads_alone() -> None:
    image = Image.new("RGB", (4, 4), (1, 2, 3))
    for payload in (
        encode(image, "PNG"),
        encode(image, "JPEG"),
        encode(image, "WEBP"),
        encode(image, "GIF"),
        b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        b"",
    ):
        assert sniff_image_container(payload) is None


# --- convert -----------------------------------------------------------------------------------


def test_convert_avif_with_transparency_keeps_its_alpha(avif_with_alpha: bytes) -> None:
    converted = convert_to_png(avif_with_alpha)
    assert converted is not None
    assert converted.source_container == "avif"
    assert (converted.width, converted.height) == (32, 16)
    png = Image.open(BytesIO(converted.data))
    assert png.format == "PNG"
    assert png.mode == "RGBA"
    assert png.getpixel((4, 8))[3] > 240
    assert png.getpixel((28, 8))[3] < 16


def test_convert_opaque_avif_gives_an_opaque_png(avif_opaque: bytes) -> None:
    converted = convert_to_png(avif_opaque)
    assert converted is not None
    png = Image.open(BytesIO(converted.data))
    assert png.format == "PNG"
    assert png.mode == "RGB"
    assert png.size == (40, 20)


def test_convert_ico_keeps_the_largest_icon(ico_two_sizes: bytes) -> None:
    converted = convert_to_png(ico_two_sizes)
    assert converted is not None
    assert converted.source_container == "ico"
    assert (converted.width, converted.height) == (48, 48)
    assert Image.open(BytesIO(converted.data)).size == (48, 48)


def test_convert_is_byte_deterministic(avif_with_alpha: bytes) -> None:
    first = convert_to_png(avif_with_alpha)
    second = convert_to_png(avif_with_alpha)
    assert first is not None and second is not None
    assert first.data == second.data


def test_convert_returns_none_for_bytes_it_does_not_handle() -> None:
    assert convert_to_png(encode(Image.new("RGB", (4, 4)), "PNG")) is None


def test_convert_refuses_an_undecodable_avif() -> None:
    broken = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1" + b"\x00" * 64
    assert sniff_image_container(broken) == "avif"
    with pytest.raises(ImageContainerError):
        convert_to_png(broken)


def test_png_filename_swaps_only_the_converted_extensions() -> None:
    assert png_filename("garner-logo.avif") == "garner-logo.png"
    assert png_filename("favicon.ICO") == "favicon.png"
    assert png_filename("photo.png") == "photo.png"
    assert png_filename("no-extension") == "no-extension"
    assert png_filename(None) is None


# --- normalize_ingest_image (pure) -------------------------------------------------------------


def test_normalize_converts_an_avif_payload_and_rewrites_mime_filename_provenance(
    avif_with_alpha: bytes,
) -> None:
    normalized = normalize_ingest_image(
        bytes_base64=b64(avif_with_alpha),
        declared_mime_type="image/avif",
        filename="atrium.avif",
        provenance={"created_by": "logo_ladder", "notes": ["kept"]},
    )
    assert normalized.refusal is None
    assert normalized.converted is not None
    assert base64.b64decode(normalized.bytes_base64) == normalized.converted.data
    assert normalized.declared_mime_type == "image/png"
    assert normalized.filename == "atrium.png"
    assert normalized.provenance is not None
    assert normalized.provenance["created_by"] == "logo_ladder"
    assert normalized.provenance["notes"][0] == "kept"
    assert normalized.provenance["notes"][1].startswith(
        "image container converted at ingestion: avif -> png"
    )


def test_normalize_leaves_other_payloads_untouched() -> None:
    encoded = b64(encode(Image.new("RGB", (4, 4)), "PNG"))
    normalized = normalize_ingest_image(
        bytes_base64=encoded, declared_mime_type="image/png", filename="dot.png", provenance=None
    )
    assert normalized.bytes_base64 is encoded
    assert normalized.declared_mime_type == "image/png"
    assert normalized.filename == "dot.png"
    assert normalized.provenance is None
    assert normalized.converted is None
    assert normalized.refusal is None


def test_normalize_refuses_an_undecodable_avif() -> None:
    broken = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1" + b"\x00" * 64
    normalized = normalize_ingest_image(
        bytes_base64=b64(broken), declared_mime_type="image/avif", filename="x.avif", provenance=None
    )
    assert normalized.converted is None
    assert normalized.refusal is not None
    assert normalized.refusal["code"] == INGEST_IMAGE_CONVERT_FAILED
    assert "x.avif" in normalized.refusal["message"]


def test_normalize_tolerates_a_payload_the_helper_would_refuse_anyway() -> None:
    normalized = normalize_ingest_image(
        bytes_base64="@@@not-base64@@@", declared_mime_type=None, filename=None, provenance=None
    )
    assert normalized.bytes_base64 == "@@@not-base64@@@"
    assert normalized.refusal is None
