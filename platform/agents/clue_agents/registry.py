"""Resolved role profiles, effective authority, and progressive skill disclosure."""

from __future__ import annotations

import os
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
    ModelPolicy,
    SkillBundle,
    ToolPin,
    WorkspacePolicy,
)
from clue_agents.resources import (
    AgentResourceSnapshot,
    ResourceBody,
    build_agent_resource_manifest,
    render_skill_references,
)

__all__ = [
    "AgentCapabilityStatus",
    "AgentProfileRegistry",
    "AgentRegistryProjection",
    "AgentSurfacePolicy",
    "AgentToolCatalog",
    "AgentToolContract",
    "ProfileProjection",
    "ResolvedAgentProfile",
    "RoleRegistryEntry",
    "RoleRegistryStatus",
    "SkillDisclosure",
    "SurfaceRegistryEntry",
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


@dataclass(frozen=True, slots=True)
class AgentSurfacePolicy:
    """A named, data-only narrowing of one role's effective tool surface (PC-C8 §8).

    A *surface* is where a role is being run — the Stage-0 conversation trial is one, the full
    product another. Some rules only hold on one surface ("this trial does no external research"),
    and this platform's own no-fake-agency principle says such a rule is governed by a tool that is
    **not installed**, never by prose asking the model not to call it.

    The policy is therefore a ceiling, not a second profile: the role keeps its single reviewed
    profile resource (same ``profile_ref``, same pinned digests, same prompt), and the surface
    withholds tools from its *effective* set. Everything downstream follows automatically because
    it already reads the effective set — the resource manifest, the generated capability map, and
    ``ExactAgentToolSurfaceMiddleware``'s allowed-set enforcement. ``framing`` is the surface's own
    honest description of itself, rendered beside the withheld tools in the generated map so the
    words and the enforcement can never drift apart.

    ``withheld_delegation_roles`` withholds *the other* way a surface can reach capability it is
    not supposed to have. A tool ceiling alone left the trial's map promising "no external
    research" while still advertising ``delegate_specialist`` and the research role beneath it —
    the surface's words and its own map disagreed, and the only thing stopping a delegation was a
    composition-root child runner raising at call time. Restriction by crash is exactly what ruling
    §2.4 rejects, so a withheld role leaves ``delegation_roles``/``delegation_tool_grants`` empty:
    the framework tool leaves the middleware's allowed set, the map stops advertising it, and the
    runner's refusal becomes an unreachable backstop instead of the mechanism.
    """

    surface: str
    role: AgentRole
    withheld_tools: frozenset[str]
    withheld_reason_code: str
    framing: str
    withheld_delegation_roles: frozenset[AgentRole] = frozenset()


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


class SurfaceRegistryEntry(ProjectionValue):
    """One declared surface of a role, as the operator projection sees it.

    Without this the ``/agent/registry`` projection reports only the role's *full* authority, so an
    operator reading it would be told the Stage-0 trial can call tools and delegate to specialists
    it structurally cannot. Both the resulting set and what was removed to get there are reported:
    "which tools does this surface have" and "which did the policy take away" are different
    questions, and only the second survives a tool being renamed out of the withheld list.
    """

    surface: str
    reason_code: str
    resource_manifest_sha256: str
    tool_addresses: tuple[str, ...]
    withheld_tool_names: tuple[str, ...]
    delegation_roles: tuple[AgentRole, ...]
    withheld_delegation_roles: tuple[AgentRole, ...]


class RoleRegistryEntry(ProjectionValue):
    role: AgentRole
    status: RoleRegistryStatus
    profile: ProfileProjection | None = None
    surfaces: tuple[SurfaceRegistryEntry, ...] = ()


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
    surface_policy: AgentSurfacePolicy | None = None

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
                return render_skill_references(skill.body, self.resource_manifest.skills)
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
        surface = self.surface_policy
        delegation_capability = (
            "- delegate_specialist: available; validated C5 delegation and fresh child wake"
            if self.profile.delegation_roles
            else (
                "- delegate_specialist: unavailable on this surface"
                if surface is not None and surface.withheld_delegation_roles
                else "- delegate_specialist: unavailable in this profile"
            )
        )
        surface_block = ""
        if surface is not None:
            withheld_lines = []
            if surface.withheld_tools:
                withheld_lines.append(
                    "- withheld tools: " + ", ".join(sorted(surface.withheld_tools))
                )
            if surface.withheld_delegation_roles:
                withheld_lines.append(
                    "- withheld delegation: "
                    + ", ".join(sorted(role.value for role in surface.withheld_delegation_roles))
                )
            surface_block = (
                "Surface policy:\n"
                f"- surface={surface.surface}\n"
                f"- {surface.framing}\n"
                + "\n".join(withheld_lines)
                + f"\n- reason={surface.withheld_reason_code}; none of the above is installed, "
                "so there is nothing here to decline\n\n"
            )
        return (
            "## Resolved resource and capability map (authoritative; generated)\n\n"
            f"{surface_block}"
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
            # The turn's round and time limits are operator settings for the conversation and
            # research agents (founder ruling 2026-09-27), so the profile's own numbers are not
            # the ones that apply; the wrap-up notice is what tells the agent it is near either.
            "- turn limits (model rounds, wall clock): set by the deployment; a platform notice "
            "tells you when you are near one, and then only finalize_turn is offered\n\n"
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


def _env_model_policy(role: AgentRole, policy: ModelPolicy) -> ModelPolicy:
    """Environment-first model selection for a role (founder ruling 2026-08-31).

    ``<ROLE>_AGENT_MODEL`` (e.g. ``HEAD_OF_ABM_AGENT_MODEL``) overrides the catalog
    profile's pinned ``model_id`` at resolution time, so a model change is a deployment
    setting rather than a new reviewed profile version. Blank or unset keeps the profile
    pin — tests and historical replay stay deterministic with no environment. Everything
    else on the policy (timeout/retries/output budget/temperature) still comes from the
    reviewed profile; the environment names the model, not the envelope. The per-role
    reasoning effort (``<ROLE>_AGENT_MODEL_EFFORT``) is read at the gateway, not here,
    because effort shapes the provider request rather than the profile contract.

    One envelope field is deployment-wide as well (founder ruling 2026-09-08, superseding
    "the environment names the model, not the envelope" for this field only):
    ``CLUE_AGENT_MODEL_TIMEOUT_S`` overrides every role's per-call ``timeout_s``, so raising
    the platform's per-call patience is one setting rather than a re-mint of every active
    profile. The gateway ceiling (``CLUE_GATEWAY_TIMEOUT_S``) still bounds it: the model
    builder refuses a value above the ceiling. Blank or unset keeps the profile pin.
    """

    model_override = os.environ.get(f"{role.value.upper()}_AGENT_MODEL", "").strip()
    timeout_override = os.environ.get("CLUE_AGENT_MODEL_TIMEOUT_S", "").strip()
    model_id = model_override or policy.model_id
    timeout_s = float(timeout_override) if timeout_override else policy.timeout_s
    if model_id == policy.model_id and timeout_s == policy.timeout_s:
        return policy
    return ModelPolicy(
        model_id=model_id,
        timeout_s=timeout_s,
        max_retries=policy.max_retries,
        max_output_tokens=policy.max_output_tokens,
        temperature=policy.temperature,
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
        surface_policies: Sequence[AgentSurfacePolicy] = (),
        required_roles: frozenset[AgentRole] = _REQUIRED_ACTIVE_ROLES,
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
        missing = required_roles - set(active)
        if missing:
            raise AgentCatalogError(
                f"required active roles have no profile: {sorted(role.value for role in missing)}"
            )
        self._active_resources = active
        self._resolved = {
            role: self._resolve_resource(resource)
            for role, resource in sorted(active.items(), key=lambda item: item[0].value)
        }
        self._validate_delegation_targets()
        self._surfaces = self._resolve_surfaces(surface_policies)

    def _resolve_surfaces(
        self,
        policies: Sequence[AgentSurfacePolicy],
    ) -> dict[tuple[AgentRole, str], ResolvedAgentProfile]:
        """Resolve every declared surface eagerly, so a stale policy fails at composition.

        A policy that withholds a tool the role's profile never pinned is refused rather than
        silently no-op'd: that is exactly how a surface restriction rots into prose — the tool is
        renamed or re-pinned, the withheld name stops matching, and the surface quietly regains
        the capability it was created to remove.
        """

        surfaces: dict[tuple[AgentRole, str], ResolvedAgentProfile] = {}
        for policy in policies:
            key = (policy.role, policy.surface)
            if key in surfaces:
                raise AgentCatalogError(
                    f"surface {policy.surface!r} is declared twice for role {policy.role.value!r}"
                )
            resource = self._active_resources.get(policy.role)
            if resource is None:
                raise AgentCatalogError(
                    f"surface {policy.surface!r} names role {policy.role.value!r}, "
                    "which has no active profile"
                )
            if not policy.withheld_tools and not policy.withheld_delegation_roles:
                raise AgentCatalogError(
                    f"surface {policy.surface!r} withholds nothing; it is not a restriction"
                )
            declared = {pin.name for pin in resource.definition.tools}
            unknown = sorted(policy.withheld_tools - declared)
            if unknown:
                raise AgentCatalogError(
                    f"surface {policy.surface!r} withholds tools "
                    f"{unknown} that profile {resource.ref.address!r} does not pin"
                )
            delegable = set(resource.definition.delegation_roles)
            undelegated = sorted(
                role.value for role in policy.withheld_delegation_roles - delegable
            )
            if undelegated:
                raise AgentCatalogError(
                    f"surface {policy.surface!r} withholds delegation roles "
                    f"{undelegated} that profile {resource.ref.address!r} does not delegate"
                )
            surfaces[key] = self._resolve_resource(resource, surface_policy=policy)
        return surfaces

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
        surface_policy: AgentSurfacePolicy | None = None,
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
        if surface_policy is not None:
            effective_ceiling = effective_ceiling - {
                pin.address for pin in declared_tools if pin.name in surface_policy.withheld_tools
            }
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

        withheld_roles = (
            surface_policy.withheld_delegation_roles
            if surface_policy is not None
            else frozenset[AgentRole]()
        )
        grants: dict[AgentRole, tuple[ToolPin, ...]] = {}
        for role, pins in definition.delegation_tool_grants.items():
            # Every declared grant is still *resolved* — a surface must not be able to hide a
            # stale or retired child pin by withholding the role it belongs to.
            resolved_pins = []
            for pin in pins:
                self._resolve_tool(pin)
                if pin.address in self._engine_tool_ceiling:
                    resolved_pins.append(pin)
            if role in withheld_roles:
                continue
            grants[role] = tuple(resolved_pins)
        effective_delegation_roles = tuple(
            role for role in definition.delegation_roles if role not in withheld_roles
        )

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
            model=_env_model_policy(definition.role, definition.model),
            workspace=workspace,
            delegation_roles=effective_delegation_roles,
            # `AgentProfile` requires a non-delegating profile to carry zero delegation budget, and
            # that is the honest reading here too: a surface with no delegable role has no
            # delegation depth to spend. `AgentPlanPolicy.from_profile` reads these, so the plan
            # policy narrows with the surface instead of advertising a budget for nothing.
            max_delegation_depth=(
                definition.max_delegation_depth if effective_delegation_roles else 0
            ),
            max_delegations=(definition.max_delegations if effective_delegation_roles else 0),
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
            surface_policy=surface_policy,
        )
        return ResolvedAgentProfile(
            profile=profile,
            profile_ref=resource.ref,
            prompt_body=render_skill_references(prompt.body, manifest.skills),
            resource_manifest=manifest,
            resource_snapshot=snapshot,
            memory_policy=definition.memory_policy,
            skills=tuple(effective_skills),
            delegation_tool_grants=grants,
            capabilities=capabilities,
            surface_policy=surface_policy,
        )

    def _capabilities_for(
        self,
        *,
        role: AgentRole,
        effective_addresses: set[str],
        surface_policy: AgentSurfacePolicy | None = None,
    ) -> tuple[ToolCapabilityDisclosure, ...]:
        disclosures: list[ToolCapabilityDisclosure] = []
        withheld = surface_policy.withheld_tools if surface_policy is not None else frozenset()
        for contract in self._tool_inventory:
            address = contract.pin.address
            if contract.pin.name in withheld:
                # Named honestly: withheld *by this surface*, not missing from the role's
                # reviewed authority. The generated map already carries the surface's framing.
                assert surface_policy is not None
                status = AgentCapabilityStatus.PROFILE_UNAVAILABLE
                reason = surface_policy.withheld_reason_code
            elif contract.unavailable_reason_code == "entity_research_agent_not_composed":
                status = AgentCapabilityStatus.REPLAY_BLOCKED
                reason = contract.unavailable_reason_code
            elif address in effective_addresses:
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

    def resolve(self, role: AgentRole, *, surface: str | None = None) -> ResolvedAgentProfile:
        """Resolve a role, optionally narrowed to one declared surface (PC-C8 §8).

        Without a surface this is the role's full reviewed authority — the resolution
        ``build_agent_profile_registry`` audits against ``C6_AGENT_TOOL_AUTHORITY``. With one it is
        the same profile resource under that surface's ceiling; a surface nobody declared is an
        error, never a silent fall-through to the full surface.
        """

        if surface is not None:
            try:
                return self._surfaces[(role, surface)]
            except KeyError:
                raise AgentCatalogError(f"role {role.value!r} has no surface {surface!r}") from None
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
                    surfaces=self._surface_projections(role),
                )
            )
        return AgentRegistryProjection(schema_version="1", roles=tuple(roles))

    def _surface_projections(self, role: AgentRole) -> tuple[SurfaceRegistryEntry, ...]:
        return tuple(
            SurfaceRegistryEntry(
                surface=surface,
                reason_code=policy.withheld_reason_code,
                resource_manifest_sha256=narrowed.resource_manifest.aggregate_sha256,
                tool_addresses=tuple(pin.address for pin in narrowed.profile.tools),
                withheld_tool_names=tuple(sorted(policy.withheld_tools)),
                delegation_roles=narrowed.profile.delegation_roles,
                withheld_delegation_roles=tuple(
                    sorted(policy.withheld_delegation_roles, key=lambda item: item.value)
                ),
            )
            for (owner, surface), narrowed in sorted(
                self._surfaces.items(), key=lambda item: item[0][1]
            )
            if owner is role and (policy := narrowed.surface_policy) is not None
        )


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
