"""The `view` tool - real pixels on demand (D2 mechanism a, S1-verified)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Optional

from py_lumen_obs import get_logger, log_span
from pydantic import StrictInt

from ..image_crop import ImageCropError, decoded_source_raster, validate_frame_index
from ..native_copy import finite_number, observe_native_text
from ..paths import to_virtual
from .asset_preview import rasterize_vector_preview
from .substrate import LumenDesignTools, blob_path_for_digest

logger = get_logger("lumen_agent.tools.view")


# Grok-4.5 (and other vision providers) reject images whose short side is under
# 512px ("Image has 64 total pixels (8x8), below the minimum" — sweep run A2
# died here: an 8x8 kit-asset thumbnail was attached at iteration 0 and killed a
# LATER model call three iterations downstream, because the bad block stayed in
# history). We upscale any sub-minimum image to the floor BEFORE it is ever
# attached, so no provider can reject the block. Nearest-neighbor keeps it
# honest — it magnifies the real pixels without inventing detail.
_VISION_MIN_PX = 512

# The other end of the same class of provider refusal, found on the first realistic
# website generation (genweb slice 0): a whole-page capture of a 3-4 section landing
# page comes out 1440x14325 (and 768x8095 at the narrow width), and OpenRouter refuses
# it outright — "invalid_prompt ... image dimensions exceed max allowed size: 8000
# pixels". The web turn is transactional, so that refusal discarded all 84 authored
# nodes. We downscale any over-ceiling image to the ceiling BEFORE it is attached, with
# headroom under the provider's 8000px so no rounding can land on the limit. LANCZOS
# (not NEAREST) on the way down: a downscale must keep the page legible enough to judge,
# and unlike the upscale it invents no detail — it averages the pixels that are there.
_VISION_MAX_PX = 7500

# The SAME refusal one limit lower, and the one web review actually lives under (genweb
# slice 2, G5): once a single request carries more than 20 image blocks, the provider's
# per-image dimension limit drops, and the first realistic chat-driven landing page died
# on the orchestrator's own call after ~28 minutes — "messages.1.content.39.image.source.
# base64.data: At least one of the image dimensions exceed max allowed size for
# many-image requests: 2000 pixels" (run_c6f4485…, anthropic/claude-opus-4.8 through
# OpenRouter's /responses endpoint). The turn is transactional, so the whole authored
# page was discarded.
#
# The number is evidence, not folklore. Probed against that same provider and endpoint
# (2026-08-19): 20 x 200x7500 ACCEPTED, 21 x 200x7500 REFUSED — the threshold is >20
# images; 40 x 200x3000/4000/5000/6000/7500 REFUSED, 40 x 200x2000 ACCEPTED — 2000 is
# accepted at twice the image count that killed the run. The vendor doc states the same
# rule: "If a single API request contains more than 20 images, a stricter per-image
# dimension limit applies ... resize each image so that neither dimension exceeds
# 2000 px, or keep the request to 20 or fewer image and document blocks."
#
# Why the web path clamps here unconditionally rather than counting images: an image is
# encoded ONCE, at attach time, and then lives in the conversation history that every
# later request replays. By the time a request is "many-image", the earlier images are
# already inside it at their original size — a clamp that only tightened on the 21st
# image would still send the first twenty oversized, and still be refused. Clamping every
# web view image is therefore the only version that provably survives accumulation, and
# it costs little real fidelity: providers downscale to their own long-edge budget anyway
# (Claude's high-resolution tier renders at most a 2576px long edge), so a whole-page
# capture was never actually being judged at 7500px.
_VISION_MANY_IMAGE_MAX_PX = 2000


def _latest_preview_png(tools: LumenDesignTools) -> Optional[Path]:
    """Resolve the newest rendered PNG on disk, or None if nothing rendered yet.

    Prefer the latest validated bundle/export artifact (its `path`/
    `critic_input_path`); fall back to the most recent `.png` in `preview_paths`.
    """
    latest = tools.latest_preview_bundle or tools.latest_export_summary
    if isinstance(latest, dict):
        for artifact in reversed(latest.get("artifacts", []) or []):
            if artifact.get("format") != "png":
                continue
            candidate = artifact.get("path") or artifact.get("critic_input_path")
            if candidate and Path(candidate).exists():
                return Path(candidate)
    for candidate in reversed(tools.preview_paths):
        path = Path(candidate)
        if path.suffix.lower() == ".png" and path.exists():
            return path
    return None


def _asset_manifest_ids(tools: LumenDesignTools) -> list[str]:
    """Asset ids available to this turn: kit, workspace library, then current scene.

    W1.1: the library half is the only DISCOVERY surface a scene turn has for a
    pre-generated asset — the manifest is looked up by id, never rendered into the
    prompt, so without it an agent that mistypes an id is told nothing useful.
    The current scene also contains assets generated after those startup
    manifests were frozen. Discover only those registered ids, never store files.
    """
    kit = tools.config.brand_kit_assets or {}
    library = tools.config.asset_library or {}
    scene_assets = tools.scene.get("assets") or {}
    manifest_ids = set(kit) | set(library)
    return (
        sorted(kit)
        + sorted(set(library) - set(kit))
        + sorted(set(scene_assets) - manifest_ids)
    )[:24]


def _reference_entries(tools: LumenDesignTools) -> list[tuple[int, str, dict]]:
    """The turn's references as (1-based index, asset_id, entry), order-sorted.

    `config.reference_assets` is the by-value RC manifest (see config.py). The
    `order` field is the 0-based user attachment order; the view/docs surface
    speaks 1-based (`reference:1` = the first attachment). None/empty → []."""
    manifest = tools.config.reference_assets or {}
    ordered = sorted(
        manifest.items(), key=lambda kv: ((kv[1] or {}).get("order", 0), kv[0])
    )
    return [(i + 1, asset_id, entry or {}) for i, (asset_id, entry) in enumerate(ordered)]


def _reference_target_labels(tools: LumenDesignTools) -> list[str]:
    return [f"reference:{i}" for (i, _aid, _e) in _reference_entries(tools)]


def _normalize_image_bytes(raw: bytes, max_px: int = _VISION_MAX_PX) -> tuple[bytes, str]:
    """Return (bytes, mime) for `raw`, clamped into the vision provider's accepted
    size band: at least `_VISION_MIN_PX` on the short side, at most `max_px` on the
    long side.

    `max_px` defaults to the SINGLE-image ceiling `_VISION_MAX_PX`. Callers whose
    images accumulate in one request — the website harness, whose review conversation
    carries three widths per render plus state captures — pass
    `_VISION_MANY_IMAGE_MAX_PX` instead.

    Sub-minimum images are magnified with nearest-neighbor and over-ceiling ones are
    reduced with LANCZOS — aspect preserved either way — so a provider can never
    reject the block for its dimensions. Static JPEG/PNG images already inside the
    band pass through byte-identical with their actual MIME. Other formats and
    animations become a PNG of frame zero of the viewed file; source bytes stay intact.
    Raises on unreadable/corrupt bytes — the caller contains it into an honest error
    string so the turn continues.

    The ceiling wins when a single image violates both bounds (an extreme sliver
    whose long side is over the ceiling and whose short side is still under the
    floor after the reduction): the two bounds are then unsatisfiable together at a
    fixed aspect, and the over-ceiling refusal is the one realistic page captures hit.
    """
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as img:
        source_format = img.format
        animated = getattr(img, "is_animated", False)
        img.seek(0)
        img.load()
        width, height = img.size
        scale = 1.0
        if min(width, height) < _VISION_MIN_PX:
            scale = _VISION_MIN_PX / float(min(width, height))
        if max(width, height) * scale > max_px:
            scale = max_px / float(max(width, height))
        if scale == 1.0 and not animated and source_format in ("JPEG", "PNG"):
            return raw, "image/jpeg" if source_format == "JPEG" else "image/png"
        if scale > 1.0:
            new_size = (max(_VISION_MIN_PX, round(width * scale)), max(_VISION_MIN_PX, round(height * scale)))
            resample = Image.NEAREST
        else:
            new_size = (
                max(1, min(max_px, round(width * scale))),
                max(1, min(max_px, round(height * scale))),
            )
            resample = Image.LANCZOS
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        resized = img.resize(new_size, resample) if scale != 1.0 else img
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


def _image_block(png_path: Path, max_px: int = _VISION_MAX_PX) -> dict:
    """Build a base64 image block, normalizing the image into the vision provider's
    accepted size band so the block cannot be rejected downstream. `max_px` is the
    long-side ceiling to clamp to (see `_normalize_image_bytes`). May raise on
    unreadable/corrupt bytes — `_view_content` is wrapped to contain that into a
    string."""
    return _image_bytes_block(png_path.read_bytes(), max_px=max_px)


def _image_bytes_block(raw: bytes, max_px: int = _VISION_MAX_PX) -> dict:
    normalized, mime = _normalize_image_bytes(raw, max_px=max_px)
    data = base64.b64encode(normalized).decode("ascii")
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": mime,
        "data": data,
    }


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _asset_alpha_inspection_blocks(raw: bytes, *, report_opaque: bool = False) -> list[dict]:
    """Disambiguate transparent artwork from the vision client's implicit matte.

    Inspection only: never register these composites or change source bytes.
    Observe decoded preview alpha, not asset-kind labels or inferred source alpha.
    """
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as source:
        source.seek(0)
        rgba = source.convert("RGBA")
    alpha = rgba.getchannel("A")
    counts = alpha.histogram()
    opaque = counts[255] == rgba.width * rgba.height
    if opaque and not report_opaque:
        return []
    bounds = alpha.getbbox()
    facts = {
        "preview_alpha": {
            "width_px": rgba.width, "height_px": rgba.height,
            "transparent_pixels": counts[0], "opaque_pixels": counts[255],
            "translucent_pixels": sum(counts[1:255]),
            "visible_bounds_px": list(bounds) if bounds else None,
        },
        "preview_sha256": hashlib.sha256(raw).hexdigest(),
        "decoded_frame_index": 0,
        "composition": "unclassified",
        "inspection_only": (
            "These facts measure the decoded preview before vision resizing, not proof "
            "about an unavailable original. Alpha does not classify a product cutout "
            "versus a finished composite: small translucent edges or rounded corners "
            "may surround a baked background. Visible bounds are not a recommended "
            "crop; they can include shadows or omit intentional transparent spacing. "
            "Bounds are [left, top, right, bottom], with right/bottom exclusive; no "
            "artwork means null bounds. "
            + ("All decoded pixels are opaque; no comparison surface is added." if opaque else
            "The next image shows the SAME preview on two artificial surfaces: "
            "LEFT white (#FFFFFF), RIGHT charcoal (#202020). These surfaces are not "
            "baked into the source and are not placement assets. The preceding image "
            "is the original preview. Transparent pixels may otherwise appear black "
            "or white in a vision client. Compare actual ink and contrast here; place "
            "the original asset ID.")
        ),
    }
    if opaque:
        return [_text_block(json.dumps(facts))]
    side, inset = 512, 24
    scale = (side - 2 * inset) / max(rgba.size)
    size = (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale)))
    artwork = rgba.resize(size, Image.Resampling.NEAREST if scale > 1 else Image.Resampling.LANCZOS)
    comparison = Image.new("RGB", (side * 2, side))
    for index, color in enumerate(((255, 255, 255, 255), (32, 32, 32, 255))):
        panel = Image.new("RGBA", (side, side), color)
        panel.alpha_composite(artwork, ((side - size[0]) // 2, (side - size[1]) // 2))
        comparison.paste(panel.convert("RGB"), (index * side, 0))
    buffer = io.BytesIO()
    comparison.save(buffer, format="PNG")
    return [_text_block(json.dumps(facts)), _image_bytes_block(buffer.getvalue())]


def _preview_page_id(tools: LumenDesignTools, png: Path) -> str | None:
    """Associate these exact preview bytes with their validated artifact's page."""
    latest = tools.latest_preview_bundle or tools.latest_export_summary
    if isinstance(latest, dict):
        for artifact in reversed(latest.get("artifacts", []) or []):
            candidate = artifact.get("path") or artifact.get("critic_input_path")
            if artifact.get("format") == "png" and candidate and Path(candidate) == png:
                return artifact.get("page_id")
    return None


