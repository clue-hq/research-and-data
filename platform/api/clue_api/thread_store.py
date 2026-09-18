"""The durable ``agent_thread`` row and its CRUD (FI Lane D slice D0 / REQ-21).

A **thread** is the conversation shell a project's turns and messages hang from. It is the one
piece of the agent plane that is deliberately *mutable*: a title is renamed, a thread is pinned and
unpinned, a thread is archived. Everything that records **what happened** inside a thread — turns,
messages, context receipts, model calls, finalizations — stays in the 13 append-only C6 tables,
which this module never writes.

Written in the repo's raw-SQL, ceremony-free style (``clue_spine/spine.py``): frozen row models and
plain async functions over an ``AsyncConnection``. There is no repository/protocol layer because
exactly one implementation will ever exist. Invalid states are impossible **by schema** (the
composite project FK pins a thread to a project *in its own workspace*; the status CHECK closes the
vocabulary), so a constraint violation surfaces as a raw
:class:`sqlalchemy.exc.IntegrityError` — deliberately not caught here.

**Ownership columns carry Clue-owned internal ids only.** ``created_by_user_id`` is a
``platform_user.user_id`` and ``created_via_membership_id`` a ``workspace_membership.membership_id``
(`FI-lane-B-authenticated-principal-contract.md` §§1.2–1.3). No provider (Clerk) subject, session,
organization, or email may ever be written to either. Both are nullable, for two distinct honest
reasons:

* a **platform-originated** thread (the stage-0 trial harness, an entity-research fleet unit, a
  specialist delegation) has no human creator at all, and inventing one would be the fabricated
  identity Lane B ruling 8 forbids; and
* ``created_via_membership_id`` additionally stays ``NULL`` for human-created threads until Lane B's
  B4 slice carries the membership through the ``ToolContext`` seam — the alternative, accepting it
  as a tool input, would put an authorization identity into a model-visible schema, which Lane B
  ruling 7 forbids outright.
"""

from __future__ import annotations

from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import OperationId, UtcDatetime

__all__ = [
    "AgentThreadRow",
    "ThreadOwnershipMismatch",
    "ThreadStatus",
    "create_thread",
    "ensure_platform_thread",
    "get_thread",
    "new_thread_id",
    "set_thread_pinned",
    "set_thread_status",
    "set_thread_title",
    "set_thread_title_if_unset",
    "thread_id_for_operation",
]

ThreadStatus = Literal["active", "archived"]


