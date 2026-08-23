"""Resolving an asset record to an ON-DISK raster preview — shared by both lanes.

This lived as `LumenDesignTools._asset_preview_path` (scene lane) until the web
lane needed the same answer for `view("asset:<id>")`. There is exactly one right
answer to "which pixels represent this asset?", so there is exactly one
implementation: a second copy would drift the moment either lane learned a new
media shape (W1.2's SVG rasterization is precisely such a change).

Pure stdlib, no substrate imports — either lane can call it, and neither owns it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

# Raster mime types the vision APIs accept as a direct preview when no derived
# thumbnail exists (an SVG has no raster preview → it is skipped, never a broken path).
PREVIEWABLE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def asset_preview_path(
    record: Dict[str, Any], store_root: Any
) -> Optional[tuple[str, Optional[int], Optional[int]]]:
    """Resolve an asset record to an ON-DISK preview the vision APIs can read,
    returning (absolute_path, pixel_width, pixel_height) or None.

    Prefer the derived 256px thumbnail (any source type gets one at ingest); else,
    if the primary media is itself a raster the vision APIs accept, use that. An
    SVG with no thumbnail has no usable raster preview → return None (the caller
    says so honestly rather than serving a path nothing can decode). Refs are
    `sha256/<first2>/<digest>` under the SAME asset-store root the tools already use
    for export/ingest — resolved the one way (Path(store_root) / opaque_ref). Only
    the path is returned; no bytes are read here (existence is checked at
    block-build time by the caller), so this stays cheap to call every curated
    context.
    """
    media = record.get("media") or {}
    root = Path(store_root)
    thumbnail = media.get("thumbnail") or {}
    thumb_ref = (thumbnail.get("location") or {}).get("opaque_ref")
    if thumb_ref:
        return (
            str(root / thumb_ref),
            thumbnail.get("pixel_width"),
            thumbnail.get("pixel_height"),
        )
    mime = media.get("mime_type")
    primary_ref = (media.get("location") or {}).get("opaque_ref")
    if mime in PREVIEWABLE_MIME_TYPES and primary_ref:
        # Pixel dims for a raster/logo asset live in its own metadata block.
        dims = record.get("raster") or record.get("logo") or {}
        return (
            str(root / primary_ref),
            dims.get("pixel_width"),
            dims.get("pixel_height"),
        )
    return None
