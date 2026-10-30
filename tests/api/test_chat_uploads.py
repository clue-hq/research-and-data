"""Chat attachments (spec 2026-09-18), Task 4: the pure upload rules.

What a person may attach is decided here — the family a media type belongs to, the one filename
segment we keep, the type we resolve when the browser declares something useless, and the byte
checks (size, UTF-8, image and document magic) both the upload route and the submission route
apply.
"""

from __future__ import annotations

import pytest

from clue_api.chat.uploads import (
    UploadRefused,
    attachment_family,
    resolve_media_type,
    sanitize_filename,
    validate_upload_bytes,
)
from clue_config import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 16
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_family_is_text_or_image_or_none() -> None:
    assert attachment_family("text/markdown") == "text"
    assert attachment_family("text/plain") == "text"
    assert attachment_family("image/png") == "image"
    assert attachment_family("application/zip") is None


def test_sanitize_filename_keeps_one_segment() -> None:
    assert sanitize_filename("  notes.md ") == "notes.md"
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("a/b/c report v2.md") == "c report v2.md"
    with pytest.raises(UploadRefused) as caught:
        sanitize_filename("....")
    assert caught.value.code == "UPLOAD_FILENAME_INVALID"


def test_resolve_media_type_prefers_declared_then_extension() -> None:
    assert resolve_media_type(declared="image/png", filename="x.bin") == "image/png"
    assert resolve_media_type(declared=None, filename="x.md") == "text/markdown"
    assert resolve_media_type(declared="application/octet-stream", filename="x.txt") == "text/plain"
    assert resolve_media_type(declared=None, filename="x.jpg") == "image/jpeg"
    with pytest.raises(UploadRefused) as caught:
        resolve_media_type(declared="application/zip", filename="x.zip")
    assert caught.value.code == "UPLOAD_UNSUPPORTED_TYPE"


def test_validate_bytes_enforces_family_rules() -> None:
    settings = Settings(
        _env_file=None,
        chat_attachment_image_max_bytes=32,
        chat_attachment_text_max_bytes=8,
    )
    validate_upload_bytes(data=PNG, media_type="image/png", settings=settings)
    validate_upload_bytes(data=JPEG, media_type="image/jpeg", settings=settings)
    validate_upload_bytes(data=WEBP, media_type="image/webp", settings=settings)
    validate_upload_bytes(data=GIF, media_type="image/gif", settings=settings)
    validate_upload_bytes(data=b"# hi", media_type="text/markdown", settings=settings)
    with pytest.raises(UploadRefused) as too_big:
        validate_upload_bytes(data=b"x" * 9, media_type="text/plain", settings=settings)
    assert too_big.value.code == "UPLOAD_TOO_LARGE"
    with pytest.raises(UploadRefused) as not_utf8:
        validate_upload_bytes(data=b"\xff\xfe", media_type="text/plain", settings=settings)
    assert not_utf8.value.code == "UPLOAD_NOT_UTF8"
    with pytest.raises(UploadRefused) as not_image:
        validate_upload_bytes(data=b"not a png", media_type="image/png", settings=settings)
    assert not_image.value.code == "UPLOAD_NOT_AN_IMAGE"


def test_document_family_and_extensions() -> None:
    assert attachment_family("application/pdf") == "document"
    assert attachment_family(DOCX) == "document"
    assert attachment_family("text/csv") == "document"
    assert attachment_family("application/json") == "document"
    assert resolve_media_type(declared=None, filename="a.PDF") == "application/pdf"
    assert resolve_media_type(declared="application/octet-stream", filename="a.xlsx").endswith(
        "spreadsheetml.sheet"
    )
    assert resolve_media_type(declared=None, filename="a.csv") == "text/csv"


