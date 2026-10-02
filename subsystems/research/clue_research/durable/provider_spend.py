"""Shared project-run guard for durable, potentially-paid provider operations.

Provider ledgers own request fingerprints, provider units, and terminal receipts.  This module owns
the one cross-provider invariant they cannot enforce independently: while a project run is active
in an allowed phase -- or one exact human-authorized entity-research job is running through the
legacy tier checkpoint -- its already-recorded spend plus every outstanding provider reservation
plus the proposed reservation must fit under the run's hard cap.

The project-run row is locked before the outstanding totals are read.  All callers reserve their
operation in the same transaction, so concurrent Exa discovery and targeted-enrichment attempts
cannot both observe the same remaining capacity.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import CostCents, ProjectPhase, ProjectRunId
from clue_research.durable.enums import ProjectRunStatus
from clue_research.durable.spend_posture import cap_refusal_is_enforced

#: Attribution for the record-only spend-cap posture (founder ruling 2026-08-20).
_SITE_PROJECT_RUN_SPEND: Final = "project_run_provider_spend"


class ProviderSpendGuardError(RuntimeError):
    """Base error for a rejected shared provider-spend reservation."""


class ProviderSpendRunNotFound(ProviderSpendGuardError):
    """The reservation referenced no durable project run."""


class ProviderSpendRunIneligible(ProviderSpendGuardError):
    """The project run is paused/terminal or is outside the operation's allowed phase."""


class ProviderSpendBudgetExceeded(ProviderSpendGuardError):
    """The proposed reservation would exceed the project-run hard cap."""


