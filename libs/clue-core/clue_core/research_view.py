"""Frozen C7.0 contracts for structured account/contact research views.

These types describe a provenance-resolving read model, not a generated dossier document. Values
owned by identity, scoring, execution, committee, coverage, and activity cross this seam only as
typed references. Research statements resolve to direct claim ids or derived claim ids with an
ordered support set.

C7.0 intentionally contains no database models, tool handlers, readers, composers, or claim-flavor
changes. Implementations arrive in later C7 slices behind the protocols frozen here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, NewType, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from clue_core.claim import Claim
from clue_core.enums import (
    ClaimFlavor,
    DisplayDecision,
    DossierBlockKind,
    EntailmentReasonCode,
    EntailmentVerdictKind,
    EntityType,
    EvidenceActionKind,
    FreshnessState,
    IdentityBinding,
    OutreachDecision,
    ResearchAvailability,
    ResearchConflictState,
    ResearchDataSpecies,
    ResearchReferenceRelation,
    ResearchSectionKind,
    ResearchStatementKind,
    ResearchSupportRole,
    UseClass,
    VerificationStatus,
)
from clue_core.execution_graph import OperationId
from clue_core.field import FieldClass, FieldKey, classify_field_key
from clue_core.primitives import (
    ClaimId,
    Confidence,
    CostCents,
    EntityId,
    ProjectRunId,
    UtcDatetime,
)
from clue_core.research_view_species import (
    compatibility_block_kind,
    species_is_allowed,
)

ResearchViewId = NewType("ResearchViewId", UUID)
ResearchStatementId = NewType("ResearchStatementId", UUID)
ResearchViewSnapshotId = NewType("ResearchViewSnapshotId", UUID)
ResearchViewChangeReportId = NewType("ResearchViewChangeReportId", UUID)

Sha256Hex = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
ReferenceToken = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
ReasonCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=80),
]


def _ensure_opaque_reference(value: str) -> str:
    lowered = value.lower()
    if "://" in lowered or lowered.startswith(("/", "file:", "s3:", "gs:", "arn:aws:")):
        raise ValueError("reference must be opaque, never a URL, path, or storage key")
    return value


OpaqueReferenceToken = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    AfterValidator(_ensure_opaque_reference),
]


def new_research_view_id() -> ResearchViewId:
    return ResearchViewId(uuid4())


def new_research_statement_id() -> ResearchStatementId:
    return ResearchStatementId(uuid4())


def new_research_view_snapshot_id() -> ResearchViewSnapshotId:
    return ResearchViewSnapshotId(uuid4())


def new_research_view_change_report_id() -> ResearchViewChangeReportId:
    return ResearchViewChangeReportId(uuid4())


class ResearchSubjectRef(BaseModel):
    """An exact canonical subject; contacts are always locked to one parent account."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    entity_type: EntityType
    canonical_entity_version: int = Field(ge=1)
    parent_account_id: EntityId | None = None

    @model_validator(mode="after")
    def _parent_matches_entity_type(self) -> ResearchSubjectRef:
        if self.entity_type is EntityType.CONTACT and self.parent_account_id is None:
            raise ValueError("a contact research subject requires parent_account_id")
        if self.entity_type is EntityType.ACCOUNT and self.parent_account_id is not None:
            raise ValueError("an account research subject cannot carry parent_account_id")
        return self


