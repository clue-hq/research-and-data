"""The behavioural review gate — the walk, the judgements, the comparison, the blind artifact.

Clone-fidelity F3.3, founder rulings D-F6 (brokenness is something the pipeline must NOTICE) and
D-F7 (the shared rubric, and the flag that changes who checks and never what is checked).

**Playwright is stubbed at the seam here, deliberately and honestly.** Nothing in this file
launches chromium; what is asserted is the walk's INPUT and its SHAPE — the same pattern F3.2's
isolation-render suite established, and the same reason: every property worth pinning about this
gate is a property of what it refuses to claim, and a refusal reachable only by launching a
browser is a refusal nobody tests. The first real-browser evidence is deliberately the live
acceptance walk.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from lumen_api.clone_review import (
    DESKTOP_VIEWPORT,
    MOBILE_VIEWPORT,
    WALK_CLASSES,
    BehaviouralWalk,
    CaptureShot,
    CloneReviewRefused,
    ConsoleEntry,
    SectionMeasurement,
    WalkObservation,
    abstained,
    broken_clones,
    build_blind_side_by_side,
    compare_to_reference,
    compose_critique,
    console_findings,
    key_matches,
    measurements_from_probe,
    reference_bands_from_fragments,
    safe_critique,
    walk_plan,
)
from lumen_api.clone_review.blind import SIDE_PUBLISHED, SIDE_REFERENCE
from lumen_api.clone_review.compare import ReferenceBand, RenderedBand
from lumen_api.clone_review.findings import (
    ADVICE_UNAVAILABLE_CODE,
    FINDING_CONSOLE_ERROR,
    FINDING_NOT_OBSERVED,
    FINDING_REDUCED_MOTION,
    FINDING_REDUCED_MOTION_NOT_COMPARED,
    FINDING_SECTION_ABSENT,
)
from lumen_api.clone_review.walk import (
    WALK_CLASS_CONSOLE,
    WALK_CLASS_FULL_PAGE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_MOBILE,
    WALK_CLASS_REDUCED_MOTION,
    WALK_CLASS_SCROLL_THROUGH,
    capture_behavioural_walk,
)
from lumen_api.fragments.degraded import (
    DEGRADED_REASON_BLANK_RENDER,
    DEGRADED_REASON_DEAD_HEIGHT,
    DEGRADED_REASON_MOBILE_UNUSABLE,
    DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
    GATE_REASONS,
    degraded_headline,
)

# --- helpers -------------------------------------------------------------------------------------


def _measurement(fragment_id: str, **overrides: Any) -> SectionMeasurement:
    base = {
        "fragment_id": fragment_id,
        "selector": f".lumen-frag-{fragment_id}",
        "viewport": DESKTOP_VIEWPORT.name,
        "present": True,
        "visible": True,
        "top_px": 0.0,
        "width_px": 1440.0,
        "height_px": 800.0,
        "content_extent_px": 600.0,
        "ink_nodes": 12,
        "scroll_width_px": 1440.0,
        "largest_gap_px": 0.0,
    }
    base.update(overrides)
    return SectionMeasurement(**base)  # type: ignore[arg-type]


def _walk(
    *,
    desktop: tuple[SectionMeasurement, ...] = (),
    mobile: tuple[SectionMeasurement, ...] = (),
    console: tuple[ConsoleEntry, ...] = (),
    reduced_notes: dict | None = None,
    mobile_made: bool = True,
) -> BehaviouralWalk:
    # A SETTLED, equal-height reduced-motion pair by default. The old default was an empty notes
    # dict, which is the "the pass ran and compared nothing" shape — and since F3.4 that shape is
    # a finding of its own, which is the whole point: a fake whose default silently means "we did
    # not find out" is the confusion the note exists to end.
    reduced_notes = (
        reduced_notes
        if reduced_notes is not None
        else {
            "document_height_px": 9000.0,
            "motion_document_height_px": 9000.0,
            "heights_settled": True,
        }
    )
    return BehaviouralWalk(
        observations=(
            WalkObservation(
                walk_class=WALK_CLASS_FULL_PAGE,
                made=True,
                shots=(
                    CaptureShot(
                        walk_class=WALK_CLASS_FULL_PAGE,
                        label="full page",
                        path="/tmp/full.png",
                        viewport_width=DESKTOP_VIEWPORT.width,
                    ),
                ),
            ),
            WalkObservation(walk_class=WALK_CLASS_SCROLL_THROUGH, made=True),
            (
                WalkObservation(
                    walk_class=WALK_CLASS_MOBILE, made=True, measurements=mobile
                )
                if mobile_made
                else abstained(WALK_CLASS_MOBILE, "timed_out")
            ),
            WalkObservation(walk_class=WALK_CLASS_CONSOLE, made=True, console=console),
            WalkObservation(
                walk_class=WALK_CLASS_HEIGHT_COLLAPSE, made=True, measurements=desktop
            ),
            WalkObservation(
                walk_class=WALK_CLASS_REDUCED_MOTION,
                made=True,
                notes=reduced_notes,
            ),
        )
    )


def _png(width: int, height: int, fill: int = 255, band: tuple[int, int, int] | None = None) -> bytes:
    """A grey PNG, optionally with one darker horizontal band ``(top, bottom, level)``."""
    from PIL import Image

    image = Image.new("L", (width, height), fill)
    if band is not None:
        top, bottom, level = band
        for y in range(max(0, top), min(height, bottom)):
            for x in range(width):
                image.putpixel((x, y), level)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# --- red case 1: the six classes, and the refusal with no browser --------------------------------


def test_a_walk_carries_every_capture_class_labelled_even_when_one_could_not_be_made():
    walk = _walk(mobile_made=False)
    seen = tuple(observation.walk_class for observation in walk.observations)
    assert seen == WALK_CLASSES
    assert len(seen) == 6
    for observation in walk.observations:
        assert observation.label and observation.label != observation.walk_class

    mobile = walk.by_class(WALK_CLASS_MOBILE)
    assert mobile.made is False
    assert mobile.because == "timed_out"
    # The abstention is a REFUSAL to speak, not an empty success: it carries no measurements and
    # it says so in the serialized result too.
    assert mobile.as_result() == {
        "class": WALK_CLASS_MOBILE,
        "label": "mobile viewport",
        "made": False,
        "because": "timed_out",
    }
    assert [item.walk_class for item in walk.abstentions] == [WALK_CLASS_MOBILE]


def test_a_walk_that_dropped_a_class_is_rejected_rather_than_read_as_a_clean_bill():
    with pytest.raises(ValueError) as excinfo:
        BehaviouralWalk(
            observations=tuple(
                observation
                for observation in _walk().observations
                if observation.walk_class != WALK_CLASS_MOBILE
            )
        )
    assert "one observation per class" in str(excinfo.value)


def test_no_browser_refuses_typed_and_never_fabricates_a_capture(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_playwright(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_playwright)
    with pytest.raises(CloneReviewRefused) as excinfo:
        capture_behavioural_walk("<html></html>", walk_plan(), output_dir="/tmp/nowhere")
    assert excinfo.value.code == "review.browser_unavailable"
    assert "playwright" in excinfo.value.message


def test_the_plan_names_the_platforms_own_phone_width_and_the_desktop_reference_width():
    plan = walk_plan([{"fragment_id": "frag_a", "selector": ".lumen-frag-frag_a"}])
    assert plan.desktop.width == 1440
    assert plan.mobile.width == 375
    assert plan.classes == WALK_CLASSES
    assert plan.as_result()["sections"] == [
        {"fragment_id": "frag_a", "selector": ".lumen-frag-frag_a"}
    ]


def test_the_probe_reader_survives_a_row_that_is_not_what_we_expect():
    measurements = measurements_from_probe(
        [
            {"fragment_id": "frag_a", "selector": ".a", "present": False},
            {"selector": ".b", "present": True},  # no id at all — dropped
            "not a row",  # not even a mapping
            {
                "fragment_id": "frag_c",
                "selector": ".c",
                "present": True,
                "height_px": "not a number",
                "visible": True,
            },
        ],
        viewport="desktop",
    )
    assert [item.fragment_id for item in measurements] == ["frag_a", "frag_c"]
    assert measurements[0].present is False
    assert measurements[1].height_px == 0.0


# --- red case 2: artificial height collapse, measured -------------------------------------------


def test_a_band_that_is_mostly_dead_height_is_flagged_with_the_numbers_behind_it():
    dead = _measurement("frag_dead", height_px=3200.0, content_extent_px=600.0)
    findings = broken_clones((dead,))
    assert [item.reason for item in findings] == [DEGRADED_REASON_RUNTIME_DEAD_HEIGHT]
    numbers = findings[0].measurement
    assert numbers["desktop"]["height_px"] == 3200.0
    assert numbers["desktop"]["content_fraction"] == pytest.approx(0.1875)
    # The thresholds ride with the verdict so a repair can be argued with, not merely obeyed.
    assert numbers["min_section_px"] == 1600.0
    assert numbers["max_content_fraction"] == 0.35
    assert "dead scroll height" not in findings[0].headline  # it is the RUNTIME headline
    assert "the page we actually render" in findings[0].headline


def test_a_healthy_band_and_a_short_one_are_not_flagged():
    healthy = _measurement("frag_ok", height_px=2400.0, content_extent_px=2000.0)
    # Short: below the floor, so however empty it looks it is not scroll cost.
    short = _measurement("frag_short", height_px=900.0, content_extent_px=100.0)
    assert broken_clones((healthy, short)) == ()


def test_the_gate_only_ever_writes_reasons_it_owns_and_dead_height_is_not_one_of_them():
    assert DEGRADED_REASON_DEAD_HEIGHT not in GATE_REASONS
    assert set(GATE_REASONS) == {
        DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
        DEGRADED_REASON_BLANK_RENDER,
        DEGRADED_REASON_MOBILE_UNUSABLE,
    }
    for reason in GATE_REASONS:
        # Every gate code has a real sentence, not the unknown-code fallback.
        assert "which this build has no description for" not in degraded_headline(reason)


def test_the_mint_time_reconciler_leaves_a_gate_verdict_alone(monkeypatch):
    """The other side of T16's own-reason rule, pinned from the gate's side.

    A later re-ingestion of the source site re-measures dead height off a FRESH capture. If it
    could clear any marker it would silently retire a verdict about how OUR page renders, which
    it never looked at. It refuses, and the reason it refuses is that the code is not its own.
    """
    from lumen_ingestion.sections.deadheight import DeadHeightAssessment
    from lumen_ingestion.sections.mint import _reconcile_degraded

    row = {
        "fragment_id": "frag_gate",
        "degraded": True,
        "degraded_reason": DEGRADED_REASON_RUNTIME_DEAD_HEIGHT,
    }
    record = type("R", (), {"index": 3, "role": "hero"})()
    segmentation = type("S", (), {"page_url": "https://example.test/"})()
    calls: list = []
    diagnostics: list = []

    result = _reconcile_degraded(
        row,
        DeadHeightAssessment(judged=True, finding=None),  # this pass says "the band is full"
        record,
        segmentation,
        lambda *args, **kwargs: calls.append((args, kwargs)),
        diagnostics,
    )
    assert result is row
    assert result["degraded"] is True
    assert result["degraded_reason"] == DEGRADED_REASON_RUNTIME_DEAD_HEIGHT
    assert calls == []
    assert diagnostics == []


# --- blankness, mobile, and the precedence between them -----------------------------------------


def test_a_band_with_no_ink_reads_as_blank_rather_than_as_dead_height():
    blank = _measurement("frag_blank", height_px=2400.0, content_extent_px=0.0, ink_nodes=0)
    findings = broken_clones((blank,))
    assert [item.reason for item in findings] == [DEGRADED_REASON_BLANK_RENDER]


def test_a_band_that_overflows_the_phone_is_mobile_unusable():
    desktop = _measurement("frag_wide")
    phone = _measurement(
        "frag_wide",
        viewport=MOBILE_VIEWPORT.name,
        width_px=375.0,
        height_px=600.0,
        content_extent_px=500.0,
        scroll_width_px=900.0,
    )
    findings = broken_clones((desktop,), (phone,))
    assert [item.reason for item in findings] == [DEGRADED_REASON_MOBILE_UNUSABLE]
    assert findings[0].measurement["mobile"]["scroll_width_px"] == 900.0


def test_a_band_a_few_pixels_over_the_phone_width_is_not_called_broken():
    desktop = _measurement("frag_tight")
    phone = _measurement(
        "frag_tight",
        viewport=MOBILE_VIEWPORT.name,
        width_px=375.0,
        height_px=600.0,
        content_extent_px=500.0,
        scroll_width_px=377.0,
    )
    assert broken_clones((desktop,), (phone,)) == ()


def test_a_walk_whose_mobile_pass_abstained_produces_no_mobile_verdicts():
    walk = _walk(desktop=(_measurement("frag_a"),), mobile_made=False)
    critique = compose_critique(walk)
    assert critique.broken == ()
    # ...and it SAYS the mobile half is missing rather than implying it passed.
    assert any(
        finding.code == FINDING_NOT_OBSERVED and "mobile" in finding.message
        for finding in critique.page_findings
    )


def test_a_band_absent_from_the_page_is_advice_and_never_a_marker_on_the_artifact():
    walk = _walk(desktop=(_measurement("frag_gone", present=False),))
    critique = compose_critique(walk)
    assert critique.broken == ()
    assert [finding.code for finding in critique.page_findings if
            finding.code == FINDING_SECTION_ABSENT] == [FINDING_SECTION_ABSENT]


# --- red case 7: console errors ------------------------------------------------------------------


def test_a_page_with_no_console_errors_reports_zero():
    walk = _walk(console=())
    critique = compose_critique(walk)
    assert [f for f in critique.page_findings if f.code == FINDING_CONSOLE_ERROR] == []


def test_an_injected_console_error_is_captured_and_attributed_to_its_source():
    entries = (
        ConsoleEntry(
            level="error",
            text="Uncaught TypeError: x is not a function",
            url="https://isolation.test/app.js",
            line=42,
            pass_name="mobile",
        ),
        ConsoleEntry(level="warning", text="a deprecation notice", url=None, line=None),
    )
    findings = console_findings(entries)
    assert len(findings) == 1  # the warning is not an error and is not reported as one
    assert findings[0].code == FINDING_CONSOLE_ERROR
    assert "https://isolation.test/app.js:42" in findings[0].message
    assert "mobile pass" in findings[0].message
    assert findings[0].detail["level"] == "error"


def test_an_uncaught_page_error_is_blamed_on_the_only_scripts_present_which_are_ours():
    """A cloned band carries no scripts, so nothing the page contains CAN throw.

    Amended in the fix round (review finding I1 / ruling R19-2): this used to be reported as a
    console error "from the document itself", indistinguishable from a genuine page fault. On the
    page the gate walks the only script is our preview shell's Tailwind runtime, so an uncaught
    exception is ours and is reported as such.
    """
    findings = console_findings(
        (ConsoleEntry(level="error", text="uncaught: boom", url=None, line=None),)
    )
    assert findings[0].code == "review.shell_console_error"
    assert "our own tooling" in findings[0].message


# --- reduced motion --------------------------------------------------------------------------------


def test_a_page_that_shrinks_without_motion_is_reported_as_advice():
    walk = _walk(
        reduced_notes={
            "document_height_px": 4000.0,
            "motion_document_height_px": 9000.0,
            "heights_settled": True,
        }
    )
    critique = compose_critique(walk)
    finding = next(f for f in critique.page_findings if f.code == FINDING_REDUCED_MOTION)
    assert finding.severity == "warning"
    assert finding.detail["shortfall"] == pytest.approx(0.5556, abs=1e-3)


def test_a_page_that_is_the_same_height_without_motion_says_nothing():
    walk = _walk(
        reduced_notes={
            "document_height_px": 8900.0,
            "motion_document_height_px": 9000.0,
            "heights_settled": True,
        }
    )
    critique = compose_critique(walk)
    assert [f for f in critique.page_findings if f.code == FINDING_REDUCED_MOTION] == []


def test_an_unsettled_height_pair_is_never_compared_and_the_review_says_so():
    """The divergence ratio is only as good as its worst half (round-3 re-review) — and the
    silence that leaves is itself reported (F3.4). The pass RAN, so `abstention_findings` cannot
    speak for it, and without a line of its own a reader cannot tell "motion costs this page
    nothing" from "we did not find out"."""
    walk = _walk(
        reduced_notes={
            "document_height_px": 4000.0,
            "motion_document_height_px": 9000.0,
            "heights_settled": False,
        }
    )
    critique = compose_critique(walk)
    assert [f for f in critique.page_findings if f.code == FINDING_REDUCED_MOTION] == []
    (note,) = [
        f
        for f in critique.page_findings
        if f.code == FINDING_REDUCED_MOTION_NOT_COMPARED
    ]
    assert note.severity == "warning"
    assert "NOT made" in note.message
    assert "settled" in note.detail["because"]
    # …and it is not an abstention: the class was observed.
    assert [f for f in critique.page_findings if f.code == "review.not_observed"] == []


