"""Governed thread CRUD (FI Lane D slice D0 / REQ-21).

Four tools — ``create_thread@1``, ``rename_thread@1``, ``set_thread_pinned@1``,
``archive_thread@1`` — implementing the semantics of the frontend's authored thread contract
(``apps/frontend/docs/api-contracts/projects.md``). They exist as *tools*, not as endpoint bodies,
because Doc A makes the toolbelt the only mutation path: the chat HTTP surface calls these through
``ToolInvoker`` and therefore inherits parameter snapshotting, the C5.1 execution journal, and A9
idempotency for free, and every thread mutation is auditable the same way a research spend is.

**Not human-only.** REQ-21 anticipates an agent managing its own threads (splitting a long
conversation, filing a side thread), so nothing here demands ``actor == "human"``. What it does
demand is a *workspace*: every read and every write filters ``workspace_id``, so a thread in
another tenant is indistinguishable from a thread that does not exist — a typed
``thread_not_found`` refusal, never a 500 and never a leak.

**Idempotency.** ``create_thread@1`` derives its row id from ``ctx.operation_id``
(:func:`~clue_api.thread_store.thread_id_for_operation`), so a retried creation lands on the same
thread instead of littering the project with duplicates; it is therefore honestly
``OPERATION_IDEMPOTENT``. The three mutators are last-write-wins over an existing row and are
``DOMAIN_IDEMPOTENT``: replaying "rename to X" produces exactly the state replaying it once does.

All four are ``WRITE``, not ``STEERING``. ``STEERING`` in this codebase means run control —
``pause_run``, ``adjust_budget``, ``submit_tier_checkpoint`` — and the C6 authority audit refuses to
grant a steering tool to any model role. Classifying a rename as steering would therefore
permanently foreclose the agent-managed threads REQ-21 anticipates, in exchange for a
before/after snapshot of a title. These tools spend nothing and drive no run; they write shell
state.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, ClassVar

from pydantic import Field, StringConstraints
from sqlalchemy import text

from clue_api.thread_store import (
    AgentThreadRow,
    create_thread,
    get_thread,
    set_thread_pinned,
    set_thread_status,
    set_thread_title,
    thread_id_for_operation,
)
from clue_db import ConnFactory, transaction
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "THREAD_TOOL_REASON_CODES",
    "ArchiveThreadInput",
    "ArchiveThreadTool",
    "CreateThreadInput",
    "CreateThreadOutput",
    "CreateThreadTool",
    "RenameThreadInput",
    "RenameThreadTool",
    "SetThreadPinnedInput",
    "SetThreadPinnedTool",
    "ThreadOutput",
    "ThreadScopedInput",
    "build_thread_tools",
]

#: Every stable reason code these tools can refuse with, and what it means. The HTTP surface maps
#: them straight onto its error envelope, so this tuple is the assertion surface for both.
THREAD_TOOL_REASON_CODES: tuple[tuple[str, str], ...] = (
    ("project_not_found", "no such project in this workspace"),
    ("thread_not_found", "no such thread in this workspace"),
    ("thread_archived", "an archived thread cannot be renamed or pinned; reactivate it first"),
    ("project_archived", "restore this project before starting a chat"),
)

_TITLE = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _references(row: AgentThreadRow) -> dict[str, Any]:
    """The reference-only result shape every thread tool returns (never a transcript, never a
    body — the tool hands back the durable handles the caller resolves)."""

    return {
        "thread_id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "status": row.status,
        "pinned": row.pinned,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


class ThreadOutput(ToolOutput):
    """The typed reference schema shared by all four tools."""

    thread_id: str
    project_id: str
    title: str | None
    status: str
    pinned: bool
    created_at: str
    updated_at: str


class _ThreadTool(Tool):
    """Shared plumbing: the connection seam, and the two lookups every tool here needs."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        # Shell state only: no model call, no provider call, no external spend.
        return ToolEstimate.free()

    async def _thread(self, *, workspace_id: str, thread_id: str) -> AgentThreadRow | None:
        async with self._conn_factory() as conn:
            return await get_thread(conn, workspace_id=workspace_id, thread_id=thread_id)

    async def _project_status(self, *, workspace_id: str, project_id: str) -> str | None:
        """The project's status, or ``None`` when this workspace has no such project.

        Status rather than a bare boolean because a thread may not be opened on an *archived*
        project: the row exists, so ``project_not_found`` would be a lie, and silently opening a
        chat on an archived project would resurrect it by the side door.
        """

        async with self._conn_factory() as conn:
            found = await conn.execute(
                text(
                    "SELECT status FROM project "
                    "WHERE project_id = :project_id AND workspace_id = :workspace_id"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
        row = found.first()
        return str(row[0]) if row is not None else None


class ThreadScopedInput(ToolInput):
    """Base for the three mutators — the one field their shared precondition reads."""

    thread_id: str = Field(min_length=1, max_length=255)


class _MutateThreadTool(_ThreadTool):
    """A tool that changes one field of an existing thread.

    All three share one precondition — the thread exists *in this workspace* — so it lives here
    rather than being written three times, which is exactly the repetition a tenancy check must
    not be subject to.
    """

    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="agent_thread(id, workspace_id)",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("thread_id",))

    #: ``True`` when the mutation is meaningless on an archived thread (rename/pin), ``False`` for
    #: archiving itself, which must stay idempotent on an already-archived thread.
    refuses_archived: ClassVar[bool] = True

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ThreadScopedInput)
        row = await self._thread(workspace_id=ctx.workspace_id, thread_id=inputs.thread_id)
        if row is None:
            return _failure("thread_not_found", "no such thread in this workspace")
        if self.refuses_archived and row.status == "archived":
            return _failure(
                "thread_archived",
                "an archived thread cannot be renamed or pinned; reactivate it first",
            )
        return ()


