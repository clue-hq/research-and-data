"""M8B O3 scripted conversation contract over the promoted Head/research resources."""

from __future__ import annotations

from pathlib import Path

import yaml

from clue_agents import AgentRole
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.toolbelt_wiring import build_toolbelt
from tests.api.conftest import hermetic_flag_env

_SCENARIOS = (
    Path(__file__).parents[1] / "fixtures" / "agents" / "o3_account_deep_conversations.yaml"
)


def test_scripted_o3_conversations_cover_the_non_linear_gate() -> None:
    payload = yaml.safe_load(_SCENARIOS.read_text())
    scenarios = payload["scenarios"]
    assert {item["name"] for item in scenarios} == {
        "show_accounts_only",
        "discover_more",
        "five_accounts_with_fax_referral_direction",
        "remove_phone_reveals",
        "edit_before_confirm",
        "edit_after_launch",
        "explicit_launch",
    }

    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    head = registry.resolve(AgentRole.HEAD_OF_ABM)
    skill = head.open_skill("skill:account-deep-steering@v1")

    for scenario in scenarios:
        assert scenario["user_turns"]
        assert scenario["required_guidance"] in skill
        actions = scenario["scripted_actions"]
        has_launch = "launch_account_deep" in actions
        assert has_launch is scenario["explicit_launch_go_ahead"]
        if not scenario["explicit_launch_go_ahead"]:
            assert "launch_account_deep" not in actions

    discovery_completion_actions = next(
        item["scripted_actions"] for item in scenarios if item["name"] == "show_accounts_only"
    )
    assert "draft_directive" not in discovery_completion_actions
    assert "launch_account_deep" not in discovery_completion_actions
    assert (
        "launched/enqueued or replayed"
        in build_toolbelt(storage=None, gateway=None)
        .descriptor("launch_account_deep")
        .model_description
    )
    assert (
        "never means"
        in build_toolbelt(storage=None, gateway=None)
        .descriptor("launch_account_deep")
        .model_description
    )


def test_research_specialist_separates_plan_review_from_admitted_execution() -> None:
    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    specialist = registry.resolve(AgentRole.RESEARCH)
    body = specialist.open_skill("skill:research-task@v3")

    assert "pre-launch plan review" in body
    assert "Invoke no spending tool" in body
    assert "standard registered fields" in body
    assert "directional questions/hypotheses" in body
    assert "is never\ncompleted research" in body
