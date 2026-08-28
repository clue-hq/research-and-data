"""The behavioural review walk — what the page DOES, not only what it looks like (F3.3, D-F6/7).

A cloned homepage can be pixel-plausible in one 1440px screenshot and still be broken: a band
whose scroll-driven content never arrives, a section that disappears on a phone, a control that
throws in the console, three screens of nothing where an animation used to be. Founder ruling
D-F7 makes brokenness the STRICT half of the review, so the review has to be able to see it —
and a screenshot alone cannot.

**Six classes, always all six, always labelled.** :data:`WALK_CLASSES` is the whole vocabulary,
and a :class:`BehaviouralWalk` carries exactly one :class:`WalkObservation` per class, in that
order, whether or not the observation could be made. A class that could not be observed says so
(``made=False`` plus a ``because`` code); it never comes back missing and it never comes back
empty-but-present, because "we did not look" and "we looked and it was fine" are different
answers and only one of them is a clean bill. This is the same distinction
``sections/deadheight.py`` draws with ``DeadHeightAssessment.judged``, for the same reason.

**Two halves, and the seam between them is the point** — the shape ``fragments/isolation.py``
established in F3.2. :func:`walk_plan` composes what will be captured and
:data:`SECTION_PROBE_SCRIPT` is the measurement, both of them browserless and both directly
testable; :func:`capture_behavioural_walk` is the browser half, and it is what raises when there
is no browser. Nothing in this package imports Playwright at module scope, so the plan, the
probe's shape and every judgement over its numbers are exercised with no chromium at all.

**Nothing here decides anything.** The walk MEASURES: heights, extents, viewport overflow,
console lines, document heights with and without motion. What those numbers mean is
:mod:`lumen_api.clone_review.findings`' business, and what to do about them is the reviewing
agent's, under the shared rubric. Keeping the two apart is what lets the same numbers be read by
a reviewer subagent and by an orchestrator self-reviewing behind the fast-loop flag without
either of them being able to measure differently from the other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- the six classes ---------------------------------------------------------------------------

#: (a) the full-page screenshot at desktop width — the one the reference comparison is made of.
WALK_CLASS_FULL_PAGE = "full_page"
#: (b) the scroll-through: the viewport at several positions down the page, each after settling,
#: so sticky chrome, in-view transitions and lazily-revealed content are photographed in the
#: state a reader actually meets them in.
WALK_CLASS_SCROLL_THROUGH = "scroll_through"
#: (c) the mobile viewport, at the platform's own phone width.
WALK_CLASS_MOBILE = "mobile"
#: (d) console errors and uncaught page errors, collected for the whole walk.
WALK_CLASS_CONSOLE = "console"
#: (e) the artificial-height-collapse check — the runtime sibling of the mint-time dead-height
#: detector, measured in the DOM rather than in pixels.
WALK_CLASS_HEIGHT_COLLAPSE = "height_collapse"
#: (f) the reduced-motion variant: the same page under ``prefers-reduced-motion: reduce``.
WALK_CLASS_REDUCED_MOTION = "reduced_motion"

#: Every class, in walk order. A :class:`BehaviouralWalk` carries exactly one observation per
#: entry — the invariant is enforced in ``__post_init__``, not merely intended.
WALK_CLASSES = (
    WALK_CLASS_FULL_PAGE,
    WALK_CLASS_SCROLL_THROUGH,
    WALK_CLASS_MOBILE,
    WALK_CLASS_CONSOLE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_REDUCED_MOTION,
)

#: What each class is called when an agent or a human reads the result. Written as the thing that
#: was looked at, not as the name of a code path.
WALK_CLASS_LABELS = {
    WALK_CLASS_FULL_PAGE: "full-page screenshot at desktop width",
    WALK_CLASS_SCROLL_THROUGH: "scroll-through capture at several positions",
    WALK_CLASS_MOBILE: "mobile viewport",
    WALK_CLASS_CONSOLE: "console errors",
    WALK_CLASS_HEIGHT_COLLAPSE: "artificial-height-collapse check",
    WALK_CLASS_REDUCED_MOTION: "reduced-motion variant",
}

#: Bumped to 2 in the round-2 fix: an observation's ``measurements`` gained ``measured`` and a
#: console entry gained ``source``. Additive, but a reader that branched on either would misread a
#: v1 payload as "measured, page-attributed" by omission, which is the thing a version exists to
#: prevent.
WALK_SCHEMA_VERSION = 2


# --- viewports and stops -----------------------------------------------------------------------


@dataclass(frozen=True)
class ViewportSpec:
    """One viewport the walk opens, and the name it is reported under."""

    name: str
    width: int
    height: int


#: The desktop width. 1440 because that is the width F0's reference screenshot was captured at and
#: the width CP1's acceptance is stated at — a comparison between two different widths would be
#: measuring the layout's responsiveness rather than the clone's fidelity.
DESKTOP_VIEWPORT = ViewportSpec("desktop", 1440, 900)

#: The platform's standard mobile width. 375 is not a fresh choice here: it is the narrowest of
#: the three widths every web preview is already captured at (``_PREVIEW_WIDTHS`` in the agent
#: substrate) and the width the reviewer's own checklist judges the phone layout at. Naming it
#: here rather than inventing a second phone width is what keeps the gate's mobile verdict and
#: the reviewer's mobile screenshot talking about the same page. A drift guard in the agent
#: runtime's tests pins the two together.
MOBILE_VIEWPORT = ViewportSpec("mobile", 375, 812)

#: Where the scroll-through stops, as fractions of the scrollable height. Five stops: the top and
#: the bottom are the two positions a reader is guaranteed to see, and the three between them are
#: what catches a band that only misbehaves once it is on screen. A fixed, small list — the walk
#: is a gate, not a video.
SCROLL_STOPS = (0.0, 0.25, 0.5, 0.75, 1.0)

#: How long the page is given to settle after a navigation or a scroll before it is photographed.
#: The same 400ms the agent's own preview pass waits, for the same reason: fonts, images and
#: CSS transitions all land inside it, and a screenshot taken before they do reports a defect
#: that does not exist.
SETTLE_MS = 400

#: How long a probe pass WAITS for the shell's Tailwind JIT to compile this page's utilities
#: before calling the evidence unsettled (ruling R19-1; round-2 re-review breakage #2). Five
#: seconds is generous for a cold compile on a loaded host and a small fraction of the walk
#: ceiling below, so a page that will never be ready costs this once per probe pass rather than
#: holding a turn open.
STYLES_READY_TIMEOUT_MS = 5_000

#: The whole walk's per-operation ceiling. Generous, because a long cloned page carries real
#: bytes; bounded, because a wedged browser must not hold a turn open.
WALK_TIMEOUT_MS = 30_000


# --- what is measured --------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionProbe:
    """One pinned clone on the page, and the selector its band renders under."""

    fragment_id: str
    selector: str


@dataclass(frozen=True)
class WalkPlan:
    """Everything the walk will do, decided before a browser is opened.

    Composed by :func:`walk_plan` and handed to the browser half whole, so what was ATTEMPTED is
    knowable from the plan alone — including on the walk that could not run.
    """

    sections: tuple[SectionProbe, ...]
    desktop: ViewportSpec = DESKTOP_VIEWPORT
    mobile: ViewportSpec = MOBILE_VIEWPORT
    scroll_stops: tuple[float, ...] = SCROLL_STOPS
    settle_ms: int = SETTLE_MS

    @property
    def classes(self) -> tuple[str, ...]:
        return WALK_CLASSES

    def as_result(self) -> dict[str, Any]:
        return {
            "classes": list(WALK_CLASSES),
            "sections": [
                {"fragment_id": probe.fragment_id, "selector": probe.selector}
                for probe in self.sections
            ],
            "desktop": {"width": self.desktop.width, "height": self.desktop.height},
            "mobile": {"width": self.mobile.width, "height": self.mobile.height},
            "scroll_stops": list(self.scroll_stops),
        }


def walk_plan(
    sections: Sequence[SectionProbe] | Sequence[Mapping[str, Any]] = (),
    *,
    desktop: ViewportSpec = DESKTOP_VIEWPORT,
    mobile: ViewportSpec = MOBILE_VIEWPORT,
    scroll_stops: Sequence[float] = SCROLL_STOPS,
) -> WalkPlan:
    """The plan for one page, from the clones pinned on it.

    A page with NO pinned clones is a legitimate plan, not an error: the page-level halves of the
    walk (console, reduced motion, the reference comparison) are exactly as meaningful there, and
    the per-band halves honestly measure nothing.
    """
    probes: list[SectionProbe] = []
    for entry in sections:
        if isinstance(entry, SectionProbe):
            probes.append(entry)
            continue
        fragment_id = str(entry.get("fragment_id") or "").strip()
        selector = str(entry.get("selector") or "").strip()
        if fragment_id and selector:
            probes.append(SectionProbe(fragment_id=fragment_id, selector=selector))
    stops = tuple(
        sorted({min(1.0, max(0.0, float(stop))) for stop in scroll_stops})
    ) or SCROLL_STOPS
    return WalkPlan(
        sections=tuple(probes), desktop=desktop, mobile=mobile, scroll_stops=stops
    )


@dataclass(frozen=True)
class SectionMeasurement:
    """One band, measured in one viewport. Numbers only — no verdict.

    ``content_extent_px`` is the vertical distance from the top of the band's first visible ink
    to the bottom of its last, which is deliberately the same question the mint-time detector
    asks of a crop's rows: how much of this band's scroll cost has anything in it at all. A COUNT
    of ink would call an ordinary hero mostly empty; the extent does not.
    """

    fragment_id: str
    selector: str
    viewport: str
    present: bool
    #: Whether the probe actually brought numbers back for this band (review finding I2).
    #:
    #: Separate from ``present`` because they fail differently and mean different things. A band
    #: that is not on the page is an editorial fact; a band that IS on the page and came back
    #: without its numbers is a MEASUREMENT that did not happen — and every number below then
    #: defaults to zero, which reads as "renders nothing at all" and would convict a healthy band
    #: of ``blank_render``. The absence of a measurement must never become a verdict, so this
    #: flag gates every judgement in `findings.py` and the gap is reported as advice instead.
    measured: bool = True
    visible: bool = False
    #: Where the band's box starts, in page coordinates. Carried because the reference
    #: comparison has to crop OUR capture at the same band it crops the reference at, and the
    #: only honest source for "where is this band on our page" is where the browser put it.
    top_px: float = 0.0
    width_px: float = 0.0
    height_px: float = 0.0
    content_extent_px: float = 0.0
    ink_nodes: int = 0
    scroll_width_px: float = 0.0
    #: The largest INTERNAL ink-free run inside the band, in CSS px (phase fix wave, walk
    #: finding F-1): the extent above is structurally blind to a hole in the middle of a band
    #: with content at both ends, and the walk's one real defect was exactly that shape. The
    #: probe computes it by merging every ink rect's vertical interval and taking the widest
    #: gap between merged intervals — the same question the mint detector's row-gap measure
    #: asks of a crop, so the two detectors keep their stated agreement.
    largest_gap_px: float = 0.0

    @property
    def content_fraction(self) -> float:
        """How much of the band's height its visible content spans. 0.0 for a band with no box —
        which is a blankness finding, and is reported as one rather than as a division."""
        if self.height_px <= 0:
            return 0.0
        return min(1.0, self.content_extent_px / self.height_px)

    def as_result(self) -> dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "selector": self.selector,
            "viewport": self.viewport,
            "present": self.present,
            "measured": self.measured,
            "visible": self.visible,
            "top_px": round(self.top_px, 1),
            "width_px": round(self.width_px, 1),
            "height_px": round(self.height_px, 1),
            "content_extent_px": round(self.content_extent_px, 1),
            "content_fraction": round(self.content_fraction, 4),
            "ink_nodes": self.ink_nodes,
            "scroll_width_px": round(self.scroll_width_px, 1),
            "largest_gap_px": round(self.largest_gap_px, 1),
        }


#: What a console entry is blamed on.
#:
#: The distinction is forced by a fact about the walked page (review finding I1): it is the
#: EDITOR render, which carries our vendored Tailwind browser JIT as an inline ``<script>``. A
#: cloned band, by contrast, carries no scripts at all — the mint sanitizer strips ``script`` and
#: every ``on*`` handler, fail-closed — so on this page **every script-originated console line is
#: OURS**, and the only console lines the page's own content can produce are resource-load
#: failures, which name the failing resource's url.
#:
#: That is the discriminator, and it is a consequence rather than a heuristic: an entry with no
#: url, or whose url is the document itself, came from the only scripts present, which are the
#: preview shell's. An entry naming a fetched resource is the page's own.
CONSOLE_SOURCE_PAGE = "page"
CONSOLE_SOURCE_SHELL = "shell"

#: Urls that mean "the document itself" rather than "a resource this page fetched". A page loaded
#: through ``set_content`` has no document url, so an inline script's errors are reported against
#: one of these (or against nothing at all).
_DOCUMENT_URLS = ("", "about:blank", "about:srcdoc")


def console_source(url: str | None) -> str:
    """Whose console line is this — the page's, or the preview shell's? See above."""
    if not url or url.strip().lower() in _DOCUMENT_URLS:
        return CONSOLE_SOURCE_SHELL
    return CONSOLE_SOURCE_PAGE


@dataclass(frozen=True)
class ConsoleEntry:
    """One line the page put on the console, with where it came from."""

    level: str
    text: str
    url: str | None = None
    line: int | None = None
    #: Which pass produced it — the walk visits the page several times and a phone-only error is
    #: a different fact from one that fires everywhere.
    pass_name: str = DESKTOP_VIEWPORT.name

    @property
    def source(self) -> str:
        return console_source(self.url)

    def as_result(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "text": self.text,
            "url": self.url,
            "line": self.line,
            "pass": self.pass_name,
            "source": self.source,
        }


@dataclass(frozen=True)
class CaptureShot:
    """One photograph the walk took, and what it is a photograph OF."""

    walk_class: str
    label: str
    path: str
    viewport_width: int
    scroll_fraction: float | None = None

    def as_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "class": self.walk_class,
            "label": self.label,
            "path": self.path,
            "viewport_width": self.viewport_width,
        }
        if self.scroll_fraction is not None:
            result["scroll_fraction"] = self.scroll_fraction
        return result


@dataclass(frozen=True)
class WalkObservation:
    """One of the six classes, observed or honestly not.

    ``made=False`` carries ``because`` and nothing else. It is never dressed up as an empty
    success: a caller that reads ``console=[]`` off an observation that was never made would be
    reporting "zero console errors" about a page nobody opened.
    """

    walk_class: str
    made: bool
    because: str | None = None
    shots: tuple[CaptureShot, ...] = ()
    measurements: tuple[SectionMeasurement, ...] = ()
    console: tuple[ConsoleEntry, ...] = ()
    notes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return WALK_CLASS_LABELS.get(self.walk_class, self.walk_class)

    def as_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "class": self.walk_class,
            "label": self.label,
            "made": self.made,
        }
        if not self.made:
            result["because"] = self.because or "unknown"
            return result
        if self.shots:
            result["shots"] = [shot.as_result() for shot in self.shots]
        if self.measurements:
            result["measurements"] = [item.as_result() for item in self.measurements]
        if self.walk_class == WALK_CLASS_CONSOLE:
            result["entries"] = [entry.as_result() for entry in self.console]
        if self.notes:
            result["notes"] = dict(self.notes)
        return result


def abstained(walk_class: str, because: str) -> WalkObservation:
    """The honest empty answer for one class. Named, so no caller invents its own shape."""
    return WalkObservation(walk_class=walk_class, made=False, because=because)


@dataclass(frozen=True)
class BehaviouralWalk:
    """What one walk of one rendered page saw — all six classes, in order.

    The invariant is checked here rather than trusted: a walk that quietly omitted the mobile
    class would read, downstream, as a page with no mobile problems.
    """

    observations: tuple[WalkObservation, ...]
    plan: WalkPlan | None = None

    def __post_init__(self) -> None:
        seen = tuple(observation.walk_class for observation in self.observations)
        if seen != WALK_CLASSES:
            raise ValueError(
                "a behavioural walk carries exactly one observation per class, in walk order "
                f"{WALK_CLASSES!r}; got {seen!r}"
            )

    def by_class(self, walk_class: str) -> WalkObservation:
        for observation in self.observations:
            if observation.walk_class == walk_class:
                return observation
        raise KeyError(walk_class)

    @property
    def abstentions(self) -> tuple[WalkObservation, ...]:
        return tuple(item for item in self.observations if not item.made)

    def as_result(self) -> dict[str, Any]:
        return {
            "schema_version": WALK_SCHEMA_VERSION,
            "plan": self.plan.as_result() if self.plan is not None else None,
            "observations": [item.as_result() for item in self.observations],
        }


class CloneReviewRefused(RuntimeError):
    """The walk could not be made at all. Carries a code the surface maps, never a fake capture.

    The mirror of :class:`~lumen_api.fragments.isolation.IsolationRenderFailed`, and for the same
    reason: a review gate that answered "no problems found" because it never opened a browser
    would be the single most dangerous output in this phase.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


