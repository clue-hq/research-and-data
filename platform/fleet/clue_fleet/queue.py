"""The durable fleet task queue (PB-B1) — the ``fleet_task`` table the worker drains.

One table holds both task kinds (:class:`~clue_fleet.enums.FleetTaskKind`): ``drive_run`` jobs
any worker may claim, and ``account_job`` rows that give the ``deep`` phase its tier-priority
order (REQ-10 — "budget exhaustion still researched the *best* accounts first"). Rows are
*fleet-plane* state: ``project_run_id`` rides as an opaque id (a soft FK, like every M7 table)
and ``payload_json`` / ``result_ref_json`` carry references only, never blobs (substrate §5b).

Semantics, all decided at the database (no read-then-write races):

* **enqueue** is idempotent on ``(kind, project_run_id, dedup_key)`` (``ON CONFLICT DO
  NOTHING``) — re-entering a drive re-offers the same work without duplicating rows.
* **claim-next** is one atomic ``UPDATE … FROM (SELECT … ORDER BY priority, enqueue_seq LIMIT 1
  FOR UPDATE SKIP LOCKED)`` — the best runnable row in ``(priority, enqueue_seq)`` order, where
  ``enqueue_seq`` is a monotonic insertion sequence (a ``GENERATED ALWAYS AS IDENTITY`` column):
  timestamps alone cannot provide FIFO because ``now()`` is transaction-stable, so same-priority
  rows enqueued in one transaction share ``enqueued_at`` and tie with no final key. Concurrent
  claimants never receive the same row. A ``CLAIMED`` row whose ``claimed_at`` has passed the
  staleness window is re-owned (its holder is presumed killed) — the M7.4 ledger's recovery
  shape.
* **finish / requeue** are holder-guarded (``WHERE claimed_by = :me AND status = 'claimed'``): a
  fenced-out zombie's write matches zero rows.
* **requeue_failed** is the explicit retry gate — a fresh drive re-entering the work re-offers
  ``FAILED`` rows; nothing retries silently.

Repository shape mirrors ``durable/idempotency.py``; :class:`DbTaskQueue` wraps the helpers in
``db.transaction()`` behind the :class:`TaskQueue` seam (in-memory-fake testable, backend
swappable — Temporal-native queues later — conventions §2).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId, UtcDatetime, parse_value_json, serialize_value_json
from clue_db import transaction
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import WorkId

# A ``CLAIMED`` task older than this is presumed orphaned by a killed worker and is re-owned by
# the next claimant. Sized to outlive the driver lease TTL (takeover is lease-gated first; the
# task follows), tunable via ``Settings.fleet_task_stale_after_s``.
DEFAULT_TASK_STALE_AFTER = timedelta(seconds=60)


class FleetTaskRow(BaseModel):
    """One ``fleet_task`` row (PB-B1) — a claimable unit of fleet work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    kind: FleetTaskKind
    project_run_id: ProjectRunId
    dedup_key: str
    priority: int
    status: FleetTaskStatus
    attempts: int
    payload: dict[str, JsonValue]
    result_ref: dict[str, JsonValue]
    claimed_by: str | None
    claimed_at: UtcDatetime | None
    enqueued_at: UtcDatetime
    enqueue_seq: int
    updated_at: UtcDatetime


