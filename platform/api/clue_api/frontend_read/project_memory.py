"""``/frontend/v1/projects/{id}/memory`` — the human's notes, through the scoped-memory seam.

The project home's Memory panel is not a notes table this surface owns: every note a human types
goes through :class:`~clue_core.MemoryWriteSeam`, so it is reconciled against what is already
remembered, born with the trust its provenance earns, journaled, and capped — exactly like a note
the agent distils from a conversation (Doc M §7). There is one write path into memory and this is
it; a second one would be a second species of truth.

Consequences the panel actually shows:

* an **edit** is a retire + a submit, not an update — the substrate is append-only, so the
  successor carries a new id and the old record keeps its trail. Both happen in one transaction:
  a refused submit rolls the retire back, and the note the human was editing survives intact.
* a **removal** invalidates the record (journaled, never deleted), so a repeat click is a 404
  rather than a second write.
* a **rejection is stated, not swallowed.** The seam refuses a body that carries verbatim contact
  data without a resolved subject (``MemoryPreconditionFailed``) or that is fact-shaped
  (``MemoryRejected``): facts belong in the claim store, and memory holds only advisory
  preferences and learnings. Both reach the human as ``422 MEMORY_REJECTED`` with the seam's own
  words, because "we did not keep this, and here is why" is the honest answer.
* **memory being off is a refusal, not an empty list** (``409 MEMORY_DISABLED``) — on the read
  too. A panel that drew nothing would say "no notes" when the truth is "nothing is being kept".
* a deployment with **no model gateway** composes no write seam, so the writes refuse
  ``503 MEMORY_UNAVAILABLE`` while the list still serves: reconciliation needs a judge, and
  writing without one would either fabricate a verdict or park every note ``proposed``.

Scope is the store's: every read and write is ``(workspace, project)``-keyed, so another tenant's
project is *absent* rather than refused, and the notes are project-scope memories the agent's own
context assembly already reads — no second mechanism carries them to the next turn.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.v1_shared import iso_utc
from clue_config import Settings
from clue_core import (
    MemoryAccepted,
    MemoryPreconditionFailed,
    MemoryProvenanceClass,
    MemoryRejected,
    MemoryScopeType,
    MemorySubmission,
    MemoryType,
    MemoryWriteSeam,
    ScopeRef,
)
from clue_db import ConnFactory
from clue_memory import Memory, get_memory, is_memory_enabled, list_project_memories, retire
from clue_spine import Project, get_project_for_workspace, touch_project

__all__ = [
    "NOTE_TRIGGER",
    "MemoryWriteFactory",
    "ProjectMemoryListResponseV1",
    "ProjectMemoryNoteResponseV1",
    "ProjectMemoryNoteV1",
    "ProjectMemoryWriteV1",
    "register_project_memory_routes",
]

#: How the write seam is handed this request's connection. The seam is connection-free by
#: contract, so the composition root binds a *factory* and every route builds its seam inside its
#: own transaction — the submit and the retire it may follow share one unit of work.
MemoryWriteFactory = Callable[[AsyncConnection], MemoryWriteSeam]

#: The ``trigger`` every note born on this surface carries. Triggers are what a later reader uses
#: to tell "the human typed this into the project's memory panel" from a distilled observation.
NOTE_TRIGGER = "project_home_note"


class ProjectMemoryNoteV1(BaseModel):
    """One note as the panel draws it: the text, and the conversation it came out of, if any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    text: str
    source_thread_id: str | None
    source_thread_title: str | None
    created_at: str


class ProjectMemoryListResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: list[ProjectMemoryNoteV1]


class ProjectMemoryNoteResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ProjectMemoryNoteV1
    #: How reconciliation disposed of the submission (``add``/``update``/``supersede``/``noop``).
    #: Surfaced because "we already knew that" is a different outcome from "noted", and the panel
    #: is allowed to say so.
    verdict: str | None = None


