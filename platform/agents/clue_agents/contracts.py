"""Frozen C6 agent-runtime value contracts.

These types are deliberately framework-neutral and body-light.  They describe the immutable
authority, resource, plan, context, delegation, and finalization records that surround a real
deepagent.  Raw prompt/context/file bodies belong to artifacts or ephemeral model input, never to
these durable envelopes.

C6.0 freezes the shapes before any C6 migration or production executor exists.  A schema digest
test makes later changes explicit contract revisions rather than accidental drift.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from clue_core import ExecutionId, OperationId

__all__ = [
    "AgentConstitution",
    "AgentFinalizeEnvelope",
    "AgentPlan",
    "AgentProfile",
    "AgentResourceManifest",
    "AgentResourceRef",
    "AgentRole",
    "AgentTurnRequest",
    "ArtifactRef",
    "ContextBundleManifest",
    "ContextLayer",
    "ContinuationRef",
    "ContextLayerManifest",
    "DelegatedFileGrant",
    "DelegationRequest",
    "DelegationResult",
    "DomainObjectRef",
    "FinalizeStatus",
    "MODEL_FORBIDDEN_AUTHORITY_KEYS",
    "ModelPolicy",
    "PlanDelegationStep",
    "PlanStep",
    "PlanToolStep",
    "ProjectContextArtifact",
    "ResourceKind",
    "SkillBundle",
    "SpecialistTaskEnvelope",
    "ToolPin",
    "ValidatedOperation",
    "ValidatedPlan",
    "WorkspacePolicy",
    "normalize_virtual_path",
]

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ResourceName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[a-z0-9-]+$"),
]
ProjectContextName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9_-]+$",
    ),
]
ResourceVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^(?:v?[0-9]+(?:\.[0-9]+){0,2})(?:[-+][a-z0-9.-]+)?$",
    ),
]
StableId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
ReasonCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9_.-]+$",
    ),
]

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_CONFUSABLE_SEPARATORS = frozenset(
    {
        "\u2044",  # fraction slash
        "\u2215",  # division slash
        "\u29f5",  # reverse solidus operator
        "\u29f8",  # big solidus
        "\ufe68",  # small reverse solidus
        "\uff0f",  # fullwidth solidus
        "\uff3c",  # fullwidth reverse solidus
    }
)
_SOURCE_EXTENSIONS = {
    ".bash",
    ".c",
    ".cc",
    ".class",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".mjs",
    ".php",
    ".pl",
    ".ps1",
    ".py",
    ".pyc",
    ".rb",
    ".rs",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
}
#: Trusted authority a model may never supply. These names are stripped from the **top level** of
#: every model-visible tool schema and rejected in top-level plan arguments; a tool that declares
#: one there is served the value from the :class:`AgentConstitution` at the execution seam.
#:
#: The set is keyed by *name*, not per tool, because each name means exactly one thing everywhere
#: it appears: the scope of the execution this constitution governs. ``brand_id`` and
#: ``client_entity_id`` (PC-C8 §6a) are whole-execution authority in the same sense as
#: ``project_id`` — a Stage-0 tool's ``brand_id`` is always *this project's* brand, and its
#: ``client_entity_id`` always *this project's* client account — so letting the model copy them out
#: of its context and hand them back is the same defect the turn binding removed for the turn's own
#: ids. Per-turn authority, which is *not* stable for an execution and *is* legitimately
#: model-authored on other tools, is marked per input model instead
#: (``clue_api.turn_binding.TRUSTED_TURN_FIELD``).
#:
#: **Top-level only — and no tool nests one any more.** ``_with_trusted_runtime`` deletes fields
#: from the input model itself, so a name nested inside a sub-model would be neither hidden nor
#: injected. Until PC-C8 task 1.4 three granted tools did exactly that
#: (``propose_field``/``propose_source`` via ``scope.brand_id``/``scope.project_id``, and
#: ``submit_ingestion`` via ``declared_context.*``), which let the model author a *wrong yet
#: existing* sibling scope in the same workspace. Task 1.4 **hoisted** those fields onto the tool
#: inputs rather than teaching the seam to recurse: the seam stays one simple rule, and the nested
#: authority it could not reach no longer exists to reach.
#:
#: That is now a permanent, repo-wide gate rather than a claim —
#: ``tests/architecture/test_model_facing_authority.py`` walks every granted tool's model-facing
#: schema at **every** depth (``$defs`` included) and fails the build if any of these names
#: reappears. So a future tool that nests one is a red build, not a quiet exception in this
#: docstring.
MODEL_FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "actor_id",
        "brand_id",
        "client_entity_id",
        "execution_id",
        "operation_id",
        "parent_execution_id",
        "project_id",
        "workspace_id",
    }
)


def normalize_virtual_path(value: str) -> str:
    """Validate a model-visible path and return its normalized POSIX representation.

    The accepted representation is already normalized and relative to the opaque execution root.
    We intentionally do not "fix" hostile input: an absolute path, backslash, duplicate separator,
    dot component, or control character fails loudly.
    """

    if not isinstance(value, str) or not value:
        raise ValueError("virtual path must be a non-empty string")
    if _CONTROL_CHARS.search(value):
        raise ValueError("virtual path must not contain control characters")
    if any(character in value for character in _CONFUSABLE_SEPARATORS):
        raise ValueError("virtual path must not contain Unicode separator confusables")
    if value.startswith("/") or value.startswith("\\"):
        raise ValueError("virtual path must be relative to the workspace root")
    if "\\" in value:
        raise ValueError("virtual path must use POSIX separators")
    if ":" in value.split("/", maxsplit=1)[0]:
        raise ValueError("virtual path must not be drive-qualified")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("virtual path must be normalized and must not contain dot components")
    return "/".join(parts)


def _unique(values: Iterable[object], *, label: str) -> None:
    materialized = tuple(values)
    if len(set(materialized)) != len(materialized):
        raise ValueError(f"{label} must be unique")


class FrozenContract(BaseModel):
    """Common strict, immutable C6 contract behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentRole(StrEnum):
    HEAD_OF_ABM = "head_of_abm"
    RESEARCH = "research"
    CONTENT_DRAFTER = "content_drafter"
    REVIEWER = "reviewer"
    ACCOUNT_RESEARCH = "account_research"
    RESEARCH_CLAIMS = "research_claims"
    RESEARCH_NARRATIVE = "research_narrative"
    # PD-part3 D2: the platform-facing role of the COMPOSITE design deepagent — the
    # orchestrator/author/reviewer trio stays internal to the design runtime (one leg,
    # one summarized outcome; a doorway, not a container). Deliberately absent from
    # C6_ACTIVE_PROFILE_VERSIONS until P3.3 registers the catalog profile.
    DESIGN = "design"
    # ARV2 Track O (O4): the brand-level onboarding synthesis agent — writes ICP and persona
    # documents from the onboarding research documents. One turn per onboarding run; never a
    # conversation surface. Registered active in C6_ACTIVE_PROFILE_VERSIONS by O4.
    ONBOARDING_SYNTHESIS = "onboarding_synthesis"


