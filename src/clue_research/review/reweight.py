"""M13.3 — the deterministic, bounded reweighters (priors → yield, not autonomous magic).

Two pure functions, one disposition signal pointed at two targets (staged-flow §9):

* :func:`reweight_source_profile` — moves each source's ordinal trust weight by **at most one level
  per run** from its measured yield (precision × downstream-signal, cost-penalized). Ordinal weights
  have a floor (``LOW``), so a source that produced only rejected claims down-weights but is **never
  zeroed** (spec §M13.3 AC). Always within bounds (the one-level cap).
* :func:`reweight_scoring_rubric` — nudges each fit/intent entry weight toward the signals that
  discriminate accepted-vs-rejected accounts in the labeled dataset, with a **capped per-weight
  delta**. Decomposed/explainable: every moved weight records which signal and outcome drove it
  (substrate §9 "decompose, don't ship an opaque 87/100"). ``within_bounds`` is ``False`` when the
  cap bit (the signal wanted a bigger move → human-gated promotion).

Both are pure (no DB, no LLM) — the loop (``learning.py``) persists their output as a versioned
``config_revision`` proposal. Policy is data: :class:`ReweightPolicy` carries the bounds/thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core import EntityId
from clue_research.icp.rubric import ScoringRubric, SubRubric
from clue_research.icp.source_profile import SourceWeight, WeightedSource
from clue_research.review.disposition import DispositionType
from clue_research.review.labeled_dataset import LabeledRow
from clue_research.review.yield_metrics import YieldMetrics

# Account-level outcomes that label an account positive/negative (mirrors yield_metrics; the rubric
# reweight reads the same accept/reject signal that reweights sources — one signal, two targets).
_POSITIVE: frozenset[DispositionType] = frozenset(
    {
        DispositionType.ACCOUNT_ACCEPTED,
        DispositionType.REPLY_RECEIVED,
        DispositionType.MEETING_BOOKED,
        DispositionType.CLOSED_WON,
    }
)
_NEGATIVE: frozenset[DispositionType] = frozenset(
    {DispositionType.ACCOUNT_REJECTED, DispositionType.CLOSED_LOST}
)

_LEVELS: tuple[SourceWeight, ...] = (SourceWeight.LOW, SourceWeight.MEDIUM, SourceWeight.HIGH)


class ReweightPolicy(BaseModel):
    """The bounds/thresholds the reweighters read — policy as data (conventions §2), swappable per
    client/ICP without code. Defaults are conservative (small steps, a clear human-gate trigger)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # source-profile: move a source up a level at/above this precision (and downstream, when known);
    # down a level below precision_down. Bounded to one level/run regardless.
    precision_up: float = 0.7
    precision_down: float = 0.3
    downstream_up: float = 0.5
    # scoring-rubric: how hard to nudge a weight toward a discriminating signal, and the cap on the
    # relative per-weight move per run (the bounded step; the human gate trips when it bites).
    rubric_learning_rate: float = 0.5
    rubric_max_rel_delta: float = 0.25


DEFAULT_REWEIGHT_POLICY = ReweightPolicy()


