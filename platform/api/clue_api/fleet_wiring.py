"""Api-composition-root wiring for the PB-B1 fleet worker (treaty §3.4 — integration-owned).

The fleet lane (`platform/fleet/clue_fleet`) never wires ``clue_api`` (the worktrees import nothing
of the composition root); the integrator does it here, post-merge. This module holds the *reusable*
builders the worker ``__main__`` (:mod:`clue_api.fleet_main`) and any resume/toolbelt surface call —
pure composition, no logic:

* :func:`build_account_lock_factory` — the Doc C §4 per-entity single-flight seam
  (``account_entity_lock_factory(get_redis())``), wired into **both** deep schedulers so two runs
  never deep-research one ``entity_id`` at once (the integrator checklist restores this — the
  baseline :class:`AccountScheduler` construction silently omitted it, and the fleet
  :class:`~clue_fleet.QueueBackedScheduler` makes it a **required** arg so a forgotten factory is a
  construction-time ``TypeError``, not a silent double-spend).
* :func:`tier_priority_from_rubric` — a :data:`~clue_fleet.TierPriority` that ranks the *real* tier
  labels the run's rubric names (``tier_cutoffs.bands`` order, most-selective first). The stock
  :func:`~clue_fleet.default_tier_priority` ranks names like ``platinum``/``gold``/``silver`` all at
  the unknown-tier floor (100), so it must NOT be the bound policy for a real rubric (spec §5).
* :func:`build_fleet_deep_scheduler` — the queue-backed deep drain (fleet mode) built from settings
  + the lock factory, a drop-in :data:`~clue_api.deep.handler.DeepAccountScheduler` the deep
  composition accepts via its ``scheduler`` param.
* :func:`build_fleet_run_driver` — the durable-backed :class:`~clue_research.durable.CampaignRun`
  the worker drives (the ``RunDriver`` seam), over the real M7 store + ledger + budget engine.
* :func:`build_fleet_worker` — the :class:`~clue_fleet.ProjectRunWorker` with every ``CLUE_FLEET_*``
  policy knob threaded from :class:`~clue_config.Settings` (policy as data, no magic numbers).
* :func:`enqueue_run_drive` — the resume-surface helper (per spec §2.4: re-driving a paused run
  after ``submit_checkpoint``/``resume`` is a *fresh* ``enqueue_drive``). The B4 toolbelt calls
  this; there is no HTTP resume surface at the api root yet (the in-process
  :class:`~clue_api.review.CampaignRunResumeHook` drives via ``run_to_completion``, the opt-out).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from clue_fleet import (
    DbLeaseStore,
    DbTaskQueue,
    LeaseStore,
    ProjectRunWorker,
    QueueBackedScheduler,
    RunDriver,
    TaskQueue,
    TierPriority,
    default_tier_priority,
    enqueue_drive,
)

from clue_config import Settings
from clue_core import CampaignRunId
from clue_locks import get_redis
from clue_research.durable import (
    BudgetEngine,
    CampaignRun,
    CampaignRunStore,
    DbCampaignRunStore,
    DbIdempotencyStore,
    IdempotencyStore,
    LockFactory,
    PhaseHandlerRegistry,
    account_entity_lock_factory,
    default_phase_handler_registry,
)
from clue_research.icp.rubric import TierCutoffs

__all__ = [
    "build_account_lock_factory",
    "tier_priority_from_rubric",
    "build_fleet_deep_scheduler",
    "build_fleet_run_driver",
    "build_fleet_worker",
    "enqueue_run_drive",
]


def build_account_lock_factory(redis: Any | None = None) -> LockFactory:
    """The production :data:`~clue_research.durable.LockFactory` — a Redis in-flight account lock
    per entity (M2.4). Defaults to the process-wide client (:func:`~clue_locks.get_redis`, requires
    an active ``redis_lifespan``); pass ``redis`` in a test. Wire the result into **both** the
    baseline :class:`AccountScheduler` (``build_deep_phase_handler(lock_factory=…)``) and the fleet
    :class:`~clue_fleet.QueueBackedScheduler` (:func:`build_fleet_deep_scheduler`) so single-flight
    is on wherever the deep phase runs (integrator checklist)."""
    return account_entity_lock_factory(redis if redis is not None else get_redis())


def tier_priority_from_rubric(
    cutoffs: TierCutoffs, *, fallback: TierPriority = default_tier_priority
) -> TierPriority:
    """A :data:`~clue_fleet.TierPriority` that ranks the run's **real** tier labels: the
    ``tier_cutoffs.bands`` are declared most-selective-first, so band *i* gets priority *i*
    (smaller = sooner), the ``fallback_tier`` (accounts that cleared no band) sorts after the last
    band, and any label the rubric does not name falls through to ``fallback`` — the stock
    name/number ladder (:func:`~clue_fleet.default_tier_priority`) as a last resort.

    This exists because ``default_tier_priority`` alone cannot rank a rubric's free-form band names
    (``platinum``/``gold``/``silver`` all hit the unknown floor, 100 — order lost); the band order
    in the run's committed cutoffs is the authority (spec §5). Bind it at run start from the ICP's
    ``rubric.tier_cutoffs`` and pass it as the scheduler's ``priority_for``."""
    band_rank = {band.tier: index for index, band in enumerate(cutoffs.bands)}
    fallback_rank = len(cutoffs.bands)

    def _priority(tier: str) -> int:
        if tier in band_rank:
            return band_rank[tier]
        if tier == cutoffs.fallback_tier:
            return fallback_rank
        return fallback(tier)

    return _priority


