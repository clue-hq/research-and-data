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
    DEAD_HEIGHT_MIN_SECTION_PX,
)

from ..fragments.degraded import (
    DEGRADED_REASON_BLANK_RENDER,
    DEGRADED_REASON_MOBILE_UNUSABLE,
    DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
    degraded_headline,
)
from .walk import (
    WALK_CLASS_CONSOLE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_MOBILE,
    WALK_CLASS_REDUCED_MOTION,
    BehaviouralWalk,
    ConsoleEntry,
    SectionMeasurement,
)

CRITIQUE_SCHEMA_VERSION = 1

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
    if not measurement.present:
        # Absent from the DOM is NOT a brokenness verdict about the artifact: the commonest cause
        # is that the band is no longer pinned on the page being walked, which is an author's
        # decision, not a defect. It is reported as a page finding instead.
        return False
    if not measurement.visible:
        return True
    if measurement.height_px < MIN_USABLE_HEIGHT_PX:
        return True
    return measurement.ink_nodes == 0


def _collapsed(measurement: SectionMeasurement) -> bool:
    """Is this band's box far taller than anything in it? The runtime half of D-F6's trigger."""
    if not measurement.present or not measurement.visible:
        return False
    if measurement.height_px < DEAD_HEIGHT_MIN_SECTION_PX:
        return False
    return measurement.content_fraction <= DEAD_HEIGHT_MAX_CONTENT_FRACTION


def _mobile_broken(measurement: SectionMeasurement) -> bool:
    if not measurement.present:
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


def console_findings(entries: Iterable[ConsoleEntry]) -> tuple[PageFinding, ...]:
    """One finding per console ERROR, attributed to where it came from.

    Warnings are dropped rather than reported: the acceptance bar is *zero console errors*, and a
    third-party stylesheet's deprecation notice is not that. An error with no source url is
    attributed to the document — which is what an uncaught page exception genuinely is.

    A page whose clones are JS-free (the sanitizer strips ``script`` and every ``on*`` handler at
    mint, fail-closed) has nothing that CAN throw, so the honest answer for a healthy cloned page
    is an empty tuple.
    """
    findings: list[PageFinding] = []
    for entry in entries:
        if entry.level != "error":
            continue
        source = entry.url or "the document itself"
        where = f"{source}:{entry.line}" if entry.line is not None else source
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
    return tuple(
        PageFinding(
            code=FINDING_SECTION_ABSENT,
            severity="warning",
            message=(
                f"the walk expected cloned section {item.fragment_id} at {item.selector!r} and "
                "found nothing there — either it is no longer pinned on this page, or it did "
                "not render"
            ),
            detail={"fragment_id": item.fragment_id, "selector": item.selector},
        )
        for item in measurements
        if not item.present
    )


def reduced_motion_findings(walk: BehaviouralWalk) -> tuple[PageFinding, ...]:
    """Did switching motion off cost the page content?"""
    observation = walk.by_class(WALK_CLASS_REDUCED_MOTION)
    if not observation.made:
        return ()
    still = _positive(observation.notes.get("document_height_px"))
    moving = _positive(observation.notes.get("motion_document_height_px"))
    if still is None or moving is None or moving <= 0:
        return ()
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

    def as_result(self) -> dict[str, Any]:
        return {
            "schema_version": CRITIQUE_SCHEMA_VERSION,
            "advice_only": True,
            "walk": self.walk.as_result(),
            "broken_clones": [item.as_result() for item in self.broken],
            "page_findings": [item.as_result() for item in self.page_findings],
            "comparison": dict(self.comparison) if self.comparison else None,
        }


def compose_critique(
    walk: BehaviouralWalk, *, comparison: Mapping[str, Any] | None = None
) -> CloneReviewCritique:
    """Read one walk under the gate's rules. Pure: nothing is written, nothing is decided."""
    collapse = walk.by_class(WALK_CLASS_HEIGHT_COLLAPSE)
    mobile = walk.by_class(WALK_CLASS_MOBILE)
    console = walk.by_class(WALK_CLASS_CONSOLE)

    desktop_measurements = collapse.measurements if collapse.made else ()
    mobile_measurements = mobile.measurements if mobile.made else ()

    findings: list[PageFinding] = []
    findings.extend(console_findings(console.console if console.made else ()))
    findings.extend(absent_section_findings(desktop_measurements))
    findings.extend(reduced_motion_findings(walk))
    findings.extend(abstention_findings(walk))
    findings.extend(comparison_findings(comparison))

    return CloneReviewCritique(
        walk=walk,
        broken=broken_clones(desktop_measurements, mobile_measurements),
        page_findings=tuple(findings),
        comparison=comparison,
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
    "reduced_motion_findings",
    "safe_critique",
]
