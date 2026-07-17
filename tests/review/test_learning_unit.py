"""M13.3 — the pure reweighters / labels / yield-stat properties (no DB).

The deterministic core of the learning loop: bounded source-profile moves (never zeroed), the
explainable rubric reweight (capped delta + human-gate flag), the account-outcome labeling, and the
M13.3 ``SourceYieldStat`` extensions (Decision 4)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from clue_core import EntityId
from clue_research.icp.rubric import RubricEntry, ScoringRubric, SubRubric
from clue_research.icp.source_profile import SourceWeight, WeightedSource
from clue_research.review import (
    SourceYield,
    YieldMetrics,
    account_outcome_labels,
    reweight_scoring_rubric,
    reweight_source_profile,
)
from clue_research.review.disposition import (
    DispositionActor,
    DispositionId,
    DispositionOrigin,
    DispositionType,
)
from clue_research.review.labeled_dataset import LabeledRow
from clue_research.sources import SourceYieldStat

_AT = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def _stat(
    source_key: str, *, total: int, verified: int, cost: str = "0", fresh: float | None = None
) -> SourceYieldStat:
    return SourceYieldStat(
        field_class=None,
        source_key=source_key,
        measurements=1,
        claims_total=total,
        claims_verified=verified,
        fields_filled=total,
        cost_cents=Decimal(cost),
        avg_freshness_seconds=fresh,
    )


def _metrics(*stats: SourceYieldStat, downstream: dict[str, float] | None = None) -> YieldMetrics:
    downstream = downstream or {}
    return YieldMetrics(
        client_id="c",
        icp_key="k",
        icp_spec_version=1,
        sources=tuple(
            SourceYield(stat=s, downstream_signal=downstream.get(s.source_key)) for s in stats
        ),
        has_downstream_signal=bool(downstream),
    )


# --- SourceYieldStat extensions (Decision 4) ------------------------------------------------------


def test_source_yield_cost_and_freshness_properties() -> None:
    s = _stat("clay", total=10, verified=8, cost="400", fresh=float(90 * 86_400))
    assert s.precision == 0.8
    assert s.cost_per_surviving_claim == Decimal("400") / 8  # cost of a *surviving* claim
    assert s.freshness_score == 0.5  # 90d over the 180d horizon → halfway fresh


def test_source_yield_none_when_no_survivors_or_freshness() -> None:
    s = _stat("x", total=2, verified=0, cost="50")
    assert s.cost_per_surviving_claim is None  # nothing survived → no denominator
    assert s.freshness_score is None  # no freshness recorded → nothing to age


# --- source-profile reweight (bounded, never zeroed) ----------------------------------------------


def test_rejected_only_source_down_weights_one_level_not_zeroed() -> None:
    """AC: a source that produced only rejected claims (precision 0) down-weights, not zeroed."""
    metrics = _metrics(_stat("clay", total=5, verified=0))
    current = (WeightedSource(source_key="clay", weight=SourceWeight.HIGH, rank=1),)
    new, moves = reweight_source_profile(current, metrics)
    assert new[0].weight is SourceWeight.MEDIUM  # one level down (bounded), not LOW/zero
    assert len(moves) == 1 and moves[0].key == "clay"


def test_rejected_only_low_source_stays_low_floor() -> None:
    metrics = _metrics(_stat("clay", total=5, verified=0))
    current = (WeightedSource(source_key="clay", weight=SourceWeight.LOW, rank=1),)
    new, _moves = reweight_source_profile(current, metrics)
    assert new[0].weight is SourceWeight.LOW  # the floor — never zeroed


def test_strong_source_up_weights_one_level() -> None:
    metrics = _metrics(_stat("apollo", total=10, verified=10), downstream={"apollo": 0.9})
    current = (WeightedSource(source_key="apollo", weight=SourceWeight.LOW, rank=1),)
    new, moves = reweight_source_profile(current, metrics)
    assert new[0].weight is SourceWeight.MEDIUM  # one level up (bounded)
    assert len(moves) == 1


def test_source_with_no_yield_is_unchanged() -> None:
    metrics = _metrics()  # no telemetry for 'unseen'
    current = (WeightedSource(source_key="unseen", weight=SourceWeight.MEDIUM, rank=1),)
    new, moves = reweight_source_profile(current, metrics)
    assert new == current and moves == ()


# --- scoring-rubric reweight (explainable, bounded, human-gate flag) ------------------------------


def _row(account: EntityId, dtype: DispositionType, *, fit_factor: float) -> LabeledRow:
    snap = {
        "value": fit_factor,
        "components": [
            {"name": "account.signal", "weight": 1.0, "value": fit_factor, "evidence_claim_ids": []}
        ],
    }
    return LabeledRow(
        disposition_id=DispositionId(uuid4()),
        disposition_type=dtype,
        actor=DispositionActor.CLIENT_SALES,
        origin=DispositionOrigin.CRM_INGEST,
        entity_id=account,
        entity_type="account",  # type: ignore[arg-type]
        account_entity_id=account,
        claim_id=None,
        campaign_run_id=None,
        client_id="c",
        icp_key="k",
        icp_spec_version=1,
        occurred_at=_AT,
        recorded_at=_AT,
        fit_score_json=snap,
        intent_score_json=snap,
    )


def _rubric() -> ScoringRubric:
    entry = RubricEntry(field_key="account.signal", weight=1.0)
    return ScoringRubric(fit=SubRubric(entries=(entry,)), intent=SubRubric())


def test_account_outcome_labels_classifies_positive_negative_neutral() -> None:
    a, b, c = EntityId(uuid4()), EntityId(uuid4()), EntityId(uuid4())
    rows = [
        _row(a, DispositionType.ACCOUNT_ACCEPTED, fit_factor=0.9),
        _row(b, DispositionType.ACCOUNT_REJECTED, fit_factor=0.1),
        _row(c, DispositionType.ACCOUNT_CONTACTED, fit_factor=0.5),  # neutral → unlabeled
    ]
    labels = account_outcome_labels(rows)
    assert labels == {a: True, b: False}  # contacted-only account omitted


def test_rubric_reweight_increases_discriminating_signal_within_bounds() -> None:
    a, b = EntityId(uuid4()), EntityId(uuid4())
    dataset = [
        _row(a, DispositionType.ACCOUNT_ACCEPTED, fit_factor=0.6),
        _row(b, DispositionType.ACCOUNT_REJECTED, fit_factor=0.4),
    ]
    fit_w, _intent_w, moves, within = reweight_scoring_rubric(_rubric(), dataset)
    assert fit_w["account.signal"] > 1.0  # the discriminating signal's weight rises
    assert within is True  # a small (0.2) discrimination stays under the cap
    assert any(m.key == "account.signal" for m in moves)  # explainable
    move = next(m for m in moves if m.key == "account.signal")
    assert move.rationale["accepted_mean"] == 0.6 and move.rationale["rejected_mean"] == 0.4


def test_rubric_reweight_caps_large_move_and_flags_human_gate() -> None:
    a, b = EntityId(uuid4()), EntityId(uuid4())
    dataset = [
        _row(a, DispositionType.ACCOUNT_ACCEPTED, fit_factor=1.0),
        _row(b, DispositionType.ACCOUNT_REJECTED, fit_factor=0.0),  # max discrimination
    ]
    fit_w, _intent_w, _moves, within = reweight_scoring_rubric(_rubric(), dataset)
    assert fit_w["account.signal"] == 1.25  # capped at +25% (the bounded step)
    assert within is False  # the cap bit → out-of-bounds → human-gated promotion
