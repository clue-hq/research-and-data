"""Fast loop v1 §5 — the core loop redesign, behind `LUMEN_AGENT_FAST_LOOP`.

Spec: `subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` §5.1, §5.2,
§5.3, §5.5, §5.6, §5.7. (§5.4 deterministic autofix and §6/§8 the format-skill
library are owned elsewhere.)

The first section is the contract everything else is allowed to lean on: with
the flag OFF, nothing changed. Every existing suite proves that too — this file
pins it directly, prompt by prompt and tool list by tool list, so a regression
shows up here as a one-line diff rather than as a mystery failure three suites
away.

deepagents is stubbed exactly as `test_deepagent_harness.py` stubs it, so no
model is ever built and no network call fires.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from lumen_agent import frame as frame_mod
from lumen_agent import harness as harness_mod
from lumen_agent.budget import (
    BUDGET_LLM_CALLS,
    BUDGET_WALL_CLOCK,
    REPAIR_ROUND_MIN_CALLS,
    REPAIR_ROUND_MIN_SECONDS,
    BudgetCallbackHandler,
    BudgetExhausted,
    RunBudget,
    attach_budget_callback,
)
from lumen_agent.harness import create_design_deepagent, run_deepagent_turn
from lumen_agent.prompts import (
    BATCHING_RULE,
    SHARED_SURFACE_CONTRACT,
    TOOL_ROUTING_RULE,
    _AUTHOR_HEADER,
    _AUTHOR_RESOURCE_MAP,
    _AUTHOR_TEACHING_BODY,
    _ORCHESTRATOR_TEMPLATE,
    build_author_prompt,
    build_orchestrator_prompt,
    build_reviewer_prompt,
)
from lumen_agent.tools import render as render_mod
from lumen_agent.tools.substrate import LumenDesignTools

from agent_fixtures import FakeCoreClient, prepare_acceptance_evidence, runtime_config
from test_deepagent_harness import _install_deepagents_stub, _tool_name


WS = "/run_test/workspace"


def fast_config(tmp_path, **overrides):
    """The fixture config with the fast loop ON (plus any budget overrides)."""
    return replace(runtime_config(tmp_path), fast_loop=True, **overrides)


def _subagents(capture: dict) -> dict:
    return {sa["name"]: sa for sa in capture["kwargs"]["subagents"]}


def _author_tool_names(capture: dict) -> set[str]:
    return {_tool_name(t) for t in _subagents(capture)["lumen-dsl-author"]["tools"]}


# ===========================================================================
# 0. FLAG OFF — byte-identical
# ===========================================================================


def test_flag_off_orchestrator_prompt_is_byte_identical() -> None:
    """The default call must still produce the pre-fast-loop template, exactly."""
    expected = _ORCHESTRATOR_TEMPLATE.format(
        shared_surface_contract=SHARED_SURFACE_CONTRACT,
        batching_rule=BATCHING_RULE,
        workspace=WS,
        references_block="",
    )
    assert build_orchestrator_prompt(WS) == expected


def test_flag_off_author_prompt_is_byte_identical() -> None:
    expected = "\n\n".join(
        [
            _AUTHOR_HEADER.format(workspace=WS),
            BATCHING_RULE,
            _AUTHOR_TEACHING_BODY,
            SHARED_SURFACE_CONTRACT,
            _AUTHOR_RESOURCE_MAP.format(workspace=WS),
        ]
    )
    assert build_author_prompt(WS) == expected


def test_flag_off_ignores_every_fast_loop_argument() -> None:
    """Passing the fast-loop knobs with the flag off must change nothing.

    The guard against a caller that threads the new parameters through
    unconditionally and silently half-enables the new loop.
    """
    assert build_orchestrator_prompt(
        WS,
        fast_loop=False,
        scene_reviewer=False,
        skills=[("linkedin-square-ad", "a square ad")],
        target_llm_calls=7,
        target_wall_clock_s=30.0,
        inner_iterations=1,
    ) == build_orchestrator_prompt(WS)
    assert build_author_prompt(
        WS, fast_loop=False, frame_payload="INLINE PAYLOAD", inner_iterations=1
    ) == build_author_prompt(WS)


def test_flag_off_harness_keeps_reviewer_and_a_render_free_author(tmp_path, monkeypatch) -> None:
    """The whole §5 delta is absent on a flag-off turn."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    _agent, tools = create_design_deepagent("Design something", runtime_config(tmp_path))

    assert set(_subagents(capture)) == {"lumen-dsl-author", "lumen-visual-reviewer"}
    assert "render_preview" not in _author_tool_names(capture)
    assert capture["kwargs"]["system_prompt"] == build_orchestrator_prompt(
        f"/{tools.run_id}/workspace"
    )
    # No budget object exists, so nothing can enforce one.
    assert getattr(tools, "fast_loop_budget", None) is None
    assert "budget" not in tools.metrics.snapshot()


def test_flag_off_metrics_snapshot_carries_no_fast_loop_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Make a poster")
    snapshot = tools.metrics.snapshot()
    for key in ("budget", "budget_exhausted", "inner_iteration_refusals"):
        assert key not in snapshot


# ===========================================================================
# §5.2 — author with eyes
# ===========================================================================