class ResourceKind(StrEnum):
    PROFILE = "profile"
    PROMPT = "prompt"
    SKILL = "skill"


class ContinuationRef(FrozenContract):
    """The completed turn a Head-of-ABM turn continues, and the messages said since it.

    The turn's graph resumes ``execution_id``'s saved state; ``gap_message_ids`` are the thread
    messages stored after that turn that its state does not hold (spec 2026-09-29 §3.1).
    """

    turn_id: UUID
    execution_id: ExecutionId
    gap_message_ids: tuple[UUID, ...] = ()


class ArtifactRef(FrozenContract):
    """Opaque durable-artifact identity; never a host path or an inline body."""

    workspace_id: StableId
    artifact_key: StableId
    sha256: Sha256
    media_type: StableId
    byte_count: int = Field(ge=0)

    @field_validator("artifact_key")
    @classmethod
    def artifact_key_is_not_a_path_escape(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or _CONTROL_CHARS.search(value):
            raise ValueError("artifact_key must be opaque and must not expose an absolute path")
        return value


class DomainObjectRef(FrozenContract):
    """Typed, scoped reference to domain state owned outside the agent runtime.

    ``note`` carries the human's own words about this one reference — the per-element annotation
    a marketer writes in the web editor. It is human intent about a target, never authority: it
    selects nothing and grants nothing. Optional, so every existing construction stays valid.
    ``title`` is what the referenced object calls itself, carried so a surface can name the card it
    draws without reading the object back. Optional, and defaulted, because most refs are the
    model's own citations of things it only read — and because a finalization recorded before this
    field existed must still validate when it is replayed.
    """

    workspace_id: StableId
    object_type: StableId
    object_id: StableId
    version: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=2_000)
    title: str | None = Field(default=None, max_length=512)


class AgentResourceRef(FrozenContract):
    """Exact immutable folder-catalog resource address."""

    kind: ResourceKind
    name: ResourceName
    version: ResourceVersion
    sha256: Sha256

    @model_validator(mode="after")
    def reject_mutable_aliases(self) -> AgentResourceRef:
        if self.version.lower() in {"latest", "current", "default", "head"}:
            raise ValueError("agent resources must be pinned to an immutable version")
        return self

    @property
    def address(self) -> str:
        return f"{self.kind.value}:{self.name}@{self.version}"


