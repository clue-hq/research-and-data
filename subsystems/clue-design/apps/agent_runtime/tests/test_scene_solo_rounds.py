"""A candidate repair budget belongs to executed work, not note-write scheduling."""

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from langchain_core.messages import AIMessage, ToolMessage
from lumen_agent import harness
from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.run_metrics import emit_run_metrics
from lumen_agent.tools.render import tools_current_round
from lumen_agent.workspace import initial_turn_state
from test_render_preview_reuse import _RenderCore
from test_scene_direction_review import review as candidate_review
from test_scene_skill_family import direction
from test_scene_solo_runtime import offline_models, solo_config


def prepared_round(tmp_path, monkeypatch, *, accepted=False, core_class=_RenderCore):
    built, _ = offline_models(monkeypatch)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", core_class)
    graph, tools = harness.create_design_deepagent("Make an ad", solo_config(tmp_path))
    workspace = tools.trace_dir / "workspace"
    (workspace / "rounds/round_1").mkdir(parents=True)
    planned = direction()
    planned["copy"][0]["text"] = "Plan"
    (workspace / "creative-direction.json").write_text(json.dumps(planned))
    validated = json.loads(tools.validate_creative_direction())
    assert validated["status"] == "ok"
    for source in ["page page_test size(1080,1080,px)", *["#headline s(400,hug)"] * 3]:
        assert json.loads(tools.compile_dsl_block(source))["compile"]["status"] == "ok"
    tools.preflight_design()
    assert "status=ok" in graph.nodes["tools"].bound.tools_by_name["render_preview"].invoke({})
    review = candidate_review(validated, page_id="page_test", node_id="headline", text="Plan")
    review.update(accepted=accepted, summary="The headline needs a spacing repair.")
    backend = AgentWorkspaceBackend(
        tools.trace_dir.parent, active_run_id=tools.run_id,
        critique_observer=tools.observe_written_critique,
    )
    key = f"/{tools.run_id}/workspace/rounds/round_1/critique.json"
    assert backend.write(key, json.dumps(review)).error is None
    assert tools._latest_visual_critique["accepted"] is accepted
    return built, graph, tools, backend, review


def test_batched_round_note_cannot_make_the_first_repair_compile_hit_the_old_cap(
    tmp_path, monkeypatch,
):
    """R37/product-Clue: ToolNode compiles before the note creates round_2."""
    built, graph, tools, _, _ = prepared_round(tmp_path, monkeypatch)
    writer_entered, cap_checked = threading.Event(), threading.Event()
    original_file_lock = AgentWorkspaceBackend._file_mutation_lock
    original_cap_check = tools._inner_iteration_refusal

    def delayed_note(backend, key):
        if key.endswith("/rounds/round_2/direction.md"):
            writer_entered.set()
            assert cap_checked.wait(5), "compile never reached its cap check"
        return original_file_lock(backend, key)

    def observed_cap_check():
        assert writer_entered.wait(5), "round note was not scheduled concurrently"
        try:
            return original_cap_check()
        finally:
            cap_checked.set()

    monkeypatch.setattr(AgentWorkspaceBackend, "_file_mutation_lock", delayed_note)
    monkeypatch.setattr(tools, "_inner_iteration_refusal", observed_cap_check)
    built[0][2].responses = [
        AIMessage(content="", tool_calls=[
            {"name": "write_file", "args": {
                "file_path": f"/{tools.run_id}/workspace/rounds/round_2/direction.md",
                "content": "Repair the headline spacing in one reconcile.\n",
            }, "id": "note"},
            {"name": "compile_dsl_block", "args": {
                "source": "#headline s(420,hug)",
            }, "id": "repair"},
        ]),
        AIMessage(content="Repair compiled."),
    ]
    result = graph.invoke(initial_turn_state(tools, "Make an ad"))
    outputs = {m.tool_call_id: m.content for m in result["messages"] if isinstance(m, ToolMessage)}
    repair = json.loads(outputs["repair"])
    assert repair.get("compile", {}).get("status") == "ok", repair
    assert (tools.trace_dir / "workspace/rounds/round_2/direction.md").is_file()
    assert tools.iteration == 5
    assert tools.metrics.snapshot().get("inner_iteration_refusals", 0) == 0


@pytest.mark.parametrize("note_first", [False, True])
def test_repair_gets_one_allowance_without_depending_on_round_notes(tmp_path, monkeypatch, note_first):
    _, _, tools, backend, review = prepared_round(tmp_path, monkeypatch)
    workspace = tools.trace_dir / "workspace"
    if note_first:
        assert backend.write(f"/{tools.run_id}/workspace/rounds/round_2/direction.md", "Repair.").error is None
    for _ in range(4):
        assert json.loads(tools.compile_dsl_block("#headline s(420,hug)"))["compile"]["status"] == "ok"
    assert tools_current_round(tools) == 2
    # Registering the round-2 rejection again, or writing future notes, cannot
    # purchase a third allowance. The previous round cannot register new review.
    key = f"/{tools.run_id}/workspace/rounds/round_2/critique.json"
    assert backend.write(key, json.dumps(review)).error is None
    assert backend.write(f"/{tools.run_id}/workspace/rounds/round_99/direction.md", "More.").error is None
    refusal = json.loads(tools.compile_dsl_block("#headline s(420,hug)"))
    assert refusal["error_code"] == "compile.inner_iteration_cap"
    assert refusal["round"] == 2
    assert tools.iteration == 8
    review["accepted"] = True
    tools.observe_written_critique(workspace / "rounds/round_1/critique.json", json.dumps(review))
    assert tools._latest_visual_critique["accepted"] is False


