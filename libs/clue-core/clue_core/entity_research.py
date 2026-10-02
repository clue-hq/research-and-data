"""M8D R0 contracts for account/contact research agents and shared fleet execution.

This module deliberately contains no runtime, provider, database, or agent construction code.  It
freezes the shapes later M8D slices must implement and makes the superseded orchestration shapes
unrepresentable in contract fixtures.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core.field import (
    ACCOUNT_AXIS_FIELD_CLASSES,
    classify_field_key,
    is_valid_field_key,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]


def _assert_field_axis(
    subject_type: ResearchSubjectType, field_keys: tuple[str, ...], *, context: str
) -> None:
    """Refuse a field the named subject axis does not own.

    The account axis is the shared field-class projection (``ACCOUNT_AXIS_FIELD_CLASSES`` —
    CORE | ACCOUNT | ACCOUNT_RESONANCE | PACK), not a raw ``account.`` prefix: an account's
    firmographic facts (``core.industry``, ``core.primary_tech_stack``, …) are organization-level
    truth and belong to account research.  Contact and contact-facet fields remain outside it.
    The contact axis keeps its literal prefix, so a ``core.*``/``account.*`` field can never be
    smuggled into contact work.
    """

    if subject_type is ResearchSubjectType.ACCOUNT:
        outside = any(
            not is_valid_field_key(field_key)
            or classify_field_key(field_key) not in ACCOUNT_AXIS_FIELD_CLASSES
            for field_key in field_keys
        )
    else:
        prefix = f"{subject_type.value}."
        outside = any(not field_key.startswith(prefix) for field_key in field_keys)
    if outside:
        raise ValueError(f"{context} contains a field outside the {subject_type.value} axis")


class ResearchSubjectType(StrEnum):
    ACCOUNT = "account"
    CONTACT = "contact"


class ResearchComponentClass(StrEnum):
    PLATFORM_DEEPAGENT = "platform_deepagent"
    FLEET_SHELL = "fleet_shell"
    JOB_CONTROLLER = "job_controller"
    ENTITY_AGENT = "entity_agent"
    FACET_AGENT = "facet_agent"
    ENGINE_SERVICE = "engine_service"


class AgentFramework(StrEnum):
    DEEPAGENTS_CREATE_DEEP_AGENT = "deepagents.create_deep_agent"
    LANGCHAIN_CREATE_AGENT = "langchain.agents.create_agent"


class ResearchRunKind(StrEnum):
    ACCOUNT_RESEARCH = "account_research"
    CONTACT_RESEARCH = "contact_research"


class ResearchOperationKind(StrEnum):
    ACCOUNT_PROFILE = "account_profile"
    COMMITTEE_DISCOVERY = "committee_discovery"
    CONTACT_RESEARCH = "contact_research"


class ResearchSelectionBasis(StrEnum):
    ACCOUNT_SELECTION = "account_selection"
    COMMITTEE_MEMBER = "committee_member"
    USER_SELECTED_ASSOCIATED_CONTACT = "user_selected_associated_contact"


class ResearchFieldOutcome(StrEnum):
    FOUND = "found"
    NULL = "null"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    REJECTED = "rejected"


class ResearchClaimDelta(StrEnum):
    ACCEPTED = "accepted"
    CORROBORATING = "corroborating"
    CONFLICTING = "conflicting"
    REJECTED = "rejected"
    NONE = "none"


class ResearchResultDelivery(StrEnum):
    INLINE_COMPLETE = "inline_complete"
    INDEXED_COMPLETE = "indexed_complete"


class ResearchFollowUpReason(StrEnum):
    NEW_ANGLE = "new_angle"
    EVIDENCE_VERIFICATION = "evidence_verification"
    CONTRADICTION_RESOLUTION = "contradiction_resolution"
    IDENTITY_DISAMBIGUATION = "identity_disambiguation"
    REMAINING_GAP = "remaining_gap"


class ResearchFinalizationOutcome(StrEnum):
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    NEEDS_REVIEW = "needs_review"
    BUDGET_STOPPED = "budget_stopped"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ResearchJobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    TERMINAL = "terminal"


class ParallelCallPurpose(StrEnum):
    INDEPENDENT_SOURCE = "independent_source"
    FACET = "facet"
    CORROBORATION = "corroboration"


class ContactChannel(StrEnum):
    EMAIL = "email"
    PHONE = "phone"


class ResearchComponentContract(BaseModel):
    """One declared component and the authority its class is allowed to hold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: NonEmptyStr
    component_class: ResearchComponentClass
    framework: AgentFramework | None = None
    subject_type: ResearchSubjectType | None = None
    chooses_research_tools: bool = False
    dispatches_provider_requests: bool = False

    @model_validator(mode="after")
    def _component_authority(self) -> Self:
        if self.component_class is ResearchComponentClass.PLATFORM_DEEPAGENT:
            if self.framework is not AgentFramework.DEEPAGENTS_CREATE_DEEP_AGENT:
                raise ValueError("platform deepagent must use deepagents.create_deep_agent")
            if self.subject_type is not None:
                raise ValueError("platform deepagent is not an entity research subject")
        elif self.component_class in {
            ResearchComponentClass.ENTITY_AGENT,
            ResearchComponentClass.FACET_AGENT,
        }:
            if self.framework is not AgentFramework.LANGCHAIN_CREATE_AGENT:
                raise ValueError("entity and facet agents must use langchain.agents.create_agent")
            if self.subject_type is None:
                raise ValueError("entity and facet agents require one research subject type")
            if not self.chooses_research_tools:
                raise ValueError("entity and facet agents own bounded research-tool choice")
            if self.dispatches_provider_requests:
                raise ValueError("agents may request governed tools but never dispatch providers")
        else:
            if self.framework is not None:
                raise ValueError(
                    "mechanical and engine components cannot declare an agent framework"
                )
            if self.subject_type is not None:
                raise ValueError("shared mechanical and engine components are subject-neutral")
            if self.chooses_research_tools:
                raise ValueError("fleet, controllers, and engines cannot choose research tools")

        if (
            self.component_class
            in {
                ResearchComponentClass.FLEET_SHELL,
                ResearchComponentClass.JOB_CONTROLLER,
            }
            and self.dispatches_provider_requests
        ):
            raise ValueError("fleet shell and job controllers cannot dispatch provider requests")
        if (
            self.dispatches_provider_requests
            and self.component_class is not ResearchComponentClass.ENGINE_SERVICE
        ):
            raise ValueError("only a governed engine service may dispatch provider requests")
        return self


