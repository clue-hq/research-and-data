"""Durable per-image tasks on the existing fleet; no provider work in the coordinator."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from clue_core import ProjectRunId
from clue_design import descriptions
from clue_design.asset_context import fingerprint
from clue_design.envelopes import AssetAnalysisEnvelope
from clue_design.errors import DesignJobFencedError
from clue_fleet.enums import FleetTaskKind
from clue_fleet.queue import TaskCapability, enqueue_task
from clue_fleet.work_worker import WorkContext, WorkResult
from py_lumen_config import settings
from sqlalchemy import text

from .design_store import DesignStoreBridge


async def require_parent(conn, workspace_id: str, job_id: str, generation: int) -> None:
    row = (
        await conn.execute(
            text("""
        SELECT lease_generation, status FROM design_ingestion_job
        WHERE workspace_id = :w AND job_id = :j FOR SHARE
    """),
            {"w": workspace_id, "j": job_id},
        )
    ).first()
    if row is None or row.lease_generation != generation or row.status != "running":
        raise DesignJobFencedError(job_id, generation, row.lease_generation if row else None)


async def require_asset_lease(conn, context: WorkContext) -> None:
    envelope = AssetAnalysisEnvelope.model_validate(context.payload)
    # Lock order is parent then child; both locks cover the result transaction.
    await require_parent(conn, envelope.workspace_id, envelope.job_id, envelope.parent_generation)
    row = (
        await conn.execute(
            text("""
        SELECT generation FROM work_lease WHERE work_id = :id AND worker_id = :worker
          AND generation = :generation AND expires_at > now() FOR SHARE
    """),
            {
                "id": envelope.work_id,
                "worker": context.worker_id,
                "generation": int(context.lease_generation),
            },
        )
    ).first()
    if row is None or context.lease_lost.is_set() or context.stop_requested.is_set():
        raise DesignJobFencedError(str(envelope.work_id), int(context.lease_generation), None)


def image_envelope(workspace_id, job_id, generation, asset_id, target):
    # A parent takeover gets fresh child tasks; cached fingerprints avoid repeat model calls.
    key = fingerprint(
        {
            "workspace": workspace_id,
            "job": job_id,
            "generation": generation,
            "asset": asset_id,
            "target": target,
        }
    )
    return AssetAnalysisEnvelope(
        work_id=uuid5(NAMESPACE_URL, f"clue:asset-analysis:{key}"),
        workspace_id=workspace_id,
        job_id=job_id,
        parent_generation=generation,
        asset_id=asset_id,
        target=target,
    )


async def offer_images(conn, *, workspace_id, job_id, generation, targets):
    await require_parent(conn, workspace_id, job_id, generation)
    offered = {}
    for asset_id, target in targets.items():
        envelope = image_envelope(workspace_id, job_id, generation, asset_id, target)
        await enqueue_task(
            conn,
            kind=FleetTaskKind.DESIGN_JOB,
            project_run_id=ProjectRunId(envelope.work_id),
            dedup_key=str(envelope.work_id),
            payload=envelope.model_dump(mode="json"),
            reopen_terminal=False,
        )
        offered[asset_id] = envelope.work_id
    return offered


def collect_summary(targets, tasks, rows):
    """Only terminal child tasks count as completed, including hard worker failures."""
    summary = {
        "total": len(targets),
        "ready": 0,
        "failed": 0,
        "unsupported": 0,
        "pending": 0,
        "cached": 0,
        "concurrency": settings.lumen_ingestion_pool_workers
        * settings.lumen_ingestion_worker_concurrency,
        "results": {},
    }
    for asset_id, work_id in targets.items():
        task = tasks.get(work_id)
        if task is None or task["status"] not in {"done", "failed"}:
            summary["pending"] += 1
            continue
        result = task.get("result") or {}
        status = result.get("analysis_status", "failed")
        row = rows.get(asset_id, {})
        if task["status"] == "failed" or status not in {
            "ready",
            "failed",
            "unsupported",
        }:
            status = "failed"
        if status == "ready" and row.get("status") != "ready":
            status = "failed"  # A newer input invalidated this task's result.
        if status == "failed":
            row = {
                **row,
                "status": "failed",
                "diagnostic": row.get("diagnostic")
                or {
                    "code": "asset_task_failed",
                    "message": "Image worker did not complete analysis",
                    "retryable": True,
                },
            }
        summary[status] += 1
        summary["cached"] += int(bool(result.get("cached")))
        summary["results"][asset_id] = row
    summary["status"] = "ready" if summary["ready"] == summary["total"] else "partial"
    return summary


def enqueue_and_collect(targets, *, workspace_id, job_id, generation, reporter):
    if generation is None:
        raise ValueError("distributed image analysis requires a leased parent ingestion")
    bridge = DesignStoreBridge(workspace_id, ensure_workspace=False)
    offered = bridge._run(
        lambda conn: offer_images(
            conn,
            workspace_id=workspace_id,
            job_id=job_id,
            generation=generation,
            targets=targets,
        )
    )

    async def read(conn):
        await require_parent(conn, workspace_id, job_id, generation)
        results = await conn.execute(
            text("""
            SELECT work_id, status, result_ref_json FROM fleet_task
            WHERE kind = 'design_job' AND work_id = ANY(:ids)
        """),
            {"ids": list(offered.values())},
        )
        tasks = {r.work_id: {"status": r.status, "result": r.result_ref_json} for r in results}
        # A hard execution/store failure can leave the description marked "analyzing".
        # Reconcile that UI state once the child task is terminal, under the parent fence.
        failed = [
            asset_id
            for asset_id, work_id in offered.items()
            if (task := tasks.get(work_id)) is not None
            and task["status"] in {"done", "failed"}
            and (
                task["status"] == "failed"
                or (task["result"] or {}).get("analysis_status") not in {"ready", "unsupported"}
            )
        ]
        if failed:
            await descriptions.fail_queued_analysis(
                conn,
                workspace_id=workspace_id,
                asset_ids=failed,
                job_id=job_id,
                reason="Image worker did not complete analysis; retry this ingestion.",
            )
        rows = await descriptions.get_many(conn, workspace_id=workspace_id, asset_ids=list(targets))
        return collect_summary(offered, tasks, rows)

    previous = None
    while True:
        summary = bridge._run(read)
        counts = tuple(summary[k] for k in ("ready", "failed", "unsupported", "pending"))
        if counts != previous:
            reporter(
                f"Asset descriptions: {summary['ready']}/{summary['total']} ready; "
                f"{summary['failed'] + summary['unsupported']} failed; "
                f"{summary['concurrency']} dedicated image slots",
                0.80 + 0.05 * (summary["total"] - summary["pending"]) / max(1, summary["total"]),
            )
            previous = counts
        if summary["pending"] == 0:
            return summary
        time.sleep(settings.lumen_ingestion_pool_poll_seconds)


class AssetAnalysisWorkHandler:
    kind = FleetTaskKind.DESIGN_JOB
    task_capabilities = (
        TaskCapability(field="kind", supported=frozenset({"asset_analysis"}), required=True),
    )

    def __init__(self, *, storage=None, engine_cache_root=None):
        self.storage = storage
        self.engine_cache_root = engine_cache_root

    async def handle(self, context: WorkContext) -> WorkResult:
        envelope = AssetAnalysisEnvelope.model_validate(context.payload)
        if envelope.work_id != context.work_id:
            raise ValueError("asset task widens its leased work id")
        body = asyncio.create_task(asyncio.to_thread(self.execute, context, envelope))
        from .fleet_handler import _first_of

        fence = asyncio.create_task(_first_of(context.lease_lost, context.stop_requested))
        try:
            done, _ = await asyncio.wait({body, fence}, return_when=asyncio.FIRST_COMPLETED)
            if body not in done:
                # Consume late errors; lease guards refuse all subsequent writes.
                body.add_done_callback(
                    lambda task: task.exception() if not task.cancelled() else None
                )
                return WorkResult(outcome="stopped", requeue=True)
            try:
                return body.result()
            except DesignJobFencedError:
                return WorkResult(outcome="superseded", references={"analysis_status": "failed"})
            except Exception as error:
                await asyncio.to_thread(self.fail, context, envelope, error)
                return WorkResult(
                    outcome="failed",
                    references={
                        "job_id": envelope.job_id,
                        "asset_id": envelope.asset_id,
                        "analysis_status": "failed",
                    },
                )
        finally:
            fence.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fence

    @staticmethod
    def fail(context, envelope, error):
        async def persist(conn):
            await require_asset_lease(conn, context)
            await descriptions.fail_queued_analysis(
                conn,
                workspace_id=envelope.workspace_id,
                asset_ids=[envelope.asset_id],
                job_id=envelope.job_id,
                reason=f"{type(error).__name__}: {error}"[:500],
            )

        try:
            DesignStoreBridge(envelope.workspace_id, ensure_workspace=False)._run(persist)
        except DesignJobFencedError:
            pass

    def execute(self, context, envelope):
        from clue_spend import LedgerStamp
        from clue_storage import storage_from_settings
        from lumen_ingestion.asset_enrichment import (
            ASSET_WORK_CONTEXT,
            JOB_CONTEXT,
            EnrichmentStore,
            enrich_assets,
        )
        from lumen_ingestion.pipeline import (
            _make_rasterize_svg,
            _make_resolve_bytes,
            _make_resolve_thumbnail_bytes,
            resolve_describer,
        )

        from . import spend
        from .design_store import DesignBlobStore, HybridRepository, api_engine_cache_root

        workspace_id = envelope.workspace_id
        bridge = DesignStoreBridge(workspace_id, ensure_workspace=False)
        try:
            bridge._run(lambda conn: require_asset_lease(conn, context))
        except DesignJobFencedError:
            return WorkResult(outcome="parent_superseded", references={"analysis_status": "failed"})
        repo = HybridRepository(workspace_id=workspace_id, ensure_workspace=False)
        blobs = DesignBlobStore(self.storage or storage_from_settings(), workspace_id)
        cache_dir = (
            Path(self.engine_cache_root) / workspace_id
            if self.engine_cache_root is not None
            else api_engine_cache_root(workspace_id)
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        job_token = JOB_CONTEXT.set((envelope.job_id, envelope.parent_generation))
        task_token = ASSET_WORK_CONTEXT.set(context)
        # The fleet UUID is a valid ledger job id; ingestion string ids are not UUIDs.
        with spend.spend_scope(
            LedgerStamp(workspace_id=workspace_id, job_id=envelope.work_id)
        ) as scope:
            try:
                summary = enrich_assets(
                    {envelope.asset_id: envelope.target},
                    workspace_id=workspace_id,
                    describer=resolve_describer(),
                    resolve_bytes=_make_resolve_bytes(repo, blobs),
                    resolve_thumbnail=_make_resolve_thumbnail_bytes(repo, blobs),
                    rasterize_svg=_make_rasterize_svg(repo, blobs, str(cache_dir)),
                    reporter=lambda *_: None,
                    job_id=envelope.job_id,
                    store=EnrichmentStore(workspace_id),
                    concurrency=1,
                )
                row = summary["results"].get(envelope.asset_id, {})
                return WorkResult(
                    outcome=row.get("status", "failed"),
                    references={
                        "job_id": envelope.job_id,
                        "asset_id": envelope.asset_id,
                        "analysis_status": row.get("status", "failed"),
                        "cached": bool(summary["cached"]),
                    },
                )
            finally:
                spend.drain_safely(scope)
                ASSET_WORK_CONTEXT.reset(task_token)
                JOB_CONTEXT.reset(job_token)
