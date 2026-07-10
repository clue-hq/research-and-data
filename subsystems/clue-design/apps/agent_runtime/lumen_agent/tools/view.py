"""The `view` tool - real pixels on demand (D2 mechanism a, S1-verified)."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional

from py_lumen_obs import get_logger, log_span

from ..paths import to_virtual
from .substrate import LumenDesignTools

logger = get_logger("lumen_agent.tools.view")


# Grok-4.5 (and other vision providers) reject images whose short side is under
# 512px ("Image has 64 total pixels (8x8), below the minimum" — sweep run A2
# died here: an 8x8 kit-asset thumbnail was attached at iteration 0 and killed a
# LATER model call three iterations downstream, because the bad block stayed in
# history). We upscale any sub-minimum image to the floor BEFORE it is ever
# attached, so no provider can reject the block. Nearest-neighbor keeps it
# honest — it magnifies the real pixels without inventing detail.
_VISION_MIN_PX = 512


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
    manifest = tools.config.brand_kit_assets or {}
    return sorted(manifest.keys())


def _normalize_image_bytes(raw: bytes) -> tuple[bytes, str]:
    """Return (bytes, mime) for `raw`, upscaling to `_VISION_MIN_PX` on the short
    side when either dimension is below the vision-provider minimum.

    Sub-minimum images are magnified with nearest-neighbor (aspect preserved) so
    a provider can never reject the block; already-large images pass through
    unchanged. Raises on unreadable/corrupt bytes — the caller contains it into
    an honest error string so the turn continues.
    """
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as img:
        img.load()
        width, height = img.size
        if width >= _VISION_MIN_PX and height >= _VISION_MIN_PX:
            return raw, "image/png"
        scale = _VISION_MIN_PX / float(min(width, height))
        new_size = (max(_VISION_MIN_PX, round(width * scale)), max(_VISION_MIN_PX, round(height * scale)))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        upscaled = img.resize(new_size, Image.NEAREST)
        buffer = io.BytesIO()
        upscaled.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


def _image_block(png_path: Path) -> dict:
    """Build a base64 image block, normalizing sub-minimum images to the vision
    floor so the block cannot be rejected downstream. May raise on unreadable/
    corrupt bytes — `_view_content` is wrapped to contain that into a string."""
    normalized, mime = _normalize_image_bytes(png_path.read_bytes())
    data = base64.b64encode(normalized).decode("ascii")
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": mime,
        "data": data,
    }


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _scene_mutation_count(tools: LumenDesignTools) -> int:
    """Monotonic count of applied scene mutations. `scene_update_sources` grows
    on every `_replace_scene_from_core_response` (compile, structured edit,
    retokenize, logo placement, preflight resolution) and never on export, so it
    is the substrate's existing, cheap 'has the scene changed since render?'
    signal — no new bookkeeping needed."""
    return len(getattr(tools, "scene_update_sources", []) or [])


def _view_content(tools: LumenDesignTools, target: str) -> list[dict]:
    """Build the ToolMessage content (a LIST of blocks) for `view(target)`.

    - "preview" -> latest rendered PNG as [text, image]; text-only when none,
      or a stale-render refusal when the scene changed since the last render.
    - "asset:<id>" -> that kit asset's preview thumbnail as [text, image];
      text-only listing available ids when unknown/missing.
    Every call records a `view_called` trace event.
    """
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
        rendered_at = getattr(tools, "_preview_scene_version", None)
        current = _scene_mutation_count(tools)
        if rendered_at is not None and current > rendered_at:
            content = [
                _text_block(
                    "view: preview is STALE — the scene changed "
                    f"({current - rendered_at} mutation(s)) since the last render "
                    f"(iteration {getattr(tools, 'iteration', '?')}). The PNG on disk "
                    f"({png}) does not reflect the current tree. Call render_preview() "
                    "first, then view(\"preview\") again."
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="preview_stale")
            return content
        content = [
            _text_block(f"view: latest rendered preview ({to_virtual(png, tools.config)})"),
            _image_block(png),
        ]
        tools.record("agent", "view_called", input_summary=target, output_summary=f"blocks={len(content)}")
        return content

    if target.startswith("asset:"):
        asset_id = target[len("asset:"):]
        manifest = tools.config.brand_kit_assets or {}
        entry = manifest.get(asset_id)
        resolved = None
        if isinstance(entry, dict):
            resolved = tools._asset_preview_path(entry.get("record") or {})
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
                )
            ]
            tools.record("agent", "view_called", input_summary=target, output_summary="asset_missing_file")
            return content
        content = [
            _text_block(
                f"view: source preview for asset {asset_id} ({to_virtual(path, tools.config)})"
            ),
            _image_block(path),
        ]
        tools.record("agent", "view_called", input_summary=target, output_summary=f"blocks={len(content)}")
        return content

    content = [
        _text_block(
            f"view: unknown target {target!r}. Use \"preview\" or \"asset:<asset_id>\". "
            f"Available asset ids: {_asset_manifest_ids(tools)}"
        )
    ]
    tools.record("agent", "view_called", input_summary=target, output_summary="unknown_target")
    return content


def make_view_tool(tools: LumenDesignTools):
    from langchain_core.tools import tool

    @tool
    def view(target: str) -> list:
        """Look at real pixels. target="preview" returns the latest rendered PNG;
        target="asset:<asset_id>" returns that kit asset's source preview
        thumbnail. Returns image content so you can judge by looking, not by
        guessing from metadata."""
        # Containment (sweep A2): NOTHING inside view() — a provider-rejectable
        # image, an unreadable file, a corrupt/undecodable thumbnail — may
        # propagate as an unhandled exception and kill the turn unfinalized. On
        # any failure we return an honest error STRING as the tool result so the
        # agent can adapt and the loop continues.
        try:
            with log_span("tool_view", logger=logger, target=target):
                return _view_content(tools, target)
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
