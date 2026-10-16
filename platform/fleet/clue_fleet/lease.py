"""Generic fleet work leases with monotone takeover generations.

``work_lease`` is fleet-private state.  A generation changes only when an expired lease is
re-owned, giving execution-plane writers a hard fence in addition to the worker's supervised
heartbeat.  The project-run functions at the bottom are compatibility adapters for PB-B1 callers.

**Generations never repeat** (site-turn durability, 2026-10-16). Releasing a lease ends it now and
KEEPS its row, so the next acquire — by anyone, the releasing worker included — is
``generation + 1``. It used to DELETE the row, which restarted the next holder at generation 1,
the very number the previous holder had: no fence could tell the old attempt from the new one
(the same reset broke research resumes on 2026-08-19, which research works around with the task
attempt count in its turn ids; that workaround keeps working). A row is removed only by
:func:`prune_released_work_leases`, long after its work stopped.

**A lapsed lease nobody took is taken back by its holder.** :func:`renew_work_lease` lands
whenever the row still names this worker and this generation, even past ``expires_at``: a live
worker that missed beats while nobody else claimed the work simply carries on, at the same
generation. Once someone else has acquired it the row names another worker and a higher
generation, and the renew fails exactly as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NewType, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId, UtcDatetime
from clue_db import transaction

WorkId = NewType("WorkId", UUID)
LeaseGeneration = NewType("LeaseGeneration", int)
DEFAULT_LEASE_TTL = timedelta(seconds=30)


class WorkLeaseRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    work_id: UUID
    worker_id: str
    generation: int
    acquired_at: UtcDatetime
    renewed_at: UtcDatetime
    expires_at: UtcDatetime
    live: bool


class RunLeaseRow(BaseModel):
    """PB-B1 compatibility projection of a generic work lease."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    worker_id: str
    generation: int = 1
    acquired_at: UtcDatetime
    renewed_at: UtcDatetime
    expires_at: UtcDatetime
    live: bool


_ACQUIRE_SQL = text(
    """
    INSERT INTO work_lease
        (work_id, worker_id, generation, acquired_at, renewed_at, expires_at)
    VALUES (:work_id, :worker_id, 1, now(), now(), now() + CAST(:ttl AS interval))
    ON CONFLICT (work_id) DO UPDATE
        SET worker_id = :worker_id,
            generation = CASE
                WHEN work_lease.expires_at <= now() THEN work_lease.generation + 1
                ELSE work_lease.generation
            END,
            acquired_at = CASE
                WHEN work_lease.expires_at <= now() THEN now()
                ELSE work_lease.acquired_at
            END,
            renewed_at = now(),
            expires_at = now() + CAST(:ttl AS interval)
        WHERE work_lease.expires_at <= now()
           OR work_lease.worker_id = :worker_id
    RETURNING work_id, worker_id, generation, acquired_at, renewed_at, expires_at,
              (expires_at > now()) AS live
    """
)

_RENEW_SQL = text(
    """
    UPDATE work_lease
    SET renewed_at = now(), expires_at = now() + CAST(:ttl AS interval)
    WHERE work_id = :work_id
      AND worker_id = :worker_id
      AND generation = :generation
    RETURNING work_id
    """
)

# Ends the lease now and keeps the row, so the next acquire takes the ``expires_at <= now()``
# branch and moves the generation on. ``LEAST`` keeps an already-lapsed lease's real expiry.
_RELEASE_SQL = text(
    """
    UPDATE work_lease
    SET expires_at = LEAST(expires_at, now())
    WHERE work_id = :work_id AND worker_id = :worker_id AND generation = :generation
    """
)

# Revocation is a fence event: the generation moves on, so the resident holder's renew and every
# domain write that checks ``generation`` fail, and the lease is ended so anyone may acquire next.
_REVOKE_SQL = text(
    """
    UPDATE work_lease
    SET generation = generation + 1, expires_at = LEAST(expires_at, now())
    WHERE work_id = :work_id
    """
)

