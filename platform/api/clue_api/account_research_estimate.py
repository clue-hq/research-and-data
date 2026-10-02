"""The one computation of an account-research launch's maximum spend (FI Lane D D4, §3-P5(b)).

Ratified **§6-D5** deferred the estimate *tool* and put a single server-derived maximum-spend
amount on the confirmation gate instead: the backend computes it when it presents the gate, stores
it immutably on the gate row, and the launcher re-verifies it at launch through
``expected_estimated_cost_cents``. That contract is only worth anything if both sides compute the
**same number the same way** — two implementations of "Σ per-account ``effort_policy
.budget_cap_cents``" would eventually disagree, and the disagreement would surface as a launch that
refuses the amount the user approved.

So the loop lives here, once, and both callers use it:

* :class:`~clue_api.account_research_fleet_launch.AccountResearchFleetLauncher` calls it and then
  applies its own exact-match verification to the result (that verification is unchanged and stays
  the launcher's);
* :class:`~clue_api.agent_gate_tools.OpenDirectiveConfirmationGateTool` calls it to derive the
  number it writes onto the immutable gate.

It is a pure read: it resolves each account's effective directive and counts the account's cap.
Account signal tiers are advisory prioritization metadata, not launch authority; the exact Account
set is authorized independently by the attributable user turn and confirmed directive. Nothing
here spends, enqueues, or writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EffectiveAccountResearchDirective,
    EntityId,
    ProjectRunId,
    ResearchDirectiveId,
)
from clue_research.directives import effective_account_research_directive

__all__ = [
    "AccountResearchEstimate",
    "compute_account_research_estimate",
]


@dataclass(frozen=True, slots=True)
class AccountResearchEstimate:
    """The per-account effective directives and the Σ of their budget caps."""

    #: Insertion-ordered by the account set the caller supplied — callers depend on that order for
    #: their own request digests, so it is part of the contract, not an accident of ``dict``.
    effective_by_account: dict[EntityId, EffectiveAccountResearchDirective]
    total_cents: Decimal


async def compute_account_research_estimate(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    directive_id: ResearchDirectiveId,
    account_ids: tuple[EntityId, ...],
    allow_draft: bool = False,
) -> AccountResearchEstimate:
    """Σ per-account ``effort_policy.budget_cap_cents`` over the explicitly selected Account set.

    Signal tiers (for example ``high`` / ``low``) and directive effort tiers (for example
    ``standard``) are intentionally independent vocabularies. A signal tier may influence queue
    priority or a suggested effort policy, but no signal value — including an absent value — makes
    an explicitly selected Account ineligible for research.

    ``allow_draft`` is what lets the *gate* run this: it prices the draft it is about to present,
    which by definition is not confirmed yet. The launcher leaves it ``False``, so nothing about
    "only a confirmed directive executes" is relaxed — only "a question may be priced".
    """

    effective_by_account: dict[EntityId, EffectiveAccountResearchDirective] = {}
    total = Decimal(0)
    for account_id in account_ids:
        effective = await effective_account_research_directive(
            conn,
            workspace_id=workspace_id,
            directive_id=directive_id,
            account_id=account_id,
            allow_draft=allow_draft,
        )
        effective_by_account[account_id] = effective
        total += effective.effort_policy.budget_cap_cents
    return AccountResearchEstimate(
        effective_by_account=effective_by_account,
        total_cents=total,
    )
