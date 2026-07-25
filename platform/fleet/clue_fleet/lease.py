"""Generic fleet work leases with monotone takeover generations.

``work_lease`` is fleet-private state.  A generation changes only when an expired lease is
re-owned, giving execution-plane writers a hard fence in addition to the worker's supervised
heartbeat.  The project-run functions at the bottom are compatibility adapters for PB-B1 callers.
"""

from __future__ import annotations

from datetime import timedelta
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
      AND expires_at > now()
    RETURNING work_id
    """
)

_RELEASE_SQL = text(
    """
    DELETE FROM work_lease
    WHERE work_id = :work_id AND worker_id = :worker_id AND generation = :generation
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
    "RunLeaseRow",
    "WorkId",
    "WorkLeaseRow",
    "WorkLeaseStore",
    "acquire_run_lease",
    "acquire_work_lease",
    "get_run_lease",
    "get_work_lease",
    "release_run_lease",
    "release_work_lease",
    "renew_run_lease",
    "renew_work_lease",
]
