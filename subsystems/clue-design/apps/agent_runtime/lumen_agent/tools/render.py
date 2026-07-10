"""The `render_preview` tool - render the scene, file the PNG, report as text."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..paths import to_virtual
from ..workspace import workspace_root
from .substrate import LumenDesignTools
from .view import _latest_preview_png

def _current_round_dir(tools: LumenDesignTools, current_round: int) -> Optional[Path]:
    if not current_round:
        return None
    candidate = workspace_root(tools) / "rounds" / f"round_{current_round}"
    return candidate if candidate.exists() else None


def _render_preview_text(tools: LumenDesignTools) -> str:
    """Wrap export_preview_bundle(critic_format="png"): render, copy the PNG into
    the round (or previews/) dir, and return a compact TEXT summary. On validation
    failure, return the errors verbatim. Never returns image blocks (§4b)."""
    raw = tools.export_preview_bundle(critic_format="png")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return f"render_preview: unexpected export output:\n{raw}"

    reviewer = payload.get("reviewer") or {}
    status = reviewer.get("status")
    validation_errors = reviewer.get("validation_errors") or []
    artifacts = reviewer.get("artifacts") or []

    lines: list[str] = [f"render_preview: status={status}"]
    png_path = _latest_preview_png(tools)
    copied_to: Optional[str] = None
    if png_path is not None:
        round_dir = _current_round_dir(tools, tools_current_round(tools))
        dest_dir = round_dir if round_dir is not None else (workspace_root(tools) / "previews")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / ("preview.png" if round_dir is not None else "latest.png")
        dest.write_bytes(png_path.read_bytes())
        # D5: the model reads its filesystem at virtual paths — surface the copied
        # preview at the same virtual form it can re-open, not the host path.
        copied_to = to_virtual(dest, tools.config)

    for artifact in artifacts:
        fmt = artifact.get("format")
        path = artifact.get("path") or artifact.get("critic_input_path")
        dims = ""
        if artifact.get("width") and artifact.get("height"):
            dims = f" {artifact['width']}x{artifact['height']}"
        # D5: artifact paths are host paths under the workspace; the model-facing
        # summary shows their virtual form (the API envelope keeps host paths).
        shown = to_virtual(path, tools.config) if path else path
        lines.append(f"- {fmt}{dims}: {shown}")
    if copied_to:
        lines.append(f"- copied preview: {copied_to}")

    diagnostics = reviewer.get("diagnostics") or []
    if diagnostics:
        lines.append(f"diagnostics ({len(diagnostics)}):")
        for diag in diagnostics[:20]:
            if isinstance(diag, dict):
                lines.append(
                    f"  [{diag.get('severity')}] {diag.get('code')}: {diag.get('message')}"
                )
    if validation_errors:
        lines.append("VALIDATION ERRORS:")
        for err in validation_errors:
            lines.append(f"  - {err}")
    return "\n".join(lines)


# The current round is resolved from the filesystem — the newest existing
# rounds/round_N directory. Round paths in task descriptions are authoritative
# (D8); this heuristic only picks where render_preview copies the PNG.
def tools_current_round(tools: LumenDesignTools) -> int:
    rounds = workspace_root(tools) / "rounds"
    if not rounds.exists():
        return 0
    highest = 0
    for child in rounds.iterdir():
        if child.is_dir() and child.name.startswith("round_"):
            suffix = child.name[len("round_"):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return highest


def make_render_preview_tool(tools: LumenDesignTools):
    from langchain_core.tools import tool

    @tool
    def render_preview() -> str:
        """Render the current scene to a validated PNG (and canonical SVG) on disk
        and return a compact text summary: artifact paths, dimensions, validation
        status, and any export diagnostics. Seeing the pixels is view("preview")'s
        job — this tool never returns image blocks.

        Requires preflight_design after any scene mutation — export refuses
        unresolved token paints."""
        return _render_preview_text(tools)

    return render_preview