# --- create ------------------------------------------------------------------------------------


class CreateThreadInput(ToolInput):
    """``POST /api/v1/projects/:projectId/threads``.

    There is deliberately no creator field: ``created_by_user_id`` is derived from the ambient
    ``ctx.actor_id`` the authenticated boundary injected. A caller-authored identity in a tool
    schema is what Lane B ruling 7 forbids.
    """

    project_id: str = Field(min_length=1, max_length=255)
    title: _TITLE | None = None


class CreateThreadOutput(ThreadOutput):
    pass


class CreateThreadTool(_ThreadTool):
    name = "create_thread"
    version = "1"
    model_description = (
        "Open a new conversation thread inside an existing project. Creates only the empty "
        "thread shell — it sends no message, starts no run, and spends nothing."
    )
    input_model: ClassVar[type[ToolInput]] = CreateThreadInput
    output_model: ClassVar[type[ToolOutput]] = CreateThreadOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="agent_thread.id = thread_id_for_operation(workspace_id, operation_id)",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id",))

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, CreateThreadInput)
        status = await self._project_status(
            workspace_id=ctx.workspace_id, project_id=inputs.project_id
        )
        if status is None:
            return _failure("project_not_found", "no such project in this workspace")
        if status == "archived":
            return _failure("project_archived", "restore this project before starting a chat")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, CreateThreadInput)
        async with self._conn_factory() as conn:
            row = await create_thread(
                conn,
                thread_id=thread_id_for_operation(
                    workspace_id=ctx.workspace_id, operation_id=ctx.operation_id
                ),
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                title=inputs.title,
                # Ambient authority only. ``actor_id`` is the Clue-owned platform_user.user_id the
                # authenticated boundary resolved; an agent-initiated thread simply has none until
                # Lane B gives agents a service identity here.
                created_by_user_id=ctx.actor_id,
                # The Lane B ⇄ Lane D join: B4 now carries the membership through the ToolContext,
                # so the second half of the ownership pair stops being NULL-by-necessity. A
                # service/legacy context carries no membership and correctly writes NULL — the
                # composite FK onto ``workspace_membership (membership_id, workspace_id)`` is
                # MATCH SIMPLE, so absence passes and a *claimed* membership must be real and must
                # belong to this thread's workspace.
                created_via_membership_id=ctx.membership_id,
            )
        return ToolResult(tool=self.name, version=self.version, references=_references(row))