@pytest.mark.parametrize("replacement", ["accepted", "malformed"])
def test_note_directory_cannot_bypass_an_unarmed_or_invalidated_review(tmp_path, monkeypatch, replacement):
    _, _, tools, _, review = prepared_round(tmp_path, monkeypatch)
    if replacement == "accepted":
        review["accepted"] = True
        assert json.loads(tools.submit_visual_critique(json.dumps(review)))["status"] == "ok"
    else:
        assert json.loads(tools.submit_visual_critique("{}"))["status"] == "error"
    (tools.trace_dir / "workspace/rounds/round_2").mkdir()
    refusal = json.loads(tools.compile_dsl_block("#headline s(420,hug)"))
    assert refusal["error_code"] == "compile.inner_iteration_cap"
    assert refusal["round"] == 1


def test_unchanged_preview_and_rejected_finalize_do_not_execute_a_repair(tmp_path, monkeypatch):
    _, graph, tools, _, _ = prepared_round(tmp_path, monkeypatch)
    (tools.trace_dir / "workspace/rounds/round_2").mkdir()
    receipt = tools._review_receipt
    tools.preflight_design()
    rendered = graph.nodes["tools"].bound.tools_by_name["render_preview"].invoke({})
    assert "reused" in rendered
    assert "rounds/round_1/preview.png" in rendered
    assert tools._review_receipt == receipt
    final = json.loads(tools.finalize_run("completed_with_warnings", "visual_qa_failed", "Draft."))
    assert final["status"] == "completed_with_warnings"
    metrics = emit_run_metrics(tools, rounds_dir=tools.trace_dir / "workspace/rounds")
    assert metrics["rounds_total"] == 1


def test_checked_operation_repair_uses_the_same_round_and_requires_fresh_review(tmp_path, monkeypatch):
    _, graph, tools, backend, review = prepared_round(tmp_path, monkeypatch)
    tools.apply_operations(json.dumps([{"kind": "update_node", "node_id": "headline", "patch": {"name": "Repaired"}}]))
    assert tools_current_round(tools) == 2
    assert tools.draft_verification()["review"]["status"] == "stale"
    tools.preflight_design()
    rendered = graph.nodes["tools"].bound.tools_by_name["render_preview"].invoke({})
    assert "rounds/round_2/preview.png" in rendered
    review["accepted"] = True
    assert backend.write(f"/{tools.run_id}/workspace/rounds/round_2/critique.json", json.dumps(review)).error is None
    assert json.loads(tools.finalize_run("accepted", "review_complete", "Ready."))["status"] == "accepted"
    assert emit_run_metrics(tools, rounds_dir=tools.trace_dir / "workspace/rounds")["rounds_total"] == 2


