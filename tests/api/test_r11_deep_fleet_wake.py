"""M8D R11.2 — the fleet-terminal wake source behind a parked DEEP phase.

The R11.1 adapter parks a project run at a DEEP ``waiting_external`` checkpoint while the M8D
account-research fleet works, and the state machine only re-enters that handler when something
wakes the run. This module is the Postgres acceptance for the thing that wakes it: the fast path
(the bound fleet run reached ``terminal`` or ``suspended``), the scheduled-poll fallback (the
payload's ``next_poll_at`` passed), the scoping that keeps another tenant's or project's fleet row
from waking a run, and the end-to-end proof that a woken run actually leaves DEEP.

Fixtures are the F1 bridge helpers — one seeded project run, one confirmed fleet launch, one state
machine over the test connection — so both slices exercise the same substrate.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import AccountResearchFleetState
from clue_api.entity_research_deep_phase import DEEP_FLEET_POLL_INTERVAL
from clue_api.external_research_wake import (
    ExternalResearchWakeDispatcher,
    ExternalResearchWakeSource,
    registered_external_research_wake_sources,
)
from clue_core import DeepFleetExternalWait, ProjectPhase, ProjectRunId
from clue_core.entity_research import ResearchFinalizationOutcome, ResearchJobState
from clue_fleet import EntityResearchRunEnvelope
from clue_research.durable import (
    DbProjectRunStore,
    PhaseCheckpointStatus,
    ProjectRun,
    ProjectRunStatus,
)
from tests.api.test_r11_deep_phase_bridge import (
    _finalize_all,
    _launch,
    _machine,
    _same_connection,
    _Scope,
    _seed_scope,
    _service,
)
from tests.fleet.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _deep_source() -> ExternalResearchWakeSource:
    """The R11.2 source exactly as production compiles it with every provider flag off."""

    sources = registered_external_research_wake_sources(
        committee_enabled=False,
        contact_external_enabled=False,
        contact_channel_enabled=False,
    )
    assert len(sources) == 1
    return sources[0]


async def _due(conn: AsyncConnection, *, now: datetime, limit: int = 100) -> Sequence[ProjectRunId]:
    return await _deep_source()(conn, now, limit)


async def _park_at_deep_wait(
    conn: AsyncConnection, *, workspace_id: str = "acme", accounts: int = 3
) -> tuple[_Scope, EntityResearchRunEnvelope, ProjectRun]:
    """Seed a run, launch its fleet, and advance DEEP once so the run parks on the R11.4 wait."""

    scope = await _seed_scope(conn, workspace_id=workspace_id)
    envelope = await _launch(conn, scope, accounts=accounts)
    machine = await _machine(conn, scope)
    run = await machine.advance(scope.project_run_id)
    assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)
    checkpoint = await machine.await_checkpoint(scope.project_run_id)
    assert checkpoint is not None
    assert checkpoint.status is PhaseCheckpointStatus.WAITING_EXTERNAL
    DeepFleetExternalWait.model_validate(checkpoint.payload)
    return scope, envelope, machine


async def _wait_payload(conn: AsyncConnection, scope: _Scope) -> DeepFleetExternalWait:
    store = DbProjectRunStore(conn_factory=lambda: _same_connection(conn))
    checkpoint = await store.get_checkpoint(scope.project_run_id, ProjectPhase.DEEP)
    assert checkpoint is not None
    return DeepFleetExternalWait.model_validate(checkpoint.payload)


async def _set_next_poll_at(conn: AsyncConnection, scope: _Scope, when: datetime) -> None:
    """Rewrite only the wait's poll time, so ordering assertions read off known instants."""

    await conn.execute(
        text(
            "UPDATE project_phase_checkpoint SET payload_json = "
            "jsonb_set(payload_json, '{next_poll_at}', to_jsonb(CAST(:when AS text))) "
            "WHERE project_run_id=:run_id AND phase=CAST('deep' AS project_phase)"
        ),
        {"when": when.isoformat(), "run_id": scope.project_run_id},
    )


