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
                notes=reduced_notes or {},
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


def test_an_uncaught_page_error_with_no_source_is_attributed_to_the_document():
    findings = console_findings(
        (ConsoleEntry(level="error", text="uncaught: boom", url=None, line=None),)
    )
    assert "the document itself" in findings[0].message


# --- reduced motion --------------------------------------------------------------------------------


def test_a_page_that_shrinks_without_motion_is_reported_as_advice():
    walk = _walk(
        reduced_notes={"document_height_px": 4000.0, "motion_document_height_px": 9000.0}
    )
    critique = compose_critique(walk)
    finding = next(f for f in critique.page_findings if f.code == FINDING_REDUCED_MOTION)
    assert finding.severity == "warning"
    assert finding.detail["shortfall"] == pytest.approx(0.5556, abs=1e-3)


def test_a_page_that_is_the_same_height_without_motion_says_nothing():
    walk = _walk(
        reduced_notes={"document_height_px": 8900.0, "motion_document_height_px": 9000.0}
    )
    critique = compose_critique(walk)
    assert [f for f in critique.page_findings if f.code == FINDING_REDUCED_MOTION] == []


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
