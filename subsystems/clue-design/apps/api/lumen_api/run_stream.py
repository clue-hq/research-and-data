"""The design run's activity stream — one durable outbox, one auth model (Part II slice D7).

D5 gave design runs a fleet lease. D6 put every design mutation behind a governed tool. D7 removes
the last private substrate on the run path: ``design_run_event`` (a per-run event log with its own
``FOR UPDATE`` sequence allocator, its own polled SSE route, and its own ``?workspace_id=`` auth
carrier) is **dropped**, and the design leg becomes a first-class *subject* on the platform's
durable ``run_event`` outbox — ``design.run.event`` / ``design.run.completed`` /
``design.run.failed`` under ``subject_kind='design_run'`` (the Round-A widening).

This module is the whole seam, in one file:

* :func:`fenced_emit` — the ONE way a design event reaches the stream, and the surviving half of the
  D5 zombie fence.
* :func:`emit_progress` / :func:`complete_run_and_emit` — the two shapes callers actually write.
* :func:`legacy_event` — the row → editor-contract mapper (R-D7-B1: the editor's wire format is
  preserved byte-for-byte, not migrated).
* :func:`mint_run_stream_token` / :func:`consume_run_stream_token` — the header-authed mint and the
  token-derived-workspace consume that together replace ``resolve_stream_workspace_id``.
* :func:`stream_run_events` — the SSE body: replay-then-live-tail over the durable subject stream.

**Why the composition root owns this.** ``clue_design`` may import only core + db + config + obs +
storage (the design-substrate contract), so it cannot reach ``clue_execution.run_events``; and
``lumen_api`` may not import ``clue_api``, so it cannot reach the SSE app either. The two halves the
write needs from the design row — the lease generation and the staleness clock — are exported by
``clue_design.runs``; everything else is here.

**Editor contract, preserved (R-D7-B1).** Two event names, ``progress`` and ``done``. A
``progress`` frame's data is ``{seq, type, data, created_at}`` exactly as ``design_run_event``
served it; ``done`` carries the run's result envelope. The design ``event_type`` free vocabulary
(~60 names from the agent runtime) rides inside the run_event payload rather than becoming topics,
which is why the three coarse topics suffice. ``seq`` is now the outbox's GLOBAL sequence, not a
per-run 1,2,3…: the editor's guard is monotonicity per run, which a global identity column
satisfies (a workspace's — and therefore a run's — rows form a strictly increasing subsequence).
The D7 recon confirmed no editor code depends on gaplessness or on the first seq being 1;
``agentChecklist`` and the web hook's event list both only append in arrival order.

**Capacity honesty (R-D7-B7, answered at D8 / R-D8-4).** ``run_event`` still carries no FK to its
subject and no CASCADE, and design payloads are markedly heavier than project-run ones — a
``dsl_compiled`` progress event carries the compile's whole applied-``operations`` array — so a
chatty turn emits dozens of heavy rows. D8 gives that growth a bound: ``lumen_api.event_pruner``
deletes the **progress** rows of design runs that finished at least a retention window ago. It is
**disabled by default** (``Settings.design_run_event_prune_interval_s = 0``) — the one sweep in the
platform that destroys durable run-visibility history — and it is hemmed in by floors written in
code, not configuration: only ``subject_kind='design_run'`` + ``topic='design.run.event'`` rows,
only for a ``succeeded``/``failed`` run, only when a terminal row survives, and only after a hard
7-day retention floor that strictly exceeds :data:`REPLAY_HORIZON_SECONDS` below.

Two consequences worth stating plainly. (1) The **[B4×SSE] reset-then-backlog** question is
answered by scope: the project stream is never touched, so its post-reset backlog stays complete;
and on the design stream retention ≫ horizon means a cursor young enough to replay gaplessly points
at a run far too young to prune, while an older cursor is reset to 0, where the surviving terminal
row still closes the stream correctly. A within-horizon cursor therefore never observes a hole, and
a fresh connect on a pruned run still ends in ``done``. (2) :func:`run_snapshot_events` (the
``GET /agent/runs/{id}`` events key) replays from seq 0, so once a run has been pruned its snapshot
returns the terminal event only. Accepted by ruling, for a default-off sweep scoped to runs that
finished a week ago; the run row and its ``result_json`` are untouched.

**A hard constraint the pruner inherits (D8 / R-D8-3), and honours.** A **terminal** row must never
be pruned. :func:`stream_run_events` closes a subscriber's stream on the terminal *event* and on
nothing else: D8 deleted the idle-poll liveness net that used to re-read ``design_agent_run`` and
close out a run whose terminal event was missing. That net existed only to cover
``HybridRepository.set_run_result`` (caller-less, terminalizing without emitting), which D8 deleted
in the same breath — so a sweep that could remove a terminal row would silently reintroduce
hang-forever streams with nothing left to catch them. The pruner cannot: its delete statement
(``clue_execution.run_events.prune_design_run_progress_events``) filters the progress topic as a
literal and additionally *requires* a surviving terminal row.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from clue_core import DESIGN_RUN_SUBJECT_KIND, ExecutionId, RunEventRow, plan_replay
from clue_db import create_engine
from clue_design import runs as design_runs
from clue_design.errors import DesignRunFencedError
from clue_execution.run_events import (
    DbRunEventReader,
    emit_design_run_event,
    list_run_events,
)
from clue_execution.stream_tokens import (
    consume_subject_stream_token,
    mint_stream_token,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

JsonObject = Dict[str, Any]

#: The three coarse routing topics a design leg may write (mirrors
#: ``clue_core.DESIGN_RUN_EVENT_TOPICS``; the emitter refuses anything else).
PROGRESS_TOPIC = "design.run.event"
COMPLETED_TOPIC = "design.run.completed"
FAILED_TOPIC = "design.run.failed"

#: Live-tail poll cadence for the DESIGN stream, deliberately overriding the platform SSE default
#: of 1.0s (``Settings.sse_poll_interval_s``). A design turn's reveal is paced by these frames — the
#: editor applies a compile's operations to the canvas the moment the event lands — and at 1 Hz the
#: authoring batches arrive in visible one-second steps instead of streaming. 4 Hz is the cadence
#: the live-design-streaming work (D2) tuned and shipped; keeping it is a UX requirement, not a
#: preference. The keepalive stays at ~1s of idle so an idle stream is not 4× chattier than the
#: platform's.
POLL_INTERVAL_SECONDS = 0.25
KEEPALIVE_INTERVAL_SECONDS = 1.0

#: One connect's worth of backlog. A turn can exceed this; the tail loop simply continues from the
#: last seq served, so a long run catches up on the next poll rather than truncating.
REPLAY_PAGE_LIMIT = 1000

#: How far back a ``Last-Event-ID`` may point before the server treats it as unknown and replays
#: from 0. Generous on purpose: design runs last minutes, so within a run a reconnect is always
#: gapless, and the only cursors this rejects are genuinely stale ones from a previous session.
REPLAY_HORIZON_SECONDS = 86_400.0

#: Stream tokens are single-use and consumed immediately after minting, so the TTL only has to
#: cover the client's mint → connect round trip. Short by design: an unused token is a credential.
STREAM_TOKEN_TTL_SECONDS = 60.0


# --- writing ------------------------------------------------------------------------------------


def progress_payload(event_type: str, data: Optional[JsonObject]) -> JsonObject:
    """The ``design.run.event`` payload envelope: the design event name plus its body.

    Two keys, always both present, so :func:`legacy_event` can rebuild the editor's row shape
    without probing. The design vocabulary stays in the payload rather than becoming topics
    (Round A's contract) precisely because it is open — ~60 agent-runtime event names that change
    with the runtime, which a routing taxonomy must not."""
    return {"event_type": event_type, "data": data if data is not None else {}}


def terminal_payload(
    event_type: str, data: Optional[JsonObject], result: Optional[JsonObject]
) -> JsonObject:
    """The terminal payload — **self-contained** (R-D7-B2).

    It carries the run's FULL result envelope alongside the marker's own ``event_type``/``data``,
    so the serve layer builds its ``done`` frame from the event and — since D8 deleted the idle
    liveness net — **never reads the run row at all**, which is now a structural property of
    :func:`stream_run_events` rather than a claim about timing. That read was the pre-D7 shape
    (``sse_frame(seq, "done", run["result"])``) and it only worked because ``complete_run`` fused
    the result and the marker into one transaction; carrying the result *in* the event removes the
    coupling instead of re-timing it.
    """
    return {"event_type": event_type, "data": data if data is not None else {}, "result": result}


async def fenced_emit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    topic: str,
    payload: JsonObject,
    expected_generation: Optional[int] = None,
    execution_id: Optional[ExecutionId] = None,
) -> RunEventRow:
    """Append one design-leg event to the durable outbox, under the D5 lease fence. One transaction.

    Three things happen here, in this order, and the order is the contract:

    1. **The run row is read** (``run_lease_generation``) — which is also the existence and tenancy
       gate. An unknown or cross-workspace run raises :class:`DesignNotFoundError`, exactly as the
       retired ``append_run_event``'s sequence allocator did.
    2. **The fence is checked before anything is written.** A writer whose generation is not the
       row's own — a superseded attempt, or one that never claimed this run under it (equality
       since 2026-10-16: generations never repeat, so the row's names exactly one attempt; a row
       never claimed has nothing to fence by) — is refused with
       :class:`DesignRunFencedError` and leaves no trace at all — no row, no partial write. This is
       the surviving half of the D5 zombie fence: an abandoned turn thread runs to completion
       (a thread cannot be interrupted), so the only thing standing between it and the takeover's
       stream is this check. It has to live at the emit site, not at the caller's, or a fenced-out
       zombie's progress would pollute the live run's stream.
    3. **The event is emitted and the run is touched.** ``touch_run`` preserves the side effect
       ``append_run_event`` carried: ``design_agent_run.updated_at`` is the *reaper's staleness
       clock*, so a long turn that only emits progress must keep proving it is alive. Folding it
       into this transaction means an emitted event and a refreshed clock cannot diverge.
    """
    generation = await design_runs.run_lease_generation(
        conn, workspace_id=workspace_id, run_id=run_id
    )
    if (
        expected_generation is not None
        and generation is not None
        and generation != expected_generation
    ):
        raise DesignRunFencedError(run_id, expected_generation, generation)
    row = await emit_design_run_event(
        conn,
        workspace_id=workspace_id,
        design_run_id=run_id,
        topic=topic,
        payload=payload,
        execution_id=execution_id,
    )
    await design_runs.touch_run(conn, workspace_id=workspace_id, run_id=run_id)
    return row


async def emit_progress(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    event_type: str,
    data: Optional[JsonObject] = None,
    expected_generation: Optional[int] = None,
    execution_id: Optional[ExecutionId] = None,
) -> int:
    """One progress event; returns the outbox seq (what ``append_run_event`` used to return)."""
    row = await fenced_emit(
        conn,
        workspace_id=workspace_id,
        run_id=run_id,
        topic=PROGRESS_TOPIC,
        payload=progress_payload(event_type, data),
        expected_generation=expected_generation,
        execution_id=execution_id,
    )
    return row.seq


async def complete_run_and_emit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: str,
    status: str,
    result: Optional[JsonObject],
    event_type: str,
    event_data: Optional[JsonObject] = None,
    expected_generation: Optional[int] = None,
) -> int:
    """Land a run's terminal result AND its terminal stream event in ONE transaction.

    The successor to ``clue_design.runs.complete_run``, moved up a layer because the event now
    lands on a table ``clue_design`` may not reach. Everything that made the fusion necessary is
    unchanged: a reader must see the run either entirely running or entirely finished, and the
    **result is written first** so an event announcing a terminal state can never be observed
    before the state it announces is committed.

    The fence guards both writes. ``set_run_result`` raises :class:`DesignRunFencedError` before
    the emit is reached, so a fenced-out zombie adds neither a result nor an event.
    """
    await design_runs.set_run_result(
        conn,
        workspace_id=workspace_id,
        run_id=run_id,
        status=status,
        result=result,
        expected_generation=expected_generation,
    )
    row = await fenced_emit(
        conn,
        workspace_id=workspace_id,
        run_id=run_id,
        topic=COMPLETED_TOPIC if status == "succeeded" else FAILED_TOPIC,
        payload=terminal_payload(event_type, event_data, result),
        expected_generation=expected_generation,
    )
    return row.seq


# --- reading ------------------------------------------------------------------------------------


def _reader(conn: AsyncConnection, *, workspace_id: str, run_id: str) -> DbRunEventReader:
    """This run's slice of the outbox, bound to one connection — what ``plan_replay`` reads through.

    D8: the planner is ``clue_core.plan_replay``, the single implementation the platform's own SSE
    endpoint also runs. It takes an injected reader rather than a connection, which is what lets one
    planner serve two streams whose packages may not import each other.
    """
    return DbRunEventReader(
        conn,
        workspace_id=workspace_id,
        subject_kind=DESIGN_RUN_SUBJECT_KIND,
        subject_id=run_id,
    )


def legacy_event(row: RunEventRow) -> JsonObject:
    """One outbox row in the shape ``design_run_event`` served — the editor contract, verbatim.

    ``{seq, type, data, created_at}``: the same four keys the retired ``run_event_from_row``
    produced, so both consumers (the ``progress`` SSE frame and the run-snapshot endpoint's
    ``events`` list) are byte-compatible across the substrate swap. ``type``/``data`` are lifted
    back out of the payload envelope :func:`progress_payload` put them in; a terminal row maps the
    same way (its extra ``result`` key is for the ``done`` frame and is deliberately not echoed
    here — the snapshot already returns ``result`` at the top level).
    """
    payload = row.payload
    data = payload.get("data")
    return {
        "seq": row.seq,
        "type": payload.get("event_type"),
        "data": data if isinstance(data, dict) else {},
        "created_at": _iso(row.created_at),
    }


def is_terminal(row: RunEventRow) -> bool:
    return row.topic in (COMPLETED_TOPIC, FAILED_TOPIC)


def terminal_result(row: RunEventRow) -> Any:
    """The result envelope a terminal row carries — the ``done`` frame's data."""
    return row.payload.get("result")


