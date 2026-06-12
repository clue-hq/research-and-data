from __future__ import annotations

import base64
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core import CoreClient, CoreError, has_error_diagnostics
from .database import NotFoundError, Repository, connect, run_migrations
from .dto import (
    brand_compatibility_dto,
    brand_governance_dto,
    brand_kit_created_dto,
    brand_kit_detail_dto,
    brand_kit_generation_dto,
    brand_kit_summary,
    brand_kit_validation_dto,
    diagnostic_views,
    diagnostics_response,
    document_summary,
    document_created_dto,
    finalize_dto,
    operation_application_dto,
    operation_summaries,
    preflight_dto,
    preflight_preview_dto,
    scene_replaced_dto,
    snapshot_summary,
)
from .models import (
    AgentTurnPreviewRequest,
    AttachBrandKitRequest,
    ApplyOperationsRequest,
    ApplyStructuredEditRequest,
    AssetMetadataRequest,
    BrandCompatibilityRequest,
    CompileStylesBrandKitRequest,
    CreateDocumentRequest,
    CreateBrandKitRequest,
    CreateSnapshotRequest,
    ExportDocumentRequest,
    ExportPreviewRequest,
    FinalizeTemplateRequest,
    GenerateBrandKitRequest,
    PreflightRequest,
    PreflightPreviewRequest,
    ReplaceSceneRequest,
    ValidateBrandKitRequest,
    ValidateDocumentBrandGovernanceRequest,
)
from .observability import (
    REQUEST_ID_HEADER,
    artifact_summary,
    bind_request_id,
    configure_structured_logging,
    diagnostic_summary,
    duration_ms,
    log_event,
    new_request_id,
    reset_request_id,
)


JsonObject = Dict[str, Any]
api_logger = logging.getLogger("lumen_api.api")


def cors_origins() -> List[str]:
    raw = os.environ.get(
        "LUMEN_API_CORS_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000",
    )
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["http://127.0.0.1:3000"]


