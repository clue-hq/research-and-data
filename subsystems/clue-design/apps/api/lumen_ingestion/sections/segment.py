"""Where this page's sections are, and what each one is (clone-fidelity F2.1).

The clone thesis is preservation, not reconstruction: a cloned nav IS the client's nav. Before
anything can be preserved, something has to say which subtree is the nav — and say it from
evidence, mechanically, the same way twice, over a snapshot captured hours ago.

**Two signal families, crossed.** LANDMARKS come from the markup itself: semantic elements and
ARIA roles (``<nav>``, ``<header>``, ``<footer>``, ``role="contentinfo"``), then the class and id
vocabulary a page builder leaves behind — Webflow's Client-First convention names a section
``section_home-hero`` and a badge strip ``home-security_badge``, which is a stronger statement of
intent than anything we could infer — then the content itself (a ``<blockquote>`` is a
testimonial; "HIPAA … SOC 2" is a security band; four images and no prose is a logo wall). The
MEASURED BAND SEQUENCE comes from the rendered capture: the browser walked the page's top-level
children and recorded each band's tag, background and height, so a band tells us a section is
real, how tall it is, and where it sits.

**Disagreement is reported, never averaged.** Every signal that voted rides on the record with
the weight it carried, and when two named roles arrive within a hair of each other with no
landmark to break the tie, the section is called ``other``. That is deliberate and it is the
rule the whole stage is built around: minting takes ``other`` sections too, so a role is only a
LABEL — a wrong label sends the agent to reuse a testimonial as a security band, while ``other``
merely means "we could not name it". An honest refusal costs a label; a confident mistake costs
a page.

**Nothing is invented.** No LLM, no network, no DB. A section's y-extent exists only where the
browser measured it: on a semantic page the probe roots at ``<main>``, so the nav and the footer
— the two most-cloned sections of all — carry no geometry, and this module says so in a
diagnostic rather than guessing a crop that would be wrong. Same html plus same bands ⇒ byte-
identical output, which is what makes the stage testable and re-runnable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from selectolax.parser import HTMLParser, Node

from .bands import MeasuredBand, SkippedChild, measured_bands, skipped_children

# --- the vocabulary -------------------------------------------------------------------------

NAV = "nav"
HERO = "hero"
PROOF = "proof"
TESTIMONIAL = "testimonial"
SECURITY = "security"
FOOTER = "footer"
OTHER = "other"

#: The named roles, plus the residual. ``other`` is a first-class answer, not a failure.
SECTION_ROLES: tuple[str, ...] = (NAV, HERO, PROOF, TESTIMONIAL, SECURITY, FOOTER, OTHER)

#: Roles a page has at most one of, and which end of the document wins the argument.
_SINGULAR_ROLES = {NAV: "first", HERO: "first", FOOTER: "last"}

# --- what each signal is worth ----------------------------------------------------------------
# A semantic landmark is the page telling us in the standard's own words; a class name is the
# builder telling us in its convention's words; content and position are us inferring. The gaps
# are wide enough that inference never outranks a declaration.

LANDMARK_WEIGHT = 0.90
STRONG_HINT_WEIGHT = 0.80
HEADLINE_WEIGHT = 0.70
CONTENT_WEIGHT = 0.65
WEAK_HINT_WEIGHT = 0.60
POSITION_WEIGHT = 0.50
#: Each additional independent signal for the same role, up to the cap. Small on purpose:
#: agreement is reassurance, not proof.
CORROBORATION_BONUS = 0.05
MAX_CONFIDENCE = 0.95
#: What a residual ``other`` carries — low, because it is an absence of evidence, not a finding.
OTHER_CONFIDENCE = 0.30
#: Two named roles this close, with no landmark behind the leader, is a tie we refuse to break.
CONTEST_MARGIN = 0.10

#: A first band shorter than this is page chrome, not a content section.
NAV_BAND_MAX_PX = 180.0
#: A band this tall, early, is a hero rather than a strip.
HERO_BAND_MIN_PX = 320.0
#: Prose this short beside several images is a logo wall, not a paragraph with pictures.
LOGO_WALL_MAX_TEXT = 200
LOGO_WALL_MIN_IMAGES = 3
#: Enough links to be a menu / a footer link farm rather than a section with a couple of CTAs.
LINK_DENSE = 3
FOOTER_LINK_DENSE = 4

# --- diagnostics ------------------------------------------------------------------------------

#: The snapshot carried no measured bands (static tier, or captured before F2.1 persisted them):
#: roles still get called, geometry does not exist.
NO_BAND_EVIDENCE_CODE = "LUMI0520"
#: The band sequence could not be lined up with the parsed DOM. Bands are then used for NOTHING —
#: a mis-aligned band would hand minting the wrong crop, which is worse than no crop.
BAND_ALIGNMENT_REFUSED_CODE = "LUMI0521"
#: The probe recorded heights but no absolute tops, so extents are the running sum of the band
#: heights: exact where bands abut (the modern edge-to-edge case), drifting where they do not.
ESTIMATED_GEOMETRY_CODE = "LUMI0522"
#: The page yielded no section at all.
NO_SECTIONS_CODE = "LUMI0523"
#: Sections that sit outside the probe's measured root — on a semantic page, the nav and footer.
UNMEASURED_SECTION_CODE = "LUMI0524"
#: Flow children dropped as insignificant that nonetheless carried text.
SKIPPED_CONTENT_CODE = "LUMI0525"

#: How many items any diagnostic spells out in its human line.
_NAMED_IN_MESSAGE = 8

# --- landmark vocabulary ----------------------------------------------------------------------

_ARIA_ROLES = {"navigation": NAV, "banner": NAV, "contentinfo": FOOTER}

_STRONG_TOKEN_HINTS: dict[str, str] = {
    "nav": NAV,
    "navbar": NAV,
    "navigation": NAV,
    "menu": NAV,
    "topbar": NAV,
    "hero": HERO,
    "masthead": HERO,
    "jumbotron": HERO,
    "logos": PROOF,
    "logowall": PROOF,
    "logocloud": PROOF,
    "clients": PROOF,
    "customers": PROOF,
    "partners": PROOF,
    "trusted": PROOF,
    "trustedby": PROOF,
    "proof": PROOF,
    "press": PROOF,
    "brands": PROOF,
    "testimonial": TESTIMONIAL,
    "testimonials": TESTIMONIAL,
    "quote": TESTIMONIAL,
    "quotes": TESTIMONIAL,
    "review": TESTIMONIAL,
    "reviews": TESTIMONIAL,
    "security": SECURITY,
    "compliance": SECURITY,
    "compliant": SECURITY,
    "hipaa": SECURITY,
    "gdpr": SECURITY,
    "soc2": SECURITY,
    "iso27001": SECURITY,
    "privacy": SECURITY,
    "trustcenter": SECURITY,
    "certifications": SECURITY,
    "footer": FOOTER,
    "colophon": FOOTER,
}

_WEAK_TOKEN_HINTS: dict[str, str] = {
    "header": NAV,
    "banner": HERO,
    "stats": PROOF,
    "metrics": PROOF,
    "story": TESTIMONIAL,
    "stories": TESTIMONIAL,
    "badge": SECURITY,
    "badges": SECURITY,
    "legal": FOOTER,
}

#: Hints whose words are split by the tokenizer ("logo-wall" → logo, wall) and only mean
#: something together. Matched against the token blob, so hyphens/underscores/case do not matter.
_PHRASE_HINTS: tuple[tuple[str, str], ...] = (
    ("logo wall", PROOF),
    ("logo cloud", PROOF),
    ("logo strip", PROOF),
    ("social proof", PROOF),
    ("as seen in", PROOF),
    ("case study", TESTIMONIAL),
    ("trust center", SECURITY),
    ("soc 2", SECURITY),
    ("iso 27001", SECURITY),
    ("above fold", HERO),
)

_SECURITY_TEXT = re.compile(
    r"\b(hipaa|soc\s?-?\s?2|gdpr|ccpa|hitrust|iso\s?-?\s?27001|pci\s?dss|"
    r"end-to-end encryption|encrypted at rest|penetration test|compliance|compliant)\b",
    re.IGNORECASE,
)
_PROOF_TEXT = re.compile(
    r"(trusted by|used by|powering|as seen in|as featured in|our customers|our partners|"
    r"loved by|join \d)",
    re.IGNORECASE,
)
_FOOTER_TEXT = re.compile(r"(©|\(c\)\s?\d{4}|copyright|all rights reserved)", re.IGNORECASE)

#: Class tokens whose whole job is to take an element out of the layout. A page that ships one
#: of these is telling us the section is not on the page — the F2 acceptance walk minted a
#: `class="hide"` announcement banner as an approved, reusable clone.
#:
#: A CLOSED list of the shared vocabulary (Bootstrap, Tailwind, Webflow, the a11y convention),
#: matched as whole tokens. It was briefly a suffix rule (`*-hidden`) and that was wrong in the
#: most instructive way: `overflow-hidden` is an OVERFLOW utility, and treating it as a
#: visibility one dropped a real testimonials band on the very page this list was written from.
#: A site's own private spelling (`ih-home-pricing-hidden`) is deliberately NOT chased — guessing
#: at one company's naming is exactly the site-tuning this wave is forbidden; the probe's own
#: `hidden` skip record (W1) is the general answer, and the feasibility floor covers captures
#: taken before the probe learned to write it down.
_HIDDEN_CLASS_TOKENS = frozenset(
    {"hide", "hidden", "is-hidden", "d-none", "sr-only", "visually-hidden", "w-condition-invisible"}
)

#: Tags that never render a band of their own.
_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "link",
        "meta",
        "template",
        "noscript",
        "title",
        "base",
        "br",
        "source",
        "track",
        "param",
        "head",
    }
)
#: The ancestors that make a nested ``<header>``/``<footer>`` that thing's header rather than the
#: page's (the HTML standard's own scoping rule for the ``banner``/``contentinfo`` landmarks).
_LANDMARK_SCOPING_TAGS = frozenset({"article", "aside", "main", "nav", "section"})
#: Elements that are a section by their own tag, however little they contain.
_SECTION_TAGS = frozenset(
    {"nav", "header", "footer", "main", "section", "article", "aside", "form", "table"}
)
#: Content that counts even when an element carries no text.
_MEDIA_SELECTOR = "img, svg, picture, video, canvas, iframe, input, button, form"
_HIDDEN_STYLE = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden)", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

# --- the record shape -------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionEvidence:
    """One signal that voted on one section's role, and what it saw.

    ``role`` is the role this signal argued for; ``signal`` is which family it came from
    (``landmark`` / ``class-hint`` / ``content`` / ``band`` / ``position`` / ``resolution``).
    A ``resolution`` entry carries no vote (weight 0) and records why the final call differs
    from what the votes alone would say.
    """

    signal: str
    role: str
    weight: float
    detail: str


@dataclass(frozen=True)
class SectionGeometry:
    """A section's document-order y-extent at the captured viewport, in CSS pixels.

    ``basis`` is ``"measured"`` when the browser recorded the band's absolute top, and
    ``"estimated"`` when tops had to be reconstructed by summing band heights from the top of
    the document (a pre-F2.1 harvest). Nothing else is ever produced — a section the browser
    never measured has no geometry at all.
    """

    top_px: float
    bottom_px: float
    height_px: float
    basis: str
    viewport_width: int | None


@dataclass(frozen=True)
class SectionRecord:
    """One top-level section of a captured page.

    ``dom_path`` is the durable handle: the chain of ELEMENT-child indices from the document's
    root element (``<html>``) down to this section, which re-resolves to the same node on any
    re-parse of the same html (:func:`resolve_section`). It survives because it names structure
    rather than styling — unlike a class selector, which a page may repeat a dozen times.
    """

    index: int
    role: str
    confidence: float
    dom_path: tuple[int, ...]
    tag: str
    element_id: str | None
    class_names: tuple[str, ...]
    band_index: int | None
    geometry: SectionGeometry | None
    heading: str | None
    text_preview: str
    evidence: tuple[SectionEvidence, ...]


@dataclass(frozen=True)
class SectionSegmentation:
    """Everything one page's segmentation pass found, in document order."""

    page_url: str
    snapshot_id: str | None
    viewport_width: int | None
    sections: tuple[SectionRecord, ...]
    diagnostics: tuple[dict[str, Any], ...]

    def by_role(self, role: str) -> tuple[SectionRecord, ...]:
        return tuple(section for section in self.sections if section.role == role)


