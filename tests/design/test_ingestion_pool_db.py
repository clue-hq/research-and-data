"""Real queue/lease proof with four OS processes and forty mocked vision calls."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from lumen_api.fleet_handler import build_design_job_handler
from lumen_api.ingestion_tasks import (
    AssetAnalysisWorkHandler,
    enqueue_and_collect,
    offer_images,
    require_asset_lease,
)
from sqlalchemy import text

from clue_core import ProjectRunId
from clue_db import db_lifespan, transaction
from clue_design import descriptions, ingestion
from clue_design.errors import DesignJobFencedError
from clue_fleet import LeasedWorkWorker
from clue_fleet.enums import FleetTaskKind
from clue_fleet.lease import WorkId, acquire_work_lease
from clue_fleet.queue import claim_next_task, enqueue_task
from clue_fleet.work_worker import WorkContext
from tests.design.test_asset_context import PNG, analysis
from tests.design.test_ingestion_descriptions_dal_db import _seed_asset, _seed_ws

pytestmark = pytest.mark.usefixtures("require_design_db")


async def seed(count):
    async with db_lifespan(), transaction() as conn:
        ws = await _seed_ws(conn)
        job_id = f"ingest_{uuid4().hex}"
        work_id = uuid4()
        await ingestion.create_job(
            conn, workspace_id=ws, kind="website", request={}, job_id=job_id, work_id=work_id
        )
        await ingestion.claim_job_for_execution(
            conn, work_id=work_id, worker_id="test-coordinator", lease_generation=1
        )
        targets = {await _seed_asset(conn, ws): {} for _ in range(count)}
        tasks = await offer_images(
            conn, workspace_id=ws, job_id=job_id, generation=1, targets=targets
        )
        replay = await offer_images(
            conn, workspace_id=ws, job_id=job_id, generation=1, targets=targets
        )
        assert replay == tasks
        return ws, job_id, targets, tasks


async def cleanup(ws, tasks):
    async with db_lifespan(), transaction() as conn:
        await conn.execute(
            text("DELETE FROM fleet_task WHERE work_id = ANY(:ids)"), {"ids": list(tasks.values())}
        )
        await conn.execute(
            text("DELETE FROM work_lease WHERE work_id = ANY(:ids)"), {"ids": list(tasks.values())}
        )
        for table in (
            "design_asset_description",
            "design_asset",
            "design_ingestion_job",
            "workspace",
        ):
            await conn.execute(text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": ws})


def analysis_process(barrier, calls, stopped):
    from lumen_ingestion.describe import DescribeResult

    class Describer:
        active = True
        model = "test/vision"

        def describe(self, items):
            assert len(items) == 1
            calls.append((os.getpid(), items[0].asset_id))
            barrier.wait(timeout=45)  # Forty simultaneous calls, not sequential batches.
            data = analysis(items[0].asset_id)
            return [
                DescribeResult(
                    items[0].asset_id,
                    data["title"],
                    data["description"],
                    data["usage"],
                    data["tags"],
                    data,
                )
            ]

    async def run():
        worker = LeasedWorkWorker(
            handlers=(AssetAnalysisWorkHandler(),), concurrency=10, poll_interval=0.05
        )

        async def watch():
            while not stopped.is_set():
                await asyncio.sleep(0.05)
            worker.stop()

        async with db_lifespan():
            task = asyncio.create_task(watch())
            try:
                await worker.run()
            finally:
                task.cancel()

    with (
        patch("lumen_ingestion.pipeline.resolve_describer", return_value=Describer()),
        patch(
            "lumen_ingestion.pipeline._make_resolve_bytes",
            return_value=lambda _: (PNG, "image/png"),
        ),
        patch("lumen_ingestion.pipeline._make_rasterize_svg", return_value=None),
    ):
        asyncio.run(run())


def test_four_processes_run_forty_image_tasks_and_primary_cannot_claim_them():
    ws, job_id, targets, tasks = asyncio.run(seed(40))
    ctx = multiprocessing.get_context("spawn")
    workers = []
    try:

        async def primary():
            async with db_lifespan(), transaction() as conn:
                return await claim_next_task(
                    conn,
                    kind=FleetTaskKind.DESIGN_JOB,
                    worker_id="primary-proof",
                    project_run_id=ProjectRunId(next(iter(tasks.values()))),
                    capabilities=build_design_job_handler().task_capabilities,
                )

        assert asyncio.run(primary()) is None
        with ctx.Manager() as manager:
            calls, barrier, stopped = manager.list(), manager.Barrier(40), ctx.Event()
            workers = [
                ctx.Process(target=analysis_process, args=(barrier, calls, stopped))
                for _ in range(4)
            ]
            for worker in workers:
                worker.start()

            async def finished():
                async with db_lifespan():
                    deadline = time.monotonic() + 65
                    while time.monotonic() < deadline:
                        async with transaction() as conn:
                            rows = (
                                await conn.execute(
                                    text("""
                                SELECT status, result_ref_json FROM fleet_task
                                WHERE work_id = ANY(:ids)
                            """),
                                    {"ids": list(tasks.values())},
                                )
                            ).all()
                        if all(r.status in {"done", "failed"} for r in rows):
                            return rows
                        await asyncio.sleep(0.1)
                    raise AssertionError("image tasks did not finish")

            rows = asyncio.run(finished())
            stopped.set()
            for worker in workers:
                worker.join(timeout=15)
            assert all(w.exitcode == 0 for w in workers)
            assert len(calls) == 40
            assert len({pid for pid, _ in calls}) == 4
            assert len({asset for _, asset in calls}) == 40
            assert all(
                r.status == "done" and r.result_ref_json["analysis_status"] == "ready" for r in rows
            )
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=10)
        asyncio.run(cleanup(ws, tasks))


def test_parent_takeover_and_expired_child_lease_block_result_writes():
    ws, job_id, targets, tasks = asyncio.run(seed(1))
    try:

        async def scenario():
            async with db_lifespan(), transaction() as conn:
                task = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.DESIGN_JOB,
                    worker_id="analysis",
                    capabilities=AssetAnalysisWorkHandler.task_capabilities,
                )
                lease = await acquire_work_lease(
                    conn, work_id=WorkId(task.project_run_id), worker_id="analysis"
                )
                context = WorkContext(
                    task_id=task.task_id,
                    work_id=WorkId(task.project_run_id),
                    worker_id="analysis",
                    lease_generation=lease.generation,
                    payload=task.payload,
                    stop_requested=asyncio.Event(),
                    lease_lost=asyncio.Event(),
                )
                await require_asset_lease(conn, context)
                await conn.execute(
                    text(
                        "UPDATE work_lease SET expires_at = now() - interval '1 second' "
                        "WHERE work_id=:id"
                    ),
                    {"id": task.project_run_id},
                )
                with pytest.raises(DesignJobFencedError):
                    await require_asset_lease(conn, context)
                await conn.execute(
                    text(
                        "UPDATE work_lease SET expires_at = now() + interval '1 minute' "
                        "WHERE work_id=:id"
                    ),
                    {"id": task.project_run_id},
                )
                await conn.execute(
                    text("UPDATE design_ingestion_job SET lease_generation=2 WHERE job_id=:j"),
                    {"j": job_id},
                )
                with pytest.raises(DesignJobFencedError):
                    await require_asset_lease(conn, context)

        asyncio.run(scenario())
    finally:
        asyncio.run(cleanup(ws, tasks))


def test_terminal_child_failure_clears_stranded_analysis_without_hanging_parent():
    ws, job_id, targets, tasks = asyncio.run(seed(1))
    asset_id, work_id = next(iter(tasks.items()))
    try:

        async def strand():
            async with db_lifespan(), transaction() as conn:
                row = await descriptions.prepare_analysis(
                    conn, workspace_id=ws, asset_id=asset_id, analysis_input={}, job_id=job_id
                )
                await descriptions.begin_analysis(
                    conn,
                    workspace_id=ws,
                    asset_id=asset_id,
                    input_fingerprint=row["input_fingerprint"],
                    token="stranded",
                    job_id=job_id,
                )
                await conn.execute(
                    text("UPDATE fleet_task SET status='failed' WHERE work_id=:id"),
                    {"id": work_id},
                )

        asyncio.run(strand())
        result = enqueue_and_collect(
            targets, workspace_id=ws, job_id=job_id, generation=1, reporter=lambda *_: None
        )
        assert result["pending"] == result["ready"] == 0
        assert result["failed"] == 1
        assert result["results"][asset_id]["status"] == "failed"

        async def persisted():
            async with db_lifespan(), transaction() as conn:
                return (
                    await conn.execute(
                        text(
                            "SELECT analysis_status, analysis_token FROM design_asset_description "
                            "WHERE workspace_id=:w AND asset_id=:a"
                        ),
                        {"w": ws, "a": asset_id},
                    )
                ).one()

        row = asyncio.run(persisted())
        assert row.analysis_status == "failed" and row.analysis_token is None
    finally:
        asyncio.run(cleanup(ws, tasks))


def test_sql_claims_route_each_pool_and_skip_missing_kind():
    async def scenario():
        async with db_lifespan() as engine, engine.connect() as conn:
            tx = await conn.begin()
            try:
                ids = {
                    kind: uuid4()
                    for kind in ("missing", "ingestion", "asset_analysis", "agent_turn")
                }
                for kind, work_id in ids.items():
                    payload = {} if kind == "missing" else {"kind": kind}
                    if kind == "ingestion":
                        payload["ingestion_kind"] = "website"
                    await enqueue_task(
                        conn,
                        kind=FleetTaskKind.DESIGN_JOB,
                        project_run_id=ProjectRunId(work_id),
                        dedup_key=str(work_id),
                        payload=payload,
                    )
                for name, handler in [
                    ("agent_turn", build_design_job_handler()),
                    ("ingestion", build_design_job_handler(ingestion_only=True)),
                    ("asset_analysis", AssetAnalysisWorkHandler()),
                ]:
                    for offered_kind, work_id in ids.items():
                        row = await claim_next_task(
                            conn,
                            kind=FleetTaskKind.DESIGN_JOB,
                            project_run_id=ProjectRunId(work_id),
                            worker_id=name,
                            capabilities=handler.task_capabilities,
                        )
                        assert (row is not None) == (offered_kind == name)
            finally:
                await tx.rollback()

    asyncio.run(scenario())