def create_app(database_path: Optional[Path] = None, migrate: bool = True) -> FastAPI:
    configure_structured_logging()
    app = FastAPI(title="ABM Design Engine Persistence API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.database_path = database_path or Path(
        os.environ.get("LUMEN_API_DATABASE_PATH", "apps/api/lumen-api.sqlite3")
    )
    app.state.core = CoreClient()
    app.state.agent_turn_runner = None
    if migrate:
        run_migrations(app.state.database_path)

    @app.middleware("http")
    async def structured_request_logging(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        request.state.request_id = request_id
        token = bind_request_id(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log_event(
                api_logger,
                logging.ERROR,
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms(start),
                client_host=request.client.host if request.client else None,
            )
            reset_request_id(token)
            raise

        response.headers[REQUEST_ID_HEADER] = request_id
        route = request.scope.get("route")
        log_event(
            api_logger,
            logging.INFO,
            "http_request_completed",
            method=request.method,
            path=request.url.path,
            route=getattr(route, "path", None),
            status_code=response.status_code,
            duration_ms=duration_ms(start),
            client_host=request.client.host if request.client else None,
        )
        reset_request_id(token)
        return response

    @app.exception_handler(NotFoundError)
    def not_found_handler(_request: Request, error: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": not_found_detail(error)})

    @app.exception_handler(sqlite3.Error)
    def database_error_handler(_request: Request, error: sqlite3.Error) -> JSONResponse:
        log_event(
            api_logger,
            logging.ERROR,
            "database_error",
            error_type=type(error).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "database.error",
                    "message": "database operation failed",
                }
            },
        )

    def repository() -> Repository:
        connection = connect(app.state.database_path)
        try:
            yield Repository(connection)
        finally:
            connection.close()

    @app.post("/brand-kits")
    def create_brand_kit(
        payload: CreateBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        try:
            validation = app.state.core.validate_brand_kit(
                payload.brand_kit, product_ready=payload.product_ready
            )
            brand_kit = validation["brand_kit"]
            summary_response = app.state.core.summarize_brand_kit(
                brand_kit, raise_on_error=False
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = summary_response.get("diagnostics") or validation.get(
            "diagnostics", []
        )
        try:
            record = repo.create_brand_kit(
                brand_kit,
                summary_response.get("brand_summary") or {},
                diagnostics,
                payload.source,
            )
        except sqlite3.IntegrityError as error:
            raise duplicate_brand_kit_error(brand_kit) from error
        return brand_kit_created_dto(record, diagnostics)

    @app.post("/brand-kits/generate")
    def generate_brand_kit(
        payload: GenerateBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        try:
            result = app.state.core.generate_brand_kit(payload.seed)
        except CoreError as error:
            raise core_http_error(error) from error

        brand_kit = result["brand_kit"]
        diagnostics = result.get("diagnostics", [])
        record = None
        if payload.persist:
            try:
                record = repo.create_brand_kit(
                    brand_kit,
                    result.get("brand_summary") or {},
                    diagnostics,
                    "generated",
                )
            except sqlite3.IntegrityError as error:
                raise duplicate_brand_kit_error(brand_kit) from error
        return brand_kit_generation_dto(
            record,
            brand_kit,
            result.get("brand_summary"),
            result.get("brand_generation") or {},
            diagnostics,
        )

    @app.post("/brand-kits/compile-styles")
    def compile_styles_brand_kit(
        payload: CompileStylesBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        try:
            result = app.state.core.compile_styles_brand_kit(
                payload.source,
                payload.brand_kit_id,
                payload.version,
                payload.name,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        brand_kit = result["brand_kit"]
        diagnostics = result.get("diagnostics", [])
        record = None
        if payload.persist:
            try:
                record = repo.create_brand_kit(
                    brand_kit,
                    result.get("brand_summary") or {},
                    diagnostics,
                    "styles",
                )
            except sqlite3.IntegrityError as error:
                raise duplicate_brand_kit_error(brand_kit) from error
        return brand_kit_generation_dto(
            record,
            brand_kit,
            result.get("brand_summary"),
            {},
            diagnostics,
        )

    @app.post("/brand-kits/validate")
    def validate_brand_kit(
        payload: ValidateBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        brand_kit = resolve_brand_kit_payload(
            repo,
            payload.brand_kit,
            payload.brand_kit_id,
            payload.version,
        )
        try:
            result = app.state.core.validate_brand_kit(
                brand_kit,
                product_ready=payload.product_ready,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error
        return brand_kit_validation_dto(
            brand_kit,
            result.get("diagnostics", []),
            payload.product_ready,
        )

    @app.post("/brand-kits/compatibility")
    def compare_brand_kit_compatibility(
        payload: BrandCompatibilityRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        from_brand_kit, from_record = resolve_brand_kit_for_compatibility(
            repo, payload.from_brand_kit, payload.from_ref
        )
        to_brand_kit, to_record = resolve_brand_kit_for_compatibility(
            repo, payload.to_brand_kit, payload.to_ref
        )
        try:
            result = app.state.core.compare_brand_kit_compatibility(
                from_brand_kit, to_brand_kit, raise_on_error=False
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        stored_report = None
        if payload.persist_report and from_record is not None and to_record is not None:
            stored_report = repo.create_brand_compatibility_report(
                new_id("brand_report"),
                from_record["brand_kit"],
                to_record["brand_kit"],
                result.get("brand_compatibility") or {},
                diagnostics,
            )
        return brand_compatibility_dto(
            result.get("brand_compatibility") or {},
            diagnostics,
            stored_report,
        )

    @app.get("/brand-kits")
    def list_brand_kits(
        all_versions: bool = Query(default=False),
        repo: Repository = Depends(repository),
    ) -> List[JsonObject]:
        return [
            brand_kit_summary(record)
            for record in repo.list_brand_kits(all_versions=all_versions)
        ]

    @app.get("/brand-kits/{brand_kit_id}")
    def get_latest_brand_kit(
        brand_kit_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return brand_kit_detail_dto(repo.require_brand_kit(brand_kit_id))

    @app.get("/brand-kits/{brand_kit_id}/versions/{version}")
    def get_brand_kit_version(
        brand_kit_id: str, version: int, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return brand_kit_detail_dto(repo.require_brand_kit(brand_kit_id, version))

    @app.get("/brand-compatibility-reports/{report_id}")
    def get_brand_compatibility_report(
        report_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_brand_compatibility_report(report_id)

    @app.post("/documents")
    def create_document(
        payload: CreateDocumentRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        document_id = payload.document_id or new_id("doc")
        try:
            if payload.scene is None:
                scene = app.state.core.new_scene(
                    document_id,
                    payload.title,
                    payload.artifact_type,
                    payload.medium,
                )
            else:
                scene = payload.scene
                scene.setdefault("meta", {})["id"] = scene.get("meta", {}).get(
                    "id", document_id
                )
                validation = app.state.core.validate_scene(scene)
                if has_error_diagnostics(validation.get("diagnostics", [])):
                    diagnostics = validation.get("diagnostics", [])
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "scene.validation_failed",
                            "diagnostics": diagnostics,
                            "views": diagnostic_views(diagnostics, diagnostics),
                        },
                    )
                scene = validation["scene"]
                reject_finalized_scene_status(scene)

            if scene["meta"]["id"] != document_id:
                document_id = scene["meta"]["id"]
            document = repo.create_document(
                scene,
                brand_kit=payload.brand_kit,
                effective_brand_source="document" if payload.brand_kit else None,
            )
            log_event(
                api_logger,
                logging.INFO,
                "document_created",
                document_id=document["id"],
                title=document["title"],
                version=document["current_version"],
                has_brand_kit=payload.brand_kit is not None,
            )
            return document_created_dto(document)
        except CoreError as error:
            raise core_http_error(error) from error

    @app.get("/documents/{document_id}")
    def get_document(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return public_document(require_document(repo, document_id))

    @app.put("/documents/{document_id}/scene")
    def replace_scene(
        document_id: str,
        payload: ReplaceSceneRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "replace the current scene")
        try:
            validation = app.state.core.validate_scene(payload.scene)
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = validation.get("diagnostics", [])
        if has_error_diagnostics(diagnostics):
            repo.store_diagnostics(document_id, "structural", diagnostics)
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "scene.validation_failed",
                    "diagnostics": diagnostics,
                    "views": diagnostic_views(diagnostics, diagnostics),
                },
            )
        scene = validation["scene"]
        reject_finalized_scene_status(scene)
        if scene["meta"]["id"] != document_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "scene.document_id_mismatch",
                    "message": "scene.meta.id must match the route document id",
                },
            )
        document = repo.replace_scene(document_id, scene, diagnostics)
        log_event(
            api_logger,
            logging.INFO,
            "document_scene_replaced",
            document_id=document_id,
            version=document["current_version"],
            **diagnostic_summary(diagnostics),
        )
        return scene_replaced_dto(document, diagnostics)

    @app.post("/documents/{document_id}/operations")
    def apply_operations(
        document_id: str,
        payload: ApplyOperationsRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        if not payload.operations:
            raise HTTPException(
                status_code=422,
                detail={"code": "operations.empty", "message": "operations cannot be empty"},
            )
        document = require_document(repo, document_id)
        require_draft_document(document, "apply operations")
        require_base_version(document, payload.base_version)
        try:
            result = app.state.core.apply_operations(
                document["scene"], payload.operations
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        envelope = {
            "intent": payload.intent or "apply_operations",
            "checkpoint_label": payload.checkpoint,
            "inverse_operations": (result.get("edit") or {}).get(
                "inverse_operations"
            ),
        }
        updated = repo.update_document_state(
            document_id,
            result["scene"],
            diagnostics,
            payload.operations,
            payload.source,
            payload.actor.kind,
            payload.actor.id,
            "structural",
            effective_brand=None,
            envelope=envelope,
        )
        snapshot = None
        if payload.snapshot_reason:
            snapshot = repo.create_snapshot(
                document_id, new_id("snap"), payload.snapshot_reason
            )
        log_event(
            api_logger,
            logging.INFO,
            "operation_batch_applied",
            document_id=document_id,
            operation_count=len(payload.operations),
            applied_operations=result.get("applied_operations", 0),
            source=payload.source,
            actor_kind=payload.actor.kind,
            snapshot_created=snapshot is not None,
            **diagnostic_summary(diagnostics),
        )
        response = operation_application_dto(
            updated,
            result.get("applied_operations", 0),
            payload.operations,
            diagnostics,
            snapshot,
        )
        response["envelope"] = latest_envelope_summary(repo, document_id)
        return response

    @app.get("/documents/{document_id}/operations")
    def list_operations(
        document_id: str, repo: Repository = Depends(repository)
    ) -> List[JsonObject]:
        return repo.list_operations(document_id)

    @app.get("/documents/{document_id}/history")
    def list_history(
        document_id: str,
        limit: int = 50,
        offset: int = 0,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        envelopes = repo.list_envelopes(
            document_id, limit=limit, offset=offset, newest_first=True
        )
        return {
            "schema_version": 1,
            "document_id": document_id,
            "envelopes": envelopes,
        }

    @app.post("/documents/{document_id}/edits")
    def apply_structured_edit(
        document_id: str,
        payload: ApplyStructuredEditRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "apply structured edit")
        require_base_version(document, payload.base_version)
        try:
            result = app.state.core.apply_structured_edit(document["scene"], payload.edit)
        except CoreError as error:
            raise core_http_error(error) from error

        operations = result.get("operations") or []
        if not operations:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "edits.no_operations",
                    "message": "structured edit did not produce canonical operations",
                    "edit": result.get("edit") or payload.edit,
                },
            )

        diagnostics = result.get("diagnostics", [])
        edit_metadata = result.get("edit") or {}
        envelope = {
            "intent": edit_metadata.get("intent") or "structured_edit",
            "checkpoint_label": payload.checkpoint
            or edit_metadata.get("checkpoint_label"),
            "touched_targets": edit_metadata.get("touched_targets") or [],
            "inverse_operations": edit_metadata.get("inverse_operations"),
            "lineage": edit_metadata.get("lineage"),
        }
        updated = repo.update_document_state(
            document_id,
            result["scene"],
            diagnostics,
            operations,
            payload.source,
            payload.actor.kind,
            payload.actor.id,
            "structural",
            effective_brand=None,
            envelope=envelope,
        )
        snapshot = None
        if payload.snapshot_reason:
            snapshot = repo.create_snapshot(
                document_id, new_id("snap"), payload.snapshot_reason
            )
        log_event(
            api_logger,
            logging.INFO,
            "structured_edit_applied",
            document_id=document_id,
            edit_kind=(result.get("edit") or {}).get("kind"),
            operation_count=len(operations),
            applied_operations=result.get("applied_operations", 0),
            source=payload.source,
            actor_kind=payload.actor.kind,
            snapshot_created=snapshot is not None,
            **diagnostic_summary(diagnostics),
        )
        response = operation_application_dto(
            updated,
            result.get("applied_operations", 0),
            operations,
            diagnostics,
            snapshot,
        )
        response["edit"] = result.get("edit") or payload.edit
        response["envelope"] = latest_envelope_summary(repo, document_id)
        return response

    @app.post("/documents/{document_id}/snapshots")
    def create_snapshot(
        document_id: str,
        payload: CreateSnapshotRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        require_document(repo, document_id)
        snapshot = repo.create_snapshot(
            document_id, payload.snapshot_id or new_id("snap"), payload.reason
        )
        return {
            "schema_version": 1,
            "status": "created",
            "snapshot": snapshot_summary(snapshot),
        }

    @app.get("/documents/{document_id}/snapshots")
    def list_snapshots(
        document_id: str, repo: Repository = Depends(repository)
    ) -> List[JsonObject]:
        return [snapshot_summary(snapshot) for snapshot in repo.list_snapshots(document_id)]

    @app.get("/documents/{document_id}/snapshots/{snapshot_id}")
    def get_snapshot(
        document_id: str, snapshot_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_snapshot(document_id, snapshot_id)

    @app.post("/documents/{document_id}/preflight")
    def preflight_document(
        document_id: str,
        payload: PreflightRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "preflight the current scene")
        try:
            source, brand_kit = choose_effective_brand(app.state.core, repo, document, payload)
            mode = choose_effective_brand_mode(document, brand_kit, payload.mode)
            result = app.state.core.preflight_scene(document["scene"], brand_kit, mode)
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        preflight = result.get("preflight") or {}
        operations = (
            preflight.get("brand_ref_operations", [])
            + preflight.get("token_operations", [])
            + preflight.get("layout_operations", [])
        )
        updated_document = document
        if not has_error_diagnostics(diagnostics):
            effective = (
                (source, brand_kit, mode)
                if payload.persist_effective_brand or source in {"platform_default", "none"}
                else None
            )
            updated_document = repo.update_document_state(
                document_id,
                result["scene"],
                diagnostics,
                operations,
                "system",
                "system",
                "preflight",
                "preflight",
                effective_brand=effective,
            )
        else:
            repo.store_diagnostics(document_id, "preflight", diagnostics)

        log_event(
            api_logger,
            logging.INFO,
            "preflight_completed",
            document_id=document_id,
            status="failed" if has_error_diagnostics(diagnostics) else "ok",
            effective_brand_source=source,
            brand_kit_id=brand_kit.get("id") if brand_kit else None,
            brand_ref_operations=len(preflight.get("brand_ref_operations", [])),
            token_operations=len(preflight.get("token_operations", [])),
            layout_operations=len(preflight.get("layout_operations", [])),
            **diagnostic_summary(diagnostics),
        )
        return preflight_dto(
            updated_document,
            diagnostics,
            preflight,
            source,
            brand_kit,
        )

    @app.post("/export-preview")
    def export_preview(payload: ExportPreviewRequest) -> JsonObject:
        try:
            result = app.state.core.export_preview(
                payload.scene,
                payload.format,
                payload.page_ids,
                payload.profile,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        export = result.get("export") or {}
        diagnostics = result.get("diagnostics", [])
        if not result.get("ok", False) and not diagnostics:
            diagnostics = diagnostics_from_helper_error(result.get("error"))
        status = (
            "failed"
            if not result.get("ok", False) or has_error_diagnostics(diagnostics)
            else "ok"
        )
        log_event(
            api_logger,
            logging.INFO,
            "export_preview_completed",
            status=status,
            format=payload.format,
            page_id_count=len(payload.page_ids or []),
            **artifact_summary(export),
            **diagnostic_summary(diagnostics),
        )
        return {
            "schema_version": 1,
            "status": status,
            "diagnostics": diagnostics,
            "export": compact_export_result(export),
        }

    @app.post("/agent/turn-preview")
    def agent_turn_preview(payload: AgentTurnPreviewRequest) -> JsonObject:
        runner = app.state.agent_turn_runner or run_agent_turn_preview
        result = runner(payload, repo_root())
        log_event(
            api_logger,
            logging.INFO,
            "agent_turn_preview_completed",
            document_id=payload.document_id,
            active_page_id=payload.active_page_id,
            selected_node_id=payload.selected_node_id,
            status=result.get("status"),
            run_id=result.get("run_id"),
            operation_count=len(result.get("operations", []))
            if isinstance(result.get("operations"), list)
            else 0,
            artifact_count=len(result.get("artifacts", []))
            if isinstance(result.get("artifacts"), list)
            else 0,
            **diagnostic_summary(result.get("diagnostics", [])),
        )
        return result

    @app.post("/documents/{document_id}/export")
    def export_document(
        document_id: str,
        payload: ExportDocumentRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        profile = resolve_document_export_profile(document["scene"], payload)
        export_format = profile.get("format") or payload.format

        try:
            source, brand_kit = choose_effective_brand(app.state.core, repo, document, payload)
            mode = choose_effective_brand_mode(document, brand_kit, payload.mode)
            preflight_result = app.state.core.preflight_scene(
                document["scene"], brand_kit, mode
            )
        except CoreError as error:
            raise core_http_error(error) from error

        preflight_diagnostics = preflight_result.get("diagnostics", [])
        preflight = preflight_result.get("preflight") or {}
        preflight_operations = preflight_operation_list(preflight)
        if preflight.get("has_errors") or has_error_diagnostics(preflight_diagnostics):
            repo.store_diagnostics(document_id, "export", preflight_diagnostics)
            log_event(
                api_logger,
                logging.INFO,
                "document_export_completed",
                document_id=document_id,
                status="failed",
                format=export_format,
                effective_brand_source=source,
                profile_name=profile.get("name"),
                preflight_blocked=True,
                **diagnostic_summary(preflight_diagnostics),
            )
            return document_export_response(
                document,
                "failed",
                preflight_diagnostics,
                preflight,
                preflight_operations,
                source,
                brand_kit,
                mode,
                export={},
                profile=profile,
            )

        export_scene = preflight_result.get("scene", document["scene"])
        updated_document = document
        if payload.persist_preflight and document["status"] == "draft":
            effective = (
                (source, brand_kit, mode)
                if payload.persist_effective_brand or source in {"platform_default", "none"}
                else None
            )
            updated_document = repo.update_document_state(
                document_id,
                export_scene,
                preflight_diagnostics,
                preflight_operations,
                "system",
                "system",
                "export_preflight",
                "preflight",
                effective_brand=effective,
            )
            export_scene = updated_document["scene"]

        try:
            export_result = app.state.core.export_preview(
                export_scene,
                export_format,
                payload.page_ids,
                profile,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        export = export_result.get("export") or {}
        export_diagnostics = export_result.get("diagnostics", [])
        if not export_result.get("ok", False) and not export_diagnostics:
            export_diagnostics = diagnostics_from_helper_error(export_result.get("error"))
        diagnostics = preflight_diagnostics + export_diagnostics
        repo.store_diagnostics(document_id, "export", diagnostics)
        status = (
            "failed"
            if not export_result.get("ok", False) or has_error_diagnostics(diagnostics)
            else "ok"
        )
        log_event(
            api_logger,
            logging.INFO,
            "document_export_completed",
            document_id=document_id,
            status=status,
            format=export_format,
            effective_brand_source=source,
            profile_name=profile.get("name"),
            preflight_blocked=False,
            **artifact_summary(export),
            **diagnostic_summary(diagnostics),
        )
        return document_export_response(
            updated_document,
            status,
            diagnostics,
            preflight,
            preflight_operations,
            source,
            brand_kit,
            mode,
            export=export,
            profile=profile,
        )

    @app.post("/preflight-preview")
    def preflight_preview(
        payload: PreflightPreviewRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        try:
            source, brand_kit = choose_effective_brand_for_scene_preview(
                app.state.core, repo, payload.scene, payload
            )
            mode = choose_effective_brand_mode_for_scene(payload.scene, brand_kit, payload.mode)
            result = app.state.core.preflight_scene(payload.scene, brand_kit, mode)
        except CoreError as error:
            raise core_http_error(error) from error

        return preflight_preview_dto(
            result.get("scene", payload.scene),
            result.get("diagnostics", []),
            result.get("preflight") or {},
            source,
            brand_kit,
            mode,
        )

    @app.post("/documents/{document_id}/brand-kit")
    def attach_brand_kit_to_document(
        document_id: str,
        payload: AttachBrandKitRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "attach a Brand Kit")
        record = repo.require_brand_kit(payload.brand_kit_id, payload.version)
        brand_kit = record["brand_kit"]
        mode = choose_effective_brand_mode(document, brand_kit, payload.mode)
        operation = update_document_brand_operation(document["scene"], brand_kit, mode)
        try:
            result = app.state.core.apply_operations(document["scene"], [operation])
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        updated = repo.update_document_state(
            document_id,
            result["scene"],
            diagnostics,
            [operation],
            "api",
            payload.actor.kind,
            payload.actor.id,
            "structural",
            effective_brand=("brand_kit_library", brand_kit, mode),
        )
        snapshot = None
        if payload.snapshot_reason:
            snapshot = repo.create_snapshot(
                document_id, new_id("snap"), payload.snapshot_reason
            )
        return operation_application_dto(
            updated,
            result.get("applied_operations", 0),
            [operation],
            diagnostics,
            snapshot,
        )

    @app.post("/documents/{document_id}/brand-governance")
    def validate_document_brand_governance(
        document_id: str,
        payload: ValidateDocumentBrandGovernanceRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        brand_kit = resolve_document_governance_brand(repo, document, payload)
        try:
            result = app.state.core.validate_scene_brand_governance(
                document["scene"],
                brand_kit,
                strictness=payload.strictness,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        repo.store_diagnostics(document_id, "brand_governance", diagnostics)
        return brand_governance_dto(
            document,
            brand_kit,
            diagnostics,
            payload.strictness,
        )

    @app.post("/documents/{document_id}/finalize")
    def finalize_document(
        document_id: str,
        payload: FinalizeTemplateRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "finalize the document")
        source_snapshot_id = payload.snapshot_id
        scene = document["scene"]
        if source_snapshot_id:
            scene = repo.require_snapshot(document_id, source_snapshot_id)["scene"]
        template_revision_id = payload.template_revision_id or new_id("tmpl")

        try:
            result = app.state.core.finalize_template(scene, template_revision_id)
        except CoreError as error:
            repo.store_diagnostics(document_id, "finalize", diagnostics_from_core_error(error))
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        finalized_scene = result["scene"]
        revision = repo.create_template_revision(
            document_id,
            template_revision_id,
            source_snapshot_id,
            finalized_scene,
            slot_summary(finalized_scene),
        )
        operation = {
            "kind": "finalize_template",
            "template_revision_id": template_revision_id,
        }
        updated = repo.update_document_state(
            document_id,
            finalized_scene,
            diagnostics,
            [operation],
            "system",
            payload.actor.kind,
            payload.actor.id,
            "finalize",
            effective_brand=None,
        )
        return finalize_dto(updated, revision, diagnostics, operation)

    @app.get("/template-revisions/{template_revision_id}")
    def get_template_revision(
        template_revision_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_template_revision(template_revision_id)

    @app.post("/asset-metadata")
    def create_asset_metadata(
        payload: AssetMetadataRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        data = (
            payload.model_dump()
            if hasattr(payload, "model_dump")
            else payload.dict()
        )
        data["asset_id"] = data["asset_id"] or new_id("asset")
        if data.get("document_id"):
            require_document(repo, data["document_id"])
        return repo.create_asset_metadata(data)

    @app.get("/asset-metadata/{asset_id}")
    def get_asset_metadata(
        asset_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_asset_metadata(asset_id)

    @app.get("/documents/{document_id}/summary")
    def get_summary(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        scene = document["scene"]
        return {
            "document": {
                "id": document["id"],
                "title": document["title"],
                "status": document["status"],
                "current_version": document["current_version"],
                "artifact_type": scene.get("meta", {}).get("artifact_type"),
                "medium": scene.get("meta", {}).get("medium"),
                "brand_kit": scene.get("meta", {}).get("brand_kit"),
            },
            "pages": page_summary(scene),
            "nodes": node_summary(scene),
            "slots": slot_summary(scene),
            "export_profiles": scene.get("export_profiles", []),
        }

    @app.get("/documents/{document_id}/slots")
    def get_slots(
        document_id: str, repo: Repository = Depends(repository)
    ) -> List[JsonObject]:
        document = require_document(repo, document_id)
        return slot_summary(document["scene"])

    @app.get("/documents/{document_id}/geometry")
    def get_geometry(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        scene = document["scene"]
        return {
            "document_id": document_id,
            "geometry": computed_geometry(scene),
            "pages": page_summary(scene),
        }

    @app.get("/documents/{document_id}/diagnostics")
    def get_diagnostics(
        document_id: str,
        kind: Optional[str] = Query(default=None),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        latest = repo.latest_diagnostics(document_id, kind)
        if latest:
            return diagnostics_response(
                latest["document_id"],
                latest["kind"],
                latest["diagnostics"],
                latest["created_at"],
            )
        return diagnostics_response(document_id, kind, [], None)

    return app


app = create_app()


def require_document(repo: Repository, document_id: str) -> JsonObject:
    try:
        return repo.require_document(document_id)
    except NotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=not_found_detail(error),
        ) from error


def not_found_detail(error: NotFoundError) -> JsonObject:
    return {
        "code": f"{error.resource_type}.not_found",
        "message": str(error),
        "resource_id": error.resource_id,
    }


def require_draft_document(document: JsonObject, action: str) -> None:
    if is_finalized_document(document):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document.finalized",
                "message": (
                    f"cannot {action} because document {document['id']} is finalized; "
                    "create a new draft revision before mutating it"
                ),
            },
        )


def require_base_version(document: JsonObject, base_version: Optional[int]) -> None:
    if base_version is not None and base_version != document["current_version"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "edits.base_version_mismatch",
                "message": (
                    f"base_version {base_version} does not match current document "
                    f"version {document['current_version']}; reload the document "
                    "and rebuild the edit"
                ),
                "current_version": document["current_version"],
            },
        )


def latest_envelope_summary(repo: Repository, document_id: str) -> Optional[JsonObject]:
    envelopes = repo.list_envelopes(document_id, limit=1, newest_first=True)
    if not envelopes:
        return None
    envelope = envelopes[0]
    return {
        "batch_id": envelope["batch_id"],
        "seq": envelope["seq"],
        "base_revision": envelope["base_revision"],
        "intent": envelope["intent"],
        "checkpoint_label": envelope["checkpoint_label"],
        "touched_targets": envelope["touched_targets"],
        "invertible": envelope["inverse_operations"] is not None,
        "lineage": envelope["lineage"],
    }


def reject_finalized_scene_status(scene: JsonObject) -> None:
    if is_finalized_scene(scene):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "scene.finalized_status_forbidden",
                "message": (
                    "scene replacement cannot set finalized status; use "
                    "POST /documents/{id}/finalize so core finalization and "
                    "template revision persistence stay in sync"
                ),
            },
        )


def is_finalized_document(document: JsonObject) -> bool:
    return document.get("status") == "finalized" or is_finalized_scene(
        document.get("scene", {})
    )


def is_finalized_scene(scene: JsonObject) -> bool:
    return scene_status_kind(scene) == "finalized"


def scene_status_kind(scene: JsonObject) -> str:
    status = scene.get("meta", {}).get("status", {})
    if isinstance(status, dict):
        return str(status.get("kind", "draft"))
    return str(status)


def public_document(document: JsonObject) -> JsonObject:
    return {
        key: value
        for key, value in document.items()
        if key != "brand_kit"
    }


def duplicate_brand_kit_error(brand_kit: JsonObject) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "brand_kit.version_exists",
            "message": (
                f"Brand Kit {brand_kit.get('id')} version "
                f"{brand_kit.get('version')} already exists"
            ),
            "brand_kit_id": brand_kit.get("id"),
            "version": brand_kit.get("version"),
        },
    )


def resolve_brand_kit_payload(
    repo: Repository,
    brand_kit: Optional[JsonObject],
    brand_kit_id: Optional[str],
    version: Optional[int],
) -> JsonObject:
    if brand_kit is not None and brand_kit_id is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "brand_kit.ambiguous_source",
                "message": "provide either an inline Brand Kit or a stored Brand Kit reference, not both",
            },
        )
    if brand_kit is not None:
        return brand_kit
    if brand_kit_id is not None:
        return repo.require_brand_kit(brand_kit_id, version)["brand_kit"]
    raise HTTPException(
        status_code=422,
        detail={
            "code": "brand_kit.missing",
            "message": "provide brand_kit or brand_kit_id",
        },
    )


def resolve_brand_kit_for_compatibility(
    repo: Repository,
    brand_kit: Optional[JsonObject],
    brand_ref: Optional[Any],
) -> Tuple[JsonObject, Optional[JsonObject]]:
    if brand_kit is not None and brand_ref is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "brand_kit.ambiguous_source",
                "message": "provide either an inline Brand Kit or a stored Brand Kit reference, not both",
            },
        )
    if brand_kit is not None:
        return brand_kit, None
    if brand_ref is not None:
        record = repo.require_brand_kit(brand_ref.brand_kit_id, brand_ref.version)
        return record["brand_kit"], record
    raise HTTPException(
        status_code=422,
        detail={
            "code": "brand_kit.missing",
            "message": "provide an inline Brand Kit or a stored Brand Kit reference",
        },
    )


def resolve_document_governance_brand(
    repo: Repository,
    document: JsonObject,
    payload: ValidateDocumentBrandGovernanceRequest,
) -> JsonObject:
    if payload.brand_kit is not None or payload.brand_kit_id is not None:
        return resolve_brand_kit_payload(
            repo,
            payload.brand_kit,
            payload.brand_kit_id,
            payload.version,
        )
    if document.get("brand_kit") is not None:
        return document["brand_kit"]
    raise HTTPException(
        status_code=422,
        detail={
            "code": "brand_kit.missing",
            "message": "attach a Brand Kit to the document or pass one in the request",
        },
    )


def update_document_brand_operation(
    scene: JsonObject,
    brand_kit: JsonObject,
    mode: Optional[JsonObject],
) -> JsonObject:
    return {
        "kind": "update_document",
        "patch": {
            "title": {"kind": "unchanged"},
            "artifact_type": {"kind": "unchanged"},
            "medium": medium_patch_from_mode(scene, mode),
            "brand_kit": {
                "kind": "set",
                "value": {"id": brand_kit["id"], "version": brand_kit["version"]},
            },
        },
    }


def medium_patch_from_mode(scene: JsonObject, mode: Optional[JsonObject]) -> JsonObject:
    medium = selected_medium(mode)
    if medium is None or medium == scene.get("meta", {}).get("medium"):
        return {"kind": "unchanged"}
    return {"kind": "set", "value": medium}


def selected_medium(mode: Optional[JsonObject]) -> Optional[str]:
    if not mode:
        return None
    values = mode.get("values") if isinstance(mode.get("values"), dict) else mode
    medium = values.get("medium") if isinstance(values, dict) else None
    return str(medium) if medium else None


def choose_effective_brand_mode(
    document: JsonObject,
    brand_kit: Optional[JsonObject],
    requested_mode: Optional[JsonObject],
) -> Optional[JsonObject]:
    if brand_kit is None:
        return None

    values: JsonObject = {}
    modes = brand_kit.get("modes") if isinstance(brand_kit.get("modes"), dict) else {}
    defaults = modes.get("defaults") if isinstance(modes.get("defaults"), dict) else {}
    values.update({str(axis): str(value) for axis, value in defaults.items()})

    stored_mode = document.get("effective_brand_mode")
    stored_values = mode_values(stored_mode)
    values.update(stored_values)

    requested_values = mode_values(requested_mode)
    values.update(requested_values)

    if "medium" not in requested_values:
        scene_medium = scene_medium_mode_value(document["scene"])
        if scene_medium:
            values["medium"] = scene_medium

    return {"values": values}


def mode_values(mode: Optional[JsonObject]) -> JsonObject:
    if not mode:
        return {}
    values = mode.get("values") if isinstance(mode.get("values"), dict) else mode
    if not isinstance(values, dict):
        return {}
    return {str(axis): str(value) for axis, value in values.items() if value is not None}


def scene_medium_mode_value(scene: JsonObject) -> Optional[str]:
    medium = scene.get("meta", {}).get("medium")
    if medium in {"print", "direct_mail"}:
        return "print"
    if medium in {"digital", "email", "ad"}:
        return "digital"
    return None


def choose_effective_brand(
    core: CoreClient,
    repo: Repository,
    document: JsonObject,
    payload: PreflightRequest,
) -> Tuple[str, Optional[JsonObject]]:
    if payload.brand_kit is not None:
        return "request", payload.brand_kit
    if payload.brand_kit_id is not None:
        return (
            "brand_kit_library",
            repo.require_brand_kit(payload.brand_kit_id, payload.brand_kit_version)[
                "brand_kit"
            ],
        )
    if document.get("brand_kit") is not None:
        return "document", document["brand_kit"]
    if payload.generated_default_brand_kit is not None:
        return "generated_default", payload.generated_default_brand_kit
    if payload.strict_no_fallback:
        return "none", None
    return "platform_default", core.platform_default_brand_kit()


def choose_effective_brand_for_scene_preview(
    core: CoreClient,
    repo: Repository,
    scene: JsonObject,
    payload: PreflightPreviewRequest,
) -> Tuple[str, Optional[JsonObject]]:
    if payload.brand_kit is not None:
        return "request", payload.brand_kit
    if payload.brand_kit_id is not None:
        return (
            "brand_kit_library",
            repo.require_brand_kit(payload.brand_kit_id, payload.brand_kit_version)[
                "brand_kit"
            ],
        )

    scene_brand_ref = scene.get("meta", {}).get("brand_kit")
    if isinstance(scene_brand_ref, dict) and scene_brand_ref.get("id"):
        try:
            return (
                "scene_ref",
                repo.require_brand_kit(
                    str(scene_brand_ref["id"]), scene_brand_ref.get("version")
                )["brand_kit"],
            )
        except NotFoundError:
            if payload.strict_no_fallback:
                raise

    if payload.generated_default_brand_kit is not None:
        return "generated_default", payload.generated_default_brand_kit
    if payload.strict_no_fallback:
        return "none", None
    return "platform_default", core.platform_default_brand_kit()


def choose_effective_brand_mode_for_scene(
    scene: JsonObject,
    brand_kit: Optional[JsonObject],
    requested_mode: Optional[JsonObject],
) -> JsonObject:
    defaults = {}
    if brand_kit:
        default_mode = brand_kit.get("default_mode") or {}
        default_values = default_mode.get("values") or {}
        if isinstance(default_values, dict):
            defaults = default_values

    values: JsonObject = {}
    values.update({str(axis): str(value) for axis, value in defaults.items()})
    requested_values = mode_values(requested_mode)
    values.update(requested_values)

    if "medium" not in requested_values:
        medium = scene.get("meta", {}).get("medium")
        if medium in {"print", "direct_mail"}:
            values["medium"] = "print"
        elif medium in {"digital", "email", "ad"}:
            values["medium"] = "digital"

    return {"values": values}


def core_http_error(error: CoreError) -> HTTPException:
    diagnostics = diagnostics_from_core_error(error)
    return HTTPException(
        status_code=422,
        detail={
            "code": error.code,
            "message": error.message,
            "diagnostics": diagnostics,
            "views": diagnostic_views(diagnostics, diagnostics),
        },
    )


def diagnostics_from_core_error(error: CoreError) -> List[JsonObject]:
    if error.diagnostics:
        return error.diagnostics
    return [
        {
            "severity": "error",
            "phase": "operation",
            "code": error.code,
            "message": error.message,
            "subject": None,
            "hint": None,
        }
    ]


def diagnostics_from_helper_error(error: Any) -> List[JsonObject]:
    if not isinstance(error, dict):
        return []
    code = str(error.get("code") or "helper.error")
    message = str(error.get("message") or "core helper returned an error")
    return [
        {
            "severity": "error",
            "phase": "export",
            "code": code,
            "message": message,
            "subject": None,
            "hint": None,
        }
    ]


def resolve_document_export_profile(
    scene: JsonObject,
    payload: ExportDocumentRequest,
) -> JsonObject:
    if payload.profile is not None and payload.profile_name:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "export_profile.ambiguous_source",
                "message": "provide either profile or profile_name, not both",
            },
        )
    if payload.profile is not None:
        profile = dict(payload.profile)
        profile.setdefault("format", payload.format)
        profile.setdefault("name", f"{profile['format']}_document_export")
        return normalize_export_profile(profile)

    if payload.profile_name:
        for profile in scene.get("export_profiles", []):
            if isinstance(profile, dict) and profile.get("name") == payload.profile_name:
                return normalize_export_profile(dict(profile))
        raise HTTPException(
            status_code=422,
            detail={
                "code": "export_profile.not_found",
                "message": f"document has no saved export profile named {payload.profile_name}",
            },
        )

    return default_export_profile(payload.format)


def default_export_profile(export_format: str) -> JsonObject:
    return normalize_export_profile(
        {
            "name": f"document_{export_format}",
            "format": export_format,
            "pdf_intent": "preview" if export_format == "pdf" else None,
            "raster": {"scale": 1, "dpi": 96} if export_format == "png" else None,
            "include_bleed": False,
            "embed_fonts": False,
        }
    )


def normalize_export_profile(profile: JsonObject) -> JsonObject:
    export_format = str(profile.get("format") or "svg")
    return {
        "name": str(profile.get("name") or f"{export_format}_document_export"),
        "format": export_format,
        "pdf_intent": profile.get("pdf_intent"),
        "raster": profile.get("raster"),
        "include_bleed": bool(profile.get("include_bleed", False)),
        "embed_fonts": bool(profile.get("embed_fonts", False)),
    }


def preflight_operation_list(preflight: JsonObject) -> List[JsonObject]:
    return (
        list(preflight.get("brand_ref_operations", []))
        + list(preflight.get("token_operations", []))
        + list(preflight.get("layout_operations", []))
    )


def document_export_response(
    document: JsonObject,
    status: str,
    diagnostics: List[JsonObject],
    preflight: JsonObject,
    preflight_operations: List[JsonObject],
    effective_brand_source: str,
    effective_brand_kit: Optional[JsonObject],
    effective_brand_mode: Optional[JsonObject],
    export: JsonObject,
    profile: JsonObject,
) -> JsonObject:
    return {
        "schema_version": 1,
        "document_id": document["id"],
        "status": status,
        "document": document_summary(document),
        "operation_application": {
            "applied_operations": 0,
            "preflight_operations": len(preflight_operations),
        },
        "operations": operation_summaries(preflight_operations),
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
        "preflight": {
            "has_errors": preflight.get("has_errors", False),
            "brand_ref_operations": len(preflight.get("brand_ref_operations", [])),
            "token_operations": len(preflight.get("token_operations", [])),
            "layout_operations": len(preflight.get("layout_operations", [])),
        },
        "brand_kit": {
            "source": effective_brand_source,
            "id": effective_brand_kit.get("id") if effective_brand_kit else None,
            "version": effective_brand_kit.get("version") if effective_brand_kit else None,
            "name": effective_brand_kit.get("name") if effective_brand_kit else None,
            "mode": effective_brand_mode,
        },
        "profile": profile,
        "export": compact_export_result(export),
    }


def compact_export_result(export: JsonObject) -> JsonObject:
    return {
        "artifacts": [
            compact_export_artifact(artifact)
            for artifact in export.get("artifacts", [])
            if isinstance(artifact, dict)
        ],
        "diagnostics": export.get("diagnostics", []),
    }


def compact_export_artifact(artifact: JsonObject) -> JsonObject:
    raw_bytes = artifact.get("bytes", [])
    byte_values = raw_bytes if isinstance(raw_bytes, list) else []
    binary = bytes(int(value) & 0xFF for value in byte_values)
    mime_type = str(artifact.get("mime_type") or "application/octet-stream")
    data_url = f"data:{mime_type};base64,{base64.b64encode(binary).decode('ascii')}"
    text = export_artifact_text(binary, mime_type)
    sidecar_json = artifact.get("sidecar_json")
    sidecar_summary = export_sidecar_summary(sidecar_json)
    filename = export_artifact_filename(artifact, sidecar_summary)
    return {
        "format": artifact.get("format"),
        "page_id": artifact.get("page_id"),
        "asset_id": artifact.get("asset_id"),
        "filename": filename,
        "sidecar_filename": (
            export_sidecar_filename(artifact, sidecar_summary)
            if isinstance(sidecar_json, str)
            else None
        ),
        "mime_type": mime_type,
        "byte_length": len(binary),
        "data_url": data_url,
        "text": text,
        "dimensions": export_artifact_dimensions(binary, mime_type, text),
        "sidecar_json": sidecar_json,
        "sidecar_summary": sidecar_summary,
    }


def export_artifact_text(binary: bytes, mime_type: str) -> Optional[str]:
    if mime_type in {"image/svg+xml", "application/json"}:
        return binary.decode("utf-8", errors="replace")
    return None


def export_artifact_filename(
    artifact: JsonObject,
    sidecar_summary: Optional[JsonObject],
) -> str:
    page = export_artifact_name_scope(artifact, sidecar_summary)
    profile = (
        safe_filename_part(str(sidecar_summary.get("profile_name")))
        if sidecar_summary and sidecar_summary.get("profile_name")
        else None
    )
    extension = export_artifact_extension(artifact.get("format"))
    parts = [page]
    if profile:
        parts.append(profile)
    return ".".join([*parts, extension])


def export_sidecar_filename(
    artifact: JsonObject,
    sidecar_summary: Optional[JsonObject],
) -> str:
    page = export_artifact_name_scope(artifact, sidecar_summary)
    profile = (
        safe_filename_part(str(sidecar_summary.get("profile_name")))
        if sidecar_summary and sidecar_summary.get("profile_name")
        else None
    )
    parts = [page]
    if profile:
        parts.append(profile)
    return ".".join([*parts, "sidecar", "json"])


def export_artifact_name_scope(
    artifact: JsonObject,
    sidecar_summary: Optional[JsonObject],
) -> str:
    if artifact.get("page_id"):
        return safe_filename_part(str(artifact["page_id"]))
    page_ids = (
        sidecar_summary.get("page_ids")
        if sidecar_summary and isinstance(sidecar_summary.get("page_ids"), list)
        else []
    )
    if len(page_ids) == 1:
        return safe_filename_part(str(page_ids[0]))
    return "document"


def export_artifact_extension(format_value: Any) -> str:
    match format_value:
        case "svg":
            return "svg"
        case "png":
            return "png"
        case "pdf":
            return "pdf"
        case "figma_manifest":
            return "json"
        case _:
            return "bin"


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return cleaned or "document"


def export_artifact_dimensions(
    binary: bytes, mime_type: str, text: Optional[str]
) -> Optional[JsonObject]:
    if mime_type == "image/svg+xml" and text:
        view_box = re.search(r'\bviewBox="([^"]+)"', text)
        if view_box:
            try:
                values = [
                    float(value)
                    for value in re.split(r"[,\s]+", view_box.group(1).strip())
                    if value
                ]
            except ValueError:
                values = []
            if len(values) == 4:
                return {
                    "width": values[2],
                    "height": values[3],
                    "unit": "scene",
                    "source": "svg_view_box",
                }
        width = numeric_xml_attribute(text, "width")
        height = numeric_xml_attribute(text, "height")
        if width is not None and height is not None:
            return {
                "width": width,
                "height": height,
                "unit": "scene",
                "source": "svg_attributes",
            }

    if mime_type == "image/png" and binary.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(binary) >= 24:
            return {
                "width": int.from_bytes(binary[16:20], "big"),
                "height": int.from_bytes(binary[20:24], "big"),
                "unit": "px",
                "source": "png_ihdr",
            }

    if mime_type == "application/pdf":
        pdf_text = binary.decode("latin-1", errors="ignore")
        media_box = re.search(
            r"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]",
            pdf_text,
        )
        if media_box:
            return {
                "width": float(media_box.group(1)),
                "height": float(media_box.group(2)),
                "unit": "pt",
                "source": "pdf_media_box",
            }

    return None


def numeric_xml_attribute(text: str, attribute: str) -> Optional[float]:
    match = re.search(rf'\b{attribute}="([0-9.]+)', text)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def export_sidecar_summary(sidecar_json: Any) -> Optional[JsonObject]:
    if not isinstance(sidecar_json, str) or not sidecar_json.strip():
        return None
    try:
        sidecar = json.loads(sidecar_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(sidecar, dict):
        return None

    pages = sidecar.get("pages", [])
    nodes = sidecar.get("nodes", [])
    slots = sidecar.get("slots", [])
    page_ids = [
        page.get("page_id")
        for page in pages
        if isinstance(page, dict) and isinstance(page.get("page_id"), str)
    ]
    slot_keys = [
        slot.get("slot_key")
        for slot in slots
        if isinstance(slot, dict) and isinstance(slot.get("slot_key"), str)
    ]

    return {
        "profile_name": sidecar.get("profile_name"),
        "page_count": len(pages) if isinstance(pages, list) else 0,
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "slot_count": len(slots) if isinstance(slots, list) else 0,
        "page_ids": page_ids,
        "slot_keys": slot_keys,
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def run_agent_turn_preview(
    payload: AgentTurnPreviewRequest, root: Path
) -> JsonObject:
    ensure_agent_runtime_path(root)
    try:
        from lumen_deepagent.config import AgentRuntimeConfig
        from lumen_deepagent.providers import create_provider_quality_loop
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.unavailable",
            "Agent runtime dependencies are not available to the API process.",
            str(error),
        )

    try:
        config = AgentRuntimeConfig.from_env(root)
        if payload.max_iterations is not None:
            config = replace(config, max_iterations=payload.max_iterations)
        prompt = editor_agent_prompt(payload)
        loop, tools = create_provider_quality_loop(prompt, config)
        result = loop.run(prompt)
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.failed",
            "Agent runtime failed before returning a proposal.",
            str(error),
        )

    return agent_response_from_trace(result, tools.trace_dir, tools.scene)


def ensure_agent_runtime_path(root: Path) -> None:
    agent_runtime_path = str(root / "apps" / "agent_runtime")
    api_path = str(root / "apps" / "api")
    for path in [agent_runtime_path, api_path]:
        if path not in sys.path:
            sys.path.insert(0, path)


def editor_agent_prompt(payload: AgentTurnPreviewRequest) -> str:
    context = {
        "document_id": payload.document_id,
        "active_page_id": payload.active_page_id,
        "selected_node_id": payload.selected_node_id,
        "scene_summary": scene_context_summary(payload.scene),
        "current_diagnostics": payload.diagnostics[:20],
        "editor_instruction": (
            "Return changes that can be applied to the current canonical Scene. "
            "Do not mutate scene JSON outside canonical operations. Prefer targeted "
            "repairs when a selected node or diagnostic target is present."
        ),
    }
    return (
        f"{payload.prompt}\n\n"
        "Editor context JSON:\n"
        f"{json.dumps(context, indent=2)}"
    )


def scene_context_summary(scene: JsonObject) -> JsonObject:
    return {
        "meta": scene.get("meta", {}),
        "pages": page_summary(scene),
        "nodes": node_summary(scene)[:80],
        "slots": slot_summary(scene),
        "asset_count": len(scene.get("assets", {})),
        "export_profile_count": len(scene.get("export_profiles", [])),
    }


def agent_response_from_trace(
    result: JsonObject, trace_dir: Path, draft_scene: Optional[JsonObject] = None
) -> JsonObject:
    operations: List[JsonObject] = []
    dsl_blocks: List[str] = []
    diagnostics: List[JsonObject] = []
    iterations_dir = trace_dir / "iterations"
    if iterations_dir.exists():
        for iteration_dir in sorted(
            path for path in iterations_dir.iterdir() if path.is_dir()
        ):
            dsl_path = iteration_dir / "dsl.lumen"
            if dsl_path.exists():
                dsl_blocks.append(dsl_path.read_text(encoding="utf-8"))
            compile_path = iteration_dir / "compile.json"
            if compile_path.exists():
                try:
                    compile_payload = json.loads(compile_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                compile_summary = compile_payload.get("compile") or {}
                diagnostics.extend(
                    agent_diagnostics_from_summaries(
                        compile_summary.get("diagnostics", []), "dsl"
                    )
                )
                if compile_summary.get("status") == "ok":
                    operations.extend(compile_payload.get("operations", []))

    raw_preview_paths = result.get("preview_paths", [])
    preview_paths = (
        [str(path) for path in raw_preview_paths if isinstance(path, str)]
        if isinstance(raw_preview_paths, list)
        else []
    )
    accepted = result.get("status") == "accepted"
    status = "proposed" if accepted and operations else "failed"
    if status == "failed" and not diagnostics:
        diagnostics.append(
            agent_diagnostic(
                "agent_runtime.no_proposal",
                result.get("summary") or "Agent did not return an accepted operation proposal.",
                "validation",
                "error",
                None,
            )
        )
    return {
        "schema_version": 1,
        "status": status,
        "summary": result.get("summary") or "Agent run completed.",
        "run_id": result.get("run_id"),
        "trace_dir": str(trace_dir),
        "preview_paths": preview_paths,
        "dsl_blocks": dsl_blocks,
        "operations": operations if status == "proposed" else [],
        "draft_scene": draft_scene,
        "stop_reason": result.get("stop_reason")
        if isinstance(result.get("stop_reason"), str)
        else None,
        "diagnostics": diagnostics,
        "artifacts": [
            {
                "format": agent_artifact_format(path),
                "page_id": None,
                "filename": Path(path).name,
                "path": path,
                "data_url": None,
                "mime_type": None,
            }
            for path in preview_paths
        ],
    }


def agent_artifact_format(path: str) -> str:
    extension = Path(path).suffix.lower().lstrip(".")
    return extension if extension in {"svg", "png", "pdf", "json"} else "artifact"


def failed_agent_turn_response(code: str, message: str, detail: str) -> JsonObject:
    return {
        "schema_version": 1,
        "status": "failed",
        "summary": message,
        "run_id": None,
        "trace_dir": None,
        "preview_paths": [],
        "dsl_blocks": [],
        "operations": [],
        "draft_scene": None,
        "stop_reason": None,
        "diagnostics": [
            agent_diagnostic(code, message, "validation", "error", detail)
        ],
        "artifacts": [],
    }


def agent_diagnostics_from_summaries(
    summaries: List[JsonObject], default_phase: str
) -> List[JsonObject]:
    diagnostics: List[JsonObject] = []
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        subject = None
        if summary.get("target_node_id"):
            subject = {"kind": "node", "id": summary["target_node_id"]}
        elif summary.get("target_page_id"):
            subject = {"kind": "page", "id": summary["target_page_id"]}
        elif summary.get("target_slot_id"):
            subject = {"kind": "slot", "id": summary["target_slot_id"]}
        diagnostics.append(
            agent_diagnostic(
                summary.get("code") or "agent_runtime.diagnostic",
                summary.get("message") or "Agent runtime returned a diagnostic.",
                default_phase,
                summary.get("severity") or "warning",
                summary.get("suggested_repair"),
                subject,
            )
        )
    return diagnostics


def agent_diagnostic(
    code: str,
    message: str,
    phase: str,
    severity: str,
    hint: Optional[str],
    subject: Optional[JsonObject] = None,
) -> JsonObject:
    return {
        "severity": "error" if severity in {"error", "blocker"} else "warning",
        "phase": phase,
        "code": code,
        "message": message,
        "subject": subject or {"kind": "document"},
        "hint": hint,
    }


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def parent_map(scene: JsonObject) -> Dict[str, JsonObject]:
    parents: Dict[str, JsonObject] = {}
    for page_id, page in scene.get("pages", {}).items():
        for child_id in page.get("children", []):
            parents[child_id] = {"kind": "page", "id": page_id}
    for node_id, node in scene.get("nodes", {}).items():
        for child_id in node.get("children", []):
            parents[child_id] = {"kind": "node", "id": node_id}
    return parents


def page_summary(scene: JsonObject) -> List[JsonObject]:
    return [
        {
            "id": page_id,
            "name": page.get("name"),
            "size": page.get("size"),
            "child_count": len(page.get("children", [])),
            "children": page.get("children", []),
        }
        for page_id, page in scene.get("pages", {}).items()
    ]


def node_summary(scene: JsonObject) -> List[JsonObject]:
    parents = parent_map(scene)
    slots_by_node: Dict[str, List[str]] = {}
    for slot in scene.get("slots", {}).values():
        for node_id in slot.get("bound_nodes", []):
            slots_by_node.setdefault(node_id, []).append(slot.get("key"))

    return [
        {
            "id": node_id,
            "name": node.get("name"),
            "kind": node.get("kind", {}).get("kind"),
            "parent": parents.get(node_id),
            "child_count": len(node.get("children", [])),
            "slot_keys": slots_by_node.get(node_id, []),
            "locked": node.get("locked", False),
            "has_computed_geometry": node.get("computed") is not None,
        }
        for node_id, node in scene.get("nodes", {}).items()
    ]


def slot_summary(scene: JsonObject) -> List[JsonObject]:
    return [
        {
            "id": slot_id,
            "key": slot.get("key"),
            "label": slot.get("label"),
            "content_type": slot.get("content_type"),
            "required": slot.get("required"),
            "scope": slot.get("scope"),
            "bound_nodes": slot.get("bound_nodes", []),
            "overflow": slot.get("overflow"),
            "editability": slot.get("editability"),
        }
        for slot_id, slot in scene.get("slots", {}).items()
    ]


def computed_geometry(scene: JsonObject) -> Dict[str, JsonObject]:
    return {
        node_id: node["computed"]
        for node_id, node in scene.get("nodes", {}).items()
        if node.get("computed") is not None
    }
