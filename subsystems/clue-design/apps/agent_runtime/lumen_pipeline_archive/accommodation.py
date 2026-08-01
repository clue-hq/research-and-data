"""Accommodation-edits conflict detector (agent-quality track, 2026-07-05).

Detects when an edited node's new placement creates a spacing/overlap
conflict with a neighbor that did NOT exist at the turn's baseline — i.e.
the conflict is TURN-INTRODUCED, not pre-existing crowding the human already
baked into the frozen layout. See the design note for the full rationale:

    .context/agent-improvement/2026-07-05-accommodation-edits.md

Key insight from calibration (measured on run_e0bb1733's final scene, the
user-confirmed "too close" case): absolute clearance cannot be the signal,
because the design's own frozen layout contains deliberate 0pt adjacencies
(subtitle -> details, label -> value). The signal is TURN-INTRODUCED-ness: a
pair that cleared the threshold at baseline but no longer does at current is
a conflict; a pair that was already tight at baseline is left alone as
advisory (pre-existing, untouchable).

Scenes are plain dicts, the same JSON shape as `.lumen-runs/*/final_scene.json`:
``scene["nodes"]`` maps node id -> node dict, ``scene["pages"]`` maps page id
-> page dict with a ``"children"`` list of top-level node ids, and each node's
``"children"`` is a list of child node ids. This module is pure functions —
no I/O, no mutation of the scenes it is given.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set

# Smallest deliberate inter-element gap observed in real frozen output was
# 15pt (eyebrow -> hero). Sub-component pairs (subtitle -> details, label ->
# value) run 0-7pt but are BASELINE pairs, not turn-introduced, so they never
# hit this threshold check in the first place. 16pt sits just above the
# smallest deliberate gap so it never flags a pre-existing, intentional
# adjacency as new.
CONFLICT_CLEARANCE_THRESHOLD = 16.0


def page_space_box(node: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Return a node's page-space box, or None if it has no resolved geometry.

    Prefers ``node["absolute_box"]`` (human-pinned, already page-space).
    Falls back to ``node["computed"]["layout_bounds"]`` (engine-resolved,
    also page-space). Returns None if neither is present.
    """
    box = node.get("absolute_box")
    if isinstance(box, dict):
        return box
    computed = node.get("computed")
    if isinstance(computed, dict):
        bounds = computed.get("layout_bounds")
        if isinstance(bounds, dict):
            return bounds
    return None