def _preview_text_table(
    scene: dict, page_id: str | None, source_height: int, proxy_height: int, *, resolved: bool,
) -> str:
    """Describe nominal em sizes, using the core's canonical page and resolved text.

    Skia maps canonical page layout height to the actual raster height. The
    proxy then resizes that raster to its *rounded* content height. No authored
    unit conversion, token resolution, glyph measurement or acceptance policy
    belongs here. Unsupported observations stay explicitly unavailable.
    """
    def unavailable(reason: str) -> str:
        return f"\n\nNative text observation: native text metrics unavailable — {reason}."

    if not resolved:
        return unavailable("no current preflight bound to these preview bytes")
    page = (scene.get("pages") or {}).get(page_id)
    if not isinstance(page, dict):
        return unavailable("rendered page association is missing")
    size = page.get("size") or {}
    if size.get("unit") != "pt" or any(
        not finite_number(size.get(axis)) or size[axis] < 1 for axis in ("width", "height")
    ):
        return unavailable("canonical page dimensions are missing or unsupported")

    def cell(value: str, limit: int | None = None) -> str:
        value = " ".join(value.split())
        if limit is not None and len(value) > limit:
            value = value[:limit - 1] + "…"
        return (
            value.replace("\\", "\\\\").replace("|", "\\|")
            .replace("<", "&lt;").replace(">", "&gt;")
        )

    inventory = observe_native_text(scene, page_id)
    rows: list[str] = []
    line_rows: list[str] = []
    hidden = len(inventory["excluded"])
    instances = sum("instance" in item["reason"] for item in inventory["unresolved"])
    omitted = 0
    for row in inventory["occurrences"]:
        node_id, font_size, issue = row["node_id"], row["font_size"], row["observation_issue"]
        source_em = font_size * source_height / size["height"] if issue is None else None
        proxy_em = font_size * proxy_height / size["height"] if issue is None else None
        if issue is None and not all(math.isfinite(value) for value in (source_em, proxy_em)):
            issue = "unrepresentable em size"
        if len(rows) >= 40:
            omitted += 1
            continue
        values = (
            f"unavailable ({issue}) | unavailable"
            if issue else f"{source_em:.2f} | {proxy_em:.2f}"
        )
        rows.append(f"| {cell(node_id)} | {cell(row['text'], 56)} | {values} |")
        geometry = row["line_geometry"]
        if geometry["status"] == "ok":
            edges = " | ".join(
                f"{geometry[key]:.2f}"
                for key in ("line_top", "line_bottom", "allocated_top", "allocated_bottom")
            )
            line_rows.append(f"| {cell(node_id)} | {geometry['line_count']} | {edges} |")
        else:
            line_rows.append(
                f"| {cell(node_id)} | unavailable ({cell(geometry['reason'])}) | — | — | — | — |"
            )

    caption = (
        f"\n\nNative text on page {cell(page_id)}: resolved em size in source-preview pixels "
        "and in the "
        "actual proxy content, rounded to 0.01px; not glyph height or a readability verdict. "
        "Use these sizes with the image to judge legibility. Clipping, occlusion, "
        "off-canvas placement and text inside images are not measured. "
        f"{hidden} zero-opacity text nodes excluded; {instances} instances not expanded; "
        f"{omitted} additional rows omitted."
    )
    if not rows:
        return caption + " No native text rows available."
    return (
        caption
        + "\n\n| Node | Authored text sample | Source preview em px | 360px proxy em px |"
        + "\n| --- | --- | ---: | ---: |\n"
        + "\n".join(rows)
        + "\n\nCore-measured vertical text edges in unrotated page-space pt (not proxy pixels). "
        "Line boxes include font leading; they are not pixel-tight glyph ink. "
        "Allocated boxes can include empty slack. For related text, subtract the upper "
        "node's line bottom from the lower node's line top to inspect their line-box gap; "
        "relationships and optical spacing still require the image. Font fallback or "
        "heuristic measurement limits remain; this does not certify legibility."
        + "\n\n| Node | Nonempty lines | Line top | Line bottom |"
        " Allocated top | Allocated bottom |"
        + "\n| --- | ---: | ---: | ---: | ---: | ---: |\n"
        + "\n".join(line_rows)
    )


