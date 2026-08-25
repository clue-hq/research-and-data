"""The text-collision advisory (fast-loop tuning, 2026-08-24).

The red case is not invented. Every number in `_SHIPPED_AD` below is lifted
verbatim from the scene acceptance run #1 committed to the document as v73 —
`run_4b5dd17f9e944269b94ca45d3bd6d9f2/final_scene.json` — the run whose output
the founder reported as "the headline text overlaps the body copy". That scene's
`preflight.json` reports `has_errors: false`, which is precisely the problem this
module exists to answer: the engine had nothing to say about it.
"""

from __future__ import annotations

import copy
import json

from lumen_agent.text_clearance import (
    NATURAL_LINE_RATIO,
    collision_advisory,
    find_text_collisions,
)


def _text(node_id, *, x, y, width, height, font_size, line_height, content="x"):
    return {
        "id": node_id,
        "kind": {
            "kind": "text",
            "content": content,
            "font_size": font_size,
            "line_height": line_height,
        },
        "children": [],
        # `size` matters only to the borrowed autofix fake engine, which reads it
        # to decide whether a text node overflows. Mirroring the computed box
        # keeps that engine quiet, so these fixtures exercise the collision
        # advisory rather than somebody else's overflow rule.
        "size": {
            "width": {"kind": "fixed", "value": width},
            "height": {"kind": "fixed", "value": height},
        },
        "computed": {
            "layout_bounds": {"x": x, "y": y, "width": width, "height": height},
        },
    }


def _column(node_id, children, *, x=96.0, y=207.0, width=888.0, height=689.0):
    return {
        "id": node_id,
        "kind": {"kind": "auto_layout", "direction": "column"},
        "children": list(children),
        "computed": {
            "layout_bounds": {"x": x, "y": y, "width": width, "height": height},
        },
    }


#: v73's `main` column, verbatim. headline is 80pt on line_height 1.0, which the
#: engine measures as exactly 2 x 80 = 160pt tall; the glyphs need ~192pt, and
#: only 24pt separates the box from `support` below it.
_SHIPPED_AD = {
    "meta": {"id": "doc", "title": "Magic Doc"},
    "pages": {},
    "slots": {},
    "assets": {},
    "nodes": {
        "main": _column("main", ["eyebrow", "headline", "support"]),
        "eyebrow": _text(
            "eyebrow", x=96.0, y=404.0, width=888.0, height=20.0,
            font_size=14.0, line_height=1.4,
            content="MAGIC DOC · FOR SPECIALTY CLINICIANS",
        ),
        "headline": _text(
            "headline", x=96.0, y=448.0, width=888.0, height=160.0,
            font_size=80.0, line_height=1.0,
            content="Clinical notes write themselves.",
        ),
        "support": _text(
            "support", x=96.0, y=632.0, width=888.0, height=68.0,
            font_size=24.0, line_height=1.4,
            content="For specialty clinicians drowning in notes.",
        ),
    },
}


# ===========================================================================
# The red case
# ===========================================================================


def test_the_shipped_ad_that_preflighted_clean_is_reported() -> None:
    """v73's exact geometry. One finding, naming both halves of the real pair."""
    findings = find_text_collisions(_SHIPPED_AD)

    assert len(findings) == 1, findings
    finding = findings[0]
    assert "headline" in finding
    assert "support" in finding
    # The two measurements that make it a collision rather than an opinion:
    # 32pt of spill against 24pt of clearance.
    assert "32pt" in finding
    assert "24pt" in finding
    # And it explains the mechanism, because "your line height is wrong" without
    # the multiplier model is advice the author cannot check.
    assert "font_size x line_height" in finding


def test_the_advisory_names_itself_as_beyond_the_engine() -> None:
    """The author has just read a clean preflight. If the advisory does not say
    why it disagrees with it, the clean preflight wins."""
    advisory = collision_advisory(_SHIPPED_AD)

    assert advisory is not None
    assert "the engine cannot detect this class" in advisory
    assert "Verify each one against the render" in advisory


# ===========================================================================
# Quiet on everything else — the property that decides whether it gets read
# ===========================================================================


def test_a_healthy_column_produces_nothing() -> None:
    """Raise the headline's leading to the natural line box and the same scene,
    unchanged in every other respect, goes silent."""
    healthy = copy.deepcopy(_SHIPPED_AD)
    healthy["nodes"]["headline"]["kind"]["line_height"] = 1.4

    assert find_text_collisions(healthy) == []
    assert collision_advisory(healthy) is None


def test_tight_leading_with_room_for_it_is_not_a_defect() -> None:
    """Tight leading on display type is good typography. The defect is tight
    leading with nowhere for the spill to go, so clearance decides — not the
    line_height on its own."""
    roomy = copy.deepcopy(_SHIPPED_AD)
    # Same 1.0 leading, same 32pt of spill; `support` simply sits further down.
    roomy["nodes"]["support"]["computed"]["layout_bounds"]["y"] = 700.0

    assert find_text_collisions(roomy) == []


def test_a_node_with_nothing_below_it_is_not_a_collision() -> None:
    """The last child in a column spills into empty space, which is a crop
    question for the eyes, not a collision between two elements."""
    lonely = {
        "meta": {}, "pages": {}, "slots": {}, "assets": {},
        "nodes": {
            "main": _column("main", ["headline"]),
            "headline": _text(
                "headline", x=96.0, y=448.0, width=888.0, height=160.0,
                font_size=80.0, line_height=1.0,
            ),
        },
    }
    assert find_text_collisions(lonely) == []


