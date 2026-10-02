"""Read-only, untruncated native text observation over the resolved scene.

Shared by the display table and candidate copy binding. This is not a second
renderer: instances/transforms are explicit limits, and clipping, occlusion,
off-canvas placement and raster-contained text remain visual review concerns.
"""

import math

from pydantic import BaseModel, ConfigDict, Field


class NativeCopyReviewProfile(BaseModel):
    """Caller-selected nominal-size policy, never an inferred viewing context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_width_px: float = Field(gt=0, allow_inf_nan=False, strict=True)
    minimum_nominal_em_px: float = Field(gt=0, allow_inf_nan=False, strict=True)


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text_line_geometry(node: dict, issue: str | None) -> dict:
    """Expose existing core line edges, never infer ink from an allocated box.

    The caller owns current preflight/preview binding. These are unrotated
    page-space line boxes, not pixel-tight ink or an optical-spacing verdict.
    """
    def unavailable(reason: str) -> dict:
        return {"status": "unavailable", "reason": reason}

    if issue:
        return unavailable(issue)
    computed = node.get("computed") or {}
    lines = computed.get("text_lines")
    box = computed.get("layout_bounds")
    if not isinstance(lines, list) or not lines or not isinstance(box, dict):
        return unavailable("measured text lines or allocated bounds are missing")

    def valid_rect(rect: object) -> bool:
        return isinstance(rect, dict) and all(
            finite_number(rect.get(key)) for key in ("x", "y", "width", "height")
        ) and rect["width"] >= 0 and rect["height"] >= 0

    if not valid_rect(box) or any(not valid_rect(line) for line in lines):
        return unavailable("invalid measured text lines or allocated bounds")
    painted = [line for line in lines if line["width"] > 0 and line["height"] > 0]
    if not painted:
        return unavailable("no nonempty measured text lines")
    edges = {
        "line_top": min(line["y"] for line in painted),
        "line_bottom": max(line["y"] + line["height"] for line in painted),
        "allocated_top": box["y"],
        "allocated_bottom": box["y"] + box["height"],
    }
    if not all(finite_number(value) for value in edges.values()):
        return unavailable("unrepresentable line edges")
    return {
        "status": "ok", "coordinate_space": "page_unrotated_pt",
        "line_count": len(painted), **edges,
    }


def observe_native_text(scene: dict, page_id: str) -> dict:
    """Inventory reachable nonempty text, retaining known hidden exclusions."""
    result = {"occurrences": [], "excluded": [], "unresolved": []}
    page = (scene.get("pages") or {}).get(page_id)
    if not isinstance(page, dict):
        result["unresolved"].append(
            {"page_id": page_id, "reason": "rendered page association is missing"}
        )
        return result
    nodes = scene.get("nodes") or {}
    visited: set[str] = set()
    pending = [
        (node_id, False, None, None, None)
        for node_id in reversed(page.get("children") or [])
    ]
    while pending:
        node_id, ancestor_hidden, ancestor_issue, binding_issue, geometry_issue = pending.pop()
        identity = {"page_id": page_id, "node_id": node_id}
        if node_id in visited:
            result["unresolved"].append({**identity, "reason": "ambiguous repeated reachability"})
            continue
        visited.add(node_id)
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            result["unresolved"].append({**identity, "reason": "reachable node is missing"})
            continue
        # The renderer's pinned pass paints from page space, outside ancestor
        # opacity/transform. Still traverse hidden parents to find pinned text.
        if node.get("position_mode") == "absolute":
            ancestor_hidden, ancestor_issue, binding_issue, geometry_issue = False, None, None, None
        opacity = node.get("opacity", 1)
        issue = ancestor_issue
        opacity_resolved = node.get("opacity_token") is None and finite_number(opacity)
        if not opacity_resolved:
            issue = binding_issue = "unresolved opacity"
        node_hidden = ancestor_hidden or (opacity_resolved and opacity <= 0)
        transform = node.get("transform") or {}
        if any(transform.get(key, 0) != 0 for key in ("rotation", "skew_x", "skew_y")):
            issue = "unsupported transform"
        if transform.get("flip_x") or transform.get("flip_y"):
            geometry_issue = "unsupported transform for line edges"
        kind = node.get("kind") or {}
        if kind.get("kind") == "instance" and not node_hidden:
            result["unresolved"].append(
                {**identity, "reason": "instance text expansion is unsupported"}
            )
        if kind.get("kind") in ("frame", "group", "auto_layout"):
            pending.extend(
                (child, node_hidden, issue, binding_issue, geometry_issue)
                for child in reversed(node.get("children") or [])
            )
        if kind.get("kind") != "text" or not (kind.get("content") or "").strip():
            continue
        row = {**identity, "text": kind["content"]}
        if node_hidden:
            result["excluded"].append({**row, "reason": "zero opacity"})
            continue
        if any(
            kind.get(key) is not None
            for key in (
                "style_token",
                "font_size_token",
                "line_height_token",
                "letter_spacing_token",
            )
        ):
            issue = "unresolved typography"
        font_size = kind.get("font_size")
        if not finite_number(font_size) or font_size <= 0:
            issue = "invalid resolved font size"
        if (page.get("size") or {}).get("unit") != "pt":
            geometry_issue = "canonical page units are missing or unsupported"
        result["occurrences"].append(
            {
                **row,
                "font_size": font_size,
                "observation_issue": issue,
                "binding_issue": binding_issue,
                "line_geometry": _text_line_geometry(node, issue or geometry_issue),
            }
        )
    return result


def native_nominal_em_at_width(
    scene: dict, page_id: str, row: dict, display_width_px: float,
) -> dict:
    """Measure untransformed nominal type at a caller-selected display width.

    ``row`` must come from ``observe_native_text`` on this same resolved scene;
    its binding issue retains ancestor opacity and pinned-node semantics. The
    caller owns preflight/preview freshness. This width-normalized measure is
    neither the rounded PNG proxy size nor rendered glyph size. Transforms,
    clipping, occlusion and raster-contained text remain visual review limits.
    """
    def unavailable(reason: str) -> dict:
        return {"status": "unavailable", "nominal_em_px": None, "reason": reason}

    if not finite_number(display_width_px) or display_width_px <= 0:
        return unavailable("display width must be positive and finite")
    page = (scene.get("pages") or {}).get(page_id)
    if not isinstance(page, dict):
        return unavailable("rendered page association is missing")
    size = page.get("size") or {}
    if size.get("unit") != "pt" or any(
        not finite_number(size.get(axis)) or size[axis] < 1 for axis in ("width", "height")
    ):
        return unavailable("canonical page dimensions are missing or unsupported")
    if row.get("page_id") != page_id:
        return unavailable("native text row belongs to another page")
    if row.get("binding_issue"):
        return unavailable(row["binding_issue"])
    issue = row.get("observation_issue")
    if issue not in (None, "unsupported transform"):
        return unavailable(issue)

    node = (scene.get("nodes") or {}).get(row.get("node_id"))
    if not isinstance(node, dict):
        return unavailable("native text source node is missing")
    kind = node.get("kind") or {}
    if kind.get("kind") != "text" or not (kind.get("content") or "").strip():
        return unavailable("source node has no native text")
    if kind["content"] != row.get("text"):
        return unavailable("native text row does not match its source")
    opacity = node.get("opacity", 1)
    if node.get("opacity_token") is not None or not finite_number(opacity) or opacity <= 0:
        return unavailable("source opacity is hidden or unresolved")
    if any(
        kind.get(key) is not None
        for key in ("style_token", "font_size_token", "line_height_token", "letter_spacing_token")
    ):
        return unavailable("unresolved source typography")
    font_size = kind.get("font_size")
    if not finite_number(font_size) or font_size <= 0:
        return unavailable("invalid resolved source font size")
    if not finite_number(row.get("font_size")) or row["font_size"] != font_size:
        return unavailable("native font size row does not match its source")
    nominal_em = font_size / size["width"] * display_width_px
    if not math.isfinite(nominal_em) or nominal_em <= 0:
        return unavailable("unrepresentable nominal em size")
    return {"status": "ok", "nominal_em_px": nominal_em, "reason": None}
