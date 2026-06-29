"""M13.3 — the concrete ``BacktestGate`` (the api-root binding of the review → M9.6 boundary).

``review`` may not import ``verification``/``evals``/``discovery_scoring``, so the M13.3 learning
loop calls the frozen ``core.BacktestGate``; this is the impl the api root injects (the M9.1
pre-spend-gate / M9.4 binding-classifier / M12.3 readiness-reader pattern).

The M9.6 golden set has **no scoring-accuracy fixtures**, so the labeled account set (M13.2) is the
scoring golden set — the human disposition is the ground truth. The gate re-scores each labeled
account under the baseline vs proposed rubric with the pure M3.4 scorer, measures each dimension's
**ranking accuracy** (AUC: the share of accepted-vs-rejected pairs the rubric ranks correctly,
in ``[0,1]``), and runs the M9.6 ``check_regressions`` engine over the two — a rubric whose AUC
drops below ``baseline − tolerance`` is blocked (spec §M13.3 AC).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import TenantScope
from clue_research.core import BacktestGate, BacktestRegression, BacktestVerdict
from clue_research.db import connection
from clue_research.evals import EvalReport, MechanismMetric
from clue_research.icp import get_rubric_version, rubric_from_slot, score_entity
from clue_research.review import account_outcome_labels, read_labeled_dataset
from clue_research.verification import check_regressions

_ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]

# A [0,1] AUC is encoded as a MechanismMetric recall (detected/expected) for the M9.6 regression
# engine to score it like any other gate metric; the scale fixes the precision of that encoding.
_SCALE = 10_000
_GOLD_SET = "m13.3_labeled_accounts"


def _auc(positive: Sequence[float], negative: Sequence[float]) -> float | None:
    """Ranking accuracy (Mann-Whitney AUC): the share of (accepted, rejected) pairs the rubric ranks
    correctly (ties count half). ``None`` when a side is empty (no discrimination computable)."""
    if not positive or not negative:
        return None
    wins = 0.0
    for p in positive:
        for n in negative:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(positive) * len(negative))


class LabeledDatasetBacktestGate:
    """The production ``core.BacktestGate`` over the M13.2 labeled account set."""

    def __init__(self, *, conn_factory: _ConnFactory = connection) -> None:
        self._conn_factory = conn_factory

    async def backtest(
        self,
        proposed_rubric_slot: Mapping[str, JsonValue],
        *,
        client_id: str,
        icp_key: str,
        baseline_version: int,
        tolerance: float = 0.0,
    ) -> BacktestVerdict:
        proposed = rubric_from_slot(proposed_rubric_slot)
        async with self._conn_factory() as conn:
            baseline = await get_rubric_version(conn, client_id, icp_key, baseline_version)
            if proposed is None or baseline is None:
                return BacktestVerdict(
                    passed=True,  # nothing to compare — can't detect a regression, so don't block
                    baseline_rubric_version=baseline.version if baseline else None,
                    proposed_rubric_version=proposed.version if proposed else None,
                    detail="no baseline/proposed rubric to compare — backtest skipped",
                )
            dataset = await read_labeled_dataset(
                conn, client_id=client_id, icp_key=icp_key, icp_spec_version=baseline_version
            )
            labels = account_outcome_labels(dataset)
            scope = TenantScope.for_tenant(client_id)
            # per dimension, the baseline/proposed scores split by label (accepted vs rejected).
            buckets: dict[str, list[list[float]]] = {
                "fit": [[], [], [], []],  # base_pos, base_neg, prop_pos, prop_neg
                "intent": [[], [], [], []],
            }
            for account_entity_id, is_positive in labels.items():
                base = await score_entity(conn, baseline, account_entity_id, scope=scope)
                prop = await score_entity(conn, proposed, account_entity_id, scope=scope)
                for dim, base_v, prop_v in (
                    ("fit", base.fit_score, prop.fit_score),
                    ("intent", base.intent_score, prop.intent_score),
                ):
                    bp, bn, pp, pn = buckets[dim]
                    (bp if is_positive else bn).append(base_v)
                    (pp if is_positive else pn).append(prop_v)

        # AUC per dimension where both labels are present (else the dimension is inconclusive).
        aucs: dict[str, tuple[float, float]] = {}
        for dim, (bp, bn, pp, pn) in buckets.items():
            base_auc, prop_auc = _auc(bp, bn), _auc(pp, pn)
            if base_auc is not None and prop_auc is not None:
                aucs[dim] = (base_auc, prop_auc)

        if not aucs:
            return BacktestVerdict(
                passed=True,  # need accepted and rejected accounts to discriminate — inconclusive
                baseline_rubric_version=baseline.version,
                proposed_rubric_version=proposed.version,
                sample_size=len(labels),
                detail="insufficient labeled accounts (need accepted and rejected) — not blocking",
            )

        base_report = EvalReport(
            gold_set=_GOLD_SET,
            judge="rubric_auc",
            mechanism_metrics=tuple(
                MechanismMetric(mechanism=dim, detected=round(ba * _SCALE), expected=_SCALE)
                for dim, (ba, _pa) in aucs.items()
            ),
        )
        prop_report = EvalReport(
            gold_set=_GOLD_SET,
            judge="rubric_auc",
            mechanism_metrics=tuple(
                MechanismMetric(mechanism=dim, detected=round(pa * _SCALE), expected=_SCALE)
                for dim, (_ba, pa) in aucs.items()
            ),
        )
        regressions = check_regressions(prop_report, base_report, tolerance=tolerance)
        bt_regressions = tuple(
            BacktestRegression(
                metric=r.metric, baseline=r.baseline, current=r.current, tolerance=r.tolerance
            )
            for r in regressions
        )
        score_delta = {f"{dim}_auc": pa - ba for dim, (ba, pa) in aucs.items()}
        passed = not bt_regressions
        detail = (
            "no AUC regression — promotion allowed"
            if passed
            else "rubric ranking accuracy (AUC) regressed below baseline−tolerance"
        )
        return BacktestVerdict(
            passed=passed,
            regressions=bt_regressions,
            score_delta=score_delta,
            baseline_rubric_version=baseline.version,
            proposed_rubric_version=proposed.version,
            sample_size=len(labels),
            detail=detail,
        )


def build_backtest_gate(*, conn_factory: _ConnFactory = connection) -> BacktestGate:
    """Construct the production ``BacktestGate`` to inject into the M13.3 loop (read-only;
    re-scores over the claim store + labeled dataset and runs the M9.6 regression engine)."""
    return LabeledDatasetBacktestGate(conn_factory=conn_factory)


# Static-time conformance: the impl satisfies the frozen core seam.
_GATE_IS_A_BACKTEST_GATE: type[BacktestGate] = LabeledDatasetBacktestGate
