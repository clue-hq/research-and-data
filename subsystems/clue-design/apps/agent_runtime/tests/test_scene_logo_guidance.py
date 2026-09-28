"""Logo selection policy must reach actual prompts, bound tools and responses.

Scripted models and fixture site bytes test instruction delivery, not taste.
"""

import json
from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from lumen_agent import harness
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.workspace import initial_turn_state
from test_fetch_logo_tool import GOODMAN_ASSETS, GOODMAN_HTML, _fake_site
from test_fetch_logo_tool import _vendor_rung_disabled as _vendor_rung_disabled
from test_scene_catalog_runtime import call
from test_scene_solo_runtime import offline_models, solo_config

LEGACY_NEXT = (
    "Place one with asset(action='place', asset_id=..., node_id=... or "
    "slot_id=...). Match the cell to the placement: *_lockup is the full "
    "logo (first choice on any surface that fits it), *_mark is the bare "
    "symbol (small placements only). Use dark_* cells on dark surfaces, "
    "light_* on light ones. `alternatives` are other real assets found "
    "for this company, also registered: use a cell first; pick an "
    "alternative only when the cell does not fit the placement, and say so."
)


def delivered(tmp_path, monkeypatch, *, solo, bundle="candidate"):
    built, _ = offline_models(monkeypatch)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda _: None,
    )
    config = replace(solo_config(tmp_path), scene_solo=solo, scene_skill_bundle=bundle)
    graph, tools = harness.create_design_deepagent("Make an account ad", config)
    director = next(model for _, role, model in built if role == "design_orchestrator")
    if not solo:
        director.responses = [
            call(
                "task",
                {"subagent_type": "lumen-dsl-author", "description": "Inspect logo options."},
                "author",
            ),
            AIMessage(content="Inspected the options."),
        ]
    graph.invoke(initial_turn_state(tools, "Make an account ad"))
    active = director if solo else next(
        model for _, role, model in built if role == "design_author"
    )
    bound = next(t for t in active.first_bound_tools if t.name == "fetch_logo")
    return tools, bound, [m.seen[0][0].text for m in (director, active)]


def assert_target_anchor_option(text):
    words = " ".join(text.split())
    assert "small placements only" not in words
    assert "logo must be its COMPLETE lockup" not in words
    assert "primary target anchor" in words
    assert "even when a complete lockup exists" in words
    assert "explicitly required wordmark" in words


@pytest.mark.parametrize("solo", [True, False])
@pytest.mark.parametrize("surface", ["prompts", "bound_tool"])
def test_candidate_target_anchor_policy_reaches_each_active_role(
    tmp_path, monkeypatch, solo, surface,
):
    """Catch legacy small-mark restrictions surviving candidate instruction selection."""
    tools, bound, prompts = delivered(tmp_path, monkeypatch, solo=solo)
    schema = convert_to_openai_tool(bound)["function"]
    original = convert_to_openai_tool(tools.fetch_logo)["function"]
    assert schema["name"] == original["name"] == "fetch_logo"
    assert schema["parameters"] == original["parameters"]
    if surface == "prompts":
        for prompt in prompts:
            assert_target_anchor_option(prompt)
    else:
        assert_target_anchor_option(schema["description"])


def test_legacy_bound_logo_description_and_prompts_keep_original_policy(tmp_path, monkeypatch):
    _, bound, prompts = delivered(tmp_path, monkeypatch, solo=False, bundle="legacy")
    for prompt in prompts:
        assert "small placements only" in " ".join(prompt.split())
        assert "primary target anchor" not in prompt
    assert bound.description == LumenDesignTools.fetch_logo.__doc__.strip()
    assert "logo must be its COMPLETE lockup" in " ".join(bound.description.split())


@pytest.mark.parametrize("bundle", ["candidate", "legacy"])
def test_bound_logo_result_delivers_selected_policy_after_real_source_resolution(
    tmp_path, monkeypatch, bundle,
):
    tools, bound, _ = delivered(tmp_path, monkeypatch, solo=bundle == "candidate", bundle=bundle)
    _fake_site(monkeypatch, GOODMAN_HTML, GOODMAN_ASSETS, "goodmancampbell.com")
    tools.compile_dsl_block("page page_test size(1080,1080,px)")
    result = json.loads(bound.invoke({"domain": "goodmancampbell.com"}))
    assert {"light_lockup", "dark_lockup"} <= {row["cell"] for row in result["logos"]}
    assert result["identity"]
    if bundle == "candidate":
        assert_target_anchor_option(result["next"])
    else:
        assert result["next"] == LEGACY_NEXT