class ToolPin(FrozenContract):
    """An exact recipe-safe agent tool address and schema commitment."""

    name: StableId
    version: StableId
    input_schema_sha256: Sha256
    output_schema_sha256: Sha256

    @field_validator("name", "version")
    @classmethod
    def address_parts_are_exact(cls, value: str) -> str:
        if "@" in value:
            raise ValueError("tool name and version are stored separately")
        return value

    @property
    def address(self) -> str:
        return f"{self.name}@{self.version}"


class ModelPolicy(FrozenContract):
    """Provider-neutral model request policy passed to the injected gateway adapter."""

    model_id: StableId
    timeout_s: float = Field(gt=0, le=600)
    max_retries: int = Field(ge=0, le=5)
    max_output_tokens: int = Field(ge=1, le=131_072)
    temperature: float = Field(ge=0, le=2)


class WorkspacePolicy(FrozenContract):
    """Model-visible workspace authority; the host root is intentionally absent."""

    virtual_mode: Literal[True] = True
    max_total_bytes: int = Field(ge=1)
    max_file_bytes: int = Field(ge=1)
    max_file_count: int = Field(ge=1)
    allowed_extensions: tuple[str, ...]
    readable_prefixes: tuple[str, ...]
    writable_prefixes: tuple[str, ...]
    retention_class: StableId

    @field_validator("allowed_extensions")
    @classmethod
    def extensions_are_data_only(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _unique(values, label="allowed extensions")
        for value in values:
            if not value.startswith(".") or value.lower() != value or "/" in value or "\\" in value:
                raise ValueError("allowed extensions must be lowercase suffixes such as '.md'")
            if value in _SOURCE_EXTENSIONS:
                raise ValueError(f"source or executable extension {value!r} is not allowed")
        return values

    @field_validator("readable_prefixes", "writable_prefixes")
    @classmethod
    def prefixes_are_relative(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_virtual_path(value.rstrip("/")) for value in values)
        _unique(normalized, label="workspace prefixes")
        return normalized

    @model_validator(mode="after")
    def writable_prefixes_are_readable_and_quota_is_coherent(self) -> WorkspacePolicy:
        for writable in self.writable_prefixes:
            if not any(
                writable == readable or writable.startswith(f"{readable}/")
                for readable in self.readable_prefixes
            ):
                raise ValueError(f"writable prefix {writable!r} must also be readable")
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError("per-file quota cannot exceed total workspace quota")
        return self


class SkillBundle(FrozenContract):
    """A progressive-disclosure skill descriptor pinned into one profile."""

    resource: AgentResourceRef
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    materialized_path: str
    required_tools: tuple[ToolPin, ...] = ()
    readiness_refs: tuple[DomainObjectRef, ...] = ()

    @field_validator("materialized_path")
    @classmethod
    def skill_path_is_normalized(cls, value: str) -> str:
        normalized = normalize_virtual_path(value)
        if not normalized.startswith(".deepagent/skills/"):
            raise ValueError("skill bundle must materialize below .deepagent/skills/")
        return normalized

    @model_validator(mode="after")
    def resource_is_a_skill_and_tools_are_unique(self) -> SkillBundle:
        if self.resource.kind is not ResourceKind.SKILL:
            raise ValueError("SkillBundle.resource must have kind='skill'")
        _unique((item.address for item in self.required_tools), label="required tool addresses")
        return self


class AgentProfile(FrozenContract):
    """Exact role policy used to construct one mind."""

    name: ResourceName
    version: ResourceVersion
    role: AgentRole
    prompt: AgentResourceRef
    skills: tuple[SkillBundle, ...]
    tools: tuple[ToolPin, ...]
    model: ModelPolicy
    workspace: WorkspacePolicy
    delegation_roles: tuple[AgentRole, ...] = ()
    max_delegation_depth: int = Field(ge=0, le=4)
    max_delegations: int = Field(ge=0, le=32)
    max_plan_nodes: int = Field(ge=1, le=256)
    turn_timeout_s: float = Field(default=300.0, gt=0, le=1800)
    max_model_rounds: int = Field(default=24, ge=1, le=128)

    @model_validator(mode="after")
    def profile_is_internally_coherent(self) -> AgentProfile:
        if self.prompt.kind is not ResourceKind.PROMPT:
            raise ValueError("AgentProfile.prompt must have kind='prompt'")
        _unique((item.resource.address for item in self.skills), label="skill addresses")
        _unique((item.address for item in self.tools), label="tool addresses")
        _unique(self.delegation_roles, label="delegation roles")
        if self.role in self.delegation_roles:
            raise ValueError("a profile cannot delegate to its own role")
        effective = {item.address for item in self.tools}
        missing = {
            pin.address
            for skill in self.skills
            for pin in skill.required_tools
            if pin.address not in effective
        }
        if missing:
            raise ValueError(f"skills require tools absent from the profile: {sorted(missing)}")
        if not self.delegation_roles and (self.max_delegation_depth or self.max_delegations):
            raise ValueError("a non-delegating profile must use zero delegation limits")
        return self


class AgentResourceManifest(FrozenContract):
    """Immutable resource snapshot committed before the first model call."""

    schema_version: Literal["1"]
    role: AgentRole
    profile: AgentResourceRef
    prompt: AgentResourceRef
    skills: tuple[AgentResourceRef, ...]
    tools: tuple[ToolPin, ...]
    aggregate_sha256: Sha256

    @model_validator(mode="after")
    def resources_have_correct_kinds_and_unique_addresses(self) -> AgentResourceManifest:
        if self.profile.kind is not ResourceKind.PROFILE:
            raise ValueError("manifest profile must have kind='profile'")
        if self.prompt.kind is not ResourceKind.PROMPT:
            raise ValueError("manifest prompt must have kind='prompt'")
        if any(item.kind is not ResourceKind.SKILL for item in self.skills):
            raise ValueError("manifest skills must all have kind='skill'")
        _unique((item.address for item in self.skills), label="manifest skill addresses")
        _unique((item.address for item in self.tools), label="manifest tool addresses")
        return self


class ProjectContextArtifact(FrozenContract):
    """One additional immutable L3 project input materialized at a canonical path."""

    # The frozen production context vocabulary uses snake_case
    # (``client_knowledge``/``stage0_project_state``), while older directive artifacts use
    # kebab-case. This field is not a folder-backed resource name and therefore has its own narrow
    # identifier type rather than widening ``ResourceName`` platform-wide.
    name: ProjectContextName
    artifact_ref: ArtifactRef
    domain_ref: DomainObjectRef


class AgentConstitution(FrozenContract):
    """Trusted immutable authority injected into a parent and every child mind.

    ``project_card_ref`` (PC-C8 §10) is the single owner of durable project state in L3: it
    replaced the ``stage_snapshot_ref``/``readiness_snapshot_ref`` pair, whose two bodies
    re-serialized the same readiness ledger and grew without bound with conversation length.
    ``budget_envelope_ref`` stays a separate ref because it is *spend authority*, not project
    state, and its consumers read it directly rather than through context.

    ``client_entity_id`` is the client account this execution speaks for. It is optional because
    only Stage-0-shaped surfaces have one; a tool that needs it and gets a constitution without one
    is refused at the execution seam rather than served a guess.
    """

    workspace_id: StableId
    project_id: StableId
    execution_id: ExecutionId
    actor_id: StableId
    role: AgentRole
    brand_id: StableId | None = None
    product_id: StableId | None = None
    client_entity_id: StableId | None = None
    workspace_root_id: StableId
    project_card_ref: ArtifactRef
    budget_envelope_ref: ArtifactRef
    profile_ref: AgentResourceRef
    resource_manifest_ref: ArtifactRef
    resource_manifest_sha256: Sha256
    focus_refs: tuple[DomainObjectRef, ...] = ()
    project_context_artifacts: tuple[ProjectContextArtifact, ...] = ()

    @model_validator(mode="after")
    def refs_match_workspace_and_profile_kind(self) -> AgentConstitution:
        refs = (
            self.project_card_ref,
            self.budget_envelope_ref,
            self.resource_manifest_ref,
        )
        if any(item.workspace_id != self.workspace_id for item in refs):
            raise ValueError("constitution artifact refs must belong to the constitution workspace")
        if any(item.workspace_id != self.workspace_id for item in self.focus_refs):
            raise ValueError("constitution focus refs must belong to the constitution workspace")
        if any(
            item.artifact_ref.workspace_id != self.workspace_id
            or item.domain_ref.workspace_id != self.workspace_id
            for item in self.project_context_artifacts
        ):
            raise ValueError("project context artifacts must belong to the constitution workspace")
        _unique(
            (item.name for item in self.project_context_artifacts),
            label="project context artifact names",
        )
        reserved_names = {"project_card", "budget"}
        if any(item.name in reserved_names for item in self.project_context_artifacts):
            raise ValueError(
                "project context artifact names cannot shadow the project card or budget"
            )
        by_name = {item.name: item for item in self.project_context_artifacts}
        client_knowledge = by_name.get("client_knowledge")
        stage0_project_state = by_name.get("stage0_project_state")
        product_profile = by_name.get("product_profile")
        product_knowledge = by_name.get("product_knowledge")
        if (client_knowledge is None) != (stage0_project_state is None):
            raise ValueError(
                "production Client-KB and Stage-0 project context must be constituted together"
            )
        if client_knowledge is not None and (
            self.client_entity_id is None
            or client_knowledge.domain_ref.object_type != "client_knowledge"
            or client_knowledge.domain_ref.object_id != self.client_entity_id
            or client_knowledge.domain_ref.version is None
        ):
            raise ValueError(
                "Client-KB context must match the constitution client and exact version"
            )
        if stage0_project_state is not None and (
            stage0_project_state.domain_ref.object_type != "stage0_project_state"
            or stage0_project_state.domain_ref.object_id != self.project_id
            or stage0_project_state.domain_ref.version is not None
        ):
            raise ValueError("Stage-0 context must belong to the constitution project")
        if product_profile is not None and (
            self.product_id is None
            or product_profile.domain_ref.object_type != "product"
            or product_profile.domain_ref.object_id != self.product_id
            or product_profile.domain_ref.version is not None
        ):
            raise ValueError("product profile context must match the confirmed project product")
        if product_knowledge is not None and (
            product_profile is None
            or self.product_id is None
            or product_knowledge.domain_ref.object_type != "product_knowledge"
            or product_knowledge.domain_ref.object_id != self.product_id
            or product_knowledge.domain_ref.version is None
            or product_knowledge.domain_ref.version < 1
        ):
            raise ValueError(
                "Product-KB context requires the matching product profile and exact version"
            )
        if self.profile_ref.kind is not ResourceKind.PROFILE:
            raise ValueError("constitution profile_ref must have kind='profile'")
        return self


class AgentTurnRequest(FrozenContract):
    """One body-free request to wake the platform agent."""

    turn_id: UUID
    thread_id: StableId
    constitution: AgentConstitution
    user_message_artifact_ref: ArtifactRef
    attachment_refs: tuple[ArtifactRef, ...] = ()
    focus_refs: tuple[DomainObjectRef, ...] = ()
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def turn_refs_match_workspace(self) -> AgentTurnRequest:
        workspace_id = self.constitution.workspace_id
        artifacts = (self.user_message_artifact_ref, *self.attachment_refs)
        if any(item.workspace_id != workspace_id for item in artifacts):
            raise ValueError("turn artifact refs must belong to the constitution workspace")
        if any(item.workspace_id != workspace_id for item in self.focus_refs):
            raise ValueError("turn focus refs must belong to the constitution workspace")
        _unique((item.artifact_key for item in artifacts), label="turn artifact keys")
        return self


class PlanToolStep(FrozenContract):
    retry_of: tuple[StableId, ...] = Field(default=(), exclude_if=lambda value: not value)
    kind: Literal["tool"] = "tool"
    node_key: StableId
    depends_on: tuple[StableId, ...] = ()
    tool: ToolPin
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    purpose: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]

    @field_validator("arguments")
    @classmethod
    def model_cannot_supply_trusted_authority(
        cls,
        values: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        forbidden = set(values) & MODEL_FORBIDDEN_AUTHORITY_KEYS
        if forbidden:
            raise ValueError(
                f"model plan arguments cannot supply trusted authority: {sorted(forbidden)}"
            )
        return values


class PlanDelegationStep(FrozenContract):
    kind: Literal["delegation"] = "delegation"
    node_key: StableId
    depends_on: tuple[StableId, ...] = ()
    role: AgentRole
    task_artifact_ref: ArtifactRef
    granted_paths: tuple[str, ...]
    domain_refs: tuple[DomainObjectRef, ...] = ()
    purpose: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]

    @field_validator("granted_paths")
    @classmethod
    def grants_are_relative(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_virtual_path(value) for value in values)
        _unique(normalized, label="delegation path grants")
        return normalized


