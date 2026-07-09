"""The `view` tool - real pixels on demand (D2 mechanism a, S1-verified)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from .substrate import LumenDesignTools



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


def _image_block(png_path: Path) -> dict:
    data = base64.b64encode(png_path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": "image/png",
        "data": data,
    }


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _view_content(tools: LumenDesignTools, target: str) -> list[dict]:
    """Build the ToolMessage content (a LIST of blocks) for `view(target)`.

    - "preview" -> latest rendered PNG as [text, image]; text-only when none.
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
        else:
            content = [_text_block(f"view: latest rendered preview ({png})"), _image_block(png)]
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
        content = [_text_block(f"view: source preview for asset {asset_id} ({path})"), _image_block(path)]
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
        return _view_content(tools, target)

    return view
