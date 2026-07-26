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
    "AgentProfileRegistry",
    "AgentRegistryProjection",
    "AgentToolCatalog",
    "AgentToolContract",
    "ProfileProjection",
    "ResolvedAgentProfile",
    "RoleRegistryEntry",
    "RoleRegistryStatus",
    "SkillDisclosure",
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


@runtime_checkable
class AgentToolCatalog(Protocol):
    """Resolve the live contract for an exact profile-pinned tool address."""

    def resolve(self, pin: ToolPin) -> AgentToolContract: ...


class ProjectionValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RoleRegistryStatus(StrEnum):
    ACTIVE = "active"
    PLANNED = "planned"


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
    ) -> None:
        self._prompts = prompts
        self._skills = skills
        self._profiles = profiles
        self._tools = tools
        self._engine_tool_ceiling = engine_tool_ceiling
        active: dict[AgentRole, ProfileResource] = {}
        for resource in profiles.list():
            definition = resource.definition
            if definition.status is ProfileStatus.RETIRED:
                continue
            if definition.role in active:
                raise AgentCatalogError(
                    f"role {definition.role.value!r} has multiple active profiles"
                )
            active[definition.role] = resource
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
        return ResolvedAgentProfile(
            profile=profile,
            profile_ref=resource.ref,
            prompt_body=prompt.body,
            resource_manifest=manifest,
            resource_snapshot=snapshot,
            memory_policy=definition.memory_policy,
            skills=tuple(effective_skills),
            delegation_tool_grants=grants,
        )

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