PlanStep = Annotated[PlanToolStep | PlanDelegationStep, Field(discriminator="kind")]


def _validate_plan_graph(steps: tuple[PlanStep, ...]) -> None:
    keys = tuple(step.node_key for step in steps)
    _unique(keys, label="plan node keys")
    known = set(keys)
    for step in steps:
        _unique(step.depends_on, label=f"dependencies for {step.node_key}")
        unknown = set(step.depends_on) - known
        if unknown:
            raise ValueError(
                f"plan node {step.node_key!r} has unknown dependencies: {sorted(unknown)}"
            )
        if step.node_key in step.depends_on:
            raise ValueError(f"plan node {step.node_key!r} cannot depend on itself")

    incoming = {step.node_key: set(step.depends_on) for step in steps}
    ready = sorted(key for key, dependencies in incoming.items() if not dependencies)
    visited = 0
    while ready:
        current = ready.pop(0)
        visited += 1
        for key, dependencies in incoming.items():
            if current in dependencies:
                dependencies.remove(current)
                if not dependencies:
                    ready.append(key)
        ready.sort()
    if visited != len(steps):
        raise ValueError("agent plan must be acyclic")


class AgentPlan(FrozenContract):
    """A model proposal. It has no execution authority until compiled and validated."""

    plan_id: UUID
    execution_id: ExecutionId
    role: AgentRole
    goal_ref: ArtifactRef
    steps: tuple[PlanStep, ...]
    proposed_at: AwareDatetime

    @model_validator(mode="after")
    def graph_is_well_formed(self) -> AgentPlan:
        if not self.steps:
            raise ValueError("agent plan must contain at least one step")
        _validate_plan_graph(self.steps)
        for step in self.steps:
            if isinstance(step, PlanDelegationStep):
                if step.task_artifact_ref.workspace_id != self.goal_ref.workspace_id:
                    raise ValueError("delegation task and plan goal must share a workspace")
                if any(
                    item.workspace_id != self.goal_ref.workspace_id for item in step.domain_refs
                ):
                    raise ValueError("delegation refs and plan goal must share a workspace")
        return self