class WorkTaskRow(BaseModel):
    """Generic fleet view. ``FleetTaskRow`` remains the project-run compatibility view."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    kind: FleetTaskKind
    work_id: WorkId
    dedup_key: str
    priority: int
    status: FleetTaskStatus
    attempts: int
    payload: dict[str, JsonValue]
    result_ref: dict[str, JsonValue]
    claimed_by: str | None
    claimed_at: UtcDatetime | None
    enqueued_at: UtcDatetime
    enqueue_seq: int
    updated_at: UtcDatetime


def _to_work_task(row: FleetTaskRow) -> WorkTaskRow:
    return WorkTaskRow.model_validate(
        {
            **row.model_dump(exclude={"project_run_id"}),
            "work_id": row.project_run_id,
        }
    )


_COLUMNS = (
    "task_id, kind, work_id AS project_run_id, dedup_key, priority, status, attempts, "
    "payload_json, result_ref_json, claimed_by, claimed_at, enqueued_at, enqueue_seq, updated_at"
)

# The claim-next RETURNING joins ``fleet_task`` with the ``candidate`` subquery, which also
# exposes ``task_id`` — qualify every column so the reference is unambiguous.
_QUALIFIED_COLUMNS = ", ".join(f"fleet_task.{col}" for col in _COLUMNS.split(", "))

_ENQUEUE_SQL = text(
    """
    INSERT INTO fleet_task (task_id, kind, work_id, dedup_key, priority, payload_json)
    VALUES (
        :task_id, CAST(:kind AS fleet_task_kind), :project_run_id, :dedup_key, :priority,
        CAST(:payload AS jsonb)
    )
    ON CONFLICT (kind, work_id, dedup_key) DO NOTHING
    RETURNING task_id
    """
)

# Re-offering variant: like _ENQUEUE_SQL, but a *terminal* (done/failed) row on the dedup key is
# re-opened back to ``queued`` — the ``enqueue_drive`` path, where "drive this run" is a
# recurring offer (a paused run's finished drive task must not block the post-resume re-drive).
# A queued/claimed row is still a no-op (the work is already offered/owned). The re-opened row
# KEEPS its original ``enqueue_seq`` — an identity column does not re-mint on UPDATE — so a
# resumed run retains its FIFO place ahead of newer work (intended, not incidental).
_ENQUEUE_REOPEN_SQL = text(
    """
    INSERT INTO fleet_task (task_id, kind, work_id, dedup_key, priority, payload_json)
    VALUES (
        :task_id, CAST(:kind AS fleet_task_kind), :project_run_id, :dedup_key, :priority,
        CAST(:payload AS jsonb)
    )
    ON CONFLICT (kind, work_id, dedup_key) DO UPDATE
        SET status = 'queued',
            claimed_by = NULL,
            claimed_at = NULL,
            result_ref_json = '{}'::jsonb,
            priority = :priority,
            updated_at = now()
        WHERE fleet_task.status IN ('done', 'failed')
    RETURNING task_id
    """
)

# Atomic claim-next. The inner SELECT picks the single best runnable row — ``queued``, or
# ``claimed`` past the staleness window — in ``(priority, enqueue_seq)`` order, locking it with
# SKIP LOCKED so concurrent claimants (in-process drainers or a second worker process) fall
# through to the next row instead of blocking or double-claiming. ``enqueue_seq`` (not
# ``enqueued_at``) is the FIFO key — the transaction-stable ``now()`` cannot break same-priority
# ties. ``:project_run_id`` narrows to one run's tasks (the deep drain) or, when NULL, spans all
# runs (the worker's drive-task drain).
_CLAIM_NEXT_SQL = text(
    f"""
    UPDATE fleet_task
    SET status = 'claimed',
        claimed_by = :worker_id,
        claimed_at = now(),
        attempts = attempts + 1,
        updated_at = now()
    FROM (
        SELECT task_id
        FROM fleet_task
        WHERE kind = CAST(:kind AS fleet_task_kind)
          AND (CAST(:project_run_id AS uuid) IS NULL OR work_id = :project_run_id)
          AND (
                status = 'queued'
                OR (status = 'claimed' AND claimed_at <= now() - CAST(:stale AS interval))
              )
        ORDER BY priority, enqueue_seq
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    ) AS candidate
    WHERE fleet_task.task_id = candidate.task_id
    RETURNING {_QUALIFIED_COLUMNS}
    """
)

_FINISH_SQL = text(
    """
    UPDATE fleet_task
    SET status = CAST(:status AS fleet_task_status),
        result_ref_json = CAST(:result_ref AS jsonb),
        updated_at = now()
    WHERE task_id = :task_id AND claimed_by = :worker_id AND status = 'claimed'
    RETURNING task_id
    """
)

# The claim heartbeat: a live holder re-stamps ``claimed_at`` so its claim never crosses the
# staleness window mid-work (the drive-task analogue of the lease renewal; long jobs would
# otherwise look orphaned to other claimants). Holder-guarded like finish/requeue.
_TOUCH_SQL = text(
    """
    UPDATE fleet_task
    SET claimed_at = now(), updated_at = now()
    WHERE task_id = :task_id AND claimed_by = :worker_id AND status = 'claimed'
    RETURNING task_id
    """
)

_REQUEUE_SQL = text(
    """
    UPDATE fleet_task
    SET status = 'queued', claimed_by = NULL, claimed_at = NULL, updated_at = now()
    WHERE task_id = :task_id AND claimed_by = :worker_id AND status = 'claimed'
    RETURNING task_id
    """
)

_REQUEUE_FAILED_SQL = text(
    """
    UPDATE fleet_task
    SET status = 'queued', claimed_by = NULL, claimed_at = NULL, updated_at = now()
    WHERE kind = CAST(:kind AS fleet_task_kind)
      AND work_id = :project_run_id
      AND status = 'failed'
    """
)

_GET_SQL = text(f"SELECT {_COLUMNS} FROM fleet_task WHERE task_id = :task_id")

_LIST_SQL = text(
    f"""
    SELECT {_COLUMNS} FROM fleet_task
    WHERE work_id = :project_run_id AND kind = CAST(:kind AS fleet_task_kind)
    ORDER BY priority, enqueue_seq
    """
)


def _decode_object(raw: object) -> dict[str, JsonValue]:
    """Decode a JSONB object column (asyncpg returns it decoded; bytes are parsed via the one
    ``core`` path — the ``durable/idempotency.py`` shape)."""
    decoded = parse_value_json(bytes(raw)) if isinstance(raw, (bytes, bytearray)) else raw
    return decoded if isinstance(decoded, dict) else {}


def _row_to_task(row: dict[str, object]) -> FleetTaskRow:
    return FleetTaskRow.model_validate(
        {
            "task_id": row["task_id"],
            "kind": row["kind"],
            "project_run_id": row["project_run_id"],
            "dedup_key": row["dedup_key"],
            "priority": row["priority"],
            "status": row["status"],
            "attempts": row["attempts"],
            "payload": _decode_object(row["payload_json"]),
            "result_ref": _decode_object(row["result_ref_json"]),
            "claimed_by": row["claimed_by"],
            "claimed_at": row["claimed_at"],
            "enqueued_at": row["enqueued_at"],
            "enqueue_seq": row["enqueue_seq"],
            "updated_at": row["updated_at"],
        }
    )


async def enqueue_task(
    conn: AsyncConnection,
    *,
    kind: FleetTaskKind,
    project_run_id: ProjectRunId,
    dedup_key: str,
    priority: int = 0,
    payload: dict[str, JsonValue] | None = None,
    reopen_terminal: bool = False,
) -> bool:
    """Idempotently enqueue one task; ``True`` iff the work is newly offered (a fresh row, or —
    with ``reopen_terminal`` — a terminal row re-opened to ``queued``).

    Default (``reopen_terminal=False``): a duplicate ``(kind, project_run_id, dedup_key)`` is a
    pure no-op whatever its state — the ``account_job`` semantics, where a ``done`` row is this
    run's exactly-once completion marker and must stay done across re-entries. With
    ``reopen_terminal=True`` (the ``drive_run`` semantics — see :func:`~clue_fleet.worker.
    enqueue_drive`): a ``done``/``failed`` row is re-opened for a fresh drive (a paused run's
    finished drive task must not block its post-resume re-drive); a ``queued``/``claimed`` row is
    still a no-op."""
    statement = _ENQUEUE_REOPEN_SQL if reopen_terminal else _ENQUEUE_SQL
    row = (
        await conn.execute(
            statement,
            {
                "task_id": uuid4(),
                "kind": kind.value,
                "project_run_id": project_run_id,
                "dedup_key": dedup_key,
                "priority": priority,
                "payload": serialize_value_json(payload if payload is not None else {}),
            },
        )
    ).first()
    return row is not None


async def claim_next_task(
    conn: AsyncConnection,
    *,
    kind: FleetTaskKind,
    worker_id: str,
    project_run_id: ProjectRunId | None = None,
    stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
) -> FleetTaskRow | None:
    """Atomically claim the best runnable task (priority, then FIFO), or ``None`` when nothing is
    claimable. Re-owns a stale ``CLAIMED`` row (killed holder); skips rows locked by concurrent
    claimants (``SKIP LOCKED``)."""
    row = (
        (
            await conn.execute(
                _CLAIM_NEXT_SQL,
                {
                    "kind": kind.value,
                    "worker_id": worker_id,
                    "project_run_id": project_run_id,
                    "stale": stale_after,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return _row_to_task(dict(row)) if row is not None else None


async def finish_task(
    conn: AsyncConnection,
    *,
    task_id: UUID,
    worker_id: str,
    status: FleetTaskStatus,
    result_ref: dict[str, JsonValue] | None = None,
) -> bool:
    """Mark a claimed task terminal (``DONE`` / ``FAILED``) with its references-only
    ``result_ref``. Holder-guarded: ``False`` when this worker no longer owns the claim (fenced
    out by a stale-reclaim) — the new owner's outcome stands."""
    if status not in (FleetTaskStatus.DONE, FleetTaskStatus.FAILED):
        raise ValueError(f"finish_task records a terminal status, not {status.value!r}")
    row = (
        await conn.execute(
            _FINISH_SQL,
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "status": status.value,
                "result_ref": serialize_value_json(result_ref if result_ref is not None else {}),
            },
        )
    ).first()
    return row is not None


