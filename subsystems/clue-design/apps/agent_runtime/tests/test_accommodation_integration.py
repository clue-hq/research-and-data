"""Integration tests for the accommodation-edits loop wiring
(.context/agent-improvement/2026-07-05-accommodation-edits.md).

`tests/test_accommodation.py` covers the detector (`turn_introduced_conflicts`)
in isolation. This file drives the FULL `LumenQualityLoop` against a SEEDED
scene with fakes, exercising the wiring in `lumen_deepagent/loop.py`:

  - `baseline_scene` capture in `run()` (deep-copied pre-first-edit geometry).
  - `_detect_accommodation_conflicts()` after the preflight-clean draft:
    appends a `previous_feedback` entry (`kind="mechanical_crowding"`) and
    records the `"accommodation_conflicts"` trace event.
  - `_accommodation_scope_node_ids()` unioned into edit-scoped-acceptance
    scope, so a blocking critique on a crowded (but unedited) neighbor still
    blocks.
  - `_accommodation_payload_json()` threaded into every `finalize_run` as the
    `"accommodation"` key of `final.json`.

Geometry reused verbatim from `test_accommodation.py`'s calibration fixtures
(run_e0bb1733): badge (884,48,148,40) vs baseline (176,1088,180,40);
organizer (715,88,520,36) with children yc_mark (715,88,36,36) +
organizer_label (761,95,460,22); footer (88,932,904,60) with note
(88,948,600,28).
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_deepagent.loop import LumenQualityLoop
from lumen_deepagent.schemas import VisualCritique, VisualIssue, VisualTarget

from test_lumen_deepagent_runtime import FakeCoreClient, ScriptedAuthor, ScriptedReviewer, runtime_config
from test_seeded_continuation import trace_events
from lumen_deepagent.tools import LumenDesignTools


def box(x: float, y: float, w: float, h: float) -> dict:
    return {"x": x, "y": y, "width": w, "height": h}


# Real geometry from run_e0bb1733's final_scene.json (mirrors test_accommodation.py).
BASELINE_BADGE_BOX = (176.0, 1088.0, 180.0, 40.0)
CONFLICT_BADGE_BOX = (884.0, 48.0, 148.0, 40.0)
# Organizer nudged down 24pt: (715, 112, 520, 36) clears the conflict badge
# box (884,48,148,40) — vertical gap = 112 - (48+40) = 24 >= 16.
NUDGED_ORGANIZER_BOX = (715.0, 112.0, 520.0, 36.0)


def accommodation_seed_scene(badge_box=BASELINE_BADGE_BOX) -> dict:
    """A minimal seeded scene carrying the startup_door geometry: badge clear
    of organizer at baseline (badge parked at the bottom, as in
    test_accommodation.py's `baseline_scene()`)."""
    return {
        "meta": {"id": "doc_live", "title": "Startup door", "status": {"kind": "draft"}},
        "pages": {
            "startup_door": {
                "id": "startup_door",
                "children": ["artboard"],
            }
        },
        "nodes": {
            "artboard": {"id": "artboard", "children": ["header", "main", "footer"]},
            "header": {
                "id": "header",
                "children": ["badge", "organizer"],
                "computed": {"layout_bounds": box(88, 88, 904, 36)},
            },
            "badge": {
                "id": "badge",
                "kind": {"kind": "text", "content": "SPEAKER"},
                "children": [],
                "absolute_box": box(*badge_box),
            },
            "organizer": {
                "id": "organizer",
                "children": ["yc_mark", "organizer_label"],
                "computed": {"layout_bounds": box(715, 88, 520, 36)},
            },
            "yc_mark": {
                "id": "yc_mark",
                "children": [],
                "computed": {"layout_bounds": box(715, 88, 36, 36)},
            },
            "organizer_label": {
                "id": "organizer_label",
                "children": [],
                "computed": {"layout_bounds": box(761, 95, 460, 22)},
            },
            "main": {
                "id": "main",
                "children": [],
                "computed": {"layout_bounds": box(88, 124, 904, 808)},
            },
            "footer": {
                "id": "footer",
                "children": ["note"],
                "computed": {"layout_bounds": box(88, 932, 904, 60)},
            },
            "note": {
                "id": "note",
                "children": [],
                "computed": {"layout_bounds": box(88, 948, 600, 28)},
            },
        },
        "slots": {},
        "assets": {},
    }


class FakeBadgeMoveCoreClient(FakeCoreClient):
    """Iteration 1 compile moves `badge` into the crowding position (clear of
    organizer at baseline, 0pt clearance at current) via a single position-only
    op naming `badge`. Iteration 2+ (if scripted) is a no-op passthrough that
    keeps the moved badge and optionally nudges `organizer` — subclasses hook
    `_apply_iteration` to vary iteration 2 behavior."""

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls = getattr(self, "compile_calls", 0) + 1
        updated = json.loads(json.dumps(scene))
        if self.compile_calls == 1:
            updated["nodes"]["badge"]["absolute_box"] = box(*CONFLICT_BADGE_BOX)
            op_node_id = "badge"
        else:
            op_node_id = self._second_iteration(updated)
        return {
            "scene": updated,
            "applied_operations": 1,
            "dsl": {
                "compile_output": {
                    "operations": [{"kind": "update_node", "node_id": op_node_id}],
                    "diagnostics": [],
                },
                "operation_error": None,
                "session_snapshot": None,
            },
        }

    def _second_iteration(self, updated: dict) -> str:
        """Default: no further edits (used when a test never reaches iter 2)."""
        return "badge"


class FakeBadgeMoveThenOrganizerNudgeCoreClient(FakeBadgeMoveCoreClient):
    """Iteration 2 nudges `organizer` (and its children, which move WITH their
    container) down 24pt, resolving the crowding."""

    def _second_iteration(self, updated: dict) -> str:
        updated["nodes"]["organizer"]["computed"]["layout_bounds"] = box(
            *NUDGED_ORGANIZER_BOX
        )
        updated["nodes"]["yc_mark"]["computed"]["layout_bounds"] = box(
            715, 112, 36, 36
        )
        updated["nodes"]["organizer_label"]["computed"]["layout_bounds"] = box(
            761, 119, 460, 22
        )
        return "organizer"


def _mechanical_crowding_entries(previous_feedback: list[dict]) -> list[dict]:
    return [f for f in previous_feedback if f.get("kind") == "mechanical_crowding"]


def final_json(config, run_id: str) -> dict:
    return json.loads((config.trace_dir / run_id / "final.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1) Conflict detected + announced (critic accepts despite missing it)
# ---------------------------------------------------------------------------


def test_conflict_detected_and_announced_when_reviewer_accepts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeBadgeMoveCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(
        config, "Move the badge", initial_scene=accommodation_seed_scene()
    )
    author = ScriptedAuthor(["#badge p(884,48)"])
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="Looks good.")])

    result = LumenQualityLoop(tools, author, reviewer).run("Move the badge")

    assert result["status"] == "accepted"
    assert result["stop_reason"] == "accepted"

    # Trace carries the accommodation_conflicts event.
    assert "accommodation_conflicts" in trace_events(config, tools.run_id)

    # The reviewer's call received previous_feedback containing the
    # mechanical_crowding entry (the critic "missed it" but the mechanism
    # still surfaced the conflict in its context).
    assert len(reviewer.calls) == 1
    reviewer_feedback = reviewer.calls[0]["previous_feedback"]
    crowding_entries = _mechanical_crowding_entries(reviewer_feedback)
    assert len(crowding_entries) == 1
    conflicts = crowding_entries[0]["feedback"]["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["edited"] == "badge"
    assert conflicts[0]["neighbor"] == "organizer"

    # final.json's accommodation payload names edited "badge" + neighbor
    # "organizer", is non-null, and unresolved is non-empty (never repaired).
    payload = final_json(config, tools.run_id)
    accommodation = payload["accommodation"]
    assert accommodation is not None
    detected = accommodation["detected"]
    assert len(detected) == 1
    assert detected[0]["edited"] == "badge"
    assert detected[0]["neighbor"] == "organizer"
    assert len(accommodation["unresolved"]) == 1
    assert accommodation["unresolved"][0]["neighbor"] == "organizer"


# ---------------------------------------------------------------------------
# 2) Scope expansion BLOCKS a critique targeting the crowded (unedited)
#    neighbor, where plain edit-scoped-acceptance would have waved it through.
# ---------------------------------------------------------------------------


def test_accommodation_scope_expansion_blocks_on_crowded_neighbor(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeBadgeMoveThenOrganizerNudgeCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(
        config, "Move the badge", initial_scene=accommodation_seed_scene()
    )
    author = ScriptedAuthor(["#badge p(884,48)", "#organizer p(715,112)"])
    reviewer = ScriptedReviewer(
        [
            VisualCritique(
                accepted=False,
                summary="organizer is crowded by the moved badge",
                issues=[
                    VisualIssue(
                        severity="error",
                        category="hierarchy",
                        message="organizer sits too close to the badge",
                        suggested_repair="nudge organizer down",
                        target=VisualTarget(page_id="startup_door", node_id="organizer"),
                    )
                ],
            ),
            VisualCritique(accepted=True, summary="Resolved."),
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Move the badge")

    # Iteration 1's blocker targets "organizer" — NOT an edited node — but IS
    # a conflict neighbor. Without accommodation scope expansion, edit-scoped
    # acceptance would have waved this through on iteration 1. It must not.
    assert len(author.requests) == 2
    assert result["status"] == "accepted"
    assert result["stop_reason"] == "accepted"
    events = trace_events(config, tools.run_id)
    # edit_scoped_acceptance never fires this run (iteration 1 blocked and
    # repaired; iteration 2 the reviewer explicitly accepts).
    assert "edit_scoped_acceptance" not in events
    assert "accommodation_conflicts" in events

    # By iteration 2 the organizer nudge resolved the conflict.
    payload = final_json(config, tools.run_id)
    accommodation = payload["accommodation"]
    assert accommodation is not None
    assert accommodation["unresolved"] == []
    applied = accommodation["applied_nudges"]
    assert applied == [{"node": "organizer", "dx": 0.0, "dy": 24.0}]


# ---------------------------------------------------------------------------
# 3) Control for #2: a blocker on an UNRELATED pre-existing node (footer, not
#    edited, not a conflict neighbor) still lets edit_scoped_acceptance fire —
#    proving the expansion is exactly the conflict neighbors, not everything.
# ---------------------------------------------------------------------------


def test_edit_scoped_acceptance_still_fires_for_unrelated_node(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeBadgeMoveCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(
        config, "Move the badge", initial_scene=accommodation_seed_scene()
    )
    author = ScriptedAuthor(["#badge p(884,48)"])
    reviewer = ScriptedReviewer(
        [
            VisualCritique(
                accepted=False,
                summary="footer note is a placeholder",
                issues=[
                    VisualIssue(
                        severity="error",
                        category="request_satisfaction",
                        message="footer note reads as a placeholder",
                        suggested_repair="write real copy",
                        target=VisualTarget(page_id="startup_door", node_id="footer"),
                    )
                ],
            )
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Move the badge")

    assert result["status"] == "edit_applied"
    assert result["stop_reason"] == "edit_scoped_acceptance"
    assert len(author.requests) == 1  # no repair iteration burned
    events = trace_events(config, tools.run_id)
    assert "edit_scoped_acceptance" in events
    assert "accommodation_conflicts" in events  # conflict still detected...

    payload = final_json(config, tools.run_id)
    accommodation = payload["accommodation"]
    assert accommodation is not None
    # ...and remains unresolved (this run never touched organizer), but the
    # unrelated footer blocker did NOT expand scope to include it.
    assert len(accommodation["unresolved"]) == 1
    assert accommodation["unresolved"][0]["neighbor"] == "organizer"


# ---------------------------------------------------------------------------
# 4) Applied nudge announced: iteration 2 nudges organizer; the payload keeps
#    reporting the nudge even though organizer is no longer a "latest"
#    conflict (it's now an edited node, excluded from re-detection).
# ---------------------------------------------------------------------------


def test_applied_nudge_is_announced_even_though_organizer_becomes_edited(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeBadgeMoveThenOrganizerNudgeCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(
        config, "Move the badge", initial_scene=accommodation_seed_scene()
    )
    author = ScriptedAuthor(["#badge p(884,48)", "#organizer p(715,112)"])
    reviewer = ScriptedReviewer(
        [
            VisualCritique(
                accepted=False,
                summary="organizer crowded",
                issues=[
                    VisualIssue(
                        severity="error",
                        category="hierarchy",
                        message="organizer sits too close to the badge",
                        suggested_repair="nudge organizer down",
                        target=VisualTarget(page_id="startup_door", node_id="organizer"),
                    )
                ],
            ),
            VisualCritique(accepted=True, summary="Resolved."),
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Move the badge")

    assert result["status"] == "accepted"
    assert len(author.requests) == 2

    payload = final_json(config, tools.run_id)
    accommodation = payload["accommodation"]
    assert accommodation is not None
    # Latest detection (post iteration 2) is empty: organizer is now an
    # edited node, so the (badge, organizer) pair is excluded as
    # "both edited" / re-detection sees no conflicts.
    assert accommodation["unresolved"] == []
    # But applied_nudges STILL reports organizer's move, diffed against the
    # baseline scene (via the conflict LOG, not the latest empty detection).
    assert accommodation["applied_nudges"] == [
        {"node": "organizer", "dx": 0.0, "dy": 24.0}
    ]
    detected = accommodation["detected"]
    assert len(detected) == 1
    assert detected[0]["edited"] == "badge"
    assert detected[0]["neighbor"] == "organizer"


# ---------------------------------------------------------------------------
# 5) Unseeded run: no baseline_scene capture -> no accommodation machinery.
# ---------------------------------------------------------------------------


def test_unseeded_run_has_no_accommodation_payload(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])

    loop = LumenQualityLoop(tools, author, reviewer)
    result = loop.run("Create a square ad")

    assert result["status"] == "accepted"
    assert loop.baseline_scene is None
    assert result.get("accommodation") is None
    assert _mechanical_crowding_entries(loop.previous_feedback) == []
    assert "accommodation_conflicts" not in trace_events(config, tools.run_id)
