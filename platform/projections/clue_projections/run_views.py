"""Run-level read projections (PB-B4 slice 3, D7) — overview, per-account progress, readiness.

Every function here is a **read** projection: it composes the existing M13.4 ``review``
:class:`~clue_research.review.ObservabilitySurface` panels (progress / burn-down / verification
health / coverage — reused, never re-derived) and the durable ``project_run`` / ``account_run``
read helpers, and it issues **no writes** (the D7 MVCC-only discipline — a projection read during a
driving worker never mutates the domain).

**Import posture (the projections contract).** ``clue_projections`` may import the ``clue_research``
*read surfaces* (``review`` / ``durable`` read helpers) + the shared base (``core``) — never
toolbelt / agents / fleet / api / memory / content / gateway / locks. The concrete durable-backed
readers (which reach ``claimstore`` + a ``BudgetEngine``) are built once at the ``clue_api``
composition root and *injected* here as an :class:`ObservabilitySurface`, so the projection logic
stays pure and the reader concretes are not duplicated (they are the M13.4 wiring, reused).

The HANDOFF **narrative-gap marker** is read straight from the HANDOFF checkpoint payload
(``narrative_emit_skipped``, written by the slice-1 composer's documented-gap handler), so
:func:`run_overview` makes a gap-completed run distinguishable from a truly-handed-off one — spec §2
slice-3 amendment / slice-1 review #10.
"""

from __future__ import annotations

from clue_core import EntityId, ProjectPhase, ProjectRunId
from clue_db import ConnFactory
from clue_projections.dtos import (
    AccountProgress,
    AccountReadiness,
    Readiness,
    RunOverview,
)
from clue_research.durable import (
    NARRATIVE_EMIT_SKIPPED_KEY,
    AccountRunRow,
    get_checkpoint,
    get_project_run,
    list_account_runs,
)
from clue_research.review import ObservabilitySurface


def _aspect_tally(row: AccountRunRow) -> tuple[int, int, tuple[str, ...]]:
    """(planned, filled, filled_aspect_names) for one account run — filled vs planned aspects from
    the M7.1 plan (``plan_json.aspects[*].aspect``) and the references index (an aspect with ≥1
    collected claim id is *filled*). A robust read: an unplanned/empty run tallies ``(0, 0, ())``.
    """
    plan = row.plan_json
    planned_names: set[str] = set()
    aspects = plan.get("aspects") if isinstance(plan, dict) else None
    if isinstance(aspects, list):
        for aspect in aspects:
            name = aspect.get("aspect") if isinstance(aspect, dict) else None
            if isinstance(name, str):
                planned_names.add(name)
    filled = tuple(sorted(name for name, ids in row.references_index.items() if ids))
    planned_names.update(filled)  # a filled aspect is, by definition, planned
    return len(planned_names), len(filled), filled


async def run_overview(
    *,
    surface: ObservabilitySurface,
    conn_factory: ConnFactory,
    project_run_id: ProjectRunId,
    workspace_id: str,
) -> RunOverview | None:
    """The run-overview projection, or ``None`` for a missing / cross-tenant run.

    Tenant scoping is inherited from the surface's ``campaign_progress`` (it returns ``None`` for a
    run that is not this workspace's), so the direct durable reads below only run for a confirmed
    owner. Reuses the M13.4 panels for progress/burn-down/health/coverage and reads the durable
    ``account_run`` rows for the accounts-by-state histogram + the HANDOFF gap marker."""
    progress = await surface.campaign_progress(
        project_run_id=project_run_id, workspace_id=workspace_id
    )
    if progress is None:
        return None
    burn_down = await surface.cost_burndown(
        project_run_id=project_run_id, workspace_id=workspace_id
    )
    health = await surface.verification_health(
        project_run_id=project_run_id, workspace_id=workspace_id
    )
    coverage = await surface.coverage_confidence(
        project_run_id=project_run_id, workspace_id=workspace_id
    )
    async with conn_factory() as conn:
        account_runs = await list_account_runs(conn, project_run_id)
        handoff_cp = await get_checkpoint(conn, project_run_id, ProjectPhase.HANDOFF)
    by_state: dict[str, int] = {}
    for row in account_runs:
        by_state[row.status.value] = by_state.get(row.status.value, 0) + 1
    handoff_payload = handoff_cp.payload if handoff_cp is not None else {}
    return RunOverview(
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        current_phase=progress.current_phase,
        run_status=progress.run_status,
        is_paused=progress.is_paused,
        is_terminal=progress.is_terminal,
        awaiting_input=progress.awaiting_input,
        phases=progress.phases,
        accounts_total=len(account_runs),
        accounts_by_state=by_state,
        burn_down=burn_down,
        verification_health=health,
        coverage=coverage,
        handoff_reached=handoff_cp is not None,
        narrative_emit_skipped=bool(handoff_payload.get(NARRATIVE_EMIT_SKIPPED_KEY, False)),
    )


async def account_progress(
    *,
    conn_factory: ConnFactory,
    project_run_id: ProjectRunId,
    workspace_id: str,
    account_entity_id: EntityId,
) -> AccountProgress | None:
    """Per-account progress within a run, or ``None`` for a missing/cross-tenant run or an account
    with no research run under it. Tenant-scoped on the run's ``workspace_id`` (fail-closed — a
    cross-tenant run resolves to ``None``, no existence leak)."""
    async with conn_factory() as conn:
        run = await get_project_run(conn, project_run_id)
        if run is None or run.workspace_id != workspace_id:
            return None
        account_runs = await list_account_runs(conn, project_run_id)
    match = next((r for r in account_runs if r.entity_id == account_entity_id), None)
    if match is None:
        return None
    planned, filled, filled_names = _aspect_tally(match)
    claim_count = sum(len(ids) for ids in match.references_index.values())
    return AccountProgress(
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        account_entity_id=account_entity_id,
        tier=match.tier,
        status=match.status.value,
        sub_phase=match.sub_phase.value if match.sub_phase is not None else None,
        cost_cents=str(match.cost_cents),
        aspects_planned=planned,
        aspects_filled=filled,
        claim_count=claim_count,
        filled_aspects=filled_names,
    )


async def run_readiness(
    *,
    surface: ObservabilitySurface,
    conn_factory: ConnFactory,
    project_run_id: ProjectRunId,
    workspace_id: str,
) -> Readiness | None:
    """The readiness/coverage projection, or ``None`` for a missing/cross-tenant run.

    Reuses the M6.5 coverage-confidence band (via the surface) and folds a filled-vs-planned aspect
    tally per account from the durable ``account_run`` rows. Tenant-scoped like
    :func:`run_overview` (the surface's coverage read returns ``None`` cross-tenant; the run
    ownership is re-checked before the durable account reads)."""
    async with conn_factory() as conn:
        run = await get_project_run(conn, project_run_id)
        if run is None or run.workspace_id != workspace_id:
            return None
        account_runs = await list_account_runs(conn, project_run_id)
    coverage = await surface.coverage_confidence(
        project_run_id=project_run_id, workspace_id=workspace_id
    )
    accounts: list[AccountReadiness] = []
    planned_total = 0
    filled_total = 0
    for row in account_runs:
        planned, filled, _ = _aspect_tally(row)
        planned_total += planned
        filled_total += filled
        accounts.append(
            AccountReadiness(
                account_entity_id=row.entity_id,
                tier=row.tier,
                status=row.status.value,
                aspects_planned=planned,
                aspects_filled=filled,
            )
        )
    return Readiness(
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        coverage=coverage,
        aspects_planned_total=planned_total,
        aspects_filled_total=filled_total,
        accounts=tuple(accounts),
    )
