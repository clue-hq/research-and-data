"""Phase 0b — seeded continuation guarantees.

Two layers:

1. REAL-ENGINE fixtures (no fakes; the actual Rust helper): the untouched-nodes
   byte-identity guarantee from probe 1, and the atomic whole-block rejection of
   re-authored ids from probe 2, pinned as regressions.
2. Loop-level tests (FakeCoreClient): mode coercion, the unwipeable seed, the
   LUMD0401/LUMA0200 reroute, and edit-scoped acceptance.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace as dc_replace
from pathlib import Path

import pytest
from py_lumen_config import settings

from lumen_deepagent.config import AgentRuntimeConfig
from lumen_deepagent.loop import (
    LumenQualityLoop,
    issue_in_edit_scope,
    reauthor_correction,
)
from lumen_deepagent.prompts import SEEDED_CONTINUATION_RECIPE
from lumen_deepagent.schemas import (
    AgentActionMode,
    AgentDirectorDecision,
    VisualCritique,
    VisualIssue,
    VisualTarget,
)
from lumen_deepagent.tools import LumenDesignTools

from test_lumen_deepagent_runtime import (
    FakeCoreClient,
    ScriptedAuthor,
    ScriptedReviewer,
    runtime_config,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# --- shared helpers --------------------------------------------------------------


def node_fingerprints(scene: dict) -> dict:
    return {
        node_id: json.dumps(node, sort_keys=True)
        for node_id, node in (scene.get("nodes") or {}).items()
    }


def trace_events(config: AgentRuntimeConfig, run_id: str) -> list[str]:
    trace_path = config.trace_dir / run_id / "trace.jsonl"
    if not trace_path.exists():
        return []
    return [
        json.loads(line).get("event")
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def seed_scene_dict() -> dict:
    """A minimal live-document seed: a page with a hero image and a headline,
    plus a band container holding a kicker (for descendant-scope tests)."""
    return {
        "meta": {"id": "doc_live", "title": "Saved doc", "status": {"kind": "draft"}},
        "pages": {
            "hero_poster": {
                "id": "hero_poster",
                "children": ["hero", "band", "headline"],
            }
        },
        "nodes": {
            "hero": {
                "id": "hero",
                "kind": {"kind": "image", "asset_id": "hero_image"},
                "children": [],
            },
            "band": {
                "id": "band",
                "kind": {"kind": "frame"},
                "children": ["kicker"],
            },
            "kicker": {
                "id": "kicker",
                "kind": {"kind": "text", "content": "CASE STUDY"},
                "children": [],
            },
            "headline": {
                "id": "headline",
                "kind": {"kind": "text", "content": "Old copy"},
                "children": [],
            },
        },
        "slots": {},
        "assets": {},
    }


class ScriptedDirector:
    def __init__(self, decisions: list[AgentDirectorDecision]) -> None:
        self.decisions = decisions
        self.calls = []

    def decide(self, *, full_context):
        self.calls.append(full_context)
        index = min(len(self.calls) - 1, len(self.decisions) - 1)
        return self.decisions[index]


# --- 1) REAL-ENGINE regression fixtures (probe 1 / probe 2, pinned) ---------------


FIXTURE_DSL = """page fixture_page size(1080,1080,px)
  canvas al(v,g(24),pad(48),x(s)) p(0,0) s(1080,1080) fill(#FFFFFF)
    kicker text "CASE STUDY" s(936,48)
    headline text "Faster triage, calmer clinics" s(936,120)
    body text "How Insight Health cut wait times." s(936,80)
    cta rect s(300,60) fill(#0A2540)
"""


@pytest.fixture(scope="module")
def real_core():
    from lumen_api.core import CoreClient

    helper = REPO_ROOT / "target" / "debug" / "lumen-api-helper"
    if helper.exists():
        os.environ.setdefault("LUMEN_CORE_HELPER", str(helper))
        if settings.lumen_core_helper is None:
            settings.lumen_core_helper = str(helper)
    return CoreClient(repo_root=REPO_ROOT)


@pytest.fixture(scope="module")
def real_seed_scene(real_core):
    scene = real_core.new_scene("doc_seed_fixture", "Seeded fixture")
    response = real_core.compile_dsl_into_scene(scene, FIXTURE_DSL)
    output = response.get("dsl", {}).get("compile_output", {})
    assert not output.get("halted_at"), f"fixture DSL halted: {output.get('halted_at')}"
    return response["scene"]


@pytest.mark.parametrize(
    ("modify_line", "edited_node_id"),
    [
        ('#headline font("Inter",64,800,left)', "headline"),
        ("#cta fill(#FF5733)", "cta"),
    ],
    ids=["font-change", "recolor"],
)
def test_seeded_modify_leaves_untouched_nodes_byte_identical(
    tmp_path: Path, real_seed_scene: dict, modify_line: str, edited_node_id: str
):
    # THE Phase 0 regression assertion: after a targeted modify on a seeded
    # scene, every node the edit did not name is byte-identical.
    tools = LumenDesignTools(
        runtime_config(tmp_path), "targeted edit", initial_scene=real_seed_scene
    )
    before = node_fingerprints(tools.scene)

    payload = json.loads(tools.compile_dsl_block(modify_line))
    summary = payload.get("compile", {})

    assert summary.get("status") == "ok", summary
    assert summary.get("applied_operations") == 1
    after = node_fingerprints(tools.scene)
    assert before[edited_node_id] != after[edited_node_id]
    changed = sorted(
        node_id
        for node_id in before
        if node_id != edited_node_id and before[node_id] != after.get(node_id)
    )
    assert changed == [], f"untouched nodes changed: {changed}"
    assert sorted(before) == sorted(after)


def test_reauthoring_existing_id_rejects_the_whole_block_atomically(
    tmp_path: Path, real_seed_scene: dict
):
    # Probe 2 pinned: a block that re-declares an existing node id halts with
    # LUMD0401 and applies NOTHING — even valid lines before the halt. The
    # entire scene (including the target) stays byte-identical.
    tools = LumenDesignTools(
        runtime_config(tmp_path), "re-author attempt", initial_scene=real_seed_scene
    )
    before = json.dumps(tools.scene, sort_keys=True)

    payload = json.loads(
        tools.compile_dsl_block(
            '#kicker text("UPDATED")\nheadline text "Re-authored" s(100,50)\n'
        )
    )
    summary = payload.get("compile", {})

    assert summary.get("status") == "error"
    assert (summary.get("halted_at") or {}).get("code") == "LUMD0401"
    assert (summary.get("applied_operations") or 0) == 0
    assert json.dumps(tools.scene, sort_keys=True) == before


# --- 2) Loop-level guarantees (FakeCoreClient) ------------------------------------


def test_seeded_new_artifact_is_coerced_to_targeted_patch(tmp_path: Path, monkeypatch):
    # The heuristic director's first decision (no feedback) is new_artifact —
    # on a seeded run the loop must coerce it and inject the continuation recipe.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Edit the headline", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#headline text("Hi")'])
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])

    result = LumenQualityLoop(tools, author, reviewer).run("Edit the headline")

    assert result["status"] == "accepted"
    decision = author.requests[0].director_decision
    assert decision.action_mode == AgentActionMode.targeted_patch
    assert "SEEDED CONTINUATION MODE" in decision.instructions_to_author
    events = trace_events(config, tools.run_id)
    assert "seeded_mode_coerced" in events
    assert "fresh_rewrite_scene_started" not in events


def test_unseeded_run_is_not_coerced(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square ad")

    assert result["status"] == "accepted"
    decision = author.requests[0].director_decision
    assert decision.action_mode == AgentActionMode.new_artifact
    assert SEEDED_CONTINUATION_RECIPE not in (decision.instructions_to_author or "")
    assert "seeded_mode_coerced" not in trace_events(config, tools.run_id)


def test_seeded_full_page_rewrite_is_coerced_and_never_wipes(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Rebuild the page", initial_scene=seed_scene_dict())
    director = ScriptedDirector(
        [
            AgentDirectorDecision(
                action_mode=AgentActionMode.full_page_rewrite,
                rationale="rebuild",
                instructions_to_author="Rebuild the page.",
            ),
            AgentDirectorDecision(
                action_mode=AgentActionMode.accept, rationale="fine"
            ),
        ]
    )
    author = ScriptedAuthor(['#headline text("Hi")'])
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])

    result = LumenQualityLoop(tools, author, reviewer, director).run("Rebuild the page")

    assert result["status"] == "accepted"
    decision = author.requests[0].director_decision
    assert decision.action_mode == AgentActionMode.targeted_patch
    events = trace_events(config, tools.run_id)
    assert "seeded_mode_coerced" in events
    assert "fresh_rewrite_scene_started" not in events
    assert "director_fresh_rewrite" not in tools.scene_update_sources


def test_start_fresh_rewrite_scene_is_refused_on_a_seeded_scene(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Edit", initial_scene=seed_scene_dict())
    before = json.dumps(tools.scene, sort_keys=True)

    tools.start_fresh_rewrite_scene("director asked for a rewrite")

    assert json.dumps(tools.scene, sort_keys=True) == before
    assert "director_fresh_rewrite" not in tools.scene_update_sources
    assert "seeded_scene_wipe_blocked" in trace_events(config, tools.run_id)


class FakeReauthorHaltOnceCoreClient(FakeCoreClient):
    """First compile halts with LUMD0401 (session-shaped diagnostic, exactly as
    the real path mangles it); later compiles succeed via the base fake."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_calls = 0

    def compile_dsl_into_scene(
        self, scene, source: str, dsl_session=None, protected_node_ids=None
    ):
        self.compile_calls += 1
        if self.compile_calls == 1:
            return {
                "scene": scene,
                "applied_operations": 0,
                "dsl": {
                    "compile_output": {
                        "operations": [],
                        "diagnostics": [
                            {
                                "diagnostic": {
                                    "code": "LUMD0401",
                                    "message": "duplicate node id headline",
                                    "severity": "error",
                                },
                                "span": {"line": 2, "column": 1},
                            }
                        ],
                        "halted_at": {"code": "LUMD0401", "line": 2},
                    },
                    "operation_error": None,
                    "session_snapshot": None,
                },
            }
        return super().compile_dsl_into_scene(
            scene, source, dsl_session, protected_node_ids
        )


def test_reauthor_halt_is_rerouted_as_surgical_corrective_feedback(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeReauthorHaltOnceCoreClient
    )
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Edit the headline", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(
        ['headline text "Re-authored" s(100,50)', '#headline text("Fixed")']
    )
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])
    loop = LumenQualityLoop(tools, author, reviewer)

    result = loop.run("Edit the headline")

    assert result["status"] == "accepted"
    first_feedback = loop.previous_feedback[0]
    correction = first_feedback.get("reauthor_correction")
    assert correction is not None
    assert correction["code"] == "LUMD0401"
    assert correction["offending_id"] == "headline"
    assert first_feedback.get("surgical_repair") is True
    assert first_feedback.get("surgical_target") == {"node_id": "headline"}
    # The corrective instruction leads the authoring constraints.
    assert "re-declared the existing node id 'headline'" in (
        first_feedback.get("authoring_constraints") or [""]
    )[0]
    assert "reauthor_rerouted" in trace_events(config, tools.run_id)
    # The next authoring attempt received the correction as its repair context.
    assert (
        author.requests[1].repair_context.get("reauthor_correction", {}).get(
            "offending_id"
        )
        == "headline"
    )