#: How long an ended lease is kept before :func:`prune_released_work_leases` may remove it.
RELEASED_LEASE_RETENTION = timedelta(days=30)

# A row ended more than ``:keep`` ago whose work has no queued or claimed fleet task. Work that
# can still be driven always has a live task (or a recent lease), so removing these restarts a
# generation only for work idle for a month — which is no worse than every release was before.
_PRUNE_SQL = text(
    """
    DELETE FROM work_lease AS lease
    WHERE lease.expires_at < now() - CAST(:keep AS interval)
      AND NOT EXISTS (
            SELECT 1 FROM fleet_task AS task
            WHERE task.work_id = lease.work_id
              AND task.status IN ('queued', 'claimed')
          )
    """
)

_GET_SQL = text(
    """
    SELECT work_id, worker_id, generation, acquired_at, renewed_at, expires_at,
           (expires_at > now()) AS live
    FROM work_lease
    WHERE work_id = :work_id
    """
)


# Does the row still name this worker and generation? Locked FOR SHARE until the caller's
# transaction ends, so an acquire (an UPDATE of this row) cannot move it under a write the caller is
# fencing with it. Expiry is deliberately not checked: a lapsed lease nobody took is still its
# holder's (the renew rule above).
_HOLD_SQL = text(
    """
    SELECT generation FROM work_lease
    WHERE work_id = :work_id AND worker_id = :worker_id AND generation = :generation
    FOR SHARE
    """
)


async def acquire_work_lease(
    conn: AsyncConnection,
    *,
    work_id: WorkId,
    worker_id: str,
    ttl: timedelta = DEFAULT_LEASE_TTL,
) -> WorkLeaseRow | None:
    row = (
        (
            await conn.execute(
                _ACQUIRE_SQL,
                {"work_id": work_id, "worker_id": worker_id, "ttl": ttl},
            )
        )
        .mappings()
        .one_or_none()
    )
    return WorkLeaseRow.model_validate(dict(row)) if row is not None else None


async def renew_work_lease(
    conn: AsyncConnection,
    *,
    work_id: WorkId,
    worker_id: str,
    generation: LeaseGeneration,
    ttl: timedelta = DEFAULT_LEASE_TTL,
) -> bool:
    row = (
        await conn.execute(
            _RENEW_SQL,
            {
                "work_id": work_id,
                "worker_id": worker_id,
                "generation": generation,
                "ttl": ttl,
            },
        )
    ).first()
    return row is not None


async def release_work_lease(
    conn: AsyncConnection,
    *,
    work_id: WorkId,
    worker_id: str,
    generation: LeaseGeneration,
) -> None:
    await conn.execute(
        _RELEASE_SQL,
        {"work_id": work_id, "worker_id": worker_id, "generation": generation},
    )


async def hold_work_lease(
    conn: AsyncConnection,
    *,
    work_id: WorkId,
    worker_id: str,
    generation: LeaseGeneration,
) -> bool:
    """Whether ``worker_id`` still holds ``work_id`` at ``generation``, for a domain write made in
    ``conn``'s transaction (the site turn's fenced save).

    True when the row still names this worker and generation, live or lapsed, and the row is then
    locked ``FOR SHARE`` until that transaction ends; False when anyone else has acquired it
    since, or the row is gone.
    """
    row = (
        await conn.execute(
            _HOLD_SQL, {"work_id": work_id, "worker_id": worker_id, "generation": generation}
        )
    ).first()
    return row is not None


async def revoke_work_lease(conn: AsyncConnection, *, work_id: WorkId) -> None:
    """Take the lease away from whoever holds it (a cancellation), without reusing a number."""
    await conn.execute(_REVOKE_SQL, {"work_id": work_id})


