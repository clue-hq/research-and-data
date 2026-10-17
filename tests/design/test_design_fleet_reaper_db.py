"""D5 Round C acceptance: nothing stays ``running`` forever, and ingestion claims like a turn.

Round B proved a design turn survives its worker's death. This file proves the two holes that
were left open when the worker does not merely die mid-turn but fails to record ANYTHING:

* **In-handler containment.** A handler exception — a store/infrastructure fault, not a failed
  turn — used to mark only the FLEET task failed and leave the design row ``running`` with nobody
  coming for it. Now the handler terminalizes the row itself, under the lease fence, and reports
  the failure honestly in its ``WorkResult``.
* **The reaper, and its exact policy: re-offer once, then fail.** When even the containment write
  cannot land (the store is unreachable, or the process is killed outright), the row IS left
  ``running``. The reaper finds it — ``running``, no live lease, terminal fleet task — hands it
  back to ``queued`` exactly once, and terminalizes it ``failed`` with the ``design.stranded``
  code the second time. A row that is genuinely being driven (a LIVE lease) is never touched.
* **Ingestion claims exactly like a turn.** Brand-kit ingestion moved onto the same ``design_job``
  queue, so its claim CAS has to agree with the run CAS on every case — including takeover, which
  is what makes a re-offered job runnable at all.

Driven at the DAL/reaper seam rather than over HTTP: what needs proving is the recovery
machinery. The API's own contribution (offer job + task in one transaction, worker drains it) is
asserted end to end in the design API suite.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from lumen_api import run_stream
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import DESIGN_RUN_SUBJECT_KIND, ProjectRunId
from clue_db import db_lifespan, transaction
from clue_design import ingestion as design_ingestion
from clue_design import runs as design_runs
from clue_design.enums import DesignIngestionKind, DesignRunKind
from clue_design.envelopes import DesignIngestionEnvelope, DesignTurnEnvelope
from clue_design.errors import DesignNotFoundError
from clue_execution.run_events import list_run_events
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import WorkId, acquire_work_lease
from clue_fleet.queue import enqueue_task
from clue_fleet.work_worker import LeasedWorkWorker

pytestmark = pytest.mark.usefixtures("require_design_db")

_LEASE_TTL = timedelta(seconds=2)
_HEARTBEAT = 0.5
_STALE_AFTER = timedelta(seconds=2)
_POLL = 0.05


# --- fixtures in the small sense: seeds and probes ---------------------------------------------


async def _seed_workspace(conn: AsyncConnection, tag: str) -> str:
    workspace_id = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )
    return workspace_id


def _minimal_turn_request(prompt: str) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "scene": {"id": "scene_test", "schema_version": 1, "pages": [], "assets": {}},
        "diagnostics": [],
    }


async def _offer_turn(workspace_id: str, prompt: str) -> tuple[str, UUID]:
    """The API's one transaction, in miniature: a queued run plus its ``design_job``."""
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


async def _offer_ingestion(workspace_id: str) -> tuple[str, UUID]:
    """The ingestion route's one transaction, in miniature."""
    job_id = design_ingestion.new_id("ingest")
    work_id = uuid4()
    envelope = DesignIngestionEnvelope(
        work_id=work_id,
        workspace_id=workspace_id,
        kind="ingestion",
        job_id=job_id,
        ingestion_kind=DesignIngestionKind.WEBSITE,
    ).model_dump(mode="json")
    async with transaction() as conn:
        await design_ingestion.create_job(
            conn,
            workspace_id=workspace_id,
            kind="website",
            request={"url": "https://example.test"},
            job_id=job_id,
            work_id=work_id,
        )
        await enqueue_task(
            conn,
            kind=FleetTaskKind.DESIGN_JOB,
            project_run_id=ProjectRunId(work_id),
            dedup_key=str(work_id),
            payload=envelope,
        )
    return job_id, work_id