#: The refusal a missing browser raises. One code, so a caller can tell "this deployment has no
#: chromium" from "this page broke the browser".
BROWSER_UNAVAILABLE_CODE = "review.browser_unavailable"
WALK_FAILED_CODE = "review.walk_failed"


# --- the measurement, as it runs in the page ----------------------------------------------------

#: What counts as INK: something a reader can actually see. Media and controls by tag; anything
#: else has to either directly contain non-whitespace text or carry a background IMAGE.
#:
#: A background GRADIENT is deliberately not ink, and that is the one judgement call in this
#: script. It matches the mint-time detector exactly: that one counts a row as content when its
#: pixels vary ACROSS the width, which a photograph does and a vertical gradient does not — so a
#: full-bleed photographic background keeps a band alive in both detectors, and 3000px of brand
#: navy under a gradient is dead in both. Two detectors that disagreed about the same band would
#: be worse than either of them alone.
SECTION_PROBE_SCRIPT = """
(probes) => {
  const INK_TAGS = 'img,svg,video,canvas,picture,iframe,input,button,select,textarea';
  const invisible = (style) =>
    style.display === 'none' ||
    style.visibility === 'hidden' ||
    Number(style.opacity) === 0;
  return probes.map((probe) => {
    const el = document.querySelector(probe.selector);
    if (!el) {
      return { fragment_id: probe.fragment_id, selector: probe.selector, present: false };
    }
    const rect = el.getBoundingClientRect();
    const own = getComputedStyle(el);
    const pageTop = rect.top + window.scrollY;
    let inkTop = null;
    let inkBottom = null;
    let inkNodes = 0;
    const intervals = [];
    const considerRect = (r) => {
      if (r.width <= 0 || r.height <= 0) return;
      const top = r.top + window.scrollY;
      const bottom = r.bottom + window.scrollY;
      inkNodes += 1;
      if (inkTop === null || top < inkTop) inkTop = top;
      if (inkBottom === null || bottom > inkBottom) inkBottom = bottom;
      intervals.push([top, bottom]);
    };
    const consider = (node) => {
      const s = getComputedStyle(node);
      if (invisible(s)) return;
      considerRect(node.getBoundingClientRect());
    };
    const hasDirectText = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 3 && child.textContent.trim().length > 0) return true;
      }
      return false;
    };
    const hasBackgroundImage = (style) => {
      const bg = style.backgroundImage || 'none';
      return bg !== 'none' && bg.indexOf('url(') !== -1;
    };
    // --- the WRAPPER itself -------------------------------------------------------------------
    // It is asked, because `cssscope` rewrites a source page's `:root`/`html`/`body` declarations
    // onto this class, so a band whose only visible content is a full-bleed background image
    // lands its ink exactly here (review finding M1) — but it is asked CAREFULLY, because its box
    // IS the band (round-2 re-review, breakage #3). Letting the wrapper's rect set the ink extent
    // made `content_fraction` exactly 1.0 for any band with a stray text node on it, which turned
    // dead-height detection off for that band entirely — the one defect D-F6 calls never
    // acceptable at any rung.
    //
    // So the two cases are separated by what they actually cover:
    //   * a background IMAGE covers the whole box, so the whole box is genuinely ink (this is
    //     also what the mint's pixel detector sees: every row of a photograph varies);
    //   * DIRECT TEXT covers only the text, so each text node is measured through a Range and
    //     contributes its own rect. The wrapper still counts toward `ink_nodes` — it is not a
    //     blank band — while 3000px of emptiness below the words stays emptiness.
    if (!invisible(own)) {
      if (el.matches(INK_TAGS) || hasBackgroundImage(own)) {
        considerRect(el.getBoundingClientRect());
      } else if (hasDirectText(el)) {
        for (const child of el.childNodes) {
          if (child.nodeType !== 3 || child.textContent.trim().length === 0) continue;
          const range = document.createRange();
          range.selectNode(child);
          considerRect(range.getBoundingClientRect());
          range.detach && range.detach();
        }
      }
    }
    // --- everything inside it ------------------------------------------------------------------
    el.querySelectorAll('*').forEach((node) => {
      const s = getComputedStyle(node);
      if (node.matches(INK_TAGS) || hasBackgroundImage(s) || hasDirectText(node)) {
        consider(node);
      }
    });
    const clamp = (value) => Math.max(pageTop, Math.min(pageTop + rect.height, value));
    const extent =
      inkTop === null || inkBottom === null ? 0 : clamp(inkBottom) - clamp(inkTop);
    // The largest INTERNAL ink-free run (walk finding F-1): merge every ink interval, then take
    // the widest gap BETWEEN merged intervals — internal by construction, so the band's top and
    // bottom padding never enter. This is the same question the mint detector's row-gap measure
    // asks of a crop; the two detectors state in their docs that they must agree.
    let largestGap = 0;
    if (intervals.length > 1) {
      const clamped = intervals
        .map(([t, b]) => [clamp(t), clamp(b)])
        .filter(([t, b]) => b > t)
        .sort((a, b) => a[0] - b[0]);
      let coveredTo = null;
      for (const [t, b] of clamped) {
        if (coveredTo !== null && t > coveredTo) {
          const gap = t - coveredTo;
          if (gap > largestGap) largestGap = gap;
        }
        if (coveredTo === null || b > coveredTo) coveredTo = b;
      }
    }
    return {
      fragment_id: probe.fragment_id,
      selector: probe.selector,
      present: true,
      visible: !invisible(own) && rect.width > 0 && rect.height > 0,
      top_px: pageTop,
      width_px: rect.width,
      height_px: rect.height,
      content_extent_px: Math.max(0, extent),
      ink_nodes: inkNodes,
      scroll_width_px: el.scrollWidth,
      largest_gap_px: largestGap,
    };
  });
}
"""