async def touch_task(conn: AsyncConnection, *, task_id: UUID, worker_id: str) -> bool:
    """Re-stamp a claimed task's ``claimed_at`` (the claim heartbeat). ``False`` when this
    worker no longer owns the claim — informational; the lease, not the task stamp, is the
    authority on who drives."""
    row = (await conn.execute(_TOUCH_SQL, {"task_id": task_id, "worker_id": worker_id})).first()
    return row is not None


async def requeue_task(conn: AsyncConnection, *, task_id: UUID, worker_id: str) -> bool:
    """Hand a claimed task back to ``QUEUED`` (the graceful-stop path). Holder-guarded like
    :func:`finish_task`."""
    row = (await conn.execute(_REQUEUE_SQL, {"task_id": task_id, "worker_id": worker_id})).first()
    return row is not None


async def requeue_failed_tasks(
    conn: AsyncConnection, *, kind: FleetTaskKind, project_run_id: ProjectRunId
) -> int:
    """Re-offer every ``FAILED`` task of ``kind`` for this run (the explicit retry gate a fresh
    drive opens on re-entry). Returns how many rows were requeued."""
    result = await conn.execute(
        _REQUEUE_FAILED_SQL, {"kind": kind.value, "project_run_id": project_run_id}
    )
    return result.rowcount or 0