async def prune_released_work_leases(
    conn: AsyncConnection, *, keep: timedelta = RELEASED_LEASE_RETENTION
) -> int:
    """Remove leases ended more than ``keep`` ago whose work has no live fleet task.

    Release keeps every row so generations never repeat; this is what stops them piling up. Run on
    the fleet maintenance clock (``clue_api.fleet_main``). Returns how many rows it removed."""
    outcome = await conn.execute(_PRUNE_SQL, {"keep": keep})
    return int(outcome.rowcount or 0)


#: The ``maintenance_run`` row and advisory-lock key of the fleet-wide lease prune.
WORK_LEASE_PRUNE = "work_lease_prune"
_WORK_LEASE_PRUNE_LOCK = "work-lease-prune"


async def prune_released_work_leases_if_due(
    conn: AsyncConnection,
    *,
    every: timedelta,
    keep: timedelta = RELEASED_LEASE_RETENTION,
    now: datetime | None = None,
) -> int | None:
    """Run :func:`prune_released_work_leases` for the whole fleet when the last run is ``every``
    old — the storage sweep's maintenance clock (``maintenance_run`` + a transaction-scoped
    advisory lock), so one process prunes and a deploy never resets the clock. ``None`` when
    nothing ran (not due, or another process holds the lock), else how many rows were removed."""
    now = now or datetime.now(UTC)
    won = (
        await conn.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": _WORK_LEASE_PRUNE_LOCK},
        )
    ).scalar_one()
    if not won:
        return None
    last = (
        await conn.execute(
            text("SELECT last_run_at FROM maintenance_run WHERE name = :name"),
            {"name": WORK_LEASE_PRUNE},
        )
    ).scalar_one_or_none()
    if last is not None and now - last < every:
        return None
    pruned = await prune_released_work_leases(conn, keep=keep)
    await conn.execute(
        text(
            "INSERT INTO maintenance_run (name, last_run_at) VALUES (:name, :at) "
            "ON CONFLICT (name) DO UPDATE SET last_run_at = EXCLUDED.last_run_at"
        ),
        {"name": WORK_LEASE_PRUNE, "at": now},
    )
    return pruned


async def get_work_lease(conn: AsyncConnection, work_id: WorkId) -> WorkLeaseRow | None:
    row = (await conn.execute(_GET_SQL, {"work_id": work_id})).mappings().one_or_none()
    return WorkLeaseRow.model_validate(dict(row)) if row is not None else None


@runtime_checkable
class WorkLeaseStore(Protocol):
    async def acquire(
        self, *, work_id: WorkId, worker_id: str, ttl: timedelta
    ) -> WorkLeaseRow | None: ...

    async def renew(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        generation: LeaseGeneration,
        ttl: timedelta,
    ) -> bool: ...

    async def release(
        self, *, work_id: WorkId, worker_id: str, generation: LeaseGeneration
    ) -> None: ...

    async def get(self, work_id: WorkId) -> WorkLeaseRow | None: ...


class DbWorkLeaseStore:
    async def acquire(
        self, *, work_id: WorkId, worker_id: str, ttl: timedelta
    ) -> WorkLeaseRow | None:
        async with transaction() as conn:
            return await acquire_work_lease(conn, work_id=work_id, worker_id=worker_id, ttl=ttl)

    async def renew(
        self,
        *,
        work_id: WorkId,
        worker_id: str,
        generation: LeaseGeneration,
        ttl: timedelta,
    ) -> bool:
        async with transaction() as conn:
            return await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id=worker_id,
                generation=generation,
                ttl=ttl,
            )

    async def release(
        self, *, work_id: WorkId, worker_id: str, generation: LeaseGeneration
    ) -> None:
        async with transaction() as conn:
            await release_work_lease(
                conn,
                work_id=work_id,
                worker_id=worker_id,
                generation=generation,
            )

    async def get(self, work_id: WorkId) -> WorkLeaseRow | None:
        async with transaction() as conn:
            return await get_work_lease(conn, work_id)


