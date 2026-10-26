"""The turn stream's HTTP surface: attach, stop, retry, and the hydrated cold-load read.

FI Lane D slice **D3**, charter §§3.2/3.5/3.6 and Lane B contract §5.5. This is the *read* half of
the turn stream — the half a browser talks to. It deliberately imports nothing model-shaped: by
ratified §6-D1 the web process never composes a gateway, so this module reaches the outbox, the
control table, the thread projections and object storage, and stops there.
:mod:`tests.api.test_lane_d2_http_gateway_isolation` walks this module's imports and would fail if
that ever stopped being true.

**Why its own router rather than routes on the chat router.** D4 owns ``chat/router.py`` this
round, and a streaming surface is a different kind of endpoint anyway (a long-lived response, a
one-shot token, a poll loop). It mounts on the same app under the same ``/api/v1`` prefix, reuses
the same principal dependency — so Lane B's authorizer, once installed, covers these routes with no
change here — and reuses the same error envelope, so a client sees one API and not two.

**Auth is Lane B §5.5, exactly.** An authenticated, authorized request *mints* a short-lived,
single-use, workspace- and turn-scoped stream token; opening the stream consumes it. No bearer
credential travels in a URL, and a token's replay or expiry cannot widen anybody's authority: it
authorises opening one stream, which serves only the rows of the workspace and turn it names.

**The four endpoints.**

* ``POST …/turns/{turn_id}/stream_token`` — mint (after proving the turn belongs to this thread of
  this project of this workspace).
* ``GET  …/turns/{turn_id}/events`` — attach: ``stream.hello``, then the ``Last-Event-ID`` backlog
  (or ``stream.reset`` when the cursor is beyond the replay horizon), then a live tail.
* ``POST …/turns/{turn_id}/stop`` / ``…/retry`` — the §3.5 controls, as durable requests.

The hydrated cold-load read is **not** here: it is the chat router's ``GET …/messages`` with
``?include=bodies``, which is where the contract puts it. This module still owns the hydrator
(:mod:`clue_api.chat.message_bodies`) that route delegates to, so there is one implementation of
"resolve this page's bodies, bounded" rather than two surfaces that drift.

**Dispatch-on-attach.** Attaching to a turn also offers the thread's next queued turn to the fleet
if none is in flight. It closes the narrow window the D2 review recorded — a process death between
finalizing a task and dispatching the next one strands a queued submission until that thread's next
POST — for the case that matters most, the one where somebody is watching. It is safe from here
because :func:`~clue_api.agent_turn_submission.dispatch_next_thread_turn` takes the per-thread
advisory lock and refuses whenever a task is already in flight, so no amount of attaching can
produce two live turns on one thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, FastAPI, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text

from clue_api.agent_turn_submission import (
    dispatch_next_thread_turn,
    get_submission,
    insert_submission,
    lock_thread_queue,
    submission_attachment_refs_for_turns,
    submission_context_refs,
    submission_context_refs_for_turns,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.composer_context import context_ref_presentations
from clue_api.chat.message_bodies import hydrate_message_bodies
from clue_api.chat.principal import (
    PERMISSION_THREAD_READ,
    PERMISSION_THREAD_WRITE,
    RequestPrincipal,
)
from clue_api.chat.queue_controls import (
    QueueResumeConflict,
    hold_queue,
    queue_control,
    resume_queue,
)
from clue_api.chat.router import (
    CHAT_PREFIX,
    _EnvelopeRoute,
    _refuse,
    chat_principal_resolver,
)
from clue_api.chat.schemas import (
    TurnAcceptedResponse,
    TurnAcceptedWire,
)
from clue_api.chat.turn_controls import (
    get_control_request,
    insert_control_request,
    lock_turn_control,
)
from clue_api.chat.turn_events import (
    LIFECYCLE_EVENT_TYPES,
    TERMINAL_TURN_EVENTS,
    TURN_STREAM_SCHEMA_VERSION,
    TurnEventRow,
    list_turn_events,
    plan_turn_replay,
)
from clue_api.conversation_capture import persist_user_turn, project_client_entity_id
from clue_api.stream_tokens import (
    AGENT_THREAD_SUBJECT_KIND,
    consume_stream_token,
    consume_turn_stream_token,
    mint_stream_token,
    mint_turn_stream_token,
)
from clue_api.thread_store import get_thread
from clue_auth import Permission
from clue_config import Settings
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_projections import (
    ThreadTurnView,
    thread_turn,
    thread_turns,
)
from clue_spine import get_project
from clue_storage import StorageBackend

log = get_logger("clue_api.chat.stream")

__all__ = [
    "build_chat_stream_router",
    "install_chat_stream_surface",
    "thread_event_frames",
]

PrincipalDep = Annotated[RequestPrincipal, Depends(chat_principal_resolver)]


class ResumeQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hold_control_id: UUID


#: A turn state that means the conversation owes the user an answer. ``queued`` counts: from the
#: user's side a submitted turn nobody has claimed yet is the conversation working, not idle.
_LIVE_TURN_STATES = frozenset({"queued", "running"})


def _running(turns: Sequence[ThreadTurnView]) -> bool:
    return any(item.state in _LIVE_TURN_STATES for item in turns)


def _sse_frame(*, event: str, data: dict[str, JsonValue], event_id: int | None = None) -> str:
    """One SSE frame: ``id:`` (the ``Last-Event-ID`` cursor), ``event:``, ``data:``.

    Identical framing to the B4 treaty stream, deliberately — one wire format for both streams
    means one client-side reader and one thing to get right.
    """

    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'), default=str)}")
    return "\n".join(lines) + "\n\n"


def _event_frame(row: TurnEventRow) -> str:
    return _sse_frame(event=row.event_type, data=row.envelope(), event_id=row.event_id)


def _is_terminal_event(row: TurnEventRow) -> bool:
    """Whether ``row`` is the last frame a turn stream may serve."""

    return row.event_type in TERMINAL_TURN_EVENTS


_KEEPALIVE_COMMENT = ": keepalive\n\n"


async def _thread_tail(conn: Any, *, workspace_id: str, thread_id: str) -> int:
    """The thread's newest frame id of any type (``0`` for a thread with none)."""

    return int(
        await conn.scalar(
            text(
                "SELECT coalesce(max(event_id), 0) FROM agent_turn_event_stream "
                "WHERE workspace_id = :workspace AND thread_id = :thread"
            ),
            {"workspace": workspace_id, "thread": thread_id},
        )
    )


