"""Claim provenance flavors at the model layer (M1.4 + C7.2, no DB).

Covers the ``Claim`` flavor coherence rules and the constructors: discovery-provenance requires a
discovery mode + a matching envelope; a field claim must not carry discovery-provenance; a contact
personal direct or derived claim requires identity_binding + use_class while a contact *discovery*
claim does not. C7.2 derived claims use support lineage rather than an external URL/span.
"""

from __future__ import annotations

import pytest

from clue_core import (
    Claim,
    ClaimFlavor,
    DiscoveryProvenance,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    account_claim,
    can_be_promoted,
    contact_claim,
    contact_field_claim,
    discovery_claim,
    field_claim,
    new_entity_id,
    new_run_id,
)

_ENTITY = new_entity_id()
_RUN = new_run_id()


def _discovery(**overrides: object) -> Claim:
    kwargs: dict[str, object] = {
        "entity_id": _ENTITY,
        "entity_type": EntityType.ACCOUNT,
        "field_key": "account.recent_funding",
        "value_json": {"amount_usd": 1},
        "source_tier": 2,
        "extraction_method": ExtractionMethod.SCRAPE,
        "confidence": 0.7,
        "run_id": _RUN,
        "research_mode": ResearchMode.ACCOUNT_DISCOVERY,
        "found_via": "exa_search",
        "matched_signal": "matches ICP: Series B SaaS",
        "discovery_confidence": 0.8,
        "source_url": "https://exa.example/result",
    }
    kwargs.update(overrides)
    return discovery_claim(**kwargs)  # type: ignore[arg-type]


def test_spec_named_constructors_are_the_field_claim_builders() -> None:
    """field_claim / contact_field_claim are the field-claim constructors (DRY aliases)."""
    assert field_claim is account_claim
    assert contact_field_claim is contact_claim


def test_discovery_claim_carries_its_envelope() -> None:
    claim = _discovery()
    assert claim.claim_flavor is ClaimFlavor.DISCOVERY
    assert claim.discovery_provenance is not None
    assert claim.discovery_provenance.found_via == "exa_search"
    assert claim.discovery_provenance.matched_signal == "matches ICP: Series B SaaS"
    assert claim.discovery_provenance.discovery_confidence == 0.8


def test_discovery_claim_requires_a_discovery_mode() -> None:
    with pytest.raises(ValueError):
        _discovery(research_mode=ResearchMode.ACCOUNT_PROFILING)


def test_field_claim_must_not_carry_discovery_provenance() -> None:
    with pytest.raises(ValueError, match="must not carry discovery_provenance"):
        Claim(
            entity_id=_ENTITY,
            entity_type=EntityType.ACCOUNT,
            field_key="account.recent_funding",
            value_json={"amount_usd": 1},
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            source_url="https://x.example",
            confidence=0.5,
            run_id=_RUN,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            claim_flavor=ClaimFlavor.FIELD_CLAIM,
            discovery_provenance=DiscoveryProvenance(
                entity_id=_ENTITY,
                found_via="x",
                matched_signal="y",
                discovery_confidence=0.5,
                run_id=_RUN,
                research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            ),
        )


def test_discovery_provenance_must_match_the_claim() -> None:
    other_entity = new_entity_id()
    with pytest.raises(ValueError, match="must match the claim"):
        Claim(
            entity_id=_ENTITY,
            entity_type=EntityType.ACCOUNT,
            field_key="account.recent_funding",
            value_json={"amount_usd": 1},
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            source_url="https://x.example",
            confidence=0.5,
            run_id=_RUN,
            research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            claim_flavor=ClaimFlavor.DISCOVERY,
            discovery_provenance=DiscoveryProvenance(
                entity_id=other_entity,  # mismatched
                found_via="x",
                matched_signal="y",
                discovery_confidence=0.5,
                run_id=_RUN,
                research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            ),
        )


