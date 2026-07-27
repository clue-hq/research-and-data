"""C7.0 contract-freeze tests for structured account/contact research views."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_core import (
    AccountResearchView,
    ContactResearchView,
    DerivationEntailmentJudge,
    DisplayDecision,
    DossierBlockKind,
    EntailmentJudgeRequest,
    EntailmentJudgeResult,
    EntailmentReasonCode,
    EntailmentVerdictKind,
    EntityType,
    EvidenceActionDescriptor,
    EvidenceActionKind,
    FreshnessState,
    IdentityBinding,
    OutreachDecision,
    ResearchAvailability,
    ResearchConflictState,
    ResearchCoverageSummary,
    ResearchDataSpecies,
    ResearchItemState,
    ResearchOwnedReference,
    ResearchPersonalizationItem,
    ResearchProvenanceRef,
    ResearchReferenceRelation,
    ResearchSection,
    ResearchSectionKind,
    ResearchStatement,
    ResearchStatementKind,
    ResearchStatusSummary,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchSupportRole,
    ResearchViewChangeReportRef,
    ResearchViewComposer,
    ResearchViewReader,
    ResearchViewReadRequest,
    ResearchViewReceipt,
    ResearchViewRef,
    ResearchViewSnapshotReader,
    UseClass,
    VerificationStatus,
    new_claim_id,
    new_entity_id,
    new_operation_id,
    new_project_run_id,
    new_research_statement_id,
    new_research_view_change_report_id,
    new_research_view_id,
    new_research_view_snapshot_id,
)

_NOW = datetime(2026, 7, 27, tzinfo=UTC)
_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _account_subject() -> ResearchSubjectRef:
    return ResearchSubjectRef(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        canonical_entity_version=1,
    )


def _contact_subject(parent: ResearchSubjectRef | None = None) -> ResearchSubjectRef:
    account = parent or _account_subject()
    return ResearchSubjectRef(
        entity_id=new_entity_id(),
        entity_type=EntityType.CONTACT,
        canonical_entity_version=1,
        parent_account_id=account.entity_id,
    )


def _available_state(*, outreach: OutreachDecision) -> ResearchItemState:
    return ResearchItemState(
        availability=ResearchAvailability.AVAILABLE,
        verification=VerificationStatus.VERIFIED,
        freshness=FreshnessState.FRESH,
        conflict=ResearchConflictState.NONE,
        display_decision=DisplayDecision.ALLOWED,
        outreach_decision=outreach,
    )


def _direct_account_statement(
    subject: ResearchSubjectRef | None = None,
    *,
    product_id: str | None = None,
) -> ResearchStatement:
    target = subject or _account_subject()
    claim_id = new_claim_id()
    return ResearchStatement(
        statement_id=new_research_statement_id(),
        subject=target,
        field_key="account.summary",
        value_json="Synthetic account summary.",
        statement_kind=ResearchStatementKind.DIRECT,
        claim_id=claim_id,
        product_id=product_id,
        state=_available_state(outreach=OutreachDecision.NOT_APPLICABLE),
        confidence=0.9,
        collected_at=_NOW,
        evidence_actions=(
            EvidenceActionDescriptor(
                kind=EvidenceActionKind.OPEN_PUBLIC_SOURCE,
                claim_id=claim_id,
                action_id=UUID("00000000-0000-0000-0000-000000000201"),
            ),
        ),
    )


def _safe_contact_statement(subject: ResearchSubjectRef | None = None) -> ResearchStatement:
    target = subject or _contact_subject()
    return ResearchStatement(
        statement_id=new_research_statement_id(),
        subject=target,
        field_key="contact.facet.public_talk",
        value_json="Presented a public technical session.",
        statement_kind=ResearchStatementKind.DIRECT,
        claim_id=new_claim_id(),
        state=_available_state(outreach=OutreachDecision.ALLOWED),
        confidence=0.93,
        collected_at=_NOW,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )


def _account_view(
    *,
    subject: ResearchSubjectRef | None = None,
    statement: ResearchStatement | None = None,
    product_id: str | None = None,
) -> AccountResearchView:
    target = subject or _account_subject()
    item = statement or _direct_account_statement(target, product_id=product_id)
    return AccountResearchView(
        view_id=new_research_view_id(),
        workspace_id="workspace-fixture",
        project_id="project-fixture",
        project_run_id=new_project_run_id(),
        subject=target,
        product_id=product_id,
        composed_at=_NOW,
        source_state_sha256=_HASH_A,
        status_summary=ResearchStatusSummary(
            total_statement_count=1,
            available_statement_count=1,
            stale_statement_count=0,
            restricted_statement_count=0,
            unknown_section_count=0,
        ),
        sections=(
            ResearchSection(
                section_id="account.summary",
                kind=ResearchSectionKind.SUMMARY,
                block_kind=DossierBlockKind.EXECUTIVE_SUMMARY,
                availability=ResearchAvailability.AVAILABLE,
                items=(item,),
            ),
        ),
        provenance_index=(
            ResearchProvenanceRef(
                statement_id=item.statement_id,
                claim_id=item.claim_id,
                statement_kind=item.statement_kind,
            ),
        ),
        coverage_summary=ResearchCoverageSummary(
            coverage_ref_ids=("coverage:fixture",),
            required_field_count=1,
            filled_field_count=1,
            terminal_gap_count=0,
            blocked_field_count=0,
            budget_exhausted_field_count=0,
        ),
    )


def test_contract_models_are_strict_and_frozen() -> None:
    subject = _account_subject()
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchSubjectRef(
            entity_id=subject.entity_id,
            entity_type=EntityType.ACCOUNT,
            canonical_entity_version=1,
            invented=True,
        )

    with pytest.raises(ValidationError):
        subject.canonical_entity_version = 2  # type: ignore[misc]


def test_contact_subject_requires_parent_and_account_subject_forbids_it() -> None:
    with pytest.raises(ValidationError, match="requires parent_account_id"):
        ResearchSubjectRef(
            entity_id=new_entity_id(),
            entity_type=EntityType.CONTACT,
            canonical_entity_version=1,
        )
    with pytest.raises(ValidationError, match="cannot carry parent_account_id"):
        ResearchSubjectRef(
            entity_id=new_entity_id(),
            entity_type=EntityType.ACCOUNT,
            canonical_entity_version=1,
            parent_account_id=new_entity_id(),
        )


def test_direct_and_derived_support_shapes_are_exclusive() -> None:
    direct = _direct_account_statement()
    support = ResearchSupportRef(
        claim_id=new_claim_id(),
        role=ResearchSupportRole.DIRECT_EVIDENCE,
        ordinal=0,
    )
    payload = direct.model_dump()
    payload["supports"] = [support.model_dump()]
    with pytest.raises(ValidationError, match="direct statement cannot"):
        ResearchStatement.model_validate(payload)

    payload = direct.model_dump()
    payload["statement_kind"] = ResearchStatementKind.DERIVED
    with pytest.raises(ValidationError, match="requires at least one support"):
        ResearchStatement.model_validate(payload)


def test_derived_supports_are_ordered_and_cannot_self_support() -> None:
    statement = _direct_account_statement()
    payload = statement.model_dump()
    payload["statement_kind"] = ResearchStatementKind.DERIVED
    payload["supports"] = [
        ResearchSupportRef(
            claim_id=new_claim_id(),
            role=ResearchSupportRole.ACCOUNT_SIGNAL,
            ordinal=1,
        ).model_dump()
    ]
    with pytest.raises(ValidationError, match="contiguous ordinals"):
        ResearchStatement.model_validate(payload)

    payload["supports"][0]["ordinal"] = 0
    payload["supports"][0]["claim_id"] = statement.claim_id
    with pytest.raises(ValidationError, match="cannot support itself"):
        ResearchStatement.model_validate(payload)


def test_hidden_or_redacted_statement_cannot_carry_value_or_evidence() -> None:
    statement = _direct_account_statement()
    payload = statement.model_dump()
    payload["state"] = ResearchItemState(
        availability=ResearchAvailability.REDACTED,
        verification=VerificationStatus.VERIFIED,
        freshness=FreshnessState.FRESH,
        display_decision=DisplayDecision.DENIED,
        outreach_decision=OutreachDecision.NOT_APPLICABLE,
        reason_codes=("subject_erased",),
    ).model_dump()
    with pytest.raises(ValidationError, match="hidden statement"):
        ResearchStatement.model_validate(payload)


def test_personalization_requires_strong_allowed_non_sensitive_contact_statement() -> None:
    safe = _safe_contact_statement()
    selected = ResearchPersonalizationItem(
        item_id="personalization:public-talk",
        statement=safe,
        selection_reason_code="public_professional_signal",
    )
    assert selected.statement.state.outreach_decision is OutreachDecision.ALLOWED

    denied_payload = safe.model_dump()
    denied_payload["state"]["outreach_decision"] = OutreachDecision.DENIED
    denied = ResearchStatement.model_validate(denied_payload)
    with pytest.raises(ValidationError, match="outreach_decision=allowed"):
        ResearchPersonalizationItem(
            item_id="personalization:denied",
            statement=denied,
            selection_reason_code="should_not_select",
        )

    sensitive_payload = safe.model_dump()
    sensitive_payload["use_class"] = UseClass.SENSITIVE
    with pytest.raises(ValidationError, match="sensitive personal data"):
        ResearchStatement.model_validate(sensitive_payload)


def test_product_scoped_statement_must_match_a_product_scoped_view() -> None:
    subject = _account_subject()
    statement = _direct_account_statement(subject, product_id="product-a")
    with pytest.raises(ValidationError, match="must match the view product_id"):
        _account_view(subject=subject, statement=statement, product_id="product-b")
    with pytest.raises(ValidationError, match="must match the view product_id"):
        _account_view(subject=subject, statement=statement, product_id=None)


def test_view_requires_exact_statement_subject_and_complete_provenance() -> None:
    account = _account_subject()
    other_account = _account_subject()
    wrong_statement = _direct_account_statement(other_account)
    with pytest.raises(ValidationError, match="exact subject"):
        _account_view(subject=account, statement=wrong_statement)

    valid = _account_view(subject=account)
    payload = valid.model_dump()
    payload["provenance_index"] = []
    with pytest.raises(ValidationError, match="cover every and only visible statement"):
        AccountResearchView.model_validate(payload)


def test_status_summary_is_derived_not_caller_invented() -> None:
    view = _account_view()
    payload = view.model_dump()
    payload["status_summary"]["available_statement_count"] = 0
    with pytest.raises(ValidationError, match="deterministic view counts"):
        AccountResearchView.model_validate(payload)


def test_account_and_contact_dtos_reject_the_wrong_subject_kind() -> None:
    account_view = _account_view()
    payload = account_view.model_dump()
    payload["view_kind"] = "contact"
    with pytest.raises(ValidationError, match="requires a contact subject"):
        ContactResearchView.model_validate(payload)


def test_contact_view_accepts_exact_parent_reference_and_governed_personalization() -> None:
    account = _account_subject()
    contact = _contact_subject(account)
    statement = _safe_contact_statement(contact)
    parent_ref = ResearchOwnedReference(
        item_id="identity:parent-account",
        subject=account,
        data_species=ResearchDataSpecies.IDENTITY,
        relation=ResearchReferenceRelation.PARENT_ACCOUNT,
        owner_ref="identity:account:v1",
    )
    view = ContactResearchView(
        view_id=new_research_view_id(),
        workspace_id="workspace-fixture",
        project_id="project-fixture",
        project_run_id=new_project_run_id(),
        subject=contact,
        composed_at=_NOW,
        source_state_sha256=_HASH_A,
        status_summary=ResearchStatusSummary(
            total_statement_count=1,
            available_statement_count=1,
            stale_statement_count=0,
            restricted_statement_count=0,
            unknown_section_count=0,
        ),
        sections=(
            ResearchSection(
                section_id="contact.identity",
                kind=ResearchSectionKind.IDENTITY,
                block_kind=None,
                availability=ResearchAvailability.AVAILABLE,
                items=(parent_ref,),
            ),
            ResearchSection(
                section_id="contact.personalization",
                kind=ResearchSectionKind.PERSONALIZATION,
                block_kind=DossierBlockKind.PERSONALIZATION,
                availability=ResearchAvailability.AVAILABLE,
                items=(
                    ResearchPersonalizationItem(
                        item_id="personalization:public-talk",
                        statement=statement,
                        selection_reason_code="public_professional_signal",
                    ),
                ),
            ),
        ),
        provenance_index=(
            ResearchProvenanceRef(
                statement_id=statement.statement_id,
                claim_id=statement.claim_id,
                statement_kind=statement.statement_kind,
            ),
        ),
        coverage_summary=ResearchCoverageSummary(
            required_field_count=1,
            filled_field_count=1,
            terminal_gap_count=0,
            blocked_field_count=0,
            budget_exhausted_field_count=0,
        ),
    )
    assert ContactResearchView.model_validate(view.model_dump()) == view

    payload = view.model_dump()
    payload["sections"][0]["items"][0]["subject"]["entity_id"] = new_entity_id()
    with pytest.raises(ValidationError, match="does not match the contact subject"):
        ContactResearchView.model_validate(payload)


def test_reference_only_outputs_forbid_body_fields() -> None:
    account = _account_subject()
    receipt = ResearchViewReceipt(
        snapshot_id=new_research_view_snapshot_id(),
        view_id=new_research_view_id(),
        workspace_id="workspace-fixture",
        project_id="project-fixture",
        project_run_id=new_project_run_id(),
        subject=account,
        source_state_sha256=_HASH_A,
        composition_sha256=_HASH_B,
        created_at=_NOW,
        fetch_ref="research-view:fixture",
    )
    view_ref = ResearchViewRef(
        view_id=receipt.view_id,
        snapshot_id=receipt.snapshot_id,
        workspace_id=receipt.workspace_id,
        project_id=receipt.project_id,
        subject_entity_id=account.entity_id,
        source_state_sha256=_HASH_A,
        fetch_ref="research-view:fixture",
    )
    report = ResearchViewChangeReportRef(
        report_id=new_research_view_change_report_id(),
        operation_id=new_operation_id(),
        old_snapshot_id=receipt.snapshot_id,
        new_snapshot_id=new_research_view_snapshot_id(),
        fetch_ref="research-view-change:fixture",
    )

    forbidden = {
        "value_json",
        "evidence_span",
        "source_url",
        "storage_key",
        "rendered_body",
        "markdown",
        "html",
        "rationale",
    }
    serialized = " ".join(model.model_dump_json() for model in (receipt, view_ref, report)).lower()
    assert forbidden.isdisjoint(serialized.split())

    payload = receipt.model_dump()
    payload["rendered_body"] = "not allowed"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchViewReceipt.model_validate(payload)

    payload = receipt.model_dump()
    payload["fetch_ref"] = "https://storage.invalid/permanent-object"
    with pytest.raises(ValidationError, match="must be opaque"):
        ResearchViewReceipt.model_validate(payload)


def test_evidence_descriptor_is_capability_only() -> None:
    claim_id = new_claim_id()
    with pytest.raises(ValidationError, match="requires action_id"):
        EvidenceActionDescriptor(
            kind=EvidenceActionKind.REQUEST_ARTIFACT_PREVIEW,
            claim_id=claim_id,
        )
    with pytest.raises(ValidationError, match="cannot carry an action_id"):
        EvidenceActionDescriptor(
            kind=EvidenceActionKind.REDACTED,
            claim_id=claim_id,
            action_id=UUID("00000000-0000-0000-0000-000000000202"),
        )
    assert "source_url" not in EvidenceActionDescriptor.model_fields
    assert "storage_key" not in EvidenceActionDescriptor.model_fields


def test_entailment_result_has_bounded_reasons_and_no_rationale_field() -> None:
    result = EntailmentJudgeResult(
        derived_claim_id=new_claim_id(),
        support_set_sha256=_HASH_A,
        verdict=EntailmentVerdictKind.SUPPORTED,
        confidence=0.91,
        reason_codes=(EntailmentReasonCode.ENTAILED,),
        requested_model="judge-model",
        answering_model="judge-model",
        prompt_version="entailment-v1",
        trace_ref="trace:fixture",
    )
    assert result.cost_cents == 0
    assert "rationale" not in EntailmentJudgeResult.model_fields

    payload = result.model_dump()
    payload["reason_codes"] = []
    with pytest.raises(ValidationError, match="at least one bounded reason"):
        EntailmentJudgeResult.model_validate(payload)


def test_research_view_protocols_are_runtime_checkable() -> None:
    for protocol in (
        ResearchViewReader,
        ResearchViewComposer,
        ResearchViewSnapshotReader,
        DerivationEntailmentJudge,
    ):
        assert not isinstance(object(), protocol)

    # The request/result types named in the protocol surface are public and strict.
    assert ResearchViewReadRequest.model_config["extra"] == "forbid"
    assert EntailmentJudgeRequest.model_config["extra"] == "forbid"
