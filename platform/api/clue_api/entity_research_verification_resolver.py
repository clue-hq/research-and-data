"""M8D R11.3 — the verification account selector, read off the M8D account-research fleet.

VERIFICATION and the HANDOFF retention sweep both need one thing from the phase before them: *which
accounts were actually researched*.  Until R11 they asked :func:`~clue_api.deep.composition.
build_high_tier_resolver`, which answers from the ``account_deep_launch`` ledger — a table whose
only production writer is the R1-quarantined ``launch_account_deep@1``.  On an M8D-researched
project run that read finds no row and the resolver returns ``()``, so the VERIFICATION phase
reports ``accounts_processed=0`` **as a success**.  That silent zero is the defect this closes.

The replacement reads the same thing the DEEP adapter does — the latest human-confirmed R6 fleet run
bound to the project run (R11 §6c) — and turns its **accepted terminal jobs** into the
``AccountSpec`` set:

* **Fail loud, never empty-success.** No fleet run for this project run (or one owned by another
  project) raises :class:`EntityResearchRunMissing`.  An empty result now means "the fleet
  researched nothing acceptable", never "nobody ever launched research" — those two are different
  facts and the phase must not conflate them.
* **Accepted outcomes only** (:data:`ACCEPTED_FINALIZATION_OUTCOMES`) — a ``completed`` or
  ``needs_review`` job reached a defensible picture of the account and its claims are durable and
  servable; ``exhausted`` / ``budget_stopped`` / ``cancelled`` / ``failed`` did not.  This mirrors
  Lane E's prose gate (``prose_synthesis_tools.SYNTHESIZABLE_OUTCOMES``) rather than inventing a
  second vocabulary.  Exclusions are censused (log + metric), never raised: a partially-cancelled
  fleet is a legitimate run whose accepted accounts still deserve verification.
* **No judge, no gateway, no toggle sensitivity.** The selector is a pure fleet read, so it behaves
  identically under ``CLUE_VERIFICATION_ENABLED`` true and false (R11 §1a) — the toggle bypasses
  *judging*, never the selector's honesty.

``build_high_tier_resolver`` is deliberately left in place (it is inventoried for the separately
triggered cleanup PR, CLAUDE.md ``[audit 2026-08-07]``); this module simply takes over its two
production consumers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import read_latest_account_fleet_for_project_run
from clue_api.deep.handler import HighTierResolver
from clue_core import EntityId, PhaseContext
from clue_core.entity_research import (
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchSubjectType,
)
from clue_db import ConnFactory, transaction
from clue_fleet.entity_research import DbEntityResearchJobStore, EntityResearchJobRow
from clue_obs import get_logger
from clue_obs.otel import MetricSink, get_metric_sink
from clue_research.durable import AccountSpec

__all__ = [
    "ACCEPTED_FINALIZATION_OUTCOMES",
    "ENTITY_RESEARCH_SELECTION_TIER",
    "METRIC_SELECTOR_EXCLUDED",
    "METRIC_SELECTOR_SELECTED",
    "EntityResearchRunMissing",
    "build_entity_research_account_resolver",
]

log = get_logger("clue_api.entity_research_verification_resolver")

#: The finalization outcomes whose accounts are handed to verification.  A ``completed`` job
#: resolved its admitted fields; a ``needs_review`` one reached an honest, reviewable picture — both
#: wrote durable, servable claims.  The other four terminal outcomes (``exhausted`` /
#: ``budget_stopped`` / ``cancelled`` / ``failed``) describe research that did not, so verifying
#: them would spend judge budget on a broken pass.  Same gate Lane E applies before prose.
ACCEPTED_FINALIZATION_OUTCOMES = frozenset(
    {ResearchFinalizationOutcome.COMPLETED, ResearchFinalizationOutcome.NEEDS_REVIEW}
)

#: ``AccountSpec.tier`` is required, but M8D has **no tier axis**: the exact human-confirmed fleet
#: selection *is* the research authorization, and depth lives in the per-job authorization (admitted
#: fields/questions) plus its immutable budget cap — there is no band to report.  Rather than invent
#: a band ("top") that no human ever approved, every M8D-selected account carries this constant,
#: which names the provenance of the selection.  Nothing downstream reads it: both consumers
#: (:class:`~clue_api.verification.VerificationPhaseHandler` and the HANDOFF
#: :class:`~clue_api.handoff_retention.RetentionSweepHandoffHandler`) use only ``entity_id``.
ENTITY_RESEARCH_SELECTION_TIER = "entity_research_selection"

#: One per resolved account handed to verification, attributed by accepted outcome.
METRIC_SELECTOR_SELECTED = "research.verification.selector.selected_accounts"
#: One per fleet job the selector left out, attributed by the outcome (or live job state) that
#: excluded it — so a run verified on 3 of 5 accounts is legible without reading the fleet tables.
METRIC_SELECTOR_EXCLUDED = "research.verification.selector.excluded_accounts"


class EntityResearchRunMissing(RuntimeError):
    """VERIFICATION (or the HANDOFF sweep) was driven for a project run that has **no** M8D
    account-research fleet run.

    Raised instead of returning an empty account set, because the two are different facts and only
    one of them is safe to report as a clean phase: "the fleet accepted no account" is a result,
    "research was never launched" is a missing precondition.  The pre-R11 resolver could not tell
    them apart and silently reported ``accounts_processed=0`` as a SUCCESS on every M8D-researched
    run.  The fix is an operator-actionable failure naming the run and the launch tool that clears
    it (the confirmed ``launch_account_research@1``)."""


@asynccontextmanager
async def _borrowed(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    """Let the R2 job store read inside the connection this resolver already holds, so the fleet row
    and its jobs are read from one consistent snapshot."""

    yield conn


def _exclusion_reason(job: EntityResearchJobRow) -> str:
    """Why this job is not in the verification set — its refused finalization outcome, or (for a job
    the fleet is still working) its live state.  The two vocabularies are disjoint, so one census
    key space carries both."""

    if job.state is not ResearchJobState.TERMINAL or job.finalization_outcome is None:
        return str(job.state.value)
    return str(job.finalization_outcome.value)


def build_entity_research_account_resolver(
    *,
    session_factory: ConnFactory = transaction,
    sink: MetricSink | None = None,
) -> HighTierResolver:
    """The :data:`~clue_api.deep.handler.HighTierResolver` that resolves a project run's researched
    accounts from its M8D account-research fleet run (R11.3).

    Raises :class:`EntityResearchRunMissing` when the run has no fleet run — in **both**
    verification-toggle states (R11 §1a).  Otherwise yields one ``AccountSpec`` per terminal job
    with an accepted finalization outcome, ordered by entity id so two calls (and the two consumers
    that share this instance) always see the same set in the same order.
    """

    async def _resolve(ctx: PhaseContext) -> Sequence[AccountSpec]:
        project_run_id = UUID(str(ctx.project_run_id))
        async with session_factory() as conn:
            fleet = await read_latest_account_fleet_for_project_run(
                conn, project_run_id, workspace_id=ctx.workspace_id
            )
            if fleet is None or fleet.project_id != ctx.project_id:
                # A row owned by another project is as absent as no row at all for this run, and
                # both are the same missing precondition: nobody launched research *here*.
                raise EntityResearchRunMissing(
                    f"project run {ctx.project_run_id} has no M8D account-research fleet run, so "
                    "there is no researched account set to verify. Launch account research through "
                    "the confirmed launch_account_research@1 action (its human-confirmed selection "
                    "is the research authorization), then re-drive this phase."
                )
            jobs = await DbEntityResearchJobStore(conn_factory=lambda: _borrowed(conn)).list_jobs(
                fleet.research_run_id
            )

        # Job scope equals run scope by construction (the R2 authorization refuses a job whose
        # workspace/project/product/run differs from its exact selection), and R6 refuses to launch
        # a non-account subject, so the workspace guard on the fleet row above covers every job.
        specs: list[AccountSpec] = []
        selected_census: dict[str, int] = {}
        excluded_census: dict[str, int] = {}
        for job in sorted(jobs, key=lambda item: str(item.subject_entity_id)):
            accepted = (
                job.subject_type is ResearchSubjectType.ACCOUNT
                and job.state is ResearchJobState.TERMINAL
                and job.finalization_outcome in ACCEPTED_FINALIZATION_OUTCOMES
            )
            if not accepted:
                reason = _exclusion_reason(job)
                excluded_census[reason] = excluded_census.get(reason, 0) + 1
                continue
            assert job.finalization_outcome is not None
            outcome = job.finalization_outcome.value
            selected_census[outcome] = selected_census.get(outcome, 0) + 1
            specs.append(
                AccountSpec(
                    entity_id=EntityId(job.subject_entity_id),
                    tier=ENTITY_RESEARCH_SELECTION_TIER,
                    workspace_id=ctx.workspace_id,
                    # The exact admitted field authority the human confirmed for this job.
                    field_keys=job.authorization.effective_admitted_field_keys,
                    # The job's own immutable cap, not the run-wide envelope: it is the per-account
                    # authority the launch handed out.
                    budget_cap_cents=job.budget_cap_cents,
                    # An M8D account job authorizes no contact axis at all (an account selection
                    # cannot carry contact channels, and contact research needs its own
                    # approve_contact_research_selection@2 → launch_contact_research@1 pair), so the
                    # model's permissive legacy default would be a false authorization here.
                    contact_profiling_allowed=False,
                    # ``research_directive`` stays the model default (None): the M8D selection pins
                    # its directive by ref+sha (``selection.directive_ref``), never as the legacy
                    # per-account ``ResearchDirectivePin`` this field holds.
                )
            )

        emit = sink or get_metric_sink()
        attributes = {"workspace_id": ctx.workspace_id}
        for outcome, count in selected_census.items():
            emit.add(METRIC_SELECTOR_SELECTED, count, {**attributes, "outcome": outcome})
        for reason, count in excluded_census.items():
            emit.add(METRIC_SELECTOR_EXCLUDED, count, {**attributes, "reason": reason})
        log.info(
            "verification_selector.fleet_selection",
            project_run_id=str(ctx.project_run_id),
            research_run_id=str(fleet.research_run_id),
            selected_accounts=len(specs),
            selected=dict(sorted(selected_census.items())),
            excluded=dict(sorted(excluded_census.items())),
        )
        return tuple(specs)

    return _resolve