class ResearchItemState(BaseModel):
    """Independent availability, verification, freshness, conflict, display, and outreach axes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    availability: ResearchAvailability
    verification: VerificationStatus
    freshness: FreshnessState
    conflict: ResearchConflictState = ResearchConflictState.NONE
    display_decision: DisplayDecision
    outreach_decision: OutreachDecision
    reason_codes: tuple[ReasonCode, ...] = ()

    @model_validator(mode="after")
    def _state_is_fail_closed(self) -> ResearchItemState:
        if self.availability is ResearchAvailability.AVAILABLE:
            if self.verification not in {
                VerificationStatus.VERIFIED,
                VerificationStatus.FLAGGED,
            }:
                raise ValueError("an available statement must be verified or flagged")
            if self.display_decision is not DisplayDecision.ALLOWED:
                raise ValueError("an available statement requires display_decision=allowed")
            if self.freshness is FreshnessState.EXPIRED:
                raise ValueError("a retention-expired statement cannot be available")
        if (
            self.availability
            in {
                ResearchAvailability.REDACTED,
                ResearchAvailability.RESTRICTED,
            }
            and self.display_decision is not DisplayDecision.DENIED
        ):
            raise ValueError("redacted/restricted statements require display_decision=denied")
        if (
            self.outreach_decision is OutreachDecision.ALLOWED
            and self.display_decision is not DisplayDecision.ALLOWED
        ):
            raise ValueError("outreach eligibility cannot exceed display eligibility")
        return self


class EvidenceActionDescriptor(BaseModel):
    """A safe action capability; never a source URL, signed URL, or object-storage key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EvidenceActionKind
    claim_id: ClaimId
    action_id: UUID | None = None
    provider_label: ReferenceToken | None = None
    media_type: ReferenceToken | None = None

    @model_validator(mode="after")
    def _action_capability_matches_kind(self) -> EvidenceActionDescriptor:
        disabled = {EvidenceActionKind.UNAVAILABLE, EvidenceActionKind.REDACTED}
        if self.kind in disabled and self.action_id is not None:
            raise ValueError("unavailable/redacted evidence cannot carry an action_id")
        if self.kind not in disabled and self.action_id is None:
            raise ValueError("an actionable evidence descriptor requires action_id")
        return self


class EvidenceAccessRequest(BaseModel):
    """One actor's request to resolve an evidence action under current policy.

    This carries only identity and authorization inputs. In particular it cannot carry a source
    URL, storage key, signed URL, or caller-selected expiry.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: ReferenceToken
    project_id: ReferenceToken
    actor_id: ReferenceToken
    subject_entity_id: EntityId
    statement_id: ResearchStatementId
    claim_id: ClaimId
    action_id: UUID
    desired_action: EvidenceActionKind

    @model_validator(mode="after")
    def _request_is_for_an_actionable_kind(self) -> EvidenceAccessRequest:
        if self.desired_action in {
            EvidenceActionKind.UNAVAILABLE,
            EvidenceActionKind.REDACTED,
        }:
            raise ValueError("unavailable/redacted are outcomes, not requested evidence actions")
        return self


class EvidenceAccessDecision(BaseModel):
    """Bounded authorization verdict; reason codes replace free-form policy explanations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    action_kind: EvidenceActionKind
    claim_id: ClaimId
    reason_codes: tuple[ReasonCode, ...]

    @model_validator(mode="after")
    def _decision_is_bounded_and_coherent(self) -> EvidenceAccessDecision:
        if not self.reason_codes:
            raise ValueError("evidence authorization requires at least one reason code")
        denied_kind = self.action_kind in {
            EvidenceActionKind.UNAVAILABLE,
            EvidenceActionKind.REDACTED,
        }
        if self.allowed == denied_kind:
            raise ValueError("allowed evidence decisions require an actionable kind")
        return self


