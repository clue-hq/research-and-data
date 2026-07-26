"""C6.2 composition of reviewed folder profiles against the live tool registry."""

from __future__ import annotations

from pathlib import Path

from clue_agents import AgentRole, ToolPin
from clue_agents.catalog import (
    AgentCatalogError,
    FolderProfileCatalog,
    FolderPromptCatalog,
    FolderSkillCatalog,
)
from clue_agents.registry import (
    AgentProfileRegistry,
    AgentToolCatalog,
    AgentToolContract,
)
from clue_toolbelt import ToolEffectClass, ToolRegistry, UnknownTool

__all__ = [
    "C6_AGENT_TOOL_AUTHORITY",
    "ToolRegistryAgentCatalog",
    "build_agent_profile_registry",
]


# Binding C6.0 32-tool admission audit. Empty means structurally absent from every initial model
# surface. Account-research remains a planned C6.7 role; its reviewed authority is recorded now but
# no active profile is created early.
C6_AGENT_TOOL_AUTHORITY: dict[str, tuple[AgentRole, ...]] = {
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


class ToolRegistryAgentCatalog(AgentToolCatalog):
    """Translate the live toolbelt descriptor into C6's provider-neutral exact contract."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def resolve(self, pin: ToolPin) -> AgentToolContract:
        try:
            descriptor = self._registry.descriptor(pin.name, pin.version)
        except UnknownTool as exc:
            raise AgentCatalogError(f"tool {pin.address!r} is unavailable") from exc
        actual = ToolPin(
            name=descriptor.name,
            version=descriptor.version,
            input_schema_sha256=descriptor.input_schema_sha256,
            output_schema_sha256=descriptor.output_schema_sha256,
        )
        return AgentToolContract(
            pin=actual,
            recipe_safe=descriptor.recipe_safe,
            steering=descriptor.effect_class is ToolEffectClass.STEERING,
        )


def build_agent_profile_registry(
    tool_registry: ToolRegistry,
    *,
    catalog_root: Path | None = None,
) -> AgentProfileRegistry:
    """Fail-fast composition of all active role resources and exact tool authority."""

    if set(tool_registry.names()) != set(C6_AGENT_TOOL_AUTHORITY):
        missing = sorted(set(C6_AGENT_TOOL_AUTHORITY) - set(tool_registry.names()))
        extra = sorted(set(tool_registry.names()) - set(C6_AGENT_TOOL_AUTHORITY))
        raise AgentCatalogError(
            f"live tool registry differs from the C6 authority audit; missing={missing}, "
            f"extra={extra}"
        )
    admitted_addresses: set[str] = set()
    for name, roles in C6_AGENT_TOOL_AUTHORITY.items():
        descriptor = tool_registry.descriptor(name)
        if roles:
            if not descriptor.recipe_safe:
                raise AgentCatalogError(
                    f"admitted tool {descriptor.address!r} is no longer replay-safe"
                )
            if descriptor.effect_class is ToolEffectClass.STEERING:
                raise AgentCatalogError(
                    f"admitted tool {descriptor.address!r} became human steering"
                )
            admitted_addresses.add(descriptor.address)

    root = catalog_root or Path(__file__).resolve().parents[2] / "agents" / "catalog"
    resolved = AgentProfileRegistry(
        prompts=FolderPromptCatalog((root / "prompts").resolve(strict=True)),
        skills=FolderSkillCatalog((root / "skills").resolve(strict=True)),
        profiles=FolderProfileCatalog((root / "profiles").resolve(strict=True)),
        tools=ToolRegistryAgentCatalog(tool_registry),
        engine_tool_ceiling=frozenset(admitted_addresses),
    )
    for role in (
        AgentRole.HEAD_OF_ABM,
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    ):
        expected = {
            f"{name}@{tool_registry.descriptor(name).version}"
            for name, roles in C6_AGENT_TOOL_AUTHORITY.items()
            if role in roles
        }
        actual = {pin.address for pin in resolved.resolve(role).profile.tools}
        if actual != expected:
            raise AgentCatalogError(
                f"profile {role.value!r} differs from reviewed authority; "
                f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )
    return resolved
