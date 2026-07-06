from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import image_cache, image_provider
from .core import CoreClient, CoreError, has_error_diagnostics
from .database import NotFoundError, Repository, connect, run_migrations, utc_now
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
    ingestion_job_dto,
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
    SetAgentInstructionsRequest,
    SetLayoutManagedEditingRequest,
    AttachBrandKitRequest,
    ApplyOperationsRequest,
    ApplyStructuredEditRequest,
    AssetMetadataRequest,
    BrandCompatibilityRequest,
    CompileStylesBrandKitRequest,
    CreateBindingSetRequest,
    CreateDocumentRequest,
    CreateBrandKitRequest,
    CreateInstanceBatchRequest,
    CreateSnapshotRequest,
    DeriveInstanceRequest,
    InstancePreviewRequest,
    ExportDocumentRequest,
    ExportPreviewRequest,
    FinalizeTemplateRequest,
    GenerateAssetRequest,
    GenerateQrRequest,
    GenerateBrandKitRequest,
    IngestWebsiteRequest,
    PreflightRequest,
    PreflightPreviewRequest,
    ReplaceSceneRequest,
    SetAssetDescriptionRequest,
    SetBrandKitApprovalRequest,
    ValidateBrandKitRequest,
    ValidateDocumentBrandGovernanceRequest,
)
from lumen_ingestion.describe import DescriptionStore
from lumen_ingestion.jobs import IngestionJobStore
from lumen_ingestion.pipeline import (
    run_asset_ingestion,
    run_pdf_ingestion,
    run_website_ingestion,
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
    app.state.asset_store_root = Path(
        os.environ.get("LUMEN_ASSET_STORE_ROOT")
        or app.state.database_path.parent / "asset-store"
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

    def asset_store_root() -> str:
        return str(app.state.asset_store_root)

    def repository() -> Repository:
        connection = connect(app.state.database_path)
        try:
            yield Repository(connection)
        finally:
            connection.close()

    @app.get("/build-info")
    def build_info() -> JsonObject:
        """Engine build info for the Track E version handshake.

        The editor compares this against the WASM module's version() and
        downgrades to server-only mode on any mismatch — never
        mixed-version optimistic editing. Cached per process: the helper
        binary's embedded commit cannot change while the API is running.
        """
        if getattr(app.state, "build_info", None) is None:
            try:
                app.state.build_info = app.state.core.build_info()
            except CoreError as error:
                raise core_http_error(error) from error
        return {
            "schema_version": 1,
            "build_info": app.state.build_info,
        }

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

    # Ingestion routes are registered BEFORE GET /brand-kits/{brand_kit_id} so
    # the literal "ingest" segment is not captured as a kit id (FastAPI matches
    # routes in registration order).
    @app.post("/brand-kits/ingest/website")
    async def ingest_website(
        payload: IngestWebsiteRequest,
        background_tasks: BackgroundTasks,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        guard = _resolve_guard_url()
        try:
            await guard(payload.url)
        except Exception as error:  # CaptureError / ValueError from the guard
            raise ingest_url_rejected(payload.url, error) from error

        job = IngestionJobStore(repo.connection).create(
            "website", payload.model_dump()
        )
        background_tasks.add_task(
            run_website_ingestion,
            str(app.state.database_path),
            asset_store_root(),
            job["job_id"],
        )
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

    @app.post("/brand-kits/ingest/pdf")
    def ingest_pdf(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        name: Optional[str] = Form(None),
        brand_kit_id: Optional[str] = Form(None),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        data = file.file.read()
        max_bytes = asset_max_bytes()
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"asset payload of {len(data)} bytes exceeds the {max_bytes}-byte limit",
            )
        is_pdf_type = (file.content_type or "").lower() == "application/pdf"
        is_pdf_name = (file.filename or "").lower().endswith(".pdf")
        if not (is_pdf_type or is_pdf_name):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ingest.unsupported_file",
                    "message": "brand-guidelines ingest requires a PDF file",
                },
            )
        if not data or not data.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ingest.not_a_pdf",
                    "message": "uploaded file is not a valid PDF (missing %PDF- header)",
                },
            )

        # Create the job first so its id names the tmp file, then write the
        # bytes to <asset_store_root>/ingest_tmp/<job_id>.pdf and record that
        # path in the job request — run_pdf_ingestion reads + deletes it. The
        # PDF bytes themselves are never stored in the job row.
        job = IngestionJobStore(repo.connection).create(
            "pdf",
            {
                "filename": file.filename,
                "name": name,
                "brand_kit_id": brand_kit_id,
                "size_bytes": len(data),
            },
        )
        tmp_dir = Path(asset_store_root()) / "ingest_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{job['job_id']}.pdf"
        tmp_path.write_bytes(data)

        request = dict(job["request"])
        request["tmp_path"] = str(tmp_path)
        job = IngestionJobStore(repo.connection).update_request(job["job_id"], request)

        background_tasks.add_task(
            run_pdf_ingestion,
            str(app.state.database_path),
            asset_store_root(),
            job["job_id"],
        )
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

    @app.post("/brand-kits/ingest/assets")
    def ingest_assets(
        background_tasks: BackgroundTasks,
        files: List[UploadFile] = File(...),
        name: Optional[str] = Form(None),
        brand_kit_id: Optional[str] = Form(None),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        if not files:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ingest.unsupported_file",
                    "message": "asset ingest requires at least one file",
                },
            )
        if len(files) > _INGEST_MAX_ASSET_FILES:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ingest.too_many_files",
                    "message": (
                        f"asset ingest accepts at most {_INGEST_MAX_ASSET_FILES} "
                        f"files, got {len(files)}"
                    ),
                },
            )

        max_bytes = asset_max_bytes()
        payloads: List[Tuple[UploadFile, bytes]] = []
        for upload in files:
            data = upload.file.read()
            if len(data) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"asset payload of {len(data)} bytes exceeds the "
                        f"{max_bytes}-byte limit"
                    ),
                )
            payloads.append((upload, data))

        # Magic-sniff each file (§2). Files failing the sniff are still passed
        # through — uploads.py skips them with diagnostics — but if NONE pass we
        # reject the whole batch up-front rather than queue a doomed job.
        if not any(_sniff_supported_asset(data) for _upload, data in payloads):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ingest.unsupported_file",
                    "message": (
                        "no uploaded file is a supported image "
                        "(PNG, JPEG, WebP, or SVG)"
                    ),
                },
            )

        # Create the job first so its id names the tmp files, then write each
        # file's bytes to <asset_store_root>/ingest_tmp/<job_id>_<idx>_<name>
        # and record those paths in the job request — run_asset_ingestion reads
        # + deletes them. The file bytes themselves are never stored in the job
        # row.
        job = IngestionJobStore(repo.connection).create(
            "asset_upload",
            {
                "name": name,
                "brand_kit_id": brand_kit_id,
                "file_count": len(payloads),
            },
        )
        tmp_dir = Path(asset_store_root()) / "ingest_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        file_specs: List[JsonObject] = []
        for idx, (upload, data) in enumerate(payloads):
            safe_name = _sanitize_tmp_filename(upload.filename)
            tmp_path = tmp_dir / f"{job['job_id']}_{idx}_{safe_name}"
            tmp_path.write_bytes(data)
            file_specs.append(
                {
                    "filename": upload.filename,
                    "content_type": upload.content_type,
                    "tmp_path": str(tmp_path),
                }
            )

        request = dict(job["request"])
        request["files"] = file_specs
        job = IngestionJobStore(repo.connection).update_request(job["job_id"], request)

        background_tasks.add_task(
            run_asset_ingestion,
            str(app.state.database_path),
            asset_store_root(),
            job["job_id"],
        )
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

    @app.get("/brand-kits/ingest")
    def list_ingestion_jobs(
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        """Most-recent 50 ingestion jobs (public dto — no request/evidence
        bodies). Registered adjacent to the param route; the literal segment
        only matches when the path has no trailing job id."""
        jobs = IngestionJobStore(repo.connection).list_recent(50)
        return {
            "schema_version": 1,
            "jobs": [ingestion_job_dto(job) for job in jobs],
        }

    @app.get("/brand-kits/ingest/{job_id}")
    def get_ingestion_job(
        job_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        job = IngestionJobStore(repo.connection).get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "ingestion_job.not_found",
                    "message": f"ingestion job {job_id} was not found",
                },
            )
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

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

    @app.post("/brand-kits/{brand_kit_id}/approval")
    def set_brand_kit_approval(
        brand_kit_id: str,
        payload: SetBrandKitApprovalRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        """Flip the approval state on the latest version of a kit (approve /
        revert to draft). Unknown kit → 404; invalid status → 422 (model)."""
        record = repo.update_brand_kit_approval(
            brand_kit_id, payload.approval_status
        )
        log_event(
            api_logger,
            logging.INFO,
            "brand_kit_approval_set",
            brand_kit_id=brand_kit_id,
            approval_status=payload.approval_status,
        )
        return brand_kit_detail_dto(record)

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

    @app.put("/documents/{document_id}/agent-instructions")
    def set_agent_instructions(
        document_id: str,
        payload: SetAgentInstructionsRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        """2e: per-document standing instructions for the agent. Stored on the
        document (they survive reloads) and sent by the editor with every
        turn; an empty/blank body clears them."""
        instructions = (payload.instructions or "").strip() or None
        document = repo.set_agent_instructions(document_id, instructions)
        return {
            "schema_version": 1,
            "document_id": document_id,
            "agent_instructions": document["agent_instructions"],
        }

    @app.put("/documents/{document_id}/layout-managed-editing")
    def set_layout_managed_editing(
        document_id: str,
        payload: SetLayoutManagedEditingRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        """Per-document advanced opt-out from handoff-absolute: when enabled,
        the editor skips both freeze seams (Accept and first gesture) so agent
        auto-layout stays live. Forward-only — enabling never un-freezes
        containers that are already Free."""
        document = repo.set_layout_managed_editing(document_id, payload.enabled)
        return {
            "schema_version": 1,
            "document_id": document_id,
            "layout_managed_editing": document["layout_managed_editing"],
        }

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
                document["scene"],
                payload.operations,
                scope=payload.scope.model_dump() if payload.scope else None,
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

    @app.get("/documents/{document_id}/checkpoints")
    def list_checkpoints(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        envelopes = repo.list_envelopes(document_id, newest_first=True)
        checkpoints = [
            {
                "batch_id": envelope["batch_id"],
                "seq": envelope["seq"],
                "label": envelope["checkpoint_label"],
                "intent": envelope["intent"],
                "created_at": envelope["created_at"],
            }
            for envelope in envelopes
            if envelope["checkpoint_label"]
        ]
        return {
            "schema_version": 1,
            "document_id": document_id,
            "checkpoints": checkpoints,
        }

    def perform_undo_step(repo: Repository, document_id: str) -> JsonObject:
        """Apply one document-level undo as a new appended envelope."""
        document = require_document(repo, document_id)
        require_draft_document(document, "undo")
        undo_stack = list(document.get("undo_stack") or [])
        if not undo_stack:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "history.nothing_to_undo",
                    "message": "no undoable batches in document history",
                },
            )
        target = repo.require_envelope(document_id, undo_stack[-1])
        if target["inverse_operations"] is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "history.not_invertible",
                    "message": (
                        f"batch {target['batch_id']} ({target['intent'] or 'unknown'}) "
                        "is not invertible and blocks undo"
                    ),
                    "batch_id": target["batch_id"],
                },
            )
        try:
            result = app.state.core.apply_operations(
                document["scene"], target["inverse_operations"]
            )
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = result.get("diagnostics", [])
        repo.update_document_state(
            document_id,
            result["scene"],
            diagnostics,
            target["inverse_operations"],
            "system",
            "system",
            "history",
            "structural",
            effective_brand=None,
            envelope={
                "intent": f"undo:{target['intent'] or target['batch_id']}",
                "reverts_batch_id": target["batch_id"],
                "touched_targets": target["touched_targets"],
                "inverse_operations": target["operations"],
            },
        )
        return target

    @app.post("/documents/{document_id}/undo")
    def undo_document(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        reverted = perform_undo_step(repo, document_id)
        document = require_document(repo, document_id)
        log_event(
            api_logger,
            logging.INFO,
            "document_undo_applied",
            document_id=document_id,
            reverted_batch_id=reverted["batch_id"],
        )
        return {
            "schema_version": 1,
            "status": "applied",
            "reverted_batch_id": reverted["batch_id"],
            "reverted_intent": reverted["intent"],
            "document": document_summary(document),
            "envelope": latest_envelope_summary(repo, document_id),
        }

    @app.post("/documents/{document_id}/redo")
    def redo_document(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "redo")
        redo_stack = list(document.get("redo_stack") or [])
        if not redo_stack:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "history.nothing_to_redo",
                    "message": "no redoable batches in document history",
                },
            )
        target = repo.require_envelope(document_id, redo_stack[-1])
        try:
            result = app.state.core.apply_operations(
                document["scene"], target["operations"]
            )
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = result.get("diagnostics", [])
        repo.update_document_state(
            document_id,
            result["scene"],
            diagnostics,
            target["operations"],
            "system",
            "system",
            "history",
            "structural",
            effective_brand=None,
            envelope={
                "intent": f"redo:{target['intent'] or target['batch_id']}",
                "reapplies_batch_id": target["batch_id"],
                "touched_targets": target["touched_targets"],
                "inverse_operations": target["inverse_operations"],
            },
        )
        document = require_document(repo, document_id)
        log_event(
            api_logger,
            logging.INFO,
            "document_redo_applied",
            document_id=document_id,
            reapplied_batch_id=target["batch_id"],
        )
        return {
            "schema_version": 1,
            "status": "applied",
            "reapplied_batch_id": target["batch_id"],
            "document": document_summary(document),
            "envelope": latest_envelope_summary(repo, document_id),
        }

    @app.post("/documents/{document_id}/revert")
    def revert_to_checkpoint(
        document_id: str,
        checkpoint: str,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "revert")
        envelopes = repo.list_envelopes(document_id, newest_first=False)
        anchor = next(
            (
                envelope
                for envelope in reversed(envelopes)
                if envelope["checkpoint_label"] == checkpoint
            ),
            None,
        )
        if anchor is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "history.checkpoint_not_found",
                    "message": f"no checkpoint labeled {checkpoint!r} in history",
                },
            )
        undo_stack = list(document.get("undo_stack") or [])
        if anchor["batch_id"] not in undo_stack:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "history.checkpoint_not_active",
                    "message": (
                        f"checkpoint {checkpoint!r} is not on the active undo path; "
                        "it may already be reverted"
                    ),
                },
            )
        anchor_index = undo_stack.index(anchor["batch_id"])
        pending = undo_stack[anchor_index + 1 :]
        for batch_id in pending:
            envelope = repo.require_envelope(document_id, batch_id)
            if envelope["inverse_operations"] is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "history.not_invertible",
                        "message": (
                            f"batch {batch_id} between head and checkpoint is not "
                            "invertible; revert is blocked"
                        ),
                        "batch_id": batch_id,
                    },
                )
        reverted = []
        for _ in pending:
            reverted.append(perform_undo_step(repo, document_id)["batch_id"])
        document = require_document(repo, document_id)
        log_event(
            api_logger,
            logging.INFO,
            "document_reverted_to_checkpoint",
            document_id=document_id,
            checkpoint=checkpoint,
            reverted_count=len(reverted),
        )
        return {
            "schema_version": 1,
            "status": "applied",
            "checkpoint": checkpoint,
            "anchor_batch_id": anchor["batch_id"],
            "reverted_batch_ids": reverted,
            "document": document_summary(document),
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
            result = app.state.core.apply_structured_edit(
                document["scene"],
                payload.edit,
                scope=payload.scope.model_dump() if payload.scope else None,
            )
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
                asset_store_root=asset_store_root(),
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
            target_node_ids=payload.target_node_ids,
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

    @app.post("/agent/turns")
    def start_agent_turn(
        payload: AgentTurnPreviewRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        # Async turn: start the run in a background thread and return its id
        # immediately. The thread streams progress events into the durable
        # run-event store (via the loop's event_sink) and writes the final
        # result on completion; the editor subscribes over SSE. The synchronous
        # /agent/turn-preview stays as-is for tests, CLI, and fixtures.
        run_id = f"run_{uuid4().hex}"
        repo.create_run(run_id, payload.document_id)
        root = repo_root()
        database_path = app.state.database_path
        override = app.state.agent_turn_runner

        def worker() -> None:
            store = Repository(connect(database_path))
            try:

                def sink(event_type: str, data: JsonObject) -> None:
                    try:
                        store.append_run_event(run_id, event_type, data)
                    except Exception:
                        pass

                try:
                    if override is not None:
                        response = override(payload, root)
                    else:
                        response = run_agent_turn_preview(payload, root, event_sink=sink)
                    status = (
                        "failed"
                        if response.get("status") in ("failed", "error")
                        else "succeeded"
                    )
                    store.set_run_result(run_id, status, response)
                    store.append_run_event(
                        run_id, "result", {"status": response.get("status")}
                    )
                except Exception as error:  # pragma: no cover - defensive
                    failed = failed_agent_turn_response(
                        "agent_runtime.failed",
                        "Agent turn crashed before returning a proposal.",
                        str(error),
                    )
                    store.set_run_result(run_id, "failed", failed)
                    store.append_run_event(run_id, "error", {"message": str(error)})
            finally:
                store.connection.close()

        threading.Thread(
            target=worker, name=f"agent-turn-{run_id}", daemon=True
        ).start()
        log_event(
            api_logger,
            logging.INFO,
            "agent_turn_started",
            run_id=run_id,
            document_id=payload.document_id,
            active_page_id=payload.active_page_id,
            target_node_ids=payload.target_node_ids,
        )
        return {"schema_version": 1, "run_id": run_id, "status": "running"}

    @app.get("/agent/runs/{run_id}")
    def get_agent_run(
        run_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        run = repo.get_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404, detail=f"agent_run {run_id} was not found"
            )
        return {
            "schema_version": 1,
            "run_id": run_id,
            "status": run["status"],
            "events": repo.list_run_events(run_id, after_seq=0),
            "result": run["result"],
        }

    @app.get("/agent/runs/{run_id}/events")
    async def stream_agent_run_events(run_id: str, request: Request):
        database_path = app.state.database_path

        def read_run() -> Optional[JsonObject]:
            store = Repository(connect(database_path))
            try:
                return store.get_run(run_id)
            finally:
                store.connection.close()

        def read_events(after_seq: int) -> List[JsonObject]:
            store = Repository(connect(database_path))
            try:
                return store.list_run_events(run_id, after_seq=after_seq)
            finally:
                store.connection.close()

        # Resume point: EventSource re-sends Last-Event-ID on auto-reconnect;
        # an explicit ?after= (used by resume-on-mount after a snapshot fetch)
        # takes precedence.
        header_id = request.headers.get("last-event-id")
        after_param = request.query_params.get("after")
        try:
            start_seq = int(after_param if after_param is not None else header_id or 0)
        except (TypeError, ValueError):
            start_seq = 0

        if await asyncio.to_thread(read_run) is None:
            raise HTTPException(
                status_code=404, detail=f"agent_run {run_id} was not found"
            )

        async def event_stream():
            last_seq = start_seq
            yield "retry: 1000\n\n"
            while True:
                if await request.is_disconnected():
                    return
                events = await asyncio.to_thread(read_events, last_seq)
                for event in events:
                    last_seq = event["seq"]
                    if event["type"] in ("result", "error"):
                        current = await asyncio.to_thread(read_run)
                        yield sse_frame(event["seq"], "done", (current or {}).get("result"))
                        return
                    yield sse_frame(event["seq"], "progress", event)
                if not events:
                    current = await asyncio.to_thread(read_run)
                    # Terminal with no terminal event yet (defensive): the run
                    # finished but the marker append lost the race — close out.
                    if current and current["status"] in ("succeeded", "failed"):
                        yield sse_frame(last_seq, "done", current.get("result"))
                        return
                    yield ": keepalive\n\n"
                    await asyncio.sleep(1.0)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

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
                asset_store_root=asset_store_root(),
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

    # ------------------------------------------------------------------
    # Phase G personalization runtime (slice G8)
    # ------------------------------------------------------------------

    def _sanitize_id_component(source: str) -> str:
        return "".join(
            ch if ch.isalnum() or ch in "_-" else "_" for ch in source
        )

    def _instance_id(template_revision_id: str, binding_set_id: str) -> str:
        return (
            "inst_"
            + _sanitize_id_component(template_revision_id)
            + "_"
            + _sanitize_id_component(binding_set_id)
        )

    def _binding_asset_records(repo: Repository, binding: JsonObject) -> list:
        """Resolve asset records referenced by binding values. Missing
        records are NOT an HTTP error here: derivation reports LUMG0301
        per slot, which is the honest per-instance verdict."""
        records = []
        for value in (binding.get("values") or {}).values():
            if isinstance(value, dict) and value.get("kind") == "asset":
                asset_id = value.get("asset_id")
                if not asset_id:
                    continue
                try:
                    records.append(repo.require_asset_record(asset_id)["asset"])
                except NotFoundError:
                    continue
        return records

    def _derive_and_persist_instance(
        repo: Repository,
        revision: JsonObject,
        binding: JsonObject,
        export_formats: list,
        export_dpi: Optional[int],
        batch_id: Optional[str] = None,
    ) -> JsonObject:
        revision_id = revision["template_revision_id"]
        binding_set_id = binding.get("binding_set_id") or new_id("bind")
        instance_id = _instance_id(revision_id, binding_set_id)
        records = _binding_asset_records(repo, binding)
        result = app.state.core.derive_instance(
            scene=revision["scene"],
            binding_set=binding,
            asset_records=records,
            store_root=asset_store_root(),
            export_formats=export_formats,
            export_dpi=export_dpi,
            raise_on_error=False,
        )

        if not result.get("ok", False):
            diagnostics = result.get("diagnostics", [])
            if not diagnostics:
                diagnostics = diagnostics_from_helper_error(result.get("error"))
            instance = repo.upsert_instance(
                {
                    "instance_id": instance_id,
                    "template_revision_id": revision_id,
                    "binding_set_id": binding_set_id,
                    "batch_id": batch_id,
                    "status": "failed",
                    "fit_status": "overflow",
                    "derived_scene": {},
                    "diagnostics": diagnostics,
                    "audit": [],
                    "fit_report": {},
                    "artifacts": [],
                    "generated_assets": {},
                }
            )
            return instance

        payload = result.get("instance") or {}
        fit_report = payload.get("fit_report") or {}
        status = "failed" if payload.get("has_errors") else "derived"
        generated = payload.get("generated") or {}
        instance = repo.upsert_instance(
            {
                "instance_id": instance_id,
                "template_revision_id": revision_id,
                "binding_set_id": binding_set_id,
                "batch_id": batch_id,
                "status": status,
                "fit_status": fit_report.get("status", "overflow"),
                "derived_scene": result.get("scene") or {},
                "diagnostics": result.get("diagnostics", []),
                "audit": payload.get("audit", []),
                "fit_report": fit_report,
                "artifacts": payload.get("artifacts", []),
                "generated_assets": generated,
            }
        )

        # Generated assets become first-class library records.
        for entry in generated.values():
            record = (entry or {}).get("record")
            if record:
                repo.create_asset_record(record)

        # AskAgentToRepair entries land in the template-level repair queue.
        for request_ in payload.get("repair_requests", []):
            repair_id = "rep_" + _sanitize_id_component(
                f"{revision_id}_{request_['slot_key']}_{binding_set_id}"
            )
            repo.upsert_repair_request(
                {
                    "repair_id": repair_id,
                    "template_revision_id": revision_id,
                    "slot_key": request_["slot_key"],
                    "node_id": request_["node_id"],
                    "binding_set_id": request_["binding_set_id"],
                    "instance_id": instance_id,
                    "reason": request_["reason"],
                    "status": "open",
                }
            )

        return instance

    def _public_instance(instance: JsonObject, include_scene: bool = True) -> JsonObject:
        public = dict(instance)
        if not include_scene:
            public.pop("derived_scene", None)
        return public

    @app.post("/binding-sets")
    def create_binding_set(
        payload: CreateBindingSetRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        binding = payload.binding_set
        binding_set_id = binding.get("binding_set_id")
        revision_id = binding.get("template_revision_id")
        if not binding_set_id or not revision_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "binding_set.incomplete",
                    "message": "binding_set_id and template_revision_id are required",
                },
            )
        revision = repo.require_template_revision(revision_id)
        try:
            result = app.state.core.validate_binding_set(
                revision["scene"], binding
            )
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = result.get("diagnostics", [])
        if not result.get("ok", False):
            log_event(
                api_logger,
                logging.INFO,
                "binding_set_rejected",
                binding_set_id=binding_set_id,
                template_revision_id=revision_id,
                **diagnostic_summary(diagnostics),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "binding_set.invalid",
                    "message": f"binding set {binding_set_id} failed validation",
                    "diagnostics": diagnostics,
                },
            )
        stored = repo.upsert_binding_set(binding, "valid", diagnostics)
        log_event(
            api_logger,
            logging.INFO,
            "binding_set_stored",
            binding_set_id=binding_set_id,
            template_revision_id=revision_id,
            **diagnostic_summary(diagnostics),
        )
        return {"schema_version": 1, **stored}

    @app.get("/binding-sets/{binding_set_id}")
    def get_binding_set(
        binding_set_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_binding_set(binding_set_id)

    @app.get("/binding-sets")
    def list_binding_sets(
        template_revision_id: Optional[str] = Query(None),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        return {
            "binding_sets": repo.list_binding_sets(template_revision_id),
        }

    @app.delete("/binding-sets/{binding_set_id}")
    def delete_binding_set(
        binding_set_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        repo.delete_binding_set(binding_set_id)
        return {"deleted": binding_set_id}

    @app.post("/template-revisions/{template_revision_id}/instances")
    def derive_instance_route(
        template_revision_id: str,
        payload: DeriveInstanceRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        revision = repo.require_template_revision(template_revision_id)
        if payload.binding_set is not None:
            binding = payload.binding_set
        elif payload.binding_set_id is not None:
            stored = repo.require_binding_set(payload.binding_set_id)
            if stored["template_revision_id"] != template_revision_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "binding_set.revision_mismatch",
                        "message": (
                            f"binding set {payload.binding_set_id} targets revision "
                            f"{stored['template_revision_id']}, not {template_revision_id}"
                        ),
                    },
                )
            binding = stored["binding_set"]
        else:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "instance.binding_missing",
                    "message": "provide binding_set_id or an inline binding_set",
                },
            )

        instance = _derive_and_persist_instance(
            repo,
            revision,
            binding,
            payload.export_formats,
            payload.export_dpi,
        )
        log_event(
            api_logger,
            logging.INFO,
            "instance_derived",
            instance_id=instance["instance_id"],
            template_revision_id=template_revision_id,
            binding_set_id=instance["binding_set_id"],
            status=instance["status"],
            fit_status=instance["fit_status"],
            artifact_count=len(instance.get("artifacts", [])),
        )
        return {"schema_version": 1, **_public_instance(instance)}

    @app.get("/instances/{instance_id}")
    def get_instance(
        instance_id: str,
        include_scene: bool = Query(True),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        return _public_instance(
            repo.require_instance(instance_id), include_scene
        )

    @app.get("/template-revisions/{template_revision_id}/instances")
    def list_revision_instances(
        template_revision_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        repo.require_template_revision(template_revision_id)
        return {
            "instances": [
                _public_instance(instance, include_scene=False)
                for instance in repo.list_instances(template_revision_id)
            ]
        }

    BATCH_EXPORT_DPI = 300

    def _process_batch(
        repo: Repository, revision: JsonObject, batch: JsonObject
    ) -> JsonObject:
        """Synchronous-chunked batch processing (Track D Decision 4):
        the cursor persists after every chunk, so an interrupted batch
        resumes exactly where it stopped — this job row is the seam where
        a real queue lands later."""
        binding_set_ids = batch["binding_set_ids"]
        counts = batch.get("counts") or {
            "total": len(binding_set_ids),
            "derived": 0,
            "failed": 0,
            "fit": {"fits": 0, "fits_with_policy": 0, "overflow": 0},
        }
        manifest = list(batch.get("manifest") or [])
        diagnostics = list(batch.get("diagnostics") or [])
        cursor = batch["cursor"]

        while cursor < len(binding_set_ids):
            chunk_end = min(cursor + batch["chunk_size"], len(binding_set_ids))
            for index in range(cursor, chunk_end):
                stored = repo.require_binding_set(binding_set_ids[index])
                instance = _derive_and_persist_instance(
                    repo,
                    revision,
                    stored["binding_set"],
                    batch["export_formats"],
                    BATCH_EXPORT_DPI,
                    batch_id=batch["batch_id"],
                )
                counts["derived" if instance["status"] == "derived" else "failed"] += 1
                fit_status = instance["fit_status"]
                if fit_status in counts["fit"]:
                    counts["fit"][fit_status] += 1
                manifest.append(
                    {
                        "instance_id": instance["instance_id"],
                        "binding_set_id": instance["binding_set_id"],
                        "status": instance["status"],
                        "fit_status": fit_status,
                        "artifacts": instance.get("artifacts", []),
                    }
                )
            cursor = chunk_end
            status = "completed" if cursor >= len(binding_set_ids) else "running"
            batch = repo.update_batch_progress(
                batch["batch_id"], cursor, status, counts, manifest, diagnostics
            )
        return batch

    @app.post("/template-revisions/{template_revision_id}/batches")
    def create_instance_batch(
        template_revision_id: str,
        payload: CreateInstanceBatchRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        revision = repo.require_template_revision(template_revision_id)
        if not payload.binding_set_ids:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "batch.empty",
                    "message": "binding_set_ids must not be empty",
                },
            )
        for binding_set_id in payload.binding_set_ids:
            stored = repo.require_binding_set(binding_set_id)
            if stored["template_revision_id"] != template_revision_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "binding_set.revision_mismatch",
                        "message": (
                            f"binding set {binding_set_id} targets revision "
                            f"{stored['template_revision_id']}, not {template_revision_id}"
                        ),
                    },
                )
        chunk_size = max(1, payload.chunk_size)
        batch = repo.create_batch(
            {
                "batch_id": new_id("batch"),
                "template_revision_id": template_revision_id,
                "status": "running",
                "binding_set_ids": payload.binding_set_ids,
                "export_formats": payload.export_formats,
                "chunk_size": chunk_size,
                "cursor": 0,
            }
        )
        batch = _process_batch(repo, revision, batch)
        log_event(
            api_logger,
            logging.INFO,
            "instance_batch_completed",
            batch_id=batch["batch_id"],
            template_revision_id=template_revision_id,
            status=batch["status"],
            counts=batch["counts"],
        )
        return {"schema_version": 1, **batch}

    @app.post("/batches/{batch_id}/resume")
    def resume_instance_batch(
        batch_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        batch = repo.require_batch(batch_id)
        if batch["status"] == "completed":
            return {"schema_version": 1, **batch}
        revision = repo.require_template_revision(batch["template_revision_id"])
        batch = _process_batch(repo, revision, batch)
        return {"schema_version": 1, **batch}

    @app.get("/batches/{batch_id}")
    def get_instance_batch(
        batch_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_batch(batch_id)

    @app.post("/instances/preview")
    def preview_instance(payload: InstancePreviewRequest) -> JsonObject:
        """Stateless worst-case/instance preview (slice G9): derive a
        binding set against an inline scene (treated as a finalized
        snapshot) and return the rendered artifact plus the fit report.
        Nothing persists — the editor renders the result read-only."""
        scene = payload.scene
        status = (scene.get("meta") or {}).get("status") or {}
        if status.get("kind") != "finalized":
            scene = {
                **scene,
                "meta": {
                    **(scene.get("meta") or {}),
                    "status": {
                        "kind": "finalized",
                        "template_revision_id": payload.binding_set.get(
                            "template_revision_id", "tmpl_preview"
                        ),
                    },
                },
            }
        export_format = payload.format if payload.format in {"svg", "png"} else "svg"
        try:
            result = app.state.core.derive_instance(
                scene=scene,
                binding_set=payload.binding_set,
                asset_records=[],
                store_root=asset_store_root(),
                export_formats=[export_format],
                export_dpi=96,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        if not result.get("ok", False):
            error = result.get("error") or {}
            if not diagnostics:
                diagnostics = diagnostics_from_helper_error(error)
            raise HTTPException(
                status_code=422,
                detail={
                    "code": error.get("code", "instance.preview_failed"),
                    "message": error.get("message", "instance preview failed"),
                    "diagnostics": diagnostics,
                },
            )

        payload_instance = result.get("instance") or {}
        artifact_payload: Optional[JsonObject] = None
        for artifact in payload_instance.get("artifacts", []):
            relative = artifact.get("relative_path")
            if not relative:
                continue
            artifact_path = Path(asset_store_root()) / relative
            if not artifact_path.exists():
                continue
            data = artifact_path.read_bytes()
            if artifact.get("format") == "svg":
                artifact_payload = {
                    "format": "svg",
                    "mime_type": artifact.get("mime_type"),
                    "content": data.decode("utf-8"),
                }
            else:
                artifact_payload = {
                    "format": artifact.get("format"),
                    "mime_type": artifact.get("mime_type"),
                    "content_base64": base64.b64encode(data).decode("ascii"),
                }
            break

        return {
            "schema_version": 1,
            "status": "failed" if payload_instance.get("has_errors") else "ok",
            "fit_report": payload_instance.get("fit_report") or {},
            "repair_requests": payload_instance.get("repair_requests", []),
            "diagnostics": diagnostics,
            "artifact": artifact_payload,
        }

    @app.get("/template-revisions/{template_revision_id}/repair-queue")
    def list_template_repair_queue(
        template_revision_id: str,
        status: Optional[str] = Query(None),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        repo.require_template_revision(template_revision_id)
        return {
            "repairs": repo.list_repair_queue(template_revision_id, status),
        }

    @app.post("/assets")
    def upload_asset(
        file: UploadFile = File(...),
        label: Optional[str] = Form(None),
        kind: Optional[str] = Form(None),
        uploaded_by: Optional[str] = Form(None),
        license_json: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        data = file.file.read()
        max_bytes = asset_max_bytes()
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"asset payload of {len(data)} bytes exceeds the {max_bytes}-byte limit",
            )
        try:
            license_payload = json.loads(license_json) if license_json else None
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=400, detail=f"license_json is not valid JSON: {error}"
            ) from error
        tag_list = [tag.strip() for tag in (tags or "").split(",") if tag.strip()] or None

        asset_id = f"asset_{uuid4().hex[:12]}"
        try:
            result = app.state.core.ingest_asset(
                store_root=asset_store_root(),
                bytes_base64=base64.b64encode(data).decode("ascii"),
                asset_id=asset_id,
                label=label or file.filename or asset_id,
                declared_mime_type=file.content_type,
                filename=file.filename,
                kind=kind,
                uploaded_by=uploaded_by,
                license=license_payload,
                provenance={
                    "created_by": uploaded_by,
                    "created_at": utc_now(),
                    "source_label": "upload",
                    "confidence": None,
                    "notes": [],
                },
                tags=tag_list,
                max_bytes=max_bytes,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        if not result.get("ok", False):
            error = result.get("error") or {}
            if not diagnostics:
                diagnostics = diagnostics_from_helper_error(error)
            status_code = 413 if error.get("code") == "ingest.too_large" else 400
            log_event(
                api_logger,
                logging.INFO,
                "asset_upload_completed",
                status="rejected",
                error_code=error.get("code"),
                **diagnostic_summary(diagnostics),
            )
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": error.get("code"),
                    "message": error.get("message"),
                    "diagnostics": diagnostics,
                },
            )

        asset_payload = result.get("asset") or {}
        record = asset_payload.get("record") or {}
        stored = repo.create_asset_record(record)
        log_event(
            api_logger,
            logging.INFO,
            "asset_upload_completed",
            status="ok",
            asset_id=record.get("id"),
            kind=record.get("kind"),
            deduplicated=asset_payload.get("deduplicated", False),
            byte_length=asset_payload.get("byte_length"),
            **diagnostic_summary(diagnostics),
        )
        return {
            "schema_version": 1,
            "asset": stored["asset"],
            "deduplicated": asset_payload.get("deduplicated", False),
            "diagnostics": diagnostics,
        }

    @app.post("/assets/generate/qr")
    def generate_qr_asset(
        payload: GenerateQrRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        asset_id = f"asset_qr_{uuid4().hex[:12]}"
        try:
            result = app.state.core.generate_qr(
                store_root=asset_store_root(),
                data=payload.data,
                asset_id=asset_id,
                label=payload.label,
                ec_level=payload.ec_level,
                print_media=payload.print_media,
                target_width_mm=payload.target_width_mm,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        if not result.get("ok", False):
            error = result.get("error") or {}
            if not diagnostics:
                diagnostics = diagnostics_from_helper_error(error)
            log_event(
                api_logger,
                logging.INFO,
                "qr_generation_completed",
                status="rejected",
                error_code=error.get("code"),
                **diagnostic_summary(diagnostics),
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "code": error.get("code"),
                    "message": error.get("message"),
                    "diagnostics": diagnostics,
                },
            )

        asset_payload = result.get("asset") or {}
        record = asset_payload.get("record") or {}
        stored = repo.create_asset_record(record)
        log_event(
            api_logger,
            logging.INFO,
            "qr_generation_completed",
            status="ok",
            asset_id=record.get("id"),
            deduplicated=asset_payload.get("deduplicated", False),
            ec_level=(asset_payload.get("qr") or {}).get("ec_level"),
            module_count=(asset_payload.get("qr") or {}).get("module_count"),
            **diagnostic_summary(diagnostics),
        )
        return {
            "schema_version": 1,
            "asset": stored["asset"],
            "qr": asset_payload.get("qr") or {},
            "deduplicated": asset_payload.get("deduplicated", False),
            "diagnostics": diagnostics,
        }

    @app.post("/assets/generate")
    def generate_asset(
        payload: GenerateAssetRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        """Public Phase E provider-registry surface (lands with Phase G):
        run any registered generation provider and persist the normalized
        asset record."""
        asset_id = f"asset_gen_{uuid4().hex[:12]}"
        cache_key: Optional[str] = None
        if image_provider.is_image_model_provider(payload.provider):
            # Phase 3b image EDIT: resolve the source asset's pixels up front.
            # The edit keys the cache on the source digest (same instruction on
            # a different image must never hit) and stamps the result's source
            # as kind "edited" with the parent asset id, so provenance chains.
            source_images: Optional[list] = None
            source_digest: Optional[str] = None
            if payload.source_asset_id:
                source_stored = repo.require_asset_record(payload.source_asset_id)
                source_media = (source_stored["asset"].get("media") or {})
                source_digest = (source_media.get("digest") or {}).get("value")
                blob_path = (
                    resolve_store_path(f"sha256/{source_digest[:2]}/{source_digest}")
                    if source_digest
                    else None
                )
                if blob_path is None or not blob_path.is_file():
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "asset.source_bytes_missing",
                            "message": (
                                f"source asset {payload.source_asset_id} has no stored"
                                " bytes to edit"
                            ),
                            "diagnostics": [],
                        },
                    )
                source_images = [
                    (blob_path.read_bytes(), source_media.get("mime_type") or "image/png")
                ]
            # Generation cache: re-use the asset produced by an identical earlier
            # request instead of re-paying the model (the byte-digest store dedup
            # only fires AFTER the paid, non-deterministic call). Checked BEFORE the
            # provider; the cache lives in the same store the assets do.
            cache_key = image_cache.generation_key(
                prompt=payload.prompt,
                model=image_provider.configured_model_id(),
                width=payload.width,
                height=payload.height,
                brand_notes=payload.brand_notes,
                aspect_ratio=payload.aspect_ratio,
                image_size=payload.image_size,
                transparent_background=payload.transparent_background,
                reference_asset_ids=payload.reference_asset_ids,
                source_digest=source_digest,
            )
            cached_record = image_cache.lookup(asset_store_root(), cache_key)
            if cached_record:
                log_event(
                    api_logger,
                    logging.INFO,
                    "asset_generation_completed",
                    status="ok",
                    provider=payload.provider,
                    asset_id=cached_record.get("id"),
                    deduplicated=True,
                    cached=True,
                )
                return {
                    "schema_version": 1,
                    "asset": cached_record,
                    "provider": {"id": payload.provider},
                    "deduplicated": True,
                    "diagnostics": [],
                }
            # Real text-to-image generation runs here in the async-capable Python
            # layer; the returned bytes are persisted through the SAME ingest
            # pipeline as uploads, stamped with a `generated` source, so the rest
            # of the stack (placement/render/export/validation) is unchanged.
            try:
                if source_images is not None:
                    generated = image_provider.edit(
                        prompt=payload.prompt,
                        source_images=source_images,
                        brand_notes=payload.brand_notes,
                        transparent_background=payload.transparent_background,
                        request_id=asset_id,
                    )
                else:
                    generated = image_provider.generate(
                        prompt=payload.prompt,
                        width=payload.width,
                        height=payload.height,
                        brand_notes=payload.brand_notes,
                        aspect_ratio=payload.aspect_ratio,
                        image_size=payload.image_size,
                        transparent_background=payload.transparent_background,
                        reference_asset_ids=payload.reference_asset_ids,
                        request_id=asset_id,
                    )
            except image_provider.ImageGenerationError as error:
                log_event(
                    api_logger,
                    logging.INFO,
                    "asset_generation_completed",
                    status="rejected",
                    provider=payload.provider,
                    error_code=error.code,
                )
                raise HTTPException(
                    status_code=error.status_code,
                    detail={"code": error.code, "message": str(error), "diagnostics": []},
                ) from error
            try:
                result = app.state.core.ingest_asset(
                    store_root=asset_store_root(),
                    bytes_base64=base64.b64encode(generated.image_bytes).decode("ascii"),
                    asset_id=asset_id,
                    label=payload.label or (payload.prompt[:60].strip() or asset_id),
                    declared_mime_type=generated.mime_type,
                    kind=payload.output_kind,
                    license=generated.license,
                    provenance=generated.provenance,
                    source=(
                        {
                            "kind": "edited",
                            "request_id": asset_id,
                            "model": generated.model,
                            "source_asset_id": payload.source_asset_id,
                        }
                        if payload.source_asset_id
                        else {
                            "kind": "generated",
                            "request_id": asset_id,
                            "model": generated.model,
                        }
                    ),
                    max_bytes=asset_max_bytes(),
                    raise_on_error=False,
                )
            except CoreError as error:
                raise core_http_error(error) from error
        else:
            request = {
                "request_id": asset_id,
                "prompt": payload.prompt,
                "output_kind": payload.output_kind,
                "target_node_id": None,
                "target_slot_id": None,
                "constraints": {
                    "width": payload.width,
                    "height": payload.height,
                    "mime_type": payload.mime_type,
                    "transparent_background": payload.transparent_background,
                    "brand_notes": payload.brand_notes,
                    "aspect_ratio": payload.aspect_ratio,
                    "image_size": payload.image_size,
                    "reference_asset_ids": payload.reference_asset_ids,
                },
            }
            try:
                result = app.state.core.generate_asset(
                    store_root=asset_store_root(),
                    provider=payload.provider,
                    request=request,
                    asset_id=asset_id,
                    label=payload.label,
                    raise_on_error=False,
                )
            except CoreError as error:
                raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        if not result.get("ok", False):
            error = result.get("error") or {}
            if not diagnostics:
                diagnostics = diagnostics_from_helper_error(error)
            log_event(
                api_logger,
                logging.INFO,
                "asset_generation_completed",
                status="rejected",
                provider=payload.provider,
                error_code=error.get("code"),
                **diagnostic_summary(diagnostics),
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "code": error.get("code"),
                    "message": error.get("message"),
                    "diagnostics": diagnostics,
                },
            )

        asset_payload = result.get("asset") or {}
        record = asset_payload.get("record") or {}
        stored = repo.create_asset_record(record)
        if cache_key is not None:
            # Record the request → asset mapping so an identical repeat re-uses
            # this asset instead of re-paying the model.
            image_cache.store(asset_store_root(), cache_key, stored["asset"])
        log_event(
            api_logger,
            logging.INFO,
            "asset_generation_completed",
            status="ok",
            provider=payload.provider,
            asset_id=record.get("id"),
            deduplicated=asset_payload.get("deduplicated", False),
            **diagnostic_summary(diagnostics),
        )
        return {
            "schema_version": 1,
            "asset": stored["asset"],
            "provider": asset_payload.get("provider") or {"id": payload.provider},
            "deduplicated": asset_payload.get("deduplicated", False),
            "diagnostics": diagnostics,
        }

    @app.get("/assets")
    def list_assets(
        kind: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        include_archived: bool = Query(False),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        rows = repo.list_asset_records(
            kind=kind,
            q=q,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return {
            "schema_version": 1,
            "assets": [row["asset"] for row in rows],
            "count": len(rows),
            "limit": limit,
            "offset": offset,
        }

    @app.post("/assets/{asset_id}/archive")
    def archive_asset(
        asset_id: str,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        stored = repo.update_asset_status(asset_id, "archived")
        log_event(
            api_logger,
            logging.INFO,
            "asset_archived",
            asset_id=asset_id,
        )
        return {"schema_version": 1, "asset": stored["asset"]}

    @app.post("/assets/{asset_id}/restore")
    def restore_asset(
        asset_id: str,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        stored = repo.update_asset_status(asset_id, "ready")
        log_event(
            api_logger,
            logging.INFO,
            "asset_restored",
            asset_id=asset_id,
        )
        return {"schema_version": 1, "asset": stored["asset"]}

    @app.delete("/assets/{asset_id}")
    def hard_delete_asset(
        asset_id: str,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        stored = repo.require_asset_record(asset_id)
        record = stored["asset"]

        # Record-level reference check (archive-first lifecycle): a hard
        # delete is refused while any document scene references the asset.
        referencing = repo.count_documents_referencing(f'"{asset_id}"')
        if referencing:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"asset {asset_id} is referenced by {referencing} document(s); "
                    "archive it instead or remove the references first"
                ),
            )

        repo.delete_asset_record(asset_id)

        # Byte-level lifecycle (Decision 4): bytes leave the store only
        # when no remaining record or document references their digest.
        removed_digests: List[str] = []
        for digest_value in record_digest_values(record):
            if repo.count_assets_with_digest(digest_value):
                continue
            if repo.count_documents_referencing(digest_value):
                continue
            if delete_stored_digest(digest_value):
                removed_digests.append(digest_value)

        log_event(
            api_logger,
            logging.INFO,
            "asset_hard_deleted",
            asset_id=asset_id,
            removed_digest_count=len(removed_digests),
        )
        return {
            "schema_version": 1,
            "deleted": asset_id,
            "removed_digests": removed_digests,
        }

    def record_digest_values(record: JsonObject) -> List[str]:
        values: List[str] = []
        media = record.get("media") or {}
        digest = media.get("digest") or {}
        if digest.get("value"):
            values.append(digest["value"])
        thumbnail = media.get("thumbnail") or {}
        thumbnail_ref = (thumbnail.get("location") or {}).get("opaque_ref") or ""
        if thumbnail_ref.startswith("sha256/"):
            thumbnail_digest = thumbnail_ref.rsplit("/", 1)[-1]
            if thumbnail_digest and thumbnail_digest not in values:
                values.append(thumbnail_digest)
        return values

    def delete_stored_digest(digest_value: str) -> bool:
        relative = f"sha256/{digest_value[:2]}/{digest_value}"
        path = resolve_store_path(relative)
        if not path.is_file():
            return False
        path.unlink()
        return True

    # GET /assets/descriptions is registered BEFORE GET /assets/{asset_id} so
    # the literal "descriptions" segment is not captured as an asset id (FastAPI
    # matches routes in registration order at the same path depth).
    @app.get("/assets/descriptions")
    def get_asset_descriptions(
        asset_ids: str = Query(..., description="comma-separated asset ids"),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        ids = [ident for ident in (asset_ids or "").split(",") if ident.strip()]
        ids = [ident.strip() for ident in ids][:200]
        store = DescriptionStore(repo.connection)
        return {
            "schema_version": 1,
            "descriptions": store.get_many(ids),
        }

    @app.put("/assets/{asset_id}/description")
    def set_asset_description(
        asset_id: str,
        payload: SetAssetDescriptionRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        """Human-author an asset's library metadata (partial merge with the
        existing row). 404 only when the asset RECORD doesn't exist."""
        repo.require_asset_record(asset_id)
        store = DescriptionStore(repo.connection)
        existing = store.get_many([asset_id]).get(asset_id) or {}

        def _merge(key: str, incoming: Optional[Any]) -> Any:
            return incoming if incoming is not None else existing.get(key)

        store.put_human(
            asset_id,
            title=_merge("title", payload.title),
            description=_merge("description", payload.description),
            usage=_merge("usage", payload.usage),
            tags=payload.tags if payload.tags is not None else list(existing.get("tags") or []),
        )
        return store.get_many([asset_id])[asset_id]

    @app.get("/assets/{asset_id}")
    def get_asset(
        asset_id: str,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        stored = repo.require_asset_record(asset_id)
        return {
            "schema_version": 1,
            "asset": stored["asset"],
            "created_at": stored["created_at"],
            "updated_at": stored["updated_at"],
        }

    @app.get("/assets/{asset_id}/bytes")
    def get_asset_bytes(
        asset_id: str,
        repo: Repository = Depends(repository),
    ) -> Response:
        stored = repo.require_asset_record(asset_id)
        record = stored["asset"]
        media = record.get("media") or {}
        location = media.get("location") or {}
        if location.get("provider") != "local-store" or not location.get("opaque_ref"):
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} has no locally stored bytes",
            )
        path = resolve_store_path(location["opaque_ref"])
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} bytes are missing from the store",
            )
        media_type = media.get("mime_type") or "application/octet-stream"
        return Response(content=path.read_bytes(), media_type=media_type)

    @app.get("/assets/{asset_id}/thumbnail")
    def get_asset_thumbnail(
        asset_id: str,
        repo: Repository = Depends(repository),
    ) -> Response:
        stored = repo.require_asset_record(asset_id)
        record = stored["asset"]
        thumbnail = (record.get("media") or {}).get("thumbnail") or {}
        location = thumbnail.get("location") or {}
        if location.get("provider") != "local-store" or not location.get("opaque_ref"):
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} has no thumbnail",
            )
        path = resolve_store_path(location["opaque_ref"])
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} thumbnail bytes are missing from the store",
            )
        media_type = thumbnail.get("mime_type") or "application/octet-stream"
        return Response(content=path.read_bytes(), media_type=media_type)

    def resolve_store_path(opaque_ref: str) -> Path:
        root = Path(app.state.asset_store_root).resolve()
        candidate = (root / opaque_ref).resolve()
        if root != candidate and root not in candidate.parents:
            raise HTTPException(status_code=400, detail="invalid asset location")
        return candidate

    def asset_max_bytes() -> int:
        return int(os.environ.get("LUMEN_ASSET_MAX_BYTES", str(10 * 1024 * 1024)))

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


