"""Current C6 replay/authority audit over the complete 39-tool registry."""

from __future__ import annotations

from pathlib import Path

from clue_agents import AgentRole
from clue_api.agent_registry_wiring import C6_AGENT_TOOL_AUTHORITY, c6_roles_for_tool
from clue_api.coverage_tools import coverage_evaluator_owner
from clue_api.toolbelt_wiring import build_toolbelt
from clue_toolbelt import ReplayPolicy, ToolEffectClass

_HUMAN_ONLY_STEERING = {
    "adjust_budget",
    "confirm_project_product",
    "override_stage0_readiness",
    "pause_run",
    "resume_run",
    "submit_project_checkpoint",
    "submit_tier_checkpoint",
}

_REPLAY_BLOCKED = {
    "decide_field_proposal@1",
    "decide_source_proposal@1",
    "research_account_gaps@1",
    "retry_ingestion@1",
}
_C65_CERTIFIED = {
    "propose_field": ReplayPolicy.DOMAIN_IDEMPOTENT,
    "propose_source": ReplayPolicy.DOMAIN_IDEMPOTENT,
    "submit_ingestion": ReplayPolicy.AT_LEAST_ONCE,
}


def test_every_current_tool_has_an_explicit_c6_authority_decision() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    assert set(C6_AGENT_TOOL_AUTHORITY) == set(registry.names())
    # 35 → 37 with PC-C8's inspection tools, then 38/39 with the E1 and S1 explicit provider-spend
    # boundaries. Every addition must have a reviewed role decision here.
    assert len(C6_AGENT_TOOL_AUTHORITY) == 41
    assert C6_AGENT_TOOL_AUTHORITY["inspect_statement_history"] == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["inspect_readiness_history"] == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["draft_account_research_directive"] == (AgentRole.HEAD_OF_ABM,)
    assert C6_AGENT_TOOL_AUTHORITY["confirm_account_research_directive"] == ()

    for descriptor in registry.all_descriptors():
        roles = c6_roles_for_tool(descriptor.address)
        if roles:
            assert descriptor.recipe_safe, f"{descriptor.address} cannot enter an agent plan"
            assert descriptor.replay.policy is not ReplayPolicy.UNCERTIFIED
            assert descriptor.effect_class is not ToolEffectClass.STEERING


def test_human_steering_and_replay_blocked_tools_are_structurally_absent() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    descriptors = {item.address: item for item in registry.all_descriptors()}

    assert all(not C6_AGENT_TOOL_AUTHORITY[name] for name in _HUMAN_ONLY_STEERING)
    assert all(
        descriptors[f"{name}@1"].effect_class is ToolEffectClass.STEERING
        for name in _HUMAN_ONLY_STEERING
    )

    assert all(not c6_roles_for_tool(address) for address in _REPLAY_BLOCKED)
    assert all(
        descriptors[address].replay.policy is ReplayPolicy.UNCERTIFIED
        for address in _REPLAY_BLOCKED
    )
    assert c6_roles_for_tool("research_account_gaps@2")
    assert descriptors["research_account_gaps@2"].recipe_safe


def test_c65_proposal_and_ingestion_certifications_are_live_and_admitted() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    descriptors = {item.name: item for item in registry.descriptors()}

    for name, replay_policy in _C65_CERTIFIED.items():
        assert C6_AGENT_TOOL_AUTHORITY[name]
        assert descriptors[name].replay.policy is replay_policy
        assert descriptors[name].recipe_safe

    assert c6_roles_for_tool("propose_field@1") == ()
    assert c6_roles_for_tool("propose_field@2") == (AgentRole.HEAD_OF_ABM,)


def test_c1_goal_judge_has_one_explicit_production_construction_owner() -> None:
    assert coverage_evaluator_owner() == "c1.engine.goal_judge"

    root = Path(__file__).resolve().parents[2]
    constructions = [
        path.relative_to(root)
        for source_root in ("platform", "subsystems")
        for path in (root / source_root).rglob("*.py")
        if "GoalJudge(" in path.read_text(encoding="utf-8")
    ]

    assert constructions == [Path("platform/api/clue_api/coverage_tools.py")]