def test_reauthor_correction_parses_halt_codes():
    assert reauthor_correction({"halted_at": {"code": "LUMD0205"}}) is None
    node = reauthor_correction(
        {
            "halted_at": {"code": "LUMD0401", "line": 2},
            "diagnostics": [
                {
                    "severity": "info",
                    "code": None,
                    "message": "{'diagnostic': {'code': 'LUMD0401', 'message': 'duplicate node id headline'}, 'span': {...}}",
                }
            ],
        }
    )
    assert node == {
        "code": "LUMD0401",
        "kind": "node",
        "offending_id": "headline",
        "instruction": node["instruction"],
    }
    assert "#headline" in node["instruction"]
    page = reauthor_correction(
        {
            "halted_at": {"code": "LUMA0200", "line": 1},
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "LUMA0200",
                    "message": "repair block tries to recreate existing page hero_poster",
                }
            ],
        }
    )
    assert page["kind"] == "page"
    assert page["offending_id"] == "hero_poster"
    # The corrective grammar must be UNAMBIGUOUS about the page-ref form — the
    # live run_8cbeae790f07 failure came from the model reading `#<id>` as
    # `#hero_poster` (node grammar) and burning every iteration on LUMD0901.
    assert "#page:hero_poster" in page["instruction"]
    assert "replace(" in page["instruction"]