def _preview_readability_blocks(
    raw: bytes, *, scene: dict | None = None, page_id: str | None = None, resolved: bool = False,
) -> list[dict]:
    """A derived observation only: never an export, asset, or acceptance receipt.

    Padding keeps the 360px-wide content below the full-view scale even after
    our provider-size normalization. Provider-internal resampling is unknown.
    """
    from PIL import Image, ImageDraw

    display_width, padding = 360, 32
    metadata = {
        "source_preview_sha256": hashlib.sha256(raw).hexdigest(),
        "display_width_assumption_px": display_width,
        "status": "unavailable",
    }

    def unavailable(reason: str) -> list[dict]:
        metadata["status"] = "unavailable"
        return [_text_block(
            f"view: readability proxy unavailable: {reason}. "
            "The full preview above remains available; feed-scale legibility was not observed.\n"
            + json.dumps(metadata, sort_keys=True)
        )]

    try:
        with Image.open(io.BytesIO(raw)) as source:
            width, height = source.size
            metadata["source_size_px"] = [width, height]
            if width < display_width:
                return unavailable("source width is smaller than 360px; no enlarged proxy was made")
            scale = display_width / width
            content_height = round(height * scale)
            canvas_size = (
                max(_VISION_MIN_PX, display_width + 2 * padding),
                max(_VISION_MIN_PX, content_height + 2 * padding),
            )
            if max(canvas_size) > _VISION_MANY_IMAGE_MAX_PX:
                return unavailable("360px-wide proxy with padding exceeds the 2000px observation limit")
            if content_height < 1:
                return unavailable("scaled source height is below one pixel")
            source.seek(0)
            reduced = source.convert("RGBA").resize(
                (display_width, content_height), Image.Resampling.LANCZOS
            )
            canvas = Image.new("RGBA", canvas_size, (224, 224, 224, 255))
            x = (canvas.width - display_width) // 2
            y = (canvas.height - content_height) // 2
            # No mask: preserve the creative's own alpha, rather than compositing
            # its transparent pixels onto the observation-only gray matte.
            canvas.paste(reduced, (x, y))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((x - 2, y - 2, x + display_width + 1, y + content_height + 1), outline=(96, 96, 96, 255))
            draw.text((12, 10), "OBSERVATION ONLY - 360 px readability proxy", fill=(32, 32, 32, 255))
            draw.text((12, canvas.height - 22), "Gray padding / border are outside the creative", fill=(32, 32, 32, 255))
            encoded = io.BytesIO()
            canvas.save(encoded, format="PNG")
        metadata.update({
            "status": "available",
            "scale": scale,
            "source_frame_index": 0,
            "content_size_px": [display_width, content_height],
            "canvas_size_px": list(canvas_size),
            "content_rect_px": [x, y, display_width, content_height],
        })
        return [
            _text_block(
                "view: illustrative 360px-wide feed readability proxy, not a platform specification. "
                "Gray padding, border and labels are outside the creative. Judge copy, CTA and product-detail "
                "legibility at this scale; successful preflight does not establish readability. "
                "The full preview above remains the source; provider-internal resampling is unknown.\n"
                + json.dumps(metadata, sort_keys=True)
                + (_preview_text_table(scene, page_id, height, content_height, resolved=resolved)
                   if scene is not None else "")
            ),
            _image_bytes_block(encoded.getvalue(), max_px=_VISION_MANY_IMAGE_MAX_PX),
        ]
    except (OSError, ValueError) as error:
        return unavailable(f"observation could not be prepared ({type(error).__name__})")


