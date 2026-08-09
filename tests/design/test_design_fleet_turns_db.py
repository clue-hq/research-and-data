"""D5 Round B acceptance: design turns as leased, recoverable fleet work.

The slice's whole claim is that a design turn survives the death of the process running it. This
file is the proof, end to end against a real database, a real fleet queue, and real leases:

* **kill-and-resume.** Worker A claims a turn (run goes ``running``, stamped with A's id and lease
  generation) and blocks mid-turn. A dies without finishing. Worker B, arriving after the lease
  expires, re-claims the SAME run at a higher generation through the D5 CAS and finishes it. The
  run reaches a terminal status exactly once, and its event stream stays coherent — one terminal
  event, and it is the last.
* **the zombie fence.** A's turn body is a synchronous thread that cannot be cancelled, so it is
  still running after A is gone and eventually tries to write its own terminal result. That write
  is refused by the generation fence: B's result survives untouched. This is the specific hazard
  the design row's ``expected_generation`` guard exists for.
* **concurrency.** Two turns in two different workspaces drain without one blocking the other's
  claim.

Deliberately driven at the WORKER seam rather than over HTTP: the API's contribution (offer the
run + its task in one transaction) is asserted in the design API suite, whereas what needs proving
here is the claim/fence/takeover machinery, which HTTP would only obscure.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId
from clue_db import db_lifespan, transaction
from clue_design import runs as design_runs
from clue_design.enums import DesignRunKind
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.errors import DesignRunFencedError
from clue_fleet.enums import FleetTaskKind
from clue_fleet.lease import DbWorkLeaseStore, LeaseGeneration, WorkId, WorkLeaseRow
from clue_fleet.queue import enqueue_task
from clue_fleet.work_worker import LeasedWorkWorker
from tests.design.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_design_db")

# Short enough that a killed worker's lease expires inside a test, long enough that the
# construction invariant (2 * heartbeat < ttl) holds and a live worker is never fenced by accident.
_LEASE_TTL = timedelta(seconds=2)
_HEARTBEAT = 0.5
_STALE_AFTER = timedelta(seconds=2)
_POLL = 0.05


def _minimal_turn_request(prompt: str) -> dict[str, Any]:
    """The smallest body ``AgentTurnPreviewRequest`` accepts — the envelope's ``config.request``."""
    return {
        "prompt": prompt,
        "scene": {"id": "scene_test", "schema_version": 1, "pages": [], "assets": {}},
        "diagnostics": [],
    }


async def _seed_workspace(conn: AsyncConnection, tag: str) -> str:
    workspace_id = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )
    return workspace_id


async def _offer_turn(workspace_id: str, prompt: str) -> tuple[str, UUID]:
    """Create a queued run and offer its ``design_job`` — the API's one transaction, in
    miniature."""
    run_id = f"run_{uuid4().hex}"
    work_id = design_runs.work_id_for_run(run_id)
    envelope = DesignTurnEnvelope(
        work_id=work_id,
        workspace_id=workspace_id,
        kind="agent_turn",
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        config={"request": _minimal_turn_request(prompt), "reference_assets": None},
    ).model_dump(mode="json")
    async with transaction() as conn:
        await design_runs.create_run(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            document_id=None,
            kind=DesignRunKind.AGENT_TURN,
            payload=envelope,
            work_id=work_id,
        )
        await enqueue_task(
            conn,
            kind=FleetTaskKind.DESIGN_JOB,
            project_run_id=ProjectRunId(work_id),
            dedup_key=str(work_id),
            payload=envelope,
        )
    return run_id, work_id


async def _read_run(workspace_id: str, run_id: str) -> dict[str, Any]:
    async with transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, leased_by, lease_generation, result_json"
                    " FROM design_agent_run WHERE run_id = :r AND workspace_id = :w"
                ),
                {"r": run_id, "w": workspace_id},
            )
        ).one()
    return {
        "status": row.status,
        "leased_by": row.leased_by,
        "lease_generation": row.lease_generation,
        "result": row.result_json,
    }