async def _read_run(workspace_id: str, run_id: str) -> dict[str, Any]:
    async with transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, leased_by, lease_generation, reoffer_count, result_json"
                    " FROM design_agent_run WHERE run_id = :r AND workspace_id = :w"
                ),
                {"r": run_id, "w": workspace_id},
            )
        ).one()
    return {
        "status": row.status,
        "leased_by": row.leased_by,
        "lease_generation": row.lease_generation,
        "reoffer_count": row.reoffer_count,
        "result": row.result_json,
    }


async def _force_task_status(work_id: UUID, status: FleetTaskStatus) -> None:
    """Put this work id's fleet task into ``status`` directly.

    Reproducing the real sequence (claim it, kill the worker, let the drive record FAILED) would
    take a live worker and a lease timeout to say the same thing the reaper actually reads: the
    task is terminal. The reaper's INPUT is what is under test here, not how the queue got there
    — the queue's own transitions are covered by ``tests/fleet``.
    """
    claimed = status is FleetTaskStatus.CLAIMED
    async with transaction() as conn:
        await conn.execute(
            text(
                "UPDATE fleet_task SET status = CAST(:s AS fleet_task_status),"
                # ``fleet_task_claim_stamped`` requires the holder columns iff the row is
                # CLAIMED, so they are set together rather than blanket-cleared.
                " claimed_by = CASE WHEN :claimed THEN 'worker-holder' ELSE NULL END,"
                " claimed_at = CASE WHEN :claimed THEN now() ELSE NULL END"
                " WHERE work_id = :w AND kind = CAST(:k AS fleet_task_kind)"
            ),
            {
                "s": status.value,
                "claimed": claimed,
                "w": work_id,
                "k": FleetTaskKind.DESIGN_JOB.value,
            },
        )


async def _force_run_running(work_id: UUID, *, worker_id: str = "worker-dead") -> None:
    """Claim the run the way a worker would, then abandon it — a stranded ``running`` row."""
    async with transaction() as conn:
        claimed = await design_runs.claim_run_for_execution(
            conn, work_id=work_id, worker_id=worker_id, lease_generation=1
        )
        assert claimed is not None


async def _read_task_status(work_id: UUID) -> str | None:
    async with transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status FROM fleet_task WHERE work_id = :w"
                    " AND kind = CAST(:k AS fleet_task_kind) ORDER BY enqueue_seq DESC LIMIT 1"
                ),
                {"w": work_id, "k": FleetTaskKind.DESIGN_JOB.value},
            )
        ).first()
    return None if row is None else row.status


def _build_worker(handler: Any, worker_id: str) -> LeasedWorkWorker:
    return LeasedWorkWorker(
        handlers=(handler,),
        worker_id=worker_id,
        poll_interval=_POLL,
        lease_ttl=_LEASE_TTL,
        heartbeat_interval=_HEARTBEAT,
        task_stale_after=_STALE_AFTER,
    )


async def _await_condition(probe: Any, *, timeout: float = 15.0, label: str = "") -> Any:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        value = await probe()
        if value is not None:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError(f"condition never held within {timeout}s: {label}")


async def _purge_work(*work_ids: UUID) -> None:
    """Erase every trace of this test's work — the queue row, the lease, and the design row.

    TWO shared-state hazards make this mandatory rather than tidy, and both bit on the way in:

    * ``fleet_task`` / ``work_lease`` are ONE table pair for the whole suite. A leftover
      ``queued`` design task is handed to the NEXT test's worker, which then drains a run it
      knows nothing about (the Round-B "cross-test queue bleed" residual — it misattributed a
      worker in the concurrency test).
    * The reaper sweeps the DATABASE, not a workspace. A test that deliberately leaves a
      ``running`` design row behind (the live-lease and still-queued cases do, on purpose) is
      *stranded work* to the next test's reaper pass, which dutifully re-offers it — re-creating
      the very queue row the first bullet forbids. Deleting the design row closes that loop.

    Deleting rather than terminalizing on purpose: a terminal row is inert to the reaper, but it
    would still be scanned forever by every later pass, and the point is to leave nothing.
    """
    async with transaction() as conn:
        for work_id in work_ids:
            await conn.execute(text("DELETE FROM fleet_task WHERE work_id = :w"), {"w": work_id})
            await conn.execute(text("DELETE FROM work_lease WHERE work_id = :w"), {"w": work_id})
            await conn.execute(
                text("DELETE FROM design_agent_run WHERE work_id = :w"), {"w": work_id}
            )
            await conn.execute(
                text("DELETE FROM design_ingestion_job WHERE work_id = :w"), {"w": work_id}
            )


