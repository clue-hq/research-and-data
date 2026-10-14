"""Api-composition-root wiring for the PB-B1 fleet worker (treaty §3.4 — integration-owned).

The fleet lane (`platform/fleet/clue_fleet`) never wires ``clue_api`` (the worktrees import nothing
of the composition root); the integrator does it here, post-merge. This module holds the *reusable*
builders the worker ``__main__`` (:mod:`clue_api.fleet_main`) and any resume/toolbelt surface call —
pure composition, no logic:

* :func:`register_boot_handlers` — the worker-boot phase-handler composition: register every handler
  composable **process-wide from settings** (today: ``ProjectPhase.REVIEW``) into the registry the
  worker drives, so a detached worker is not born with an empty registry that FAILs every task. The
  per-``(client, icp)`` handlers (DEEP/VERIFICATION) are registered per run, not at boot (skipped +
  documented on the function).
* :func:`build_account_lock_factory` / :func:`lazy_account_lock_factory` (re-exported from
  :mod:`clue_api.locks`) — the Doc C §4 per-entity single-flight seam. The **lazy** form is the
  default ``lock_factory`` for the deep composition (single-flight on by default without an active
  ``redis_lifespan`` at construction); both feed the fleet
  :class:`~clue_fleet.QueueBackedScheduler`, which makes the factory a **required** arg so a
  forgotten one is a construction-time ``TypeError``, not a silent double-spend.
* :func:`tier_priority_from_rubric` — a :data:`~clue_fleet.TierPriority` that ranks the *real* tier
  labels the run's rubric names (``tier_cutoffs.bands`` order, most-selective first). The stock
  :func:`~clue_fleet.default_tier_priority` ranks names like ``platinum``/``gold``/``silver`` all at
  the unknown-tier floor (100), so it must NOT be the bound policy for a real rubric (spec §5).
* :func:`build_fleet_deep_scheduler` — the queue-backed deep drain (fleet mode) built from settings
  + the lock factory, a drop-in :data:`~clue_api.deep.handler.DeepAccountScheduler` the deep
  composition accepts via its ``scheduler`` param.
* :func:`build_fleet_run_driver` — the durable-backed :class:`~clue_research.durable.ProjectRun`
  the worker drives (the ``RunDriver`` seam), over the real M7 store + ledger + budget engine.
* :func:`build_fleet_worker` — the :class:`~clue_fleet.ProjectRunWorker` with every ``CLUE_FLEET_*``
  policy knob threaded from :class:`~clue_config.Settings` (policy as data, no magic numbers).
* :func:`enqueue_run_drive` — the resume-surface helper (per spec §2.4: re-driving a paused run
  after ``submit_checkpoint``/``resume`` is a *fresh* ``enqueue_drive``). The B4 toolbelt calls
  this; there is no HTTP resume surface at the api root yet (the in-process
  :class:`~clue_api.review.ProjectRunResumeHook` drives via ``run_to_completion``, the opt-out).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import text

from clue_api.locks import build_account_lock_factory, lazy_account_lock_factory
from clue_api.project_execution_router import ProjectExecutionRouter
from clue_config import Settings
from clue_core import ExecutionId, ProjectPhase, ProjectRunId
from clue_db import ConnFactory, transaction
from clue_execution import enqueue_recipe_execution
from clue_fleet import (
    AccountAdmission,
    CapabilityGated,
    DbLeaseStore,
    DbTaskQueue,
    DbWorkLeaseStore,
    DbWorkQueue,
    FleetTaskKind,
    LeasedWorkWorker,
    LeaseStore,
    ProjectRunWorker,
    ProjectRunWorkHandler,
    QueueBackedScheduler,
    RunDriver,
    TaskCapability,
    TaskQueue,
    TierPriority,
    WorkContext,
    WorkHandler,
    WorkLeaseStore,
    WorkQueue,
    WorkResult,
    default_tier_priority,
    enqueue_drive,
)
from clue_obs import get_logger
from clue_research.durable import (
    BudgetEngine,
    DbIdempotencyStore,
    DbProjectRunStore,
    IdempotencyStore,
    LockFactory,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunStore,
    default_phase_handler_registry,
)
from clue_research.icp.rubric import TierCutoffs
from clue_storage import StorageBackend

__all__ = [
    "build_account_lock_factory",
    "lazy_account_lock_factory",
    "register_boot_handlers",
    "tier_priority_from_rubric",
    "build_fleet_deep_scheduler",
    "build_fleet_run_driver",
    "build_fleet_worker",
    "build_multi_work_worker",
    "enqueue_run_drive",
]

log = get_logger("clue_api.fleet_wiring")


class _OwnedRunGuardHandler:
    """Refuse the legacy driver whenever Recipe #1 owns the run."""

    kind = FleetTaskKind.DRIVE_RUN

    def __init__(
        self,
        inner: WorkHandler,
        *,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._inner = inner
        self._conn_factory = conn_factory

    async def handle(self, context: WorkContext) -> WorkResult:
        async with self._conn_factory() as conn:
            owner = (
                await conn.execute(
                    text(
                        """
                        SELECT execution_id FROM project_run_execution_owner
                        WHERE project_run_id = :run_id
                        """
                    ),
                    {"run_id": context.work_id},
                )
            ).scalar_one_or_none()
        if owner is not None:
            raise RuntimeError(
                f"project run {context.work_id} is owned by recipe execution {owner}; "
                "legacy drive is forbidden"
            )
        return await self._inner.handle(context)


def register_boot_handlers(
    settings: Settings,
    *,
    storage: StorageBackend | None,
    registry: PhaseHandlerRegistry | None = None,
    project_execution_router: ProjectExecutionRouter | None = None,
) -> frozenset[ProjectPhase]:
    """Register every phase handler the fleet worker can compose **process-wide from settings** and
    return the set of phases now bound. The worker owns *execution*, but the phase-handler registry
    it drives is populated by the composition root (``durable`` never imports a handler) — so a
    detached worker that composed no handlers would raise ``NoPhaseHandlerRegistered`` and park
    every ``drive_run`` task FAILED. This is the boot composition that prevents that.

    **What composes at boot (process-wide, no per-run inputs):**

    * ``ProjectPhase.REVIEW`` — via ``review_feedback_wiring.build_reviewed_phase_handler`` (the
      M13.1 ↔ M13.2 production surface: the human-review gate whose actions mirror into
      dispositions). Its account set is the durable M12-ready readiness reader (no ICP spec) and its
      collaborators all default from process-wide state, so it is fully composable here.

    **What is deliberately NOT registrable at boot (skipped, documented):**

    * ``ProjectPhase.DEEP`` — the handler is **campaign-scoped**: it holds one ``ICPSpec`` and its
      committee ``sources``, both per-``(client, icp)``. It is registered per run at run start (the
      in-process path already does; the fleet path is the B4 delegation contract), never at boot.
    * ``ProjectPhase.VERIFICATION`` — ``register_verification_phase_handler`` needs both a
      ``gateway`` (buildable from ``GatewayConfig``/settings) **and** a required resolver whose
      production form (``build_high_tier_resolver``) is keyed on the per-``(client, icp)``
      high-tier set (the same reason DEEP is per-campaign). So it is per-run, not boot — skipped.
    * ``ProjectPhase.HANDOFF`` — the real M12 narrative handler and its retention-sweep wrapper are
      now composed per run by :class:`~clue_api.run_composition.ComposingRunDriver` (C7.6). They
      require the exact run/product-bound governed committee reader and per-run account resolver,
      so they remain intentionally unavailable to this process-wide boot registry — skipped here.

    The M5/M6 phases (``REVERSE_PROFILING`` … ``TIER_CHECKPOINT``) have no ``clue_api`` registration
    surface yet, so there is nothing to compose for them here. Consequently a run whose *current*
    phase has no boot- or run-registered handler fails its drive task with ``outcome=error`` (see
    :mod:`clue_api.fleet_main`); the per-``(client, icp, product)`` DEEP/VERIFICATION/HANDOFF
    composition lives in :mod:`clue_api.run_composition`.

    ``registry`` defaults to the process-default registry the state machine drives (a fresh registry
    is injectable for tests). ``storage`` is the B2 backend the storage-consuming registrations
    (retention-sweep HANDOFF, DEEP snapshot binding) will take once they become boot-registrable —
    none are today, so it is recorded for observability and otherwise reserved.
    """
    # Function-level import avoids any api-package import cycle (fleet_wiring ← clue_api.__init__ →
    # review_feedback_wiring …): the M13 wiring chain is only needed when we actually compose.
    from clue_api.review_feedback_wiring import build_reviewed_phase_handler

    target = registry if registry is not None else default_phase_handler_registry()
    # Construction is DB-free (every collaborator only stores its conn/session factory); the handler
    # touches the DB only when the state machine drives REVIEW.
    target.register(build_reviewed_phase_handler(project_execution_router=project_execution_router))

    phases = target.phases()
    log.info(
        "fleet.boot.handlers_registered",
        phases=sorted(phase.value for phase in phases),
        storage_wired=storage is not None,
    )
    return phases


def tier_priority_from_rubric(
    cutoffs: TierCutoffs, *, fallback: TierPriority = default_tier_priority
) -> TierPriority:
    """A :data:`~clue_fleet.TierPriority` that ranks the run's **real** tier labels: the
    ``tier_cutoffs.bands`` are declared most-selective-first, so band *i* gets priority *i*
    (smaller = sooner), the ``fallback_tier`` (accounts that cleared no band) sorts after the last
    band, and any label the rubric does not name falls through to the stock name/number ladder
    (:func:`~clue_fleet.default_tier_priority`) — but ranked **strictly after** the fallback tier,
    so an unknown label can never leapfrog a real band or the fallback
    (``default_tier_priority("top")`` is ``0`` — it would otherwise tie the most-selective band).

    This exists because ``default_tier_priority`` alone cannot rank a rubric's free-form band names
    (``platinum``/``gold``/``silver`` all hit the unknown floor, 100 — order lost); the band order
    in the run's committed cutoffs is the authority (spec §5). Bind it at run start from the ICP's
    ``rubric.tier_cutoffs`` and pass it as the scheduler's ``priority_for``. Labels are matched
    case-insensitively / trimmed, consistent with :func:`~clue_fleet.default_tier_priority`."""
    band_rank = {band.tier.strip().lower(): index for index, band in enumerate(cutoffs.bands)}
    fallback_rank = len(cutoffs.bands)
    fallback_label = cutoffs.fallback_tier.strip().lower()

    def _priority(tier: str) -> int:
        key = tier.strip().lower()
        if key in band_rank:
            return band_rank[key]
        if key == fallback_label:
            return fallback_rank
        # Genuinely-unknown label: rank it after the fallback tier (``fallback_rank + 1`` floor)
        # plus the ladder's own rank — so the name/number ladder is a *last resort* that never ties
        # or beats a named band / the fallback (``default_tier_priority("top") == 0`` otherwise).
        return fallback_rank + 1 + fallback(tier)

    return _priority


def build_fleet_deep_scheduler(
    settings: Settings,
    *,
    lock_factory: LockFactory,
    priority_for: TierPriority,
    queue: TaskQueue | None = None,
    account_admission: AccountAdmission | None = None,
) -> QueueBackedScheduler:
    """The PB-B1 queue-backed deep drain (fleet mode) — the durable tier-priority
    :data:`~clue_api.deep.handler.DeepAccountScheduler` the deep composition swaps in via its
    ``scheduler`` param. ``window`` and ``stale_after`` come from ``CLUE_FLEET_*`` settings;
    ``lock_factory`` is **required** (the fleet scheduler makes single-flight non-optional).
    ``priority_for`` is **required too** — bind it from :func:`tier_priority_from_rubric` at run
    start so account jobs drain best-tier-first over the rubric's real labels. The stock
    :func:`~clue_fleet.default_tier_priority` must not be the bound policy for a real rubric (it
    collapses free-form band names to the unknown floor — spec §5), so it is *not* defaulted."""
    resolved_queue = queue if queue is not None else DbTaskQueue()
    stale_after = timedelta(seconds=settings.fleet_task_stale_after_s)
    if account_admission is None:
        return QueueBackedScheduler(
            queue=resolved_queue,
            window=settings.fleet_deep_window,
            lock_factory=lock_factory,
            priority_for=priority_for,
            stale_after=stale_after,
        )
    return QueueBackedScheduler(
        queue=resolved_queue,
        window=settings.fleet_deep_window,
        lock_factory=lock_factory,
        priority_for=priority_for,
        stale_after=stale_after,
        account_admission=account_admission,
    )


def build_fleet_run_driver(
    *,
    registry: PhaseHandlerRegistry | None = None,
    store: ProjectRunStore | None = None,
    ledger: IdempotencyStore | None = None,
    budget_engine: BudgetEngine | None = None,
    enforce_budget: bool = True,
) -> RunDriver:
    """The durable-backed ``RunDriver`` the worker drives: a
    :class:`~clue_research.durable.ProjectRun` over the real M7 persistence
    (:class:`DbProjectRunStore`), the M7.4 exactly-once ledger (:class:`DbIdempotencyStore`), a
    :class:`BudgetEngine`, and the process phase-handler registry.

    ``registry`` defaults to the process-default registry the ``register_*_phase_handler`` binders
    populate. The DEEP handler is **campaign-scoped** (one ICPSpec) and is registered per
    ``(client, icp)`` at run start — over the fleet :func:`build_fleet_deep_scheduler` for the
    worker deployment (``build_deep_phase_handler(scheduler=…)``) — exactly as the in-process path
    already registers it at run start; the worker never composes handlers (spec §2.4, worker.py).

    ``enforce_budget`` is the FI pilot budget-controls switch — pass
    ``Settings.budget_controls_enabled``. False disables only the M7.5 pre-phase graceful-stop gate;
    the engine stays wired so burn-down/estimate reads and every recorded charge are unchanged."""
    return ProjectRun(
        store=store if store is not None else DbProjectRunStore(),
        registry=registry if registry is not None else default_phase_handler_registry(),
        budget_engine=budget_engine if budget_engine is not None else BudgetEngine(),
        ledger=ledger if ledger is not None else DbIdempotencyStore(),
        enforce_budget=enforce_budget,
    )


def build_fleet_worker(
    settings: Settings,
    *,
    driver: RunDriver,
    queue: TaskQueue | None = None,
    leases: LeaseStore | None = None,
    worker_id: str | None = None,
) -> ProjectRunWorker:
    """The detached :class:`~clue_fleet.ProjectRunWorker` with every policy knob threaded from
    ``CLUE_FLEET_*`` settings (poll interval, lease TTL, heartbeat, stale window — policy as
    data). ``queue``/``leases`` default to the Postgres repos. The construction-time
    ``2·heartbeat_interval < lease_ttl`` invariant holds for the shipped defaults (10s / 30s)."""
    return ProjectRunWorker(
        driver=driver,
        queue=queue if queue is not None else DbTaskQueue(),
        leases=leases if leases is not None else DbLeaseStore(),
        worker_id=worker_id,
        poll_interval=settings.fleet_poll_interval_s,
        lease_ttl=timedelta(seconds=settings.fleet_lease_ttl_s),
        heartbeat_interval=settings.fleet_heartbeat_interval_s,
        task_stale_after=timedelta(seconds=settings.fleet_task_stale_after_s),
    )


class _SerializedHandler:
    """Run one wrapped ``handle`` at a time, whatever the worker's concurrency.

    ``CLUE_FLEET_WORKER_CONCURRENCY`` > 1 makes several ``handle()`` calls share one handler
    *instance*. A handler that keeps per-instance mutable state across awaits is correct only
    when its calls do not interleave, so this wrapper gives it back the one-at-a-time guarantee
    it was written under — a lock, not a rewrite, because the alternative is editing another
    lane's driver to satisfy a fleet knob.

    Only the wrapped kind is serialised: every other kind on the process keeps draining in
    parallel, so the cost is the throughput of one kind, not of the worker.
    """

    def __init__(self, inner: WorkHandler) -> None:
        self._inner = inner
        self._lock = asyncio.Lock()

    @property
    def kind(self) -> FleetTaskKind:
        return self._inner.kind

    @property
    def task_capabilities(self) -> tuple[TaskCapability, ...]:
        """Forward the R3-B declaration; an ungated inner handler still claims its whole kind.

        Read per call, like :class:`~clue_fleet.CapabilityGated` requires — the wrapper must not
        freeze a capability that depends on live configuration.
        """
        inner = self._inner
        if not isinstance(inner, CapabilityGated):
            return ()
        return tuple(inner.task_capabilities)

    async def handle(self, context: WorkContext) -> WorkResult:
        async with self._lock:
            return await self._inner.handle(context)


def selected_worker_kinds(raw: str) -> frozenset[FleetTaskKind] | None:
    """Parse ``CLUE_FLEET_WORKER_KINDS``: ``None`` (blank) means every kind.

    An unknown name fails loudly — a typo must not start a worker that silently claims nothing.
    """
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        return None
    valid = {kind.value: kind for kind in FleetTaskKind}
    unknown = [name for name in names if name not in valid]
    if unknown:
        raise ValueError(
            f"CLUE_FLEET_WORKER_KINDS names unknown task kinds {unknown}; "
            f"valid kinds are {sorted(valid)}"
        )
    return frozenset(valid[name] for name in names)


def build_multi_work_worker(
    settings: Settings,
    *,
    driver: RunDriver,
    graph_handler: WorkHandler,
    entity_research_handler: WorkHandler | None = None,
    agent_turn_handler: WorkHandler | None = None,
    stage0_recon_handler: WorkHandler | None = None,
    official_site_crawl_handler: WorkHandler | None = None,
    design_handler: WorkHandler | None = None,
    onboarding_handler: WorkHandler | None = None,
    arv2_account_research_handler: WorkHandler | None = None,
    arv2_discovery_handler: WorkHandler | None = None,
    arv2_display_page_handler: WorkHandler | None = None,
    product_page_handler: WorkHandler | None = None,
    queue: WorkQueue | None = None,
    leases: WorkLeaseStore | None = None,
    worker_id: str | None = None,
) -> LeasedWorkWorker:
    """One leased drain for project runs, recipe graphs, design jobs, and optional governed
    work kinds.

    R2 adds only the composition seam.  Production deliberately omits the optional handler until
    R3 supplies the governed ``create_agent()`` driver, preserving R1's fail-loud quarantine.

    ``agent_turn_handler`` (Lane D D2) is optional for the same reason: a deployment with chat
    disabled composes no conversation engine and nothing enqueues ``agent_turn`` tasks, so the
    worker simply never offers that kind. Each kind gets its own keyword and its own guard rather
    than a registry, so a handler wired to the wrong queue is a composition-time error.

    ``design_handler`` (Part II D5 Round B) joins on exactly the same terms: optional, kind-checked
    here so a wiring mistake fails at construction rather than at claim time, and off unless
    ``design_runtime_enabled`` is set.  ONE fleet worker drains every kind — design work does not
    get a private drain (the round-robin in :class:`~clue_fleet.LeasedWorkWorker` already keeps
    one kind from starving another).

    ``onboarding_handler`` (Track O, O3) is the same shape again: optional because a deployment
    without ``onboarding_v2_enabled`` composes no onboarding driver and nothing enqueues the kind.

    ``arv2_account_research_handler`` (Track R, R2) is the same shape again: optional because a
    deployment without ``arv2_account_research_enabled`` composes no account driver.

    ``arv2_discovery_handler`` (Track R, R4) joins on exactly those terms: optional because a
    deployment without ``arv2_discovery_enabled`` (or without ``CLUE_EXA_API_KEY``) composes no
    discovery driver, and kind-guarded here so a handler wired to the wrong keyword fails at
    construction rather than after a run has already claimed its row.

    ``arv2_display_page_handler`` (spec 2026-09-12) is the same shape again: optional because a
    deployment with the display flag off or no model key composes none, and kind-guarded here.

    ``CLUE_FLEET_WORKER_CONCURRENCY`` (founder ruling 2026-09-10) is threaded here like every
    other ``CLUE_FLEET_*`` knob: it is how many tasks THIS process drives at once. Several worker
    processes still run against the same queue; the knob multiplies each of them. A handler whose
    ``handle`` is not safe under concurrent calls on ONE instance is wrapped in
    :class:`_SerializedHandler` at the point it joins the worker, so raising the knob can never
    make a handler less correct — only the work that handler gates less parallel.

    ``CLUE_FLEET_WORKER_KINDS`` (first deployment) narrows the registered handlers to the named
    kinds; blank keeps every kind.
    """
    if (
        entity_research_handler is not None
        and entity_research_handler.kind is not FleetTaskKind.ENTITY_RESEARCH_JOB
    ):
        raise ValueError("entity_research_handler must own entity_research_job tasks")
    if agent_turn_handler is not None and agent_turn_handler.kind is not FleetTaskKind.AGENT_TURN:
        raise ValueError("agent_turn_handler must own agent_turn tasks")
    if (
        stage0_recon_handler is not None
        and stage0_recon_handler.kind is not FleetTaskKind.STAGE0_RECON
    ):
        raise ValueError("stage0_recon_handler must own stage0_recon tasks")
    if (
        official_site_crawl_handler is not None
        and official_site_crawl_handler.kind is not FleetTaskKind.OFFICIAL_SITE_CRAWL
    ):
        raise ValueError("official_site_crawl_handler must own official_site_crawl tasks")
    if design_handler is not None and design_handler.kind is not FleetTaskKind.DESIGN_JOB:
        raise ValueError("design_handler must own design_job tasks")
    if (
        onboarding_handler is not None
        and onboarding_handler.kind is not FleetTaskKind.ONBOARDING_RUN
    ):
        raise ValueError("onboarding_handler must own onboarding_run tasks")
    if (
        arv2_account_research_handler is not None
        and arv2_account_research_handler.kind is not FleetTaskKind.ARV2_ACCOUNT_RESEARCH
    ):
        raise ValueError("arv2_account_research_handler must own arv2_account_research tasks")
    if (
        arv2_discovery_handler is not None
        and arv2_discovery_handler.kind is not FleetTaskKind.ARV2_DISCOVERY
    ):
        raise ValueError("arv2_discovery_handler must own arv2_discovery tasks")
    if (
        arv2_display_page_handler is not None
        and arv2_display_page_handler.kind is not FleetTaskKind.ARV2_DISPLAY_PAGE
    ):
        raise ValueError("arv2_display_page_handler must own arv2_display_page tasks")
    if (
        product_page_handler is not None
        and product_page_handler.kind is not FleetTaskKind.PRODUCT_PAGE_WRITE
    ):
        raise ValueError("product_page_handler must own product_page_write tasks")
    handlers: list[WorkHandler] = [
        # The one kind the 9d handler-safety audit found NOT safe to run concurrently on one
        # instance. Two independent reasons, both in code today:
        #   * the production driver (``ComposingRunDriver``) keeps an LRU per-run registry cache
        #     with no lock and an ``await`` between the cache miss and the fill, and evicts by
        #     size — so concurrent drives both compose, and past the cache size they evict each
        #     other's mid-drive registry;
        #   * ``clue_research.durable.ProjectRun`` states single-driver-per-run as a
        #     *precondition* ("what lets phase idempotency use a zero ``stale_after``") and says
        #     the enforcing lock is left to the scheduler — and the fleet cannot supply it here,
        #     because every slot claims under the SAME ``worker_id`` and ``work_lease``'s acquire
        #     hands its own worker a live lease at the SAME generation, so the lease fence that
        #     separates two worker *processes* does not separate two slots of one process.
        # A lock, not a rewrite: both fixes belong to their own lanes. Only ``drive_run`` pays.
        _SerializedHandler(_OwnedRunGuardHandler(ProjectRunWorkHandler(driver))),
        graph_handler,
    ]
    if entity_research_handler is not None:
        handlers.append(entity_research_handler)
    if agent_turn_handler is not None:
        handlers.append(agent_turn_handler)
    if stage0_recon_handler is not None:
        handlers.append(stage0_recon_handler)
    if official_site_crawl_handler is not None:
        handlers.append(official_site_crawl_handler)
    if design_handler is not None:
        handlers.append(design_handler)
    if onboarding_handler is not None:
        handlers.append(onboarding_handler)
    if arv2_account_research_handler is not None:
        handlers.append(arv2_account_research_handler)
    if arv2_discovery_handler is not None:
        handlers.append(arv2_discovery_handler)
    if arv2_display_page_handler is not None:
        handlers.append(arv2_display_page_handler)
    if product_page_handler is not None:
        handlers.append(product_page_handler)
    selected = selected_worker_kinds(settings.fleet_worker_kinds)
    if selected is not None:
        handlers = [handler for handler in handlers if handler.kind in selected]
        if not handlers:
            raise ValueError(
                f"CLUE_FLEET_WORKER_KINDS={settings.fleet_worker_kinds!r} leaves this worker with "
                "no handler: none of the selected kinds is composed in this deployment"
            )
    return LeasedWorkWorker(
        handlers=tuple(handlers),
        queue=queue if queue is not None else DbWorkQueue(),
        leases=leases if leases is not None else DbWorkLeaseStore(),
        worker_id=worker_id,
        poll_interval=settings.fleet_poll_interval_s,
        lease_ttl=timedelta(seconds=settings.fleet_lease_ttl_s),
        heartbeat_interval=settings.fleet_heartbeat_interval_s,
        task_stale_after=timedelta(seconds=settings.fleet_task_stale_after_s),
        concurrency=settings.fleet_worker_concurrency,
    )


async def enqueue_run_drive(
    project_run_id: ProjectRunId,
    *,
    queue: TaskQueue | None = None,
    work_queue: WorkQueue | None = None,
    conn_factory: ConnFactory = transaction,
    priority: int = 0,
) -> bool:
    """Offer a run to the fleet — the resume-surface helper (spec §2.4). Re-driving a paused run
    after ``submit_checkpoint``/``resume`` is a *fresh* :func:`~clue_fleet.enqueue_drive`, which
    re-opens the finished ``drive_run`` task (``reopen_terminal``). The B4 toolbelt calls this after
    a resume; ``queue`` defaults to the Postgres :class:`DbTaskQueue`."""
    task_queue = queue if queue is not None else DbTaskQueue()
    # Preserve the original pure queue-adapter surface for focused fake-queue tests. Production
    # uses DbTaskQueue; integration tests that need routing inject their connection factory.
    should_route = (
        queue is None
        or isinstance(task_queue, DbTaskQueue)
        or conn_factory is not transaction
        or work_queue is not None
    )
    if not should_route:
        return await enqueue_drive(task_queue, project_run_id, priority=priority)
    async with conn_factory() as conn:
        owner = (
            await conn.execute(
                text(
                    """
                    SELECT execution_id FROM project_run_execution_owner
                    WHERE project_run_id = :run_id
                    """
                ),
                {"run_id": project_run_id},
            )
        ).scalar_one_or_none()
    if owner is not None:
        return await enqueue_recipe_execution(
            work_queue if work_queue is not None else DbWorkQueue(task_queue),
            ExecutionId(owner),
            priority=priority,
        )
    return await enqueue_drive(task_queue, project_run_id, priority=priority)