def _resolve_guard_url():
    """Resolve the capture SSRF guard lazily.

    Agent A's ``lumen_ingestion.capture.net.guard_url`` is an async callable
    that resolves DNS and rejects loopback/private/link-local/reserved
    addresses, non-standard ports, userinfo, and non-http(s) schemes. It is
    imported lazily so this module stays importable while the capture package
    is being built; tests monkeypatch this resolver.
    """
    from lumen_ingestion.capture.net import guard_url

    return guard_url


# Asset-upload ingest (slice 3 §6). The cap mirrors uploads.py's own LUMI0702
# cap so the route and analyzer agree; the sniff mirrors §2's accepted types.
_INGEST_MAX_ASSET_FILES = 20


def _sniff_supported_asset(data: bytes) -> bool:
    """True when ``data`` looks like PNG, JPEG, WebP, or SVG by magic bytes
    (§2). Mirrors uploads.py's own sniff so the route and analyzer agree on
    which files are worth queuing; uploads.py re-sniffs and skips per-file."""
    if not data:
        return False
    if data.startswith(b"\x89PNG"):
        return True
    if data.startswith(b"\xff\xd8"):  # JPEG
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    # SVG: first 512 bytes contain "<svg" after optional decl/whitespace/comments.
    head = data[:512]
    try:
        text = head.decode("utf-8", errors="ignore").lower()
    except Exception:
        return False
    return "<svg" in text


