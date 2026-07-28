"""C7.7 authorized HTTP surface for live and saved structured research views."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text

from clue_config import Settings
from clue_core import (
    ClaimId,
    EntityId,
    EvidenceAccessRequest,
    EvidenceAccessService,
    EvidenceActionKind,
    OperationId,
    ProjectRunId,
    ResearchSectionKind,
    ResearchStatementId,
    ResearchView,
    ResearchViewComposer,
    ResearchViewReadRequest,
    ResearchViewSnapshotId,
    operation_id_from_key,
)
from clue_db import ConnFactory
from clue_projections import PROJECTIONS_SCHEMA_VERSION, research_view_statuses
from clue_research.narrative import (
    ResearchViewCompositionError,
    ResearchViewSnapshotService,
)
from clue_toolbelt import (
    Actor,
    IdempotencyConflict,
    PreconditionFailed,
    ToolContext,
    ToolInvoker,
)


def research_workspace_resolver(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> str:
    if not x_workspace_id:
        raise HTTPException(status_code=401, detail="missing X-Workspace-Id (tenant) header")
    return x_workspace_id


def research_actor_resolver(
    x_actor: Annotated[str | None, Header(alias="X-Actor")] = None,
) -> Actor:
    if x_actor is None or x_actor == "human":
        return "human"
    if x_actor == "agent":
        return "agent"
    raise HTTPException(status_code=422, detail="X-Actor must be 'human' or 'agent'")


WorkspaceDep = Annotated[str, Depends(research_workspace_resolver)]
ActorDep = Annotated[Actor, Depends(research_actor_resolver)]


class ComposeResearchViewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    project_run_id: UUID
    subject_entity_id: UUID
    product_id: str | None = Field(default=None, min_length=1)
    supersedes_snapshot_id: UUID | None = None


class RecheckResearchViewRequestBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    subject_entity_id: UUID
    section_kinds: tuple[ResearchSectionKind, ...] = ()
    request_research: bool = False


class EvidenceActionRequestBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    subject_entity_id: UUID
    claim_id: UUID
    action_id: UUID
    desired_action: EvidenceActionKind


def _etag(source_state_sha256: str) -> str:
    return f'"{source_state_sha256}"'


def _page_view(
    view: ResearchView,
    *,
    section_kind: ResearchSectionKind | None,
    cursor: int,
    limit: int,
) -> dict[str, Any]:
    """Return full detail or one stable item page while carrying the full-view hash."""

    if section_kind is None:
        return {
            "schema_version": view.schema_version,
            "view": view.model_dump(mode="json"),
            "pagination": None,
        }
    section = next((item for item in view.sections if item.kind is section_kind), None)
    if section is None:
        raise HTTPException(status_code=404, detail="no such research-view section")
    bounded_cursor = max(cursor, 0)
    bounded_limit = min(max(limit, 1), 100)
    items = section.items[bounded_cursor : bounded_cursor + bounded_limit]
    next_cursor = (
        bounded_cursor + bounded_limit
        if bounded_cursor + bounded_limit < len(section.items)
        else None
    )
    section_payload = section.model_dump(mode="json")
    section_payload["items"] = [item.model_dump(mode="json") for item in items]
    return {
        "schema_version": view.schema_version,
        "view_ref": {
            "view_id": str(view.view_id),
            "snapshot_id": str(view.snapshot_id) if view.snapshot_id is not None else None,
            "workspace_id": view.workspace_id,
            "project_id": view.project_id,
            "project_run_id": str(view.project_run_id),
            "subject": view.subject.model_dump(mode="json"),
            "product_id": view.product_id,
            "source_state_sha256": view.source_state_sha256,
        },
        "status_summary": view.status_summary.model_dump(mode="json"),
        "coverage_summary": view.coverage_summary.model_dump(mode="json"),
        "section": section_payload,
        "pagination": {
            "cursor": bounded_cursor,
            "limit": bounded_limit,
            "next_cursor": next_cursor,
            "total_items": len(section.items),
        },
    }


def build_research_view_router(
    *,
    composer: ResearchViewComposer,
    snapshots: ResearchViewSnapshotService,
    evidence_access: EvidenceAccessService,
    tool_invoker: ToolInvoker,
    conn_factory: ConnFactory,
    settings: Settings,
) -> APIRouter:
    """Build canonical and legacy-alias routes over one authorization/composition path."""

    router = APIRouter()

    async def scope_request(
        *,
        workspace_id: str,
        project_id: str,
        subject_entity_id: UUID,
        subject_type: Literal["account", "contact"],
    ) -> ResearchViewReadRequest:
        async with conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT pr.id, p.product_id
                        FROM project p
                        JOIN project_run pr
                          ON pr.project_id = p.project_id
                         AND pr.workspace_id = p.workspace_id
                         AND (
                             pr.product_id IS NULL
                             OR pr.product_id IS NOT DISTINCT FROM p.product_id
                         )
                        WHERE p.project_id = :project_id
                          AND p.workspace_id = :workspace_id
                          AND (
                              (
                                  :subject_type = 'account'
                                  AND EXISTS (
                                      SELECT 1
                                      FROM account_entity ae
                                      JOIN account_run ar
                                        ON ar.entity_id = ae.id
                                       AND ar.project_run_id = pr.id
                                      WHERE ae.id = CAST(:subject_entity_id AS uuid)
                                        AND ae.workspace_id = :workspace_id
                                        AND ae.merged_into IS NULL
                                  )
                              )
                              OR (
                                  :subject_type = 'contact'
                                  AND EXISTS (
                                      SELECT 1
                                      FROM contact_entity ce
                                      JOIN account_run ar
                                        ON ar.entity_id = ce.account_entity_id
                                       AND ar.project_run_id = pr.id
                                      WHERE ce.id = CAST(:subject_entity_id AS uuid)
                                        AND ce.workspace_id = :workspace_id
                                        AND ce.merged_into IS NULL
                                  )
                              )
                          )
                        ORDER BY pr.created_at DESC, pr.id DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "subject_entity_id": subject_entity_id,
                        "subject_type": subject_type,
                    },
                )
            ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="research view not found")
        return ResearchViewReadRequest(
            workspace_id=workspace_id,
            project_id=project_id,
            project_run_id=ProjectRunId(row[0]),
            subject_entity_id=EntityId(subject_entity_id),
            product_id=row[1],
        )

    async def compose_live(request: ResearchViewReadRequest) -> ResearchView:
        try:
            return await composer.compose(request)
        except ResearchViewCompositionError as exc:
            raise HTTPException(status_code=404, detail="research view not found") from exc

    async def invoke_mutation(
        *,
        tool_name: str,
        body: dict[str, Any],
        workspace_id: str,
        actor: Actor,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        if not idempotency_key:
            raise HTTPException(status_code=422, detail="missing Idempotency-Key header")
        operation_id: OperationId = operation_id_from_key(
            workspace_id, f"tool:{tool_name}:{idempotency_key}"
        )
        try:
            result = await tool_invoker.invoke(
                tool_name,
                body,
                ToolContext(
                    workspace_id=workspace_id,
                    actor=actor,
                    conn_factory=conn_factory,
                    operation_id=operation_id,
                ),
                version="1",
                idempotency_key=idempotency_key,
            )
        except PreconditionFailed as exc:
            status = (
                404
                if "research_view_subject_not_found" in exc.reason_codes
                or "research_view_snapshot_not_found" in exc.reason_codes
                else 422
            )
            raise HTTPException(
                status_code=status,
                detail={
                    "error": "precondition_failed",
                    "reason_codes": list(exc.reason_codes),
                },
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_conflict", "reason": exc.reason},
            ) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "result": result.references,
            "replayed": result.replayed,
        }

    async def live_response(
        *,
        project_id: str,
        subject_entity_id: UUID,
        subject_type: Literal["account", "contact"],
        workspace_id: str,
        response: Response,
        section_kind: ResearchSectionKind | None,
        cursor: int,
        limit: int,
    ) -> dict[str, Any]:
        request = await scope_request(
            workspace_id=workspace_id,
            project_id=project_id,
            subject_entity_id=subject_entity_id,
            subject_type=subject_type,
        )
        view = await compose_live(request)
        response.headers["ETag"] = _etag(view.source_state_sha256)
        response.headers["X-Research-Source-State-Sha256"] = view.source_state_sha256
        return _page_view(view, section_kind=section_kind, cursor=cursor, limit=limit)

    async def get_account_view(
        project_id: str,
        account_id: UUID,
        response: Response,
        workspace_id: WorkspaceDep,
        section_kind: Annotated[ResearchSectionKind | None, Query()] = None,
        cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        return await live_response(
            project_id=project_id,
            subject_entity_id=account_id,
            subject_type="account",
            workspace_id=workspace_id,
            response=response,
            section_kind=section_kind,
            cursor=cursor,
            limit=limit,
        )

    async def get_contact_view(
        project_id: str,
        contact_id: UUID,
        response: Response,
        workspace_id: WorkspaceDep,
        section_kind: Annotated[ResearchSectionKind | None, Query()] = None,
        cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        return await live_response(
            project_id=project_id,
            subject_entity_id=contact_id,
            subject_type="contact",
            workspace_id=workspace_id,
            response=response,
            section_kind=section_kind,
            cursor=cursor,
            limit=limit,
        )

    async def get_snapshot(
        snapshot_id: UUID,
        response: Response,
        workspace_id: WorkspaceDep,
        section_kind: Annotated[ResearchSectionKind | None, Query()] = None,
        cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        try:
            view = await snapshots.resolve(
                workspace_id=workspace_id,
                snapshot_id=ResearchViewSnapshotId(snapshot_id),
            )
        except ResearchViewCompositionError as exc:
            raise HTTPException(status_code=404, detail="research-view snapshot not found") from exc
        if view is None:
            raise HTTPException(status_code=404, detail="research-view snapshot not found")
        response.headers["ETag"] = _etag(view.source_state_sha256)
        response.headers["X-Research-Source-State-Sha256"] = view.source_state_sha256
        return _page_view(view, section_kind=section_kind, cursor=cursor, limit=limit)

    async def post_snapshot(
        body: ComposeResearchViewRequest,
        workspace_id: WorkspaceDep,
        actor: ActorDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        return await invoke_mutation(
            tool_name="compose_dossier",
            body=body.model_dump(mode="json"),
            workspace_id=workspace_id,
            actor=actor,
            idempotency_key=idempotency_key,
        )

    async def post_recheck(
        snapshot_id: UUID,
        body: RecheckResearchViewRequestBody,
        workspace_id: WorkspaceDep,
        actor: ActorDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        return await invoke_mutation(
            tool_name="recheck_research_view",
            body={**body.model_dump(mode="json"), "snapshot_id": str(snapshot_id)},
            workspace_id=workspace_id,
            actor=actor,
            idempotency_key=idempotency_key,
        )

    async def post_evidence_action(
        statement_id: UUID,
        body: EvidenceActionRequestBody,
        workspace_id: WorkspaceDep,
        actor: ActorDep,
    ) -> dict[str, Any]:
        result = await evidence_access.request_access(
            EvidenceAccessRequest(
                workspace_id=workspace_id,
                project_id=body.project_id,
                actor_id=actor,
                subject_entity_id=EntityId(body.subject_entity_id),
                statement_id=ResearchStatementId(statement_id),
                claim_id=ClaimId(body.claim_id),
                action_id=body.action_id,
                desired_action=body.desired_action,
            )
        )
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "result": result.model_dump(mode="json"),
        }

    async def get_statuses(
        project_id: str,
        workspace_id: WorkspaceDep,
        subject_entity_type: Annotated[str | None, Query()] = None,
        cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        try:
            page = await research_view_statuses(
                workspace_id=workspace_id,
                project_id=project_id,
                subject_entity_type=subject_entity_type,
                cursor=cursor,
                limit=limit,
                conn_factory=conn_factory,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema_version": PROJECTIONS_SCHEMA_VERSION,
            "status": page.model_dump(mode="json"),
        }

    def legacy_headers(response: Response) -> None:
        response.headers["Deprecation"] = "true"
        response.headers["Link"] = '</v1/research-view-snapshots>; rel="successor-version"'
        response.headers["X-Clue-Canonical-Resource"] = "research-view"

    async def get_legacy_account_dossier(
        project_id: str,
        account_id: UUID,
        response: Response,
        workspace_id: WorkspaceDep,
        section_kind: Annotated[ResearchSectionKind | None, Query()] = None,
        cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        payload = await live_response(
            project_id=project_id,
            subject_entity_id=account_id,
            subject_type="account",
            workspace_id=workspace_id,
            response=response,
            section_kind=section_kind,
            cursor=cursor,
            limit=limit,
        )
        legacy_headers(response)
        return payload

    async def get_legacy_contact_dossier(
        project_id: str,
        contact_id: UUID,
        response: Response,
        workspace_id: WorkspaceDep,
        section_kind: Annotated[ResearchSectionKind | None, Query()] = None,
        cursor: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        payload = await live_response(
            project_id=project_id,
            subject_entity_id=contact_id,
            subject_type="contact",
            workspace_id=workspace_id,
            response=response,
            section_kind=section_kind,
            cursor=cursor,
            limit=limit,
        )
        legacy_headers(response)
        return payload

    async def post_legacy_dossier(
        body: ComposeResearchViewRequest,
        response: Response,
        workspace_id: WorkspaceDep,
        actor: ActorDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        payload = await invoke_mutation(
            tool_name="compose_dossier",
            body=body.model_dump(mode="json"),
            workspace_id=workspace_id,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        legacy_headers(response)
        return payload

    if settings.c7_research_view_read_enabled:
        router.add_api_route(
            "/v1/projects/{project_id}/accounts/{account_id}/research-view",
            get_account_view,
            methods=["GET"],
        )
        router.add_api_route(
            "/v1/projects/{project_id}/contacts/{contact_id}/research-view",
            get_contact_view,
            methods=["GET"],
        )
        router.add_api_route(
            "/v1/research-view-snapshots/{snapshot_id}",
            get_snapshot,
            methods=["GET"],
        )
        router.add_api_route(
            "/v1/projects/{project_id}/research-view-status",
            get_statuses,
            methods=["GET"],
        )
    if settings.c7_snapshot_compose_enabled:
        router.add_api_route(
            "/v1/research-view-snapshots",
            post_snapshot,
            methods=["POST"],
        )
    if settings.c7_recheck_enabled:
        router.add_api_route(
            "/v1/research-view-snapshots/{snapshot_id}/recheck",
            post_recheck,
            methods=["POST"],
        )
    if settings.c7_evidence_actions_enabled:
        router.add_api_route(
            "/v1/research-statements/{statement_id}/evidence-action",
            post_evidence_action,
            methods=["POST"],
        )
    if settings.c7_legacy_dossier_alias_enabled and settings.c7_research_view_read_enabled:
        router.add_api_route(
            "/v1/projects/{project_id}/accounts/{account_id}/dossier",
            get_legacy_account_dossier,
            methods=["GET"],
        )
        router.add_api_route(
            "/v1/projects/{project_id}/contacts/{contact_id}/dossier",
            get_legacy_contact_dossier,
            methods=["GET"],
        )
    if settings.c7_legacy_dossier_alias_enabled and settings.c7_snapshot_compose_enabled:
        router.add_api_route(
            "/v1/dossier",
            post_legacy_dossier,
            methods=["POST"],
        )

    return router


__all__ = [
    "build_research_view_router",
    "research_actor_resolver",
    "research_workspace_resolver",
]
