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

This entrypoint also runs the B2 **orphan-blob sweep**, the two D8 **retention sweeps** (spent
``stream_token`` rows — default ON because a swept token was already unreadable; and the design
run-event pruner — default OFF, the one sweep that destroys durable run-visibility history) and
provider lifecycle wake paths as background tasks alongside the worker (started with it, cancelled
on drain). Sweep/wake errors are logged and never fatal to the worker; they do not originate new
quarantined entity-research work.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import stat
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.ports import AgentModelProvider
from clue_agents.sandbox.docker_runner import kill_area_containers
from clue_agents.sandbox.workspaces import SandboxWorkspaces
from clue_agents.worker_area import WorkerArea
from clue_api.agent_execution_wiring import DbAgentPlanJournal
from clue_api.agent_model_wiring import build_agent_model_provider
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    build_agent_platform_components,
)
from clue_api.agent_turn_fleet_wiring import (
    AgentTurnWorkHandler,
    build_agent_turn_work_handler,
    build_design_leg_exit_judge,
    sweep_thread_dispatch,
    sweep_turn_stream_retention,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.agent_workspace_cache import AgentWorkspaceCacheJob
from clue_api.agent_workspace_retention import (
    AgentWorkspaceRetentionJob,
    run_retention_if_due,
)
from clue_api.agent_workspace_snapshots import DbWorkspaceSnapshotStore
from clue_api.agent_workspace_wiring import build_agent_workspace_factory
from clue_api.arv2.account_research_driver import (
    Arv2AccountResearchWorkHandler,
    build_arv2_account_research_handler,
)
from clue_api.arv2.account_research_launch import DbArv2LaunchService
from clue_api.arv2.discovery_driver import (
    Arv2DiscoveryWorkHandler,
    build_arv2_discovery_handler,
)
from clue_api.arv2.discovery_launch import DbArv2DiscoveryService
from clue_api.arv2.display.fleet_handler import build_arv2_display_page_handler
from clue_api.arv2.icp_authoring import DbIcpAuthoringService
from clue_api.arv2.onboarding_driver import (
    CatalogRegenerator,
    CurrentDocumentReader,
    IcpRef,
    IcpSynthesisOutcome,
    OnboardingRunWorkHandler,
    SynthesisLauncher,
    SynthesisOutcome,
    build_onboarding_exa_client_factory,
    build_onboarding_provider_caller,
)
from clue_api.arv2.onboarding_reconcile import CatalogReconciler, OpenRouterCatalogReconciler
from clue_api.arv2.read_tools import DbArv2ReadService
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_api.arv2_wiring import register_arv2_wiring
from clue_api.brand_knowledge_writes import current_brand_version
from clue_api.chat.turn_stream import TurnStreamPolicy
from clue_api.compliance_wiring import register_compliance_wiring
from clue_api.composition import build_pre_spend_gate, load_research_packs
from clue_api.contact_content_handoff import ContactContentHandoffService
from clue_api.contact_research_fleet_launch import ContactResearchSelectionApprover
from clue_api.conversation_naming import build_conversation_namer
from clue_api.crm.read_sinks import CrmReadSinks
from clue_api.crm.write_executor import build_crm_write_handler
from clue_api.design_fleet import (
    build_design_job_handler,
    build_design_leg_lane_driver,
    start_design_event_pruner,
    start_design_reaper,
)
from clue_api.design_leg_wiring import build_design_leg_finisher
from clue_api.design_memory_runtime import build_configured_design_preference_resolver_factory
from clue_api.design_platform_reads import build_design_platform_reads_factory
from clue_api.discovery_wake import DbDiscoveryWake
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
from clue_api.memory_wiring import memory_assembly_factory, memory_write_factory_builder
from clue_api.narrative_wiring import build_client_knowledge_retriever, register_narrative_wiring
from clue_api.official_site_crawl_wiring import build_official_site_crawl_fleet
from clue_api.onboarding_client_binding import Stage0ClientEntityBinder
from clue_api.onboarding_synthesis_wiring import (
    OnboardingSynthesisLauncher,
    RegisteredIcp,
    build_onboarding_synthesis_launcher,
)
from clue_api.persona_request_tools import DbPersonaRequestService
from clue_api.phase_c_wiring import Stage0ScrapeBinder, build_stage0_scrape_binder
from clue_api.product_management import read_brand_document, regenerate_catalog
from clue_api.product_page_writer import build_product_page_handler
from clue_api.product_path_preflight import assert_product_path_composition
from clue_api.production_metrics import production_metrics_lifespan
from clue_api.production_tracing import (
    install_production_langfuse,
    install_production_sentry,
    install_production_tracing,
    production_tracing_lifespan,
)
from clue_api.project_document_tools import DbProjectDocumentService
from clue_api.project_execution_router import (
    DeferredProjectExecutionRouter,
    Recipe1ProjectExecutionRouter,
)
from clue_api.project_library_refresh import ProjectLibraryRefresher
from clue_api.prose_synthesis_step import ProseSynthesisStep
from clue_api.prose_synthesis_tools import ProseSynthesisServices
from clue_api.provider_observers import provider_observer
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    seed_system_recipes,
)
from clue_api.research_view_runtime import build_production_research_view_runtime
from clue_api.run_composition import (
    ComposingRunDriver,
    bind_stage0_search_resolver,
    build_platform_gateway,
    build_stage0_claim_extractor,
)
from clue_api.run_events_wiring import build_run_event_emitter
from clue_api.stage0_setup_fleet import Stage0ReconWorkHandler
from clue_api.storage_wiring import build_storage_backend, run_orphan_blob_sweep_if_due
from clue_api.sumble_discovery_gaps import build_production_sumble_discovery_gap_resolver
from clue_api.supervisor_wiring import DeferredSupervisorActions, ToolbeltSupervisorActions
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.value_narrative_tools import ValueNarrativeServices
from clue_config import Secrets, Settings, default_gateway_config, get_config, load_settings
from clue_config.gateway import GatewayConfig
from clue_core import ProjectPhase
from clue_core.gateway import LLMGateway
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
    sweep_stream_tokens,
)
from clue_fleet import DbTaskQueue, DbWorkQueue, WorkQueue, install_thread_pool, run_worker
from clue_fleet.lease import prune_released_work_leases_if_due
from clue_locks import redis_lifespan
from clue_obs import get_logger, setup
from clue_obs.sentry import capture
from clue_research.adapters import default_scrape_backend
from clue_research.adapters.exa_websets import ExaWebsetsClient
from clue_research.narrative import ProseSynthesizer
from clue_research.resolvers import ScrapePolicy
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