def test_flag_on_author_toolset_includes_render(tmp_path, monkeypatch) -> None:
    """The single most important line of the redesign: the author can look."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent("Design something", fast_config(tmp_path))

    assert _author_tool_names(capture) == {
        "view",
        "inspect",
        "compile_dsl_block",
        "asset",
        "validate_binding_set",
        "preflight_design",
        "render_preview",
        # v2 logo-ladder merge (32e067aad): the author can fetch a target
        # account's real logo mid-turn on both lanes.
        "fetch_logo",
    }
    # The orchestrator keeps its own render — it is still the verification step
    # AND the P0.4 checkpoint trigger.
    assert "render_preview" in {_tool_name(t) for t in capture["kwargs"]["tools"]}


def test_flag_on_author_prompt_makes_looking_mandatory() -> None:
    author = build_author_prompt(WS, fast_loop=True, inner_iterations=4)
    assert "LOOK AT YOUR OWN RENDER" in author
    assert "This step is MANDATORY before you" in author
    assert "report done" in author
    # The loop, in order. Step 4's heading gained "AS SOON AS PREFLIGHT IS CLEAN"
    # in the 2026-08-24 TTFP tuning; see
    # test_the_first_render_is_an_obligation_with_no_detour for what that buys.
    for step in ("COMPILE.", "PREFLIGHT.", "RENDER AS SOON AS", "SELF-AUDIT.", "FIX."):
        assert step in author
    positions = [
        author.index("2. COMPILE."),
        author.index("3. PREFLIGHT."),
        author.index("4. RENDER AS SOON AS PREFLIGHT IS CLEAN."),
        author.index("5. LOOK AT YOUR OWN RENDER."),
        author.index("6. SELF-AUDIT."),
        author.index("7. FIX."),
    ]
    assert positions == sorted(positions)
    # The cap is stated with its configured number, not hand-waved.
    assert "A round allows\n   4 inner iterations (compiles)" in author
    assert build_author_prompt(WS, fast_loop=True, inner_iterations=2).count(
        "2 inner iterations"
    ) == 1


# ---------------------------------------------------------------------------
# TTFP tuning (2026-08-24). Acceptance run #1 took 6m09s to its first preview
# against a 4m gate. The trace says where it went: the author spent three calls
# and 110s reading eight SKILL.md files (two of them twice) before its first
# compile, then — with a CLEAN preflight already in hand at 232s — spent another
# 137s on three inspects and a second compile before it finally rendered at 369s.
# Rendering off that first clean preflight alone would have landed at ~236s.
# ---------------------------------------------------------------------------


def test_the_first_compile_must_be_the_whole_design() -> None:
    """A warm-up compile costs a second compile plus the minutes around it.

    The author already holds the brief, the brand card, the resolved type ramp
    and the format skill before its first call, so a skeleton-then-fill pass buys
    nothing the payload did not already give it.
    """
    author = build_author_prompt(WS, fast_loop=True)
    assert "YOUR FIRST COMPILE MUST BE THE WHOLE DESIGN." in author
    assert "Not a skeleton, not a warm-up" in author
    # Founder style: the rule carries a worked example of the mistake.
    assert "compiling a bare frame with three empty text nodes" in author


def test_the_first_render_is_an_obligation_with_no_detour() -> None:
    """The 137s between the first clean preflight and the first render.

    Nothing the author did in that gap needed doing before a picture existed, so
    the prompt now forbids each thing it actually did — inspect, measure, polish,
    recompile — by name rather than merely asking for speed.
    """
    author = build_author_prompt(WS, fast_loop=True)
    assert "RENDER AS SOON AS PREFLIGHT IS CLEAN." in author
    assert "Go straight here from step 3." in author
    for forbidden in ("Do NOT inspect", "do NOT measure", "do NOT polish"):
        assert forbidden in author
    assert "compile a second time before your first render exists" in author


def test_the_author_gets_one_reading_response_and_no_re_reads() -> None:
    """Eight skill reads over three calls, two of them duplicates.

    The capability skills are named as background precisely because the run read
    all four of them (create-design, brand-and-tokens, effects, brand-imagery)
    before writing a single line of DSL.
    """
    author = build_author_prompt(WS, fast_loop=True)
    assert "You get ONE reading response before you compile." in author
    assert "Never read the same file twice." in author
    assert "are background, not a prerequisite" in author
    # The one skill it DOES need is still named as required reading.
    assert "the FORMAT SKILL named in your direction" in author


def test_the_orchestrator_is_told_to_delegate_before_it_reads_around() -> None:
    """The orchestrator burned 117s and 7 calls before delegating.

    Five of those calls were filesystem hunting — two globs, three ls, and one
    read of a knowledge path that did not exist. §5.1's no-search rule only ever
    bound the author; the orchestrator spends from the same ceiling.
    """
    orchestrator = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False)
    assert "GET TO THE AUTHOR FAST." in orchestrator
    assert "Do NOT ls, glob or grep the knowledge tree." in orchestrator
    assert "every minute you spend there is a minute the author does\nnot get" in orchestrator


def test_flag_on_author_prompt_advertises_render_in_its_resource_map() -> None:
    author = build_author_prompt(WS, fast_loop=True)
    assert "render_preview (render the current scene to a validated PNG" in author
    # And no longer claims it cannot render.
    assert "You do NOT have: rendering" not in author


def test_author_render_tool_does_not_checkpoint_but_the_orchestrators_does(
    tmp_path, monkeypatch
) -> None:
    """§5.2's deliberate decision: a checkpoint still means 'a round was accepted'.

    Both tools run the same render over the same substrate and both file their
    PNG into the round directory; only the orchestrator's fires the P0.4 commit.
    """
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(fast_config(tmp_path), "Make a LinkedIn ad")

    png = tmp_path / "preview.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(
        tools,
        "export_preview_bundle",
        # The full bundle shape: since task 4b the checkpoint predicate reads the
        # canonical/critic summaries, not the folded reviewer verdict.
        lambda **_: json.dumps(
            {
                "canonical": {
                    "status": "ok",
                    "artifacts": [{"format": "svg", "validation_errors": []}],
                    "validation_errors": [],
                },
                "critic": {
                    "status": "ok",
                    "artifacts": [
                        {
                            "format": "png",
                            "path": str(png),
                            "validation_errors": [],
                        }
                    ],
                    "validation_errors": [],
                },
                "reviewer": {
                    "status": "ok",
                    "validation_errors": [],
                    "artifacts": [{"format": "png", "path": str(png)}],
                },
            }
        ),
    )
    monkeypatch.setattr(render_mod, "_latest_preview_png", lambda _tools: png)

    calls: list[str] = []
    monkeypatch.setattr(tools, "checkpoint_scene", lambda reason: calls.append(reason))

    render_mod._render_preview_text(tools, checkpoint=False)
    assert calls == []

    render_mod._render_preview_text(tools, checkpoint=True)
    assert calls == ["render_preview"]


def test_author_render_still_files_its_png_into_the_round_directory(
    tmp_path, monkeypatch
) -> None:
    """Custody unchanged (§5.2): the author's renders land where renders land."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(fast_config(tmp_path), "Make a LinkedIn ad")
    round_dir = tools.trace_dir / "workspace" / "rounds" / "round_1"
    round_dir.mkdir(parents=True)

    png = tmp_path / "preview.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(
        tools,
        "export_preview_bundle",
        lambda **_: json.dumps(
            {"reviewer": {"status": "ok", "validation_errors": [], "artifacts": []}}
        ),
    )
    monkeypatch.setattr(render_mod, "_latest_preview_png", lambda _tools: png)

    render_mod._render_preview_text(tools, checkpoint=False)
    assert (round_dir / "preview.png").read_bytes() == b"\x89PNG\r\n\x1a\n"


# ===========================================================================
# §5.2 — the inner-iteration cap
# ===========================================================================


def _compile_source() -> str:
    return "page page_test size(1080,1080,px)"


def test_inner_iteration_cap_refuses_past_the_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(fast_config(tmp_path, fast_loop_inner_iterations=2), "Ad")
    (tools.trace_dir / "workspace" / "rounds" / "round_1").mkdir(parents=True)

    first = json.loads(tools.compile_dsl_block(_compile_source()))
    second = json.loads(tools.compile_dsl_block(_compile_source()))
    third = json.loads(tools.compile_dsl_block(_compile_source()))

    assert "compile" in first and "compile" in second
    assert third["error_code"] == "compile.inner_iteration_cap"
    assert third["inner_iteration_cap"] == 2
    # The refusal is actionable, not a bare "no".
    assert "render_preview()" in third["message"]
    assert "critique.json" in third["message"]
    # Nothing was rolled back and nothing was counted against the run.
    assert tools.iteration == 2
    assert tools.metrics.snapshot()["compile_iterations_total"] == 2
    assert tools.metrics.snapshot()["inner_iteration_refusals"] == 1


def test_inner_iteration_cap_resets_on_the_next_round(tmp_path, monkeypatch) -> None:
    """The orchestrator's one permitted repair round gets a full fresh budget."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(fast_config(tmp_path, fast_loop_inner_iterations=1), "Ad")
    rounds = tools.trace_dir / "workspace" / "rounds"
    (rounds / "round_1").mkdir(parents=True)

    assert "compile" in json.loads(tools.compile_dsl_block(_compile_source()))
    assert (
        json.loads(tools.compile_dsl_block(_compile_source())).get("error_code")
        == "compile.inner_iteration_cap"
    )

    (rounds / "round_2").mkdir()
    assert "compile" in json.loads(tools.compile_dsl_block(_compile_source()))


def test_no_cap_when_the_flag_is_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(
        replace(runtime_config(tmp_path), fast_loop_inner_iterations=1), "Ad"
    )
    (tools.trace_dir / "workspace" / "rounds" / "round_1").mkdir(parents=True)

    for _ in range(4):
        assert "compile" in json.loads(tools.compile_dsl_block(_compile_source()))
    assert tools.iteration == 4


# ===========================================================================
# §5.3 — reviewer quarantined (R3), kill-switch live
# ===========================================================================


def test_flag_on_scene_reviewer_is_not_dispatched(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent("Design something", fast_config(tmp_path))

    assert set(_subagents(capture)) == {"lumen-dsl-author"}


def test_kill_switch_puts_the_reviewer_back_without_leaving_the_fast_loop(
    tmp_path, monkeypatch
) -> None:
    """`LUMEN_AGENT_SCENE_REVIEWER=1` — §7's kill-switch check, and the rollback."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent(
        "Design something", fast_config(tmp_path, scene_reviewer=True)
    )

    subagents = _subagents(capture)
    assert set(subagents) == {"lumen-dsl-author", "lumen-visual-reviewer"}
    # Still the fast loop: the author kept its eyes.
    assert "render_preview" in _author_tool_names(capture)
    # And the reviewer came back INTACT — same prompt, same structured output.
    assert subagents["lumen-visual-reviewer"]["response_format"] is not None


def test_the_quarantined_reviewer_code_path_is_still_whole() -> None:
    """R3 is 'archived, not removed'. The builder must still produce its prompt."""
    reviewer = build_reviewer_prompt(WS)
    assert "You are the Lumen visual reviewer." in reviewer
    assert "critique.json" in reviewer


