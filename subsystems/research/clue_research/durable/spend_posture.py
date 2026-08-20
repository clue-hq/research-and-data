"""Record-only posture for the platform's *own* spend caps (founder ruling, 2026-08-20).

The ruling — `_memory/2026-08-20-seven-fix-night-close-out.md`, "Founder rulings 2026-08-20",
item 2 — is: **"Spend caps exist but do not block, for now."** In the FI pilot posture a cap we set
ourselves stops being a refusal and becomes a record: the comparison is still computed, the amounts
are still written to the ledger exactly, and the skip is announced loudly — but an otherwise
authorized provider call is never stopped on cost grounds. Hard spend control lives at the provider
consoles (the same reasoning as ``Settings.budget_controls_enabled``, whose switch this reuses;
there is deliberately no second flag).

The lesson behind it is concrete: on 2026-08-19 a live account run made all three Sumble calls, was
charged for all three, and then *threw the data away* because the total exceeded a cap we had
derived from the bounded worst case — the unbounded ``/techs`` endpoint cannot be bounded in
advance, so the refusal came after the money was gone.

This module is the single place that decides. Callers keep their comparison and their raise; they
only ask this function whether the refusal is still enforced::

    if reserved > cap and cap_refusal_is_enforced(
        enforce_budget,
        site="sumble_account_gap_reservation",
        reason="reserved_units_above_cap",
        amounts={"provider_units_reserved": reserved, "provider_credit_cap": cap},
    ):
        raise AccountGapBudgetExceeded(...)

Two things this is emphatically **not**:

* It is not a *provider* posture. A real Sumble 4xx, a credit-contract violation, and the
  unknown-spend quarantine are the provider's facts and this module never touches them.
* It is not an accounting relaxation. Reserved/charged numbers, the table CHECKs
  (``charged <= reserved``) and the burn-down surfaces are unchanged; where a record-only charge
  could now pass its reservation the caller reserves honestly larger instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Final

from clue_obs import get_logger
from clue_obs.otel import MetricSink, get_metric_sink

log = get_logger("clue_research.durable.spend_posture")

#: One counter for every cap refusal the pilot posture skipped, attributed by ``site`` and
#: ``reason`` so a deployment can see exactly which of our caps stopped biting and how often.
METRIC_SPEND_CAP_RECORD_ONLY: Final = "research.spend.cap_record_only"

#: The structured-log event that carries the amounts (the metric carries only the labels).
EVENT_SPEND_CAP_RECORD_ONLY: Final = "spend_cap.record_only"


def cap_refusal_is_enforced(
    enforce_budget: bool,
    *,
    site: str,
    reason: str,
    amounts: Mapping[str, Decimal | int | str],
    sink: MetricSink | None = None,
) -> bool:
    """Decide whether an already-detected cap breach still refuses, and record it when it does not.

    Call this only once the breach is known to be real, so the record is never emitted for a
    request that was within its cap anyway. Returns ``True`` when the caller must still raise
    (the enforcing posture — today's behaviour, unchanged), and ``False`` after emitting the
    record-only log + metric naming what would have been refused and by how much.
    """

    if enforce_budget:
        return True
    log.warning(
        EVENT_SPEND_CAP_RECORD_ONLY,
        site=site,
        reason=reason,
        **{key: str(value) for key, value in amounts.items()},
    )
    (sink or get_metric_sink()).add(
        METRIC_SPEND_CAP_RECORD_ONLY, 1.0, {"site": site, "reason": reason}
    )
    return False


__all__ = [
    "EVENT_SPEND_CAP_RECORD_ONLY",
    "METRIC_SPEND_CAP_RECORD_ONLY",
    "cap_refusal_is_enforced",
]
