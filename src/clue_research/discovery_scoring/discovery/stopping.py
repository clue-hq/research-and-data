"""The discovery stopping rule — when to stop an open-ended search (M6.1 / ENG-128).

Open-ended discovery runs forever unless told to stop (staged-flow §3). Two independent stop
conditions, both versioned config (D7), never constants:

* **marginal yield** — when the *new-candidate rate* (post-dedup new candidates / records seen)
  over a sliding window of recent expand rounds drops below a threshold, the search has saturated:
  more queries mostly return companies already found. This is a *recall* control.
* **budget cap** — when cumulative resolver spend reaches the discovery budget cap, stop regardless
  of yield. This is a *cost* control.

The ``stopping_reason`` distinguishes the two (and ``EXHAUSTED`` when channels simply run out),
which matters downstream: a budget-cap stop while yield is still high means coverage is *low* and
the client should raise the budget (M6.5 reads this), whereas a marginal-yield stop means the search
genuinely saturated. The rule is pure and deterministic for fixed inputs.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from enum import StrEnum

from clue_core import CostCents


class StoppingReason(StrEnum):
    """Why a discovery run stopped (staged-flow §3; the ``DiscoveryResult.stopping_reason``)."""

    MARGINAL_YIELD = "marginal_yield"  # new-candidate rate fell below the threshold (saturated)
    BUDGET_CAP = "budget_cap"  # cumulative resolver spend reached the discovery cap
    EXHAUSTED = "exhausted"  # all channels ran out of planned queries (nothing left to ask)
    ROUND_CAP = (
        "round_cap"  # the max-rounds safety backstop fired with work still queued (abnormal)
    )


def marginal_yield(new_candidates: int, records_seen: int) -> float:
    """The new-candidate rate over a window: fraction of seen records that were *new* (post-dedup).

    ``0.0`` when nothing was seen (a degenerate window cannot show fresh yield). A high value means
    the search is still finding new companies; a low value means it has saturated.
    """
    return new_candidates / records_seen if records_seen > 0 else 0.0


class StoppingRule:
    """Track the sliding window of expand-round yields + cumulative spend; decide when to stop.

    Feed one :meth:`record_round` per expand round (the new-candidate and records-seen counts for
    that round, plus the round's spend); :meth:`reason` returns the firing :class:`StoppingReason`
    or ``None``. The marginal-yield check only engages once the window is full (so a slow first
    round does not trip it); the budget check engages immediately. Pure/deterministic.
    """

    def __init__(
        self,
        *,
        window_size: int,
        marginal_yield_threshold: float,
        budget_cap_cents: CostCents | None,
    ) -> None:
        if window_size < 1:
            raise ValueError(f"window_size must be >= 1 (got {window_size})")
        self._window_size = window_size
        self._threshold = marginal_yield_threshold
        self._budget_cap = budget_cap_cents
        self._new_window: deque[int] = deque(maxlen=window_size)
        self._seen_window: deque[int] = deque(maxlen=window_size)
        self._spent: CostCents = Decimal(0)

    @property
    def spent_cents(self) -> CostCents:
        return self._spent

    def record_round(
        self, *, new_candidates: int, records_seen: int, cost_cents: CostCents
    ) -> None:
        """Record one expand round's outcome into the window + cumulative spend."""
        self._new_window.append(new_candidates)
        self._seen_window.append(records_seen)
        self._spent += cost_cents

    def window_yield(self) -> float:
        """The marginal yield over the current window (new / seen)."""
        return marginal_yield(sum(self._new_window), sum(self._seen_window))

    def budget_exceeded(self) -> bool:
        return self._budget_cap is not None and self._spent >= self._budget_cap

    def reason(self) -> StoppingReason | None:
        """The firing stop reason, or ``None`` to keep going. Budget is checked first (a cost cap
        overrides yield); marginal yield only once the window is full."""
        if self.budget_exceeded():
            return StoppingReason.BUDGET_CAP
        if len(self._seen_window) >= self._window_size and self.window_yield() < self._threshold:
            return StoppingReason.MARGINAL_YIELD
        return None


__all__ = ["StoppingReason", "StoppingRule", "marginal_yield"]
