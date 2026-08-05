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
from clue_core.field import FieldClass, FieldKey, classify_field_key
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


class ContactResearchPolicyPin(BaseModel):
    """The exact resolved contact-research policy embedded in an authorization receipt.

    ``clue_config`` owns layering and produces this pin from the effective workspace/ICP policy.
    Embedding the resolved values makes the receipt self-validating and content-addresses every
    cap, source family, freshness rule, provider-contract reference, and reveal permission that can
    affect downstream work.  A later durable compiler must still prove that the pin came from the
    effective config revision; it cannot widen a receipt after approval.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: int = Field(default=1, ge=1)
    contract_ref: str = Field(default="M8C-C0@2026-08-05", min_length=1)
    sumble_runtime_contract_ref: str = Field(default="sumble-rest-v9@2026-08-05", min_length=1)
    sumble_public_reference_ref: str = Field(
        default="sumble-public-v3@2026-08-05-non-authorizing", min_length=1
    )
    # C3's accepted contact-targeted compiler contract; C4 still owns dispatch/live acquisition.
    exa_search_contract_ref: str = Field(
        default="m8c-c3-exa-contact-compiler@2026-08-05", min_length=1
    )
    exa_websets_contract_ref: str = Field(
        default="exa-websets-reference@2026-08-05-non-authorizing", min_length=1
    )
    max_selected_contacts: int = Field(default=3, ge=1, le=20)
    max_fields_per_contact: int = Field(default=8, ge=1, le=32)
    exa_max_results: int = Field(default=50, ge=1, le=50)
    exa_max_additional_queries: int = Field(default=10, ge=0, le=10)
    professional_source_plan: tuple[str, ...] = ("sumble_people", "sumble_teams")
    personal_facet_source_plan: tuple[str, ...] = ("exa_deep",)
    channel_reveal_source_plan: tuple[str, ...] = ()
    professional_freshness_days: int = Field(default=30, ge=1, le=365)
    personal_facet_freshness_days: int = Field(default=30, ge=1, le=365)
    contact_reveals_enabled: bool = False
    email_reveal_native_unit_cap: int = Field(default=0, ge=0)
    phone_reveal_native_unit_cap: int = Field(default=0, ge=0)
    email_reveal_budget_cents: int = Field(default=0, ge=0)
    phone_reveal_budget_cents: int = Field(default=0, ge=0)
    phone_identity_promotion_allowed: bool = False
    approved_strong_profile_hosts: tuple[str, ...] = ("linkedin.com",)

    @model_validator(mode="after")
    def _policy_is_bounded_and_fail_closed(self) -> ContactResearchPolicyPin:
        for label, values in (
            ("professional source plan", self.professional_source_plan),
            ("personal facet source plan", self.personal_facet_source_plan),
            ("channel reveal source plan", self.channel_reveal_source_plan),
            ("strong profile hosts", self.approved_strong_profile_hosts),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"contact research {label} must be unique")
            if any(not value.strip() for value in values):
                raise ValueError(f"contact research {label} cannot contain an empty value")
        if not self.professional_source_plan or not self.personal_facet_source_plan:
            raise ValueError("contact research requires professional and personal-facet plans")
        if self.phone_identity_promotion_allowed:
            raise ValueError("phone remains delivery data and can never be an identity key")
        reveal_budgets = (
            self.email_reveal_native_unit_cap,
            self.phone_reveal_native_unit_cap,
            self.email_reveal_budget_cents,
            self.phone_reveal_budget_cents,
        )
        if not self.contact_reveals_enabled and (
            self.channel_reveal_source_plan or any(reveal_budgets)
        ):
            raise ValueError("disabled contact reveals require no provider plan and zero budgets")
        if self.contact_reveals_enabled and (
            not self.channel_reveal_source_plan or not any(reveal_budgets)
        ):
            raise ValueError("enabled contact reveals require providers and a non-zero reservation")
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

    @property
    def freshness_policy_ref(self) -> str:
        return f"contact-research-freshness:{self.sha256()}"


class ContactProviderFailureClass(StrEnum):
    """Closed failure categories shared by future C3/C4/C5 contact providers."""

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    INSUFFICIENT_CREDIT = "insufficient_credit"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    TRANSPORT = "transport"


class ContactProviderFailureDisposition(StrEnum):
    HARD = "hard"
    BUDGET_PAUSED = "budget_paused"
    RETRYABLE = "retryable"
    SPEND_UNKNOWN = "spend_unknown"


class ContactProviderFailure(BaseModel):
    """Body-independent HTTP failure classification with honest dispatch/spend semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status_code: int | None = Field(default=None, ge=100, le=599)
    failure_class: ContactProviderFailureClass
    disposition: ContactProviderFailureDisposition
    dispatched: bool
    retry_after_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _retry_after_is_rate_limit_only(self) -> ContactProviderFailure:
        if self.retry_after_seconds is not None and (
            self.failure_class is not ContactProviderFailureClass.RATE_LIMIT
        ):
            raise ValueError("Retry-After is valid only for a rate-limit response")
        return self