# --- entry points ----------------------------------------------------------------------------


def segment_snapshot(snapshot: Any) -> SectionSegmentation:
    """Segment one persisted page (the :mod:`lumen_ingestion.site_snapshot` read seam's shape).

    Duck-typed on purpose: everything this needs (``html``, ``page_url``, ``viewport_width``,
    ``meta``, ``snapshot_id``) is a plain attribute of ``LoadedSiteSnapshot``, and taking the
    shape rather than the class keeps this module free of the DAL, the storage backend and the
    async world they live in.
    """
    return segment_page(
        getattr(snapshot, "html", "") or "",
        page_url=getattr(snapshot, "page_url", "") or "",
        bands=measured_bands(getattr(snapshot, "meta", None)),
        skips=skipped_children(getattr(snapshot, "meta", None)),
        viewport_width=getattr(snapshot, "viewport_width", None),
        snapshot_id=getattr(snapshot, "snapshot_id", None),
    )


def segment_page(
    html: str,
    *,
    page_url: str,
    bands: Sequence[MeasuredBand] = (),
    skips: Sequence[SkippedChild] = (),
    viewport_width: int | None = None,
    snapshot_id: str | None = None,
) -> SectionSegmentation:
    """The pure pass: html + measured bands ⇒ ordered, typed, evidenced sections."""
    tree = HTMLParser(html or "")
    diagnostics: list[dict[str, Any]] = []
    candidates, skipped = _page_flow(tree)

    if candidates:
        _bind_bands(candidates, tuple(bands), diagnostics, tuple(skips))
        candidates = _section_shaped(candidates, skipped, tuple(skips))

    if not candidates:
        diagnostics.append(
            _diag(
                NO_SECTIONS_CODE,
                "warning",
                "no top-level section survived segmentation — the page's flow is empty, "
                "entirely non-rendering, or nothing but loose content",
            )
        )
        return SectionSegmentation(
            page_url=page_url,
            snapshot_id=snapshot_id,
            viewport_width=viewport_width,
            sections=(),
            diagnostics=tuple(diagnostics) + tuple(_skip_diagnostic(skipped)),
        )

    _assign_geometry(candidates, viewport_width, diagnostics)
    _call_roles(candidates)

    diagnostics.extend(_skip_diagnostic(skipped))

    sections = tuple(
        SectionRecord(
            index=index,
            role=candidate.role,
            confidence=round(candidate.confidence, 3),
            dom_path=candidate.path,
            tag=candidate.tag,
            element_id=candidate.element_id,
            class_names=candidate.class_names,
            band_index=candidate.band.index if candidate.band else None,
            geometry=candidate.geometry,
            heading=candidate.heading,
            text_preview=candidate.text[:160],
            evidence=tuple(candidate.evidence),
        )
        for index, candidate in enumerate(candidates)
    )
    return SectionSegmentation(
        page_url=page_url,
        snapshot_id=snapshot_id,
        viewport_width=viewport_width,
        sections=sections,
        diagnostics=tuple(diagnostics),
    )


