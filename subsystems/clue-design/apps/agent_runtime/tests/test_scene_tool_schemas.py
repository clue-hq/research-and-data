"""The solo scene agent's tool schemas say what every parameter means (harness alignment T11).

Founder rulings 2026-10-18: every scene tool parameter carries one plain description in the schema
the model receives; JSON-in-a-string inputs became real objects (apply_structured_edit) or were
dropped (finalize_run's carry-overs); validate_binding_set is not offered; a fixed list of allowed
values exists only where the code already refuses every other value.

The structured-edit scenarios run on the real engine (the release helper), through the same tool
object the solo agent is given, so a wrong example in the schema or a broken wrapper fails here.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from lumen_agent import harness, prompts
from lumen_agent.models.scene_tool_inputs import SCENE_EDIT_KINDS
from lumen_agent.tools import substrate
from lumen_agent.workspace import initial_turn_state
from test_scene_catalog_runtime import ScriptedModel

SCENE_TOOLS = {
    "view", "render_preview", "inspect", "search_assets", "preflight_design", "record_gap",
    "validate_creative_direction", "finalize_run", "compile_dsl_block", "asset", "fetch_logo",
    "apply_structured_edit", "request_clarification",
}


def _first_call_schemas(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    built = []

    def build(model_id, **kwargs):
        model = ScriptedModel(responses=[AIMessage(content="done")])
        model.seen = []
        built.append(model)
        return model

    monkeypatch.setattr("lumen_agent.llm.init_model", build)
    monkeypatch.setattr("lumen_agent.llm.assert_model_supports_image_input", lambda *a, **k: None)
    config = replace(runtime_config(tmp_path), scene_solo=True, scene_skill_bundle="candidate",
                     fast_loop=True)
    graph, tools = harness.create_design_deepagent("Make an ad", config)
    graph.invoke(initial_turn_state(tools, "Make an ad") | {"messages": [("human", "Make an ad")]},
                 {"configurable": {"thread_id": "schemas"}})
    names = [getattr(tool, "name", None) for tool in built[0].first_bound_tools]
    schemas = {
        schema["function"]["name"]: schema["function"]
        for schema in (convert_to_openai_tool(tool) for tool in built[0].first_bound_tools)
    }
    return names, schemas


def _walk_properties(schema):
    """Every (path, property) in a JSON schema, through nested objects, arrays and unions."""
    stack = [("", schema)]
    while stack:
        path, node = stack.pop()
        if not isinstance(node, dict):
            continue
        for name, prop in (node.get("properties") or {}).items():
            yield f"{path}.{name}", prop
            stack.append((f"{path}.{name}", prop))
        for key in ("items", "anyOf", "oneOf", "allOf"):
            value = node.get(key)
            for child in value if isinstance(value, list) else [value] if value else []:
                stack.append((path, child))


def test_every_scene_tool_parameter_is_described_and_typed(tmp_path, monkeypatch):
    names, schemas = _first_call_schemas(tmp_path, monkeypatch)
    assert SCENE_TOOLS <= set(schemas)
    assert names.count("search_assets") == 1
    assert "validate_binding_set" not in schemas
    for name in SCENE_TOOLS:
        schema = schemas[name]
        assert not any(line.startswith("    ") for line in schema["description"].splitlines()), (
            f"{name}: description still carries source indentation"
        )
        for path, prop in _walk_properties(schema["parameters"]):
            if path.count(".") == 1 or name != "apply_structured_edit":
                assert prop.get("description") or prop.get("$ref"), f"{name}{path} has no description"
        params = set(schema["parameters"].get("properties") or {})
        assert not {p for p in params if p.endswith("_json")}, f"{name} still takes JSON strings"
    assert set(schemas["finalize_run"]["parameters"]["properties"]) == {
        "status", "stop_reason", "summary",
    }
    assert set(schemas["record_gap"]["parameters"]["properties"]) == {"area", "summary", "evidence"}
    # record_gap.area stays free text: the code files an unknown area instead of refusing it.
    assert "enum" not in schemas["record_gap"]["parameters"]["properties"]["area"]
    asset = schemas["asset"]["parameters"]["properties"]
    assert set(asset["action"]["enum"]) == {
        "generate_image", "edit_image", "crop_image", "generate_qr", "place", "use_brand_asset",
    }
    assert "enum" not in json.dumps(asset["ec_level"])  # the code also takes "low", "HIGH" ...
    inspect_view = schemas["inspect"]["parameters"]["properties"]["view"]
    assert len(inspect_view["enum"]) == 8
    limit = schemas["search_assets"]["parameters"]["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"]) == (1, 20)
    assert set(schemas["apply_structured_edit"]["parameters"]["properties"]) == {"edit", "scope"}
    edit_text = json.dumps(schemas["apply_structured_edit"])
    for kind in SCENE_EDIT_KINDS:
        assert f'"{kind}"' in edit_text
    for left_out in ("archive_asset", "hard_delete_asset", "detach_to_freehand",
                     "reattach_to_layout", "convert_container_layout", "freeze_layout",
                     "delete_export_profile"):
        assert left_out not in edit_text
    logo = " ".join(schemas["fetch_logo"]["description"].split())
    assert "Choose the authentic variant" in logo and "In an account-personalized" not in logo


def test_solo_prompt_names_tools_without_brackets_and_no_missing_parameter():
    prompt = prompts.build_scene_solo_prompt("/run_test/workspace")
    assert not re.findall(
        r"\b(?:render_preview|preflight_design|validate_creative_direction)\(\)", prompt
    )
    flat = " ".join(prompt.split())
    assert "critique_json" not in flat
    assert "finalize_run uses the review registered from critique.json." in flat


# --- apply_structured_edit on the real engine -----------------------------------------------------

AD = """page ad size(1080,1080,px)
  card al(v, x(s), g(16), pad(24)) p(40,40) s(600,hug) fill(#ffffff)
    headline text "Old headline" s(552,hug) font("Inter",48,700,left)
    support text "Support line" s(552,hug) font("Inter",24,400,left)
  badge r p(800,800) s(120,120) fill(#ff0000) rd(8)
  dot e p(900,100) s(40,40) fill(#00ff00)
"""


_HELPER = Path(substrate.__file__).resolve().parents[4] / "target/release/lumen-api-helper"


@pytest.fixture
def edit_tool(tmp_path, monkeypatch):
    if not _HELPER.is_file():
        pytest.skip("needs the release helper: cargo build --release -p lumen-api-helper")
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "lumen_core_helper", str(_HELPER))
    tools = substrate.LumenDesignTools(runtime_config(tmp_path), "Edit the ad.")
    compiled = json.loads(tools.compile_dsl_block(AD))
    assert compiled["compile"]["status"] == "ok", compiled
    return tools, harness._make_structured_edit_tool(tools)


def _edit(tool, **arguments):
    return json.loads(tool.invoke(arguments))["structured_edit"]


def test_the_edit_tool_takes_objects_and_the_engine_applies_them(edit_tool):
    tools, tool = edit_tool
    node = {"kind": "node", "id": "headline"}
    result = _edit(tool, edit={
        "kind": "modify", "target": node,
        "patch": {"kind": "node", "value": {"text": {
            "content": {"kind": "set", "value": "New headline"},
            "font_size": {"kind": "set", "value": 56},
        }}},
    })
    assert result["status"] == "ok", result
    assert tools.scene["nodes"]["headline"]["kind"]["content"] == "New headline"
    assert tools.scene["nodes"]["headline"]["kind"]["font_size"] == 56
    # clone and replace without the optional policies: the harness sends the DSL's own defaults.
    result = _edit(tool, edit={"kind": "clone_subtree", "request": {
        "source": "support", "new_root_id": "support_2",
        "placement": {"kind": "after", "anchor": "support"},
    }})
    assert result["status"] == "ok", result
    assert "support_2" in tools.scene["nodes"]
    card = tools.scene["nodes"]["card"]["children"]
    assert card.index("support_2") == card.index("support") + 1
    result = _edit(tool, edit={"kind": "replace_node", "request": {
        "target": "dot", "replacement": "badge",
    }})
    assert result["status"] == "ok", result
    assert "dot" not in tools.scene["nodes"]
    result = _edit(tool, edit={"kind": "group", "node_ids": ["badge"], "group_id": "marks"})
    assert result["status"] == "ok", result
    result = _edit(tool, edit={"kind": "ungroup", "node_id": "marks"})
    assert result["status"] == "ok", result
    assert "marks" not in tools.scene["nodes"]


def test_a_strict_scope_refuses_an_edit_outside_it_and_changes_nothing(edit_tool):
    tools, tool = edit_tool
    before = json.dumps(tools.scene, sort_keys=True)
    result = _edit(
        tool,
        edit={"kind": "modify", "target": {"kind": "node", "id": "support"},
              "patch": {"kind": "node", "value": {"text": {"content": {"kind": "set",
                                                                        "value": "Out of scope"}}}}},
        scope={"mode": "strict", "allowed": [{"kind": "node", "id": "headline"}]},
    )
    assert result["status"] == "error"
    assert result["operation_error"]["code"] == "edit.scope_violation"
    assert json.dumps(tools.scene, sort_keys=True) == before


def test_a_left_out_kind_or_a_partial_position_comes_back_as_a_readable_error(edit_tool):
    tools, tool = edit_tool
    with pytest.raises(Exception):  # not one of the nine shapes the agent is offered
        tool.invoke({"edit": {"kind": "freeze_layout"}})
    result = _edit(tool, edit={
        "kind": "modify", "target": {"kind": "node", "id": "badge"},
        "patch": {"kind": "node", "value": {"transform": {"kind": "set", "value": {"x": 1, "y": 2}}}},
    })
    assert result["status"] == "error"
    assert "rotation" in result["operation_error"]["message"]
