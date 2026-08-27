"""Where a cloned section can be re-filled, found mechanically (clone-fidelity F2.2).

This is Ploy's shallow refactor, done at ingest and without a model. A verbatim clone is worth
little if nothing in it can be changed, so every minted fragment carries a small, deterministic
set of *slots*: the headline, the body copy, the images, the call to action's words and its
target, and the section's own visibility. F1's annotator stamps them; this module decides where.

**Deterministic, and honestly incomplete.** Detection is a walk over already-sanitized markup
with fixed rules — same input, same slots, byte for byte. It does not try to understand the
section. Not every section yields every kind, and a fragment with no slots at all is still a
valid clone: an honest empty result beats a guessed one, because a slot in the wrong place is
worse than no slot (it is an edit control that changes the wrong thing).

**The selectors are the contract with the annotator.** They are structural
(``body > *:nth-child(2) > *:nth-child(1)``) rather than class-based, because a real page's
class names are not unique inside one section — ``.button_label`` appears three times in a
pricing table — and ``css_first`` would silently take the first. A structural path names exactly
one element, and it is computed from the SAME parse the annotator will make.

**Nesting: the rule is consumption, not containment.** ``LUMW0417`` fires when a bound marker
sits inside a slot whose value *replaced or hid* its subtree. Only ``text`` (which replaces the
element's content) and ``visibility`` (which removes it) consume; ``href`` and ``image`` rewrite
one attribute and consume nothing. So detection refuses to mint inside a TEXT slot's subtree —
an ``<img>`` inside the headline is not offered — while ``cta_label`` inside the anchor that
holds ``cta_href`` is perfectly legal and is exactly the shape real markup takes.

The section-level ``visible`` slot is the one deliberate exception, and it has to be: it covers
the whole section by definition, so treating it as a consumer would mean a section could hold
one slot and no others. Its fallback is ``True``, so it consumes nothing until a human hides the
section — at which point every inner binding being moot is the intent, not a defect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lumen_api.fragments import MAX_FRAGMENT_SLOTS, SlotSpec, asset_url_digest
from selectolax.lexbor import LexborHTMLParser, LexborNode

#: Per-kind caps. Deliberately far below the engine's 64: a picker showing thirty text boxes for
#: one section is not an editing surface, and the tail of a long section is boilerplate.
MAX_BODY_SLOTS = 8
MAX_IMAGE_SLOTS = 8

#: Heading tags in the order a section's dominant headline is looked for.
_HEADING_TAGS = ("h1", "h2", "h3")

#: Body-copy tags. ``<p>`` only: a ``<div>`` of copy is indistinguishable from a layout wrapper,
#: and slotting a wrapper would let one edit blow away a whole column.
_BODY_TAGS = ("p",)

#: A class token has to LOOK like a button for its link to be the section's call to action. A
#: nav's links are not CTAs, and minting the first ``<a>`` on the page as one would put the
#: section's only href slot on "Pricing".
_CTA_CLASS_RE = re.compile(r"(?:^|[-_])(?:btn|button|cta)(?:$|[-_])|button|btn|cta", re.I)


@dataclass(frozen=True)
class DetectedSlots:
    """The slots one section offers, and what detection could not offer and why."""

    specs: tuple[SlotSpec, ...]
    notes: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.specs)


def detect_slots(sanitized_html: str) -> DetectedSlots:
    """Read one sanitized section subtree and say where it can be re-filled.

    ``sanitized_html`` must already have been through
    :func:`~lumen_api.fragments.sanitize.sanitize_fragment_html`: detection runs on the markup
    that will actually be stored, so a slot can never be offered on an element the sanitizer was
    about to remove, and an image slot's fallback is a digest the reference gate already vouched
    for. (Sanitization is a fixed point, so re-running it inside the artifact build is free.)
    """
    tree = LexborHTMLParser(sanitized_html or "")
    body = tree.body
    if body is None:
        return DetectedSlots(specs=(), notes=("the section's markup is empty",))

    specs: list[SlotSpec] = []
    notes: list[str] = []
    consumed: set[int] = set()

    _detect_headline(body, specs, consumed)
    _detect_cta(body, specs, notes, consumed)
    _detect_images(body, specs, notes, consumed)
    _detect_body(body, specs, notes, consumed)
    _detect_visibility(body, specs, notes)

    if len(specs) > MAX_FRAGMENT_SLOTS:
        notes.append(
            f"capped this section at {MAX_FRAGMENT_SLOTS} slots; "
            f"{len(specs) - MAX_FRAGMENT_SLOTS} more were detected and dropped"
        )
        specs = specs[:MAX_FRAGMENT_SLOTS]
    return DetectedSlots(specs=tuple(specs), notes=tuple(notes))


# --------------------------------------------------------------------------- #
# the five detectors
# --------------------------------------------------------------------------- #


def _detect_headline(body: LexborNode, specs: list[SlotSpec], consumed: set[int]) -> None:
    """One headline per section: the strongest heading tag present, first of that tag."""
    for tag in _HEADING_TAGS:
        for node in body.css(tag):
            if not _visible_text(node) or _inside_consumed(node, consumed):
                continue
            specs.append(SlotSpec(selector=_selector(node), key="headline", kind="text"))
            consumed.add(node.mem_id)
            return


def _detect_cta(
    body: LexborNode, specs: list[SlotSpec], notes: list[str], consumed: set[int]
) -> None:
    """The section's call to action: its target first, then its words if they have an element.

    The href takes the anchor because it is the half a clone MUST be able to change — a section
    lifted from somebody else's site whose button still points at their ``/signup`` is not
    shippable — and one element holds one marker. The label then needs an element of its own;
    when the anchor's words are its own text node there is nowhere to put it, and that is said
    out loud rather than left as a mysteriously missing key.
    """
    anchor = _cta_anchor(body, consumed)
    if anchor is None:
        return
    specs.append(SlotSpec(selector=_selector(anchor), key="cta_href", kind="href"))

    label = _label_element(anchor)
    if label is None:
        notes.append(
            "no cta_label slot: the call to action's words are the anchor's own text, and the "
            "anchor already carries cta_href (one element holds one slot marker)"
        )
        return
    specs.append(SlotSpec(selector=_selector(label), key="cta_label", kind="text"))
    consumed.add(label.mem_id)


def _detect_images(
    body: LexborNode, specs: list[SlotSpec], notes: list[str], consumed: set[int]
) -> None:
    """Every ``<img>`` whose src is already a rehosted digest, capped.

    An ``<img>`` with no resolvable digest is skipped rather than offered: the annotator REFUSES
    an image slot with no fallback, so offering one would turn a decorative image into a whole
    unmintable section.
    """
    found = 0
    for node in body.css("img"):
        if _inside_consumed(node, consumed):
            continue
        if asset_url_digest(node.attributes.get("src") or "") is None:
            continue
        if found >= MAX_IMAGE_SLOTS:
            notes.append(
                f"capped this section at {MAX_IMAGE_SLOTS} image slots; the rest keep the "
                "section's own artwork and are simply not editable"
            )
            return
        found += 1
        specs.append(SlotSpec(selector=_selector(node), key=_numbered("image", found), kind="image"))
        consumed.add(node.mem_id)


def _detect_body(
    body: LexborNode, specs: list[SlotSpec], notes: list[str], consumed: set[int]
) -> None:
    found = 0
    for tag in _BODY_TAGS:
        for node in body.css(tag):
            if not _visible_text(node) or _inside_consumed(node, consumed):
                continue
            if found >= MAX_BODY_SLOTS:
                notes.append(
                    f"capped this section at {MAX_BODY_SLOTS} body slots; "
                    "the rest keep the section's own copy and are simply not editable"
                )
                return
            found += 1
            specs.append(
                SlotSpec(selector=_selector(node), key=_numbered("body", found), kind="text")
            )
            consumed.add(node.mem_id)


def _detect_visibility(body: LexborNode, specs: list[SlotSpec], notes: list[str]) -> None:
    """The whole section, shown or not — one slot, on the section's own root element."""
    roots = [node for node in body.iter(include_text=False) if node.tag]
    if len(roots) != 1:
        notes.append(
            f"no visible slot: this fragment has {len(roots)} top-level elements, so there is "
            "no single element that IS the section"
        )
        return
    specs.append(SlotSpec(selector=_selector(roots[0]), key="visible", kind="visibility"))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _cta_anchor(body: LexborNode, consumed: set[int]) -> LexborNode | None:
    for node in body.css("a"):
        if _inside_consumed(node, consumed) or node.mem_id in consumed:
            continue
        href = (node.attributes.get("href") or "").strip()
        if not href or href == "#":
            continue
        if _looks_like_a_button(node):
            return node
    return None