class EvidenceAccessResult(BaseModel):
    """Authorized request-time access capability.

    ``access_ref`` is an opaque, server-handled capability (for example, a redirect endpoint
    reference). The service implementation may mint a short-lived storage preview behind that
    endpoint, but a signed URL or storage key never crosses this contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_kind: EvidenceActionKind
    claim_id: ClaimId
    access_ref: OpaqueReferenceToken | None = None
    provider_label: ReferenceToken | None = None
    media_type: ReferenceToken | None = None
    reason_codes: tuple[ReasonCode, ...]

    @model_validator(mode="after")
    def _result_exposes_only_authorized_capabilities(self) -> EvidenceAccessResult:
        unavailable = self.action_kind in {
            EvidenceActionKind.UNAVAILABLE,
            EvidenceActionKind.REDACTED,
        }
        if unavailable and self.access_ref is not None:
            raise ValueError("unavailable/redacted evidence cannot carry an access_ref")
        if not unavailable and self.access_ref is None:
            raise ValueError("authorized evidence requires an opaque access_ref")
        if not self.reason_codes:
            raise ValueError("evidence access result requires at least one reason code")
        return self


class ResearchSupportRef(BaseModel):
    """One ordered claim edge supporting a derived statement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    role: ResearchSupportRole
    ordinal: int = Field(ge=0)
    required: bool = True


class ResearchStatement(BaseModel):
    """A display item resolving to one direct claim or one fully-supported derived claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_kind: Literal["statement"] = "statement"
    statement_id: ResearchStatementId
    subject: ResearchSubjectRef
    field_key: FieldKey
    value_json: JsonValue | None = None
    statement_kind: ResearchStatementKind
    claim_id: ClaimId
    supports: tuple[ResearchSupportRef, ...] = ()
    product_id: ReferenceToken | None = None
    state: ResearchItemState
    confidence: Confidence
    observed_at: UtcDatetime | None = None
    collected_at: UtcDatetime
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    evidence_actions: tuple[EvidenceActionDescriptor, ...] = ()

    @model_validator(mode="after")
    def _statement_is_resolvable_and_governed(self) -> ResearchStatement:
        if self.statement_kind is ResearchStatementKind.DIRECT and self.supports:
            raise ValueError("a direct statement cannot carry support claims")
        if self.statement_kind is ResearchStatementKind.DERIVED and not self.supports:
            raise ValueError("a derived statement requires at least one support claim")
        if self.supports:
            ordinals = tuple(support.ordinal for support in self.supports)
            if ordinals != tuple(range(len(self.supports))):
                raise ValueError("derived supports must have unique contiguous ordinals from zero")
            if any(support.claim_id == self.claim_id for support in self.supports):
                raise ValueError("a claim cannot support itself")

        is_available = self.state.availability is ResearchAvailability.AVAILABLE
        if is_available and self.value_json is None:
            raise ValueError("an available statement requires value_json")
        if not is_available and (self.value_json is not None or self.evidence_actions):
            raise ValueError("a hidden statement cannot carry value_json or evidence actions")
        if any(action.claim_id != self.claim_id for action in self.evidence_actions):
            raise ValueError("every evidence action must resolve the statement's claim_id")

        if (self.identity_binding is None) != (self.use_class is None):
            raise ValueError("identity_binding and use_class must be supplied together")
        if (
            self.subject.entity_type is EntityType.CONTACT
            and classify_field_key(self.field_key) is FieldClass.CONTACT_FACET
            and (self.identity_binding is None or self.use_class is None)
        ):
            raise ValueError("contact.facet.* statements require identity_binding and use_class")
        if self.subject.entity_type is EntityType.ACCOUNT and (
            self.identity_binding is not None or self.use_class is not None
        ):
            raise ValueError("account statements cannot carry personal-data governance provenance")
        if (
            self.use_class is UseClass.SENSITIVE
            and self.state.outreach_decision is OutreachDecision.ALLOWED
        ):
            raise ValueError("sensitive personal data cannot be outreach eligible")
        if self.state.outreach_decision is OutreachDecision.ALLOWED:
            if self.subject.entity_type is not EntityType.CONTACT:
                raise ValueError("only contact statements may be outreach eligible")
            if self.identity_binding is not IdentityBinding.STRONG:
                raise ValueError("outreach eligibility requires strong identity binding")
            if self.use_class is None:
                raise ValueError("outreach eligibility requires a classified use_class")
        return self


class ResearchOwnedReference(BaseModel):
    """A reference to data authored by an existing authority, with no copied value payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_kind: Literal["reference"] = "reference"
    item_id: ReferenceToken
    subject: ResearchSubjectRef
    data_species: ResearchDataSpecies
    relation: ResearchReferenceRelation
    owner_ref: OpaqueReferenceToken
    product_id: ReferenceToken | None = None
    evidence_claim_ids: tuple[ClaimId, ...] = ()

    @model_validator(mode="after")
    def _reference_preserves_owner(self) -> ResearchOwnedReference:
        if self.data_species is ResearchDataSpecies.CLAIM_DERIVATION:
            raise ValueError("claim/derivation values must use ResearchStatement")
        if self.data_species is ResearchDataSpecies.SCORE:
            if not self.evidence_claim_ids:
                raise ValueError("a score reference requires evidence_claim_ids")
            if self.product_id is None:
                raise ValueError("a fit/score reference requires exact product_id")
        return self


