"""The one-time fragment sanitizer (clone-fidelity F1.2, ruling D-F4).

**Sanitization happens exactly once, at artifact creation.** Everything downstream — the F1.3
render arm, the F1.4 derive path, the F1.5 export/publish package — may trust stored artifact
HTML absolutely, because no write path can put markup into a fragment except this one. That is
the same guarantee shape the engine uses on its own write path (``lumen-web``'s
``canonicalize_incoming_kind`` in ``ops.rs``: an operation's payload is canonicalized once, on
the way in, so every reader downstream is reading canonical data by construction), and the same
philosophy as ``inline.rs``'s rich-text allowlist — decide what may exist at the door.

It differs from ``inline.rs`` in exactly one way, and the difference is deliberate. Inline
sanitization NEVER fails: a disallowed span is unwrapped, and unparseable input becomes escaped
plain text, because a user typing into a text field must never be told "no". A fragment is not
user typing — it is a claim that we hold a faithful, self-contained copy of somebody's section —
so a reference we cannot honour REFUSES the fragment (``fragment.unrehosted_reference``) rather
than producing an artifact that renders a hole. Everything that is merely *unwanted* rather than
*unrepresentable* is still stripped and reported, exactly as ``inline.rs`` does.

The ruling, construct by construct:

* ``<script>`` — dropped with its content. Refusing instead would make cloning any real page
  impossible; scripts are on every one of them, and a clone does not want the behaviour.
* ``on*`` attributes — dropped. ALL of them, by prefix, not by a list of the ones we thought of.
* ``<iframe> <object> <embed> <form>`` — dropped with their subtrees. A form in a clone posts a
  visitor's data to somebody else's endpoint; the others are arbitrary third-party execution.
* ``<meta> <base> <link>`` — dropped. Document-level elements have no meaning in a section, and
  ``<base>`` silently re-points every relative URL in the page it lands in.
* ``<style>`` — dropped, with its rules going nowhere. Not in the ruled list, and it is the hole
  that would swallow the CSS scoper: an inline ``<style>`` block is unscoped global CSS smuggled
  in through the markup door. Its rules belong in the artifact's ``css``, which IS scoped.
* ``<noscript>`` — dropped. Its content is markup for a world we do not render into, and it
  would otherwise carry un-rehosted references past the reference gate.
* ``javascript:``/``data:`` (and any other non-allowlisted scheme) in a link — the ATTRIBUTE is
  dropped and the element stays. The visible text is section content; only the target is unsafe.
* ``src``/``srcset``/``poster``, SVG ``<use href>``, and every ``url()`` in an inline ``style`` —
  must resolve to a rehosted digest (see :mod:`lumen_api.fragments.refs`) and are rewritten to
  ``/asset-store/{digest}``. Fail-closed.
* Inline SVG is PRESERVED — it is the section's artwork, and dropping it would gut most modern
  hero sections — with ``<script>``, ``<foreignObject>`` and the SMIL animation elements removed
  and handlers stripped like anywhere else.
* ``data-lumen-*`` attributes present in the SOURCE are stripped. Only the annotator mints those,
  and it runs after this pass.

Three of those rulings came out of the first review round, and each names a way something got
PAST an attribute-time gate rather than through it — worth stating, because the pattern is what
generalises:

* **SMIL** (``<set attributeName="href" to="javascript:…">``) does not carry a dangerous value
  when we look at it; it rewrites another element's attribute later, at run time.
* **``<template>``** content lives in a separate document fragment, so it is not on the element
  walk at all — yet it is serialized on the way out, which made it a hole with no visible edge.
* **A source-planted ``data-lumen-slot``** is not dangerous by itself; it becomes dangerous when
  F1.4 later treats it as a marker we minted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .cssscope import rewrite_declaration_urls
from .reference_identity import indexed_references
from .refs import FragmentRefused, asset_reference_url, link_scheme_allowed, resolve_asset_reference

#: Elements removed with everything inside them. See the module docstring for the reasoning on
#: each; `foreignobject` is the SVG escape hatch back into arbitrary HTML (and, historically,
#: into script), so it goes with the rest.
DROPPED_ELEMENTS = frozenset(
    {
        "script",
        "iframe",
        "object",
        "embed",
        "form",
        "meta",
        "base",
        "link",
        "style",
        "noscript",
        "foreignobject",
        "frame",
        "frameset",
        "applet",
        "portal",
        # SMIL. These do not carry a dangerous value at parse time — they REWRITE another
        # element's attribute at run time (`<set attributeName="href" to="javascript:…">`,
        # `<animate … values="javascript:…">`), which walks straight past an attribute-time
        # href gate. Dropping the elements outright is the only posture that is sound without
        # re-implementing SMIL's semantics to decide which rewrites are safe; the cost is that
        # a cloned section loses declarative SVG animation, which is rare and cosmetic.
        "animate",
        "set",
        "animatetransform",
        "animatemotion",
        "animatecolor",
        # SVG2 `<discard>` cannot retarget an href — it deletes its target at a time offset — so
        # it is not the same hazard. It is the same FAMILY, though, and a cloned section that
        # deletes parts of itself on a timer is not something we want stored either. Dropping it
        # costs nothing.
        "discard",
        # `<template>`'s content lives in a SEPARATE document fragment: it is not part of the
        # element walk below, but it IS serialized on the way out. Left alone, a template round-
        # tripped unchanged — stored script text and un-rehosted remote references sailing past
        # a gate that is meant to be fail-closed. Dropping it is sound and cheap; a cloned
        # section that needs inert markup it never instantiates is not a case worth the risk of
        # descending into a second tree.
        "template",
    }
)

#: Attribute prefix reserved for markers WE mint. A cloned page may already carry a
#: ``data-lumen-slot``; if it survived, a source-chosen key could collide with an
#: annotator-minted one, and F1.4's substitution would then write tenant content into markup the
#: source positioned. Only the annotator mints these, and it runs after this pass.
_RESERVED_ATTR_PREFIX = "data-lumen-"

#: Attributes whose value loads bytes and therefore must already be in our custody.
_ASSET_ATTRS = frozenset({"src", "poster", "background"})
_ASSET_LIST_ATTRS = frozenset({"srcset", "imagesrcset"})

#: SVG elements on which ``href``/``xlink:href`` loads bytes rather than linking a page.
_SVG_ASSET_ELEMENTS = frozenset({"use", "image", "feimage", "textpath", "mpath", "pattern"})

_LINK_ATTRS = frozenset({"href", "xlink:href", "ping", "formaction", "action", "cite"})


@dataclass(frozen=True)
class SanitizedHtml:
    """One fragment's markup after the single sanitization pass."""

    html: str
    asset_digests: tuple[str, ...]
    notes: tuple[str, ...]


