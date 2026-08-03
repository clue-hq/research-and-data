"""Production ``__main__`` for the detached PB-B1 fleet worker (``python -m clue_api.fleet_main``).

The worker deployment's process entrypoint (harness build step 0, treaty §3.4 — the composition the
fleet lane deliberately did not commit). Composition-only, no logic: open the process-wide DB engine
+ Redis client, register the boot-composable phase handlers, build the durable-backed ``RunDriver``
and the :class:`~clue_fleet.ProjectRunWorker` from :class:`~clue_config.Settings` (all the
``CLUE_FLEET_*`` knobs), then hand off to :func:`~clue_fleet.run_worker` (the shell that owns
SIGTERM/SIGINT → graceful drain). Structured logging via :func:`clue_obs.setup`.

**The B4 composing driver drives whole runs.** The worker never *composes* phase handlers inside a
run — it drives the injected ``RunDriver``. Since PB-B4 slice 1 that driver is the
:class:`~clue_api.run_composition.ComposingRunDriver`: it composes a **per-project-run** phase
registry (LRU-cached) on each run's first advance — every phase of the
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
* **REVERSE_PROFILING needs a client-input provider** — the remaining documented composition gap.
  C7.6 closed the HANDOFF gap: the per-run composer now binds the production governed committee
  reader and the real materialise-then-outbox M12 handler. See :mod:`clue_api.run_composition`.

This entrypoint also runs the B2 **orphan-blob sweep** on ``CLUE_STORAGE_ORPHAN_SWEEP_INTERVAL_S``
as a background task alongside the worker (started with it, cancelled on drain) — the orphan leg the
retention sweep does not cover. Sweep errors are logged, never fatal to the worker.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from clue_agents import AgentRole
from clue_api.account_research_turn_wiring import (
    DbCompiledContextCardReader,
    PreparedAccountResearchTurnRunner,
    build_account_research_context,
)
from clue_api.account_research_wiring import AccountResearchAgentRuntime, GovernedAccountProfiler
from clue_api.agent_cleanup import AgentWorkspaceCleanupJob
from clue_api.agent_execution_wiring import DbAgentPlanJournal
from clue_api.agent_platform_wiring import build_agent_platform_components
from clue_api.agent_workspace_wiring import build_agent_workspace_factory
from clue_api.compliance_wiring import register_compliance_wiring
from clue_api.composition import load_research_packs
from clue_api.exa_targeted_enrichment import (
    ExaTargetedEnrichmentCoordinator,
    ExaTargetedEnrichmentWorker,
    build_production_exa_targeted_starter,
)
from clue_api.exa_websets_acquisition import ExaWebsetsDiscoveryStarter
from clue_api.exa_websets_lifecycle import (
    DurableExaWebsetLifecycle,
    ExaDiscoveryWakeWorker,
)
from clue_api.exa_websets_materialization import ExaWebsetsD4Materializer
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
    enqueue_run_drive,
    register_boot_handlers,
)
from clue_api.narrative_wiring import register_narrative_wiring
from clue_api.project_execution_router import (
    DeferredProjectExecutionRouter,
    Recipe1ProjectExecutionRouter,
)
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    seed_system_recipes,
)
from clue_api.research_view_runtime import build_production_research_view_runtime
from clue_api.run_composition import ComposingRunDriver, build_platform_gateway
from clue_api.run_events_wiring import build_run_event_emitter
from clue_api.storage_wiring import build_storage_backend, run_orphan_blob_sweep
from clue_api.sumble_account_gaps import build_production_sumble_account_gap_starter
from clue_api.sumble_discovery_gaps import build_production_sumble_discovery_gap_resolver
from clue_api.supervisor_wiring import DeferredSupervisorActions, ToolbeltSupervisorActions
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Secrets, Settings, default_gateway_config, get_config, load_settings
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
from clue_research.adapters.exa_websets import ExaWebsetsClient
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


async def _agent_cleanup_loop(
    settings: Settings,
    job: AgentWorkspaceCleanupJob,
    *,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    while True:
        await sleep(settings.agent_cleanup_interval_s)
        try:
            result = await job.run_once()
            if result.considered:
                log.info(
                    "fleet.agent_cleanup.completed",
                    considered=result.considered,
                    removed=result.removed,
                    already_absent=result.already_absent,
                )
        except Exception:  # noqa: BLE001 — cleanup failure must not sink run execution
            log.warning("fleet.agent_cleanup.error", exc_info=True)


def _start_agent_cleanup(
    settings: Settings,
    job: AgentWorkspaceCleanupJob | None,
) -> asyncio.Task[None] | None:
    if (
        job is None
        or settings.agent_cleanup_interval_s <= 0
        or settings.agent_workspace_root is None
    ):
        log.info("fleet.agent_cleanup.disabled")
        return None
    return asyncio.create_task(_agent_cleanup_loop(settings, job))


async def _exa_discovery_loop(
    settings: Settings,
    *,
    api_key: object,
    storage: StorageBackend,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    from pydantic import SecretStr

    if not isinstance(api_key, SecretStr):
        raise TypeError("Exa discovery worker requires a SecretStr API key")
    async with ExaWebsetsClient(api_key=api_key, lookup_attempts=1) as client:
        worker = ExaDiscoveryWakeWorker(
            lifecycle=DurableExaWebsetLifecycle(transport=client, storage=storage),
            materializer=ExaWebsetsD4Materializer(storage=storage),
            project_run_waker=enqueue_run_drive,
        )
        while True:
            try:
                completed = await worker.run_due()
                if completed:
                    log.info("fleet.exa_discovery.completed", wake_count=completed)
            except Exception:  # noqa: BLE001 - one provider fault cannot sink run execution
                log.warning("fleet.exa_discovery.error", exc_info=True)
            await sleep(settings.exa_websets_poll_worker_interval_s)


def _start_exa_discovery(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
) -> asyncio.Task[None] | None:
    if not settings.exa_websets_lifecycle_enabled:
        log.info("fleet.exa_discovery.disabled")
        return None
    if secrets.exa_api_key is None:
        raise RuntimeError(
            "Exa Websets lifecycle is enabled but CLUE_EXA_API_KEY is not configured"
        )
    loop = asyncio.get_running_loop()
    return loop.create_task(
        _exa_discovery_loop(settings, api_key=secrets.exa_api_key, storage=storage)
    )


def _build_exa_discovery_starter(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
) -> ExaWebsetsDiscoveryStarter | None:
    """Bind paid acquisition only under its explicit spend switch and a live reconciler."""

    if not settings.exa_websets_acquisition_enabled:
        return None
    if not settings.exa_websets_lifecycle_enabled:
        raise RuntimeError(
            "Exa Websets acquisition is enabled but its lifecycle worker is disabled"
        )
    api_key = secrets.exa_api_key
    if api_key is None:
        raise RuntimeError(
            "Exa Websets lifecycle is enabled but CLUE_EXA_API_KEY is not configured"
        )
    return ExaWebsetsDiscoveryStarter(
        transport_factory=lambda: ExaWebsetsClient(api_key=api_key, lookup_attempts=1),
        storage=storage,
    )


async def _exa_targeted_enrichment_loop(
    settings: Settings,
    *,
    api_key: object,
    storage: StorageBackend,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    from pydantic import SecretStr

    if not isinstance(api_key, SecretStr):
        raise TypeError("Exa targeted enrichment worker requires a SecretStr API key")
    async with ExaWebsetsClient(api_key=api_key, lookup_attempts=1) as client:
        worker = ExaTargetedEnrichmentWorker(
            coordinator=ExaTargetedEnrichmentCoordinator(
                transport=client,
                storage=storage,
            )
        )
        while True:
            try:
                completed = await worker.run_due()
                if completed:
                    log.info("fleet.exa_targeted_enrichment.completed", operation_count=completed)
            except Exception:  # noqa: BLE001 - one provider fault cannot sink run execution
                log.warning("fleet.exa_targeted_enrichment.error", exc_info=True)
            await sleep(settings.exa_websets_poll_worker_interval_s)


def _start_exa_targeted_enrichment(
    settings: Settings,
    *,
    secrets: Secrets,
    storage: StorageBackend,
) -> asyncio.Task[None] | None:
    # Draining is controlled by the lifecycle switch, not the new-spend switch: turning off new
    # E1 starts must never strand an operation that was already accepted by Exa.
    if not settings.exa_websets_lifecycle_enabled:
        log.info("fleet.exa_targeted_enrichment.disabled")
        return None
    if secrets.exa_api_key is None:
        raise RuntimeError(
            "Exa Websets lifecycle is enabled but CLUE_EXA_API_KEY is not configured"
        )
    return asyncio.get_running_loop().create_task(
        _exa_targeted_enrichment_loop(
            settings,
            api_key=secrets.exa_api_key,
            storage=storage,
        )
    )


async def _account_agent_runtime_required(
    settings: Settings,
    *,
    conn_factory: ConnFactory = transaction,
) -> bool:
    """Keep sticky deepagent-owned runs resumable after rollout switches are reduced."""

    configured_cohort = (
        settings.agent_runtime_routing_enabled
        and settings.agent_account_routing_enabled
        and (bool(settings.agent_workspace_allowlist) or settings.agent_canary_percent > 0)
    )
    if configured_cohort:
        return True
    async with conn_factory() as conn:
        return bool(
            (
                await conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM agent_runtime_route "
                        "WHERE surface='account_research' AND owner='deepagent')"
                    )
                )
            ).scalar_one()
        )


async def _serve() -> None:
    """Open the process-wide DB + Redis lifecycles, register the boot handlers, and drive the worker
    (with the orphan sweep alongside) until a graceful stop."""
    settings = load_settings()
    secrets = Secrets()
    storage = build_storage_backend(settings)
    async with db_lifespan(), redis_lifespan():
        register_compliance_wiring()
        register_narrative_wiring()
        async with transaction() as conn:
            await load_research_packs(conn)
        project_execution_router = DeferredProjectExecutionRouter()
        # Boot smoke: the process-wide-composable handler set (REVIEW today) must compose — a clean
        # refuse-to-start if it cannot (a degenerate no-composer deployment). The ComposingRunDriver
        # (below) *re-folds* these same boot handlers into every per-run registry, so this
        # process-default registration is a composition-machinery health check, not the drive path.
        phases = register_boot_handlers(
            settings,
            storage=storage,
            project_execution_router=project_execution_router,
        )
        _require_registered(phases)
        log.info("fleet.boot.phases", phases=sorted(phase.value for phase in phases))
        task_queue = DbTaskQueue()
        work_queue = DbWorkQueue(task_queue)
        gateway = build_platform_gateway(settings)
        c7_enabled = any(
            (
                settings.c7_research_view_read_enabled,
                settings.c7_snapshot_compose_enabled,
                settings.c7_evidence_actions_enabled,
                settings.c7_recheck_enabled,
                settings.c7_production_handoff_enabled,
            )
        )
        research_views = (
            build_production_research_view_runtime(storage=storage) if c7_enabled else None
        )
        registry = build_toolbelt(
            storage=storage,
            settings=settings,
            gateway=gateway,
            queue=task_queue,
            project_execution_router=project_execution_router,
            research_view_composer=(
                research_views.composer if research_views is not None else None
            ),
            research_view_snapshots=(
                research_views.snapshots if research_views is not None else None
            ),
            research_view_recheck=(research_views.recheck if research_views is not None else None),
            targeted_enrichment_starter=build_production_exa_targeted_starter(
                settings,
                secrets=secrets,
                storage=storage,
            ),
            account_gap_enrichment_starter=build_production_sumble_account_gap_starter(
                settings,
                secrets=secrets,
                storage=storage,
            ),
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
        artifact_store = StorageParameterArtifactStore(storage=storage)
        execution_parameters = StorageExecutionParameterStore(artifact_store)
        tool_invoker = build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(),
            storage=storage,
            settings=settings,
        )
        if research_views is not None:
            research_views.bind_tool_invoker(tool_invoker)
        deferred_supervisor_actions.bind(
            ToolbeltSupervisorActions(invoker=tool_invoker, conn_factory=transaction)
        )
        recipe_reader = DbRecipeReader(conn_factory=transaction)
        recipe_repository = DbRecipeRepository(conn_factory=transaction)
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
            max_concurrency=settings.recipe_executor_max_concurrency,
        )
        account_agent_profiler = None
        agent_workspace_factory = None
        if await _account_agent_runtime_required(settings):
            agent_components = build_agent_platform_components(
                settings=settings,
                secrets=secrets,
                gateway_config=default_gateway_config(),
                storage=storage,
                tools=registry,
            )
            agent_workspace_factory = agent_components.workspaces
            account_runtime = AccountResearchAgentRuntime(
                profiles=agent_components.profiles,
                models=agent_components.models,
                turns=agent_components.turns,
                artifacts=agent_components.artifacts,
                tools=registry,
            )
            account_context = build_account_research_context(
                resolved_profile=agent_components.profiles.resolve(AgentRole.ACCOUNT_RESEARCH),
                artifacts=agent_components.artifacts,
                cards=DbCompiledContextCardReader(),
            )
            account_turns = PreparedAccountResearchTurnRunner(
                settings=settings,
                runtime=account_runtime,
                profiles=agent_components.profiles,
                workspaces=agent_components.workspaces,
                artifacts=agent_components.artifacts,
                turns=agent_components.turns,
                history=agent_components.history,
                contexts=account_context,
                tools=registry,
                tool_invoker=tool_invoker,
                executor=executor,
                compatibility=compatibility,
                plans=DbAgentPlanJournal(),
                recipes=recipe_reader,
                starter=starter,
                parameters=execution_parameters,
            )
            account_agent_profiler = GovernedAccountProfiler(turns=account_turns)
            log.info("fleet.agent_account_runtime.composed")

        # Bind the selected account owner into the existing DEEP slot. With the switches off—or
        # for non-selected workspaces—the durable router chooses the mechanical profiler.
        driver = ComposingRunDriver(
            settings=settings,
            gateway=gateway,
            storage=storage,
            discovery_batch_starter=_build_exa_discovery_starter(
                settings,
                secrets=secrets,
                storage=storage,
            ),
            discovery_required_field_resolver=build_production_sumble_discovery_gap_resolver(
                settings,
                secrets=secrets,
                storage=storage,
            ),
            lock_factory=build_account_lock_factory(),
            event_emitter=build_run_event_emitter(),
            controls=controls,
            supervisor_actions=deferred_supervisor_actions,
            execution_journal=journal,
            project_execution_router=project_execution_router,
            account_agent_profiler=account_agent_profiler,
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
        await seed_system_recipes(
            repository=recipe_repository,
            lifecycle=build_recipe_lifecycle(
                tool_registry=registry,
                conn_factory=transaction,
                pin_registry=pin_registry,
            ),
        )
        project_execution_router.bind(
            Recipe1ProjectExecutionRouter(
                settings=settings,
                recipes=recipe_reader,
                starter=starter,
                executor=executor,
                parameters=execution_parameters,
                compatibility=compatibility,
                queue=work_queue,
            )
        )
        worker = build_multi_work_worker(
            settings,
            driver=driver,
            graph_handler=RecipeExecutionHandler(executor),
            queue=work_queue,
        )
        sweep = _start_orphan_sweep(settings, storage)
        if agent_workspace_factory is None and settings.agent_workspace_root is not None:
            agent_workspace_factory = build_agent_workspace_factory(
                storage=storage,
                settings=settings,
            )
        agent_cleanup = _start_agent_cleanup(
            settings,
            (
                AgentWorkspaceCleanupJob(
                    settings=settings,
                    workspaces=agent_workspace_factory,
                )
                if agent_workspace_factory is not None
                else None
            ),
        )
        exa_discovery = _start_exa_discovery(
            settings,
            secrets=secrets,
            storage=storage,
        )
        exa_targeted_enrichment = _start_exa_targeted_enrichment(
            settings,
            secrets=secrets,
            storage=storage,
        )
        try:
            await run_worker(worker)
        finally:
            for background in (
                sweep,
                agent_cleanup,
                exa_discovery,
                exa_targeted_enrichment,
            ):
                if background is None:
                    continue
                background.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await background
            if agent_workspace_factory is not None:
                agent_workspace_factory.close()


def main() -> None:
    """Configure logging and run the worker event loop (the ``python -m`` entrypoint)."""
    setup()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
