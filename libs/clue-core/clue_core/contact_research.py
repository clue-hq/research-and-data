"""Provider-neutral contact-research authorization and preparation contracts (M8C C0).

Contact research is an independently invokable capability of the platform deepagent, not a new
project phase.  These reference-only contracts freeze the exact selected contacts, admitted
fields, provider/channel permissions, policy lineage, and preparation outcome without placing a
provider name in the orchestrator.

Channel observation, corroboration, reachability, identity promotion, and outreach permission are
deliberately separate states.  In particular, a reachable work email does not become a verified
identity key until it is strongly bound and independently corroborated; a phone never becomes an
identity key under the C0 policy.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import NewType, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core.discovery import Sha256Hex
from clue_core.enums import IdentityBinding
from clue_core.field import FieldKey
from clue_core.primitives import ClaimId, EntityId, ProjectRunId, UtcDatetime
from clue_core.research_directive import ResearchDirectivePin

ContactResearchSelectionId = NewType("ContactResearchSelectionId", UUID)

# C0's semantic freeze.  ``core.work_email`` already has the required meaning and is reused;
# ``core.company_phone`` is organization-level and therefore cannot represent a person's direct
# number.  ``core.direct_phone`` is reserved for C5 registration after a reveal provider is
# accepted.  The professional fields are registered by C1.
CONTACT_PROFESSIONAL_FIELD_KEYS: tuple[str, ...] = (
    "contact.current_title",
    "contact.job_function",
    "contact.job_level",
    "contact.team_membership",
    "contact.current_location",
    "contact.organization_relationship",
)
CONTACT_CHANNEL_FIELD_KEYS: dict[ContactChannel, str]  # assigned after the enum declaration


def new_contact_research_selection_id() -> ContactResearchSelectionId:
    """Mint a selection-receipt id; persistence remains owned by a later M8C slice."""

    return ContactResearchSelectionId(uuid4())


class ContactChannel(StrEnum):
    """The two independently authorized delivery-channel classes in M8C."""

    EMAIL = "email"
    PHONE = "phone"


CONTACT_CHANNEL_FIELD_KEYS = {
    ContactChannel.EMAIL: "core.work_email",
    ContactChannel.PHONE: "core.direct_phone",
}


class ChannelIdentityCorroboration(StrEnum):
    """Whether an independent source binds a channel to the exact person and employer."""

    NOT_CHECKED = "not_checked"
    MATCHED = "matched"
    CONFLICTED = "conflicted"


class ChannelReachability(StrEnum):
    """Independent deliverability/reachability disposition for a channel."""

    NOT_CHECKED = "not_checked"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class ChannelUseDecision(StrEnum):
    """Appropriateness/use permission, independent of channel correctness or reachability."""

    NOT_EVALUATED = "not_evaluated"
    ALLOWED = "allowed"
    DENIED = "denied"


class ContactChannelState(StrEnum):
    """The channel lifecycle; only email may enter ``VERIFIED_IDENTITY``."""

    OBSERVED = "observed"
    CORROBORATED = "corroborated"
    VALIDATED = "validated"
    VERIFIED_IDENTITY = "verified_identity"
    REJECTED = "rejected"


class ContactChannelValidation(BaseModel):
    """Reference-only result of the three independent channel decisions.

    ``VALIDATED`` means the value is independently bound and reachable.  It is intentionally not
    an identity mutation.  ``VERIFIED_IDENTITY`` additionally requires a strong email binding and
    may be consumed by a governed identity operation.  ``use_decision`` remains orthogonal: even a
    verified email is not delivery-eligible when outreach use is denied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: ContactChannel
    observed_claim_id: ClaimId
    state: ContactChannelState
    identity_binding: IdentityBinding
    corroboration: ChannelIdentityCorroboration = ChannelIdentityCorroboration.NOT_CHECKED
    reachability: ChannelReachability = ChannelReachability.NOT_CHECKED
    use_decision: ChannelUseDecision = ChannelUseDecision.NOT_EVALUATED
    corroborating_claim_ids: tuple[ClaimId, ...] = ()
    validation_reference_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _state_has_required_evidence(self) -> ContactChannelValidation:
        if len(set(self.corroborating_claim_ids)) != len(self.corroborating_claim_ids):
            raise ValueError("channel corroborating claim references must be unique")
        if len(set(self.validation_reference_ids)) != len(self.validation_reference_ids):
            raise ValueError("channel validation references must be unique")
        if self.state is ContactChannelState.CORROBORATED and (
            self.corroboration is not ChannelIdentityCorroboration.MATCHED
            or not self.corroborating_claim_ids
        ):
            raise ValueError("corroborated channel requires an independent matching claim")
        if self.state in {
            ContactChannelState.VALIDATED,
            ContactChannelState.VERIFIED_IDENTITY,
        } and (
            self.corroboration is not ChannelIdentityCorroboration.MATCHED
            or not self.corroborating_claim_ids
            or self.reachability is not ChannelReachability.REACHABLE
            or not self.validation_reference_ids
        ):
            raise ValueError(
                "validated channel requires independent identity corroboration and a "
                "reachable validator result"
            )
        if self.state is ContactChannelState.VERIFIED_IDENTITY:
            if self.channel is not ContactChannel.EMAIL:
                raise ValueError("phone is delivery data and cannot become a verified identity")
            if self.identity_binding is not IdentityBinding.STRONG:
                raise ValueError("verified email identity requires strong identity binding")
        if self.state is ContactChannelState.REJECTED and not (
            self.corroboration is ChannelIdentityCorroboration.CONFLICTED
            or self.reachability is ChannelReachability.UNREACHABLE
            or self.use_decision is ChannelUseDecision.DENIED
        ):
            raise ValueError("rejected channel requires a conflict, unreachable result, or denial")
        return self

    @property
    def delivery_eligible(self) -> bool:
        """Whether the channel is both validated and independently allowed for outreach."""

        return (
            self.state
            in {
                ContactChannelState.VALIDATED,
                ContactChannelState.VERIFIED_IDENTITY,
            }
            and self.use_decision is ChannelUseDecision.ALLOWED
        )


