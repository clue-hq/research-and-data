"""Tests for the accommodation-edits conflict detector
(.context/agent-improvement/2026-07-05-accommodation-edits.md).

Fixtures are built from the REAL geometry measured in the calibration
section, off run_e0bb1733's final_scene.json (the user-confirmed "too
close" case): badge (884,48,148,40) moved from baseline (176,1088,180,40);
header (88,88,904,36); organizer (715,88,520,36) with children yc_mark
(715,88,36,36) + organizer_label (761,95,460,22); main (88,124,904,808)
with eyebrow (90,256,904,21), hero (88,292,904,334), subtitle
(88,633,860,71), details (88,704,904,53); footer (88,932,904,60) with note
(88,948,600,28); artboard (0,0,1080,1080), page startup_door 1080x1080.

Deviation from the brief: case D's suggested probe coordinates
(700,170,148,40) actually overlap `main` (header's row 88-124 sits flush
against main's top at y=124 with zero baked gap between them, and a 40pt-tall
badge starting at y=170 extends well past both header and 16pt clear of
nothing). The real geometry requires the badge to sit inside the header's
own row (y in [88,124)) to clear `main` by >=16pt, so case D here uses
(300,88,148,20): clearance to main is exactly 16 (boundary, not a conflict),
to organizer 267, to footer 824 — zero conflicts, as calibrated.
"""

from __future__ import annotations

from typing import Dict

from lumen_pipeline_archive.accommodation import (
    CONFLICT_CLEARANCE_THRESHOLD,
    clearance,
    page_space_box,
    turn_introduced_conflicts,
)


def box(x: float, y: float, w: float, h: float) -> Dict[str, float]:
    return {"x": x, "y": y, "width": w, "height": h}


# Real geometry from run_e0bb1733's final_scene.json.
BASELINE_BADGE_BOX = (176.0, 1088.0, 180.0, 40.0)
CONFLICT_BADGE_BOX = (884.0, 48.0, 148.0, 40.0)


def make_scene(badge_box=CONFLICT_BADGE_BOX, *, badge_visible=None):
    """Build the startup_door scene shape with a parametrizable badge box.

    Mirrors the real node graph: artboard -> header -> {badge, organizer},
    artboard -> main -> {eyebrow, hero, subtitle, details},
    artboard -> footer -> {note}. `badge` and `eyebrow` carry `absolute_box`
    (pinned/human-placed) like the real scene; everything else resolves via
    `computed.layout_bounds`.
    """
    badge_node = {
        "children": ["badge_text"],
        "absolute_box": box(*badge_box),
    }
    if badge_visible is not None:
        badge_node["visible"] = badge_visible

    nodes = {
        "artboard": {"children": ["header", "main", "footer"]},
        "header": {
            "children": ["badge", "organizer"],
            "computed": {"layout_bounds": box(88, 88, 904, 36)},
        },
        "badge": badge_node,
        "badge_text": {"children": []},
        "organizer": {
            "children": ["yc_mark", "organizer_label"],
            "computed": {"layout_bounds": box(715, 88, 520, 36)},
        },
        "yc_mark": {
            "children": [],
            "computed": {"layout_bounds": box(715, 88, 36, 36)},
        },
        "organizer_label": {
            "children": [],
            "computed": {"layout_bounds": box(761, 95, 460, 22)},
        },
        "main": {
            "children": ["eyebrow", "hero", "subtitle", "details"],
            "computed": {"layout_bounds": box(88, 124, 904, 808)},
        },
        "eyebrow": {
            "children": [],
            "absolute_box": box(90, 256, 904, 21),
        },
        "hero": {
            "children": [],
            "computed": {"layout_bounds": box(88, 292, 904, 334)},
        },
        "subtitle": {
            "children": [],
            "computed": {"layout_bounds": box(88, 633, 860, 71)},
        },
        "details": {
            "children": [],
            "computed": {"layout_bounds": box(88, 704, 904, 53)},
        },
        "footer": {
            "children": ["note"],
            "computed": {"layout_bounds": box(88, 932, 904, 60)},
        },
        "note": {
            "children": [],
            "computed": {"layout_bounds": box(88, 948, 600, 28)},
        },
    }
    return {
        "nodes": nodes,
        "pages": {"startup_door": {"children": ["artboard"]}},
    }


def baseline_scene():
    return make_scene(BASELINE_BADGE_BOX)


# ---------------------------------------------------------------------------
# Calibration cases A-E
# ---------------------------------------------------------------------------