def test_within_block_duplicate_gets_rename_correction_not_inplace_edit():
    # run_bdfe575c pinned: one block declared `artboard` on BOTH variant pages
    # of a fresh generation. The id exists nowhere in the scene, so the
    # existing-node correction ("edit it in place with `#artboard` modify
    # lines") would chase a phantom node into LUMD0901. The correction must
    # instead demand unique per-page ids and a full re-emit.
    summary = {
        "halted_at": {"code": "LUMD0401", "line": 14},
        "diagnostics": [
            {
                "severity": "info",
                "code": None,
                "message": "{'diagnostic': {'code': 'LUMD0401', 'message': 'duplicate node id artboard'}, 'span': {...}}",
            }
        ],
    }
    empty_scene = {"pages": {}, "nodes": {}}
    correction = reauthor_correction(summary, empty_scene)
    assert correction["kind"] == "duplicate_in_block"
    assert correction["offending_id"] == "artboard"
    assert "MORE THAN ONCE" in correction["instruction"]
    assert "artboard_a" in correction["instruction"]
    # With the id actually IN the scene, the existing-node correction stands.
    seeded = {"pages": {}, "nodes": {"artboard": {"id": "artboard"}}}
    assert reauthor_correction(summary, seeded)["kind"] == "node"
    # Legacy callers without a scene keep the existing-node behavior.
    assert reauthor_correction(summary)["kind"] == "node"


