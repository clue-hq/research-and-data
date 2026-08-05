"""Reference-only contact research handoff for downstream content consumers (M8C C7).

The handoff is a projection over the claim store, research views, the immutable selected-contact
receipt, and the channel ledger.  It is deliberately not another truth store and it carries no
claim values.  In particular, validated email/phone observations remain delivery references and
can never enter the generic drafting context.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core.compliance import UseDecision
from clue_core.contact_channel import ContactChannelOperationId
from clue_core.contact_research import (
    CONTACT_CHANNEL_FIELD_KEYS,
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    ContactChannel,
    ContactResearchSelectionId,
)
from clue_core.discovery import Sha256Hex
from clue_core.enums import IdentityBinding, Persona, ResearchConflictState, UseClass
from clue_core.field import FieldKey
from clue_core.primitives import ClaimId, EntityId, ProjectRunId, UtcDatetime
from clue_core.research_view import ResearchViewId


class ContactHandoffClaimKind(StrEnum):
    ROLE = "role"
    PERSONA = "persona"
    PROFESSIONAL = "professional"
    ACCOUNT_CONTEXT = "account_context"
    VALUE_NARRATIVE = "value_narrative"
    PERSONAL_FACET = "personal_facet"


class ContactDraftingFallback(StrEnum):
    CONTACT_PERSONALIZED = "contact_personalized"
    ACCOUNT_LEVEL = "account_level"
    GENERIC_REVIEW = "generic_review"


class ContactChannelCoverageState(StrEnum):
    DELIVERY_ELIGIBLE = "delivery_eligible"
    EXCLUDED = "excluded"
    FAILED_VALIDATION = "failed_validation"
    NOT_REQUESTED = "not_requested"


class ContactHandoffClaimRef(BaseModel):
    """One governed claim edge.  Values and evidence bodies stay behind the claim id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    field_key: FieldKey
    kind: ContactHandoffClaimKind
    support_claim_ids: tuple[ClaimId, ...] = ()
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    use_decision: UseDecision | None = None
    conflict: ResearchConflictState = ResearchConflictState.NONE

    @model_validator(mode="after")
    def _is_safe_for_its_declared_use(self) -> ContactHandoffClaimRef:
        field = str(self.field_key)
        if field in set(CONTACT_CHANNEL_FIELD_KEYS.values()):
            raise ValueError("raw contact-channel claims cannot enter the drafting handoff")
        if len(self.support_claim_ids) != len(set(self.support_claim_ids)):
            raise ValueError("handoff support claim ids must be unique")
        if self.claim_id in self.support_claim_ids:
            raise ValueError("a handoff claim cannot support itself")

        if self.kind is ContactHandoffClaimKind.ROLE and field != "contact.role_on_committee":
            raise ValueError("role refs require contact.role_on_committee")
        if self.kind is ContactHandoffClaimKind.PERSONA and field != "contact.persona":
            raise ValueError("persona refs require contact.persona")
        if self.kind is ContactHandoffClaimKind.PROFESSIONAL and field not in set(
            CONTACT_PROFESSIONAL_FIELD_KEYS
        ):
            raise ValueError("professional refs require a registered professional field")
        if self.kind is ContactHandoffClaimKind.VALUE_NARRATIVE and field != (
            "account.value_narrative"
        ):
            raise ValueError("value-narrative refs require account.value_narrative")

        facet = field.startswith("contact.facet.")
        if facet != (self.kind is ContactHandoffClaimKind.PERSONAL_FACET):
            raise ValueError("contact.facet.* and personal_facet kind must agree")
        if facet:
            if self.identity_binding is not IdentityBinding.STRONG:
                raise ValueError("personalized facets require strong identity binding")
            if (
                self.use_decision is None
                or self.use_decision.claim_id != self.claim_id
                or not self.use_decision.usable_for_outreach
            ):
                raise ValueError("personalized facets require an allowed exact-claim use decision")
            if self.use_class is None or self.use_class is UseClass.SENSITIVE:
                raise ValueError("sensitive or unclassified facets cannot enter drafting")
        elif self.use_decision is not None and self.use_decision.claim_id != self.claim_id:
            raise ValueError("a use decision must refer to the same claim")
        return self