#: The attribute the preview shell stamps on the ``<script>`` it injects to carry the Tailwind
#: browser JIT. Declared HERE, in the module the predicate below lives in, because the two are one
#: mechanism: the renderer that stamps it (``LumenWebTools._render_page_html``) and the check that
#: looks for it must never be able to disagree about the spelling.
TAILWIND_RUNTIME_MARKER = "data-lumen-tailwind-runtime"

#: Has the preview shell's Tailwind JIT finished compiling this page's utilities? (Review finding
#: I1(b), ruling R19-1: a DURABLE degraded write requires SETTLED evidence.)
#:
#: **Anchored on OUR OWN script element, and this is the whole correction** (round-2 re-review,
#: breakage #1). The first version of this predicate asked "is head's last element child an
#: untyped, non-empty ``<style>``?", which is sound while the runtime is present and catastrophic
#: when it is not: the engine's editor-mode head ends with an unconditional untyped ``@layer
#: base`` block (`crates/lumen-web/src/render.rs`), so a page with the runtime MISSING — and no
#: utility CSS at all — answered ``true``. It failed OPEN, in exactly the case the ruling exists
#: to catch, and the vendored runtime is untracked in git, so runtime-absent is a reachable
#: deployment state rather than a hypothetical.
#:
#: The rule is now: find the script we injected; then look for an untyped, non-empty ``<style>``
#: that FOLLOWS it. The vendored runtime creates exactly one ``<style>`` and its final synchronous
#: statement is ``document.head.append(fr)``, so the compiled output can only ever land after our
#: script — and every style the engine emitted is before it. With no runtime there is no anchor
#: and the answer is ``false``, permanently, which is what "fail closed" means here.
#:
#: The answer is deliberately TRI-STATE at the Python boundary. ``false`` and ``null`` (the check
#: could not run) both mean **not settled**, and a not-settled walk writes no durable marker at
#: all — it reports the same findings as advice. Every way this signal can be wrong therefore errs
#: toward writing nothing.
#: (Substituted with `str.replace`, not ``%``-formatting: this body is JavaScript, and any future
#: ``%`` inside it — a `width: 100%`, a `%c` console format — would break the module at import.)
STYLES_READY_SCRIPT = """
() => {
  const head = document.head;
  if (!head) return false;
  const runtime = head.querySelector('script[__MARKER__]');
  if (!runtime) return false;
  let node = runtime.nextElementSibling;
  while (node) {
    if (
      node.tagName === 'STYLE' &&
      !node.getAttribute('type') &&
      (node.textContent || '').trim().length > 0
    ) {
      return true;
    }
    node = node.nextElementSibling;
  }
  return false;
}
""".replace("__MARKER__", TAILWIND_RUNTIME_MARKER)