def _sanitize_tmp_filename(filename: Optional[str]) -> str:
    """Sanitize an uploaded filename for use in a tmp path: keep only
    ``[A-Za-z0-9._-]`` and cap length. Never returns empty."""
    base = os.path.basename(filename or "")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or "asset"
    return cleaned[:80]


def ingest_url_rejected(url: str, error: Exception) -> HTTPException:
    code = getattr(error, "code", "LUMI0501")
    message = getattr(error, "message", None) or str(error) or f"blocked url: {url}"
    return HTTPException(
        status_code=422,
        detail={"code": code, "message": message},
    )


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
    payload: AgentTurnPreviewRequest, root: Path, event_sink=None
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
        if payload.model:
            config = replace(config, model=payload.model)
        if config.asset_store_root is None:
            # A seeded scene references assets ingested through the API's store;
            # the agent must export from the same root or seeded imagery fails
            # with LUME0210 (asset bytes missing). LUMEN_AGENT_ASSET_STORE still
            # overrides explicitly.
            config = replace(config, asset_store_root=api_asset_store_root())
        brand_kit, brand_kit_source = resolve_agent_turn_brand_kit(payload)
        if brand_kit is not None:
            # K0 (kit application): the document's attached kit rides the run
            # config BY VALUE so the runtime preflights against it instead of
            # the platform default — without this, an attached scene ref vs the
            # default kit trips LUMB0101 and token resolution short-circuits.
            config = replace(
                config, brand_kit=brand_kit, brand_kit_source=brand_kit_source
            )
        prompt = editor_agent_prompt(payload)
        loop, tools = create_provider_quality_loop(
            prompt,
            config,
            initial_scene=agent_seed_scene(payload),
            event_sink=event_sink,
        )
        result = loop.run(prompt)
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.failed",
            "Agent runtime failed before returning a proposal.",
            str(error),
        )

    return agent_response_from_trace(result, tools.trace_dir, tools.scene)


