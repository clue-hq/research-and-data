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
    skill = head.open_skill("skill:account-deep-steering@v3")

    for scenario in scenarios:
        assert scenario["user_turns"]
        assert scenario["required_guidance"] in skill
        actions = scenario["scripted_actions"]
        has_launch = "launch_account_research" in actions
        assert has_launch is scenario["explicit_launch_go_ahead"]
        if not scenario["explicit_launch_go_ahead"]:
            assert "launch_account_research" not in actions

    discovery_completion_actions = next(
        item["scripted_actions"] for item in scenarios if item["name"] == "show_accounts_only"
    )
    assert "draft_directive" not in discovery_completion_actions
    assert "launch_account_research" not in discovery_completion_actions

    # The steering skill — not the launch tool's registered description — carries the
    # human-approval gate and the "a receipt is not completed research" reading rule, so the
    # contract is pinned where it actually lives.
    assert (
        "Call `launch_account_research@1` only after the current user action explicitly approves "
        "the exact\nconfirmed directive, account set, estimate, and cap." in skill
    )
    assert "A queue receipt or provider wait is not completed research." in skill
    assert (
        "Never translate a successful tool call, launch receipt, replay, or model\n"
        "stop into successful research." in skill
    )

    # The registered launch tool is the exact governed spend-class contract that gate steers, and
    # its durable identity is the approved directive/selection/budget triple — so a replay is the
    # same launch, never a second one.
    descriptor = build_toolbelt(storage=None, gateway=None).descriptor("launch_account_research")
    assert "only after the current user action explicitly approves" in descriptor.model_description
    assert (
        "it never means account or committee research has completed" in descriptor.model_description
    )
    assert "never authorizes contact research" in descriptor.model_description
    assert descriptor.effect_class.value == "spend"
    assert descriptor.replay.policy.value == "domain_idempotent"
    assert (
        descriptor.replay.durable_identity
        == "confirmed directive + exact account selection + approved budget"
    )
    assert descriptor.pin_requirements == (
        "project_run",
        "research_directive",
        "account_research_selection",
    )


def test_research_specialist_separates_plan_review_from_admitted_execution() -> None:
    with hermetic_flag_env():
        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    specialist = registry.resolve(AgentRole.RESEARCH)
    body = specialist.open_skill("skill:research-task@v4")

    assert "For a pre-launch review, analyze only." in body
    assert "Do not imitate, launch, or replace those units." in body
    assert (
        "Inventory exact entities, fields, directional\nquestions, evidence gaps, source plans"
        in body
    )
    assert (
        "A provider receipt, fleet return, or partial claim set is not verified merely because it\n"
        "exists." in body
    )
    assert (
        "Never claim completion for an account/contact job whose\n"
        "accepted finalization receipt is absent." in body
    )
