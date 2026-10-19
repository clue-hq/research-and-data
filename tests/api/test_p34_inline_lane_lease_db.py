"""Adversarial-review fixes E+B — the inline design lane holds its lease, and the leg
run's row payload is the frozen envelope.

Finding E: ``InlineDesignLaneDriver`` acquired the design run's work lease once (TTL 30s)
and held it, renewal-free, across a design turn that runs minutes — so the design reaper
(enabled by the same switch) declared every real leg run stranded and re-offered it.
The fix is the B1 supervised-heartbeat pattern: renew at TTL/3, retry transient renew
errors without killing the beat, declare loss only when fenced or when no beat can land
before true expiry (flipping ``context.lease_lost`` so the handler abandons
cooperatively) — and after the handler returns, whatever the outcome, join the run to a
terminal state (bounded), because a takeover owns only the *design run* while the
platform turn/leg projection is ours alone: re-joining the takeover's result is the only
path that completes the turn.

Finding B: the run row's ``payload`` must BE the frozen ``DesignTurnEnvelope`` — the
reaper re-enqueues ``handed_back["payload"]`` verbatim ("re-read from the design row
rather than rebuilt"), so a config-only payload made every re-offered leg run a poison
task and broke strand repair for legs.

The two lease tests run on the REAL pooled connection factory (the heartbeat genuinely
runs concurrently with the handler; a shared savepoint connection cannot serve both) and
clean up their committed rows; the payload test stays on the rolled-back session.
"""

from __future__ import annotations

import asyncio
import os
import socket
from contextlib import asynccontextmanager as contextlib_asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from pydantic import TypeAdapter
from sqlalchemy import text

from clue_api.agent_turn_submission import message_artifact_ref
from clue_api.design_fleet import InlineDesignLaneDriver, design_leg_lane_worker_id
from clue_db import db_lifespan, transaction
from clue_design import runs as design_runs
from clue_design.envelopes import DesignTurnEnvelope
from clue_fleet import LeaseGeneration, WorkId, acquire_work_lease, get_work_lease
from clue_fleet.work_worker import WorkContext, WorkResult
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

_ENVELOPE_ADAPTER: TypeAdapter[DesignTurnEnvelope] = TypeAdapter(DesignTurnEnvelope)


def _leg_envelope(*, workspace_id: str, run_id: str) -> DesignTurnEnvelope:
    return DesignTurnEnvelope(
        kind="agent_turn",
        work_id=design_runs.work_id_for_run(run_id),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        config={"request": {"prompt": "lease probe", "scene": {}}},
    )


async def _seed_committed_run(label: str) -> DesignTurnEnvelope:
    """Workspace + queued design run, COMMITTED (the lease tests use the real pool)."""

    workspace_id = f"ws_p34lease_{label}_{uuid4().hex[:8]}"
    run_id = f"run_{uuid5(NAMESPACE_URL, f'p34lease:{label}').hex}"
    envelope = _leg_envelope(workspace_id=workspace_id, run_id=run_id)
    async with transaction() as conn:
        await conn.execute(
            text(
                "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w) "
                "ON CONFLICT (workspace_id) DO NOTHING"
            ),
            {"w": workspace_id},
        )
        await design_runs.create_run(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            document_id=None,
            payload=envelope.model_dump(mode="json"),
            work_id=envelope.work_id,
        )
    return envelope


async def _cleanup_committed_run(envelope: DesignTurnEnvelope) -> None:
    async with transaction() as conn:
        await conn.execute(
            text("DELETE FROM work_lease WHERE work_id = :w"), {"w": envelope.work_id}
        )
        await conn.execute(
            text("DELETE FROM design_agent_run WHERE run_id = :r AND workspace_id = :ws"),
            {"r": envelope.run_id, "ws": envelope.workspace_id},
        )
        await conn.execute(
            text("DELETE FROM workspace WHERE workspace_id = :ws"),
            {"ws": envelope.workspace_id},
        )


class _SlowCompletingHandler:
    """Runs 'work' longer than several lease TTLs, then lands the terminal result."""

    def __init__(self, *, run_seconds: float) -> None:
        self._run_seconds = run_seconds
        self.contexts: list[WorkContext] = []

    async def handle(self, context: WorkContext) -> WorkResult:
        self.contexts.append(context)
        await asyncio.sleep(self._run_seconds)
        envelope = context.payload
        async with transaction() as conn:
            await design_runs.set_run_result(
                conn,
                workspace_id=str(envelope["workspace_id"]),
                run_id=str(envelope["run_id"]),
                status="succeeded",
                result={"schema_version": 1, "status": "accepted"},
                expected_generation=int(context.lease_generation),
            )
        return WorkResult(outcome="succeeded", references={})