def resolve_section(source: HTMLParser | str, record: SectionRecord) -> Node | None:
    """Re-find a section's element in a fresh parse of the same html — or ``None``.

    A path is a POSITION, and positions move: insert one section above the hero and the hero's
    path now points at its neighbour. Walking the path alone would hand that neighbour back with
    every appearance of success, and minting extracts ``resolve_section(...).html`` — so a silent
    shift mints the wrong subtree, which is precisely the failure a durable handle exists to
    prevent. The path therefore only proposes; the element has to still LOOK like the section
    that was recorded (same tag, and the same id or a shared class name) before it is returned.

    ``None`` rather than an exception because a caller holding a record and drifted html has a
    real decision to make — re-segment, or refuse the mint — and an exception here would only
    move that decision somewhere less informed.
    """
    tree = source if isinstance(source, HTMLParser) else HTMLParser(source)
    node = tree.root
    if node is None:
        return None
    for index in record.dom_path:
        children = _element_children(node)
        if index >= len(children):
            return None
        node = children[index][1]
    return node if _matches_record(node, record) else None


def _matches_record(node: Node, record: SectionRecord) -> bool:
    """Is the element at the end of the path still the section the record describes?

    Identity is checked in the order it is trustworthy: an id is unique on a page, so a recorded
    id must be the id found; otherwise a shared class name settles it (INTERSECTION, for the same
    reason band matching uses it — a page's own JS toggles classes between the html snapshot and
    anything that re-parses it). A section that had neither is checked on its tag alone, which is
    all it ever offered.
    """
    if (node.tag or "").lower() != record.tag:
        return False
    found_id = (node.attributes.get("id") or "").strip() or None
    if record.element_id:
        return found_id == record.element_id
    if record.class_names:
        found = set((node.attributes.get("class") or "").split())
        return bool(found & set(record.class_names))
    return True


# --- candidates ------------------------------------------------------------------------------


@dataclass
class _Candidate:
    node: Node
    path: tuple[int, ...]
    tag: str
    element_id: str | None
    class_names: tuple[str, ...]
    tokens: tuple[str, ...]
    token_blob: str
    aria_role: str | None
    text: str
    heading: str | None
    link_count: int
    image_count: int
    has_h1: bool
    has_quote: bool
    in_measured_root: bool
    is_page_scoped: bool = True
    band: MeasuredBand | None = None
    geometry: SectionGeometry | None = None
    evidence: list[SectionEvidence] = None  # type: ignore[assignment]
    role: str = OTHER
    confidence: float = OTHER_CONFIDENCE

    def __post_init__(self) -> None:
        if self.evidence is None:
            self.evidence = []


def _page_flow(tree: HTMLParser) -> tuple[list[_Candidate], list[tuple[str, str]]]:
    """The page's top-level sections, in document order, plus what was skipped.

    The measured root (``<main>`` when the page has one, else the body descended through
    single-child wrappers) is EXPANDED in place, so a semantic page contributes its header, then
    main's bands, then its footer — one flat sequence of the page's real visual bands, which is
    what "top-level sections" means to a reader and to a clone.
    """
    root = tree.root
    if root is None:
        return [], []
    body = _first_child_with_tag(root, "body")
    if body is None:
        body_node, body_path = root, ()
    else:
        body_node, body_path = body

    measured = _measured_root(tree, body_node, body_path)
    skipped: list[tuple[str, str]] = []
    if measured[1] == body_path:
        return _children_as_candidates(body_node, body_path, True, skipped), skipped
    return _expand(body_node, body_path, measured[1], skipped), skipped


def _section_shaped(
    candidates: list[_Candidate],
    skipped: list[tuple[str, str]],
    skips: tuple[SkippedChild, ...] = (),
) -> list[_Candidate]:
    """Keep the flow children that are SECTIONS; note the loose content that is not.

    A section is something a page could reuse: a container, a sectioning element, or whatever the
    browser measured as a band. A bare ``<h1>`` or ``<p>`` sitting directly in the body — a
    prototype page, a stripped template, a body whose wrapper never rendered — is real content
    and still not a section, because there is nothing there to clone. Dropping it silently would
    overstate coverage, so each one is named in the skip diagnostic.
    """
    # A class token is a GUESS about a stylesheet nobody here evaluated, so it may only remove a
    # a section when a measurement agrees with it. `hidden md:block` is the standard Tailwind
    # DESKTOP-visible variant and captures are taken at desktop width — the element is on the
    # very page being cloned — so a bare token dropped real sections from every static-tier
    # capture and every page whose binding was refused, which are exactly the pages that measured
    # nothing and therefore have no evidence either way.
    bound_any = any(candidate.band is not None for candidate in candidates)
    kept: list[_Candidate] = []
    for candidate in candidates:
        if candidate.band is None and _is_hidden_by_class(candidate) and (
            _probe_skipped(candidate, skips)
            # The browser measured THIS page and this eligible child got no band: it looked and
            # did not see it. Restricted to the measured root, because a nav or footer outside it
            # was never eligible, so "no band" says nothing about whether it renders.
            or (bound_any and candidate.in_measured_root)
        ):
            skipped.append((candidate.tag, candidate.text[:80]))
            continue
        if (
            candidate.band is not None
            or candidate.tag in _SECTION_TAGS
            or _element_children(candidate.node)
        ):
            kept.append(candidate)
        else:
            skipped.append((candidate.tag, candidate.text[:80]))
    return kept


