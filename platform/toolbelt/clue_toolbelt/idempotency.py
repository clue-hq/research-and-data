"""A9 idempotency — the store seam + its Db impl over ``tool_invocation`` (D6 / S4).

An invocation may carry an ``idempotency_key`` (the A9 header at HTTP; slice 3). Dedup is scoped
``(workspace_id, idempotency_key)`` — the **same** key in a different workspace is a clean miss, so
one tenant can never replay or conflict against another's invocation. The runner consults this store
*before* executing and reserves the slot up-front:

* **no row (or a TTL-expired one)** → :meth:`reserve` a ``pending`` row, execute, then
  :meth:`complete` it with the response;
* **a live ``completed`` row** with the same ``tool_name`` + body hash → replay the stored response;
* **a live row** with a *different* body hash **or** a *different* ``tool_name`` →
  :class:`~clue_toolbelt.errors.IdempotencyConflict` (the pause/resume same-body trap dies via the
  ``tool_name`` check);
* **a live ``pending`` row** → a same-key invocation is in flight (a concurrent double-submit) →
  ``IdempotencyConflict`` with a ``pending`` reason;
* **a failed invoke** → :meth:`release` deletes the ``pending`` reservation (a
  ``PreconditionFailed`` or a raising body must never be cached).

The record is keyed on ``(workspace_id, idempotency_key)`` and stores ``body_sha256`` (the
canonicalised request-body hash — how "same body" is decided), the ``tool_name``, a ``status``
(``pending``|``completed``), and the JSON response. TTL is a *read-time* window (``created_at``
within ``ttl_s``): a stale row is treated as absent and taken over by the next :meth:`reserve`, so a
reused key after its TTL is a fresh invocation, not a conflict.

Purity (D5): this module imports only ``clue_core`` (JSON helpers) / ``clue_db`` (the
``ConnFactory`` seam) — never a research/durable idempotency ledger (that is a *different*,
domain-scoped idempotency at the M7.4 layer; A9 is additive over it, D6)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable

from sqlalchemy import text

from clue_core import canonical_json, decode_jsonb
from clue_db import ConnFactory, transaction

__all__ = [
    "body_sha256",
    "InvocationStatus",
    "StoredInvocation",
    "IdempotencyStore",
    "DbIdempotencyStore",
]

InvocationStatus = Literal["pending", "completed"]


def body_sha256(body: Mapping[str, Any]) -> str:
    """The canonical SHA-256 of a request body — the D6 "same body" key. Canonicalised
    (sorted-keys, separator-stable) via :func:`clue_core.canonical_json` so two equal bodies with
    different key order or whitespace hash identically (a retry is recognised regardless of
    serialisation)."""
    return hashlib.sha256(canonical_json(dict(body)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredInvocation:
    """One recorded invocation, scoped ``(workspace_id, idempotency_key)``: the request
    ``body_sha256``, the ``tool_name``, the ``status`` (``pending`` reservation vs ``completed``),
    the JSON response (a ``ToolResult`` dump — ``None`` while pending), and when it was recorded."""

    workspace_id: str
    idempotency_key: str
    body_sha256: str
    tool_name: str
    status: InvocationStatus
    response_json: dict[str, Any] | None
    created_at: datetime


@runtime_checkable
class IdempotencyStore(Protocol):
    """The A9 persistence seam the runner consults. A test injects an in-memory fake; production
    binds :class:`DbIdempotencyStore`."""

    async def lookup(
        self, workspace_id: str, idempotency_key: str, *, ttl_s: float, now: datetime | None = None
    ) -> StoredInvocation | None:
        """The live (within ``ttl_s``) record for ``(workspace_id, idempotency_key)``, or ``None``
        if absent or expired. An expired row is reported as ``None`` so a reused key past its TTL
        re-executes; a key present only in *another* workspace is likewise ``None`` (a clean
        miss)."""
        ...

    async def reserve(
        self,
        workspace_id: str,
        idempotency_key: str,
        *,
        tool_name: str,
        body_sha256: str,
        ttl_s: float,
        now: datetime | None = None,
    ) -> bool:
        """Claim the ``(workspace_id, idempotency_key)`` slot with a ``pending`` row before
        executing. Returns ``True`` if this caller won the reservation (the row was absent or
        TTL-expired), ``False`` if a live row already holds it (the caller re-looks-up to
        replay/conflict per the rules)."""
        ...

    async def complete(
        self,
        workspace_id: str,
        idempotency_key: str,
        *,
        response_json: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        """Mark this caller's ``pending`` reservation ``completed`` with its response."""
        ...

    async def release(self, workspace_id: str, idempotency_key: str) -> None:
        """Delete this caller's ``pending`` reservation (a failed invoke — never cache a failure).
        Only a ``pending`` row is removed; a ``completed`` row from a race is left intact."""
        ...


