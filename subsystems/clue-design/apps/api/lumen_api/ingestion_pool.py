"""On-demand local ingestion pool. Run with ``python -m lumen_api.ingestion_pool``.

The controller only observes the existing queue and manages processes. A database
advisory lock elects one controller. Execution uses the normal fleet claim and lease
machinery, so an external deployment can run the coordinator/analysis roles directly.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from clue_config import Secrets, load_settings
from clue_db import create_engine, db_lifespan
from clue_fleet import LeasedWorkWorker, run_worker
from clue_obs import get_logger, setup
from clue_obs.langfuse import flush_langfuse, shutdown_langfuse
from clue_obs.otel import TracingRuntime
from clue_obs.production import (
    install_production_langfuse,
    install_production_sentry,
    install_production_tracing,
)
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
from py_lumen_config import settings
from sqlalchemy import text

log = get_logger(__name__)
# Session advisory lock, scoped by the database. Never shares a transaction connection.
CONTROLLER_LOCK = 739421852171


def desired_roles(coordinators: int, images: int) -> list[str]:
    roles = ["coordinator"] if coordinators else []
    if images:
        roles += ["analysis"] * settings.lumen_ingestion_pool_workers
    return roles


class LocalProcesses:
    """Replaceable launcher boundary; owns only the children it started."""

    def __init__(self):
        self.children: list[tuple[str, subprocess.Popen]] = []
        self.failed_starts = 0
        self.retry_at = 0.0
        self.log_dir = Path(settings.effective_asset_store_root) / "ingestion-pool-logs"

    def reconcile(self, roles: list[str]) -> None:
        live = []
        for role, child in self.children:
            code = child.poll()
            if code is None:
                live.append((role, child))
            else:
                log.warning(
                    "ingestion_pool.child_exited",
                    role=role,
                    pid=child.pid,
                    exit_code=code,
                )
                self.failed_starts += 1
                self.retry_at = time.monotonic() + min(30, 2 ** min(self.failed_starts, 5))
                # A dead worker may have left helper/browser grandchildren in its group.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
        self.children = live
        # Keep live children until the whole pool is idle; never kill an active task on a dip.
        missing = list(roles)
        for role, _ in live:
            if role in missing:
                missing.remove(role)
        if time.monotonic() < self.retry_at:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for role in missing:
            with (self.log_dir / f"{role}.log").open("ab") as output:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "lumen_api.ingestion_pool",
                        "--role",
                        role,
                        "--parent-pid",
                        str(os.getpid()),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            self.children.append((role, child))
            log.info(
                "ingestion_pool.child_started",
                role=role,
                pid=child.pid,
                slots=settings.lumen_ingestion_worker_concurrency if role == "analysis" else 1,
            )

    async def stop(self) -> None:
        for _, child in self.children:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGTERM)
        deadline = time.monotonic() + 30
        while (
            any(child.poll() is None for _, child in self.children) and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.2)
        for _, child in self.children:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        self.children.clear()
        self.failed_starts = 0
        self.retry_at = 0
        log.info("ingestion_pool.scaled_to_zero")


async def pending_counts(conn) -> tuple[int, int]:
    # Claimed rows count until completion (including the stale reclaim window).
    row = (
        await conn.execute(
            text("""
        SELECT count(*) FILTER (WHERE payload_json->>'kind' = 'ingestion') AS coordinators,
               count(*) FILTER (WHERE payload_json->>'kind' = 'asset_analysis') AS images
        FROM fleet_task WHERE kind = 'design_job' AND status IN ('queued', 'claimed')
          AND payload_json->>'kind' IN ('ingestion', 'asset_analysis')
    """)
        )
    ).one()
    return row.coordinators, row.images


async def supervise(conn, processes, stopped, *, now=time.monotonic):
    idle_since = None
    while not stopped.is_set():
        coordinators, images = await pending_counts(conn)
        await conn.commit()  # No long-lived transaction/snapshot; session lock remains held.
        if coordinators or images:
            idle_since = None
            processes.reconcile(desired_roles(coordinators, images))
        else:
            idle_since = now() if idle_since is None else idle_since
            if (
                processes.children
                and now() - idle_since >= settings.lumen_ingestion_pool_idle_seconds
            ):
                await processes.stop()
        try:
            await asyncio.wait_for(
                stopped.wait(), timeout=settings.lumen_ingestion_pool_poll_seconds
            )
        except TimeoutError:
            pass


def controller_engine():
    """The controller's engine: its own direct URL when one is configured (the session lock
    must not pass through a transaction pooler), else CLUE_DATABASE_URL. Children never call
    this; they keep the container's CLUE_DATABASE_URL."""
    return create_engine(settings.lumen_ingestion_controller_database_url or None)