def _probe_skipped(candidate: _Candidate, skips: tuple[SkippedChild, ...]) -> bool:
    """Did the browser itself say it passed this child over for being hidden?"""
    return any(
        record.reason == "hidden" and _skip_matches(candidate, record) for record in skips
    )


def _is_hidden_by_class(candidate: _Candidate) -> bool:
    """Does this element say, in its own attributes, that it is not on the page?

    Evidence-backed rather than invented: W1's probe records the children it declined to measure
    and WHY, and `hidden` is one of its reasons — this is the same judgement, made from the
    markup for a capture whose probe never got to make it, and overruled by the probe wherever
    the probe spoke.
    """
    if (candidate.node.attributes.get("aria-hidden") or "").strip().lower() == "true":
        return True
    for token in candidate.class_names:
        lowered = token.lower()
        if lowered in _HIDDEN_CLASS_TOKENS:
            return True
    return False


def _skip_diagnostic(skipped: list[tuple[str, str]]) -> list[dict[str, Any]]:
    if not skipped:
        return []
    with_text = [entry for entry in skipped if entry[1]]
    return [
        _diag(
            SKIPPED_CONTENT_CODE,
            "warning" if with_text else "info",
            f"{len(skipped)} flow child(ren) were not segmented "
            f"({', '.join(tag for tag, _ in skipped[:_NAMED_IN_MESSAGE])})"
            + (f"; {len(with_text)} carried text" if with_text else ""),
            skipped=[{"tag": tag, "text": text} for tag, text in skipped],
        )
    ]


def _expand(
    node: Node,
    path: tuple[int, ...],
    measured_path: tuple[int, ...],
    skipped: list[tuple[str, str]],
) -> list[_Candidate]:
    out: list[_Candidate] = []
    for index, child in _element_children(node):
        child_path = path + (index,)
        if child_path == measured_path:
            out.extend(_children_as_candidates(child, child_path, True, skipped))
        elif measured_path[: len(child_path)] == child_path:
            out.extend(_expand(child, child_path, measured_path, skipped))
        elif _is_significant(child):
            out.append(_candidate(child, child_path, in_measured_root=False))
        else:
            _note_skip(child, skipped)
    return out


def _children_as_candidates(
    node: Node,
    path: tuple[int, ...],
    in_measured_root: bool,
    skipped: list[tuple[str, str]],
) -> list[_Candidate]:
    out: list[_Candidate] = []
    for index, child in _element_children(node):
        if _is_significant(child):
            out.append(_candidate(child, path + (index,), in_measured_root=in_measured_root))
        else:
            _note_skip(child, skipped)
    return out


def _measured_root(
    tree: HTMLParser, body: Node, body_path: tuple[int, ...]
) -> tuple[Node, tuple[int, ...]]:
    """Replay the capture probe's own root choice, in Python.

    ``capture/geometry.py`` takes ``document.querySelector('main') || document.body`` and then
    descends through up to four single-child wrappers. Mirroring it exactly is what lets a
    measured band be matched to a parsed element at all; the one unavoidable difference is that
    the browser filtered children by rendered size and we filter by markup significance.
    """
    found = _find_first(tree.root, (), "main")
    node, path = found if found is not None else (body, body_path)
    for _ in range(4):
        children = [
            (index, child) for index, child in _element_children(node) if _is_significant(child)
        ]
        if len(children) != 1:
            break
        index, child = children[0]
        node, path = child, path + (index,)
    return node, path


def _candidate(node: Node, path: tuple[int, ...], *, in_measured_root: bool) -> _Candidate:
    attributes = node.attributes
    class_names = tuple((attributes.get("class") or "").split())
    element_id = (attributes.get("id") or "").strip() or None
    tokens = _tokenize(" ".join(class_names) + " " + (element_id or ""))
    text = rendered_text(node)
    return _Candidate(
        node=node,
        path=path,
        tag=(node.tag or "").lower(),
        element_id=element_id,
        class_names=class_names,
        tokens=tokens,
        token_blob=" ".join(tokens),
        aria_role=((attributes.get("role") or "").strip().lower() or None),
        text=text,
        heading=_first_heading(node),
        link_count=len(node.css("a")),
        image_count=len(node.css("img")) + len(node.css("svg")),
        has_h1=bool(node.css("h1")),
        has_quote=bool(node.css("blockquote")) or bool(node.css("q")),
        in_measured_root=in_measured_root,
        is_page_scoped=_is_page_scoped(node),
    )


def _is_page_scoped(node: Node) -> bool:
    """Does a ``<header>``/``<footer>`` here belong to the PAGE, or to a section of it?

    The HTML standard already answers this and it is worth following literally: a ``<header>`` is
    the ``banner`` landmark, and a ``<footer>`` the ``contentinfo`` landmark, only when it is not
    inside an ``article``, ``aside``, ``main``, ``nav`` or ``section``. Inside one of those it is
    that thing's own header — a section heading block, not the site's masthead.

    This replaced a proxy that looked equivalent and was not: "outside the capture probe's
    measured root" agrees with the standard on a page that HAS a ``<main>``, and on a page
    without one — which is most Webflow pages, where the wrapper is a plain ``<div>`` — it marks
    every body child as in-root, so the site header lost its landmark and a class token like
    `masthead` was left to name it a hero. Ancestry is the fact; root membership was a stand-in
    for it that quietly stopped being true.
    """
    parent = node.parent
    while parent is not None:
        tag = (parent.tag or "").lower()
        if tag in _LANDMARK_SCOPING_TAGS:
            return False
        if tag in {"body", "html"}:
            break
        parent = parent.parent
    return True


# --- band alignment --------------------------------------------------------------------------