def classify_contact_provider_failure(
    status_code: int | None,
    *,
    dispatched: bool,
    retry_after_seconds: int | None = None,
) -> ContactProviderFailure:
    """Classify a provider failure without trusting an undocumented error-body schema.

    A transport failure or retryable HTTP response after possible dispatch is spend-unknown. Before
    dispatch it is retryable. Authentication/validation are hard, while an explicit 402 is the
    independently governed insufficient-credit/budget pause. This is intentionally provider-neutral:
    Sumble and Exa bodies may change, but HTTP status, dispatch evidence, and
    ``Retry-After`` are the executable contract.
    """

    if status_code is not None and 200 <= status_code <= 299:
        raise ValueError("a successful HTTP status is not a provider failure")
    if status_code in {401, 403}:
        failure_class = ContactProviderFailureClass.AUTHENTICATION
        disposition = ContactProviderFailureDisposition.HARD
    elif status_code == 402:
        failure_class = ContactProviderFailureClass.INSUFFICIENT_CREDIT
        disposition = ContactProviderFailureDisposition.BUDGET_PAUSED
    elif status_code == 429:
        failure_class = ContactProviderFailureClass.RATE_LIMIT
        disposition = (
            ContactProviderFailureDisposition.SPEND_UNKNOWN
            if dispatched
            else ContactProviderFailureDisposition.RETRYABLE
        )
    elif status_code is not None and 500 <= status_code <= 599:
        failure_class = ContactProviderFailureClass.SERVER
        disposition = (
            ContactProviderFailureDisposition.SPEND_UNKNOWN
            if dispatched
            else ContactProviderFailureDisposition.RETRYABLE
        )
    elif status_code is None or status_code in {408, 425}:
        failure_class = ContactProviderFailureClass.TRANSPORT
        disposition = (
            ContactProviderFailureDisposition.SPEND_UNKNOWN
            if dispatched
            else ContactProviderFailureDisposition.RETRYABLE
        )
    else:
        failure_class = ContactProviderFailureClass.VALIDATION
        disposition = ContactProviderFailureDisposition.HARD
    return ContactProviderFailure(
        status_code=status_code,
        failure_class=failure_class,
        disposition=disposition,
        dispatched=dispatched,
        retry_after_seconds=retry_after_seconds,
    )


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


def _validate_target_field_scope(target: ContactResearchTarget) -> None:
    professional = set(CONTACT_PROFESSIONAL_FIELD_KEYS)
    channels = set(CONTACT_CHANNEL_FIELD_KEYS.values())
    for field_key in target.field_keys:
        token = str(field_key)
        if token in professional or token in channels:
            continue
        if classify_field_key(field_key) is FieldClass.CONTACT_FACET:
            continue
        raise ValueError(
            f"contact research target field {token!r} is not a professional fact, "
            "personal facet, or separately authorized channel"
        )


def _source_plan_for(
    target: ContactResearchTarget,
    policy: ContactResearchPolicyPin,
) -> tuple[str, ...]:
    """Compile the complete, ordered, non-widenable source plan for one selected contact."""

    field_tokens = {str(field_key) for field_key in target.field_keys}
    sources: list[str] = []
    if field_tokens.intersection(CONTACT_PROFESSIONAL_FIELD_KEYS):
        sources.extend(policy.professional_source_plan)
    if any(
        classify_field_key(field_key) is FieldClass.CONTACT_FACET for field_key in target.field_keys
    ):
        sources.extend(policy.personal_facet_source_plan)
    if CONTACT_CHANNEL_FIELD_KEYS[ContactChannel.EMAIL] in field_tokens:
        sources.extend(target.email.provider_source_keys)
    if CONTACT_CHANNEL_FIELD_KEYS[ContactChannel.PHONE] in field_tokens:
        sources.extend(target.phone.provider_source_keys)
    return tuple(dict.fromkeys(sources))


