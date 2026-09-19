"""The project's own documents: ``/frontend/v1/projects/{project_id}/documents`` (list, one, PUT).

One project's documents are whatever this project wrote for itself — the plan, its audience
documents, a brief the agent judged worth keeping — never the brand's knowledge, which is the
``/brand-context`` surface's question. Every one of them is editable here: the project owns them,
and the store no longer keeps a list of kinds a human is allowed to type over.

The three routes here are the HTTP face of :mod:`clue_api.arv2.project_documents`: the
store decides what exists, what may be edited and what a stale revision means, and this module
turns its answers into the wire.

Scope is the store's, not a check re-applied here: every read and every write is
``(workspace, project)``-keyed, so another project's document — and another tenant's — is *absent*
rather than refused, and a probe cannot tell "not yours" from "not there".

The wire is snake_case in a ``{"data": …}`` envelope, like its ``discovery/current`` and
``research/progress`` neighbours on this router, rather than the camelCase ``WireModel`` the
accounts contract uses. ``title`` is the one value composed here, and every document is titled by
its own text: its front matter's ``title``, else its first heading, else the name on its path —
never invented, and never the platform's word for what the document is (founder ruling
2026-09-14).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

# The title rule, imported rather than restated so a document's title cannot read one way in this
# list and another way in the agent's focus card or the ICP gate.
from clue_api.arv2.project_documents import (
    INSTRUCTIONS_PATH,
    ProjectDocumentRefused,
    ProjectDocumentRow,
    document_title,
    list_project_documents,
    read_project_document,
    save_project_document,
)
from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.v1_shared import iso_utc
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_storage import StorageBackend, StorageError

if TYPE_CHECKING:  # the refresher's module imports this one's neighbours; only the type is needed
    from clue_api.project_library_refresh import ProjectLibraryRefresher

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


def _title(row: ProjectDocumentRow, *, front: Mapping[str, Any], body: str) -> str:
    """What this document is called on screen: its own words, and only its own words.

    The rule the ICP gate already serves — front matter ``title``, else the first heading — with
    the file's own name as the last resort. No kind is titled by what the platform thinks it is:
    the agent may write any document under ``project/``, and a name invented for it here would be
    the one place in the product where a document is called something it never called itself.
    """

    return document_title(front, body, path=row.path)


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

    One blob read per row, because every document is now titled by its own text and no row's title
    can be known without it. A document whose bytes cannot be read is still listed — by the name on
    its path — because a missing blob is a reason to show less, never a reason to fail the whole
    tab.

    ``project/instructions.md`` is the one row this *list* leaves out: it is a real document of this
    project — the agent reads it in its mounted workspace, and it is still served by id below — but
    the project home draws it in its own Instructions panel, and a second card for it in this feed
    is a surface the design never drew (spec §1.4). The exclusion is here, at the composition, and
    not in :func:`list_project_documents`, so the project library's tree still contains the file.
    """

    wires: list[ProjectDocumentV1] = []
    for row in await list_project_documents(conn, workspace_id=workspace_id, project_id=project_id):
        if row.path == INSTRUCTIONS_PATH:
            continue
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
            except (StorageError, ValueError):
                # Exactly what reading a verified artifact can raise: a missing, foreign, erased or
                # corrupt blob, and the digest mismatch this module's reader raises itself. A
                # *database* error is not caught here — the transaction is aborted, so continuing
                # the loop would only produce N misleading failures instead of one true one.
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
    library: ProjectLibraryRefresher | None = None,
) -> None:
    """Register the project-documents list, detail and PUT on the scoped ``/frontend/v1`` router.

    ``library`` is the project-library refresher the PUT calls once its edit has committed, so the
    version the human just saved is the one the library serves. Absent on a deployment with no
    agent-workspace root, and then the PUT behaves exactly as it did before.
    """

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
                # A version this project has since superseded is served with its real status, so an
                # editor holding it can rebase; only a document this project does not own — or one
                # that never existed — is absent.
                servable_only=False,
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
        # After the commit, never inside it: the library's compile takes this project's row lock,
        # which the save above was holding. Best-effort by contract — an edit that saved must not
        # report failure because its rendering could not be written.
        if library is not None:
            await library.refresh(workspace_id=workspace_id, project_id=project_id)
        if found is None:  # pragma: no cover - the save above either landed or refused
            raise _not_found()
        row, front, body = found
        return ProjectDocumentDetailResponseV1(data=_detail(row, front=front, body=body))
