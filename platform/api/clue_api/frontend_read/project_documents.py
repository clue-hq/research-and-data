"""The project's own documents: ``/frontend/v1/projects/{project_id}/documents`` (list, one, PUT).

One project's documents are the plan the Head of ABM writes and the audience documents the project
authored for itself — never the brand's knowledge, which is the ``/brand-context`` surface's
question. The three routes here are the HTTP face of :mod:`clue_api.arv2.project_documents`: the
store decides what exists, what may be edited and what a stale revision means, and this module
turns its answers into the wire.

Scope is the store's, not a check re-applied here: every read and every write is
``(workspace, project)``-keyed, so another project's document — and another tenant's — is *absent*
rather than refused, and a probe cannot tell "not yours" from "not there".

The wire is snake_case in a ``{"data": …}`` envelope, like its ``discovery/current`` and
``research/progress`` neighbours on this router, rather than the camelCase ``WireModel`` the
accounts contract uses. ``title`` is the one value composed here: a plan is "Plan", a persona
document is named for its ICP, and everything else is titled by its own text (its front matter's
``title``, else its first heading) — never invented.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

# The ICP title rule, imported rather than restated so a document's title cannot read one way in
# the ICP gate and another way in this list. ``ICP_KIND`` is its module's public name; ``_title``
# is private there only because the gate is its single caller until now.
from clue_api.arv2.icp_confirmation import _title as _titled_by_its_own_text
from clue_api.arv2.project_documents import (
    PLAN_KIND,
    ProjectDocumentRefused,
    ProjectDocumentRow,
    list_project_documents,
    read_project_document,
    save_project_document,
)
from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.v1_shared import iso_utc
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_storage import StorageBackend

log = get_logger("clue_api.frontend_read.project_documents")

__all__ = [
    "ProjectDocumentDetailResponseV1",
    "ProjectDocumentDetailV1",
    "ProjectDocumentListResponseV1",
    "ProjectDocumentListV1",
    "ProjectDocumentUpdateV1",
    "ProjectDocumentV1",
    "register_project_document_routes",
]

#: The persona document one ICP owns. Restated rather than imported: the kind is written by the
#: ``audience-persona`` skill's front matter and has no Python home to import it from.
PERSONA_KIND = "audience-persona"
#: A project has exactly one plan, so its title is a constant rather than its heading — the tab it
#: is drawn in is called Plan, and the document's own H1 is the campaign's name, not the file's.
PLAN_TITLE = "Plan"

#: The store's refusal vocabulary, mapped onto this surface's statuses and codes. A version race
#: and a stale revision are the same answer to the human: someone else wrote first.
_REFUSALS: dict[str, tuple[int, str]] = {
    "project_document_not_found": (404, "PROJECT_DOCUMENT_NOT_FOUND"),
    "project_document_revision_conflict": (409, "DOCUMENT_REVISION_CONFLICT"),
    "project_document_version_race": (409, "DOCUMENT_REVISION_CONFLICT"),
    "project_document_body_empty": (422, "DOCUMENT_BODY_EMPTY"),
}


class ProjectDocumentV1(BaseModel):
    """One servable version of one of this project's documents, as the document list serves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: str
    kind: str
    title: str
    version: int
    status: str
    updated_at: str
    icp_key: str | None


class ProjectDocumentDetailV1(ProjectDocumentV1):
    """The same document with its bytes: the markdown the editor loads, and its front matter."""

    markdown: str
    front_matter: dict[str, Any]


class ProjectDocumentListV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: list[ProjectDocumentV1]


class ProjectDocumentListResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ProjectDocumentListV1


class ProjectDocumentDetailResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ProjectDocumentDetailV1


