"""What the walk's numbers MEAN — the gate's judgements, and the advice it hands the agent (F3.3).

Two kinds of output, and the difference between them is a standing carve-out, not a detail:

* **Findings about a CLONE are durable.** A band that renders blank, collapses to dead height, or
  breaks on a phone is a fact about the artifact, and it is written to the fragment's ``degraded``
  marker with one of the gate's own reason codes (:data:`~lumen_api.fragments.degraded.GATE_REASONS`)
  so the next turn's discovery, the repair ladder and the inspector card all see it. The MODEL
  does not choose these: they are computed here from measured numbers, and the write refuses any
  reason the gate does not own. An agent cannot argue a band into being broken, or out of it.
* **Findings about the PAGE are advice.** Console errors, a reduced-motion divergence, a
  reference comparison that has drifted — these are structured critique for the reviewing agent
  to read under the shared rubric. They never block a publish by themselves (the standing
  advice-only carve-out), and :func:`safe_critique` guarantees that a critique that cannot even
  be composed degrades to advice-absent with a loud diagnostic rather than ending a run.

**The thresholds are the mint-time detector's, imported rather than restated.** "Vastly
exceeding" was given a number in F3.0 (``DEAD_HEIGHT_MIN_SECTION_PX`` /
``DEAD_HEIGHT_MAX_CONTENT_FRACTION``) after an argument about false positives; the runtime half
of the same D-F6 trigger asking a different question with a different number would mean a band
could be dead at mint and healthy at review, or the reverse, with nobody able to say which was
right.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lumen_ingestion.sections.deadheight import (
    DEAD_HEIGHT_MAX_CONTENT_FRACTION,
    DEAD_HEIGHT_MAX_GAP_PX,
    DEAD_HEIGHT_MIN_SECTION_PX,
)

from ..fragments.degraded import (
    DEGRADED_REASON_BLANK_RENDER,
    DEGRADED_REASON_MOBILE_UNUSABLE,
    DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
    degraded_headline,
)
from .walk import (
    CONSOLE_SOURCE_SHELL,
    WALK_CLASS_CONSOLE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_MOBILE,
    WALK_CLASS_REDUCED_MOTION,
    BehaviouralWalk,
    ConsoleEntry,
    SectionMeasurement,
)

#: Bumped to 2 in the round-2 fix: the critique gained `evidence_settled`, and a measurement
#: gained `measured`. A reader branching on the first would read a v1 critique as settled.
#: Bumped to 3 in the phase fix wave: a measurement gained `largest_gap_px` (the F-1 second
#: dead-height condition), and its absence in an older row means "not measured that way", not 0.
CRITIQUE_SCHEMA_VERSION = 3

#: A band shorter than this at mobile width has effectively collapsed. Four pixels rather than
#: zero: a band whose only remaining content is a hairline border is not a band.
MIN_USABLE_HEIGHT_PX = 4.0

#: How far a band may exceed the phone's viewport before it counts as overflowing. Five percent,
#: not a pixel or two: sub-pixel layout rounding and a scrollbar-less headless viewport routinely
#: produce a 1–2px excess on a perfectly usable band, and a gate that marked those broken would
#: be marking most of the web broken. At 5% of 375px (~19px) the content is genuinely off-screen.
MOBILE_OVERFLOW_TOLERANCE = 1.05

#: How much SHORTER a page may become with motion switched off before it is worth saying out
#: loud. Ten percent: a page that loses a tenth of its height under ``prefers-reduced-motion`` is
#: a page whose content depends on animation having run, which is the exact class D-F6 is about.
#: Advice rather than a durable marker — the divergence is a fact about the PAGE, and which band
#: caused it is not something this measurement can say.
REDUCED_MOTION_HEIGHT_TOLERANCE = 0.10


@dataclass(frozen=True)
class BrokenClone:
    """One clone the gate measured as broken, with the numbers and the reason code it will write."""

    fragment_id: str
    reason: str
    #: The numbers behind the verdict, so a repair can be argued with rather than merely obeyed —
    #: the same courtesy the mint detector's ``provenance_json["degraded"]`` extends.
    measurement: Mapping[str, Any]

    @property
    def headline(self) -> str:
        return degraded_headline(self.reason)

    def as_result(self) -> dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "reason": self.reason,
            "headline": self.headline,
            "measurement": dict(self.measurement),
        }


@dataclass(frozen=True)
class PageFinding:
    """One thing worth telling the reviewing agent about the page. ADVICE, always."""

    code: str
    severity: str
    message: str
    detail: Mapping[str, Any] | None = None

    def as_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.detail:
            result["detail"] = dict(self.detail)
        return result


# --- per-clone verdicts ---------------------------------------------------------------------------


def _blank(measurement: SectionMeasurement) -> bool:
    """Does this band show a reader nothing at all?"""
    if not measurement.present or not measurement.measured:
        # Absent from the DOM is NOT a brokenness verdict about the artifact: the commonest cause
        # is that the band is no longer pinned on the page being walked, which is an author's
        # decision, not a defect. A band the probe could not measure is not a verdict either
        # (review finding I2) — its numbers would all be zero, which is precisely the shape of
        # this finding. Both are reported as page findings instead.
        return False
    if not measurement.visible:
        return True
    if measurement.height_px < MIN_USABLE_HEIGHT_PX:
        return True
    return measurement.ink_nodes == 0


def _collapsed(measurement: SectionMeasurement) -> bool:
    """Is this band's box far taller than anything in it? The runtime half of D-F6's trigger.

    Two independent conditions, mirroring the mint detector exactly (walk finding F-1): a band
    mostly empty end to end (the extent fraction), and a band with one contiguous internal hole
    a reader drags through (the largest merged-interval gap) — which the fraction is
    structurally blind to when ink sits at both ends. Shared constants, so the two detectors'
    stated must-agree invariant survives the fix.
    """
    if not measurement.present or not measurement.measured or not measurement.visible:
        return False
    if measurement.height_px < DEAD_HEIGHT_MIN_SECTION_PX:
        return False
    if measurement.content_fraction <= DEAD_HEIGHT_MAX_CONTENT_FRACTION:
        return True
    return measurement.largest_gap_px > DEAD_HEIGHT_MAX_GAP_PX


def _mobile_broken(measurement: SectionMeasurement) -> bool:
    if not measurement.present or not measurement.measured:
        return False
    if not measurement.visible or measurement.height_px < MIN_USABLE_HEIGHT_PX:
        return True
    if measurement.width_px <= 0:
        return True
    overflow_limit = max(measurement.width_px, 1.0) * MOBILE_OVERFLOW_TOLERANCE
    return measurement.scroll_width_px > overflow_limit


def broken_clones(
    desktop: Sequence[SectionMeasurement],
    mobile: Sequence[SectionMeasurement] = (),
) -> tuple[BrokenClone, ...]:
    """The gate's durable verdicts, one per fragment at most.

    **Precedence, and why it is this order.** The row holds ONE reason, so a band that is broken
    in more than one way has to be described by the worst of them:

    1. ``blank_render`` — the band reaches the reader with nothing in it. Nothing else that is
       also true of it matters as much, and no other reason would lead a repair to the right work.
    2. ``mobile_unusable`` — it reads on a desktop and breaks on a phone. Ahead of dead height
       because a band nobody can read on a phone is unusable, while a band with generous dead
       height is merely bad.
    3. ``runtime_dead_height`` — it reads, and the reader drags through emptiness to get past it.

    A fragment measured only at one viewport is judged only on what was measured; a walk whose
    mobile pass abstained produces no ``mobile_unusable`` verdicts at all, which is the honest
    answer rather than a clean bill.
    """
    by_id: dict[str, SectionMeasurement] = {}
    for measurement in desktop:
        by_id.setdefault(measurement.fragment_id, measurement)
    mobile_by_id: dict[str, SectionMeasurement] = {}
    for measurement in mobile:
        mobile_by_id.setdefault(measurement.fragment_id, measurement)

    findings: list[BrokenClone] = []
    for fragment_id in list(by_id) + [
        key for key in mobile_by_id if key not in by_id
    ]:
        desk = by_id.get(fragment_id)
        phone = mobile_by_id.get(fragment_id)
        if desk is not None and _blank(desk):
            findings.append(
                BrokenClone(
                    fragment_id=fragment_id,
                    reason=DEGRADED_REASON_BLANK_RENDER,
                    measurement=_numbers(desk, phone),
                )
            )
            continue
        if phone is not None and _mobile_broken(phone):
            findings.append(
                BrokenClone(
                    fragment_id=fragment_id,
                    reason=DEGRADED_REASON_MOBILE_UNUSABLE,
                    measurement=_numbers(desk, phone),
                )
            )
            continue
        if desk is not None and _collapsed(desk):
            findings.append(
                BrokenClone(
                    fragment_id=fragment_id,
                    reason=DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
                    measurement=_numbers(desk, phone),
                )
            )
    return tuple(findings)


def _numbers(
    desktop: SectionMeasurement | None, mobile: SectionMeasurement | None
) -> dict[str, Any]:
    """The bounded evidence shape a verdict carries. Numbers and thresholds; no pixels, no markup."""
    measurement: dict[str, Any] = {
        "detector": "behavioural_walk@1",
        "min_section_px": DEAD_HEIGHT_MIN_SECTION_PX,
        "max_content_fraction": DEAD_HEIGHT_MAX_CONTENT_FRACTION,
        "mobile_overflow_tolerance": MOBILE_OVERFLOW_TOLERANCE,
        "min_usable_height_px": MIN_USABLE_HEIGHT_PX,
    }
    if desktop is not None:
        measurement["desktop"] = desktop.as_result()
    if mobile is not None:
        measurement["mobile"] = mobile.as_result()
    return measurement


# --- page-level advice ------------------------------------------------------------------------


#: Codes on the page findings. Namespaced by the gate rather than borrowed from the engine's
#: `LUMW`/`LUMI` families: none of these is something the renderer could have known.
FINDING_CONSOLE_ERROR = "review.console_error"
FINDING_SECTION_ABSENT = "review.section_absent"
FINDING_REDUCED_MOTION = "review.reduced_motion_divergence"
FINDING_NOT_OBSERVED = "review.not_observed"
FINDING_REFERENCE_DRIFT = "review.reference_drift"
#: A console error raised by our own preview shell rather than by the page (I1 / R19-2).
FINDING_SHELL_ERROR = "review.shell_console_error"
#: A band that IS on the page but came back without its numbers (I2).
FINDING_SECTION_UNMEASURED = "review.section_unmeasured"
#: The walk's evidence is not settled, so no durable marker may be written from it (R19-1).
FINDING_EVIDENCE_UNSETTLED = "review.evidence_unsettled"
#: The reduced-motion pass RAN and its two heights could not be compared (F3.4). Its own code
#: rather than an abstention: the pass was made, so `abstention_findings` — which walks the
#: classes that were never observed — cannot speak for it, and without this line a reader cannot
#: tell "motion costs this page nothing" from "we did not find out".
FINDING_REDUCED_MOTION_NOT_COMPARED = "review.reduced_motion_not_compared"


def console_findings(entries: Iterable[ConsoleEntry]) -> tuple[PageFinding, ...]:
    """One finding per console ERROR, blamed on whoever actually caused it.

    Warnings are dropped rather than reported: the acceptance bar is *zero console errors*, and a
    third-party stylesheet's deprecation notice is not that.

    **The page's errors and the preview shell's are different findings** (review finding I1,
    ruling R19-2). The gate walks the EDITOR render, which carries our vendored Tailwind browser
    JIT as an inline script; a cloned band carries no scripts at all, because the mint sanitizer
    strips them fail-closed. So on this page every script-originated line is OURS, and the only
    console lines the page's own content can produce are resource-load failures naming the
    resource. :func:`~lumen_api.clone_review.walk.console_source` draws that line, and a shell
    error is reported under its own code as a fault in the harness rather than in the page —
    which is what keeps the rubric's "a cloned band carries no scripts" clause TRUE of the
    entries it is talking about.

    A page whose clones are JS-free and whose bytes all load therefore reports an empty tuple,
    which is the honest answer for a healthy cloned page.
    """
    findings: list[PageFinding] = []
    for entry in entries:
        if entry.level != "error":
            continue
        if entry.source == CONSOLE_SOURCE_SHELL:
            findings.append(
                PageFinding(
                    code=FINDING_SHELL_ERROR,
                    severity="warning",
                    message=(
                        f"the PREVIEW SHELL raised a console error during the {entry.pass_name} "
                        f"pass: {entry.text}. This is our own tooling (the render's Tailwind "
                        "runtime), not the page — do not brief a repair for it, and do not count "
                        "it toward the page's console-error bar"
                    ),
                    detail=entry.as_result(),
                )
            )
            continue
        where = f"{entry.url}:{entry.line}" if entry.line is not None else str(entry.url)
        findings.append(
            PageFinding(
                code=FINDING_CONSOLE_ERROR,
                severity="error",
                message=(
                    f"console error during the {entry.pass_name} pass, from {where}: "
                    f"{entry.text}"
                ),
                detail=entry.as_result(),
            )
        )
    return tuple(findings)


def absent_section_findings(
    measurements: Sequence[SectionMeasurement],
) -> tuple[PageFinding, ...]:
    """Bands the walk looked for and did not find on the page.

    Advice, not a durable marker: a clone that is not in the DOM is almost always a clone the
    author took off the page, and marking the ARTIFACT broken because the PAGE does not carry it
    would be the gate inventing a defect out of an editorial decision.
    """
    findings: list[PageFinding] = []
    for item in measurements:
        if not item.present:
            findings.append(
                PageFinding(
                    code=FINDING_SECTION_ABSENT,
                    severity="warning",
                    message=(
                        f"the walk expected cloned section {item.fragment_id} at "
                        f"{item.selector!r} and found nothing there — either it is no longer "
                        "pinned on this page, or it did not render"
                    ),
                    detail={"fragment_id": item.fragment_id, "selector": item.selector},
                )
            )
        elif not item.measured:
            findings.append(
                PageFinding(
                    code=FINDING_SECTION_UNMEASURED,
                    severity="warning",
                    message=(
                        f"cloned section {item.fragment_id} is on the page but the probe brought "
                        "back no usable numbers for it, so this review makes NO judgement about "
                        "it — not a good one and not a bad one"
                    ),
                    detail={"fragment_id": item.fragment_id, "selector": item.selector},
                )
            )
    return tuple(findings)


def reduced_motion_findings(walk: BehaviouralWalk) -> tuple[PageFinding, ...]:
    """Did switching motion off cost the page content?

    Compared only when BOTH heights were read off a settled page (`heights_settled`, stamped by
    the reduced-motion pass). One settled height over one unstyled height measures nothing but
    the clock: on a slow JIT it fabricated this exact warning about a compiled-taller page and
    would have suppressed a real one about a compiled-shorter page (round-3 re-review).
    """
    observation = walk.by_class(WALK_CLASS_REDUCED_MOTION)
    if not observation.made:
        return ()
    # A pass that RAN and did not compare is not an abstention — `walk.abstentions` holds the
    # classes that were never observed, and this one was — so it used to return nothing at all
    # and read exactly like "no divergence" (F3.4). Both ways out say so instead.
    if observation.notes.get("heights_settled") is not True:
        return (_reduced_motion_not_compared("neither height was read off a settled page"),)
    still = _positive(observation.notes.get("document_height_px"))
    moving = _positive(observation.notes.get("motion_document_height_px"))
    if still is None or moving is None or moving <= 0:
        return (
            _reduced_motion_not_compared(
                "the pass came back without a usable document height for one or both states"
            ),
        )
    shortfall = (moving - still) / moving
    if shortfall <= REDUCED_MOTION_HEIGHT_TOLERANCE:
        return ()
    return (
        PageFinding(
            code=FINDING_REDUCED_MOTION,
            severity="warning",
            message=(
                f"with prefers-reduced-motion the page is {shortfall:.0%} shorter "
                f"({still:g}px against {moving:g}px) — content on this page depends on an "
                "animation having run, so a reader who asks for less motion sees less page"
            ),
            detail={
                "reduced_motion_height_px": still,
                "motion_height_px": moving,
                "shortfall": round(shortfall, 4),
                "tolerance": REDUCED_MOTION_HEIGHT_TOLERANCE,
            },
        ),
    )


def _reduced_motion_not_compared(because: str) -> PageFinding:
    """The honest note for a reduced-motion pass that ran and measured nothing usable."""
    return PageFinding(
        code=FINDING_REDUCED_MOTION_NOT_COMPARED,
        severity="warning",
        message=(
            f"the reduced-motion comparison was NOT made ({because}) — this review says nothing "
            "about whether content on this page depends on an animation having run, which is not "
            "the same as saying it does not"
        ),
        detail={"class": WALK_CLASS_REDUCED_MOTION, "because": because},
    )


def abstention_findings(walk: BehaviouralWalk) -> tuple[PageFinding, ...]:
    """Every class the walk could not observe, said out loud.

    This is the finding that keeps the whole gate honest: a review whose mobile pass silently
    failed reads exactly like a review that found no mobile problems, and the difference is the
    entire value of the exercise.
    """
    return tuple(
        PageFinding(
            code=FINDING_NOT_OBSERVED,
            severity="warning",
            message=(
                f"the {observation.label} could not be made ({observation.because}) — this "
                "review says NOTHING about it, which is not the same as saying it is fine"
            ),
            detail={"class": observation.walk_class, "because": observation.because},
        )
        for observation in walk.abstentions
    )


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# --- the critique ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class CloneReviewCritique:
    """The gate's whole structured output. ADVICE — it carries no verdict and refuses nothing.

    There is deliberately no ``accepted`` / ``blocking`` field. The standing carve-out is that
    structured critique is agent-facing advice: the reviewing agent judges it under the shared
    rubric and the human decides. A boolean here would become a gate on a publish by the first
    caller that read it, which is precisely what the carve-out forbids.
    """

    walk: BehaviouralWalk
    broken: tuple[BrokenClone, ...]
    page_findings: tuple[PageFinding, ...]
    comparison: Mapping[str, Any] | None = None
    #: Whether the numbers behind ``broken`` were taken after styling and images settled
    #: (ruling R19-1). ``False`` does not make the findings wrong — it makes them unfit to be
    #: written down: the caller reports them as advice and records no durable marker. See
    #: :func:`evidence_settled`.
    settled: bool = True

    def as_result(self) -> dict[str, Any]:
        return {
            "schema_version": CRITIQUE_SCHEMA_VERSION,
            "advice_only": True,
            "evidence_settled": self.settled,
            "walk": self.walk.as_result(),
            "broken_clones": [item.as_result() for item in self.broken],
            "page_findings": [item.as_result() for item in self.page_findings],
            "comparison": dict(self.comparison) if self.comparison else None,
        }


def evidence_settled(walk: BehaviouralWalk) -> bool:
    """Were these numbers taken after styling and image loading settled? (Ruling R19-1.)

    The gate walks the EDITOR render, whose utility CSS is compiled IN THE BROWSER by our
    vendored Tailwind JIT. Before that compile lands the page has no layout utilities at all: a
    band's images sit at their natural width, its blocks are unconstrained, and at 375px it
    overflows trivially. `_mobile_broken` would then fire on a perfectly healthy band — and
    unlike the preview beside it, whose output is a picture a human judges and discards, this
    walk's output is a marker `mark_degraded` can never clear.

    So a durable verdict requires a page that SAYS it is ready, not a page that has been asleep
    for 400ms. Every probe pass reports `styles_ready` as a tri-state, and only ``True`` from
    every pass that contributed measurements counts. ``False`` (not compiled) and ``None`` (the
    check could not run) both mean unsettled, so every way the signal can be wrong errs toward
    writing nothing. Lazy images must also have loaded and decoded under a bounded
    scroll pass; an absent media observation is not evidence of readiness.
    """
    for walk_class in (WALK_CLASS_HEIGHT_COLLAPSE, WALK_CLASS_MOBILE):
        observation = walk.by_class(walk_class)
        if not observation.made or not observation.measurements:
            continue
        if observation.notes.get("styles_ready") is not True:
            return False
        media = observation.notes.get("media_readiness")
        if not isinstance(media, Mapping) or media.get("settled") is not True:
            return False
    return True


def compose_critique(
    walk: BehaviouralWalk, *, comparison: Mapping[str, Any] | None = None
) -> CloneReviewCritique:
    """Read one walk under the gate's rules. Pure: nothing is written, nothing is decided."""
    collapse = walk.by_class(WALK_CLASS_HEIGHT_COLLAPSE)
    mobile = walk.by_class(WALK_CLASS_MOBILE)
    console = walk.by_class(WALK_CLASS_CONSOLE)

    desktop_measurements = collapse.measurements if collapse.made else ()
    mobile_measurements = mobile.measurements if mobile.made else ()
    broken = broken_clones(desktop_measurements, mobile_measurements)
    settled = evidence_settled(walk)

    findings: list[PageFinding] = []
    findings.extend(console_findings(console.console if console.made else ()))
    findings.extend(absent_section_findings(desktop_measurements))
    findings.extend(desktop_overflow_findings(desktop_measurements))
    findings.extend(reduced_motion_findings(walk))
    findings.extend(abstention_findings(walk))
    findings.extend(comparison_findings(comparison))
    if broken and not settled:
        findings.append(
            PageFinding(
                code=FINDING_EVIDENCE_UNSETTLED,
                severity="warning",
                message=(
                    f"the walk measured {len(broken)} cloned section(s) as broken, but the page's "
                    "styling or images had not settled when it looked — so NOTHING was recorded "
                    "in the library. Treat these as advice: look at the captures, and re-run the "
                    "review before briefing a repair on the strength of them"
                ),
                detail={
                    "fragment_ids": [item.fragment_id for item in broken],
                    "media_readiness": {
                        walk_class: walk.by_class(walk_class).notes.get("media_readiness")
                        for walk_class in (WALK_CLASS_HEIGHT_COLLAPSE, WALK_CLASS_MOBILE)
                    },
                    "styles_ready": {
                        walk_class: walk.by_class(walk_class).notes.get("styles_ready")
                        for walk_class in (WALK_CLASS_HEIGHT_COLLAPSE, WALK_CLASS_MOBILE)
                    },
                },
            )
        )

    return CloneReviewCritique(
        walk=walk,
        broken=broken,
        page_findings=tuple(findings),
        comparison=comparison,
        settled=settled,
    )


