"""Production ``__main__`` for the detached PB-B1 fleet worker (``python -m clue_api.fleet_main``).

The worker deployment's process entrypoint (harness build step 0, treaty §3.4 — the composition the
fleet lane deliberately did not commit). Composition-only, no logic: open the process-wide DB engine
+ Redis client, register the boot-composable phase handlers, build the durable-backed ``RunDriver``
and the :class:`~clue_fleet.ProjectRunWorker` from :class:`~clue_config.Settings` (all the
``CLUE_FLEET_*`` knobs), then hand off to :func:`~clue_fleet.run_worker` (the shell that owns
SIGTERM/SIGINT → graceful drain). Structured logging via :func:`clue_obs.setup`.

**The B4 composing driver drives whole runs.** The worker never *composes* phase handlers inside a
run — it drives the injected ``RunDriver``. Since PB-B4 slice 1 that driver is the
:class:`~clue_api.run_composition.ComposingRunDriver`: it composes a **per-``(workspace_id, icp_key,
icp_version)``** phase registry (LRU-cached) on each run's first advance — every phase of the
sequence, including the campaign-scoped DEEP/VERIFICATION (each holds one ``ICPSpec``) that could
not live in the single process-default registry (two ICPs would collide on the DEEP slot). The
process-wide-composable boot handlers (REVIEW) are re-folded into every per-run registry. So the
worker cleanly drives the full ``reverse_profiling → … → handoff`` sequence, single-flight and
rubric priority on (closing CLAUDE.md ``[B4×fleet]`` + the B1-wiring residuals).

:func:`~clue_api.fleet_wiring.register_boot_handlers` still runs at boot as a composition-machinery
health check, and the worker **refuses to start** (a clean error exit) if that set is empty (a
degenerate no-composer deployment). Two honest limits remain:

* **A run whose current phase has no registered handler fails its drive task with
  ``outcome=error``** (``ProjectRun.advance`` raises ``NoPhaseHandlerRegistered``; the worker
  records the task FAILED). That is the *correct* fail-loud behavior — a misconfigured deployment
  should not silently drop runs.
* **HANDOFF emits no narrative** and **REVERSE_PROFILING needs a client-input provider** — two
  documented gaps the composer surfaces loudly (no production ``HandoffCommitteeReader``; the
  ``[M5×M7]`` client-input threading). See :mod:`clue_api.run_composition`.

This entrypoint also runs the B2 **orphan-blob sweep** on ``CLUE_STORAGE_ORPHAN_SWEEP_INTERVAL_S``
as a background task alongside the worker (started with it, cancelled on drain) — the orphan leg the
retention sweep does not cover. Sweep errors are logged, never fatal to the worker.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from clue_api.execution_tools import (
    ExecutionControlServices,
    register_execution_control_tools,
)
from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_api.fleet_wiring import (
    build_account_lock_factory,
    build_multi_work_worker,
    register_boot_handlers,
)
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    seed_system_recipes,
)
from clue_api.run_composition import ComposingRunDriver
from clue_api.run_events_wiring import build_run_event_emitter
from clue_api.storage_wiring import build_storage_backend, run_orphan_blob_sweep
from clue_api.supervisor_wiring import DeferredSupervisorActions, ToolbeltSupervisorActions
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings, get_config, load_settings
from clue_core import ProjectPhase
from clue_db import ConnFactory, db_lifespan, transaction
from clue_execution import (
    CompatibilityLoader,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    DbRunControlStore,
    RecipeExecutionHandler,
    RecipeExecutor,
)
from clue_fleet import DbTaskQueue, DbWorkQueue, run_worker
from clue_locks import redis_lifespan
from clue_obs import get_logger, setup
from clue_storage import StorageBackend
from clue_toolbelt import DbIdempotencyStore

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
        # Boot smoke: the process-wide-composable handler set (REVIEW today) must compose — a clean
        # refuse-to-start if it cannot (a degenerate no-composer deployment). The ComposingRunDriver
        # (below) *re-folds* these same boot handlers into every per-run registry, so this
        # process-default registration is a composition-machinery health check, not the drive path.
        phases = register_boot_handlers(settings, storage=storage)
        _require_registered(phases)
        log.info("fleet.boot.phases", phases=sorted(phase.value for phase in phases))
        task_queue = DbTaskQueue()
        work_queue = DbWorkQueue(task_queue)
        registry = build_toolbelt(
            storage=storage,
            settings=settings,
            gateway=None,
            queue=task_queue,
        )
        pin_registry = build_recipe_pin_registry(tool_registry=registry)
        compatibility = CompatibilityLoader(pin_registry)
        transport = ExecutionRunEventWriter()
        journal = DbExecutionJournal(transport=transport)
        controls = DbRunControlStore(
            conn_factory=transaction,
            journal=journal,
            policy_for=lambda workspace_id, icp_key: (
                get_config(workspace_id, icp_key).supervisor_policy
            ),
        )
        deferred_supervisor_actions = DeferredSupervisorActions()
        # The B4 per-run composer now also binds C5.5's run-local source breaker, account admission,
        # aggregate supervisor, and deep canary. The deferred action seam is bound to the toolbelt
        # below before the worker can claim its first task.
        driver = ComposingRunDriver(
            settings=settings,
            storage=storage,
            lock_factory=build_account_lock_factory(),
            event_emitter=build_run_event_emitter(),
            controls=controls,
            supervisor_actions=deferred_supervisor_actions,
            execution_journal=journal,
        )
        artifact_store = StorageParameterArtifactStore(storage=storage)
        execution_parameters = StorageExecutionParameterStore(artifact_store)
        tool_invoker = build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(),
            storage=storage,
            settings=settings,
        )
        deferred_supervisor_actions.bind(
            ToolbeltSupervisorActions(invoker=tool_invoker, conn_factory=transaction)
        )
        recipe_reader = DbRecipeReader(conn_factory=transaction)
        recipe_repository = DbRecipeRepository(conn_factory=transaction)
        await seed_system_recipes(
            repository=recipe_repository,
            lifecycle=build_recipe_lifecycle(
                tool_registry=registry,
                conn_factory=transaction,
                pin_registry=pin_registry,
            ),
        )
        starter = DbExecutionStarter(
            conn_factory=transaction,
            recipes=recipe_reader,
            compatibility=compatibility,
            journal=journal,
        )
        executor = RecipeExecutor(
            conn_factory=transaction,
            recipes=recipe_reader,
            compatibility=compatibility,
            journal=journal,
            parameters=execution_parameters,
            tool_invoker=tool_invoker,
            controls=controls,
        )
        register_execution_control_tools(
            ExecutionControlServices(
                starter=starter,
                executor=executor,
                parameters=execution_parameters,
                recipes=recipe_repository,
                run_machine=driver,
                queue=work_queue,
                conn_factory=transaction,
                registry=registry,
                controls=controls,
            )
        )
        worker = build_multi_work_worker(
            settings,
            driver=driver,
            graph_handler=RecipeExecutionHandler(executor),
            queue=work_queue,
        )
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
