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
from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.tools.asset_preview")

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


# ---------------------------------------------------------------------------
# on-demand vector rasterization (D3)
# ---------------------------------------------------------------------------

VECTOR_MIME = "image/svg+xml"
_RASTER_SIDE = 512.0
_RASTER_PAGE_ID = "page_svg_raster"


def vector_source_digest(record: Dict[str, Any]) -> Optional[str]:
    """The digest of an SVG asset's own bytes, or None if it is not a vector."""
    media = record.get("media") or {}
    if media.get("mime_type") != VECTOR_MIME:
        return None
    return ((media.get("digest") or {}).get("value")) or location_digest(
        media.get("location")
    )


def _raster_page() -> Dict[str, Any]:
    return {
        "id": _RASTER_PAGE_ID,
        "name": "svg raster",
        "size": {
            "width": _RASTER_SIDE, "height": _RASTER_SIDE, "unit": "pt",
            "preset": None, "orientation": "portrait",
        },
        "children": [], "bleed": None, "safe_area": None, "background": [],
    }


def _raster_image_node(asset_id: str) -> Dict[str, Any]:
    # Mirrors lumen_ingestion.pipeline._raster_image_node — the engine's Node
    # schema has NO serde defaults for most fields, so an omitted key is a hard
    # apply_operations refusal, not a soft fallback. `corner` was exactly such
    # an omission: this builder shipped without it and every SVG view died as
    # CoreError("missing field `corner`") inside the old blanket swallow
    # (Wave-C D3 forensic). The real-engine schema test now pins acceptance.
    return {
        "id": "svg_raster_image",
        "name": "svg raster image",
        "kind": {"kind": "image", "asset_id": asset_id, "alt": None},
        "children": [], "fills": [], "strokes": [],
        "corner": {
            "top_left": 0.0, "top_right": 0.0,
            "bottom_left": 0.0, "bottom_right": 0.0,
        },
        "opacity": 1.0, "clip": False, "locked": False,
        "layout": None, "computed": None,
        "position_mode": "absolute",
        "absolute_box": {"x": 0.0, "y": 0.0, "width": _RASTER_SIDE, "height": _RASTER_SIDE},
        "size": {
            "width": {"kind": "fixed", "value": _RASTER_SIDE},
            "height": {"kind": "fixed", "value": _RASTER_SIDE},
        },
        "transform": {
            "x": 0.0, "y": 0.0, "rotation": 0.0, "skew_x": 0.0, "skew_y": 0.0,
            "flip_x": False, "flip_y": False,
        },
    }


def rasterized_vector_path(store_root: Any, digest: str) -> Path:
    """Where an on-demand vector raster is cached: content-addressed, so a
    second `view` of the same artwork costs nothing and a changed asset (a new
    digest) can never be served a stale picture."""
    return Path(store_root) / "svg-preview" / f"{digest}.png"


def rasterize_vector_preview(
    core: Any, record: Dict[str, Any], asset_id: str, store_root: Any
) -> Optional[Path]:
    """Render an SVG asset to a cached PNG through the ENGINE, or None.

    Why this exists: `asset_preview_path` correctly returns None for a vector
    whose stored thumbnail is not pixels, and the agent was then told
    `asset_unavailable` — so it PLACED marks it could never look at. That is how
    apollo.io shipped an ad carrying OpenAI's logomark: the agent flagged the
    logo twice from metadata alone ("renders as the asterisk-A mark, not a
    wordmark") because it had no way to see it.

    Ingestion already rasterizes SVGs two ways: the helper's standalone
    `rasterize_svg_thumbnail` at ingest, and — when that declines — the
    ingestion pipeline's engine round-trip (wrap the asset in a one-image scene
    and export a PNG, the same `skia_safe::svg::Dom` path production rendering
    uses). This is that second mechanism, on the view path, for the assets the
    first one did not cover: pre-W1.2 records, and any SVG the standalone
    thumbnailer declined to paint.

    Deliberately NOT folded into `asset_preview_path`, which is documented as
    cheap enough to call for every curated context and every contact sheet. An
    engine round-trip belongs only where the agent deliberately looks at ONE
    asset. Contact sheets keep omitting vectors and keep counting them.
    """
    digest = vector_source_digest(record)
    if not digest:
        return None
    cached = rasterized_vector_path(store_root, digest)
    if cached.exists():
        return cached
    # The engine rasterizes from ITS content-addressed cache; materializing
    # durable bytes into that cache is the API read-throughs' job (the kit and
    # library manifests already do it before a turn starts). If the bytes are
    # absent the engine does NOT fail — it paints a BLANK plate and only
    # *warns* (LUME0210; proven live, Wave-C D3 probe D) — and a blank cached
    # under this digest would be served as the artwork forever. So absence is
    # checked here, before the round trip, and answered as honestly unviewable.
    if not blob_path_for_digest(store_root, digest).exists():
        logger.warning(
            "svg_raster_bytes_not_materialized", asset_id=asset_id, digest=digest
        )
        return None
    try:
        scene = core.new_scene("doc_svg_raster", "svg raster")
        scene["pages"] = {_RASTER_PAGE_ID: _raster_page()}
        scene.setdefault("assets", {})[asset_id] = record
        applied = core.apply_operations(
            scene,
            [{
                "kind": "insert_node",
                "parent": {"kind": "page", "id": _RASTER_PAGE_ID},
                "index": 0,
                "node": _raster_image_node(asset_id),
            }],
        )
        scene = applied.get("scene") or scene
        export = core.export_preview(
            scene, "png",
            page_ids=[_RASTER_PAGE_ID],
            raise_on_error=False,
            asset_store_root=str(store_root),
        )
        # Defense in depth behind the byte precheck (races, partial writes):
        # a diagnostic naming this asset or node means the pixels are painted
        # AROUND a problem, not the artwork — never cache such a plate.
        for diagnostic in export.get("diagnostics") or []:
            subject_id = (diagnostic.get("subject") or {}).get("id")
            if subject_id in (asset_id, "svg_raster_image"):
                logger.warning(
                    "svg_raster_refused_diagnostic",
                    asset_id=asset_id,
                    code=diagnostic.get("code"),
                )
                return None
        for artifact in (export.get("export") or {}).get("artifacts") or []:
            # The engine emits raw pixel bytes under `bytes` (a list of ints),
            # never `bytes_base64` — reading the wrong key silently drops every
            # rasterized preview.
            raw = artifact.get("bytes")
            if raw:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(bytes(raw))
                return cached
        logger.warning("svg_raster_no_artifact", asset_id=asset_id)
    except Exception:  # noqa: BLE001 - an unviewable asset is the caller's honest answer…
        # …but never a SILENT one: the old bare swallow hid an engine schema
        # refusal for the fix's whole shipped life (Wave-C D3 forensic).
        logger.warning("svg_raster_failed", asset_id=asset_id, exc_info=True)
        return None
    return None