class ProjectDocumentUpdateV1(BaseModel):
    """A human's edit: the whole body, and the version they typed it over."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=1_000_000)
    expected_revision: int = Field(ge=1, strict=True)


def _file_name(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[:-3] if name.endswith(".md") else name


def _title(row: ProjectDocumentRow, *, front: Mapping[str, Any], body: str) -> str:
    """What this document is called on screen.

    Two kinds are named by what they *are* — the project's one plan, and the persona set that
    belongs to one ICP. Everything else is named by its own text, which is the rule the ICP gate
    already serves, so a document cannot be titled one way there and another way here.
    """

    if row.kind == PLAN_KIND:
        return PLAN_TITLE
    subject = row.icp_key or _file_name(row.path)
    if row.kind == PERSONA_KIND:
        return f"Personas — {subject}"
    return _titled_by_its_own_text(front, body, icp_key=subject)


def _wire(row: ProjectDocumentRow, *, front: Mapping[str, Any], body: str) -> ProjectDocumentV1:
    return ProjectDocumentV1(
        id=str(row.document_id),
        path=row.path,
        kind=row.kind,
        title=_title(row, front=front, body=body),
        version=row.version,
        status=row.status,
        updated_at=iso_utc(row.updated_at),
        icp_key=row.icp_key,
    )


def _detail(
    row: ProjectDocumentRow, *, front: Mapping[str, Any], body: str
) -> ProjectDocumentDetailV1:
    return ProjectDocumentDetailV1(
        **_wire(row, front=front, body=body).model_dump(),
        markdown=body,
        front_matter=dict(front),
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "PROJECT_DOCUMENT_NOT_FOUND",
            "message": "no such document in this project",
        },
    )


def _storage_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "KNOWLEDGE_STORAGE_UNAVAILABLE",
            "message": "this process has no artifact storage configured",
        },
    )


def _refused(refusal: ProjectDocumentRefused) -> HTTPException:
    status_code, code = _REFUSALS.get(refusal.code, (409, "DOCUMENT_REVISION_CONFLICT"))
    return HTTPException(status_code=status_code, detail={"code": code, "message": str(refusal)})


async def _listed(
    conn: AsyncConnection,
    storage: StorageBackend | None,
    *,
    workspace_id: str,
    project_id: str,
) -> list[ProjectDocumentV1]:
    """This project's documents, each read once for the title its own bytes carry.

    One blob per document, sequentially: a project owns a plan and its audience documents, so the
    list is a handful of rows rather than a page. A document whose bytes cannot be read is still
    listed — by the name on its path — because a missing blob is a reason to show less, never a
    reason to fail the whole tab.
    """

    wires: list[ProjectDocumentV1] = []
    for row in await list_project_documents(conn, workspace_id=workspace_id, project_id=project_id):
        front: Mapping[str, Any] = {}
        body = ""
        if storage is not None:
            try:
                read = await read_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    document_id=row.document_id,
                )
            except Exception:  # noqa: BLE001 — an unreadable blob lists the document, never 500s
                read = None
                log.warning(
                    "project_documents.document_unreadable",
                    workspace_id=workspace_id,
                    project_id=project_id,
                    document_id=str(row.document_id),
                    path=row.path,
                )
            if read is not None:
                _, front, body = read
        wires.append(_wire(row, front=front, body=body))
    return wires


def register_project_document_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend | None,
    allow_local_mutations: bool = False,
) -> None:
    """Register the project-documents list, detail and PUT on the scoped ``/frontend/v1`` router."""

    @router.get("/projects/{project_id}/documents", response_model=ProjectDocumentListResponseV1)
    async def get_project_documents(
        project_id: str, workspace_id: WorkspaceDep
    ) -> ProjectDocumentListResponseV1:
        async with conn_factory() as conn:
            documents = await _listed(
                conn, storage, workspace_id=workspace_id, project_id=project_id
            )
        return ProjectDocumentListResponseV1(data=ProjectDocumentListV1(documents=documents))

    @router.get(
        "/projects/{project_id}/documents/{document_id}",
        response_model=ProjectDocumentDetailResponseV1,
    )
    async def get_project_document(
        project_id: str, document_id: UUID, workspace_id: WorkspaceDep
    ) -> ProjectDocumentDetailResponseV1:
        if storage is None:
            raise _storage_unavailable()
        async with conn_factory() as conn:
            found = await read_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=document_id,
            )
        if found is None:
            raise _not_found()
        row, front, body = found
        return ProjectDocumentDetailResponseV1(data=_detail(row, front=front, body=body))

    @router.put(
        "/projects/{project_id}/documents/{document_id}",
        response_model=ProjectDocumentDetailResponseV1,
    )
    async def put_project_document(
        request: Request,
        project_id: str,
        document_id: UUID,
        update: ProjectDocumentUpdateV1,
        workspace_id: WorkspaceDep,
    ) -> ProjectDocumentDetailResponseV1:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("project.write")
            user_id = principal.user_id
        elif allow_local_mutations:
            user_id = "local-development-user"
        else:
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "An authenticated session is required."},
            )
        if storage is None:
            raise _storage_unavailable()
        async with conn_factory() as conn:
            try:
                saved = await save_project_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    document_id=document_id,
                    body=update.body,
                    expected_revision=update.expected_revision,
                    user_id=user_id,
                )
            except ProjectDocumentRefused as refusal:
                raise _refused(refusal) from refusal
            found = await read_project_document(
                conn,
                storage,
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=saved.document_id,
            )
        if found is None:  # pragma: no cover - the save above either landed or refused
            raise _not_found()
        row, front, body = found
        return ProjectDocumentDetailResponseV1(data=_detail(row, front=front, body=body))