def test_text_over_an_image_is_never_reported() -> None:
    """The single most common intentional overlay in the craft. Restricting the
    sweep to text-versus-text is what keeps this advisory worth reading."""
    overlay = {
        "meta": {}, "pages": {}, "slots": {}, "assets": {},
        "nodes": {
            "hero": {
                "id": "hero",
                "kind": {"kind": "auto_layout", "direction": "column"},
                "children": ["photo", "caption"],
                "computed": {
                    "layout_bounds": {"x": 0.0, "y": 0.0, "width": 1080.0, "height": 600.0}
                },
            },
            "photo": {
                "id": "photo",
                "kind": {"kind": "image"},
                "children": [],
                "computed": {
                    "layout_bounds": {"x": 0.0, "y": 0.0, "width": 1080.0, "height": 600.0}
                },
            },
            "caption": _text(
                "caption", x=96.0, y=440.0, width=600.0, height=60.0,
                font_size=40.0, line_height=1.4,
            ),
        },
    }
    assert find_text_collisions(overlay) == []


# ===========================================================================
# The other branch, and the failure modes
# ===========================================================================


def test_two_text_boxes_that_actually_intersect_are_reported() -> None:
    """Unreachable inside an auto-layout parent, which flows its children — which
    is exactly why it is worth saying when a freely-positioned parent produces
    it."""
    stacked = {
        "meta": {}, "pages": {}, "slots": {}, "assets": {},
        "nodes": {
            "group": {
                "id": "group",
                "kind": {"kind": "group"},
                "children": ["a", "b"],
                "computed": {
                    "layout_bounds": {"x": 0.0, "y": 0.0, "width": 500.0, "height": 200.0}
                },
            },
            "a": _text("a", x=0.0, y=0.0, width=400.0, height=100.0,
                       font_size=40.0, line_height=1.4),
            "b": _text("b", x=50.0, y=50.0, width=400.0, height=100.0,
                       font_size=40.0, line_height=1.4),
        },
    }
    findings = find_text_collisions(stacked)

    assert len(findings) == 1
    assert "overlap" in findings[0]
    assert "almost never intended" in findings[0]


def test_a_malformed_scene_yields_no_findings_rather_than_an_exception() -> None:
    """An advisory must never be the reason a preflight fails."""
    for junk in (
        None,
        {},
        {"nodes": "not a dict"},
        {"nodes": {"a": None}},
        {"nodes": {"a": {"kind": {"kind": "text"}, "children": []}}},  # no computed
        {"nodes": {"p": {"kind": {"kind": "group"}, "children": ["missing"]}}},
    ):
        assert find_text_collisions(junk) == []
        assert collision_advisory(junk) is None


def test_zero_and_negative_type_metrics_are_ignored() -> None:
    """Division by a zero line box is the obvious way to crash this."""
    degenerate = {
        "meta": {}, "pages": {}, "slots": {}, "assets": {},
        "nodes": {
            "main": _column("main", ["a", "b"]),
            "a": _text("a", x=0.0, y=0.0, width=100.0, height=50.0,
                       font_size=0.0, line_height=0.0),
            "b": _text("b", x=0.0, y=60.0, width=100.0, height=50.0,
                       font_size=-12.0, line_height=1.0),
        },
    }
    assert find_text_collisions(degenerate) == []


def test_the_natural_ratio_is_the_only_tunable_and_it_is_conservative() -> None:
    """1.2 is the CSS `normal` approximation and sits just under Inter's ~1.21em.
    Above the real metric it would invent collisions; far below it would miss
    them."""
    assert 1.15 <= NATURAL_LINE_RATIO <= 1.25


# ===========================================================================
# The seam — flag-gated, so a flag-off preflight payload is unchanged
# ===========================================================================


def test_the_advisory_rides_preflight_only_under_the_flag(tmp_path, monkeypatch) -> None:
    """Wiring, at the real tool. `_tools` is borrowed from the autofix suite
    rather than re-faked here: it is the same substrate seam, and a second fake
    engine would be a second thing to keep true."""
    from test_autofix import _tools

    off = _tools(tmp_path, monkeypatch, _SHIPPED_AD)
    off_payload = json.loads(off.preflight_design())
    assert "text_collisions" not in off_payload
    assert set(off_payload) == {"preflight", "raw_preflight", "effective_brand"}

    on = _tools(tmp_path, monkeypatch, _SHIPPED_AD, fast_loop=True)
    on_payload = json.loads(on.preflight_design())
    assert "text_collisions" in on_payload
    assert "headline" in on_payload["text_collisions"]
    assert "support" in on_payload["text_collisions"]
    # Advisory, not a gate: it must not have made the preflight fail.
    assert on_payload["preflight"]["has_errors"] is False


def test_a_clean_scene_adds_no_key_even_under_the_flag(tmp_path, monkeypatch) -> None:
    """Silence on a clean scene is the whole reason the advisory stays readable."""
    from test_autofix import _tools

    healthy = copy.deepcopy(_SHIPPED_AD)
    healthy["nodes"]["headline"]["kind"]["line_height"] = 1.4

    tools = _tools(tmp_path, monkeypatch, healthy, fast_loop=True)
    payload = json.loads(tools.preflight_design())

    assert "text_collisions" not in payload
