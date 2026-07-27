"""C7.0 executable ownership map: the composer may aggregate but not author owner data."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from clue_core import (
    BLOCK_KIND_BY_SECTION,
    LEGACY_DOSSIER_ALIASES,
    SECTION_SPECIES_POLICY,
    DisplayDecision,
    DossierBlockKind,
    EntityType,
    FreshnessState,
    OutreachDecision,
    ResearchAvailability,
    ResearchConflictState,
    ResearchDataSpecies,
    ResearchItemState,
    ResearchOwnedReference,
    ResearchReferenceRelation,
    ResearchSection,
    ResearchSectionKind,
    ResearchStatement,
    ResearchStatementKind,
    ResearchSubjectRef,
    VerificationStatus,
    allowed_species,
    compatibility_block_kind,
    new_claim_id,
    new_entity_id,
    new_research_statement_id,
    species_is_allowed,
)

_NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _account_subject() -> ResearchSubjectRef:
    return ResearchSubjectRef(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        canonical_entity_version=1,
    )


def _statement(subject: ResearchSubjectRef) -> ResearchStatement:
    return ResearchStatement(
        statement_id=new_research_statement_id(),
        subject=subject,
        field_key="account.summary",
        value_json="Synthetic summary.",
        statement_kind=ResearchStatementKind.DIRECT,
        claim_id=new_claim_id(),
        state=ResearchItemState(
            availability=ResearchAvailability.AVAILABLE,
            verification=VerificationStatus.VERIFIED,
            freshness=FreshnessState.FRESH,
            conflict=ResearchConflictState.NONE,
            display_decision=DisplayDecision.ALLOWED,
            outreach_decision=OutreachDecision.NOT_APPLICABLE,
        ),
        confidence=0.9,
        collected_at=_NOW,
    )


def test_every_section_has_one_frozen_species_and_block_policy() -> None:
    assert set(SECTION_SPECIES_POLICY) == set(ResearchSectionKind)
    assert set(BLOCK_KIND_BY_SECTION) == set(ResearchSectionKind)
    assert all(allowed_species(kind) for kind in ResearchSectionKind)


def test_nine_block_compatibility_vocabulary_is_exact() -> None:
    assert {kind.value for kind in DossierBlockKind} == {
        "executive_summary",
        "company_profile",
        "fit_assessment",
        "signal",
        "committee_member",
        "personalization",
        "value_narrative",
        "feasibility",
        "coverage_gap",
    }
    assert (
        compatibility_block_kind(ResearchSectionKind.SUMMARY) is DossierBlockKind.EXECUTIVE_SUMMARY
    )
    assert compatibility_block_kind(ResearchSectionKind.IDENTITY) is None


def test_claim_sections_reject_owner_refs_and_owner_sections_reject_claims() -> None:
    subject = _account_subject()
    identity_ref = ResearchOwnedReference(
        item_id="identity:account",
        subject=subject,
        data_species=ResearchDataSpecies.IDENTITY,
        relation=ResearchReferenceRelation.SUBJECT,
        owner_ref="identity:account:v1",
    )
    with pytest.raises(ValidationError, match="not authoritative for section summary"):
        ResearchSection(
            section_id="account.summary",
            kind=ResearchSectionKind.SUMMARY,
            block_kind=DossierBlockKind.EXECUTIVE_SUMMARY,
            availability=ResearchAvailability.AVAILABLE,
            items=(identity_ref,),
        )
    with pytest.raises(ValidationError, match="not authoritative for section identity"):
        ResearchSection(
            section_id="account.identity",
            kind=ResearchSectionKind.IDENTITY,
            block_kind=None,
            availability=ResearchAvailability.AVAILABLE,
            items=(_statement(subject),),
        )


def test_score_references_require_evidence_and_carry_no_value_payload() -> None:
    subject = _account_subject()
    with pytest.raises(ValidationError, match="requires evidence_claim_ids"):
        ResearchOwnedReference(
            item_id="score:fit",
            subject=subject,
            data_species=ResearchDataSpecies.SCORE,
            relation=ResearchReferenceRelation.SUBJECT,
            owner_ref="score:fit:v1",
        )
    assert "value_json" not in ResearchOwnedReference.model_fields
    assert "payload" not in ResearchOwnedReference.model_fields


def test_section_block_kind_cannot_drift_from_compatibility_map() -> None:
    with pytest.raises(ValidationError, match="requires compatibility block"):
        ResearchSection(
            section_id="account.coverage",
            kind=ResearchSectionKind.COVERAGE_GAPS,
            block_kind=DossierBlockKind.SIGNAL,
            availability=ResearchAvailability.UNKNOWN,
            reason_codes=("not_researched",),
        )


def test_legacy_dossier_names_are_aliases_to_one_research_view_surface() -> None:
    assert dict(LEGACY_DOSSIER_ALIASES) == {
        "compose_dossier@1": "research_view.compose",
        "dossier.updated": "research_view.updated",
        "dossier.section.stale": "research_view.section_stale",
    }
    with pytest.raises(TypeError):
        LEGACY_DOSSIER_ALIASES["another"] = "second.implementation"  # type: ignore[index]


def test_source_species_helpers_are_closed_and_consistent() -> None:
    assert species_is_allowed(
        ResearchSectionKind.FIT,
        ResearchDataSpecies.SCORE,
    )
    assert not species_is_allowed(
        ResearchSectionKind.FIT,
        ResearchDataSpecies.CLAIM_DERIVATION,
    )
    assert allowed_species(ResearchSectionKind.ACTIVITY) == frozenset(
        {ResearchDataSpecies.ACTIVITY}
    )