def test_document_bytes_rules() -> None:
    settings = Settings(_env_file=None, chat_attachment_document_max_bytes=64)
    validate_upload_bytes(
        data=b"%PDF-1.7\n" + b"\x00" * 10, media_type="application/pdf", settings=settings
    )
    validate_upload_bytes(data=b"PK\x03\x04" + b"\x00" * 10, media_type=DOCX, settings=settings)
    validate_upload_bytes(data=b'{"a": 1}', media_type="application/json", settings=settings)
    validate_upload_bytes(data=b"a,b\n1,2\n", media_type="text/csv", settings=settings)
    with pytest.raises(UploadRefused) as too_big:
        validate_upload_bytes(
            data=b"%PDF-" + b"x" * 100, media_type="application/pdf", settings=settings
        )
    assert too_big.value.code == "UPLOAD_TOO_LARGE"
    with pytest.raises(UploadRefused) as not_pdf:
        validate_upload_bytes(data=b"hello", media_type="application/pdf", settings=settings)
    assert not_pdf.value.code == "UPLOAD_NOT_A_DOCUMENT"
    with pytest.raises(UploadRefused) as not_json:
        validate_upload_bytes(data=b"{oops", media_type="application/json", settings=settings)
    assert not_json.value.code == "UPLOAD_NOT_A_DOCUMENT"
    with pytest.raises(UploadRefused) as not_utf8:
        validate_upload_bytes(data=b"\xff\xfe,x\n", media_type="text/csv", settings=settings)
    assert not_utf8.value.code == "UPLOAD_NOT_A_DOCUMENT"


def test_more_image_formats_are_accepted_by_their_bytes() -> None:
    """Spec 2026-10-30 §3.6: SVG, HEIC/HEIF, AVIF, TIFF, BMP and ICO are chat images too."""

    settings = Settings(_env_file=None)
    accepted = {
        "image/svg+xml": b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>',
        "image/heic": b"\x00\x00\x00\x18ftypheic" + b"\x00" * 12,
        "image/heif": b"\x00\x00\x00\x18ftypmif1" + b"\x00" * 12,
        "image/avif": b"\x00\x00\x00\x1cftypavif" + b"\x00" * 12,
        "image/tiff": b"II*\x00" + b"\x00" * 12,
        "image/bmp": b"BM" + b"\x00" * 14,
        "image/x-icon": b"\x00\x00\x01\x00" + b"\x00" * 12,
    }
    for media_type, data in accepted.items():
        assert attachment_family(media_type) == "image"
        validate_upload_bytes(data=data, media_type=media_type, settings=settings)
    validate_upload_bytes(
        data=b"MM\x00*" + b"\x00" * 12, media_type="image/tiff", settings=settings
    )
    for extension, media_type in (
        ("svg", "image/svg+xml"),
        ("heic", "image/heic"),
        ("heif", "image/heif"),
        ("avif", "image/avif"),
        ("tif", "image/tiff"),
        ("tiff", "image/tiff"),
        ("bmp", "image/bmp"),
        ("ico", "image/x-icon"),
    ):
        assert resolve_media_type(declared=None, filename=f"a.{extension}") == media_type
    with pytest.raises(UploadRefused) as refused:
        validate_upload_bytes(data=PNG, media_type="image/heic", settings=settings)
    assert refused.value.code == "UPLOAD_NOT_AN_IMAGE"
    with pytest.raises(UploadRefused) as refused:
        validate_upload_bytes(data=b"<html></html>", media_type="image/svg+xml", settings=settings)
    assert refused.value.code == "UPLOAD_NOT_AN_IMAGE"


def test_an_svg_whose_tag_follows_a_long_comment_is_accepted() -> None:
    """Review M-8: the check read only the first 4 KB, refusing a valid SVG whose <svg> tag comes
    after a long comment or DOCTYPE (design tools write both)."""

    svg = (
        b'<?xml version="1.0"?>\n<!-- '
        + b"x" * 6000
        + b' -->\n<svg xmlns="http://www.w3.org/2000/svg"/>'
    )
    validate_upload_bytes(data=svg, media_type="image/svg+xml", settings=Settings(_env_file=None))