class ContactChannelAuthorization(BaseModel):
    """One exact channel permission and its separately reserved budget."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: ContactChannel
    allowed: bool = False
    provider_source_keys: tuple[str, ...] = ()
    provider_native_unit_cap: int = Field(default=0, ge=0)
    budget_cap_cents: int = Field(default=0, ge=0)
    independent_validation_required: bool = False

    @model_validator(mode="after")
    def _authorization_is_fail_closed(self) -> ContactChannelAuthorization:
        if len(set(self.provider_source_keys)) != len(self.provider_source_keys):
            raise ValueError("channel provider source keys must be unique")
        if not self.allowed and (
            self.provider_source_keys
            or self.provider_native_unit_cap
            or self.budget_cap_cents
            or self.independent_validation_required
        ):
            raise ValueError("a disallowed channel cannot reserve a provider or budget")
        if self.allowed and (
            not self.provider_source_keys
            or not self.independent_validation_required
            or self.provider_native_unit_cap < 1
        ):
            raise ValueError(
                "an allowed reveal requires an admitted provider, native-unit cap, and "
                "independent validation"
            )
        return self


class ContactResearchTarget(BaseModel):
    """One exact canonical contact selected inside one canonical account."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    committee_claim_ids: tuple[ClaimId, ...] = Field(min_length=1)
    strong_identity_claim_ids: tuple[ClaimId, ...] = Field(min_length=1)
    field_keys: tuple[FieldKey, ...] = Field(min_length=1, max_length=32)
    directional_question_ids: tuple[str, ...] = Field(default=(), max_length=32)
    exa_max_results: int = Field(default=50, ge=1, le=50)
    email: ContactChannelAuthorization = ContactChannelAuthorization(channel=ContactChannel.EMAIL)
    phone: ContactChannelAuthorization = ContactChannelAuthorization(channel=ContactChannel.PHONE)

    @model_validator(mode="after")
    def _target_is_exact_and_unique(self) -> ContactResearchTarget:
        for label, values in (
            ("committee claim ids", self.committee_claim_ids),
            ("strong identity claim ids", self.strong_identity_claim_ids),
            ("field keys", self.field_keys),
            ("directional question ids", self.directional_question_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"contact research {label} must be unique")
        if self.email.channel is not ContactChannel.EMAIL:
            raise ValueError("email authorization must describe the email channel")
        if self.phone.channel is not ContactChannel.PHONE:
            raise ValueError("phone authorization must describe the phone channel")
        return self


class ContactResearchSelectionBody(BaseModel):
    """The content-addressed execution body of a selected-contact receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_run_id: ProjectRunId
    account_entity_id: EntityId
    research_directive: ResearchDirectivePin
    targets: tuple[ContactResearchTarget, ...] = Field(min_length=1, max_length=64)
    source_profile_ref: str = Field(min_length=1)
    jurisdiction_policy_ref: str = Field(min_length=1)
    use_policy_ref: str = Field(min_length=1)
    retention_policy_ref: str = Field(min_length=1)
    budget_reservation_ref: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: UtcDatetime

    @model_validator(mode="after")
    def _selection_is_scoped(self) -> ContactResearchSelectionBody:
        contact_ids = tuple(target.contact_entity_id for target in self.targets)
        if len(set(contact_ids)) != len(contact_ids):
            raise ValueError("a contact selection cannot repeat a canonical contact")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def sha256(self) -> Sha256Hex:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class ContactResearchSelection(BaseModel):
    """Immutable action-scoped authorization for selected-contact work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selection_id: ContactResearchSelectionId
    body: ContactResearchSelectionBody
    selection_sha256: Sha256Hex

    @model_validator(mode="after")
    def _digest_matches_body(self) -> ContactResearchSelection:
        if self.selection_sha256 != self.body.sha256():
            raise ValueError("contact research selection digest does not match its body")
        return self

    @classmethod
    def from_body(
        cls,
        body: ContactResearchSelectionBody,
        *,
        selection_id: ContactResearchSelectionId | None = None,
    ) -> ContactResearchSelection:
        return cls(
            selection_id=selection_id or new_contact_research_selection_id(),
            body=body,
            selection_sha256=body.sha256(),
        )


class ContactResearchIntent(BaseModel):
    """One exact-contact preparation request derived from a frozen selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_run_id: ProjectRunId
    account_entity_id: EntityId
    contact_entity_id: EntityId
    selection_id: ContactResearchSelectionId
    selection_sha256: Sha256Hex
    research_directive: ResearchDirectivePin
    field_keys: tuple[FieldKey, ...] = Field(min_length=1, max_length=32)
    directional_question_ids: tuple[str, ...] = Field(default=(), max_length=32)
    source_plan: tuple[str, ...] = Field(min_length=1, max_length=32)
    source_profile_ref: str = Field(min_length=1)
    freshness_policy_ref: str = Field(min_length=1)
    budget_reservation_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def _intent_lists_are_unique(self) -> ContactResearchIntent:
        for label, values in (
            ("field keys", self.field_keys),
            ("directional question ids", self.directional_question_ids),
            ("source plan", self.source_plan),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"contact research intent {label} must be unique")
        return self


class ContactPreparationStatus(StrEnum):
    READY = "ready"
    WAITING_EXTERNAL = "waiting_external"
    BUDGET_PAUSED = "budget_paused"
    NOT_ELIGIBLE = "not_eligible"
    FAILED = "failed"


class ContactResearchPreparation(BaseModel):
    """Reference-only result consumed by the provider-neutral orchestrator seam."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ContactPreparationStatus
    snapshot_reference_ids: tuple[str, ...] = ()
    operation_reference_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    next_wake_at: UtcDatetime | None = None
    spend_settlement_reference_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _outcome_is_coherent(self) -> ContactResearchPreparation:
        for label, values in (
            ("snapshot references", self.snapshot_reference_ids),
            ("operation references", self.operation_reference_ids),
            ("reason codes", self.reason_codes),
            ("spend settlement references", self.spend_settlement_reference_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"contact preparation {label} must be unique")
        if self.status is ContactPreparationStatus.READY and not self.snapshot_reference_ids:
            raise ValueError("ready contact preparation requires an immutable snapshot reference")
        if self.status is ContactPreparationStatus.WAITING_EXTERNAL and (
            not self.operation_reference_ids or self.next_wake_at is None
        ):
            raise ValueError("waiting contact preparation requires an operation and next wake")
        if (
            self.status
            in {
                ContactPreparationStatus.BUDGET_PAUSED,
                ContactPreparationStatus.NOT_ELIGIBLE,
                ContactPreparationStatus.FAILED,
            }
            and not self.reason_codes
        ):
            raise ValueError("non-ready terminal/paused preparation requires governed reasons")
        if self.status is not ContactPreparationStatus.WAITING_EXTERNAL and self.next_wake_at:
            raise ValueError("only waiting contact preparation may schedule a next wake")
        return self


@runtime_checkable
class ContactResearchPreparer(Protocol):
    """Prepare external contact work outside claim transactions, by registration."""

    async def prepare(self, intent: ContactResearchIntent) -> ContactResearchPreparation: ...


__all__ = [
    "CONTACT_CHANNEL_FIELD_KEYS",
    "CONTACT_PROFESSIONAL_FIELD_KEYS",
    "ChannelIdentityCorroboration",
    "ChannelReachability",
    "ChannelUseDecision",
    "ContactChannel",
    "ContactChannelAuthorization",
    "ContactChannelState",
    "ContactChannelValidation",
    "ContactPreparationStatus",
    "ContactResearchIntent",
    "ContactResearchPreparation",
    "ContactResearchPreparer",
    "ContactResearchSelection",
    "ContactResearchSelectionBody",
    "ContactResearchSelectionId",
    "ContactResearchTarget",
    "new_contact_research_selection_id",
]
