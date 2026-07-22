"""A9 idempotency — the store seam + its Db impl over ``tool_invocation`` (D6).

An invocation may carry an ``idempotency_key`` (the A9 header at HTTP; slice 3). The runner consults
this store *before* executing:

* **no row (or an expired one)** → execute, then :meth:`record` the response;
* **a live row (within TTL) with the same body hash** → replay the stored response (no re-exec);
* **a live row with a *different* body hash** → :class:`~clue_toolbelt.errors.IdempotencyConflict`.

The record is keyed on ``idempotency_key`` (unique) and stores ``body_sha256`` (the canonicalised
request-body hash — how "same body" is decided) + the JSON response. TTL is a *read-time* window
(``created_at`` within ``ttl_s``): a stale row is treated as absent and overwritten on the next
:meth:`record`, so a reused key after its TTL is a fresh invocation, not a conflict.

Purity (D5): this module imports only ``clue_core`` (JSON helpers) / ``clue_db`` (the
``ConnFactory`` seam) — never a research/durable idempotency ledger (that is a *different*,
domain-scoped idempotency at the M7.4 layer; A9 is additive over it, D6)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import text

from clue_core import canonical_json, decode_jsonb
from clue_db import ConnFactory, transaction

__all__ = [
    "body_sha256",
    "StoredInvocation",
    "IdempotencyStore",
    "DbIdempotencyStore",
]


def body_sha256(body: Mapping[str, Any]) -> str:
    """The canonical SHA-256 of a request body — the D6 "same body" key. Canonicalised
    (sorted-keys, separator-stable) via :func:`clue_core.canonical_json` so two equal bodies with
    different key order or whitespace hash identically (a retry is recognised regardless of
    serialisation)."""
    return hashlib.sha256(canonical_json(dict(body)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredInvocation:
    """One recorded invocation: the key, the request ``body_sha256``, the ``tool_name``, the JSON
    response (a ``ToolResult`` dump), and when it was recorded."""

    idempotency_key: str
    body_sha256: str
    tool_name: str
    response_json: dict[str, Any]
    created_at: datetime


@runtime_checkable
class IdempotencyStore(Protocol):
    """The A9 persistence seam the runner consults. A test injects an in-memory fake; production
    binds :class:`DbIdempotencyStore`."""

    async def lookup(
        self, idempotency_key: str, *, ttl_s: float, now: datetime | None = None
    ) -> StoredInvocation | None:
        """The live (within ``ttl_s``) record for ``idempotency_key``, or ``None`` if absent or
        expired. An expired row is reported as ``None`` so a reused key past its TTL re-executes."""
        ...

    async def record(self, entry: StoredInvocation) -> None:
        """Persist ``entry`` (upsert on ``idempotency_key`` — a re-executed expired key overwrites
        its stale row)."""
        ...


_LOOKUP_SQL = text(
    """
    SELECT idempotency_key, body_sha256, tool_name, response_json, created_at
    FROM tool_invocation
    WHERE idempotency_key = :key
    """
)

# Upsert: a fresh key inserts; a reused expired key overwrites its stale row (the runner only calls
# record on the EXECUTE path, i.e. after lookup reported None — so an overwrite is always of an
# expired/absent record, never of a live one it should have replayed).
_RECORD_SQL = text(
    """
    INSERT INTO tool_invocation (idempotency_key, body_sha256, tool_name, response_json, created_at)
    VALUES (:key, :body_sha256, :tool_name, CAST(:response_json AS jsonb), :created_at)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET body_sha256   = EXCLUDED.body_sha256,
            tool_name     = EXCLUDED.tool_name,
            response_json = EXCLUDED.response_json,
            created_at    = EXCLUDED.created_at
    """
)


class DbIdempotencyStore:
    """The Postgres A9 store over ``tool_invocation``, using an injected
    :data:`~clue_db.ConnFactory` (defaults to :func:`clue_db.transaction`) so tests can bind a
    savepoint-scoped factory."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def lookup(
        self, idempotency_key: str, *, ttl_s: float, now: datetime | None = None
    ) -> StoredInvocation | None:
        moment = now if now is not None else datetime.now(UTC)
        async with self._conn_factory() as conn:
            row = (
                (await conn.execute(_LOOKUP_SQL, {"key": idempotency_key})).mappings().one_or_none()
            )
        if row is None:
            return None
        created_at = _as_aware(row["created_at"])
        # TTL is a read-time window: a row older than ttl_s is reported absent (re-executable).
        if moment - created_at > timedelta(seconds=ttl_s):
            return None
        decoded = decode_jsonb(row["response_json"])
        return StoredInvocation(
            idempotency_key=row["idempotency_key"],
            body_sha256=row["body_sha256"],
            tool_name=row["tool_name"],
            response_json=decoded if isinstance(decoded, dict) else {},
            created_at=created_at,
        )

    async def record(self, entry: StoredInvocation) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(
                _RECORD_SQL,
                {
                    "key": entry.idempotency_key,
                    "body_sha256": entry.body_sha256,
                    "tool_name": entry.tool_name,
                    "response_json": canonical_json(entry.response_json),
                    "created_at": _as_aware(entry.created_at),
                },
            )


def _as_aware(moment: datetime) -> datetime:
    """Treat a naive timestamp (e.g. a driver that drops tzinfo) as UTC, so the TTL arithmetic never
    compares an aware ``now`` against a naive ``created_at``."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
