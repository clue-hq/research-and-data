"""``clue_fleet`` — the fleet shell: detached worker, per-run driver lease, task drain,
tier-priority queue (PB-B1 / harness build step 0).

The governance shell around the existing research pipeline (harness §6, Doc A §1.3 — "always
mechanical"): the :class:`ProjectRunWorker` process drives M7 campaign-run state machines as
``drive_run`` jobs under a per-run :mod:`~clue_fleet.lease`; the ``deep`` phase's account jobs
drain from the durable tier-priority :mod:`~clue_fleet.queue` via the
:class:`QueueBackedScheduler`. No new research behavior — the pipeline gains kill-resumability,
single-driver enforcement, and best-tier-first ordering. See ``docs/specs/PB-B1-fleet-worker.md``.
"""

from __future__ import annotations

from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import (
    DEFAULT_LEASE_TTL,
    DbLeaseStore,
    LeaseStore,
    RunLeaseRow,
    acquire_run_lease,
    get_run_lease,
    release_run_lease,
    renew_run_lease,
)
from clue_fleet.queue import (
    DEFAULT_TASK_STALE_AFTER,
    DbTaskQueue,
    FleetTaskRow,
    TaskQueue,
    claim_next_task,
    enqueue_task,
    finish_task,
    get_task,
    list_tasks,
    requeue_failed_tasks,
    requeue_task,
    touch_task,
)
from clue_fleet.runner import run_worker
from clue_fleet.scheduler import QueueBackedScheduler, TierPriority, default_tier_priority
from clue_fleet.worker import ProjectRunWorker, RunDriver, enqueue_drive

__all__ = [
    # enums
    "FleetTaskKind",
    "FleetTaskStatus",
    # driver lease
    "DEFAULT_LEASE_TTL",
    "LeaseStore",
    "DbLeaseStore",
    "RunLeaseRow",
    "acquire_run_lease",
    "renew_run_lease",
    "release_run_lease",
    "get_run_lease",
    # task queue
    "DEFAULT_TASK_STALE_AFTER",
    "TaskQueue",
    "DbTaskQueue",
    "FleetTaskRow",
    "enqueue_task",
    "claim_next_task",
    "finish_task",
    "touch_task",
    "requeue_task",
    "requeue_failed_tasks",
    "get_task",
    "list_tasks",
    # tier-priority deep drain
    "QueueBackedScheduler",
    "TierPriority",
    "default_tier_priority",
    # the worker
    "ProjectRunWorker",
    "RunDriver",
    "enqueue_drive",
    "run_worker",
]
