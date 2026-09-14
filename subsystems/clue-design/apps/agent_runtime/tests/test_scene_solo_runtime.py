"""Offline construction/dispatch checks for the candidate's one-agent loop."""

import json
from dataclasses import replace

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from lumen_agent import config as config_module
from lumen_agent import harness
from lumen_agent.cancellation import TurnCancelled
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.workspace import initial_turn_state
from py_lumen_config.config import Settings
from test_scene_catalog_runtime import ScriptedModel, call


def solo_config(tmp_path, **overrides):
    config = runtime_config(tmp_path)
    assert hasattr(config, "scene_solo"), "scene solo construction selector is missing"
    return replace(
        config,
        scene_solo=True,
        scene_skill_bundle="candidate",
        fast_loop=True,
        **overrides,
    )


def offline_models(monkeypatch, responses=None):
    built = []
    checked = []

    def build(model_id, **kwargs):
        model = ScriptedModel(responses=responses or [AIMessage(content="Offline complete.")])
        built.append((model_id, kwargs["role"], model))
        return model

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.init_model", build)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_model_supports_image_input",
        lambda model_id, **kwargs: checked.append(model_id),
    )
    return built, checked


def test_scene_solo_env_defaults_off_and_explicit_boolean_reaches_factory_config(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("LUMEN_AGENT_SCENE_SOLO", raising=False)
    default = Settings(_env_file=None)
    assert getattr(default, "lumen_agent_scene_solo", None) is False
    monkeypatch.setenv("LUMEN_AGENT_SCENE_SOLO", "1")
    enabled = Settings(_env_file=None)
    monkeypatch.setattr(config_module, "settings", enabled)
    config = config_module.AgentRuntimeConfig.from_env(tmp_path)
    assert config.scene_solo is True
    assert config.model == enabled.lumen_agent_model
    monkeypatch.setenv("LUMEN_AGENT_SCENE_SOLO", "0")
    assert Settings(_env_file=None).lumen_agent_scene_solo is False


@pytest.mark.parametrize(
    "bundle,fast_loop", [("legacy", True), ("candidate", False), ("legacy", False)]
)
def test_solo_rejects_incompatible_scene_configuration_before_any_model_or_workspace(
    tmp_path, monkeypatch, bundle, fast_loop
):
    built, checked = offline_models(monkeypatch)
    config = replace(solo_config(tmp_path), scene_skill_bundle=bundle, fast_loop=fast_loop)
    with pytest.raises(ValueError, match="candidate.*fast.loop"):
        harness.create_design_deepagent("Make an ad", config)
    assert built == checked == []
    assert not config.workspace_root.exists()


@pytest.mark.parametrize("scene_reviewer", [False, True])
def test_solo_compiled_graph_has_no_dispatch_and_builds_only_the_active_model(
    tmp_path, monkeypatch, scene_reviewer
):
    config = solo_config(
        tmp_path,
        scene_reviewer=scene_reviewer,
        agent_model_author="openai:unused-author",
        agent_model_reviewer="openai:unused-reviewer",
    )
    built, checked = offline_models(monkeypatch)
    graph, tools = harness.create_design_deepagent("Make an ad", config)
    assert [(model_id, role) for model_id, role, _ in built] == [
        (config.orchestrator_model, "design_orchestrator")
    ]
    assert checked == [config.orchestrator_model]
    names = set(graph.nodes["tools"].bound.tools_by_name)
    assert not {"task", "task_background", "task_result", "task_status"} & names
    assert {
        "view", "render_preview", "inspect", "compile_dsl_block", "asset", "fetch_logo",
        "validate_binding_set", "preflight_design", "validate_creative_direction",
        "record_gap", "finalize_run", "read_file", "write_file", "edit_file", "write_todos",
    } <= names
    assert tools.fast_loop_budget is not None
    assert config.scene_reviewer_enabled is False
    topology = [
        json.loads(line) for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
        if json.loads(line)["event"] == "scene_agent_topology"
    ]
    assert topology[-1]["payload"] == {
        "mode": "solo", "active_model_roles": ["orchestrator"], "subagents": [],
    }


def test_solo_uses_real_progressive_skills_permissions_and_durable_state(tmp_path, monkeypatch):
    responses = [
        call("read_file", {"file_path": "/.deepagent/skills/event-webinar/SKILL.md"}, "read"),
        call(
            "write_file",
            {"file_path": "/.deepagent/skills/event-webinar/forbidden.txt", "content": "new file"},
            "denied",
        ),
        call(
            "edit_file",
            {"file_path": "/.deepagent/skills/event-webinar/SKILL.md",
             "old_string": "name: event-webinar", "new_string": "name: changed"},
            "edit-denied",
        ),
        call("task", {"subagent_type": "general-purpose", "description": "Delegate"}, "absent"),
        AIMessage(content="Read locally without delegation."),
    ]
    built, _ = offline_models(monkeypatch, responses)
    checkpoint = InMemorySaver()
    graph, tools = harness.create_design_deepagent(
        "Make an event ad", solo_config(tmp_path), checkpointer=checkpoint
    )
    skill_path = tools.config.workspace_root / ".deepagent/skills/event-webinar/SKILL.md"
    original = skill_path.read_text()
    invocation = {"configurable": {"thread_id": "solo-offline"}}
    result = graph.invoke(initial_turn_state(tools, "Make an event ad"), invocation)
    outputs = {
        message.tool_call_id: message
        for message in result["messages"] if isinstance(message, ToolMessage)
    }
    read_body = "\n".join(line.split("\t", 1)[1] for line in outputs["read"].content.splitlines())
    assert read_body.strip() == original.strip()
    assert outputs["absent"].status == "error"
    assert "not a valid tool" in outputs["absent"].content
    assert skill_path.read_text() == original
    assert not skill_path.with_name("forbidden.txt").exists()
    assert "denied" in outputs["denied"].content.lower()
    assert "denied" in outputs["edit-denied"].content.lower()
    assert len(built) == 1
    first_system = built[0][2].seen[0][0].text
    assert "event-webinar" in first_system
    assert original.split("---", 2)[2].strip() not in first_system
    component_path = "/knowledge_docs/knowledge/scene/components.md"
    component_body = (tools.config.workspace_root / component_path.lstrip("/")).read_text()
    assert first_system.count(component_body) == 1
    initial_gather = first_system.split("1. Gather ", 1)[1].split("2. Inspect ", 1)[0]
    assert component_path not in initial_gather
    assert "Apply the loaded component guide" in first_system
    saved = checkpoint.get_tuple(invocation)
    assert saved is not None
    assert saved.checkpoint["channel_values"]["turn_request"] == "Make an event ad"
    assert tools.fast_loop_budget.calls == 5


@pytest.mark.parametrize(
    "auto_defaults,already_requested", [(False, False), (True, False), (False, True)]
)
def test_solo_retains_one_round_clarification_policy(
    tmp_path, monkeypatch, auto_defaults, already_requested
):
    offline_models(monkeypatch)
    graph, _ = harness.create_design_deepagent(
        "Make an ad", solo_config(tmp_path, auto_defaults=auto_defaults),
        clarification_already_requested=already_requested,
    )
    assert ("request_clarification" in graph.nodes["tools"].bound.tools_by_name) is (
        not auto_defaults and not already_requested
    )


def test_solo_cancellation_refuses_the_sole_model_before_generation(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch)
    graph, tools = harness.create_design_deepagent(
        "Make an ad", solo_config(tmp_path), cancel_requested=lambda: True,
    )
    with pytest.raises(TurnCancelled):
        graph.invoke(initial_turn_state(tools, "Make an ad"))
    assert built[0][2].seen == []


def test_scene_control_still_exposes_delegation_after_solo_construction(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch)
    config = solo_config(tmp_path)
    harness.create_design_deepagent("Make a solo ad", config)
    graph, _ = harness.create_design_deepagent(
        "Make a control ad", replace(config, scene_solo=False)
    )
    assert "task" in graph.nodes["tools"].bound.tools_by_name
    assert [role for _, role, _ in built] == [
        "design_orchestrator", "design_orchestrator", "design_author", "design_reviewer",
    ]


@pytest.mark.parametrize("web_solo", [False, True])
def test_scene_solo_selector_does_not_change_website_construction(tmp_path, monkeypatch, web_solo):
    from test_web_solo_mode import REPO_ROOT, _create_web_agent

    monkeypatch.setattr("lumen_agent.tools.web_substrate.new_run_id", lambda: "run_web_unchanged")
    config = replace(
        solo_config(tmp_path), repo_root=REPO_ROOT, scene_skill_bundle="legacy", fast_loop=False,
        web_solo=web_solo,
    )
    # This selector combination is refused for scenes, but website construction
    # must continue with exactly its own policy and tool surface.
    before = _create_web_agent(tmp_path, monkeypatch, replace(config, scene_solo=False))
    after = _create_web_agent(tmp_path, monkeypatch, config)

    def tool_names(entries):
        return {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in entries}

    assert before["system_prompt"] == after["system_prompt"]
    assert len(before["subagents"]) == len(after["subagents"])
    for control, current in zip(before["subagents"], after["subagents"], strict=True):
        for field in ("name", "description", "system_prompt", "model", "skills"):
            assert control[field] == current[field]
        assert tool_names(control["tools"]) == tool_names(current["tools"])
    assert before["skills"] == after["skills"]
    assert tool_names(before["tools"]) == tool_names(after["tools"])


def test_solo_compile_ceiling_preserves_scene_and_names_callable_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(solo_config(tmp_path, fast_loop_inner_iterations=1), "Make an ad")
    rounds = tools.trace_dir / "workspace/rounds"
    (rounds / "round_1").mkdir(parents=True)
    source = "page page_test size(1080,1080,px)"
    assert "compile" in json.loads(tools.compile_dsl_block(source))
    compiled_scene = json.dumps(tools.scene, sort_keys=True)
    refusal = json.loads(tools.compile_dsl_block(source))
    assert refusal["error_code"] == "compile.inner_iteration_cap"
    assert refusal["inner_iteration_cap"] == 1
    assert json.dumps(tools.scene, sort_keys=True) == compiled_scene
    assert "orchestrator" not in refusal["message"].lower()
    assert "finalize_run" in refusal["message"]
    assert "critique.json" in refusal["message"]
    assert "render_preview" in refusal["message"]
    (rounds / "round_2").mkdir()
    assert "compile" in json.loads(tools.compile_dsl_block(source))


def test_solo_budget_backstop_finishes_without_calling_another_model(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch, [
        call("read_file", {"file_path": "/.deepagent/skills/event-webinar/SKILL.md"}, "read"),
        AIMessage(content="This second call must never execute."),
    ])
    result, tools = harness.run_deepagent_turn(
        "Make an event ad", solo_config(tmp_path, fast_loop_max_llm_calls=1),
    )
    assert result["status"] == "failed"
    assert result["stop_reason"] == "budget_exhausted_llm_calls"
    assert tools.fast_loop_budget.calls == 1
    assert len(built) == 1 and len(built[0][2].seen) == 1
    assert json.loads((tools.trace_dir / "final.json").read_text()) == result


def test_solo_file_review_registers_current_evidence_and_render_checkpoints_once(
    tmp_path, monkeypatch
):
    from test_render_preview_reuse import _RenderCore
    from test_scene_skill_family import direction

    built, _ = offline_models(monkeypatch)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _RenderCore)
    checkpoints = []
    graph, tools = harness.create_design_deepagent(
        "Make an ad", solo_config(tmp_path),
        scene_checkpoint=lambda operations, meta: checkpoints.append((operations, meta)),
    )
    workspace = tools.trace_dir / "workspace"
    round_dir = workspace / "rounds/round_1"
    round_dir.mkdir(parents=True)
    (workspace / "creative-direction.json").write_text(json.dumps(direction()))
    registered = graph.nodes["tools"].bound.tools_by_name
    validated = json.loads(registered["validate_creative_direction"].invoke({}))
    assert validated["status"] == "ok"
    registered["compile_dsl_block"].invoke({"source": "page page_test size(1080,1080,px)"})
    registered["preflight_design"].invoke({})
    assert "status=ok" in registered["render_preview"].invoke({})
    review = {
        "accepted": True, "summary": "Inspected the current fixture pixels.", "issues": [],
        "direction_review": {
            "direction_digest": validated["direction_digest"],
            "checks": [
                {"section": row["section"], "index": row["index"], "status": "met",
                 "notes": "The fixture satisfies this declared requirement."}
                for row in validated["review_requirements"]
            ],
        },
    }
    finalize_args = {"status": "accepted", "stop_reason": "review_complete", "summary": "Ready."}
    built[0][2].responses = [
        call("finalize_run", finalize_args, "unreviewed"),
        call("write_file", {
            "file_path": f"/{tools.run_id}/workspace/rounds/round_1/critique.json",
            "content": json.dumps(review),
        }, "review"),
        call("render_preview", {}, "verified"),
        call("finalize_run", finalize_args, "accepted"),
        AIMessage(content="Creative ready."),
    ]
    result = graph.invoke(initial_turn_state(tools, "Make an ad"))
    outputs = {
        message.tool_call_id: message.content
        for message in result["messages"] if isinstance(message, ToolMessage)
    }
    assert outputs["unreviewed"].startswith("REFUSED")
    assert '"registered_review_current": true' in outputs["verified"]
    assert json.loads(outputs["accepted"])["status"] == "accepted"
    assert len(checkpoints) == 1
    assert [op["kind"] for op in checkpoints[0][0]] == ["add_page", "insert_node"]
    assert tools.core.exports == ["svg", "png"]
    assert (round_dir / "critique.json").is_file()
    assert json.loads((tools.trace_dir / "final.json").read_text())["acceptance_receipt"]