_ACCOUNT_REQUIRED_TOOLS = frozenset(
    {
        "read_account_research_state",
        "research_account_deep",
        "enrich_account",
        "inspect_account_evidence",
        "discover_buying_committee",
        "record_committee_role_inferences",
        "assess_account_coverage",
        "read_research_result",
        "read_evidence",
        "finalize_account_research",
    }
)
_CONTACT_REQUIRED_TOOLS = frozenset(
    {
        "read_contact_research_state",
        "research_contact_deep",
        "enrich_contact",
        "inspect_contact_evidence",
        "assess_contact_coverage",
        "read_research_result",
        "read_evidence",
        "finalize_contact_research",
    }
)


class EntityAgentToolSurface(BaseModel):
    """Minimal semantic tool surface for one entity-agent class."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_type: ResearchSubjectType
    tool_names: tuple[NonEmptyStr, ...]
    exposes_provider_sdk: bool = False

    @model_validator(mode="after")
    def _surface_is_complete(self) -> Self:
        if len(self.tool_names) != len(set(self.tool_names)):
            raise ValueError("entity-agent tool names must be unique")
        names = frozenset(self.tool_names)
        if "research_account_gaps" in names:
            raise ValueError("research_account_gaps is a superseded entity-agent tool")
        required = (
            _ACCOUNT_REQUIRED_TOOLS
            if self.subject_type is ResearchSubjectType.ACCOUNT
            else _CONTACT_REQUIRED_TOOLS
        )
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"entity-agent tool surface is incomplete: {missing}")
        allowed = set(required)
        if self.subject_type is ResearchSubjectType.ACCOUNT:
            allowed.add("delegate_account_facet")
        else:
            allowed.update(
                {
                    "delegate_contact_facet",
                    "reveal_contact_channel",
                    "validate_contact_channel",
                }
            )
        unknown = sorted(names - allowed)
        if unknown:
            raise ValueError(f"entity-agent tool surface contains ungoverned tools: {unknown}")
        if self.exposes_provider_sdk:
            raise ValueError("entity agents receive governed semantic tools, never provider SDKs")
        if {"reveal_contact_channel", "validate_contact_channel"}.intersection(names) and not {
            "reveal_contact_channel",
            "validate_contact_channel",
        }.issubset(names):
            raise ValueError("contact channel observation and validation tools must be paired")
        return self


class EntityResearchAuthorityContract(BaseModel):
    """Closed component and surface manifest frozen by M8D R0."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["m8d-r0-v1"]
    components: tuple[ResearchComponentContract, ...]
    tool_surfaces: tuple[EntityAgentToolSurface, ...]

    @model_validator(mode="after")
    def _manifest_is_complete(self) -> Self:
        ids = [item.component_id for item in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component ids must be unique")
        if (
            sum(
                item.component_class is ResearchComponentClass.FLEET_SHELL
                for item in self.components
            )
            != 1
        ):
            raise ValueError("account and contact runs must share exactly one fleet shell")
        entity_agents = [
            item
            for item in self.components
            if item.component_class is ResearchComponentClass.ENTITY_AGENT
        ]
        entity_subjects = {item.subject_type for item in entity_agents}
        if len(entity_agents) != 2 or entity_subjects != {
            ResearchSubjectType.ACCOUNT,
            ResearchSubjectType.CONTACT,
        }:
            raise ValueError("manifest requires one account and one contact entity-agent class")
        if (
            len(self.tool_surfaces) != 2
            or {item.subject_type for item in self.tool_surfaces} != entity_subjects
        ):
            raise ValueError("every entity-agent class requires one matching tool surface")
        if (
            sum(
                item.component_class is ResearchComponentClass.PLATFORM_DEEPAGENT
                for item in self.components
            )
            != 1
        ):
            raise ValueError("manifest requires exactly one user-facing platform deepagent")
        if (
            sum(
                item.component_class is ResearchComponentClass.JOB_CONTROLLER
                for item in self.components
            )
            != 1
        ):
            raise ValueError("manifest requires exactly one subject-neutral job controller")
        if not any(
            item.component_class is ResearchComponentClass.ENGINE_SERVICE
            and item.dispatches_provider_requests
            for item in self.components
        ):
            raise ValueError("manifest requires a governed provider-dispatch engine service")
        return self


class SelectedResearchSubject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_entity_id: UUID
    basis: ResearchSelectionBasis
    strong_identity_claim_refs: tuple[NonEmptyStr, ...] = ()
    association_evidence_refs: tuple[NonEmptyStr, ...] = ()
    committee_claim_refs: tuple[NonEmptyStr, ...] = ()
    contact_authority: SelectedContactResearchAuthority | None = None


class FieldSourceAuthority(BaseModel):
    """Exact source keys authorized for one selected/requested field.

    R0 previously stored fields and sources as independent sets.  That admitted an invalid
    cross-product: a source selected for field A could be submitted for field B.  This value is the
    executable relation.  Strategy labels are intentionally absent; an agent chooses a semantic
    tool and an exact source, while the frozen effective source plan remains the authority.

    ``source_keys`` may be **empty**: an admitted field that no authorized source can actually
    request (a source may *own* a field under the §3.1 contract while its pinned provider action
    has no wire parameter for it) is born with no authority at all.  That is the honest
    disposition, not a defect — every source is then unauthorized for the field, so the engine
    refuses any request for it and the execution-completeness reader treats it as exhausted, i.e.
    an honest gap that settles ``needs_review`` instead of an obligation nothing can discharge.
    The launcher, not this contract, decides when that is correct.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: NonEmptyStr
    source_keys: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _sources_are_unique(self) -> Self:
        if len(self.source_keys) != len(set(self.source_keys)):
            raise ValueError("field source authority cannot repeat a source")
        return self


class SelectedContactResearchAuthority(BaseModel):
    """The exact per-contact projection of one durable contact-selection target.

    A contact run may legitimately choose different questions, facets, channels, or budgets for
    two people.  Keeping those values only on the run-wide selection would authorize every job to
    consume the union.  R7 therefore freezes the target-local authority here; the run-wide fields
    remain an index whose values must equal the exact union of these subject projections.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_selection_ref: NonEmptyStr
    contact_selection_sha256: Sha256
    contact_intent_ref: NonEmptyStr
    contact_intent_sha256: Sha256
    field_plan_ref: NonEmptyStr
    source_plan_ref: NonEmptyStr
    admitted_field_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    admitted_source_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    field_source_authority: tuple[FieldSourceAuthority, ...] = Field(min_length=1)
    research_questions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    facet_keys: tuple[NonEmptyStr, ...] = ()
    channel_permissions: tuple[ContactChannel, ...] = ()
    channel_source_keys: tuple[NonEmptyStr, ...] = ()
    policy_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    budget_envelope_ref: NonEmptyStr
    budget_cap_cents: Decimal = Field(ge=0)
    approval_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _exact_target_authority(self) -> Self:
        for values, message in (
            (self.admitted_field_keys, "contact target fields must be unique"),
            (self.admitted_source_keys, "contact target sources must be unique"),
            (self.research_questions, "contact target questions must be unique"),
            (self.facet_keys, "contact target facets must be unique"),
            (self.channel_permissions, "contact target channels must be unique"),
            (self.channel_source_keys, "contact target channel sources must be unique"),
            (self.policy_refs, "contact target policy references must be unique"),
            (self.approval_refs, "contact target approval references must be unique"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(message)
        _assert_field_axis(
            ResearchSubjectType.CONTACT,
            self.admitted_field_keys,
            context="selected contact target",
        )
        authority_fields = tuple(item.field_key for item in self.field_source_authority)
        if len(authority_fields) != len(set(authority_fields)):
            raise ValueError("contact target field source authority must be unique by field")
        if set(authority_fields) != set(self.admitted_field_keys):
            raise ValueError("contact target source authority must cover every admitted field")
        sources = {
            source_key for item in self.field_source_authority for source_key in item.source_keys
        }
        if sources != set(self.admitted_source_keys):
            raise ValueError("contact target sources differ from its field source authority")
        return self


class SealedDiscoveryLaunchReceipt(BaseModel):
    """Immutable discovery authority pinned when an Account fleet is launched.

    The receipt names the exact sealed generation and both stored membership artifacts.  It is
    intentionally carried inside the already-versioned selection JSON: newly launched Account
    jobs can consume immutable launch authority without changing historical job rows or inventing
    a second mutable pointer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_batch_id: UUID
    discovery_generation: int = Field(ge=1)
    discovery_seal_sha256: Sha256
    account_manifest_ref: NonEmptyStr
    account_manifest_sha256: Sha256
    claim_manifest_ref: NonEmptyStr
    claim_manifest_sha256: Sha256


class EntityResearchSelection(BaseModel):
    """Exact user-confirmed account/contact set for one separately launched run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selection_id: UUID
    # Object-spine identifiers are opaque text, not entity UUIDs.  Their authoritative
    # workspace/project/product tables use text primary keys.
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    product_id: NonEmptyStr
    project_run_id: UUID
    subject_type: ResearchSubjectType
    # Compatibility: historical Account authorizations predate the launch-pinned seal receipt and
    # must remain readable. The Account launcher requires this for every new selection; contact
    # selections have no discovery authority and therefore keep it absent.
    discovery_receipt: SealedDiscoveryLaunchReceipt | None = None
    account_entity_id: UUID | None = None
    subjects: tuple[SelectedResearchSubject, ...] = Field(min_length=1)
    directive_ref: NonEmptyStr
    directive_sha256: Sha256
    field_plan_ref: NonEmptyStr
    source_plan_ref: NonEmptyStr
    admitted_field_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    admitted_source_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    field_source_authority: tuple[FieldSourceAuthority, ...] = Field(min_length=1)
    committee_source_keys: tuple[NonEmptyStr, ...] = ()
    # Account research can be fully bounded by its exact field/source authority. Directional
    # questions are optional there; the validator below keeps them mandatory for contact runs,
    # where the question is part of the personal-research authorization.
    research_questions: tuple[NonEmptyStr, ...] = ()
    facet_keys: tuple[NonEmptyStr, ...] = ()
    channel_permissions: tuple[ContactChannel, ...] = ()
    policy_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    budget_envelope_ref: NonEmptyStr
    approval_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    confirmed_by: NonEmptyStr
    confirmed_at: datetime

    @model_validator(mode="after")
    def _selection_scope(self) -> Self:
        subject_ids = [subject.subject_entity_id for subject in self.subjects]
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("selected research subjects must be unique")
        for values, message in (
            (self.admitted_field_keys, "selected research fields must be unique"),
            (self.admitted_source_keys, "selected research sources must be unique"),
            (self.committee_source_keys, "selected committee sources must be unique"),
            (self.research_questions, "selected research questions must be unique"),
            (self.facet_keys, "selected contact facets must be unique"),
            (self.channel_permissions, "selected channel permissions must be unique"),
            (self.policy_refs, "selected policy references must be unique"),
            (self.approval_refs, "selected approval references must be unique"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(message)
        if self.confirmed_at.utcoffset() is None:
            raise ValueError("selection confirmation time must be timezone-aware")
        if self.subject_type is ResearchSubjectType.CONTACT and not self.research_questions:
            raise ValueError("contact research selection requires directional questions")
        if self.subject_type is ResearchSubjectType.ACCOUNT:
            if self.account_entity_id is not None:
                raise ValueError("account selection subjects are their own account identities")
            if any(
                subject.basis is not ResearchSelectionBasis.ACCOUNT_SELECTION
                for subject in self.subjects
            ):
                raise ValueError("account research subjects require account_selection basis")
            if self.channel_permissions:
                raise ValueError("account research selection cannot authorize contact channels")
            if any(
                subject.strong_identity_claim_refs
                or subject.association_evidence_refs
                or subject.committee_claim_refs
                for subject in self.subjects
            ):
                raise ValueError("account selection cannot carry contact identity evidence")
            if any(subject.contact_authority is not None for subject in self.subjects):
                raise ValueError("account selection cannot carry contact target authority")
        else:
            if self.discovery_receipt is not None:
                raise ValueError("contact selection cannot carry Account discovery authority")
            if self.committee_source_keys:
                raise ValueError("contact selection cannot authorize committee enumeration")
            if self.account_entity_id is None:
                raise ValueError("contact selection requires the exact parent account")
            for subject in self.subjects:
                if subject.basis is ResearchSelectionBasis.ACCOUNT_SELECTION:
                    raise ValueError("contact selection requires a contact selection basis")
                if not subject.strong_identity_claim_refs:
                    raise ValueError("selected contacts require strong identity evidence")
                if not subject.association_evidence_refs:
                    raise ValueError("selected contacts require exact-account association evidence")
                if (
                    subject.basis is ResearchSelectionBasis.COMMITTEE_MEMBER
                    and not subject.committee_claim_refs
                ):
                    raise ValueError("committee-selected contacts require committee claim evidence")
                if subject.contact_authority is None:
                    raise ValueError("selected contacts require exact target research authority")
        _assert_field_axis(
            self.subject_type,
            self.admitted_field_keys,
            context="entity research selection",
        )
        authority_fields = tuple(item.field_key for item in self.field_source_authority)
        if len(authority_fields) != len(set(authority_fields)):
            raise ValueError("selected field source authority must be unique by field")
        if set(authority_fields) != set(self.admitted_field_keys):
            raise ValueError("selected field source authority must cover every admitted field")
        authority_sources = {
            source_key for item in self.field_source_authority for source_key in item.source_keys
        }
        if authority_sources | set(self.committee_source_keys) != set(self.admitted_source_keys):
            raise ValueError(
                "selected sources must equal field authority plus committee source authority"
            )
        if self.subject_type is ResearchSubjectType.CONTACT:
            target_authorities = tuple(
                subject.contact_authority
                for subject in self.subjects
                if subject.contact_authority is not None
            )

            def union(attribute: str) -> tuple[object, ...]:
                return tuple(
                    dict.fromkeys(
                        value
                        for authority in target_authorities
                        for value in getattr(authority, attribute)
                    )
                )

            target_field_sources: dict[str, list[str]] = {}
            for authority in target_authorities:
                for item in authority.field_source_authority:
                    source_values = target_field_sources.setdefault(item.field_key, [])
                    source_values.extend(
                        source for source in item.source_keys if source not in source_values
                    )
            global_field_sources = {
                item.field_key: item.source_keys for item in self.field_source_authority
            }
            if global_field_sources != {
                field_key: tuple(source_keys)
                for field_key, source_keys in target_field_sources.items()
            }:
                raise ValueError(
                    "contact run field source authority differs from the exact target union"
                )
            for attribute, global_values in (
                ("admitted_field_keys", self.admitted_field_keys),
                ("admitted_source_keys", self.admitted_source_keys),
                ("research_questions", self.research_questions),
                ("facet_keys", self.facet_keys),
                ("channel_permissions", self.channel_permissions),
                ("policy_refs", self.policy_refs),
                ("approval_refs", self.approval_refs),
            ):
                if set(union(attribute)) != set(global_values):
                    raise ValueError(f"contact run {attribute} differs from the exact target union")
        return self


class EntityResearchJobAuthorization(BaseModel):
    """One job projected from, and unable to widen, its exact selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: UUID
    research_run_id: UUID
    subject_type: ResearchSubjectType
    subject_entity_id: UUID
    parent_account_id: UUID | None = None
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    product_id: NonEmptyStr
    project_run_id: UUID
    selection: EntityResearchSelection
    agent_profile_ref: NonEmptyStr
    agent_profile_sha256: Sha256
    checkpoint_thread_id: NonEmptyStr
    attempt_id: UUID
    lease_id: UUID

    @model_validator(mode="after")
    def _job_is_selected(self) -> Self:
        if self.subject_type is not self.selection.subject_type:
            raise ValueError("job subject type differs from its selection")
        job_scope = (self.workspace_id, self.project_id, self.product_id, self.project_run_id)
        selection_scope = (
            self.selection.workspace_id,
            self.selection.project_id,
            self.selection.product_id,
            self.selection.project_run_id,
        )
        if job_scope != selection_scope:
            raise ValueError("entity job scope differs from its exact selection")
        selected = {item.subject_entity_id for item in self.selection.subjects}
        if self.subject_entity_id not in selected:
            raise ValueError("entity job target is not present in the exact selection")
        if self.subject_type is ResearchSubjectType.CONTACT:
            if self.parent_account_id != self.selection.account_entity_id:
                raise ValueError("contact job requires its selection's exact parent account")
        elif self.parent_account_id is not None:
            raise ValueError("account job cannot carry a contact parent account")
        return self

    @property
    def selected_subject(self) -> SelectedResearchSubject:
        return next(
            subject
            for subject in self.selection.subjects
            if subject.subject_entity_id == self.subject_entity_id
        )

    @property
    def effective_contact_authority(self) -> SelectedContactResearchAuthority | None:
        return self.selected_subject.contact_authority

    @property
    def effective_admitted_field_keys(self) -> tuple[str, ...]:
        authority = self.effective_contact_authority
        return (
            self.selection.admitted_field_keys
            if authority is None
            else authority.admitted_field_keys
        )

    @property
    def effective_admitted_source_keys(self) -> tuple[str, ...]:
        authority = self.effective_contact_authority
        return (
            self.selection.admitted_source_keys
            if authority is None
            else authority.admitted_source_keys
        )

    @property
    def effective_field_source_authority(self) -> tuple[FieldSourceAuthority, ...]:
        authority = self.effective_contact_authority
        return (
            self.selection.field_source_authority
            if authority is None
            else authority.field_source_authority
        )

    @property
    def effective_research_questions(self) -> tuple[str, ...]:
        authority = self.effective_contact_authority
        return (
            self.selection.research_questions if authority is None else authority.research_questions
        )

    @property
    def effective_facet_keys(self) -> tuple[str, ...]:
        authority = self.effective_contact_authority
        return self.selection.facet_keys if authority is None else authority.facet_keys

    @property
    def effective_channel_permissions(self) -> tuple[ContactChannel, ...]:
        authority = self.effective_contact_authority
        return (
            self.selection.channel_permissions
            if authority is None
            else authority.channel_permissions
        )

    @property
    def effective_channel_source_keys(self) -> tuple[str, ...]:
        authority = self.effective_contact_authority
        return () if authority is None else authority.channel_source_keys

    @property
    def effective_policy_refs(self) -> tuple[str, ...]:
        authority = self.effective_contact_authority
        return self.selection.policy_refs if authority is None else authority.policy_refs

    @property
    def effective_budget_envelope_ref(self) -> str:
        authority = self.effective_contact_authority
        return (
            self.selection.budget_envelope_ref
            if authority is None
            else authority.budget_envelope_ref
        )

    @property
    def effective_approval_refs(self) -> tuple[str, ...]:
        authority = self.effective_contact_authority
        return self.selection.approval_refs if authority is None else authority.approval_refs


class ResearchRunLifecycleContract(BaseModel):
    """Separately confirmed account/contact run with no automatic successor run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    run_kind: ResearchRunKind
    selection: EntityResearchSelection
    user_confirmed_launch: bool
    operations: tuple[ResearchOperationKind, ...]
    automatic_successor_run: bool = False

    @model_validator(mode="after")
    def _lifecycle_is_separate(self) -> Self:
        if not self.user_confirmed_launch:
            raise ValueError("entity research runs require an explicit user-confirmed launch")
        if self.automatic_successor_run:
            raise ValueError(
                "account and contact research runs cannot launch successors automatically"
            )
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("entity research run operations must be unique")
        operation_set = frozenset(self.operations)
        if self.run_kind is ResearchRunKind.ACCOUNT_RESEARCH:
            if self.selection.subject_type is not ResearchSubjectType.ACCOUNT:
                raise ValueError("account run requires an account selection")
            if ResearchOperationKind.CONTACT_RESEARCH in operation_set:
                raise ValueError("account research run cannot perform contact deep research")
            if ResearchOperationKind.ACCOUNT_PROFILE not in operation_set:
                raise ValueError("account run requires account profiling")
            committee_planned = ResearchOperationKind.COMMITTEE_DISCOVERY in operation_set
            committee_authorized = bool(self.selection.committee_source_keys)
            if committee_planned != committee_authorized:
                raise ValueError(
                    "account run committee operation must match committee source authority"
                )
        else:
            if self.selection.subject_type is not ResearchSubjectType.CONTACT:
                raise ValueError("contact run requires a contact selection")
            if operation_set != {ResearchOperationKind.CONTACT_RESEARCH}:
                raise ValueError("contact run contains account-owned operations")
        return self


class PlannedSourceAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: NonEmptyStr


class FieldResearchSourcePlan(BaseModel):
    """Executable attempts compiled only from sources applicable to one field/question."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: NonEmptyStr
    applicable_source_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    attempts: tuple[PlannedSourceAttempt, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _attempts_are_applicable(self) -> Self:
        allowed = frozenset(self.applicable_source_keys)
        if len(allowed) != len(self.applicable_source_keys):
            raise ValueError("applicable field sources must be unique")
        attempt_keys = [attempt.source_key for attempt in self.attempts]
        if len(attempt_keys) != len(set(attempt_keys)):
            raise ValueError("field research attempts must be unique")
        for attempt in self.attempts:
            if attempt.source_key not in allowed:
                raise ValueError(
                    "field research attempt names a source absent from the effective source plan"
                )
        return self


class GovernedResearchToolRequest(BaseModel):
    """Provider-neutral request journaled before an engine may reserve external work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: UUID
    job_id: UUID
    subject_type: ResearchSubjectType
    target_entity_id: UUID
    parent_account_id: UUID | None = None
    agent_turn_id: UUID
    agent_execution_id: UUID
    tool_call_id: UUID
    tool_name: NonEmptyStr
    tool_version: int = Field(ge=1)
    tool_input_sha256: Sha256
    field_plan_ref: NonEmptyStr
    source_plan_ref: NonEmptyStr
    field_keys: tuple[NonEmptyStr, ...] = ()
    source_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    field_source_authority: tuple[FieldSourceAuthority, ...] = ()
    questions: tuple[NonEmptyStr, ...] = ()
    budget_reservation_key: NonEmptyStr
    idempotency_key: NonEmptyStr
    parent_operation_ref: NonEmptyStr | None = None
    parent_observation_ref: NonEmptyStr | None = None
    follow_up_reason: ResearchFollowUpReason | None = None
    prior_result_sha256: Sha256 | None = None
    prior_research_context: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _request_is_exact(self) -> Self:
        for values, message in (
            (self.field_keys, "tool request field keys must be unique"),
            (self.source_keys, "tool request source keys must be unique"),
            (self.questions, "tool request questions must be unique"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(message)
        if self.subject_type is ResearchSubjectType.CONTACT and not self.questions:
            raise ValueError("contact research request requires directional questions")
        if self.subject_type is ResearchSubjectType.CONTACT:
            if self.parent_account_id is None:
                raise ValueError("contact tool request requires the exact parent account")
        elif self.parent_account_id is not None:
            raise ValueError("account tool request cannot carry a contact parent account")
        allowed_tools = (
            _ACCOUNT_REQUIRED_TOOLS | {"delegate_account_facet"}
            if self.subject_type is ResearchSubjectType.ACCOUNT
            else _CONTACT_REQUIRED_TOOLS
            | {
                "delegate_contact_facet",
                "reveal_contact_channel",
                "validate_contact_channel",
            }
        )
        if self.tool_name not in allowed_tools:
            raise ValueError("tool request is outside its entity-agent semantic tool surface")
        if self.tool_name == "discover_buying_committee":
            if self.subject_type is not ResearchSubjectType.ACCOUNT:
                raise ValueError("committee discovery requires an account research job")
            if self.field_keys or self.field_source_authority:
                raise ValueError(
                    "committee discovery enumerates contacts and cannot manufacture account fields"
                )
        else:
            if not self.field_keys:
                raise ValueError("field-producing research tool requires selected fields")
            _assert_field_axis(self.subject_type, self.field_keys, context="governed tool request")
            authority_fields = tuple(item.field_key for item in self.field_source_authority)
            if len(authority_fields) != len(set(authority_fields)):
                raise ValueError("tool field source authority must be unique by field")
            if set(authority_fields) != set(self.field_keys):
                raise ValueError("tool field source authority must cover every requested field")
            authority_sources = {
                source_key
                for item in self.field_source_authority
                for source_key in item.source_keys
            }
            if authority_sources != set(self.source_keys):
                raise ValueError("tool sources must equal the union of per-field source authority")
        lineage = (
            self.parent_operation_ref,
            self.parent_observation_ref,
            self.follow_up_reason,
            self.prior_result_sha256,
            self.prior_research_context,
        )
        if any(value is not None for value in lineage) and not all(
            value is not None for value in lineage
        ):
            raise ValueError(
                "follow-up tool request requires parent lineage and exact prior research context"
            )
        return self


class ResearchEvidenceProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_ref: NonEmptyStr
    source_key: NonEmptyStr
    provider_source_id: NonEmptyStr | None = None
    source_url: NonEmptyStr | None = None
    artifact_ref: NonEmptyStr
    evidence_span: NonEmptyStr

    @model_validator(mode="after")
    def _evidence_has_source_identity(self) -> Self:
        if self.provider_source_id is None and self.source_url is None:
            raise ValueError("evidence requires a provider source id or source URL")
        return self


class ResearchFieldResultProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: NonEmptyStr
    outcome: ResearchFieldOutcome
    value: JsonValue | None = None
    value_ref: NonEmptyStr | None = None
    claim_delta: ResearchClaimDelta
    claim_refs: tuple[NonEmptyStr, ...] = ()
    decision_refs: tuple[NonEmptyStr, ...] = ()
    evidence: tuple[ResearchEvidenceProjection, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_status: NonEmptyStr

    @model_validator(mode="after")
    def _field_outcome_is_honest(self) -> Self:
        if self.outcome is ResearchFieldOutcome.FOUND:
            if self.value is None and self.value_ref is None:
                raise ValueError("found field requires a complete value or durable value reference")
            if not self.evidence:
                raise ValueError("found field requires retained evidence")
        if self.outcome in {ResearchFieldOutcome.NULL, ResearchFieldOutcome.UNSUPPORTED}:
            if self.value is not None or self.value_ref is not None:
                raise ValueError("null/unsupported field cannot carry a value")
            if self.claim_delta is not ResearchClaimDelta.NONE:
                raise ValueError("null/unsupported field cannot claim a materialized delta")
        if (
            self.claim_delta
            in {
                ResearchClaimDelta.ACCEPTED,
                ResearchClaimDelta.CORROBORATING,
                ResearchClaimDelta.CONFLICTING,
            }
            and not self.claim_refs
        ):
            raise ValueError("materialized claim delta requires claim references")
        if (
            self.outcome is ResearchFieldOutcome.CONFLICT
            and self.claim_delta is not ResearchClaimDelta.CONFLICTING
        ):
            raise ValueError("conflicting field outcome requires conflicting claim delta")
        if (
            self.outcome is ResearchFieldOutcome.REJECTED
            and self.claim_delta is not ResearchClaimDelta.REJECTED
        ):
            raise ValueError("rejected field outcome requires rejected claim delta")
        if self.claim_delta is ResearchClaimDelta.REJECTED and not self.decision_refs:
            raise ValueError("rejected claim delta requires durable decision references")
        if self.claim_delta is ResearchClaimDelta.CONFLICTING and (
            self.outcome is not ResearchFieldOutcome.CONFLICT
        ):
            raise ValueError("conflicting claim delta requires a conflicting field outcome")
        if self.claim_delta is ResearchClaimDelta.REJECTED and (
            self.outcome is not ResearchFieldOutcome.REJECTED
        ):
            raise ValueError("rejected claim delta requires a rejected field outcome")
        if self.outcome is ResearchFieldOutcome.FOUND and self.claim_delta not in {
            ResearchClaimDelta.ACCEPTED,
            ResearchClaimDelta.CORROBORATING,
        }:
            raise ValueError("found field requires an accepted or corroborating claim delta")
        return self


class ResearchDiscoveredSubjectProjection(BaseModel):
    """One identity-admitted contact discovered by an account-scoped committee operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_type: Literal[ResearchSubjectType.CONTACT]
    target_entity_id: UUID
    parent_account_id: UUID
    strong_identity_claim_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    association_evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    fields: tuple[ResearchFieldResultProjection, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _contact_projection_is_exact(self) -> Self:
        field_keys = tuple(field.field_key for field in self.fields)
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("discovered contact projection cannot repeat a field")
        _assert_field_axis(
            ResearchSubjectType.CONTACT,
            field_keys,
            context="discovered contact projection",
        )
        return self


class PersistedResearchToolResult(BaseModel):
    """Complete persisted provider result or complete index returned to an entity agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_type: ResearchSubjectType
    target_entity_id: UUID
    operation_ref: NonEmptyStr
    result_ref: NonEmptyStr
    request_artifact_ref: NonEmptyStr
    raw_response_artifact_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    retained_result_artifact_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    normalized_result_artifact_ref: NonEmptyStr
    provider_receipt_ref: NonEmptyStr
    cost_settlement_ref: NonEmptyStr
    requested_field_keys: tuple[NonEmptyStr, ...] = ()
    fields: tuple[ResearchFieldResultProjection, ...] = ()
    discovered_subjects: tuple[ResearchDiscoveredSubjectProjection, ...] = ()
    confirmed_empty_discovery: bool = False
    delivery: ResearchResultDelivery
    read_tool_address: NonEmptyStr | None = None
    provider_reported_cost_cents: Decimal = Field(ge=0)
    cost_cents: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _result_is_complete(self) -> Self:
        requested = tuple(dict.fromkeys(self.requested_field_keys))
        if requested != self.requested_field_keys:
            raise ValueError("requested research fields must be unique and stable")
        returned = tuple(field.field_key for field in self.fields)
        if len(returned) != len(set(returned)) or set(returned) != set(requested):
            raise ValueError("result projection must index every requested field exactly once")
        if requested:
            _assert_field_axis(
                self.subject_type,
                self.requested_field_keys,
                context="persisted research result",
            )
        if not self.fields and not self.discovered_subjects and not self.confirmed_empty_discovery:
            raise ValueError("persisted result requires fields or discovered subjects")
        if self.confirmed_empty_discovery:
            if self.subject_type is not ResearchSubjectType.ACCOUNT:
                raise ValueError("only account research may confirm an empty discovery")
            if self.requested_field_keys or self.fields or self.discovered_subjects:
                raise ValueError(
                    "confirmed empty discovery cannot carry fields or discovered subjects"
                )
        discovered_ids = tuple(item.target_entity_id for item in self.discovered_subjects)
        if len(discovered_ids) != len(set(discovered_ids)):
            raise ValueError("persisted result cannot repeat a discovered subject")
        if self.discovered_subjects:
            if self.subject_type is not ResearchSubjectType.ACCOUNT:
                raise ValueError("only account research may return discovered contacts")
            if any(
                item.parent_account_id != self.target_entity_id for item in self.discovered_subjects
            ):
                raise ValueError("discovered contact belongs to a different parent account")
        for references, message in (
            (
                self.raw_response_artifact_refs,
                "raw response artifact references must be unique",
            ),
            (
                self.retained_result_artifact_refs,
                "retained result artifact references must be unique",
            ),
        ):
            if len(references) != len(set(references)):
                raise ValueError(message)
        if self.delivery is ResearchResultDelivery.INLINE_COMPLETE:
            if self.read_tool_address is not None:
                raise ValueError("inline-complete result does not require a lossless read tool")
            all_fields = self.fields + tuple(
                field for subject in self.discovered_subjects for field in subject.fields
            )
            if any(
                field.outcome is ResearchFieldOutcome.FOUND and field.value is None
                for field in all_fields
            ):
                raise ValueError("inline-complete found fields require their complete values")
        else:
            if self.read_tool_address is None:
                raise ValueError("indexed-complete result requires a lossless read tool")
            all_fields = self.fields + tuple(
                field for subject in self.discovered_subjects for field in subject.fields
            )
            if any(
                field.outcome is ResearchFieldOutcome.FOUND and field.value_ref is None
                for field in all_fields
            ):
                raise ValueError("indexed-complete found fields require durable value references")
        return self


class ProviderOperationCausation(BaseModel):
    """Chronological proof that an entity-agent tool call caused a provider operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_type: ResearchSubjectType
    target_entity_id: UUID
    provider_operation_ref: NonEmptyStr
    agent_turn_id: UUID
    agent_execution_id: UUID
    tool_call_id: UUID
    tool_name: NonEmptyStr
    tool_version: int = Field(ge=1)
    tool_input_sha256: Sha256
    agent_turn_started_at: datetime
    tool_call_recorded_at: datetime
    provider_operation_reserved_at: datetime
    provider_dispatched_at: datetime
    parent_operation_ref: NonEmptyStr | None = None
    parent_observation_ref: NonEmptyStr | None = None
    follow_up_reason: ResearchFollowUpReason | None = None

    @model_validator(mode="after")
    def _causation_is_ordered(self) -> Self:
        times = (
            self.agent_turn_started_at,
            self.tool_call_recorded_at,
            self.provider_operation_reserved_at,
            self.provider_dispatched_at,
        )
        if any(value.utcoffset() is None for value in times):
            raise ValueError("causation timestamps must be timezone-aware")
        if list(times) != sorted(times):
            raise ValueError(
                "provider operation must follow agent start, tool journal, and durable reservation"
            )
        lineage = (self.parent_operation_ref, self.parent_observation_ref, self.follow_up_reason)
        if any(value is not None for value in lineage) and not all(
            value is not None for value in lineage
        ):
            raise ValueError(
                "follow-up causation requires parent operation, observation, and reason"
            )
        return self


class FacetDelegationContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    max_depth: int = Field(ge=0)
    max_children: int = Field(ge=0)
    children_may_delegate: bool = False
    shares_parent_budget: bool = True

    @model_validator(mode="after")
    def _delegation_is_bounded(self) -> Self:
        if self.children_may_delegate:
            raise ValueError("facet children cannot delegate")
        if not self.shares_parent_budget:
            raise ValueError("facet children must draw from the parent budget")
        if self.enabled:
            if self.max_depth != 1 or not 1 <= self.max_children <= 2:
                raise ValueError("enabled facet delegation is depth one with one or two children")
        elif self.max_depth != 0 or self.max_children != 0:
            raise ValueError("disabled facet delegation must reserve zero depth and children")
        return self


class PlannedResearchToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_call_id: UUID
    tool_name: NonEmptyStr
    source_family: NonEmptyStr
    field_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    budget_reservation_ref: NonEmptyStr
    purpose: ParallelCallPurpose
    facet_key: NonEmptyStr | None = None
    depends_on_tool_call_ids: tuple[UUID, ...] = ()
    overlap_authorization_ref: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _call_is_well_formed(self) -> Self:
        if len(self.field_keys) != len(set(self.field_keys)):
            raise ValueError("one tool call cannot repeat a field")
        if self.purpose is ParallelCallPurpose.FACET:
            if self.facet_key is None:
                raise ValueError("facet tool call requires an exact facet key")
        elif self.facet_key is not None:
            raise ValueError("only facet tool calls may carry a facet key")
        if self.purpose is ParallelCallPurpose.CORROBORATION:
            if self.overlap_authorization_ref is None:
                raise ValueError("corroboration tool call requires overlap authorization")
        elif self.overlap_authorization_ref is not None:
            raise ValueError("only corroboration calls may carry overlap authorization")
        return self


class ParallelToolExecutionContract(BaseModel):
    """Engine-authorized concurrent calls with no hidden dependency or duplicate work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_type: ResearchSubjectType
    target_entity_id: UUID
    engine_authorized: bool
    concurrency_cap: int = Field(ge=1)
    calls: tuple[PlannedResearchToolCall, ...] = Field(min_length=2)
    provider_rate_limit_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    wait_policy: Literal["persist_release_slot_resume_same_checkpoint"]

    @model_validator(mode="after")
    def _calls_are_independent(self) -> Self:
        if not self.engine_authorized:
            raise ValueError("parallel entity-agent tool execution requires engine authorization")
        if len(self.calls) > self.concurrency_cap:
            raise ValueError("parallel call count exceeds its admitted concurrency cap")
        if len(self.provider_rate_limit_refs) != len(set(self.provider_rate_limit_refs)):
            raise ValueError("provider rate-limit references must be unique")
        ids = [call.tool_call_id for call in self.calls]
        if len(ids) != len(set(ids)):
            raise ValueError("parallel tool-call ids must be unique")
        if len({call.budget_reservation_ref for call in self.calls}) != len(self.calls):
            raise ValueError("parallel calls require separate atomic budget reservations")
        batch_ids = frozenset(ids)
        if any(batch_ids.intersection(call.depends_on_tool_call_ids) for call in self.calls):
            raise ValueError("a tool call cannot run beside another call it depends on")

        fields_to_calls: dict[str, list[PlannedResearchToolCall]] = {}
        for call in self.calls:
            _assert_field_axis(
                self.subject_type,
                call.field_keys,
                context="parallel tool execution",
            )
            for field_key in call.field_keys:
                fields_to_calls.setdefault(field_key, []).append(call)
        for field_calls in fields_to_calls.values():
            if len(field_calls) < 2:
                continue
            overlap_refs = {call.overlap_authorization_ref for call in field_calls}
            if (
                any(call.purpose is not ParallelCallPurpose.CORROBORATION for call in field_calls)
                or None in overlap_refs
                or len(overlap_refs) != 1
            ):
                raise ValueError("overlapping parallel field work requires explicit corroboration")

        same_provider: dict[tuple[str, str], list[PlannedResearchToolCall]] = {}
        for call in self.calls:
            same_provider.setdefault((call.tool_name, call.source_family), []).append(call)
        for grouped in same_provider.values():
            if len(grouped) < 2:
                continue
            facet_keys = {call.facet_key for call in grouped}
            if (
                any(call.purpose is not ParallelCallPurpose.FACET for call in grouped)
                or None in facet_keys
                or len(facet_keys) != len(grouped)
            ):
                raise ValueError(
                    "parallel calls to one research provider require distinct admitted facets"
                )
        return self


class ResearchFinalizationProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID
    subject_type: ResearchSubjectType
    target_entity_id: UUID
    outcome: ResearchFinalizationOutcome
    current_state_sha256: Sha256
    coverage_ledger_ref: NonEmptyStr
    claim_delta_ledger_ref: NonEmptyStr
    spend_reconciliation_ref: NonEmptyStr
    identity_use_verification_ref: NonEmptyStr
    completed_field_keys: tuple[NonEmptyStr, ...] = ()
    unresolved_field_keys: tuple[NonEmptyStr, ...] = ()
    claim_refs: tuple[NonEmptyStr, ...] = ()
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    result_refs: tuple[NonEmptyStr, ...] = ()
    unresolved_reasons: tuple[NonEmptyStr, ...] = ()
    review_flags: tuple[NonEmptyStr, ...] = ()
    pending_operation_refs: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def _proposal_is_complete(self) -> Self:
        _assert_field_axis(
            self.subject_type,
            self.completed_field_keys + self.unresolved_field_keys,
            context="finalization proposal",
        )
        if set(self.completed_field_keys).intersection(self.unresolved_field_keys):
            raise ValueError("a field cannot be both complete and unresolved")
        if self.pending_operation_refs:
            raise ValueError("finalization cannot be proposed while provider work is pending")
        if self.unresolved_field_keys and not self.unresolved_reasons:
            raise ValueError("unresolved fields require explicit gap reasons")
        if self.outcome is ResearchFinalizationOutcome.NEEDS_REVIEW and not self.review_flags:
            raise ValueError("needs_review finalization requires durable review flags")
        if self.outcome is ResearchFinalizationOutcome.COMPLETED and self.unresolved_field_keys:
            raise ValueError("completed finalization cannot retain unresolved fields")
        return self


class FinalizationVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    no_pending_operations: bool
    evidence_complete: bool
    coverage_matches: bool
    spend_reconciled: bool
    identity_use_verification_complete: bool
    policy_scope_respected: bool
    current_state_matches: bool

    def all_passed(self) -> bool:
        return all(self.model_dump().values())


class ResearchFinalizationReceipt(BaseModel):
    """Engine-owned immutable acceptance; model prose alone can never substitute for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: UUID
    proposal: ResearchFinalizationProposal
    proposal_ref: NonEmptyStr
    engine_actor: NonEmptyStr
    accepted_at: datetime
    accepted_state_sha256: Sha256
    verification: FinalizationVerification

    @model_validator(mode="after")
    def _engine_acceptance_is_valid(self) -> Self:
        if self.accepted_at.utcoffset() is None:
            raise ValueError("finalization acceptance time must be timezone-aware")
        if self.accepted_state_sha256 != self.proposal.current_state_sha256:
            raise ValueError("finalization receipt does not accept the proposed current state")
        if not self.verification.all_passed():
            raise ValueError("engine cannot accept finalization before every verification passes")
        return self


class EntityResearchJobStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: UUID
    state: ResearchJobState
    finalization_outcome: ResearchFinalizationOutcome | None = None
    finalization_receipt_ref: NonEmptyStr | None = None
    model_final_message_ref: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _terminal_requires_receipt(self) -> Self:
        if self.state is ResearchJobState.TERMINAL:
            if self.finalization_outcome is None or self.finalization_receipt_ref is None:
                raise ValueError("terminal entity job requires an accepted finalization receipt")
        elif self.finalization_outcome is not None or self.finalization_receipt_ref is not None:
            raise ValueError("non-terminal entity job cannot carry finalization authority")
        return self


__all__ = [
    "AgentFramework",
    "ContactChannel",
    "EntityAgentToolSurface",
    "EntityResearchAuthorityContract",
    "EntityResearchJobAuthorization",
    "EntityResearchJobStatus",
    "EntityResearchSelection",
    "FacetDelegationContract",
    "FieldSourceAuthority",
    "FieldResearchSourcePlan",
    "FinalizationVerification",
    "GovernedResearchToolRequest",
    "ParallelCallPurpose",
    "ParallelToolExecutionContract",
    "PersistedResearchToolResult",
    "PlannedResearchToolCall",
    "PlannedSourceAttempt",
    "ProviderOperationCausation",
    "ResearchClaimDelta",
    "ResearchComponentClass",
    "ResearchComponentContract",
    "ResearchDiscoveredSubjectProjection",
    "ResearchEvidenceProjection",
    "ResearchFieldOutcome",
    "ResearchFieldResultProjection",
    "ResearchFinalizationOutcome",
    "ResearchFinalizationProposal",
    "ResearchFinalizationReceipt",
    "ResearchFollowUpReason",
    "ResearchJobState",
    "ResearchOperationKind",
    "ResearchResultDelivery",
    "ResearchRunKind",
    "ResearchRunLifecycleContract",
    "ResearchSelectionBasis",
    "SealedDiscoveryLaunchReceipt",
    "ResearchSubjectType",
    "SelectedContactResearchAuthority",
    "SelectedResearchSubject",
]