def _looks_like_a_button(node: LexborNode) -> bool:
    if (node.attributes.get("role") or "").strip().lower() == "button":
        return True
    return any(
        _CTA_CLASS_RE.search(token) for token in (node.attributes.get("class") or "").split()
    )


def _label_element(anchor: LexborNode) -> LexborNode | None:
    """The element inside a CTA anchor that carries its words, if exactly one does.

    "Exactly one" is the point. An anchor holding an icon and a span has one text-bearing child
    and the choice is obvious; one holding two is a shape whose label is genuinely ambiguous, and
    guessing which half a human meant is how a slot ends up editing the wrong words.
    """
    bearers = [
        child
        for child in anchor.iter(include_text=False)
        if child.tag and _visible_text(child)
    ]
    return bearers[0] if len(bearers) == 1 else None


def _visible_text(node: LexborNode) -> str:
    return " ".join((node.text(deep=True) or "").split())


def _inside_consumed(node: LexborNode, consumed: set[int]) -> bool:
    """Would this element be swallowed by a slot already minted above it?"""
    current = node.parent
    while current is not None:
        if current.mem_id in consumed:
            return True
        current = current.parent
    return False


def _numbered(base: str, ordinal: int) -> str:
    """``image``, ``image_2``, ``image_3`` — the first of a kind is unsuffixed."""
    return base if ordinal == 1 else f"{base}_{ordinal}"


def _selector(node: LexborNode) -> str:
    """A structural path from ``body`` to exactly this element.

    ``:nth-child`` counts element children, which is what the walk below counts, so the selector
    means the same thing to lexbor's engine as it did to this function. Anchored at ``body >``
    because the annotator evaluates the selector in whole-document context: an unanchored
    ``*:nth-child(1)`` matches ``<body>`` itself.
    """
    steps: list[str] = []
    current: LexborNode | None = node
    while current is not None:
        parent = current.parent
        if parent is None:
            break
        steps.append(f"*:nth-child({_element_index(parent, current)})")
        if (parent.tag or "").lower() == "body":
            break
        current = parent
    steps.reverse()
    return "body > " + " > ".join(steps)


def _element_index(parent: LexborNode, child: LexborNode) -> int:
    index = 0
    for candidate in parent.iter(include_text=False):
        if not candidate.tag:
            continue
        index += 1
        if candidate.mem_id == child.mem_id:
            return index
    return index


__all__ = ["MAX_BODY_SLOTS", "MAX_IMAGE_SLOTS", "DetectedSlots", "detect_slots"]