def test_reviewer_role_is_still_registered_with_metrics(tmp_path, monkeypatch) -> None:
    """'Zero reviewer calls' must be visible as a fact, not as a missing key."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    seen: list[str] = []
    monkeypatch.setattr(
        harness_mod,
        "_instrument",
        lambda cfg, tools, model_id, role, budget=None: (
            seen.append(role),
            tools.metrics.register_role(role),
            object(),
        )[-1],
    )

    _agent, tools = create_design_deepagent("Design something", fast_config(tmp_path))

    assert seen == ["orchestrator", "author", "reviewer"]
    assert tools.metrics.snapshot()["by_role"]["reviewer"]["calls"] == 0


def test_flag_on_orchestrator_judges_the_self_audit_instead_of_delegating_review() -> None:
    orch = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False)
    assert "Judge the SELF-AUDIT" in orch
    assert "There is no separate visual reviewer on a scene turn" in orch
    # The three outcomes survive verbatim in meaning.
    assert "ACCEPT when" in orch
    assert "ONE REPAIR ROUND, MAX" in orch
    assert "FINALIZE WITH GAPS" in orch
    # The delegation it can no longer perform is gone from the steps AND the map.
    assert 'task(subagent_type="lumen-visual-reviewer"' not in orch
    assert "lumen-dsl-author ONLY" in orch
    # rounds/index.md discipline is unchanged (§5.3).
    assert "Append one line to\n   rounds/index.md after every round" in orch
    # And the finalize step still follows.
    assert "8. Finish honestly with finalize_run:" in orch


def test_the_fast_loop_splices_survive_a_reference_turn() -> None:
    """The §5.3/§5.7 replacements are index splices into the shared template.

    A reference turn interpolates an extra block into that template, so this is
    the case where an anchor could plausibly move. Both must still land, and RC's
    own blocks must survive intact.
    """
    orch = build_orchestrator_prompt(
        WS, has_references=True, fast_loop=True, scene_reviewer=False
    )
    assert "REFERENCE IMAGES (this turn" in orch
    assert "Judge the SELF-AUDIT" in orch
    assert "CONDITIONAL CLARIFICATION" in orch
    assert "8. Finish honestly with finalize_run:" in orch

    author = build_author_prompt(WS, has_references=True, fast_loop=True)
    assert "REFERENCE IMAGES:" in author
    assert "LOOK AT YOUR OWN RENDER" in author


def test_kill_switch_orchestrator_keeps_the_original_review_steps() -> None:
    orch = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=True)
    assert 'task(subagent_type="lumen-visual-reviewer"' in orch
    assert "Judge the SELF-AUDIT" not in orch


def test_author_writes_the_critique_in_the_visual_critique_shape() -> None:
    author = build_author_prompt(WS, fast_loop=True)
    assert "critique.json" in author
    assert "VisualCritique shape" in author
    for field in ("accepted", "summary", "issues", "acceptance_notes", "confidence"):
        assert f'"{field}"' in author
    # The rubber-stamp failure mode is named explicitly.
    assert "rubber-stamps its own work" in author


# ===========================================================================
# §5.5 — tool routing
# ===========================================================================


def test_tool_routing_rule_rides_both_flag_on_prompts() -> None:
    author = build_author_prompt(WS, fast_loop=True)
    orch = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False)
    for prompt in (author, orch):
        assert prompt.count(TOOL_ROUTING_RULE) == 1
        assert "THREE OR MORE nodes" in prompt
        assert "LOCALIZED fixes ONLY" in prompt
        assert "VERBATIM" in prompt


def test_the_routing_rule_spells_out_the_verbatim_data_contract() -> None:
    """"Copy it VERBATIM" alone left room to "improve" a number on the way past.

    The reconcile path rewrites existing nodes, so a rebuild is exactly where
    invented or silently-corrected data enters a design. The rule therefore has to
    say what verbatim covers, give the agent a countable check, and close the two
    excuses (rounding a number, shortening a label to fit).
    """
    for prompt in (
        build_author_prompt(WS, fast_loop=True),
        build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False),
    ):
        assert "THE DATA CONTRACT" in prompt
        # The record, and the countable check over it.
        assert "the nodes already in the scene are the record" in prompt
        assert "Count the data items going in and count them coming out" in prompt
        # The two named excuses are closed.
        assert "Do not round 1,247 to 1,200" in prompt
        assert "change the LAYOUT, never the data" in prompt
        # Exactly two exceptions, and a number is not one of them.
        assert "exactly two exceptions" in prompt
        assert "never typos you may auto-fix" in prompt
        assert "let a human decide" in prompt


def test_the_verbatim_data_contract_is_absent_with_the_flag_off() -> None:
    """It rides the routing rule, so it must inherit the routing rule's flag gate."""

    for prompt in (build_author_prompt(WS), build_orchestrator_prompt(WS)):
        assert "THE DATA CONTRACT" not in prompt


def test_tool_routing_rule_is_absent_with_the_flag_off() -> None:
    assert TOOL_ROUTING_RULE not in build_author_prompt(WS)
    assert TOOL_ROUTING_RULE not in build_orchestrator_prompt(WS)


# ===========================================================================
# §5.1 — the composed frame payload
# ===========================================================================


BRAND_KIT = {
    "id": "brand_kit_test",
    "version": 3,
    "name": "Insight Test",
    "constraints": {"tone": ["clinical", "warm"]},
    "tokens": {
        "colors": {
            "surface.page": {"value": {"default": {"kind": "hex", "value": "#ffffff"}}},
            "palette.accent": {
                "value": {"default": {"kind": "oklch", "l": 0.8, "c": 0.2, "h": 165.0}}
            },
        },
        "typography": {
            "type.display": {
                "value": {
                    "default": {
                        "kind": "style",
                        "font_family": "Aeonik",
                        "font_size": 64,
                        "font_weight": 700,
                    }
                }
            },
            "type.body": {
                "value": {
                    "default": {
                        "kind": "style",
                        "font_family": "Inter",
                        "font_size": 22,
                        "font_weight": 400,
                    }
                }
            },
        },
    },
    "assets": {
        "logos": {
            "primary": {
                "usage": "primary",
                "allowed_backgrounds": ["light"],
                "variants": [
                    {"name": "dark", "color_mode": "dark", "asset_id": "asset_logo_dark"}
                ],
            }
        },
        "images": {
            "hero": {
                "asset_id": "asset_hero",
                "role": "hero",
                "title": "Clinician at a desk",
            }
        },
    },
}


def _kit_tools(tmp_path, monkeypatch, initial_scene=None):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = fast_config(
        tmp_path,
        brand_kit=BRAND_KIT,
        brand_kit_source="document",
        brand_kit_assets={"asset_logo_dark": {"record": {"kind": "logo"}}},
    )
    return LumenDesignTools(config, "A LinkedIn square ad", initial_scene=initial_scene)


def test_frame_payload_inlines_the_brand_card_type_ramp_scene_and_assets(
    tmp_path, monkeypatch
) -> None:
    tools = _kit_tools(tmp_path, monkeypatch)
    payload = frame_mod.build_frame_payload(tools)

    assert "## BRAND CARD" in payload
    assert "Insight Test" in payload
    assert "## TYPE RAMP — resolved for this canvas" in payload
    assert "type.display" in payload
    assert "## SCENE DIGEST" in payload
    assert "## ASSET INDEX" in payload
    assert "asset_logo_dark" in payload
    assert "asset_hero" in payload
    assert "## PINNED KNOWLEDGE" in payload
    # The anti-search instruction is the acceptance criterion, stated to the model.
    assert "do not `ls`, `glob` or `grep` for context" in payload


def test_frame_payload_inlines_the_pinned_knowledge_bodies(tmp_path, monkeypatch) -> None:
    """Pinned means the TEXT is here, not that a path is mentioned."""
    tools = _kit_tools(tmp_path, monkeypatch)
    payload = frame_mod.build_frame_payload(tools)

    for relative in frame_mod.DEFAULT_PINNED_KNOWLEDGE:
        source = (
            Path(frame_mod.__file__).resolve().parent.parent / "knowledge_docs" / relative
        )
        body = source.read_text(encoding="utf-8")
        assert f"/knowledge_docs/{relative}" in payload
        # A distinctive interior line, not just the heading.
        probe = next(
            line for line in body.splitlines()[4:] if len(line.strip()) > 40
        )
        assert probe.strip() in payload


