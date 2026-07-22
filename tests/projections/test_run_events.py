"""B4 slice-3 — the ``run_event`` outbox (D8): ordering, replay planning, and the emitter mapping.

Covers: monotone per-workspace ``seq`` + tenant scoping on the durable outbox; the pure
``plan_phase_events`` advance→topics mapping (started/completed/progress/done, no-op suppression);
the ``DbRunEventEmitter`` end-to-end (rows land, a failed emit never raises into the drive path);
and the ``plan_replay`` horizon logic the SSE endpoint runs (fresh connect, mid-stream cursor,
cursor-older-than-horizon → reset).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from clue_api.run_events_wiring import DbRunEventEmitter, plan_phase_events
from clue_core import ProjectPhase, new_project_run_id
from clue_projections import plan_replay
from clue_research.durable import (
    RUN_EVENT_TOPICS,
    ProjectRunStatus,
    RunEventTopic,
    emit_run_event,
    event_created_at,
    list_run_events,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.projections._helpers import seed_run

_WS = "ws-acme"
_OTHER = "ws-other"

pytestmark = pytest.mark.usefixtures("require_profiling_db")


# --- pure: the advance → topics mapping -------------------------------------------------------


def _row(run, *, phase: ProjectPhase, status: ProjectRunStatus):
    return run.model_copy(update={"phase": phase, "status": status})


def _seeded_row():
    """A frozen ProjectRunRow fixture (pure — no DB)."""
    from decimal import Decimal

    from clue_research.durable import ProjectRunRow

    now = datetime.now(UTC)
    return ProjectRunRow(
        id=new_project_run_id(),
        workspace_id=_WS,
        icp_key="default",
        icp_version=1,
        phase=ProjectPhase.REVERSE_PROFILING,
        status=ProjectRunStatus.ACTIVE,
        budget_cap_cents=None,
        spent_cents=Decimal(0),
        tier_cutoffs={},
        paused_at=None,
        resumed_at=None,
        created_at=now,
        updated_at=now,
    )


def test_plan_phase_events_maps_transitions() -> None:
    base = _seeded_row()
    # A phase advance: progress + completed(before) + started(after).
    events = plan_phase_events(
        _row(base, phase=ProjectPhase.DISCOVERY, status=ProjectRunStatus.ACTIVE),
        _row(base, phase=ProjectPhase.SCORING, status=ProjectRunStatus.ACTIVE),
    )
    topics = [t for t, _ in events]
    assert topics == [
        RunEventTopic.STEP_PROGRESS.value,
        RunEventTopic.PHASE_COMPLETED.value,
        RunEventTopic.PHASE_STARTED.value,
    ]
    progress = dict(events)[RunEventTopic.STEP_PROGRESS.value]
    assert progress["from_phase"] == "discovery" and progress["to_phase"] == "scoring"
    assert progress["phase_index"] == 4 and progress["phase_total"] == len(ProjectPhase)

    # Terminal completion on the last phase: progress + completed + done (no new started).
    done_events = plan_phase_events(
        _row(base, phase=ProjectPhase.HANDOFF, status=ProjectRunStatus.ACTIVE),
        _row(base, phase=ProjectPhase.HANDOFF, status=ProjectRunStatus.COMPLETED),
    )
    done_topics = [t for t, _ in done_events]
    assert RunEventTopic.DONE.value in done_topics
    assert RunEventTopic.PHASE_STARTED.value not in done_topics

    # A true no-op advance (paused run re-advanced) emits nothing.
    paused = _row(base, phase=ProjectPhase.DEEP, status=ProjectRunStatus.PAUSED)
    assert plan_phase_events(paused, paused) == []

    # Every emitted topic is in the stored-topic vocabulary.
    for t, _ in events + done_events:
        assert t in RUN_EVENT_TOPICS


# --- DB: outbox ordering + tenancy ------------------------------------------------------------


def test_run_event_seq_is_monotone_and_tenant_scoped() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_a = new_project_run_id()
            run_b = new_project_run_id()
            e1 = await emit_run_event(
                conn, workspace_id=_WS, run_id=run_a, topic="run.phase.started", payload={"n": 1}
            )
            e2 = await emit_run_event(
                conn, workspace_id=_WS, run_id=run_a, topic="run.phase.completed", payload={"n": 2}
            )
            other = await emit_run_event(
                conn, workspace_id=_OTHER, run_id=run_b, topic="run.done", payload={}
            )
            e3 = await emit_run_event(
                conn, workspace_id=_WS, run_id=run_b, topic="run.done", payload={"n": 3}
            )
            # Monotone per workspace (a strictly-increasing subsequence of the global seq).
            assert e1.seq < e2.seq < e3.seq
            ws_events = await list_run_events(conn, workspace_id=_WS)
            assert [e.seq for e in ws_events] == sorted(e.seq for e in ws_events)
            assert {e.seq for e in ws_events} == {e1.seq, e2.seq, e3.seq}
            # Tenant scoping: the other workspace's event never appears.
            assert other.seq not in {e.seq for e in ws_events}
            # Run filter.
            run_a_events = await list_run_events(conn, workspace_id=_WS, run_id=run_a)
            assert [e.seq for e in run_a_events] == [e1.seq, e2.seq]
            # Cursor: after_seq replays strictly-greater rows only.
            after = await list_run_events(conn, workspace_id=_WS, after_seq=e1.seq)
            assert [e.seq for e in after] == [e2.seq, e3.seq]
            # event_created_at is tenant-scoped too.
            assert await event_created_at(conn, workspace_id=_WS, seq=e1.seq) is not None
            assert await event_created_at(conn, workspace_id=_OTHER, seq=e1.seq) is None

    run_async(_run())


def test_db_emitter_writes_rows_and_swallows_faults() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            cf = conn_session_factory(conn)
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.DISCOVERY)
            base = _seeded_row().model_copy(update={"id": run_id})
            emitter = DbRunEventEmitter(conn_factory=cf)
            await emitter.phase_transition(
                _row(base, phase=ProjectPhase.DISCOVERY, status=ProjectRunStatus.ACTIVE),
                _row(base, phase=ProjectPhase.SCORING, status=ProjectRunStatus.ACTIVE),
            )
            events = await list_run_events(conn, workspace_id=_WS, run_id=run_id)
            assert [e.topic for e in events] == [
                RunEventTopic.STEP_PROGRESS.value,
                RunEventTopic.PHASE_COMPLETED.value,
                RunEventTopic.PHASE_STARTED.value,
            ]

        # A broken conn factory must be swallowed (best-effort — never sinks the drive path).
        class _BrokenFactory:
            def __call__(self):
                raise RuntimeError("db down")

        broken = DbRunEventEmitter(conn_factory=_BrokenFactory())  # type: ignore[arg-type]
        base2 = _seeded_row()
        await broken.phase_transition(
            _row(base2, phase=ProjectPhase.DISCOVERY, status=ProjectRunStatus.ACTIVE),
            _row(base2, phase=ProjectPhase.SCORING, status=ProjectRunStatus.ACTIVE),
        )  # does not raise

    run_async(_run())


# --- replay planning (the SSE horizon logic) --------------------------------------------------


def test_plan_replay_fresh_midstream_and_horizon_reset() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_project_run_id()
            events = []
            for i in range(4):
                events.append(
                    await emit_run_event(
                        conn,
                        workspace_id=_WS,
                        run_id=run_id,
                        topic="run.step.progress",
                        payload={"i": i},
                    )
                )
            horizon = 3600.0

            # Fresh connect (no cursor): everything, no reset.
            fresh = await plan_replay(
                conn,
                workspace_id=_WS,
                run_id=run_id,
                last_event_id=None,
                horizon_s=horizon,
            )
            assert not fresh.reset
            assert [e.seq for e in fresh.backlog] == [e.seq for e in events]

            # Mid-stream cursor within the horizon: strictly-later events, zero gap, no reset.
            mid = await plan_replay(
                conn,
                workspace_id=_WS,
                run_id=run_id,
                last_event_id=events[1].seq,
                horizon_s=horizon,
            )
            assert not mid.reset
            assert [e.seq for e in mid.backlog] == [e.seq for e in events[2:]]

            # A cursor older than the horizon → reset (age the cursor's row in-place).
            await conn.execute(
                text("UPDATE run_event SET created_at = :old WHERE seq = :seq"),
                {"old": datetime.now(UTC) - timedelta(seconds=horizon + 60), "seq": events[0].seq},
            )
            stale = await plan_replay(
                conn,
                workspace_id=_WS,
                run_id=run_id,
                last_event_id=events[0].seq,
                horizon_s=horizon,
            )
            assert stale.reset

            # An unknown cursor (never existed for this tenant) is conservatively a reset.
            unknown = await plan_replay(
                conn,
                workspace_id=_WS,
                run_id=run_id,
                last_event_id=10_000_000,
                horizon_s=horizon,
            )
            assert unknown.reset

    run_async(_run())
