"""Candidate model finalization consumes the registered review through the real graph."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from lumen_agent import harness, harness_web
from lumen_agent.workspace import initial_turn_state
from test_final_acceptance_contract import _compile, _prepare
from test_scene_catalog_runtime import call
from test_scene_direction_review import review, validate, write_direction
from test_scene_skill_family import direction
from test_scene_solo_runtime import offline_models, solo_config

FINAL_ARGS = {"status": "accepted", "stop_reason": "review_complete", "summary": "Ready."}


def candidate_graph(tmp_path, monkeypatch, *, solo=True, fast_loop=True):
    built, _ = offline_models(monkeypatch)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda _: None
    )
    graph, tools = harness.create_design_deepagent(
        "Make an ad", replace(solo_config(tmp_path), scene_solo=solo, fast_loop=fast_loop)
    )
    return graph, tools, built[0][2]


def first_bound_schemas(graph, tools, model):
    graph.invoke(initial_turn_state(tools, "Make an ad"))
    assert model.first_bound_tools is not None
    return [convert_to_openai_tool(tool)["function"] for tool in model.first_bound_tools]


@pytest.mark.parametrize("solo,fast_loop", [(True, True), (False, True), (False, False)])
def test_candidate_first_model_schema_exposes_only_registered_review_finalizer(
    tmp_path, monkeypatch, solo, fast_loop
):
    graph, tools, model = candidate_graph(tmp_path, monkeypatch, solo=solo, fast_loop=fast_loop)
    finalizers = [
        s for s in first_bound_schemas(graph, tools, model) if s["name"] == "finalize_run"
    ]
    assert len(finalizers) == 1
    schema = finalizers[0]["parameters"]
    # Harness alignment T11 (founder rulings 2026-10-18): the agent sees only these three; the
    # runtime's own re-finalize still passes the rest to the method.
    assert set(schema["properties"]) == {"status", "stop_reason", "summary"}
    assert schema["required"] == ["status", "stop_reason", "summary"]
    assert all(prop.get("description") for prop in schema["properties"].values())
    # LangChain's model-facing subset drops Pydantic model_config; validation
    # still uses the explicit input schema (exercised through ToolNode below).
    bound = graph.nodes["tools"].bound.tools_by_name["finalize_run"]
    assert bound.args_schema.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("solo", [True, False])
@pytest.mark.parametrize("unknown", ["critique_json", "critique_path", "review_ref"])
def test_candidate_toolnode_refuses_unknown_review_arguments(tmp_path, monkeypatch, solo, unknown):
    graph, tools, model = candidate_graph(tmp_path, monkeypatch, solo=solo)
    model.responses = [
        call(
            "finalize_run",
            {**FINAL_ARGS, "status": "completed_with_warnings", unknown: "{}"},
            "extra",
        ),
        AIMessage(content="Retained the unfinished draft."),
    ]
    result = graph.invoke(initial_turn_state(tools, "Make an ad"))
    output = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert output.status == "error"
    assert unknown in output.content
    assert not (tools.trace_dir / "final.json").exists()


@pytest.mark.parametrize("fast_loop", [True, False])
def test_legacy_first_model_schema_and_explicit_critique_stay_available(
    tmp_path, monkeypatch, fast_loop
):
    built, _ = offline_models(monkeypatch)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda _: None
    )
    graph, tools = harness.create_design_deepagent(
        "Make an ad",
        replace(
            solo_config(tmp_path),
            scene_solo=False,
            scene_skill_bundle="legacy",
            fast_loop=fast_loop,
        ),
    )
    finalizers = [
        s for s in first_bound_schemas(graph, tools, built[0][2]) if s["name"] == "finalize_run"
    ]
    assert len(finalizers) == 1
    assert finalizers[0]["parameters"]["properties"]["critique_json"]["default"] == "{}"
    critique = _prepare(tools)
    result = (
        graph.nodes["tools"]
        .bound.tools_by_name["finalize_run"]
        .invoke({**FINAL_ARGS, "critique_json": json.dumps(critique)})
    )
    assert json.loads(result)["status"] == "accepted"


@pytest.mark.parametrize("solo", [True, False])
def test_website_first_model_finalizer_schema_is_unchanged(tmp_path, monkeypatch, solo):
    from lumen_api.core import CoreClient
    from test_web_solo_mode import REPO_ROOT

    built, _ = offline_models(monkeypatch)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda _: None
    )
    config = replace(solo_config(tmp_path), repo_root=REPO_ROOT, web_solo=solo)
    doc = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_finalize", "Finalizer", None)["web_doc"]
    graph, tools = harness_web.create_web_deepagent("Build a page", config, doc)
    graph.invoke({"messages": [{"role": "user", "content": "Inspect the page"}]})
    schemas = [convert_to_openai_tool(tool)["function"] for tool in built[0][2].first_bound_tools]
    assert not any(s["name"] == "finalize_run" for s in schemas)
    finalizers = [s for s in schemas if s["name"] == "finalize_web_run"]
    assert len(finalizers) == 1
    schema = finalizers[0]["parameters"]
    assert set(schema["properties"]) == {"outcome", "summary", "ladder_gap"}
    assert schema["required"] == ["outcome", "summary"]
    assert schema["properties"]["ladder_gap"]["default"] is None


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "missing_review",
        "malformed_review",
        "rejected",
        "blocker",
        "error",
        "missing_preflight",
        "missing_preview",
        "missing_direction_index",
        "direction_deviation",
        "changed_direction",
        "stale_scene",
        "stale_preflight",
        "deleted_preview",
        "changed_preview",
        "fidelity_1",
        "fidelity_2",
    ],
)
def test_candidate_facade_preserves_authoritative_acceptance_checks(tmp_path, monkeypatch, defect):
    graph, tools, _ = candidate_graph(tmp_path, monkeypatch)
    _compile(tools)
    if defect != "missing_preflight":
        tools.preflight_design()
    if defect != "missing_preview":
        tools.export_preview("svg")
    planned = direction()
    planned["copy"][0]["text"] = "Plan"  # The actual FakeCore fixture's native text.
    body = review(validate(tools, planned), page_id="page_test", node_id="headline", text="Plan")
    if defect == "rejected":
        body["accepted"] = False
    elif defect in {"blocker", "error"}:
        body["issues"] = [
            {
                "severity": defect,
                "category": "brand_fit",
                "message": "Wrong logo",
                "suggested_repair": "Use the supplied logo.",
            }
        ]
    elif defect == "missing_direction_index":
        body["direction_review"]["checks"].pop()
    elif defect == "direction_deviation":
        body["direction_review"]["checks"][0]["status"] = "deviation"
    elif defect in {"fidelity_1", "fidelity_2"}:
        tools._selected_reference_ids.add("source-reference")
        body["reference_fidelity"] = {"score": 1 if defect == "fidelity_1" else 2}
    if defect != "missing_review":
        registered = json.loads(tools.submit_visual_critique(json.dumps(body)))
        invalid = defect in {
            "missing_direction_index", "direction_deviation", "missing_preflight", "missing_preview"
        }
        assert registered["status"] == ("error" if invalid else "ok")
    if defect == "malformed_review":
        tools.submit_visual_critique('{"accepted": true}')
    elif defect == "changed_direction":
        changed = direction()
        changed["preserve"] = ["Changed requirement"]
        write_direction(tools, changed)
    elif defect in {"stale_scene", "stale_preflight"}:
        _compile(tools)
        if defect == "stale_preflight":
            tools.export_preview("svg")
            tools.submit_visual_critique(json.dumps(body))
    elif defect in {"deleted_preview", "changed_preview"}:
        path = Path(tools.latest_export_summary["artifacts"][0]["path"])
        if defect == "deleted_preview":
            path.unlink()
        else:
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Changed</text></svg>')
    finalizer = graph.nodes["tools"].bound.tools_by_name["finalize_run"]
    result = finalizer.invoke(FINAL_ARGS)
    if defect in {None, "fidelity_2"}:
        assert json.loads(result)["status"] == "accepted"
        assert json.loads(result)["acceptance_receipt"] == tools._review_receipt
        assert json.loads(result)["ops_valid_through_iteration"] is None
        assert json.loads(result)["baseline_advisory"] is None
        assert json.loads(result)["accommodation"] is None
    else:
        assert result.startswith("REFUSED"), result
        assert not (tools.trace_dir / "final.json").exists()


def test_reviewed_candidate_preserves_separate_draft_channel_copy_in_final_summary(
    tmp_path, monkeypatch,
):
    """The handoff consumes final.json, so a loose assistant message is insufficient."""
    graph, tools, _ = candidate_graph(tmp_path, monkeypatch)
    _compile(tools)
    tools.preflight_design()
    tools.export_preview("svg")
    planned = direction()
    planned["copy"][0]["text"] = "Plan"
    body = review(validate(tools, planned), page_id="page_test", node_id="headline", text="Plan")
    assert json.loads(tools.submit_visual_critique(json.dumps(body)))["status"] == "ok"
    summary = "Creative reviewed.\n\nDraft LinkedIn copy:\nAcme team, explore a clearer next step."
    result = json.loads(graph.nodes["tools"].bound.tools_by_name["finalize_run"].invoke({
        **FINAL_ARGS, "summary": summary,
    }))
    persisted = json.loads((tools.trace_dir / "final.json").read_text())
    assert result["status"] == persisted["status"] == "accepted"
    assert result["summary"] == persisted["summary"] == summary
    # Companion draft copy does not enter the artwork or add a direction field.
    assert tools.scene["nodes"]["headline"]["kind"]["content"] == "Plan"
    assert tools._validated_direction.copy_blocks[0].text == "Plan"


@pytest.mark.parametrize(
    "status,stale",
    [
        ("completed_with_warnings", False),
        ("completed_with_warnings", True),
        ("edit_applied", False),
    ],
)
def test_candidate_nonaccepted_exit_preserves_review_draft_and_refuses_dropped_arguments(
    tmp_path, monkeypatch, status, stale
):
    graph, tools, _ = candidate_graph(tmp_path, monkeypatch)
    _compile(tools)
    tools.preflight_design()
    tools.export_preview("svg")
    body = {"accepted": False, "summary": "The headline still needs repair."}
    tools.submit_visual_critique(json.dumps(body))
    if stale:
        _compile(tools)
    finalize = graph.nodes["tools"].bound.tools_by_name["finalize_run"]
    # Harness alignment T11: the agent can no longer pass the three dropped arguments.
    for dropped in ("ops_valid_through_iteration", "baseline_advisory_json", "accommodation_json"):
        with pytest.raises(Exception):
            finalize.invoke({**FINAL_ARGS, "status": status, "stop_reason": "x", dropped: "null"})
    result = json.loads(
        finalize.invoke({**FINAL_ARGS, "status": status, "stop_reason": "review_rejected"})
    )
    assert result["status"] == status
    assert result["stop_reason"] == "review_rejected"
    if stale:
        assert result["critique"] == {}
        assert result["historical_critique"]["critique"]["accepted"] is False
        assert result["historical_critique"]["status"] == "stale"
    else:
        assert result["critique"]["accepted"] is False
        if status == "completed_with_warnings":
            assert body["summary"] in result["summary"]
    assert result["acceptance_receipt"] is None
    assert result["ops_valid_through_iteration"] is None
    assert result["baseline_advisory"] is None
    assert result["accommodation"] is None
    assert json.loads((tools.trace_dir / "final_scene.json").read_text()) == tools.scene