def sse_frame(seq: int, event: str, data: Any) -> str:
    """One Server-Sent Events frame. `id:` carries the monotonic run-event
    seq so the browser's EventSource replays from it via Last-Event-ID."""
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data)}\n\n"


def ensure_agent_runtime_path(root: Path) -> None:
    agent_runtime_path = str(root / "apps" / "agent_runtime")
    api_path = str(root / "apps" / "api")
    for path in [agent_runtime_path, api_path]:
        if path not in sys.path:
            sys.path.insert(0, path)


def api_asset_store_root() -> Path:
    """The API's asset store root, resolved exactly as create_app resolves it."""
    database_path = Path(
        os.environ.get("LUMEN_API_DATABASE_PATH", "apps/api/lumen-api.sqlite3")
    )
    return Path(
        os.environ.get("LUMEN_ASSET_STORE_ROOT") or database_path.parent / "asset-store"
    )


def resolve_agent_turn_brand_kit(
    payload: AgentTurnPreviewRequest,
) -> Tuple[Optional[JsonObject], Optional[str]]:
    """The Brand Kit attached to the turn's document, loaded from the kit
    library so it can be passed BY VALUE into the runtime config (the runtime
    never reads the API database).

    Resolution failures never fail the turn: no scene ref, an unknown kit id,
    or an unreadable database all return (None, None) and the runtime falls
    back to the platform default kit — exactly the pre-K0 behavior."""
    scene = payload.scene if isinstance(payload.scene, dict) else None
    meta = scene.get("meta") if scene else None
    ref = meta.get("brand_kit") if isinstance(meta, dict) else None
    if not isinstance(ref, dict) or not ref.get("id"):
        return None, None
    database_path = Path(
        os.environ.get("LUMEN_API_DATABASE_PATH", "apps/api/lumen-api.sqlite3")
    )
    try:
        connection = connect(database_path)
    except Exception:
        return None, None
    try:
        record = Repository(connection).require_brand_kit(
            str(ref["id"]), ref.get("version")
        )
        return record["brand_kit"], "document"
    except Exception:
        return None, None
    finally:
        connection.close()


