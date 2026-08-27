"""Slot markers: the spots in a cloned section that a document may re-fill (F1.2).

A verbatim clone is worth little if nothing in it can be changed. The annotator stamps
``data-lumen-slot="<key>"`` onto chosen elements of already-sanitized markup and emits the
matching ``slot_manifest`` entry, which is the contract between the artifact (what CAN be
replaced, and what it says by default) and the document node (what this instance replaced it
with — flat scalars, ≤64 of them, per ``WebNodeKind::Fragment``).

**Keys obey the ENGINE's grammar, not a looser one of our own**: non-empty, at most 64
characters, every character in ``[a-z0-9_-]``. Task 5's fix round narrowed that deliberately —
the key is interpolated into markup and selectors downstream — and the engine refuses anything
else at both its write paths. A key minted here that the engine would refuse is a stored trap
that only detonates when somebody tries to bind it, so the same predicate is enforced at
minting time.

**Manifest kinds map onto the engine's tagged slot values**: ``text`` → ``{"text": …}``,
``image`` → ``{"asset": …}``, ``href`` → ``{"text": …}`` (an href IS a string; the manifest kind
is what tells F1.4 to treat it as a link target rather than as copy), ``visibility`` →
``{"visible": …}``.

**One asymmetry, recorded rather than enforced**: a node's text/asset slot value is capped at
8 KB by the engine, but the manifest's ``fallback`` lives in the ARTIFACT, which has no such
bound — a section's default paragraph may legitimately be longer than any override could be. So
an oversized fallback is legal and is kept verbatim; it is merely reported, because a marker
whose default could never be re-expressed as a node value is a trap worth naming at creation.

F2 does the automatic detection of where the slots should go. Here the annotator takes explicit
specs and is exercised by tests, which is what keeps this module a primitive rather than a
policy.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .refs import FragmentRefused, asset_url_digest

#: ``lumen_web::doc::MAX_FRAGMENT_SLOTS`` — the node cannot hold more than this.
MAX_FRAGMENT_SLOTS = 64
#: ``lumen_web::doc::MAX_FRAGMENT_SLOT_KEY_CHARS``.
MAX_SLOT_KEY_CHARS = 64
#: ``lumen_web::doc::MAX_FRAGMENT_SLOT_VALUE_BYTES`` — a NODE bound, not an artifact one.
MAX_NODE_SLOT_VALUE_BYTES = 8192

#: ``lumen_web::doc::fragment_slot_key_is_valid``.
SLOT_KEY_RE = re.compile(r"[a-z0-9_-]{1,%d}" % MAX_SLOT_KEY_CHARS)

SLOT_MARKER_ATTR = "data-lumen-slot"

SLOT_KINDS = ("text", "image", "href", "visibility")

#: How a manifest kind becomes an engine slot-value tag (``lumen_web::doc::FragmentSlotValue``,
#: which is serde-TAGGED: ``{"text": …}`` / ``{"asset": …}`` / ``{"visible": …}``). Note that
#: ``href`` and ``text`` share a tag — an href IS a string to the node — so the manifest kind is
#: the ONLY place that remembers a slot is a link target rather than copy. Stated here as data so
#: F1.4's binding reads the mapping instead of re-deriving it.
SLOT_KIND_TO_NODE_TAG = {
    "text": "text",
    "image": "asset",
    "href": "text",
    "visibility": "visible",
}


@dataclass(frozen=True)
class SlotSpec:
    """One editable spot: where it is, what it is called, and what kind of thing it holds."""

    selector: str
    key: str
    kind: str


@dataclass(frozen=True)
class AnnotatedHtml:
    html: str
    slot_manifest: dict[str, dict[str, Any]]
    notes: tuple[str, ...]


def slot_key_is_valid(key: str) -> bool:
    """The engine's predicate, mirrored. Kept a named function so the mirror is greppable."""
    return bool(SLOT_KEY_RE.fullmatch(key))