def test_case_a_badge_moved_conflicts_with_organizer_rolled_up():
    current = make_scene(CONFLICT_BADGE_BOX)
    results = turn_introduced_conflicts(baseline_scene(), current, {"badge"})

    assert len(results) == 1
    entry = results[0]
    assert entry["edited"] == "badge"
    assert entry["neighbor"] == "organizer"  # rolled up, NOT yc_mark
    assert entry["clearance"] == 0.0
    assert entry["overlap"] is False


def test_case_b_badge_overlaps_footer_note():
    # (80,940,180,40): overlaps both `note` and its parent `footer`.
    overlapping_badge = (80.0, 940.0, 180.0, 40.0)
    current = make_scene(overlapping_badge)
    results = turn_introduced_conflicts(baseline_scene(), current, {"badge"})

    conflict_ids = {r["neighbor"] for r in results}
    # `note`'s parent `footer` ALSO conflicts (clearance -40 vs note's -28),
    # so the roll-up rule (topmost ancestor that still clears < threshold)
    # promotes the reported neighbor to "footer", not "note".
    assert "footer" in conflict_ids
    assert "note" not in conflict_ids

    footer_entry = next(r for r in results if r["neighbor"] == "footer")
    assert footer_entry["overlap"] is True
    assert footer_entry["clearance"] < 0


def test_case_c_subtitle_details_adjacency_never_flagged_when_unedited():
    current = baseline_scene()
    # No edits at all: baseline pairs (subtitle<->details at 0pt) must never
    # surface, since nothing was edited this turn.
    results = turn_introduced_conflicts(baseline_scene(), current, set())
    assert results == []

    # Editing an unrelated node (badge, moved to a clear spot) must still
    # never surface the pre-existing subtitle<->details adjacency, since
    # neither of that pair was edited.
    current_with_edit = make_scene((300.0, 88.0, 148.0, 20.0))
    results_edit = turn_introduced_conflicts(
        baseline_scene(), current_with_edit, {"badge"}
    )
    assert all(
        {"subtitle", "details"} != {r["edited"], r["neighbor"]}
        for r in results_edit
    )


def test_case_d_badge_moved_to_clear_spot_zero_conflicts():
    # Real geometry deviation: header's row (y in [88,124)) sits flush
    # against main's top (y=124) with a zero baked gap already, so the badge
    # must stay inside that 36pt-tall row and end by y<=108 to clear `main`
    # by >=16pt. (300,88,148,20) clears main by exactly 16 (not a conflict),
    # organizer by 267, footer by 824.
    clear_badge_box = (300.0, 88.0, 148.0, 20.0)
    current = make_scene(clear_badge_box)

    badge_box = box(*clear_badge_box)
    assert clearance(badge_box, box(88, 124, 904, 808)) == 16  # main
    assert clearance(badge_box, box(715, 88, 520, 36)) >= CONFLICT_CLEARANCE_THRESHOLD  # organizer
    assert clearance(badge_box, box(88, 932, 904, 60)) >= CONFLICT_CLEARANCE_THRESHOLD  # footer
    assert clearance(badge_box, box(88, 292, 904, 334)) >= CONFLICT_CLEARANCE_THRESHOLD  # hero

    results = turn_introduced_conflicts(baseline_scene(), current, {"badge"})
    assert results == []


def test_case_e_badge_header_never_reported_ancestor_exclusion():
    current = make_scene(CONFLICT_BADGE_BOX)
    results = turn_introduced_conflicts(baseline_scene(), current, {"badge"})
    assert all(r["neighbor"] != "header" for r in results)

    # Also true for the clear-spot and overlap cases, and even when we crank
    # the threshold up so header WOULD otherwise be considered "close".
    for candidate_box in (CONFLICT_BADGE_BOX, (300.0, 88.0, 148.0, 20.0)):
        current_variant = make_scene(candidate_box)
        results_variant = turn_introduced_conflicts(
            baseline_scene(), current_variant, {"badge"}, threshold=10_000.0
        )
        assert all(r["neighbor"] != "header" for r in results_variant)
        assert all(r["edited"] != "header" for r in results_variant)


# ---------------------------------------------------------------------------
# page_space_box
# ---------------------------------------------------------------------------


def test_page_space_box_prefers_absolute_box():
    node = {
        "absolute_box": box(1, 2, 3, 4),
        "computed": {"layout_bounds": box(9, 9, 9, 9)},
    }
    assert page_space_box(node) == box(1, 2, 3, 4)