def test_a_reduced_motion_pass_with_no_usable_heights_says_so_too():
    walk = _walk(reduced_notes={"heights_settled": True})
    critique = compose_critique(walk)
    (note,) = [
        f
        for f in critique.page_findings
        if f.code == FINDING_REDUCED_MOTION_NOT_COMPARED
    ]
    assert "document height" in note.detail["because"]


def test_a_compared_reduced_motion_pass_leaves_no_not_compared_note():
    walk = _walk(
        reduced_notes={
            "document_height_px": 8900.0,
            "motion_document_height_px": 9000.0,
            "heights_settled": True,
        }
    )
    critique = compose_critique(walk)
    assert [
        f
        for f in critique.page_findings
        if f.code == FINDING_REDUCED_MOTION_NOT_COMPARED
    ] == []


# --- red case 5: advice-only ---------------------------------------------------------------------


def test_the_critique_carries_no_verdict_at_all():
    critique = compose_critique(
        _walk(desktop=(_measurement("frag_dead", height_px=3200.0, content_extent_px=200.0),))
    )
    result = critique.as_result()
    assert result["advice_only"] is True
    # Nothing a caller could mistake for a gate.
    assert "accepted" not in result
    assert "blocking" not in result
    assert result["broken_clones"][0]["reason"] == DEGRADED_REASON_RUNTIME_DEAD_HEIGHT


