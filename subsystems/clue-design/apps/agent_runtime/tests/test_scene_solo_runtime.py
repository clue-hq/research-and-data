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


def test_scene_solo_env_defaults_on_and_explicit_boolean_reaches_factory_config(
    tmp_path, monkeypatch
):
    # Founder ruling 2026-10-04, restated 2026-10-16: the scene agent always runs solo, so solo
    # and the candidate bundle it requires are the code defaults.
    monkeypatch.delenv("LUMEN_AGENT_SCENE_SOLO", raising=False)
    monkeypatch.delenv("LUMEN_AGENT_SCENE_SKILL_BUNDLE", raising=False)
    default = Settings(_env_file=None)
    assert getattr(default, "lumen_agent_scene_solo", None) is True
    assert default.lumen_agent_scene_skill_bundle == "candidate"
    assert default.lumen_agent_fast_loop is True
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
    # Harness alignment I9: no to-do tool in the scene agent.
    assert "write_todos" not in names
    assert {
        "view", "render_preview", "inspect", "compile_dsl_block", "asset", "fetch_logo",
        "validate_binding_set", "preflight_design", "validate_creative_direction",
        "record_gap", "finalize_run", "read_file", "write_file", "edit_file",
        # A follow-up's targeted edit goes through the typed edit builder, not a compile.
        "apply_structured_edit",
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


@pytest.mark.parametrize(
    "skill_name,user_prompt",
    [("event-webinar", "Make an event ad"), ("account-adaptation", "Make an ad addressed to Acme")],
)
def test_solo_uses_real_progressive_skills_permissions_and_durable_state(
    tmp_path, monkeypatch, skill_name, user_prompt
):
    virtual_skill = f"/.deepagent/skills/{skill_name}/SKILL.md"
    responses = [
        call("read_file", {"file_path": virtual_skill, "limit": 500}, "read"),
        call(
            "write_file",
            {"file_path": f"/.deepagent/skills/{skill_name}/forbidden.txt", "content": "new file"},
            "denied",
        ),
        call(
            "edit_file",
            {"file_path": virtual_skill,
             "old_string": f"name: {skill_name}", "new_string": "name: changed"},
            "edit-denied",
        ),
        call("task", {"subagent_type": "general-purpose", "description": "Delegate"}, "absent"),
        AIMessage(content="Read locally without delegation."),
    ]
    built, _ = offline_models(monkeypatch, responses)
    checkpoint = InMemorySaver()
    graph, tools = harness.create_design_deepagent(
        user_prompt, solo_config(tmp_path), checkpointer=checkpoint
    )
    skill_path = tools.config.workspace_root / virtual_skill.lstrip("/")
    original = skill_path.read_text()
    invocation = {"configurable": {"thread_id": "solo-offline"}}
    result = graph.invoke(initial_turn_state(tools, user_prompt), invocation)
    outputs = {
        message.tool_call_id: message
        for message in result["messages"] if isinstance(message, ToolMessage)
    }
    assert outputs["read"].additional_kwargs["guidance_read"]["whole_resource"] is True
    _, numbered_source = outputs["read"].content.split("\n\n", 1)
    read_body = "\n".join(line.split("\t", 1)[1] for line in numbered_source.splitlines())
    assert read_body.strip() == original.strip()
    assert outputs["absent"].status == "error"
    assert "not a valid tool" in outputs["absent"].content
    assert skill_path.read_text() == original
    assert not skill_path.with_name("forbidden.txt").exists()
    assert "denied" in outputs["denied"].content.lower()
    assert "denied" in outputs["edit-denied"].content.lower()
    assert len(built) == 1
    first_system = built[0][2].seen[0][0].text
    assert skill_name in first_system
    assert original.split("---", 2)[2].strip() not in first_system
    component_path = "/knowledge_docs/knowledge/scene/components.md"
    component_body = (tools.config.workspace_root / component_path.lstrip("/")).read_text()
    assert first_system.count(component_body) == 1
    initial_gather = first_system.split("1. Gather ", 1)[1].split("2. Inspect ", 1)[0]
    assert component_path not in initial_gather
    assert "Apply the component guide and the DSL grammar, both already in this prompt" in first_system
    saved = checkpoint.get_tuple(invocation)
    assert saved is not None
    assert saved.checkpoint["channel_values"]["turn_request"] == user_prompt
    assert tools.fast_loop_budget.calls == 5


def test_solo_bound_prompt_separates_logo_page_bootstrap_from_creative_construction(
    tmp_path, monkeypatch
):
    """Catch the page-required/source-ID cycle in the prompt the solo model receives."""
    built, _ = offline_models(monkeypatch)
    graph, tools = harness.create_design_deepagent(
        "Make an account ad using its real logo", solo_config(tmp_path)
    )
    graph.invoke(initial_turn_state(tools, tools.prompt))
    prompt = built[0][2].seen[0][0].text
    preparation = prompt.split("2. Inspect ", 1)[1].split("3. Write ", 1)[0]
    assert "page-only source preparation" in preparation
    assert preparation.index("compile_dsl_block") < preparation.index("fetch_logo")
    assert preparation.index("fetch_logo") < preparation.index("view('asset:<returned_id>')")
    assert "creative nodes or new imagery spend" in preparation
    direction = prompt.split("3. Write ", 1)[1].split("4. Create ", 1)[0]
    assert "validate_creative_direction()" in direction
    assert "Resolve refusals before construction" in direction
    # Harness alignment I11: the step-2 instruction is the one home of this rule. The eagerly
    # bound component guide no longer carries its own copy, so it cannot carry a conflicting one.
    assert "Page before spend" not in prompt
    assert prompt.count("page-only source preparation") == 1


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
    # A note directory alone is not executed repair work or a budget grant.
    assert json.loads(tools.compile_dsl_block(source))["error_code"] == "compile.inner_iteration_cap"
    assert json.dumps(tools.scene, sort_keys=True) == compiled_scene


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


@pytest.mark.parametrize("verify_again", [False, True])
def test_solo_file_review_registers_current_evidence_and_render_checkpoints_once(
    tmp_path, monkeypatch, verify_again
):
    from test_render_preview_reuse import _RenderCore
    from test_scene_direction_review import review as candidate_review
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
    planned = direction()
    planned["copy"][0]["text"] = "Plan"  # The actual FakeCore fixture's native text.
    (workspace / "creative-direction.json").write_text(json.dumps(planned))
    registered = graph.nodes["tools"].bound.tools_by_name
    validated = json.loads(registered["validate_creative_direction"].invoke({}))
    assert validated["status"] == "ok"
    registered["compile_dsl_block"].invoke({"source": "page page_test size(1080,1080,px)"})
    registered["preflight_design"].invoke({})
    assert "status=ok" in registered["render_preview"].invoke({})
    review = candidate_review(validated, page_id="page_test", node_id="headline", text="Plan")
    finalize_args = {"status": "accepted", "stop_reason": "review_complete", "summary": "Ready."}
    receipt = {"scene": tools._scene_stamp(), "preview": tools._preview_receipt}
    built[0][2].responses = [
        call("view", {"target": "preview"}, "pixels"),
        call("write_file", {
            "file_path": f"/{tools.run_id}/workspace/rounds/round_1/critique.json",
            "content": json.dumps(review),
        }, "review"),
        *([call("render_preview", {}, "verified")] if verify_again else []),
        call("finalize_run", finalize_args, "accepted"),
        AIMessage(content="Creative ready."),
    ]
    result = graph.invoke(initial_turn_state(tools, "Make an ad"))
    outputs = {
        message.tool_call_id: message.content
        for message in result["messages"] if isinstance(message, ToolMessage)
    }
    assert any(block.get("type") == "image" and block.get("data") for block in outputs["pixels"])
    if verify_again:
        assert '"registered_review_current": true' in outputs["verified"]
    final = json.loads(outputs["accepted"])
    assert final["status"] == "accepted"
    assert final["acceptance_receipt"] == receipt == tools._review_receipt
    assert len(checkpoints) == 1
    assert [op["kind"] for op in checkpoints[0][0]] == ["add_page", "insert_node"]
    assert tools.core.exports == ["svg", "png"]
    assert (round_dir / "critique.json").is_file()
    assert json.loads((tools.trace_dir / "final.json").read_text())["acceptance_receipt"]
    events = [
        json.loads(line)["event"]
        for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
    ]
    assert events.count("critique_result") == events.count("run_finalized") == 1
    assert "preflight_completed" not in events[events.index("critique_result") + 1:]
    final_calls = [
        call for turn in built[0][2].seen for message in turn
        if isinstance(message, AIMessage) for call in message.tool_calls
        if call["name"] == "finalize_run"
    ]
    assert len(final_calls) == 1
    assert final_calls[0]["args"] == finalize_args


# --- the platform's account reads ride the solo graph (design note 2026-09-19) ---
class _StubReads:
    """The duck type the design runtime knows: three reads plus the seller's pinned set."""

    def read_project_accounts(self, **kw):
        return {"total": 0, "accounts": []}

    def read_account_research(self, **kw):
        return {"sections": []}

    def read_claims(self, **kw):
        return {"claims": [], "prefixes": []}

    def seller_knowledge(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            documents_sha256=None, documents=(), confirmed_icp_path=None, product_set=None
        )


@pytest.mark.parametrize("attached", [True, False])
def test_the_account_reads_are_registered_only_when_the_platform_injected_them(
    tmp_path, monkeypatch, attached
):
    offline_models(monkeypatch)
    config = solo_config(tmp_path, platform_reads=_StubReads() if attached else None)
    graph, tools = harness.create_design_deepagent("Make an ad for Premier", config)

    names = set(graph.nodes["tools"].bound.tools_by_name)
    reads = {"read_project_accounts", "read_account_research", "read_claims"}
    assert (reads <= names) is attached
    events = [
        json.loads(line) for line in (tools.turn_dir / "trace.jsonl").read_text().splitlines()
    ]
    attached_events = [e for e in events if e["event"] == "platform_reads_attached"]
    assert bool(attached_events) is attached
    if attached:
        assert set(attached_events[-1]["payload"]["tools"]) == reads