class _AbandonOnLeaseLossHandler:
    """The real handler's cooperative shape: wait for the fence, abandon, report honestly."""

    async def handle(self, context: WorkContext) -> WorkResult:
        await context.lease_lost.wait()
        return WorkResult(outcome="lease_lost", references={}, requeue=True)


def test_the_leg_run_row_payload_is_the_frozen_envelope(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Finding B: what the runner stores is exactly what the reaper may re-offer — the
    full envelope, parseable by the design handler's own validator."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.agent_registry_wiring import build_agent_profile_registry
            from clue_api.toolbelt_wiring import build_toolbelt
            from clue_design import legs as design_legs
            from tests.api.conftest import hermetic_flag_env
            from tests.api.test_p34_design_leg_engine_db import (
                _card_payload,
                _FakeLane,
                _runner,
                _seed_leg_conversation,
                _submit_message,
            )

            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="payload")
            with hermetic_flag_env():
                catalog = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            submission = await _submit_message(
                conn, seeds, label="payload-t1", message="Frozen-envelope probe."
            )
            leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
            )
            assert leg is not None
            await _runner(
                seeds, catalog, _FakeLane(conn_factory=seeds["conn_factory"])
            ).run_leg_turn(
                submission=submission,
                leg=leg,
                user_message_ref=await message_artifact_ref(conn, submission),
                focus_refs=(),
                card_payload=_card_payload(seeds),
                stream=None,
            )
            stored = (
                await conn.execute(
                    text(
                        "SELECT payload FROM design_agent_run "
                        "WHERE workspace_id = :ws AND leg_id = CAST(:leg AS uuid)"
                    ),
                    {"ws": seeds["workspace_id"], "leg": leg["id"]},
                )
            ).scalar_one()
            parsed = _ENVELOPE_ADAPTER.validate_python(stored)
            assert parsed.kind == "agent_turn"
            assert parsed.workspace_id == seeds["workspace_id"]
            assert parsed.config["request"]["prompt"] == "Frozen-envelope probe."
            assert parsed.config["leg"]["leg_id"] == leg["id"]

    run_async(scenario())


def test_the_inline_lane_renews_its_lease_across_a_long_turn(
    migrated_db: bool,  # noqa: F811
) -> None:
    """Finding E, the common case: a turn several TTLs long never lets the lease lapse,
    so the reaper's ``_is_stranded`` (dead lease + no task) can never fire on live work."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            await _renew_scenario()

    async def _renew_scenario() -> None:
        envelope = await _seed_committed_run("renew")
        try:
            handler = _SlowCompletingHandler(run_seconds=2.5)
            driver = InlineDesignLaneDriver(
                handler=handler,
                lease_ttl=timedelta(seconds=1.0),
                heartbeat_interval_s=0.25,
                join_poll_interval_s=0.1,
                join_timeout_s=10.0,
            )
            drive = asyncio.create_task(driver.drive(envelope=envelope))
            # Mid-flight, well past the un-renewed TTL: the lease must still be live.
            await asyncio.sleep(1.6)
            async with transaction() as conn:
                lease = await get_work_lease(conn, WorkId(envelope.work_id))
            assert lease is not None and lease.live, (
                "the lease lapsed mid-turn — the reaper would strand this live run"
            )
            await drive
            assert driver.renewals >= 2
            async with transaction() as conn:
                run = await design_runs.get_run(
                    conn, workspace_id=envelope.workspace_id, run_id=envelope.run_id
                )
            assert run is not None and run["status"] == "succeeded"
        finally:
            await _cleanup_committed_run(envelope)

    run_async(scenario())


def test_a_fenced_out_lane_abandons_and_rejoins_the_takeovers_terminal_run(
    migrated_db: bool,  # noqa: F811
) -> None:
    """Finding E, the takeover case: when a higher generation steals the lease, the lane
    flips ``lease_lost`` (the handler abandons cooperatively) and then converges by
    joining the takeover's terminal result instead of failing the platform turn."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            await _fence_scenario()

    async def _fence_scenario() -> None:
        envelope = await _seed_committed_run("fence")
        try:
            driver = InlineDesignLaneDriver(
                handler=_AbandonOnLeaseLossHandler(),
                lease_ttl=timedelta(seconds=1.0),
                heartbeat_interval_s=0.25,
                join_poll_interval_s=0.1,
                join_timeout_s=10.0,
            )
            drive = asyncio.create_task(driver.drive(envelope=envelope))
            await asyncio.sleep(0.5)
            # The theft: force-expire the lane's lease and acquire a HIGHER generation —
            # exactly what a reaper-fed takeover worker does after a genuine stall.
            async with transaction() as conn:
                await conn.execute(
                    text(
                        "UPDATE work_lease SET expires_at = now() - interval '1 second' "
                        "WHERE work_id = :w"
                    ),
                    {"w": envelope.work_id},
                )
                thief = await acquire_work_lease(
                    conn, work_id=WorkId(envelope.work_id), worker_id="takeover-worker"
                )
            assert thief is not None
            # The takeover finishes the design work under ITS generation.
            async with transaction() as conn:
                await design_runs.set_run_result(
                    conn,
                    workspace_id=envelope.workspace_id,
                    run_id=envelope.run_id,
                    status="succeeded",
                    result={"schema_version": 1, "status": "accepted"},
                    expected_generation=int(thief.generation),
                )
            # The lane converges on the takeover's result rather than raising.
            await asyncio.wait_for(drive, timeout=8.0)
            async with transaction() as conn:
                run = await design_runs.get_run(
                    conn, workspace_id=envelope.workspace_id, run_id=envelope.run_id
                )
            assert run is not None and run["status"] == "succeeded"
        finally:
            await _cleanup_committed_run(envelope)

    run_async(scenario())