class ValidatedOperation(FrozenContract):
    """One trusted C5-ready operation compiled from a proposal step."""

    node_key: StableId
    operation_id: OperationId
    kind: Literal["tool", "delegation"]
    address: StableId
    depends_on: tuple[StableId, ...]
    parameter_artifact_ref: ArtifactRef
    parameter_sha256: Sha256
    estimated_cost_millicents: int = Field(ge=0)
    authority_sha256: Sha256

    @field_validator("depends_on")
    @classmethod
    def operation_dependencies_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _unique(values, label="validated operation dependencies")
        return values

    @model_validator(mode="after")
    def address_matches_operation_kind(self) -> ValidatedOperation:
        if self.kind == "tool" and self.address.count("@") != 1:
            raise ValueError("validated tool operation must use an exact name@version address")
        if self.kind == "delegation" and "@" in self.address:
            raise ValueError("delegation address is a governed role, not a tool version")
        return self


class ValidatedPlan(FrozenContract):
    """Trusted, bounded, exact-version execution plan accepted by the C5 adapter."""

    plan_id: UUID
    execution_id: ExecutionId
    validated_plan_artifact_ref: ArtifactRef
    proposal_sha256: Sha256
    resource_manifest_sha256: Sha256
    operations: tuple[ValidatedOperation, ...]
    max_parallelism: int = Field(ge=1, le=32)
    estimated_cost_millicents: int = Field(ge=0)
    budget_limit_millicents: int = Field(ge=0)
    budget_mode: Literal["enforced", "record_only"] = "enforced"
    validated_at: AwareDatetime

    @model_validator(mode="after")
    def operations_form_a_bounded_graph(self) -> ValidatedPlan:
        if not self.operations:
            raise ValueError("validated plan must contain at least one operation")
        keys = tuple(item.node_key for item in self.operations)
        _unique(keys, label="validated operation node keys")
        _unique((item.operation_id for item in self.operations), label="operation ids")
        known = set(keys)
        for operation in self.operations:
            if set(operation.depends_on) - known:
                raise ValueError(
                    f"validated operation {operation.node_key!r} has unknown dependencies"
                )
            if operation.node_key in operation.depends_on:
                raise ValueError(
                    f"validated operation {operation.node_key!r} cannot depend on itself"
                )
            if (
                operation.parameter_artifact_ref.workspace_id
                != self.validated_plan_artifact_ref.workspace_id
            ):
                raise ValueError("validated plan parameter artifacts must share a workspace")
        incoming = {operation.node_key: set(operation.depends_on) for operation in self.operations}
        ready = sorted(key for key, dependencies in incoming.items() if not dependencies)
        visited = 0
        while ready:
            current = ready.pop(0)
            visited += 1
            for key, dependencies in incoming.items():
                if current in dependencies:
                    dependencies.remove(current)
                    if not dependencies:
                        ready.append(key)
            ready.sort()
        if visited != len(self.operations):
            raise ValueError("validated plan must be acyclic")
        operation_estimate = sum(
            operation.estimated_cost_millicents for operation in self.operations
        )
        if self.estimated_cost_millicents != operation_estimate:
            raise ValueError("validated plan estimate must equal the sum of operation estimates")
        if (
            self.budget_mode == "enforced"
            and self.estimated_cost_millicents > self.budget_limit_millicents
        ):
            raise ValueError("validated plan estimate exceeds its budget limit")
        return self