def test_within_block_duplicate_halt_is_not_pinned_surgical(
    tmp_path: Path, monkeypatch
):
    # Fresh (unseeded) generation halts LUMD0401 because the block collides
    # with ITSELF. The reroute must deliver the rename correction WITHOUT
    # surgical enforcement — pinning the next iteration to `#headline` modify
    # lines would target a node that does not exist (run_a0c54fab spent its
    # final iteration exactly that way).
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeReauthorHaltOnceCoreClient
    )
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create two variant pages")
    author = ScriptedAuthor(
        [
            # First block: the same generic id on both pages (the live failure).
            "page variant_a size(1080,1350,px)\n"
            '  headline text "A" s(400,80)\n'
            "page variant_b size(1080,1350,px)\n"
            '  headline text "B" s(400,80)',
            # Corrected re-emit: per-page suffixed ids.
            "page variant_a size(1080,1350,px)\n"
            '  headline_a text "A" s(400,80)\n'
            "page variant_b size(1080,1350,px)\n"
            '  headline_b text "B" s(400,80)',
        ]
    )
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])
    loop = LumenQualityLoop(tools, author, reviewer)

    result = loop.run("Create two variant pages")

    assert result["status"] == "accepted"
    feedback = loop.previous_feedback[0]
    correction = feedback.get("reauthor_correction")
    assert correction is not None
    assert correction["kind"] == "duplicate_in_block"
    assert correction["offending_id"] == "headline"
    assert feedback.get("surgical_repair") is None
    assert feedback.get("surgical_target") is None
    assert "MORE THAN ONCE" in (feedback.get("authoring_constraints") or [""])[0]
    assert "reauthor_rerouted" in trace_events(config, tools.run_id)


def test_page_ref_grammar_trap_is_rerouted():
    # From the live failure: the author wrote `#page_a4 size(...)` (node-ref
    # grammar) for a PAGE, halting LUMD0901 with "target node page_a4 does not
    # exist". With the scene available the guardrail must produce the exact
    # `#page:page_a4` correction instead of leaving the model guessing.
    summary = {
        "halted_at": {"code": "LUMD0901", "line": 1},
        "diagnostics": [
            {
                "severity": "info",
                "code": None,
                "message": "{'diagnostic': {'code': 'LUMD0901', 'hint': 'Use a node id from the current scene.', 'message': 'target node page_a4 does not exist'}, 'span': {...}}",
            }
        ],
    }
    scene = {"pages": {"page_a4": {"id": "page_a4"}}, "nodes": {}}

    correction = reauthor_correction(summary, scene)
    assert correction is not None
    assert correction["kind"] == "page_ref"
    assert correction["offending_id"] == "page_a4"
    assert "#page:page_a4" in correction["instruction"]
    assert "replace(" in correction["instruction"]

    # replace() pointed at a page reroutes the same way.
    replace_summary = {
        "halted_at": {"code": "LUMD0901", "line": 3},
        "diagnostics": [
            {
                "severity": "info",
                "code": None,
                "message": "{'diagnostic': {'code': 'LUMD0901', 'message': 'replace target page_a4 does not exist or has no parent'}, 'span': {...}}",
            }
        ],
    }
    assert reauthor_correction(replace_summary, scene)["kind"] == "page_ref"

    # A genuinely missing NODE id (not a page) stays on the generic repair
    # path — no correction.
    missing_node = {
        "halted_at": {"code": "LUMD0901", "line": 1},
        "diagnostics": [
            {
                "severity": "info",
                "code": None,
                "message": "{'diagnostic': {'code': 'LUMD0901', 'message': 'target node no_such_node does not exist'}, 'span': {...}}",
            }
        ],
    }
    assert reauthor_correction(missing_node, scene) is None
    # And without a scene (legacy callers) LUMD0901 is never claimed.
    assert reauthor_correction(summary) is None