class _StatefulHandler:
    """Attempt 1 abandons on the fence; attempt 2 (the re-acquire) completes the run."""

    def __init__(self, *, conn_factory: Any) -> None:
        self._conn_factory = conn_factory
        self.attempts = 0

    async def handle(self, context: WorkContext) -> WorkResult:
        self.attempts += 1
        if self.attempts == 1:
            await context.lease_lost.wait()
            return WorkResult(outcome="lease_lost", references={}, requeue=True)
        envelope = context.payload
        async with transaction() as conn:
            await design_runs.set_run_result(
                conn,
                workspace_id=str(envelope["workspace_id"]),
                run_id=str(envelope["run_id"]),
                status="succeeded",
                result={"schema_version": 1, "status": "accepted"},
                expected_generation=int(context.lease_generation),
            )
        return WorkResult(outcome="succeeded", references={})


def test_a_refused_lane_reacquires_when_the_holders_lease_dies(
    migrated_db: bool,  # noqa: F811
) -> None:
    """MED-6 (adversarial-review fix): a lane whose acquire was refused used to park in a
    blind terminal-join for up to 30 minutes — while the reaper's recovery design_job landed
    in the very queue this parked worker drains (the single-worker deadlock the inline lane
    exists to avoid). Now it waits only while the foreign holder's lease is LIVE and
    re-acquires the moment nobody is driving, completing the run itself."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            await _refused_scenario()

    async def _refused_scenario() -> None:
        envelope = await _seed_committed_run("refused")
        try:
            # A foreign holder with a short lease it will never renew — a worker that died
            # a moment after claiming.
            async with transaction() as conn:
                foreign = await acquire_work_lease(
                    conn,
                    work_id=WorkId(envelope.work_id),
                    worker_id="dead-foreign-worker",
                    ttl=timedelta(seconds=1.0),
                )
            assert foreign is not None
            handler = _SlowCompletingHandler(run_seconds=0.1)
            driver = InlineDesignLaneDriver(
                handler=handler,
                lease_ttl=timedelta(seconds=1.0),
                heartbeat_interval_s=0.25,
                join_poll_interval_s=0.2,
                join_timeout_s=8.0,
            )
            await asyncio.wait_for(driver.drive(envelope=envelope), timeout=10.0)
            assert len(handler.contexts) == 1  # the lane drove the run ITSELF
            async with transaction() as conn:
                run = await design_runs.get_run(
                    conn, workspace_id=envelope.workspace_id, run_id=envelope.run_id
                )
            assert run is not None and run["status"] == "succeeded"
        finally:
            await _cleanup_committed_run(envelope)

    run_async(scenario())


def test_a_fenced_lane_reacquires_when_the_takeover_dies_without_finishing(
    migrated_db: bool,  # noqa: F811
) -> None:
    """MED-6, the fenced flavor: the thief steals the lease and dies. The fenced lane used
    to wait on a terminal row nobody would ever write; now it re-acquires once the thief's
    lease lapses and finishes the work under its new generation."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            await _fenced_dead_thief_scenario()

    async def _fenced_dead_thief_scenario() -> None:
        envelope = await _seed_committed_run("deadthief")
        try:
            handler = _StatefulHandler(conn_factory=transaction)
            driver = InlineDesignLaneDriver(
                handler=handler,
                lease_ttl=timedelta(seconds=1.0),
                heartbeat_interval_s=0.25,
                join_poll_interval_s=0.2,
                join_timeout_s=10.0,
            )
            drive = asyncio.create_task(driver.drive(envelope=envelope))
            await asyncio.sleep(0.5)
            # The theft: force-expire the lane's lease; the thief claims with a SHORT lease
            # and then dies (never renews, never completes the run).
            async with transaction() as conn:
                await conn.execute(
                    text(
                        "UPDATE work_lease SET expires_at = now() - interval '1 second' "
                        "WHERE work_id = :w"
                    ),
                    {"w": envelope.work_id},
                )
                thief = await acquire_work_lease(
                    conn,
                    work_id=WorkId(envelope.work_id),
                    worker_id="thief-that-dies",
                    ttl=timedelta(seconds=1.0),
                )
            assert thief is not None
            await asyncio.wait_for(drive, timeout=12.0)
            assert handler.attempts == 2  # abandoned once, then re-acquired and finished
            async with transaction() as conn:
                run = await design_runs.get_run(
                    conn, workspace_id=envelope.workspace_id, run_id=envelope.run_id
                )
            assert run is not None and run["status"] == "succeeded"
        finally:
            await _cleanup_committed_run(envelope)

    run_async(scenario())