class WeightMove(BaseModel):
    """One entry in a reweight's decomposed explanation: a ``key`` (source_key or field_key) whose
    weight moved ``old`` → ``new``, plus the measured ``rationale`` (precision / downstream-signal /
    accepted-vs-rejected means) that drove the move — the explainability surface (§M13.3 AC)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    field_class: str | None = None
    old: float
    new: float
    delta: float
    rationale: dict[str, JsonValue] = {}


# --- source-profile reweight ------------------------------------------------


class _SourceAgg(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    precision: float | None
    downstream_signal: float | None
    cost_per_surviving_claim: float | None


def _aggregate_by_source(metrics: YieldMetrics) -> dict[str, _SourceAgg]:
    """Aggregate a source's slots (one per field-class) into one merit view: pooled precision, the
    per-source downstream signal, and a representative cost-per-surviving-claim."""
    out: dict[str, _SourceAgg] = {}
    for source_key, slots in metrics.by_source_key().items():
        total = sum(s.stat.claims_total for s in slots)
        verified = sum(s.stat.claims_verified for s in slots)
        downstream = next(
            (s.downstream_signal for s in slots if s.downstream_signal is not None), None
        )
        costs = [float(s.cost_per_surviving_claim) for s in slots if s.cost_per_surviving_claim]
        out[source_key] = _SourceAgg(
            precision=(verified / total if total else None),
            downstream_signal=downstream,
            cost_per_surviving_claim=(sum(costs) / len(costs) if costs else None),
        )
    return out


def _bounded_level(current: SourceWeight, agg: _SourceAgg, policy: ReweightPolicy) -> SourceWeight:
    """The new ordinal weight: up a level on strong yield, down on weak, else unchanged — capped
    to a single level (never below ``LOW``, so a source is never zeroed)."""
    if agg.precision is None:
        return current  # produced nothing — nothing to judge, leave the prior
    idx = _LEVELS.index(current)
    strong_downstream = (
        agg.downstream_signal is None or agg.downstream_signal >= policy.downstream_up
    )
    if agg.precision >= policy.precision_up and strong_downstream:
        return _LEVELS[min(idx + 1, len(_LEVELS) - 1)]
    if agg.precision < policy.precision_down:
        return _LEVELS[max(idx - 1, 0)]
    return current


def reweight_source_profile(
    current: Sequence[WeightedSource],
    metrics: YieldMetrics,
    *,
    policy: ReweightPolicy = DEFAULT_REWEIGHT_POLICY,
) -> tuple[tuple[WeightedSource, ...], tuple[WeightMove, ...]]:
    """Bounded, deterministic reweight of one source-profile slot from yield (spec §M13.3).

    Each source moves at most one ordinal level per run (``HIGH``↔``MEDIUM``↔``LOW``); a source with
    no measured yield keeps its weight; a source is never zeroed (``LOW`` is the floor). Returns the
    new ``WeightedSource`` tuple (ranks preserved) and the decomposed per-source moves."""
    agg = _aggregate_by_source(metrics)
    new_sources: list[WeightedSource] = []
    moves: list[WeightMove] = []
    for ws in current:
        a = agg.get(ws.source_key)
        target = _bounded_level(ws.weight, a, policy) if a is not None else ws.weight
        if target is not ws.weight:
            moves.append(
                WeightMove(
                    key=ws.source_key,
                    old=ws.weight.prior,
                    new=target.prior,
                    delta=target.prior - ws.weight.prior,
                    rationale={
                        "precision": a.precision if a else None,
                        "downstream_signal": a.downstream_signal if a else None,
                        "cost_per_surviving_claim": a.cost_per_surviving_claim if a else None,
                        "from": ws.weight.value,
                        "to": target.value,
                    },
                )
            )
        new_sources.append(ws.model_copy(update={"weight": target}))
    return tuple(new_sources), tuple(moves)


# --- scoring-rubric reweight ------------------------------------------------


def account_outcome_labels(dataset: Sequence[LabeledRow]) -> dict[EntityId, bool]:
    """Each account's label: ``True`` (positive) if it carries any positive outcome, ``False`` if it
    carries only negative outcomes. Accounts with no account outcome are unlabeled (omitted)."""
    positive: set[EntityId] = set()
    negative: set[EntityId] = set()
    for row in dataset:
        if row.disposition_type in _POSITIVE:
            positive.add(row.account_entity_id)
        elif row.disposition_type in _NEGATIVE:
            negative.add(row.account_entity_id)
    labels: dict[EntityId, bool] = dict.fromkeys(positive, True)
    for acct in negative:
        if acct not in positive:
            labels[acct] = False
    return labels


def _factors_by_field(score_json: JsonValue) -> dict[str, float]:
    """Per field_key, the ``[0,1]`` factor from a serialized ``core.Score`` snapshot's parts."""
    if not isinstance(score_json, Mapping):
        return {}
    components = score_json.get("components")
    if not isinstance(components, Sequence):
        return {}
    out: dict[str, float] = {}
    for comp in components:
        if isinstance(comp, Mapping) and isinstance(comp.get("name"), str):
            value = comp.get("value")
            if isinstance(value, (int, float)):
                out[str(comp["name"])] = float(value)
    return out


