"""Static (no-database) tests for M5.4 — hybrid lookalike seeding.

Exercises the pure policy blend, the dedup/anchor ordering, the reuse policy, the SeedSet shape +
counts, and the deterministic run id without a connection.
"""

from __future__ import annotations

from clue_research.core import EntityId
from clue_research.icp import TierBand, TierCutoffs, fit_floor
from clue_research.stage0 import (
    DEFAULT_SEED_POLICY,
    SEED_REUSE_POLICY,
    ICPSpecRef,
    SeedAccount,
    SeedPolicy,
    SeedReason,
    SeedSet,
    SkippedSeed,
    seeds_run_id,
)
from clue_research.stage0.seeds import _Candidate, _rank_and_gate
from clue_research.stage0.seeds_types import is_customer_reason, reason_rank


def _eid() -> EntityId:
    from uuid import uuid4

    return EntityId(uuid4())


def test_seed_confidence_blends_and_clamps() -> None:
    p = DEFAULT_SEED_POLICY  # w_resolution=0.3, w_fit=0.5, customer_bonus=0.2
    # a perfect customer: 0.3*1 + 0.5*1 + 0.2 = 1.0 (clamped, not 1.0+)
    assert p.seed_confidence(resolution_confidence=1.0, fit=1.0, is_customer=True) == 1.0
    # a high-fit non-customer import: 0.3*1 + 0.5*0.8 = 0.7
    assert p.seed_confidence(resolution_confidence=1.0, fit=0.8, is_customer=False) == 0.7
    # a customer with no scorable fit still gets the resolution + customer terms: 0.3 + 0.2 = 0.5
    assert p.seed_confidence(resolution_confidence=1.0, fit=0.0, is_customer=True) == 0.5
    # the customer bonus strictly lifts an otherwise-identical candidate (ranking preference)
    base = p.seed_confidence(resolution_confidence=0.9, fit=0.4, is_customer=False)
    boosted = p.seed_confidence(resolution_confidence=0.9, fit=0.4, is_customer=True)
    assert boosted > base


def test_seed_policy_defaults_are_clean_anchors() -> None:
    p = SeedPolicy()
    assert p.min_resolution_confidence == 0.85  # deterministic/high-confidence identity only
    assert p.admit_unmatched_customers is False  # don't mint claim-less candidates by default
    assert p.max_seeds == 50


def test_reason_rank_orders_customers_above_imports() -> None:
    assert reason_rank(SeedReason.CRM_CUSTOMER) > reason_rank(SeedReason.EXISTING_CUSTOMER)
    assert reason_rank(SeedReason.EXISTING_CUSTOMER) > reason_rank(SeedReason.HIGH_FIT_IMPORT)
    # a genuine customer (any flavor) carries the customer bonus; a high-fit import does not
    assert is_customer_reason(SeedReason.CRM_CUSTOMER)
    assert is_customer_reason(SeedReason.EXISTING_CUSTOMER)
    assert not is_customer_reason(SeedReason.HIGH_FIT_IMPORT)


def test_seed_reuse_policy_privatizes_discovery() -> None:
    # the seed marker is a discovery.provenance claim; "which accounts a client seeds from" is
    # client-tuned intent, so the discovery namespace is privatized for the seed scenario
    assert "discovery." in SEED_REUSE_POLICY.tenant_private_prefixes


def test_seedset_counts_and_customer_count() -> None:
    seeds = (
        SeedAccount(account_entity_id=_eid(), seed_reason=SeedReason.CRM_CUSTOMER.value),
        SeedAccount(account_entity_id=_eid(), seed_reason=SeedReason.EXISTING_CUSTOMER.value),
        SeedAccount(account_entity_id=_eid(), seed_reason=SeedReason.CASE_STUDY.value),
        SeedAccount(account_entity_id=_eid(), seed_reason=SeedReason.HIGH_FIT_IMPORT.value),
    )
    seed_set = SeedSet(client_id="t", icp_key="primary", icp_version=1, seeds=seeds)
    assert seed_set.seed_count == 4
    # customer_seed_count uses the canonical is_customer_reason — incl. case_study, not the import
    assert seed_set.customer_seed_count == 3
    assert not seed_set.suppressed


def test_rank_and_gate_caps_to_top_ranked_seeds() -> None:
    """_rank_and_gate sorts by seed_confidence (desc) then truncates at max_seeds — the cap keeps
    the highest-confidence anchors, not an arbitrary subset."""
    cands = {
        _eid(): _cand(0.6),
        _eid(): _cand(0.9),
        _eid(): _cand(0.7),
    }
    policy = SeedPolicy(max_seeds=2, min_resolution_confidence=0.0, min_seed_confidence=0.0)
    chosen = _rank_and_gate(cands, policy=policy, fit_floor=0.0)
    assert [c.seed_confidence for c in chosen] == [0.9, 0.7]  # top-2, ordered


def test_rank_and_gate_drops_below_floor_and_thresholds() -> None:
    """A candidate below the ICP fit floor, the resolution-confidence floor, or the seed-confidence
    floor is excluded (the per-ICP partition + clean-anchor gates)."""
    below_fit = _cand(0.9, fit=0.2)
    dirty = _cand(0.9, resolution_confidence=0.6)
    weak = _cand(0.4)
    good = _cand(0.9)
    cands = {_eid(): below_fit, _eid(): dirty, _eid(): weak, _eid(): good}
    chosen = _rank_and_gate(cands, policy=DEFAULT_SEED_POLICY, fit_floor=0.5)
    assert chosen == [good]


def _cand(
    seed_confidence: float, *, fit: float = 1.0, resolution_confidence: float = 1.0
) -> _Candidate:
    return _Candidate(
        entity_id=_eid(),
        reason=SeedReason.EXISTING_CUSTOMER,
        fit=fit,
        resolution_confidence=resolution_confidence,
        justifying=(),
        seed_confidence=seed_confidence,
    )


def test_shared_fit_floor_helper() -> None:
    """M5.4 seeding and M5.3 non-fit flagging share the M3.4 fit_floor (lowest min_fit; 0.0 = no
    bar) so they can never drift on the D5/D6 partition threshold."""
    cutoffs = TierCutoffs(
        bands=(TierBand(tier="high", min_fit=0.7), TierBand(tier="mid", min_fit=0.3)),
        fallback_tier="low",
    )
    assert fit_floor(cutoffs) == 0.3  # the lowest band floor
    assert fit_floor(TierCutoffs()) == 0.0  # no bands → no bar


def test_suppressed_seedset_is_empty() -> None:
    seed_set = SeedSet(client_id="t", icp_key="primary", icp_version=1, suppressed=True)
    assert seed_set.suppressed
    assert seed_set.seed_count == 0
    assert seed_set.seeds == ()


def test_skipped_seed_carries_a_reason() -> None:
    skip = SkippedSeed(identity_repr="Acme Co", reason="did not resolve")
    assert skip.identity_repr == "Acme Co"
    assert skip.reason


def test_seeds_run_id_is_deterministic_per_client_and_icp() -> None:
    ref = ICPSpecRef(client_id="t", icp_key="primary", icp_version=1)
    other_version = ICPSpecRef(client_id="t", icp_key="primary", icp_version=2)
    other_icp = ICPSpecRef(client_id="t", icp_key="secondary", icp_version=1)
    assert seeds_run_id("t", ref) == seeds_run_id("t", ref)
    assert seeds_run_id("t", ref) != seeds_run_id("t", other_version)
    assert seeds_run_id("t", ref) != seeds_run_id("t", other_icp)
    assert seeds_run_id("other-tenant", ref) != seeds_run_id("t", ref)