def annotate_fragment_slots(
    html: str, specs: Sequence[SlotSpec]
) -> AnnotatedHtml:
    """Mark the fragment's editable spots and describe them. Refuses rather than half-marking."""
    if len(specs) > MAX_FRAGMENT_SLOTS:
        raise FragmentRefused(
            "fragment.slot_limit",
            f"a fragment may declare at most {MAX_FRAGMENT_SLOTS} slots, got {len(specs)}",
        )

    tree = LexborHTMLParser(html)
    body = tree.body
    if body is None:
        if specs:
            raise FragmentRefused(
                "fragment.slot_selector_unmatched", "fragment markup is empty, so nothing matches"
            )
        return AnnotatedHtml(html="", slot_manifest={}, notes=())

    manifest: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    for spec in specs:
        if spec.kind not in SLOT_KINDS:
            raise FragmentRefused(
                "fragment.slot_kind_invalid",
                f"slot {spec.key!r} has unknown kind {spec.kind!r}; "
                f"expected one of {', '.join(SLOT_KINDS)}",
                reference=spec.key,
            )
        if not slot_key_is_valid(spec.key):
            raise FragmentRefused(
                "fragment.slot_key_invalid",
                f"slot key must be 1-{MAX_SLOT_KEY_CHARS} characters of [a-z0-9_-]: {spec.key!r}",
                reference=spec.key,
            )
        if spec.key in manifest:
            raise FragmentRefused(
                "fragment.slot_key_duplicate",
                f"slot key {spec.key!r} is declared twice",
                reference=spec.key,
            )
        node = _match(body, spec)
        if node.attributes.get(SLOT_MARKER_ATTR):
            raise FragmentRefused(
                "fragment.slot_element_taken",
                f"slot {spec.key!r} targets an element already marked as "
                f"{node.attributes[SLOT_MARKER_ATTR]!r}; one element holds one slot",
                reference=spec.key,
            )
        fallback = _fallback(node, spec)
        node.attrs[SLOT_MARKER_ATTR] = spec.key
        manifest[spec.key] = {"kind": spec.kind, "fallback": fallback}
        _note_oversize(spec, fallback, notes)

    rendered = "".join(child.html or "" for child in body.iter(include_text=True))
    return AnnotatedHtml(html=rendered, slot_manifest=manifest, notes=tuple(notes))


def _match(body: LexborNode, spec: SlotSpec) -> LexborNode:
    try:
        node = body.css_first(spec.selector)
    except Exception as error:  # selectolax raises its own parse error type
        raise FragmentRefused(
            "fragment.slot_selector_invalid",
            f"slot {spec.key!r} has an unparseable selector {spec.selector!r}: {error}",
            reference=spec.selector,
        ) from error
    if node is None:
        raise FragmentRefused(
            "fragment.slot_selector_unmatched",
            f"slot {spec.key!r} selector {spec.selector!r} matches nothing in the fragment",
            reference=spec.selector,
        )
    return node


def _fallback(node: LexborNode, spec: SlotSpec) -> Any:
    """What this slot says when nothing overrides it — the section's own content."""
    if spec.kind == "visibility":
        # The section shipped the element, so the default is "shown".
        return True
    if spec.kind == "text":
        return node.text(deep=True)
    if spec.kind == "href":
        href = node.attributes.get("href")
        if not href:
            raise FragmentRefused(
                "fragment.slot_fallback_missing",
                f"href slot {spec.key!r} targets an element with no href",
                reference=spec.key,
            )
        return href
    digest = asset_url_digest(node.attributes.get("src") or "")
    if digest is None:
        raise FragmentRefused(
            "fragment.slot_fallback_missing",
            f"image slot {spec.key!r} targets an element with no rehosted src",
            reference=spec.key,
        )
    return digest


def _note_oversize(spec: SlotSpec, fallback: Any, notes: list[str]) -> None:
    if not isinstance(fallback, str):
        return
    size = len(fallback.encode("utf-8"))
    if size > MAX_NODE_SLOT_VALUE_BYTES:
        notes.append(
            f"slot {spec.key!r} fallback is {size} bytes; a document node's slot value is "
            f"capped at {MAX_NODE_SLOT_VALUE_BYTES}, so this default can be shown but never "
            "re-expressed as an override"
        )