def clearance(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Separation between two page-space boxes ``a`` and ``b``.

    Per-axis gaps ``gx``/``gy`` are the empty space between the boxes on
    that axis (negative means the boxes overlap on that axis):

        gx = max(a.x, b.x) - min(a.x + a.width, b.x + b.width)
        gy = max(a.y, b.y) - min(a.y + a.height, b.y + b.height)

    - If both gaps are positive, the boxes are diagonally separated and the
      clearance is the euclidean distance ``hypot(gx, gy)``.
    - If exactly one gap is positive, the boxes overlap on the other axis
      (e.g. share a column) and the clearance is that single positive gap.
    - If both gaps are negative, the boxes truly overlap in both dimensions;
      the clearance is ``max(gx, gy)`` — the less-negative (shallower)
      penetration — which is itself negative, signalling overlap.
    """
    ax0, ay0 = a["x"], a["y"]
    ax1, ay1 = ax0 + a["width"], ay0 + a["height"]
    bx0, by0 = b["x"], b["y"]
    bx1, by1 = bx0 + b["width"], by0 + b["height"]

    gx = max(ax0, bx0) - min(ax1, bx1)
    gy = max(ay0, by0) - min(ay1, by1)

    if gx > 0 and gy > 0:
        return math.hypot(gx, gy)
    if gx > 0:
        return gx
    if gy > 0:
        return gy
    return max(gx, gy)


def _page_children_map(scene: Dict[str, Any]) -> Dict[str, str]:
    """Map every node id reachable from a page's top-level children to that
    page id, by walking each node's `children` list transitively. This gives
    us "which page is this node on" and, incidentally, every node's full
    descendant set per page root."""
    nodes = scene.get("nodes") or {}
    pages = scene.get("pages") or {}
    node_page: Dict[str, str] = {}
    for page_id, page in pages.items():
        roots = page.get("children") or []
        stack: List[str] = list(roots)
        while stack:
            nid = stack.pop()
            if nid in node_page:
                continue
            node_page[nid] = page_id
            node = nodes.get(nid)
            if not isinstance(node, dict):
                continue
            stack.extend(node.get("children") or [])
    return node_page


def _parent_map(scene: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Map every node id to its parent node id (None for page-root nodes)."""
    nodes = scene.get("nodes") or {}
    pages = scene.get("pages") or {}
    parent: Dict[str, Optional[str]] = {}
    for page in pages.values():
        for root_id in page.get("children") or []:
            parent.setdefault(root_id, None)
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            continue
        for child_id in node.get("children") or []:
            parent[child_id] = nid
    return parent


def _ancestor_chain(node_id: str, parent: Dict[str, Optional[str]]) -> List[str]:
    """Ancestor ids from immediate parent up to (and including) the page root,
    in bottom-up order. Guards against cycles/missing entries defensively."""
    chain: List[str] = []
    seen: Set[str] = set()
    current = parent.get(node_id)
    while current is not None and current not in seen:
        chain.append(current)
        seen.add(current)
        current = parent.get(current)
    return chain


def turn_introduced_conflicts(
    baseline_scene: Dict[str, Any],
    current_scene: Dict[str, Any],
    edited_node_ids: Set[str],
    *,
    threshold: float = CONFLICT_CLEARANCE_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Find spacing/overlap conflicts that this turn's edits introduced.

    For each edited node E present in `current_scene` with a resolved box,
    on its page, every other node N on the SAME page with a resolved box is
    considered, skipping:
      - E's own ancestors (containment is not conflict — E is INSIDE them),
      - E's own descendants (same reason, inverted),
      - other edited node ids (an edit to both is the author's own
        coordination, not something for the detector to referee),
      - N whose `visible` is explicitly False.

    A pair (E, N) is a TURN-INTRODUCED conflict iff:
        clearance(E, N) in current_scene < threshold
        AND clearance(E, N) in baseline_scene >= threshold

    Pairs missing from the baseline entirely (E or N absent there, or either
    boxless there) count as NOT previously conflicting — i.e. eligible to be
    flagged now. This is deliberately permissive: no baseline data means no
    evidence of a pre-existing conflict to protect.

    Before reporting, N is rolled up: walk N's ancestor chain upward
    (stopping below the page root/artboard, and never crossing into E's own
    ancestor chain) and report the TOPMOST ancestor whose box also clears
    below `threshold` against E. That container is the correct nudge unit —
    nudging a deeply nested leaf (e.g. a glyph inside a lockup) in isolation
    would break the composite visual unit it belongs to.

    Returns entries shaped:
        {"edited": E, "neighbor": rolled_up_N, "clearance": float,
         "baseline_clearance": float | None, "overlap": bool}
    sorted by clearance ascending. Deduped to one entry per
    (edited, rolled-up neighbor) pair.
    """
    nodes = current_scene.get("nodes") or {}
    baseline_nodes = baseline_scene.get("nodes") or {}
    node_page = _page_children_map(current_scene)
    parent = _parent_map(current_scene)

    # Page root ids (artboards) — roll-up must stop at/below these, never
    # promote past the page root itself.
    page_roots: Set[str] = set()
    for page in (current_scene.get("pages") or {}).values():
        page_roots.update(page.get("children") or [])

    results: Dict[tuple, Dict[str, Any]] = {}

    for edited_id in edited_node_ids:
        edited_node = nodes.get(edited_id)
        if not isinstance(edited_node, dict):
            continue
        edited_box = page_space_box(edited_node)
        if edited_box is None:
            continue
        page_id = node_page.get(edited_id)
        if page_id is None:
            continue

        edited_ancestors = set(_ancestor_chain(edited_id, parent))
        edited_descendants = _descendant_ids(edited_id, nodes)

        for other_id, other_node in nodes.items():
            if other_id == edited_id:
                continue
            if node_page.get(other_id) != page_id:
                continue
            if other_id in edited_ancestors or other_id in edited_descendants:
                continue
            if other_id in edited_node_ids:
                continue
            if not isinstance(other_node, dict):
                continue
            if other_node.get("visible") is False:
                continue
            other_box = page_space_box(other_node)
            if other_box is None:
                continue

            current_clearance = clearance(edited_box, other_box)
            if current_clearance >= threshold:
                continue

            baseline_clearance = _baseline_clearance(
                baseline_nodes, edited_id, other_id
            )
            was_conflicting = (
                baseline_clearance is not None and baseline_clearance < threshold
            )
            if was_conflicting:
                continue

            rolled_id, rolled_box = _roll_up(
                other_id,
                other_box,
                edited_box,
                parent,
                edited_ancestors,
                page_roots,
                nodes,
                threshold,
                edited_node_ids,
            )
            rolled_clearance = clearance(edited_box, rolled_box)
            rolled_baseline_clearance = _baseline_clearance(
                baseline_nodes, edited_id, rolled_id
            )

            key = (edited_id, rolled_id)
            entry = {
                "edited": edited_id,
                "neighbor": rolled_id,
                "clearance": rolled_clearance,
                "baseline_clearance": rolled_baseline_clearance,
                "overlap": rolled_clearance < 0,
            }
            existing = results.get(key)
            if existing is None or rolled_clearance < existing["clearance"]:
                results[key] = entry

    return sorted(results.values(), key=lambda e: e["clearance"])


def _descendant_ids(node_id: str, nodes: Dict[str, Any]) -> Set[str]:
    descendants: Set[str] = set()
    stack = list((nodes.get(node_id) or {}).get("children") or [])
    while stack:
        nid = stack.pop()
        if nid in descendants:
            continue
        descendants.add(nid)
        node = nodes.get(nid)
        if isinstance(node, dict):
            stack.extend(node.get("children") or [])
    return descendants


def _baseline_clearance(
    baseline_nodes: Dict[str, Any], edited_id: str, other_id: str
) -> Optional[float]:
    """Clearance between `edited_id` and `other_id` in the baseline scene, or
    None if either node is absent or boxless there (treated by the caller as
    "not previously conflicting")."""
    edited_baseline = baseline_nodes.get(edited_id)
    other_baseline = baseline_nodes.get(other_id)
    if not isinstance(edited_baseline, dict) or not isinstance(other_baseline, dict):
        return None
    edited_box = page_space_box(edited_baseline)
    other_box = page_space_box(other_baseline)
    if edited_box is None or other_box is None:
        return None
    return clearance(edited_box, other_box)


def _roll_up(
    node_id: str,
    node_box: Dict[str, float],
    edited_box: Dict[str, float],
    parent: Dict[str, Optional[str]],
    edited_ancestors: Set[str],
    page_roots: Set[str],
    nodes: Dict[str, Any],
    threshold: float,
    edited_node_ids: Set[str],
) -> tuple:
    """Walk `node_id`'s ancestor chain upward, returning the (id, box) of the
    TOPMOST ancestor whose box still clears < threshold against `edited_box`.
    Stops before entering a page root/artboard, never crosses into the
    edited node's own ancestor chain (which would make it an ancestor of the
    edited node too — containment, not conflict), and never promotes INTO
    another edited node — an ancestor that was itself edited this turn is
    the author's own coordination, same as a direct edited-edited pair."""
    best_id, best_box = node_id, node_box
    current_id = parent.get(node_id)
    while current_id is not None:
        if current_id in edited_ancestors:
            break
        if current_id in edited_node_ids:
            break
        current_node = nodes.get(current_id)
        if not isinstance(current_node, dict):
            break
        current_box = page_space_box(current_node)
        if current_box is not None:
            if clearance(edited_box, current_box) < threshold:
                best_id, best_box = current_id, current_box
            else:
                # This ancestor no longer conflicts; nothing further up will
                # either shrink back below threshold in a meaningful way for
                # our purposes, so stop climbing once we hit a non-clearing
                # ancestor above a clearing one is impossible geometrically
                # in practice, but we still stop at the first non-conflict.
                pass
        if current_id in page_roots:
            break
        current_id = parent.get(current_id)
    return best_id, best_box