#: How often the fleet prunes ended work leases (on the maintenance clock below).
_WORK_LEASE_PRUNE_EVERY = timedelta(days=1)
#: With snapshots off a chat folder is the only copy, so it stays a day unused (the old purge).
_LOCAL_IDLE_S = 86400.0
#: A media download's temp folder older than this belongs to a process that died.
_MEDIA_TEMP_MAX_AGE_S = 6 * 3600.0
#: How often a worker ASKS whether the fleet owes its expiry pass — not how often the pass runs
#: (that is ``agent_workspace_retention_sweep_interval_s``, daily, kept in the database). A check
#: is one row read, and asking often is what keeps a restarted worker from skipping a whole day.
#: A constant, not a knob, like ``_WORK_LEASE_PRUNE_EVERY`` above.
_RETENTION_CHECK_EVERY_S = 300.0


async def _orphan_sweep_loop(
    settings: Settings,
    storage: StorageBackend,
    *,
    conn_factory: ConnFactory = transaction,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """Every ``storage_orphan_sweep_check_interval_s`` seconds, ask whether the FLEET is due its
    storage sweep (purge erased artifacts, then orphan blobs) and run it if so, until cancelled.

    The interval ``storage_orphan_sweep_interval_s`` belongs to the fleet, not to this process:
    :func:`~clue_api.storage_wiring.run_orphan_blob_sweep_if_due` keeps the last run in the
    database, so a restart never resets it and one process sweeps (2026-10-09; it used to be every
    6 h in every process, on a timer each deploy reset). Each pass is fully isolated: a sweep fault
    is logged and the loop continues — the sweep must never sink the worker."""
    every = timedelta(seconds=settings.storage_orphan_sweep_interval_s)
    check = settings.storage_orphan_sweep_check_interval_s
    while True:
        await sleep(check)
        try:
            async with conn_factory() as conn:
                deleted = await run_orphan_blob_sweep_if_due(conn, every=every, storage=storage)
            if deleted is not None:
                log.info("fleet.orphan_sweep.ran", deleted=len(deleted))
        except Exception as exc:  # noqa: BLE001 — a sweep fault is non-fatal to the worker
            log.warning("fleet.orphan_sweep.error", exc_info=True)
            capture(exc)
        # The same maintenance clock prunes ended work leases (2026-10-16): release keeps a lease's
        # row so its generation never repeats, and rows ended a month ago, whose work has no live
        # task, are removed once a day. Its own transaction, so a storage fault never skips it.
        try:
            async with conn_factory() as conn:
                pruned = await prune_released_work_leases_if_due(
                    conn, every=_WORK_LEASE_PRUNE_EVERY
                )
            if pruned is not None:
                log.info("fleet.work_lease_prune.ran", pruned=pruned)
        except Exception as exc:  # noqa: BLE001 — a prune fault is non-fatal to the worker
            log.warning("fleet.work_lease_prune.error", exc_info=True)
            capture(exc)


def _start_orphan_sweep(settings: Settings, storage: StorageBackend) -> asyncio.Task[None] | None:
    """Start the background orphan-sweep task, or ``None`` when disabled
    (``storage_orphan_sweep_interval_s`` or its check interval ``<= 0``). Must be called with a
    running event loop."""
    if (
        settings.storage_orphan_sweep_interval_s <= 0
        or settings.storage_orphan_sweep_check_interval_s <= 0
    ):
        log.info("fleet.orphan_sweep.disabled")
        return None
    return asyncio.create_task(_orphan_sweep_loop(settings, storage))


async def _stream_token_sweep_loop(
    settings: Settings,
    *,
    conn_factory: ConnFactory = transaction,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """Run :func:`~clue_execution.sweep_stream_tokens` every ``stream_token_sweep_interval_s``
    seconds until cancelled (Part II D8, ruling R-D8-4). Modelled on the orphan-blob sweep above,
    down to the per-pass isolation: a sweep fault is logged and the loop continues.

    Deleting a spent token is semantically free — both consume statements require
    ``used_at IS NULL AND expires_at > now()``, so every row this removes was already unreadable by
    every code path — which is why this loop is ON by default while the design-event pruner below
    is off."""
    interval = settings.stream_token_sweep_interval_s
    while True:
        await sleep(interval)
        try:
            async with conn_factory() as conn:
                deleted = await sweep_stream_tokens(conn)
            if deleted:
                log.info("fleet.stream_token_sweep.deleted", count=deleted)
        except Exception as exc:  # noqa: BLE001 — a sweep fault is non-fatal to the worker
            log.warning("fleet.stream_token_sweep.error", exc_info=True)
            capture(exc)


def _start_stream_token_sweep(settings: Settings) -> asyncio.Task[None] | None:
    """Start the background stream-token sweep, or ``None`` when disabled
    (``stream_token_sweep_interval_s <= 0``). Must be called with a running event loop."""
    if settings.stream_token_sweep_interval_s <= 0:
        log.info("fleet.stream_token_sweep.disabled")
        return None
    return asyncio.create_task(_stream_token_sweep_loop(settings))


async def _chat_sweep_loop(
    settings: Settings,
    *,
    conn_factory: ConnFactory = transaction,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """FI Lane D D3's two chat sweeps, every ``chat_sweep_interval_s`` seconds until cancelled.

    * **Stranded dispatch** — a thread whose queued submission never got its fleet task, because the
      process died between finalizing a task and offering the thread's next turn. Self-healing but,
      without this, only on that thread's next POST.
    * **Turn-outbox retention** — prune terminal turns' frames past the replay window (§3.3(7)).

    Isolated exactly like the orphan sweep: a fault is logged and the loop continues. Neither sweep
    may ever sink the worker, and neither touches a live turn.
    """
    interval = settings.chat_sweep_interval_s
    while True:
        await sleep(interval)
        try:
            dispatched = await sweep_thread_dispatch(conn_factory)
            pruned = await sweep_turn_stream_retention(
                conn_factory,
                retention_s=settings.chat_turn_event_retention_s,
            )
            if dispatched or pruned:
                log.info("fleet.chat_sweep.done", dispatched=dispatched, pruned=pruned)
        except Exception as exc:  # noqa: BLE001 — a sweep fault is non-fatal to the worker
            log.warning("fleet.chat_sweep.error", exc_info=True)
            capture(exc)


def _start_chat_sweep(settings: Settings) -> asyncio.Task[None] | None:
    """Start the chat sweep task, or ``None`` when chat or the cadence is disabled."""
    if not settings.chat_enabled or settings.chat_sweep_interval_s <= 0:
        return None
    return asyncio.create_task(_chat_sweep_loop(settings))


async def _workspace_cache_sweep_loop(
    interval_s: float,
    job: AgentWorkspaceCacheJob,
    *,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    while True:
        await sleep(interval_s)
        try:
            # Deleting folders is blocking file work; keep it off the event loop.
            await asyncio.to_thread(job.run_once)
        except Exception as exc:  # noqa: BLE001 — a cleanup fault must not sink run execution
            log.warning("fleet.workspace_cache_sweep.error", exc_info=True)
            capture(exc)


def _workspace_cache_job(settings: Settings, area: WorkerArea) -> AgentWorkspaceCacheJob:
    """The sweep for this worker's area (WS-16, WS-17; AW-11, AW-17).

    With snapshots off a deleted folder is gone for good, so the idle window is a day, like the
    old purge, instead of the 30 minutes a restorable copy can afford. With snapshots on, each
    sweep also removes the switch's leftover ``<root>/local`` once no snapshots-off process is
    alive (only the snapshots-on side ever removes it).
    """

    snapshots = settings.agent_workspace_snapshots_enabled
    root = settings.agent_workspace_root
    return AgentWorkspaceCacheJob(
        area=area,
        idle_s=settings.agent_workspace_cache_idle_s if snapshots else _LOCAL_IDLE_S,
        max_bytes=settings.agent_workspace_cache_max_bytes,
        leftover_local_root=Path(root) if snapshots and root is not None else None,
    )


def _start_workspace_cache_sweep(
    settings: Settings, area: WorkerArea | None
) -> asyncio.Task[None] | None:
    if area is None:
        log.info("fleet.workspace_cache_sweep.disabled")
        return None
    return asyncio.create_task(
        _workspace_cache_sweep_loop(
            settings.agent_workspace_cache_sweep_interval_s,
            _workspace_cache_job(settings, area),
        )
    )


async def _workspace_retention_loop(
    interval_s: float,
    job: AgentWorkspaceRetentionJob,
    every: timedelta,
    *,
    conn_factory: ConnFactory = transaction,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    """Every ``interval_s`` seconds, ask whether the FLEET is due its expiry pass and run it if so.

    ``every`` belongs to the fleet, not to this process:
    :func:`~clue_api.agent_workspace_retention.run_retention_if_due` keeps the last run in the
    database, so a restart never resets it, and the pass claims itself in a short transaction, so
    one process runs while the others skip however long it takes. A fault is logged and the loop
    continues — expiring old files must never sink run execution."""

    while True:
        await sleep(interval_s)
        try:
            report = await run_retention_if_due(job=job, every=every, conn_factory=conn_factory)
            if report is not None:
                log.info(
                    "fleet.workspace_retention.ran",
                    chats_checked=report.chats_checked,
                    chats_expired=report.chats_expired,
                    files_expired=report.files_expired,
                    skipped_busy=report.skipped_busy,
                    stale=report.stale,
                    failed=report.failed,
                )
        except Exception as exc:  # noqa: BLE001 — a cleanup fault must not sink run execution
            log.warning("fleet.workspace_retention.error", exc_info=True)
            capture(exc)


def _start_workspace_retention(
    settings: Settings, storage: StorageBackend
) -> asyncio.Task[None] | None:
    """Start the F3 Phase 2 expiry job (WS-26, AW-24), or ``None`` when snapshots are off.

    With snapshots off a chat's folder is the only copy of its files and nothing holds them in
    storage, so there is nothing for this job to expire; the cache sweep's own day-long idle
    window is the whole of retention then.
    """

    if not settings.agent_workspace_snapshots_enabled:
        log.info("fleet.workspace_retention.disabled")
        return None
    job = AgentWorkspaceRetentionJob(
        store=DbWorkspaceSnapshotStore(
            storage=storage,
            conn_factory=transaction,
            concurrency=settings.agent_workspace_transfer_concurrency,
        ),
        conn_factory=transaction,
        raw_s=settings.agent_workspace_raw_retention_s,
        working_s=settings.agent_workspace_working_retention_s,
    )
    every = timedelta(seconds=settings.agent_workspace_retention_sweep_interval_s)
    return asyncio.create_task(_workspace_retention_loop(_RETENTION_CHECK_EVERY_S, job, every))


def _remove_stale_media_dirs(temp_root: Path, *, now: float | None = None) -> int:
    """Remove ``arv2-media-*`` temp folders this user left over 6 hours ago; return how many.

    A media download that died with its process leaves its ``TemporaryDirectory`` behind. Run at
    start-up only; a live download's folder is never that old.
    """

    cutoff = (time.time() if now is None else now) - _MEDIA_TEMP_MAX_AGE_S
    removed = 0
    for folder in temp_root.glob("arv2-media-*"):
        try:
            metadata = folder.lstat()
        except OSError:
            continue
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mtime >= cutoff
        ):
            continue
        shutil.rmtree(folder, ignore_errors=True)
        removed += 1
    return removed


def _clean_up_at_start(settings: Settings, area: WorkerArea | None) -> None:
    """What a worker's previous process may have left running or on disk (plan Task 10)."""

    if area is not None and settings.agent_workspace_snapshots_enabled and settings.sandbox_enabled:
        killed = kill_area_containers(area.name)
        if killed:
            log.info("fleet.sandbox.leftover_containers_killed", area=area.name, count=killed)
    removed = _remove_stale_media_dirs(Path(tempfile.gettempdir()))
    if removed:
        log.info("fleet.media_temp.removed", count=removed)


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
        except Exception as exc:  # noqa: BLE001 - one wake scan must not sink the fleet
            log.warning("fleet.external_research.wake_error", exc_info=True)
            capture(exc)
        await sleep(settings.external_research_wake_worker_interval_s)


def _start_external_research_wake(settings: Settings) -> asyncio.Task[None]:
    # The loop always runs (R11.2): the compiled registry always carries the DEEP fleet source,
    # because the R11.1 DEEP bridge is composed for every project run and a run parked at a DEEP
    # ``waiting_external`` checkpoint is only re-entered by a wake.  The three provider sources
    # stay flag-gated, so with every provider off this loop scans exactly one query.
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
    async with ExaWebsetsClient(
        api_key=api_key, lookup_attempts=1, observe=provider_observer("exa_websets")
    ) as client:
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
        transport_factory=lambda: ExaWebsetsClient(
            api_key=api_key, lookup_attempts=1, observe=provider_observer("exa_websets")
        ),
        storage=storage,
        enforce_budget=settings.budget_controls_enabled,
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
    async with ExaWebsetsClient(
        api_key=api_key, lookup_attempts=1, observe=provider_observer("exa_websets")
    ) as client:
        worker = ExaTargetedEnrichmentWorker(
            coordinator=ExaTargetedEnrichmentCoordinator(
                transport=client,
                storage=storage,
                enforce_budget=settings.budget_controls_enabled,
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


def _build_stage0_scrape_binder(
    settings: Settings, *, gateway: LLMGateway | None, secrets: Secrets | None = None
) -> Stage0ScrapeBinder | None:
    """The worker's live Stage-0 scrape composition — the HTTP root's, with the same extractor.

    Flag-gated exactly as ``projections_main`` is: with ``legacy_stage0_recon_enabled`` off
    (the default since 2026-09-12 — ledger A4 split it off ``self_serve_provisioning_enabled``)
    there is no binder and ``start_recon`` keeps refusing before any spend. The ``gateway`` is the
    one ``_serve`` already built for every other model consumer in this process — this seam takes it
    rather than building a second client for the same credential.

    Slice 3 task 7: the tier-3 ``exa_search`` source is bound here too, over the same extractor
    instance and the same account lookup, so the background research lane the worker drives can
    fill ``client.competitor`` / ``client.buyer_profile``. Bound only with an Exa credential.
    """
    # 2026-09-12: the old recon is its own switch (ledger A4); provisioning no longer implies it.
    if not settings.legacy_stage0_recon_enabled:
        return None
    extractor = build_stage0_claim_extractor(gateway)
    binder = build_stage0_scrape_binder(
        extractor=extractor,
        scraper=default_scrape_backend(settings),
        policy=ScrapePolicy(),
    )
    bind_stage0_search_resolver(extractor=extractor, accounts=binder, secrets=secrets)
    return binder


class _SynthesisSeam:
    """Join O4's launcher to O3's ``SynthesisLauncher`` seam at the composition root.

    The two lanes were built apart: the driver reads four fields of a step outcome, the launcher
    returns those four plus the document ids it registered. Nothing else differs, so the join is a
    field-for-field copy here rather than a shared type either lane would have had to import from
    the other before it existed.

    Both turns cross here. The ICP turn's ``RegisteredIcp`` rows become the driver's ``IcpRef``s on
    the way out, and each one comes back as its own ``RegisteredIcp`` when the driver opens that
    ICP's persona turn — the same fields, copied in both directions. ``project_id`` is one of them:
    a persona is written in the scope of the ICP it is about, and a personas-only run carries that
    scope in from its fleet payload rather than deriving it here.
    """

    def __init__(self, launcher: OnboardingSynthesisLauncher) -> None:
        self._launcher = launcher

    async def launch_icps(
        self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID
    ) -> IcpSynthesisOutcome:
        result = await self._launcher.launch_icps(
            workspace_id=workspace_id, brand_id=brand_id, run_id=run_id, step_id=step_id
        )
        return IcpSynthesisOutcome(
            status=result.status,
            failure_code=result.failure_code,
            failure_message=result.failure_message,
            cost_usd=result.cost_usd,
            icps=tuple(
                IcpRef(
                    document_id=icp.document_id,
                    icp_key=icp.icp_key,
                    version=icp.version,
                    path=icp.path,
                    project_id=icp.project_id,
                )
                for icp in result.icps
            ),
        )

    async def launch_persona(
        self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID, icp: IcpRef
    ) -> SynthesisOutcome:
        result = await self._launcher.launch_persona(
            workspace_id=workspace_id,
            brand_id=brand_id,
            run_id=run_id,
            step_id=step_id,
            icp=RegisteredIcp(
                document_id=icp.document_id,
                icp_key=icp.icp_key,
                version=icp.version,
                path=icp.path,
                project_id=icp.project_id,
            ),
        )
        return SynthesisOutcome(
            status=result.status,
            failure_code=result.failure_code,
            failure_message=result.failure_message,
            cost_usd=result.cost_usd,
        )


def _build_onboarding_handler(
    settings: Settings,
    secrets: Secrets,
    *,
    storage: StorageBackend,
    synthesis: SynthesisLauncher | None = None,
) -> OnboardingRunWorkHandler | None:
    """The ARV2 onboarding lane (Track O, O3) on this worker, behind ``onboarding_v2_enabled``.

    The client-entity seam is injected from *outside* ``clue_api.arv2`` (the lane may not import
    ``clue_research.stage0``). ``synthesis`` is O4's launcher behind :class:`_SynthesisSeam`, or
    ``None`` when the agent platform is not composed — then the synthesis step settles ``empty``
    with its reason rather than pretending it ran.

    A deployment that turns the flag on without ``CLUE_EXA_API_KEY`` gets a loud warning and **no
    handler**: the enqueued runs then wait in the queue for a correctly-credentialed worker,
    which is the honest outcome. Failing the boot instead would take every other kind of work on
    this process down with it, and composing a keyless handler would fail each run at its first
    provider call.
    """
    if not settings.onboarding_v2_enabled:
        return None
    try:
        exa = build_onboarding_exa_client_factory(secrets)
    except ValueError:
        log.warning(
            "onboarding.handler_not_composed",
            reason="CLUE_EXA_API_KEY is not configured",
            detail=(
                "CLUE_ONBOARDING_V2_ENABLED is on but this worker has no Exa credential; "
                "onboarding runs stay queued until a worker with CLUE_EXA_API_KEY drains them"
            ),
        )
        return None
    return OnboardingRunWorkHandler(
        settings=settings,
        conn_factory=transaction,
        artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction),
        exa=exa,
        client_binder=Stage0ClientEntityBinder(),
        synthesis=synthesis,
        reconciler_factory=_build_catalog_reconciler_factory(settings, secrets),
        catalog_regenerator=_catalog_regenerator(storage),
        current_document=_current_brand_document(storage),
    )


def _catalog_regenerator(storage: StorageBackend) -> CatalogRegenerator:
    """Spec 2026-10-15 §9: a re-run that met merged or removed products rebuilds the catalog."""

    async def regenerate(conn: AsyncConnection, *, workspace_id: str, brand_id: str) -> object:
        return await regenerate_catalog(
            conn, storage, workspace_id=workspace_id, brand_id=brand_id, change_id=None
        )

    return regenerate


def _current_brand_document(storage: StorageBackend) -> CurrentDocumentReader:
    """R-4.5: the customers step reads the current ``proof/customers.md`` to keep its CRM rows."""

    async def read(
        conn: AsyncConnection, *, workspace_id: str, brand_id: str, path: str
    ) -> str | None:
        current = await current_brand_version(
            conn, workspace_id=workspace_id, brand_id=brand_id, path=path
        )
        if current is None:
            return None
        found = await read_brand_document(
            conn,
            storage,
            workspace_id=workspace_id,
            brand_id=brand_id,
            document_id=current.document_id,
        )
        return None if found is None else found[1]

    return read


def _build_catalog_reconciler_factory(
    settings: Settings, secrets: Secrets
) -> Callable[[RawSink, LedgerSink], CatalogReconciler] | None:
    """The catalog identity ladder's model stage, behind the reconcile flag.

    (``CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED``, model ``CLUE_ONBOARDING_RECONCILE_MODEL``.)

    A **factory of one reconciler per run**, not a reconciler: the call spends through R1's
    ``ProviderCaller`` built over the catalog step's own buffered sinks, so its one call lands on
    ``provider_call_ledger`` with the run's stamp (slice 1b) — the driver hands the factory the
    sinks.

    Missing credential ≠ missing handler here (unlike the Exa key one level up): without the model
    stage the ladder still runs its deterministic rungs, which is exactly what it did before the
    stage existed. So a keyless worker composes normally and says so once, at composition, rather
    than either refusing to drain onboarding work or failing every run at the reconcile call.
    """
    if not settings.onboarding_catalog_reconcile_enabled:
        # Deliberate, so it is stated rather than warned about — but stated, because "why did this
        # run mint a near-miss product row?" should be answerable from the boot log alone.
        log.info(
            "onboarding.reconciler_not_composed",
            reason="CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED is off",
            detail="the catalog sync runs its deterministic rungs only",
        )
        return None
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        log.warning(
            "onboarding.reconciler_not_composed",
            reason="CLUE_OPENROUTER_API_KEY is not configured",
            detail=(
                "CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED is on but this worker has no model "
                "credential; the catalog sync runs its deterministic rungs only, so a lineup "
                "entry no spelling key matches mints a new product row"
            ),
        )
        return None
    base_url = GatewayConfig().base_url

    def factory(raw: RawSink, ledger: LedgerSink) -> CatalogReconciler:
        return OpenRouterCatalogReconciler(
            caller_factory=lambda: build_onboarding_provider_caller(raw=raw, ledger=ledger),
            api_key=key,
            model=settings.onboarding_reconcile_model,
            base_url=base_url,
        )

    return factory


def _build_arv2_account_research_handler(
    settings: Settings,
    secrets: Secrets,
    *,
    storage: StorageBackend,
    model_provider: AgentModelProvider | None,
    queue: WorkQueue,
) -> Arv2AccountResearchWorkHandler | None:
    """The ARV2 account-research lane (Track R, R2) on this worker, behind its own flag.

    Same posture as onboarding above, and for the same reason: a worker that is missing a
    credential (or the model provider that needs one) gets a named warning and **no handler**, so
    the enqueued jobs wait for a correctly-configured worker instead of failing one by one after
    they have already spent model rounds.

    The artifact sink and the model provider are injected from *outside* the lane — ARV2 may not
    open a second write path into the artifact table, and it may not reach the vendor SDK behind
    ``clue_gateway``. What the lane itself decides is which credentials a job needs and which
    model id it runs on (``build_arv2_account_research_handler``).
    """
    if not settings.arv2_account_research_enabled:
        return None
    if model_provider is None:
        log.warning(
            "arv2.account_handler_not_composed",
            reason="CLUE_OPENROUTER_API_KEY is not configured",
            detail=(
                "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is on but this worker has no model "
                "credential; account research jobs stay queued until a worker with "
                "CLUE_OPENROUTER_API_KEY drains them"
            ),
        )
        return None
    from clue_api.quality_research_wiring import build_quality_job_runner

    return build_arv2_account_research_handler(
        settings,
        secrets,
        storage=storage,
        artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction),
        model_provider=model_provider,
        quality_runner=build_quality_job_runner(
            settings=settings, storage=storage, connections=transaction, models=model_provider
        ),
        # R3: an account job that resolves a committee creates one person job per member and offers
        # it here, on this process's own queue — the same one the launch service uses, so a fanned
        # out person job is queued through exactly the machinery that drains it.
        queue=queue,
    )


async def _quality_reconcile_loop(
    handler: Arv2AccountResearchWorkHandler, settings: Settings
) -> None:
    while True:
        try:
            offered = await handler.sweep_quality()
            if offered:
                log.info("arv2.quality.continuations_offered", count=offered)
        except Exception as error:
            log.warning("arv2.quality.continuation_sweep_failed", exc_info=True)
            capture(error)
        await asyncio.sleep(settings.arv2_quality_reconcile_interval_s)


def _build_arv2_discovery_handler(
    settings: Settings,
    secrets: Secrets,
    *,
    storage: StorageBackend,
) -> Arv2DiscoveryWorkHandler | None:
    """The ARV2 discovery lane (Track R, R4) on this worker, behind its own flag.

    Same posture as the account lane above: a worker that is missing the Exa credential gets a
    named warning and **no handler**, so launched runs wait for a correctly-configured worker
    instead of claiming a row and failing at their first provider call. The artifact sink is
    injected from *outside* the lane — ARV2 may not open a second write path into the artifact
    table — and what the lane itself decides is which credential a run needs and the refusal when
    it is missing (``build_arv2_discovery_handler``).
    """
    if not settings.arv2_discovery_enabled:
        return None
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=transaction)
    return build_arv2_discovery_handler(
        settings,
        secrets,
        storage=storage,
        artifacts=artifacts,
        # Spec 2026-09-30 §4: a run launched from a thread ends by queuing the Head of ABM's turn
        # there. Built here, outside the lane, because it writes a turn submission.
        wake=DbDiscoveryWake(artifacts),
    )


async def _serve() -> None:
    """Open the process-wide DB + Redis lifecycles, register the boot handlers, and drive the worker
    (with the orphan sweep alongside) until a graceful stop."""
    settings = load_settings()
    # Before anything runs a thread: provider calls and the heartbeat's DNS lookups share this pool.
    install_thread_pool(asyncio.get_running_loop(), max_workers=settings.fleet_thread_pool_size)
    secrets = Secrets()
    # Startup gate: a declared product path that is missing a provider credential refuses here,
    # before any lifecycle is opened or handler composed (see ``product_path_preflight``).
    assert_product_path_composition(settings, secrets)
    # Lane 3 slice 2: the worker's tracer provider (and Sentry) before any lifecycle is opened, so
    # every task span belongs to one provider. Both are no-ops without an endpoint / a DSN.
    tracing = install_production_tracing(settings, secrets, service_name="clue-worker-fleet")
    install_production_sentry(settings, secrets, service_name="clue-worker-fleet")
    install_production_langfuse(
        settings, secrets, runtime=tracing, service_name="clue-worker-fleet"
    )
    storage = build_storage_backend(settings)
    async with (
        production_tracing_lifespan(tracing),
        production_metrics_lifespan(
            settings,
            service_name="clue-worker-fleet",
        ),
        db_lifespan(),
        redis_lifespan(),
    ):
        register_compliance_wiring()
        register_narrative_wiring()
        register_arv2_wiring()
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
        prose_step = ProseSynthesisStep(
            narrative_enabled=settings.value_narrative_synthesis_enabled
        )
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
        # Lane E E3. The positioning services share the same toggle-following judge; the
        # Client-Knowledge retriever is the api-root `read_client_kb_claims` seam (pgvector lands
        # behind the same signature later). Composed only under the flag, so a disabled deployment
        # registers the tool and refuses it rather than holding a live positioning surface.
        value_narrative = (
            ValueNarrativeServices(
                gateway=gateway,
                judge=prose_judge,
                retriever=build_client_knowledge_retriever(conn_factory=transaction),
                conn_factory=transaction,
            )
            if settings.value_narrative_synthesis_enabled
            else None
        )
        discovery_batch_starter = _build_exa_discovery_starter(
            settings,
            secrets=secrets,
            storage=storage,
        )
        # ARV2 Track R, R2 (seam 1). The launch service is composed only where the lane is: with
        # the flag off the two tools still register and refuse
        # ``arv2_account_research_not_composed`` before any spend. It shares this process's work
        # queue, so a launched job is queued through exactly the machinery that drains it.
        arv2_account_launch = (
            DbArv2LaunchService(settings, storage, queue=work_queue)
            if settings.arv2_account_research_enabled
            else None
        )
        # ARV2 Track R, R4, on exactly the same terms: composed only behind
        # ``arv2_discovery_enabled``, sharing this process's work queue so a launched run is
        # offered through the machinery that drains it.
        arv2_discovery_launch = (
            DbArv2DiscoveryService(settings, storage, queue=work_queue)
            if settings.arv2_discovery_enabled
            else None
        )
        # The project library's refresher (2026-09-14): the two writing tools below rebuild this
        # project's library once their write has committed, so the settled state the frontend reads
        # is the state the tool just wrote rather than the state of the last turn. The factory is
        # this worker's own, on the shared root — the tree replace is atomic across processes — and
        # it is the same one the workspace cache sweep cleans below. Without a configured workspace
        # root there is no refresher and both hooks are no-ops.
        agent_workspace_factory = (
            build_agent_workspace_factory(storage=storage, settings=settings)
            if settings.agent_workspace_root is not None
            else None
        )
        # Since F3 (AW-20) the refresher writes nothing to disk: a forced refresh bumps the
        # project's library epoch, and each chat resyncs its own copy on its next turn.
        project_library = ProjectLibraryRefresher(conn_factory=transaction)
        # ICP authoring needs no flag of its own: writing a proposal spends nothing and confirms
        # nothing. What it needs is the storage the knowledge documents live in, so it composes
        # where the composed backend is. Without a service the tool registers and refuses by name.
        icp_authoring = DbIcpAuthoringService(storage, library=project_library)
        # The persona request DOES need the onboarding flag: what it opens is an onboarding run,
        # and with the lane off no worker would ever drive it — the row would sit ``queued``
        # forever, holding that ICP document's one open slot. Off, the tool refuses by name.
        persona_requests = (
            DbPersonaRequestService(queue=work_queue) if settings.onboarding_v2_enabled else None
        )
        # The project plan has no flag of its own either: writing it down spends nothing and
        # confirms nothing, and it needs only the storage the knowledge documents live in.
        # Without a service the tool registers and refuses by name.
        project_documents = DbProjectDocumentService(storage, library=project_library)
        # The ARV2 reads have no flag at all, and need no storage: they read rows that exist on
        # every deployment (account membership, display blocks, claims, discovery runs) and reading
        # them spends nothing. Composed unconditionally; the tools refuse by name only where the
        # read surface itself is absent. ``settings`` is here for one predicate: the claims read
        # mirrors the account page's display gate, whose tier-4 arm is armed by
        # ``verification_enabled``.
        arv2_reads = DbArv2ReadService(settings=settings)
        # The code sandbox's one registry (spec 2026-09-19 §3.4), built HERE because two
        # composition steps need the SAME object: the toolbelt, whose ``run_python@1`` looks a
        # turn up in it, and the platform components, whose conversation engine registers the
        # turn in it while it holds the lease. Two instances would mean a tool that can never
        # find the turn the engine bound. With the sandbox off nothing is composed, both sides
        # get ``None``, and the tool refuses by name.
        sandbox_workspaces = (
            SandboxWorkspaces(max_runs_per_turn=settings.sandbox_max_runs_per_turn)
            if settings.sandbox_enabled
            else None
        )
        # The CRM reads' one registry, for the same two-sided reason: ``run_crm_action@1`` looks
        # the turn's ``reads/`` folder up in it, and the conversation engine binds it there.
        crm_read_sinks = CrmReadSinks()
        registry = build_toolbelt(
            storage=storage,
            settings=settings,
            # ARV2 O4: ``build_toolbelt(secrets=...)`` is fail-closed — the default ``None`` means
            # *no credentials*, and ``exa_search_evidence@1`` would then refuse
            # ``exa_not_configured`` before any spend. This production root passes the real
            # secrets so the synthesis turn's one evidence call can actually reach Exa.
            secrets=secrets,
            gateway=gateway,
            # FI-4 slice 2 / slice 3: same live scrape composition as projections_main, behind the
            # same flag, and now with the same REAL extractor — reusing the gateway built above, so
            # recon drafts grounded client.* values instead of capturing snapshots nobody claims
            # from. When the flag is off start_recon keeps refusing.
            stage0_scrape_binder=_build_stage0_scrape_binder(
                settings, gateway=gateway, secrets=secrets
            ),
            pre_spend_gate=pre_spend_gate,
            research_directive_memory_write_factory=memory_write_factory_builder(settings, gateway),
            queue=task_queue,
            project_execution_router=project_execution_router,
            confirmed_discovery_preflight=discovery_batch_starter,
            research_view_composer=(
                research_views.composer if research_views is not None else None
            ),
            research_view_snapshots=(
                research_views.snapshots if research_views is not None else None
            ),
            research_view_recheck=(research_views.recheck if research_views is not None else None),
            contact_content_handoff=contact_content_handoff,
            entity_research_launches=entity_research_launches,
            arv2_account_launch=arv2_account_launch,
            arv2_discovery_launch=arv2_discovery_launch,
            arv2_reads=arv2_reads,
            icp_authoring=icp_authoring,
            persona_requests=persona_requests,
            project_documents=project_documents,
            prose_synthesis=prose_synthesis,
            value_narrative=value_narrative,
            sandbox_workspaces=sandbox_workspaces,
            crm_read_sinks=crm_read_sinks,
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
        # The project DEEP phase remains the R1 loud quarantine. M8D entity runs are independently
        # launched through the promoted tool surfaces and drained by the handler below.
        driver = ComposingRunDriver(
            settings=settings,
            gateway=gateway,
            storage=storage,
            discovery_batch_starter=discovery_batch_starter,
            discovery_required_field_resolver=build_production_sumble_discovery_gap_resolver(
                settings,
                secrets=secrets,
                storage=storage,
            ),
            event_emitter=build_run_event_emitter(),
            project_execution_router=project_execution_router,
        )
        # FI Lane D D2: the production conversation turn executor, composed ONCE here (§3-P3) and
        # reused by every turn. Only when chat is enabled — nothing enqueues ``agent_turn`` tasks
        # otherwise, and an unused composition would still resolve a profile and a manifest at boot.
        # ORDERING IS LOAD-BEARING: this must compose BEFORE ``register_execution_control_tools``
        # widens the shared registry. ``build_agent_platform_components`` audits the registry
        # against ``C6_AGENT_TOOL_AUTHORITY``, whose reviewed surface is exactly the model-facing
        # toolbelt (``build_toolbelt`` names — pinned by ``test_tool_authority_audit``); the
        # run-control tools registered below are the human/API run-control plane sharing this
        # registry object, not model-surface tools, and composing after them fails the audit
        # at boot.
        # ARV2 O4: the onboarding synthesis turn needs the SAME agent platform components as the
        # conversation turn (profiles, models, workspaces, artifacts, turn journal), so the one
        # composition is shared by both switches rather than duplicated per surface.
        agent_turn_handler: AgentTurnWorkHandler | None = None
        memory = (
            memory_assembly_factory(settings, transaction)
            if settings.chat_enabled
            or (settings.design_runtime_enabled and settings.design_preference_context_enabled)
            else None
        )
        design_preference_resolver_factory = (
            build_configured_design_preference_resolver_factory(
                settings=settings, memory=memory, conn_factory=transaction
            )
            if memory is not None
            else None
        )
        # Design note 2026-09-19: what a design LEG turn may read from the platform mid-turn —
        # the target account's research through the governed tools, and the seller's pinned
        # knowledge. Composed HERE, with this worker's journaled invoker and storage, because the
        # design runtime opens no platform database; gated on the same switch as the lane below,
        # since a deployment that runs no design work has nothing to read for.
        design_platform_reads_factory = (
            build_design_platform_reads_factory(
                invoker=tool_invoker, storage=storage, conn_factory=transaction
            )
            if settings.design_runtime_enabled
            else None
        )
        platform_components: AgentPlatformComponents | None = None
        if settings.chat_enabled or settings.onboarding_v2_enabled:
            platform_components = build_agent_platform_components(
                settings=settings,
                secrets=secrets,
                gateway_config=gateway_config,
                storage=storage,
                tools=registry,
                sandbox_workspaces=sandbox_workspaces,
                crm_read_sinks=crm_read_sinks,
            )
        if settings.chat_enabled and platform_components is not None:
            assert memory is not None
            # Conversation naming (2026-09-18 §4.1): composed once at boot. It states its own
            # absence — off by flag, or no OpenRouter key — and a worker without one simply
            # leaves every chat and Home project on its placeholder name.
            namer = build_conversation_namer(
                settings=settings,
                secrets=secrets,
                artifacts=platform_components.artifacts,
                conn_factory=transaction,
            )
            agent_turn_handler = build_agent_turn_work_handler(
                components=platform_components,
                tools=registry,
                tool_invoker=tool_invoker,
                executor=executor,
                compatibility=compatibility,
                recipes=recipe_reader,
                starter=starter,
                parameters=execution_parameters,
                memory=memory,
                queue=work_queue,
                # ARV2 onboarding O6: the same backend the onboarding synthesis seam receives —
                # the turn reads its pinned brand-knowledge documents from it.
                storage=storage,
                # P3.4: the design-leg lane. Same switch as the design_job handler below —
                # a worker that drains design work can also drive a leg's design turns
                # inline; one that does not composes the fail-loud unavailable lane.
                design_lane=build_design_leg_lane_driver(
                    enabled=settings.design_runtime_enabled,
                    preference_resolver_factory=design_preference_resolver_factory,
                    platform_reads_factory=design_platform_reads_factory,
                ),
                # P3.7: the §2.2 exit bridge — the design role's own catalog model judges
                # each leg message pre-dispatch, and the governed finish tool executes a
                # finish verdict. Same switch as the lane: without the design runtime the
                # judge is absent and every leg message simply designs.
                design_exit_judge=(
                    build_design_leg_exit_judge(
                        models=platform_components.models,
                        profiles=platform_components.profiles,
                    )
                    if settings.design_runtime_enabled
                    else None
                ),
                design_leg_finisher=build_design_leg_finisher(invoker=tool_invoker),
                design_preference_context_enabled=settings.design_preference_context_enabled,
                namer=namer,
                streaming=settings.chat_turn_streaming_enabled,
                stream_policy=TurnStreamPolicy(
                    batch_max_chars=settings.chat_turn_stream_batch_max_chars,
                    batch_interval_s=settings.chat_turn_stream_batch_interval_s,
                    # The dev-only raw-reasoning lens. ``raw`` is refused at settings construction
                    # outside a dev deployment, so a production worker composes ``False`` here or
                    # does not start at all.
                    reasoning_trace=settings.chat_reasoning_trace_mode == "raw",
                    # FI pilot budget-controls: with the switch off the gate card carries no price.
                    gate_amount_visible=settings.budget_controls_enabled,
                ),
                stop_poll_interval_s=settings.chat_turn_stop_poll_interval_s,
            )
        # ARV2 O4: the onboarding synthesis turn's production seam. Composed under the same
        # ordering rule as the conversation turn above — before ``register_execution_control_tools``
        # widens the shared registry, because the launcher resolves the ONBOARDING_SYNTHESIS
        # profile against the model-facing toolbelt the C6 authority audit covers.
        synthesis_launcher: OnboardingSynthesisLauncher | None = None
        if settings.onboarding_v2_enabled and platform_components is not None:
            synthesis_launcher = build_onboarding_synthesis_launcher(
                settings=settings,
                secrets=secrets,
                storage=storage,
                components=platform_components,
                tools=registry,
                tool_invoker=tool_invoker,
                executor=executor,
                compatibility=compatibility,
                plans=DbAgentPlanJournal(conn_factory=transaction),
                recipes=recipe_reader,
                starter=starter,
                parameters=execution_parameters,
            )
        # O3's OnboardingRunWorkHandler takes this below, through ``_SynthesisSeam``.
        log.info(
            "onboarding_synthesis.launcher_composed",
            enabled=synthesis_launcher is not None,
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
        official_site_crawl = build_official_site_crawl_fleet(
            settings=settings,
            secrets=secrets,
            storage=storage,
            gateway=gateway,
            queue=work_queue,
        )
        stage0_recon_handler = (
            Stage0ReconWorkHandler(
                tool_invoker=tool_invoker,
                crawl_enqueuer=official_site_crawl.enqueuer,
                settings=settings,
            )
            # 2026-09-12: the old recon is its own switch (ledger A4); provisioning no longer
            # implies it.
            if settings.legacy_stage0_recon_enabled
            else None
        )
        onboarding_handler = _build_onboarding_handler(
            settings,
            secrets,
            storage=storage,
            synthesis=(
                _SynthesisSeam(synthesis_launcher) if synthesis_launcher is not None else None
            ),
        )
        # R2: the same model provider the other governed agents use, built here only when the lane
        # is on and this process has the credential — ``build_agent_model_provider`` raises without
        # one, and a fleet worker must not fail its boot over an optional lane.
        arv2_account_models = (
            build_agent_model_provider(config=gateway_config, secrets=secrets)
            if settings.arv2_account_research_enabled and secrets.openrouter_api_key is not None
            else None
        )
        arv2_account_research_handler = _build_arv2_account_research_handler(
            settings,
            secrets,
            storage=storage,
            model_provider=arv2_account_models,
            queue=work_queue,
        )
        # R4: the discovery drain. No model provider — a discovery run is Websets plus Exa Answer
        # and a pile of arithmetic, not an agent loop.
        arv2_discovery_handler = _build_arv2_discovery_handler(settings, secrets, storage=storage)
        # Spec 2026-09-12: the page writer. No model provider object — the runner reads the key
        # itself, the way the web seam's production factory does. The artifact sink is injected
        # from outside the lane, like the discovery lane's (Global Constraint 7).
        arv2_display_page_handler = build_arv2_display_page_handler(
            settings,
            secrets,
            artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction),
        )
        # Spec 2026-10-15 §6: a person's add or merge in Brand context, written in the background.
        product_page_handler = build_product_page_handler(
            settings,
            secrets,
            storage=storage,
            artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction),
        )
        # CRM integration Phase 2: approved CRM changes are sent in the background, one task per
        # connection.
        crm_write_handler = build_crm_write_handler(
            settings=settings,
            secrets=secrets,
            conn_factory=transaction,
            artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=transaction),
        )
        worker = build_multi_work_worker(
            settings,
            driver=driver,
            graph_handler=RecipeExecutionHandler(executor),
            entity_research_handler=(
                entity_research.handler if entity_research is not None else None
            ),
            agent_turn_handler=agent_turn_handler,
            stage0_recon_handler=stage0_recon_handler,
            official_site_crawl_handler=official_site_crawl.handler,
            onboarding_handler=onboarding_handler,
            arv2_account_research_handler=arv2_account_research_handler,
            arv2_discovery_handler=arv2_discovery_handler,
            arv2_display_page_handler=arv2_display_page_handler,
            product_page_handler=product_page_handler,
            crm_write_handler=crm_write_handler,
            # Part II D5 Round B: design agent turns drain on THIS worker when the switch is on.
            design_handler=build_design_job_handler(
                enabled=settings.design_runtime_enabled,
                preference_resolver_factory=design_preference_resolver_factory,
                # The same reads the inline leg lane above composes: a queued design job and an
                # inline leg turn are one unit of work and must see one platform.
                platform_reads_factory=design_platform_reads_factory,
            ),
            queue=work_queue,
        )
        sweep = _start_orphan_sweep(settings, storage)
        chat_sweep = _start_chat_sweep(settings)
        # Part II D8: the spent-``stream_token`` reclaim. Default ON — a used or expired token is
        # already unreadable by every code path, so its deletion is unobservable.
        token_sweep = _start_stream_token_sweep(settings)
        # Part II D5 Round C: the stranded-design-work reaper, beside the orphan-blob sweep it
        # copies. Only a design-draining deployment runs it (same switch as the handler above).
        design_reaper = start_design_reaper(
            enabled=settings.design_runtime_enabled,
            interval_s=settings.design_reaper_interval_s,
        )
        # Part II D8: the design run-event pruner. Its OWN switch, default 0 = disabled — this is
        # the one sweep that destroys durable run-visibility history, so a deployment gets it only
        # by asking. Its floors (never a terminal row, never a project subject, never a run that is
        # not long-finished) live in ``lumen_api.event_pruner``, not in the knob.
        design_event_pruner = start_design_event_pruner(
            interval_s=settings.design_run_event_prune_interval_s,
            retention_s=settings.design_run_event_retention_s,
        )
        workspace_area = (
            agent_workspace_factory.area if agent_workspace_factory is not None else None
        )
        _clean_up_at_start(settings, workspace_area)
        workspace_cache_sweep = _start_workspace_cache_sweep(settings, workspace_area)
        # F3 Phase 2 (WS-26, AW-24): the daily expiry of cold chats' raw inputs and
        # working files. Its own loop, its own fleet clock in ``maintenance_run``.
        workspace_retention = _start_workspace_retention(settings, storage)
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
        quality_reconcile = (
            asyncio.create_task(_quality_reconcile_loop(arv2_account_research_handler, settings))
            if arv2_account_research_handler is not None
            else None
        )
        try:
            await run_worker(worker)
        finally:
            for background in (
                sweep,
                chat_sweep,
                token_sweep,
                design_reaper,
                design_event_pruner,
                workspace_cache_sweep,
                workspace_retention,
                exa_discovery,
                exa_targeted_enrichment,
                external_research_wake,
                quality_reconcile,
            ):
                if background is None:
                    continue
                background.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await background
            if agent_workspace_factory is not None:
                agent_workspace_factory.close()
            from clue_storage import close_shared_s3_clients

            await close_shared_s3_clients()


def main() -> None:
    """Configure logging and run the worker event loop (the ``python -m`` entrypoint)."""
    setup()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
