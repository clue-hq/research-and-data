"""Real graph/tool execution with scripted offline models, not paid quality tests."""

import json

import pytest
from agent_fixtures import FakeCoreClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from lumen_agent import harness, materialize
from test_scene_skill_family import candidate_config, direction

EXPECTED_PLAYBOOKS = {
    "type-led-positioning",
    "authentic-product",
    "attributed-proof",
    "workflow-contrast",
    "problem-solution",
    "feature-deep-dive",
    "product-in-use",
    "launch-announcement",
    "comparison-alternatives",
    "case-study-narrative",
    "objection-handling",
    "offer-conversion",
    "event-webinar",
    "integration-ecosystem",
    "educational-guide",
    "visual-metaphor",
    "customer-spotlight",
    "editorial-pov",
}


class ScriptedModel(FakeMessagesListChatModel):
    seen: list = []
    bound_names: list = []
    first_bound_tools: list | None = None

    def bind_tools(self, tools, **kwargs):
        if self.first_bound_tools is None:
            self.first_bound_tools = list(tools)
        self.bound_names = [tool.name if hasattr(tool, "name") else tool["name"] for tool in tools]
        return self

    def _generate(self, messages, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, **kwargs)


def call(name, args, ident):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": ident}])


def test_real_harness_author_can_discover_load_revise_and_revalidate(tmp_path, monkeypatch):
    """Read a late-selected skill after delegation, then re-read on a new turn."""
    config = candidate_config(tmp_path)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.tools.substrate.new_run_id", lambda: "run_catalog")
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda _: None
    )
    playbook_path = "/.deepagent/skills/event-webinar/SKILL.md"
    author = ScriptedModel(
        responses=[
            call(
                "read_file", {"file_path": "/knowledge_docs/knowledge/scene/catalog.md"}, "catalog"
            ),
            call("read_file", {"file_path": playbook_path}, "first-read"),
            call("validate_creative_direction", {}, "validate"),
            AIMessage(content="Read and validated the direction."),
            call("read_file", {"file_path": playbook_path}, "revision-read"),
            call(
                "validate_creative_direction",
                {"revision_reason": "Update the supported message for this revision."},
                "revalidate",
            ),
            AIMessage(content="Re-read and validated the revision."),
        ]
    )
    director = ScriptedModel(
        responses=[
            call(
                "task",
                {
                    "subagent_type": "lumen-dsl-author",
                    "description": "Inspect the selected playbook.",
                },
                "delegate",
            ),
            AIMessage(content="First pass inspected."),
            call(
                "task",
                {
                    "subagent_type": "lumen-dsl-author",
                    "description": "Re-read the skill and validate the revised direction.",
                },
                "revision",
            ),
            AIMessage(content="Revision inspected."),
        ]
    )
    reviewer = ScriptedModel(responses=[AIMessage(content="unused")])
    models = iter([director, author, reviewer])
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: next(models))
    agent, tools = harness.create_design_deepagent(
        "Make an ad", config, checkpointer=InMemorySaver()
    )
    payload = direction()
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.write_text(json.dumps(payload))
    invocation = {"configurable": {"thread_id": "catalog-test"}, "recursion_limit": 30}
    agent.invoke(
        {"messages": [{"role": "user", "content": "Inspect the selected playbook."}]}, invocation
    )
    payload["copy"][0]["text"] = "A changed, supported message"
    path.write_text(json.dumps(payload))
    agent.invoke(
        {"messages": [{"role": "user", "content": "Review the revised copy."}]}, invocation
    )

    assert "validate_creative_direction" in author.bound_names
    messages = [m for turn in author.seen for m in turn if isinstance(m, ToolMessage)]
    by_id = {m.tool_call_id: m for m in messages}
    assert "Error" not in str(by_id["catalog"].content)
    assert "event-webinar" in str(by_id["catalog"].content)
    assert by_id["first-read"].content == by_id["revision-read"].content
    assert "event-webinar" in str(by_id["revision-read"].content)
    assert json.loads(by_id["validate"].content)["status"] == "ok"
    assert (
        json.loads(by_id["revalidate"].content)["direction"]["copy"][0]["text"]
        == payload["copy"][0]["text"]
    )
    # Metadata reaches every model call, while full playbook bodies arrive only
    # through explicit tool reads. No new policy is inferred from model output.
    for model in (director, author):
        for turn in model.seen:
            system = str(turn[0].content)
            assert all(name in system for name in EXPECTED_PLAYBOOKS)
            assert "## When to use" not in system