def _image_observation_label(
    path: Path, label: str, *, source_mime: str | None = None, raw: bytes | None = None,
) -> str:
    """Describe the still observation in a standard text block beside the image.

    The frame index belongs to the viewed file. A static thumbnail of a GIF does
    not establish which original frame it depicts, even when its pixels are PNG.
    """
    from PIL import Image

    with Image.open(io.BytesIO(raw) if raw is not None else path) as img:
        if getattr(img, "is_animated", False):
            return label + "; first frame only (frame index 0 of the viewed file); animation not reviewed."
    if source_mime == "image/gif":
        return label + "; still preview of GIF source; source frame index unknown; animation not reviewed."
    return label


def _original_gif_hint(tools: LumenDesignTools, asset_id: str, record: dict) -> str:
    """Original availability is independent of which frame a thumbnail depicts."""
    if (record.get("media") or {}).get("mime_type") != "image/gif":
        return ""
    try:
        _record, raw, mime, digest = tools._original_raster_source(asset_id)
        with decoded_source_raster(raw, mime_type=mime, frame_index=0) as (source, count):
            width, height = source.size
    except ImageCropError:
        return (
            "; verified original GIF frames unavailable; "
            "this still does not establish all source content."
        )
    return (
        f" Original GIF available: {count} frames, decoded canvas {width}x{height}, "
        f"source SHA-256 {digest}. Inspect a specific source frame with "
        f'view(target="asset:{asset_id}", frame_index=<integer 0..{count - 1}>). '
        "A blank still does not establish that the whole source is blank."
    )


