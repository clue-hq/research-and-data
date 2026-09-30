"""Thread and thread-message read projections (REQ-21 / FI Lane D D0).

Two paginated surfaces:

* :func:`threads_for_project` — the project's thread list the sidebar hierarchy renders.
* :func:`thread_messages` — the **cold-load** transcript surface charter §3.6 requires: "initial /
  cold load comes from paginated durable messages … not replaying the entire SSE history". Each
  message summary is body-free (the body stays in its content-addressed artifact) and carries the
  typed :mod:`~clue_projections.thread_refs` ``refs[]`` REQ-21 specifies.

Read-only, like everything in this package, and workspace-scoped in SQL on every statement: a
cross-workspace read returns an empty page, never another tenant's row.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import ConnFactory, transaction
from clue_projections.pagination import InvalidCursorError, decode_cursor, encode_cursor
from clue_projections.thread_refs import (
    ARTIFACT_OBJECT_TYPE,
    MessageObjectRef,
    MessageRefFlavor,
    flavors_for_message_role,
)

__all__ = [
    "AGENT_TURN_TASK_DEDUP_PREFIX",
    "DEFAULT_THREAD_PAGE_SIZE",
    "DEFAULT_THREAD_MESSAGE_PAGE_SIZE",
    "MAX_THREAD_PAGE_SIZE",
    "MAX_THREAD_MESSAGE_PAGE_SIZE",
    "DEFAULT_PROJECT_SIDEBAR_PAGE_SIZE",
    "MAX_PROJECT_SIDEBAR_PAGE_SIZE",
    "ProjectSidebarPage",
    "ProjectSidebarProjectView",
    "ThreadMessagePage",
    "ThreadMessageSummary",
    "ThreadPage",
    "ThreadTurnView",
    "ThreadView",
    "thread_messages",
    "thread_turn",
    "thread_turns",
    "project_sidebar_page",
    "threads_for_project",
    "threads_running",
]

DEFAULT_THREAD_PAGE_SIZE = 50
MAX_THREAD_PAGE_SIZE = 200
DEFAULT_THREAD_MESSAGE_PAGE_SIZE = 50
MAX_THREAD_MESSAGE_PAGE_SIZE = 200
DEFAULT_PROJECT_SIDEBAR_PAGE_SIZE = 50
MAX_PROJECT_SIDEBAR_PAGE_SIZE = 100

#: The ``fleet_task.dedup_key`` prefix one ``AGENT_TURN`` task is named by. It is *authored* in
#: ``clue_api.agent_turn_submission``; this package may not import that one (projections import no
#: composition root), so the value is restated here and a test asserts the two never drift. A
#: silently divergent prefix would make every turn look permanently queued.
AGENT_TURN_TASK_DEDUP_PREFIX = "agent-turn:"


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ThreadView(_View):
    """One thread's shell state. Body-free: it says nothing about what was said in the thread."""

    thread_id: str
    project_id: str
    title: str | None
    status: str
    pinned: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ThreadPage(_View):
    items: tuple[ThreadView, ...]
    next_cursor: str | None = None


class ProjectSidebarProjectView(_View):
    """One workspace project and its batch-hydrated thread summaries.

    ``updated_at`` is the composite ``GREATEST(project.updated_at, MAX(active thread.updated_at))``
    the project directory sorts by (spec 2026-09-19 §2.3) — the same expression, deliberately, so
    the rail and the directory can never present the same workspace in two different orders.
    """

    project_id: str
    title: str
    pinned: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime
    threads: tuple[ThreadView, ...]


class ProjectSidebarPage(_View):
    items: tuple[ProjectSidebarProjectView, ...]
    next_cursor: str | None = None