def _iso(value: object) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def sse_frame(seq: int, event: str, data: Any) -> str:
    """One Server-Sent Events frame. ``id:`` carries the outbox seq so a reconnect resumes from it
    via ``Last-Event-ID``. Byte-identical to the retired ``lumen_api.main.sse_frame``."""
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data)}\n\n"


# --- auth: the mint/consume pair that replaced ``?workspace_id=`` --------------------------------


async def mint_run_stream_token(
    conn: AsyncConnection, *, workspace_id: str, run_id: str
) -> UUID:
    """Mint a single-use token bound to THIS run's stream subject.

    Called from a header-authenticated route, so ``workspace_id`` is the caller's proven tenant;
    the token row records it, and :func:`consume_run_stream_token` reads it back. That is the whole
    of D7's auth change: the workspace stops travelling in a query string (a claim anyone can make)
    and starts travelling in a credential the server minted.
    """
    return await mint_stream_token(
        conn,
        workspace_id=workspace_id,
        subject_kind=DESIGN_RUN_SUBJECT_KIND,
        subject_id=run_id,
        ttl_s=STREAM_TOKEN_TTL_SECONDS,
    )


async def consume_run_stream_token(
    conn: AsyncConnection, *, token: UUID, run_id: str
) -> Optional[str]:
    """Consume a run-stream token once and return the workspace it was minted for (or ``None``)."""
    return await consume_subject_stream_token(
        conn, token=token, subject_kind=DESIGN_RUN_SUBJECT_KIND, subject_id=run_id
    )