def _selected_frame_content(
    tools: LumenDesignTools, target: str, asset_id: str, frame_index: int,
) -> list[dict]:
    """A read-only still from the same verified bytes and decoder used by crop."""
    try:
        _record, raw, mime, digest = tools._original_raster_source(asset_id)
        with decoded_source_raster(raw, mime_type=mime, frame_index=frame_index) as (source, count):
            width, height = source.size
            output = io.BytesIO()
            source.save(output, format="PNG")
        content = [
            _text_block(
                f"view: asset {asset_id}; selected frame index {frame_index} of {count} frames; "
                f"decoded composited canvas {width}x{height}; source SHA-256 {digest}. "
                "Still observation only; animation not reviewed. Crop coordinates use these "
                "decoded source pixels, not the possibly resized observation."
            ),
            _image_bytes_block(output.getvalue()),
        ]
        status = f"frame_index={frame_index}; blocks={len(content)}"
    except ImageCropError as error:
        code = error.code.replace("asset.crop_", "view.frame_")
        content = [_text_block(f"{code}: {error}")]
        status = code
    tools.record("agent", "view_called", input_summary=target, output_summary=status)
    return content


def _view_content(tools, target: str, frame_index=None) -> list:
    from .asset_catalog import context_text, materialize_asset
    entry = {}
    if target.startswith("asset:"):
        asset_id = target.removeprefix("asset:")
        entry = (tools.config.brand_kit_assets or {}).get(asset_id) or (tools.config.asset_library or {}).get(asset_id) or {}
        record = entry.get("record") or (tools.scene.get("assets") or {}).get(asset_id)
        if record:
            materialize_asset(tools.config, record)
    elif target.startswith("reference:"):
        ref = target.removeprefix("reference:")
        entry = next((e for i, aid, e in _reference_entries(tools)
                      if str(i) == ref or aid == ref), {})
    content = _view_pixels(tools, target, frame_index=frame_index)
    details = context_text(entry)
    return ([_text_block(details)] if details else []) + content


