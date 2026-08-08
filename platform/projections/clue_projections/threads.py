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

from datetime import UTC, datetime
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
    "DEFAULT_THREAD_PAGE_SIZE",
    "DEFAULT_THREAD_MESSAGE_PAGE_SIZE",
    "MAX_THREAD_PAGE_SIZE",
    "MAX_THREAD_MESSAGE_PAGE_SIZE",
    "ThreadMessagePage",
    "ThreadMessageSummary",
    "ThreadPage",
    "ThreadView",
    "thread_messages",
    "threads_for_project",
]

DEFAULT_THREAD_PAGE_SIZE = 50
MAX_THREAD_PAGE_SIZE = 200
DEFAULT_THREAD_MESSAGE_PAGE_SIZE = 50
MAX_THREAD_MESSAGE_PAGE_SIZE = 200


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


def _parse_timestamp(position: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(position)
    except ValueError as exc:
        raise InvalidCursorError("cursor is not a value this endpoint issued") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# --- messages ----------------------------------------------------------------------------------

# Keyset over the per-thread ``sequence``, which is already UNIQUE (workspace_id, thread_id,
# sequence) and gap-free by construction — so it is a total order on its own and needs no tiebreak.
_PAGE_MESSAGES = text(
    """
    SELECT id, turn_id, sequence, role, body_artifact_key, body_sha256, created_at
    FROM agent_thread_message
    WHERE workspace_id = :workspace_id
      AND thread_id = :thread_id
      AND (CAST(:cursor_sequence AS bigint) IS NULL OR sequence > CAST(:cursor_sequence AS bigint))
    ORDER BY sequence
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

_ARTIFACT_REF_ROLES: tuple[str, ...] = (
    MessageRefFlavor.ATTACHMENT.value,
    MessageRefFlavor.NEXT_ACTION.value,
    MessageRefFlavor.ASSUMPTION.value,
    MessageRefFlavor.WORKSPACE_OUTPUT.value,
)


async def _refs_by_turn(
    conn: AsyncConnection, *, workspace_id: str, turn_ids: tuple[UUID, ...]
) -> dict[UUID, tuple[MessageObjectRef, ...]]:
    """Batch every candidate ref for a page of messages — two statements, not one per message."""

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
    """One keyset page of a thread's durable messages, oldest first, with typed ``refs[]``.

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
        page = rows[:limit]
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
    next_cursor = encode_cursor(str(items[-1].sequence)) if has_more and items else None
    return ThreadMessagePage(items=items, next_cursor=next_cursor)