# --- rename ------------------------------------------------------------------------------------


class RenameThreadInput(ThreadScopedInput):
    title: _TITLE


class RenameThreadTool(_MutateThreadTool):
    name = "rename_thread"
    version = "1"
    model_description = (
        "Rename an existing conversation thread. Changes its label and nothing else."
    )
    input_model: ClassVar[type[ToolInput]] = RenameThreadInput
    output_model: ClassVar[type[ToolOutput]] = ThreadOutput

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RenameThreadInput)
        async with self._conn_factory() as conn:
            row = await set_thread_title(
                conn,
                workspace_id=ctx.workspace_id,
                thread_id=inputs.thread_id,
                title=inputs.title,
            )
        if row is None:
            # Only reachable if the thread vanished between precondition and invoke; a loud raise
            # is right — a silent no-op would report a rename that never happened.
            raise ValueError("thread disappeared from its workspace during the rename")
        return ToolResult(tool=self.name, version=self.version, references=_references(row))


# --- pin ---------------------------------------------------------------------------------------


class SetThreadPinnedInput(ThreadScopedInput):
    pinned: bool


class SetThreadPinnedTool(_MutateThreadTool):
    name = "set_thread_pinned"
    version = "1"
    model_description = (
        "Pin or unpin a conversation thread so it sorts to the top of the project's thread list."
    )
    input_model: ClassVar[type[ToolInput]] = SetThreadPinnedInput
    output_model: ClassVar[type[ToolOutput]] = ThreadOutput
    parameter_policy = JournalParameterPolicy(safe_display_fields=("thread_id", "pinned"))

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SetThreadPinnedInput)
        async with self._conn_factory() as conn:
            row = await set_thread_pinned(
                conn,
                workspace_id=ctx.workspace_id,
                thread_id=inputs.thread_id,
                pinned=inputs.pinned,
            )
        if row is None:
            raise ValueError("thread disappeared from its workspace during the pin change")
        return ToolResult(tool=self.name, version=self.version, references=_references(row))


# --- archive -----------------------------------------------------------------------------------


class ArchiveThreadInput(ThreadScopedInput):
    pass


class ArchiveThreadTool(_MutateThreadTool):
    name = "archive_thread"
    version = "1"
    model_description = (
        "Archive a conversation thread: hide its chat history from the active thread list. It "
        "deletes nothing — the project keeps its artifacts, runs, turns, and messages."
    )
    input_model: ClassVar[type[ToolInput]] = ArchiveThreadInput
    output_model: ClassVar[type[ToolOutput]] = ThreadOutput
    # Archiving an archived thread is the state the caller asked for, not an error.
    refuses_archived = False

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ArchiveThreadInput)
        async with self._conn_factory() as conn:
            row = await set_thread_status(
                conn,
                workspace_id=ctx.workspace_id,
                thread_id=inputs.thread_id,
                status="archived",
            )
        if row is None:
            raise ValueError("thread disappeared from its workspace during archival")
        return ToolResult(tool=self.name, version=self.version, references=_references(row))


def build_thread_tools(*, conn_factory: ConnFactory = transaction) -> tuple[Tool, ...]:
    """The four REQ-21 thread tools, in registration order."""

    return (
        CreateThreadTool(conn_factory=conn_factory),
        RenameThreadTool(conn_factory=conn_factory),
        SetThreadPinnedTool(conn_factory=conn_factory),
        ArchiveThreadTool(conn_factory=conn_factory),
    )