def sanitize_fragment_html(html: str, *, rehosted: Mapping[str, str]) -> SanitizedHtml:
    """Sanitize one captured section subtree. Refuses on an unrehostable reference.

    ``rehosted`` maps source references to held sha256 digests. Fragment-only aliases may resolve
    when all matching entries name the same digest; other URL spelling stays exact. A reference
    already written ``/asset-store/{digest}`` needs no entry. In-resource fragments survive both
    rewriting and a repeat sanitization.
    """
    rehosted = indexed_references(rehosted)
    tree = LexborHTMLParser(html)
    body = tree.body
    notes: list[str] = []
    digests: set[str] = set()
    if body is None:
        return SanitizedHtml(html="", asset_digests=(), notes=("input had no content",))

    _drop_banned_elements(body, notes)
    for node in body.traverse(include_text=False):
        if node.tag and node.tag.lower() != "body":
            _clean_attributes(node, rehosted=rehosted, digests=digests, notes=notes)

    rendered = "".join(child.html or "" for child in body.iter(include_text=True))
    return SanitizedHtml(
        html=rendered, asset_digests=tuple(sorted(digests)), notes=tuple(notes)
    )


def _drop_banned_elements(body: LexborNode, notes: list[str]) -> None:
    """Remove every banned element, outermost first.

    Re-scanning after each removal rather than collecting a list up front: decomposing a node
    invalidates its descendants, and a ``<form>`` containing an ``<iframe>`` is not exotic.
    Fragments are one section's markup, so the repeated scan costs nothing worth optimising.
    """
    while True:
        target = None
        for node in body.traverse(include_text=False):
            if node.tag and node.tag.lower() in DROPPED_ELEMENTS:
                target = node
                break
        if target is None:
            return
        notes.append(f"dropped <{target.tag.lower()}> and its content")
        target.decompose()