def test_pinned_knowledge_can_be_overridden_and_a_bad_pin_is_skipped(tmp_path) -> None:
    config = fast_config(
        tmp_path,
        fast_loop_pinned_knowledge="knowledge/lumen-dsl/colors.md, knowledge/nope.md",
    )
    assert frame_mod.pinned_knowledge_paths(config) == (
        "knowledge/lumen-dsl/colors.md",
        "knowledge/nope.md",
    )
    pinned = frame_mod.build_pinned_knowledge(config)
    assert [path for path, _ in pinned] == ["/knowledge_docs/knowledge/lumen-dsl/colors.md"]


def test_type_ramp_resolves_against_a_declared_canvas(tmp_path, monkeypatch) -> None:
    """The pilot skill's own numbers: display ≥64 and body ≥22 on 1080."""
    tools = _kit_tools(tmp_path, monkeypatch)
    ramp = frame_mod.resolve_type_ramp(tools.brand_card, width=1080.0, height=1080.0)

    assert ramp["canvas"]["short_edge"] == 1080.0
    assert ramp["scale_vs_1080"] == 1.0
    rows = {row["role"]: row for row in ramp["roles"]}
    assert rows["type.display"]["floor"] == 64
    assert rows["type.body"]["floor"] == 22
    assert rows["type.display"]["resolved"] == 64
    assert rows["type.display"]["family"] == "Aeonik"


def test_type_ramp_scales_off_the_reference_canvas(tmp_path, monkeypatch) -> None:
    tools = _kit_tools(tmp_path, monkeypatch)
    ramp = frame_mod.resolve_type_ramp(tools.brand_card, width=2160.0, height=2160.0)
    rows = {row["role"]: row for row in ramp["roles"]}
    assert ramp["scale_vs_1080"] == 2.0
    assert rows["type.display"]["resolved"] == 128
    assert rows["type.display"]["floor"] == 128


def test_type_ramp_is_honest_when_no_page_exists_yet(tmp_path, monkeypatch) -> None:
    """A create turn starts with ZERO pages — the ramp must not invent a canvas."""
    tools = _kit_tools(tmp_path, monkeypatch)
    ramp = frame_mod.resolve_type_ramp(tools.brand_card, width=None, height=None)

    assert ramp["canvas"] is None
    assert "no page yet" in ramp["note"]
    rows = {row["role"]: row for row in ramp["roles"]}
    assert rows["type.display"]["floor_at_1080"] == 64
    assert "floor" not in rows["type.display"]


def test_scene_digest_degrades_past_the_node_cap(tmp_path, monkeypatch) -> None:
    nodes = {
        f"n{i}": {"id": f"n{i}", "kind": {"kind": "text"}, "children": []}
        for i in range(frame_mod.MAX_DIGEST_NODES + 1)
    }
    scene = {
        "meta": {"id": "doc", "title": "Big"},
        "pages": {"p1": {"id": "p1", "children": list(nodes)}},
        "nodes": nodes,
        "slots": {},
        "assets": {},
    }
    tools = _kit_tools(tmp_path, monkeypatch, initial_scene=scene)
    digest = frame_mod.build_scene_digest(tools)

    assert "node_trees" not in digest
    assert "exceeds the" in digest["note"]
    assert "inspect(view='page'" in digest["note"]


def test_scene_digest_carries_the_node_trees_for_a_normal_document(
    tmp_path, monkeypatch
) -> None:
    scene = {
        "meta": {"id": "doc", "title": "Live"},
        "pages": {"p1": {"id": "p1", "children": ["headline"]}},
        "nodes": {
            "headline": {
                "id": "headline",
                "kind": {"kind": "text", "content": "Hi"},
                "children": [],
            }
        },
        "slots": {},
        "assets": {},
    }
    tools = _kit_tools(tmp_path, monkeypatch, initial_scene=scene)
    digest = frame_mod.build_scene_digest(tools)

    assert digest["node_trees"]["p1"][0]["id"] == "headline"


def test_frame_payload_rides_the_author_system_prompt(tmp_path, monkeypatch) -> None:
    """Composed at assembly, delivered in the system prompt (cache-stable)."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent(
        "A LinkedIn square ad",
        fast_config(tmp_path, brand_kit=BRAND_KIT, brand_kit_source="document"),
    )

    author_prompt = _subagents(capture)["lumen-dsl-author"]["system_prompt"]
    assert "COMPOSED FRAME PAYLOAD" in author_prompt
    assert "Insight Test" in author_prompt
    assert "## TYPE RAMP" in author_prompt


def test_flag_off_author_prompt_carries_no_frame_payload(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent(
        "A LinkedIn square ad",
        replace(runtime_config(tmp_path), brand_kit=BRAND_KIT, brand_kit_source="document"),
    )

    assert "COMPOSED FRAME PAYLOAD" not in _subagents(capture)["lumen-dsl-author"]["system_prompt"]


def test_the_round_direction_is_required_inline_in_the_delegation() -> None:
    """§5.1's 'round direction' half — the part that cannot be composed at assembly."""
    author = build_author_prompt(WS, fast_loop=True)
    assert "arrives INLINE in the delegation that woke you" in author
    assert "Do NOT ls, glob or grep" in author


# ===========================================================================
# §5.6 — budgets and graceful finalize
# ===========================================================================


# ---------------------------------------------------------------------------
# Budget HEADROOM (2026-08-24 tuning). Acceptance run #1 opened round 2 with the
# wall clock already at ~9m56s of 10m, delegated, and died mid-repair — the
# design shipped with the defect the round existed to fix. Every number needed
# to refuse that delegation was already inside RunBudget; nothing showed it to
# the one role that could act on it.
# ---------------------------------------------------------------------------


def test_remaining_reports_both_ceilings_and_a_verdict(monkeypatch) -> None:
    clock = {"now": 500.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = RunBudget(max_llm_calls=45, wall_clock_s=600.0)
    for _ in range(20):
        budget.check_and_count()
    clock["now"] = 500.0 + 120.0

    state = budget.remaining()
    assert state["calls_used"] == 20
    assert state["calls_left"] == 25
    assert state["elapsed_s"] == pytest.approx(120.0)
    assert state["seconds_left"] == pytest.approx(480.0)
    assert state["room_for_another_round"] is True


def test_a_round_needs_room_on_BOTH_ceilings(monkeypatch) -> None:
    """Either floor alone is enough to refuse: a round starved of calls and a
    round starved of clock both stop in the same half-finished place."""
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    # Plenty of clock, not enough calls.
    starved_calls = RunBudget(max_llm_calls=45, wall_clock_s=600.0)
    for _ in range(45 - (REPAIR_ROUND_MIN_CALLS - 1)):
        starved_calls.check_and_count()
    assert starved_calls.remaining()["calls_left"] == REPAIR_ROUND_MIN_CALLS - 1
    assert starved_calls.remaining()["room_for_another_round"] is False

    # Plenty of calls, not enough clock — this is acceptance run #1's shape.
    clock["now"] = 0.0
    starved_clock = RunBudget(max_llm_calls=45, wall_clock_s=600.0)
    clock["now"] = 600.0 - (REPAIR_ROUND_MIN_SECONDS - 1.0)
    assert starved_clock.remaining()["calls_left"] == 45
    assert starved_clock.remaining()["room_for_another_round"] is False


def test_the_status_line_states_the_verdict_in_words(monkeypatch) -> None:
    """The consumer is a model at a decision point, so it is told what to do —
    `calls_left: 9` invites an argument that "there is NOT room" does not."""
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = RunBudget(max_llm_calls=45, wall_clock_s=600.0)

    clock["now"] = 120.0
    roomy = budget.status_line()
    assert roomy.startswith("BUDGET LEFT: ")
    assert "0 of 45 model calls used, 45 left" in roomy
    assert "2.0 of 10.0 minutes used, 8.0 left" in roomy
    assert "There is room for another authoring round." in roomy

    clock["now"] = 600.0 - 56.0  # where run #1 actually delegated round 2
    cramped = budget.status_line()
    assert "There is NOT room for another authoring round" in cramped
    assert "do not delegate" in cramped
    assert "record_gap" in cramped


def test_the_orchestrators_render_reports_headroom_and_the_authors_does_not(
    tmp_path, monkeypatch
) -> None:
    """Same split, same reason, as the checkpoint flag: only the orchestrator
    decides whether to open another round. Telling the author its run is nearly
    over would invite it to cut corners on work it was told to finish."""
    from lumen_agent.tools import render as render_module

    monkeypatch.setattr(
        render_module, "_latest_preview_png", lambda tools: None
    )

    class _Tools:
        config = None

        def export_preview_bundle(self, critic_format: str) -> str:
            return json.dumps({"reviewer": {"status": "ok", "artifacts": []}})

        def checkpoint_scene(self, _label: str) -> None:  # pragma: no cover
            raise AssertionError("no PNG, so no checkpoint")

    budget = RunBudget(max_llm_calls=45, wall_clock_s=600.0)
    tools = _Tools()

    orchestrator_text = render_module._render_preview_text(
        tools, checkpoint=True, budget=budget
    )
    author_text = render_module._render_preview_text(tools, checkpoint=False, budget=None)

    assert "BUDGET LEFT:" in orchestrator_text
    assert orchestrator_text.splitlines()[-1].startswith("BUDGET LEFT:")
    assert "BUDGET LEFT:" not in author_text


def test_a_budget_that_cannot_describe_itself_never_fails_a_render(
    tmp_path, monkeypatch
) -> None:
    """A render that succeeded must not be lost to a broken status line."""
    from lumen_agent.tools import render as render_module

    monkeypatch.setattr(render_module, "_latest_preview_png", lambda tools: None)

    class _Tools:
        config = None

        def export_preview_bundle(self, critic_format: str) -> str:
            return json.dumps({"reviewer": {"status": "ok", "artifacts": []}})

    class _BrokenBudget:
        def status_line(self):
            raise RuntimeError("clock exploded")

    text = render_module._render_preview_text(
        _Tools(), checkpoint=False, budget=_BrokenBudget()
    )
    assert "render_preview: status=ok" in text
    assert "BUDGET LEFT:" not in text


def test_flag_off_render_carries_no_budget_line(tmp_path, monkeypatch) -> None:
    """Off the flag the harness passes budget=None, so the summary is unchanged."""
    from lumen_agent.tools import render as render_module

    monkeypatch.setattr(render_module, "_latest_preview_png", lambda tools: None)

    class _Tools:
        config = None

        def export_preview_bundle(self, critic_format: str) -> str:
            return json.dumps({"reviewer": {"status": "ok", "artifacts": []}})

    assert "BUDGET" not in render_module._render_preview_text(_Tools(), checkpoint=True)


def test_the_orchestrator_prompt_forbids_a_round_it_cannot_finish() -> None:
    """Harness-computed, prompt-consumed: the model is pointed at the line the
    render emits rather than asked to do arithmetic against two ceilings."""
    orchestrator = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False)
    assert "DO NOT OPEN A ROUND YOU CANNOT FINISH." in orchestrator
    assert "BUDGET LEFT line" in orchestrator
    assert "When it says there is no room, do not delegate again." in orchestrator
    # And it says what to do instead, so the rule is not merely a prohibition.
    assert "record_gap every issue you are leaving" in orchestrator