def _latest_snapshot(
    dataset: Sequence[LabeledRow], *, intent: bool
) -> dict[EntityId, dict[str, float]]:
    """Per account, the per-field factors from its (fit or intent) score snapshot — taken from the
    account's latest labeled row (deterministic: the dataset is ordered, the last wins)."""
    out: dict[EntityId, dict[str, float]] = {}
    for row in dataset:
        snap = row.intent_score_json if intent else row.fit_score_json
        factors = _factors_by_field(snap)
        if factors:
            out[row.account_entity_id] = factors
    return out


def _discrimination(
    field_key: str, labels: Mapping[EntityId, bool], factors: Mapping[EntityId, dict[str, float]]
) -> tuple[float | None, dict[str, JsonValue]]:
    """The signal's discriminating power: mean factor among positive accounts minus mean among
    negative accounts (``None`` when a side is empty). Returned with the supporting stats."""
    pos = [factors[a][field_key] for a in labels if labels[a] and field_key in factors.get(a, {})]
    neg = [
        factors[a][field_key] for a in labels if not labels[a] and field_key in factors.get(a, {})
    ]
    if not pos or not neg:
        return None, {"n_positive": len(pos), "n_negative": len(neg)}
    pos_mean = sum(pos) / len(pos)
    neg_mean = sum(neg) / len(neg)
    return pos_mean - neg_mean, {
        "accepted_mean": pos_mean,
        "rejected_mean": neg_mean,
        "n_positive": len(pos),
        "n_negative": len(neg),
    }


def _reweight_sub(
    sub: SubRubric,
    labels: Mapping[EntityId, bool],
    factors: Mapping[EntityId, dict[str, float]],
    policy: ReweightPolicy,
    dimension: str,
) -> tuple[dict[str, float], list[WeightMove], bool]:
    """Reweight one sub-rubric's entries; returns (new weights, moves, within_bounds)."""
    new_weights: dict[str, float] = {}
    moves: list[WeightMove] = []
    within = True
    for entry in sub.entries:
        disc, stats = _discrimination(entry.field_key, labels, factors)
        if disc is None or entry.weight <= 0.0:
            continue  # no usable signal (or an immovable zero weight) — leave it
        desired = entry.weight * (1.0 + policy.rubric_learning_rate * disc)
        desired = max(0.0, desired)
        lo = entry.weight * (1.0 - policy.rubric_max_rel_delta)
        hi = entry.weight * (1.0 + policy.rubric_max_rel_delta)
        capped = min(hi, max(lo, desired))
        if abs(desired - capped) > 1e-9:
            within = False  # the cap bit — the signal wanted a bigger move (human gate)
        if abs(capped - entry.weight) > 1e-9:
            new_weights[entry.field_key] = capped
            moves.append(
                WeightMove(
                    key=entry.field_key,
                    old=entry.weight,
                    new=capped,
                    delta=capped - entry.weight,
                    rationale={"dimension": dimension, "discrimination": disc, **stats},
                )
            )
    return new_weights, moves, within


def reweight_scoring_rubric(
    rubric: ScoringRubric,
    dataset: Sequence[LabeledRow],
    *,
    policy: ReweightPolicy = DEFAULT_REWEIGHT_POLICY,
) -> tuple[Mapping[str, float], Mapping[str, float], tuple[WeightMove, ...], bool]:
    """Bounded, deterministic fit/intent weight reweight from the labeled dataset (spec §M13.3).

    Each entry's weight is nudged toward signals discriminating accepted-vs-rejected accounts, with
    the per-weight move capped (the bounded step). Returns ``(fit_weights, intent_weights, moves,
    within_bounds)`` — the weight overrides for ``icp.reweighted``, the decomposed explanation,
    and whether every move stayed within the cap (``False`` ⇒ human-gated)."""
    labels = account_outcome_labels(dataset)
    fit_factors = _latest_snapshot(dataset, intent=False)
    intent_factors = _latest_snapshot(dataset, intent=True)
    fit_weights, fit_moves, fit_within = _reweight_sub(
        rubric.fit, labels, fit_factors, policy, "fit"
    )
    intent_weights, intent_moves, intent_within = _reweight_sub(
        rubric.intent, labels, intent_factors, policy, "intent"
    )
    return (
        fit_weights,
        intent_weights,
        tuple(fit_moves + intent_moves),
        fit_within and intent_within,
    )