def test_cancelled_inline_driver_waits_for_its_body_and_keeps_lease(
    migrated_db: bool,  # noqa: F811
) -> None:
    """The caller cannot acknowledge Stop while the owned handler is still unwinding."""
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            envelope = await _seed_committed_run("stop-body")
            entered, release, exited = asyncio.Event(), asyncio.Event(), asyncio.Event()

            class Handler:
                async def handle(self, context: WorkContext) -> WorkResult:
                    entered.set()
                    await release.wait()
                    exited.set()
                    return WorkResult(outcome="cancelled", references={})

            driver = InlineDesignLaneDriver(
                handler=Handler(),
                lease_ttl=timedelta(seconds=1),
                heartbeat_interval_s=0.2,
                join_poll_interval_s=0.05,
                join_timeout_s=5,
            )
            drive = asyncio.create_task(driver.drive(envelope=envelope))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                drive.cancel()
                await asyncio.sleep(1.1)
                assert not drive.done() and not exited.is_set()
                async with transaction() as conn:
                    lease = await get_work_lease(conn, WorkId(envelope.work_id))
                async with transaction() as conn:
                    assert await design_runs.cancellation_requested(
                        conn, workspace_id=envelope.workspace_id, run_id=envelope.run_id
                    )
                assert lease is not None and lease.live
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(drive, 2)
                assert exited.is_set()
            finally:
                release.set()
                if not drive.done():
                    drive.cancel()
                await _cleanup_committed_run(envelope)

    run_async(scenario())


# --- site-turn durability, task 1 (2026-10-16) -------------------------------------------------
#
# The inline lane used ONE worker id, "design-leg-inline-lane", in every process, and the lease
# lets its holder re-acquire a live lease — so two processes could both "hold" one design run's
# lease and drive it at once. The id is now per process.


def test_the_inline_lane_worker_id_names_its_host_and_process() -> None:
    assert design_leg_lane_worker_id() == (
        f"design-leg-inline-lane:{socket.gethostname()}:{os.getpid()}"
    )
    assert design_leg_lane_worker_id(host="h", pid=1) != design_leg_lane_worker_id(host="h", pid=2)


