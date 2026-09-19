"""``/frontend/v1/projects/{id}/instructions`` — the human's standing instructions for one project.

The project home's Instructions panel is one document and nothing more: ``project/instructions.md``
in this project's own document chain (spec 2026-09-19 §2.6). Storing it there rather than in a
column of its own is the whole point — the agent already reads this project's documents in its
workspace, so instructions a human types are context the next turn has, with no second mechanism
for carrying them.

One path, so the wire names a *revision* rather than a document id: the panel never holds an id,
it holds the version it last read, and sends it back with the next save. ``expected_revision:
null`` means "there were none when I opened this" and creates version 1; any number means "I typed
over this version" and appends the next one. Either request that disagrees with what is at rest is
refused with ``DOCUMENT_REVISION_CONFLICT`` — the same answer the documents PUT gives, because it
is the same event: someone wrote first.

Scope is the store's, exactly as it is for the documents surface: every read and write is
``(workspace, project)``-keyed, so another tenant's project is *absent* rather than refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.project_documents import (
    INSTRUCTIONS_PATH,
    ProjectDocumentRefused,
    create_human_project_document,
    read_project_document,
    save_project_document,
)
from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.v1_shared import iso_utc
from clue_db import ConnFactory
from clue_spine import Project, get_project_for_workspace, touch_project
from clue_storage import StorageBackend

if TYPE_CHECKING:  # the refresher's module imports this one's neighbours; only the type is needed
    from clue_api.project_library_refresh import ProjectLibraryRefresher

__all__ = [
    "INSTRUCTIONS_KIND",
    "ProjectInstructionsResponseV1",
    "ProjectInstructionsUpdateV1",
    "ProjectInstructionsV1",
    "register_project_instructions_routes",
]

#: What this document calls itself. Stamped into its front matter at birth, kept by every edit,
#: and the value the documents list shows in the ``kind`` column.
INSTRUCTIONS_KIND = "project-instructions"
INSTRUCTIONS_TITLE = "Instructions"

#: The store's refusal vocabulary, mapped onto this surface. An existing document, a stale revision
#: and a lost race to publish the next version are one answer to the human — someone wrote first —
#: so all three are the conflict; anything else is a request this surface could not carry out,
#: named by the store's own reason.
_REFUSALS: dict[str, tuple[int, str]] = {
    "project_document_revision_conflict": (409, "DOCUMENT_REVISION_CONFLICT"),
    "project_document_exists": (409, "DOCUMENT_REVISION_CONFLICT"),
    "project_document_version_race": (409, "DOCUMENT_REVISION_CONFLICT"),
    "project_document_body_empty": (422, "PROJECT_DOCUMENT_BODY_EMPTY"),
}

#: The servable version at this project's instructions path, newest first. The same predicate
#: :func:`clue_api.arv2.project_documents.read_project_document` serves a document under.
_CURRENT = text(
    "SELECT document_id FROM brand_knowledge_document "
    "WHERE workspace_id = :workspace_id AND project_id = :project_id AND path = :path "
    "  AND status IN ('ready', 'proposed', 'confirmed') AND artifact_key IS NOT NULL "
    "ORDER BY version DESC LIMIT 1"
)


class ProjectInstructionsV1(BaseModel):
    """The instructions as the panel draws them: the text, the version, and when it last moved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    body: str
    revision: int
    updated_at: str


class ProjectInstructionsResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: ``None`` is the honest empty panel: this project has never had instructions.
    data: ProjectInstructionsV1 | None