def _clean_attributes(
    node: LexborNode,
    *,
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
) -> None:
    tag = (node.tag or "").lower()
    for name, value in list(node.attributes.items()):
        lowered = name.lower()
        raw = value or ""

        if lowered.startswith("on"):
            del node.attrs[name]
            notes.append(f"stripped event handler {lowered} on <{tag}>")
            continue

        if lowered.startswith(_RESERVED_ATTR_PREFIX):
            del node.attrs[name]
            notes.append(f"stripped source-planted {lowered} on <{tag}> (we mint our own)")
            continue

        if lowered in _ASSET_ATTRS or (
            lowered in ("href", "xlink:href") and tag in _SVG_ASSET_ELEMENTS
        ):
            digest = resolve_asset_reference(raw, rehosted)
            if digest is not None:
                digests.add(digest)
                node.attrs[name] = asset_reference_url(raw, digest)
            continue

        if lowered in _ASSET_LIST_ATTRS:
            node.attrs[name] = _rewrite_srcset(raw, rehosted=rehosted, digests=digests)
            continue

        if lowered == "style":
            rewritten, found = rewrite_declaration_urls(raw, rehosted)
            digests.update(found)
            node.attrs[name] = rewritten
            continue

        if lowered in _LINK_ATTRS and not link_scheme_allowed(raw):
            del node.attrs[name]
            notes.append(f"stripped disallowed {lowered} on <{tag}>: {raw.strip()[:80]}")


def _rewrite_srcset(
    value: str, *, rehosted: Mapping[str, str], digests: set[str]
) -> str:
    """Every candidate in a ``srcset`` is its own reference; all of them are gated.

    Gating only the first would let the 2x candidate — the one a retina visitor actually loads —
    stay pointed at somebody else's CDN.

    Candidates are split by :func:`parse_srcset_candidates`, the real grammar, not by a bare
    ``,``. F1 shipped the bare split with its error direction recorded (a URL containing a comma
    was cut into halves no rehost map contains, so the fragment refused rather than storing a
    wrong URL) and the honest fix ledgered. F2.2 takes it: a CDN URL with a comma in a crop
    rectangle (``?rect=0,0,100,100``) is ordinary on real pages, and a refusal there would
    starve minting of the very sections it exists to clone.
    """
    candidates: list[str] = []
    for url, descriptor in parse_srcset_candidates(value):
        digest = resolve_asset_reference(url, rehosted)
        target = url if digest is None else asset_reference_url(url, digest)
        if digest is not None:
            digests.add(digest)
        candidates.append(f"{target} {descriptor}".strip() if descriptor else target)
    return ", ".join(candidates)


def parse_srcset_candidates(value: str) -> list[tuple[str, str]]:
    """``srcset`` → ``[(url, descriptor), …]``, per the HTML spec's own splitting algorithm.

    The interesting part of that algorithm — and the whole reason a naive ``value.split(",")``
    is wrong — is that **a comma only separates candidates when it cannot belong to the URL**.
    The spec resolves that by reading the URL as a run of non-whitespace characters FIRST:

    * ``hero.jpg?rect=0,0,100,100 2x`` — the run is the whole URL (commas and all) and does not
      end in a comma, so what follows the whitespace is its descriptor;
    * ``a.png, b.png 2x`` — the run is ``a.png,``; a run ending in a comma means the candidate
      had no descriptor, the trailing commas are separators, and the next candidate starts after
      them;
    * ``a.png 100w, b.png 200w`` — the descriptor is read up to the first comma that is not
      inside parentheses, so a future descriptor grammar with a function in it still splits.

    Returns the descriptor as the author wrote it (whitespace-collapsed), because this module
    re-serializes rather than re-authors: a fragment's markup is not ours to normalize beyond
    the reference rewrite that is the point of the pass.
    """
    out: list[tuple[str, str]] = []
    index, length = 0, len(value)
    while index < length:
        while index < length and (value[index].isspace() or value[index] == ","):
            index += 1
        if index >= length:
            break
        start = index
        while index < length and not value[index].isspace():
            index += 1
        url = value[start:index]
        if url.endswith(","):
            out.append((url.rstrip(","), ""))
            continue
        descriptor_start = index
        in_parentheses = False
        while index < length:
            char = value[index]
            if in_parentheses:
                if char == ")":
                    in_parentheses = False
            elif char == "(":
                in_parentheses = True
            elif char == ",":
                break
            index += 1
        descriptor = " ".join(value[descriptor_start:index].split())
        index += 1  # step over the separating comma (or past the end, harmlessly)
        if url:
            out.append((url, descriptor))
    return out


__all__ = [
    "DROPPED_ELEMENTS",
    "FragmentRefused",
    "SanitizedHtml",
    "parse_srcset_candidates",
    "sanitize_fragment_html",
]