def desktop_overflow_findings(measurements: Sequence[SectionMeasurement]) -> tuple[PageFinding, ...]:
    """Surface excess desktop content width without minting a clone verdict.

    A carousel may intentionally scroll. This measurement asks the reviewer to
    inspect clipping and the page boundary; it does not label that intent broken.
    Use the same rounding tolerance as the mobile measurement.
    """
    return tuple(
        PageFinding(
            code="review.desktop_overflow",
            severity="warning",
            message=(
                f"desktop content in {item.fragment_id} exceeds its section width: "
                f"{item.scroll_width_px:g}px inside {item.width_px:g}px. Inspect the current "
                "desktop capture for clipped text or page overflow; intentional contained "
                "horizontal scrolling may be valid. These measurements are advice only"
            ),
            detail={"fragment_id": item.fragment_id, "width_px": item.width_px,
                    "scroll_width_px": item.scroll_width_px, "viewport": item.viewport},
        )
        for item in measurements
        if item.present and item.measured and item.visible and item.width_px > 0
        and item.scroll_width_px > item.width_px * MOBILE_OVERFLOW_TOLERANCE
    )


def comparison_findings(comparison: Mapping[str, Any] | None) -> tuple[PageFinding, ...]:
    """The reference comparison, turned into one advisory line per band that drifted.

    The NUMBERS are the comparison's; the interpretation is the rubric's. This only surfaces the
    bands worth looking at so the agent does not have to read a table to find them — it never
    says a band is wrong, because "different from the source" is exactly the judgement D-F7 puts
    on the soft side of the line.
    """
    if not comparison or comparison.get("status") != "ok":
        return ()
    findings: list[PageFinding] = []
    for band in comparison.get("bands") or ():
        if not isinstance(band, Mapping) or not band.get("drifted"):
            continue
        findings.append(
            PageFinding(
                code=FINDING_REFERENCE_DRIFT,
                severity="info",
                message=(
                    f"cloned section {band.get('fragment_id')} differs measurably from the "
                    f"reference capture: it renders {band.get('height_ratio')}x the reference "
                    f"height and {band.get('pixel_delta')} of its cells differ. Judge it under "
                    "the rubric — a measured difference is not automatically a defect"
                ),
                detail=dict(band),
            )
        )
    return tuple(findings)