class ThreadTurnView(_View):
    """One turn of a thread — the **submissions-union** the ratified two-phase identity requires.

    After D2's accepted deviation a turn's identity lands in two halves: the
    ``agent_turn_submission`` row the HTTP route writes before it enqueues anything, and the
    ``agent_turn`` row the worker writes once it has an execution. A read surface built on
    ``agent_turn`` alone therefore cannot see a *queued* turn at all — the exact turns a user most
    wants to see, because they are the ones that have not answered yet. So this view is anchored on
    the submission and enriched with whatever execution evidence exists: the turn's own terminal
    event, or its fleet task's state.

    ``state`` is derived, never stored:

    * ``queued`` — a submission with no execution evidence yet;
    * ``running`` — its generation has started (a ``turn.started`` frame) or its task is claimed;
    * ``completed`` / ``awaiting_input`` / ``failed`` / ``cancelled`` — its terminal turn event, or,
      when the stream frames have been pruned, the terminal state of its fleet task.
    """

    turn_id: UUID
    thread_id: str
    project_id: str
    state: str
    requested_at: AwareDatetime
    submitted_by_user_id: str
    message_artifact_key: str
    message_sha256: str
    #: The stream cursor a client should attach after, when frames for this turn still exist.
    last_event_id: int | None = None
    generation_attempts: int = 0
    #: Spec 2026-09-20 §2.2: set when the server made this turn from the user's own bytes; the
    #: client renders no user bubble for it.
    derivation: str | None = None


class ThreadMessageSummary(_View):
    """One durable thread message, body-free.

    ``body_artifact_key``/``body_sha256`` are the exact content address of the body; resolving it is
    a separate, permissioned read. ``refs`` is REQ-21's typed object-ref list, projected from the
    turn's durable receipts by :mod:`clue_projections.thread_refs`'s attribution rule.
    """

    message_id: UUID
    turn_id: UUID
    sequence: int = Field(ge=1)
    role: str
    body_artifact_key: str
    body_sha256: str
    created_at: AwareDatetime
    refs: tuple[MessageObjectRef, ...] = ()


class ThreadMessagePage(_View):
    items: tuple[ThreadMessageSummary, ...]
    next_cursor: str | None = None


# --- thread listing ---------------------------------------------------------------------------

_PAGE_THREADS = text(
    """
    SELECT id, project_id, title, status, pinned, created_at, updated_at
    FROM agent_thread
    WHERE workspace_id = :workspace_id
      AND project_id = :project_id
      -- Only conversations a person started. Machine threads (research runs, onboarding
      -- synthesis) are created with no user and are never a chat in any listing.
      AND created_by_user_id IS NOT NULL
      AND (CAST(:status AS text) IS NULL OR status = :status)
      AND (
          CAST(:cursor_created_at AS timestamptz) IS NULL
          OR (created_at, id) > (:cursor_created_at, CAST(:cursor_id AS text))
      )
    ORDER BY created_at, id
    LIMIT :row_limit
    """
)


