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
    "C6_ACTIVE_PROFILE_VERSIONS",
    "C6_AGENT_TOOL_AUTHORITY",
    "c6_roles_for_tool",
    "ToolRegistryAgentCatalog",
    "build_agent_profile_registry",
]

C6_ACTIVE_PROFILE_VERSIONS: dict[AgentRole, str] = {
    AgentRole.HEAD_OF_ABM: "v7",
    AgentRole.RESEARCH: "v4",
    AgentRole.CONTENT_DRAFTER: "v4",
    AgentRole.REVIEWER: "v4",
    AgentRole.ACCOUNT_RESEARCH: "v3",
}


# C6.7 live authority. Empty means structurally absent from every current model surface.
C6_AGENT_TOOL_AUTHORITY: dict[str, tuple[AgentRole, ...]] = {
    "adjust_budget": (),
    "compose_handoff": (
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    ),
    "compose_dossier": (),
    "confirm_icp": (),
    "confirm_project_product": (),
    "decide_field_proposal": (),
    "decide_source_proposal": (),
    "discover_accounts": (),
    "estimate_project": (),
    "evaluate_stage0_readiness": (AgentRole.HEAD_OF_ABM,),
    "get_research_view": (
        AgentRole.HEAD_OF_ABM,
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
        AgentRole.ACCOUNT_RESEARCH,
    ),
    "import_accounts": (),
    "override_stage0_readiness": (),
    "pause_run": (),
    "profile_contact": (AgentRole.RESEARCH,),
    "propose_field": (AgentRole.HEAD_OF_ABM,),
    "propose_source": (AgentRole.HEAD_OF_ABM,),
    "record_interview_answer": (AgentRole.HEAD_OF_ABM,),
    "recheck_research_view": (),
    "research_account_gaps": (AgentRole.ACCOUNT_RESEARCH,),
    "resolve_committee": (AgentRole.RESEARCH,),
    "resume_run": (),
    "retry_ingestion": (),
    "reverse_profile": (),
    "run_deep_account": (AgentRole.RESEARCH,),
    "run_verification": (AgentRole.RESEARCH,),
    "score_accounts": (),
    "start_confirmed_project_run": (AgentRole.HEAD_OF_ABM,),
    "start_project_run": (),
    "start_recon": (AgentRole.HEAD_OF_ABM,),
    "submit_ingestion": (AgentRole.HEAD_OF_ABM,),
    "submit_onboarding_input": (AgentRole.HEAD_OF_ABM,),
    "submit_project_checkpoint": (),
    "submit_tier_checkpoint": (),
    "synthesize_icps": (AgentRole.HEAD_OF_ABM,),
}

_HUMAN_ONLY_TOOLS = frozenset(
    {
        "adjust_budget",
        "confirm_icp",
        "confirm_project_product",
        "decide_field_proposal",
        "decide_source_proposal",
        "override_stage0_readiness",
        "pause_run",
        "resume_run",
        "submit_project_checkpoint",
        "submit_tier_checkpoint",
    }
)
_RESERVED_REASON: dict[str, str] = {
    "discover_accounts": "post_stage0_not_admitted",
    "estimate_project": "post_stage0_not_admitted",
    "import_accounts": "post_stage0_not_admitted",
    "retry_ingestion": "replay_not_certified",
    "reverse_profile": "superseded_by_governed_stage0_recon",
    "score_accounts": "post_stage0_not_admitted",
    "start_project_run": "legacy_unconfirmed_entry_forbidden",
}


def _roles_for(address: str, name: str) -> tuple[AgentRole, ...]:
    """Resolve authority by exact address where versions have different safety proofs."""

    if name == "research_account_gaps":
        return (AgentRole.ACCOUNT_RESEARCH,) if address == "research_account_gaps@2" else ()
    return C6_AGENT_TOOL_AUTHORITY.get(name, ())


def c6_roles_for_tool(address: str) -> tuple[AgentRole, ...]:
    name, separator, _version = address.partition("@")
    if not separator:
        raise ValueError("C6 tool authority requires an exact name@version address")
    return _roles_for(address, name)


def _unavailable_reason(address: str, name: str) -> str | None:
    if address == "research_account_gaps@1":
        return "replaced_by_replay_safe_v2"
    return _RESERVED_REASON.get(name)


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
            effect_class=descriptor.effect_class.value,
            admitted_roles=_roles_for(descriptor.address, descriptor.name),
            unavailable_reason_code=(
                "human_authority"
                if descriptor.name in _HUMAN_ONLY_TOOLS
                else _unavailable_reason(descriptor.address, descriptor.name)
            ),
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
    for descriptor in tool_registry.all_descriptors():
        roles = _roles_for(descriptor.address, descriptor.name)
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
        selected_profile_versions=C6_ACTIVE_PROFILE_VERSIONS,
        tool_inventory=tuple(
            ToolRegistryAgentCatalog(tool_registry).resolve(
                ToolPin(
                    name=descriptor.name,
                    version=descriptor.version,
                    input_schema_sha256=descriptor.input_schema_sha256,
                    output_schema_sha256=descriptor.output_schema_sha256,
                )
            )
            for descriptor in tool_registry.all_descriptors()
        ),
    )
    for role in (
        AgentRole.HEAD_OF_ABM,
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
        AgentRole.ACCOUNT_RESEARCH,
    ):
        expected = {
            descriptor.address
            for descriptor in tool_registry.all_descriptors()
            if role in _roles_for(descriptor.address, descriptor.name)
        }
        actual = {pin.address for pin in resolved.resolve(role).profile.tools}
        if actual != expected:
            raise AgentCatalogError(
                f"profile {role.value!r} differs from reviewed authority; "
                f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )
    return resolved
