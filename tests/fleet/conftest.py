"""Fleet test harness (PB-B1) — in-memory fakes + the migrated-DB gate.

The worker-loop and queue-scheduler tests run on in-memory fakes of the two fleet seams
(:class:`~clue_fleet.LeaseStore`, :class:`~clue_fleet.TaskQueue`) plus a scripted
:class:`~clue_fleet.RunDriver`, so the drain/lease/drive control flow is exercised without a
database. The lease/queue semantics and enum-parity tests need the real Postgres tables and
``pytest.skip`` when no DB is reachable, reusing the M0.3 ``run_async`` + reachable-DB probe
(the ``tests/durable/conftest.py`` shape, DRY).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

# Reuse the M0.3 single-loop coroutine runner + reachable-DB gate (DRY).
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

# The single shared per-entity lock factory (fleet + durable + the exit-gate harness); re-exported
# so existing ``from tests.fleet.conftest import ProcessLocalLockFactory`` imports keep working.
from tests.lock_factory import ProcessLocalLockFactory as ProcessLocalLockFactory

from clue_core import CostCents, ProjectPhase, ProjectRunId
from clue_db import db_lifespan
from clue_fleet import FleetTaskKind, FleetTaskRow, FleetTaskStatus, RunLeaseRow
from clue_research.durable import ProjectRunRow, ProjectRunStatus

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- DB gate (mirrors tests/durable/conftest.py) ----------------------------


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> bool:
    """Migrate to head once per session when a DB is reachable; return whether it is."""
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_fleet_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable database (with the fleet tables) is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the fleet DB tests"
        )


@asynccontextmanager
async def rollback_conn() -> AsyncIterator[AsyncConnection]:
    """Yield a connection inside a transaction that is always rolled back (test isolation).

    Note: inside one transaction Postgres ``now()`` is frozen at the transaction timestamp, so
    expiry/staleness tests use zero TTLs/windows (``expires_at <= now()`` holds immediately)
    instead of sleeping."""
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
            await conn.close()


# --- in-memory fakes for the loop/scheduler tests ---------------------------


def _now() -> datetime:
    return datetime.now(UTC)


class FakeLeaseStore:
    """An in-memory :class:`~clue_fleet.LeaseStore` (no DB, no real clock).

    Holds ``run → worker`` ownership; :meth:`expire` simulates a TTL lapse; ``deny_renewal``
    makes the next renew fail (the lease-lost path). Calls are journaled for assertions."""

    def __init__(self) -> None:
        self.holders: dict[ProjectRunId, str] = {}
        self.deny_renewal = False
        # Renewal-fault injection (audit finding #2): ``renew_always_raises`` makes every renew
        # raise; ``renew_raise_budget`` raises for the next N renews then behaves normally (the
        # transient-fault case). A raise models a DB blip on the renewal path — the exact trigger
        # that used to silently kill the heartbeat coroutine.
        self.renew_always_raises = False
        self.renew_raise_budget = 0
        # Round-trip latency injection (review finding a): ``latency_s`` sleeps at the start of
        # both acquire and renew, modelling the server round-trip. The conservative-deadline fix
        # seeds the ownership deadline from the loop time captured *before* acquire/renew (so the
        # local deadline is never later than the DB's ``expires_at``); with a non-zero latency the
        # old post-round-trip seed drifts the fence past true expiry.
        self.latency_s = 0.0
        # Photo-finish injection (review finding e): when ``renew_gate`` is an ``asyncio.Event``,
        # a renew blocks on it and returns ``False`` when it is set — so a scripted driver can make
        # its final advance and the fencing renew resolve on the same tick.
        self.renew_gate: asyncio.Event | None = None
        self.events: list[str] = []

    async def acquire(
        self, *, project_run_id: ProjectRunId, worker_id: str, ttl: timedelta
    ) -> bool:
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        holder = self.holders.get(project_run_id)
        if holder is None or holder == worker_id:
            self.holders[project_run_id] = worker_id
            self.events.append(f"acquire:{worker_id}")
            return True
        self.events.append(f"acquire-denied:{worker_id}")
        return False

    async def renew(self, *, project_run_id: ProjectRunId, worker_id: str, ttl: timedelta) -> bool:
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        if self.renew_always_raises or self.renew_raise_budget > 0:
            if not self.renew_always_raises:
                self.renew_raise_budget -= 1
            self.events.append(f"renew-raised:{worker_id}")
            raise RuntimeError("simulated renewal fault")
        if self.renew_gate is not None:
            await self.renew_gate.wait()
            self.events.append(f"renew-gated-false:{worker_id}")
            return False
        if self.deny_renewal or self.holders.get(project_run_id) != worker_id:
            self.events.append(f"renew-failed:{worker_id}")
            return False
        self.events.append(f"renew:{worker_id}")
        return True

    async def release(self, *, project_run_id: ProjectRunId, worker_id: str) -> None:
        if self.holders.get(project_run_id) == worker_id:
            del self.holders[project_run_id]
        self.events.append(f"release:{worker_id}")

    async def get(self, project_run_id: ProjectRunId) -> RunLeaseRow | None:
        holder = self.holders.get(project_run_id)
        if holder is None:
            return None
        now = _now()
        return RunLeaseRow(
            project_run_id=project_run_id,
            worker_id=holder,
            acquired_at=now,
            renewed_at=now,
            expires_at=now,
            live=True,
        )

    def expire(self, project_run_id: ProjectRunId) -> None:
        """Simulate the TTL lapsing (the previous holder is forgotten)."""
        self.holders.pop(project_run_id, None)


@dataclass
class _FakeTask:
    # The row is the single source of the FIFO key: ``row.enqueue_seq`` (minted at insert, mirroring
    # the DB's ``GENERATED ALWAYS AS IDENTITY`` column). No separate wrapper ``seq`` — one truth.
    row: FleetTaskRow


class FakeTaskQueue:
    """An in-memory :class:`~clue_fleet.TaskQueue` (no DB).

    Implements the enqueue-dedup, priority/FIFO claim order, and holder-guarded finish/requeue
    semantics; staleness reclaim is a DB-level behavior covered by the DB tests, so a claimed
    task here stays claimed until finished/requeued."""

    def __init__(self) -> None:
        self._tasks: dict[tuple[FleetTaskKind, ProjectRunId, str], _FakeTask] = {}
        self._seq = count()
        self.touches = 0

    def _fresh_row(
        self,
        *,
        kind: FleetTaskKind,
        project_run_id: ProjectRunId,
        dedup_key: str,
        priority: int,
        payload: dict[str, JsonValue],
        seq: int,
    ) -> FleetTaskRow:
        now = _now()
        return FleetTaskRow(
            task_id=uuid4(),
            kind=kind,
            project_run_id=project_run_id,
            dedup_key=dedup_key,
            priority=priority,
            status=FleetTaskStatus.QUEUED,
            attempts=0,
            payload=payload,
            result_ref={},
            claimed_by=None,
            claimed_at=None,
            enqueued_at=now,
            enqueue_seq=seq,  # the monotonic total FIFO key — matches the real identity column
            updated_at=now,
        )

    async def enqueue(
        self,
        *,
        kind: FleetTaskKind,
        project_run_id: ProjectRunId,
        dedup_key: str,
        priority: int = 0,
        payload: dict[str, JsonValue] | None = None,
        reopen_terminal: bool = False,
    ) -> bool:
        key = (kind, project_run_id, dedup_key)
        if key in self._tasks:
            existing = self._tasks[key]
            if reopen_terminal and existing.row.status in (
                FleetTaskStatus.DONE,
                FleetTaskStatus.FAILED,
            ):
                existing.row = existing.row.model_copy(
                    update={
                        "status": FleetTaskStatus.QUEUED,
                        "claimed_by": None,
                        "claimed_at": None,
                        "result_ref": {},
                        "priority": priority,
                    }
                )
                return True
            return False
        self._tasks[key] = _FakeTask(
            row=self._fresh_row(
                kind=kind,
                project_run_id=project_run_id,
                dedup_key=dedup_key,
                priority=priority,
                payload=payload if payload is not None else {},
                seq=next(self._seq),
            )
        )
        return True

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        project_run_id: ProjectRunId | None = None,
        stale_after: timedelta | None = None,
    ) -> FleetTaskRow | None:
        candidates = sorted(
            (
                task
                for task in self._tasks.values()
                if task.row.kind is kind
                and task.row.status is FleetTaskStatus.QUEUED
                and (project_run_id is None or task.row.project_run_id == project_run_id)
            ),
            key=lambda task: (task.row.priority, task.row.enqueue_seq),
        )
        if not candidates:
            return None
        task = candidates[0]
        task.row = task.row.model_copy(
            update={
                "status": FleetTaskStatus.CLAIMED,
                "claimed_by": worker_id,
                "claimed_at": _now(),
                "attempts": task.row.attempts + 1,
            }
        )
        return task.row

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, JsonValue] | None = None,
    ) -> bool:
        task = self._by_id(task_id)
        if (
            task is None
            or task.row.status is not FleetTaskStatus.CLAIMED
            or task.row.claimed_by != worker_id
        ):
            return False
        task.row = task.row.model_copy(
            update={"status": status, "result_ref": result_ref if result_ref is not None else {}}
        )
        return True

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool:
        task = self._by_id(task_id)
        if (
            task is None
            or task.row.status is not FleetTaskStatus.CLAIMED
            or task.row.claimed_by != worker_id
        ):
            return False
        task.row = task.row.model_copy(update={"claimed_at": _now()})
        self.touches += 1
        return True

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool:
        task = self._by_id(task_id)
        if (
            task is None
            or task.row.status is not FleetTaskStatus.CLAIMED
            or task.row.claimed_by != worker_id
        ):
            return False
        task.row = task.row.model_copy(
            update={"status": FleetTaskStatus.QUEUED, "claimed_by": None, "claimed_at": None}
        )
        return True

    async def requeue_failed(self, *, kind: FleetTaskKind, project_run_id: ProjectRunId) -> int:
        requeued = 0
        for task in self._tasks.values():
            if (
                task.row.kind is kind
                and task.row.project_run_id == project_run_id
                and task.row.status is FleetTaskStatus.FAILED
            ):
                task.row = task.row.model_copy(
                    update={
                        "status": FleetTaskStatus.QUEUED,
                        "claimed_by": None,
                        "claimed_at": None,
                    }
                )
                requeued += 1
        return requeued

    async def list_tasks(
        self, *, project_run_id: ProjectRunId, kind: FleetTaskKind
    ) -> list[FleetTaskRow]:
        return [
            task.row
            for task in sorted(
                self._tasks.values(), key=lambda t: (t.row.priority, t.row.enqueue_seq)
            )
            if task.row.project_run_id == project_run_id and task.row.kind is kind
        ]

    # -- test helpers --

    def _by_id(self, task_id: UUID) -> _FakeTask | None:
        for task in self._tasks.values():
            if task.row.task_id == task_id:
                return task
        return None

    def row(
        self, kind: FleetTaskKind, project_run_id: ProjectRunId, dedup_key: str
    ) -> FleetTaskRow:
        return self._tasks[(kind, project_run_id, dedup_key)].row

    def mark_done(self, kind: FleetTaskKind, project_run_id: ProjectRunId, dedup_key: str) -> None:
        """Simulate a previous drive having finished this task (the resume/replay path)."""
        task = self._tasks[(kind, project_run_id, dedup_key)]
        task.row = task.row.model_copy(update={"status": FleetTaskStatus.DONE})


def run_row(
    project_run_id: ProjectRunId,
    *,
    phase: ProjectPhase = ProjectPhase.REVERSE_PROFILING,
    status: ProjectRunStatus = ProjectRunStatus.ACTIVE,
    spent_cents: CostCents | None = None,
) -> ProjectRunRow:
    """A minimal :class:`ProjectRunRow` for scripting fake drivers."""
    from decimal import Decimal

    now = _now()
    return ProjectRunRow(
        id=project_run_id,
        project_id="prj-fleet-test",
        brand_id="brd-fleet-test",
        workspace_id="ws-fleet-test",
        icp_key="icp",
        icp_version=1,
        phase=phase,
        status=status,
        budget_cap_cents=None,
        spent_cents=spent_cents if spent_cents is not None else Decimal(0),
        tier_cutoffs={},
        paused_at=None,
        resumed_at=None,
        created_at=now,
        updated_at=now,
    )


@dataclass
class ScriptedDriver:
    """A scripted :class:`~clue_fleet.RunDriver`: ``status`` returns ``initial``; each ``advance``
    pops the next row from ``steps`` (repeating the last one when exhausted — the no-progress
    shape). ``on_advance`` lets a test trigger side effects (e.g. ``worker.stop()``) mid-drive."""

    initial: ProjectRunRow
    steps: list[ProjectRunRow] = field(default_factory=list)
    advance_delay_s: float = 0.0
    on_advance: Any = None
    advances: int = 0
    # Phase-boundary vs mid-phase observability (audit finding #2): ``advance_started`` ticks at
    # entry (before the delay), ``advance_finished`` only after the body completes. A phase
    # cancelled mid-flight leaves ``advance_started > advance_finished`` — the proof that fencing
    # is now immediate cancellation, not a wait for the next boundary.
    advance_started: int = 0
    advance_finished: int = 0

    async def status(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        return self.initial

    async def advance(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        import asyncio

        self.advance_started += 1
        if self.advance_delay_s:
            await asyncio.sleep(self.advance_delay_s)
        if self.on_advance is not None:
            self.on_advance()
        self.advances += 1
        if self.steps:
            self.initial = self.steps.pop(0)
        self.advance_finished += 1
        return self.initial
