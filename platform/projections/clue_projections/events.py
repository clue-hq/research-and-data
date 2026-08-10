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

**Subjects (Part II D7).** The outbox is keyed on ``(subject_kind, subject_id)``, not on a project
run, so a design leg is a first-class stream subject. :func:`plan_replay` is subject-capable; the
``clue_api`` SSE endpoint stays project-run-scoped this round (it passes ``run_id=`` as before) and
the design leg mounts its own stream in Round B. The design *emitter* is not reachable from here —
it lives in ``clue_execution.run_events`` for the import-contract reason documented in that module.
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
    cursor is unknown or older than the replay horizon → it re-fetches the projection), the ordered
    backlog to deliver, and the ``effective_cursor`` the live tail must resume from. ``duplicates
    tolerated by seq`` — a consumer dedups on the envelope id, so re-sending an event the consumer
    already saw is harmless.

    ``effective_cursor`` is the load-bearing field for the tail: on reset it is **0** (never the
    consumer's bogus cursor — a corrupted/future/cross-environment ``Last-Event-ID`` used as the
    tail floor would silently match nothing forever, a permanently dead "live" stream)."""

    reset: bool
    backlog: tuple[RunEventRow, ...]
    effective_cursor: int


async def plan_replay(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: ProjectRunId | None = None,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    last_event_id: int | None,
    horizon_s: float,
    now: datetime | None = None,
    limit: int = 1000,
) -> ReplayPlan:
    """Plan a reconnecting consumer's replay from ``last_event_id`` (the ``Last-Event-ID`` cursor).

    The stream is keyed on a **subject** since D7. Name it either way — ``run_id=`` (the
    project-run stream, exactly as before, which is what the ``clue_api`` SSE endpoint passes) or
    ``subject_kind=``/``subject_id=`` (the general form, which a design leg's stream uses). Passing
    neither plans over the whole workspace stream. The horizon/reset decision is subject-agnostic:
    it is a property of the cursor's row, so the semantics below hold identically for every kind.

    * No cursor (a fresh connect) → no reset; backlog is every event so far (``seq > 0``).
    * A cursor whose event is **within** the horizon → no reset; backlog is ``seq > cursor``
      (gapless — duplicates tolerated by seq); the tail resumes from the cursor.
    * A cursor whose event is **older than** the horizon, or is unknown/aged-out (corrupted,
      cross-environment, cross-workspace, future) → **reset**: the surface emits ``stream.reset``
      (the client re-fetches the projection — the projection, not the backlog, is the authority
      after a reset), the ``effective_cursor`` drops to **0**, and both the backlog and the live
      tail restart from the beginning. The bogus cursor is never reused as the tail floor (it
      would silently match nothing forever — a permanently dead stream).

    Forward-note (slice-1 review F5): no ``run_event`` sweep/pruner exists in this slice, so the
    post-reset backlog is genuinely complete. The day a sweep lands, reset-then-backlog becomes a
    partial view and these semantics must be revisited (close-after-reset, or a documented
    projection-first re-sync contract).

    Read-only — issues no writes (the D7 MVCC-only discipline)."""
    cursor = last_event_id if last_event_id is not None and last_event_id > 0 else 0
    reset = False
    if cursor > 0:
        moment = now if now is not None else datetime.now(UTC)
        cutoff = moment - timedelta(seconds=horizon_s)
        cursor_ts = await event_created_at(conn, workspace_id=workspace_id, seq=cursor)
        reset = cursor_ts is None or cursor_ts < cutoff
    effective_cursor = 0 if reset else cursor
    backlog = await list_run_events(
        conn,
        workspace_id=workspace_id,
        run_id=run_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        after_seq=effective_cursor,
        limit=limit,
    )
    return ReplayPlan(reset=reset, backlog=tuple(backlog), effective_cursor=effective_cursor)