class DelegationRequest(FrozenContract):
    """Narrowed child authority and explicit fresh-wake inputs."""

    delegation_id: UUID
    parent_execution_id: ExecutionId
    parent_role: AgentRole
    subagent_role: AgentRole
    task_artifact_ref: ArtifactRef
    granted_paths: tuple[str, ...]
    domain_refs: tuple[DomainObjectRef, ...]
    child_budget_envelope_ref: ArtifactRef
    resource_manifest_ref: ArtifactRef
    resource_manifest_sha256: Sha256
    depth: int = Field(ge=1, le=4)

    @field_validator("granted_paths")
    @classmethod
    def delegation_paths_are_relative(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_virtual_path(value) for value in values)
        _unique(normalized, label="delegation path grants")
        return normalized

    @model_validator(mode="after")
    def child_is_fresh_and_workspace_scoped(self) -> DelegationRequest:
        if self.parent_role is self.subagent_role:
            raise ValueError("delegation must wake a distinct governed role")
        workspace_id = self.task_artifact_ref.workspace_id
        if self.child_budget_envelope_ref.workspace_id != workspace_id:
            raise ValueError("child budget and task must belong to the same workspace")
        if self.resource_manifest_ref.workspace_id != workspace_id:
            raise ValueError("child resource manifest and task must belong to the same workspace")
        if any(item.workspace_id != workspace_id for item in self.domain_refs):
            raise ValueError("delegation domain refs must belong to the task workspace")
        return self


