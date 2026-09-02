"""Font container normalization for the design asset store (option A, 2026-09-02).

INVARIANT: a font asset's primary bytes are always a single sfnt face, TTF or CFF-OTF.

WOFF and WOFF2 are compressed wrappers around exactly those bytes. Every reader of stored
fonts speaks sfnt and none of them speaks WOFF2: Skia via FreeType (the Linux raster; the
macOS dev box only works because CoreText happens to read WOFF2), the SVG embedder and its
fsType license read (`crates/lumen-skia/src/embed.rs::parse_fs_type`), the klippa subsetter,
and CanvasKit in the browser editor. Before this module, 367 of 517 stored brand faces were
WOFF2, so the SVG export refused them every round and the browser canvas shaped their text in
the Inter fallback.

So the wrapper is removed ONCE, where bytes enter (`CoreClient.ingest_asset`), and put back
only where a web page wants it (`web_export`). Decoding is lossless (same tables) and, with
`recalcTimestamp=False` / `recalcBBoxes=False`, byte-deterministic, which is what keeps the
content-addressed store idempotent across re-ingests and backfills.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Optional

FontContainer = Literal["woff2", "woff", "ttf", "otf"]

#: Leading magic → container. `true` is the legacy Apple TrueType tag.
_MAGIC: tuple[tuple[bytes, FontContainer], ...] = (
    (b"wOF2", "woff2"),
    (b"wOFF", "woff"),
    (b"OTTO", "otf"),
    (b"\x00\x01\x00\x00", "ttf"),
    (b"true", "ttf"),
)

#: The MIME the asset record carries for each stored (sfnt) container.
SFNT_MIME: dict[str, str] = {"ttf": "font/ttf", "otf": "font/otf"}

#: The wrappers this module removes.
WEB_CONTAINERS: tuple[str, ...] = ("woff2", "woff")


class FontContainerError(ValueError):
    """A WOFF/WOFF2 payload that cannot be decoded, or sfnt bytes that cannot be encoded."""


def sniff_font_container(data: bytes) -> Optional[FontContainer]:
    """The container the leading magic bytes name, or ``None`` for anything else."""
    head = data[:4]
    for magic, container in _MAGIC:
        if head == magic:
            return container
    return None


@dataclass(frozen=True)
class DecodedFont:
    """One web font unwrapped to sfnt."""

    data: bytes
    container: FontContainer
    mime_type: str
    source_container: FontContainer
    source_sha256: str


def _open_font(data: bytes):
    from fontTools.ttLib import TTFont

    # Both recalc flags OFF: the tables are already correct, and touching `head.modified`
    # would make the same input produce different bytes on every run.
    return TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False)


def decode_web_font(data: bytes) -> Optional[DecodedFont]:
    """Unwrap WOFF/WOFF2 to sfnt. ``None`` when ``data`` is not a web container.

    Raises :class:`FontContainerError` when the payload claims to be WOFF/WOFF2 but cannot be
    decoded, or decodes to something that is not a single sfnt face.
    """
    source = sniff_font_container(data)
    if source not in WEB_CONTAINERS:
        return None
    try:
        font = _open_font(data)
        font.flavor = None
        out = BytesIO()
        font.save(out)
    except Exception as error:  # noqa: BLE001 — fontTools raises a zoo of types
        raise FontContainerError(
            f"{source} font could not be decoded to sfnt: {type(error).__name__}: {error}"
        ) from error
    decoded = out.getvalue()
    container = sniff_font_container(decoded)
    if container not in SFNT_MIME:
        raise FontContainerError(
            f"{source} font decoded to an unexpected container {container!r}"
        )
    return DecodedFont(
        data=decoded,
        container=container,
        mime_type=SFNT_MIME[container],
        source_container=source,
        source_sha256=hashlib.sha256(data).hexdigest(),
    )


def encode_woff2(data: bytes) -> bytes:
    """Wrap sfnt bytes as WOFF2. Identity for WOFF2 input; refuses anything else."""
    container = sniff_font_container(data)
    if container == "woff2":
        return data
    if container not in SFNT_MIME:
        raise FontContainerError(
            f"cannot encode {container or 'non-font'} bytes as WOFF2; sfnt (TTF/OTF) required"
        )
    try:
        font = _open_font(data)
        font.flavor = "woff2"
        out = BytesIO()
        font.save(out)
    except Exception as error:  # noqa: BLE001
        raise FontContainerError(
            f"sfnt font could not be encoded as WOFF2: {type(error).__name__}: {error}"
        ) from error
    return out.getvalue()


def sfnt_filename(filename: Optional[str], container: FontContainer) -> Optional[str]:
    """``x.woff2`` / ``x.woff`` → ``x.<container>``; any other name is returned unchanged."""
    if not filename:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if dot and ext.lower() in WEB_CONTAINERS:
        return f"{stem}.{container}"
    return filename


def decode_note(decoded: DecodedFont) -> str:
    """The provenance note the record carries so the source bytes stay traceable."""
    return (
        "font container decoded at ingestion: "
        f"{decoded.source_container} -> {decoded.container} "
        f"(source sha256:{decoded.source_sha256})"
    )