def build_fleet_deep_scheduler(
    settings: Settings,
    *,
    lock_factory: LockFactory,
    priority_for: TierPriority = default_tier_priority,
    queue: TaskQueue | None = None,
) -> QueueBackedScheduler:
    """The PB-B1 queue-backed deep drain (fleet mode) — the durable tier-priority
    :data:`~clue_api.deep.handler.DeepAccountScheduler` the deep composition swaps in via its
    ``scheduler`` param. ``window`` and ``stale_after`` come from ``CLUE_FLEET_*`` settings;
    ``lock_factory`` is **required** (the fleet scheduler makes single-flight non-optional). Bind
    ``priority_for`` from :func:`tier_priority_from_rubric` at run start so account jobs drain
    best-tier-first over the rubric's real labels."""
    return QueueBackedScheduler(
        queue=queue if queue is not None else DbTaskQueue(),
        window=settings.fleet_deep_window,
        lock_factory=lock_factory,
        priority_for=priority_for,
        stale_after=timedelta(seconds=settings.fleet_task_stale_after_s),
    )


def build_fleet_run_driver(
    *,
    registry: PhaseHandlerRegistry | None = None,
    store: CampaignRunStore | None = None,
    ledger: IdempotencyStore | None = None,
    budget_engine: BudgetEngine | None = None,
) -> RunDriver:
    """The durable-backed ``RunDriver`` the worker drives: a
    :class:`~clue_research.durable.CampaignRun` over the real M7 persistence
    (:class:`DbCampaignRunStore`), the M7.4 exactly-once ledger (:class:`DbIdempotencyStore`), a
    :class:`BudgetEngine`, and the process phase-handler registry.

    ``registry`` defaults to the process-default registry the ``register_*_phase_handler`` binders
    populate. The DEEP handler is **campaign-scoped** (one ICPSpec) and is registered per
    ``(client, icp)`` at run start — over the fleet :func:`build_fleet_deep_scheduler` for the
    worker deployment (``build_deep_phase_handler(scheduler=…)``) — exactly as the in-process path
    already registers it at run start; the worker never composes handlers (spec §2.4, worker.py)."""
    return CampaignRun(
        store=store if store is not None else DbCampaignRunStore(),
        registry=registry if registry is not None else default_phase_handler_registry(),
        budget_engine=budget_engine if budget_engine is not None else BudgetEngine(),
        ledger=ledger if ledger is not None else DbIdempotencyStore(),
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


async def enqueue_run_drive(
    project_run_id: CampaignRunId, *, queue: TaskQueue | None = None, priority: int = 0
) -> bool:
    """Offer a run to the fleet — the resume-surface helper (spec §2.4). Re-driving a paused run
    after ``submit_checkpoint``/``resume`` is a *fresh* :func:`~clue_fleet.enqueue_drive`, which
    re-opens the finished ``drive_run`` task (``reopen_terminal``). The B4 toolbelt calls this after
    a resume; ``queue`` defaults to the Postgres :class:`DbTaskQueue`."""
    return await enqueue_drive(
        queue if queue is not None else DbTaskQueue(), project_run_id, priority=priority
    )