def _view_pixels(
    tools: LumenDesignTools, target: str, frame_index: int | None = None,
) -> list[dict]:
    """Build the ToolMessage content (a LIST of blocks) for `view(target)`.

    - "preview" -> latest rendered PNG as [text, image], plus a candidate-scene
      readability proxy when representable; text-only when none,
      or a stale-render refusal when the scene changed since the last render.
    - "asset:<id>" -> that kit, library, or current scene asset's preview as [text, image];
      text-only listing available ids when unknown/missing.
    Every call records a `view_called` trace event.
    """
    if frame_index is not None:
        try:
            validate_frame_index(frame_index)
            if not target.startswith(("asset:", "reference:")):
                raise ImageCropError(
                    "view.frame_unsupported_target",
                    "frame_index requires an asset or turn reference target.",
                )
        except ImageCropError as error:
            code = error.code.replace("asset.crop_", "view.frame_")
            tools.record("agent", "view_called", input_summary=target, output_summary=code)
            return [_text_block(f"{code}: {error}")]
    if target == "preview":
        png = _latest_preview_png(tools)
        if png is None:
            content = [
                _text_block(
                    "view: no preview has been rendered yet — call render_preview() first."
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="no_preview")
            return content
        # Staleness contract (sweep A3 burned rounds on stale black frames): the
        # scene was mutated after the last render, so the on-disk PNG no longer
        # reflects the current tree. Refuse rather than silently serve a lie —
        # view is a cheap read; re-rendering inside it would couple this read to
        # the export machinery (which can itself fail and kill the turn, the
        # very A2 failure mode this pass hardens). Tell the agent to render.
        rendered_scene = getattr(tools, "_preview_scene_stamp", None)
        receipt = getattr(tools, "_preview_receipt", None)
        changed_scene = rendered_scene is not None and tools._scene_stamp() != rendered_scene
        changed_artifacts = receipt is not None and tools._current_preview_receipt() != receipt
        if changed_scene or changed_artifacts:
            content = [
                _text_block(
                    "view: preview is STALE — scene content or rendered bytes changed "
                    "since the last verified render "
                    f"(iteration {getattr(tools, 'iteration', '?')}). The PNG on disk "
                    f"({png}) does not reflect the current tree. Call render_preview() "
                    "first, then view(\"preview\") again."
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="preview_stale")
            return content
        # Both observations derive from the same read, with the original full
        # image first. Website/legacy/reference observations keep their contract.
        candidate = getattr(tools.config, "scene_skill_bundle", "legacy") == "candidate"
        raw = png.read_bytes() if candidate else None
        content = [
            _text_block(_image_observation_label(
                png, f"view: latest rendered preview ({to_virtual(png, tools.config)})", raw=raw,
            )),
            _image_bytes_block(raw) if raw is not None else _image_block(png),
        ]
        if raw is not None:
            content.extend(_preview_readability_blocks(
                raw, scene=tools.scene, page_id=_preview_page_id(tools, png),
                resolved=(receipt is not None and rendered_scene is not None
                          and getattr(tools, "_preflight_scene_stamp", None) == rendered_scene),
            ))
        tools.record("agent", "view_called", input_summary=target, output_summary=f"blocks={len(content)}")
        return content

    if target.startswith("asset:"):
        asset_id = target[len("asset:"):]
        if frame_index is not None:
            return _selected_frame_content(tools, target, asset_id, frame_index)
        # Preserve the kit/library lookup order, then fall back to the current
        # scene for assets generated after the by-value manifests were frozen.
        # The same resolver keeps every source bound to this run's asset store.
        entry = (tools.config.brand_kit_assets or {}).get(asset_id)
        if not isinstance(entry, dict):
            entry = (tools.config.asset_library or {}).get(asset_id)
        resolved = None
        if isinstance(entry, dict):
            record = entry.get("record") or {}
        else:
            record = (tools.scene.get("assets") or {}).get(asset_id) or {}
        if record:
            resolved = tools._asset_preview_path(record)
        if resolved is None and record:
            # D3: a vector whose stored thumbnail is not pixels has no preview to
            # resolve — rasterize it through the engine, once, and cache it. The
            # agent must never place a mark it cannot look at (apollo.io, W5).
            rasterized = rasterize_vector_preview(
                tools.core, record, asset_id, tools.config.effective_asset_store_root
            )
            if rasterized is not None:
                resolved = (str(rasterized), None, None)
        if resolved is None:
            available = _asset_manifest_ids(tools)
            content = [
                _text_block(
                    f"view: asset {asset_id!r} has no viewable preview. "
                    f"Available asset ids: {available}"
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="asset_unavailable")
            return content
        preview_path, _pw, _ph = resolved
        path = Path(preview_path)
        if not path.exists():
            available = _asset_manifest_ids(tools)
            content = [
                _text_block(
                    f"view: asset {asset_id!r} preview file is missing. "
                    f"Available asset ids: {available}"
                    + _original_gif_hint(tools, asset_id, record)
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="asset_missing_file")
            return content
        content = [
            _text_block(_image_observation_label(
                path, f"view: source preview for asset {asset_id} ({to_virtual(path, tools.config)})",
                source_mime=(record.get("media") or {}).get("mime_type"),
            ) + _original_gif_hint(tools, asset_id, record)),
            _image_block(path),
        ]
        if getattr(tools.config, "scene_skill_bundle", "legacy") == "candidate":
            content.extend(_asset_alpha_inspection_blocks(path.read_bytes()))
        tools.record("agent", "view_called", input_summary=target, output_summary=f"blocks={len(content)}")
        return content

    if target.startswith("reference:"):
        ref = target[len("reference:"):]
        entries = _reference_entries(tools)
        match = None
        # 1-based index (`reference:1` = first attachment) or exact asset id.
        if ref.isdigit():
            wanted = int(ref)
            match = next((e for e in entries if e[0] == wanted), None)
        if match is None:
            match = next((e for e in entries if e[1] == ref), None)
        if match is None:
            content = [
                _text_block(
                    f"view: unknown reference {ref!r}. "
                    f"Available references: {_reference_target_labels(tools)}"
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="reference_unknown")
            return content
        index, asset_id, entry = match
        if frame_index is not None:
            return _selected_frame_content(tools, target, asset_id, frame_index)
        digest = entry.get("preview_digest")
        path = None
        if digest:
            path = blob_path_for_digest(tools.config.effective_asset_store_root, digest)
        if path is None or not path.exists():
            content = [
                _text_block(
                    f"view: reference {index} ({asset_id}) preview bytes are missing. "
                    f"Available references: {_reference_target_labels(tools)}"
                    + _original_gif_hint(tools, asset_id, entry.get("record") or {})
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="reference_missing_file")
            return content
        label = entry.get("title") or asset_id
        content = [
            _text_block(_image_observation_label(
                path, f"view: reference {index} — {label} ({to_virtual(path, tools.config)})",
                source_mime=((entry.get("record") or {}).get("media") or {}).get("mime_type"),
            ) + _original_gif_hint(tools, asset_id, entry.get("record") or {})),
            _image_block(path),
        ]
        tools.record("agent", "view_called", input_summary=target, output_summary=f"blocks={len(content)}")
        return content

    # Invalid target. Advertise the reference form ONLY when references rode this
    # turn — never tease an empty target family (no-op guarantee: a no-reference
    # turn's error string is byte-identical to before RC).
    if tools.config.reference_assets:
        targets = "\"preview\", \"asset:<asset_id>\", or \"reference:<n>\""
    else:
        targets = "\"preview\" or \"asset:<asset_id>\""
    content = [
        _text_block(
            f"view: unknown target {target!r}. Use {targets}. "
            f"Available asset ids: {_asset_manifest_ids(tools)}"
        )
    ]
    tools.record("agent", "view_called", input_summary=target, output_summary="unknown_target")
    return content


def make_view_tool(tools: LumenDesignTools):
    from langchain_core.tools import tool

    @tool
    def view(target: str, frame_index: StrictInt | None = None) -> list:
        """Look at real pixels. target="preview" returns the latest rendered PNG;
        target="asset:<asset_id>" returns that asset's source preview thumbnail —
        a brand-kit asset, a workspace library asset, or an asset registered in
        the current scene (including newly generated imagery). Returns image
        content so you can judge by looking, not by guessing from metadata.
        Optional frame_index is an explicit nonnegative integer for a GIF original
        in this run's authorized asset context, including reference:<n> aliases.
        It inspects one composited source frame; animation is not reviewed. The
        original digest and decoded pixel dimensions accompany the still. Omit
        it to retain the default preview; it is unsupported for target="preview"."""
        # Containment (sweep A2): NOTHING inside view() — a provider-rejectable
        # image, an unreadable file, a corrupt/undecodable thumbnail — may
        # propagate as an unhandled exception and kill the turn unfinalized. On
        # any failure we return an honest error STRING as the tool result so the
        # agent can adapt and the loop continues.
        try:
            with log_span("tool_view", logger=logger, target=target):
                if target == "preview":
                    # Keep freshness, file selection and both pixel observations
                    # in the same transaction as scene edits and preview exports.
                    with tools._scene_mutation_lock:
                        return _view_content(tools, target, frame_index=frame_index)
                return _view_content(tools, target, frame_index=frame_index)
        except Exception as exc:  # noqa: BLE001 - deliberate turn-safety boundary
            try:
                tools.record(
                    "agent",
                    "view_called",
                    input_summary=target,
                    output_summary=f"view_failed: {type(exc).__name__}",
                )
            except Exception:  # pragma: no cover - trace must never mask the result
                pass
            return f"view failed: {exc}"

    return view