def agent_seed_scene(payload: AgentTurnPreviewRequest) -> Optional[JsonObject]:
    """Phase 0a: the live editor scene seeds the agent's working scene, so a
    targeted edit lands on existing NodeIds instead of an empty document. Only
    a payload that carries a structurally plausible scene document seeds the
    run; anything else falls back to a fresh scene.

    An EMPTY document (no pages, no nodes) also runs unseeded: there is no
    user work to preserve, and continuation mode would only force the agent
    to fight a blank scaffold — the fresh-generation path is the proven one.
    (Observed live: a generation brief into the old default demo page burned
    every iteration on page-collision repairs.)"""
    scene = payload.scene
    if (
        isinstance(scene, dict)
        and isinstance(scene.get("nodes"), dict)
        and isinstance(scene.get("pages"), dict)
        and isinstance(scene.get("meta"), dict)
    ):
        if not scene["pages"] and not scene["nodes"]:
            return None
        return scene
    return None


def editor_target_node_ids(payload: AgentTurnPreviewRequest) -> List[str]:
    """The nodes the human chipped as edit targets (2c).
    De-duplicated, order preserved."""
    raw = payload.target_node_ids
    seen: set[str] = set()
    targets: List[str] = []
    for node_id in raw:
        if node_id and node_id not in seen:
            seen.add(node_id)
            targets.append(node_id)
    return targets


