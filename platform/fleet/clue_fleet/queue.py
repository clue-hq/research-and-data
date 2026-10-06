"""The durable fleet task queue (PB-B1) — the ``fleet_task`` table the worker drains.

One table holds every mechanical task kind (:class:`~clue_fleet.enums.FleetTaskKind`): project-run
drives, run-internal legacy account jobs, recipe graphs, and M8D subject-neutral entity-research
jobs. Rows are *fleet-plane* state: ``work_id`` is an opaque UUID (the compatibility projection
still calls it ``project_run_id``) and ``payload_json`` / ``result_ref_json`` carry references
only, never blobs (substrate §5b).

Semantics, all decided at the database (no read-then-write races):

* **enqueue** is idempotent on ``(kind, project_run_id, dedup_key)`` (``ON CONFLICT DO
  NOTHING``) — re-entering a drive re-offers the same work without duplicating rows.
* **claim-next** is one atomic ``UPDATE … FROM (SELECT … ORDER BY priority, enqueue_seq LIMIT 1
  FOR UPDATE SKIP LOCKED)`` — the best runnable row in ``(priority, enqueue_seq)`` order after its
  DB-clock ``available_at`` boundary. ``enqueue_seq`` is a monotonic insertion sequence (a
  ``GENERATED ALWAYS AS IDENTITY`` column): timestamps alone cannot provide FIFO because
  ``now()`` is transaction-stable, so same-priority rows enqueued in one transaction share
  ``enqueued_at`` and tie with no final key. Concurrent claimants never receive the same row. A
  ``CLAIMED`` row whose ``claimed_at`` has passed the staleness window is re-owned (its holder is
  presumed killed) — the M7.4 ledger's recovery shape.
* **finish / requeue** are holder-guarded (``WHERE claimed_by = :me AND status = 'claimed'``): a
  fenced-out zombie's write matches zero rows.
* **requeue_failed** is the explicit retry gate — a fresh drive re-entering the work re-offers
  ``FAILED`` rows; nothing retries silently.

Repository shape mirrors ``durable/idempotency.py``; :class:`DbTaskQueue` wraps the helpers in
``db.transaction()`` behind the :class:`TaskQueue` seam (in-memory-fake testable, backend
swappable — Temporal-native queues later — conventions §2).
"""

from __future__ import annotations

from collections.abc import Mapping
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
from clue_obs.otel import carrier_from_current_span

# A ``CLAIMED`` task older than this is presumed orphaned by a killed worker and is re-owned by
# the next claimant. Sized to outlive the driver lease TTL (takeover is lease-gated first; the
# task follows), tunable via ``Settings.fleet_task_stale_after_s``.
DEFAULT_TASK_STALE_AFTER = timedelta(seconds=60)