class ResearchPersonalizationItem(BaseModel):
    """An explicitly-selected, strongly-bound, outreach-eligible contact statement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_kind: Literal["personalization"] = "personalization"
    item_id: ReferenceToken
    statement: ResearchStatement
    selection_reason_code: ReasonCode

    @model_validator(mode="after")
    def _selection_is_governed(self) -> ResearchPersonalizationItem:
        if self.statement.subject.entity_type is not EntityType.CONTACT:
            raise ValueError("personalization requires a contact statement")
        if self.statement.state.outreach_decision is not OutreachDecision.ALLOWED:
            raise ValueError("personalization requires outreach_decision=allowed")
        if self.statement.identity_binding is not IdentityBinding.STRONG:
            raise ValueError("personalization requires strong identity binding")
        if self.statement.use_class is UseClass.SENSITIVE:
            raise ValueError("sensitive data cannot be selected for personalization")
        return self


ResearchViewItem = Annotated[
    ResearchStatement | ResearchOwnedReference | ResearchPersonalizationItem,
    Field(discriminator="item_kind"),
]


def _item_species(item: ResearchViewItem) -> ResearchDataSpecies:
    if isinstance(item, ResearchOwnedReference):
        return item.data_species
    return ResearchDataSpecies.CLAIM_DERIVATION


def _item_id(item: ResearchViewItem) -> str:
    if isinstance(item, ResearchStatement):
        return str(item.statement_id)
    return str(item.item_id)


def _item_statement(item: ResearchViewItem) -> ResearchStatement | None:
    if isinstance(item, ResearchStatement):
        return item
    if isinstance(item, ResearchPersonalizationItem):
        return item.statement
    return None


class ResearchSection(BaseModel):
    """One semantic page section with an exact authority and optional old-block adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: ReferenceToken
    kind: ResearchSectionKind
    block_kind: DossierBlockKind | None
    availability: ResearchAvailability
    reason_codes: tuple[ReasonCode, ...] = ()
    items: tuple[ResearchViewItem, ...] = ()

    @model_validator(mode="after")
    def _section_matches_species_and_block_map(self) -> ResearchSection:
        expected_block = compatibility_block_kind(self.kind)
        if self.block_kind is not expected_block:
            raise ValueError(
                f"section {self.kind.value} requires compatibility block "
                f"{expected_block.value if expected_block is not None else None}"
            )
        if self.items and self.availability is not ResearchAvailability.AVAILABLE:
            raise ValueError("a section with items must be available")
        if not self.items and self.availability is ResearchAvailability.AVAILABLE:
            raise ValueError("an empty section must expose an explicit non-available state")
        for item in self.items:
            species = _item_species(item)
            if not species_is_allowed(self.kind, species):
                raise ValueError(
                    f"{species.value} is not authoritative for section {self.kind.value}"
                )
        item_ids = tuple(_item_id(item) for item in self.items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("section item ids must be unique")
        return self


class ResearchProvenanceRef(BaseModel):
    """Reference-only provenance index entry for one visible statement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: ResearchStatementId
    claim_id: ClaimId
    statement_kind: ResearchStatementKind
    support_claim_ids: tuple[ClaimId, ...] = ()

    @model_validator(mode="after")
    def _support_shape_matches_kind(self) -> ResearchProvenanceRef:
        if self.statement_kind is ResearchStatementKind.DIRECT and self.support_claim_ids:
            raise ValueError("direct provenance cannot carry support_claim_ids")
        if self.statement_kind is ResearchStatementKind.DERIVED and not self.support_claim_ids:
            raise ValueError("derived provenance requires support_claim_ids")
        return self


class ResearchStatusSummary(BaseModel):
    """Small deterministic status counts; it never carries research bodies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_statement_count: int = Field(ge=0)
    available_statement_count: int = Field(ge=0)
    stale_statement_count: int = Field(ge=0)
    restricted_statement_count: int = Field(ge=0)
    unknown_section_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_are_bounded(self) -> ResearchStatusSummary:
        if self.available_statement_count > self.total_statement_count:
            raise ValueError("available_statement_count cannot exceed total_statement_count")
        if self.stale_statement_count > self.total_statement_count:
            raise ValueError("stale_statement_count cannot exceed total_statement_count")
        if self.restricted_statement_count > self.total_statement_count:
            raise ValueError("restricted_statement_count cannot exceed total_statement_count")
        return self


class ResearchCoverageSummary(BaseModel):
    """Reference/count-only C1 coverage projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage_ref_ids: tuple[ReferenceToken, ...] = ()
    required_field_count: int = Field(ge=0)
    filled_field_count: int = Field(ge=0)
    terminal_gap_count: int = Field(ge=0)
    blocked_field_count: int = Field(ge=0)
    budget_exhausted_field_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _coverage_counts_are_possible(self) -> ResearchCoverageSummary:
        classified = (
            self.filled_field_count
            + self.terminal_gap_count
            + self.blocked_field_count
            + self.budget_exhausted_field_count
        )
        if classified > self.required_field_count:
            raise ValueError("classified coverage fields cannot exceed required_field_count")
        return self


class ResearchViewBase(BaseModel):
    """Common reference-resolving payload for account and contact views."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    view_id: ResearchViewId
    snapshot_id: ResearchViewSnapshotId | None = None
    workspace_id: ReferenceToken
    project_id: ReferenceToken
    project_run_id: ProjectRunId
    subject: ResearchSubjectRef
    product_id: ReferenceToken | None = None
    composed_at: UtcDatetime
    source_state_sha256: Sha256Hex
    status_summary: ResearchStatusSummary
    sections: tuple[ResearchSection, ...]
    provenance_index: tuple[ResearchProvenanceRef, ...]
    coverage_summary: ResearchCoverageSummary

    @model_validator(mode="after")
    def _view_is_exact_and_internally_complete(self) -> ResearchViewBase:
        section_ids = tuple(section.section_id for section in self.sections)
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("section ids must be unique")

        all_items = tuple(item for section in self.sections for item in section.items)
        item_ids = tuple(_item_id(item) for item in all_items)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("item ids must be unique across the view")

        statements = tuple(
            statement for item in all_items if (statement := _item_statement(item)) is not None
        )
        for statement in statements:
            if statement.subject != self.subject:
                raise ValueError("every research statement must target the view's exact subject")
            if statement.product_id is not None and statement.product_id != self.product_id:
                raise ValueError("a product-scoped statement must match the view product_id")
            if statement.product_id is not None and self.product_id is None:
                raise ValueError("a product-neutral view cannot contain a product-scoped statement")

        for item in all_items:
            if not isinstance(item, ResearchOwnedReference):
                continue
            if item.product_id is not None and item.product_id != self.product_id:
                raise ValueError("a product-scoped owner reference must match the view product_id")
            if item.product_id is not None and self.product_id is None:
                raise ValueError(
                    "a product-neutral view cannot contain a product-scoped owner reference"
                )
            if item.relation is ResearchReferenceRelation.SUBJECT and item.subject != self.subject:
                raise ValueError("a subject reference must target the view's exact subject")
            if item.relation is ResearchReferenceRelation.PARENT_ACCOUNT:
                if self.subject.entity_type is not EntityType.CONTACT:
                    raise ValueError("only a contact view may carry a parent-account reference")
                if (
                    item.subject.entity_type is not EntityType.ACCOUNT
                    or item.subject.entity_id != self.subject.parent_account_id
                ):
                    raise ValueError("parent-account reference does not match the contact subject")
            if item.relation is ResearchReferenceRelation.COMMITTEE_MEMBER:
                if self.subject.entity_type is not EntityType.ACCOUNT:
                    raise ValueError("only an account view may carry committee-member references")
                if (
                    item.subject.entity_type is not EntityType.CONTACT
                    or item.subject.parent_account_id != self.subject.entity_id
                ):
                    raise ValueError("committee member is not bound to the view account")

        provenance_by_statement = {ref.statement_id: ref for ref in self.provenance_index}
        if len(provenance_by_statement) != len(self.provenance_index):
            raise ValueError("provenance statement ids must be unique")
        if set(provenance_by_statement) != {statement.statement_id for statement in statements}:
            raise ValueError("provenance index must cover every and only visible statement")
        for statement in statements:
            provenance = provenance_by_statement[statement.statement_id]
            if provenance.claim_id != statement.claim_id:
                raise ValueError("provenance claim_id must match its statement")
            if provenance.statement_kind is not statement.statement_kind:
                raise ValueError("provenance statement_kind must match its statement")
            if provenance.support_claim_ids != tuple(
                support.claim_id for support in statement.supports
            ):
                raise ValueError("provenance supports must match the ordered statement supports")

        unique_statements = {statement.statement_id: statement for statement in statements}
        available = sum(
            statement.state.availability is ResearchAvailability.AVAILABLE
            for statement in unique_statements.values()
        )
        stale = sum(
            statement.state.freshness is FreshnessState.STALE
            for statement in unique_statements.values()
        )
        restricted = sum(
            statement.state.availability
            in {ResearchAvailability.RESTRICTED, ResearchAvailability.REDACTED}
            for statement in unique_statements.values()
        )
        unknown_sections = sum(
            section.availability is ResearchAvailability.UNKNOWN for section in self.sections
        )
        expected_summary = ResearchStatusSummary(
            total_statement_count=len(unique_statements),
            available_statement_count=available,
            stale_statement_count=stale,
            restricted_statement_count=restricted,
            unknown_section_count=unknown_sections,
        )
        if self.status_summary != expected_summary:
            raise ValueError("status_summary must equal the deterministic view counts")
        return self


class AccountResearchView(ResearchViewBase):
    """The account-facing C7 read contract."""

    view_kind: Literal["account"] = "account"

    @model_validator(mode="after")
    def _subject_is_account(self) -> AccountResearchView:
        if self.subject.entity_type is not EntityType.ACCOUNT:
            raise ValueError("AccountResearchView requires an account subject")
        return self


class ContactResearchView(ResearchViewBase):
    """The contact-facing C7 read contract."""

    view_kind: Literal["contact"] = "contact"

    @model_validator(mode="after")
    def _subject_is_contact(self) -> ContactResearchView:
        if self.subject.entity_type is not EntityType.CONTACT:
            raise ValueError("ContactResearchView requires a contact subject")
        return self


ResearchView = Annotated[
    AccountResearchView | ContactResearchView,
    Field(discriminator="view_kind"),
]


class ResearchViewReadRequest(BaseModel):
    """Authorized scope needed to resolve a current view; no policy-weakening knobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: ReferenceToken
    project_id: ReferenceToken
    project_run_id: ProjectRunId
    subject_entity_id: EntityId
    product_id: ReferenceToken | None = None
    schema_version: Literal["1.0"] = "1.0"


class ResearchViewReceipt(BaseModel):
    """Reference-only result of ``compose_dossier@1`` / snapshot composition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: ResearchViewSnapshotId
    view_id: ResearchViewId
    workspace_id: ReferenceToken
    project_id: ReferenceToken
    project_run_id: ProjectRunId
    subject: ResearchSubjectRef
    product_id: ReferenceToken | None = None
    source_state_sha256: Sha256Hex
    composition_sha256: Sha256Hex
    created_at: UtcDatetime
    fetch_ref: OpaqueReferenceToken


class ResearchViewRecheckRequest(BaseModel):
    """Closed, operation-idempotent input for an additive snapshot re-check.

    Callers can narrow the report to known section kinds and request the existing governed
    research operation. They cannot supply policy thresholds, prompts, models, values, sources,
    or evidence-link lifetimes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: OperationId
    workspace_id: ReferenceToken
    project_id: ReferenceToken
    subject_entity_id: EntityId
    snapshot_id: ResearchViewSnapshotId
    section_kinds: tuple[ResearchSectionKind, ...] = ()
    request_research: bool = False

    @field_validator("section_kinds", mode="before")
    @classmethod
    def _canonicalize_section_selector(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(sorted(value, key=str))
        return value

    @model_validator(mode="after")
    def _section_selector_is_unique(self) -> ResearchViewRecheckRequest:
        if len(self.section_kinds) != len(set(self.section_kinds)):
            raise ValueError("section_kinds must be unique")
        return self


class ResearchViewRef(BaseModel):
    """Reference-only output for effect-free research-view lookup tools."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    view_id: ResearchViewId
    snapshot_id: ResearchViewSnapshotId | None = None
    workspace_id: ReferenceToken
    project_id: ReferenceToken
    subject_entity_id: EntityId
    product_id: ReferenceToken | None = None
    source_state_sha256: Sha256Hex
    fetch_ref: OpaqueReferenceToken


class ResearchViewChangeReportRef(BaseModel):
    """Body-free result of additive snapshot re-check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: ResearchViewChangeReportId
    operation_id: OperationId
    old_snapshot_id: ResearchViewSnapshotId
    new_snapshot_id: ResearchViewSnapshotId
    old_source_state_sha256: Sha256Hex
    new_source_state_sha256: Sha256Hex
    old_composition_sha256: Sha256Hex
    new_composition_sha256: Sha256Hex
    unchanged_statement_ids: tuple[ResearchStatementId, ...] = ()
    added_statement_ids: tuple[ResearchStatementId, ...] = ()
    removed_statement_ids: tuple[ResearchStatementId, ...] = ()
    stale_statement_ids: tuple[ResearchStatementId, ...] = ()
    restricted_statement_ids: tuple[ResearchStatementId, ...] = ()
    requested_operation_ids: tuple[OperationId, ...] = ()
    reason_codes: tuple[ReasonCode, ...] = ()
    fetch_ref: OpaqueReferenceToken


class EntailmentSupport(BaseModel):
    """One full support supplied to the internal judge; never an external/tool output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: Claim
    role: ResearchSupportRole
    ordinal: int = Field(ge=0)
    required: bool = True


class EntailmentJudgeRequest(BaseModel):
    """Governed internal request to judge one proposed derived claim against exact supports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    derived_claim: Claim
    target: ResearchSubjectRef
    supports: tuple[EntailmentSupport, ...]
    support_set_sha256: Sha256Hex
    policy_version: int = Field(ge=1)

    @model_validator(mode="after")
    def _request_is_target_locked(self) -> EntailmentJudgeRequest:
        if self.derived_claim.claim_flavor is not ClaimFlavor.DERIVED:
            raise ValueError("entailment requires claim_flavor=derived")
        if (
            self.derived_claim.entity_id != self.target.entity_id
            or self.derived_claim.entity_type is not self.target.entity_type
        ):
            raise ValueError("derived claim must target the exact research subject")
        if not self.supports:
            raise ValueError("entailment requires at least one support")
        if not any(support.required for support in self.supports):
            raise ValueError("entailment requires at least one required support")
        ordinals = tuple(support.ordinal for support in self.supports)
        if ordinals != tuple(range(len(self.supports))):
            raise ValueError("entailment supports require contiguous ordinals from zero")
        if any(support.claim.id == self.derived_claim.id for support in self.supports):
            raise ValueError("a derived claim cannot support itself")
        return self


class EntailmentJudgeResult(BaseModel):
    """Bounded, auditable entailment output with no persisted free-form rationale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    derived_claim_id: ClaimId
    support_set_sha256: Sha256Hex
    verdict: EntailmentVerdictKind
    confidence: Confidence
    reason_codes: tuple[EntailmentReasonCode, ...]
    requested_model: ReferenceToken
    answering_model: ReferenceToken
    prompt_version: ReferenceToken
    trace_ref: OpaqueReferenceToken
    cost_cents: CostCents = Decimal(0)

    @model_validator(mode="after")
    def _result_has_a_bounded_reason(self) -> EntailmentJudgeResult:
        if not self.reason_codes:
            raise ValueError("entailment result requires at least one bounded reason code")
        if len(self.reason_codes) > 8:
            raise ValueError("entailment result permits at most eight bounded reason codes")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("entailment reason codes must be unique")
        if self.verdict is EntailmentVerdictKind.SUPPORTED and self.reason_codes != (
            EntailmentReasonCode.ENTAILED,
        ):
            raise ValueError("a supported verdict requires only the entailed reason code")
        if (
            self.verdict is EntailmentVerdictKind.UNSUPPORTED
            and EntailmentReasonCode.ENTAILED in self.reason_codes
        ):
            raise ValueError("an unsupported verdict cannot carry the entailed reason code")
        if (
            self.verdict is EntailmentVerdictKind.UNSUPPORTED
            and EntailmentReasonCode.MODEL_ERROR in self.reason_codes
        ):
            raise ValueError("an unsupported verdict cannot carry the model_error reason code")
        if self.verdict is EntailmentVerdictKind.ERROR and self.reason_codes != (
            EntailmentReasonCode.MODEL_ERROR,
        ):
            raise ValueError("an error verdict requires only the model_error reason code")
        return self


@runtime_checkable
class ResearchViewReader(Protocol):
    """Read a live structured research view from existing authorities."""

    async def read(self, request: ResearchViewReadRequest) -> ResearchView | None: ...


@runtime_checkable
class ResearchViewComposer(Protocol):
    """Deterministically compose a structured view; implementations do not author owner data."""

    async def compose(self, request: ResearchViewReadRequest) -> ResearchView: ...


@runtime_checkable
class ResearchViewSnapshotReader(Protocol):
    """Resolve a saved reference receipt under current authorization and policy."""

    async def resolve(
        self,
        *,
        workspace_id: str,
        snapshot_id: ResearchViewSnapshotId,
    ) -> ResearchView | None: ...


@runtime_checkable
class EvidenceAccessAuthorizer(Protocol):
    """Current-policy authorization seam for one exact evidence action."""

    async def authorize(self, request: EvidenceAccessRequest) -> EvidenceAccessDecision: ...


@runtime_checkable
class EvidenceAccessService(Protocol):
    """API-root evidence resolver; the only C7 layer permitted to reach storage presigning."""

    async def request_access(self, request: EvidenceAccessRequest) -> EvidenceAccessResult: ...


@runtime_checkable
class DerivationEntailmentJudge(Protocol):
    """Entailment mode behind the existing governed model gateway."""

    async def judge(self, request: EntailmentJudgeRequest) -> EntailmentJudgeResult: ...