async def thread_event_frames(
    *,
    conn_factory: ConnFactory,
    settings: Settings,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    cursor: int | None,
    live_tail: bool = True,
) -> AsyncIterator[str]:
    """The thread stream's frames: hello, then the lifecycle frames of any turn in the thread.

    CRM trial 1, F2 (R-10.1). Only ``turn.*`` frames travel here (:data:`LIFECYCLE_EVENT_TYPES`);
    they tell an open chat that a turn exists — one the server queued, another tab sent, or a
    teammate started — and the chat then attaches that turn's own stream for its parts and text.

    * **No cursor** (a fresh open): start at the thread's tail. The chat has just read the thread,
      so nothing older is news. ``stream.hello`` carries the start point as its ``id``, so the
      client always holds a cursor to reconnect from.
    * **A cursor**: replay the lifecycle frames after it, or, when it is older than the replay
      horizon (or unknown), send ``stream.reset`` and start at the tail — the chat re-reads the
      thread on a reset, so replaying old frames would only repeat what that read returns.

    There is no terminal frame: a thread outlives its turns, and the stream ends when the client
    disconnects. While nothing happens it sends an SSE comment every
    ``chat_thread_stream_keepalive_s`` so no proxy closes an idle connection. Everything is read
    from Postgres on each poll, so any API process can serve any chat.
    """

    envelope: dict[str, JsonValue] = {
        "schema_version": TURN_STREAM_SCHEMA_VERSION,
        "thread_id": thread_id,
        "project_id": project_id,
    }
    reset = False
    backlog: tuple[TurnEventRow, ...] = ()
    async with conn_factory() as conn:
        if cursor is not None:
            plan = await plan_turn_replay(
                conn,
                workspace_id=workspace_id,
                turn_id=None,
                thread_id=thread_id,
                last_event_id=cursor,
                horizon_s=settings.sse_replay_horizon_s,
                limit=settings.sse_replay_page_limit,
                event_types=LIFECYCLE_EVENT_TYPES,
            )
            reset = plan.reset
            if not reset:
                backlog = plan.backlog
                last_seen = plan.effective_cursor
        if cursor is None or reset:
            last_seen = await _thread_tail(conn, workspace_id=workspace_id, thread_id=thread_id)
    # The start point is fixed before hello, so a turn that begins while the client reads hello
    # is still ahead of the cursor.
    # Its ``id`` is the start point, so a client that reconnects before any turn frame arrives
    # (a tab hidden at once, a proxy cut) resumes from here and misses nothing in between.
    yield _sse_frame(
        event="stream.hello", data={**envelope, "type": "stream.hello"}, event_id=last_seen
    )
    if reset:
        yield _sse_frame(
            event="stream.reset",
            data={
                **envelope,
                "type": "stream.reset",
                "reason": "cursor_older_than_horizon",
                "rehydrate": "transcript",
            },
        )
    for row in backlog:
        yield _event_frame(row)
        last_seen = row.event_id
    if not live_tail:
        return
    last_sent = time.monotonic()
    while True:
        await asyncio.sleep(settings.chat_thread_stream_poll_interval_s)
        async with conn_factory() as conn:
            fresh = await list_turn_events(
                conn,
                workspace_id=workspace_id,
                thread_id=thread_id,
                after_event_id=last_seen,
                event_types=LIFECYCLE_EVENT_TYPES,
            )
        for row in fresh:
            yield _event_frame(row)
            last_seen = row.event_id
        now = time.monotonic()
        if fresh:
            last_sent = now
        elif now - last_sent >= settings.chat_thread_stream_keepalive_s:
            yield _KEEPALIVE_COMMENT
            last_sent = now