def test_a_critique_that_cannot_be_composed_degrades_to_advice_absent_and_never_raises():
    def _explode():
        raise RuntimeError("the critique blew up")

    critique, failure = safe_critique(_explode)
    assert critique is None
    assert failure is not None
    assert failure.code == ADVICE_UNAVAILABLE_CODE
    assert failure.severity == "error"
    assert "offers NO advice" in failure.message
    assert "RuntimeError" in failure.detail["error"]


# --- the reference comparison ---------------------------------------------------------------------


def test_the_comparison_names_which_half_is_missing_rather_than_saying_unavailable():
    assert compare_to_reference(
        reference_png=None,
        capture_png=b"x",
        reference_viewport_width=1440,
        rendered_viewport_width=1440,
    )["because"] == "no_reference_screenshot"
    assert compare_to_reference(
        reference_png=b"x",
        capture_png=None,
        reference_viewport_width=1440,
        rendered_viewport_width=1440,
    )["because"] == "no_page_capture"
    assert compare_to_reference(
        reference_png=b"x",
        capture_png=b"y",
        reference_viewport_width=None,
        rendered_viewport_width=1440,
    )["because"] == "reference_viewport_unknown"


def test_two_identical_pages_compare_as_no_drift_and_two_different_ones_do_not():
    reference = _png(1440, 2000, fill=255, band=(400, 900, 20))
    same = _png(1440, 2000, fill=255, band=(400, 900, 20))
    different = _png(1440, 2000, fill=255)  # the band's content is simply gone

    bands = [ReferenceBand(fragment_id="frag_a", top_px=400.0, bottom_px=900.0)]
    rendered = [RenderedBand(fragment_id="frag_a", top_px=400.0, height_px=500.0)]

    identical = compare_to_reference(
        reference_png=reference,
        capture_png=same,
        reference_viewport_width=1440,
        rendered_viewport_width=1440,
        reference_bands=bands,
        rendered_bands=rendered,
    )
    assert identical["status"] == "ok"
    assert identical["bands"][0]["pixel_delta"] == pytest.approx(0.0, abs=1e-6)
    assert identical["bands"][0]["drifted"] is False
    assert identical["bands"][0]["height_ratio"] == 1.0

    drifted = compare_to_reference(
        reference_png=reference,
        capture_png=different,
        reference_viewport_width=1440,
        rendered_viewport_width=1440,
        reference_bands=bands,
        rendered_bands=rendered,
    )
    assert drifted["bands"][0]["drifted"] is True
    assert drifted["bands"][0]["pixel_delta"] > 0.08