class TaskCapability(BaseModel):
    """One claim-time capability constraint a worker applies to a kind's payloads (R3-B).

    Reads: *if this task's payload carries* ``field``, *its value must be one this worker*
    ``supported``. With ``required=True``, a missing field is also refused. Otherwise a payload
    without the field is unconstrained, preserving optional capability hints.

    It exists because a :class:`~clue_fleet.enums.FleetTaskKind` is not always fine-grained
    enough to answer "can this process run this task?". ``design_job`` is the proven case: ONE
    fleet kind carries agent turns and brand-kit ingestions, and an ingestion's runnability
    depends on its ``ingestion_kind`` — a lane the worker's build may not know about at all, or
    may know about behind a deployment flag that is off. The W5 acceptance walk caught the
    consequence: a two-day-old detached worker claimed an ``ad_assets`` ingestion it could not
    execute, failed it in half a second, and the winner of the claim race decided at random
    whether lane onboarding worked.

    The constraint is applied **inside the claim statement**, not after the claim, which is the
    whole point: an unsupported task must be left ``queued`` for a capable worker rather than
    claimed-and-failed. ``supported`` is what this process CAN run, never a blacklist of what it
    cannot — a worker whose code predates a payload value cannot enumerate it, but it also
    cannot list it as supported, so it is excluded for free.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: A top-level key of ``payload_json``.
    field: str
    #: The values of that key this worker can execute. Empty means "none" — the field's mere
    #: presence disqualifies the task.
    supported: frozenset[str]
    # Routing boundaries require a discriminant; optional capability hints do not.
    required: bool = False

    def as_json(self) -> dict[str, JsonValue]:
        """The jsonb shape the claim statement's capability predicate iterates (sorted, so the
        bound parameter is stable and diffable in a query log)."""
        # Widened by construction rather than by a cast: ``list`` is invariant, so a
        # ``list[str]`` is not a ``list[JsonValue]`` however obviously every element is one.
        supported: list[JsonValue] = []
        supported.extend(sorted(self.supported))
        return {
            "field": self.field,
            "supported": supported,
            **({"required": True} if self.required else {}),
        }

    def permits(self, payload: Mapping[str, JsonValue]) -> bool:
        """Whether this constraint admits ``payload`` — the Python mirror of the SQL predicate.

        Production claims in SQL; the in-memory fakes the loop tests drive claim through this.
        One definition, two evaluators, so a fake cannot quietly hand a worker work the database
        would have withheld. A non-string or ``null`` value is admitted by neither, which is the
        fail-closed direction: a payload whose discriminant is not a value this worker listed is
        not this worker's to run.
        """
        if self.field not in payload:
            return not self.required
        return isinstance(payload[self.field], str) and payload[self.field] in self.supported


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
    available_at: UtcDatetime
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
    available_at: UtcDatetime
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
    "payload_json, result_ref_json, claimed_by, claimed_at, available_at, enqueued_at, "
    "enqueue_seq, updated_at"
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
            available_at = now(),
            result_ref_json = '{}'::jsonb,
            priority = :priority,
            updated_at = now()
        WHERE fleet_task.status IN ('done', 'failed')
    RETURNING task_id
    """
)

# Offer-if-idle variant: like _ENQUEUE_SQL, but nothing is inserted while any *live* (queued or
# claimed) task of the same kind exists on the work id, whatever its dedup key. Tasks that share a
# work id share one lease, so a second live task could only wait on the first; the offerer offers
# again after the live task ends. Serialized per (kind, work id) by the advisory lock taken just
# before it in the same transaction, so two concurrent offerers cannot both find the work idle.
_ENQUEUE_IF_IDLE_SQL = text(
    """
    INSERT INTO fleet_task (task_id, kind, work_id, dedup_key, priority, payload_json)
    SELECT
        :task_id, CAST(:kind AS fleet_task_kind), :project_run_id, :dedup_key, :priority,
        CAST(:payload AS jsonb)
    WHERE NOT EXISTS (
        SELECT 1 FROM fleet_task
        WHERE kind = CAST(:kind AS fleet_task_kind)
          AND work_id = :project_run_id
          AND status IN ('queued', 'claimed')
    )
    ON CONFLICT (kind, work_id, dedup_key) DO NOTHING
    RETURNING task_id
    """
)

_OFFER_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")

