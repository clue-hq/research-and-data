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

Site documents (Puck, Wave 2): a target is a ``design_node`` ref whose object_id is
``site:<route>#<componentId>`` with an optional ``.<propName>``
(``site:/analysis#Hero-1a2b.title``), or ``site:shell#header`` / ``site:shell#footer``. It is
validated against the stored site at the pinned version: the route is a page, the component's
``props.id`` is on it, the prop is one of its props.

Which document a target belongs to: a message's ``design_node`` refs all point into its one
``design_document`` ref (the composer refuses anything else), so a turn addressing several
documents hands those targets ONLY to that document's run (:func:`refs_for_document`). Site and
scene targets name a page and a section or node, which documents built from one template share —
handing a note to every addressed document applied it to the wrong accounts (review finding S5-2).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; this module stays runtime-dependency-free
    from clue_agents import DomainObjectRef

__all__ = [
    "SITE_TARGET_PREFIX",
    "DesignTurnTargetError",
    "ResolvedSceneTargets",
    "ResolvedSiteTargets",
    "ResolvedWebTargets",
    "SiteTarget",
    "SiteTargetNote",
    "WebTargetNote",
    "refs_for_document",
    "resolve_scene_targets",
    "resolve_site_targets",
    "resolve_web_targets",
    "split_web_target",
    "validate_site_targets",
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


def refs_for_document(
    refs: Sequence[DomainObjectRef], document_id: str | None
) -> tuple[DomainObjectRef, ...]:
    """The message's refs as one addressed document should see them: its ``design_node`` targets
    only when it is the document the message named, every other ref (reference images, accounts,
    the named document itself) unchanged. Targets with no document named reach no document."""

    named = next((ref.object_id for ref in refs if ref.object_type == "design_document"), None)
    if named is not None and named == document_id:
        return tuple(refs)
    return tuple(ref for ref in refs if ref.object_type != "design_node")


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


SITE_TARGET_PREFIX = "site:"
_SITE_ROUTE = re.compile(r"^/(?:[a-z0-9][a-z0-9-]*)?$")
_SHELL_PARTS = ("header", "footer")


@dataclass(frozen=True, slots=True)
class SiteTarget:
    #: "/", "/<name>" or "shell".
    route: str
    #: The component's ``props.id``; "header" or "footer" for the shell.
    component_id: str
    prop: str | None


@dataclass(frozen=True, slots=True)
class SiteTargetNote:
    target: SiteTarget
    note: str | None


@dataclass(frozen=True, slots=True)
class ResolvedSiteTargets:
    targets: tuple[SiteTarget, ...]
    #: One entry per submitted ref, in submission order (annotations are numbered by the human).
    target_notes: tuple[SiteTargetNote, ...]


def _site_component_props(
    site: dict[str, Any], route: str, component_id: str
) -> dict[str, Any] | None:
    """The props of the component a target names, or None when the stored site has no such one."""
    if route == "shell":
        shell = site.get("shell")
        part = (
            shell.get(component_id)
            if isinstance(shell, dict) and component_id in _SHELL_PARTS
            else None
        )
        return part if isinstance(part, dict) else None
    pages = site.get("pages")
    page = pages.get(route) if isinstance(pages, dict) else None
    content = page.get("content") if isinstance(page, dict) else None
    for item in content if isinstance(content, list) else ():
        props = item.get("props") if isinstance(item, dict) else None
        if isinstance(props, dict) and props.get("id") == component_id:
            return props
    return None


def _site_target(site: dict[str, Any], object_id: str) -> SiteTarget:
    if not object_id.startswith(SITE_TARGET_PREFIX) or "#" not in object_id:
        raise DesignTurnTargetError(
            "CONTEXT_REF_RELATIONSHIP_MISMATCH",
            "a target on a site document is site:<route>#<component>[.<prop>]",
        )
    route, _, rest = object_id[len(SITE_TARGET_PREFIX) :].partition("#")
    if route != "shell" and not _SITE_ROUTE.fullmatch(route):
        raise DesignTurnTargetError(
            "CONTEXT_REF_NOT_FOUND", "a targeted site page is not a route of this site"
        )
    # The whole rest is a component id first (ids may contain dots); only then "<id>.<prop>".
    if _site_component_props(site, route, rest) is not None:
        return SiteTarget(route=route, component_id=rest, prop=None)
    component_id, dot, prop = rest.rpartition(".")
    props = _site_component_props(site, route, component_id) if dot else None
    if props is None or prop not in props:
        raise DesignTurnTargetError(
            "CONTEXT_REF_NOT_FOUND",
            "a targeted site component or field does not exist in the submitted site document",
        )
    return SiteTarget(route=route, component_id=component_id, prop=prop)


def validate_site_targets(
    site: dict[str, Any], target_ids: Sequence[str]
) -> tuple[SiteTarget, ...]:
    """Refuse site targets the stored site cannot support; return them parsed, in order."""
    ordered = tuple(target_ids)
    if not ordered:
        raise DesignTurnTargetError(
            "CONTEXT_REF_RELATIONSHIP_MISMATCH",
            "a focused design turn requires at least one design node",
        )
    if len(set(ordered)) != len(ordered):
        raise DesignTurnTargetError(
            "CONTEXT_REF_DUPLICATE", "the same design node may appear only once in a submission"
        )
    return tuple(_site_target(site, object_id) for object_id in ordered)


def resolve_site_targets(
    site: dict[str, Any], focus_refs: Sequence[DomainObjectRef]
) -> ResolvedSiteTargets | None:
    """The turn's ``design_node`` refs as site targets with their notes; None when there are
    none."""
    nodes = [ref for ref in focus_refs if ref.object_type == "design_node"]
    if not nodes:
        return None
    targets = validate_site_targets(site, [ref.object_id for ref in nodes])
    return ResolvedSiteTargets(
        targets=tuple(dict.fromkeys(targets)),
        target_notes=tuple(
            SiteTargetNote(target=target, note=ref.note)
            for target, ref in zip(targets, nodes, strict=True)
        ),
    )
