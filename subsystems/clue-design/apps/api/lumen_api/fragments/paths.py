"""Resolving an annotation's structural path against a clone's stored HTML (spec §3.1).

Everything inside a cloned band is the harvested artifact's own markup and carries no node
id of its own, so the one way to name an element in there is by POSITION. The editor bridge
builds that address (``web_bridge.py``'s ``elementPath``) as a chain of ``:nth-child(n)``
steps, 1-based, element children only, measured from the element the engine stamps
``data-fragment-root`` on. This module is the server-side mirror of that walk, run against
the artifact's stored HTML so a note about "this headline" can reach the agent naming the
element and quoting the words it actually reads today.

**The origin is the clone WRAPPER, which is why the walk starts at ``body``.** The engine
renders a fragment node as ``<div class="lumen-fragment …" data-node-id=… data-fragment-root>``
followed by the artifact's stored HTML verbatim (``render.rs``, the ``WebNodeKind::Fragment``
arm), so the wrapper's element children are exactly the stored HTML's top-level elements —
which is exactly what parsing that HTML puts under ``body``. A path's first step therefore
names a top-level element of the artifact, and the two walks agree step for step.

**A path that does not resolve is ``None``, never a near miss.** The markup an annotation was
made against can legitimately have moved on — a later turn rewrote the band — and the honest
answer is to tell the agent the path is dead and let it use its judgment. Guessing at "the
nearest heading" would put words in the marketer's mouth.

**The browser measured the path against the RENDERED clone, not the stored artifact.** Between
the two sits the slot pass: a slot bound ``{"visible": false}`` DROPS its whole element from the
render (``fragment.rs``), so counted naively over the stored HTML the same address lands one
element early per hidden sibling before the target — a note about the headline resolving to the
badge nobody can see. ``hidden_slot_keys`` is how a caller that holds the node reconciles the two
walks: those elements are skipped, and not descended into, exactly the way the render drops them.
"""

from __future__ import annotations

import re
from typing import Any, Collection

from selectolax.lexbor import LexborHTMLParser

__all__ = ["PATH_RE", "resolve_structural_path"]

#: The one closed grammar for an inner-element path, character for character the platform's
#: acceptance gate (``clue_api.design_turn_targets._WEB_TARGET_PATH``), this API's request
#: model (``lumen_api.models.WebTurnTargetNote.path``) and the bridge's own producer. The
#: seam forbids sharing a module across those, so change one and change all three. Nothing
#: here may widen into a selector: only ``:nth-child(n)`` steps joined by `` > ``.
PATH_RE = re.compile(r"^(:nth-child\(\d+\)( > )?)+$")

_STEP_RE = re.compile(r":nth-child\((\d+)\)")

#: Markup the parser reports as a "tag" but which is not an element: text and comment nodes.
#: The bridge counts ``firstElementChild``/``nextElementSibling``, so these must not count here.
_NON_ELEMENT_TAGS = frozenset({"-text", "-comment", "-undef", "_text", "_comment"})


def resolve_structural_path(
    html: str, path: str | None, hidden_slot_keys: Collection[str] = ()
) -> dict[str, Any] | None:
    """Walk ``path`` through ``html`` and describe what it lands on.

    Returns ``{"tag": …, "text": …, "slot": …}`` — the element's tag name, its whitespace-
    collapsed visible text (inline markup flattened, the way a human reads it), and its
    ``data-lumen-slot`` key when it carries one — or ``None`` when the path is malformed,
    steps outside the closed grammar, or names a child the markup does not have.

    ``hidden_slot_keys`` are the node's slot keys bound ``{"visible": false}``. An element
    carrying one of them is not on the rendered page at all, so it is neither counted as a
    sibling nor enterable as a parent — the second half is what stops an address from landing
    INSIDE something invisible. Empty (the default) walks the stored artifact as-is, which is
    correct for an unpersonalized clone.
    """

    if not path or not PATH_RE.match(path):
        return None
    try:
        tree = LexborHTMLParser(html or "")
    except Exception:
        # A stored artifact is sanitized at creation, so an unparseable one is not expected;
        # if it ever happens the annotation degrades to "no longer resolves" rather than
        # taking the whole prompt build down with it.
        return None
    current = resolve_structural_node(tree.body, path, hidden_slot_keys)
    if current is None:
        return None
    slot = current.attributes.get("data-lumen-slot")
    return {
        "tag": current.tag,
        "text": " ".join((current.text(deep=True, separator=" ") or "").split()),
        "slot": slot if isinstance(slot, str) and slot else None,
    }


def structural_children(node: Any, hidden_slot_keys: Collection[str] = ()) -> list:
    """Element-only children shared by the inspector and structural path resolver."""
    return [child for child in node.iter(include_text=False)
            if child.tag not in _NON_ELEMENT_TAGS
            and child.attributes.get("data-lumen-slot") not in hidden_slot_keys]


def resolve_structural_node(body: Any, path: str | None, hidden_slot_keys: Collection[str] = ()) -> Any:
    """Resolve against an existing parser tree, without guessing or mutating it."""
    if not path or not PATH_RE.fullmatch(path):
        return None
    current = body
    if current is None:
        return None
    hidden = frozenset(hidden_slot_keys)
    for step in _STEP_RE.findall(path):
        index = int(step)
        children = structural_children(current, hidden)
        if index < 1 or index > len(children):
            return None
        current = children[index - 1]
    return current