# Atomic claim-next. A MATERIALIZED candidate prevents planner rescans of the locking SELECT
# from selecting more rows as SKIP LOCKED changes under concurrent updates.
# The inner SELECT picks the single best runnable row — ``queued``, or
# ``claimed`` past the staleness window — in ``(priority, enqueue_seq)`` order, locking it with
# SKIP LOCKED so concurrent claimants (in-process drainers or a second worker process) fall
# through to the next row instead of blocking or double-claiming. ``enqueue_seq`` (not
# ``enqueued_at``) is the FIFO key — the transaction-stable ``now()`` cannot break same-priority
# ties. ``:project_run_id`` narrows to one run's tasks (the deep drain) or, when NULL, spans all
# runs (the worker's drive-task drain).
#
# THE CAPABILITY PREDICATE (R3-B). ``:capabilities`` is a jsonb array of
# :class:`TaskCapability`-shaped objects — ``[]`` for a worker that can run every payload of the
# kind, which makes the ``NOT EXISTS`` vacuously true and the statement byte-for-byte equivalent
# to the pre-R3-B one. A capability disqualifies a row only when the row's payload actually
# CARRIES the named field and its value is outside the supported set, so a kind that mixes
# payload shapes (``design_job``: turns and ingestions) filters only the shape that declares the
# discriminant. This is a SELECT-side predicate, so an unsupported task is never claimed at all —
# it stays ``queued``, with its position intact, for a worker that can run it.
_CLAIM_NEXT_SQL = text(
    f"""
    WITH candidate AS MATERIALIZED (
        SELECT task_id
        FROM fleet_task
        WHERE kind = CAST(:kind AS fleet_task_kind)
          AND (CAST(:project_run_id AS uuid) IS NULL OR work_id = :project_run_id)
          AND (
                (status = 'queued' AND available_at <= now())
                OR (status = 'claimed' AND claimed_at <= now() - CAST(:stale AS interval))
              )
          AND NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(CAST(:capabilities AS jsonb)) AS cap
                WHERE (COALESCE((cap->>'required')::boolean, false)
                       AND NOT payload_json ? (cap->>'field'))
                  OR (payload_json ? (cap->>'field')
                  AND NOT cap->'supported' @> jsonb_build_array(
                        payload_json->(cap->>'field')
                      ))
              )
        ORDER BY priority, enqueue_seq
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE fleet_task
    SET status = 'claimed',
        claimed_by = :worker_id,
        claimed_at = now(),
        attempts = attempts + 1,
        updated_at = now()
    FROM candidate
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
    SET status = 'queued', claimed_by = NULL, claimed_at = NULL,
        available_at = now() + make_interval(secs => :delay_seconds),
        attempts = attempts - CAST(:uncount AS integer), updated_at = now()
    WHERE task_id = :task_id AND claimed_by = :worker_id AND status = 'claimed'
    RETURNING task_id
    """
)

_REQUEUE_FAILED_SQL = text(
    """
    UPDATE fleet_task
    SET status = 'queued', claimed_by = NULL, claimed_at = NULL,
        available_at = now(), updated_at = now()
    WHERE kind = CAST(:kind AS fleet_task_kind)
      AND work_id = :project_run_id
      AND status = 'failed'
    """
)

_CANCEL_WORK_SQL = text(
    """
    UPDATE fleet_task
    SET status = 'done',
        result_ref_json = CAST(:result_ref AS jsonb),
        claimed_by = NULL,
        claimed_at = NULL,
        updated_at = now()
    WHERE kind = CAST(:kind AS fleet_task_kind)
      AND work_id = :work_id
      AND (
            status IN ('queued', 'claimed')
            OR (status = 'done' AND result_ref_json->>'outcome' = 'waiting_external')
          )
    """
)