def test_a_band_the_fragment_map_cannot_place_is_skipped_and_named():
    reference = _png(1440, 2000)
    capture = _png(1440, 2000)
    result = compare_to_reference(
        reference_png=reference,
        capture_png=capture,
        reference_viewport_width=1440,
        rendered_viewport_width=1440,
        reference_bands=(),
        rendered_bands=[RenderedBand(fragment_id="frag_x", top_px=0.0, height_px=500.0)],
    )
    assert result["bands"] == []
    assert result["skipped_bands"] == [
        {"fragment_id": "frag_x", "because": "no_reference_geometry"}
    ]


def test_the_reference_geometry_is_read_from_the_mints_own_provenance():
    bands, viewport, snapshot = reference_bands_from_fragments(
        [
            {
                "fragment_id": "frag_a",
                "provenance": {
                    "snapshot_id": "snap_1",
                    "viewport_width": 1440,
                    "geometry": {"top_px": 0, "bottom_px": 700, "basis": "measured"},
                },
            },
            {
                "fragment_id": "frag_b",
                "provenance": {
                    "snapshot_id": "snap_1",
                    "viewport_width": 1440,
                    # A section the capture never measured contributes NO band rather than a
                    # rectangle somebody guessed.
                    "geometry": None,
                },
            },
        ]
    )
    assert [band.fragment_id for band in bands] == ["frag_a"]
    assert viewport == 1440
    assert snapshot == "snap_1"


def test_fragments_with_no_snapshot_provenance_yield_no_snapshot_to_compare_against():
    bands, viewport, snapshot = reference_bands_from_fragments(
        [{"fragment_id": "frag_a", "provenance": {}}]
    )
    assert bands == () and viewport is None and snapshot is None


# --- red case 6: the blind side-by-side ------------------------------------------------------------


def test_the_blind_artifact_carries_both_images_unlabelled_with_the_key_sealed_separately():
    published = _png(1440, 1800, fill=250)
    reference = _png(1440, 1800, fill=200)
    blind = build_blind_side_by_side(
        published_png=published, reference_png=reference, seed="seed-a"
    )

    from PIL import Image

    with Image.open(BytesIO(blind.image_png)) as image:
        assert image.width > 1400  # two panels side by side
    # The KEY is a separate object. Nothing about which panel is which travels with the picture.
    assert set(blind.key["panels"]) == {"A", "B"}
    assert set(blind.key["panels"].values()) == {SIDE_PUBLISHED, SIDE_REFERENCE}
    assert key_matches(blind.key, blind.image_png)
    # ...and a key read against a DIFFERENT artifact is caught rather than believed.
    assert not key_matches(blind.key, published)


def test_the_blind_order_is_seeded_so_a_disputed_walk_can_be_rebuilt_exactly():
    published = _png(600, 900, fill=250)
    reference = _png(600, 900, fill=200)
    first = build_blind_side_by_side(
        published_png=published, reference_png=reference, seed="run-7:1"
    )
    again = build_blind_side_by_side(
        published_png=published, reference_png=reference, seed="run-7:1"
    )
    assert first.key["panels"] == again.key["panels"]
    assert first.image_sha256 == again.image_sha256

    # Two different seeds do not both put the published page on the left, or the exercise is a
    # coin nobody flipped.
    sides = {
        build_blind_side_by_side(
            published_png=published, reference_png=reference, seed=f"s{index}"
        ).key["panels"]["A"]
        for index in range(12)
    }
    assert sides == {SIDE_PUBLISHED, SIDE_REFERENCE}


def test_a_very_tall_page_is_cropped_and_the_key_says_so():
    published = _png(600, 9000, fill=250)
    reference = _png(600, 400, fill=200)
    blind = build_blind_side_by_side(
        published_png=published, reference_png=reference, seed="tall"
    )
    assert blind.key["cropped"][SIDE_PUBLISHED] is True
    assert blind.key["cropped"][SIDE_REFERENCE] is False


# =================================================================================================
# Fix round — the review's C1 / I1 / I2 and the minors folded in with them
# =================================================================================================