def test_catalog_is_derived_and_new_registration_needs_no_python_change(tmp_path, monkeypatch):
    import shutil

    from lumen_agent.tools.substrate import LumenDesignTools

    source = tmp_path / "source"
    shutil.copytree(materialize._PACKAGE_KNOWLEDGE_DOCS, source)
    scene = source / "views/scene"
    name = "a-future-evidence-family"
    description = "Choose this when an independently registered evidence structure applies."
    folder = scene / "skills" / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# Future family\n"
    )
    manifest_path = scene / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["skills"].append(name)
    manifest["playbooks"].append(name)
    manifest_path.write_text(json.dumps(manifest))
    config = candidate_config(tmp_path)
    materialize.materialize_agent_workspace(
        config, source_knowledge_docs=source, knowledge_view="scene"
    )
    catalog = (config.workspace_root / "knowledge_docs/knowledge/scene/catalog.md").read_text()
    assert name in catalog and description in catalog
    assert "# Future family" not in catalog
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(config, "Make an evidence-led creative")
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = direction()
    payload["playbook"] = name
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "ok"
    payload["playbook"] = "not-registered"
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "error"

    # Description changes invalidate the materialized stamp/catalog together.
    old_stamp = (config.workspace_root / ".deepagent/.sync-stamp").read_text()
    skill = folder / "SKILL.md"
    skill.write_text(skill.read_text().replace(description, "A revised discovery description."))
    materialize.materialize_agent_workspace(
        config, source_knowledge_docs=source, knowledge_view="scene"
    )
    catalog = (config.workspace_root / "knowledge_docs/knowledge/scene/catalog.md").read_text()
    assert "A revised discovery description." in catalog and description not in catalog
    assert (config.workspace_root / ".deepagent/.sync-stamp").read_text() != old_stamp

    # A future family can opt into existing evidence mechanics through data.
    manifest.setdefault("playbook_requirements", {})[name] = {
        "claim_kinds": ["statistic"],
        "attribution": True,
    }
    manifest_path.write_text(json.dumps(manifest))
    materialize.materialize_agent_workspace(
        config, source_knowledge_docs=source, knowledge_view="scene"
    )
    payload["playbook"] = name
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "error"
    payload["evidence"] = [
        {
            "id": "result",
            "source": "supplied-report:1",
            "excerpt": "12 teams in the documented pilot",
        }
    ]
    payload["copy"][0].update(text="12 teams", claim_kind="statistic", evidence_refs=["result"])
    payload["copy"].append(
        {
            "id": "credit",
            "role": "attribution",
            "text": "Documented pilot",
            "claim_kind": "assertion",
            "evidence_refs": ["result"],
        }
    )
    payload["layers"].append(
        {
            "id": "credit",
            "kind": "native_text",
            "purpose": "Identify source",
            "copy_id": "credit",
            "placement": {"x": 0, "y": 0.9, "width": 0.9, "height": 0.1},
        }
    )
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction(
        revision_reason="Add the supplied pilot statistic and its native attribution."
    ))["status"] == "ok"