async def _bind_wait_to(conn: AsyncConnection, scope: _Scope, research_run_id: UUID) -> None:
    """Point a parked wait at another fleet run without touching anything else in the payload."""

    await conn.execute(
        text(
            "UPDATE project_phase_checkpoint SET payload_json = "
            "jsonb_set(payload_json, '{research_run_id}', to_jsonb(CAST(:fleet AS text))) "
            "WHERE project_run_id=:run_id AND phase=CAST('deep' AS project_phase)"
        ),
        {"fleet": str(research_run_id), "run_id": scope.project_run_id},
    )


async def _terminal(conn: AsyncConnection, envelope: EntityResearchRunEnvelope) -> None:
    await _finalize_all(
        conn,
        envelope,
        outcomes=(ResearchFinalizationOutcome.COMPLETED,) * len(envelope.jobs),
    )


async def _suspend(
    conn: AsyncConnection, scope: _Scope, envelope: EntityResearchRunEnvelope
) -> None:
    projection = await _service(conn).pause_job(
        envelope.jobs[0].authorization.job_id,
        workspace_id=scope.workspace_id,
        actor="user:owner",
        reason_code="operator_hold",
    )
    assert projection.fleet_state is AccountResearchFleetState.SUSPENDED


# --- the two ways a parked DEEP wait becomes due -------------------------------------------------


def test_a_working_fleet_with_a_future_poll_is_not_woken() -> None:
    """The wait is doing its job: nothing has changed and the poll has not come round."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, _, _ = await _park_at_deep_wait(conn)
            wait = await _wait_payload(conn, scope)
            assert wait.next_poll_at > datetime.now(UTC)

            assert await _due(conn, now=datetime.now(UTC)) == ()

    run_async(scenario())


def test_a_terminal_fleet_wakes_its_run_ahead_of_the_scheduled_poll() -> None:
    """The fast path: the fleet finished, so the run is re-offered without waiting for the poll."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, envelope, _ = await _park_at_deep_wait(conn)
            await _terminal(conn, envelope)

            wait = await _wait_payload(conn, scope)
            now = datetime.now(UTC)
            assert wait.next_poll_at > now  # the scheduled fallback is nowhere near due
            assert await _due(conn, now=now) == (scope.project_run_id,)

    run_async(scenario())


def test_a_suspended_fleet_wakes_its_run_ahead_of_the_scheduled_poll() -> None:
    """A suspension is a human decision point — the run must surface it, not sit on the wait."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, envelope, _ = await _park_at_deep_wait(conn)
            await _suspend(conn, scope, envelope)

            assert await _due(conn, now=datetime.now(UTC)) == (scope.project_run_id,)

    run_async(scenario())


def test_a_working_fleet_wakes_once_its_scheduled_poll_falls_due() -> None:
    """The fallback: the fleet is still working, so the handler re-reads and re-emits a wait."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, _, machine = await _park_at_deep_wait(conn)
            wait = await _wait_payload(conn, scope)
            due_at = wait.next_poll_at + timedelta(seconds=1)

            assert await _due(conn, now=due_at) == (scope.project_run_id,)

            # Re-entering emits a fresh wait one poll interval out, so the run stops being due.
            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)
            refreshed = await _wait_payload(conn, scope)
            assert refreshed.next_poll_at > wait.next_poll_at
            assert await _due(conn, now=datetime.now(UTC)) == ()

    run_async(scenario())