class _FakePage:
    """Enough of a Playwright page for `run_walk` to be exercised with no chromium.

    Deliberately dumb: it records what was asked of it and answers from a script the test wrote.
    Nothing here pretends to render — what these tests are about is which passes opened, how the
    six observations are assembled from them, and what happens when one of them dies.
    """

    def __init__(self, owner: "_FakeBrowser", viewport: dict, reduced_motion: str) -> None:
        self.owner = owner
        self.viewport = viewport
        self.reduced_motion = reduced_motion
        self.handlers: dict[str, Any] = {}
        self.scrolled: list[float] = []
        self.screenshots: list[str] = []
        self.context = self
        # Geometry is PAGE-LOCAL, like a real browser's: each pass opens its own page, and that
        # page's height settles when ITS readiness wait resolves — not when a sibling's did.
        self.geometry = dict(owner.geometry)

    # --- the surface run_walk touches ---
    def set_default_timeout(self, _ms: int) -> None:
        pass

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    def set_content(self, html: str, wait_until: str = "load") -> None:
        self.owner.html = html

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def wait_for_function(self, script: str, *, timeout: int = 0) -> None:
        from lumen_api.clone_review.walk import STYLES_READY_SCRIPT

        assert script == STYLES_READY_SCRIPT
        self.owner.waits.append(timeout)
        if self.owner.styles_ready is not True:
            raise TimeoutError("styles never became ready")
        # The JIT finishing is exactly when a real page's geometry settles: a test that hands
        # `geometry_after_ready` is describing a page whose unstyled height differs from its
        # compiled one, which is the page the readiness wait exists for. Page-local, so a pass
        # that never waited keeps seeing the unstyled height.
        if self.owner.geometry_after_ready is not None:
            self.geometry = dict(self.owner.geometry_after_ready)

    def evaluate(self, script: str, arg: Any = None) -> Any:
        from lumen_api.clone_review.walk import (
            DOCUMENT_HEIGHT_SCRIPT,
            SECTION_PROBE_SCRIPT,
            STYLES_READY_SCRIPT,
        )

        if script == DOCUMENT_HEIGHT_SCRIPT:
            return dict(self.geometry)
        if script == STYLES_READY_SCRIPT:
            return self.owner.styles_ready
        if script == SECTION_PROBE_SCRIPT:
            return [dict(row) for row in self.owner.probe_rows]
        if "scrollTo" in script:
            self.scrolled.append(float(arg or 0.0))
            return None
        raise AssertionError(f"unexpected evaluate: {script[:40]}")

    def screenshot(self, *, path: str, full_page: bool = False) -> None:
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        self.screenshots.append(path)

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(
        self,
        *,
        geometry: dict | None = None,
        geometry_after_ready: dict | None = None,
        probe_rows: list | None = None,
        styles_ready: Any = True,
        fail_passes: tuple[str, ...] = (),
    ) -> None:
        self.geometry = geometry or {"height": 4000, "width": 1440, "viewport": 1440}
        self.geometry_after_ready = geometry_after_ready
        self.probe_rows = probe_rows or []
        self.styles_ready = styles_ready
        self.fail_passes = fail_passes
        self.pages: list[_FakePage] = []
        self.waits: list[int] = []
        self.html = ""
        # What each `new_context` call was asked for — including a pass that then refuses — so a
        # test can pin what the walk asks the browser for (the QA User-Agent override, D11).
        self.context_kwargs: list[dict] = []

    def new_context(self, *, viewport: dict, reduced_motion: str, **kwargs) -> "_FakeBrowser":
        self.context_kwargs.append(
            {"viewport": viewport, "reduced_motion": reduced_motion, **kwargs}
        )
        # The pass identity a test can refuse on: desktop / mobile / reduced-motion.
        if viewport["width"] == 375:
            name = "mobile"
        elif reduced_motion == "reduce":
            name = "reduced_motion"
        else:
            name = "desktop"
        if name in self.fail_passes:
            raise RuntimeError(f"{name} context refused")
        self._pending = (viewport, reduced_motion)
        return self

    def new_page(self) -> _FakePage:
        page = _FakePage(self, *self._pending)
        self.pages.append(page)
        return page

    # `page.context.close()` lands here.
    def close(self) -> None:
        pass


def _factory(browser: _FakeBrowser):
    from contextlib import contextmanager

    @contextmanager
    def _make():
        yield browser

    return _make


def _run(browser: _FakeBrowser, tmp_path, plan=None):
    from lumen_api.clone_review.browser import run_walk

    return run_walk(
        "<html></html>",
        plan or walk_plan(),
        output_dir=tmp_path,
        browser_factory=_factory(browser),
    )


# --- C1: the console class may not report a pass that never happened -----------------------------


def test_the_console_class_abstains_when_not_one_pass_opened_a_page(tmp_path):
    walk = _run(
        _FakeBrowser(fail_passes=("desktop", "mobile", "reduced_motion")), tmp_path
    )
    console = walk.by_class(WALK_CLASS_CONSOLE)
    assert console.made is False
    assert console.because == "no_pass_opened"
    # ...and it is not silently absent from the review's own list of gaps.
    assert WALK_CLASS_CONSOLE in [item.walk_class for item in walk.abstentions]
    assert len(walk.abstentions) == 6


def test_the_console_note_names_only_the_passes_that_actually_opened(tmp_path):
    walk = _run(_FakeBrowser(fail_passes=("mobile",)), tmp_path)
    console = walk.by_class(WALK_CLASS_CONSOLE)
    assert console.made is True
    assert console.notes["passes"] == ["desktop", "reduced_motion"]
    assert walk.by_class(WALK_CLASS_MOBILE).made is False


def test_a_walk_where_every_pass_opened_reports_all_three(tmp_path):
    walk = _run(_FakeBrowser(), tmp_path)
    assert walk.by_class(WALK_CLASS_CONSOLE).notes["passes"] == [
        "desktop",
        "mobile",
        "reduced_motion",
    ]
    assert all(observation.made for observation in walk.observations)


def test_a_console_error_from_a_pass_that_opened_still_arrives(tmp_path):
    browser = _FakeBrowser()
    walk_result: dict = {}

    class _Message:
        type = "error"
        text = "Failed to load resource"
        location = {"url": "https://cdn.test/logo.png", "lineNumber": 0}

    from lumen_api.clone_review.browser import run_walk

    original_new_page = browser.new_page

    def _new_page():
        page = original_new_page()
        real_set_content = page.set_content

        def _set_content(html, wait_until="load"):
            real_set_content(html, wait_until)
            page.handlers["console"](_Message())

        page.set_content = _set_content
        return page

    browser.new_page = _new_page
    walk_result["walk"] = run_walk(
        "<html></html>",
        walk_plan(),
        output_dir=tmp_path,
        browser_factory=_factory(browser),
    )
    console = walk_result["walk"].by_class(WALK_CLASS_CONSOLE)
    assert console.made is True
    assert len(console.console) == 3  # one per pass
    assert {entry.pass_name for entry in console.console} == {
        "desktop",
        "mobile",
        "reduced_motion",
    }


# --- I3's other dividends: scroll arithmetic and per-class degradation ---------------------------


def test_a_page_shorter_than_the_viewport_is_photographed_once_not_five_times(tmp_path):
    from lumen_api.clone_review.browser import scroll_offsets

    assert scroll_offsets(600.0, 900, (0.0, 0.25, 0.5, 0.75, 1.0)) == ((0.0, 0.0),)
    walk = _run(_FakeBrowser(geometry={"height": 600, "width": 1440}), tmp_path)
    scroll = walk.by_class(WALK_CLASS_SCROLL_THROUGH)
    assert len(scroll.shots) == 1
    assert scroll.shots[0].scroll_fraction == 0.0
    assert scroll.notes["distinct_positions"] == 1


