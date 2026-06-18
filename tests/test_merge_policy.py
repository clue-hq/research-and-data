"""M1.2 (ENG-110) — the pure deterministic merge policy (`merge_claims`), no DB required.

These exercise the merge *algorithm* directly over in-memory ``Claim`` objects: tier ordering,
every tie-break level, freshness gating + ``freshness_state``, the D7 freshness-mode flip, conflict
detection, and the tier-4 / weak-binding / rejected / superseded exclusions. The DB seam
(`current_value` / `current_values` / `provenance_index`) is covered separately in
``tests/claimstore/test_merge.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clue_research.claimstore import FreshnessMode, MergePolicy, merge_claims
from clue_research.core import (
    Claim,
    ClaimId,
    EntityType,
    ExtractionMethod,
    FreshnessState,
    IdentityBinding,
    ResearchMode,
    UseClass,
    VerificationStatus,
    discovery_claim,
    new_claim_id,
    new_entity_id,
    new_run_id,
)

_ENTITY = new_entity_id()
_RUN = new_run_id()
_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
_TTL = timedelta(days=90)


def _claim(
    tier: int,
    *,
    value: object = None,
    conf: float = 0.8,
    corr: int = 0,
    collected: datetime | None = None,
    observed: datetime | None = None,
    status: VerificationStatus = VerificationStatus.UNVERIFIED,
    superseded: ClaimId | None = None,
    entity_type: EntityType = EntityType.ACCOUNT,
    binding: IdentityBinding | None = None,
    span: str | None = None,
    field: str = "account.recent_funding",
    cid: ClaimId | None = None,
) -> Claim:
    method = (
        ExtractionMethod.LLM_SYNTHESIS
        if tier == 4
        else (ExtractionMethod.API if tier == 1 else ExtractionMethod.SCRAPE)
    )
    use_class = None
    if entity_type is EntityType.CONTACT:
        binding = binding or IdentityBinding.STRONG
        use_class = UseClass.PROFESSIONAL_PUBLIC
    kwargs: dict[str, object] = {
        "id": cid or new_claim_id(),
        "entity_id": _ENTITY,
        "entity_type": entity_type,
        "field_key": field,
        "value_json": {"amount_usd": 1} if value is None else value,
        "source_url": "https://src.example",
        "source_tier": tier,
        "extraction_method": method,
        "evidence_span": span,
        "confidence": conf,
        "corroborations": corr,
        "collected_at": collected or _NOW,
        "observed_at": observed,
        "run_id": _RUN,
        "research_mode": ResearchMode.ACCOUNT_PROFILING,
        "verification_status": status,
        "superseded_by": superseded,
        "identity_binding": binding,
        "use_class": use_class,
    }
    return Claim(**kwargs)  # type: ignore[arg-type]


def _merge(claims: list[Claim], *, policy: MergePolicy | None = None, ttl: timedelta | None = _TTL):
    return merge_claims(claims, ttl, policy or MergePolicy(), _NOW)


def test_lowest_tier_wins_over_higher_tiers() -> None:
    """A fresh tier-1 fact beats a fresh tier-3 and a (here unverified) tier-4 claim."""
    result = _merge(
        [_claim(3, value={"amount_usd": 30}), _claim(4), _claim(1, value={"amount_usd": 10})]
    )
    assert result is not None
    assert result.value_json == {"amount_usd": 10}
    assert result.provenance.source_tier == 1
    assert result.freshness_state is FreshnessState.FRESH


def test_tiebreak_corroborations_then_confidence_then_recency() -> None:
    """Equal tier resolves by corroborations desc, then confidence desc, then collected_at desc."""
    # corroborations dominate confidence/recency
    by_corr = _merge(
        [
            _claim(1, corr=1, conf=0.99, collected=_NOW, cid=ClaimId(new_claim_id())),
            _claim(1, corr=5, conf=0.10, collected=_NOW - timedelta(days=1)),
        ]
    )
    assert by_corr is not None and by_corr.provenance.corroborations == 5

    # equal corroborations -> confidence wins
    by_conf = _merge([_claim(1, corr=2, conf=0.4), _claim(1, corr=2, conf=0.9)])
    assert by_conf is not None and by_conf.provenance.confidence == 0.9

    # equal corroborations + confidence -> later collected_at wins
    later = _NOW
    earlier = _NOW - timedelta(days=2)
    by_recency = _merge(
        [
            _claim(1, corr=2, conf=0.7, collected=earlier),
            _claim(1, corr=2, conf=0.7, collected=later),
        ]
    )
    assert by_recency is not None and by_recency.provenance.collected_at == later


def test_stale_claim_is_returned_flagged_not_dropped() -> None:
    """A past-TTL claim is the winner with freshness_state='stale' (never dropped from the set)."""
    stale = _claim(1, observed=_NOW - timedelta(days=200))
    result = _merge([stale])
    assert result is not None
    assert result.freshness_state is FreshnessState.STALE
    assert result.provenance.claim_id == stale.id


def test_d7_freshness_mode_flip_changes_winner() -> None:
    """Fresh-low-trust vs stale-high-trust: the D7 policy decides, overridable via config."""
    stale_tier1 = _claim(1, value={"amount_usd": 1}, observed=_NOW - timedelta(days=200))
    fresh_tier3 = _claim(3, value={"amount_usd": 3}, observed=_NOW)

    default = _merge([stale_tier1, fresh_tier3])  # TTL_GATES_ELIGIBILITY (default)
    assert default is not None
    assert default.provenance.source_tier == 3  # fresh beats stale
    assert default.freshness_state is FreshnessState.FRESH

    trust_first = _merge(
        [stale_tier1, fresh_tier3],
        policy=MergePolicy(freshness_mode=FreshnessMode.TRUST_FIRST),
    )
    assert trust_first is not None
    assert trust_first.provenance.source_tier == 1  # highest trust wins even if stale
    assert trust_first.freshness_state is FreshnessState.STALE


def test_conflict_flag_only_for_tier_le2_disagreement() -> None:
    """Two disagreeing tier<=2 claims flag a conflict with both ids; tier-2 vs tier-4 does not."""
    a = _claim(1, value={"amount_usd": 1}, cid=ClaimId(new_claim_id()))
    b = _claim(2, value={"amount_usd": 2}, cid=ClaimId(new_claim_id()))
    conflicting = _merge([a, b])
    assert conflicting is not None
    assert conflicting.conflict is True
    assert set(conflicting.conflicting_claim_ids) == {a.id, b.id}

    # tier-2 vs a (verified) tier-4 with a different value: only one tier<=2 claim -> no conflict
    t2 = _claim(2, value={"amount_usd": 2})
    t4 = _claim(4, value={"amount_usd": 99}, status=VerificationStatus.VERIFIED, span="cited")
    no_conflict = _merge([t2, t4])
    assert no_conflict is not None and no_conflict.conflict is False


def test_unverified_tier4_is_excluded() -> None:
    """An unverified tier-4 claim never wins; alone it yields empty (None)."""
    assert _merge([_claim(4)]) is None
    # but with an eligible tier-1 present, the tier-1 wins and the tier-4 is ignored
    result = _merge([_claim(4), _claim(1, value={"amount_usd": 7})])
    assert result is not None and result.value_json == {"amount_usd": 7}
    # a verified tier-4 (with a span) is eligible when it is the only claim
    verified = _merge([_claim(4, status=VerificationStatus.VERIFIED, span="model cited this")])
    assert verified is not None and verified.provenance.source_tier == 4


def test_weak_binding_contact_claim_excluded() -> None:
    """A weak-binding contact claim never wins; a strong-binding one is eligible."""
    weak = _claim(
        2,
        entity_type=EntityType.CONTACT,
        binding=IdentityBinding.WEAK,
        field="contact.facet.recent_post",
        value="weak hook",
    )
    assert _merge([weak]) is None
    strong = _claim(
        2,
        entity_type=EntityType.CONTACT,
        binding=IdentityBinding.STRONG,
        field="contact.facet.recent_post",
        value="strong hook",
    )
    result = _merge([strong])
    assert result is not None and result.value_json == "strong hook"


def test_superseded_and_rejected_are_never_considered() -> None:
    """Superseded claims and rejected claims are excluded from the merge."""
    superseded = _claim(1, value={"amount_usd": 1}, superseded=ClaimId(new_claim_id()))
    assert _merge([superseded]) is None
    rejected = _claim(1, value={"amount_usd": 1}, status=VerificationStatus.REJECTED)
    assert _merge([rejected]) is None


def test_no_claims_is_empty() -> None:
    assert _merge([]) is None


def test_discovery_claim_does_not_pollute_conflict() -> None:
    """A discovery claim is admission evidence, not a disagreeing field-value source."""
    field = _claim(1, value={"amount_usd": 10})
    disc = discovery_claim(
        entity_id=_ENTITY,
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json={"amount_usd": 999},
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        source_url="https://exa.example",
        confidence=0.7,
        run_id=_RUN,
        research_mode=ResearchMode.ACCOUNT_DISCOVERY,
        found_via="exa",
        matched_signal="match",
        discovery_confidence=0.8,
    )
    result = _merge([field, disc])
    assert result is not None
    assert result.value_json == {"amount_usd": 10}
    assert result.conflict is False
    assert result.conflicting_claim_ids == ()


def test_weak_binding_claim_does_not_pollute_conflict() -> None:
    """A weak-binding contact claim (someone else's fact) is not a disagreeing source."""
    strong = _claim(
        2,
        entity_type=EntityType.CONTACT,
        binding=IdentityBinding.STRONG,
        field="contact.facet.recent_post",
        value="real hook",
    )
    weak = _claim(
        2,
        entity_type=EntityType.CONTACT,
        binding=IdentityBinding.WEAK,
        field="contact.facet.recent_post",
        value="someone else's hook",
    )
    result = _merge([strong, weak])
    assert result is not None
    assert result.value_json == "real hook"
    assert result.conflict is False


def test_fallback_to_unpromotable_returns_flagged_value() -> None:
    """With the opt-in policy, the only-un-promotable case returns the best claim, flagged."""
    only_tier4 = _claim(4, value={"amount_usd": 4})
    result = _merge([only_tier4], policy=MergePolicy(fallback_to_unpromotable=True))
    assert result is not None
    assert result.conflict is True  # flagged
    assert result.value_json == {"amount_usd": 4}