def test_the_headroom_floors_sit_under_the_d1_targets(tmp_path) -> None:
    """The floors decide when to stop spending, and under D1 they are measured
    against the TARGET (what the agent steers by), not the backstop. A floor at
    or above its target would refuse every round on a fresh run, so the ordering
    is the thing worth pinning."""
    config = runtime_config(tmp_path)
    assert REPAIR_ROUND_MIN_CALLS < config.fast_loop_target_llm_calls
    assert REPAIR_ROUND_MIN_SECONDS < config.fast_loop_target_wall_clock_s
    fresh = RunBudget(
        target_llm_calls=config.fast_loop_target_llm_calls,
        target_wall_clock_s=config.fast_loop_target_wall_clock_s,
        max_llm_calls=config.fast_loop_max_llm_calls,
        wall_clock_s=config.fast_loop_wall_clock_s,
    )
    assert fresh.remaining()["room_for_another_round"] is True


def test_budget_admits_exactly_its_limit_then_refuses() -> None:
    budget = RunBudget(max_llm_calls=3, wall_clock_s=999.0)
    for _ in range(3):
        budget.check_and_count()
    assert budget.calls == 3

    with pytest.raises(BudgetExhausted) as excinfo:
        budget.check_and_count()
    assert excinfo.value.kind == BUDGET_LLM_CALLS
    assert excinfo.value.limit == 3


def test_a_breached_budget_is_sticky() -> None:
    """Once out of budget, every later call must refuse — including a retry."""
    budget = RunBudget(max_llm_calls=1, wall_clock_s=999.0)
    budget.check_and_count()
    with pytest.raises(BudgetExhausted):
        budget.check_and_count()
    with pytest.raises(BudgetExhausted):
        budget.check_and_count()
    assert budget.calls == 1
    assert budget.breach.kind == BUDGET_LLM_CALLS