def test_two_inline_lane_processes_cannot_both_drive_one_run(
    migrated_db: bool,  # noqa: F811
) -> None:
    """Process 1 is driving the run; process 2's lane is refused the lease, waits on the live
    foreign holder, and returns once process 1 has finished — its handler never runs."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan():
            envelope = await _seed_committed_run("two-processes")
            entered, release = asyncio.Event(), asyncio.Event()
            seen: list[str] = []

            class FirstProcessHandler:
                async def handle(self, context: WorkContext) -> WorkResult:
                    seen.append(context.worker_id)
                    entered.set()
                    await release.wait()
                    async with transaction() as conn:
                        await design_runs.claim_run_for_execution(
                            conn,
                            work_id=envelope.work_id,
                            worker_id=context.worker_id,
                            lease_generation=int(context.lease_generation),
                        )
                        await design_runs.set_run_result(
                            conn,
                            workspace_id=envelope.workspace_id,
                            run_id=envelope.run_id,
                            status="succeeded",
                            result={"schema_version": 1, "status": "accepted"},
                            expected_generation=int(context.lease_generation),
                        )
                    return WorkResult(outcome="succeeded", references={})

            class SecondProcessHandler:
                async def handle(self, context: WorkContext) -> WorkResult:
                    seen.append(context.worker_id)
                    return WorkResult(outcome="succeeded", references={})

            settings = {
                "lease_ttl": timedelta(seconds=1.0),
                "heartbeat_interval_s": 0.25,
                "join_poll_interval_s": 0.1,
                "join_timeout_s": 10.0,
            }
            try:
                first = InlineDesignLaneDriver(
                    handler=FirstProcessHandler(),
                    worker_id=design_leg_lane_worker_id(host="vm", pid=101),
                    **settings,
                )
                second = InlineDesignLaneDriver(
                    handler=SecondProcessHandler(),
                    worker_id=design_leg_lane_worker_id(host="vm", pid=202),
                    **settings,
                )
                one = asyncio.create_task(first.drive(envelope=envelope))
                await asyncio.wait_for(entered.wait(), 3)
                two = asyncio.create_task(second.drive(envelope=envelope))
                await asyncio.sleep(0.6)
                assert not two.done()  # waiting on process 1's live lease, not driving
                async with transaction() as conn:
                    lease = await get_work_lease(conn, WorkId(envelope.work_id))
                assert lease is not None and lease.live
                assert lease.worker_id == design_leg_lane_worker_id(host="vm", pid=101)
                release.set()
                await asyncio.wait_for(asyncio.gather(one, two), 8)
                assert seen == [design_leg_lane_worker_id(host="vm", pid=101)]
            finally:
                release.set()
                await _cleanup_committed_run(envelope)

    run_async(scenario())


def test_the_lane_keeps_a_lease_whose_beats_land_late_while_nobody_took_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The database is unreachable for longer than the TTL; when it returns, the renew lands
    (nobody claimed the run), so the lane does not abandon the turn. A renew that reaches the
    database and fails — someone took the lease — still ends it at once."""

    import clue_api.design_fleet as design_fleet

    state = {"back": False, "taken": False, "renewed": 0}

    async def renew(conn: object, **_: object) -> bool:
        if not state["back"]:
            raise RuntimeError("connection refused")
        if state["taken"]:
            return False
        state["renewed"] += 1
        return True

    @contextlib_asynccontextmanager
    async def connections() -> Any:
        yield object()

    monkeypatch.setattr(design_fleet, "renew_work_lease", renew)

    async def scenario() -> None:
        driver = InlineDesignLaneDriver(
            handler=_AbandonOnLeaseLossHandler(),
            conn_factory=connections,
            lease_ttl=timedelta(seconds=0.3),
            heartbeat_interval_s=0.05,
        )
        lease_lost = asyncio.Event()
        loop = asyncio.get_running_loop()
        beat = asyncio.create_task(
            driver._keep_lease(
                work_id=WorkId(uuid4()),
                generation=LeaseGeneration(1),
                lease_lost=lease_lost,
                acquired_at=loop.time(),
            )
        )
        await asyncio.sleep(0.6)  # twice the TTL with every renew failing to connect
        assert not lease_lost.is_set() and not beat.done()
        state["back"] = True
        await asyncio.sleep(0.2)
        assert state["renewed"] > 0 and not lease_lost.is_set()
        state["taken"] = True
        await asyncio.wait_for(beat, 1)
        assert lease_lost.is_set()

    run_async(scenario())