#: The document's own scroll height, read once per pass. The reduced-motion comparison is made of
#: it: a page whose content only exists once an animation has run is SHORTER with motion off.
DOCUMENT_HEIGHT_SCRIPT = (
    "() => ({ height: document.documentElement.scrollHeight,"
    " width: document.documentElement.scrollWidth,"
    " viewport: window.innerWidth })"
)


def measurements_from_probe(
    raw: Sequence[Mapping[str, Any]], *, viewport: str
) -> tuple[SectionMeasurement, ...]:
    """Turn the probe's raw rows into measurements, tolerating a row that is not what we expect.

    Written total on purpose. The script runs in a page whose markup came off somebody else's
    website; a row that comes back with a missing key must produce an honest "not present"
    measurement, not an exception that voids the whole walk.
    """
    measurements: list[SectionMeasurement] = []
    for row in raw or ():
        if not isinstance(row, Mapping):
            continue
        fragment_id = str(row.get("fragment_id") or "")
        selector = str(row.get("selector") or "")
        if not fragment_id:
            continue
        if not row.get("present"):
            measurements.append(
                SectionMeasurement(
                    fragment_id=fragment_id,
                    selector=selector,
                    viewport=viewport,
                    present=False,
                    measured=False,
                )
            )
            continue
        numbers = {key: _maybe_number(row.get(key)) for key in MEASURED_KEYS}
        if any(value is None for value in numbers.values()):
            # Present, and not measured. Reported as such rather than defaulted to zeros: every
            # judgement in `findings.py` reads these numbers, and a zero height with no ink is
            # exactly the shape of `blank_render` (review finding I2).
            measurements.append(
                SectionMeasurement(
                    fragment_id=fragment_id,
                    selector=selector,
                    viewport=viewport,
                    present=True,
                    measured=False,
                    visible=bool(row.get("visible")),
                )
            )
            continue
        measurements.append(
            SectionMeasurement(
                fragment_id=fragment_id,
                selector=selector,
                viewport=viewport,
                present=True,
                measured=True,
                visible=bool(row.get("visible")),
                top_px=_maybe_number(row.get("top_px")) or 0.0,
                width_px=numbers["width_px"] or 0.0,
                height_px=numbers["height_px"] or 0.0,
                content_extent_px=numbers["content_extent_px"] or 0.0,
                ink_nodes=int(numbers["ink_nodes"] or 0.0),
                scroll_width_px=numbers["scroll_width_px"] or 0.0,
                largest_gap_px=numbers["largest_gap_px"] or 0.0,
            )
        )
    return tuple(measurements)