def test_registered_families_cannot_bypass_evidence_source_or_native_checks(tmp_path, monkeypatch):
    from lumen_agent.tools.substrate import LumenDesignTools

    config = candidate_config(tmp_path)
    materialize.materialize_agent_workspace(config, knowledge_view="scene")
    assert set(materialize.scene_view_manifest()["playbooks"]) == EXPECTED_PLAYBOOKS
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(config, "Check a supplied direction")
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED_PLAYBOOKS:
        for defect in ("unsupported-quote", "unavailable-source", "raster-copy"):
            payload = direction()
            payload["playbook"] = name
            if defect == "unsupported-quote":
                payload["copy"][0].update(claim_kind="quote", evidence_refs=["made-up"])
            elif defect == "unavailable-source":
                payload["source_roles"] = [{"asset_id": "missing", "role": "product"}]
            else:
                payload["layers"][0]["kind"] = "generated_image"
            path.write_text(json.dumps(payload))
            result = json.loads(tools.validate_creative_direction())
            assert result["status"] == "error", (name, defect, result)


@pytest.mark.parametrize("playbook", ["authentic-product", "attributed-proof"])
def test_partial_edit_cannot_omit_required_source_or_proof(tmp_path, monkeypatch, playbook):
    from lumen_agent.tools.substrate import LumenDesignTools

    config = candidate_config(tmp_path)
    materialize.materialize_agent_workspace(config, knowledge_view="scene")
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(config, "Repair spacing")
    payload = direction()
    payload.update(playbook=playbook, intent="edit", copy=[])
    payload["layers"] = [
        {
            "id": "frame",
            "kind": "native_geometry",
            "purpose": "Repair spacing",
            "placement": {"x": 0, "y": 0, "width": 1, "height": 1},
        }
    ]
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "error"


@pytest.mark.parametrize("playbook", ["editorial-pov", "attributed-proof", "customer-spotlight"])
def test_actual_quote_needs_attribution_linked_to_its_source_in_every_family(playbook):
    from lumen_agent.models.creative_direction import CreativeDirection

    payload = direction()
    payload["playbook"] = playbook
    payload["copy"][0].update(claim_kind="quote", evidence_refs=["source-quote"])
    payload["evidence"] = [
        {
            "id": "source-quote",
            "source": "supplied-case-study:12",
            "excerpt": "Make the next step clear — Operations lead",
        }
    ]
    with pytest.raises(ValueError, match="attribution"):
        CreativeDirection.model_validate(payload)
    payload["copy"].append(
        {
            "id": "credit",
            "role": "attribution",
            "text": "Operations lead",
            "claim_kind": "assertion",
            "evidence_refs": ["source-quote"],
        }
    )
    payload["layers"].append(
        {
            "id": "credit",
            "kind": "native_text",
            "purpose": "Credit the speaker",
            "copy_id": "credit",
            "placement": {"x": 0, "y": 0.9, "width": 0.9, "height": 0.1},
        }
    )
    assert CreativeDirection.model_validate(payload).playbook == playbook
    # An edit can retain unchanged attribution without requiring it to mutate.
    payload["intent"] = "edit"
    assert CreativeDirection.model_validate(payload).copy_blocks[1].role == "attribution"


@pytest.mark.parametrize("playbook", ["authentic-product", "attributed-proof"])
def test_new_direction_keeps_registered_evidence_requirement(tmp_path, monkeypatch, playbook):
    from lumen_agent.tools.substrate import LumenDesignTools

    config = candidate_config(tmp_path)
    materialize.materialize_agent_workspace(config, knowledge_view="scene")
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(config, "Make a creative")
    payload = direction()
    payload["playbook"] = playbook
    path = tools.trace_dir / "workspace/creative-direction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    assert json.loads(tools.validate_creative_direction())["status"] == "error"


def test_candidate_frame_preserves_authored_type_without_inventing_canvas_floors(
    tmp_path, monkeypatch
):
    from lumen_agent.frame import build_frame_payload
    from lumen_agent.tools.substrate import LumenDesignTools

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(candidate_config(tmp_path), "Recompose an editorial brand ad")
    tools.brand_card = {
        "name": "Measured brand",
        "type_roles": {"type.display": {"family": "Source Face", "weight": 500, "size": 41}},
    }
    payload = build_frame_payload(tools)
    assert "Source Face" in payload
    assert "41" in payload
    assert "floor_at_1080" not in payload
    assert "floor at 1080" not in payload
    assert "Multiply by your declared short edge" not in payload