def _bind_bands(
    candidates: list[_Candidate],
    bands: tuple[MeasuredBand, ...],
    diagnostics: list[dict[str, Any]],
    skips: tuple[SkippedChild, ...] = (),
) -> None:
    """Line the measured bands up with the parsed sections — band by band, not all or nothing.

    The bands are, by construction, a SUBSEQUENCE of the measured root's children: the browser
    skipped whatever was hidden, under 40px tall, or narrower than half the viewport, and this
    module cannot reproduce any of those judgements without the stylesheet and a layout engine.
    So the alignment is a greedy in-order walk that may skip a parsed section but may never
    reorder one — and a greedy walk has one failure mode, which is that it takes the FIRST thing
    that matches whether or not it was the only one.

    That is not hypothetical. Three sections named alike with the middle one hidden by a class
    (`w-condition-invisible` on a Webflow page) binds the third band's geometry to the second
    section, and every downstream consumer then crops a picture of the wrong part of the page.
    So the walk is run in BOTH directions: forward gives each band the EARLIEST candidate it
    could take in any valid alignment, backward the LATEST.

    **Where the two agree, that band is forced** — no valid alignment can place it anywhere else,
    because there is nothing earlier and nothing later available to it — so it binds, and it binds
    with the same certainty whole-list agreement used to demand. Where they differ, the evidence
    genuinely does not say, and only THAT band goes unbound.

    This is the floor guarantee, and the F2 acceptance walk is why it exists. The first real site
    walked hid one of three same-class sections; whole-list agreement saw the divergence and
    refused the page's entire binding, so thirteen fragments got no preview because two bands were
    contested. Per-band feasibility loses those two and keeps the other four. Refusing costs
    geometry; guessing costs a wrong picture that looks right; refusing MORE than the evidence
    requires costs geometry nobody had to lose.

    Two things narrow it, deliberately:

    * ``skips`` — what the browser tells us it declined to measure — is subtracted
      first. When the residue lines up one-for-one, the alignment is not merely forced band by
      band, it is *known*, and the page binds completely. That is the real fix; the feasibility
      floor is what carries a capture taken before the probe learned to say so.
    * partial binding is allowed only when every band carries a measured ``top``. The
      running-sum fallback in :func:`_assign_geometry` reconstructs tops by accumulating heights,
      which is only true when the bound set is contiguous — with holes in it, it would place
      every later section at the wrong offset. So a top-less sequence keeps the old
      all-or-nothing rule rather than producing confidently wrong extents.
    """
    if not bands:
        diagnostics.append(
            _diag(
                NO_BAND_EVIDENCE_CODE,
                "info",
                "no measured band sequence on this snapshot — roles come from landmarks and "
                "content alone, and no section carries geometry",
            )
        )
        return

    measured = [candidate for candidate in candidates if candidate.in_measured_root]
    if not any(band.element_id or band.class_names for band in bands):
        # An ANONYMOUS sequence (a pre-F2.1 harvest recorded tags and heights only) carries
        # nothing to tell one <div> from the next, so in-order tag matching would cheerfully bind
        # the hero's band to a nav div the browser had skipped. Demand that it account for every
        # parsed section instead: a 1:1 sequence is checkable, a subsequence is a guess.
        if len(bands) != len(measured):
            diagnostics.append(
                _diag(
                    BAND_ALIGNMENT_REFUSED_CODE,
                    "warning",
                    f"the measured band sequence carries no element identity and its "
                    f"{len(bands)} band(s) do not line up one-for-one with the "
                    f"{len(measured)} parsed section(s) of the measured root — no geometry "
                    "was bound",
                    reason="anonymous-count-mismatch",
                    bands=len(bands),
                    measured_sections=len(measured),
                )
            )
            return

    # What the browser said it skipped is subtracted before anything is inferred. A skip record
    # is matched by the same rule a band is, and consumed once, in order.
    residue, subtracted = _subtract_skipped(measured, skips)
    if subtracted and _lines_up(residue, bands):
        for candidate, band in zip(residue, bands):
            candidate.band = band
        return

    # A capture whose probe never learned to report its skips can still often be resolved: the
    # markup itself says which sections are not on the page. That hint only ever PROPOSES a
    # residue, and the proposal has to line up one-for-one before it is believed — so a class
    # named `hide` that the stylesheet ignores costs nothing, while the common case (a page that
    # hides one of several same-class sections) binds completely instead of contesting.
    if not subtracted:
        proposed = [c for c in measured if not _is_hidden_by_class(c)]
        removed = [c for c in measured if _is_hidden_by_class(c)]
        if (
            removed
            and _lines_up(proposed, bands)
            and _proposal_is_safe(proposed, removed, bands)
        ):
            for candidate, band in zip(proposed, bands):
                candidate.band = band
            return

    forward = _greedy_alignment(residue, bands)
    backward = _greedy_alignment(residue, bands, reverse=True)
    if forward is None or backward is None:
        # Which direction failed is a real distinction and used to be lost: a `None` backward
        # walk fell into the ambiguity branch, where `zip(forward, backward or [])` compared
        # nothing and the diagnostic reported "ambiguous" with the first band as the culprit —
        # a confident answer to a question that had not been asked.
        unmatched = _first_unmatched_band(residue, bands)
        diagnostics.append(
            _diag(
                BAND_ALIGNMENT_REFUSED_CODE,
                "warning",
                f"the measured band sequence ({len(bands)} bands) could not be aligned with the "
                f"{len(residue)} parsed section(s) of the measured root; band {unmatched} "
                "matched no section — no geometry was bound",
                reason="unmatched",
                bands=len(bands),
                measured_sections=len(residue),
                unmatched_band=unmatched,
                direction="forward" if forward is None else "backward",
            )
        )
        return

    forced = [position for position in range(len(bands)) if forward[position] == backward[position]]
    contested = [position for position in range(len(bands)) if forward[position] != backward[position]]

    if not contested:
        for position, band in enumerate(bands):
            residue[forward[position]].band = band
        return

    tops_measured = all(band.top_px is not None for band in bands)
    if not forced or not tops_measured:
        diagnostics.append(
            _diag(
                BAND_ALIGNMENT_REFUSED_CODE,
                "warning",
                f"the measured band sequence has more than one way to line up with the "
                f"{len(residue)} parsed section(s) of the measured root — "
                f"band {bands[contested[0]].index} could belong to either of two sections that "
                "name themselves alike, and "
                + (
                    "no band could be placed with certainty"
                    if not forced
                    else "the capture recorded no absolute tops, so a partial binding could not "
                    "be turned into honest extents"
                )
                + " — no geometry was bound",
                reason="ambiguous",
                bands=len(bands),
                measured_sections=len(residue),
                contested_band=bands[contested[0]].index,
                contested_bands=[bands[position].index for position in contested],
                bound_bands=[],
            )
        )
        return

    for position in forced:
        residue[forward[position]].band = bands[position]
    diagnostics.append(
        _diag(
            BAND_ALIGNMENT_REFUSED_CODE,
            "warning",
            f"{len(contested)} of {len(bands)} measured band(s) could belong to more than one of "
            f"the {len(residue)} parsed section(s) that name themselves alike, so those band(s) "
            f"bound nothing; the other {len(forced)} were placed with certainty and carry their "
            "measured geometry",
            reason="partial",
            bands=len(bands),
            measured_sections=len(residue),
            contested_band=bands[contested[0]].index,
            contested_bands=[bands[position].index for position in contested],
            bound_bands=[bands[position].index for position in forced],
        )
    )


