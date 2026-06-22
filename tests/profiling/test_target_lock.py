"""M8.1 target-lock validator (pure, no DB) — staged-flow §5/§8.

The mode-M2 anti-hallucination contract: a drift-prone (tier ≥ 3) claim must bind to the *resolved*
entity, and the bare canonical name never disambiguates two same-name companies. Covers the M8.1 AC
"a tier-4 claim whose evidence_span does not bind to the resolved entity is rejected" and "no claim
about company B is written to company A".
"""

from __future__ import annotations

from clue_research.core import (
    AccountEntity,
    ExtractionMethod,
    ResearchMode,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.profiling import (
    binds_to_entity,
    build_target_lock,
    is_lockable,
    requires_binding_check,
)


def _account(
    *,
    name: str = "Acme Robotics",
    domain: str | None = "acme-robotics.com",
    hq_geo: dict[str, object] | None = None,
    registry_ids: dict[str, str] | None = None,
    aliases: tuple[str, ...] = (),
) -> AccountEntity:
    return AccountEntity(
        id=new_entity_id(),
        canonical_name=name,
        primary_domain=domain,
        hq_geo=hq_geo,
        registry_ids=registry_ids or {},
        aliases=aliases,
    )


def _claim(tier: int, *, span: str | None, url: str = "https://example.com/x"):
    method = ExtractionMethod.LLM_SYNTHESIS if tier == 4 else ExtractionMethod.SCRAPE
    return account_claim(
        entity_id=new_entity_id(),
        field_key="account.operational_pain",
        value_json={"summary": "x"},
        source_tier=tier,
        extraction_method=method,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url=url,
        evidence_span=span,
    )


# --- build_target_lock ------------------------------------------------------


def test_build_target_lock_folds_domain_and_names_entity() -> None:
    lock = build_target_lock(_account(domain="https://www.Acme-Robotics.com/path"))
    assert lock.canonical_domain == "acme-robotics.com"  # registrable-domain folded
    assert lock.identifiers["canonical_name"] == "Acme Robotics"
    assert "Acme Robotics" in lock.no_drift_instruction
    assert "acme-robotics.com" in lock.no_drift_instruction


# --- is_lockable ------------------------------------------------------------


def test_lockable_with_domain() -> None:
    assert is_lockable(build_target_lock(_account(domain="acme.com")))


def test_lockable_with_registry_id_no_domain() -> None:
    lock = build_target_lock(_account(domain=None, registry_ids={"DUNS": "123456789"}))
    assert is_lockable(lock)


def test_lockable_with_name_plus_geo_no_domain() -> None:
    lock = build_target_lock(_account(domain=None, hq_geo={"city": "Boston"}))
    assert is_lockable(lock)


def test_not_lockable_name_only() -> None:
    # Name-only entity cannot be disambiguated from a same-name stranger → not lockable.
    assert not is_lockable(build_target_lock(_account(domain=None)))


# --- binds_to_entity --------------------------------------------------------


def test_deterministic_tiers_always_bind() -> None:
    lock = build_target_lock(_account())
    for tier in (1, 2):
        assert not requires_binding_check(_claim(tier, span=None))
        assert binds_to_entity(_claim(tier, span="anything"), lock)


def test_tier3_binds_when_evidence_names_the_domain() -> None:
    lock = build_target_lock(_account(domain="acme-robotics.com"))
    claim = _claim(3, span="Acme Robotics raised $50M; see acme-robotics.com/news.")
    assert binds_to_entity(claim, lock)


def test_tier3_same_name_company_does_not_bind() -> None:
    # Company A: acme-robotics.com / Boston. A tier-3 claim that is actually about a *different*
    # same-name company (acme-corp.io / San Francisco) must NOT bind to A (the same-name trap).
    lock = build_target_lock(
        _account(domain="acme-robotics.com", hq_geo={"city": "Boston", "region": "Massachusetts"})
    )
    other = _claim(
        3,
        span="Acme Robotics in San Francisco shipped a new arm (acme-corp.io).",
        url="https://acme-corp.io/x",
    )
    assert not binds_to_entity(other, lock)


def test_tier3_binds_on_name_plus_geo() -> None:
    lock = build_target_lock(
        _account(domain=None, hq_geo={"city": "Boston", "region": "Massachusetts"})
    )
    claim = _claim(3, span="Acme Robotics, headquartered in Boston, is hiring.")
    assert binds_to_entity(claim, lock)


def test_tier3_name_alone_does_not_bind() -> None:
    # Name present, but no domain/registry-id/geo disambiguator in the evidence → not bound.
    lock = build_target_lock(_account(domain="acme-robotics.com", hq_geo={"city": "Boston"}))
    claim = _claim(
        3, span="Acme Robotics announced a partnership.", url="https://blog.example.org/p"
    )
    assert not binds_to_entity(claim, lock)


def test_tier3_binds_on_registry_id() -> None:
    lock = build_target_lock(_account(domain=None, registry_ids={"LEI": "ABC123XYZ"}))
    claim = _claim(3, span="Filing LEI ABC123XYZ shows the entity raised capital.")
    assert binds_to_entity(claim, lock)


def test_tier4_without_span_never_binds() -> None:
    lock = build_target_lock(_account())
    assert not binds_to_entity(_claim(4, span=None), lock)


# --- boundary matching (regression: substring false-binds, audit findings) ------------------


def test_domain_does_not_bind_to_longer_suffix_tld() -> None:
    # acme.co (locked) must NOT bind to evidence about the distinct company acme.co.uk.
    lock = build_target_lock(_account(domain="acme.co"))
    other = _claim(
        3, span="Acme makes coats; see acme.co.uk for the UK firm.", url="https://acme.co.uk/x"
    )
    assert not binds_to_entity(other, lock)


def test_domain_does_not_bind_to_left_prefix_host() -> None:
    # acme.com (locked) must NOT bind to the unrelated company notacme.com.
    lock = build_target_lock(_account(domain="acme.com"))
    other = _claim(
        3, span="notacme.com is a different company entirely.", url="https://notacme.com/x"
    )
    assert not binds_to_entity(other, lock)


def test_registry_id_does_not_bind_to_longer_id() -> None:
    lock = build_target_lock(_account(domain=None, registry_ids={"LEI": "ABC123"}))
    other = _claim(3, span="Filing LEI ABC123456789 belongs to a different entity.")
    assert not binds_to_entity(other, lock)


def test_name_prefix_does_not_bind_to_longer_org_name() -> None:
    # "Acme" (locked) must NOT bind to evidence about "Acme Robotics", even with the same geo.
    lock = build_target_lock(_account(name="Acme", domain=None, hq_geo={"city": "Boston"}))
    other = _claim(
        3, span="Acme Robotics, headquartered in Boston, is hiring.", url="https://x.org/p"
    )
    assert not binds_to_entity(other, lock)


def test_short_name_binds_when_it_is_the_complete_org_reference() -> None:
    # "Acme" as the complete reference (followed by punctuation / lowercase) + geo → binds.
    lock = build_target_lock(_account(name="Acme", domain=None, hq_geo={"city": "Boston"}))
    claim = _claim(3, span="Acme, based in Boston, raised a round.", url="https://x.org/p")
    assert binds_to_entity(claim, lock)


def test_geo_token_does_not_bind_to_superstring_placename() -> None:
    # geo "York" must NOT match "Yorktown" (a different place) — token boundary, not substring.
    lock = build_target_lock(_account(name="Acme", domain=None, hq_geo={"city": "York"}))
    other = _claim(3, span="Acme operates out of Yorktown these days.", url="https://x.org/p")
    assert not binds_to_entity(other, lock)
