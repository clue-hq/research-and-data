"""Current C6 replay/authority audit over the complete 32-tool C4 registry."""

from __future__ import annotations

from clue_api.agent_registry_wiring import C6_AGENT_TOOL_AUTHORITY
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
    "decide_field_proposal",
    "decide_source_proposal",
    "research_account_gaps",
    "retry_ingestion",
}
_C65_CERTIFIED = {
    "propose_field": ReplayPolicy.DOMAIN_IDEMPOTENT,
    "propose_source": ReplayPolicy.DOMAIN_IDEMPOTENT,
    "submit_ingestion": ReplayPolicy.AT_LEAST_ONCE,
}


def test_every_current_tool_has_an_explicit_c6_authority_decision() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    assert set(C6_AGENT_TOOL_AUTHORITY) == set(registry.names())
    assert len(C6_AGENT_TOOL_AUTHORITY) == 32

    for descriptor in registry.all_descriptors():
        roles = C6_AGENT_TOOL_AUTHORITY[descriptor.name]
        if roles:
            assert descriptor.recipe_safe, f"{descriptor.address} cannot enter an agent plan"
            assert descriptor.replay.policy is not ReplayPolicy.UNCERTIFIED
            assert descriptor.effect_class is not ToolEffectClass.STEERING


def test_human_steering_and_replay_blocked_tools_are_structurally_absent() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    descriptors = {item.name: item for item in registry.all_descriptors()}

    assert all(not C6_AGENT_TOOL_AUTHORITY[name] for name in _HUMAN_ONLY_STEERING)
    assert all(
        descriptors[name].effect_class is ToolEffectClass.STEERING for name in _HUMAN_ONLY_STEERING
    )

    assert all(not C6_AGENT_TOOL_AUTHORITY[name] for name in _REPLAY_BLOCKED)
    assert all(
        descriptors[name].replay.policy is ReplayPolicy.UNCERTIFIED for name in _REPLAY_BLOCKED
    )


def test_c65_proposal_and_ingestion_certifications_are_live_and_admitted() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    descriptors = {item.name: item for item in registry.all_descriptors()}

    for name, replay_policy in _C65_CERTIFIED.items():
        assert C6_AGENT_TOOL_AUTHORITY[name]
        assert descriptors[name].replay.policy is replay_policy
        assert descriptors[name].recipe_safe