#: The numbers a `present` row MUST carry before any verdict may be read off it. ``top_px`` is not
#: among them: zero is a legitimate value for a band at the top of the page, and nothing judges it
#: — it exists so the reference comparison can crop our capture where the browser put the band.
MEASURED_KEYS = (
    "width_px",
    "height_px",
    "content_extent_px",
    "ink_nodes",
    "scroll_width_px",
    "largest_gap_px",
)


def _maybe_number(value: Any) -> float | None:
    """A finite float, or ``None`` for "this is not a number I can use".

    ``None`` rather than ``0.0`` is the whole of review finding I2: a default silently turns a
    missing measurement into the most damning measurement there is.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return number


# --- the browser half ----------------------------------------------------------------------------


def capture_behavioural_walk(
    page_html: str,
    plan: WalkPlan,
    *,
    output_dir: str | Path,
    browser_factory: Any = None,
) -> BehaviouralWalk:
    """Walk one rendered page in a real browser and bring back all six classes.

    ``page_html`` is the page as it will be seen — the caller renders it (the engine's own
    delivery/editor render, with the fragment map and stylesheet already resolved) and this
    function does not compose, rewrite or invent a single byte of it. What is walked is what was
    rendered, which is the only reason the verdicts mean anything.

    ``browser_factory`` is the injection seam (review finding I3): a callable returning a
    context-managed browser handle. ``None`` — every production caller — means "launch chromium",
    and is the only path that probes for Playwright at all, so a test supplying a fake never
    needs one installed.

    Raises :class:`CloneReviewRefused` when there is no browser to walk with, and when the walk
    itself fails outright. A partial walk does NOT raise: each class that could not be observed
    comes back abstained, because a mobile pass that timed out must not throw away a desktop pass
    that succeeded.
    """
    from .browser import chromium_browser, run_walk  # lazy: no Playwright in this import graph

    if browser_factory is None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception as error:  # noqa: BLE001 — one refusal, whatever the import fault is
            raise CloneReviewRefused(
                BROWSER_UNAVAILABLE_CODE,
                f"the behavioural review walk needs a browser and playwright is not available: "
                f"{error}",
            ) from error
        browser_factory = chromium_browser

    try:
        return run_walk(
            page_html, plan, output_dir=Path(output_dir), browser_factory=browser_factory
        )
    except CloneReviewRefused:
        raise
    except Exception as error:  # noqa: BLE001 — a browser fault is one refusal to the caller
        raise CloneReviewRefused(
            WALK_FAILED_CODE,
            f"the behavioural review walk could not be completed: "
            f"{type(error).__name__}: {error}",
        ) from error


__all__ = [
    "BROWSER_UNAVAILABLE_CODE",
    "DESKTOP_VIEWPORT",
    "CONSOLE_SOURCE_PAGE",
    "CONSOLE_SOURCE_SHELL",
    "DOCUMENT_HEIGHT_SCRIPT",
    "MEASURED_KEYS",
    "MOBILE_VIEWPORT",
    "SCROLL_STOPS",
    "SECTION_PROBE_SCRIPT",
    "SETTLE_MS",
    "STYLES_READY_SCRIPT",
    "STYLES_READY_TIMEOUT_MS",
    "TAILWIND_RUNTIME_MARKER",
    "WALK_CLASSES",
    "WALK_CLASS_CONSOLE",
    "WALK_CLASS_FULL_PAGE",
    "WALK_CLASS_HEIGHT_COLLAPSE",
    "WALK_CLASS_LABELS",
    "WALK_CLASS_MOBILE",
    "WALK_CLASS_REDUCED_MOTION",
    "WALK_CLASS_SCROLL_THROUGH",
    "WALK_FAILED_CODE",
    "WALK_SCHEMA_VERSION",
    "WALK_TIMEOUT_MS",
    "BehaviouralWalk",
    "CaptureShot",
    "CloneReviewRefused",
    "ConsoleEntry",
    "SectionMeasurement",
    "SectionProbe",
    "ViewportSpec",
    "WalkObservation",
    "WalkPlan",
    "abstained",
    "capture_behavioural_walk",
    "console_source",
    "measurements_from_probe",
    "walk_plan",
]