class DelegationResult(FrozenContract):
    """Body-free child completion receipt returned to the parent."""

    delegation_id: UUID
    parent_execution_id: ExecutionId
    child_execution_id: ExecutionId
    status: Literal["completed", "awaiting_input", "blocked", "failed"]
    output_refs: tuple[ArtifactRef, ...] = ()
    domain_refs: tuple[DomainObjectRef, ...] = ()
    finalization_ref: ArtifactRef
    spend_millicents: int = Field(ge=0)
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def successful_child_has_a_durable_output(self) -> DelegationResult:
        if self.child_execution_id == self.parent_execution_id:
            raise ValueError("child execution must be distinct from parent execution")
        if self.status == "completed" and not (self.output_refs or self.domain_refs):
            raise ValueError("completed delegation must return at least one durable reference")
        workspace_id = self.finalization_ref.workspace_id
        if any(item.workspace_id != workspace_id for item in self.output_refs):
            raise ValueError("delegation output refs must share the finalization workspace")
        if any(item.workspace_id != workspace_id for item in self.domain_refs):
            raise ValueError("delegation domain refs must share the finalization workspace")
        return self


class DelegatedFileGrant(FrozenContract):
    """One exact parent file copied by value into a child's read-only context."""

    source_path: str
    materialized_path: str
    artifact_ref: ArtifactRef

    @field_validator("source_path")
    @classmethod
    def source_is_relative(cls, value: str) -> str:
        return normalize_virtual_path(value)

    @field_validator("materialized_path")
    @classmethod
    def materialization_is_read_only(cls, value: str) -> str:
        normalized = normalize_virtual_path(value)
        if not normalized.startswith("context/delegated/"):
            raise ValueError("delegated files must materialize below context/delegated/")
        return normalized


class SpecialistTaskEnvelope(FrozenContract):
    """Typed, immutable fresh-wake task body for a C6.6 specialist.

    Small inputs are preserved verbatim. Canonical files are copied to artifacts and described by
    exact path/digest refs. Domain state remains a typed ref. A child never receives a prose
    paraphrase in place of an available original.
    """

    schema_version: Literal["1"] = "1"
    role: Literal[
        AgentRole.RESEARCH,
        AgentRole.CONTENT_DRAFTER,
        AgentRole.REVIEWER,
        AgentRole.RESEARCH_CLAIMS,
        AgentRole.RESEARCH_NARRATIVE,
    ]
    goal: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048)]
    instructions: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=8_192),
    ]
    verbatim_context: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=16_384)], ...
    ] = ()
    file_grants: tuple[DelegatedFileGrant, ...] = ()
    domain_refs: tuple[DomainObjectRef, ...] = ()
    required_output_path: str

    @field_validator("required_output_path")
    @classmethod
    def output_is_role_scoped(cls, value: str) -> str:
        normalized = normalize_virtual_path(value)
        if not normalized.startswith("outputs/"):
            raise ValueError("specialist output must be written below outputs/")
        return normalized

    @model_validator(mode="after")
    def refs_and_grants_are_scoped_and_unique(self) -> SpecialistTaskEnvelope:
        workspace_ids = {
            *(item.artifact_ref.workspace_id for item in self.file_grants),
            *(item.workspace_id for item in self.domain_refs),
        }
        if len(workspace_ids) > 1:
            raise ValueError("specialist task refs must share one workspace")
        _unique((item.source_path for item in self.file_grants), label="delegated source paths")
        _unique(
            (item.materialized_path for item in self.file_grants),
            label="delegated materialized paths",
        )
        _unique(
            (f"{item.object_type}:{item.object_id}:{item.version}" for item in self.domain_refs),
            label="specialist domain refs",
        )
        return self