def editor_agent_prompt(payload: AgentTurnPreviewRequest) -> str:
    targets = editor_target_node_ids(payload)
    context = {
        "document_id": payload.document_id,
        "active_page_id": payload.active_page_id,
        "target_node_ids": targets,
        "scene_summary": scene_context_summary(payload.scene),
        "current_diagnostics": payload.diagnostics[:20],
        "editor_instruction": editor_instruction(targets),
    }
    instructions = (payload.agent_instructions or "").strip()
    if instructions:
        # 2e: the document's standing instructions apply to EVERY turn — they
        # shape style and constraints but never override the current request.
        context["standing_instructions"] = (
            f"{instructions} (These are the document's standing instructions; "
            "apply them to every turn, but the user's current request wins on conflict.)"
        )
    return (
        f"{payload.prompt}\n\n"
        "Editor context JSON:\n"
        f"{json.dumps(context, indent=2)}"
    )


def editor_instruction(targets: List[str]) -> str:
    """2c compensating-edit contract (Moda §1.6): scope the change to the
    chipped target(s), then re-fit and verify — and report both what changed
    and what was preserved. When targets are named, everything else must stay
    byte-identical."""
    base = (
        "Return changes that can be applied to the current canonical Scene. "
        "Do not mutate scene JSON outside canonical operations. "
    )
    if targets:
        scope = (
            "Scope every change to these target node id(s): "
            f"{', '.join(targets)}. Do not touch any other node — every "
            "untouched node must stay byte-identical. "
        )
    else:
        scope = (
            "Prefer targeted repairs when a selected node or diagnostic target "
            "is present, and touch as little else as possible. "
        )
    contract = (
        "Make a compensating edit: apply the requested change, then re-fit and "
        "verify the result — text must still fit its box (no overflow), nodes "
        "must not newly overlap, and the surrounding layout must be preserved. "
        "In your summary, state both what you changed and what you preserved."
    )
    return base + scope + contract


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
    # Phase 0b: the loop's keep-best snapshot can return an EARLIER iteration's
    # scene as the draft. Operations from later iterations are then not part of
    # that draft and must not be replayed by the editor.
    ops_valid_through = result.get("ops_valid_through_iteration")
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
                if compile_summary.get("status") == "ok" and iteration_in_ops_window(
                    iteration_dir.name, ops_valid_through
                ):
                    operations.extend(compile_payload.get("operations", []))

    raw_preview_paths = result.get("preview_paths", [])
    preview_paths = (
        [str(path) for path in raw_preview_paths if isinstance(path, str)]
        if isinstance(raw_preview_paths, list)
        else []
    )
    accepted = result.get("status") == "accepted"
    # Phase 0b edit-scoped acceptance: a seeded turn whose requested edit is
    # verified applied proposes its operations even though the whole-design
    # critique still has (advisory) complaints.
    edit_scoped = result.get("status") == "edit_applied"
    # Agent-quality: `completed_with_warnings` means the loop kept a
    # PREFLIGHT-CLEAN best draft that simply never won explicit visual
    # acceptance within the repair budget. That is a reviewable proposal —
    # mapping it to "failed" threw away good drafts (runs d6e08a28/d77d41d in
    # the 2e gate both died here). The unresolved critique rides along as
    # advisory warnings, exactly like an edit-scoped acceptance.
    best_draft = result.get("status") == "completed_with_warnings"
    status = (
        "proposed" if (accepted or edit_scoped or best_draft) and operations else "failed"
    )
    if (edit_scoped or best_draft) and status == "proposed":
        diagnostics.extend(
            advisory_critique_diagnostics(result.get("critique"))
        )
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
        "acceptance_scope": "edit" if edit_scoped else ("design" if accepted else None),
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