class ThreadOwnershipMismatch(RuntimeError):
    """A thread id resolves to a row owned by a different workspace/project than the caller's.

    Typed (not a bare ``ValueError``) because callers must be able to distinguish "this turn cannot
    be journaled — its thread belongs to somebody else" from any other write failure, and because
    the ``reason_code`` is the stable string a surface maps to its refusal envelope. The message
    deliberately names neither the surviving workspace nor the surviving project: a caller who
    guessed an id must not learn whose it is.
    """

    def __init__(self, *, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_COLUMNS = (
    "id, workspace_id, project_id, created_by_user_id, created_via_membership_id, "
    "status, pinned, title, created_at, updated_at"
)


def new_thread_id() -> str:
    """Mint an opaque thread id (the platform's prefixed-uuid4-hex convention over text keys)."""

    return "thr_" + uuid4().hex


def thread_id_for_operation(*, workspace_id: str, operation_id: OperationId) -> str:
    """Derive the thread id a *logical operation* creates.

    Deriving rather than minting is what makes ``create_thread@1`` operation-idempotent: a retry of
    the same logical operation lands on the same row and the ``ON CONFLICT`` in
    :func:`create_thread` turns the second attempt into a replay rather than a second thread. The
    workspace is in the digest so two tenants can never collide even on a shared operation id.
    """

    return "thr_" + uuid5(NAMESPACE_URL, f"clue-agent-thread:{workspace_id}:{operation_id}").hex


class AgentThreadRow(BaseModel):
    """One ``agent_thread`` row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    created_by_user_id: str | None
    created_via_membership_id: str | None
    status: ThreadStatus
    pinned: bool
    title: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


async def create_thread(
    conn: AsyncConnection,
    *,
    thread_id: str,
    workspace_id: str,
    project_id: str,
    title: str | None = None,
    created_by_user_id: str | None = None,
    created_via_membership_id: str | None = None,
) -> AgentThreadRow:
    """Insert a thread and return it; a repeat of the same id in the same workspace replays it.

    ``ON CONFLICT (id) DO NOTHING`` plus the workspace-scoped re-read is the replay path. A
    conflicting id in a *different* workspace returns ``None`` from the re-read and raises, rather
    than leaking the existence of another tenant's thread by returning it.
    """

    await conn.execute(
        text(
            "INSERT INTO agent_thread "
            "(id, workspace_id, project_id, created_by_user_id, created_via_membership_id, title) "
            "VALUES (:id, :workspace_id, :project_id, :user_id, :membership_id, :title) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": thread_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "user_id": created_by_user_id,
            "membership_id": created_via_membership_id,
            "title": title,
        },
    )
    row = await get_thread(conn, workspace_id=workspace_id, thread_id=thread_id)
    if row is None:
        raise ValueError("thread id already exists outside this workspace")
    return row


async def ensure_platform_thread(
    conn: AsyncConnection,
    *,
    thread_id: str,
    workspace_id: str,
    project_id: str,
) -> None:
    """Provision the shell row for a **platform-originated** thread, idempotently.

    Called by the turn journal so every durable turn — the stage-0 trial's, an entity-research
    fleet unit's, a specialist delegation's — names a thread that exists, which is what makes the
    ``agent_turn (thread_id, workspace_id)`` foreign key enforceable for new writes instead of a
    constraint that would break every non-chat turn producer. These rows carry no creator: no human
    authored them, and Lane B ruling 8 forbids synthesising one.

    ``ON CONFLICT (id) DO NOTHING`` alone would make a *pre-existing* thread id silently acceptable
    no matter which project or workspace owns it, so the turn would attach itself to somebody
    else's conversation. Hence the ``RETURNING`` + fallback read: the surviving row's
    ``(workspace_id, project_id)`` must be the caller's, or this raises
    :class:`ThreadOwnershipMismatch`. A cross-*workspace* collision would already fail on the turn's
    own foreign key; a cross-*project* one inside a single workspace would not, which is precisely
    the hole this closes.

    Cost: one round trip in the common case (the insert wins and ``RETURNING`` yields the row), a
    second only on conflict — where a read is exactly what correctness requires anyway.
    """

    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_thread (id, workspace_id, project_id) "
                    "VALUES (:id, :workspace_id, :project_id) "
                    "ON CONFLICT (id) DO NOTHING "
                    "RETURNING workspace_id, project_id"
                ),
                {"id": thread_id, "workspace_id": workspace_id, "project_id": project_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        return
    surviving = (
        (
            await conn.execute(
                text("SELECT workspace_id, project_id FROM agent_thread WHERE id = :id"),
                {"id": thread_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if surviving is None:
        # The conflicting row vanished between statements (a concurrent delete — no production
        # path deletes threads). Nothing was written and nothing can be proved; refuse.
        raise ThreadOwnershipMismatch(
            reason_code="thread_owner_unresolved",
            message=f"thread {thread_id!r} could not be provisioned or read back",
        )
    if surviving["workspace_id"] != workspace_id or surviving["project_id"] != project_id:
        raise ThreadOwnershipMismatch(
            reason_code="thread_project_mismatch",
            message=(
                f"thread {thread_id!r} already exists under a different owner; a turn may not "
                "attach to a thread outside its own workspace and project"
            ),
        )


async def get_thread(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str
) -> AgentThreadRow | None:
    """Read one thread **inside one workspace**. A cross-workspace read is a miss, never a row."""

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM agent_thread "
                    "WHERE id = :id AND workspace_id = :workspace_id"
                ),
                {"id": thread_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentThreadRow.model_validate(dict(row)) if row is not None else None


async def _update(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    assignment: str,
    params: dict[str, object],
) -> AgentThreadRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"UPDATE agent_thread SET {assignment}, updated_at = now() "
                    "WHERE id = :id AND workspace_id = :workspace_id "
                    f"RETURNING {_COLUMNS}"
                ),
                {"id": thread_id, "workspace_id": workspace_id, **params},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentThreadRow.model_validate(dict(row)) if row is not None else None


async def set_thread_title(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str, title: str
) -> AgentThreadRow | None:
    """Rename a thread. ``None`` ⇒ no such thread in this workspace (the caller refuses typed)."""

    return await _update(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        assignment="title = :title",
        params={"title": title},
    )


async def set_thread_title_if_unset(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str, title: str
) -> AgentThreadRow | None:
    """Give an untitled thread its generated title — and only an untitled one.

    ``title IS NULL`` is the manual-wins rule (spec 2026-09-18-conversation-naming-design §4.5):
    a rename that landed first makes this a zero-row no-op, reported as ``None``. Not routed
    through :func:`_update` because that helper has no room for an extra predicate.
    """

    row = (
        (
            await conn.execute(
                text(
                    "UPDATE agent_thread SET title = :title, updated_at = now() "
                    "WHERE id = :id AND workspace_id = :workspace_id AND title IS NULL "
                    f"RETURNING {_COLUMNS}"
                ),
                {"id": thread_id, "workspace_id": workspace_id, "title": title},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentThreadRow.model_validate(dict(row)) if row is not None else None


async def set_thread_pinned(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str, pinned: bool
) -> AgentThreadRow | None:
    """Pin or unpin a thread. ``None`` ⇒ no such thread in this workspace."""

    return await _update(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        assignment="pinned = :pinned",
        params={"pinned": pinned},
    )


async def set_thread_status(
    conn: AsyncConnection, *, workspace_id: str, thread_id: str, status: ThreadStatus
) -> AgentThreadRow | None:
    """Archive (or reactivate) a thread. Archiving hides chat history; it deletes nothing —
    artifacts, runs, turns, and messages all remain attached to the project."""

    return await _update(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        assignment="status = :status",
        params={"status": status},
    )
