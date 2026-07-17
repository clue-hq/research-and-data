"""M13.3 learning-loop contract — the ``BacktestGate`` seam (the review → M9.6 boundary).

The M13.3 learning loop (in ``review``) proposes versioned config revisions — source profiles (M4.6)
and the fit/intent scoring rubric (M3.4) — from measured outcomes (verification survival +
dispositions), and **gates a rubric promotion on a backtest** against the labeled account set
(M13.2): a reweight that regresses the golden-set accuracy is blocked (spec §M13.3 AC).

``review`` may not import ``verification`` / ``discovery_scoring`` / ``evals`` (the worker-
independence contract), so the backtest is a **frozen** ``core`` :class:`BacktestGate` whose
concrete impl — which reads the ``labeled_dataset``, re-scores each labeled account under the
proposed rubric with the pure M3.4 scorer, and runs the M9.6 regression engine — is assembled at the
``api`` composition root and injected. This is the established interface-in-``core`` /
impl-injected-at-``api`` pattern (the M9.1 pre-spend gate, the M9.4 binding classifier, the M12.3
handoff-readiness reader). The :class:`LearningLoop` impl and its value types live in ``review``
(``api`` may import ``review`` directly); only this cross-package gate needs ``core``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue


class BacktestRegression(BaseModel):
    """One regressed metric in a backtest — restated in ``core`` (rather than importing
    ``evals.Regression``) so the verdict stays kernel-pure (``core`` imports nothing internal). A
    metric regressed when ``baseline - current > tolerance``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    baseline: float
    current: float
    tolerance: float = 0.0


class BacktestVerdict(BaseModel):
    """The outcome of backtesting a proposed scoring-rubric revision against the labeled golden
    account set (M13.2).

    ``passed=False`` blocks promotion (spec §M13.3: "the backtest guardrail blocks promotion of a
    rubric revision that regresses the golden-set accuracy below threshold"). The regressed metrics,
    the per-metric proposed-minus-baseline ``score_delta``, and the ``sample_size`` make the block
    auditable; ``detail`` is a human-readable summary for the promotion UI / audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    regressions: tuple[BacktestRegression, ...] = ()
    score_delta: dict[str, float] = {}
    baseline_rubric_version: int | None = None
    proposed_rubric_version: int | None = None
    sample_size: int = 0
    detail: str | None = None


@runtime_checkable
class BacktestGate(Protocol):
    """Backtest a proposed scoring-rubric revision against the M13.2 labeled account set and decide
    whether promotion may proceed (M13.3 guardrail).

    ``review`` imports only this Protocol; the concrete impl (reads ``labeled_dataset``, re-scores
    the labeled accounts under the proposed vs baseline rubric with M3.4 ``score``, and runs
    the M9.6 ``check_regressions`` engine) is built and injected at the ``api`` root. The proposed
    rubric is passed as its serialized ``icp_spec.scoring_rubric`` slot (a ``JsonValue`` mapping) so
    this seam carries no ``icp`` dependency. ``baseline_version`` is the ICP-spec version of the
    currently-active (baseline) rubric the proposed revision is compared against."""

    async def backtest(
        self,
        proposed_rubric_slot: Mapping[str, JsonValue],
        *,
        client_id: str,
        icp_key: str,
        baseline_version: int,
        tolerance: float = 0.0,
    ) -> BacktestVerdict: ...
