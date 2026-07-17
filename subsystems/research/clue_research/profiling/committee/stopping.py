"""The committee bounded-discovery stopping rule (M8.3).

Committee discovery is an ``expand`` bounded to one company's people — open-ended over the people-
sources, but never the open web (staged-flow §6). It must terminate: it stops consulting further
sources when the **marginal new-admit yield** drops below a threshold OR a **committee budget cap**
is reached. This is the contact-axis analogue of M6's discovery stopping rule, one level down; it is
M8-owned (M6's ``StoppingRule`` lives in ``discovery_scoring`` — unimportable here).

The rule treats each *source consultation* as a step (V1 ``CommitteeSource``s return their full
bounded candidate set in one call, so there is no pagination to round over): after each source it
records ``(new_admits, seen)`` and the spend, and fires once the sliding window's yield drops or the
cap is hit. A source that returns only already-seen people contributes ``new_admits=0`` → the window
yield falls → the walk halts without unbounded querying (M8.3 AC).
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from clue_core import CostCents


class CommitteeStopReason(StrEnum):
    """Why committee discovery stopped consulting sources."""

    MARGINAL_YIELD = "marginal_yield"  # the window's new-admit yield dropped below the threshold
    BUDGET_CAP = "budget_cap"  # the committee budget cap was reached
    EXHAUSTED = "exhausted"  # every bound source was consulted; neither stop condition fired


class CommitteeStoppingConfig(BaseModel):
    """Stopping-rule knobs (policy as data; Doc C §8 — confirm against real cost data)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Sliding window of recent source consultations the marginal-yield rule averages over.
    window_size: int = Field(default=2, ge=1)
    # Stop when window new-admit yield (new_admits / candidates_seen) falls below this.
    marginal_yield_threshold: float = Field(default=0.05, ge=0.0, le=1.0)


DEFAULT_COMMITTEE_STOPPING_CONFIG = CommitteeStoppingConfig()


class CommitteeStoppingRule:
    """Track marginal new-admit yield + cumulative spend; fire on budget-cap or yield drop.

    Budget is checked first (a tight cap stops immediately, regardless of yield); the marginal-yield
    rule only fires once the window is full, so a single productive source is never cut off
    prematurely. Mutable accumulator (not a frozen model) — updated per source consultation."""

    def __init__(
        self,
        config: CommitteeStoppingConfig = DEFAULT_COMMITTEE_STOPPING_CONFIG,
        *,
        budget_cap_cents: CostCents | None = None,
    ) -> None:
        self._config = config
        self._budget_cap_cents = budget_cap_cents
        self._spent = Decimal(0)
        self._window: deque[tuple[int, int]] = deque(maxlen=config.window_size)

    def record(self, *, new_admits: int, candidates_seen: int, cost_cents: CostCents) -> None:
        """Record one source consultation's outcome (new admits, candidates seen, spend)."""
        self._spent += cost_cents
        self._window.append((new_admits, candidates_seen))

    @property
    def spent_cents(self) -> CostCents:
        return self._spent

    def _window_yield(self) -> float:
        seen = sum(seen for _, seen in self._window)
        if seen <= 0:
            return 0.0
        admits = sum(admits for admits, _ in self._window)
        return admits / seen

    def reason(self) -> CommitteeStopReason | None:
        """Whether to stop now — budget cap first, then a full-window marginal-yield drop.

        Returns ``None`` to keep consulting sources. The caller maps a clean run out of sources to
        :attr:`CommitteeStopReason.EXHAUSTED`."""
        if self._budget_cap_cents is not None and self._spent >= self._budget_cap_cents:
            return CommitteeStopReason.BUDGET_CAP
        if (
            len(self._window) >= self._config.window_size
            and self._window_yield() < self._config.marginal_yield_threshold
        ):
            return CommitteeStopReason.MARGINAL_YIELD
        return None