class ProjectMemoryWriteV1(BaseModel):
    """A note the human typed, and the thread they typed it from, when there is one."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    source_thread_id: str | None = None


#: The thread a note cites must be this project's own — otherwise a note could point at another
#: project's (or another tenant's) conversation for its provenance.
_THREAD_IN_PROJECT = text(
    "SELECT 1 FROM agent_thread "
    "WHERE id = :thread_id AND workspace_id = :workspace_id AND project_id = :project_id"
)

_THREAD_TITLE = text("SELECT title FROM agent_thread WHERE id = :thread_id")


def _refuse(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def register_project_memory_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    settings: Settings,
    memory_write_factory: MemoryWriteFactory | None,
    allow_local_mutations: bool = False,
) -> None:
    """Register the project-memory list, add, edit and remove on the scoped ``/frontend/v1``
    router.

    ``memory_write_factory`` is ``None`` on a deployment that composes no model gateway; the list
    still serves there and the three writes refuse ``MEMORY_UNAVAILABLE``.
    """

    async def _project(
        conn: AsyncConnection, *, workspace_id: str, project_id: str, for_write: bool
    ) -> Project:
        project = await get_project_for_workspace(
            conn, workspace_id=workspace_id, project_id=project_id
        )
        # A system scope anchor is not a project a human opens, so it is absent here for the same
        # reason another workspace's project is.
        if project is None or project.kind == "system":
            raise _refuse(404, "PROJECT_NOT_FOUND", "no such project in this workspace")
        if for_write and project.status == "archived":
            raise _refuse(409, "PROJECT_ARCHIVED", "Restore this project before making changes.")
        # Checked on the read too: an empty list would claim "no notes" when the truth is that
        # nothing is being kept at all.
        if not await is_memory_enabled(conn, workspace_id, settings):
            raise _refuse(409, "MEMORY_DISABLED", "memory is turned off for this workspace")
        return project

    async def _note(conn: AsyncConnection, memory: Memory) -> ProjectMemoryNoteV1:
        # The thread's title is joined at read time rather than copied onto the memory: a renamed
        # or deleted thread must not leave the panel quoting a title that no longer exists.
        thread_id = memory.source_thread_id
        title = (
            None
            if thread_id is None
            else await conn.scalar(_THREAD_TITLE, {"thread_id": thread_id})
        )
        return ProjectMemoryNoteV1(
            id=memory.memory_id,
            text=memory.body,
            source_thread_id=thread_id,
            source_thread_title=title,
            created_at=iso_utc(memory.created_at),
        )

    async def _retire_one(
        conn: AsyncConnection,
        *,
        workspace_id: str,
        project_id: str,
        memory_id: str,
        actor: str,
        cause: str,
    ) -> None:
        """Retire a note this project's panel actually shows, or 404.

        :func:`clue_memory.retire` is fail-closed on workspace and on "still active", but it knows
        nothing about the project in the path — so on its own it would let ``/projects/A/…``
        remove a note belonging to project B of the same tenant. The scope and provenance are
        therefore checked here against the same predicate the list uses: the verbs act on exactly
        the set the panel draws, and everything else is absent.
        """
        record = await get_memory(conn, memory_id)
        if (
            record is None
            or record.workspace_id != workspace_id
            or record.scope_type is not MemoryScopeType.PROJECT
            or record.scope_id != project_id
            or record.provenance_class is not MemoryProvenanceClass.USER_STATED
        ):
            raise _refuse(404, "MEMORY_NOT_FOUND", "this note is no longer available")
        # Fail-closed and idempotent-by-refusal: an already-removed note, a repeat click and a
        # record that is not active any more are one answer.
        if not await retire(
            conn,
            memory_id=memory_id,
            workspace_id=workspace_id,
            actor=actor,
            cause=cause,
        ):
            raise _refuse(404, "MEMORY_NOT_FOUND", "this note is no longer available")

    def _user(request: Request) -> str:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("project.write")
            return principal.user_id
        if allow_local_mutations:
            return "local-development-user"
        raise _refuse(401, "UNAUTHORIZED", "An authenticated session is required.")

    async def _submit(
        conn: AsyncConnection,
        *,
        workspace_id: str,
        project_id: str,
        write: ProjectMemoryWriteV1,
    ) -> ProjectMemoryNoteResponseV1:
        if memory_write_factory is None:
            raise _refuse(503, "MEMORY_UNAVAILABLE", "this deployment cannot write memory")
        if write.source_thread_id is not None:
            owned = await conn.scalar(
                _THREAD_IN_PROJECT,
                {
                    "thread_id": write.source_thread_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                },
            )
            if owned is None:
                raise _refuse(
                    422,
                    "MEMORY_SOURCE_NOT_IN_PROJECT",
                    "A memory source must belong to this project.",
                )
        submission = MemorySubmission(
            workspace_id=workspace_id,
            scope=ScopeRef(scope_type=MemoryScopeType.PROJECT, scope_id=project_id),
            type=MemoryType.PREFERENCE,
            trigger=NOTE_TRIGGER,
            body=write.text,
            # The human said it, in their own words: the strongest provenance the substrate has,
            # so the note is born active rather than parked for review.
            provenance_class=MemoryProvenanceClass.USER_STATED,
            source_thread_id=write.source_thread_id,
        )
        try:
            outcome = await memory_write_factory(conn).submit(submission)
        except MemoryPreconditionFailed as exc:
            # Malformed, not merely unwelcome — the seam's own words are the honest explanation.
            raise _refuse(422, "MEMORY_REJECTED", str(exc)) from exc
        if isinstance(outcome, MemoryRejected):
            raise _refuse(422, "MEMORY_REJECTED", outcome.detail)
        if not isinstance(outcome, MemoryAccepted):
            # ``MemoryDisabled`` — the switch moved between this request's gate and its write.
            raise _refuse(409, "MEMORY_DISABLED", "memory is turned off for this workspace")
        memory = await get_memory(conn, outcome.memory_id)
        if memory is None:  # pragma: no cover - the seam just wrote this row in this transaction
            raise _refuse(500, "MEMORY_UNAVAILABLE", "the stored note could not be read back")
        # The directory sorts by this, and a note is a change to the project: the bump shares the
        # write's transaction, so a refused submit never moves the project's row.
        await touch_project(conn, workspace_id=workspace_id, project_id=project_id)
        return ProjectMemoryNoteResponseV1(
            data=await _note(conn, memory), verdict=outcome.verdict.value
        )

    @router.get("/projects/{project_id}/memory", response_model=ProjectMemoryListResponseV1)
    async def list_project_memory(
        project_id: str, workspace_id: WorkspaceDep
    ) -> ProjectMemoryListResponseV1:
        async with conn_factory() as conn:
            await _project(conn, workspace_id=workspace_id, project_id=project_id, for_write=False)
            memories = await list_project_memories(
                conn, workspace_id=workspace_id, project_id=project_id
            )
            return ProjectMemoryListResponseV1(
                data=[await _note(conn, memory) for memory in memories]
            )

    @router.post(
        "/projects/{project_id}/memory",
        response_model=ProjectMemoryNoteResponseV1,
        status_code=201,
    )
    async def add_project_memory(
        request: Request,
        project_id: str,
        write: ProjectMemoryWriteV1,
        workspace_id: WorkspaceDep,
    ) -> ProjectMemoryNoteResponseV1:
        _user(request)
        async with conn_factory() as conn:
            await _project(conn, workspace_id=workspace_id, project_id=project_id, for_write=True)
            return await _submit(
                conn, workspace_id=workspace_id, project_id=project_id, write=write
            )

    @router.put(
        "/projects/{project_id}/memory/{memory_id}",
        response_model=ProjectMemoryNoteResponseV1,
    )
    async def edit_project_memory(
        request: Request,
        project_id: str,
        memory_id: str,
        write: ProjectMemoryWriteV1,
        workspace_id: WorkspaceDep,
    ) -> ProjectMemoryNoteResponseV1:
        user_id = _user(request)
        # One transaction on purpose: a refused submit raises out of this block, so the retire
        # rolls back with it and the note the human was editing is still there.
        async with conn_factory() as conn:
            await _project(conn, workspace_id=workspace_id, project_id=project_id, for_write=True)
            await _retire_one(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                memory_id=memory_id,
                actor=user_id,
                cause="edited on project home",
            )
            return await _submit(
                conn, workspace_id=workspace_id, project_id=project_id, write=write
            )

    @router.delete("/projects/{project_id}/memory/{memory_id}", status_code=204)
    async def remove_project_memory(
        request: Request,
        project_id: str,
        memory_id: str,
        workspace_id: WorkspaceDep,
    ) -> Response:
        user_id = _user(request)
        async with conn_factory() as conn:
            await _project(conn, workspace_id=workspace_id, project_id=project_id, for_write=True)
            await _retire_one(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                memory_id=memory_id,
                actor=user_id,
                cause="removed on project home",
            )
            await touch_project(conn, workspace_id=workspace_id, project_id=project_id)
        return Response(status_code=204)