_LOOKUP_SQL = text(
    """
    SELECT workspace_id, idempotency_key, body_sha256, tool_name, status, response_json, created_at
    FROM tool_invocation
    WHERE workspace_id = :ws AND idempotency_key = :key
    """
)

# Reservation upsert (S4): insert a `pending` row; on conflict take over ONLY a TTL-expired row
# (created_at <= cutoff). A live row (pending or completed) fails the WHERE → no row returned → the
# caller lost the reservation and re-looks-up. RETURNING a row means we won (fresh insert OR expired
# takeover); Postgres evaluates the ON CONFLICT ... WHERE against the existing row.
_RESERVE_SQL = text(
    """
    INSERT INTO tool_invocation
        (workspace_id, idempotency_key, body_sha256, tool_name, status, response_json, created_at)
    VALUES (:ws, :key, :body_sha256, :tool_name, 'pending', NULL, :created_at)
    ON CONFLICT (workspace_id, idempotency_key) DO UPDATE
        SET body_sha256   = EXCLUDED.body_sha256,
            tool_name     = EXCLUDED.tool_name,
            status        = 'pending',
            response_json = NULL,
            created_at    = EXCLUDED.created_at
        WHERE tool_invocation.created_at <= :cutoff
    RETURNING idempotency_key
    """
)

_COMPLETE_SQL = text(
    """
    UPDATE tool_invocation
        SET status = 'completed', response_json = CAST(:response_json AS jsonb)
    WHERE workspace_id = :ws AND idempotency_key = :key
    """
)

# Only a pending reservation is released (a failed invoke); a completed row from a race is left.
_RELEASE_SQL = text(
    """
    DELETE FROM tool_invocation
    WHERE workspace_id = :ws AND idempotency_key = :key AND status = 'pending'
    """
)


class DbIdempotencyStore:
    """The Postgres A9 store over ``tool_invocation``, using an injected
    :data:`~clue_db.ConnFactory` (defaults to :func:`clue_db.transaction`) so tests can bind a
    savepoint-scoped factory."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def lookup(
        self, workspace_id: str, idempotency_key: str, *, ttl_s: float, now: datetime | None = None
    ) -> StoredInvocation | None:
        moment = now if now is not None else datetime.now(UTC)
        async with self._conn_factory() as conn:
            row = (
                (await conn.execute(_LOOKUP_SQL, {"ws": workspace_id, "key": idempotency_key}))
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        created_at = _as_aware(row["created_at"])
        # TTL is a read-time window: a row older than ttl_s is reported absent (re-executable).
        if moment - created_at > timedelta(seconds=ttl_s):
            return None
        raw = row["response_json"]
        decoded = decode_jsonb(raw) if raw is not None else None
        return StoredInvocation(
            workspace_id=row["workspace_id"],
            idempotency_key=row["idempotency_key"],
            body_sha256=row["body_sha256"],
            tool_name=row["tool_name"],
            status=row["status"],
            response_json=decoded if isinstance(decoded, dict) else None,
            created_at=created_at,
        )

    async def reserve(
        self,
        workspace_id: str,
        idempotency_key: str,
        *,
        tool_name: str,
        body_sha256: str,
        ttl_s: float,
        now: datetime | None = None,
    ) -> bool:
        moment = now if now is not None else datetime.now(UTC)
        cutoff = moment - timedelta(seconds=ttl_s)
        async with self._conn_factory() as conn:
            row = (
                await conn.execute(
                    _RESERVE_SQL,
                    {
                        "ws": workspace_id,
                        "key": idempotency_key,
                        "body_sha256": body_sha256,
                        "tool_name": tool_name,
                        "created_at": moment,
                        "cutoff": cutoff,
                    },
                )
            ).one_or_none()
        return row is not None

    async def complete(
        self,
        workspace_id: str,
        idempotency_key: str,
        *,
        response_json: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(
                _COMPLETE_SQL,
                {
                    "ws": workspace_id,
                    "key": idempotency_key,
                    "response_json": canonical_json(response_json),
                },
            )

    async def release(self, workspace_id: str, idempotency_key: str) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(_RELEASE_SQL, {"ws": workspace_id, "key": idempotency_key})


def _as_aware(moment: datetime) -> datetime:
    """Treat a naive timestamp (e.g. a driver that drops tzinfo) as UTC, so the TTL arithmetic never
    compares an aware ``now`` against a naive ``created_at``."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