class FakeSeededEditCoreClient(FakeCoreClient):
    """Compile applies a targeted update to the SEEDED scene (id-carrying op),
    instead of replacing the scene with the base fake's canned page."""

    edited_node_id = "headline"

    def compile_dsl_into_scene(
        self, scene, source: str, dsl_session=None, protected_node_ids=None
    ):
        self.last_protected_node_ids = protected_node_ids
        updated = json.loads(json.dumps(scene))
        node = updated.get("nodes", {}).get(self.edited_node_id)
        if node is not None:
            node["kind"]["content"] = "Edited"
        return {
            "scene": updated,
            "applied_operations": 1,
            "dsl": {
                "compile_output": {
                    "operations": [
                        {"kind": "update_node", "node_id": self.edited_node_id}
                    ],
                    "diagnostics": [],
                },
                "operation_error": None,
                "session_snapshot": None,
            },
        }


def rejected_critique(
    node_id: str, message: str, severity: str = "error"
) -> VisualCritique:
    return VisualCritique(
        accepted=False,
        summary=message,
        issues=[
            VisualIssue(
                severity=severity,
                category="hierarchy",
                message=message,
                suggested_repair="adjust it",
                target=VisualTarget(page_id="hero_poster", node_id=node_id),
            )
        ],
    )


