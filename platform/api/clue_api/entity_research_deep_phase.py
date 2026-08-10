"""M8D R11.1 — the join-only DEEP phase adapter over the R6 account-research fleet.

The project-run DEEP slot used to hold the R1 quarantine handler, which raised unconditionally, so
no composed run could reach VERIFICATION or HANDOFF.  Meanwhile the M8D account-research fleet ran
entirely off the phase machine, launched from chat by the human-confirmed
``launch_account_research@1``.

This handler is the bridge, and it is deliberately a **join**, never a driver:

* it never launches a fleet run — launch authority stays with the confirmed launch tool, because an
  adapter-initiated launch would recreate exactly the automatic progression M8D retired;
* it owns no spend, so it re-checks no budget: the fleet's cap was enforced once at admission and
  R11 §6d ratifies that the settled fleet spend is merely *reported* into the M7.4 phase ledger for
  attribution; and
* it takes no gateway/judge dependency, so it composes and behaves identically under
  ``CLUE_VERIFICATION_ENABLED`` true and false (R11 §1a).

Every ``run`` is a pure read of the latest fleet run bound to the project run (R11 §6c), mapped to
one phase result:

===========================================  ===================  ==============================
Fleet state                                  PhaseResult          Semantics
===========================================  ===================  ==============================
no fleet run                                 ``PAUSED``           durable human hold: launch, resume
``canary`` / ``open`` / ``waiting_external``  ``WAITING_EXTERNAL``  non-human wait; run stays ACTIVE
``suspended``                                ``PAUSED``           honest human decision point
``terminal``                                 ``COMPLETED``        advance to VERIFICATION
===========================================  ===================  ==============================

Both ``PAUSED`` results are *plain* holds, not decision gates: they carry
:data:`~clue_research.durable.REENTRANT_HOLD_KEY` so an explicit ``resume`` re-runs this handler
against current fleet state (R11 §6b).  Without it the state machine's ``AWAITING_INPUT``
checkpoint could only be cleared by approving it, which would finalize DEEP having researched
nothing.

Because the read is pure, re-entry after a crash (the phase machine stages ``IN_PROGRESS`` before
invoking, so a not-yet-committed phase re-runs) simply re-evaluates fleet state — double entry is
harmless by construction and the adapter writes no ledger rows of its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import (
    AccountResearchFleetRow,
    AccountResearchFleetState,
    read_latest_account_fleet_for_project_run,
)
from clue_core import (
    DeepFleetExternalWait,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
)
from clue_core.entity_research import ResearchJobState
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_research.durable import REENTRANT_HOLD_KEY

__all__ = [
    "DEEP_FLEET_POLL_INTERVAL",
    "REASON_FLEET_NOT_LAUNCHED",
    "REASON_FLEET_SUSPENDED",
    "REASON_FLEET_TERMINAL",
    "EntityResearchDeepPhaseHandler",
]

log = get_logger("clue_api.entity_research_deep_phase")

#: Scheduled-poll fallback while the fleet works.  The R11.2 fleet-terminal wake source is the fast
#: path; this is the same belt-and-braces discipline the discovery wait uses.
DEEP_FLEET_POLL_INTERVAL = timedelta(seconds=60)

REASON_FLEET_NOT_LAUNCHED = "entity_research_fleet_not_launched"
REASON_FLEET_SUSPENDED = "entity_research_fleet_suspended"
REASON_FLEET_TERMINAL = "entity_research_fleet_terminal"

_NONTERMINAL_FLEET_STATES = frozenset(
    {
        AccountResearchFleetState.CANARY,
        AccountResearchFleetState.OPEN,
        AccountResearchFleetState.WAITING_EXTERNAL,
    }
)


async def _job_state_counts(conn: AsyncConnection, research_run_id: UUID) -> dict[str, int]:
    """The live census of the fleet run's jobs, keyed by ``ResearchJobState`` value."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT state, count(*) AS jobs FROM entity_research_job "
                    "WHERE research_run_id=:run_id GROUP BY state"
                ),
                {"run_id": research_run_id},
            )
        )
        .mappings()
        .all()
    )
    return {str(row["state"]): int(row["jobs"]) for row in rows}