class ContactDraftingContextRef(BaseModel):
    """Claim refs available to content planning/drafting; never delivery coordinates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    professional_claims: tuple[ContactHandoffClaimRef, ...] = ()
    account_context_claims: tuple[ContactHandoffClaimRef, ...] = ()
    value_narrative_claims: tuple[ContactHandoffClaimRef, ...] = ()
    personal_facet_claims: tuple[ContactHandoffClaimRef, ...] = ()
    fallback: ContactDraftingFallback
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _categories_and_fallback_are_coherent(self) -> ContactDraftingContextRef:
        expected = (
            (self.professional_claims, ContactHandoffClaimKind.PROFESSIONAL),
            (self.account_context_claims, ContactHandoffClaimKind.ACCOUNT_CONTEXT),
            (self.value_narrative_claims, ContactHandoffClaimKind.VALUE_NARRATIVE),
            (self.personal_facet_claims, ContactHandoffClaimKind.PERSONAL_FACET),
        )
        all_refs: list[ContactHandoffClaimRef] = []
        for refs, kind in expected:
            if any(item.kind is not kind for item in refs):
                raise ValueError(f"drafting context contains a ref outside {kind.value}")
            all_refs.extend(refs)
        if len({item.claim_id for item in all_refs}) != len(all_refs):
            raise ValueError("drafting context claim ids must be unique")
        if self.personal_facet_claims:
            expected_fallback = ContactDraftingFallback.CONTACT_PERSONALIZED
        elif self.account_context_claims or self.value_narrative_claims:
            expected_fallback = ContactDraftingFallback.ACCOUNT_LEVEL
        else:
            expected_fallback = ContactDraftingFallback.GENERIC_REVIEW
        if self.fallback is not expected_fallback:
            raise ValueError("drafting fallback does not match available governed evidence")
        if self.fallback is not ContactDraftingFallback.CONTACT_PERSONALIZED and not (
            self.reason_codes
        ):
            raise ValueError("a non-personalized fallback requires an explicit reason")
        return self


class ContactDeliveryChannelRef(BaseModel):
    """Validated delivery capability with no email/phone value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: ContactChannel
    operation_id: ContactChannelOperationId
    operation_ref: str = Field(min_length=1)
    observed_claim_id: ClaimId
    corroborating_claim_ids: tuple[ClaimId, ...]
    validation_reference_ids: tuple[str, ...]
    freshness_expires_at: UtcDatetime
    retention_expires_at: UtcDatetime
    retention_policy_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def _has_independent_validation(self) -> ContactDeliveryChannelRef:
        if not self.corroborating_claim_ids or not self.validation_reference_ids:
            raise ValueError("delivery refs require independent validation references")
        if len(set(self.corroborating_claim_ids)) != len(self.corroborating_claim_ids):
            raise ValueError("delivery corroborating claim ids must be unique")
        if len(set(self.validation_reference_ids)) != len(self.validation_reference_ids):
            raise ValueError("delivery validation references must be unique")
        # Retention may equal freshness, but it may never expire first because then the capability
        # would be unusable for part of its advertised freshness interval.
        if self.retention_expires_at < self.freshness_expires_at:
            raise ValueError("channel retention cannot expire before freshness")
        return self


class ContactChannelCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: ContactChannel
    state: ContactChannelCoverageState
    operation_ref: str | None = None
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _state_has_the_right_reference(self) -> ContactChannelCoverage:
        if (
            self.state is ContactChannelCoverageState.NOT_REQUESTED
            and self.operation_ref is not None
        ):
            raise ValueError("a not-requested channel cannot carry an operation ref")
        if (
            self.state is not ContactChannelCoverageState.NOT_REQUESTED
            and self.operation_ref is None
        ):
            raise ValueError("an attempted channel requires its durable operation ref")
        if (
            self.state is not ContactChannelCoverageState.DELIVERY_ELIGIBLE
            and not self.reason_codes
        ):
            raise ValueError("a non-deliverable channel requires an explicit reason")
        return self


