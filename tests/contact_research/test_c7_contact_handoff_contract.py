"""M8C C7 reference-only handoff and downstream content-consumer contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clue_core import (
    ContactChannel,
    ContactChannelCoverage,
    ContactChannelCoverageState,
    ContactContentBundle,
    ContactDeliveryChannelRef,
    ContactDraftingContextRef,
    ContactDraftingFallback,
    ContactHandoffClaimKind,
    ContactHandoffClaimRef,
    ContactHandoffCoverage,
    ContactResearchSelectionId,
    IdentityBinding,
    Persona,
    UseClass,
    UseDecision,
    UseReason,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
    new_research_view_id,
)

_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _professional() -> ContactHandoffClaimRef:
    return ContactHandoffClaimRef(
        claim_id=new_claim_id(),
        field_key="contact.current_title",
        kind=ContactHandoffClaimKind.PROFESSIONAL,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )


def _facet(*, allowed: bool = True) -> ContactHandoffClaimRef:
    claim_id = new_claim_id()
    return ContactHandoffClaimRef(
        claim_id=claim_id,
        field_key="contact.facet.publications",
        kind=ContactHandoffClaimKind.PERSONAL_FACET,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        use_decision=UseDecision(
            claim_id=claim_id,
            usable_for_outreach=allowed,
            reason=UseReason.ALLOWED if allowed else UseReason.USE_CLASS_DISALLOWED_FOR_REGIME,
            policy_version=1,
        ),
    )


def _coverage(*, channel_state: ContactChannelCoverageState) -> ContactHandoffCoverage:
    email_ref = None if channel_state is ContactChannelCoverageState.NOT_REQUESTED else "op:email"
    return ContactHandoffCoverage(
        attempted_field_keys=("contact.current_title", "contact.facet.publications"),
        filled_field_keys=("contact.current_title", "contact.facet.publications"),
        channels=(
            ContactChannelCoverage(
                channel=ContactChannel.EMAIL,
                state=channel_state,
                operation_ref=email_ref,
                reason_codes=(
                    ()
                    if channel_state is ContactChannelCoverageState.DELIVERY_ELIGIBLE
                    else ("email_not_requested",)
                ),
            ),
            ContactChannelCoverage(
                channel=ContactChannel.PHONE,
                state=ContactChannelCoverageState.NOT_REQUESTED,
                reason_codes=("phone_not_requested",),
            ),
        ),
        coverage_reason_codes=("committee_coverage_not_durable",),
    )


def test_drafting_context_accepts_only_strong_use_cleared_facets() -> None:
    facet = _facet()
    context = ContactDraftingContextRef(
        professional_claims=(_professional(),),
        personal_facet_claims=(facet,),
        fallback=ContactDraftingFallback.CONTACT_PERSONALIZED,
    )
    assert context.personal_facet_claims == (facet,)

    with pytest.raises(ValidationError, match="allowed exact-claim use decision"):
        _facet(allowed=False)
    with pytest.raises(ValidationError, match="raw contact-channel claims"):
        ContactHandoffClaimRef(
            claim_id=new_claim_id(),
            field_key="core.work_email",
            kind=ContactHandoffClaimKind.PROFESSIONAL,
        )


def test_missing_personal_evidence_requires_explicit_safe_fallback() -> None:
    account_ref = ContactHandoffClaimRef(
        claim_id=new_claim_id(),
        field_key="account.operational_pain",
        kind=ContactHandoffClaimKind.ACCOUNT_CONTEXT,
    )
    context = ContactDraftingContextRef(
        account_context_claims=(account_ref,),
        fallback=ContactDraftingFallback.ACCOUNT_LEVEL,
        reason_codes=("personal_evidence_missing_use_account_context",),
    )
    assert context.fallback is ContactDraftingFallback.ACCOUNT_LEVEL
    with pytest.raises(ValidationError, match="explicit reason"):
        ContactDraftingContextRef(
            fallback=ContactDraftingFallback.GENERIC_REVIEW,
        )


def test_delivery_ref_is_separate_and_cannot_accept_a_raw_channel_value() -> None:
    observed = new_claim_id()
    delivery = ContactDeliveryChannelRef(
        channel=ContactChannel.EMAIL,
        operation_id=uuid4(),
        operation_ref="contact-channel-operation:test",
        observed_claim_id=observed,
        corroborating_claim_ids=(new_claim_id(),),
        validation_reference_ids=("validator:test",),
        freshness_expires_at=_AT + timedelta(days=30),
        retention_expires_at=_AT + timedelta(days=90),
        retention_policy_ref="retention:test:v1",
    )
    assert "value" not in delivery.model_dump()
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ContactDeliveryChannelRef.model_validate(
            {**delivery.model_dump(), "raw_value": "person@example.test"}
        )


class _ReferenceOnlyContentConsumer:
    """The M8C fixture: content consumes ids and delivery refs, never research providers."""

    @staticmethod
    def consume(bundle: ContactContentBundle) -> dict[str, tuple[str, ...]]:
        drafting = bundle.drafting_context
        claims = (
            *drafting.professional_claims,
            *drafting.account_context_claims,
            *drafting.value_narrative_claims,
            *drafting.personal_facet_claims,
        )
        return {
            "drafting_claim_ids": tuple(str(item.claim_id) for item in claims),
            "delivery_operation_refs": tuple(
                item.operation_ref for item in bundle.delivery_channels
            ),
        }


def test_content_consumer_receives_claim_refs_and_delivery_refs_only() -> None:
    professional = _professional()
    facet = _facet()
    role_id = new_claim_id()
    persona_id = new_claim_id()
    delivery = ContactDeliveryChannelRef(
        channel=ContactChannel.EMAIL,
        operation_id=uuid4(),
        operation_ref="contact-channel-operation:test",
        observed_claim_id=new_claim_id(),
        corroborating_claim_ids=(new_claim_id(),),
        validation_reference_ids=("validator:test",),
        freshness_expires_at=_AT + timedelta(days=30),
        retention_expires_at=_AT + timedelta(days=90),
        retention_policy_ref="retention:test:v1",
    )
    bundle = ContactContentBundle(
        workspace_id="workspace-test",
        project_id="project-test",
        project_run_id=new_project_run_id(),
        product_id="product-test",
        account_entity_id=new_entity_id(),
        contact_entity_id=new_entity_id(),
        persona=Persona.CHAMPION,
        account_identity_ref="identity:account:test:v1",
        contact_identity_ref="identity:contact:test:v1",
        selection_id=ContactResearchSelectionId(uuid4()),
        selection_sha256="0" * 64,
        selection_ref="contact-selection:test",
        account_view_id=new_research_view_id(),
        contact_view_id=new_research_view_id(),
        account_view_state_sha256="1" * 64,
        contact_view_state_sha256="2" * 64,
        role_claim=ContactHandoffClaimRef(
            claim_id=role_id,
            field_key="contact.role_on_committee",
            kind=ContactHandoffClaimKind.ROLE,
            identity_binding=IdentityBinding.STRONG,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
        ),
        persona_claim=ContactHandoffClaimRef(
            claim_id=persona_id,
            field_key="contact.persona",
            kind=ContactHandoffClaimKind.PERSONA,
            identity_binding=IdentityBinding.STRONG,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
        ),
        drafting_context=ContactDraftingContextRef(
            professional_claims=(professional,),
            personal_facet_claims=(facet,),
            fallback=ContactDraftingFallback.CONTACT_PERSONALIZED,
        ),
        delivery_channels=(delivery,),
        coverage=_coverage(channel_state=ContactChannelCoverageState.DELIVERY_ELIGIBLE),
        use_policy_ref="use:test:v1",
        retention_policy_ref="retention:test:v1",
        composed_at=_AT,
    )
    consumed = _ReferenceOnlyContentConsumer.consume(bundle)
    assert consumed["drafting_claim_ids"] == (
        str(professional.claim_id),
        str(facet.claim_id),
    )
    assert consumed["delivery_operation_refs"] == (delivery.operation_ref,)
    serialized = bundle.model_dump_json()
    assert "person@example.test" not in serialized
    assert "core.work_email" not in serialized
    assert "core.direct_phone" not in serialized


def test_coverage_rejects_unclassified_or_overlapping_fields() -> None:
    with pytest.raises(ValidationError, match="every attempted contact field"):
        ContactHandoffCoverage(
            attempted_field_keys=("contact.current_title",),
            coverage_reason_codes=("committee_coverage_not_durable",),
            channels=(
                ContactChannelCoverage(
                    channel=ContactChannel.EMAIL,
                    state=ContactChannelCoverageState.NOT_REQUESTED,
                    reason_codes=("not_requested",),
                ),
                ContactChannelCoverage(
                    channel=ContactChannel.PHONE,
                    state=ContactChannelCoverageState.NOT_REQUESTED,
                    reason_codes=("not_requested",),
                ),
            ),
        )
    with pytest.raises(ValidationError, match="dispositions must be disjoint"):
        ContactHandoffCoverage(
            attempted_field_keys=("contact.current_title",),
            filled_field_keys=("contact.current_title",),
            conflicted_field_keys=("contact.current_title",),
            coverage_reason_codes=("committee_coverage_not_durable",),
            channels=(
                ContactChannelCoverage(
                    channel=ContactChannel.EMAIL,
                    state=ContactChannelCoverageState.NOT_REQUESTED,
                    reason_codes=("not_requested",),
                ),
                ContactChannelCoverage(
                    channel=ContactChannel.PHONE,
                    state=ContactChannelCoverageState.NOT_REQUESTED,
                    reason_codes=("not_requested",),
                ),
            ),
        )