def test_a_long_page_gets_every_stop(tmp_path):
    from lumen_api.clone_review.browser import scroll_offsets

    positions = scroll_offsets(5000.0, 900, (0.0, 0.25, 0.5, 0.75, 1.0))
    assert [stop for stop, _ in positions] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert [offset for _, offset in positions] == [0.0, 1025.0, 2050.0, 3075.0, 4100.0]


def test_one_class_failing_does_not_take_the_pass_down_with_it(tmp_path):
    browser = _FakeBrowser()
    walk = _run(browser, tmp_path, plan=walk_plan())
    # A page that refuses to be photographed at all still yields its other observations.
    broken = _FakeBrowser()

    def _boom(*args, **kwargs):
        raise RuntimeError("screenshot refused")

    original = broken.new_page

    def _new_page():
        page = original()
        page.screenshot = _boom
        return page

    broken.new_page = _new_page
    degraded = _run(broken, tmp_path / "b")
    assert degraded.by_class(WALK_CLASS_FULL_PAGE).made is False
    assert degraded.by_class(WALK_CLASS_FULL_PAGE).because == "browser_error"
    assert degraded.by_class(WALK_CLASS_HEIGHT_COLLAPSE).made is True
    assert degraded.by_class(WALK_CLASS_CONSOLE).made is True
    assert walk.by_class(WALK_CLASS_FULL_PAGE).made is True


# --- I2: a present row with no numbers is an abstention, never a conviction ----------------------


def test_a_present_row_with_no_numbers_is_measured_false():
    measurements = measurements_from_probe(
        [{"fragment_id": "frag_c", "selector": ".c", "present": True, "visible": True}],
        viewport="desktop",
    )
    assert measurements[0].present is True
    assert measurements[0].measured is False


def test_an_unmeasured_band_is_never_convicted_of_anything():
    """The last call the previous round's tolerance test stopped short of."""
    unmeasured = measurements_from_probe(
        [{"fragment_id": "frag_c", "selector": ".c", "present": True, "visible": True}],
        viewport="desktop",
    )
    assert broken_clones(unmeasured) == ()
    # It is reported as a gap instead, so the silence is not silent.
    walk = _walk(desktop=unmeasured)
    critique = compose_critique(walk)
    assert critique.broken == ()
    assert [f.code for f in critique.page_findings] == ["review.section_unmeasured"]


def test_a_row_whose_numbers_are_junk_is_also_unmeasured():
    measurements = measurements_from_probe(
        [
            {
                "fragment_id": "frag_c",
                "selector": ".c",
                "present": True,
                "visible": True,
                "width_px": 1440,
                "height_px": "tall",
                "content_extent_px": 10,
                "ink_nodes": 2,
                "scroll_width_px": 1440,
            }
        ],
        viewport="desktop",
    )
    assert measurements[0].measured is False
    assert broken_clones(measurements) == ()


def test_a_complete_row_is_measured_and_judged_normally():
    measurements = measurements_from_probe(
        [
            {
                "fragment_id": "frag_c",
                "selector": ".c",
                "present": True,
                "visible": True,
                "top_px": 10,
                "width_px": 1440,
                "height_px": 3200,
                "content_extent_px": 300,
                "ink_nodes": 4,
                "scroll_width_px": 1440,
                "largest_gap_px": 0,
            }
        ],
        viewport="desktop",
    )
    assert measurements[0].measured is True
    assert [item.reason for item in broken_clones(measurements)] == [
        DEGRADED_REASON_RUNTIME_DEAD_HEIGHT
    ]


# --- I1(a): the shell's console errors are not the page's ---------------------------------------


def test_a_console_error_from_our_own_shell_is_blamed_on_the_shell():
    from lumen_api.clone_review.walk import CONSOLE_SOURCE_PAGE, CONSOLE_SOURCE_SHELL

    shell = ConsoleEntry(level="error", text="tailwind blew up", url="about:blank", line=3)
    page = ConsoleEntry(level="error", text="404", url="https://cdn.test/hero.jpg")
    assert shell.source == CONSOLE_SOURCE_SHELL
    assert page.source == CONSOLE_SOURCE_PAGE
    assert ConsoleEntry(level="error", text="uncaught: boom").source == CONSOLE_SOURCE_SHELL

    findings = console_findings((shell, page))
    codes = [finding.code for finding in findings]
    assert codes == ["review.shell_console_error", "review.console_error"]
    assert findings[0].severity == "warning"
    assert "not the page" in findings[0].message
    assert findings[1].severity == "error"
    assert "hero.jpg" in findings[1].message


# --- I1(b) / R19-1: a durable verdict needs settled evidence ------------------------------------


def _settled_walk(styles_ready, *, desktop=(), mobile=()):
    return BehaviouralWalk(
        observations=(
            WalkObservation(walk_class=WALK_CLASS_FULL_PAGE, made=True),
            WalkObservation(walk_class=WALK_CLASS_SCROLL_THROUGH, made=True),
            WalkObservation(
                walk_class=WALK_CLASS_MOBILE,
                made=True,
                measurements=mobile,
                notes={"styles_ready": styles_ready},
            ),
            WalkObservation(walk_class=WALK_CLASS_CONSOLE, made=True),
            WalkObservation(
                walk_class=WALK_CLASS_HEIGHT_COLLAPSE,
                made=True,
                measurements=desktop,
                notes={"styles_ready": styles_ready},
            ),
            WalkObservation(walk_class=WALK_CLASS_REDUCED_MOTION, made=True, notes={}),
        )
    )


@pytest.mark.parametrize("ready,settled", [(True, True), (False, False), (None, False)])
def test_only_a_page_that_says_it_is_ready_yields_settled_evidence(ready, settled):
    from lumen_api.clone_review.findings import evidence_settled

    dead = _measurement("frag_dead", height_px=3200.0, content_extent_px=200.0)
    walk = _settled_walk(ready, desktop=(dead,))
    assert evidence_settled(walk) is settled
    critique = compose_critique(walk)
    # The FINDING is made either way — what changes is whether it may be written down.
    assert [item.reason for item in critique.broken] == [DEGRADED_REASON_RUNTIME_DEAD_HEIGHT]
    assert critique.settled is settled
    assert critique.as_result()["evidence_settled"] is settled
    unsettled_notes = [
        f for f in critique.page_findings if f.code == "review.evidence_unsettled"
    ]
    assert bool(unsettled_notes) is (not settled)