async def get_task(conn: AsyncConnection, task_id: UUID) -> FleetTaskRow | None:
    """Read one task row, or ``None``."""
    row = (await conn.execute(_GET_SQL, {"task_id": task_id})).mappings().one_or_none()
    return _row_to_task(dict(row)) if row is not None else None


async def list_tasks(
    conn: AsyncConnection, *, project_run_id: ProjectRunId, kind: FleetTaskKind
) -> list[FleetTaskRow]:
    """Every task of ``kind`` for this run in claim order — the drain/observability read."""
    rows = (
        (await conn.execute(_LIST_SQL, {"project_run_id": project_run_id, "kind": kind.value}))
        .mappings()
        .all()
    )
    return [_row_to_task(dict(row)) for row in rows]


# --- the persistence seam --------------------------------------------------------------------


@runtime_checkable
class TaskQueue(Protocol):
    """The seam the worker and the queue-backed scheduler drain tasks through (PB-B1). In-memory
    fakes drive the loop tests; :class:`DbTaskQueue` is production (conventions §2)."""

    async def enqueue(
        self,
        *,
        kind: FleetTaskKind,
        project_run_id: ProjectRunId,
        dedup_key: str,
        priority: int = 0,
        payload: dict[str, JsonValue] | None = None,
        reopen_terminal: bool = False,
    ) -> bool: ...

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        project_run_id: ProjectRunId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
    ) -> FleetTaskRow | None: ...

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, JsonValue] | None = None,
    ) -> bool: ...

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool: ...

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool: ...

    async def requeue_failed(self, *, kind: FleetTaskKind, project_run_id: ProjectRunId) -> int: ...

    async def list_tasks(
        self, *, project_run_id: ProjectRunId, kind: FleetTaskKind
    ) -> list[FleetTaskRow]: ...


