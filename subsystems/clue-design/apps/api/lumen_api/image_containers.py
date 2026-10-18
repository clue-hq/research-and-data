"""Image container normalization for the design asset store (2026-10-18).

INVARIANT: a stored image's primary bytes are a format every reader of the store speaks —
PNG, JPEG, GIF, WebP or SVG.

AVIF and ICO are not. The engine's sniffer (`crates/lumen-assets/src/mime.rs::sniff_mime`)
does not recognize them, so the helper stored them as `application/octet-stream` with no
thumbnail: the agent's `view` had nothing to show, the renderer could not paint them, and the
agent cropped logos out of old ads instead (blurry, with stray pixels). On the dev store that
was Atrium's light logo, Garner's reversed logo, 21 Garner site images and a few favicons.

So they are converted to PNG ONCE, where bytes enter (`CoreClient.ingest_asset`) — the same
chokepoint as the font decode in `font_containers.py`. PNG is lossless and readable by the
engine, the browser editor and the vision APIs alike. ICO keeps its largest icon; an animated
AVIF keeps its first frame. Conversion is byte-deterministic, which keeps the
content-addressed store idempotent across re-ingests and the backfill
(`scripts/convert_stored_web_images.py`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal, Optional

ImageContainer = Literal["avif", "ico"]

PNG_MIME = "image/png"

#: The containers this module converts.
CONVERTED_CONTAINERS: tuple[str, ...] = ("avif", "ico")

_ICO_MAGIC = b"\x00\x00\x01\x00"
_AVIF_BRANDS = (b"avif", b"avis")


class ImageContainerError(ValueError):
    """An AVIF/ICO payload that cannot be decoded."""


def sniff_image_container(data: bytes) -> Optional[ImageContainer]:
    """``"avif"`` / ``"ico"`` when the leading bytes name one, ``None`` for anything else."""
    if data[:4] == _ICO_MAGIC:
        return "ico"
    if data[4:8] == b"ftyp":
        # ISO-BMFF: the major brand, then compatible brands, inside the `ftyp` box.
        size = int.from_bytes(data[:4], "big")
        end = min(size, len(data)) if size >= 16 else len(data)
        brands = [data[8:12]] + [data[i : i + 4] for i in range(16, end - 3, 4)]
        if any(brand in _AVIF_BRANDS for brand in brands):
            return "avif"
    return None


@dataclass(frozen=True)
class ConvertedImage:
    """One AVIF/ICO payload converted to PNG."""

    data: bytes
    width: int
    height: int
    source_container: ImageContainer
    source_sha256: str


def convert_to_png(data: bytes) -> Optional[ConvertedImage]:
    """Convert AVIF/ICO to PNG. ``None`` when ``data`` is neither.

    Raises :class:`ImageContainerError` when the payload claims to be AVIF/ICO but cannot be
    decoded.
    """
    source = sniff_image_container(data)
    if source is None:
        return None
    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as image:
            # ICO opens at its largest icon; an image sequence opens at frame 0.
            image.load()
            has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
            converted = image.convert("RGBA" if has_alpha else "RGB")
            icc_profile = image.info.get("icc_profile")
        out = BytesIO()
        params: dict[str, Any] = {"format": "PNG"}
        if icc_profile:
            params["icc_profile"] = icc_profile
        converted.save(out, **params)
    except Exception as error:  # noqa: BLE001 — Pillow raises a zoo of types
        raise ImageContainerError(
            f"{source} image could not be converted to PNG: {type(error).__name__}: {error}"
        ) from error
    return ConvertedImage(
        data=out.getvalue(),
        width=converted.width,
        height=converted.height,
        source_container=source,
        source_sha256=hashlib.sha256(data).hexdigest(),
    )


def png_filename(filename: Optional[str]) -> Optional[str]:
    """``x.avif`` / ``x.ico`` → ``x.png``; any other name is returned unchanged."""
    if not filename:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if dot and ext.lower() in CONVERTED_CONTAINERS:
        return f"{stem}.png"
    return filename


def convert_note(converted: ConvertedImage) -> str:
    """The provenance note the record carries so the source bytes stay traceable."""
    return (
        "image container converted at ingestion: "
        f"{converted.source_container} -> png "
        f"(source sha256:{converted.source_sha256})"
    )


# ---------------------------------------------------------------------------------------------
# Ingestion chokepoint
# ---------------------------------------------------------------------------------------------

#: The refusal code an undecodable AVIF/ICO ingest returns. Bytes no reader can use are not an
#: image asset, the same rule as the font decode (ruling R2, 2026-09-02).
INGEST_IMAGE_CONVERT_FAILED = "ingest.image_convert_failed"


@dataclass(frozen=True)
class NormalizedImageIngest:
    """`CoreClient.ingest_asset`'s arguments after image normalization.

    For an AVIF/ICO payload exactly one outcome is set: ``converted`` (bytes, MIME, filename
    and provenance rewritten) or ``refusal`` (``{"code", "message"}``; nothing rewritten). Any
    other payload comes back untouched, ``bytes_base64`` being the very same object.
    """

    bytes_base64: str
    declared_mime_type: Optional[str]
    filename: Optional[str]
    provenance: Optional[dict[str, Any]]
    converted: Optional[ConvertedImage]
    refusal: Optional[dict[str, str]]


def _leading_bytes(bytes_base64: str) -> bytes:
    # 128 base64 characters decode to 96 bytes — enough for the ICO magic and an AVIF `ftyp`
    # box with its compatible brands — so a large photo is never decoded whole just to learn
    # it is a JPEG.
    head = bytes_base64[:128]
    head = head[: len(head) - len(head) % 4]
    try:
        return base64.b64decode(head, validate=True)
    except (binascii.Error, ValueError):
        return b""


def normalize_ingest_image(
    *,
    bytes_base64: str,
    declared_mime_type: Optional[str],
    filename: Optional[str],
    provenance: Optional[dict[str, Any]],
) -> NormalizedImageIngest:
    """Rewrite an ingest call so an AVIF/ICO payload reaches the helper as PNG.

    The MIME is rewritten with the bytes (the helper refuses a declared MIME that contradicts
    them); the filename keeps its stem and gets `.png`; the provenance gains one note naming
    the source container and its sha256 so the original stays traceable.
    """
    untouched = NormalizedImageIngest(
        bytes_base64, declared_mime_type, filename, provenance, converted=None, refusal=None
    )
    if sniff_image_container(_leading_bytes(bytes_base64)) is None:
        return untouched
    try:
        raw = base64.b64decode(bytes_base64, validate=True)
    except (binascii.Error, ValueError):
        return untouched  # the helper reports malformed base64 exactly as it always has
    try:
        converted = convert_to_png(raw)
    except ImageContainerError as error:
        return NormalizedImageIngest(
            bytes_base64,
            declared_mime_type,
            filename,
            provenance,
            converted=None,
            refusal={
                "code": INGEST_IMAGE_CONVERT_FAILED,
                "message": f"{filename or 'image'}: {error}",
            },
        )
    if converted is None:  # the leading-byte sniff and the full payload disagree only on garbage
        return untouched
    stamped = dict(provenance or {})
    notes = list(stamped.get("notes") or [])
    notes.append(convert_note(converted))
    stamped["notes"] = notes
    return NormalizedImageIngest(
        base64.b64encode(converted.data).decode("ascii"),
        PNG_MIME,
        png_filename(filename),
        stamped,
        converted=converted,
        refusal=None,
    )
