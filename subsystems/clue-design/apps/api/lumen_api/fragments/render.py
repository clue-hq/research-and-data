"""Resolving a page's cloned sections for a render (clone-fidelity F1.3).

The engine render stays PURE: it never reads a registry, never opens a blob, never decides which
artifact a node means. It is handed a map of already-resolved artifacts and a sheet of
already-scoped CSS, and it emits them. This module is the other half of that seam — the API's
answer to "which artifacts does this page need, what are they, and what should worry us about
putting them on the same page as the compiled utilities".

The shape mirrors :mod:`lumen_api.custom_component_runtime`, which does exactly this job for
custom components: a Python walk finds the referenced ids, the API resolves each one out of
durable custody, and an id that will not resolve is REPORTED rather than guessed at — the engine
renders its placeholder, so a document with a dead pin still loads, still edits and still renders
the rest of the page.

**The package travels by value.** The editor render route builds it per request; a web agent turn
builds it once at composition and hands it to the runtime in its config, because the runtime is
fleet work that never reads the API database. Both paths thread the same two things into
``core.web_render`` — ``fragments`` and ``fragment_css`` — so a section cannot render in one
preview and vanish from the other.

**The cascade note.** ``fragment_css`` is spliced through the theme's base layer, which puts it in
the head BEFORE any compiled utility sheet. Fragment selectors are all scoped under
``.lumen-frag-<hex>``, so ordinarily nothing collides. The exception is a cloned class name that
the surrounding document ALSO authors as a utility: the compiled utility then wins the tie and the
cloned section loses that rule. That is a ledgered, accepted risk — :func:`fragment_collision_diagnostics`
names it in the render's diagnostics rather than refusing a render over it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from clue_storage import StorageBackend

from ..database import NotFoundError
from .refs import FRAGMENT_ID_RE, FragmentRefused, fragment_wrapper_class
from .registry import read_web_fragment
from .slots import SLOT_KINDS

#: Version of the by-value package shape, so a fleet worker running older code against a newer
#: API refuses to improvise rather than silently rendering half a page.
FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION = 1

#: Class names in a stylesheet: ``.foo``, ``.foo-bar``, ``.md\:flex``. Deliberately a scan, not a
#: parser — this feeds a DIAGNOSTIC, so a missed exotic selector costs a warning nobody sees, and
#: nothing about the render changes.
_CSS_CLASS_RE = re.compile(r"\.(-?[_a-zA-Z](?:[\w-]|\\.)*)")

def empty_fragment_render_package() -> dict[str, Any]:
    """A package that resolves nothing — the honest value for a page with no fragments."""
    return {
        "schema_version": FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION,
        "fragments": {},
        "missing": [],
    }


# --------------------------------------------------------------------------- #
# The walks
# --------------------------------------------------------------------------- #


def _page(web_doc: Any, page_id: str) -> dict[str, Any] | None:
    """The named page, else the first one — the fallback ``_custom_component_nodes`` uses, so both
    resolvers agree about which page a render means."""
    pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
    if not isinstance(pages, list):
        return None
    page = next(
        (item for item in pages if isinstance(item, dict) and item.get("id") == page_id),
        None,
    )
    if page is None:
        page = next((item for item in pages if isinstance(item, dict)), None)
    return page if isinstance(page, dict) else None


def _reachable_nodes(web_doc: Any, page_id: str) -> list[dict[str, Any]]:
    """Every node reachable from the page root, in document order, root first.

    Reachable-only on purpose: a node sitting in the map but off the tree is not on the page, so
    resolving its artifact would splice CSS for a section nobody can see.
    """
    page = _page(web_doc, page_id)
    if page is None:
        return []
    nodes = page.get("nodes")
    if not isinstance(nodes, dict):
        return []
    root = page.get("root") if isinstance(page.get("root"), str) else "root"
    pending = [root]
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    while pending:
        node_id = pending.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        found.append(node)
        children = node.get("children")
        if isinstance(children, list):
            pending = [child for child in children if isinstance(child, str)] + pending
    return found


def web_doc_fragment_ids(web_doc: Any, page_id: str) -> list[str]:
    """Every fragment artifact id this page references, in document order, once each.

    The Python analog of the engine's ``page_fragment_ids``. Both exist: the engine answers for
    itself, and the API — which is the thing that actually resolves artifacts — must not have to
    call into the engine to learn what to fetch before it can call the engine.
    """
    ids: list[str] = []
    for node in _reachable_nodes(web_doc, page_id):
        if node.get("kind") != "fragment":
            continue
        fragment_id = node.get("fragment_id")
        if isinstance(fragment_id, str) and fragment_id and fragment_id not in ids:
            ids.append(fragment_id)
    return ids


def web_doc_class_tokens(web_doc: Any, page_id: str) -> set[str]:
    """Every class token the DOCUMENT authors on this page.

    This is the utility vocabulary a compiled ``site.css`` is built from (and the vocabulary the
    editor's Tailwind runtime generates), so it is the live-utility side of the collision check.
    """
    tokens: set[str] = set()
    for node in _reachable_nodes(web_doc, page_id):
        classes = node.get("classes")
        if isinstance(classes, str):
            tokens.update(classes.split())
    return tokens


def css_class_names(css: str) -> set[str]:
    """Every class name a stylesheet declares. A scan (see ``_CSS_CLASS_RE``), not a parser."""
    return {match.group(1) for match in _CSS_CLASS_RE.finditer(css or "")}


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def build_fragment_render_package(
    storage: StorageBackend,
    *,
    workspace_id: str,
    web_doc: Any,
    page_id: str,
) -> dict[str, Any]:
    """Resolve every fragment this page references into one by-value package.

    Fail-SOFT, deliberately and unlike creation: an id this workspace cannot resolve — deleted,
    another tenant's, or a purged payload — lands in ``missing`` and the engine renders its
    placeholder. Refusing the whole render instead would make one dead pin cost the entire page,
    and the F1.2 gate exists precisely so a document with a dead pin stays usable.
    """
    package = empty_fragment_render_package()
    for fragment_id in web_doc_fragment_ids(web_doc, page_id):
        if not FRAGMENT_ID_RE.fullmatch(fragment_id):
            # Not an artifact address at all; there is nothing to look up. The
            # engine re-checks the same grammar and renders its placeholder.
            package["missing"].append(fragment_id)
            continue
        try:
            loaded = read_web_fragment(
                storage, workspace_id=workspace_id, fragment_id=fragment_id
            )
        except NotFoundError:
            package["missing"].append(fragment_id)
            continue
        package["fragments"][fragment_id] = {
            "html": loaded.html,
            "css": loaded.css,
            "slot_kinds": slot_kinds(loaded.slot_manifest),
        }
    return package


def slot_kinds(slot_manifest: Mapping[str, Any]) -> dict[str, str]:
    """``{slot key: kind}`` from an artifact's slot manifest — the half of the manifest the ENGINE
    needs (F1.4).

    The engine substitutes a node's slot values into the artifact's markers, and it cannot decide
    what a value MEANS without this: an href and a paragraph both ride the node's ``text`` tag
    (see :data:`lumen_api.fragments.slots.SLOT_KIND_TO_NODE_TAG`), so without the kind a link
    target could be written into a heading. The fallbacks stay behind — they are already in the
    markup, which is where the engine reads them from.

    Unknown kinds are dropped rather than passed on: the engine's enum is closed, and a value
    whose kind it cannot name falls back loudly instead of failing the whole render.
    """
    return {
        str(key): str(entry.get("kind"))
        for key, entry in (slot_manifest or {}).items()
        if isinstance(entry, Mapping) and str(entry.get("kind")) in SLOT_KINDS
    }


def fragment_render_map(
    package: Mapping[str, Any], fragment_ids: Sequence[str]
) -> dict[str, dict[str, str]]:
    """The engine's ``RenderOptions.fragments`` — markup plus each slot's kind.

    CSS is deliberately absent: it reaches the page through the head, once per fragment, not once
    per node that pins it. The slot kinds ride here rather than in the head because they are read
    per node, at the moment the node's own values are applied (F1.4).
    """
    fragments = package.get("fragments") if isinstance(package, Mapping) else None
    fragments = fragments if isinstance(fragments, Mapping) else {}
    return {
        fragment_id: {
            "html": str(fragments[fragment_id].get("html") or ""),
            "slot_kinds": dict(fragments[fragment_id].get("slot_kinds") or {}),
        }
        for fragment_id in _unique(fragment_ids)
        if isinstance(fragments.get(fragment_id), Mapping)
    }


def fragment_css_sheet(
    package: Mapping[str, Any], fragment_ids: Sequence[str]
) -> str | None:
    """The concatenated scoped CSS for these fragments, or ``None`` when there is none.

    Sorted by fragment id rather than laid out in document order: every rule is scoped, so the
    blocks cannot interact, which makes document order a source of byte churn (moving a section
    would rewrite the sheet) with no cascade meaning. Each block keeps a source comment naming its
    artifact, so a rule in a rendered head can be traced back to the fragment it came from.
    """
    fragments = package.get("fragments") if isinstance(package, Mapping) else None
    fragments = fragments if isinstance(fragments, Mapping) else {}
    blocks: list[str] = []
    for fragment_id in sorted(set(fragment_ids)):
        record = fragments.get(fragment_id)
        if not isinstance(record, Mapping):
            continue
        css = str(record.get("css") or "").strip()
        if not css:
            continue
        blocks.append(f"/* fragment {fragment_id} */\n{css}")
    return "\n".join(blocks) if blocks else None


# --------------------------------------------------------------------------- #
# The cascade diagnostic
# --------------------------------------------------------------------------- #


def fragment_class_collisions(
    package: Mapping[str, Any],
    fragment_ids: Sequence[str],
    live_classes: Iterable[str],
) -> list[tuple[str, list[str]]]:
    """``(fragment_id, colliding class names)`` for each fragment the utilities can overrule.

    A collision is a class the fragment's own CSS styles that the document ALSO authors as a
    utility class. The compiled utility lands after the fragment CSS, so it wins — the cloned
    section quietly loses that rule. The wrapper class is excluded: it is ours, it is on the
    wrapper by construction, and reporting it would fire on every fragment ever rendered.
    """
    fragments = package.get("fragments") if isinstance(package, Mapping) else None
    fragments = fragments if isinstance(fragments, Mapping) else {}
    live = {token for token in live_classes if token}
    collisions: list[tuple[str, list[str]]] = []
    for fragment_id in _unique(fragment_ids):
        record = fragments.get(fragment_id)
        if not isinstance(record, Mapping):
            continue
        declared = css_class_names(str(record.get("css") or ""))
        try:
            declared.discard(fragment_wrapper_class(fragment_id))
        except FragmentRefused:
            # A malformed id has no wrapper class to exclude — and no artifact
            # either, so this loop will not reach here in practice.
            pass
        shared = sorted(declared & live)
        if shared:
            collisions.append((fragment_id, shared))
    return collisions


def fragment_collision_diagnostics(
    package: Mapping[str, Any], web_doc: Any, page_id: str
) -> list[dict[str, Any]]:
    """The collision report, in the engine's diagnostic shape so it merges into one list.

    A warning, never a refusal (the ledgered ruling): the render is correct, one rule of one
    cloned section may not be. Naming it is what lets a producer rename the class instead of
    discovering the loss in a screenshot.
    """
    fragment_ids = web_doc_fragment_ids(web_doc, page_id)
    live = web_doc_class_tokens(web_doc, page_id)
    diagnostics: list[dict[str, Any]] = []
    for fragment_id, classes in fragment_class_collisions(package, fragment_ids, live):
        joined = ", ".join(f"`{name}`" for name in classes)
        diagnostics.append(
            {
                "severity": "warning",
                "phase": "web",
                "code": "fragment.class_collision",
                "message": (
                    f"fragment `{fragment_id}` styles {joined}, which the page also authors as "
                    "utility class(es). Compiled utilities are applied after fragment CSS, so "
                    "the utility wins and the cloned section loses those rules."
                ),
                "subject": None,
                "hint": (
                    "Rename the colliding class on the document's own nodes, or accept the "
                    "utility's value for that property."
                ),
            }
        )
    return diagnostics


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


__all__ = [
    "FRAGMENT_RENDER_PACKAGE_SCHEMA_VERSION",
    "build_fragment_render_package",
    "css_class_names",
    "empty_fragment_render_package",
    "fragment_class_collisions",
    "fragment_collision_diagnostics",
    "fragment_css_sheet",
    "fragment_render_map",
    "slot_kinds",
    "web_doc_class_tokens",
    "web_doc_fragment_ids",
]