class _ExplodingCheckpointer:
    """A checkpointer factory that raises — the cheapest faithful "the store fell over" fault.

    It fires INSIDE ``_execute_turn``, i.e. inside the worker thread and after the run has already
    been claimed, which is exactly the window that used to strand a row: the claim landed, the
    terminal write never did. Raising anywhere earlier (in ``handle`` itself) would test the
    fleet's generic error path instead of the design handler's containment.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, thread_id: str) -> Any:
        self.calls += 1
        raise RuntimeError("simulated store fault inside the claimed turn")


# --- 1. in-handler containment -----------------------------------------------------------------


def test_a_handler_exception_terminalizes_the_run_instead_of_stranding_it() -> None:
    from lumen_api.fleet_handler import DesignTurnHost, build_design_job_handler

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "contain")
            run_id, work_id = await _offer_turn(workspace_id, "explode please")

            exploding = _ExplodingCheckpointer()
            handler = build_design_job_handler(
                host_provider=lambda: DesignTurnHost(agent_turn_runner=lambda *a, **k: {}),
                checkpointer_factory=exploding,
            )
            worker = _build_worker(handler, "worker-contained")
            task = asyncio.create_task(worker.run())
            try:

                async def terminal() -> dict[str, Any] | None:
                    row = await _read_run(workspace_id, run_id)
                    return row if row["status"] in ("succeeded", "failed") else None

                row = await _await_condition(terminal, label="the handler contains its own fault")
            finally:
                worker.stop()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

            assert exploding.calls >= 1
            # The row is terminal, NOT stranded 'running' — the whole point.
            assert row["status"] == "failed"
            assert row["result"]["error"]["code"] == "design_job.handler_error"
            assert "simulated store fault" in row["result"]["error"]["message"]

            # And the SSE-visible stream carries its terminal marker, so a subscriber settles.
            async with transaction() as conn:
                events = await run_stream.run_snapshot_events(
                    conn, workspace_id=workspace_id, run_id=run_id
                )
            assert [event["type"] for event in events][-1] == "error"
            await _purge_work(work_id)

    asyncio.run(scenario())


# --- 2. the reaper: re-offer once, then fail ---------------------------------------------------


def test_the_reaper_reoffers_a_stranded_run_once_then_terminalizes_it() -> None:
    from lumen_api.fleet_reaper import STRANDED_CODE, run_reaper_pass

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "reap")
            run_id, work_id = await _offer_turn(workspace_id, "strand me")

            # The shape a worker leaves behind when it cannot even record its own failure: the
            # run is claimed and running, its task is terminal, and no lease covers it.
            await _force_run_running(work_id)
            await _force_task_status(work_id, FleetTaskStatus.FAILED)

            # --- pass 1: re-offered, not failed.
            #
            # The sweep is DATABASE-WIDE by construction (a stranded row belongs to whichever
            # tenant owns it), and this suite shares one database, so the counters are asserted
            # as lower bounds and THIS row is asserted exactly. A counter equality here would be
            # a test that fails whenever a sibling test happens to leave a row behind.
            first = await run_reaper_pass(transaction, stranded_after_s=0)
            assert first.reoffered >= 1, first

            row = await _read_run(workspace_id, run_id)
            assert row["status"] == "queued"
            assert row["reoffer_count"] == 1
            # The dead attempt's stamp is KEPT (2026-10-16; it used to be cleared). Lease
            # generations never repeat, so the next claimant always holds a higher one and
            # re-stamps the row at its claim; until then the row still fences on the dead one.
            assert (row["leased_by"], row["lease_generation"]) == ("worker-dead", 1)
            # And a task actually exists again — a queued row with no task is a WORSE strand.
            assert await _read_task_status(work_id) == FleetTaskStatus.QUEUED.value

            # --- the re-offered attempt strands too.
            await _force_run_running(work_id, worker_id="worker-dead-again")
            await _force_task_status(work_id, FleetTaskStatus.FAILED)

            # --- pass 2: the budget is spent, so it is terminalized.
            second = await run_reaper_pass(transaction, stranded_after_s=0)
            assert second.failed >= 1, second

            row = await _read_run(workspace_id, run_id)
            assert row["status"] == "failed"
            assert row["result"]["error"]["code"] == STRANDED_CODE
            assert row["reoffer_count"] == 1

            async with transaction() as conn:
                events = await run_stream.run_snapshot_events(
                    conn, workspace_id=workspace_id, run_id=run_id
                )
                rows = await list_run_events(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind=DESIGN_RUN_SUBJECT_KIND,
                    subject_id=run_id,
                )
            assert events[-1]["type"] == "error"
            assert STRANDED_CODE in events[-1]["data"]["message"]
            # D7 (R-D7-B2): the reaper's terminal event is SELF-CONTAINED — it carries the stranded
            # result envelope in its own payload, so the SSE ``done`` frame is built from the event
            # alone and never re-reads the run row after a terminal.
            assert rows[-1].topic == run_stream.FAILED_TOPIC
            assert rows[-1].payload["result"]["error"]["code"] == STRANDED_CODE

            # --- pass 3 leaves it alone: a terminal row is never re-judged.
            await run_reaper_pass(transaction, stranded_after_s=0)
            again = await _read_run(workspace_id, run_id)
            assert (again["status"], again["reoffer_count"]) == ("failed", 1)
            assert again["result"]["error"]["code"] == STRANDED_CODE
            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_reaper_never_touches_a_run_under_a_live_lease() -> None:
    from lumen_api.fleet_reaper import run_reaper_pass

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "live")
            run_id, work_id = await _offer_turn(workspace_id, "leave me alone")
            await _force_run_running(work_id, worker_id="worker-alive")

            # The adversarial arrangement on purpose: the task row LOOKS terminal (the shape that
            # otherwise means "stranded"), but a live lease says someone is driving this right
            # now. The lease is the authoritative fence, so it must win.
            await _force_task_status(work_id, FleetTaskStatus.FAILED)
            async with transaction() as conn:
                lease = await acquire_work_lease(
                    conn,
                    work_id=WorkId(work_id),
                    worker_id="worker-alive",
                    ttl=timedelta(seconds=120),
                )
            assert lease is not None and lease.live

            sweep = await run_reaper_pass(transaction, stranded_after_s=0)
            assert sweep.skipped_live >= 1, sweep

            row = await _read_run(workspace_id, run_id)
            assert row["status"] == "running"
            assert row["leased_by"] == "worker-alive"
            assert row["reoffer_count"] == 0
            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_reaper_leaves_a_still_queued_task_alone() -> None:
    """A row whose task is queued or claimed is on its way to a worker, not stranded."""
    from lumen_api.fleet_reaper import run_reaper_pass

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "queued")
            run_id, work_id = await _offer_turn(workspace_id, "still coming")
            await _force_run_running(work_id)
            await _force_task_status(work_id, FleetTaskStatus.CLAIMED)

            await run_reaper_pass(transaction, stranded_after_s=0)
            row = await _read_run(workspace_id, run_id)
            assert (row["status"], row["reoffer_count"]) == ("running", 0)
            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_reaper_recovers_a_stranded_ingestion_job_the_same_way() -> None:
    from lumen_api.fleet_reaper import STRANDED_CODE, run_reaper_pass

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "reapjob")
            job_id, work_id = await _offer_ingestion(workspace_id)

            async with transaction() as conn:
                claimed = await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="worker-dead", lease_generation=1
                )
            assert claimed is not None and claimed["status"] == "running"
            await _force_task_status(work_id, FleetTaskStatus.FAILED)

            first = await run_reaper_pass(transaction, stranded_after_s=0)
            assert first.reoffered >= 1, first
            async with transaction() as conn:
                job = await design_ingestion.require_job(
                    conn, workspace_id=workspace_id, job_id=job_id
                )
            assert job["status"] == "queued"
            # The rebuilt envelope has to be executable by a real worker, not merely well-shaped:
            # parse it back through the same union the handler parses.
            async with transaction() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT payload_json FROM fleet_task WHERE work_id = :w"
                            " AND kind = CAST(:k AS fleet_task_kind)"
                        ),
                        {"w": work_id, "k": FleetTaskKind.DESIGN_JOB.value},
                    )
                ).one()
            payload = row.payload_json
            if isinstance(payload, (bytes, bytearray, str)):
                import json

                payload = json.loads(payload)
            reoffered = DesignIngestionEnvelope.model_validate(payload)
            assert reoffered.job_id == job_id
            assert reoffered.workspace_id == workspace_id
            assert reoffered.ingestion_kind is DesignIngestionKind.WEBSITE

            async with transaction() as conn:
                await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="worker-dead-2", lease_generation=2
                )
            await _force_task_status(work_id, FleetTaskStatus.FAILED)

            second = await run_reaper_pass(transaction, stranded_after_s=0)
            assert second.failed >= 1, second
            async with transaction() as conn:
                job = await design_ingestion.require_job(
                    conn, workspace_id=workspace_id, job_id=job_id
                )
            assert job["status"] == "failed"
            assert job["error"]["code"] == STRANDED_CODE
            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_reaper_ignores_an_ingestion_job_that_was_never_dispatched() -> None:
    """A direct/CLI ingestion has no fleet task, so there is nothing to judge it against."""
    from lumen_api.fleet_reaper import run_reaper_pass

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "direct")
                job = await design_ingestion.create_job(
                    conn,
                    workspace_id=workspace_id,
                    kind="website",
                    request={"url": "https://direct.test"},
                )
                await design_ingestion.set_running(
                    conn, workspace_id=workspace_id, job_id=job["job_id"]
                )

            await run_reaper_pass(transaction, stranded_after_s=0)
            async with transaction() as conn:
                after = await design_ingestion.require_job(
                    conn, workspace_id=workspace_id, job_id=job["job_id"]
                )
            assert after["status"] == "running"

    asyncio.run(scenario())


# --- 3. the ingestion claim CAS agrees with the run CAS ----------------------------------------


def test_ingestion_claim_cas_matches_the_run_cas_case_for_case() -> None:
    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "claim")
            job_id, work_id = await _offer_ingestion(workspace_id)

            async with transaction() as conn:
                # queued -> running.
                first = await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="w1", lease_generation=1
                )
                assert first is not None
                assert first["status"] == "running"
                assert first["leased_by"] == "w1"
                assert first["lease_generation"] == 1
                assert first["workspace_id"] == workspace_id

                # same generation -> idempotent re-claim (at-least-once redelivery).
                again = await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="w1", lease_generation=1
                )
                assert again is not None and again["lease_generation"] == 1

                # a LOWER generation is fenced out and must not overwrite the holder's stamp.
                async with conn.begin_nested():
                    refused = await design_ingestion.claim_job_for_execution(
                        conn, work_id=work_id, worker_id="w0", lease_generation=0
                    )
                assert refused is None
                held = await design_ingestion.get_job_by_work_id(conn, work_id=work_id)
                assert held is not None and held["leased_by"] == "w1"

                # a HIGHER generation takes over a running row.
                taken = await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="w2", lease_generation=7
                )
                assert taken is not None
                assert taken["leased_by"] == "w2" and taken["lease_generation"] == 7

                # terminal work is never re-claimed.
                await design_ingestion.fail(
                    conn,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    error={"code": "x", "message": "done"},
                )
                assert (
                    await design_ingestion.claim_job_for_execution(
                        conn, work_id=work_id, worker_id="w3", lease_generation=9
                    )
                    is None
                )

                # an unknown work id is a POISON task, not a refusal — a different answer.
                with pytest.raises(DesignNotFoundError):
                    await design_ingestion.claim_job_for_execution(
                        conn, work_id=uuid4(), worker_id="w3", lease_generation=1
                    )
            await _purge_work(work_id)

    asyncio.run(scenario())


def test_a_fenced_ingestion_write_is_refused_rather_than_clobbering_the_takeover() -> None:
    """The zombie fence, at the ingestion DAL: a stale writer's terminal write cannot land."""
    from clue_design.errors import DesignJobFencedError

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "fence")
            job_id, work_id = await _offer_ingestion(workspace_id)

            async with transaction() as conn:
                await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="w1", lease_generation=1
                )
                # A takeover claims the same job under a newer generation.
                await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="w2", lease_generation=2
                )

                # The abandoned attempt (generation 1) tries to finish. Every one of its writes
                # is refused, so a stale progress stamp cannot appear either.
                for write in (
                    lambda: design_ingestion.set_stage(
                        conn,
                        workspace_id=workspace_id,
                        job_id=job_id,
                        stage="zombie",
                        progress=0.5,
                        expected_generation=1,
                    ),
                    lambda: design_ingestion.fail(
                        conn,
                        workspace_id=workspace_id,
                        job_id=job_id,
                        error={"code": "zombie", "message": "should never land"},
                        expected_generation=1,
                    ),
                ):
                    async with conn.begin_nested():
                        with pytest.raises(DesignJobFencedError) as excinfo:
                            await write()
                    assert excinfo.value.expected_generation == 1
                    assert excinfo.value.current_generation == 2

                job = await design_ingestion.require_job(
                    conn, workspace_id=workspace_id, job_id=job_id
                )
                assert job["status"] == "running"
                assert job["stage"] is None
                assert job["error"] is None

                # The takeover's own write, at the current generation, lands normally.
                done = await design_ingestion.fail(
                    conn,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    error={"code": "real", "message": "the live attempt's outcome"},
                    expected_generation=2,
                )
                assert done["status"] == "failed"
                assert done["error"]["code"] == "real"
            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_reaper_loop_deletes_expired_site_turn_conversations_with_the_configured_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each reaper pass also runs the conversation retention (founder 2026-10-17: a finished site
    turn's conversation is kept 96 h for debugging, then deleted), in its own transaction, with
    the configured retention; a fault there never stops the loop."""
    import asyncio
    import contextlib

    from lumen_api import fleet_reaper

    seen: list[float] = []

    async def fake_prune(conn, *, retain_s: float) -> int:
        seen.append(retain_s)
        if len(seen) == 1:
            raise RuntimeError("database hiccup")  # the loop must carry on
        return 2

    async def fake_pass(conn_factory, *, stranded_after_s: float):
        return fleet_reaper.ReaperSweep(
            considered=0, skipped_live=0, skipped_queued=0, reoffered=0, failed=0
        )

    @contextlib.asynccontextmanager
    async def fake_conn():
        yield object()

    sleeps = {"n": 0}

    async def fake_sleep(_seconds: float) -> None:
        sleeps["n"] += 1
        if sleeps["n"] > 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(fleet_reaper, "prune_expired_site_turn_checkpoints", fake_prune)
    monkeypatch.setattr(fleet_reaper, "run_reaper_pass", fake_pass)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(fleet_reaper.reaper_loop(
            interval_s=1,
            conn_factory=fake_conn,
            sleep=fake_sleep,
            conversation_retention_s=345_600.0,
        ))
    assert seen == [345_600.0, 345_600.0]