class DbTaskQueue:
    """The Postgres :class:`TaskQueue`. Each method is its own ``db.transaction()`` — a claim is
    one atomic statement whose row lock must not outlive the call (holding it across a long job
    would defeat SKIP LOCKED's liveness)."""

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
        async with transaction() as conn:
            return await enqueue_task(
                conn,
                kind=kind,
                project_run_id=project_run_id,
                dedup_key=dedup_key,
                priority=priority,
                payload=payload,
                reopen_terminal=reopen_terminal,
            )

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        project_run_id: ProjectRunId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
    ) -> FleetTaskRow | None:
        async with transaction() as conn:
            return await claim_next_task(
                conn,
                kind=kind,
                worker_id=worker_id,
                project_run_id=project_run_id,
                stale_after=stale_after,
            )

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, JsonValue] | None = None,
    ) -> bool:
        async with transaction() as conn:
            return await finish_task(
                conn, task_id=task_id, worker_id=worker_id, status=status, result_ref=result_ref
            )

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool:
        async with transaction() as conn:
            return await touch_task(conn, task_id=task_id, worker_id=worker_id)

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool:
        async with transaction() as conn:
            return await requeue_task(conn, task_id=task_id, worker_id=worker_id)

    async def requeue_failed(self, *, kind: FleetTaskKind, project_run_id: ProjectRunId) -> int:
        async with transaction() as conn:
            return await requeue_failed_tasks(conn, kind=kind, project_run_id=project_run_id)

    async def list_tasks(
        self, *, project_run_id: ProjectRunId, kind: FleetTaskKind
    ) -> list[FleetTaskRow]:
        async with transaction() as conn:
            return await list_tasks(conn, project_run_id=project_run_id, kind=kind)


@runtime_checkable
class WorkQueue(Protocol):
    """Generic top-level queue seam used by the multi-handler fleet worker."""

    async def enqueue(
        self,
        *,
        kind: FleetTaskKind,
        work_id: WorkId,
        dedup_key: str,
        priority: int = 0,
        payload: dict[str, JsonValue] | None = None,
        reopen_terminal: bool = False,
    ) -> bool: ...

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
    ) -> WorkTaskRow | None: ...

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, JsonValue] | None = None,
    ) -> bool: ...

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool: ...

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool: ...


class DbWorkQueue:
    """Generic adapter over the fleet table's existing repository implementation."""

    def __init__(self, queue: TaskQueue | None = None) -> None:
        self._queue = queue if queue is not None else DbTaskQueue()

    async def enqueue(
        self,
        *,
        kind: FleetTaskKind,
        work_id: WorkId,
        dedup_key: str,
        priority: int = 0,
        payload: dict[str, JsonValue] | None = None,
        reopen_terminal: bool = False,
    ) -> bool:
        return await self._queue.enqueue(
            kind=kind,
            project_run_id=ProjectRunId(work_id),
            dedup_key=dedup_key,
            priority=priority,
            payload=payload,
            reopen_terminal=reopen_terminal,
        )

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
    ) -> WorkTaskRow | None:
        row = await self._queue.claim_next(
            kind=kind,
            worker_id=worker_id,
            project_run_id=ProjectRunId(work_id) if work_id is not None else None,
            stale_after=stale_after,
        )
        return _to_work_task(row) if row is not None else None

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, JsonValue] | None = None,
    ) -> bool:
        return await self._queue.finish(
            task_id=task_id,
            worker_id=worker_id,
            status=status,
            result_ref=result_ref,
        )

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool:
        return await self._queue.touch(task_id=task_id, worker_id=worker_id)

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool:
        return await self._queue.requeue(task_id=task_id, worker_id=worker_id)


__all__ = [
    "DEFAULT_TASK_STALE_AFTER",
    "DbTaskQueue",
    "DbWorkQueue",
    "FleetTaskRow",
    "TaskQueue",
    "WorkQueue",
    "WorkTaskRow",
    "claim_next_task",
    "enqueue_task",
    "finish_task",
    "get_task",
    "list_tasks",
    "requeue_failed_tasks",
    "requeue_task",
    "touch_task",
]