async def threads_for_project(
    *,
    workspace_id: str,
    project_id: str,
    status: str | None = None,
    limit: int = DEFAULT_THREAD_PAGE_SIZE,
    cursor: str | None = None,
    conn_factory: ConnFactory = transaction,
) -> ThreadPage:
    """One keyset page of a project's threads, oldest first.

    ``status=None`` lists active *and* archived threads; the surface passes ``'active'`` for the
    default sidebar view. Archiving hides history, so the filter is a view choice, not a deletion.
    """

    if not 1 <= limit <= MAX_THREAD_PAGE_SIZE:
        raise ValueError(f"thread page size must be between 1 and {MAX_THREAD_PAGE_SIZE}")
    cursor_created_at: datetime | None = None
    cursor_id: str | None = None
    if cursor is not None:
        position, cursor_id = decode_cursor(cursor, parts=2)
        cursor_created_at = _parse_timestamp(position)
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _PAGE_THREADS,
                    {
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "status": status,
                        "cursor_created_at": cursor_created_at,
                        "cursor_id": cursor_id,
                        "row_limit": limit + 1,
                    },
                )
            )
            .mappings()
            .all()
        )
    has_more = len(rows) > limit
    items = tuple(
        ThreadView(
            thread_id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            status=row["status"],
            pinned=bool(row["pinned"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows[:limit]
    )
    next_cursor = (
        encode_cursor(items[-1].created_at.isoformat(), items[-1].thread_id)
        if has_more and items
        else None
    )
    return ThreadPage(items=items, next_cursor=next_cursor)


_PROJECT_SIDEBAR_PAGE = text(
    """
    WITH activity AS (
        -- An archived conversation is not activity, exactly as the directory read defines it
        -- (clue_projections.projects._ITEM_SELECT); the two composites must agree row for row.
        SELECT t.project_id,
               MAX(t.updated_at) FILTER (WHERE t.status = 'active') AS last_thread_at
        FROM agent_thread t
        WHERE t.workspace_id = :workspace_id
          AND t.created_by_user_id IS NOT NULL
        GROUP BY t.project_id
    ),
    selected_projects AS MATERIALIZED (
        SELECT p.project_id,
               p.name,
               p.created_at,
               p.pinned,
               GREATEST(p.updated_at, COALESCE(a.last_thread_at, p.updated_at)) AS updated_at
        FROM project p
        LEFT JOIN activity a ON a.project_id = p.project_id
        WHERE p.workspace_id = :workspace_id
          -- Archiving a project takes it out of the rail entirely (O6), and a system scope
          -- anchor never enters it. Both filters belong here rather than in the client so the
          -- page cursor never has to step over rows nobody may see.
          AND p.status = 'active'
          AND p.kind = 'marketing'
          AND (
              CAST(:cursor_pinned AS boolean) IS NULL
              OR (
                     p.pinned,
                     GREATEST(p.updated_at, COALESCE(a.last_thread_at, p.updated_at)),
                     p.project_id
                 )
                 < (CAST(:cursor_pinned AS boolean), CAST(:cursor_updated_at AS timestamptz),
                    CAST(:cursor_project_id AS text))
          )
        ORDER BY p.pinned DESC, updated_at DESC, p.project_id DESC
        LIMIT :row_limit
    )
    SELECT
        p.project_id,
        p.name AS project_title,
        p.created_at AS project_created_at,
        p.pinned AS project_pinned,
        p.updated_at AS project_updated_at,
        t.id AS thread_id,
        t.title AS thread_title,
        t.status AS thread_status,
        t.pinned AS thread_pinned,
        t.created_at AS thread_created_at,
        t.updated_at AS thread_updated_at
    FROM selected_projects p
    LEFT JOIN agent_thread t
      ON t.workspace_id = :workspace_id
     AND t.project_id = p.project_id
     AND t.created_by_user_id IS NOT NULL
    ORDER BY
        p.pinned DESC,
        p.updated_at DESC,
        p.project_id DESC,
        t.pinned DESC NULLS LAST,
        t.updated_at DESC NULLS LAST,
        t.id DESC NULLS LAST
    """
)


async def project_sidebar_page(
    *,
    workspace_id: str,
    limit: int = DEFAULT_PROJECT_SIDEBAR_PAGE_SIZE,
    cursor: str | None = None,
    conn_factory: ConnFactory = transaction,
) -> ProjectSidebarPage:
    """One page of the rail: the workspace's marketing projects, pinned first then most recently
    active, each with all its thread summaries, in one SQL read.

    The order is the project directory's order (spec 2026-09-19 §2.3) — same pin flag, same
    composite ``updated_at``, same tiebreak — because the rail and the directory show the same
    workspace and may never disagree about which project is on top.

    The project limit is applied inside the CTE, before the thread join, so a
    project with many conversations cannot crowd another project out of the
    page. Thread hydration is one batch query for the whole page; gate and busy
    status are separate whole-page batch reads at the HTTP composition layer.

    The cursor carries the whole sort key — the pin flag, the composite ``updated_at`` and the
    project id — so a project that is pinned (or whose newest conversation moves) between two page
    reads still pages deterministically instead of repeating or skipping rows.
    """

    if not 1 <= limit <= MAX_PROJECT_SIDEBAR_PAGE_SIZE:
        raise ValueError(
            f"project sidebar page size must be between 1 and {MAX_PROJECT_SIDEBAR_PAGE_SIZE}"
        )
    cursor_pinned: bool | None = None
    cursor_updated_at: datetime | None = None
    cursor_project_id: str | None = None
    if cursor is not None:
        pinned_part, position, cursor_project_id = decode_cursor(cursor, parts=3)
        if pinned_part not in ("0", "1"):
            raise InvalidCursorError("sidebar cursor pinned flag must be 0 or 1")
        cursor_pinned = pinned_part == "1"
        cursor_updated_at = _parse_timestamp(position)

    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _PROJECT_SIDEBAR_PAGE,
                    {
                        "workspace_id": workspace_id,
                        "cursor_pinned": cursor_pinned,
                        "cursor_updated_at": cursor_updated_at,
                        "cursor_project_id": cursor_project_id,
                        "row_limit": limit + 1,
                    },
                )
            )
            .mappings()
            .all()
        )

    project_order: list[str] = []
    project_rows: dict[str, dict[str, object]] = {}
    threads: dict[str, list[ThreadView]] = {}
    for row in rows:
        project_id = str(row["project_id"])
        if project_id not in project_rows:
            project_order.append(project_id)
            project_rows[project_id] = dict(row)
            threads[project_id] = []
        if row["thread_id"] is not None:
            threads[project_id].append(
                ThreadView(
                    thread_id=str(row["thread_id"]),
                    project_id=project_id,
                    title=row["thread_title"],
                    status=str(row["thread_status"]),
                    pinned=bool(row["thread_pinned"]),
                    created_at=row["thread_created_at"],
                    updated_at=row["thread_updated_at"],
                )
            )

    has_more = len(project_order) > limit
    selected_ids = project_order[:limit]
    items = tuple(
        ProjectSidebarProjectView(
            project_id=project_id,
            title=str(project_rows[project_id]["project_title"]),
            pinned=bool(project_rows[project_id]["project_pinned"]),
            created_at=cast(datetime, project_rows[project_id]["project_created_at"]),
            updated_at=cast(datetime, project_rows[project_id]["project_updated_at"]),
            threads=tuple(threads[project_id]),
        )
        for project_id in selected_ids
    )
    next_cursor = (
        encode_cursor(
            "1" if items[-1].pinned else "0",
            items[-1].updated_at.isoformat(),
            items[-1].project_id,
        )
        if has_more and items
        else None
    )
    return ProjectSidebarPage(items=items, next_cursor=next_cursor)


