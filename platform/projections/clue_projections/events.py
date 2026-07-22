"""The SSE **read side** — replay planning over the ``run_event`` outbox (PB-B4 slice 3, D8).

This is the read half of the treaty SSE surface (REQ-11 / A5). The *write* half — appending
``run_event`` rows at the run drive boundary — lives in ``clue_research.durable.run_events`` (run-
run-machinery, called from the ``clue_api`` drive path); this module only **reads** it, so
``clue_projections`` stays a pure read package (importing the durable *read* helpers is a research
read surface, allowed by the projections import contract; the emitter is deliberately NOT here —
that would make projections a write surface).

:func:`plan_replay` is the pure heart of gapless ``Last-Event-ID`` reconnect: given the consumer's
last-seen ``seq`` cursor and the configured replay horizon, it decides whether the cursor is still
replayable (backlog of ``seq > cursor``) or is older than the horizon and must be **reset** (the
client re-fetches the projection, then resumes live). The ``clue_api`` SSE endpoint wraps this with
the transport concerns — ``stream.hello`` / ``stream.reset`` framing, the live tail loop, and
single-use stream tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId
from clue_research.durable import RunEventRow, event_created_at, list_run_events


@dataclass(frozen=True, slots=True)
class ReplayPlan:
    """The outcome of a reconnect-replay decision: whether the consumer must be **reset** (its
    cursor is older than the replay horizon → it re-fetches the projection) and the ordered backlog
    of events with ``seq > cursor`` to deliver. ``duplicates tolerated by seq`` — a consumer dedups
    on the envelope id, so re-sending an event the consumer already saw is harmless."""

    reset: bool
    backlog: tuple[RunEventRow, ...]


async def plan_replay(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: ProjectRunId | None,
    last_event_id: int | None,
    horizon_s: float,
    now: datetime | None = None,
    limit: int = 1000,
) -> ReplayPlan:
    """Plan a reconnecting consumer's replay from ``last_event_id`` (the ``Last-Event-ID`` cursor).

    * No cursor (a fresh connect) → no reset; backlog is every event so far (``seq > 0``).
    * A cursor whose event is **within** the horizon → no reset; backlog is ``seq > cursor``
      (gapless — duplicates tolerated by seq).
    * A cursor whose event is **older than** the horizon, or is unknown/aged-out → **reset**: the
      surface emits ``stream.reset`` (the client re-fetches the projection) then resumes live. The
      backlog (``seq > cursor``) is still returned so a live consumer misses nothing after the
      re-sync (seq-idempotent), and no sweep runs in this slice so it is in fact complete.

    Read-only — issues no writes (the D7 MVCC-only discipline)."""
    cursor = last_event_id if last_event_id is not None and last_event_id > 0 else 0
    reset = False
    if cursor > 0:
        moment = now if now is not None else datetime.now(UTC)
        cutoff = moment - timedelta(seconds=horizon_s)
        cursor_ts = await event_created_at(conn, workspace_id=workspace_id, seq=cursor)
        reset = cursor_ts is None or cursor_ts < cutoff
    backlog = await list_run_events(
        conn, workspace_id=workspace_id, run_id=run_id, after_seq=cursor, limit=limit
    )
    return ReplayPlan(reset=reset, backlog=tuple(backlog))