def test_page_space_box_falls_back_to_layout_bounds():
    node = {"computed": {"layout_bounds": box(5, 6, 7, 8)}}
    assert page_space_box(node) == box(5, 6, 7, 8)


def test_page_space_box_none_when_neither_present():
    assert page_space_box({}) is None
    assert page_space_box({"computed": {}}) is None
    assert page_space_box({"absolute_box": None, "computed": None}) is None


# ---------------------------------------------------------------------------
# clearance() regimes
# ---------------------------------------------------------------------------


def test_clearance_diagonal_hypot_when_both_gaps_positive():
    a = box(0, 0, 10, 10)  # spans x:[0,10] y:[0,10]
    b = box(13, 14, 10, 10)  # spans x:[13,23] y:[14,24]
    # gx = 13 - 10 = 3, gy = 14 - 10 = 4 -> hypot(3,4) = 5
    assert clearance(a, b) == 5.0


def test_clearance_single_axis_gap_when_one_positive():
    a = box(0, 0, 10, 10)  # x:[0,10] y:[0,10]
    b = box(20, 0, 10, 10)  # x:[20,30] y:[0,10] (same rows, gap only on x)
    # gx = 20 - 10 = 10, gy = 0 - 10 = -10 -> single positive gap = 10
    assert clearance(a, b) == 10.0


def test_clearance_true_overlap_returns_less_negative_penetration():
    a = box(0, 0, 10, 10)  # x:[0,10] y:[0,10]
    b = box(4, 4, 10, 10)  # x:[4,14] y:[4,14]
    # gx = 4 - 10 = -6, gy = 4 - 10 = -6 -> max(-6,-6) = -6
    assert clearance(a, b) == -6.0

    c = box(2, 8, 10, 10)  # x:[2,12] y:[8,18] -> gx = 2-10=-8, gy=8-10=-2
    # max(-8, -2) = -2 (the shallower / less-negative penetration)
    assert clearance(a, c) == -2.0


def test_clearance_threshold_boundary():
    a = box(0, 0, 10, 10)
    b_exact = box(16, 0, 10, 10)  # gx = 16-10 = 6... adjust for exact 16
    # Build directly for an exact-16 single-axis gap.
    b_16 = box(26, 0, 10, 10)  # gx = 26-10 = 16
    assert clearance(a, b_16) == 16.0
    assert not (clearance(a, b_16) < CONFLICT_CLEARANCE_THRESHOLD)

    b_15_9 = box(25.9, 0, 10, 10)  # gx = 25.9-10 = 15.9
    assert abs(clearance(a, b_15_9) - 15.9) < 1e-9
    assert clearance(a, b_15_9) < CONFLICT_CLEARANCE_THRESHOLD


# ---------------------------------------------------------------------------
# Other detector rules: baseline-missing, visible:false, both-edited
# ---------------------------------------------------------------------------


def test_baseline_missing_node_counts_as_eligible():
    # A neighbor absent from the baseline entirely (e.g. newly inserted this
    # turn) has no baseline clearance to protect it -> still eligible to
    # conflict.
    current = make_scene(CONFLICT_BADGE_BOX)
    baseline = baseline_scene()
    # Remove organizer AND yc_mark/organizer_label from the baseline scene's
    # nodes entirely, simulating "this node didn't exist at baseline".
    del baseline["nodes"]["organizer"]
    del baseline["nodes"]["yc_mark"]
    del baseline["nodes"]["organizer_label"]

    results = turn_introduced_conflicts(baseline, current, {"badge"})
    entry = next(r for r in results if r["neighbor"] == "organizer")
    assert entry["baseline_clearance"] is None


def test_visible_false_neighbor_skipped():
    current = make_scene(CONFLICT_BADGE_BOX)
    current["nodes"]["organizer"]["visible"] = False
    current["nodes"]["yc_mark"]["visible"] = False
    current["nodes"]["organizer_label"]["visible"] = False

    results = turn_introduced_conflicts(baseline_scene(), current, {"badge"})
    assert all(r["neighbor"] != "organizer" for r in results)


def test_both_edited_pair_skipped():
    # If organizer is ALSO edited this turn, the badge<->organizer pair is
    # the author's own coordination and must not be reported.
    current = make_scene(CONFLICT_BADGE_BOX)
    results = turn_introduced_conflicts(
        baseline_scene(), current, {"badge", "organizer"}
    )
    assert all(r["neighbor"] != "organizer" for r in results)