#: What a caller gets instead of advice when the critique could not be composed at all.
ADVICE_UNAVAILABLE_CODE = "review.advice_unavailable"


def safe_critique(
    build: Callable[[], CloneReviewCritique],
) -> tuple[CloneReviewCritique | None, PageFinding | None]:
    """Compose a critique, or degrade to advice-absent — never raise, never terminate a run.

    The standing carve-out has a second half that is easy to forget: advice that cannot be
    produced must not take the run down with it. A behavioural walk that succeeded and a critique
    that then failed to compose is a page that was genuinely looked at; killing the turn there
    would throw away the walk, the captures, and whatever the author had built.

    So the failure is LOUD (a finding a reader cannot miss, naming the exception) and it is
    ADVICE-ABSENT, which is the honest state: this review offers no opinion.
    """
    try:
        return build(), None
    except Exception as error:  # noqa: BLE001 — advice must never be fatal
        return None, PageFinding(
            code=ADVICE_UNAVAILABLE_CODE,
            severity="error",
            message=(
                "the behavioural review produced captures but its structured critique could not "
                f"be composed ({type(error).__name__}: {error}) — this review offers NO advice. "
                "Look at the captures yourself and judge them against the rubric"
            ),
            detail={"error": f"{type(error).__name__}: {error}"},
        )


__all__ = [
    "ADVICE_UNAVAILABLE_CODE",
    "CRITIQUE_SCHEMA_VERSION",
    "FINDING_CONSOLE_ERROR",
    "FINDING_EVIDENCE_UNSETTLED",
    "FINDING_REDUCED_MOTION_NOT_COMPARED",
    "FINDING_SECTION_UNMEASURED",
    "FINDING_SHELL_ERROR",
    "FINDING_NOT_OBSERVED",
    "FINDING_REDUCED_MOTION",
    "FINDING_REFERENCE_DRIFT",
    "FINDING_SECTION_ABSENT",
    "MIN_USABLE_HEIGHT_PX",
    "MOBILE_OVERFLOW_TOLERANCE",
    "REDUCED_MOTION_HEIGHT_TOLERANCE",
    "BrokenClone",
    "CloneReviewCritique",
    "PageFinding",
    "abstention_findings",
    "absent_section_findings",
    "broken_clones",
    "comparison_findings",
    "compose_critique",
    "console_findings",
    "evidence_settled",
    "reduced_motion_findings",
    "safe_critique",
]
