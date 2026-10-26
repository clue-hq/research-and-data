"""The artifacts library on ``/frontend/v1``: one workspace-wide read and the caller's marks.

Spec ``docs/superpowers/specs/archive/2026-09-15-artifacts-page-integration-design.md`` §3.1–§3.2.
The read is the workspace-wide form of the per-project design-artifact feed; the marks are user
metadata (saved, last-viewed) and never document state — document writes (rename, archive) are
governed design tools on the design API, not routes here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from clue_api.auth_wiring import principal_from_request
from clue_api.design_leg_wiring import design_document_card_fields, workspace_design_documents
from clue_api.frontend_read.app import WorkspaceDep
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_obs.otel import get_metric_sink, traced_step
from clue_projections.pagination import InvalidCursorError, decode_cursor, encode_cursor

log = get_logger("clue_api.frontend_read.artifacts")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class ArtifactAccountV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    domain: str | None
    account_entity_id: str | None


class ArtifactV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    document_id: str
    project_id: str
    project_title: str
    kind: str
    title: str
    status: str
    current_version: int
    created_at: str
    updated_at: str
    origin_thread_id: str
    artifact_type: str | None
    width_px: int | None
    height_px: int | None
    account: ArtifactAccountV1 | None
    archived_at: str | None
    saved: bool
    last_viewed_at: str | None


class ArtifactListV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifacts: list[ArtifactV1]


class ArtifactPageMetaV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    next_cursor: str | None


class ArtifactListResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ArtifactListV1
    meta: ArtifactPageMetaV1


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _wire(row: Mapping[str, Any]) -> ArtifactV1:
    fields = design_document_card_fields(row)
    account = (
        ArtifactAccountV1(
            id=str(row["account_id"]),
            name=str(row["account_name"]),
            domain=row["account_domain"],
            account_entity_id=(
                None if row["account_entity_id"] is None else str(row["account_entity_id"])
            ),
        )
        if row["account_id"] is not None
        else None
    )
    return ArtifactV1(
        id=str(row["id"]),
        document_id=str(row["id"]),
        project_id=str(row["project_id"]),
        project_title=str(row["project_title"]),
        kind=fields["kind"],
        title=str(row["title"]),
        status=str(row["status"]),
        current_version=int(row["current_version"]),
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
        origin_thread_id=str(row["origin_thread_id"]),
        artifact_type=fields["artifact_type"],
        width_px=fields["width_px"],
        height_px=fields["height_px"],
        account=account,
        archived_at=_iso(row["archived_at"]),
        saved=bool(row["saved"]),
        last_viewed_at=_iso(row["last_viewed_at"]),
    )


def _caller_user_id(request: Request) -> str | None:
    principal = principal_from_request(request)
    return None if principal is None else principal.user_id


def _require_caller(request: Request) -> str:
    """The marks are the caller's own, so a write needs a real user (401 otherwise; no dev
    stand-in — the marks table's user FK would refuse one anyway)."""

    user_id = _caller_user_id(request)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "an authenticated session is required"},
        )
    return user_id


class ArtifactSavedUpdateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved: bool


class ArtifactSavedV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    saved: bool


class ArtifactSavedResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ArtifactSavedV1


class ArtifactViewedV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    last_viewed_at: str


class ArtifactViewedResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ArtifactViewedV1


async def _require_document(conn: Any, *, workspace_id: str, document_id: str) -> None:
    """The mark is about a document of THIS workspace; anything else is absent, not refused."""

    exists = (
        await conn.execute(
            text("SELECT 1 FROM design_document WHERE id = :d AND workspace_id = :w"),
            {"d": document_id, "w": workspace_id},
        )
    ).first()
    if exists is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": "no such artifact in this workspace"},
        )


def register_artifact_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    @router.get("/artifacts", response_model=ArtifactListResponseV1)
    async def list_artifacts(
        request: Request,
        workspace_id: WorkspaceDep,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: Annotated[str | None, Query()] = None,
    ) -> ArtifactListResponseV1:
        cursor_updated_at: datetime | None = None
        cursor_id: str | None = None
        if cursor is not None:
            try:
                position, cursor_id = decode_cursor(cursor, parts=2)
                cursor_updated_at = datetime.fromisoformat(position)
            except (InvalidCursorError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail={"code": "INVALID_CURSOR", "message": str(exc)}
                ) from exc
        async with conn_factory() as conn:
            with traced_step(
                "artifacts.library_read",
                workspace_id=workspace_id,
                limit=limit,
                paged=cursor is not None,
            ):
                rows = await workspace_design_documents(
                    conn,
                    workspace_id=workspace_id,
                    user_id=_caller_user_id(request),
                    limit=limit + 1,
                    cursor_updated_at=cursor_updated_at,
                    cursor_id=cursor_id,
                )
        page = rows[:limit]
        next_cursor = (
            encode_cursor(page[-1]["updated_at"].isoformat(), str(page[-1]["id"]))
            if len(rows) > limit
            else None
        )
        return ArtifactListResponseV1(
            data=ArtifactListV1(artifacts=[_wire(row) for row in page]),
            meta=ArtifactPageMetaV1(next_cursor=next_cursor),
        )

    @router.put("/artifacts/{artifact_id}/saved", response_model=ArtifactSavedResponseV1)
    async def set_saved(
        artifact_id: str, body: ArtifactSavedUpdateV1, request: Request, workspace_id: WorkspaceDep
    ) -> ArtifactSavedResponseV1:
        user_id = _require_caller(request)
        async with conn_factory() as conn:
            await _require_document(conn, workspace_id=workspace_id, document_id=artifact_id)
            await conn.execute(
                text(
                    "INSERT INTO design_document_user_mark (workspace_id, user_id, document_id,"
                    " saved)"
                    " VALUES (:w, :u, :d, :s)"
                    " ON CONFLICT (workspace_id, user_id, document_id)"
                    " DO UPDATE SET saved = EXCLUDED.saved, updated_at = now()"
                ),
                {"w": workspace_id, "u": user_id, "d": artifact_id, "s": body.saved},
            )
        get_metric_sink().add(
            "artifacts.mark.written",
            1,
            {"kind": "saved", "value": "true" if body.saved else "false"},
        )
        return ArtifactSavedResponseV1(data=ArtifactSavedV1(saved=body.saved))

    @router.post("/artifacts/{artifact_id}/viewed", response_model=ArtifactViewedResponseV1)
    async def record_viewed(
        artifact_id: str, request: Request, workspace_id: WorkspaceDep
    ) -> ArtifactViewedResponseV1:
        user_id = _require_caller(request)
        viewed_at = datetime.now(UTC)
        async with conn_factory() as conn:
            await _require_document(conn, workspace_id=workspace_id, document_id=artifact_id)
            await conn.execute(
                text(
                    "INSERT INTO design_document_user_mark (workspace_id, user_id, document_id,"
                    " last_viewed_at)"
                    " VALUES (:w, :u, :d, :at)"
                    " ON CONFLICT (workspace_id, user_id, document_id)"
                    " DO UPDATE SET last_viewed_at = EXCLUDED.last_viewed_at, updated_at = now()"
                ),
                {"w": workspace_id, "u": user_id, "d": artifact_id, "at": viewed_at},
            )
        get_metric_sink().add("artifacts.mark.written", 1, {"kind": "viewed", "value": "true"})
        return ArtifactViewedResponseV1(data=ArtifactViewedV1(last_viewed_at=viewed_at.isoformat()))