def test_a_settled_fleet_whose_poll_also_passed_is_offered_exactly_once() -> None:
    """Both conditions hit the same run; the source lists it once, not twice."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, envelope, _ = await _park_at_deep_wait(conn)
            await _terminal(conn, envelope)
            wait = await _wait_payload(conn, scope)

            due = await _due(conn, now=wait.next_poll_at + timedelta(seconds=1))
            assert due == (scope.project_run_id,)

    run_async(scenario())


# --- batching -----------------------------------------------------------------------------------


def test_settled_runs_sort_ahead_of_scheduled_polls_and_the_limit_is_respected() -> None:
    """Deterministic order — a run that can actually leave DEEP first, then by poll time — so a
    bounded batch is spent on progress before housekeeping."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            base = datetime.now(UTC) - timedelta(hours=1)
            polling_first, _, _ = await _park_at_deep_wait(conn, accounts=1)
            await _set_next_poll_at(conn, polling_first, base)
            polling_second, _, _ = await _park_at_deep_wait(conn, accounts=1)
            await _set_next_poll_at(conn, polling_second, base + timedelta(minutes=1))
            settled, envelope, _ = await _park_at_deep_wait(conn, accounts=1)
            await _terminal(conn, envelope)
            # The settled run's own poll is the *latest* of the three: only the fast path can
            # explain it coming first.
            await _set_next_poll_at(conn, settled, base + timedelta(minutes=2))

            now = datetime.now(UTC)
            assert await _due(conn, now=now) == (
                settled.project_run_id,
                polling_first.project_run_id,
                polling_second.project_run_id,
            )
            assert await _due(conn, now=now, limit=1) == (settled.project_run_id,)
            assert await _due(conn, now=now, limit=2) == (
                settled.project_run_id,
                polling_first.project_run_id,
            )

    run_async(scenario())


# --- what must never wake a run ------------------------------------------------------------------


def test_only_a_deep_waiting_external_checkpoint_of_an_active_run_is_woken() -> None:
    """Another phase, another checkpoint status, or a run that is not driving: all out of scope."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, envelope, _ = await _park_at_deep_wait(conn)
            await _terminal(conn, envelope)
            payload = (await _wait_payload(conn, scope)).model_dump(mode="json")
            store = DbProjectRunStore(conn_factory=lambda: _same_connection(conn))
            now = datetime.now(UTC)
            assert await _due(conn, now=now) == (scope.project_run_id,)

            # Another status on the same phase: a committed DEEP phase has nothing to re-enter.
            await store.put_checkpoint(
                project_run_id=scope.project_run_id,
                phase=ProjectPhase.DEEP,
                idempotency_key=f"deep:{scope.project_run_id}",
                status=PhaseCheckpointStatus.COMMITTED,
                payload=payload,
            )
            assert await _due(conn, now=now) == ()

            # Back to a genuine DEEP wait, but on a run nobody is driving: advance is a no-op while
            # the run is paused, so waking it would be a pointless offer every scan, forever.
            await store.put_checkpoint(
                project_run_id=scope.project_run_id,
                phase=ProjectPhase.DEEP,
                idempotency_key=f"deep:{scope.project_run_id}",
                status=PhaseCheckpointStatus.WAITING_EXTERNAL,
                payload=payload,
            )
            assert await _due(conn, now=now) == (scope.project_run_id,)
            await store.mark_status(
                scope.project_run_id, status=ProjectRunStatus.PAUSED, stamp_paused=True
            )
            assert await _due(conn, now=now) == ()

    run_async(scenario())


def test_a_fleet_shaped_wait_at_another_phase_is_not_this_sources_business() -> None:
    """DISCOVERY owns its own external waits; only the DEEP checkpoint is this bridge's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            envelope = await _launch(conn, scope, accounts=1)
            await _terminal(conn, envelope)
            store = DbProjectRunStore(conn_factory=lambda: _same_connection(conn))
            await store.transition(
                scope.project_run_id,
                phase=ProjectPhase.DISCOVERY,
                status=ProjectRunStatus.ACTIVE,
            )
            # Both due conditions are satisfied by this payload, so only the phase can explain the
            # empty result.
            wait = DeepFleetExternalWait(
                research_run_id=envelope.lifecycle.run_id,
                job_state_counts={ResearchJobState.QUEUED.value: 1},
                next_poll_at=datetime.now(UTC) - timedelta(minutes=5),
            )
            await store.put_checkpoint(
                project_run_id=scope.project_run_id,
                phase=ProjectPhase.DISCOVERY,
                idempotency_key=f"discovery:{scope.project_run_id}",
                status=PhaseCheckpointStatus.WAITING_EXTERNAL,
                payload=wait.model_dump(mode="json"),
            )

            assert await _due(conn, now=datetime.now(UTC)) == ()

    run_async(scenario())