def test_wall_clock_budget_refuses_the_next_call(monkeypatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = RunBudget(max_llm_calls=999, wall_clock_s=600.0)

    budget.check_and_count()
    clock["now"] += 601.0
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.check_and_count()
    assert excinfo.value.kind == BUDGET_WALL_CLOCK


def test_a_breach_lands_in_the_metrics_summary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(fast_config(tmp_path), "Ad")
    budget = RunBudget(max_llm_calls=1, wall_clock_s=999.0, metrics=tools.metrics)
    tools.metrics.attach_budget(budget)

    budget.check_and_count()
    with pytest.raises(BudgetExhausted):
        budget.check_and_count()

    snapshot = tools.metrics.snapshot()
    assert snapshot["budget"]["max_llm_calls"] == 1
    assert snapshot["budget"]["llm_calls_admitted"] == 1
    assert snapshot["budget_exhausted"]["kind"] == BUDGET_LLM_CALLS
    from lumen_agent.run_metrics import summarize_line

    assert "BUDGET BACKSTOP HIT (llm_calls)" in summarize_line(snapshot)


# ===========================================================================
# RULING D1 (founder, 2026-08-26) — budgets are GUIDANCE, not gates
#
# The proof obligation is one sentence: a run that goes past its target must
# NOT be stopped, and the backstop must still fire for a run that has genuinely
# run away. Everything below is that sentence, split by mechanism.
#
# The evidence the ruling rests on is the Apollo A/B
# (`.context/ref-ads-pilot-apollo-report.md`, 2026-08-26): at a 600s HARD wall
# the run was cut right after its first look and shipped reference_fidelity 1;
# at 900s the same brief reacted to its own critique and reached 2.
# ===========================================================================


def _d1_budget(clock, metrics=None) -> RunBudget:
    """A budget at the shipped D1 numbers, on a clock the test owns."""
    return RunBudget(
        target_llm_calls=45,
        target_wall_clock_s=900.0,
        max_llm_calls=90,
        wall_clock_s=1800.0,
        metrics=metrics,
    )


def test_passing_the_wall_clock_target_does_not_stop_the_run(monkeypatch) -> None:
    """THE ruling, on the axis the Apollo A/B measured.

    Under the old contract the call at 900.1s raised and the design shipped
    half-repaired. Here it is admitted, and so is every call for the next
    fifteen minutes.
    """
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = _d1_budget(clock)

    budget.check_and_count()
    clock["now"] = 900.1  # one tenth of a second past the target

    # Not a raise, not a refusal — the run simply carries on.
    for _ in range(20):
        budget.check_and_count()
    assert budget.calls == 21
    assert budget.breach is None

    # And it keeps carrying on well past the target, right up to the backstop.
    clock["now"] = 1799.9
    budget.check_and_count()
    assert budget.breach is None


def test_passing_the_call_target_does_not_stop_the_run(monkeypatch) -> None:
    """Same ruling, other axis: call 46 used to raise. Now it is admitted."""
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = _d1_budget(clock)

    for _ in range(60):  # 15 calls past the 45-call target
        budget.check_and_count()
    assert budget.calls == 60
    assert budget.breach is None


def test_the_backstop_still_fires_and_still_names_its_axis(monkeypatch) -> None:
    """Guidance is not permission. A hung run is still stopped, on either axis."""
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    wall = _d1_budget(clock)
    wall.check_and_count()
    clock["now"] = 1800.0
    with pytest.raises(BudgetExhausted) as excinfo:
        wall.check_and_count()
    assert excinfo.value.kind == BUDGET_WALL_CLOCK
    assert excinfo.value.limit == 1800.0
    # The message says WHICH number this was, so nobody reads it as the target.
    assert "BACKSTOP" in str(excinfo.value)

    clock["now"] = 0.0
    calls = _d1_budget(clock)
    for _ in range(90):
        calls.check_and_count()
    with pytest.raises(BudgetExhausted) as excinfo:
        calls.check_and_count()
    assert excinfo.value.kind == BUDGET_LLM_CALLS
    assert excinfo.value.limit == 90.0


def test_a_target_crossing_and_a_backstop_hit_are_DIFFERENT_metrics_facts(
    tmp_path, monkeypatch
) -> None:
    """D1 clause 4. Routine drift past 900s and a run that hung must never be
    read off the same field, or the drift signal is worthless."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    tools = LumenDesignTools(fast_config(tmp_path), "Ad")
    budget = _d1_budget(clock, metrics=tools.metrics)
    tools.metrics.attach_budget(budget)

    budget.check_and_count()
    clock["now"] = 1000.0
    budget.check_and_count()  # crosses the target; must NOT raise

    snapshot = tools.metrics.snapshot()
    exceeded = snapshot["budget_target_exceeded"]
    assert exceeded["kind"] == BUDGET_WALL_CLOCK
    assert exceeded["target"] == 900.0
    assert exceeded["observed"] == pytest.approx(1000.0)
    # The abnormal key is ABSENT — nothing was stopped.
    assert "budget_exhausted" not in snapshot
    # Even the shapes differ, so the two dicts cannot be confused by a consumer.
    assert "limit" not in exceeded

    # Both thresholds are reported, so the numbers behind the verdict are visible.
    assert snapshot["budget"]["target_wall_clock_s"] == 900.0
    assert snapshot["budget"]["wall_clock_s"] == 1800.0
    assert snapshot["budget"]["target_exceeded"]["kind"] == BUDGET_WALL_CLOCK
    assert snapshot["budget"]["exhausted"] is None

    from lumen_agent.run_metrics import summarize_line

    line = summarize_line(snapshot)
    assert "past target (wall_clock)" in line
    assert "BACKSTOP" not in line

    # Now run it into the backstop: BOTH facts stand, separately.
    clock["now"] = 1800.0
    with pytest.raises(BudgetExhausted):
        budget.check_and_count()
    after = tools.metrics.snapshot()
    assert after["budget_target_exceeded"]["kind"] == BUDGET_WALL_CLOCK
    assert after["budget_exhausted"]["kind"] == BUDGET_WALL_CLOCK
    assert after["budget_exhausted"]["limit"] == 1800.0
    assert "past target (wall_clock)" in summarize_line(after)
    assert "BUDGET BACKSTOP HIT (wall_clock)" in summarize_line(after)


def test_the_target_crossing_is_recorded_once_on_the_first_axis(monkeypatch) -> None:
    """Sticky, like the breach. The question is "did this run drift, and where
    first", not "how many calls did it make afterwards"."""
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = _d1_budget(clock)

    for _ in range(45):
        budget.check_and_count()
    assert budget.target_exceeded is None  # 45 calls is AT the target, not past

    budget.check_and_count()
    first = budget.target_exceeded
    assert first == {"kind": BUDGET_LLM_CALLS, "target": 45.0, "observed": 45.0}

    clock["now"] = 1000.0  # now the wall-clock target goes too
    budget.check_and_count()
    assert budget.target_exceeded == first  # unchanged: first crossing wins


def test_a_run_with_no_target_crossing_reports_no_such_key(
    tmp_path, monkeypatch
) -> None:
    """The key is additive: a well-behaved run's metrics are unchanged."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    tools = LumenDesignTools(fast_config(tmp_path), "Ad")
    budget = _d1_budget(clock, metrics=tools.metrics)
    tools.metrics.attach_budget(budget)

    for _ in range(10):
        budget.check_and_count()
    clock["now"] = 500.0

    snapshot = tools.metrics.snapshot()
    assert "budget_target_exceeded" not in snapshot
    assert "budget_exhausted" not in snapshot
    assert snapshot["budget"]["target_exceeded"] is None

    from lumen_agent.run_metrics import summarize_line

    assert "target" not in summarize_line(snapshot)


def test_the_status_line_measures_against_the_target_and_never_names_the_backstop(
    monkeypatch,
) -> None:
    """What the orchestrator reads at a round boundary is its GUIDANCE.

    Quoting the backstop here would both hide the target it was asked to hit and
    invite it to spend up to a circuit breaker.
    """
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = _d1_budget(clock)

    clock["now"] = 120.0
    roomy = budget.status_line()
    assert roomy.startswith("BUDGET LEFT: ")
    assert "0 of 45 model calls used, 45 left" in roomy
    assert "2.0 of 15.0 minutes used, 13.0 left" in roomy
    assert "There is room for another authoring round." in roomy
    for backstop in ("30.0 minutes", "90 model calls", "backstop"):
        assert backstop not in roomy


def test_the_status_line_tells_a_past_target_run_to_finalize(monkeypatch) -> None:
    """Past the target the honest verdict changes: nothing will cut you off, and
    that is exactly why you should stop yourself."""
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = _d1_budget(clock)

    clock["now"] = 1000.0
    line = budget.status_line()
    assert "PAST this turn's target" in line
    assert "nothing is going to cut you off here" in line
    assert "Do not open another authoring round." in line
    assert "record_gap what is still wrong" in line
    # Clamped, never negative — "-1.7 left" would read as a live allowance.
    assert "0.0 left" in line
    assert budget.remaining()["seconds_left"] == 0.0
    assert budget.remaining()["past_target"] is True


def test_a_run_past_its_target_keeps_working_then_the_backstop_finalizes_it(
    tmp_path, monkeypatch
) -> None:
    """The whole ruling, end to end through the REAL runner.

    A loop that would have died at 600s spends another twenty minutes designing,
    every one of those calls admitted; the backstop then stops it at 1800s and
    the graceful finalize keeps the work — `completed_with_warnings`, a gap in
    the ledger, metrics on disk. Not one line of that finalize path was weakened
    to make the target advisory.
    """
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    class _ClockDrivenAgent:
        """Stands in for the compiled graph: one model call per simulated minute."""

        def __init__(self, tools) -> None:
            self._tools = tools

        def invoke(self, *args, **kwargs):
            budget = self._tools.fast_loop_budget
            while True:
                budget.check_and_count()  # raises ONLY at the backstop
                clock["now"] += 60.0
                # A round's work lands as it goes — this is what must survive.
                self._tools.scene = {
                    **self._tools.scene,
                    "nodes": {"headline": {"id": "headline", "children": []}},
                }

    holder: dict = {}
    real = harness_mod.create_design_deepagent

    def fake_create(prompt, **kwargs):
        _agent, tools = real(prompt, **kwargs)
        holder["tools"] = tools
        return _ClockDrivenAgent(tools), tools

    monkeypatch.setattr(harness_mod, "create_design_deepagent", fake_create)

    payload, tools = run_deepagent_turn("Design something", fast_config(tmp_path))
    budget = tools.fast_loop_budget

    # It ran the full 30 simulated minutes — 15 of them PAST the 900s target.
    # Under the pre-D1 contract this run stopped at call 11 (600s) with half a
    # design; the extra calls are the repair round the ruling exists to buy.
    assert budget.calls == 30
    assert budget.target_exceeded["kind"] == BUDGET_WALL_CLOCK
    assert budget.target_exceeded["target"] == 900.0

    # The backstop stopped it, and the finalize was graceful — work kept, gap
    # recorded, metrics written, and no `accepted` fabricated.
    assert payload["status"] == "completed_with_warnings"
    assert payload["stop_reason"] == "budget_exhausted_wall_clock"
    assert tools.gaps
    assert tools.gaps[-1]["area"] == "agent_protocol"
    assert "budget" in tools.gaps[-1]["summary"]
    assert (tools.trace_dir / "metrics.json").exists()

    written = json.loads((tools.trace_dir / "metrics.json").read_text(encoding="utf-8"))
    assert written["budget_target_exceeded"]["kind"] == BUDGET_WALL_CLOCK
    assert written["budget_exhausted"]["kind"] == BUDGET_WALL_CLOCK


def test_a_budget_given_only_a_backstop_targets_it(monkeypatch) -> None:
    """Back-compat seam: single-number construction means what it always meant,
    so a caller that has not been taught about targets cannot silently acquire a
    target of zero (which would report every run as past guidance)."""
    clock = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])
    budget = RunBudget(max_llm_calls=45, wall_clock_s=600.0)
    assert budget.target_llm_calls == 45
    assert budget.target_wall_clock_s == 600.0
    assert budget.past_target() is False


def test_the_budget_callback_raises_rather_than_being_swallowed() -> None:
    """langchain logs and drops a handler exception unless `raise_error` is set."""
    budget = RunBudget(max_llm_calls=1, wall_clock_s=999.0)
    handler = BudgetCallbackHandler(budget, "author")
    assert handler.raise_error is True

    handler.on_chat_model_start({}, [[]])
    with pytest.raises(BudgetExhausted):
        handler.on_chat_model_start({}, [[]])
    # The text-completion entry point is gated too.
    with pytest.raises(BudgetExhausted):
        handler.on_llm_start({}, ["prompt"])
    # An unknown hook is inert, never an AttributeError mid-run.
    handler.on_llm_new_token("tok")


def test_attach_budget_callback_leaves_a_sentinel_model_alone() -> None:
    sentinel = object()
    budget = RunBudget(max_llm_calls=1, wall_clock_s=1.0)
    assert attach_budget_callback(sentinel, budget, "a") is sentinel


def test_flag_on_harness_builds_and_shares_one_budget(tmp_path, monkeypatch) -> None:
    """One ceiling for the RUN — the orchestrator cannot buy calls by delegating."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    seen: list = []
    real_instrument = harness_mod._instrument

    def spy(cfg, tools, model_id, role, budget=None):
        seen.append(budget)
        return real_instrument(cfg, tools, model_id, role, budget)

    monkeypatch.setattr(harness_mod, "_instrument", spy)

    _agent, tools = create_design_deepagent(
        "Design something", fast_config(tmp_path, fast_loop_max_llm_calls=11)
    )

    assert len(seen) == 3
    assert all(b is tools.fast_loop_budget for b in seen)
    assert tools.fast_loop_budget.max_llm_calls == 11


class _BudgetBlowingAgent:
    """Stands in for the compiled graph: the run dies at the ceiling."""

    def __init__(self, breach: BudgetExhausted, tools: LumenDesignTools | None = None) -> None:
        self._breach = breach
        self._tools = tools

    def invoke(self, *args, **kwargs):
        if self._tools is not None:
            # A round's work landed before the ceiling was hit — this is what the
            # graceful finalize must not throw away.
            self._tools.scene = {
                **self._tools.scene,
                "nodes": {"headline": {"id": "headline", "children": []}},
            }
        raise self._breach


def _install_budget_agent(monkeypatch, breach, with_content: bool):
    holder: dict = {}
    real = harness_mod.create_design_deepagent

    def fake_create(prompt, **kwargs):
        _agent, tools = real(prompt, **kwargs)
        holder["tools"] = tools
        return _BudgetBlowingAgent(breach, tools if with_content else None), tools

    monkeypatch.setattr(harness_mod, "create_design_deepagent", fake_create)
    return holder


def test_budget_breach_finalizes_with_warnings_and_a_gap(tmp_path, monkeypatch) -> None:
    """§5.6: stop cleanly, keep the work, say what happened. Never a silent grind."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    breach = BudgetExhausted(BUDGET_LLM_CALLS, 45.0, 45.0)
    _install_budget_agent(monkeypatch, breach, with_content=True)

    payload, tools = run_deepagent_turn("Design something", fast_config(tmp_path))

    assert payload["status"] == "completed_with_warnings"
    assert payload["stop_reason"] == "budget_exhausted_llm_calls"
    assert "unverified" in payload["summary"]
    # The honest incompleteness is in the ledger, not only in a log line.
    assert tools.gaps
    assert "budget" in tools.gaps[-1]["summary"]
    assert tools.gaps[-1]["area"] == "agent_protocol"
    assert "45" in tools.gaps[-1]["evidence"]
    # And the run STILL emitted its §7 metrics.
    assert (tools.trace_dir / "metrics.json").exists()


def test_budget_breach_before_any_authoring_fails_honestly(tmp_path, monkeypatch) -> None:
    """No draft means no draft — `completed_with_warnings` would be a fabrication."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    breach = BudgetExhausted(BUDGET_WALL_CLOCK, 600.0, 612.0)
    _install_budget_agent(monkeypatch, breach, with_content=False)

    payload, _tools = run_deepagent_turn("Design something", fast_config(tmp_path))

    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "budget_exhausted_wall_clock"
    assert "no draft to keep" in payload["summary"]


def test_a_budget_breach_after_the_agent_finalized_keeps_the_real_final(
    tmp_path, monkeypatch
) -> None:
    """A run that already wrote final.json owns its own verdict."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    breach = BudgetExhausted(BUDGET_LLM_CALLS, 45.0, 45.0)
    holder = _install_budget_agent(monkeypatch, breach, with_content=True)

    def invoke_after_finalize(self, *args, **kwargs):
        prepare_acceptance_evidence(holder["tools"])
        result = holder["tools"].finalize_run("accepted", "reviewer_accepted", "shipped")
        assert json.loads(result)["status"] == "accepted"
        # This case is a late budget signal with unchanged accepted evidence.
        # The general helper above also authors a new scene before raising.
        raise breach

    monkeypatch.setattr(_BudgetBlowingAgent, "invoke", invoke_after_finalize)

    payload, _tools = run_deepagent_turn("Design something", fast_config(tmp_path))
    assert payload["status"] == "accepted"


def test_flag_on_orchestrator_prompt_states_its_targets_not_a_ceiling() -> None:
    """D1: the prompt communicates TARGETS in plain language and promises no cut.

    The two halves are equally load-bearing. Stating the numbers without the
    "nothing stops you" sentence would leave the agent reading them as the hard
    ceiling they used to be, which is the behaviour the ruling exists to end.
    """
    orch = build_orchestrator_prompt(
        WS,
        fast_loop=True,
        scene_reviewer=False,
        target_llm_calls=45,
        target_wall_clock_s=900.0,
    )
    assert "Aim to finish this turn inside 15 minutes of wall clock." in orch
    assert "Aim to finish it inside 45 model calls across ALL roles." in orch
    assert "targets you steer by, not walls" in orch
    assert "Nothing stops you the moment you pass a target." in orch
    # And the OLD hard-ceiling language is gone, not merely contradicted.
    assert "hard ceiling" not in orch
    assert "enforced by the harness, not by your goodwill" not in orch


def test_the_orchestrator_prompt_never_names_the_backstop() -> None:
    """D1: the agent's prompt talks about the TARGET only.

    Naming the circuit breaker would teach the agent that the target is
    negotiable and that it has 1800s to spend — the exact opposite of guidance
    it is trusted to steer by. Proven against the real shipped defaults, since a
    prompt built from custom numbers could pass this vacuously.
    """
    orch = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False)
    for backstop_number in ("1800", "90 model calls", "30 minutes"):
        assert backstop_number not in orch
    for backstop_word in ("backstop", "circuit breaker", "BACKSTOP"):
        assert backstop_word not in orch


# ===========================================================================
# §5.7 — conditional clarification (R2)
# ===========================================================================


def test_flag_on_gate_names_the_required_decisions_and_the_skill_interface() -> None:
    orch = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False)
    assert "CONDITIONAL CLARIFICATION" in orch
    # The built-in fallback list — the four the spec names.
    for decision in ("AUDIENCE", "OFFER/CTA", "TONE", "BRAND ADHERENCE"):
        assert decision in orch
    # The skill interface, referenced by its exact section name so a §6.1 skill
    # plugs in with no code change.
    assert "`## Defaults & required decisions` section IS the list" in orch
    # The old, vaguer paragraph is gone.
    assert "CLARIFYING A VAGUE BRIEF" not in orch


def test_flag_on_gate_teaches_both_branches() -> None:
    orch = build_orchestrator_prompt(WS, fast_loop=True, scene_reviewer=False)
    # Ask branch.
    assert "MATERIAL GAPS EXIST" in orch
    assert "2 to 4 questions via request_clarification" in orch
    # Defaults branch.
    assert "OTHERWISE → do not ask" in orch
    assert "record_gap ONE assumption per applied default" in orch
    # And the tool-absent case still resolves to the defaults branch.
    assert "If request_clarification is absent from your tools" in orch


def test_flag_on_clarification_tool_presence_is_unchanged(tmp_path, monkeypatch) -> None:
    """§5.7 uses the EXISTING machinery: the same two structural suppressors."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent("Design something", fast_config(tmp_path))
    assert "request_clarification" in {_tool_name(t) for t in capture["kwargs"]["tools"]}

    create_design_deepagent("Design something", fast_config(tmp_path, auto_defaults=True))
    assert "request_clarification" not in {_tool_name(t) for t in capture["kwargs"]["tools"]}

    create_design_deepagent(
        "Design something", fast_config(tmp_path), clarification_already_requested=True
    )
    assert "request_clarification" not in {_tool_name(t) for t in capture["kwargs"]["tools"]}


def test_flag_on_orchestrator_carries_the_composed_skill_index(tmp_path, monkeypatch) -> None:
    """The orchestrator selects a format skill without an `ls` (§5.1's move)."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent("Design something", fast_config(tmp_path))
    prompt = capture["kwargs"]["system_prompt"]

    assert "SKILL INDEX" in prompt
    assert "- clarify-design-brief:" in prompt
    assert "- create-design:" in prompt
    # Descriptions are real, not placeholders.
    assert "(no description)" not in prompt


def test_skill_index_reads_wrapped_frontmatter_descriptions(tmp_path) -> None:
    config = fast_config(tmp_path)
    skill = Path(config.workspace_root) / ".deepagent" / "skills" / "widget-ad"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: widget-ad\ndescription: Author a widget ad end-to-end —\n"
        "  concept plan, layout, type.\n---\n\n# Widget\n",
        encoding="utf-8",
    )
    assert harness_mod._materialized_skill_index(config) == [
        ("widget-ad", "Author a widget ad end-to-end — concept plan, layout, type.")
    ]


def test_skill_index_survives_a_broken_skill_file(tmp_path) -> None:
    config = fast_config(tmp_path)
    root = Path(config.workspace_root) / ".deepagent" / "skills"
    (root / "broken").mkdir(parents=True)
    (root / "broken" / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    (root / "empty").mkdir()

    assert harness_mod._materialized_skill_index(config) == [
        ("broken", "(no description)")
    ]


def test_skill_index_is_empty_without_a_materialized_tree(tmp_path) -> None:
    assert harness_mod._materialized_skill_index(fast_config(tmp_path)) == []


# ===========================================================================
# config surface
# ===========================================================================


def test_scene_reviewer_enabled_expresses_r3(tmp_path) -> None:
    base = runtime_config(tmp_path)
    assert base.scene_reviewer_enabled is True
    assert replace(base, fast_loop=True).scene_reviewer_enabled is False
    assert replace(base, fast_loop=True, scene_reviewer=True).scene_reviewer_enabled is True
    # The kill-switch is meaningless off the fast loop; the reviewer runs either way.
    assert replace(base, scene_reviewer=True).scene_reviewer_enabled is True


def test_budget_defaults_are_the_d1_numbers(tmp_path) -> None:
    """R4's single ceiling became D1's target + distant backstop (2026-08-26)."""
    config = runtime_config(tmp_path)
    # The guidance the agent is told about.
    assert config.fast_loop_target_llm_calls == 45
    assert config.fast_loop_target_wall_clock_s == 900.0
    # The circuit breaker, at ~2x, that the agent is never told about.
    assert config.fast_loop_max_llm_calls == 90
    assert config.fast_loop_wall_clock_s == 1800.0
    assert config.fast_loop_inner_iterations == 4
    assert config.fast_loop is False


def test_the_backstop_sits_at_roughly_twice_the_target(tmp_path) -> None:
    """The ratio IS the ruling: close enough and it is a second gate, far enough
    and a genuinely hung run burns money for an hour."""
    config = runtime_config(tmp_path)
    assert config.fast_loop_max_llm_calls == 2 * config.fast_loop_target_llm_calls
    assert config.fast_loop_wall_clock_s == 2 * config.fast_loop_target_wall_clock_s


# --- the env seam itself (D1 clause 1 + 3: SHIPPED defaults) ----------------


def _isolated_settings(monkeypatch, **kwargs):
    """`Settings` with no ambient env, because the repo `.env` legitimately sets
    several of these and dotenv may already have exported them into this
    process — the same isolation `test_settings_validate_reasoning_effort` uses."""
    from py_lumen_config.config import Settings

    for name in (
        "LUMEN_AGENT_REASONING",
        "LUMEN_AGENT_FAST_LOOP_TARGET_LLM_CALLS",
        "LUMEN_AGENT_FAST_LOOP_TARGET_WALL_CLOCK_S",
        "LUMEN_AGENT_FAST_LOOP_MAX_LLM_CALLS",
        "LUMEN_AGENT_FAST_LOOP_WALL_CLOCK_S",
    ):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None, **kwargs)


def test_settings_ship_the_d1_budget_defaults(monkeypatch) -> None:
    settings = _isolated_settings(monkeypatch)
    assert settings.lumen_agent_fast_loop_target_llm_calls == 45
    assert settings.lumen_agent_fast_loop_target_wall_clock_s == 900.0
    assert settings.lumen_agent_fast_loop_max_llm_calls == 90
    assert settings.lumen_agent_fast_loop_wall_clock_s == 1800.0


def test_settings_ship_medium_reasoning(monkeypatch) -> None:
    """D1 clause 1. The code default was already medium; `.env.example` was the
    last place still handing a fresh deployment a blank (i.e. no reasoning field
    at all), which is the configuration the Apollo A/B measured as slow."""
    assert _isolated_settings(monkeypatch).lumen_agent_reasoning == "medium"

    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    lines = env_example.read_text(encoding="utf-8").splitlines()
    assert "LUMEN_AGENT_REASONING=medium" in lines


def test_every_d1_budget_knob_still_honors_its_env_override(monkeypatch) -> None:
    """Guidance is still configurable — the ruling changed the numbers, not the
    seam. Overridden together, since the backstop must stay above its target."""
    settings = _isolated_settings(
        monkeypatch,
        lumen_agent_reasoning="high",
        lumen_agent_fast_loop_target_llm_calls=20,
        lumen_agent_fast_loop_target_wall_clock_s=300.0,
        lumen_agent_fast_loop_max_llm_calls=40,
        lumen_agent_fast_loop_wall_clock_s=600.0,
    )
    assert settings.lumen_agent_reasoning == "high"
    assert settings.lumen_agent_fast_loop_target_llm_calls == 20
    assert settings.lumen_agent_fast_loop_target_wall_clock_s == 300.0
    assert settings.lumen_agent_fast_loop_max_llm_calls == 40
    assert settings.lumen_agent_fast_loop_wall_clock_s == 600.0


def test_a_non_positive_target_fails_at_startup(monkeypatch) -> None:
    """Same rule the backstop always had: a budget that silently does nothing is
    worse than no budget at all."""
    with pytest.raises(Exception) as excinfo:
        _isolated_settings(monkeypatch, lumen_agent_fast_loop_target_wall_clock_s=0.0)
    assert "must be positive" in str(excinfo.value)
    with pytest.raises(Exception):
        _isolated_settings(monkeypatch, lumen_agent_fast_loop_target_llm_calls=-1)


def test_a_backstop_below_its_own_target_fails_at_startup(monkeypatch) -> None:
    """It would invert the ruling: the run would be hard-stopped before it ever
    crossed the guidance it was told to steer by, making the prompt's "nothing
    cuts you off" a lie the harness tells the agent."""
    with pytest.raises(Exception) as excinfo:
        _isolated_settings(
            monkeypatch,
            lumen_agent_fast_loop_target_wall_clock_s=900.0,
            lumen_agent_fast_loop_wall_clock_s=600.0,
        )
    assert "must be >=" in str(excinfo.value)

    with pytest.raises(Exception) as excinfo:
        _isolated_settings(
            monkeypatch,
            lumen_agent_fast_loop_target_llm_calls=45,
            lumen_agent_fast_loop_max_llm_calls=44,
        )
    assert "must be >=" in str(excinfo.value)

    # Equal is allowed — that is "no backstop headroom", a deliberate choice.
    equal = _isolated_settings(
        monkeypatch,
        lumen_agent_fast_loop_target_llm_calls=45,
        lumen_agent_fast_loop_max_llm_calls=45,
    )
    assert equal.lumen_agent_fast_loop_max_llm_calls == 45
