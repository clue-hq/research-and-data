"""Single-use SSE ``stream_token`` store (PB-B4 slice 3, D8) — a composition-root write surface.

The SSE endpoint (``GET …/events``) is opened with a one-shot token a consumer mints first. The
token authorises *opening* a stream exactly once: :func:`consume_stream_token` stamps ``used_at``
atomically (``… WHERE used_at IS NULL AND expires_at > now() RETURNING``), so a second presentation
finds no live row and is refused. ``EventSource`` reconnect re-mints (the ``Last-Event-ID`` cursor
carries replay state across connects independently of the token, so single-use never breaks
gapless reconnect — the client just mints a fresh token per connect).

**Why here, not in ``clue_projections``.** Minting and consuming are *writes*; the read-only
projections package cannot own them (that would break its MVCC-only discipline). The token store is
composition-root machinery (SSE transport auth), so it lives in ``clue_api`` alongside the SSE app.
Tenant-scoped: a token is consumable only in the ``workspace_id`` it was minted for.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId

_MINT_SQL = text(
    """
    INSERT INTO stream_token (workspace_id, run_id, expires_at)
    VALUES (:workspace_id, :run_id, now() + make_interval(secs => :ttl_s))
    RETURNING token
    """
)

# Single-use consume: stamp used_at atomically only for a live, unused, unexpired, same-tenant,
# same-run row. A second use (used_at already set), an expired token, a cross-tenant token, or a
# token minted for a DIFFERENT run returns no row (run-bound: a run-scoped token opens only the
# stream it was minted for; a NULL-run token is workspace-wide by design).
_CONSUME_SQL = text(
    """
    UPDATE stream_token
    SET used_at = now()
    WHERE token = :token
      AND workspace_id = :workspace_id
      AND used_at IS NULL
      AND expires_at > now()
      AND (run_id IS NULL OR run_id = :run_id)
    RETURNING token
    """
)


#: The FI Lane D D3 turn-stream pair. Same table, same single-use semantics, a **different scope
#: column** (migration ``98a5ddafa21b`` adds ``turn_id`` plus a CHECK that at most one of
#: ``run_id``/``turn_id`` is set). Carrying a turn id in the ``run_id`` column would have been one
#: fewer migration and a permanent lie to every future reader of this table.
_MINT_TURN_SQL = text(
    """
    INSERT INTO stream_token (workspace_id, turn_id, expires_at)
    VALUES (:workspace_id, :turn_id, now() + make_interval(secs => :ttl_s))
    RETURNING token
    """
)

_CONSUME_TURN_SQL = text(
    """
    UPDATE stream_token
    SET used_at = now()
    WHERE token = :token
      AND workspace_id = :workspace_id
      AND used_at IS NULL
      AND expires_at > now()
      AND turn_id = :turn_id
    RETURNING token
    """
)


async def mint_turn_stream_token(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
    ttl_s: float,
) -> UUID:
    """Mint a single-use token that opens **one turn's** stream, once, within ``ttl_s``.

    Lane B contract §5.5 in one function: an already-authenticated request mints a short-lived,
    single-use, principal-scoped, workspace-scoped, turn-scoped token; no bearer credential ever
    travels in a URL, and the token's expiry or replay cannot extend anybody's domain authority —
    it authorises *opening a stream*, and the stream serves only rows of the workspace and turn the
    token names.
    """

    token = (
        await conn.execute(
            _MINT_TURN_SQL,
            {"workspace_id": workspace_id, "turn_id": turn_id, "ttl_s": ttl_s},
        )
    ).scalar_one()
    return UUID(str(token))


async def consume_turn_stream_token(
    conn: AsyncConnection, *, token: UUID, workspace_id: str, turn_id: UUID
) -> bool:
    """Atomically consume a turn-stream token: ``True`` iff live, this tenant's, and this turn's.

    ``False`` — indistinguishably — for a used, expired, cross-tenant, wrong-turn, run-scoped, or
    unknown token, so a probe learns nothing about which of those it was. Reconnect re-mints; the
    ``Last-Event-ID`` cursor carries replay state independently, so single-use never costs a
    gapless reconnect.
    """

    row = (
        await conn.execute(
            _CONSUME_TURN_SQL,
            {"token": token, "workspace_id": workspace_id, "turn_id": turn_id},
        )
    ).one_or_none()
    return row is not None


async def mint_stream_token(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: ProjectRunId | None,
    ttl_s: float,
) -> UUID:
    """Mint a single-use stream token for ``workspace_id`` (optionally run-scoped), expiring
    ``ttl_s`` seconds from now. Returns the opaque token the consumer presents to open a stream."""
    token = (
        await conn.execute(
            _MINT_SQL,
            {"workspace_id": workspace_id, "run_id": run_id, "ttl_s": ttl_s},
        )
    ).scalar_one()
    return UUID(str(token))


async def consume_stream_token(
    conn: AsyncConnection, *, token: UUID, workspace_id: str, run_id: ProjectRunId | None = None
) -> bool:
    """Atomically consume ``token`` for ``workspace_id`` on ``run_id``'s stream: ``True`` iff live
    (unused, unexpired, this tenant's, and minted for this run — or minted run-unscoped) —
    stamping ``used_at`` so a second use is refused. ``False`` for a used / expired / cross-tenant
    / wrong-run / unknown token (indistinguishable — no existence leak)."""
    row = (
        await conn.execute(
            _CONSUME_SQL, {"token": token, "workspace_id": workspace_id, "run_id": run_id}
        )
    ).one_or_none()
    return row is not None
