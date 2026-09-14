"""Read-only, untruncated native text observation over the resolved scene.

Shared by the display table and candidate copy binding. This is not a second
renderer: instances/transforms are explicit limits, and clipping, occlusion,
off-canvas placement and raster-contained text remain visual review concerns.
"""

import math


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


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
    pending = [(node_id, False, None, None) for node_id in reversed(page.get("children") or [])]
    while pending:
        node_id, ancestor_hidden, ancestor_issue, binding_issue = pending.pop()
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
            ancestor_hidden, ancestor_issue, binding_issue = False, None, None
        opacity = node.get("opacity", 1)
        issue = ancestor_issue
        opacity_resolved = node.get("opacity_token") is None and finite_number(opacity)
        if not opacity_resolved:
            issue = binding_issue = "unresolved opacity"
        node_hidden = ancestor_hidden or (opacity_resolved and opacity <= 0)
        transform = node.get("transform") or {}
        if any(transform.get(key, 0) != 0 for key in ("rotation", "skew_x", "skew_y")):
            issue = "unsupported transform"
        kind = node.get("kind") or {}
        if kind.get("kind") == "instance" and not node_hidden:
            result["unresolved"].append(
                {**identity, "reason": "instance text expansion is unsupported"}
            )
        if kind.get("kind") in ("frame", "group", "auto_layout"):
            pending.extend(
                (child, node_hidden, issue, binding_issue)
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
        result["occurrences"].append(
            {
                **row,
                "font_size": font_size,
                "observation_issue": issue,
                "binding_issue": binding_issue,
            }
        )
    return result
