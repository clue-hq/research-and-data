"""Pure adversarial tests for the no-numeric-scoring discovery selection policy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clue_core import (
    DiscoveryFieldResolution,
    DiscoveryFieldResolutionState,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    SealedDiscoveryAccounts,
    discovery_claim,
    new_claim_id,
    new_discovery_batch_id,
    new_entity_id,
    new_run_id,
)
from clue_research.discovery_scoring.tiering import (
    DiscoverySelectionDisposition,
    DiscoverySelectionPolicy,
)
from clue_research.discovery_scoring.tiering.selection import classify_discovery_criteria

_CRITERIA = ("Independent practice", "Multiple providers")
_REQUIRED_FIELD = "discovery.industry"


def _policy() -> DiscoverySelectionPolicy:
    return DiscoverySelectionPolicy.from_slot(
        {
            "scoring_mode": "disabled",
            "selection_mode": "discovery_criteria",
            "must_have_criteria": list(_CRITERIA),
            "approved_tier": "high",
        }
    )


def _provenance(account_id, states: tuple[str, str]):
    return discovery_claim(
        entity_id=account_id,
        entity_type=EntityType.ACCOUNT,
        field_key="core.discovery_provenance",
        value_json={
            "matched_channel": "exa_websets",
            "matched_signal": "criterion evaluation",
            "discovery_confidence": 0.9,
            "evidence": {
                "evaluations": [
                    {
                        "criterion": criterion,
                        "satisfied": state,
                        "reasoning": f"reason for {criterion}",
                        "references": [
                            {
                                "url": f"https://evidence.example/{index}",
                                "title": "Evidence",
                                "snippet": "supporting snippet",
                            }
                        ],
                    }
                    for index, (criterion, state) in enumerate(zip(_CRITERIA, states, strict=True))
                ]
            },
        },
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_DISCOVERY,
        found_via="exa_websets",
        matched_signal="criterion evaluation",
        discovery_confidence=0.9,
        source_url="https://exa.example/item",
    )


def test_policy_requires_explicit_coherent_bypass_controls() -> None:
    with pytest.raises(ValueError, match="must be set together"):
        DiscoverySelectionPolicy.from_slot(
            {
                "scoring_mode": "disabled",
                "must_have_criteria": ["Independent practice"],
            }
        )
    with pytest.raises(ValueError, match="at least one"):
        DiscoverySelectionPolicy.from_slot(
            {
                "scoring_mode": "disabled",
                "selection_mode": "discovery_criteria",
                "must_have_criteria": [],
            }
        )


def test_strict_criteria_and_required_field_classification() -> None:
    batch_id = new_discovery_batch_id()
    selected_id = new_entity_id()
    unclear_id = new_entity_id()
    excluded_id = new_entity_id()
    field_hold_id = new_entity_id()
    claims = {
        claim.id: claim
        for claim in (
            _provenance(selected_id, ("yes", "yes")),
            _provenance(unclear_id, ("yes", "unclear")),
            _provenance(excluded_id, ("yes", "no")),
            _provenance(field_hold_id, ("yes", "yes")),
        )
    }
    now = datetime.now(UTC)
    resolutions = []
    for account_id in (selected_id, unclear_id, excluded_id):
        claim_id = next(claim.id for claim in claims.values() if claim.entity_id == account_id)
        resolutions.append(
            DiscoveryFieldResolution(
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key=_REQUIRED_FIELD,
                state=DiscoveryFieldResolutionState.RESOLVED,
                claim_ids=(claim_id,),
                winning_claim_id=claim_id,
                updated_at=now,
            )
        )
    resolutions.append(
        DiscoveryFieldResolution(
            batch_id=batch_id,
            account_entity_id=field_hold_id,
            logical_field_key=_REQUIRED_FIELD,
            state=DiscoveryFieldResolutionState.CONFIRMED_MISSING,
            reason_code="provider_returned_null",
            updated_at=now,
        )
    )
    sealed = SealedDiscoveryAccounts(
        discovery_batch_id=batch_id,
        seal_sha256="a" * 64,
        account_manifest_ref="fixture/" + "b" * 64,
        account_ids=(selected_id, unclear_id, excluded_id, field_hold_id),
        claim_manifest_ref="fixture/" + "c" * 64,
        claim_ids=tuple(claims),
        required_criteria=_CRITERIA,
        required_account_fields=(_REQUIRED_FIELD,),
        field_resolutions=tuple(resolutions),
    )

    result = classify_discovery_criteria(sealed=sealed, claims=claims, policy=_policy())
    by_id = {row.account_id: row for row in result.accounts}

    assert by_id[selected_id].disposition is DiscoverySelectionDisposition.SELECTED
    assert by_id[unclear_id].disposition is DiscoverySelectionDisposition.HOLD
    assert by_id[excluded_id].disposition is DiscoverySelectionDisposition.EXCLUDED
    assert by_id[field_hold_id].disposition is DiscoverySelectionDisposition.HOLD
    assert result.distribution == {"selected": 1, "hold": 2, "excluded": 1}
    assert by_id[unclear_id].criteria[1].observations[0].reasoning == (
        "reason for Multiple providers"
    )
    assert by_id[selected_id].criteria[0].observations[0].references[0].url.startswith("https://")


def test_missing_required_criterion_holds_instead_of_guessing() -> None:
    account_id = new_entity_id()
    claim = _provenance(account_id, ("yes", "yes"))
    value = dict(claim.value_json)
    evidence = dict(value["evidence"])
    evidence["evaluations"] = evidence["evaluations"][:1]
    value["evidence"] = evidence
    claim = claim.model_copy(update={"value_json": value, "id": new_claim_id()})
    batch_id = new_discovery_batch_id()
    resolution = DiscoveryFieldResolution(
        batch_id=batch_id,
        account_entity_id=account_id,
        logical_field_key=_REQUIRED_FIELD,
        state=DiscoveryFieldResolutionState.RESOLVED,
        claim_ids=(claim.id,),
        winning_claim_id=claim.id,
        updated_at=datetime.now(UTC),
    )
    sealed = SealedDiscoveryAccounts(
        discovery_batch_id=batch_id,
        seal_sha256="d" * 64,
        account_manifest_ref="fixture/" + "e" * 64,
        account_ids=(account_id,),
        claim_ids=(claim.id,),
        required_criteria=_CRITERIA,
        required_account_fields=(_REQUIRED_FIELD,),
        field_resolutions=(resolution,),
    )

    result = classify_discovery_criteria(
        sealed=sealed,
        claims={claim.id: claim},
        policy=_policy(),
    )
    assert result.accounts[0].disposition is DiscoverySelectionDisposition.HOLD
    assert result.accounts[0].criteria[1].decision.value == "missing"


def test_policy_cannot_omit_a_criterion_from_the_sealed_plan() -> None:
    account_id = new_entity_id()
    claim = _provenance(account_id, ("yes", "yes"))
    sealed = SealedDiscoveryAccounts(
        discovery_batch_id=new_discovery_batch_id(),
        seal_sha256="f" * 64,
        account_manifest_ref="fixture/" + "9" * 64,
        account_ids=(account_id,),
        claim_ids=(claim.id,),
        required_criteria=_CRITERIA,
    )
    incomplete_policy = DiscoverySelectionPolicy.from_slot(
        {
            "scoring_mode": "disabled",
            "selection_mode": "discovery_criteria",
            "must_have_criteria": [_CRITERIA[0]],
        }
    )

    with pytest.raises(ValueError, match="immutable discovery plan"):
        classify_discovery_criteria(
            sealed=sealed,
            claims={claim.id: claim},
            policy=incomplete_policy,
        )
