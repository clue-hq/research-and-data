"""The per-run driver lease (PB-B1) — at most one worker drives a campaign run at a time.

M7.3's state machine *documents* single-driver-per-run as a precondition ("a per-run driver lock
that would enforce this … is left to the scheduler/ops layer" — ``durable/campaign.py``); this
module is that layer. One ``run_lease`` row per driven run: a worker **acquires** it before
driving, **renews** it on a heartbeat while driving, and **releases** it when the drive ends. A
kill -9'd driver simply stops renewing; the lease expires by TTL and the next worker's acquire
atomically re-owns it — takeover is possible *only* after expiry (the exit-gate property).

All clock reads are database ``now()`` (the M7.4 ledger convention — no cross-worker NTP skew),
and every mutation after acquire is **holder-guarded** (``WHERE worker_id = :me``): a fenced-out
zombie's renew/release matches zero rows instead of stealing the lease back. Fencing is
cooperative — a driver that loses its lease aborts its drive at the next phase boundary; the
residual zombie-mid-phase window is governed by the account-step ledger and the M2.4 entity
locks, exactly as on today's resume path (spec §2.3).

Repository shape mirrors ``durable/campaign_run.py``: module-level ``text(...)`` + ``async def``
helpers over an :class:`~sqlalchemy.ext.asyncio.AsyncConnection`; :class:`DbLeaseStore` wraps
them in ``db.transaction()`` behind the :class:`LeaseStore` seam so the worker loop is testable
on an in-memory store (conventions §2).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import CampaignRunId, UtcDatetime
from clue_db import transaction

# Default driver-lease TTL. Generous enough that a healthy heartbeat (a fraction of this — see
# ``Settings.fleet_heartbeat_interval_s``) never lets a live drive lapse, short enough that a
# killed driver's run is re-drivable quickly. Policy-as-data: the worker passes the configured
# value; this is only the seam default.
DEFAULT_LEASE_TTL = timedelta(seconds=30)


class RunLeaseRow(BaseModel):
    """One ``run_lease`` row (PB-B1). ``live`` is computed against database ``now()`` at read
    time — ``True`` while the lease is held (``expires_at > now()``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_run_id: CampaignRunId
    worker_id: str
    acquired_at: UtcDatetime
    renewed_at: UtcDatetime
    expires_at: UtcDatetime
    live: bool


# Atomic acquire: insert if absent, else re-own ONLY an expired row — or re-enter one this worker
# already holds (an idempotent re-acquire extends it). A live foreign lease leaves the predicate
# false → no row returned → not acquired. Same single-upsert atomicity as the M7.4 ledger claim:
# two racing acquirers can never both get a returned row.
_ACQUIRE_SQL = text(
    """
    INSERT INTO run_lease (campaign_run_id, worker_id, acquired_at, renewed_at, expires_at)
    VALUES (:campaign_run_id, :worker_id, now(), now(), now() + CAST(:ttl AS interval))
    ON CONFLICT (campaign_run_id) DO UPDATE
        SET worker_id = :worker_id,
            acquired_at = now(),
            renewed_at = now(),
            expires_at = now() + CAST(:ttl AS interval)
        WHERE run_lease.expires_at <= now()
           OR run_lease.worker_id = :worker_id
    RETURNING campaign_run_id
    """
)

# Holder-guarded renew: only the current holder of a still-live lease may extend it. An expired
# lease is NOT renewable even by its old holder — once past ``expires_at`` a takeover may already
# have happened (or be racing this statement), so the old driver must treat renewal failure as
# "lease lost" and abort its drive.
_RENEW_SQL = text(
    """
    UPDATE run_lease
    SET renewed_at = now(), expires_at = now() + CAST(:ttl AS interval)
    WHERE campaign_run_id = :campaign_run_id
      AND worker_id = :worker_id
      AND expires_at > now()
    RETURNING campaign_run_id
    """
)

# Holder-guarded release; a lost lease (re-owned by another worker) matches zero rows — a no-op.
_RELEASE_SQL = text(
    """
    DELETE FROM run_lease
    WHERE campaign_run_id = :campaign_run_id AND worker_id = :worker_id
    """
)

_GET_SQL = text(
    """
    SELECT campaign_run_id, worker_id, acquired_at, renewed_at, expires_at,
           (expires_at > now()) AS live
    FROM run_lease
    WHERE campaign_run_id = :campaign_run_id
    """
)


async def acquire_run_lease(
    conn: AsyncConnection,
    *,
    campaign_run_id: CampaignRunId,
    worker_id: str,
    ttl: timedelta = DEFAULT_LEASE_TTL,
) -> bool:
    """Atomically acquire (or re-enter) the driver lease for ``campaign_run_id``.

    ``True`` when this worker now holds the lease (fresh, re-owned-after-expiry, or its own
    re-acquire); ``False`` when another worker holds it live — the caller must not drive."""
    row = (
        await conn.execute(
            _ACQUIRE_SQL,
            {"campaign_run_id": campaign_run_id, "worker_id": worker_id, "ttl": ttl},
        )
    ).first()
    return row is not None


async def renew_run_lease(
    conn: AsyncConnection,
    *,
    campaign_run_id: CampaignRunId,
    worker_id: str,
    ttl: timedelta = DEFAULT_LEASE_TTL,
) -> bool:
    """Extend a still-live lease this worker holds. ``False`` = the lease was lost (expired or
    taken over) — the driver must abort its drive at the next boundary."""
    row = (
        await conn.execute(
            _RENEW_SQL,
            {"campaign_run_id": campaign_run_id, "worker_id": worker_id, "ttl": ttl},
        )
    ).first()
    return row is not None


async def release_run_lease(
    conn: AsyncConnection, *, campaign_run_id: CampaignRunId, worker_id: str
) -> None:
    """Release the lease if this worker still holds it (holder-guarded; a lost lease is a
    no-op)."""
    await conn.execute(_RELEASE_SQL, {"campaign_run_id": campaign_run_id, "worker_id": worker_id})


async def get_run_lease(
    conn: AsyncConnection, campaign_run_id: CampaignRunId
) -> RunLeaseRow | None:
    """Read the lease row (with its DB-clock ``live`` verdict), or ``None`` if never leased."""
    row = (
        (await conn.execute(_GET_SQL, {"campaign_run_id": campaign_run_id}))
        .mappings()
        .one_or_none()
    )
    return RunLeaseRow.model_validate(dict(row)) if row is not None else None


# --- the persistence seam --------------------------------------------------------------------


@runtime_checkable
class LeaseStore(Protocol):
    """The seam the worker holds/renews leases through (PB-B1). Abstracting persistence keeps the
    drive loop testable on an in-memory store; the production implementation is
    :class:`DbLeaseStore` (conventions §2)."""

    async def acquire(
        self, *, campaign_run_id: CampaignRunId, worker_id: str, ttl: timedelta
    ) -> bool: ...

    async def renew(
        self, *, campaign_run_id: CampaignRunId, worker_id: str, ttl: timedelta
    ) -> bool: ...

    async def release(self, *, campaign_run_id: CampaignRunId, worker_id: str) -> None: ...

    async def get(self, campaign_run_id: CampaignRunId) -> RunLeaseRow | None: ...


class DbLeaseStore:
    """The Postgres :class:`LeaseStore`. Each method runs in its own ``db.transaction()``
    (mirroring :class:`~clue_research.durable.DbIdempotencyStore`) — a lease operation is a
    single atomic statement, never part of a larger unit of work."""

    async def acquire(
        self, *, campaign_run_id: CampaignRunId, worker_id: str, ttl: timedelta
    ) -> bool:
        async with transaction() as conn:
            return await acquire_run_lease(
                conn, campaign_run_id=campaign_run_id, worker_id=worker_id, ttl=ttl
            )

    async def renew(
        self, *, campaign_run_id: CampaignRunId, worker_id: str, ttl: timedelta
    ) -> bool:
        async with transaction() as conn:
            return await renew_run_lease(
                conn, campaign_run_id=campaign_run_id, worker_id=worker_id, ttl=ttl
            )

    async def release(self, *, campaign_run_id: CampaignRunId, worker_id: str) -> None:
        async with transaction() as conn:
            await release_run_lease(conn, campaign_run_id=campaign_run_id, worker_id=worker_id)

    async def get(self, campaign_run_id: CampaignRunId) -> RunLeaseRow | None:
        async with transaction() as conn:
            return await get_run_lease(conn, campaign_run_id)