async def _read_events(workspace_id: str, run_id: str) -> list[dict[str, Any]]:
    async with transaction() as conn:
        return await design_runs.list_run_events(
            conn, workspace_id=workspace_id, run_id=run_id, after_seq=0
        )


async def _await_condition(probe: Any, *, timeout: float = 15.0, label: str = "") -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await probe()
        if value is not None:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError(f"condition never held within {timeout}s: {label}")


def _build_worker(handler: Any, worker_id: str, *, leases: Any = None) -> LeasedWorkWorker:
    return LeasedWorkWorker(
        handlers=(handler,),
        leases=leases,
        worker_id=worker_id,
        poll_interval=_POLL,
        lease_ttl=_LEASE_TTL,
        heartbeat_interval=_HEARTBEAT,
        task_stale_after=_STALE_AFTER,
    )


class _KilledWorkerLeases:
    """A lease store that never releases — what a SIGKILLed worker's lease looks like.

    Cancelling a worker task is NOT a faithful death simulation on its own: ``_run_task``'s
    ``finally`` still runs, and a released lease row is deleted, so the next acquire starts back
    at generation 1 and no takeover is observable. A process that is killed outright never gets
    that far — its lease row sits there, held and un-renewed, until it expires and the next
    acquire increments the generation. That increment is the entire fencing mechanism, so the
    test has to reproduce the real shape rather than the tidy one.
    """

    def __init__(self, inner: DbWorkLeaseStore | None = None) -> None:
        self._inner = inner if inner is not None else DbWorkLeaseStore()

    async def acquire(
        self, *, work_id: WorkId, worker_id: str, ttl: timedelta
    ) -> WorkLeaseRow | None:
        return await self._inner.acquire(work_id=work_id, worker_id=worker_id, ttl=ttl)

    async def renew(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        generation: LeaseGeneration,
        ttl: timedelta,
    ) -> bool:
        return await self._inner.renew(
            work_id=work_id, worker_id=worker_id, generation=generation, ttl=ttl
        )

    async def release(
        self, *, work_id: WorkId, worker_id: str, generation: LeaseGeneration
    ) -> None:
        return None

    async def get(self, work_id: WorkId) -> WorkLeaseRow | None:
        return await self._inner.get(work_id)