class ProviderSpendCapacity(BaseModel):
    """The locked run state used to authorize one new provider reservation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    phase: ProjectPhase
    status: ProjectRunStatus
    cap_cents: CostCents | None
    spent_cents: CostCents
    outstanding_cents: CostCents
    proposed_cents: CostCents


_OUTSTANDING_SQL = text(
    """
    SELECT COALESCE(sum(reserved), 0) AS outstanding
    FROM (
        SELECT operation.cost_cents_reserved AS reserved
        FROM discovery_operation operation
        JOIN discovery_batch batch
          ON batch.id = operation.batch_id
         AND batch.workspace_id = operation.workspace_id
        WHERE batch.project_run_id = :project_run_id
          AND operation.state NOT IN (
              'succeeded', 'accepted_terminal_failure', 'failed_terminal', 'cancelled'
          )
        UNION ALL
        SELECT operation.cost_cents_reserved AS reserved
        FROM targeted_enrichment_operation operation
        WHERE operation.project_run_id = :project_run_id
          AND operation.state NOT IN ('succeeded', 'failed_terminal', 'cancelled')
        UNION ALL
        SELECT operation.cost_cents_reserved AS reserved
        FROM account_gap_operation operation
        WHERE operation.project_run_id = :project_run_id
          AND operation.state NOT IN (
              'succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'
          )
        UNION ALL
        SELECT operation.cost_cents_reserved AS reserved
        FROM discovery_gap_operation operation
        WHERE operation.project_run_id = :project_run_id
          AND operation.state NOT IN (
              'succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'
          )
        UNION ALL
        SELECT operation.cost_cents_reserved AS reserved
        FROM committee_acquisition_operation operation
        WHERE operation.project_run_id = :project_run_id
          AND operation.state NOT IN (
              'ready', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'
          )
        UNION ALL
        SELECT operation.cost_cents_reserved AS reserved
        FROM external_research_operation operation
        WHERE operation.project_run_id = :project_run_id
          AND operation.state NOT IN ('ready', 'failed_terminal', 'cancelled')
          AND NOT (
              operation.state = 'spend_outcome_unknown'
              AND EXISTS (
                  SELECT 1 FROM external_research_cost_reconciliation reconciliation
                  WHERE reconciliation.operation_id = operation.id
              )
          )
        UNION ALL
        SELECT
            CASE
                WHEN operation.acquisition_spend_outcome IN ('charged', 'not_charged') THEN 0
                ELSE (operation.request_json->>'acquisition_budget_cap_cents')::numeric
            END
            + CASE
                WHEN operation.validation_spend_outcome IN ('charged', 'not_charged') THEN 0
                ELSE (operation.request_json->>'validation_budget_cap_cents')::numeric
            END AS reserved
        FROM contact_channel_operation operation
        WHERE operation.project_run_id = :project_run_id
          AND operation.state NOT IN ('succeeded', 'rejected', 'failed_terminal', 'cancelled')
    ) reservations
    """
)


async def require_provider_spend_capacity(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    proposed_cents: CostCents,
    allowed_phases: frozenset[ProjectPhase],
    entity_research_job_id: UUID | None = None,
    enforce_budget: bool = True,
) -> ProviderSpendCapacity:
    """Lock a run and authorize one new reservation against all provider ledgers.

    The caller must insert its ledger row before committing this transaction.  Replays must be
    detected before calling this function (and rechecked after the lock) because an existing
    operation consumes no new capacity.

    ``enforce_budget`` is the FI pilot budget-controls switch
    (``Settings.budget_controls_enabled``), threaded from the api composition roots through each
    reserving service — never read here, so this function stays a pure durable primitive. With it
    False the *money* comparison at the end no longer raises
    :class:`ProviderSpendBudgetExceeded`; **everything else is unchanged**, which is the whole
    point. The run is still locked, the run must still be ACTIVE unless an exact entity-research
    job is running while its outer run is paused at the legacy tier checkpoint, the phase/job
    authority is still proved, the outstanding total is still computed, and the returned
    :class:`ProviderSpendCapacity` still reports the true cap, spend and outstanding — so the
    caller writes exactly the ledger row it always wrote and a pilot deployment's spend is recorded
    honestly while simply exceeding its cap.
    """

    if proposed_cents < 0:
        raise ValueError("provider spend reservation must be non-negative")
    row = (
        (
            await conn.execute(
                text(
                    "SELECT id, phase::text, status::text, budget_cap_cents, spent_cents "
                    "FROM project_run WHERE id=:project_run_id FOR UPDATE"
                ),
                {"project_run_id": project_run_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProviderSpendRunNotFound(f"project run {project_run_id}")
    phase = ProjectPhase(str(row["phase"]))
    status = ProjectRunStatus(str(row["status"]))
    if entity_research_job_id is not None:
        job = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT job.state::text AS job_state, run.state::text AS run_state,
                               job.workspace_id, job.project_run_id,
                               EXISTS (
                                   SELECT 1 FROM entity_research_account_fleet_job_control control
                                   WHERE control.job_id=job.job_id
                                     AND control.research_run_id=job.research_run_id
                                     AND control.admission_state IN ('admitted', 'released')
                               ) AS account_authorized,
                               EXISTS (
                                   SELECT 1 FROM entity_research_contact_job_authority authority
                                   WHERE authority.job_id=job.job_id
                                     AND authority.research_run_id=job.research_run_id
                                     AND authority.workspace_id=job.workspace_id
                               ) AS contact_authorized
                        FROM entity_research_job job
                        JOIN entity_research_run run USING (research_run_id)
                        WHERE job.job_id=:job_id
                          AND job.project_run_id=:project_run_id
                          AND run.project_run_id=:project_run_id
                        FOR SHARE OF job, run
                        """
                    ),
                    {
                        "job_id": entity_research_job_id,
                        "project_run_id": project_run_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            job is None
            or str(job["job_state"]) != "running"
            or str(job["run_state"]) != "running"
            or bool(job["account_authorized"]) == bool(job["contact_authorized"])
        ):
            raise ProviderSpendRunIneligible(
                "provider reservation lacks one exact live entity-research job authority"
            )
        # The explicitly launched entity job is the human authority for its selected subject.
        # Permit that exact job while the outer discovery state machine is paused only at its
        # legacy tier checkpoint; manual pauses elsewhere and every terminal status remain hard
        # stops. This lets low/no-tier selected accounts run without weakening unrelated runs.
        if status is not ProjectRunStatus.ACTIVE and not (
            status is ProjectRunStatus.PAUSED and phase is ProjectPhase.TIER_CHECKPOINT
        ):
            raise ProviderSpendRunIneligible(
                f"project run {project_run_id} is {status.value}, not active"
            )
    elif status is not ProjectRunStatus.ACTIVE:
        raise ProviderSpendRunIneligible(
            f"project run {project_run_id} is {status.value}, not active"
        )
    elif phase not in allowed_phases:
        allowed = ", ".join(sorted(value.value for value in allowed_phases))
        raise ProviderSpendRunIneligible(
            f"project run {project_run_id} is in {phase.value}; allowed phase(s): {allowed}"
        )
    spent = Decimal(row["spent_cents"])
    cap = Decimal(row["budget_cap_cents"]) if row["budget_cap_cents"] is not None else None
    outstanding = Decimal(
        (await conn.execute(_OUTSTANDING_SQL, {"project_run_id": project_run_id})).scalar_one()
    )
    # Already record-only when controls are off (the FI pilot ruling, 2026-08-11); the 2026-08-20
    # cap ruling only adds the announcement, so a skipped project-run stop is as visible as the
    # per-provider ones it sits above.
    if (
        cap is not None
        and spent + outstanding + proposed_cents > cap
        and cap_refusal_is_enforced(
            enforce_budget,
            site=_SITE_PROJECT_RUN_SPEND,
            reason="project_run_cap_exceeded",
            amounts={
                "spent_cents": spent,
                "outstanding_cents": outstanding,
                "proposed_cents": proposed_cents,
                "budget_cap_cents": cap,
            },
        )
    ):
        raise ProviderSpendBudgetExceeded(
            "provider reservation exceeds project-run cap: "
            f"spent={spent}, outstanding={outstanding}, proposed={proposed_cents}, cap={cap}"
        )
    return ProviderSpendCapacity(
        project_run_id=project_run_id,
        phase=phase,
        status=status,
        cap_cents=cap,
        spent_cents=spent,
        outstanding_cents=outstanding,
        proposed_cents=proposed_cents,
    )


__all__ = [
    "ProviderSpendBudgetExceeded",
    "ProviderSpendCapacity",
    "ProviderSpendGuardError",
    "ProviderSpendRunIneligible",
    "ProviderSpendRunNotFound",
    "require_provider_spend_capacity",
]
