"""Pure scene-target resolution for focused platform design turns.

The browser submits node ids, never a page id.  A page is derived from the exact
server-side scene so a stale or fabricated client page cannot broaden the edit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DesignTurnTargetError",
    "ResolvedSceneTargets",
    "resolve_scene_targets",
]


class DesignTurnTargetError(ValueError):
    """The submitted nodes cannot form one safe scene-scoped edit target."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ResolvedSceneTargets:
    target_node_ids: tuple[str, ...]
    active_page_id: str


def _node_children(nodes: dict[str, Any], node_id: str) -> tuple[str, ...]:
    node = nodes.get(node_id)
    if not isinstance(node, dict):
        return ()
    children = node.get("children")
    if not isinstance(children, list):
        return ()
    return tuple(str(child_id) for child_id in children if isinstance(child_id, str))


def _page_by_node(scene: dict[str, Any]) -> dict[str, str | None]:
    """Map every page-reachable node to its one page; ``None`` means ambiguous."""

    nodes = scene.get("nodes")
    pages = scene.get("pages")
    if not isinstance(nodes, dict) or not isinstance(pages, dict):
        return {}
    result: dict[str, str | None] = {}
    for page_key, page in pages.items():
        if not isinstance(page_key, str) or not isinstance(page, dict):
            continue
        page_id = page.get("id") if isinstance(page.get("id"), str) else page_key
        roots = page.get("children")
        if not isinstance(roots, list):
            continue
        stack = [str(node_id) for node_id in reversed(roots) if isinstance(node_id, str)]
        visited: set[str] = set()
        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            if node_id not in nodes:
                continue
            previous = result.get(node_id)
            if node_id in result and previous != page_id:
                result[node_id] = None
            else:
                result[node_id] = page_id
            stack.extend(reversed(_node_children(nodes, node_id)))
    return result


def resolve_scene_targets(
    scene: dict[str, Any],
    target_node_ids: Sequence[str],
) -> ResolvedSceneTargets:
    """Resolve an ordered node snapshot to the one page the runtime request needs."""

    ordered = tuple(target_node_ids)
    if not ordered:
        raise DesignTurnTargetError(
            "CONTEXT_REF_RELATIONSHIP_MISMATCH",
            "a focused design turn requires at least one design node",
        )
    if len(set(ordered)) != len(ordered):
        raise DesignTurnTargetError(
            "CONTEXT_REF_DUPLICATE",
            "the same design node may appear only once in a submission",
        )
    nodes = scene.get("nodes")
    if not isinstance(nodes, dict) or any(node_id not in nodes for node_id in ordered):
        raise DesignTurnTargetError(
            "CONTEXT_REF_NOT_FOUND",
            "a targeted design node does not exist in the submitted document scene",
        )
    page_by_node = _page_by_node(scene)
    page_ids = {page_by_node.get(node_id) for node_id in ordered}
    if None in page_ids:
        raise DesignTurnTargetError(
            "CONTEXT_REF_NOT_FOUND",
            "a targeted design node is not reachable from exactly one page in the scene",
        )
    if len(page_ids) != 1:
        raise DesignTurnTargetError(
            "CONTEXT_REF_RELATIONSHIP_MISMATCH",
            "all targeted design nodes must belong to the same page",
        )
    return ResolvedSceneTargets(
        target_node_ids=ordered,
        active_page_id=next(iter(page_ids)),  # type: ignore[arg-type]
    )