class ProjectInstructionsUpdateV1(BaseModel):
    """A save: the whole text, and the revision it was typed over (``None`` for the first one)."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=12_000)
    expected_revision: int | None = Field(default=None, ge=1)


def _refuse(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _refused(refusal: ProjectDocumentRefused) -> HTTPException:
    status_code, code = _REFUSALS.get(refusal.code, (422, refusal.code.upper()))
    return _refuse(status_code, code, str(refusal))


def register_project_instructions_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend | None,
    allow_local_mutations: bool = False,
    library: ProjectLibraryRefresher | None = None,
) -> None:
    """Register the instructions GET and PUT on the scoped ``/frontend/v1`` router.

    ``library`` is the project-library refresher the PUT calls once its write has committed, for
    the reason the documents PUT calls it: the version the human just saved must be the one the
    agent's mounted workspace serves on the next turn.
    """

    async def _current(
        conn: AsyncConnection, *, workspace_id: str, project_id: str
    ) -> ProjectInstructionsV1 | None:
        if storage is None:
            # Nothing was ever stored on a deployment with no artifact storage, so the panel is
            # empty rather than broken. The PUT still refuses loudly.
            return None
        document_id = await conn.scalar(
            _CURRENT,
            {"workspace_id": workspace_id, "project_id": project_id, "path": INSTRUCTIONS_PATH},
        )
        if document_id is None:
            return None
        found = await read_project_document(
            conn,
            storage,
            workspace_id=workspace_id,
            project_id=project_id,
            document_id=UUID(str(document_id)),
        )
        if found is None:  # pragma: no cover - the row above is servable and cites its bytes
            return None
        row, _front, body = found
        return ProjectInstructionsV1(
            body=body, revision=row.version, updated_at=iso_utc(row.updated_at)
        )

    async def _project_or_404(
        conn: AsyncConnection, *, workspace_id: str, project_id: str
    ) -> Project:
        project = await get_project_for_workspace(
            conn, workspace_id=workspace_id, project_id=project_id
        )
        # A system scope anchor is not a project a human opens, so it is absent here for the same
        # reason another workspace's project is: this surface only knows the directory's projects.
        if project is None or project.kind == "system":
            raise _refuse(404, "PROJECT_NOT_FOUND", "no such project in this workspace")
        return project

    @router.get("/projects/{project_id}/instructions", response_model=ProjectInstructionsResponseV1)
    async def get_project_instructions(
        project_id: str, workspace_id: WorkspaceDep
    ) -> ProjectInstructionsResponseV1:
        async with conn_factory() as conn:
            await _project_or_404(conn, workspace_id=workspace_id, project_id=project_id)
            data = await _current(conn, workspace_id=workspace_id, project_id=project_id)
        return ProjectInstructionsResponseV1(data=data)

    @router.put("/projects/{project_id}/instructions", response_model=ProjectInstructionsResponseV1)
    async def put_project_instructions(
        request: Request,
        project_id: str,
        update: ProjectInstructionsUpdateV1,
        workspace_id: WorkspaceDep,
    ) -> ProjectInstructionsResponseV1:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("project.write")
            user_id = principal.user_id
        elif allow_local_mutations:
            user_id = "local-development-user"
        else:
            raise _refuse(401, "UNAUTHORIZED", "An authenticated session is required.")
        if storage is None:
            raise _refuse(
                503,
                "KNOWLEDGE_STORAGE_UNAVAILABLE",
                "this process has no artifact storage configured",
            )
        async with conn_factory() as conn:
            project = await _project_or_404(conn, workspace_id=workspace_id, project_id=project_id)
            if project.status == "archived":
                raise _refuse(
                    409, "PROJECT_ARCHIVED", "Restore this project before making changes."
                )
            current_id = await conn.scalar(
                _CURRENT,
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "path": INSTRUCTIONS_PATH,
                },
            )
            try:
                if update.expected_revision is None:
                    if current_id is not None:
                        # The panel opened empty and something was written while it was open.
                        raise ProjectDocumentRefused(
                            "project_document_revision_conflict",
                            "instructions already exist; reload and edit the current version",
                        )
                    await create_human_project_document(
                        conn,
                        storage,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        path=INSTRUCTIONS_PATH,
                        kind=INSTRUCTIONS_KIND,
                        title=INSTRUCTIONS_TITLE,
                        body=update.body,
                        user_id=user_id,
                    )
                else:
                    if current_id is None:
                        raise ProjectDocumentRefused(
                            "project_document_revision_conflict",
                            "no instructions exist yet; save without a revision",
                        )
                    await save_project_document(
                        conn,
                        storage,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        document_id=UUID(str(current_id)),
                        body=update.body,
                        expected_revision=update.expected_revision,
                        user_id=user_id,
                    )
            except ProjectDocumentRefused as refusal:
                raise _refused(refusal) from refusal
            # The directory sorts by this, and instructions are a change to the project: the bump
            # shares the write's transaction, so a refused save never moves the project's row.
            await touch_project(conn, workspace_id=workspace_id, project_id=project_id)
            data = await _current(conn, workspace_id=workspace_id, project_id=project_id)
        # After the commit, never inside it: the library's compile takes this project's row lock,
        # which the write above was holding (the documents PUT refreshes for the same reason).
        if library is not None:
            await library.refresh(workspace_id=workspace_id, project_id=project_id)
        return ProjectInstructionsResponseV1(data=data)