async def controller():
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    engine = controller_engine()
    processes = LocalProcesses()
    try:
        async with engine.connect() as conn:
            acquired = await conn.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": CONTROLLER_LOCK}
            )
            await conn.commit()
            if not acquired:
                raise RuntimeError("An ingestion pool controller already owns this database")
            log.info(
                "ingestion_pool.controller_started",
                workers=settings.lumen_ingestion_pool_workers,
                concurrency=settings.lumen_ingestion_worker_concurrency,
            )
            # A broken control connection must fail closed. Connection invalidation cannot
            # silently reconnect while retaining a leadership claim that PostgreSQL released.
            await supervise(conn, processes, stopped)
    finally:
        await processes.stop()
        await engine.dispose()


async def execution(role: str, parent_pid: int | None):
    from .fleet_handler import build_design_job_handler
    from .ingestion_tasks import AssetAnalysisWorkHandler

    handler = (
        build_design_job_handler(ingestion_only=True)
        if role == "coordinator"
        else AssetAnalysisWorkHandler()
    )
    worker = LeasedWorkWorker(
        handlers=(handler,),
        concurrency=1 if role == "coordinator" else settings.lumen_ingestion_worker_concurrency,
        poll_interval=0.25,
        worker_id=f"ingestion-{role}:{os.getpid()}",
    )

    async def watch_parent():
        while True:
            if parent_pid is not None and os.getppid() != parent_pid:
                worker.stop()
                log.warning("ingestion_pool.controller_lost", role=role)
                # The controller is gone; kill this owned group so synchronous
                # threads cannot outlive supervision. Fleet leases recover the work.
                if os.getpgrp() == os.getpid():
                    os.killpg(os.getpid(), signal.SIGKILL)
                os._exit(1)  # Manually launched roles must never kill a caller's shell group.
            await asyncio.sleep(1)

    monitor = asyncio.create_task(watch_parent())
    try:
        async with db_lifespan():
            await run_worker(worker)
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor


#: One service for every pool process (controller, coordinator, analysis workers).
SERVICE_NAME = "clue-ingestion-pool"


def _process_has_tracer() -> bool:
    return isinstance(otel_trace.get_tracer_provider(), SdkTracerProvider)


def install_pool_telemetry() -> TracingRuntime | None:
    """OTel, Sentry and Langfuse for this pool process, as ``clue-ingestion-pool``.

    Installed at process start, so the coordinator's later lazy import of ``lumen_api.main`` (to
    run a job) finds a provider already in place and skips its own ``clue-design-api`` install —
    the same "does this process already have a root?" guard ``lumen_api.main`` uses. Before
    2026-10-03 the controller and the analysis workers had no telemetry at all.
    """
    if _process_has_tracer():
        return None
    settings, secrets = load_settings(), Secrets()
    runtime = install_production_tracing(settings, secrets, service_name=SERVICE_NAME)
    install_production_sentry(settings, secrets, service_name=SERVICE_NAME)
    install_production_langfuse(settings, secrets, runtime=runtime, service_name=SERVICE_NAME)
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role",
        choices=("controller", "coordinator", "analysis"),
        default="controller",
    )
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    setup()
    runtime = install_pool_telemetry()
    try:
        asyncio.run(
            controller() if args.role == "controller" else execution(args.role, args.parent_pid)
        )
    finally:
        flush_langfuse()
        shutdown_langfuse()
        if runtime is not None:
            runtime.shutdown()


if __name__ == "__main__":
    main()
