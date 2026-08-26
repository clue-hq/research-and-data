"""Resolving an asset record to an ON-DISK raster preview — shared by both lanes.

This lived as `LumenDesignTools._asset_preview_path` (scene lane) until the web
lane needed the same answer for `view("asset:<id>")`. There is exactly one right
answer to "which pixels represent this asset?", so there is exactly one
implementation: a second copy would drift the moment either lane learned a new
media shape (W1.2's SVG rasterization is precisely such a change).

No substrate imports — either lane can call it, and neither owns it.

**Resolve by DIGEST, never by the stored ref's text** (the rule
`clue_design.storage.location_digest` states, which is why this calls it rather
than re-deriving it). Three `opaque_ref` shapes exist in the wild — the engine's
`sha256/<ab>/<digest>`, D4's durable `<workspace>/design/<digest>`, and a bare
digest — and only the trailing segment is common to all three. This used to
append the ref verbatim onto the store root, which is the per-WORKSPACE engine
materialization cache: a D4 ref then produced the doubled
`<cache>/ws_X/ws_X/design/<digest>` and EVERY `view("asset:…")` on a
durably-stored brand-kit asset answered `asset_missing_file` (2026-08-24
forensics; fast-loop v1 spec §4 P0.1). The digest goes through
`blob_path_for_digest` — the one place the engine-cache layout is spelled out —
and the API's `brand_kit_asset_manifest` read-through has already materialized
those bytes out of durable storage into that cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from clue_design.storage import location_digest

# Raster mime types the vision APIs accept as a direct preview when no derived
# thumbnail exists (an SVG has no raster preview → it is skipped, never a broken path).
PREVIEWABLE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def blob_path_for_digest(store_root: Any, digest: str) -> Path:
    """The content-addressed store path for a sha256 digest:
    `<store_root>/sha256/<first2>/<digest>`. The ONE place this layout is spelled
    out for digest→path resolution (both lanes' asset previews, view's reference
    preview, and the runtime's reference-conditioning all resolve through it)."""
    return Path(store_root) / "sha256" / digest[:2] / digest


def _is_raster_thumbnail(thumbnail: Dict[str, Any]) -> bool:
    """Whether a thumbnail block is pixels something can actually decode.

    Vectors ingested before W1.2 carry a SELF-REFERENTIAL thumbnail: the block
    points back at the SVG bytes with mime `image/svg+xml`. Serving that as a
    raster handed the viewer a path PIL cannot open — a contained "view failed"
    string in place of the designed honest one. So a DECLARED mime must be one
    the vision APIs read.

    A block with no mime keeps today's behavior (trusted): every real writer
    stamps `image/png`, and a record in flight must not lose its preview to a
    missing field.
    """
    mime = thumbnail.get("mime_type")
    return mime is None or mime in PREVIEWABLE_MIME_TYPES


def asset_preview_path(
    record: Dict[str, Any], store_root: Any
) -> Optional[tuple[str, Optional[int], Optional[int]]]:
    """Resolve an asset record to an ON-DISK preview the vision APIs can read,
    returning (absolute_path, pixel_width, pixel_height) or None.

    Prefer the derived thumbnail (any source type gets one at ingest — since W1.2
    a vector's is a real PNG rasterized from the SVG), but only when it is pixels:
    a thumbnail declaring a mime outside `PREVIEWABLE_MIME_TYPES` is skipped, which
    is how the legacy self-referential SVG "thumbnail" degrades honestly. Else, if
    the primary media is itself a raster the vision APIs accept, use that. An SVG
    with no usable thumbnail has no raster preview → return None (the caller says
    so honestly rather than serving a path nothing can decode). Resolution is by
    DIGEST through `blob_path_for_digest` (see the module docstring for why ref
    text must never touch the path). Only the path is returned; no bytes are read
    here (existence is checked at block-build time by the caller), so this stays
    cheap to call every curated context.
    """
    media = record.get("media") or {}
    thumbnail = media.get("thumbnail") or {}
    thumb_digest = location_digest(thumbnail.get("location"))
    if thumb_digest and _is_raster_thumbnail(thumbnail):
        return (
            str(blob_path_for_digest(store_root, thumb_digest)),
            thumbnail.get("pixel_width"),
            thumbnail.get("pixel_height"),
        )
    mime = media.get("mime_type")
    # `media.digest.value` is the record's own byte identity and the primary
    # source of truth; the location is the fallback for a record that carries
    # only a ref.
    primary_digest = ((media.get("digest") or {}).get("value")) or location_digest(
        media.get("location")
    )
    if mime in PREVIEWABLE_MIME_TYPES and primary_digest:
        # Pixel dims for a raster/logo asset live in its own metadata block.
        dims = record.get("raster") or record.get("logo") or {}
        return (
            str(blob_path_for_digest(store_root, primary_digest)),
            dims.get("pixel_width"),
            dims.get("pixel_height"),
        )
    return None
