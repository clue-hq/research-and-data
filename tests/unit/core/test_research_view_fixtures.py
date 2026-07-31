"""C7.0 executable frontend/negative fixture map."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from clue_core import (
    AccountResearchView,
    DisplayDecision,
    DossierBlockKind,
    EntityType,
    FreshnessState,
    IdentityBinding,
    OutreachDecision,
    ResearchAvailability,
    ResearchConflictState,
    ResearchCoverageSummary,
    ResearchDataSpecies,
    ResearchItemState,
    ResearchOwnedReference,
    ResearchProvenanceRef,
    ResearchReferenceRelation,
    ResearchSection,
    ResearchSectionKind,
    ResearchStatement,
    ResearchStatementKind,
    ResearchStatusSummary,
    ResearchSubjectRef,
    UseClass,
    VerificationStatus,
    compatibility_block_kind,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
    new_research_statement_id,
    new_research_view_id,
    species_is_allowed,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "research_views"
_NOW = datetime(2026, 7, 27, tzinfo=UTC)
_HASH = "a" * 64


class _FixtureSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ResearchSectionKind
    owner_species: ResearchDataSpecies
    block_kind: DossierBlockKind | None
    required_elements: tuple[str, ...]


class _FrontendFixtureManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"]
    fixture_id: str
    sanitized: Literal[True]
    view_kind: Literal["account", "contact"]
    subject_fixture_id: str
    parent_account_fixture_id: str | None = None
    sections: tuple[_FixtureSection, ...]
    forbidden_authoritative_fields: tuple[str, ...]


class _AdversarialCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    category: str
    first_guard_stage: str
    contract_case: str | None
    later_guard_stage: str
    expected_reason_code: str
    expected_outcome: Literal["rejected", "restricted", "unavailable"]


class _AdversarialManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"]
    fixture_id: str
    sanitized: Literal[True]
    cases: tuple[_AdversarialCase, ...]


def _load_frontend(name: str) -> _FrontendFixtureManifest:
    return _FrontendFixtureManifest.model_validate_json((FIXTURES / name).read_text())


def _load_adversarial() -> _AdversarialManifest:
    return _AdversarialManifest.model_validate_json(
        (FIXTURES / "adversarial_cases.json").read_text()
    )


def _account_subject() -> ResearchSubjectRef:
    return ResearchSubjectRef(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        canonical_entity_version=1,
    )


def _contact_subject(account: ResearchSubjectRef) -> ResearchSubjectRef:
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


def _account_statement(
    subject: ResearchSubjectRef,
    *,
    product_id: str | None = None,
) -> ResearchStatement:
    return ResearchStatement(
        statement_id=new_research_statement_id(),
        subject=subject,
        field_key="account.summary",
        value_json="Synthetic summary.",
        statement_kind=ResearchStatementKind.DIRECT,
        claim_id=new_claim_id(),
        product_id=product_id,
        state=_available_state(outreach=OutreachDecision.NOT_APPLICABLE),
        confidence=0.9,
        collected_at=_NOW,
    )


def _build_account_view(
    subject: ResearchSubjectRef,
    section: ResearchSection,
    *,
    statement: ResearchStatement | None = None,
    product_id: str | None = None,
) -> AccountResearchView:
    provenance = ()
    statement_count = 0
    if statement is not None:
        statement_count = 1
        provenance = (
            ResearchProvenanceRef(
                statement_id=statement.statement_id,
                claim_id=statement.claim_id,
                statement_kind=statement.statement_kind,
            ),
        )
    return AccountResearchView(
        view_id=new_research_view_id(),
        workspace_id="workspace-fixture",
        project_id="project-fixture",
        project_run_id=new_project_run_id(),
        subject=subject,
        product_id=product_id,
        composed_at=_NOW,
        source_state_sha256=_HASH,
        status_summary=ResearchStatusSummary(
            total_statement_count=statement_count,
            available_statement_count=statement_count,
            stale_statement_count=0,
            restricted_statement_count=0,
            unknown_section_count=0,
        ),
        sections=(section,),
        provenance_index=provenance,
        coverage_summary=ResearchCoverageSummary(
            required_field_count=0,
            filled_field_count=0,
            terminal_gap_count=0,
            blocked_field_count=0,
            budget_exhausted_field_count=0,
        ),
    )


def _wrong_statement_subject() -> None:
    subject = _account_subject()
    wrong_statement = _account_statement(_account_subject())
    section = ResearchSection(
        section_id="account.summary",
        kind=ResearchSectionKind.SUMMARY,
        block_kind=DossierBlockKind.EXECUTIVE_SUMMARY,
        availability=ResearchAvailability.AVAILABLE,
        items=(wrong_statement,),
    )
    _build_account_view(subject, section, statement=wrong_statement)


def _sensitive_outreach() -> None:
    account = _account_subject()
    ResearchStatement(
        statement_id=new_research_statement_id(),
        subject=_contact_subject(account),
        field_key="contact.facet.medical_history",
        value_json="Synthetic sensitive value.",
        statement_kind=ResearchStatementKind.DIRECT,
        claim_id=new_claim_id(),
        state=_available_state(outreach=OutreachDecision.ALLOWED),
        confidence=0.9,
        collected_at=_NOW,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.SENSITIVE,
    )


def _wrong_subject_reference() -> None:
    subject = _account_subject()
    activity_ref = ResearchOwnedReference(
        item_id="activity:wrong-account",
        subject=_account_subject(),
        data_species=ResearchDataSpecies.ACTIVITY,
        relation=ResearchReferenceRelation.SUBJECT,
        owner_ref="activity:fixture",
    )
    section = ResearchSection(
        section_id="account.activity",
        kind=ResearchSectionKind.ACTIVITY,
        block_kind=None,
        availability=ResearchAvailability.AVAILABLE,
        items=(activity_ref,),
    )
    _build_account_view(subject, section)


def _product_mismatch() -> None:
    subject = _account_subject()
    statement = _account_statement(subject, product_id="product-a")
    section = ResearchSection(
        section_id="account.summary",
        kind=ResearchSectionKind.SUMMARY,
        block_kind=DossierBlockKind.EXECUTIVE_SUMMARY,
        availability=ResearchAvailability.AVAILABLE,
        items=(statement,),
    )
    _build_account_view(
        subject,
        section,
        statement=statement,
        product_id="product-b",
    )


_CONTRACT_CASES = {
    "wrong_statement_subject": _wrong_statement_subject,
    "sensitive_outreach": _sensitive_outreach,
    "wrong_subject_reference": _wrong_subject_reference,
    "product_mismatch": _product_mismatch,
}


def test_account_fixture_covers_the_current_frontend_species() -> None:
    fixture = _load_frontend("account_view_manifest.json")
    assert fixture.view_kind == "account"
    assert {section.kind for section in fixture.sections} == {
        ResearchSectionKind.IDENTITY,
        ResearchSectionKind.RESEARCH_STATUS,
        ResearchSectionKind.SUMMARY,
        ResearchSectionKind.ABOUT,
        ResearchSectionKind.FIT,
        ResearchSectionKind.INSIGHTS,
        ResearchSectionKind.COMMITTEE,
        ResearchSectionKind.ACTIVITY,
        ResearchSectionKind.COVERAGE_GAPS,
    }
    fit = next(section for section in fixture.sections if section.kind is ResearchSectionKind.FIT)
    assert {
        "positive_criterion_ref",
        "negative_criterion_ref",
        "unknown_criterion_ref",
    } <= set(fit.required_elements)


def test_contact_fixture_covers_research_and_governed_personalization() -> None:
    fixture = _load_frontend("contact_view_manifest.json")
    assert fixture.view_kind == "contact"
    assert fixture.parent_account_fixture_id
    assert {
        ResearchSectionKind.IDENTITY,
        ResearchSectionKind.RESEARCH_STATUS,
        ResearchSectionKind.COMMITTEE,
        ResearchSectionKind.SUMMARY,
        ResearchSectionKind.PROFESSIONAL_SIGNALS,
        ResearchSectionKind.EVIDENCE,
        ResearchSectionKind.QUOTES,
        ResearchSectionKind.BACKGROUND,
        ResearchSectionKind.CAREER,
        ResearchSectionKind.EDUCATION,
        ResearchSectionKind.PUBLICATIONS,
        ResearchSectionKind.AWARDS,
        ResearchSectionKind.PERSONALIZATION,
        ResearchSectionKind.COVERAGE_GAPS,
    } == {section.kind for section in fixture.sections}
    personalization = next(
        section
        for section in fixture.sections
        if section.kind is ResearchSectionKind.PERSONALIZATION
    )
    assert {
        "strong_identity_binding",
        "allowed_outreach_decision",
        "non_sensitive_use_class",
        "selection_reason_code",
    } <= set(personalization.required_elements)


@pytest.mark.parametrize(
    "fixture_name",
    ["account_view_manifest.json", "contact_view_manifest.json"],
)
def test_frontend_fixture_sections_match_the_executable_ownership_maps(
    fixture_name: str,
) -> None:
    fixture = _load_frontend(fixture_name)
    for section in fixture.sections:
        assert species_is_allowed(section.kind, section.owner_species)
        assert section.block_kind is compatibility_block_kind(section.kind)
        assert section.required_elements


def test_fixture_manifests_are_sanitized_and_body_free() -> None:
    for path in FIXTURES.glob("*.json"):
        text = path.read_text().lower()
        data = json.loads(text)
        assert data["sanitized"] is True
        assert "http://" not in text
        assert "https://" not in text
        assert "@" not in text
        assert "rendered_markdown" not in {
            key for key in data if key != "forbidden_authoritative_fields"
        }


def test_adversarial_fixture_map_is_complete_and_stage_owned() -> None:
    fixture = _load_adversarial()
    cases = {case.case_id: case for case in fixture.cases}
    assert set(cases) == {
        "wrong_person_biography",
        "inconsistent_pronoun_or_identity_signal",
        "sensitive_medical_personalization",
        "wrong_account_activity",
        "cross_product_bleed",
    }
    assert cases["inconsistent_pronoun_or_identity_signal"].first_guard_stage == "c7.3_target_lock"
    assert cases["inconsistent_pronoun_or_identity_signal"].contract_case is None
    assert all(case.expected_reason_code for case in cases.values())


@pytest.mark.parametrize("contract_case", sorted(_CONTRACT_CASES))
def test_c70_adversarial_contract_cases_fail_closed(contract_case: str) -> None:
    mapped = {
        case.contract_case
        for case in _load_adversarial().cases
        if case.first_guard_stage == "c7.0_contract"
    }
    assert set(_CONTRACT_CASES) == mapped
    with pytest.raises(ValidationError):
        _CONTRACT_CASES[contract_case]()