# --- the submissions-union ---------------------------------------------------------------------

# One statement, anchored on the submission (the durable half that always exists) and enriched by
# two lateral reads: the turn's stream frames, and its fleet task. Both are LEFT joins because both
# are legitimately absent — a queued turn has neither, and a turn whose frames were pruned past the
# retention window still has its task.
_TURN_UNION_SELECT = """
    SELECT
        s.turn_id,
        s.thread_id,
        s.project_id,
        s.requested_at,
        s.submitted_by_user_id,
        s.message_artifact_key,
        s.message_sha256,
        s.derivation,
        e.terminal_event,
        e.started,
        e.last_event_id,
        e.attempts,
        j.status AS journal_status,
        c.control_id AS stop_control_id,
        ack.acknowledged_at AS stop_acknowledged_at,
        f.status AS task_status
    FROM agent_turn_submission s
    LEFT JOIN agent_turn_control_request c ON c.workspace_id=s.workspace_id
      AND c.turn_id=s.turn_id AND c.kind='stop'
    LEFT JOIN agent_turn_stop_ack ack ON ack.control_id=c.control_id
    LEFT JOIN LATERAL (
        SELECT
            max(event_id) AS last_event_id,
            count(DISTINCT generation_attempt_id) AS attempts,
            bool_or(event_type = 'turn.started') AS started,
            (ARRAY_REMOVE(ARRAY_AGG(
                CASE WHEN event_type IN ('turn.completed', 'turn.failed', 'turn.cancelled',
                                         'turn.awaiting_input')
                     THEN event_type END
                ORDER BY event_id DESC), NULL))[1] AS terminal_event
        FROM agent_turn_event_stream v
        WHERE v.workspace_id = s.workspace_id AND v.turn_id = s.turn_id
    ) e ON TRUE
    LEFT JOIN LATERAL (
        SELECT v.status
        FROM agent_turn_event v
        WHERE v.workspace_id = s.workspace_id AND v.turn_id = s.turn_id
        ORDER BY v.seq DESC
        LIMIT 1
    ) j ON TRUE
    LEFT JOIN LATERAL (
        SELECT t.status
        FROM fleet_task t
        WHERE t.kind = CAST('agent_turn' AS fleet_task_kind)
          AND t.dedup_key = :dedup_prefix || s.turn_id::text
        LIMIT 1
    ) f ON TRUE
    WHERE s.workspace_id = :workspace_id
"""

_THREAD_TURNS = text(
    f"{_TURN_UNION_SELECT} AND s.thread_id = :thread_id "
    "ORDER BY s.requested_at, s.turn_id LIMIT :row_limit"
)

_THREAD_TURN = text(
    f"{_TURN_UNION_SELECT} AND s.thread_id = :thread_id AND s.turn_id = :turn_id LIMIT 1"
)

