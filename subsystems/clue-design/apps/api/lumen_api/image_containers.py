"""Image container normalization for the design asset store (2026-10-04).

AVIF and ICO, the two raster formats a site serves for logos that the engine cannot sniff, are
decoded to PNG where bytes enter. (ICO: a favicon is often the only small mark a site publishes.)

INVARIANT: a raster asset's primary bytes are a format the engine sniffs and renders —
PNG, JPEG, GIF or WebP (`crates/lumen-assets/src/mime.rs`).

AVIF is none of those. A CDN that negotiates the format from the request's ``Accept`` header
(Cloudflare ``cdn-cgi/image/f=auto``) serves AVIF to any client that lists it, so a logo
fetched that way reached the helper as unsniffable bytes, was stored as
``application/octet-stream`` of kind ``other``, and every later placement failed
``op.asset_incompatible`` (found live on Atrium Hospitality's header logo).

So AVIF is decoded to PNG ONCE, where bytes enter (`CoreClient.ingest_asset`), the same
chokepoint `font_containers` uses for WOFF/WOFF2. PNG is lossless, keeps alpha, and Pillow's
PNG writer stamps no timestamp, so the same input always stores the same bytes and the
content-addressed store stays idempotent across re-ingests.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Optional

#: ISO-BMFF brands that mark an AVIF image or sequence.
_AVIF_BRANDS = (b"avif", b"avis")

#: The refusal code an undecodable AVIF ingest returns: bytes no engine can read are not an
#: image asset, the same ruling the font chokepoint applies (`ingest.font_decode_failed`).
INGEST_IMAGE_DECODE_FAILED = "ingest.image_decode_failed"


class ImageContainerError(ValueError):
    """An AVIF payload that cannot be decoded to PNG."""


def is_ico(data: bytes) -> bool:
    """Whether ``data`` is a Windows icon (``ICONDIR``: reserved 0, type 1, at least one image)."""
    return len(data) >= 6 and data[:4] == b"\x00\x00\x01\x00" and data[4:6] != b"\x00\x00"


def is_avif(data: bytes) -> bool:
    """Whether ``data`` is an AVIF file: an ISO-BMFF ``ftyp`` box naming an AVIF brand.

    The major brand (bytes 8-12) is checked first; a file whose major brand is generic
    (``mif1``) still counts when an AVIF brand is among its compatible brands.
    """
    if len(data) < 12 or data[4:8] != b"ftyp":
        return False
    box_size = int.from_bytes(data[:4], "big")
    brands = data[8 : min(box_size, len(data))] if box_size >= 16 else data[8:12]
    return any(brands[i : i + 4] in _AVIF_BRANDS for i in range(0, len(brands) - 3, 4))


@dataclass(frozen=True)
class DecodedImage:
    """One AVIF image decoded to PNG."""

    data: bytes
    mime_type: str
    source_sha256: str
    source_format: str = "avif"


def decode_to_png(data: bytes) -> Optional[DecodedImage]:
    """Decode AVIF or ICO to PNG. ``None`` when ``data`` is neither.

    An animated AVIF keeps its first frame, which is what a logo or still placement shows; an ICO
    keeps its largest image. Raises :class:`ImageContainerError` when the payload claims one of
    the two formats but cannot be decoded.
    """
    if is_avif(data):
        source_format = "avif"
    elif is_ico(data):
        source_format = "ico"
    else:
        return None
    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as image:
            if source_format == "ico":
                largest = max(image.info.get("sizes") or {image.size}, key=lambda s: s[0] * s[1])
                image.size = largest
            image.seek(0)
            has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
            frame = image.convert("RGBA" if has_alpha else "RGB")
        out = BytesIO()
        frame.save(out, format="PNG")
    except Exception as error:  # noqa: BLE001 — Pillow raises a zoo of types
        raise ImageContainerError(
            f"{source_format} image could not be decoded to png: {type(error).__name__}: {error}"
        ) from error
    return DecodedImage(
        data=out.getvalue(),
        mime_type="image/png",
        source_sha256=hashlib.sha256(data).hexdigest(),
        source_format=source_format,
    )


def png_filename(filename: Optional[str]) -> Optional[str]:
    """``x.avif`` / ``x.ico`` → ``x.png``; any other name is returned unchanged."""
    if not filename:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if dot and ext.lower() in ("avif", "ico"):
        return f"{stem}.png"
    return filename


def decode_note(decoded: DecodedImage) -> str:
    """The provenance note the record carries so the source bytes stay traceable."""
    return (
        f"image container decoded at ingestion: {decoded.source_format} -> png "
        f"(source sha256:{decoded.source_sha256})"
    )


@dataclass(frozen=True)
class NormalizedImageIngest:
    """`CoreClient.ingest_asset`'s arguments after image normalization.

    For an AVIF payload exactly one outcome is set: ``decoded`` (bytes, MIME, filename and
    provenance rewritten) or ``refusal`` (``{"code", "message"}``; nothing rewritten). Any other
    payload comes back untouched, ``bytes_base64`` being the very same object.
    """

    bytes_base64: str
    declared_mime_type: Optional[str]
    filename: Optional[str]
    provenance: Optional[dict[str, Any]]
    decoded: Optional[DecodedImage]
    refusal: Optional[dict[str, str]]


def _leading_bytes(bytes_base64: str) -> bytes:
    # 64 base64 characters decode to 48 bytes: the ftyp box header plus several compatible
    # brands, so a non-AVIF payload is never decoded whole just to learn what it is not.
    try:
        return base64.b64decode(bytes_base64[:64], validate=True)
    except (binascii.Error, ValueError):
        return b""


def normalize_ingest_image(
    *,
    bytes_base64: str,
    declared_mime_type: Optional[str],
    filename: Optional[str],
    provenance: Optional[dict[str, Any]],
) -> NormalizedImageIngest:
    """Rewrite an ingest call so an AVIF payload reaches the helper as PNG.

    The helper refuses a declared MIME that contradicts the sniffed bytes, so the MIME is
    rewritten with the bytes; the filename keeps its stem and gets ``.png``; the provenance
    gains one note naming the source format and its sha256 so the original stays traceable.
    """
    untouched = NormalizedImageIngest(
        bytes_base64, declared_mime_type, filename, provenance, decoded=None, refusal=None
    )
    head = _leading_bytes(bytes_base64)
    if not (is_avif(head) or is_ico(head)):
        return untouched
    try:
        raw = base64.b64decode(bytes_base64, validate=True)
    except (binascii.Error, ValueError):
        return untouched  # the helper reports malformed base64 exactly as it always has
    try:
        decoded = decode_to_png(raw)
    except ImageContainerError as error:
        return NormalizedImageIngest(
            bytes_base64,
            declared_mime_type,
            filename,
            provenance,
            decoded=None,
            refusal={
                "code": INGEST_IMAGE_DECODE_FAILED,
                "message": f"{filename or 'image'}: {error}",
            },
        )
    if decoded is None:
        return untouched
    stamped = dict(provenance or {})
    notes = list(stamped.get("notes") or [])
    notes.append(decode_note(decoded))
    stamped["notes"] = notes
    return NormalizedImageIngest(
        base64.b64encode(decoded.data).decode("ascii"),
        decoded.mime_type,
        png_filename(filename),
        stamped,
        decoded=decoded,
        refusal=None,
    )