def _lines_up(residue: list[_Candidate], bands: tuple[MeasuredBand, ...]) -> bool:
    """Is this residue the band sequence exactly — same length, every pair identifiable?"""
    return len(residue) == len(bands) and all(
        _band_matches(candidate, band) for candidate, band in zip(residue, bands)
    )


def _identifies(candidate: _Candidate, band: MeasuredBand) -> bool:
    """Does this candidate account for EVERY class the browser recorded on that band?

    Stronger than :func:`_band_matches`, which asks only for a shared class. The difference is
    the whole of N1: `section hide` and `section` intersect, so a line-up built on intersection
    cannot see that one of them is named exactly and the other merely overlaps.
    """
    if candidate.tag != band.tag:
        return False
    return set(band.class_names) <= set(candidate.class_names)


def _proposal_is_safe(
    proposed: list[_Candidate], removed: list[_Candidate], bands: tuple[MeasuredBand, ...]
) -> bool:
    """Would believing this proposal hand a band to a section the removed one describes better?

    The class hint removes candidates on a GUESS about a stylesheet nobody evaluated, and the
    line-up that is supposed to check the guess compares classes by intersection — so the token
    that distinguishes the removed section (`hide`) is exactly the token the check ignores. A
    section that is really on the page, whose band names it verbatim, could therefore be removed
    and its band handed two positions down the page to a plain sibling: a confident wrong crop,
    with no feasibility argument behind it, on a page the old all-or-nothing rule refused.

    So the proposal is believed only when no removed candidate is a BETTER answer than the one
    taking the band: if a removed candidate accounts for every class the band recorded and the
    proposed owner does not, the hint has been caught contradicting the measurement, and the
    measurement wins. Falling through costs the shortcut and nothing else — the feasibility floor
    below still binds every band that is forced.
    """
    for position, band in enumerate(bands):
        owner = proposed[position]
        if _identifies(owner, band):
            continue
        if any(_identifies(candidate, band) for candidate in removed):
            return False
    return True


def _subtract_skipped(
    measured: list[_Candidate], skipped: tuple[SkippedChild, ...]
) -> tuple[list[_Candidate], bool]:
    """Remove exactly the candidates the browser said it declined to measure.

    In order and once each: the probe walks the same children in the same order this module
    parses them, so a skip record is consumed by the first not-yet-consumed candidate it
    identifies. A record that identifies nothing is simply not subtracted — it costs the
    certainty shortcut, never a wrong removal.
    """
    if not skipped:
        return list(measured), False
    remaining = list(skipped)
    residue: list[_Candidate] = []
    removed = False
    for candidate in measured:
        match = next(
            (record for record in remaining if _skip_matches(candidate, record)), None
        )
        if match is None:
            residue.append(candidate)
            continue
        remaining.remove(match)
        removed = True
    return residue, removed


def _skip_matches(candidate: _Candidate, record: SkippedChild) -> bool:
    """Is this the candidate the probe declined to measure?

    Stricter than :func:`_band_matches` on purpose, and the difference matters. A BAND is matched
    by class INTERSECTION because the page's own JS toggles a class between the html snapshot and
    the probe, and refusing a page's geometry over one modifier would be absurd. A SKIP is a
    subtraction: getting it wrong removes the wrong section from the alignment, so it must carry
    ALL of the record's classes — otherwise a record for `section pricing-not-shown` would
    happily remove the first plain `section` it met. A record that identifies nothing is simply
    not subtracted, which costs the certainty shortcut and nothing else.
    """
    if candidate.tag != record.tag:
        return False
    if record.element_id and candidate.element_id and candidate.element_id != record.element_id:
        return False
    if record.class_names:
        return set(record.class_names) <= set(candidate.class_names)
    return not candidate.class_names


def _greedy_alignment(
    measured: list[_Candidate], bands: tuple[MeasuredBand, ...], *, reverse: bool = False
) -> list[int] | None:
    """Bands ⇒ the index of the section each one binds to, or ``None`` if one matches nothing.

    ``reverse`` walks the same greedy rule from the end of both sequences. Comparing the two
    answers is what makes an ambiguous alignment visible: a sequence with exactly one valid
    alignment produces the same list either way, and one with several does not.
    """
    order = range(len(bands) - 1, -1, -1) if reverse else range(len(bands))
    cursor = len(measured) - 1 if reverse else 0
    out: dict[int, int] = {}
    for position in order:
        band = bands[position]
        while 0 <= cursor < len(measured) and not _band_matches(measured[cursor], band):
            cursor += -1 if reverse else 1
        if not 0 <= cursor < len(measured):
            return None
        out[position] = cursor
        cursor += -1 if reverse else 1
    return [out[position] for position in range(len(bands))]


def _first_unmatched_band(
    measured: list[_Candidate], bands: tuple[MeasuredBand, ...]
) -> int:
    cursor = 0
    for band in bands:
        while cursor < len(measured) and not _band_matches(measured[cursor], band):
            cursor += 1
        if cursor >= len(measured):
            return band.index
        cursor += 1
    return bands[-1].index if bands else -1


def _band_matches(candidate: _Candidate, band: MeasuredBand) -> bool:
    """Is this parsed section the element the browser measured as that band?

    Class lists are compared by INTERSECTION rather than equality on purpose: the capture
    serializes the html before it runs the geometry probe, so the page's own JS can add or drop
    a class in between (a sticky nav gaining ``is-scrolled`` is the everyday case). Sharing a
    class is still decisive — two different sections of a real page do not share their names —
    while demanding an identical list would refuse a whole page's geometry over one toggled
    modifier.
    """
    if candidate.tag != band.tag:
        return False
    if band.element_id and candidate.element_id and candidate.element_id != band.element_id:
        return False
    if band.class_names and candidate.class_names:
        if not set(band.class_names) & set(candidate.class_names):
            return False
    return True