class ContactHandoffCoverage(BaseModel):
    """Truthful partial-completion projection for one selected contact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempted_field_keys: tuple[FieldKey, ...]
    filled_field_keys: tuple[FieldKey, ...] = ()
    empty_field_keys: tuple[FieldKey, ...] = ()
    conflicted_field_keys: tuple[FieldKey, ...] = ()
    blocked_field_keys: tuple[FieldKey, ...] = ()
    searched_source_keys: tuple[str, ...] = ()
    unsearched_source_keys: tuple[str, ...] = ()
    channels: tuple[ContactChannelCoverage, ...]
    committee_coverage_estimate: float | None = Field(default=None, ge=0, le=1)
    coverage_reason_codes: tuple[str, ...] = ()
    coverage_ref_ids: tuple[str, ...] = ()
    stop_reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _field_and_source_partitions_are_exact(self) -> ContactHandoffCoverage:
        attempted = set(self.attempted_field_keys)
        groups = (
            set(self.filled_field_keys),
            set(self.empty_field_keys),
            set(self.conflicted_field_keys),
            set(self.blocked_field_keys),
        )
        if any(not group.issubset(attempted) for group in groups):
            raise ValueError("contact coverage classifies only attempted fields")
        if set().union(*groups) != attempted:
            raise ValueError("every attempted contact field requires one coverage disposition")
        for index, group in enumerate(groups):
            if any(group.intersection(other) for other in groups[index + 1 :]):
                raise ValueError("contact field coverage dispositions must be disjoint")
        searched = set(self.searched_source_keys)
        unsearched = set(self.unsearched_source_keys)
        if searched.intersection(unsearched):
            raise ValueError("a source cannot be both searched and unsearched")
        if {item.channel for item in self.channels} != set(ContactChannel):
            raise ValueError("coverage must classify both email and phone")
        if self.committee_coverage_estimate is None and not self.coverage_reason_codes:
            raise ValueError("missing committee coverage requires an explicit reason")
        return self


class ContactContentBundle(BaseModel):
    """One exact ``account x contact x persona`` content-facing research bundle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_run_id: ProjectRunId
    product_id: str | None = None
    account_entity_id: EntityId
    contact_entity_id: EntityId
    persona: Persona
    account_identity_ref: str = Field(min_length=1)
    contact_identity_ref: str = Field(min_length=1)
    selection_id: ContactResearchSelectionId
    selection_sha256: Sha256Hex
    selection_ref: str = Field(min_length=1)
    account_view_id: ResearchViewId
    contact_view_id: ResearchViewId
    account_view_state_sha256: Sha256Hex
    contact_view_state_sha256: Sha256Hex
    role_claim: ContactHandoffClaimRef
    persona_claim: ContactHandoffClaimRef
    drafting_context: ContactDraftingContextRef
    delivery_channels: tuple[ContactDeliveryChannelRef, ...] = ()
    coverage: ContactHandoffCoverage
    use_policy_ref: str = Field(min_length=1)
    retention_policy_ref: str = Field(min_length=1)
    composed_at: UtcDatetime

    @model_validator(mode="after")
    def _bundle_keeps_drafting_and_delivery_separate(self) -> ContactContentBundle:
        if self.role_claim.kind is not ContactHandoffClaimKind.ROLE:
            raise ValueError("bundle role_claim has the wrong kind")
        if self.persona_claim.kind is not ContactHandoffClaimKind.PERSONA:
            raise ValueError("bundle persona_claim has the wrong kind")
        if len({item.channel for item in self.delivery_channels}) != len(self.delivery_channels):
            raise ValueError("a bundle may expose at most one delivery ref per channel")
        eligible = {
            item.channel
            for item in self.coverage.channels
            if item.state is ContactChannelCoverageState.DELIVERY_ELIGIBLE
        }
        if eligible != {item.channel for item in self.delivery_channels}:
            raise ValueError("delivery refs and channel coverage eligibility must agree")
        return self


class ContactHandoffExclusion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    selected: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)


class ContactContentHandoff(BaseModel):
    """Account-level projection naming selected bundles and every skipped/excluded contact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_run_id: ProjectRunId
    product_id: str | None = None
    account_entity_id: EntityId
    bundles: tuple[ContactContentBundle, ...] = ()
    exclusions: tuple[ContactHandoffExclusion, ...] = ()
    reason_codes: tuple[str, ...] = ()
    composed_at: UtcDatetime

    @model_validator(mode="after")
    def _contacts_are_classified_once(self) -> ContactContentHandoff:
        bundled = {item.contact_entity_id for item in self.bundles}
        excluded = {item.contact_entity_id for item in self.exclusions}
        if len(bundled) != len(self.bundles) or len(excluded) != len(self.exclusions):
            raise ValueError("handoff contacts must be unique")
        if bundled.intersection(excluded):
            raise ValueError("a contact cannot be both bundled and excluded")
        if not self.bundles and not self.reason_codes:
            raise ValueError("an empty handoff requires an explicit reason")
        return self


__all__ = [
    "ContactChannelCoverage",
    "ContactChannelCoverageState",
    "ContactContentBundle",
    "ContactContentHandoff",
    "ContactDeliveryChannelRef",
    "ContactDraftingContextRef",
    "ContactDraftingFallback",
    "ContactHandoffClaimKind",
    "ContactHandoffClaimRef",
    "ContactHandoffCoverage",
    "ContactHandoffExclusion",
]
