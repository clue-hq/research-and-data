"""Production ``__main__`` for the detached PB-B1 fleet worker (``python -m clue_api.fleet_main``).

The worker deployment's process entrypoint (harness build step 0, treaty §3.4 — the composition the
fleet lane deliberately did not commit). Composition-only, no logic: open the process-wide DB engine
+ Redis client, register the boot-composable phase handlers, build the durable-backed ``RunDriver``
and the :class:`~clue_fleet.ProjectRunWorker` from :class:`~clue_config.Settings` (all the
``CLUE_FLEET_*`` knobs), then hand off to :func:`~clue_fleet.run_worker` (the shell that owns
SIGTERM/SIGINT → graceful drain). Structured logging via :func:`clue_obs.setup`.

**Phase-handler registration is the load-bearing boot step.** The worker never *composes* phase
handlers inside a run — it drives the injected :class:`~clue_research.durable.ProjectRun`, whose
handlers live in the phase-handler registry. So the worker must populate that registry at boot, or
every claimed ``drive_run`` task raises ``NoPhaseHandlerRegistered`` and parks FAILED (and resume
flows are poisoned). :func:`~clue_api.fleet_wiring.register_boot_handlers` registers every handler
composable **process-wide from settings** (today: ``ProjectPhase.REVIEW``) and the worker **refuses
to start** (a clean error exit) if that set is empty.

Two honest limits of the boot registry, stated plainly:

* **A run whose current phase has no registered handler fails its drive task with
  ``outcome=error``** (``ProjectRun.advance`` raises ``NoPhaseHandlerRegistered``; the worker
  records the task FAILED). That is the *correct* fail-loud behavior, not a bug to paper over — a
  misconfigured deployment should not silently drop runs.
* **The per-``(client, icp)`` DEEP (and VERIFICATION) composition inside the worker is a deliberate
  open design item** — those handlers hold a campaign-scoped ``ICPSpec`` + committee sources, so
  they are registered per run at run start, not at boot. Wiring that into the detached worker is the
  B4 delegation contract; until it lands, the worker cleanly drives only the boot-composable phases.

This entrypoint also runs the B2 **orphan-blob sweep** on ``CLUE_STORAGE_ORPHAN_SWEEP_INTERVAL_S``
as a background task alongside the worker (started with it, cancelled on drain) — the orphan leg the
retention sweep does not cover. Sweep errors are logged, never fatal to the worker.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from clue_api.fleet_wiring import (
    build_fleet_run_driver,
    build_fleet_worker,
    register_boot_handlers,
)
from clue_api.storage_wiring import build_storage_backend, run_orphan_blob_sweep
from clue_config import Settings, load_settings
from clue_core import ProjectPhase
from clue_db import ConnFactory, db_lifespan, transaction
from clue_fleet import run_worker
from clue_locks import redis_lifespan
from clue_obs import get_logger, setup
from clue_storage import StorageBackend

log = get_logger("clue_api.fleet_main")


class NoBootHandlersRegistered(RuntimeError):
    """The worker refuses to start: :func:`~clue_api.fleet_wiring.register_boot_handlers` composed
    no phase handlers, so every ``drive_run`` task the worker claimed would raise
    ``NoPhaseHandlerRegistered`` and park FAILED. Fail fast at boot instead."""


def _require_registered(phases: frozenset[ProjectPhase]) -> None:
    """Refuse to start (raise) when no phase handlers were composed at boot — a clean error exit
    beats a worker that FAILs every task it claims."""
    if not phases:
        raise NoBootHandlersRegistered(
            "no phase handlers could be composed from settings at boot; refusing to start the "
            "fleet worker (every claimed run would fail). Check the api-root boot composition."
        )


async def _orphan_sweep_loop(
    settings: Settings,
    storage: StorageBackend,
    *,
    conn_factory: ConnFactory = transaction,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """Run :func:`~clue_api.storage_wiring.run_orphan_blob_sweep` every
    ``storage_orphan_sweep_interval_s`` seconds until cancelled. Each pass is fully isolated: a
    sweep fault is logged and the loop continues — the orphan sweep must never sink the worker."""
    interval = settings.storage_orphan_sweep_interval_s
    while True:
        await sleep(interval)
        try:
            async with conn_factory() as conn:
                deleted = await run_orphan_blob_sweep(conn, storage=storage)
            if deleted:
                log.info("fleet.orphan_sweep.deleted", count=len(deleted))
        except Exception:  # noqa: BLE001 — a sweep fault is non-fatal to the worker
            log.warning("fleet.orphan_sweep.error", exc_info=True)


def _start_orphan_sweep(settings: Settings, storage: StorageBackend) -> asyncio.Task[None] | None:
    """Start the background orphan-sweep task, or ``None`` when disabled
    (``storage_orphan_sweep_interval_s <= 0``). Must be called with a running event loop."""
    if settings.storage_orphan_sweep_interval_s <= 0:
        log.info("fleet.orphan_sweep.disabled")
        return None
    return asyncio.create_task(_orphan_sweep_loop(settings, storage))


async def _serve() -> None:
    """Open the process-wide DB + Redis lifecycles, register the boot handlers, and drive the worker
    (with the orphan sweep alongside) until a graceful stop."""
    settings = load_settings()
    storage = build_storage_backend(settings)
    async with db_lifespan(), redis_lifespan():
        phases = register_boot_handlers(settings, storage=storage)
        _require_registered(phases)
        log.info("fleet.boot.phases", phases=sorted(phase.value for phase in phases))
        driver = build_fleet_run_driver()
        worker = build_fleet_worker(settings, driver=driver)
        sweep = _start_orphan_sweep(settings, storage)
        try:
            await run_worker(worker)
        finally:
            if sweep is not None:
                sweep.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sweep


def main() -> None:
    """Configure logging and run the worker event loop (the ``python -m`` entrypoint)."""
    setup()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