class _GatedRunner:
    """A stubbed ``agent_turn_runner``: attempt 1 blocks until released, attempt 2+ returns.

    This is exactly the shape the kill-and-resume scenario needs and nothing more. Attempt 1 is
    the doomed one — it is still inside ``agent.invoke``'s stand-in when its worker dies — and
    attempt 2 is the takeover, which must be able to finish without waiting on the corpse.
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.attempt_1_started = threading.Event()
        self.attempt_1_returned = threading.Event()
        self.attempts = 0
        self._lock = threading.Lock()

    def __call__(self, payload: Any, root: Any) -> dict[str, Any]:
        with self._lock:
            self.attempts += 1
            attempt = self.attempts
        if attempt == 1:
            self.attempt_1_started.set()
            self.release.wait(timeout=30)
            self.attempt_1_returned.set()
            return {"schema_version": 1, "status": "proposed", "summary": "zombie attempt"}
        return {"schema_version": 1, "status": "proposed", "summary": f"attempt {attempt}"}


def test_a_killed_worker_is_taken_over_and_its_zombie_write_is_fenced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from lumen_api.fleet_handler import DesignTurnHost, build_design_job_handler

    caplog.set_level("WARNING", logger="lumen_api.fleet_handler")

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "takeover")
            run_id, work_id = await _offer_turn(workspace_id, "design a poster")

            runner = _GatedRunner()
            # No checkpointer: the stub never builds a graph, so a saver would only add a
            # connection per turn. The checkpointer seam itself is covered by the harness tests.
            handler = build_design_job_handler(
                host_provider=lambda: DesignTurnHost(agent_turn_runner=runner),
                checkpointer_factory=None,
            )

            worker_a = _build_worker(handler, "worker-a", leases=_KilledWorkerLeases())
            task_a = asyncio.create_task(worker_a.run())

            async def claimed_by_a() -> dict[str, Any] | None:
                row = await _read_run(workspace_id, run_id)
                claimed = row["status"] == "running" and row["leased_by"] == "worker-a"
                return row if claimed else None

            first = await _await_condition(claimed_by_a, label="worker A claims the run")
            assert first["lease_generation"] == 1

            async def attempt_1_running() -> bool | None:
                return True if runner.attempt_1_started.is_set() else None

            await _await_condition(attempt_1_running, label="A's turn body is mid-flight")
            assert runner.attempts == 1

            # --- A dies mid-turn. Not a graceful stop: the drive is cancelled outright, exactly
            # as a SIGKILL would, so A never releases its lease and never finalizes its task. The
            # synchronous turn thread it started is NOT cancelled (Python cannot) and is still
            # blocked inside the stub — the zombie.
            task_a.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task_a

            # The lease and the claimed task both have to age out before a takeover is legal.
            await asyncio.sleep(_LEASE_TTL.total_seconds() + 0.5)

            worker_b = _build_worker(handler, "worker-b")
            task_b = asyncio.create_task(worker_b.run())
            try:

                async def finished_by_b() -> dict[str, Any] | None:
                    row = await _read_run(workspace_id, run_id)
                    return row if row["status"] in ("succeeded", "failed") else None

                terminal = await _await_condition(finished_by_b, label="worker B finishes the run")
                assert terminal["status"] == "succeeded"
                assert terminal["leased_by"] == "worker-b"
                # Generations are monotonic: B's claim proves A's lease was superseded.
                assert terminal["lease_generation"] > first["lease_generation"]
                assert terminal["result"]["summary"] == "attempt 2"
                assert runner.attempts == 2

                # --- now let the zombie finish. It will try to complete the SAME run under its
                # stale generation, which is precisely the write the fence exists to refuse.
                runner.release.set()
                assert runner.attempt_1_returned.wait(timeout=15)
                # The zombie's terminal write happens just after its runner returns; give it room
                # to land (or, as asserted below, to be refused).
                await asyncio.sleep(2.0)

                after_zombie = await _read_run(workspace_id, run_id)
                assert after_zombie["result"]["summary"] == "attempt 2", (
                    "the fenced-out zombie overwrote the takeover worker's result"
                )
                assert after_zombie["status"] == "succeeded"
                assert after_zombie["leased_by"] == "worker-b"

                # The SSE-visible stream is coherent: exactly one terminal event, and it is last.
                events = await _read_events(workspace_id, run_id)
                terminal_events = [e for e in events if e["type"] in ("result", "error")]
                assert len(terminal_events) == 1, events
                assert events[-1]["type"] == "result"
                assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)

                # And the refusal was OBSERVED, not merely inferred from an unchanged row: the
                # zombie really did attempt its terminal write and the fence really did refuse it.
                fenced = [
                    record
                    for record in caplog.records
                    if "terminal_write_fenced" in str(record.msg)
                ]
                assert fenced, "the zombie's fenced terminal write was never recorded"
                assert any(
                    str(record.msg).find("'lease_generation': 1") >= 0
                    and str(record.msg).find("'current_generation': 2") >= 0
                    for record in fenced
                ), fenced
            finally:
                worker_b.stop()
                task_b.cancel()
                await asyncio.gather(task_b, return_exceptions=True)

    run_async(scenario())


def test_the_generation_fence_refuses_stale_terminal_writes_and_stale_events() -> None:
    """The fence in isolation — the DAL-level statement of what the scenario above proves."""

    async def scenario() -> None:
        async with db_lifespan(), transaction() as conn:
            workspace_id = await _seed_workspace(conn, "fence")
            run_id = f"run_{uuid4().hex}"
            work_id = design_runs.work_id_for_run(run_id)
            await design_runs.create_run(
                conn, workspace_id=workspace_id, run_id=run_id, document_id=None, work_id=work_id
            )
            # A takeover worker owns the run at generation 5.
            claimed = await design_runs.claim_run_for_execution(
                conn, work_id=work_id, worker_id="worker-live", lease_generation=5
            )
            assert claimed is not None

            # The abandoned generation-1 writer is refused on BOTH durable surfaces.
            with pytest.raises(DesignRunFencedError) as terminal_error:
                await design_runs.complete_run(
                    conn,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    status="failed",
                    result={"summary": "zombie"},
                    event_type="error",
                    expected_generation=1,
                )
            assert terminal_error.value.expected_generation == 1
            assert terminal_error.value.current_generation == 5

            with pytest.raises(DesignRunFencedError):
                await design_runs.append_run_event(
                    conn,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    event_type="progress",
                    data={"from": "zombie"},
                    expected_generation=1,
                )

            # Refused, not partially applied: no result, no status change, no event.
            run = await design_runs.require_run(conn, workspace_id=workspace_id, run_id=run_id)
            assert run["status"] == "running"
            assert run["result"] is None
            assert (
                await design_runs.list_run_events(
                    conn, workspace_id=workspace_id, run_id=run_id, after_seq=0
                )
                == []
            )

            # The LIVE holder writes through the same fence unimpeded.
            await design_runs.complete_run(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                status="succeeded",
                result={"summary": "live"},
                event_type="result",
                expected_generation=5,
            )
            done = await design_runs.require_run(conn, workspace_id=workspace_id, run_id=run_id)
            assert done["status"] == "succeeded"
            assert done["result"] == {"summary": "live"}
            await conn.rollback()

    run_async(scenario())


def test_two_workspaces_drain_concurrently_without_blocking_each_other() -> None:
    from lumen_api.fleet_handler import DesignTurnHost, build_design_job_handler

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_a = await _seed_workspace(conn, "conc_a")
                workspace_b = await _seed_workspace(conn, "conc_b")
            run_a, _ = await _offer_turn(workspace_a, "poster for tenant A")
            run_b, _ = await _offer_turn(workspace_b, "poster for tenant B")

            # Each turn parks until BOTH have been claimed. If the two drains were serialized the
            # first turn could never be released and this test would time out — which is exactly
            # the property being asserted, rather than a timing coincidence.
            both_started = threading.Event()
            started = threading.Semaphore(0)

            def runner(payload: Any, root: Any) -> dict[str, Any]:
                started.release()
                assert both_started.wait(timeout=20)
                return {"schema_version": 1, "status": "proposed", "summary": payload.prompt}

            handler = build_design_job_handler(
                host_provider=lambda: DesignTurnHost(agent_turn_runner=runner),
                checkpointer_factory=None,
            )
            workers = [_build_worker(handler, f"worker-conc-{index}") for index in range(2)]
            tasks = [asyncio.create_task(worker.run()) for worker in workers]
            try:

                async def both_claimed() -> bool | None:
                    return True if started._value >= 2 else None  # noqa: SLF001 - test probe

                await _await_condition(both_claimed, label="both turns claimed concurrently")
                both_started.set()

                async def both_done() -> bool | None:
                    first = await _read_run(workspace_a, run_a)
                    second = await _read_run(workspace_b, run_b)
                    return (
                        True
                        if first["status"] == "succeeded" and second["status"] == "succeeded"
                        else None
                    )

                await _await_condition(both_done, label="both turns complete")

                first = await _read_run(workspace_a, run_a)
                second = await _read_run(workspace_b, run_b)
                assert first["result"]["summary"] == "poster for tenant A"
                assert second["result"]["summary"] == "poster for tenant B"
                assert first["leased_by"] != second["leased_by"]
            finally:
                for worker in workers:
                    worker.stop()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    run_async(scenario())
