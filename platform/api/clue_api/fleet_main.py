"""Production ``__main__`` for the detached PB-B1 fleet worker (``python -m clue_api.fleet_main``).

The worker deployment's process entrypoint (harness build step 0, treaty §3.4 — the composition the
fleet lane deliberately did not commit). Composition-only, no logic: open the process-wide DB engine
+ Redis client, register the boot-composable phase handlers, build the durable-backed ``RunDriver``
and the :class:`~clue_fleet.ProjectRunWorker` from :class:`~clue_config.Settings` (all the
``CLUE_FLEET_*`` knobs), then hand off to :func:`~clue_fleet.run_worker` (the shell that owns
SIGTERM/SIGINT → graceful drain). Structured logging via :func:`clue_obs.setup`.

**The B4 composing driver drives runs through the active composition.** The worker never
*composes* phase handlers inside a run — it drives the injected ``RunDriver``. Since PB-B4 slice 1
that driver is the
:class:`~clue_api.run_composition.ComposingRunDriver`: it composes a **per-project-run** phase
registry (LRU-cached) on each run's first advance — every phase of the
sequence, including the campaign-scoped DEEP/VERIFICATION (each holds one ``ICPSpec``) that could
not live in the single process-default registry (two ICPs would collide on the DEEP slot). The
process-wide-composable boot handlers (REVIEW) are re-folded into every per-run registry.

M8D R10 promotes separately confirmed account/contact ``create_agent()`` runs through the same
detached work drain. The outer project DEEP phase remains a loud quarantine for the superseded
pipeline: it never launches entity research and never performs automatic account-to-contact
progression. Provider lifecycle workers continue to drain already-authorized durable operations.

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

This entrypoint also runs the B2 **orphan-blob sweep** and provider lifecycle wake paths as
background tasks alongside the worker (started with it, cancelled on drain). Sweep/wake errors are
logged and never fatal to the worker; they do not originate new quarantined entity-research work.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from clue_api.agent_cleanup import AgentWorkspaceCleanupJob
from clue_api.agent_model_wiring import build_agent_model_provider
from clue_api.agent_workspace_wiring import build_agent_workspace_factory
from clue_api.compliance_wiring import register_compliance_wiring
from clue_api.composition import build_pre_spend_gate, load_research_packs
from clue_api.contact_content_handoff import ContactContentHandoffService
from clue_api.contact_research_fleet_launch import ContactResearchSelectionApprover
from clue_api.entity_research_launch_tools import EntityResearchLaunchServices
from clue_api.entity_research_parallel import EntityResearchBatchWakeService
from clue_api.entity_research_provider_wiring import build_production_entity_research_fleet
from clue_api.exa_targeted_enrichment import (
    ExaTargetedEnrichmentCoordinator,
    ExaTargetedEnrichmentWorker,
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
from clue_api.external_research_wake import (
    ExternalResearchWakeDispatcher,
    registered_entity_research_wait_sources,
    registered_external_research_wake_sources,
)
from clue_api.fleet_wiring import build_multi_work_worker, enqueue_run_drive, register_boot_handlers
from clue_api.memory_wiring import memory_write_factory_builder
from clue_api.narrative_wiring import register_narrative_wiring
from clue_api.project_execution_router import (
    DeferredProjectExecutionRouter,
    Recipe1ProjectExecutionRouter,
)
from clue_api.prose_synthesis_step import ProseSynthesisStep
from clue_api.prose_synthesis_tools import ProseSynthesisServices
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    seed_system_recipes,
)
from clue_api.research_view_runtime import build_production_research_view_runtime
from clue_api.run_composition import ComposingRunDriver, build_platform_gateway
from clue_api.run_events_wiring import build_run_event_emitter
from clue_api.storage_wiring import build_storage_backend, run_orphan_blob_sweep
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
from clue_research.narrative import ProseSynthesizer
from clue_research.verification import FaithfulnessJudgeImpl
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


async def _external_research_wake_loop(
    settings: Settings,
    worker: ExternalResearchWakeDispatcher,
    *,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """Wake due registered external operations without provider logic in the fleet loop."""

    while True:
        try:
            completed = await worker.run_due()
            if completed:
                log.info("fleet.external_research.woke", run_count=completed)
        except Exception:  # noqa: BLE001 - one wake scan must not sink the fleet
            log.warning("fleet.external_research.wake_error", exc_info=True)
        await sleep(settings.external_research_wake_worker_interval_s)


def _start_external_research_wake(settings: Settings) -> asyncio.Task[None] | None:
    if not any(
        (
            settings.sumble_committee_acquisition_enabled,
            settings.exa_contact_deep_acquisition_enabled,
            settings.contact_channel_enrichment_enabled,
        )
    ):
        log.info("fleet.external_research.wake_disabled")
        return None
    entity_wakes = (
        EntityResearchBatchWakeService() if settings.entity_research_runtime_enabled else None
    )

    async def wake_entity_member(wait_ref: str) -> int:
        assert entity_wakes is not None
        return await entity_wakes.notify_member_ready(
            wait_ref,
            actor="provider-due:entity-research",
        )

    return asyncio.create_task(
        _external_research_wake_loop(
            settings,
            ExternalResearchWakeDispatcher(
                project_run_waker=enqueue_run_drive,
                sources=registered_external_research_wake_sources(
                    committee_enabled=settings.sumble_committee_acquisition_enabled,
                    contact_external_enabled=settings.exa_contact_deep_acquisition_enabled,
                    contact_channel_enabled=settings.contact_channel_enrichment_enabled,
                ),
                entity_member_waker=(wake_entity_member if entity_wakes is not None else None),
                entity_wait_sources=(
                    registered_entity_research_wait_sources(
                        committee_enabled=settings.sumble_committee_acquisition_enabled,
                        contact_external_enabled=settings.exa_contact_deep_acquisition_enabled,
                        contact_channel_enabled=settings.contact_channel_enrichment_enabled,
                    )
                    if entity_wakes is not None
                    else ()
                ),
            ),
        )
    )


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
        gateway_config = default_gateway_config()
        pre_spend_gate = build_pre_spend_gate(conn_factory=transaction)
        # Lane E E1. Constructed here because the fleet composition needs it, but it cannot be
        # handed an invoker yet: the fleet's launch services feed `build_toolbelt` below, and
        # the invoker is built from the resulting registry. It is bound after that (`:bind`).
        prose_step = ProseSynthesisStep()
        entity_research = build_production_entity_research_fleet(
            settings=settings,
            secrets=secrets,
            storage=storage,
            models=(
                build_agent_model_provider(config=gateway_config, secrets=secrets)
                if settings.entity_research_runtime_enabled
                else None
            ),
            gateway=gateway,
            gateway_config=gateway_config,
            pre_spend_gate=pre_spend_gate,
            conn_factory=transaction,
            prose_step=prose_step,
        )
        entity_research_launches = (
            EntityResearchLaunchServices(
                account_launcher=entity_research.accounts.launcher,
                account_fleets=entity_research.accounts.fleets,
                contact_approver=ContactResearchSelectionApprover(conn_factory=transaction),
                contact_launcher=entity_research.contacts.launcher,
                contact_fleets=entity_research.contacts.fleets,
            )
            if entity_research is not None
            else None
        )
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
        contact_content_handoff = (
            ContactContentHandoffService(research_views=research_views.composer)
            if settings.c7_production_handoff_enabled and research_views is not None
            else None
        )
        # Lane E E1. The judge follows the runtime verification toggle exactly as the project-run
        # composition does: with verification off there is no judge, the prose claim stays at its
        # born `unverified` status, and the disabled-mode effective merge policy is what serves it.
        prose_judge = (
            FaithfulnessJudgeImpl(gateway=gateway, conn_factory=transaction)
            if settings.verification_enabled
            else None
        )
        # One synthesizer instance serves both prose species (E2). The two service fields are the
        # seam for composing them differently later — a different policy, model, or judge per
        # species — not an obligation to build two objects today.
        prose_synthesizer = ProseSynthesizer(gateway=gateway, judge=prose_judge)
        prose_synthesis = ProseSynthesisServices(
            account=prose_synthesizer, contact=prose_synthesizer
        )
        registry = build_toolbelt(
            storage=storage,
            settings=settings,
            gateway=gateway,
            pre_spend_gate=pre_spend_gate,
            research_directive_memory_write_factory=memory_write_factory_builder(settings, gateway),
            queue=task_queue,
            project_execution_router=project_execution_router,
            research_view_composer=(
                research_views.composer if research_views is not None else None
            ),
            research_view_snapshots=(
                research_views.snapshots if research_views is not None else None
            ),
            research_view_recheck=(research_views.recheck if research_views is not None else None),
            contact_content_handoff=contact_content_handoff,
            entity_research_launches=entity_research_launches,
            prose_synthesis=prose_synthesis,
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
        prose_step.bind(tool_invoker)
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
        agent_workspace_factory = None
        # The project DEEP phase remains the R1 loud quarantine. M8D entity runs are independently
        # launched through the promoted tool surfaces and drained by the handler below.
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
            event_emitter=build_run_event_emitter(),
            project_execution_router=project_execution_router,
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
            entity_research_handler=(
                entity_research.handler if entity_research is not None else None
            ),
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
        external_research_wake = _start_external_research_wake(settings)
        try:
            await run_worker(worker)
        finally:
            for background in (
                sweep,
                agent_cleanup,
                exa_discovery,
                exa_targeted_enrichment,
                external_research_wake,
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