# "Which of these threads is busy?" — the same union, reduced to a per-thread boolean, so the
# thread listing answers it in one statement instead of one per row.
_THREADS_RUNNING = text(
    f"""
    SELECT u.thread_id
    FROM ({_TURN_UNION_SELECT} AND s.thread_id = ANY(CAST(:thread_ids AS text[]))) u
    WHERE u.terminal_event IS NULL
      AND u.stop_acknowledged_at IS NULL
      AND (u.task_status IS NULL OR u.task_status NOT IN ('done', 'failed'))
    GROUP BY u.thread_id
    UNION
    SELECT launched_thread_id
    FROM arv2_discovery_run
    WHERE workspace_id = :workspace_id
      AND launched_thread_id = ANY(CAST(:thread_ids AS text[]))
      AND released_at IS NULL
    """
)

#: ``turn.<x>`` event → the ``state`` a turn view reports.
_TERMINAL_STATES: dict[str, str] = {
    "turn.completed": "completed",
    "turn.failed": "failed",
    "turn.cancelled": "cancelled",
    "turn.awaiting_input": "awaiting_input",
}


def _turn_state(row: dict[str, object]) -> str:
    if row.get("stop_acknowledged_at") is not None:
        return "cancelled"
    if row.get("stop_control_id") is not None:
        return "running"
    terminal = row.get("terminal_event")
    if terminal is not None:
        return _TERMINAL_STATES.get(str(terminal), "completed")
    journal_status = str(row.get("journal_status") or "")
    if journal_status in {"completed", "awaiting_input", "failed", "cancelled"}:
        return journal_status
    if journal_status in {"abandoned", "privacy_tombstoned"}:
        return "failed"
    task_status = row.get("task_status")
    if task_status in {"done", "failed"}:
        # The frames aged out of the outbox but the task remembers. Reporting ``queued`` here would
        # resurrect a finished turn every time retention caught up with it.
        return "completed" if task_status == "done" else "failed"
    if bool(row.get("started")) or task_status == "claimed":
        return "running"
    return "queued"


def _thread_turn_view(row: dict[str, object]) -> ThreadTurnView:
    return ThreadTurnView(
        turn_id=UUID(str(row["turn_id"])),
        thread_id=str(row["thread_id"]),
        project_id=str(row["project_id"]),
        state=_turn_state(row),
        requested_at=cast(datetime, row["requested_at"]),
        submitted_by_user_id=str(row["submitted_by_user_id"]),
        message_artifact_key=str(row["message_artifact_key"]),
        message_sha256=str(row["message_sha256"]),
        last_event_id=(None if row["last_event_id"] is None else int(str(row["last_event_id"]))),
        generation_attempts=int(str(row["attempts"] or 0)),
        derivation=(None if row.get("derivation") is None else str(row["derivation"])),
    )