class ContextLayer(StrEnum):
    L1_IDENTITY = "l1_identity"
    L2_WORKSPACE_PRODUCT = "l2_workspace_product"
    L3_PROJECT = "l3_project"
    L4_MEMORY = "l4_memory"
    L5_FOCUS = "l5_focus"
    L6_CONVERSATION = "l6_conversation"
    L7_TURN = "l7_turn"


_CONTEXT_LAYER_ORDER = tuple(ContextLayer)


class ContextLayerManifest(FrozenContract):
    layer: ContextLayer
    source_refs: tuple[DomainObjectRef | ArtifactRef, ...] = ()
    materialized_paths: tuple[str, ...] = ()
    content_sha256s: tuple[Sha256, ...] = ()
    token_count: int = Field(ge=0)
    excluded_refs: tuple[DomainObjectRef | ArtifactRef, ...] = ()
    exclusion_reason_codes: tuple[ReasonCode, ...] = ()

    @field_validator("materialized_paths")
    @classmethod
    def context_paths_are_relative(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_virtual_path(value) for value in values)
        if any(
            not value.startswith(("context/", "inputs/", ".deepagent/")) for value in normalized
        ):
            raise ValueError("context materializations must stay in read-only runtime prefixes")
        _unique(normalized, label="context materialized paths")
        return normalized

    @model_validator(mode="after")
    def exclusions_have_reason_codes(self) -> ContextLayerManifest:
        if bool(self.excluded_refs) != bool(self.exclusion_reason_codes):
            raise ValueError("excluded context refs and reason codes must be present together")
        return self


class ContextBundleManifest(FrozenContract):
    """Durable body-free receipt for the deterministic seven-layer opening context."""

    context_bundle_id: UUID
    execution_id: ExecutionId
    schema_version: Literal["1"]
    layers: tuple[ContextLayerManifest, ...]
    aggregate_sha256: Sha256
    assembled_at: AwareDatetime

    @model_validator(mode="after")
    def exactly_seven_ordered_layers(self) -> ContextBundleManifest:
        actual = tuple(item.layer for item in self.layers)
        if actual != _CONTEXT_LAYER_ORDER:
            raise ValueError("context bundle must contain exactly L1-L7 in canonical order")
        return self


class FinalizeStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_INPUT = "awaiting_input"
    BLOCKED = "blocked"
    FAILED = "failed"


class AgentFinalizeEnvelope(FrozenContract):
    """The only honest terminal envelope; normal model termination is not success."""

    finalization_id: UUID
    execution_id: ExecutionId
    status: FinalizeStatus
    user_message_artifact_ref: ArtifactRef | None = None
    output_refs: tuple[ArtifactRef, ...] = ()
    domain_refs: tuple[DomainObjectRef, ...] = ()
    open_gate_refs: tuple[DomainObjectRef, ...] = ()
    assumption_refs: tuple[ArtifactRef, ...] = ()
    next_action_refs: tuple[ArtifactRef, ...] = ()
    failure_code: ReasonCode | None = None
    finalized_at: AwareDatetime

    @model_validator(mode="after")
    def terminal_shape_is_honest(self) -> AgentFinalizeEnvelope:
        if self.status is FinalizeStatus.COMPLETED:
            if self.user_message_artifact_ref is None:
                raise ValueError("completed turn must have a durable user-message artifact")
            if self.failure_code is not None:
                raise ValueError("completed turn cannot carry a failure code")
        elif self.status is FinalizeStatus.FAILED:
            if self.failure_code is None:
                raise ValueError("failed turn must carry a stable failure code")
        elif self.failure_code is not None:
            raise ValueError("only failed turns may carry a failure code")

        if self.status in {FinalizeStatus.AWAITING_INPUT, FinalizeStatus.BLOCKED} and not (
            self.open_gate_refs or self.next_action_refs
        ):
            raise ValueError("non-terminal progress status must identify a gate or next action")
        return self