def build_chat_stream_router(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    storage: StorageBackend | None = None,
    live_tail: bool = True,
) -> APIRouter:
    """Build the turn-stream router. Empty unless ``settings.chat_enabled``.

    ``live_tail=False`` makes ``…/events`` replay-then-close, which is what makes the disconnect,
    duplicate-delivery and cursor-replay cases of the §5 suite deterministic; production leaves it
    open. ``storage`` gates only the two routes that need bytes (body hydration and retry's
    re-capture): a surface that cannot durably capture must not pretend it can.
    """

    router = APIRouter(prefix=CHAT_PREFIX, tags=["chat-stream"], route_class=_EnvelopeRoute)
    if not settings.chat_enabled:
        return router
    artifacts = (
        None
        if storage is None
        else DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    )

    def _require(who: RequestPrincipal, permission: Permission) -> None:
        if permission not in who.permissions:
            raise _refuse(
                status_code=403,
                code="PERMISSION_DENIED",
                message=f"the active membership lacks {permission}",
            )

    async def _scope(
        *,
        who: RequestPrincipal,
        project_id: str,
        thread_id: str,
        turn_id: UUID | None = None,
    ) -> Any:
        """Prove the path names a real thread of a real project of *this* workspace.

        A thread in another project or another workspace is **not found**, never forbidden: a 403
        would confirm to somebody who cannot see it that it exists. When ``turn_id`` is supplied its
        durable submission must belong to the same thread — so a turn id borrowed from another
        conversation opens nothing.
        """

        async with conn_factory() as conn:
            thread = await get_thread(conn, workspace_id=who.workspace_id, thread_id=thread_id)
            if thread is None or thread.project_id != project_id:
                raise _refuse(
                    status_code=404,
                    code="THREAD_NOT_FOUND",
                    message="no such thread in this project",
                )
            if turn_id is None:
                return None
            submission = await get_submission(conn, workspace_id=who.workspace_id, turn_id=turn_id)
            if submission is None or submission.thread_id != thread_id:
                raise _refuse(
                    status_code=404,
                    code="TURN_NOT_FOUND",
                    message="no such turn in this thread",
                )
            return submission

    # --- the submissions-union read -------------------------------------------------------------

    @router.get("/projects/{project_id}/threads/{thread_id}/turns")
    async def list_turns_route(
        project_id: str,
        thread_id: str,
        who: PrincipalDep,
        include: Annotated[str | None, Query(pattern="^submission_bodies$")] = None,
    ) -> dict[str, JsonValue]:
        """Every turn of the thread in submission order — **queued ones included**.

        The read half of the two-phase turn identity ratified after D2: a turn that has been
        accepted but not yet executed exists only as a submission row, so a surface built on
        ``agent_turn`` alone would show a user's three waiting questions as nothing at all. Each
        entry carries the stream cursor to attach after, so a client can cold-load this list and
        then attach to whichever turn is live without replaying its history.
        """

        _require(who, PERMISSION_THREAD_READ)
        await _scope(who=who, project_id=project_id, thread_id=thread_id)
        turns = await thread_turns(
            workspace_id=who.workspace_id,
            thread_id=thread_id,
            conn_factory=conn_factory,
        )
        async with conn_factory() as conn:
            queue_state = await queue_control(
                conn, workspace_id=who.workspace_id, thread_id=thread_id
            )
            stops = (
                (
                    await conn.execute(
                        text(
                            "SELECT turn_id, control_id, requested_at "
                            "FROM agent_turn_control_request "
                            "WHERE workspace_id=:workspace AND thread_id=:thread AND kind='stop'"
                        ),
                        {"workspace": who.workspace_id, "thread": thread_id},
                    )
                )
                .mappings()
                .all()
            )
        stop_by_turn = {row["turn_id"]: row for row in stops}
        submission_messages: dict[UUID, dict[str, JsonValue]] = {}
        if include is not None:
            if storage is None:
                raise _refuse(
                    status_code=503,
                    code="BODIES_UNAVAILABLE",
                    message="this deployment has no artifact backend to hydrate submission bodies",
                )
            turn_ids = tuple(item.turn_id for item in turns)
            async with conn_factory() as conn:
                materialized = frozenset(
                    UUID(str(value))
                    for value in (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT turn_id FROM agent_thread_message "
                                "WHERE workspace_id=:workspace_id AND thread_id=:thread_id "
                                "AND role='user' AND turn_id=ANY(CAST(:turn_ids AS uuid[]))"
                            ),
                            {
                                "workspace_id": who.workspace_id,
                                "thread_id": thread_id,
                                "turn_ids": [str(turn_id) for turn_id in turn_ids],
                            },
                        )
                    ).scalars()
                )
                pending = tuple(item for item in turns if item.turn_id not in materialized)
                bodies = await hydrate_message_bodies(
                    conn,
                    storage=storage,
                    workspace_id=who.workspace_id,
                    references=tuple(
                        (item.message_artifact_key, item.message_sha256) for item in pending
                    ),
                )
                context_by_turn = await submission_context_refs_for_turns(
                    conn,
                    workspace_id=who.workspace_id,
                    turn_ids=tuple(item.turn_id for item in pending),
                )
                attachments_by_turn = await submission_attachment_refs_for_turns(
                    conn,
                    workspace_id=who.workspace_id,
                    turn_ids=tuple(item.turn_id for item in pending),
                )
                presentations = await context_ref_presentations(
                    conn,
                    workspace_id=who.workspace_id,
                    refs=tuple(ref for refs in context_by_turn.values() for ref in refs),
                    storage=storage,
                )
            for item in pending:
                hydrated = bodies.get(item.message_artifact_key)
                refs: list[JsonValue] = [
                    {
                        "flavor": "context",
                        "workspace_id": ref.workspace_id,
                        "object_type": ref.object_type,
                        "object_id": ref.object_id,
                        "version": ref.version,
                        "ordinal": ordinal,
                        **presentations.get((ref.object_type, ref.object_id), {}),
                    }
                    for ordinal, ref in enumerate(context_by_turn.get(item.turn_id, ()))
                ]
                # The attachment rows already carry their own presentation — the human's
                # filename, the media type, and the upload the bytes are served from — so a
                # pending turn's chips read exactly like the durable ones they become.
                refs.extend(
                    {
                        "flavor": "attachment",
                        "workspace_id": who.workspace_id,
                        "object_type": "artifact",
                        "object_id": attachment.ref.artifact_key,
                        "version": None,
                        "ordinal": attachment.ordinal,
                        "label": attachment.filename,
                        "media_type": attachment.ref.media_type,
                        "upload_id": str(attachment.upload_id),
                    }
                    for attachment in attachments_by_turn.get(item.turn_id, ())
                )
                submission_messages[item.turn_id] = {
                    "id": str(uuid5(item.turn_id, "user")),
                    "turn_id": str(item.turn_id),
                    "thread_id": item.thread_id,
                    "sequence": 0,
                    "role": "user",
                    "body_artifact_key": item.message_artifact_key,
                    "body_sha256": item.message_sha256,
                    "body": None if hydrated is None else hydrated.body,
                    "body_unavailable_reason": (
                        "unavailable" if hydrated is None else hydrated.reason
                    ),
                    "created_at": item.requested_at.isoformat(),
                    "refs": refs,
                }
        return {
            "data": [
                {
                    "turn_id": str(item.turn_id),
                    "thread_id": item.thread_id,
                    "project_id": item.project_id,
                    "state": item.state,
                    "requested_at": item.requested_at.isoformat(),
                    "last_event_id": item.last_event_id,
                    "generation_attempts": item.generation_attempts,
                    "derivation": item.derivation,
                    "answered_gate_id": (
                        None if item.answered_gate_id is None else str(item.answered_gate_id)
                    ),
                    "stop_request": (
                        {
                            "control_id": str(stop_by_turn[item.turn_id]["control_id"]),
                            "requested_at": stop_by_turn[item.turn_id]["requested_at"].isoformat(),
                            "pending": item.state != "cancelled",
                        }
                        if item.turn_id in stop_by_turn
                        else None
                    ),
                    "submission_message": submission_messages.get(item.turn_id),
                }
                for item in turns
            ],
            "meta": {
                "thread_status": "running" if _running(turns) else "idle",
                "queue_control": queue_state,
            },
        }

    # --- attach ---------------------------------------------------------------------------------

    @router.post("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/stream_token")
    async def mint_token_route(
        project_id: str,
        thread_id: str,
        turn_id: UUID,
        who: PrincipalDep,
    ) -> dict[str, JsonValue]:
        _require(who, PERMISSION_THREAD_READ)
        await _scope(who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id)
        async with conn_factory() as conn:
            token = await mint_turn_stream_token(
                conn,
                workspace_id=who.workspace_id,
                turn_id=turn_id,
                ttl_s=settings.chat_stream_token_ttl_s,
            )
        return {
            "data": {
                "schema_version": TURN_STREAM_SCHEMA_VERSION,
                "stream_token": str(token),
                "turn_id": str(turn_id),
            }
        }

    @router.get("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/events")
    async def turn_events_route(
        project_id: str,
        thread_id: str,
        turn_id: UUID,
        who: PrincipalDep,
        stream_token: Annotated[str, Query()],
        last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        last_event_id_query: Annotated[int | None, Query(alias="last_event_id")] = None,
    ) -> StreamingResponse:
        _require(who, PERMISSION_THREAD_READ)
        await _scope(who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id)
        try:
            token = UUID(stream_token)
        except (AttributeError, TypeError, ValueError) as exc:
            raise _refuse(
                status_code=401,
                code="INVALID_STREAM_TOKEN",
                message="invalid stream token",
            ) from exc
        async with conn_factory() as conn:
            consumed = await consume_turn_stream_token(
                conn, token=token, workspace_id=who.workspace_id, turn_id=turn_id
            )
        if not consumed:
            raise _refuse(
                status_code=401,
                code="INVALID_STREAM_TOKEN",
                message="invalid or already-used stream token",
            )

        # A parseable header (an EventSource reconnect) wins; the query cursor is the fallback,
        # including when the header is garbage — an unparseable header must not silently discard an
        # already-parsed query cursor.
        cursor: int | None = last_event_id_query
        if last_event_id_header is not None:
            with contextlib.suppress(ValueError):
                cursor = int(last_event_id_header)

        # Dispatch-on-attach: somebody is watching this conversation, so make sure it is actually
        # moving. Refuses by construction if a task is already in flight.
        async with conn_factory() as conn:
            await dispatch_next_thread_turn(
                conn, workspace_id=who.workspace_id, thread_id=thread_id
            )

        async def _stream() -> AsyncIterator[str]:
            yield _sse_frame(
                event="stream.hello",
                data={
                    "schema_version": TURN_STREAM_SCHEMA_VERSION,
                    "type": "stream.hello",
                    "turn_id": str(turn_id),
                    "thread_id": thread_id,
                    "project_id": project_id,
                },
            )
            async with conn_factory() as conn:
                plan = await plan_turn_replay(
                    conn,
                    workspace_id=who.workspace_id,
                    turn_id=turn_id,
                    last_event_id=cursor,
                    horizon_s=settings.sse_replay_horizon_s,
                    limit=settings.sse_replay_page_limit,
                )
            if plan.reset:
                yield _sse_frame(
                    event="stream.reset",
                    data={
                        "schema_version": TURN_STREAM_SCHEMA_VERSION,
                        "type": "stream.reset",
                        "turn_id": str(turn_id),
                        "thread_id": thread_id,
                        "project_id": project_id,
                        "reason": "cursor_older_than_horizon",
                        "rehydrate": "transcript",
                    },
                )
            # The tail floor is the plan's *effective* cursor: on reset that is 0, never the
            # consumer's unusable cursor, which as a floor would match nothing forever.
            last_seen = plan.effective_cursor
            for row in plan.backlog:
                yield _event_frame(row)
                last_seen = row.event_id
                if _is_terminal_event(row):
                    return
            if not live_tail:
                return
            # The outbox is the buffer (§3.3(7)): this loop reads it, and a slow or vanished
            # consumer only slows this generator. Model execution is in another process entirely
            # and cannot be blocked by anybody's socket.
            while True:
                await asyncio.sleep(settings.chat_stream_poll_interval_s)
                async with conn_factory() as conn:
                    fresh = await list_turn_events(
                        conn,
                        workspace_id=who.workspace_id,
                        turn_id=turn_id,
                        after_event_id=last_seen,
                    )
                if not fresh:
                    async with conn_factory() as conn:
                        acknowledged = await conn.scalar(
                            text(
                                "SELECT 1 FROM agent_turn_stop_ack a "
                                "JOIN agent_turn_control_request c USING (control_id) "
                                "WHERE c.workspace_id=:workspace AND c.turn_id=:turn"
                            ),
                            {"workspace": who.workspace_id, "turn": turn_id},
                        )
                    if acknowledged:
                        # A worker may die after the durable acknowledgement but before
                        # its terminal stream frame. Rehydrate history without replaying a model.
                        yield _sse_frame(
                            event="stream.reset",
                            data={
                                "schema_version": TURN_STREAM_SCHEMA_VERSION,
                                "type": "stream.reset",
                                "turn_id": str(turn_id),
                                "thread_id": thread_id,
                                "project_id": project_id,
                                "reason": "cancellation_acknowledged",
                                "rehydrate": "transcript",
                            },
                        )
                        return
                for row in fresh:
                    yield _event_frame(row)
                    last_seen = row.event_id
                    if _is_terminal_event(row):
                        return

        return StreamingResponse(_stream(), media_type="text/event-stream")

    # --- the thread stream (CRM trial 1, F2) ----------------------------------------------------

    @router.post("/projects/{project_id}/threads/{thread_id}/stream_token")
    async def mint_thread_token_route(
        project_id: str,
        thread_id: str,
        who: PrincipalDep,
    ) -> dict[str, JsonValue]:
        _require(who, PERMISSION_THREAD_READ)
        await _scope(who=who, project_id=project_id, thread_id=thread_id)
        async with conn_factory() as conn:
            token = await mint_stream_token(
                conn,
                workspace_id=who.workspace_id,
                subject_kind=AGENT_THREAD_SUBJECT_KIND,
                subject_id=thread_id,
                ttl_s=settings.chat_stream_token_ttl_s,
            )
        return {
            "data": {
                "schema_version": TURN_STREAM_SCHEMA_VERSION,
                "stream_token": str(token),
                "thread_id": thread_id,
            }
        }

    @router.get("/projects/{project_id}/threads/{thread_id}/events")
    async def thread_events_route(
        project_id: str,
        thread_id: str,
        who: PrincipalDep,
        stream_token: Annotated[str, Query()],
        last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        last_event_id_query: Annotated[int | None, Query(alias="last_event_id")] = None,
    ) -> StreamingResponse:
        _require(who, PERMISSION_THREAD_READ)
        await _scope(who=who, project_id=project_id, thread_id=thread_id)
        try:
            token = UUID(stream_token)
        except (AttributeError, TypeError, ValueError) as exc:
            raise _refuse(
                status_code=401,
                code="INVALID_STREAM_TOKEN",
                message="invalid stream token",
            ) from exc
        # A per-turn token never opens this stream: the consume statement requires
        # ``turn_id IS NULL``, and a token minted for another thread names another subject.
        async with conn_factory() as conn:
            consumed = await consume_stream_token(
                conn,
                token=token,
                workspace_id=who.workspace_id,
                subject_kind=AGENT_THREAD_SUBJECT_KIND,
                subject_id=thread_id,
            )
        if not consumed:
            raise _refuse(
                status_code=401,
                code="INVALID_STREAM_TOKEN",
                message="invalid or already-used stream token",
            )
        cursor: int | None = last_event_id_query
        if last_event_id_header is not None:
            with contextlib.suppress(ValueError):
                cursor = int(last_event_id_header)
        return StreamingResponse(
            thread_event_frames(
                conn_factory=conn_factory,
                settings=settings,
                workspace_id=who.workspace_id,
                project_id=project_id,
                thread_id=thread_id,
                cursor=cursor,
                live_tail=live_tail,
            ),
            media_type="text/event-stream",
        )

    # --- controls (§3.5) -----------------------------------------------------------------------

    @router.post("/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/stop", status_code=202)
    async def stop_turn_route(
        project_id: str,
        thread_id: str,
        turn_id: UUID,
        who: PrincipalDep,
    ) -> dict[str, JsonValue]:
        """Ask the worker to cancel this turn's active generation attempt.

        ``202``, never ``200``: this endpoint records a request, it does not perform a
        cancellation. The worker observes the row within its poll interval and cancels only the
        active attempt; committed tool effects and detached research runs are untouched (§3.5).
        A repeated stop is a replay of the same durable request, reported as ``already_requested``
        rather than pretending a second cancellation happened.
        """

        _require(who, PERMISSION_THREAD_WRITE)
        submission = await _scope(
            who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id
        )
        async with conn_factory() as conn:
            await lock_thread_queue(conn, workspace_id=who.workspace_id, thread_id=thread_id)
            await lock_turn_control(conn, workspace_id=who.workspace_id, turn_id=turn_id)
            existing = await get_control_request(
                conn,
                workspace_id=who.workspace_id,
                turn_id=turn_id,
                kind="stop",
            )
            if existing is not None:
                control, created = existing, False
            else:
                target = await thread_turn(
                    conn,
                    workspace_id=who.workspace_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
                finalized = await conn.scalar(
                    text(
                        "SELECT 1 FROM agent_finalization_commit "
                        "WHERE workspace_id=:workspace AND turn_id=:turn"
                    ),
                    {"workspace": who.workspace_id, "turn": turn_id},
                )
                if finalized or target is None or target.state != "running":
                    raise _refuse(
                        status_code=409,
                        code="TURN_NOT_RUNNING",
                        message="only the running turn can be stopped",
                    )
                control, created = await insert_control_request(
                    conn,
                    workspace_id=who.workspace_id,
                    project_id=submission.project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    kind="stop",
                    # Ambient authority, never a request field.
                    requested_by_user_id=who.user_id,
                    requested_via_membership_id=who.membership_id,
                )
                await hold_queue(
                    conn,
                    workspace_id=who.workspace_id,
                    thread_id=thread_id,
                    control_id=control.control_id,
                )
        return {
            "data": {
                "turn_id": str(turn_id),
                "control_id": str(control.control_id),
                "requested_at": control.requested_at.isoformat(),
                "already_requested": not created,
            }
        }

    @router.post("/projects/{project_id}/threads/{thread_id}/queue/resume", status_code=202)
    async def resume_queue_route(
        project_id: str,
        thread_id: str,
        body: ResumeQueueRequest,
        who: PrincipalDep,
    ) -> dict[str, JsonValue]:
        _require(who, PERMISSION_THREAD_WRITE)
        await _scope(who=who, project_id=project_id, thread_id=thread_id)
        try:
            async with conn_factory() as conn:
                receipt = await resume_queue(
                    conn,
                    workspace_id=who.workspace_id,
                    thread_id=thread_id,
                    hold_control_id=body.hold_control_id,
                    user_id=who.user_id,
                    membership_id=who.membership_id,
                )
        except QueueResumeConflict as error:
            raise _refuse(status_code=409, code=error.code, message=str(error)) from error
        return {"data": receipt}

    if artifacts is not None:

        @router.post(
            "/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/retry", status_code=202
        )
        async def retry_turn_route(
            project_id: str,
            thread_id: str,
            turn_id: UUID,
            who: PrincipalDep,
        ) -> TurnAcceptedResponse:
            """Ask the same question again as a **new** turn (§3.5's ``retry_of_turn_id``).

            The prior transcript is never mutated or overwritten: a retry re-captures the original
            message under a fresh, derived turn identity, records the durable link back to the turn
            it retries, and enters the same queue a typed message does. Retrying twice resolves to
            the retry that already exists, because the control row is insert-once per turn.
            """

            _require(who, PERMISSION_THREAD_WRITE)
            original = await _scope(
                who=who, project_id=project_id, thread_id=thread_id, turn_id=turn_id
            )
            retry_turn_id = turn_id_for_submission(
                workspace_id=who.workspace_id,
                thread_id=thread_id,
                idempotency_key=f"retry-of:{turn_id}",
            )
            async with conn_factory() as conn:
                existing = await get_control_request(
                    conn, workspace_id=who.workspace_id, turn_id=turn_id, kind="retry"
                )
                if existing is not None and existing.retry_turn_id is not None:
                    replayed = await get_submission(
                        conn, workspace_id=who.workspace_id, turn_id=existing.retry_turn_id
                    )
                    if replayed is not None:
                        await dispatch_next_thread_turn(
                            conn, workspace_id=who.workspace_id, thread_id=thread_id
                        )
                        return TurnAcceptedResponse(
                            data=TurnAcceptedWire(
                                turn_id=str(replayed.turn_id),
                                thread_id=thread_id,
                                requested_at=replayed.requested_at.isoformat(),
                                replayed=True,
                            )
                        )
                project = await get_project(conn, project_id)
                if project is None or project.workspace_id != who.workspace_id:
                    raise _refuse(
                        status_code=404,
                        code="PROJECT_NOT_FOUND",
                        message="no such project in this workspace",
                    )
                bodies = await hydrate_message_bodies(
                    conn,
                    storage=storage,  # type: ignore[arg-type]
                    workspace_id=who.workspace_id,
                    references=((original.message_artifact_key, original.message_sha256),),
                )
                body = bodies.get(original.message_artifact_key)
                if body is None or body.body is None:
                    raise _refuse(
                        status_code=409,
                        code="TURN_MESSAGE_UNAVAILABLE",
                        message=(
                            "the original message can no longer be read, so it cannot be retried"
                        ),
                    )
                captured = await persist_user_turn(
                    conn,
                    artifacts=artifacts,
                    workspace_id=who.workspace_id,
                    brand_id=project.brand_id,
                    product_id=project.product_id,
                    project_id=project_id,
                    turn_id=retry_turn_id,
                    message=body.body,
                    client_entity_id=await project_client_entity_id(
                        conn, workspace_id=who.workspace_id, project_id=project_id
                    ),
                )
                submission, _created = await insert_submission(
                    conn,
                    turn_id=retry_turn_id,
                    workspace_id=who.workspace_id,
                    project_id=project_id,
                    thread_id=thread_id,
                    submitted_by_user_id=who.user_id,
                    submitted_via_membership_id=who.membership_id,
                    onboarding_input_id=captured.onboarding_input_id,
                    message_artifact_key=captured.artifact_ref.artifact_key,
                    message_sha256=captured.artifact_ref.sha256,
                    idempotency_key=f"retry-of:{turn_id}",
                    context_refs=await submission_context_refs(
                        conn,
                        workspace_id=who.workspace_id,
                        turn_id=turn_id,
                    ),
                    agent_profile_id=original.agent_profile_id,
                )
                await insert_control_request(
                    conn,
                    workspace_id=who.workspace_id,
                    project_id=project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    kind="retry",
                    requested_by_user_id=who.user_id,
                    requested_via_membership_id=who.membership_id,
                    retry_turn_id=retry_turn_id,
                )
                await dispatch_next_thread_turn(
                    conn, workspace_id=who.workspace_id, thread_id=thread_id
                )
            return TurnAcceptedResponse(
                data=TurnAcceptedWire(
                    turn_id=str(submission.turn_id),
                    thread_id=thread_id,
                    requested_at=submission.requested_at.isoformat(),
                    replayed=False,
                )
            )

    return router


def install_chat_stream_surface(
    app: FastAPI,
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    storage: StorageBackend | None = None,
    live_tail: bool = True,
) -> None:
    """Mount the turn-stream router when ``settings.chat_enabled``; otherwise do nothing at all.

    No principal resolver is installed here on purpose: these routes declare the *same* dependency
    the chat surface does, so whichever resolver that surface installed — Lane B's authorizer in
    production, the guarded development one locally — governs them too. A stream surface mounted
    without a chat surface therefore refuses every request rather than serving anybody.
    """

    if not settings.chat_enabled:
        return
    app.include_router(
        build_chat_stream_router(
            settings=settings,
            conn_factory=conn_factory,
            storage=storage,
            live_tail=live_tail,
        )
    )