# -- PB-B1 project-run compatibility ---------------------------------------------------------


async def acquire_run_lease(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    worker_id: str,
    ttl: timedelta = DEFAULT_LEASE_TTL,
) -> bool:
    return (
        await acquire_work_lease(
            conn,
            work_id=WorkId(project_run_id),
            worker_id=worker_id,
            ttl=ttl,
        )
        is not None
    )


async def renew_run_lease(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    worker_id: str,
    ttl: timedelta = DEFAULT_LEASE_TTL,
) -> bool:
    current = await get_work_lease(conn, WorkId(project_run_id))
    if current is None or current.worker_id != worker_id:
        return False
    return await renew_work_lease(
        conn,
        work_id=WorkId(project_run_id),
        worker_id=worker_id,
        generation=LeaseGeneration(current.generation),
        ttl=ttl,
    )


async def release_run_lease(
    conn: AsyncConnection, *, project_run_id: ProjectRunId, worker_id: str
) -> None:
    current = await get_work_lease(conn, WorkId(project_run_id))
    if current is not None:
        await release_work_lease(
            conn,
            work_id=WorkId(project_run_id),
            worker_id=worker_id,
            generation=LeaseGeneration(current.generation),
        )


async def get_run_lease(conn: AsyncConnection, project_run_id: ProjectRunId) -> RunLeaseRow | None:
    row = await get_work_lease(conn, WorkId(project_run_id))
    if row is None:
        return None
    return RunLeaseRow(
        project_run_id=project_run_id,
        worker_id=row.worker_id,
        generation=row.generation,
        acquired_at=row.acquired_at,
        renewed_at=row.renewed_at,
        expires_at=row.expires_at,
        live=row.live,
    )


@runtime_checkable
class LeaseStore(Protocol):
    async def acquire(
        self, *, project_run_id: ProjectRunId, worker_id: str, ttl: timedelta
    ) -> bool: ...

    async def renew(
        self, *, project_run_id: ProjectRunId, worker_id: str, ttl: timedelta
    ) -> bool: ...

    async def release(self, *, project_run_id: ProjectRunId, worker_id: str) -> None: ...

    async def get(self, project_run_id: ProjectRunId) -> RunLeaseRow | None: ...


class DbLeaseStore:
    async def acquire(
        self, *, project_run_id: ProjectRunId, worker_id: str, ttl: timedelta
    ) -> bool:
        async with transaction() as conn:
            return await acquire_run_lease(
                conn, project_run_id=project_run_id, worker_id=worker_id, ttl=ttl
            )

    async def renew(self, *, project_run_id: ProjectRunId, worker_id: str, ttl: timedelta) -> bool:
        async with transaction() as conn:
            return await renew_run_lease(
                conn, project_run_id=project_run_id, worker_id=worker_id, ttl=ttl
            )

    async def release(self, *, project_run_id: ProjectRunId, worker_id: str) -> None:
        async with transaction() as conn:
            await release_run_lease(conn, project_run_id=project_run_id, worker_id=worker_id)

    async def get(self, project_run_id: ProjectRunId) -> RunLeaseRow | None:
        async with transaction() as conn:
            return await get_run_lease(conn, project_run_id)


__all__ = [
    "DEFAULT_LEASE_TTL",
    "DbLeaseStore",
    "DbWorkLeaseStore",
    "LeaseGeneration",
    "LeaseStore",
    "RELEASED_LEASE_RETENTION",
    "RunLeaseRow",
    "WORK_LEASE_PRUNE",
    "WorkId",
    "WorkLeaseRow",
    "WorkLeaseStore",
    "acquire_run_lease",
    "acquire_work_lease",
    "get_run_lease",
    "get_work_lease",
    "prune_released_work_leases",
    "prune_released_work_leases_if_due",
    "release_run_lease",
    "release_work_lease",
    "renew_run_lease",
    "renew_work_lease",
    "revoke_work_lease",
]