def test_edit_scoped_acceptance_when_critique_targets_untouched_content(
    tmp_path: Path, monkeypatch
):
    # The critique rejects — but its only issue targets `hero`, which this turn
    # never touched. The seeded turn accepts at edit scope on iteration 1.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeSeededEditCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Edit the headline", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#headline text("Edited")'])
    reviewer = ScriptedReviewer(
        [rejected_critique("hero", "hero image is a placeholder gradient")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Edit the headline")

    assert result["status"] == "edit_applied"
    assert result["stop_reason"] == "edit_scoped_acceptance"
    assert result["ops_valid_through_iteration"] == 1
    assert result["critique"]["issues"][0]["target"]["node_id"] == "hero"
    assert len(author.requests) == 1  # no iteration burned re-litigating scope
    assert "edit_scoped_acceptance" in trace_events(config, tools.run_id)
    # The edit itself is present in the returned draft scene.
    assert tools.scene["nodes"]["headline"]["kind"]["content"] == "Edited"


def test_warning_on_edited_node_is_advisory_not_blocking(tmp_path: Path, monkeypatch):
    # A WARNING-severity critique issue on the edited node ("could dominate
    # more") is advisory by severity — it must not force extra repair rounds.
    # Only error/blocker issues in scope block. (Observed live in the 0b e2e.)
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeSeededEditCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Edit the headline", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#headline text("Edited")'])
    reviewer = ScriptedReviewer(
        [rejected_critique("headline", "headline could dominate more", severity="warning")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Edit the headline")

    assert result["status"] == "edit_applied"
    assert result["stop_reason"] == "edit_scoped_acceptance"
    assert len(author.requests) == 1


def test_in_scope_critique_still_blocks_and_repairs(tmp_path: Path, monkeypatch):
    # The critique targets the EDITED node — the turn must keep repairing, and
    # at budget exhaustion the verified edit still reaches the editor.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeSeededEditCoreClient)
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Edit the headline", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#headline text("Edited")', '#headline font_size(64)'])
    reviewer = ScriptedReviewer(
        [rejected_critique("headline", "the edited headline overflows its band")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Edit the headline")

    assert len(author.requests) == 2  # it DID keep repairing
    assert result["status"] == "edit_applied"
    assert result["stop_reason"] == "max_iterations_reached"
    # Both iterations earned identical critiques, so keep-best retains the
    # EARLIER draft on the tie — and the ops window points at it, so the editor
    # never replays iteration-2 ops that are not part of the returned scene.
    assert result["ops_valid_through_iteration"] == 1
    assert "edit_scoped_acceptance" not in trace_events(config, tools.run_id)


# --- Slice 2.5: declared-target gating of edit-scoped acceptance ------------------
#
# Moda-probe P1r2/P5r2 (measured live): the user chipped the target node, the
# agent edited an UNRELATED node, the reviewer raised a 0.95-confidence blocker
# on the requested node — and edit-scoped acceptance downgraded it to advisory
# because the blocker's target was outside the (agent-chosen) edit scope. The
# turn finalized "edit_applied" and offered Accept for an edit that did not do
# what the user asked. These tests pin the two mechanism fixes.


def test_blocker_on_declared_but_unedited_target_blocks_shortcut(
    tmp_path: Path, monkeypatch
):
    # Two chips; the turn addresses one (headline) but the reviewer's blocker
    # names the OTHER declared target (hero, untouched). Declared targets are
    # always in scope — the shortcut must not fire.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeSeededEditCoreClient)
    config = dc_replace(
        runtime_config(tmp_path, max_iterations=2),
        turn_target_node_ids=["hero", "headline"],
    )
    tools = LumenDesignTools(config, "Edit both", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#headline text("Edited")', '#headline font_size(64)'])
    reviewer = ScriptedReviewer(
        [rejected_critique("hero", "the requested hero change was not made")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Edit both")

    assert len(author.requests) == 2  # it kept repairing instead of shortcutting
    assert result["stop_reason"] != "edit_scoped_acceptance"
    assert "edit_scoped_acceptance" not in trace_events(config, tools.run_id)


def test_shortcut_withheld_when_no_declared_target_was_touched(
    tmp_path: Path, monkeypatch
):
    # The chip names hero; the turn only edits headline; the critique's issue
    # targets pre-existing content (band) that is out of every scope. The old
    # behavior shortcuts ("no in-scope issues"); the guard now withholds the
    # shortcut because the request was never addressed, and records why.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeSeededEditCoreClient)
    config = dc_replace(
        runtime_config(tmp_path, max_iterations=2),
        turn_target_node_ids=["hero"],
    )
    tools = LumenDesignTools(config, "Change the hero", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#headline text("Edited")', '#headline font_size(64)'])
    reviewer = ScriptedReviewer(
        [rejected_critique("band", "band feels cramped", severity="error")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Change the hero")

    assert result["stop_reason"] != "edit_scoped_acceptance"
    events = trace_events(config, tools.run_id)
    assert "edit_scoped_acceptance" not in events
    assert "edit_scope_target_untouched" in events


def test_shortcut_still_fires_when_declared_target_was_edited(
    tmp_path: Path, monkeypatch
):
    # Regression: chip names headline, the turn edits headline, the critique's
    # only issue targets untouched pre-existing content — the shortcut must
    # keep working exactly as before the guard.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeSeededEditCoreClient)
    config = dc_replace(
        runtime_config(tmp_path),
        turn_target_node_ids=["headline"],
    )
    tools = LumenDesignTools(config, "Edit the headline", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#headline text("Edited")'])
    reviewer = ScriptedReviewer(
        [rejected_critique("hero", "hero image is a placeholder gradient")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Edit the headline")

    assert result["status"] == "edit_applied"
    assert result["stop_reason"] == "edit_scoped_acceptance"
    assert len(author.requests) == 1


def test_editing_a_descendant_addresses_the_chipped_container(
    tmp_path: Path, monkeypatch
):
    # Chip names the band CONTAINER; the turn edits its child kicker. That
    # addresses the request (descendant scope) — the shortcut fires.
    fake = type(
        "FakeKickerEditCoreClient", (FakeSeededEditCoreClient,), {"edited_node_id": "kicker"}
    )
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", fake)
    config = dc_replace(
        runtime_config(tmp_path),
        turn_target_node_ids=["band"],
    )
    tools = LumenDesignTools(config, "Edit the band", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(['#kicker text("Edited")'])
    reviewer = ScriptedReviewer(
        [rejected_critique("hero", "hero image is a placeholder gradient")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Edit the band")

    assert result["status"] == "edit_applied"
    assert result["stop_reason"] == "edit_scoped_acceptance"


def test_insert_into_chipped_container_counts_as_addressed(tmp_path: Path):
    # Unit-level: _track_edited_ids records insert destinations (ParentRef
    # {"kind":"node","id":...}) separately, and _declared_targets_addressed
    # accepts an insert INTO the chipped container.
    config = dc_replace(runtime_config(tmp_path), turn_target_node_ids=["band"])
    tools = LumenDesignTools(config, "Add a badge", initial_scene=seed_scene_dict())
    loop = LumenQualityLoop(tools, ScriptedAuthor([]), ScriptedReviewer([]))

    loop._track_edited_ids(
        [
            {
                "kind": "insert_node",
                "parent": {"kind": "node", "id": "band"},
                "index": 0,
                "node": {"id": "badge_new"},
            }
        ]
    )

    assert "band" in loop.insert_parent_node_ids
    assert "band" not in loop.edited_node_ids  # critique scope semantics unchanged
    assert loop._declared_targets_addressed() is True


# --- Slice 3 phase B: protected-id passthrough + reconcile gating ----------------


def test_seeded_turn_passes_seed_node_ids_as_protected(tmp_path: Path, monkeypatch):
    # The human contract: on a seeded turn every compile call carries the seed
    # scene's node ids as protected_node_ids so an omission cannot delete human
    # content. The set is frozen at init from the seed scene.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeSeededEditCoreClient)
    tools = LumenDesignTools(
        runtime_config(tmp_path), "Edit the headline", initial_scene=seed_scene_dict()
    )
    seed_ids = sorted(seed_scene_dict()["nodes"].keys())
    assert tools.protected_node_ids == seed_ids

    tools.compile_dsl_block('#headline text("Edited")')
    assert tools.core.last_protected_node_ids == seed_ids


def test_fresh_turn_passes_no_protected_ids(tmp_path: Path, monkeypatch):
    # An unseeded run has no human content to protect — pure declarative
    # reconcile semantics — so the compile call carries None.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Make a poster")
    assert tools.protected_node_ids is None

    tools.compile_dsl_block("page p size(1080,1080,px)")
    assert tools.core.last_protected_node_ids is None


class FakeReconcileChippedContainerCoreClient(FakeSeededEditCoreClient):
    """A reconcile of `band` that inserts a new child into it — the ops the
    engine diff would emit — so the loop's _track_edited_ids records `band` as an
    insert destination (declared-target addressed)."""

    def compile_dsl_into_scene(
        self, scene, source: str, dsl_session=None, protected_node_ids=None
    ):
        updated = json.loads(json.dumps(scene))
        updated["nodes"]["badge_new"] = {
            "id": "badge_new",
            "kind": {"kind": "text", "content": "NEW"},
            "children": [],
        }
        updated["nodes"]["band"]["children"].append("badge_new")
        return {
            "scene": updated,
            "applied_operations": 1,
            "dsl": {
                "compile_output": {
                    "operations": [
                        {
                            "kind": "insert_node",
                            "parent": {"kind": "node", "id": "band"},
                            "index": 1,
                            "node": {"id": "badge_new"},
                        }
                    ],
                    "diagnostics": [],
                },
                "operation_error": None,
                "session_snapshot": None,
            },
        }


def test_reconcile_of_chipped_container_finalizes_via_edit_scope(
    tmp_path: Path, monkeypatch
):
    # Chip names the band container; the turn reconciles it (inserting a child).
    # The reconcile ops touch band, so _declared_targets_addressed is satisfied
    # and a critique on untouched content accepts at edit scope.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeReconcileChippedContainerCoreClient
    )
    config = dc_replace(runtime_config(tmp_path), turn_target_node_ids=["band"])
    tools = LumenDesignTools(config, "Add a badge to the band", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(["reconcile(band)\n  badge_new text \"NEW\""])
    reviewer = ScriptedReviewer(
        [rejected_critique("hero", "hero image is a placeholder gradient")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Add a badge to the band")

    assert result["status"] == "edit_applied"
    assert result["stop_reason"] == "edit_scoped_acceptance"
    assert len(author.requests) == 1  # no round burned re-litigating scope


class FakeBandEditCoreClient(FakeSeededEditCoreClient):
    edited_node_id = "band"


def test_descendants_of_edited_nodes_are_in_scope(tmp_path: Path, monkeypatch):
    # The turn edited `band`; the critique targets `kicker` (band's child).
    # Descendants are in scope, so this blocks instead of edit-scope accepting.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeBandEditCoreClient)
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Tighten the band", initial_scene=seed_scene_dict())
    author = ScriptedAuthor(["#band pad(24)", "#band pad(32)"])
    reviewer = ScriptedReviewer(
        [rejected_critique("kicker", "kicker is clipped by the band's new padding")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Tighten the band")

    assert len(author.requests) == 2
    assert result["stop_reason"] == "max_iterations_reached"
    assert "edit_scoped_acceptance" not in trace_events(config, tools.run_id)


def test_issue_in_edit_scope_rules():
    scope = {"band", "kicker"}
    edited_pages = {"new_page"}
    in_scope = VisualIssue(
        category="hierarchy",
        message="m",
        suggested_repair="r",
        target=VisualTarget(node_id="kicker"),
    )
    out_node = VisualIssue(
        category="hierarchy",
        message="m",
        suggested_repair="r",
        target=VisualTarget(node_id="hero"),
    )
    page_only = VisualIssue(
        category="visual_balance",
        message="m",
        suggested_repair="r",
        target=VisualTarget(page_id="hero_poster"),
    )
    edited_page = VisualIssue(
        category="visual_balance",
        message="m",
        suggested_repair="r",
        target=VisualTarget(page_id="new_page"),
    )
    untargeted = VisualIssue(
        category="visual_balance", message="m", suggested_repair="r", target=None
    )
    assert issue_in_edit_scope(in_scope, scope, edited_pages) is True
    assert issue_in_edit_scope(out_node, scope, edited_pages) is False
    assert issue_in_edit_scope(page_only, scope, edited_pages) is False
    assert issue_in_edit_scope(edited_page, scope, edited_pages) is True
    assert issue_in_edit_scope(untargeted, scope, edited_pages) is False


# --- 4) Phase 1e: freehand visibility (agent sees "human pinned this") ------------


def freehand_seed_scene() -> dict:
    """The 0b seed plus freehand state: the headline is pinned (detached and
    nudged by a human), and the band is a Free container."""
    scene = seed_scene_dict()
    scene["nodes"]["headline"]["position_mode"] = "absolute"
    scene["nodes"]["headline"]["absolute_box"] = {
        "x": 80.0,
        "y": 150.0,
        "width": 120.0,
        "height": 40.0,
    }
    scene["nodes"]["headline"]["base_anchor"] = {
        "x": 30.0,
        "y": 140.0,
        "width": 120.0,
        "height": 40.0,
    }
    scene["nodes"]["band"]["kind"] = {
        "kind": "auto_layout",
        "direction": "column",
        "wrap": False,
    }
    scene["nodes"]["band"]["layout"] = {
        "gap": 10.0,
        "padding": [0.0, 0.0, 0.0, 0.0],
        "grow": 0.0,
        "layout_mode": "free",
    }
    return scene


def test_node_brief_exposes_freehand_fields_only_when_set(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(
        runtime_config(tmp_path), "edit", initial_scene=freehand_seed_scene()
    )

    pinned = tools._node_brief("headline")
    assert pinned["position_mode"] == "absolute"
    assert pinned["absolute_box"] == {
        "x": 80.0,
        "y": 150.0,
        "width": 120.0,
        "height": 40.0,
    }
    assert pinned["base_anchor"] == {
        "x": 30.0,
        "y": 140.0,
        "width": 120.0,
        "height": 40.0,
    }

    free_container = tools._node_brief("band")
    assert free_container["layout_mode"] == "free"

    # A managed node's brief gains NO freehand keys (pre-freehand briefs stay
    # byte-identical — the same skip-when-default discipline as the engine).
    managed = tools._node_brief("hero")
    for key in ("position_mode", "absolute_box", "base_anchor", "layout_mode"):
        assert key not in managed


def test_scene_summary_surfaces_freehand_state_for_the_director(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(
        runtime_config(tmp_path), "edit", initial_scene=freehand_seed_scene()
    )
    summary = json.loads(tools.summarize_scene())
    assert summary["freehand"]["pinned_nodes"] == ["headline"]
    assert summary["freehand"]["free_containers"] == ["band"]
    assert "human-owned" in summary["freehand"]["note"]

    # No freehand state → no freehand key (summary stays byte-identical for
    # pre-freehand scenes).
    plain = LumenDesignTools(
        runtime_config(tmp_path / "plain"), "edit", initial_scene=seed_scene_dict()
    )
    assert "freehand" not in json.loads(plain.summarize_scene())


def test_query_geometry_shows_the_pin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(
        runtime_config(tmp_path), "edit", initial_scene=freehand_seed_scene()
    )
    pinned = json.loads(tools.query_geometry("headline"))
    assert pinned["position_mode"] == "absolute"
    assert pinned["absolute_box"]["x"] == 80.0
    assert pinned["base_anchor"]["y"] == 140.0

    managed = json.loads(tools.query_geometry("hero"))
    assert "position_mode" not in managed
    assert "absolute_box" not in managed


def test_seeded_recipe_carries_the_freehand_rules():
    # The prompt note that closes deferred Phase-0 item 4: the author is told
    # pinned boxes are human-owned, base_anchor is the nudge signal, free
    # containers stay hand-placed, and freehand warnings are advisory.
    assert "FREEHAND / PINNED NODES" in SEEDED_CONTINUATION_RECIPE
    for phrase in (
        "position_mode",
        "absolute_box",
        "base_anchor",
        "layout_mode",
        "ADVISORY",
    ):
        assert phrase in SEEDED_CONTINUATION_RECIPE


def test_seeded_recipe_carries_the_taste_first_policy():
    # Taste-first edit policy (user-decided 2026-07-05, .context/agent-
    # improvement/2026-07-05-taste-first-edit-policy.md): slight collateral
    # adjustments freely (announced as `// collateral:` lines), big
    # rearrangements only with a `// heads-up:` opener, unannounced changes
    # forbidden, accommodation nudges remain the non-optional mechanical floor.
    for phrase in (
        "YOU OWN THE COMPOSITION",
        "// collateral:",
        "// heads-up:",
        "UNANNOUNCED change",
        "mechanical floor",
        "meaningful intent, not an obstacle",
        "BIG rearrangement",
    ):
        assert phrase in SEEDED_CONTINUATION_RECIPE, phrase
    # The old strict-scope wording must be gone.
    assert "Touch ONLY what the request requires" not in SEEDED_CONTINUATION_RECIPE
    assert "move or resize it ONLY" not in SEEDED_CONTINUATION_RECIPE
