"""C6.0 replay/authority audit over the complete 32-tool C4 registry."""

from __future__ import annotations

from clue_agents import AgentRole
from clue_api.toolbelt_wiring import build_toolbelt
from clue_toolbelt import ReplayPolicy, ToolEffectClass

# This is an audit fixture, not production routing.  C6.2 materializes reviewed profile allowlists
# from folder resources; C6.4 constructs only the admitted tool adapters.
C6_INITIAL_AGENT_AUTHORITY: dict[str, tuple[AgentRole, ...]] = {
    "adjust_budget": (),
    "compose_handoff": (
        AgentRole.HEAD_OF_ABM,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    ),
    "confirm_icp": (),
    "confirm_project_product": (),
    "decide_field_proposal": (),
    "decide_source_proposal": (),
    "discover_accounts": (AgentRole.HEAD_OF_ABM,),
    "estimate_project": (AgentRole.HEAD_OF_ABM,),
    "evaluate_stage0_readiness": (AgentRole.HEAD_OF_ABM,),
    "import_accounts": (AgentRole.HEAD_OF_ABM,),
    "override_stage0_readiness": (),
    "pause_run": (),
    "profile_contact": (AgentRole.RESEARCH, AgentRole.ACCOUNT_RESEARCH),
    "propose_field": (),
    "propose_source": (),
    "record_interview_answer": (AgentRole.HEAD_OF_ABM,),
    "research_account_gaps": (),
    "resolve_committee": (AgentRole.RESEARCH, AgentRole.ACCOUNT_RESEARCH),
    "resume_run": (),
    "retry_ingestion": (),
    "reverse_profile": (AgentRole.HEAD_OF_ABM,),
    "run_deep_account": (AgentRole.RESEARCH, AgentRole.ACCOUNT_RESEARCH),
    "run_verification": (AgentRole.RESEARCH, AgentRole.ACCOUNT_RESEARCH),
    "score_accounts": (AgentRole.HEAD_OF_ABM,),
    "start_confirmed_project_run": (AgentRole.HEAD_OF_ABM,),
    "start_project_run": (),
    "start_recon": (AgentRole.HEAD_OF_ABM,),
    "submit_ingestion": (),
    "submit_onboarding_input": (AgentRole.HEAD_OF_ABM,),
    "submit_project_checkpoint": (),
    "submit_tier_checkpoint": (),
    "synthesize_icps": (AgentRole.HEAD_OF_ABM,),
}

_HUMAN_ONLY_STEERING = {
    "adjust_budget",
    "confirm_project_product",
    "override_stage0_readiness",
    "pause_run",
    "resume_run",
    "submit_project_checkpoint",
    "submit_tier_checkpoint",
}

_UNCERTIFIED = {
    "decide_field_proposal",
    "decide_source_proposal",
    "propose_field",
    "propose_source",
    "research_account_gaps",
    "retry_ingestion",
    "submit_ingestion",
}


def test_every_current_tool_has_an_explicit_c6_authority_decision() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    assert set(C6_INITIAL_AGENT_AUTHORITY) == set(registry.names())
    assert len(C6_INITIAL_AGENT_AUTHORITY) == 32

    for descriptor in registry.all_descriptors():
        roles = C6_INITIAL_AGENT_AUTHORITY[descriptor.name]
        if roles:
            assert descriptor.recipe_safe, f"{descriptor.address} cannot enter an agent plan"
            assert descriptor.replay.policy is not ReplayPolicy.UNCERTIFIED
            assert descriptor.effect_class is not ToolEffectClass.STEERING


def test_human_steering_and_uncertified_tools_are_structurally_absent() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    descriptors = {item.name: item for item in registry.all_descriptors()}

    assert all(not C6_INITIAL_AGENT_AUTHORITY[name] for name in _HUMAN_ONLY_STEERING)
    assert all(
        descriptors[name].effect_class is ToolEffectClass.STEERING for name in _HUMAN_ONLY_STEERING
    )

    assert all(not C6_INITIAL_AGENT_AUTHORITY[name] for name in _UNCERTIFIED)
    assert all(descriptors[name].replay.policy is ReplayPolicy.UNCERTIFIED for name in _UNCERTIFIED)