def iteration_in_ops_window(dir_name: str, ops_valid_through: Any) -> bool:
    """True when an iteration's applied operations belong to the returned draft."""
    if not isinstance(ops_valid_through, int):
        return True
    try:
        return int(dir_name) <= ops_valid_through
    except ValueError:
        return True


def advisory_critique_diagnostics(critique: Any) -> List[JsonObject]:
    """Surface a whole-design critique as ADVISORY warnings (Phase 0b).

    On an edit-scoped acceptance the critique did not block the turn; the
    editor still shows its issues so the human can act on them (or ask the
    agent to, as a follow-up turn)."""
    diagnostics: List[JsonObject] = []
    if isinstance(critique, dict) and critique.get("kind") == "visual":
        # A completed_with_warnings run finalizes with the loop's last FEEDBACK
        # envelope ({"kind": "visual", "feedback": {critique...}}), not the bare
        # critique. Non-visual envelopes (compile/preflight) carry no critique
        # issues and simply yield no advisories.
        critique = critique.get("feedback")
    issues = (critique or {}).get("issues") if isinstance(critique, dict) else None
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        target = issue.get("target") or {}
        subject = None
        if isinstance(target, dict):
            if target.get("node_id"):
                subject = {"kind": "node", "id": target["node_id"]}
            elif target.get("page_id"):
                subject = {"kind": "page", "id": target["page_id"]}
        diagnostics.append(
            agent_diagnostic(
                "agent_runtime.visual_critique_advisory",
                str(issue.get("message") or "Visual critique note."),
                "review",
                "warning",
                issue.get("suggested_repair"),
                subject,
            )
        )
    return diagnostics


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
