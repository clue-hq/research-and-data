"""``POST /frontend/v1/uploads`` and ``GET /frontend/v1/uploads/{id}/bytes`` (spec 2026-09-18).

The two routes a chat attachment needs before it is ever attached to a turn: the one that takes a
person's file and hands back the receipt the composer holds, and the one that serves those bytes
again when the transcript draws the chip.

Validation is :mod:`clue_api.chat.uploads`'s, not restated here — the same sanitizer, the same
media-type resolution and the same size/shape rules the submission route applies, so a file cannot
be accepted by one door and refused by the other. Refusals travel as an ``HTTPException`` whose
``detail`` carries ``{"code", "message"}``, which is how every route on this surface emits a domain
code: the frontend-read envelope renders it as ``{"error": {"code", "message", "requestId"}}``.

Scope is the row's, not a check re-applied here: :func:`get_chat_uploads` is ``workspace``-keyed, so
another tenant's upload is *absent* rather than refused, and a probe cannot tell "not yours" from
"not there".
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict

from clue_agents.contracts import ArtifactRef
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_wiring import principal_from_request
from clue_api.chat.uploads import (
    UploadRefused,
    get_chat_uploads,
    record_chat_upload,
    resolve_media_type,
    sanitize_filename,
    validate_upload_bytes,
)
from clue_api.frontend_read.app import WorkspaceDep
from clue_config import Settings
from clue_db import ConnFactory
from clue_storage import ArtifactNotFound, StorageBackend

__all__ = ["UploadResponseV1", "UploadV1", "register_upload_routes"]

#: The refusal codes that are about the request rather than its content: too big is ``413``, an
#: unaccepted type is ``415``, and everything else (a bad name, non-UTF-8 text, bytes that are not
#: the image they claim) is a ``422``.
_STATUS = {"UPLOAD_TOO_LARGE": 413, "UPLOAD_UNSUPPORTED_TYPE": 415}


class UploadV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    upload_id: str
    filename: str
    media_type: str
    byte_count: int
    artifact_key: str
    sha256: str


class UploadResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: UploadV1


def register_upload_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend | None,
    settings: Settings,
    allow_local_mutations: bool = False,
) -> None:
    """Register the upload receipt and the bytes behind it on the frontend-read router."""

    artifacts = (
        None
        if storage is None
        else DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    )

    def _user_id(request: Request) -> str:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("project.write")
            return principal.user_id
        if allow_local_mutations:
            return "local-development-user"
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "An authenticated session is required."},
        )

    def _require_artifacts() -> DurableAgentArtifactStore:
        if artifacts is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "STORAGE_UNAVAILABLE",
                    "message": "this deployment has no artifact storage configured",
                },
            )
        return artifacts

    @router.post("/uploads", response_model=UploadResponseV1, status_code=201)
    async def post_upload(
        request: Request,
        workspace_id: WorkspaceDep,
        file: Annotated[UploadFile, File()],
    ) -> UploadResponseV1:
        user_id = _user_id(request)
        store = _require_artifacts()
        data = await file.read()
        try:
            filename = sanitize_filename(file.filename or "attachment")
            media_type = resolve_media_type(declared=file.content_type, filename=filename)
            validate_upload_bytes(data=data, media_type=media_type, settings=settings)
        except UploadRefused as refusal:
            raise HTTPException(
                status_code=_STATUS.get(refusal.code, 422),
                detail={"code": refusal.code, "message": refusal.message},
            ) from refusal
        ref = await store.persist_body(workspace_id=workspace_id, data=data, media_type=media_type)
        async with conn_factory() as conn:
            row = await record_chat_upload(
                conn,
                workspace_id=workspace_id,
                user_id=user_id,
                filename=filename,
                media_type=media_type,
                ref=ref,
            )
        return UploadResponseV1(
            data=UploadV1(
                upload_id=str(row.upload_id),
                filename=row.filename,
                media_type=row.media_type,
                byte_count=row.byte_count,
                artifact_key=row.artifact_key,
                sha256=row.sha256,
            )
        )

    @router.get("/uploads/{upload_id}/bytes")
    async def get_upload_bytes(upload_id: UUID, workspace_id: WorkspaceDep) -> Response:
        store = _require_artifacts()
        async with conn_factory() as conn:
            row = (
                await get_chat_uploads(conn, workspace_id=workspace_id, upload_ids=[upload_id])
            ).get(upload_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "UPLOAD_NOT_FOUND", "message": "no such upload"},
            )
        try:
            data = await store.read(
                ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=row.artifact_key,
                    sha256=row.sha256,
                    media_type=row.media_type,
                    byte_count=row.byte_count,
                )
            )
        except ArtifactNotFound as missing:
            # The upload row survives an erasure/purge/tombstone of its bytes, so a readable
            # receipt with unreadable content is a normal end state, not a server fault.
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "UPLOAD_NOT_FOUND",
                    "message": "the upload's bytes are no longer available",
                },
            ) from missing
        # The stored name is already sanitized (no path separators, no control characters); the
        # quote strip is what keeps it from ending the header's quoted string early.
        safe_name = row.filename.replace('"', "")
        return Response(
            content=data,
            media_type=row.media_type,
            headers={
                "Content-Disposition": f'inline; filename="{safe_name}"',
                # The bytes are immutable and tenant-scoped: a shared cache must never hold them.
                "Cache-Control": "private, max-age=3600",
                # A person's file served from the app's own origin: an SVG (or anything a browser
                # might sniff as HTML) opened in a tab must not run script with the viewer's session
                # (review I-5). Pictures still render in <img>.
                "Content-Security-Policy": "sandbox; default-src 'none'",
                "X-Content-Type-Options": "nosniff",
            },
        )
