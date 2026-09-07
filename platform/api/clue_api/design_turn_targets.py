"""Pure target resolution for focused platform design turns.

Scene documents: the browser submits node ids, never a page id.  A page is derived from
the exact server-side scene so a stale or fabricated client page cannot broaden the edit.

Web documents: the browser submits a web node id, optionally suffixed with an inner
``#`` path (``frg_a#:nth-child(1) > :nth-child(2)``) naming one element INSIDE that node,
plus the human's own note about it.  A web target is validated against the stored web
document — an id nobody can point at, or a path that is not the closed ``:nth-child``
grammar, is refused at the HTTP boundary rather than handed to the design runtime.
Unlike a scene turn, web targets MAY span pages: the design API's TURN TARGET line names
each target's page itself.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; this module stays runtime-dependency-free
    from clue_agents import DomainObjectRef

__all__ = [
    "DesignTurnTargetError",
    "ResolvedSceneTargets",
    "ResolvedWebTargets",
    "WebTargetNote",
    "resolve_scene_targets",
    "resolve_web_targets",
    "split_web_target",
    "validate_web_targets",
]

#: The one closed grammar for a web target's inner path. The editor builds it from
#: ``:nth-child`` steps only, so nothing an annotation carries can widen into a selector.
_WEB_TARGET_PATH = re.compile(r"^(:nth-child\(\d+\)( > )?)+$")


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


@dataclass(frozen=True, slots=True)
class WebTargetNote:
    """One annotated web target: the owning node, the inner element, the human's words."""

    target: str
    path: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class ResolvedWebTargets:
    #: The owning node ids, deduplicated in first-seen order.
    target_node_ids: tuple[str, ...]
    #: One entry per submitted ref, in submission order — annotations are numbered by the
    #: human ("1.", "2.", …) and the order is part of what they said.
    target_notes: tuple[WebTargetNote, ...]


def split_web_target(object_id: str) -> tuple[str, str | None]:
    """Split ``node_id`` / ``node_id#path`` on the FIRST ``#``.

    The one split both the acceptance validator and the envelope builder use, so a target
    can never be validated one way and dispatched another.
    """

    node_id, _, path = object_id.partition("#")
    return node_id, path or None


def resolve_web_targets(
    focus_refs: Sequence[DomainObjectRef],
) -> ResolvedWebTargets | None:
    """Split the turn's ``design_node`` refs into owning node ids plus ordered notes.

    ``None`` when the turn carries no node targets at all — the caller then leaves the web
    request byte-for-byte as it shipped (plan F4), rather than sending empty keys.
    """

    notes: list[WebTargetNote] = []
    ids: list[str] = []
    for ref in focus_refs:
        if ref.object_type != "design_node":
            continue
        target, path = split_web_target(ref.object_id)
        notes.append(WebTargetNote(target=target, path=path, note=ref.note))
        if target not in ids:
            ids.append(target)
    if not notes:
        return None
    return ResolvedWebTargets(target_node_ids=tuple(ids), target_notes=tuple(notes))


def _web_node_ids(web_doc: dict[str, Any]) -> set[str]:
    """Every node id on every page of the web document.

    Targets may span pages here (the design API's TURN TARGET line names each page), so a
    web target only has to exist SOMEWHERE in the document.
    """

    pages = web_doc.get("pages")
    if isinstance(pages, dict):
        candidates: Sequence[Any] = tuple(pages.values())
    elif isinstance(pages, list):
        candidates = pages
    else:
        return set()
    node_ids: set[str] = set()
    for page in candidates:
        if not isinstance(page, dict):
            continue
        nodes = page.get("nodes")
        if not isinstance(nodes, dict):
            continue
        node_ids.update(node_id for node_id in nodes if isinstance(node_id, str))
    return node_ids


def validate_web_targets(web_doc: dict[str, Any], target_ids: Sequence[str]) -> None:
    """Refuse web node targets that the stored document cannot support.

    Raises :class:`DesignTurnTargetError`; returns ``None`` when every target is usable.
    """

    ordered = tuple(target_ids)
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
    known = _web_node_ids(web_doc)
    for object_id in ordered:
        node_id, path = split_web_target(object_id)
        if node_id not in known:
            raise DesignTurnTargetError(
                "CONTEXT_REF_NOT_FOUND",
                "a targeted design node does not exist in the submitted web document",
            )
        if path is not None and _WEB_TARGET_PATH.fullmatch(path) is None:
            raise DesignTurnTargetError(
                "CONTEXT_REF_NOT_FOUND",
                "a targeted design node carries an unusable inner element path",
            )


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