def _assign_geometry(
    candidates: list[_Candidate], viewport_width: int | None, diagnostics: list[dict[str, Any]]
) -> None:
    bound = [candidate for candidate in candidates if candidate.band is not None]
    if not bound:
        return

    estimated = any(band.top_px is None for band in (c.band for c in bound) if band)
    running = 0.0
    for candidate in bound:
        band = candidate.band
        assert band is not None
        top = running if estimated or band.top_px is None else band.top_px
        height = max(0.0, band.height_px)
        candidate.geometry = SectionGeometry(
            top_px=top,
            bottom_px=top + height,
            height_px=height,
            basis="estimated" if estimated else "measured",
            viewport_width=viewport_width,
        )
        running = top + height

    if estimated:
        diagnostics.append(
            _diag(
                ESTIMATED_GEOMETRY_CODE,
                "info",
                "the capture recorded band heights but no absolute tops, so section extents are "
                "the running sum of the band heights from the top of the document",
            )
        )

    unmeasured = [candidate for candidate in candidates if candidate.geometry is None]
    if not unmeasured:
        return

    # Two different facts, and the diagnostic has to keep them apart. A section OUTSIDE the
    # probe's root was never eligible to be measured; a section INSIDE it was eligible and the
    # browser skipped it, which is a statement about the section (hidden, tiny, narrow), not
    # about the root. One sentence covering both would be false about one of them.
    outside = [candidate for candidate in unmeasured if not candidate.in_measured_root]
    inside = [candidate for candidate in unmeasured if candidate.in_measured_root]
    reasons: list[str] = []
    if outside:
        reasons.append(
            f"{len(outside)} sit outside the capture probe's measured root (the probe roots at "
            "<main>, so a page that has one never measures its nav or footer)"
        )
    if inside:
        reasons.append(
            f"{len(inside)} sit inside the measured root and the browser measured no band for "
            "them (it skips a band that is hidden, under 40px tall, or narrower than half the "
            "viewport)"
        )
    diagnostics.append(
        _diag(
            UNMEASURED_SECTION_CODE,
            "info",
            f"{len(unmeasured)} section(s) carry no geometry: " + "; ".join(reasons),
            tags=sorted({candidate.tag for candidate in unmeasured}),
            count=len(unmeasured),
            outside_measured_root=len(outside),
            inside_measured_root=len(inside),
        )
    )


# --- role calling ----------------------------------------------------------------------------


def _call_roles(candidates: list[_Candidate]) -> None:
    for candidate in candidates:
        candidate.evidence.extend(_declared_signals(candidate))
        candidate.evidence.extend(_content_signals(candidate))
    _positional_signals(candidates)

    for candidate in candidates:
        candidate.role, candidate.confidence = _resolve(candidate)
    _enforce_singular_roles(candidates)

    for candidate in candidates:
        candidate.evidence.sort(key=lambda ev: (-ev.weight, ev.signal, ev.role, ev.detail))


def _declared_signals(candidate: _Candidate) -> list[SectionEvidence]:
    """What the markup itself declares: semantic tag, ARIA role, class/id vocabulary."""
    out: list[SectionEvidence] = []
    if candidate.tag == NAV:
        out.append(SectionEvidence("landmark", NAV, LANDMARK_WEIGHT, "<nav> element"))
    elif candidate.tag == "header" and candidate.is_page_scoped:
        out.append(
            SectionEvidence(
                "landmark", NAV, LANDMARK_WEIGHT, "<header> element scoped to the whole page"
            )
        )
    elif candidate.tag == FOOTER and candidate.is_page_scoped:
        out.append(
            SectionEvidence(
                "landmark", FOOTER, LANDMARK_WEIGHT, "<footer> element scoped to the whole page"
            )
        )

    aria = _ARIA_ROLES.get(candidate.aria_role or "")
    if aria:
        out.append(
            SectionEvidence(
                "landmark", aria, LANDMARK_WEIGHT, f'role="{candidate.aria_role}" attribute'
            )
        )

    seen: set[tuple[str, str]] = set()
    for token in candidate.tokens:
        role = _STRONG_TOKEN_HINTS.get(token)
        weight = STRONG_HINT_WEIGHT
        if role is None:
            role = _WEAK_TOKEN_HINTS.get(token)
            weight = WEAK_HINT_WEIGHT
        if role is None or (role, token) in seen:
            continue
        seen.add((role, token))
        out.append(
            SectionEvidence("class-hint", role, weight, f'"{token}" in the class/id vocabulary')
        )
    for phrase, role in _PHRASE_HINTS:
        if phrase in candidate.token_blob:
            out.append(
                SectionEvidence(
                    "class-hint",
                    role,
                    STRONG_HINT_WEIGHT,
                    f'"{phrase}" in the class/id vocabulary',
                )
            )
    return out


def _content_signals(candidate: _Candidate) -> list[SectionEvidence]:
    """What the section's own content says, when nobody declared anything."""
    out: list[SectionEvidence] = []
    if candidate.has_h1:
        out.append(SectionEvidence("content", HERO, HEADLINE_WEIGHT, "carries the page's <h1>"))
    if candidate.has_quote:
        out.append(
            SectionEvidence("content", TESTIMONIAL, CONTENT_WEIGHT, "contains a quotation element")
        )
    security = _SECURITY_TEXT.search(candidate.text)
    if security:
        out.append(
            SectionEvidence(
                "content", SECURITY, CONTENT_WEIGHT, f'compliance language ("{security.group(0)}")'
            )
        )
    proof = _PROOF_TEXT.search(candidate.text)
    if proof:
        out.append(
            SectionEvidence(
                "content", PROOF, CONTENT_WEIGHT, f'proof language ("{proof.group(0)}")'
            )
        )
    if candidate.image_count >= LOGO_WALL_MIN_IMAGES and len(candidate.text) <= LOGO_WALL_MAX_TEXT:
        out.append(
            SectionEvidence(
                "content",
                PROOF,
                CONTENT_WEIGHT,
                f"logo wall shape ({candidate.image_count} images, "
                f"{len(candidate.text)} characters of prose)",
            )
        )
    if _FOOTER_TEXT.search(candidate.text):
        out.append(
            SectionEvidence("content", FOOTER, CONTENT_WEIGHT, "carries a copyright line")
        )
    return out


def _positional_signals(candidates: list[_Candidate]) -> None:
    """Where a section sits, corroborated by its shape or its measured band.

    Position alone says nothing — plenty of pages open on a banner and close on a CTA — so every
    rule here needs a second fact: a link-dense first strip, a short first band, a tall band under
    the page's headline, a link farm with a copyright at the end.
    """
    first = candidates[0]
    declared_nav = [
        index
        for index, candidate in enumerate(candidates)
        if any(ev.role == NAV and ev.weight >= STRONG_HINT_WEIGHT for ev in candidate.evidence)
    ]
    nav_index = declared_nav[0] if declared_nav else None

    if nav_index is None or nav_index == 0:
        if first.link_count >= LINK_DENSE and not first.has_h1:
            first.evidence.append(
                SectionEvidence(
                    "position",
                    NAV,
                    POSITION_WEIGHT,
                    f"first section, {first.link_count} links and no headline",
                )
            )
            nav_index = 0
        if first.band is not None and first.band.height_px < NAV_BAND_MAX_PX:
            first.evidence.append(
                SectionEvidence(
                    "band",
                    NAV,
                    POSITION_WEIGHT,
                    f"first measured band is only {first.band.height_px:g}px tall",
                )
            )
            nav_index = 0

    for index, candidate in enumerate(candidates):
        if nav_index is not None and index <= nav_index:
            continue
        band_height = candidate.band.height_px if candidate.band is not None else 0.0
        tall = candidate.band is not None and band_height >= HERO_BAND_MIN_PX
        if candidate.has_h1 or tall:
            candidate.evidence.append(
                SectionEvidence(
                    "position",
                    HERO,
                    POSITION_WEIGHT,
                    "first content section of the page",
                )
            )
            if tall:
                candidate.evidence.append(
                    SectionEvidence(
                        "band",
                        HERO,
                        POSITION_WEIGHT,
                        f"opening band is {band_height:g}px tall",
                    )
                )
            break

    last = candidates[-1]
    if last is not first and (
        last.link_count >= FOOTER_LINK_DENSE or _FOOTER_TEXT.search(last.text)
    ):
        last.evidence.append(
            SectionEvidence(
                "position",
                FOOTER,
                POSITION_WEIGHT,
                f"last section, {last.link_count} links",
            )
        )


