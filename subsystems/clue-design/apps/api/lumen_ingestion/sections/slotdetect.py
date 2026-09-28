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

**Nesting: the rule is consumption, not containment — and it runs BOTH WAYS.** ``LUMW0417``
fires when a bound marker sits inside a slot whose value *replaced or hid* its subtree. Only
``text`` (which replaces the element's content) and ``visibility`` (which removes it) consume;
``href`` and ``image`` rewrite one attribute and consume nothing. So detection refuses to mint
inside a TEXT slot's subtree — an ``<img>`` inside the headline is not offered — while
``cta_label`` inside the anchor that holds ``cta_href`` is perfectly legal and is exactly the
shape real markup takes.

The second direction matters just as much, and is easy to miss because detection has an order.
``<p>Look <img> and <a class="btn"><span>Go</span></a></p>`` mints the image and the CTA first;
the paragraph is only reached afterwards, and slotting it would put a CONSUMING slot on the
PARENT of two markers already minted inside it. Binding the body then discards both — the same
``LUMW0417``, arriving from above instead of below. So a consuming candidate is also refused
when its own subtree already contains ANY marker (not merely a consuming one: a text slot's
substitution swallows an ``href`` marker just as completely as it swallows a text one). First
minted wins, which keeps the result deterministic, and the refusal is reported.

The section-level ``visible`` slot is the one deliberate exception, and it has to be: it covers
the whole section by definition, so treating it as a consumer would mean a section could hold
one slot and no others. Its fallback is ``True``, so it consumes nothing until a human hides the
section — at which point every inner binding being moot is the intent, not a defect.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from lumen_api.fragments import MAX_FRAGMENT_SLOTS, SlotSpec, asset_url_digest
from selectolax.lexbor import LexborHTMLParser, LexborNode

#: Per-kind caps. Deliberately far below the engine's 64: a picker showing thirty text boxes for
#: one section is not an editing surface, and the tail of a long section is boilerplate.
MAX_BODY_SLOTS = 8
MAX_IMAGE_SLOTS = 8
MAX_HEADLINE_SLOTS = 8
MAX_CTA_SLOTS = 8

#: Heading tags in the order a section's dominant headline is looked for.
_HEADING_TAGS = ("h1", "h2", "h3")

#: Body-copy tags. ``<p>`` only: a ``<div>`` of copy is indistinguishable from a layout wrapper,
#: and slotting a wrapper would let one edit blow away a whole column.
_BODY_TAGS = ("p",)

#: A class token has to LOOK like a button for its link to be the section's call to action. A
#: nav's links are not CTAs, and minting the first ``<a>`` on the page as one would put the
#: section's only href slot on "Pricing".
_CTA_CLASS_RE = re.compile(r"(?:^|[-_])(?:btn|button|cta)(?:$|[-_])|button|btn|cta", re.I)


class _Marks:
    """Which elements already carry a slot, and which of those swallow what is inside them.

    Two sets rather than one because the two directions of the nesting check ask different
    questions: "is an ancestor going to swallow me?" is about CONSUMING slots only, while "am I
    about to swallow something?" is about EVERY marker already minted below.
    """

    def __init__(self) -> None:
        self.marked: set[int] = set()
        self.consumed: set[int] = set()

    def add(self, node: LexborNode, *, consumes: bool) -> None:
        self.marked.add(node.mem_id)
        if consumes:
            self.consumed.add(node.mem_id)

    def blocked(self, node: LexborNode, *, consuming: bool) -> bool:
        """Would minting a slot on this element hit the LUMW0417 class, either way round?"""
        current = node.parent
        while current is not None:
            if current.mem_id in self.consumed:
                return True
            current = current.parent
        if not consuming:
            return False
        return any(
            descendant.mem_id in self.marked
            for descendant in node.traverse(include_text=False)
            if descendant.mem_id != node.mem_id
        )


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
    marks = _Marks()

    _detect_headline(body, specs, marks)
    _detect_cta(body, specs, notes, marks)
    _detect_images(body, specs, notes, marks)
    _detect_secondary_headlines(body, specs, notes, marks)
    _detect_body(body, specs, notes, marks)
    _detect_visibility(body, specs, notes)

    if len(specs) > MAX_FRAGMENT_SLOTS:
        notes.append(
            f"capped this section at {MAX_FRAGMENT_SLOTS} slots; "
            f"{len(specs) - MAX_FRAGMENT_SLOTS} more were detected and dropped"
        )
        specs = specs[:MAX_FRAGMENT_SLOTS]
    return DetectedSlots(specs=tuple(specs), notes=tuple(notes))


# --------------------------------------------------------------------------- #
# detectors
# --------------------------------------------------------------------------- #


def _detect_headline(body: LexborNode, specs: list[SlotSpec], marks: _Marks) -> None:
    """One headline per section: the strongest heading tag present, first of that tag."""
    for tag in _HEADING_TAGS:
        for node in body.css(tag):
            if not _visible_text(node) or marks.blocked(node, consuming=True):
                continue
            specs.append(SlotSpec(selector=_selector(node), key="headline", kind="text"))
            marks.add(node, consumes=True)
            return


def _detect_cta(
    body: LexborNode, specs: list[SlotSpec], notes: list[str], marks: _Marks
) -> None:
    """The section's call to action: its target first, then its words if they have an element.

    The href takes the anchor because it is the half a clone MUST be able to change — a section
    lifted from somebody else's site whose button still points at their ``/signup`` is not
    shippable — and one element holds one marker. The label then needs an element of its own;
    when the anchor's words are its own text node there is nowhere to put it, and that is said
    out loud rather than left as a mysteriously missing key.
    """
    for ordinal, anchor in enumerate(_cta_anchors(body, marks), 1):
        if ordinal > MAX_CTA_SLOTS:
            notes.append(f"capped this section at {MAX_CTA_SLOTS} CTA pairs; remaining links keep source values")
            break
        specs.append(SlotSpec(selector=_selector(anchor), key=_numbered("cta_href", ordinal), kind="href"))
        marks.add(anchor, consumes=False)
        label = _label_element(anchor)
        label_key = _numbered("cta_label", ordinal)
        if label is None or marks.blocked(label, consuming=True):
            notes.append(
                f"no {label_key} slot: label has no independent text element; use exact label "
                "repair for a single text node, or a reviewed variant for mixed styled text"
            )
            continue
        specs.append(SlotSpec(selector=_selector(label), key=label_key, kind="text"))
        marks.add(label, consumes=True)


def _detect_secondary_headlines(
    body: LexborNode, specs: list[SlotSpec], notes: list[str], marks: _Marks,
) -> None:
    # Keep the original dominant headline key. Additional headings follow DOM order;
    # they cannot consume images or CTA markers already admitted above.
    count = sum(spec.key == "headline" for spec in specs)
    for node in body.css("h1,h2,h3,h4,h5,h6"):
        if node.mem_id in marks.marked or not _visible_text(node) or marks.blocked(node, consuming=True):
            continue
        if count >= MAX_HEADLINE_SLOTS:
            notes.append(f"capped this section at {MAX_HEADLINE_SLOTS} headline slots; remaining headings keep source copy")
            return
        count += 1
        specs.append(SlotSpec(selector=_selector(node), key=_numbered("headline", count), kind="text"))
        marks.add(node, consumes=True)


def _detect_images(
    body: LexborNode, specs: list[SlotSpec], notes: list[str], marks: _Marks
) -> None:
    """Every ``<img>`` whose src is already a rehosted digest, capped.

    An ``<img>`` with no resolvable digest is skipped rather than offered: the annotator REFUSES
    an image slot with no fallback, so offering one would turn a decorative image into a whole
    unmintable section.
    """
    found = 0
    for node in body.css("img"):
        if marks.blocked(node, consuming=False):
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
        marks.add(node, consumes=False)


def _detect_body(
    body: LexborNode, specs: list[SlotSpec], notes: list[str], marks: _Marks
) -> None:
    found = 0
    for tag in _BODY_TAGS:
        for node in body.css(tag):
            if not _visible_text(node):
                continue
            if marks.blocked(node, consuming=True):
                notes.append(
                    f"no {_numbered('body', found + 1)!r} slot on a <{tag}> that wraps slots "
                    "already minted inside it: replacing its copy would discard their values"
                )
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
            marks.add(node, consumes=True)


def _detect_visibility(body: LexborNode, specs: list[SlotSpec], notes: list[str]) -> None:
    """The whole section, shown or not — one slot, on the section's own root element.

    Deliberately outside :class:`_Marks` in both directions. The section root contains every
    other slot by definition, so a containment check here would mean a section could hold this
    slot or all the others and never both; and its fallback is "shown", so it consumes nothing
    until a human hides the whole section — at which point every inner binding being moot is
    precisely what was asked for.
    """
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


def _cta_anchors(body: LexborNode, marks: _Marks) -> Iterator[LexborNode]:
    for node in body.css("a"):
        if node.mem_id in marks.marked or marks.blocked(node, consuming=False):
            continue
        href = (node.attributes.get("href") or "").strip()
        if not href or href == "#":
            continue
        if _looks_like_a_button(node):
            yield node


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
    if any(child.tag == "-text" and child.text().strip() for child in anchor.iter(include_text=True)):
        return None
    bearers = [
        child
        for child in anchor.iter(include_text=False)
        if child.tag not in {"svg", "img", "math"}
        and child.attributes.get("aria-hidden") != "true" and _visible_text(child)
    ]
    if len(bearers) != 1 or bearers[0].css("svg, img, math, [aria-hidden=true]"):
        return None
    return bearers[0]


def _visible_text(node: LexborNode) -> str:
    return " ".join((node.text(deep=True) or "").split())


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
        # Lexbor still returns -comment nodes when include_text=False.
        # CSS :nth-child counts elements only; React suspense comments must not
        # shift the selector onto a different child or outside the subtree.
        if not candidate.tag or candidate.tag.startswith("-"):
            continue
        index += 1
        if candidate.mem_id == child.mem_id:
            return index
    return index


__all__ = ["MAX_BODY_SLOTS", "MAX_IMAGE_SLOTS", "DetectedSlots", "detect_slots"]
