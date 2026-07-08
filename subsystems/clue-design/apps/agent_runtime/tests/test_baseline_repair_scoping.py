"""Agent-improvement follow-ups from the frozen-doc turn wedge
(.context/agent-improvement/2026-07-05-frozen-doc-turn-wedge.md,
run_4a0feb15048e4fbe993029bd2cab436f):

1. Baseline-diff repair scoping — the Phase A preflight gate must block ONLY
   on errors THIS TURN introduced, never on errors that already existed on the
   seeded scene. Pre-existing errors are surfaced as advisory context instead
   of burning the repair-iteration budget.
3. Freehand state in the INITIAL brief — `input.json`'s scene summary must
   carry the same freehand block (free_containers / pinned_nodes / note) that
   repair requests already see, so the author is never blind to frozen
   geometry on the first pass.
5. Insert-into-frozen guidance — covered in test_seeded_continuation.py's
   `test_seeded_recipe_carries_the_freehand_rules`; this file only asserts the
   NEW insert-transform guidance text (kept here since it is adjacent to the
   freehand contract these tests exercise).
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_deepagent.loop import LumenQualityLoop
from lumen_deepagent.prompts import SEEDED_CONTINUATION_RECIPE
from lumen_deepagent.schemas import VisualCritique
from lumen_deepagent.tools import LumenDesignTools

from test_lumen_deepagent_runtime import FakeCoreClient, ScriptedAuthor, ScriptedReviewer, runtime_config
from test_seeded_continuation import freehand_seed_scene, seed_scene_dict, trace_events


BASELINE_DIAGNOSTIC = {
    "severity": "error",
    "code": "LUMV0810",
    "message": "slot event.eyebrow fixture overflows text node kicker",
    "target_slot_id": "slot_event_eyebrow",
    "hint": None,
}


class FakeBaselineErrorPreflightCoreClient(FakeCoreClient):
    """Preflight ALWAYS reports the SAME pre-existing error (fixed subject),
    as if it were a legacy slot-fixture overflow baked into the seeded doc.
    Counts calls so a test can assert the baseline capture + iteration 1's own
    preflight both see it, unchanged."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.preflight_calls = 0

    def preflight_scene(self, scene, brand_kit, brand_fonts=None):
        self.preflight_calls += 1
        return {
            "scene": scene,
            "diagnostics": [dict(BASELINE_DIAGNOSTIC)],
            "preflight": {
                "has_errors": True,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }


class FakeBaselineErrorPlusIntroducedCoreClient(FakeCoreClient):
    """Same constant baseline error as above, PLUS a NEW error on `headline`
    that appears once compile has run with a too-small size and clears once
    the author widens it (`s(900,120)`) — i.e. a real, fixable introduced
    error, not a permanent one. Never appears on the pre-loop baseline
    capture (that call happens before any compile, so `introduced_error` is
    still False)."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.introduced_error = False
        self.preflight_calls = 0

    def compile_dsl_into_scene(
        self, scene, source: str, dsl_session=None, protected_node_ids=None
    ):
        self.introduced_error = "s(900,120)" not in source
        return super().compile_dsl_into_scene(
            scene, source, dsl_session=dsl_session, protected_node_ids=protected_node_ids
        )

    def preflight_scene(self, scene, brand_kit, brand_fonts=None):
        self.preflight_calls += 1
        diagnostics = [dict(BASELINE_DIAGNOSTIC)]
        if self.introduced_error:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "LUMV0903",
                    "message": "text node headline exceeds available height",
                    "target_node_id": "headline",
                    "hint": "Use hug height or reduce the headline font size.",
                }
            )
        return {
            "scene": scene,
            "diagnostics": diagnostics,
            "preflight": {
                "has_errors": True,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }


# --- Gap 1: baseline-diff repair scoping ------------------------------------------


def test_baseline_error_present_and_turn_introduces_none_converges_on_iteration_one(
    tmp_path: Path, monkeypatch
):
    """The exact wedge from run_4a0feb15048e4fbe993029bd2cab436f: a seeded doc
    carries a pre-existing preflight ERROR unrelated to the turn's edit. The
    turn's own edit introduces no new errors. The Phase A gate must treat
    iteration 1 as CLEAN (the baseline error is advisory, never blocking) and
    reach acceptance without spending a single repair iteration on it."""
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeBaselineErrorPreflightCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(
        config, "Move the headline", initial_scene=seed_scene_dict()
    )
    author = ScriptedAuthor(['#headline p(48,48)'])
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="Looks good.")])

    result = LumenQualityLoop(tools, author, reviewer).run("Move the headline")

    assert result["status"] == "accepted"
    # Exactly one authoring attempt — no repair iteration was ever spent on
    # the pre-existing LUMV0810.
    assert len(author.requests) == 1
    assert "repair_requested" not in trace_events(config, tools.run_id)

    # The baseline WAS captured (against the seeded scene, before any edit)...
    assert tools.core.preflight_calls >= 1
    # ...and it rides along as advisory in the final result, not silently
    # dropped and not treated as a turn failure.
    advisory = result.get("baseline_advisory")
    assert advisory is not None
    assert advisory["count"] == 1
    assert advisory["diagnostics"][0]["code"] == "LUMV0810"
    assert "predate this turn" in advisory["note"]


def test_turn_introduced_error_still_blocks_and_repairs(tmp_path: Path, monkeypatch):
    """A baseline error rides along as advisory, but an error THIS TURN
    introduces must still gate the draft and drive a real repair — baseline
    scoping must not become a blanket amnesty for every error."""
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeBaselineErrorPlusIntroducedCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(
        config, "Widen the headline", initial_scene=seed_scene_dict()
    )
    author = ScriptedAuthor(
        ['#headline s(900,40)', '#headline s(900,120)']
    )
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])

    result = LumenQualityLoop(tools, author, reviewer).run("Widen the headline")

    assert result["status"] == "accepted"
    # The introduced LUMV0903 forced a real repair round: two authoring
    # attempts, with a repair request recorded for iteration 1's failure.
    assert len(author.requests) == 2
    assert "repair_requested" in trace_events(config, tools.run_id)
    # The repair request's diagnostics carry ONLY the introduced error, never
    # the pre-existing LUMV0810 — the model must not be asked to fix baseline
    # issues it was never told about as a blocking concern.
    repair_context = author.requests[1].repair_context
    assert repair_context["kind"] == "preflight"
    repaired_codes = {
        diag["code"] for diag in repair_context["feedback"]["diagnostics"]
    }
    assert repaired_codes == {"LUMV0903"}
    assert "baseline_advisory" in repair_context
    assert repair_context["baseline_advisory"]["count"] == 1
    assert repair_context["baseline_advisory"]["diagnostics"][0]["code"] == "LUMV0810"


def test_unseeded_run_has_no_baseline_to_scope_against(tmp_path: Path, monkeypatch):
    """A fresh (unseeded) run has no prior document state — baseline capture
    must be a no-op (empty set, no extra preflight call at all) and every
    diagnostic on iteration 1 is, by definition, introduced."""
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeBaselineErrorPreflightCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a square ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])

    loop = LumenQualityLoop(tools, author, reviewer)
    result = loop.run("Create a square ad")

    # Baseline capture is a no-op for an unseeded run: no extra preflight call
    # was ever made on its behalf, and every diagnostic that DOES surface
    # counts as introduced (nothing to compare against).
    assert loop.baseline_diagnostic_keys == set()
    assert result.get("baseline_advisory") is None


# --- Gap 3: freehand state in the initial brief -----------------------------------


def test_input_json_scene_summary_includes_freehand_block(tmp_path: Path, monkeypatch):
    """The FIRST-pass brief (`input.json`, written at LumenDesignTools
    construction, before any iteration runs) must carry the same freehand
    block (`free_containers` / `pinned_nodes` / note) that repair requests
    already see — reusing `_scene_summary()`, not a fork of it."""
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(
        runtime_config(tmp_path), "edit", initial_scene=freehand_seed_scene()
    )

    input_payload = json.loads((tools.trace_dir / "input.json").read_text(encoding="utf-8"))
    assert "scene_summary" in input_payload
    freehand = input_payload["scene_summary"]["freehand"]
    assert freehand["pinned_nodes"] == ["headline"]
    assert freehand["free_containers"] == ["band"]
    assert "human-owned" in freehand["note"]


def test_input_json_scene_summary_omits_freehand_when_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(
        runtime_config(tmp_path), "edit", initial_scene=seed_scene_dict()
    )

    input_payload = json.loads((tools.trace_dir / "input.json").read_text(encoding="utf-8"))
    assert "freehand" not in input_payload["scene_summary"]


# --- Gap 5: insert-into-frozen guidance --------------------------------------------


def test_seeded_recipe_tells_the_author_to_transform_new_inserts_into_free_containers():
    assert 'layout_mode: "free"' in SEEDED_CONTINUATION_RECIPE
    for phrase in ("INSERTING a NEW element", "p(x,y)", "s(w,h)", "origin"):
        assert phrase in SEEDED_CONTINUATION_RECIPE
