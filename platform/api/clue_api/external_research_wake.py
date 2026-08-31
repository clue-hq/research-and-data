"""Provider-neutral due-operation dispatcher for the existing detached fleet (M8C C6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import AccountResearchFleetState
from clue_core import ProjectPhase, ProjectRunId
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    PhaseCheckpointStatus,
    ProjectRunStatus,
    list_due_committee_acquisition_project_runs,
    list_due_contact_channel_project_runs,
    list_due_contact_external_research_project_runs,
)

ProjectRunWaker = Callable[[ProjectRunId], Awaitable[bool]]
ExternalResearchWakeSource = Callable[
    [AsyncConnection, datetime, int], Awaitable[Sequence[ProjectRunId]]
]
EntityResearchMemberWaker = Callable[[str], Awaitable[int]]
EntityResearchWaitSource = Callable[[AsyncConnection, datetime, int], Awaitable[Sequence[str]]]


async def _committee_due(
    conn: AsyncConnection, now: datetime, limit: int
) -> Sequence[ProjectRunId]:
    return await list_due_committee_acquisition_project_runs(conn, now=now, limit=limit)


async def _contact_external_due(
    conn: AsyncConnection, now: datetime, limit: int
) -> Sequence[ProjectRunId]:
    return await list_due_contact_external_research_project_runs(conn, now=now, limit=limit)


async def _channel_due(conn: AsyncConnection, now: datetime, limit: int) -> Sequence[ProjectRunId]:
    return await list_due_contact_channel_project_runs(conn, now=now, limit=limit)


# R11.2 — the fleet-terminal wake source.
#
# A project run parked at a DEEP ``WAITING_EXTERNAL`` checkpoint is only re-entered by a wake (the
# state machine's advance falls through ``WAITING_EXTERNAL`` and re-runs the handler), so without
# this query a run whose fleet has finished waits until something else happens to drive it.  Two
# ways to become due, ORed so a run is listed exactly once when both hit:
#
# * fast path — the bound fleet run (the checkpoint payload's ``research_run_id``) reached
#   ``terminal`` or ``suspended``; wake regardless of ``next_poll_at``; and
# * scheduled-poll fallback — the payload's ``next_poll_at`` has passed, so the handler re-reads
#   fleet state and re-emits a fresh wait (the same belt-and-braces discipline as discovery).
#
# The fleet join repeats the R11.1 adapter's scoping guard (same workspace *and* project) so this
# source never wakes a run on the strength of another tenant's or project's fleet row — such a row
# reads as absent here exactly as it does in the handler.  Only fleet-shaped payloads are
# considered (``research_run_id`` present): a legacy ``DeepExternalWait`` checkpoint belongs to the
# retired M8C operations this bridge replaced and was never woken by this dispatcher.
#
# The run must also still be ACTIVE at DEEP: ``advance`` is a no-op on a paused or terminal run, so
# offering one would re-queue the same drive on every scan forever without ever clearing the wait.
_DEEP_FLEET_DUE_SQL = text(
    """
    WITH deep_wait AS (
        SELECT checkpoint.project_run_id AS project_run_id,
               CAST(checkpoint.payload_json->>'next_poll_at' AS timestamptz) AS next_poll_at,
               (fleet.state IN (:terminal_state, :suspended_state)) IS TRUE AS fleet_settled
        FROM project_phase_checkpoint AS checkpoint
        JOIN project_run AS run ON run.id = checkpoint.project_run_id
        LEFT JOIN entity_research_account_fleet AS fleet
               ON fleet.research_run_id
                    = CAST(checkpoint.payload_json->>'research_run_id' AS uuid)
              AND fleet.workspace_id = run.workspace_id
              AND fleet.project_id = run.project_id
        WHERE checkpoint.phase = CAST(:deep AS project_phase)
          AND checkpoint.status = CAST(:waiting AS phase_checkpoint_status)
          AND checkpoint.payload_json->>'research_run_id' IS NOT NULL
          AND run.phase = CAST(:deep AS project_phase)
          AND run.status = CAST(:active AS project_run_status)
    )
    SELECT project_run_id
    FROM deep_wait
    WHERE fleet_settled OR next_poll_at <= :now
    ORDER BY fleet_settled DESC, next_poll_at, project_run_id
    LIMIT :limit
    """
)


async def _deep_fleet_due(
    conn: AsyncConnection, now: datetime, limit: int
) -> Sequence[ProjectRunId]:
    """Project runs parked at a DEEP fleet wait whose bound fleet settled, or whose poll is due.

    A settled fleet sorts first: that run can actually leave DEEP, whereas a scheduled poll only
    re-emits the same wait, so the batch limit is spent on progress before housekeeping.
    """

    rows = (
        await conn.execute(
            _DEEP_FLEET_DUE_SQL,
            {
                # ``terminal`` completes the phase and ``suspended`` turns it into an honest human
                # hold; either way the handler must re-read now, not at the next scheduled poll.
                "terminal_state": AccountResearchFleetState.TERMINAL.value,
                "suspended_state": AccountResearchFleetState.SUSPENDED.value,
                "deep": ProjectPhase.DEEP.value,
                "waiting": PhaseCheckpointStatus.WAITING_EXTERNAL.value,
                "active": ProjectRunStatus.ACTIVE.value,
                "now": now,
                "limit": limit,
            },
        )
    ).all()
    return tuple(ProjectRunId(row.project_run_id) for row in rows)


async def _committee_waits_due(conn: AsyncConnection, now: datetime, limit: int) -> Sequence[str]:
    rows = (
        await conn.execute(
            text(
                "SELECT 'committee-operation:' || id::text AS wait_ref "
                "FROM committee_acquisition_operation WHERE state='waiting_external' "
                "AND next_poll_at IS NOT NULL AND next_poll_at <= :now "
                "ORDER BY next_poll_at, id LIMIT :limit"
            ),
            {"now": now, "limit": limit},
        )
    ).scalars()
    return tuple(str(value) for value in rows)


async def _contact_external_waits_due(
    conn: AsyncConnection, now: datetime, limit: int
) -> Sequence[str]:
    rows = (
        await conn.execute(
            text(
                "SELECT 'external-research-operation:' || id::text AS wait_ref "
                "FROM external_research_operation WHERE subject_kind='contact' "
                "AND state='dispatching' AND dispatch_lease_expires_at <= :now "
                "ORDER BY dispatch_lease_expires_at, id LIMIT :limit"
            ),
            {"now": now, "limit": limit},
        )
    ).scalars()
    return tuple(str(value) for value in rows)


async def _channel_waits_due(conn: AsyncConnection, now: datetime, limit: int) -> Sequence[str]:
    rows = (
        await conn.execute(
            text(
                "SELECT CASE WHEN state IN ('ready_to_validate', 'validating') "
                "THEN 'contact-channel-validation:' ELSE 'contact-channel-acquisition:' END "
                "|| id::text AS wait_ref FROM contact_channel_operation "
                "WHERE next_poll_at IS NOT NULL AND next_poll_at <= :now AND state IN "
                "('waiting_external', 'ready_to_validate', 'validating', 'failed_retryable') "
                "ORDER BY next_poll_at, id LIMIT :limit"
            ),
            {"now": now, "limit": limit},
        )
    ).scalars()
    return tuple(str(value) for value in rows)


def registered_external_research_wake_sources(
    *,
    committee_enabled: bool,
    contact_external_enabled: bool,
    contact_channel_enabled: bool,
) -> tuple[ExternalResearchWakeSource, ...]:
    """Compile the exact enabled wake registry; disabled sources are never even scanned.

    The R11.2 DEEP fleet source is **unconditional**: unlike the three provider-gated sources it
    belongs to no provider, and the R11.1 DEEP bridge is composed for every project run — so a run
    parked at a DEEP fleet wait must be wakeable whatever the provider flags say.
    """

    sources: list[ExternalResearchWakeSource] = [_deep_fleet_due]
    if committee_enabled:
        sources.append(_committee_due)
    if contact_external_enabled:
        sources.append(_contact_external_due)
    if contact_channel_enabled:
        sources.append(_channel_due)
    return tuple(sources)


def registered_entity_research_wait_sources(
    *,
    committee_enabled: bool,
    contact_external_enabled: bool,
    contact_channel_enabled: bool,
) -> tuple[EntityResearchWaitSource, ...]:
    """Compile due-operation adapters for exact R9 composite member waits."""

    sources: list[EntityResearchWaitSource] = []
    if committee_enabled:
        sources.append(_committee_waits_due)
    if contact_external_enabled:
        sources.append(_contact_external_waits_due)
    if contact_channel_enabled:
        sources.append(_channel_waits_due)
    return tuple(sources)


class ExternalResearchWakeDispatcher:
    """Re-offer owning runs; provider polling remains inside registered preparation adapters."""

    def __init__(
        self,
        *,
        project_run_waker: ProjectRunWaker,
        sources: Sequence[ExternalResearchWakeSource] = (
            _deep_fleet_due,
            _committee_due,
            _contact_external_due,
            _channel_due,
        ),
        entity_member_waker: EntityResearchMemberWaker | None = None,
        entity_wait_sources: Sequence[EntityResearchWaitSource] = (),
        conn_factory: ConnFactory = transaction,
        batch_limit: int = 100,
    ) -> None:
        if batch_limit < 1:
            raise ValueError("external-research wake batch limit must be positive")
        self._project_run_waker = project_run_waker
        self._sources = tuple(sources)
        self._entity_member_waker = entity_member_waker
        self._entity_wait_sources = tuple(entity_wait_sources)
        self._conn_factory = conn_factory
        self._batch_limit = batch_limit

    async def run_due(self, *, now: datetime | None = None) -> int:
        observed_at = now or datetime.now(UTC)
        run_ids: list[ProjectRunId] = []
        member_wait_refs: list[str] = []
        async with self._conn_factory() as conn:
            for project_source in self._sources:
                run_ids.extend(await project_source(conn, observed_at, self._batch_limit))
            for entity_source in self._entity_wait_sources:
                member_wait_refs.extend(await entity_source(conn, observed_at, self._batch_limit))
        offered = 0
        for project_run_id in tuple(dict.fromkeys(run_ids))[: self._batch_limit]:
            if await self._project_run_waker(project_run_id):
                offered += 1
        if self._entity_member_waker is not None:
            for wait_ref in tuple(dict.fromkeys(member_wait_refs))[: self._batch_limit]:
                offered += await self._entity_member_waker(wait_ref)
        return offered


__all__ = [
    "ExternalResearchWakeDispatcher",
    "ExternalResearchWakeSource",
    "EntityResearchMemberWaker",
    "EntityResearchWaitSource",
    "ProjectRunWaker",
    "registered_entity_research_wait_sources",
    "registered_external_research_wake_sources",
]