async def _finalization_outcome_counts(
    conn: AsyncConnection, research_run_id: UUID
) -> dict[str, int]:
    """Terminal jobs grouped by accepted finalization outcome (``completed``/``needs_review``/…)."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT finalization_outcome, count(*) AS jobs FROM entity_research_job "
                    "WHERE research_run_id=:run_id AND state=:terminal "
                    "GROUP BY finalization_outcome"
                ),
                {"run_id": research_run_id, "terminal": ResearchJobState.TERMINAL.value},
            )
        )
        .mappings()
        .all()
    )
    return {str(row["finalization_outcome"]): int(row["jobs"]) for row in rows}


class EntityResearchDeepPhaseHandler:
    """Join the project run's DEEP phase to its latest M8D account-research fleet run."""

    phase = ProjectPhase.DEEP

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        async with self._conn_factory() as conn:
            fleet = await self._current_fleet(conn, ctx)
            if fleet is None:
                return self._not_launched(ctx)
            if fleet.state in _NONTERMINAL_FLEET_STATES:
                return await self._waiting(conn, fleet)
            if fleet.state is AccountResearchFleetState.SUSPENDED:
                return self._suspended(fleet)
            return await self._terminal(conn, fleet)

    async def _current_fleet(
        self, conn: AsyncConnection, ctx: PhaseContext
    ) -> AccountResearchFleetRow | None:
        fleet = await read_latest_account_fleet_for_project_run(
            conn, UUID(str(ctx.project_run_id)), workspace_id=ctx.workspace_id
        )
        if fleet is None:
            return None
        if fleet.workspace_id != ctx.workspace_id or fleet.project_id != ctx.project_id:
            # Fail closed rather than research a run's DEEP phase against another tenant's or
            # project's fleet.  Not an exception: an out-of-scope row is indistinguishable from no
            # row for this run, and the durable hold below is the honest outcome either way.
            log.warning(
                "deep_bridge.fleet_out_of_scope",
                project_run_id=str(ctx.project_run_id),
                research_run_id=str(fleet.research_run_id),
                expected_workspace_id=ctx.workspace_id,
                fleet_workspace_id=fleet.workspace_id,
                expected_project_id=ctx.project_id,
                fleet_project_id=fleet.project_id,
            )
            return None
        return fleet

    def _not_launched(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(
            status=PhaseStatus.PAUSED,
            payload={
                # A plain hold, not a decision gate (R11 §6b): there is nothing for the operator to
                # submit — they launch account research and resume, and this handler re-reads.
                REENTRANT_HOLD_KEY: True,
                "reason_code": REASON_FLEET_NOT_LAUNCHED,
                "project_run_id": str(ctx.project_run_id),
                "resume_action": "launch_account_research@1",
                "detail": (
                    "no M8D account-research fleet run is bound to this project run; launch "
                    "account research through the confirmed launch_account_research@1 action, "
                    "then resume the project run"
                ),
            },
        )

    async def _waiting(self, conn: AsyncConnection, fleet: AccountResearchFleetRow) -> PhaseResult:
        # A fleet run always carries at least one job (the R2 launch envelope requires a non-empty
        # exact job set), so the census is never empty while the run is nonterminal.
        wait = DeepFleetExternalWait(
            research_run_id=fleet.research_run_id,
            job_state_counts=await _job_state_counts(conn, fleet.research_run_id),
            next_poll_at=datetime.now(UTC) + DEEP_FLEET_POLL_INTERVAL,
        )
        return PhaseResult(
            status=PhaseStatus.WAITING_EXTERNAL, payload=wait.model_dump(mode="json")
        )

    def _suspended(self, fleet: AccountResearchFleetRow) -> PhaseResult:
        # Never FAILED: the R6 supervisor suspends on a canary block, a review-fraction breach or a
        # worker error, all of which are honest human decision points with a durable diagnosis.
        payload: dict[str, JsonValue] = {
            # Same plain-hold shape: the operator resumes the fleet, then resumes the run, and this
            # handler re-reads the fleet's state rather than being approved past it.
            REENTRANT_HOLD_KEY: True,
            "reason_code": REASON_FLEET_SUSPENDED,
            "research_run_id": str(fleet.research_run_id),
            "diagnosis": dict(fleet.diagnosis),
            "suspended_at": None if fleet.suspended_at is None else fleet.suspended_at.isoformat(),
        }
        return PhaseResult(status=PhaseStatus.PAUSED, payload=payload)

    async def _terminal(self, conn: AsyncConnection, fleet: AccountResearchFleetRow) -> PhaseResult:
        run = (
            (
                await conn.execute(
                    text(
                        "SELECT selection_id, spent_cents FROM entity_research_run "
                        "WHERE research_run_id=:run_id"
                    ),
                    {"run_id": fleet.research_run_id},
                )
            )
            .mappings()
            .one()
        )
        outcomes = await _finalization_outcome_counts(conn, fleet.research_run_id)
        payload: dict[str, JsonValue] = {
            "reason_code": REASON_FLEET_TERMINAL,
            "research_run_id": str(fleet.research_run_id),
            "selection_id": str(run["selection_id"]),
            "finalization_outcome_counts": dict(outcomes),
        }
        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=sum(outcomes.values()),
            # R11 §6d: the fleet's settled spend is *reported* into the M7.4 phase ledger for
            # attribution.  Enforcement happened once, at fleet admission; nothing here re-gates it.
            cost_cents=Decimal(run["spent_cents"]),
            payload=payload,
        )
