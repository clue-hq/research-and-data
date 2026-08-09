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

It is a pure read: it resolves each account's effective directive and *proves the human tier
checkpoint* before counting the account's cap, which is why it also serves as the gate's
precondition — a gate can only be presented for a set of accounts the launcher would actually
accept. Nothing here spends, enqueues, or writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EffectiveAccountResearchDirective,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchDirectiveId,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.directives import effective_account_research_directive

__all__ = [
    "TIER_CHECKPOINT_FIELD",
    "AccountResearchEstimate",
    "AccountTierCheckpointMissing",
    "compute_account_research_estimate",
]

#: The claim field carrying a human tier checkpoint's disposition for one account.
TIER_CHECKPOINT_FIELD = "account.scoring.tier"


class AccountTierCheckpointMissing(ValueError):
    """This account has no single, human-approved ``selected`` tier claim for this project run.

    Its own type so the gate tool can turn it into a typed precondition failure while the launcher
    keeps raising its own launch error — one rule, two idioms, no duplicated predicate.
    """

    def __init__(self, account_id: EntityId) -> None:
        super().__init__(f"account {account_id} lacks one exact human-approved selected tier")
        self.account_id = account_id


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
    """Σ per-account ``effort_policy.budget_cap_cents`` over a human-checkpointed account set.

    Each account must carry exactly one tier claim that is HUMAN-extracted, tier-1, names *this*
    project run, agrees with the account's effective tier, and reads ``disposition='selected'``.
    Anything else raises :class:`AccountTierCheckpointMissing` — "no checkpoint" and "two
    checkpoints" are equally disqualifying, because either means nobody deliberately approved
    exactly this account for exactly this run.

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
        matching_tiers = [
            claim
            for claim in await claims_for(
                conn,
                account_id,
                TIER_CHECKPOINT_FIELD,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            if isinstance(claim.value_json, dict)
            and claim.extraction_method is ExtractionMethod.HUMAN
            and claim.source_tier == 1
            and claim.value_json.get("project_run_id") == str(project_run_id)
            and claim.value_json.get("tier") == effective.effort_policy.tier
            and claim.value_json.get("disposition") == "selected"
        ]
        if len(matching_tiers) != 1:
            raise AccountTierCheckpointMissing(account_id)
        effective_by_account[account_id] = effective
        total += effective.effort_policy.budget_cap_cents
    return AccountResearchEstimate(
        effective_by_account=effective_by_account,
        total_cents=total,
    )