def test_contact_field_claim_requires_governance() -> None:
    """A contact *field* claim needs binding + use_class; a contact *discovery* claim does not."""
    # contact field claim with both present is valid
    ok = contact_field_claim(
        entity_id=_ENTITY,
        field_key="contact.facet.recent_post",
        value_json="spoke at KubeCon",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        source_url="https://li.example/post",
        confidence=0.8,
        run_id=_RUN,
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    assert ok.identity_binding is IdentityBinding.STRONG

    # a contact personal (contact.facet.*) field claim missing governance is rejected
    with pytest.raises(ValueError, match="require both identity_binding"):
        Claim(
            entity_id=_ENTITY,
            entity_type=EntityType.CONTACT,
            field_key="contact.facet.recent_post",
            value_json="x",
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            source_url="https://li.example/post",
            confidence=0.8,
            run_id=_RUN,
            research_mode=ResearchMode.CONTACT_PROFILING,
        )

    # a contact discovery claim (mode M3) needs no binding/use_class
    contact_discovery = _discovery(
        entity_type=EntityType.CONTACT,
        field_key="contact.role_on_committee",
        value_json="champion",
        research_mode=ResearchMode.COMMITTEE_DISCOVERY,
    )
    assert contact_discovery.identity_binding is None
    assert contact_discovery.claim_flavor is ClaimFlavor.DISCOVERY


def test_non_personal_contact_fact_claim_needs_no_governance() -> None:
    """A plain contact.* fact (role_on_committee) is not a personal hook — needs no governance."""
    fact = Claim(
        entity_id=_ENTITY,
        entity_type=EntityType.CONTACT,
        field_key="contact.role_on_committee",
        value_json="champion",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        source_url="https://li.example/p",
        confidence=0.8,
        run_id=_RUN,
        research_mode=ResearchMode.CONTACT_PROFILING,
    )
    assert fact.identity_binding is None
    assert fact.use_class is None


def test_derived_claim_uses_support_lineage_not_external_evidence() -> None:
    derived = Claim(
        entity_id=_ENTITY,
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json="funding creates a near-term transformation window",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.7,
        run_id=_RUN,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        claim_flavor=ClaimFlavor.DERIVED,
    )
    assert derived.source_url is None
    assert derived.evidence_span is None
    assert can_be_promoted(derived)


def test_derived_contact_facet_is_born_governed() -> None:
    with pytest.raises(ValueError, match="require both identity_binding"):
        Claim(
            entity_id=_ENTITY,
            entity_type=EntityType.CONTACT,
            field_key="contact.facet.recent_post",
            value_json="derived personal interpretation",
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            confidence=0.7,
            run_id=_RUN,
            research_mode=ResearchMode.CONTACT_PROFILING,
            claim_flavor=ClaimFlavor.DERIVED,
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"source_url": "https://invented.invalid"}, "support edges"),
        ({"evidence_span": "copied support"}, "support edges"),
        (
            {
                "source_tier": 2,
                "extraction_method": ExtractionMethod.SCRAPE,
            },
            "tier-4/model-authored",
        ),
        (
            {
                "discovery_provenance": DiscoveryProvenance(
                    entity_id=_ENTITY,
                    found_via="x",
                    matched_signal="y",
                    discovery_confidence=0.5,
                    run_id=_RUN,
                    research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                )
            },
            "non-discovery",
        ),
    ],
)
def test_derived_claim_rejects_other_provenance(override: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "entity_id": _ENTITY,
        "entity_type": EntityType.ACCOUNT,
        "field_key": "account.recent_funding",
        "value_json": "derived",
        "source_tier": 4,
        "extraction_method": ExtractionMethod.LLM_SYNTHESIS,
        "confidence": 0.7,
        "run_id": _RUN,
        "research_mode": ResearchMode.ACCOUNT_PROFILING,
        "claim_flavor": ClaimFlavor.DERIVED,
    }
    values.update(override)
    with pytest.raises(ValueError, match=message):
        Claim.model_validate(values)
