"""M13.3 — wire the ``LearningLoop`` at the api composition root.

Builds the M13.3 :class:`~clue_research.review.LearningLoopImpl` with the concrete
``core.BacktestGate`` injected (the review → M9.6 boundary the loop's ``promote``
consults for a rubric revision). ``review`` owns the loop impl + the reweighters; ``api`` is the one
place that may also reach ``verification`` / ``evals`` (through the gate). Mirrors the other M13
joins in ``api/review_feedback_wiring.py``.
"""

from __future__ import annotations

from clue_api.backtest_wiring import build_backtest_gate
from clue_core import BacktestGate
from clue_db import ConnFactory, connection, transaction
from clue_research.review import DEFAULT_REWEIGHT_POLICY, LearningLoopImpl, ReweightPolicy


def build_learning_loop(
    *,
    conn_factory: ConnFactory = transaction,
    backtest_gate: BacktestGate | None = None,
    gate_conn_factory: ConnFactory = connection,
    policy: ReweightPolicy = DEFAULT_REWEIGHT_POLICY,
) -> LearningLoopImpl:
    """The production M13.3 ``LearningLoop``: a write-path ``conn_factory`` (one committed txn
    per propose/promote) and the injected ``BacktestGate`` (read-only) gating rubric promotion. Pass
    an explicit ``backtest_gate`` to override (e.g. a fake in tests); ``None`` builds the concrete
    labeled-dataset gate. ``policy`` carries the reweight bounds (policy as data)."""
    gate = (
        backtest_gate
        if backtest_gate is not None
        else build_backtest_gate(conn_factory=gate_conn_factory)
    )
    return LearningLoopImpl(conn_factory=conn_factory, backtest_gate=gate, policy=policy)