def test_another_workspaces_or_projects_fleet_row_never_wakes_a_run() -> None:
    """The source repeats the adapter's fail-closed scoping: an out-of-scope fleet row reads as
    absent here exactly as it does in the handler, so only the scheduled poll can fire."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, _, _ = await _park_at_deep_wait(conn)

            # A terminal fleet run in a different workspace entirely (its own project run is not
            # parked at DEEP, so nothing but this run's wait could be listed).
            foreign_scope = await _seed_scope(conn, workspace_id="other-workspace")
            foreign_envelope = await _launch(conn, foreign_scope, accounts=1)
            await _terminal(conn, foreign_envelope)
            await _bind_wait_to(conn, scope, foreign_envelope.lifecycle.run_id)
            now = datetime.now(UTC)
            assert await _due(conn, now=now) == ()

            # And a terminal fleet run bound to this project run but owned by another project.
            other_project = await _launch(conn, scope, accounts=1, project_id="prj-elsewhere")
            await _terminal(conn, other_project)
            await _bind_wait_to(conn, scope, other_project.lifecycle.run_id)
            assert await _due(conn, now=now) == ()

            # The scheduled fallback still covers it: nothing is stranded, it just is not fast.
            wait = await _wait_payload(conn, scope)
            assert await _due(conn, now=wait.next_poll_at + timedelta(seconds=1)) == (
                scope.project_run_id,
            )

    run_async(scenario())


# --- registration + end to end --------------------------------------------------------------------


def test_the_deep_source_is_registered_whatever_the_provider_flags_say() -> None:
    """The DEEP bridge is composed for every run, so its wake source belongs to no provider flag."""

    every_flag_off = registered_external_research_wake_sources(
        committee_enabled=False,
        contact_external_enabled=False,
        contact_channel_enabled=False,
    )
    every_flag_on = registered_external_research_wake_sources(
        committee_enabled=True,
        contact_external_enabled=True,
        contact_channel_enabled=True,
    )
    assert len(every_flag_off) == 1
    assert len(every_flag_on) == 4
    # The DEEP source leads the registry: a settled fleet is the one wake that lets a run leave a
    # phase, so it is never crowded out of a bounded batch by provider housekeeping.
    assert every_flag_on[0] is every_flag_off[0]


def test_a_woken_run_re_enters_deep_and_advances_to_verification() -> None:
    """End to end (AC4): the fleet goes terminal, the dispatcher offers the run to the waker, the
    waker drives it, the DEEP handler re-runs off the parked wait, and the phase commits."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope, envelope, machine = await _park_at_deep_wait(conn)
            await _terminal(conn, envelope)

            offered: list[ProjectRunId] = []

            async def drive(project_run_id: ProjectRunId) -> bool:
                offered.append(project_run_id)
                await machine.advance(project_run_id)
                return True

            # The *default* source tuple, so this also proves the DEEP source ships in the
            # dispatcher's own registry and coexists with the three provider sources.
            dispatcher = ExternalResearchWakeDispatcher(
                project_run_waker=drive,
                conn_factory=lambda: _same_connection(conn),
            )
            assert await dispatcher.run_due(now=datetime.now(UTC)) == 1
            assert offered == [scope.project_run_id]

            run = await machine.status(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.VERIFICATION, ProjectRunStatus.ACTIVE)
            committed = await machine.await_checkpoint(
                scope.project_run_id, phase=ProjectPhase.DEEP
            )
            assert committed is not None
            assert committed.status is PhaseCheckpointStatus.COMMITTED

            # The wait is gone, so the next scan has nothing to offer.
            assert await dispatcher.run_due(now=datetime.now(UTC) + DEEP_FLEET_POLL_INTERVAL) == 0

    run_async(scenario())
