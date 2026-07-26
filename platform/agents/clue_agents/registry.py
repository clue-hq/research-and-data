"""Resolved role profiles, effective authority, and progressive skill disclosure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_agents.catalog import (
    AgentCatalogError,
    ProfileCatalog,
    ProfileResource,
    ProfileStatus,
    PromptCatalog,
    SkillCatalog,
    SkillResource,
)
from clue_agents.contracts import (
    AgentProfile,
    AgentResourceManifest,
    AgentResourceRef,
    AgentRole,
    SkillBundle,
    ToolPin,
    WorkspacePolicy,
)
from clue_agents.resources import (
    AgentResourceSnapshot,
    ResourceBody,
    build_agent_resource_manifest,
)

__all__ = [
    "AgentCapabilityStatus",
    "AgentProfileRegistry",
    "AgentRegistryProjection",
    "AgentToolCatalog",
    "AgentToolContract",
    "ProfileProjection",
    "ResolvedAgentProfile",
    "RoleRegistryEntry",
    "RoleRegistryStatus",
    "SkillDisclosure",
    "ToolCapabilityDisclosure",
]

_REQUIRED_ACTIVE_ROLES = frozenset(
    {
        AgentRole.HEAD_OF_ABM,
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
    }
)


@dataclass(frozen=True, slots=True)
class AgentToolContract:
    pin: ToolPin
    recipe_safe: bool
    steering: bool
    available: bool = True
    effect_class: str = "unknown"
    admitted_roles: tuple[AgentRole, ...] = ()
    unavailable_reason_code: str | None = None


@runtime_checkable
class AgentToolCatalog(Protocol):
    """Resolve the live contract for an exact profile-pinned tool address."""

    def resolve(self, pin: ToolPin) -> AgentToolContract: ...


class ProjectionValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RoleRegistryStatus(StrEnum):
    ACTIVE = "active"
    PLANNED = "planned"


class AgentCapabilityStatus(StrEnum):
    AVAILABLE = "available"
    HUMAN_ONLY = "human_only"
    REPLAY_BLOCKED = "replay_blocked"
    ROLE_UNAVAILABLE = "role_unavailable"
    PROFILE_UNAVAILABLE = "profile_unavailable"
    RETIRED_OR_MISSING = "retired_or_missing"


class ToolCapabilityDisclosure(ProjectionValue):
    address: str
    effect_class: str
    status: AgentCapabilityStatus
    reason_code: str


class SkillDisclosure(ProjectionValue):
    resource: AgentResourceRef
    summary: str
    materialized_path: str
    required_tool_addresses: tuple[str, ...]
    readiness_requirements: tuple[str, ...]


class ProfileProjection(ProjectionValue):
    role: AgentRole
    status: RoleRegistryStatus
    profile_ref: AgentResourceRef
    prompt_ref: AgentResourceRef
    resource_manifest_sha256: str
    memory_policy: str
    model_id: str
    tool_addresses: tuple[str, ...]
    skills: tuple[SkillDisclosure, ...]
    delegation_roles: tuple[AgentRole, ...]
    delegation_tool_addresses: dict[AgentRole, tuple[str, ...]]
    workspace: WorkspacePolicy
    capabilities: tuple[ToolCapabilityDisclosure, ...]


class RoleRegistryEntry(ProjectionValue):
    role: AgentRole
    status: RoleRegistryStatus
    profile: ProfileProjection | None = None


class AgentRegistryProjection(ProjectionValue):
    schema_version: str
    roles: tuple[RoleRegistryEntry, ...]


@dataclass(frozen=True, slots=True)
class ResolvedAgentProfile:
    profile: AgentProfile
    profile_ref: AgentResourceRef
    prompt_body: str
    resource_manifest: AgentResourceManifest
    resource_snapshot: AgentResourceSnapshot
    memory_policy: str
    skills: tuple[SkillResource, ...]
    delegation_tool_grants: Mapping[AgentRole, tuple[ToolPin, ...]]
    capabilities: tuple[ToolCapabilityDisclosure, ...] = ()

    @property
    def resource_map(self) -> tuple[AgentResourceRef, ...]:
        return (
            self.profile_ref,
            self.profile.prompt,
            *(bundle.resource for bundle in self.profile.skills),
        )

    def skill_disclosures(self) -> tuple[SkillDisclosure, ...]:
        resources = {item.ref.address: item for item in self.skills}
        return tuple(
            SkillDisclosure(
                resource=bundle.resource,
                summary=bundle.summary,
                materialized_path=bundle.materialized_path,
                required_tool_addresses=tuple(tool.address for tool in bundle.required_tools),
                readiness_requirements=resources[bundle.resource.address].readiness_requirements,
            )
            for bundle in self.profile.skills
        )

    def open_skill(self, address: str) -> str:
        """Return a skill body only after its disclosed exact address is selected."""

        for skill in self.skills:
            if skill.ref.address == address:
                return skill.body
        raise AgentCatalogError(f"skill {address!r} is not disclosed by this profile")

    @property
    def generated_resource_map(self) -> str:
        """Render the exhaustive, host-free map from resolved facts only."""

        manifest = self.resource_manifest
        resources = "\n".join(
            f"- {item.address} sha256={item.sha256}"
            for item in (manifest.profile, manifest.prompt, *manifest.skills)
        )
        skills = "\n".join(
            f"- {item.resource.address}: {item.summary}; open={item.materialized_path}"
            for item in self.skill_disclosures()
        )
        available = "\n".join(
            f"- {item.address} effect={item.effect_class}"
            for item in self.capabilities
            if item.status is AgentCapabilityStatus.AVAILABLE
        )
        unavailable = "\n".join(
            f"- {item.address} status={item.status.value} reason={item.reason_code}"
            for item in self.capabilities
            if item.status is not AgentCapabilityStatus.AVAILABLE
        )
        workspace = self.profile.workspace
        delegations = "\n".join(
            f"- {role.value}: "
            + ", ".join(pin.address for pin in self.delegation_tool_grants.get(role, ()))
            for role in self.profile.delegation_roles
        )
        delegation_capability = (
            "- delegate_specialist: available; validated C5 delegation and fresh child wake"
            if self.profile.delegation_roles
            else "- delegate_specialist: unavailable in this profile"
        )
        return (
            "## Resolved resource and capability map (authoritative; generated)\n\n"
            "Pinned resources:\n"
            f"{resources or '- none'}\n\n"
            "Progressively disclosed skills:\n"
            f"{skills or '- none'}\n\n"
            "Governed platform tools available to this role:\n"
            f"{available or '- none'}\n\n"
            "Framework tools available:\n"
            "- write_todos: ephemeral turn planning only\n"
            "- ls, read_file, glob, grep: relative reads inside authorized virtual prefixes\n"
            "- write_file, edit_file: relative writes inside authorized virtual prefixes\n"
            "- finalize_turn: required durable terminal action\n\n"
            "Platform tools not available to this role:\n"
            f"{unavailable or '- none'}\n\n"
            "Explicitly unavailable runtime capabilities:\n"
            "- framework task/subagent: unavailable; it bypasses governed delegation\n"
            f"{delegation_capability}\n"
            "- execute/shell/process: unavailable; the backend has no execution protocol\n"
            "- host filesystem/repository/environment/secrets/provider SDKs: unavailable\n"
            "- arbitrary network access: unavailable; external effects require governed tools\n"
            "- human confirmation, override, budget, and checkpoint authority: unavailable\n\n"
            "Workspace:\n"
            "- virtual_mode=true; every model path is relative to the virtual root\n"
            f"- readable_prefixes={','.join(workspace.readable_prefixes)}\n"
            f"- writable_prefixes={','.join(workspace.writable_prefixes)}\n"
            f"- allowed_extensions={','.join(workspace.allowed_extensions)}\n"
            f"- max_total_bytes={workspace.max_total_bytes}; "
            f"max_file_bytes={workspace.max_file_bytes}; "
            f"max_file_count={workspace.max_file_count}\n"
            f"- retention_class={workspace.retention_class}\n\n"
            "Delegation:\n"
            f"{delegations or '- none'}\n\n"
            "Model policy:\n"
            f"- model_id={self.profile.model.model_id}; "
            f"timeout_s={self.profile.model.timeout_s}; "
            f"max_retries={self.profile.model.max_retries}; "
            f"max_output_tokens={self.profile.model.max_output_tokens}; "
            f"temperature={self.profile.model.temperature}\n"
            f"- turn_timeout_s={self.profile.turn_timeout_s}; "
            f"max_model_rounds={self.profile.max_model_rounds}\n\n"
            "## End resolved resource and capability map"
        )

    @property
    def system_prompt(self) -> str:
        return f"{self.prompt_body.rstrip()}\n\n{self.generated_resource_map}"

    def projection(self) -> ProfileProjection:
        return ProfileProjection(
            role=self.profile.role,
            status=RoleRegistryStatus.ACTIVE,
            profile_ref=self.profile_ref,
            prompt_ref=self.profile.prompt,
            resource_manifest_sha256=self.resource_manifest.aggregate_sha256,
            memory_policy=self.memory_policy,
            model_id=self.profile.model.model_id,
            tool_addresses=tuple(tool.address for tool in self.profile.tools),
            skills=self.skill_disclosures(),
            delegation_roles=self.profile.delegation_roles,
            delegation_tool_addresses={
                role: tuple(pin.address for pin in pins)
                for role, pins in sorted(
                    self.delegation_tool_grants.items(),
                    key=lambda item: item[0].value,
                )
            },
            workspace=self.profile.workspace,
            capabilities=self.capabilities,
        )


class AgentProfileRegistry:
    """Eagerly resolve active role profiles against resources, tools, and engine ceilings."""

    def __init__(
        self,
        *,
        prompts: PromptCatalog,
        skills: SkillCatalog,
        profiles: ProfileCatalog,
        tools: AgentToolCatalog,
        engine_tool_ceiling: frozenset[str],
        selected_profile_versions: Mapping[AgentRole, str] | None = None,
        tool_inventory: Sequence[AgentToolContract] = (),
    ) -> None:
        self._prompts = prompts
        self._skills = skills
        self._profiles = profiles
        self._tools = tools
        self._engine_tool_ceiling = engine_tool_ceiling
        inventory_by_address = {item.pin.address: item for item in tool_inventory}
        if len(inventory_by_address) != len(tool_inventory):
            raise AgentCatalogError("tool capability inventory contains duplicate addresses")
        self._tool_inventory = tuple(
            inventory_by_address[address] for address in sorted(inventory_by_address)
        )
        active: dict[AgentRole, ProfileResource] = {}
        if selected_profile_versions is None:
            for resource in profiles.list():
                definition = resource.definition
                if definition.status is ProfileStatus.RETIRED:
                    continue
                if definition.role in active:
                    raise AgentCatalogError(
                        f"role {definition.role.value!r} has multiple active profiles"
                    )
                active[definition.role] = resource
        else:
            for role, version in selected_profile_versions.items():
                candidates = [
                    resource
                    for resource in profiles.list()
                    if resource.definition.role is role
                    and resource.definition.version == version
                    and resource.definition.status is ProfileStatus.ACTIVE
                ]
                if len(candidates) != 1:
                    raise AgentCatalogError(
                        f"selected profile {role.value!r}@{version} is not uniquely active"
                    )
                active[role] = candidates[0]
        missing = _REQUIRED_ACTIVE_ROLES - set(active)
        if missing:
            raise AgentCatalogError(
                f"required active roles have no profile: {sorted(role.value for role in missing)}"
            )
        if AgentRole.ACCOUNT_RESEARCH in active:
            raise AgentCatalogError("account-research profile is reserved for C6.7")
        self._active_resources = active
        self._resolved = {
            role: self._resolve_resource(resource)
            for role, resource in sorted(active.items(), key=lambda item: item[0].value)
        }
        self._validate_delegation_targets()

    def _resolve_tool(self, pin: ToolPin) -> AgentToolContract:
        contract = self._tools.resolve(pin)
        if contract.pin != pin:
            raise AgentCatalogError(f"tool {pin.address!r} schema digest changed")
        if not contract.available:
            raise AgentCatalogError(f"tool {pin.address!r} is unavailable or retired")
        if not contract.recipe_safe:
            raise AgentCatalogError(f"tool {pin.address!r} is not replay-certified")
        if contract.steering:
            raise AgentCatalogError(f"tool {pin.address!r} is human-only steering authority")
        return contract

    def _resolve_resource(
        self,
        resource: ProfileResource,
        *,
        authority_ceiling: frozenset[str] | None = None,
        workspace_ceiling: WorkspacePolicy | None = None,
    ) -> ResolvedAgentProfile:
        definition = resource.definition
        if definition.status is not ProfileStatus.ACTIVE:
            raise AgentCatalogError(f"profile {resource.ref.address!r} is not active")
        prompt = self._prompts.get(
            definition.prompt.name,
            definition.prompt.version,
            expected_sha256=definition.prompt.sha256,
        )
        if prompt.role is not definition.role:
            raise AgentCatalogError(
                f"prompt {prompt.ref.address!r} belongs to role {prompt.role.value!r}"
            )

        declared_tools = tuple(definition.tools)
        for pin in declared_tools:
            self._resolve_tool(pin)
        declared_by_address = {pin.address: pin for pin in declared_tools}
        effective_ceiling = self._engine_tool_ceiling
        if authority_ceiling is not None:
            effective_ceiling = effective_ceiling & authority_ceiling
        effective_tools = tuple(pin for pin in declared_tools if pin.address in effective_ceiling)
        effective_addresses = {pin.address for pin in effective_tools}

        effective_skills: list[SkillResource] = []
        for resource_pin in definition.skills:
            skill = self._skills.get(
                resource_pin.name,
                resource_pin.version,
                expected_sha256=resource_pin.sha256,
            )
            if definition.role not in skill.roles:
                raise AgentCatalogError(
                    f"skill {skill.ref.address!r} does not admit role {definition.role.value!r}"
                )
            for required in skill.required_tools:
                self._resolve_tool(required)
                declared = declared_by_address.get(required.address)
                if declared != required:
                    raise AgentCatalogError(
                        f"skill {skill.ref.address!r} requires an unpinned profile tool "
                        f"{required.address!r}"
                    )
            if {pin.address for pin in skill.required_tools} <= effective_addresses:
                effective_skills.append(skill)

        grants: dict[AgentRole, tuple[ToolPin, ...]] = {}
        for role, pins in definition.delegation_tool_grants.items():
            resolved_pins: list[ToolPin] = []
            for pin in pins:
                self._resolve_tool(pin)
                if pin.address in self._engine_tool_ceiling:
                    resolved_pins.append(pin)
            grants[role] = tuple(resolved_pins)

        workspace = definition.workspace.to_contract()
        if workspace_ceiling is not None:
            workspace = _intersect_workspace(workspace, workspace_ceiling)
        bundles = tuple(
            SkillBundle(
                resource=skill.ref,
                summary=skill.summary,
                materialized_path=(
                    f".deepagent/skills/{skill.ref.name}/{skill.ref.version}/SKILL.md"
                ),
                required_tools=skill.required_tools,
            )
            for skill in effective_skills
        )
        profile = AgentProfile(
            name=definition.name,
            version=definition.version,
            role=definition.role,
            prompt=prompt.ref,
            skills=bundles,
            tools=effective_tools,
            model=definition.model,
            workspace=workspace,
            delegation_roles=tuple(definition.delegation_roles),
            max_delegation_depth=definition.max_delegation_depth,
            max_delegations=definition.max_delegations,
            max_plan_nodes=definition.max_plan_nodes,
            turn_timeout_s=definition.turn_timeout_s,
            max_model_rounds=definition.max_model_rounds,
        )
        manifest = build_agent_resource_manifest(
            role=profile.role,
            profile=resource.ref,
            prompt=prompt.ref,
            skills=tuple(skill.ref for skill in effective_skills),
            tools=profile.tools,
        )
        resources = (
            ResourceBody(resource.ref, resource.content, "application/yaml"),
            ResourceBody(prompt.ref, prompt.content, "text/markdown"),
            *(
                ResourceBody(skill.ref, skill.content, "text/markdown")
                for skill in effective_skills
            ),
        )
        snapshot = AgentResourceSnapshot(manifest=manifest, bodies=resources)
        capabilities = self._capabilities_for(
            role=profile.role,
            effective_addresses={pin.address for pin in profile.tools},
        )
        return ResolvedAgentProfile(
            profile=profile,
            profile_ref=resource.ref,
            prompt_body=prompt.body,
            resource_manifest=manifest,
            resource_snapshot=snapshot,
            memory_policy=definition.memory_policy,
            skills=tuple(effective_skills),
            delegation_tool_grants=grants,
            capabilities=capabilities,
        )

    def _capabilities_for(
        self,
        *,
        role: AgentRole,
        effective_addresses: set[str],
    ) -> tuple[ToolCapabilityDisclosure, ...]:
        disclosures: list[ToolCapabilityDisclosure] = []
        for contract in self._tool_inventory:
            address = contract.pin.address
            if address in effective_addresses:
                status = AgentCapabilityStatus.AVAILABLE
                reason = "effective_profile_tool"
            elif not contract.available:
                status = AgentCapabilityStatus.RETIRED_OR_MISSING
                reason = contract.unavailable_reason_code or "tool_unavailable"
            elif contract.steering or contract.unavailable_reason_code == "human_authority":
                status = AgentCapabilityStatus.HUMAN_ONLY
                reason = contract.unavailable_reason_code or "human_steering_authority"
            elif not contract.recipe_safe:
                status = AgentCapabilityStatus.REPLAY_BLOCKED
                reason = contract.unavailable_reason_code or "replay_not_certified"
            elif role not in contract.admitted_roles:
                status = AgentCapabilityStatus.ROLE_UNAVAILABLE
                reason = contract.unavailable_reason_code or "not_admitted_for_role"
            else:
                status = AgentCapabilityStatus.PROFILE_UNAVAILABLE
                reason = contract.unavailable_reason_code or "absent_from_effective_profile"
            disclosures.append(
                ToolCapabilityDisclosure(
                    address=address,
                    effect_class=contract.effect_class,
                    status=status,
                    reason_code=reason,
                )
            )
        return tuple(disclosures)

    def _validate_delegation_targets(self) -> None:
        for resolved in self._resolved.values():
            for role in resolved.profile.delegation_roles:
                if role not in self._resolved:
                    raise AgentCatalogError(
                        f"profile {resolved.profile_ref.address!r} delegates to inactive "
                        f"role {role.value!r}"
                    )
                child_tools = {pin.address for pin in self._resolved[role].profile.tools}
                granted = {pin.address for pin in resolved.delegation_tool_grants.get(role, ())}
                if not child_tools <= granted:
                    raise AgentCatalogError(
                        f"profile {resolved.profile_ref.address!r} does not grant the full "
                        f"active authority of delegated role {role.value!r}"
                    )

    def resolve(self, role: AgentRole) -> ResolvedAgentProfile:
        try:
            return self._resolved[role]
        except KeyError:
            raise AgentCatalogError(f"role {role.value!r} has no active profile") from None

    def resolve_delegation(
        self,
        *,
        parent: ResolvedAgentProfile,
        child_role: AgentRole,
        current_depth: int,
    ) -> ResolvedAgentProfile:
        if child_role not in parent.profile.delegation_roles:
            raise AgentCatalogError(
                f"role {child_role.value!r} is not delegated by {parent.profile.role.value!r}"
            )
        if current_depth < 0 or current_depth >= parent.profile.max_delegation_depth:
            raise AgentCatalogError("delegation depth limit is exhausted")
        grant = parent.delegation_tool_grants.get(child_role, ())
        grant_ceiling = frozenset(pin.address for pin in grant)
        child_resource = self._active_resources[child_role]
        return self._resolve_resource(
            child_resource,
            authority_ceiling=grant_ceiling,
            workspace_ceiling=parent.profile.workspace,
        )

    def projection(self) -> AgentRegistryProjection:
        roles: list[RoleRegistryEntry] = []
        for role in sorted(AgentRole, key=lambda item: item.value):
            resolved = self._resolved.get(role)
            roles.append(
                RoleRegistryEntry(
                    role=role,
                    status=(
                        RoleRegistryStatus.ACTIVE
                        if resolved is not None
                        else RoleRegistryStatus.PLANNED
                    ),
                    profile=resolved.projection() if resolved is not None else None,
                )
            )
        return AgentRegistryProjection(schema_version="1", roles=tuple(roles))


def _prefix_is_authorized(prefix: str, ceilings: Sequence[str]) -> bool:
    return any(prefix == ceiling or prefix.startswith(f"{ceiling}/") for ceiling in ceilings)


def _intersect_workspace(
    requested: WorkspacePolicy,
    ceiling: WorkspacePolicy,
) -> WorkspacePolicy:
    if requested.retention_class != ceiling.retention_class:
        raise AgentCatalogError("delegated workspace retention class cannot widen or change")
    extensions = tuple(
        extension
        for extension in requested.allowed_extensions
        if extension in ceiling.allowed_extensions
    )
    readable = tuple(
        prefix
        for prefix in requested.readable_prefixes
        if _prefix_is_authorized(prefix, ceiling.readable_prefixes)
    )
    writable = tuple(
        prefix
        for prefix in requested.writable_prefixes
        if _prefix_is_authorized(prefix, ceiling.writable_prefixes)
        and _prefix_is_authorized(prefix, readable)
    )
    return WorkspacePolicy(
        max_total_bytes=min(requested.max_total_bytes, ceiling.max_total_bytes),
        max_file_bytes=min(requested.max_file_bytes, ceiling.max_file_bytes),
        max_file_count=min(requested.max_file_count, ceiling.max_file_count),
        allowed_extensions=extensions,
        readable_prefixes=readable,
        writable_prefixes=writable,
        retention_class=requested.retention_class,
    )