_REOFFER_GOVERNED_PARTIAL_SQL = text(
    """
    UPDATE fleet_task
    SET status = 'queued',
        claimed_by = NULL,
        claimed_at = NULL,
        available_at = now(),
        result_ref_json = '{}'::jsonb,
        updated_at = now()
    WHERE kind = 'account_job'
      AND work_id = :project_run_id
      AND dedup_key = :dedup_key
      AND status = 'done'
      AND result_ref_json->>'status' = 'governed_partial'
    RETURNING task_id
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


def payload_is_claimable(
    capabilities: tuple[TaskCapability, ...], payload: Mapping[str, JsonValue]
) -> bool:
    """Whether every declared capability admits ``payload``. Empty capabilities admit anything."""
    return all(capability.permits(payload) for capability in capabilities)


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
            "available_at": row["available_at"],
            "enqueued_at": row["enqueued_at"],
            "enqueue_seq": row["enqueue_seq"],
            "updated_at": row["updated_at"],
        }
    )


def _with_trace_carrier(payload: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    """The payload plus the current span's W3C carrier (lane 3 slice 2, D1).

    Stamped only when a valid span is current, and never over a key the caller set, so an enqueue
    outside any trace writes exactly the payload it was given.
    """
    stamped: dict[str, JsonValue] = dict(payload) if payload is not None else {}
    for key, value in carrier_from_current_span().items():
        stamped.setdefault(key, value)
    return stamped


async def enqueue_task(
    conn: AsyncConnection,
    *,
    kind: FleetTaskKind,
    project_run_id: ProjectRunId,
    dedup_key: str,
    priority: int = 0,
    payload: dict[str, JsonValue] | None = None,
    reopen_terminal: bool = False,
    only_if_work_idle: bool = False,
) -> bool:
    """Idempotently enqueue one task; ``True`` iff the work is newly offered (a fresh row, or —
    with ``reopen_terminal`` — a terminal row re-opened to ``queued``).

    Default (``reopen_terminal=False``): a duplicate ``(kind, project_run_id, dedup_key)`` is a
    pure no-op whatever its state — the ``account_job`` semantics, where a ``done`` row is this
    run's exactly-once completion marker and must stay done across re-entries. With
    ``reopen_terminal=True`` (the ``drive_run`` semantics — see :func:`~clue_fleet.worker.
    enqueue_drive`): a ``done``/``failed`` row is re-opened for a fresh drive (a paused run's
    finished drive task must not block its post-resume re-drive); a ``queued``/``claimed`` row is
    still a no-op.

    ``only_if_work_idle=True``: also a no-op while any queued or claimed task of ``kind`` exists
    on ``project_run_id`` under *another* dedup key — for an offerer that re-offers the latest
    state on a timer and must not pile tasks behind one lease (the ARV2 quality sweep)."""
    if only_if_work_idle and reopen_terminal:
        raise ValueError("only_if_work_idle cannot be combined with reopen_terminal")
    statement = _ENQUEUE_REOPEN_SQL if reopen_terminal else _ENQUEUE_SQL
    if only_if_work_idle:
        await conn.execute(_OFFER_LOCK_SQL, {"key": f"fleet-offer:{kind.value}:{project_run_id}"})
        statement = _ENQUEUE_IF_IDLE_SQL
    row = (
        await conn.execute(
            statement,
            {
                "task_id": uuid4(),
                "kind": kind.value,
                "project_run_id": project_run_id,
                "dedup_key": dedup_key,
                "priority": priority,
                "payload": serialize_value_json(_with_trace_carrier(payload)),
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
    capabilities: tuple[TaskCapability, ...] = (),
) -> FleetTaskRow | None:
    """Atomically claim the best runnable task (priority, then FIFO), or ``None`` when nothing is
    claimable. Re-owns a stale ``CLAIMED`` row (killed holder); skips rows locked by concurrent
    claimants (``SKIP LOCKED``).

    ``capabilities`` narrows the claim to payloads this worker can actually execute (see
    :class:`TaskCapability`). The default — none — is the historical behaviour exactly.
    """
    row = (
        (
            await conn.execute(
                _CLAIM_NEXT_SQL,
                {
                    "kind": kind.value,
                    "worker_id": worker_id,
                    "project_run_id": project_run_id,
                    "stale": stale_after,
                    "capabilities": serialize_value_json(
                        [capability.as_json() for capability in capabilities]
                    ),
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


async def requeue_task(
    conn: AsyncConnection,
    *,
    task_id: UUID,
    worker_id: str,
    delay: timedelta | None = None,
    uncount_attempt: bool = False,
) -> bool:
    """Hand a claimed task back to ``QUEUED`` (the graceful-stop path). Holder-guarded like
    :func:`finish_task`.

    ``delay`` persists a DB-clock eligibility boundary rather than sleeping in one worker process.
    This lets the worker drain unrelated work while recovery waits and survives process restarts.

    ``uncount_attempt`` takes back the attempt the claim counted, for a claim that never ran its
    handler (the work lease was held elsewhere) — ``attempts`` is read as a retry budget.
    """

    delay_seconds = 0.0 if delay is None else delay.total_seconds()
    if delay_seconds < 0:
        raise ValueError("requeue delay cannot be negative")
    row = (
        await conn.execute(
            _REQUEUE_SQL,
            {
                "task_id": task_id,
                "worker_id": worker_id,
                "delay_seconds": delay_seconds,
                "uncount": int(uncount_attempt),
            },
        )
    ).first()
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


async def cancel_work_tasks(
    conn: AsyncConnection,
    *,
    kind: FleetTaskKind,
    work_id: WorkId,
    result_ref: dict[str, JsonValue] | None = None,
) -> int:
    """Atomically terminalize queued/claimed/suspended work so it cannot be reclaimed.

    An in-flight holder is fenced because its later holder-guarded ``finish`` sees ``done`` and
    updates zero rows. A durable external-wait marker is already ``done`` so it is rewritten only
    when its recorded outcome is ``waiting_external``. Domain state must be cancelled in the same
    transaction by the caller.
    """

    result = await conn.execute(
        _CANCEL_WORK_SQL,
        {
            "kind": kind.value,
            "work_id": work_id,
            "result_ref": serialize_value_json(result_ref or {"outcome": "cancelled"}),
        },
    )
    return result.rowcount or 0


async def reoffer_governed_partial_task(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    dedup_key: str,
) -> bool:
    """Explicitly reoffer one scheduler-parked account after quarantine release."""

    row = (
        await conn.execute(
            _REOFFER_GOVERNED_PARTIAL_SQL,
            {"project_run_id": project_run_id, "dedup_key": dedup_key},
        )
    ).first()
    return row is not None


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
        only_if_work_idle: bool = False,
    ) -> bool: ...

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        project_run_id: ProjectRunId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
        capabilities: tuple[TaskCapability, ...] = (),
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

    async def requeue(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        delay: timedelta | None = None,
        uncount_attempt: bool = False,
    ) -> bool: ...

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
        only_if_work_idle: bool = False,
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
                only_if_work_idle=only_if_work_idle,
            )

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        project_run_id: ProjectRunId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
        capabilities: tuple[TaskCapability, ...] = (),
    ) -> FleetTaskRow | None:
        async with transaction() as conn:
            return await claim_next_task(
                conn,
                kind=kind,
                worker_id=worker_id,
                project_run_id=project_run_id,
                stale_after=stale_after,
                capabilities=capabilities,
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

    async def requeue(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        delay: timedelta | None = None,
        uncount_attempt: bool = False,
    ) -> bool:
        async with transaction() as conn:
            return await requeue_task(
                conn,
                task_id=task_id,
                worker_id=worker_id,
                delay=delay,
                uncount_attempt=uncount_attempt,
            )

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
        only_if_work_idle: bool = False,
    ) -> bool: ...

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
        capabilities: tuple[TaskCapability, ...] = (),
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

    async def requeue(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        delay: timedelta | None = None,
        uncount_attempt: bool = False,
    ) -> bool: ...


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
        only_if_work_idle: bool = False,
    ) -> bool:
        return await self._queue.enqueue(
            kind=kind,
            project_run_id=ProjectRunId(work_id),
            dedup_key=dedup_key,
            priority=priority,
            payload=payload,
            reopen_terminal=reopen_terminal,
            only_if_work_idle=only_if_work_idle,
        )

    async def claim_next(
        self,
        *,
        kind: FleetTaskKind,
        worker_id: str,
        work_id: WorkId | None = None,
        stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
        capabilities: tuple[TaskCapability, ...] = (),
    ) -> WorkTaskRow | None:
        row = await self._queue.claim_next(
            kind=kind,
            worker_id=worker_id,
            project_run_id=ProjectRunId(work_id) if work_id is not None else None,
            stale_after=stale_after,
            capabilities=capabilities,
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

    async def requeue(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        delay: timedelta | None = None,
        uncount_attempt: bool = False,
    ) -> bool:
        return await self._queue.requeue(
            task_id=task_id,
            worker_id=worker_id,
            delay=delay,
            uncount_attempt=uncount_attempt,
        )


__all__ = [
    "DEFAULT_TASK_STALE_AFTER",
    "DbTaskQueue",
    "DbWorkQueue",
    "FleetTaskRow",
    "TaskCapability",
    "TaskQueue",
    "WorkQueue",
    "WorkTaskRow",
    "claim_next_task",
    "cancel_work_tasks",
    "enqueue_task",
    "finish_task",
    "get_task",
    "list_tasks",
    "payload_is_claimable",
    "requeue_failed_tasks",
    "reoffer_governed_partial_task",
    "requeue_task",
    "touch_task",
]