def test_a_walk_that_measured_nothing_is_settled_by_default():
    from lumen_api.clone_review.findings import evidence_settled

    assert evidence_settled(_settled_walk(None)) is True


def test_the_readiness_probe_answers_a_tri_state(tmp_path):
    for ready in (True, False, None):
        walk = _run(_FakeBrowser(styles_ready=ready), tmp_path / f"r_{ready}")
        assert walk.by_class(WALK_CLASS_HEIGHT_COLLAPSE).notes["styles_ready"] is ready
        assert walk.by_class(WALK_CLASS_MOBILE).notes["styles_ready"] is ready


def test_a_readiness_check_that_answers_nonsense_reads_as_unknown(tmp_path):
    walk = _run(_FakeBrowser(styles_ready="yes please"), tmp_path)
    assert walk.by_class(WALK_CLASS_HEIGHT_COLLAPSE).notes["styles_ready"] is None


# --- M4 / M9: the comparison's two honesty fixes -------------------------------------------------


def test_a_reference_captured_at_a_different_width_is_not_compared_through():
    result = compare_to_reference(
        reference_png=_png(1280, 900),
        capture_png=_png(1440, 900),
        reference_viewport_width=1280,
        rendered_viewport_width=1440,
    )
    assert result["status"] == "unavailable"
    assert result["because"] == "reference_viewport_mismatch"
    assert result["reference_viewport_width"] == 1280


def test_an_unsamplable_whole_page_delta_is_none_rather_than_maximally_different():
    # A capture one pixel tall cannot fill the comparison grid; the honest answer is "no number".
    result = compare_to_reference(
        reference_png=_png(1440, 2000),
        capture_png=_png(1440, 1),
        reference_viewport_width=1440,
        rendered_viewport_width=1440,
    )
    assert result["status"] == "ok"
    assert result["whole_page_pixel_delta"] is None


# =================================================================================================
# Round-2 fixes — the readiness gate must fail CLOSED, and the wrapper must not swallow the extent
# =================================================================================================


def test_the_readiness_predicate_is_anchored_on_our_own_script():
    """It can only ever answer `true` about a page that HAS the runtime.

    The first version asked "is head's last element child an untyped, non-empty style?", which the
    engine's own unconditional `@layer base` block satisfies — so a render with NO Tailwind
    runtime, and therefore no utility CSS at all, read as ready. The predicate now names the
    script we inject.
    """
    from lumen_api.clone_review.walk import STYLES_READY_SCRIPT, TAILWIND_RUNTIME_MARKER

    assert f"script[{TAILWIND_RUNTIME_MARKER}]" in STYLES_READY_SCRIPT
    assert "if (!runtime) return false;" in STYLES_READY_SCRIPT
    # It looks FORWARD from the anchor, so nothing the engine emitted before it can satisfy it.
    assert "nextElementSibling" in STYLES_READY_SCRIPT
    assert "lastElementChild" not in STYLES_READY_SCRIPT


def test_readiness_is_waited_for_not_sampled(tmp_path):
    """Ruling R19-1 asked for a deterministic signal, not a deterministic signal after a sleep."""
    from lumen_api.clone_review.walk import STYLES_READY_TIMEOUT_MS

    ready = _FakeBrowser(styles_ready=True)
    _run(ready, tmp_path / "ready")
    # All three probe passes wait: desktop, mobile, and (since the round-3 asymmetry fix)
    # reduced motion, whose height is divided by the desktop's post-readiness one.
    assert ready.waits == [STYLES_READY_TIMEOUT_MS] * 3

    # A page that never becomes ready waits to the deadline and then answers honestly.
    slow = _FakeBrowser(styles_ready=False)
    walk = _run(slow, tmp_path / "slow")
    assert slow.waits == [STYLES_READY_TIMEOUT_MS] * 3
    assert walk.by_class(WALK_CLASS_HEIGHT_COLLAPSE).notes["styles_ready"] is False


def test_the_scroll_plan_is_built_from_post_readiness_geometry(tmp_path):
    """The stop offsets must come from the COMPILED page's height, not the unstyled one.

    On a slow JIT — the exact page the readiness wait exists for — the unstyled document can
    tower over the compiled one (12,000px of unwrapped flow vs 4,000px of grid). Planning the
    scroll stops off the pre-readiness height re-claims the M3 defect (several captions, one
    clamped position) and the taller-compiled converse never photographs the page bottom. So
    geometry is read only after the readiness wait has resolved.
    """
    plan = walk_plan()
    browser = _FakeBrowser(
        geometry={"height": 12_000, "width": 1440, "viewport": 1440},
        geometry_after_ready={"height": 4_000, "width": 1440, "viewport": 1440},
    )
    walk = _run(browser, tmp_path, plan)
    scrollable = 4_000.0 - plan.desktop.height

    scroll = walk.by_class(WALK_CLASS_SCROLL_THROUGH)
    assert scroll.made
    assert scroll.notes["scrollable_px"] == round(scrollable, 1)

    desktop = browser.pages[0]
    assert desktop.scrolled, "the scroll-through pass scrolled nowhere"
    assert max(desktop.scrolled) <= scrollable, (
        "an offset was planned from the pre-readiness height: "
        f"{max(desktop.scrolled)} > {scrollable}"
    )

    full_page = walk.by_class(WALK_CLASS_FULL_PAGE)
    assert full_page.notes["document_height_px"] == 4_000


def test_the_reduced_motion_height_pair_is_measured_at_the_same_moment(tmp_path):
    """Both halves of the divergence ratio must describe the COMPILED page.

    Moving only the desktop height to post-readiness (fix round 3) made the pair temporally
    asymmetric: on a compiled-TALLER page the reduced pass, read at settle time, still saw the
    unstyled height — a fabricated "content depends on an animation having run" warning about a
    page whose only difference was when it was measured. Now the reduced pass waits too, and the
    finding is gated on both heights being settled.
    """
    from lumen_api.clone_review.findings import compose_critique as compose

    browser = _FakeBrowser(
        geometry={"height": 4_000, "width": 1440, "viewport": 1440},
        geometry_after_ready={"height": 12_000, "width": 1440, "viewport": 1440},
    )
    walk = _run(browser, tmp_path)
    reduced = walk.by_class(WALK_CLASS_REDUCED_MOTION)
    assert reduced.notes["document_height_px"] == 12_000
    assert reduced.notes["motion_document_height_px"] == 12_000
    assert reduced.notes["heights_settled"] is True
    critique = compose(walk)
    assert [f for f in critique.page_findings if f.code == FINDING_REDUCED_MOTION] == []

    # A pair that never settled is no basis for the warning either — unsettled heights compare
    # two unstyled layouts, which is not what the finding claims to be about.
    slow = _FakeBrowser(
        geometry={"height": 4_000, "width": 1440, "viewport": 1440},
        styles_ready=False,
    )
    walk = _run(slow, tmp_path / "slow")
    assert walk.by_class(WALK_CLASS_REDUCED_MOTION).notes["heights_settled"] is False


