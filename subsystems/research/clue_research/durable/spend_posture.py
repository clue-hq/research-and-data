"""Record-only posture for the platform's *own* mechanical refusals (founder rulings, 2026-08-20).

Two families live here, because they share one announcement shape and one deployment story:

* **Spend caps** — :func:`cap_refusal_is_enforced` for a comparison the caller can gate, and
  :func:`record_cap_refusal_skipped` for a cap that lives inside a SQL predicate and can only be
  read back afterwards. Pilot-gated on the existing ``Settings.budget_controls_enabled`` switch.
* **Policy/judgment/hygiene refusals** — :func:`policy_refusal_is_enforced` for a genuine pilot
  call, and :func:`record_policy_refusal_skipped` where the degradation is unconditional (an
  *advisory* subsystem may never veto a primary flow in any posture). Our own quality opinions,
  recorded rather than allowed to kill a draft, a launch, or a job.

The spend half of the doc follows.

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
    record_cap_refusal_skipped(site=site, reason=reason, amounts=amounts, sink=sink)
    return False


def record_cap_refusal_skipped(
    *,
    site: str,
    reason: str,
    amounts: Mapping[str, Decimal | int | str],
    sink: MetricSink | None = None,
) -> None:
    """The announcement half of :func:`cap_refusal_is_enforced`, for callers that cannot ask.

    A cap enforced *inside* a SQL predicate has no comparison to gate: the record-only posture
    drops the guard clause from the statement, so the breach is only knowable afterwards, read
    back off the row the write returned. Those callers announce directly. Same event, same
    counter, same discipline — call it only once the breach is known to be real.
    """

    log.warning(
        EVENT_SPEND_CAP_RECORD_ONLY,
        site=site,
        reason=reason,
        **{key: str(value) for key, value in amounts.items()},
    )
    (sink or get_metric_sink()).add(
        METRIC_SPEND_CAP_RECORD_ONLY, 1.0, {"site": site, "reason": reason}
    )


# --- policy / judgment / hygiene refusals ------------------------------------

#: One counter for every policy refusal that did not stop the flow, attributed by ``site`` and
#: ``reason``, so a deployment can see which of our quality opinions stopped biting and how often.
METRIC_POLICY_REFUSAL_RECORD_ONLY: Final = "research.policy.refusal_record_only"

#: The structured-log event that carries the detail (the metric carries only the labels).
EVENT_POLICY_REFUSAL_RECORD_ONLY: Final = "policy_refusal.record_only"


def record_policy_refusal_skipped(
    *,
    site: str,
    reason: str,
    detail: str,
    sink: MetricSink | None = None,
) -> None:
    """Announce a mechanical policy refusal the flow deliberately did not obey.

    The announcement primitive: a loud structured log naming the site, the reason and the
    refusal's own detail, plus the :data:`METRIC_POLICY_REFUSAL_RECORD_ONLY` counter. Call it
    only once the refusal is known to be real, so nothing is recorded for a clean request.

    Use this directly where the degradation is unconditional (a subsystem whose contract says it
    is *advisory* may never veto a primary flow in any posture); use
    :func:`policy_refusal_is_enforced` where the refusal is a genuine pilot-posture call.
    """

    log.warning(EVENT_POLICY_REFUSAL_RECORD_ONLY, site=site, reason=reason, detail=detail)
    (sink or get_metric_sink()).add(
        METRIC_POLICY_REFUSAL_RECORD_ONLY, 1.0, {"site": site, "reason": reason}
    )


def policy_refusal_is_enforced(
    enforce_policy: bool,
    *,
    site: str,
    reason: str,
    detail: str,
    sink: MetricSink | None = None,
) -> bool:
    """Decide whether an already-detected policy refusal still refuses, and record it when not.

    ``enforce_policy`` is fed from the same FI pilot switch as ``enforce_budget``
    (``Settings.budget_controls_enabled``) — deliberately no second flag, so one deployment
    setting describes one posture. Returns ``True`` when the caller must still refuse (today's
    behaviour, unchanged), and ``False`` after recording what would have been refused.
    """

    if enforce_policy:
        return True
    record_policy_refusal_skipped(site=site, reason=reason, detail=detail, sink=sink)
    return False


__all__ = [
    "EVENT_POLICY_REFUSAL_RECORD_ONLY",
    "EVENT_SPEND_CAP_RECORD_ONLY",
    "METRIC_POLICY_REFUSAL_RECORD_ONLY",
    "METRIC_SPEND_CAP_RECORD_ONLY",
    "cap_refusal_is_enforced",
    "policy_refusal_is_enforced",
    "record_cap_refusal_skipped",
    "record_policy_refusal_skipped",
]