async def consume_run_stream_token_isolated(
    *, token: UUID, run_id: str, engine_factory: Any = create_engine
) -> Optional[str]:
    """:func:`consume_run_stream_token` on its own engine — the stream route's entry point.

    Every other design DB call goes through ``HybridRepository``, which is built FROM a workspace.
    This one cannot: resolving the workspace is precisely what it does. So it owns its connection
    directly, on the serving loop, and commits the single-use stamp before the stream body opens —
    a token must be spent even if the client hangs up mid-handshake.
    """
    engine: AsyncEngine = engine_factory()
    try:
        async with engine.connect() as conn, conn.begin():
            return await consume_run_stream_token(conn, token=token, run_id=run_id)
    finally:
        await engine.dispose()


# --- the SSE body --------------------------------------------------------------------------------


async def stream_run_events(
    *,
    workspace_id: str,
    run_id: str,
    cursor: Optional[int],
    live_tail: bool = True,
    engine_factory: Any = create_engine,
) -> AsyncIterator[str]:
    """Replay this run's stream from ``cursor``, then live-tail it until the client disconnects.

    One engine for the stream's lifetime, one connection+transaction per read — an improvement on
    the pre-D7 loop, which rebuilt a whole ``HybridRepository`` (and therefore an engine) on every
    250ms poll. The engine is created and disposed on the serving loop, so the O5 rule ("one
    connection, one transaction, bound to this call's loop") still holds; only the per-poll setup
    cost is gone.

    Replay semantics come from ``clue_core.plan_replay`` — literally the same function the platform
    stream runs, so "no cursor ⇒ full backlog / cursor within horizon ⇒ gapless / stale cursor ⇒
    restart from 0" is one implementation (D8 folded D7's parity-bound twin into it). A reset is **not** framed to the client: R-D7-B1 pins this
    stream to exactly two event names, and a reset here is indistinguishable from the fresh-connect
    replay the editor already performs on every mount. (The platform stream's ``stream.hello`` /
    ``stream.reset`` frames are why the new editor client ignores unknown event names — it will
    point at that stream too, at Part IV.)
    """
    engine: AsyncEngine = engine_factory()
    try:
        # The browser's own reconnect hint, preserved from the pre-D7 stream.
        yield "retry: 1000\n\n"
        async with engine.connect() as conn, conn.begin():
            plan = await plan_replay(
                _reader(conn, workspace_id=workspace_id, run_id=run_id),
                last_event_id=cursor,
                horizon_s=REPLAY_HORIZON_SECONDS,
                limit=REPLAY_PAGE_LIMIT,
            )
        last_seq = plan.effective_cursor
        for row in plan.backlog:
            last_seq = row.seq
            if is_terminal(row):
                yield sse_frame(row.seq, "done", terminal_result(row))
                return
            yield sse_frame(row.seq, "progress", legacy_event(row))
        if not live_tail:
            return

        polls_per_keepalive = max(1, round(KEEPALIVE_INTERVAL_SECONDS / POLL_INTERVAL_SECONDS))
        idle_polls = 0
        while True:
            async with engine.connect() as conn, conn.begin():
                rows = await list_run_events(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind=DESIGN_RUN_SUBJECT_KIND,
                    subject_id=run_id,
                    after_seq=last_seq,
                    limit=REPLAY_PAGE_LIMIT,
                )
            for row in rows:
                last_seq = row.seq
                if is_terminal(row):
                    yield sse_frame(row.seq, "done", terminal_result(row))
                    return
                yield sse_frame(row.seq, "progress", legacy_event(row))
            if rows:
                idle_polls = 0
                continue
            # D8 (R-D8-3) removed the defensive terminal branch that used to sit here, together
            # with the one surface that could produce the state it covered for
            # (``HybridRepository.set_run_result`` — caller-less, terminalizing WITHOUT emitting).
            # Both live terminal writers — the worker's ``complete_run_and_emit`` and the reaper's
            # stranded terminal — write the result and its event in ONE transaction, so "terminal
            # status, no terminal event" is now unreachable and this loop reads no run row at all.
            #
            # CONSEQUENCE FOR RETENTION: a terminal ``run_event`` row is the ONLY thing that closes
            # a subscriber's stream. A pruner must never delete one, or every reader of that run
            # hangs until it gives up — the net that used to catch that is gone on purpose. D8's
            # pruner (``lumen_api.event_pruner``) honours that structurally: it deletes only the
            # progress topic, and only for a subject that still holds a terminal row.
            if idle_polls % polls_per_keepalive == 0:
                yield ": keepalive\n\n"
            idle_polls += 1
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        await engine.dispose()


async def run_snapshot_events(
    conn: AsyncConnection, *, workspace_id: str, run_id: str
) -> List[JsonObject]:
    """This run's whole stream in the legacy row shape — the ``GET /agent/runs/{id}`` events key."""
    rows = await list_run_events(
        conn,
        workspace_id=workspace_id,
        subject_kind=DESIGN_RUN_SUBJECT_KIND,
        subject_id=run_id,
        after_seq=0,
        limit=REPLAY_PAGE_LIMIT,
    )
    return [legacy_event(row) for row in rows]