def test_a_wrapper_with_a_stray_text_node_can_still_be_convicted_of_dead_height():
    """The M1 fix must not disable the detector it sits next to.

    Letting `consider(el)` set the ink extent made `content_fraction` exactly 1.0 for any band
    with a direct text node — so a band with one heading and 3,000px of emptiness could never be
    called dead height, which is the defect D-F6 says is never acceptable at any rung. The probe
    now measures the TEXT, not the band, while still counting the band as non-blank.
    """
    from lumen_api.clone_review.walk import SECTION_PROBE_SCRIPT

    # The wrapper's own box is the DENOMINATOR; only a covering background may claim it.
    assert "considerRect(el.getBoundingClientRect());" in SECTION_PROBE_SCRIPT
    assert "hasBackgroundImage(own)" in SECTION_PROBE_SCRIPT
    # Direct text on the wrapper is measured through a Range, i.e. the text's own rect.
    assert "range.selectNode(child);" in SECTION_PROBE_SCRIPT

    # And the arithmetic downstream still convicts: one heading's worth of ink in a 3200px band.
    band = _measurement("frag_stray", height_px=3200.0, content_extent_px=64.0, ink_nodes=1)
    assert [item.reason for item in broken_clones((band,))] == [
        DEGRADED_REASON_RUNTIME_DEAD_HEIGHT
    ]
    # ...while a band whose ink really does cover it is left alone.
    covered = _measurement("frag_photo", height_px=3200.0, content_extent_px=3200.0, ink_nodes=1)
    assert broken_clones((covered,)) == ()


def test_a_band_whose_only_ink_is_on_the_wrapper_is_not_called_blank():
    """M1's original intent, kept: counted as ink, so never `blank_render`."""
    band = _measurement("frag_bg", height_px=900.0, content_extent_px=900.0, ink_nodes=1)
    assert broken_clones((band,)) == ()


def test_the_console_note_names_every_pass_whose_console_was_actually_heard(tmp_path):
    """Round-2 rider: handlers attach before `set_content`, so a pass that failed to open can
    still have contributed entries. The note now reports what was heard, with `opened` beside it."""
    from lumen_api.clone_review.browser import run_walk

    browser = _FakeBrowser(fail_passes=("mobile",))

    class _Message:
        type = "error"
        text = "boom"
        location = {"url": "https://cdn.test/a.png", "lineNumber": 1}

    original = browser.new_page

    def _new_page():
        page = original()
        real = page.set_content

        def _set_content(html, wait_until="load"):
            real(html, wait_until)
            page.handlers["console"](_Message())

        page.set_content = _set_content
        return page

    browser.new_page = _new_page
    walk = run_walk(
        "<html></html>", walk_plan(), output_dir=tmp_path, browser_factory=_factory(browser)
    )
    console = walk.by_class(WALK_CLASS_CONSOLE)
    # The mobile pass never opened, so it neither opened nor was heard.
    assert console.notes["opened"] == ["desktop", "reduced_motion"]
    assert console.notes["passes"] == ["desktop", "reduced_motion"]
    assert {entry.pass_name for entry in console.console} == {"desktop", "reduced_motion"}


def test_the_result_shapes_carry_their_new_version(tmp_path):
    """Round-2 rider (and the phase fix wave): fields were added, so the versions move.

    Both moved to 3 with `largest_gap_px` (walk finding F-1): the measurements ride INSIDE the
    walk payload too (wave round 2, I2), and a reader of a pre-wave row must treat the field's
    absence as "not measured that way", never as 0.0 ("no hole").
    """
    from lumen_api.clone_review import CRITIQUE_SCHEMA_VERSION, WALK_SCHEMA_VERSION

    assert WALK_SCHEMA_VERSION == 3
    assert CRITIQUE_SCHEMA_VERSION == 3
    walk = _run(_FakeBrowser(), tmp_path)
    assert walk.as_result()["schema_version"] == 3
    assert compose_critique(walk).as_result()["schema_version"] == 3


def test_descendant_direct_text_is_range_measured_like_the_wrapper_branch():
    """Wave round 2, I3 (premise-pinned like the readiness anchor): a full-height inner
    container with one line of text must contribute the TEXT's rect, not its whole box —
    box-measuring it zeroed the internal-gap measure while the mint's pixel detector still saw
    the hole, breaking the two detectors' stated must-agree invariant."""
    from lumen_api.clone_review.walk import SECTION_PROBE_SCRIPT

    descendants = SECTION_PROBE_SCRIPT[SECTION_PROBE_SCRIPT.index("everything inside it") :]
    assert "createRange" in descendants
    assert "selectNode" in descendants
    # The ELEMENT box rect is reserved for media/backgrounds in that branch — exactly one call
    # on the node; text is measured through the Range's own rect.
    assert descendants.count("node.getBoundingClientRect") == 1
    assert "range.getBoundingClientRect" in descendants


# --- the middle hole, runtime half (phase fix wave, walk finding F-1) -----------------------------


def test_a_band_with_an_internal_hole_is_convicted_even_when_its_extent_reads_full():
    """The walk's F-1 at the runtime gate, with its numbers: the real defect was a ~6,100px
    ink-free hole inside a band with content at both ends — extent fraction 0.990, so the old
    single-condition rule read it healthy. The largest merged-interval gap sees it."""
    from lumen_api.clone_review.findings import broken_clones

    holed = _measurement(
        "frag_00000000000000aa",
        height_px=8110.0,
        content_extent_px=8030.0,  # content at both ends: extent ~0.990 of the band
        largest_gap_px=6115.0,
    )
    verdicts = broken_clones((holed,))
    assert [v.reason for v in verdicts] == [DEGRADED_REASON_RUNTIME_DEAD_HEIGHT]

    ordinary = _measurement(
        "frag_00000000000000ab",
        height_px=8110.0,
        content_extent_px=8030.0,
        largest_gap_px=145.0,  # the walk's healthy-page maximum
    )
    assert broken_clones((ordinary,)) == ()