def test_parallel_repair_compiles_consume_a_single_shared_allowance(tmp_path, monkeypatch):
    _, _, tools, _, _ = prepared_round(tmp_path, monkeypatch)
    entered = threading.Barrier(2)

    def compile_repair():
        entered.wait(5)
        return json.loads(tools.compile_dsl_block("#headline s(420,hug)"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(compile_repair) for _ in range(2)]
        assert all(f.result(5)["compile"]["status"] == "ok" for f in futures)
    for _ in range(2):
        assert json.loads(tools.compile_dsl_block("#headline s(420,hug)"))["compile"]["status"] == "ok"
    assert json.loads(tools.compile_dsl_block("#headline s(420,hug)"))["error_code"] == "compile.inner_iteration_cap"
    assert tools.iteration == 8


def test_source_preparation_and_direction_validation_do_not_count_as_construction(tmp_path, monkeypatch):
    offline_models(monkeypatch)
    _, tools = harness.create_design_deepagent("Prepare a target logo", solo_config(tmp_path))
    tools.compile_dsl_block("page page_test size(1080,1080,px)")
    rounds = tools.trace_dir / "workspace/rounds"
    (rounds / "round_99").mkdir()
    assert emit_run_metrics(tools, rounds_dir=rounds)["rounds_total"] == 0
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.write_text(json.dumps(direction()))
    assert json.loads(tools.validate_creative_direction())["status"] == "ok"
    assert emit_run_metrics(tools, rounds_dir=rounds)["rounds_total"] == 0
    tools.compile_dsl_block("#headline s(400,hug)")
    assert emit_run_metrics(tools, rounds_dir=rounds)["rounds_total"] == 1


@pytest.mark.parametrize("verified", [True, False])
def test_only_verified_autofix_commit_consumes_the_pending_repair(tmp_path, monkeypatch, verified):
    from test_autofix import _AutofixCore, _diag

    _, _, tools, _, _ = prepared_round(tmp_path, monkeypatch)
    # Keep the real planner, verification and ledger commit. Substitute only
    # the engine boundary, as the existing autofix seam tests do.
    tools.core = _AutofixCore(repo_root=tools.config.repo_root)
    tools.config = replace(tools.config, autofix_max_passes=1)
    if not verified:
        tools.core.engine.parent_width = 10  # Hug would introduce a new overflow.
    result = tools._run_autofix(
        [*tools.core.engine.diagnose(tools.scene), _diag("LUMV0902", "error", "node", "headline")],
        None, tools._iteration_dir(),
    )
    assert result.changed is verified
    if verified:
        assert tools.scene["nodes"]["headline"]["size"]["width"] == {"kind": "hug"}
        assert tools.operations_ledger[-1]["source"] == "autofix"
        assert tools_current_round(tools) == 2
    else:
        assert tools.scene["nodes"]["headline"]["size"]["width"] == {"kind": "fixed", "value": 400.0}
        assert tools.operations_ledger[-1]["source"] != "autofix"
        assert tools_current_round(tools) == 1


def changing_preflight(tools, monkeypatch):
    original = tools.core.preflight_scene

    def normalize(*args, **kwargs):
        response = copy.deepcopy(original(*args, **kwargs))
        response["scene"]["nodes"]["headline"]["computed"]["layout_bounds"]["height"] += 1
        return response

    monkeypatch.setattr(tools.core, "preflight_scene", normalize)


def test_changed_preflight_normalization_does_not_consume_repair(tmp_path, monkeypatch):
    _, _, tools, _, _ = prepared_round(tmp_path, monkeypatch)
    stamp = tools._scene_stamp()
    changing_preflight(tools, monkeypatch)
    tools.preflight_design()
    assert tools._scene_stamp() != stamp
    assert tools.draft_verification()["review"]["status"] == "stale"
    assert tools_current_round(tools) == 1
    assert json.loads(tools.compile_dsl_block("#headline s(420,hug)"))["compile"]["status"] == "ok"
    assert tools_current_round(tools) == 2


def test_finalize_empty_page_cleanup_does_not_execute_a_repair(tmp_path, monkeypatch):
    class EmptyPageCore(_RenderCore):
        def compile_dsl_into_scene(self, *args, **kwargs):
            response = super().compile_dsl_into_scene(*args, **kwargs)
            response["scene"]["pages"]["empty"] = {"id": "empty", "children": []}
            return response

        def apply_operations(self, scene, operations, **kwargs):
            response = copy.deepcopy(super().apply_operations(scene, operations, **kwargs))
            for operation in operations:
                if operation["kind"] == "remove_page":
                    response["scene"]["pages"].pop(operation["page_id"])
            return response

    _, _, tools, _, _ = prepared_round(tmp_path, monkeypatch, core_class=EmptyPageCore)
    result = json.loads(tools.finalize_run("completed_with_warnings", "visual_qa_failed", "Draft."))
    assert result["status"] == "completed_with_warnings"
    assert "empty" not in tools.scene["pages"]
    assert tools.operations_ledger[-1]["source"] == "prune_empty_pages"
    assert tools_current_round(tools) == 1
    assert emit_run_metrics(tools, rounds_dir=tools.trace_dir / "workspace/rounds")["rounds_total"] == 1


def test_seeded_review_without_construction_keeps_root_critique_custody(tmp_path, monkeypatch):
    offline_models(monkeypatch)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _RenderCore)
    core = _RenderCore(repo_root=tmp_path)
    seed = core.compile_dsl_into_scene(core.new_scene("seed", "Seed"), "page")['scene']
    graph, tools = harness.create_design_deepagent("Review the scene", solo_config(tmp_path), initial_scene=seed)
    planned = direction()
    planned["copy"][0]["text"] = "Plan"
    workspace = tools.trace_dir / "workspace"
    (workspace / "creative-direction.json").write_text(json.dumps(planned))
    validated = json.loads(tools.validate_creative_direction())
    changing_preflight(tools, monkeypatch)
    tools.preflight_design()
    rendered = graph.nodes["tools"].bound.tools_by_name["render_preview"].invoke({})
    assert "previews/latest.png" in rendered
    assert tools_current_round(tools) == 0
    body = candidate_review(validated, page_id="page_test", node_id="headline", text="Plan")
    backend = AgentWorkspaceBackend(tools.trace_dir.parent, active_run_id=tools.run_id,
                                    critique_observer=tools.observe_written_critique)
    assert backend.write(f"/{tools.run_id}/workspace/critique.json", json.dumps(body)).error is None
    assert json.loads(tools.finalize_run("accepted", "review_complete", "Already ready."))["status"] == "accepted"
    assert emit_run_metrics(tools, rounds_dir=workspace / "rounds")["rounds_total"] == 0