async def thread_turn(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    turn_id: UUID,
) -> ThreadTurnView | None:
    """Read one turn's derived state inside the caller's transaction.

    State-sensitive writes such as Stop must use the same submissions-union
    derivation as the list surface. Taking the caller's connection keeps the
    check and the resulting control receipt in one transaction without copying
    the projection SQL into the write layer.
    """

    row = (
        (
            await conn.execute(
                _THREAD_TURN,
                {
                    "workspace_id": workspace_id,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "dedup_prefix": AGENT_TURN_TASK_DEDUP_PREFIX,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _thread_turn_view(dict(row))


async def thread_turns(
    *,
    workspace_id: str,
    thread_id: str,
    limit: int = MAX_THREAD_PAGE_SIZE,
    conn_factory: ConnFactory = transaction,
) -> tuple[ThreadTurnView, ...]:
    """Every turn of one thread in submission order — queued ones included.

    Read-only and workspace-scoped in SQL, like everything here. Bounded by ``limit`` rather than
    paginated: a thread's *turn* count is small (its messages are the thing that grows), and the
    caller that needs a page of history reads :func:`thread_messages`.
    """

    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _THREAD_TURNS,
                    {
                        "workspace_id": workspace_id,
                        "thread_id": thread_id,
                        "dedup_prefix": AGENT_TURN_TASK_DEDUP_PREFIX,
                        "row_limit": limit,
                    },
                )
            )
            .mappings()
            .all()
        )
    return tuple(_thread_turn_view(dict(row)) for row in rows)


async def threads_running(
    *,
    workspace_id: str,
    thread_ids: Sequence[str],
    conn_factory: ConnFactory = transaction,
) -> frozenset[str]:
    """Which of ``thread_ids`` hold a turn that is queued or executing (the ``running`` badge).

    One statement for a whole page of threads. "Queued" counts as running on purpose: from the
    user's side a turn they submitted thirty seconds ago that has not been claimed yet is the
    conversation working, not the conversation idle. A thread whose discovery run is unreleased is
    running too (spec 2026-09-30 §5): it holds every message until the run's wake turn finishes.
    """

    if not thread_ids:
        return frozenset()
    async with conn_factory() as conn:
        rows = (
            await conn.execute(
                _THREADS_RUNNING,
                {
                    "workspace_id": workspace_id,
                    "thread_ids": list(thread_ids),
                    "dedup_prefix": AGENT_TURN_TASK_DEDUP_PREFIX,
                },
            )
        ).scalars()
    return frozenset(str(value) for value in rows)


def _parse_timestamp(position: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(position)
    except ValueError as exc:
        raise InvalidCursorError("cursor is not a value this endpoint issued") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# --- messages ----------------------------------------------------------------------------------

# Keyset over the per-thread ``sequence``, which is already UNIQUE (workspace_id, thread_id,
# sequence) and gap-free by construction — so it is a total order on its own and needs no tiebreak.
#
# Newest-first page *selection* (Slice C C5): the first page is the tail of the thread, and the
# cursor is a *before*-key naming the preceding page — ``sequence < cursor`` walking backward.
# Rows come back descending and are reversed in Python, so within any page the display order is
# ascending, identical to the old read for a thread under one page.
_PAGE_MESSAGES = text(
    """
    SELECT id, turn_id, sequence, role, body_artifact_key, body_sha256, created_at
    FROM agent_thread_message
    WHERE workspace_id = :workspace_id
      AND thread_id = :thread_id
      AND (CAST(:cursor_sequence AS bigint) IS NULL OR sequence < CAST(:cursor_sequence AS bigint))
    ORDER BY sequence DESC
    LIMIT :row_limit
    """
)

# The turn-scoped artifact refs whose ``ref_role`` is a message ref flavor. ``owner_kind``/
# ``owner_id`` stay out of the projection: the flavor plus the turn is the whole attribution rule.
_ARTIFACT_REFS = text(
    """
    SELECT turn_id, ref_role, ordinal, artifact_key
    FROM agent_artifact_ref
    WHERE workspace_id = :workspace_id
      AND turn_id = ANY(CAST(:turn_ids AS uuid[]))
      AND ref_role = ANY(CAST(:roles AS text[]))
    ORDER BY turn_id, ref_role, ordinal
    """
)

# The finalization's domain refs — the objects the turn produced, and the gate it is waiting on.
_FINALIZATION_REFS = text(
    """
    SELECT f.turn_id, r.ref_role, r.ordinal, r.object_type, r.object_id, r.object_version
    FROM agent_finalization_domain_ref r
    JOIN agent_finalization f
      ON f.id = r.finalization_id AND f.workspace_id = r.workspace_id
    WHERE r.workspace_id = :workspace_id
      AND f.turn_id = ANY(CAST(:turn_ids AS uuid[]))
    ORDER BY f.turn_id, r.ref_role, r.ordinal
    """
)

_SUBMISSION_CONTEXT_REFS = text(
    """
    SELECT turn_id, ordinal, object_type, object_id, object_version
    FROM agent_turn_submission_context_ref
    WHERE workspace_id = :workspace_id
      AND turn_id = ANY(CAST(:turn_ids AS uuid[]))
    ORDER BY turn_id, ordinal
    """
)

_ARTIFACT_REF_ROLES: tuple[str, ...] = (
    MessageRefFlavor.ATTACHMENT.value,
    MessageRefFlavor.NEXT_ACTION.value,
    MessageRefFlavor.ASSUMPTION.value,
    MessageRefFlavor.WORKSPACE_OUTPUT.value,
)


async def _refs_by_turn(
    conn: AsyncConnection, *, workspace_id: str, turn_ids: tuple[UUID, ...]
) -> dict[UUID, tuple[MessageObjectRef, ...]]:
    """Batch every candidate ref for a page of messages, never one statement per message."""

    if not turn_ids:
        return {}
    ids = [str(value) for value in turn_ids]
    collected: dict[UUID, list[MessageObjectRef]] = {}
    artifact_rows = (
        await conn.execute(
            _ARTIFACT_REFS,
            {"workspace_id": workspace_id, "turn_ids": ids, "roles": list(_ARTIFACT_REF_ROLES)},
        )
    ).mappings()
    for row in artifact_rows:
        collected.setdefault(row["turn_id"], []).append(
            MessageObjectRef(
                flavor=MessageRefFlavor(row["ref_role"]),
                workspace_id=workspace_id,
                object_type=ARTIFACT_OBJECT_TYPE,
                object_id=row["artifact_key"],
                version=None,
                ordinal=int(row["ordinal"]),
            )
        )
    context_rows = (
        await conn.execute(
            _SUBMISSION_CONTEXT_REFS,
            {"workspace_id": workspace_id, "turn_ids": ids},
        )
    ).mappings()
    for row in context_rows:
        collected.setdefault(row["turn_id"], []).append(
            MessageObjectRef(
                flavor=MessageRefFlavor.CONTEXT,
                workspace_id=workspace_id,
                object_type=row["object_type"],
                object_id=row["object_id"],
                version=(None if row["object_version"] is None else int(row["object_version"])),
                ordinal=int(row["ordinal"]),
            )
        )
    finalization_rows = (
        await conn.execute(_FINALIZATION_REFS, {"workspace_id": workspace_id, "turn_ids": ids})
    ).mappings()
    for row in finalization_rows:
        collected.setdefault(row["turn_id"], []).append(
            MessageObjectRef(
                flavor=MessageRefFlavor(row["ref_role"]),
                workspace_id=workspace_id,
                object_type=row["object_type"],
                object_id=row["object_id"],
                version=(None if row["object_version"] is None else int(row["object_version"])),
                ordinal=int(row["ordinal"]),
            )
        )
    return {turn_id: tuple(refs) for turn_id, refs in collected.items()}


async def thread_messages(
    *,
    workspace_id: str,
    thread_id: str,
    limit: int = DEFAULT_THREAD_MESSAGE_PAGE_SIZE,
    cursor: str | None = None,
    conn_factory: ConnFactory = transaction,
) -> ThreadMessagePage:
    """One keyset page of a thread's durable messages, **newest page first**, with typed ``refs[]``.

    Slice C C5's read direction: with no cursor this serves the *latest* ``limit`` messages —
    in ascending display order within the page — because the defect the flip fixes was a long
    thread whose reload served the oldest 50 and lost the user's most recent prompts.
    ``next_cursor`` is a *before*-cursor: passing it back serves the preceding (older) page, and
    ``None`` means history is exhausted. A thread at or under one page is served whole, ascending,
    with no cursor — byte-identical to the pre-flip read.

    Raises :class:`~clue_projections.pagination.InvalidCursorError` for a foreign cursor and
    ``ValueError`` for an out-of-range ``limit``.
    """

    if not 1 <= limit <= MAX_THREAD_MESSAGE_PAGE_SIZE:
        raise ValueError(f"message page size must be between 1 and {MAX_THREAD_MESSAGE_PAGE_SIZE}")
    cursor_sequence: int | None = None
    if cursor is not None:
        (position,) = decode_cursor(cursor, parts=1)
        try:
            cursor_sequence = int(position)
        except ValueError as exc:
            raise InvalidCursorError("cursor is not a value this endpoint issued") from exc
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _PAGE_MESSAGES,
                    {
                        "workspace_id": workspace_id,
                        "thread_id": thread_id,
                        "cursor_sequence": cursor_sequence,
                        "row_limit": limit + 1,
                    },
                )
            )
            .mappings()
            .all()
        )
        has_more = len(rows) > limit
        # Selected newest-first; reversed so the page reads in ascending display order.
        page = list(reversed(rows[:limit]))
        refs = await _refs_by_turn(
            conn,
            workspace_id=workspace_id,
            turn_ids=tuple({row["turn_id"] for row in page}),
        )
    items = tuple(
        ThreadMessageSummary(
            message_id=row["id"],
            turn_id=row["turn_id"],
            sequence=int(row["sequence"]),
            role=row["role"],
            body_artifact_key=row["body_artifact_key"],
            body_sha256=row["body_sha256"],
            created_at=row["created_at"],
            # The attribution rule (thread_refs): a turn's user message carries the turn's
            # attachments, its assistant message carries what the turn produced or awaits.
            refs=tuple(
                ref
                for ref in refs.get(row["turn_id"], ())
                if ref.flavor in flavors_for_message_role(row["role"])
            ),
        )
        for row in page
    )
    # The before-cursor is the page's *oldest* row: older history continues below it.
    next_cursor = encode_cursor(str(items[0].sequence)) if has_more and items else None
    return ThreadMessagePage(items=items, next_cursor=next_cursor)