def _resolve(candidate: _Candidate) -> tuple[str, float]:
    """The winning role and its confidence — or ``other`` when the evidence is contested."""
    tallies: dict[str, tuple[float, int]] = {}
    for evidence in candidate.evidence:
        if evidence.weight <= 0:
            continue
        strongest, supporting = tallies.get(evidence.role, (0.0, 0))
        tallies[evidence.role] = (max(strongest, evidence.weight), supporting + 1)

    if not tallies:
        return OTHER, OTHER_CONFIDENCE

    scores = {
        role: min(MAX_CONFIDENCE, strongest + CORROBORATION_BONUS * (supporting - 1))
        for role, (strongest, supporting) in tallies.items()
    }
    ranked = sorted(scores.items(), key=lambda item: (-item[1], SECTION_ROLES.index(item[0])))
    role, score = ranked[0]
    if len(ranked) > 1 and score < LANDMARK_WEIGHT and ranked[1][1] >= score - CONTEST_MARGIN:
        candidate.evidence.append(
            SectionEvidence(
                "resolution",
                OTHER,
                0.0,
                f"contested: {role} ({score:.2f}) vs {ranked[1][0]} ({ranked[1][1]:.2f}) with no "
                "landmark to settle it — named `other` rather than risk the wrong role",
            )
        )
        return OTHER, OTHER_CONFIDENCE
    return role, score


def _enforce_singular_roles(candidates: list[_Candidate]) -> None:
    """A page has one nav, one hero and one footer; the runners-up become ``other``.

    Which one keeps the name is decided by the role's own end of the document (a page's nav and
    hero are its first; its footer is its last) and ties on confidence never arise because the
    keeper is chosen by position, not score.
    """
    for role, which in _SINGULAR_ROLES.items():
        holders = [candidate for candidate in candidates if candidate.role == role]
        if len(holders) < 2:
            continue
        keeper = holders[0] if which == "first" else holders[-1]
        for candidate in holders:
            if candidate is keeper:
                continue
            candidate.evidence.append(
                SectionEvidence(
                    "resolution",
                    OTHER,
                    0.0,
                    f"the page already has a {role} ({which} one wins) — demoted to `other` "
                    "rather than named twice",
                )
            )
            candidate.role = OTHER
            candidate.confidence = OTHER_CONFIDENCE


# --- DOM helpers -----------------------------------------------------------------------------


def _element_children(node: Node) -> list[tuple[int, Node]]:
    """This node's ELEMENT children, index-numbered.

    Comment and text nodes are excluded from the numbering, which is what makes ``dom_path`` a
    handle a human can read and a re-parse can follow.
    """
    out: list[tuple[int, Node]] = []
    for child in node.iter():
        tag = child.tag or ""
        if tag.startswith("_") or tag.startswith("-"):
            continue
        out.append((len(out), child))
    return out


def _first_child_with_tag(node: Node, tag: str) -> tuple[Node, tuple[int, ...]] | None:
    for index, child in _element_children(node):
        if (child.tag or "").lower() == tag:
            return child, (index,)
    return None


def _find_first(
    node: Node | None, path: tuple[int, ...], tag: str
) -> tuple[Node, tuple[int, ...]] | None:
    """Document-order search for the first element with ``tag``, carrying its path."""
    if node is None:
        return None
    for index, child in _element_children(node):
        child_path = path + (index,)
        if (child.tag or "").lower() == tag:
            return child, child_path
        found = _find_first(child, child_path, tag)
        if found is not None:
            return found
    return None


def _is_significant(node: Node) -> bool:
    tag = (node.tag or "").lower()
    if tag in _SKIP_TAGS or tag.startswith("_") or tag.startswith("-"):
        return False
    attributes = node.attributes
    if "hidden" in attributes:
        return False
    if _HIDDEN_STYLE.search(attributes.get("style") or ""):
        return False
    if rendered_text(node):
        return True
    return bool(node.css(_MEDIA_SELECTOR))


def _note_skip(node: Node, skipped: list[tuple[str, str]]) -> None:
    tag = (node.tag or "").lower()
    if tag in _SKIP_TAGS or tag.startswith("_") or tag.startswith("-"):
        return
    skipped.append((tag, rendered_text(node, limit=80)))


def rendered_text(node: Node, *, limit: int | None = None) -> str:
    """The text a visitor would READ — never the source of what the sanitizer will throw away.

    ``selectolax``'s ``text(deep=True)`` returns every text node under an element, which on a
    real page includes ``<script>`` bodies and ``<style>`` rules. The F2 acceptance walk showed
    exactly what that costs: the nav — the single most valuable clone on the page — was labelled
    ``Nav — document.querySelectorAll('.w-dropdown').forEach(dropdown => …``, an empty Webflow
    ``<style>`` embed scored ``security`` @0.65 off a CSS comment, and a ``<script>`` shell was
    admitted as a section because its JavaScript read as prose.

    All three are one defect: the segmenter judged sections by text that will not exist in the
    artifact. This is the one place that answers "what does this element say?", so labels, role
    signals and significance can no longer disagree about it, and none of them can read source.

    ``_SKIP_TAGS`` is the same list every other consumer here uses, so a tag that never renders a
    band also never contributes a word.
    """
    parts: list[str] = []
    _collect_rendered_text(node, parts)
    text = _WHITESPACE.sub(" ", " ".join(parts)).strip()
    return text[:limit] if limit is not None else text


def _collect_rendered_text(node: Node, out: list[str]) -> None:
    for child in node.iter(include_text=True):
        tag = (child.tag or "").lower()
        if tag == "-text":
            fragment = child.text() or ""
            if fragment.strip():
                out.append(fragment)
            continue
        if tag in _SKIP_TAGS or tag.startswith("_") or tag.startswith("-"):
            continue
        _collect_rendered_text(child, out)


def _first_heading(node: Node) -> str | None:
    for tag in ("h1", "h2", "h3"):
        found = node.css_first(tag)
        if found is not None:
            text = rendered_text(found, limit=160)
            if text:
                return text
    return None


def _tokenize(value: str) -> tuple[str, ...]:
    out: list[str] = []
    for token in _TOKEN_SPLIT.split(value.lower()):
        if token and token not in out:
            out.append(token)
    return tuple(out)


def _diag(code: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **extra}
