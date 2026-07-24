"""Fleet-plane lifecycle enums — table-column taxonomies internal to ``clue_fleet`` (PB-B1).

Deliberately **package-local**, not in ``core.enums`` (the treaty §3.3 preference, mirroring the
``durable/enums.py`` precedent): these are internal lifecycle states of the fleet tables that no
other package references — research code never learns the queue exists (Rule F1).

Each enum is mirrored by a Postgres ``ENUM`` created in the PB-B1 migration; the parity test in
``tests/fleet/`` asserts the Python members and the DB labels stay in lock-step (the same
``StrEnum`` discipline as ``core.enums`` / ``durable/enums.py``).
"""

from __future__ import annotations

from enum import StrEnum


class FleetTaskKind(StrEnum):
    """What a ``fleet_task`` row asks a worker to do (PB-B1).

    * ``DRIVE_RUN`` — drive one project run forward until it can't advance (terminal, paused, or
      stalled). Claimed by any :class:`~clue_fleet.worker.ProjectRunWorker`; guarded by the
      per-run driver lease.
    * ``ACCOUNT_JOB`` — one per-account deep-research job inside a run's ``deep`` phase (the
      REQ-10 tier-priority queue unit). Drained only by the run's current driver (the lease keeps
      drivers exclusive), ordered by ``priority`` (tier rank) under the concurrency window.
    """

    DRIVE_RUN = "drive_run"
    ACCOUNT_JOB = "account_job"
    EXECUTE_GRAPH = "execute_graph"


class FleetTaskStatus(StrEnum):
    """Lifecycle of one ``fleet_task`` row (PB-B1).

    ``QUEUED`` → ``CLAIMED`` (a worker owns it; ``claimed_by``/``claimed_at`` stamped) →
    ``DONE`` | ``FAILED``. A ``CLAIMED`` row whose claim has gone stale (its holder was killed)
    is re-owned by the next claimant — the same recovery shape as the M7.4 idempotency ledger; a
    ``FAILED`` row is retried only by an explicit requeue (a fresh drive re-entering the work),
    never silently. A graceful stop hands a claimed task back to ``QUEUED``.
    """

    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"