class ContactResearchSelectionBody(BaseModel):
    """The content-addressed execution body of a selected-contact receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_run_id: ProjectRunId
    account_entity_id: EntityId
    research_directive: ResearchDirectivePin
    targets: tuple[ContactResearchTarget, ...] = Field(min_length=1, max_length=20)
    policy: ContactResearchPolicyPin
    source_profile_ref: str = Field(min_length=1)
    jurisdiction_policy_ref: str = Field(min_length=1)
    use_policy_ref: str = Field(min_length=1)
    retention_policy_ref: str = Field(min_length=1)
    budget_reservation_ref: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: UtcDatetime

    @model_validator(mode="after")
    def _selection_is_scoped(self) -> ContactResearchSelectionBody:
        if self.research_directive.account_id != self.account_entity_id:
            raise ValueError(
                "contact selection directive must belong to the exact selected account"
            )
        contact_ids = tuple(target.contact_entity_id for target in self.targets)
        if len(set(contact_ids)) != len(contact_ids):
            raise ValueError("a contact selection cannot repeat a canonical contact")
        if len(self.targets) > self.policy.max_selected_contacts:
            raise ValueError("contact selection exceeds the effective policy contact cap")

        channel_totals = {
            ContactChannel.EMAIL: {"native": 0, "money": 0},
            ContactChannel.PHONE: {"native": 0, "money": 0},
        }
        for target in self.targets:
            if len(target.field_keys) > self.policy.max_fields_per_contact:
                raise ValueError("contact selection target exceeds the effective policy field cap")
            if target.exa_max_results > self.policy.exa_max_results:
                raise ValueError("contact selection target exceeds the effective Exa result cap")
            if len(target.directional_question_ids) > self.policy.exa_max_additional_queries:
                raise ValueError(
                    "contact selection target exceeds the effective additional-query cap"
                )
            _validate_target_field_scope(target)
            for channel, authorization in (
                (ContactChannel.EMAIL, target.email),
                (ContactChannel.PHONE, target.phone),
            ):
                channel_field = CONTACT_CHANNEL_FIELD_KEYS[channel]
                if authorization.allowed != (channel_field in target.field_keys):
                    raise ValueError(
                        f"{channel.value} authorization must exactly match selection of "
                        f"{channel_field}"
                    )
                if not authorization.allowed:
                    continue
                if not self.policy.contact_reveals_enabled:
                    raise ValueError("contact selection cannot enable a policy-disabled reveal")
                if not set(authorization.provider_source_keys).issubset(
                    self.policy.channel_reveal_source_plan
                ):
                    raise ValueError(
                        "contact selection channel provider is outside the effective policy plan"
                    )
                channel_totals[channel]["native"] += authorization.provider_native_unit_cap
                channel_totals[channel]["money"] += authorization.budget_cap_cents

        for channel, native_cap, money_cap in (
            (
                ContactChannel.EMAIL,
                self.policy.email_reveal_native_unit_cap,
                self.policy.email_reveal_budget_cents,
            ),
            (
                ContactChannel.PHONE,
                self.policy.phone_reveal_native_unit_cap,
                self.policy.phone_reveal_budget_cents,
            ),
        ):
            if channel_totals[channel]["native"] > native_cap:
                raise ValueError(
                    f"contact selection exceeds the effective {channel.value} native-unit cap"
                )
            if channel_totals[channel]["money"] > money_cap:
                raise ValueError(
                    f"contact selection exceeds the effective {channel.value} money cap"
                )
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
        effective_policy: ContactResearchPolicyPin,
        selection_id: ContactResearchSelectionId | None = None,
    ) -> ContactResearchSelection:
        if body.policy != effective_policy:
            raise ValueError(
                "contact research selection policy differs from the effective config policy"
            )
        return cls(
            selection_id=selection_id or new_contact_research_selection_id(),
            body=body,
            selection_sha256=body.sha256(),
        )

    def require_effective_policy(self, effective_policy: ContactResearchPolicyPin) -> None:
        """Fail closed when a later compiler resolves a different effective policy revision."""

        if self.body.policy != effective_policy:
            raise ValueError(
                "contact research selection no longer matches the effective config policy"
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
    selection: ContactResearchSelection
    research_directive: ResearchDirectivePin
    field_keys: tuple[FieldKey, ...] = Field(min_length=1, max_length=32)
    directional_question_ids: tuple[str, ...] = Field(default=(), max_length=32)
    source_plan: tuple[str, ...] = Field(min_length=1, max_length=32)
    source_profile_ref: str = Field(min_length=1)
    freshness_policy_ref: str = Field(min_length=1)
    budget_reservation_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def _intent_is_an_exact_selection_projection(self) -> ContactResearchIntent:
        for label, values in (
            ("field keys", self.field_keys),
            ("directional question ids", self.directional_question_ids),
            ("source plan", self.source_plan),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"contact research intent {label} must be unique")
        body = self.selection.body
        if (
            self.selection_id != self.selection.selection_id
            or self.selection_sha256 != self.selection.selection_sha256
        ):
            raise ValueError("contact research intent selection reference is inconsistent")
        if (
            self.workspace_id != body.workspace_id
            or self.project_id != body.project_id
            or self.project_run_id != body.project_run_id
            or self.account_entity_id != body.account_entity_id
            or self.research_directive != body.research_directive
            or self.source_profile_ref != body.source_profile_ref
            or self.budget_reservation_ref != body.budget_reservation_ref
        ):
            raise ValueError("contact research intent widens or changes its parent selection")
        target = next(
            (
                candidate
                for candidate in body.targets
                if candidate.contact_entity_id == self.contact_entity_id
            ),
            None,
        )
        if target is None:
            raise ValueError("contact research intent contact is absent from its parent selection")
        if (
            self.field_keys != target.field_keys
            or self.directional_question_ids != target.directional_question_ids
        ):
            raise ValueError(
                "contact research intent fields/questions differ from the selected target"
            )
        if self.source_plan != _source_plan_for(target, body.policy):
            raise ValueError("contact research intent source plan differs from effective policy")
        if self.freshness_policy_ref != body.policy.freshness_policy_ref:
            raise ValueError(
                "contact research intent freshness policy differs from effective policy"
            )
        return self

    @classmethod
    def from_selection(
        cls,
        selection: ContactResearchSelection,
        *,
        contact_entity_id: EntityId,
    ) -> ContactResearchIntent:
        """Derive the sole valid exact-contact intent projection from an approved selection."""

        body = selection.body
        target = next(
            (
                candidate
                for candidate in body.targets
                if candidate.contact_entity_id == contact_entity_id
            ),
            None,
        )
        if target is None:
            raise ValueError("cannot derive contact intent for an unselected contact")
        return cls(
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            project_run_id=body.project_run_id,
            account_entity_id=body.account_entity_id,
            contact_entity_id=target.contact_entity_id,
            selection_id=selection.selection_id,
            selection_sha256=selection.selection_sha256,
            selection=selection,
            research_directive=body.research_directive,
            field_keys=target.field_keys,
            directional_question_ids=target.directional_question_ids,
            source_plan=_source_plan_for(target, body.policy),
            source_profile_ref=body.source_profile_ref,
            freshness_policy_ref=body.policy.freshness_policy_ref,
            budget_reservation_ref=body.budget_reservation_ref,
        )

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def sha256(self) -> Sha256Hex:
        """Stable intent material; C3 adds its exact provider wire contract to the fingerprint."""

        return hashlib.sha256(self.canonical_bytes()).hexdigest()


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
    "ContactProviderFailure",
    "ContactProviderFailureClass",
    "ContactProviderFailureDisposition",
    "ContactResearchIntent",
    "ContactResearchPolicyPin",
    "ContactResearchPreparation",
    "ContactResearchPreparer",
    "ContactResearchSelection",
    "ContactResearchSelectionBody",
    "ContactResearchSelectionId",
    "ContactResearchTarget",
    "classify_contact_provider_failure",
    "new_contact_research_selection_id",
]
