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
from contextlib import asynccontextmanager
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
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from . import image_cache, image_provider
from .core import CoreClient, CoreError, has_error_diagnostics
from .database import NotFoundError, Repository, connect, run_migrations, utc_now
from .font_library import manifest as font_library_manifest
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
    SetBrandKitLogoRequest,
    ValidateBrandKitRequest,
    ValidateDocumentBrandGovernanceRequest,
)
from lumen_ingestion.capture.uploads import sniff_mime
from lumen_ingestion.describe import DescriptionStore
from lumen_ingestion.jobs import IngestionJobStore
from lumen_ingestion.pipeline import (
    run_asset_ingestion,
    run_pdf_ingestion,
    run_website_ingestion,
)
from py_lumen_config import settings
from py_lumen_obs import bind_request_id, configure, get_logger, unbind_context

from .observability import (
    REQUEST_ID_HEADER,
    artifact_summary,
    diagnostic_summary,
    duration_ms,
    log_event,
    new_request_id,
)


JsonObject = Dict[str, Any]
api_logger = get_logger("lumen_api.api")


def _bridge_uvicorn_loggers() -> None:
    """Route uvicorn's own loggers through the shared obs stdlib bridge.

    uvicorn installs private StreamHandlers on ``uvicorn`` / ``uvicorn.error`` /
    ``uvicorn.access`` when the server boots; left alone they double-emit beside
    the structured stream with their raw ``INFO:`` format. Clearing those
    handlers and letting the loggers propagate to the root means every uvicorn
    line flows through the same processor chain as everything else. Runs at
    lifespan startup — AFTER uvicorn has configured its logging — so the clear
    actually takes effect (doing it at import time would be a no-op).
    """
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


_AGENT_RELEVANT_PREFIXES = ("/agent", "/documents")


def _is_agent_relevant(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _AGENT_RELEVANT_PREFIXES)


def _content_length(headers: Any) -> Optional[int]:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def cors_origins() -> List[str]:
    return settings.cors_origins_list


def create_app(database_path: Optional[Path] = None, migrate: bool = True) -> FastAPI:
    # The ONE logging setup for the API: hand off to the shared obs module.
    # mode/format come from the environment (LUMEN_LOG_MODE / LUMEN_LOG_FORMAT);
    # nothing else in apps/api configures logging after this. Idempotent, so a
    # second create_app (e.g. per-test) reinstalls a single owned handler.
    configure(mode=None)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # uvicorn has configured its own logging by the time lifespan startup
        # runs; fold its loggers into the shared bridge so there is one stream.
        _bridge_uvicorn_loggers()
        yield

    app = FastAPI(title="ABM Design Engine Persistence API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.database_path = database_path or settings.lumen_api_database_path
    app.state.asset_store_root = (
        settings.lumen_asset_store_root
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
        # Bind once into the obs contextvar — every event for this request
        # (here and in the core-helper path) is stamped with request_id by the
        # merge_contextvars processor, so no call threads it explicitly.
        bind_request_id(request_id)
        start = time.perf_counter()
        try:
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
                raise

            response.headers[REQUEST_ID_HEADER] = request_id
            route = request.scope.get("route")
            elapsed = duration_ms(start)
            log_event(
                api_logger,
                logging.INFO,
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                route=getattr(route, "path", None),
                status_code=response.status_code,
                duration_ms=elapsed,
                client_host=request.client.host if request.client else None,
            )
            # Debug-only request/response summary on agent-relevant routes.
            # Sizes only — NEVER bodies/asset bytes (asset byte routes live under
            # /assets/*, disjoint from these prefixes). Emitted at DEBUG so it
            # only surfaces when LUMEN_LOG_MODE=debug.
            if _is_agent_relevant(request.url.path):
                log_event(
                    api_logger,
                    logging.DEBUG,
                    "http_request_summary",
                    method=request.method,
                    path=request.url.path,
                    route=getattr(route, "path", None),
                    status_code=response.status_code,
                    duration_ms=elapsed,
                    request_bytes=_content_length(request.headers),
                    response_bytes=_content_length(response.headers),
                )
            return response
        finally:
            unbind_context("request_id")

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

    @app.get("/font-library")
    def font_library() -> JsonObject:
        """The curated font-library manifest (Track B): always-present
        families with per-weight faces in the asset store, measured metrics,
        and agent-facing tone/pairing notes. The editor loads faces for
        families the open document references via `/assets/{id}/bytes`, the
        same leg kit fonts ride. An unprovisioned environment gets an empty
        library, not an error."""
        parsed = font_library_manifest()
        return parsed if parsed is not None else {"version": 1, "families": []}

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
        # The platform default kit is the ENGINE's builtin, not an ingested
        # kit — it has no registry row by definition. Serve it from the
        # engine (with `ensure_platform_color_tokens` backfilled), because
        # the editor's canvas token resolution fetches this id for kit-less
        # documents to mirror server-side resolution; a 404 here silently
        # dropped the canvas to its string heuristic — token colors then
        # diverged from every export. The response goes through the SAME
        # detail DTO as ingested kits (a synthesized record), so every
        # consumer sees one envelope shape.
        if brand_kit_id == "brand_kit_platform_default":
            kit = app.state.core.platform_default_brand_kit()
            detail = brand_kit_detail_dto(
                {
                    "brand_kit_id": brand_kit_id,
                    "version": 0,
                    "name": kit.get("name") or "Platform default",
                    "approval_status": "approved",
                    "product_ready": True,
                    "source": "builtin",
                    "brand_kit": kit,
                    "brand_summary": {},
                    "diagnostics": [],
                    "created_at": None,
                    "updated_at": None,
                }
            )
            detail["builtin"] = True
            return detail
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

    @app.post("/brand-kits/{brand_kit_id}/logo")
    def set_brand_kit_logo(
        brand_kit_id: str,
        payload: SetBrandKitLogoRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        """Human logo curation: promote a library asset into a logo slot of
        the kit's latest version and publish it as a NEW version (manual
        provenance, confidence 1.0). The scraper's guess stays in history;
        the human's choice becomes current. Works for ANY kit — nothing here
        is brand-specific."""
        record = repo.require_brand_kit(brand_kit_id)
        asset_record = repo.require_asset_record(payload.asset_id)
        asset = asset_record.get("asset") or asset_record

        brand_kit = json.loads(json.dumps(record["brand_kit"]))
        assets = brand_kit.setdefault("assets", {}) or brand_kit["assets"]
        logos = assets.setdefault("logos", {}) or assets["logos"]
        slot = logos.get(payload.slot)
        if not isinstance(slot, dict):
            slot = {
                "usage": payload.slot,
                "min_size": 24.0,
                "clearspace": None,
                "allowed_backgrounds": [],
                "license": None,
            }
        slot["variants"] = [
            {
                "asset_id": payload.asset_id,
                "name": payload.color_mode,
                "color_mode": payload.color_mode,
                "width": None,
                "height": None,
            }
        ]
        slot["provenance"] = {
            "confidence": 1.0,
            "source": f"manual :: human-selected {asset.get('label') or payload.asset_id}",
        }
        logos[payload.slot] = slot
        brand_kit["version"] = int(brand_kit.get("version") or 1) + 1

        try:
            validation = app.state.core.validate_brand_kit(
                brand_kit, product_ready=False
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
            created = repo.create_brand_kit(
                brand_kit,
                summary_response.get("brand_summary") or {},
                diagnostics,
                "manual",
            )
        except sqlite3.IntegrityError as error:
            raise duplicate_brand_kit_error(brand_kit) from error
        log_event(
            api_logger,
            logging.INFO,
            "brand_kit_logo_set",
            brand_kit_id=brand_kit_id,
            slot=payload.slot,
            asset_id=payload.asset_id,
            version=brand_kit["version"],
        )
        return brand_kit_created_dto(created, diagnostics)

    @app.post("/brand-kits/{brand_kit_id}/describe-assets")
    def describe_brand_kit_assets(
        brand_kit_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        """Imagery slice 1 backfill: describe the latest kit version's
        logo/image assets (cache-first — only misses cost a vision call) and,
        when anything changed, publish a NEW kit version carrying the
        metadata. The republish is load-bearing: descriptions are frozen into
        the kit JSON at publish, so healing the ``asset_descriptions`` library
        alone never reaches the agent's brand card. Generic for any kit."""
        from lumen_ingestion.describe import describe_kit_assets
        from lumen_ingestion.normalizer.font_metrics import (
            ensure_glyph_coverage,
            ensure_type_size_ramp,
        )
        from lumen_ingestion.pipeline import (
            make_rasterize_svg,
            make_resolve_bytes,
            resolve_describer,
        )

        record = repo.require_brand_kit(brand_kit_id)
        brand_kit = json.loads(json.dumps(record["brand_kit"]))
        before = json.dumps(brand_kit, sort_keys=True)
        # Re-run the normalizer's type-size ramp emission before publishing:
        # kits produced before the ramp normalizer (K4 rung 2) lack $type.size.*
        # and die preflight LUMB0301 on standard size tokens. Idempotent — a kit
        # that already carries the up-to-date ramp is left byte-identical, so
        # this alone never forces a no-op republish.
        ensure_type_size_ramp(brand_kit)
        store_root = str(asset_store_root())
        describe_diagnostics: list = []
        # Glyph-coverage audit backfill (same pattern as the ramp): kits ingested
        # before the audit get fonts.*.metrics.missing_glyphs stamped from their
        # stored face bytes, so the honesty note reaches the agent's brand card
        # on republish without a full re-ingestion. Advisory LUMI0806 warnings.
        ensure_glyph_coverage(
            brand_kit,
            make_resolve_bytes(repo, store_root),
            describe_diagnostics,
        )
        counts = describe_kit_assets(
            brand_kit,
            connection=repo.connection,
            describer=resolve_describer(),
            resolve_bytes=make_resolve_bytes(repo, store_root),
            rasterize_svg=make_rasterize_svg(repo, store_root),
            diagnostics=describe_diagnostics,
            brand_name=record.get("name"),
        )
        if json.dumps(brand_kit, sort_keys=True) == before:
            # Nothing stamped (all failed, describe disabled, or already
            # described) — publishing an identical version would be noise.
            return {
                "brand_kit_id": brand_kit_id,
                "published": False,
                "counts": counts,
                "diagnostics": describe_diagnostics,
            }
        brand_kit["version"] = int(brand_kit.get("version") or 1) + 1
        try:
            validation = app.state.core.validate_brand_kit(
                brand_kit, product_ready=False
            )
            brand_kit = validation["brand_kit"]
            summary_response = app.state.core.summarize_brand_kit(
                brand_kit, raise_on_error=False
            )
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = (
            summary_response.get("diagnostics")
            or validation.get("diagnostics", [])
        ) + describe_diagnostics
        try:
            created = repo.create_brand_kit(
                brand_kit,
                summary_response.get("brand_summary") or {},
                diagnostics,
                "manual",
            )
        except sqlite3.IntegrityError as error:
            raise duplicate_brand_kit_error(brand_kit) from error
        log_event(
            api_logger,
            logging.INFO,
            "brand_kit_assets_described",
            brand_kit_id=brand_kit_id,
            version=brand_kit["version"],
            **counts,
        )
        response = brand_kit_created_dto(created, diagnostics)
        response["published"] = True
        response["counts"] = counts
        return response

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
            result = app.state.core.preflight_scene(
                document["scene"],
                brand_kit,
                mode,
                brand_fonts=brand_kit_font_spec(repo, brand_kit, asset_store_root()),
            )
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
    def export_preview(
        payload: ExportPreviewRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        # K3: a stateless export still shapes text with the scene's kit fonts
        # — the scene ref is the only kit signal this route carries.
        brand_fonts = scene_brand_fonts(repo, payload.scene, asset_store_root())
        try:
            result = app.state.core.export_preview(
                payload.scene,
                payload.format,
                payload.page_ids,
                payload.profile,
                raise_on_error=False,
                asset_store_root=asset_store_root(),
                brand_fonts=brand_fonts,
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
        #
        # RC (adversarial-gate ship-blocker 1): validate + resolve reference
        # attachments HERE, before the run row exists — inside the worker the
        # catch-all would swallow the resolver's 422s into a generic
        # agent_runtime.failed and the client would never see
        # reference.asset_not_found / too_many / preview_unavailable. The
        # resolved manifest rides into the worker so SVG rasterization is not
        # paid twice.
        resolved_reference_assets = resolve_agent_turn_references(payload)
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
                        response = run_agent_turn_preview(
                            payload,
                            root,
                            event_sink=sink,
                            resolved_reference_assets=resolved_reference_assets,
                        )
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
            document_brand_fonts = brand_kit_font_spec(
                repo, brand_kit, asset_store_root()
            )
            preflight_result = app.state.core.preflight_scene(
                document["scene"], brand_kit, mode, brand_fonts=document_brand_fonts
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
                brand_fonts=document_brand_fonts,
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
            result = app.state.core.preflight_scene(
                payload.scene,
                brand_kit,
                mode,
                brand_fonts=brand_kit_font_spec(repo, brand_kit, asset_store_root()),
            )
        except CoreError as error:
            raise core_http_error(error) from error

        scene = result.get("scene", payload.scene)
        diagnostics = result.get("diagnostics", [])
        preflight = result.get("preflight") or {}

        # K1.6(b): bake the freeze on the RESOLVED, server-relaid-out scene —
        # the only geometry source that can never carry skeleton-literal
        # solves. Raw ops (not summaries) ride a `bake` block so the editor
        # can merge them into the accept envelope. A preflight with errors
        # skips the bake: freezing broken geometry helps nobody, and the
        # editor falls back to its client-side path.
        bake = None
        if payload.freeze_layout and not has_error_diagnostics(diagnostics):
            try:
                freeze_result = app.state.core.apply_structured_edit(
                    scene, {"kind": "freeze_layout"}
                )
            except CoreError as error:
                raise core_http_error(error) from error
            frozen_scene = freeze_result.get("scene", scene)
            freeze_edit = freeze_result.get("edit") or {}
            bake = {
                "scene": frozen_scene,
                "resolution_operations": (
                    preflight.get("brand_ref_operations", [])
                    + preflight.get("token_operations", [])
                    + preflight.get("layout_operations", [])
                ),
                "freeze_operations": freeze_result.get("operations") or [],
                "freeze_inverse_operations": freeze_edit.get("inverse_operations")
                or [],
            }
            scene = frozen_scene

        return preflight_preview_dto(
            scene,
            diagnostics,
            preflight,
            source,
            brand_kit,
            mode,
            bake=bake,
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
        export_profile: Optional[JsonObject] = None,
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
            export_profile=export_profile,
            # Bulk runs shape with the template's kit faces — without this
            # every instance silently substituted bundled Inter.
            brand_fonts=scene_brand_fonts(repo, revision["scene"], asset_store_root()),
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
            export_profile=resolve_saved_or_inline_profile(
                revision["scene"], payload.export_profile, payload.export_profile_name
            ),
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

    def _instance_error_codes(instance: JsonObject) -> List[str]:
        """Per-instance failure codes for the batch manifest: artifact-level
        errors (e.g. export.print_not_ready) plus error-severity diagnostics
        of failed derivations, de-duplicated in first-seen order."""
        codes: List[str] = []
        for artifact in instance.get("artifacts", []):
            error = artifact.get("error")
            if isinstance(error, dict) and error.get("code"):
                codes.append(str(error["code"]))
        if instance.get("status") == "failed":
            for diagnostic in instance.get("diagnostics", []):
                if (
                    isinstance(diagnostic, dict)
                    and diagnostic.get("severity") == "error"
                    and diagnostic.get("code")
                ):
                    codes.append(str(diagnostic["code"]))
        seen: set = set()
        return [code for code in codes if not (code in seen or seen.add(code))]

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
                    export_profile=batch.get("export_profile"),
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
                        # A failed instance's why was previously buried in the
                        # instance row; the manifest names it directly.
                        "error_codes": _instance_error_codes(instance),
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
        export_profile = resolve_saved_or_inline_profile(
            revision["scene"], payload.export_profile, payload.export_profile_name
        )
        # Fail-fast template preflight: a bleed-requesting print profile
        # against a template with no bleed geometry would gate EVERY
        # instance (export.print_not_ready) — kill the run at copy zero,
        # before deriving anything.
        if (
            export_profile
            and export_profile.get("format") == "pdf"
            and export_profile.get("include_bleed")
        ):
            missing = [
                page_id
                for page_id, page in (revision["scene"].get("pages") or {}).items()
                if not isinstance(page, dict) or not page.get("bleed")
            ]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "batch.template_not_print_ready",
                        "message": (
                            "export profile requests bleed but page(s) "
                            f"{', '.join(missing)} have no bleed rect — add print "
                            "geometry to the template before running a batch"
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
                "export_profile": export_profile,
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
    def preview_instance(
        payload: InstancePreviewRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
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
                brand_fonts=scene_brand_fonts(repo, scene, asset_store_root()),
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
            # RC (D-RC2.5): reference-conditioned GENERATION — resolve the
            # request's reference_asset_ids into real bytes (the field was inert
            # before) so the editor's generate flow conditions on attached style
            # references. Only on the pure-generation path (an edit already rides
            # its source pixels). Empty ids → None → byte-identical to today.
            reference_images: Optional[list] = None
            reference_digests: Optional[List[str]] = None
            if source_images is None:
                ref_ids = _dedupe_and_cap_reference_ids(payload.reference_asset_ids)
                if ref_ids:
                    reference_images, reference_digests = (
                        resolve_reference_images_for_generate(
                            repo, ref_ids, asset_store_root()
                        )
                    )
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
                reference_digests=reference_digests,
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
                        reference_images=reference_images,
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

    @app.get("/asset-store/{digest}")
    def get_asset_store_bytes(digest: str) -> Response:
        """Content-addressed byte serving. The editor canvas resolves image
        pixels from the SAME source of truth server exports use — the scene's
        asset record digest — so a scene-borne asset renders regardless of
        registry state (the registry-backed `/assets/{id}/bytes` 404s for any
        asset whose producer never registered it, which is how generated
        imagery vanished from the canvas while every export carried it).
        Content addressing makes the response immutable, hence the aggressive
        cache header; the strict hex gate also makes path traversal
        unexpressible (the path is built from validated hex, never client
        text)."""
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise HTTPException(
                status_code=404, detail="not a sha256 content digest"
            )
        # The store layout has ONE owner: resolve through the same helper
        # every opaque_ref-based route uses.
        path = resolve_store_path(f"sha256/{digest[:2]}/{digest}")
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"no stored bytes for digest {digest}",
            )
        with path.open("rb") as handle:
            head = handle.read(512)
        return FileResponse(
            path,
            media_type=sniff_mime(head) or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

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
        return settings.lumen_asset_max_bytes

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

    # K0.5: a kit attached through the editor's operations path (an
    # update_document patch) lands only in scene.meta.brand_kit — the
    # document row's brand_kit_json stays null (only the dedicated attach
    # route fills it). Without this fallback, preflight/export on such a
    # document resolved against the platform default and the engine's
    # scene-ref check failed with LUMB0101. Mirrors
    # choose_effective_brand_for_scene_preview's scene_ref branch.
    scene_brand_ref = (document.get("scene") or {}).get("meta", {}).get("brand_kit")
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


def resolve_saved_or_inline_profile(
    scene: JsonObject,
    profile: Optional[JsonObject],
    profile_name: Optional[str],
    default_format: Optional[str] = None,
) -> Optional[JsonObject]:
    """The one profile-resolution contract, shared by document exports and
    the bulk instance/batch paths: an inline profile and a saved-profile
    name are mutually exclusive; names resolve against the scene's
    `export_profiles` and miss loudly. Returns None when neither is given —
    the caller owns its own default."""
    if profile is not None and profile_name:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "export_profile.ambiguous_source",
                "message": "provide either profile or profile_name, not both",
            },
        )
    if profile is not None:
        resolved = dict(profile)
        if default_format is not None:
            resolved.setdefault("format", default_format)
        if not resolved.get("format"):
            # Callers without a format context (bulk instance/batch paths)
            # must say what they want — normalize's svg default would
            # silently misroute a print profile.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "export_profile.format_required",
                    "message": "inline export profile must declare a format",
                },
            )
        resolved.setdefault("name", f"{resolved['format']}_document_export")
        return normalize_export_profile(resolved)

    if profile_name:
        for saved in scene.get("export_profiles", []):
            if isinstance(saved, dict) and saved.get("name") == profile_name:
                return normalize_export_profile(dict(saved))
        raise HTTPException(
            status_code=422,
            detail={
                "code": "export_profile.not_found",
                "message": f"document has no saved export profile named {profile_name}",
            },
        )

    return None


def resolve_document_export_profile(
    scene: JsonObject,
    payload: ExportDocumentRequest,
) -> JsonObject:
    resolved = resolve_saved_or_inline_profile(
        scene, payload.profile, payload.profile_name, default_format=payload.format
    )
    if resolved is not None:
        return resolved
    return default_export_profile(payload.format)


def default_export_profile(export_format: str) -> JsonObject:
    return normalize_export_profile(
        {
            "name": f"document_{export_format}",
            "format": export_format,
            "pdf_intent": "preview" if export_format == "pdf" else None,
            "raster": {"scale": 1, "dpi": 96} if export_format == "png" else None,
            "include_bleed": False,
            "embed_fonts": export_format in ("svg", "pdf"),
        }
    )


def normalize_export_profile(profile: JsonObject) -> JsonObject:
    export_format = str(profile.get("format") or "svg")
    # embed_fonts defaults ON for the formats where it means something:
    # SVG (@font-face subsets — a name-only SVG depends on viewer-installed
    # fonts) and PDF (the vector renderer always embeds). Only an explicit
    # false opts out. PNG has no font payload; default off.
    embed_default = export_format in ("svg", "pdf")
    normalized = {
        "name": str(profile.get("name") or f"{export_format}_document_export"),
        "format": export_format,
        "pdf_intent": profile.get("pdf_intent"),
        "raster": profile.get("raster"),
        "include_bleed": bool(profile.get("include_bleed", False)),
        "embed_fonts": bool(profile.get("embed_fonts", embed_default)),
        # Print W2/W3: crop marks ride the profile; dropping the flag here
        # silently downgraded marked exports (browser-verify finding).
        "include_marks": bool(profile.get("include_marks", False)),
    }
    # Optional print controls (W4 imposition, W7 proof, W5 CMYK color):
    # this whitelist rebuild silently dropped imposition/proof for saved
    # document profiles — the same defect class as the include_marks find
    # above. Present-only passthrough keeps the engine's "absent = off"
    # serialization contract.
    if profile.get("imposition") is not None:
        normalized["imposition"] = profile.get("imposition")
    if profile.get("proof"):
        normalized["proof"] = True
    if profile.get("color") is not None:
        normalized["color"] = profile.get("color")
    return normalized


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
    compact = {
        "artifacts": [
            compact_export_artifact(artifact)
            for artifact in export.get("artifacts", [])
            if isinstance(artifact, dict)
        ],
        "diagnostics": export.get("diagnostics", []),
    }
    # Print W6: the print-ready preflight report rides print-intent PDF
    # exports; the editor renders it and the agent loop reads it. Rebuilding
    # the payload without it silently hid the report (browser-verify finding).
    if export.get("print_ready") is not None:
        compact["print_ready"] = export["print_ready"]
    return compact


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


#: Sentinel distinguishing "caller did not resolve references" from a resolved
#: None (= no references). The async route resolves BEFORE creating its run row
#: so the 422 reaches the client; it then passes the manifest here to avoid
#: resolving (and rasterizing SVGs) twice.
_REFERENCES_UNRESOLVED = object()


def run_agent_turn_preview(
    payload: AgentTurnPreviewRequest,
    root: Path,
    event_sink=None,
    resolved_reference_assets=_REFERENCES_UNRESOLVED,
) -> JsonObject:
    ensure_agent_runtime_path(root)
    try:
        from lumen_agent.config import AgentRuntimeConfig
        from lumen_agent.harness import run_deepagent_turn
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.unavailable",
            "Agent runtime dependencies are not available to the API process.",
            str(error),
        )

    # RC: resolve the turn's reference attachments into a by-value manifest
    # BEFORE the main try/except. A bad attachment (unknown id, >4, broken
    # preview) is explicit user intent (D2) and must surface as a real 422 to
    # the client, never be folded into an agent_runtime.failed response — so
    # the resolver's HTTPExceptions propagate past this function. The async
    # /agent/turns route resolves in its HANDLER (before the run row exists —
    # a worker-thread 422 would be swallowed by its catch-all; adversarial-gate
    # ship-blocker 1) and hands the manifest in via resolved_reference_assets.
    if resolved_reference_assets is _REFERENCES_UNRESOLVED:
        reference_assets = resolve_agent_turn_references(payload)
    else:
        reference_assets = resolved_reference_assets

    try:
        config = AgentRuntimeConfig.from_env(root)
        if payload.max_iterations is not None:
            # v0 harness does not consume max_iterations (no Python-loop cap);
            # kept set for config parity + offline/CLI paths that still read it.
            config = replace(config, max_iterations=payload.max_iterations)
        if payload.model:
            config = replace(config, model=payload.model)
        if config.asset_store_root is None:
            # A seeded scene references assets ingested through the API's store;
            # the agent must export from the same root or seeded imagery fails
            # with LUME0210 (asset bytes missing). LUMEN_AGENT_ASSET_STORE still
            # overrides explicitly.
            config = replace(config, asset_store_root=api_asset_store_root())
        brand_kit, brand_kit_source, brand_kit_assets, brand_fonts = (
            resolve_agent_turn_brand_kit(payload)
        )
        if brand_kit is not None:
            # K0 (kit application): the document's attached kit rides the run
            # config BY VALUE so the runtime preflights against it instead of
            # the platform default — without this, an attached scene ref vs the
            # default kit trips LUMB0101 and token resolution short-circuits.
            # K2: the kit-asset manifest rides along so use_brand_asset can
            # place the kit's logos/images. K3: the font spec rides along so
            # preflight measurement and previews shape in the kit's faces.
            config = replace(
                config,
                brand_kit=brand_kit,
                brand_kit_source=brand_kit_source,
                brand_kit_assets=brand_kit_assets,
                brand_fonts=brand_fonts,
            )
        turn_targets = editor_target_node_ids(payload)
        if turn_targets:
            # Slice 2.5: the chipped edit targets ride the run BY VALUE so the
            # loop's edit-scoped acceptance can (a) treat blocking critique on
            # a requested node as always in scope and (b) withhold the shortcut
            # when the applied ops touched none of the targets. Prompt-only
            # delivery measured unenforceable (moda probe P1r2/P5r2).
            config = replace(config, turn_target_node_ids=turn_targets)
        if reference_assets:
            # RC (reference-conditioned design): the user-attached references
            # ride the run BY VALUE so all three minds can view("reference:<n>")
            # them (same rule as brand_kit_assets — the runtime never reads the
            # API database). The store root is pinned to the API's store so the
            # runtime resolves the (possibly SVG-rasterized) preview bytes.
            # DELIBERATE exception (channel refuter, minor 2): this overrides an
            # explicit LUMEN_AGENT_ASSET_STORE for reference turns — the resolver
            # wrote the previews into the API store, so pointing anywhere else
            # would blind view("reference:<n>"). Normal deployments share one
            # store; a split-store operator loses the env override only on turns
            # that attach references.
            config = replace(
                config,
                reference_assets=reference_assets,
                asset_store_root=api_asset_store_root(),
            )
        # Slice 2 D4: the loop is mandatory-multimodal (Director + reviewer attach
        # images every turn). Fail LOUDLY here, before the run authors, if the
        # configured model is text-only — otherwise the run dies mid-turn at the
        # reviewer with `404 No endpoints found that support image input`, wasting the
        # paid authoring call. Raised ValueError falls through this block's try/except
        # to a clean agent_runtime.failed response. Unknown/network errors never raise.
        from lumen_agent.llm import assert_model_supports_image_input

        assert_model_supports_image_input(
            config.model,
            base_url=config.agent_base_url,
            api_key=config.agent_api_key,
        )
        prompt = editor_agent_prompt(payload)
        # One-round-per-turn: if the previous turn asked the user to clarify, the
        # harness withholds request_clarification so this turn designs from the
        # answer instead of asking again (structural, not a prompt nudge).
        clarification_already_requested = (
            payload.previous_turn_outcome == "clarification_requested"
        )
        payload_result, tools = run_deepagent_turn(
            prompt,
            config,
            initial_scene=agent_seed_scene(payload),
            event_sink=event_sink,
            clarification_already_requested=clarification_already_requested,
        )
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.failed",
            "Agent runtime failed before returning a proposal.",
            str(error),
        )

    return agent_response_from_trace(payload_result, tools.trace_dir, tools.scene)


def sse_frame(seq: int, event: str, data: Any) -> str:
    """One Server-Sent Events frame. `id:` carries the monotonic run-event
    seq so the browser's EventSource replays from it via Last-Event-ID."""
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data)}\n\n"


def ensure_agent_runtime_path(root: Path) -> None:
    agent_runtime_path = str(root / "apps" / "agent_runtime")
    api_path = str(root / "apps" / "api")
    for path in [agent_runtime_path, api_path, str(root)]:
        if path not in sys.path:
            sys.path.insert(0, path)


def api_asset_store_root() -> Path:
    """The API's asset store root, resolved exactly as create_app resolves it."""
    return settings.effective_asset_store_root


def resolve_agent_turn_brand_kit(
    payload: AgentTurnPreviewRequest,
) -> Tuple[
    Optional[JsonObject], Optional[str], Optional[JsonObject], Optional[JsonObject]
]:
    """The Brand Kit attached to the turn's document, loaded from the kit
    library so it can be passed BY VALUE into the runtime config (the runtime
    never reads the API database) — plus (K2) the kit-ASSET MANIFEST: the
    library asset records + usage guidance for the kit's logo variants and
    brand images, so `use_brand_asset` can register them into the scene —
    plus (K3) the kit FONT SPEC ({store_root, digests}) so the runtime's
    preflights and previews shape text in the kit's real font faces.

    Resolution failures never fail the turn: no scene ref, an unknown kit id,
    or an unreadable database all return (None, None, None, None) and the
    runtime falls back to the platform default kit — exactly the pre-K0
    behavior. A kit WITHOUT placeable assets (e.g. styles-compiled) gets an
    empty manifest, not an error; a kit without stored font faces gets a None
    font spec (bundled fallback, exactly as before)."""
    scene = payload.scene if isinstance(payload.scene, dict) else None
    meta = scene.get("meta") if scene else None
    ref = meta.get("brand_kit") if isinstance(meta, dict) else None
    if not isinstance(ref, dict) or not ref.get("id"):
        return None, None, None, None
    database_path = settings.lumen_api_database_path
    try:
        connection = connect(database_path)
    except Exception:
        return None, None, None, None
    try:
        repo = Repository(connection)
        record = repo.require_brand_kit(str(ref["id"]), ref.get("version"))
        brand_kit = record["brand_kit"]
        manifest = brand_kit_asset_manifest(repo, connection, brand_kit)
        font_spec = brand_kit_font_spec(repo, brand_kit, str(api_asset_store_root()))
        return brand_kit, "document", manifest, font_spec
    except Exception:
        return None, None, None, None
    finally:
        connection.close()


def brand_kit_asset_manifest(
    repo: Repository, connection, brand_kit: JsonObject
) -> JsonObject:
    """K2: {asset_id: {record, title, description, usage}} for the kit's logo
    variants and brand images. Records come back VERBATIM from the library
    (they were engine-built at ingestion) — the runtime rewrites only the
    scene copy's provenance. Missing records are skipped silently: a kit may
    reference assets whose bytes/rows never landed, and a partial manifest
    beats a failed turn."""
    assets = brand_kit.get("assets") or {}
    asset_ids: list[str] = []
    for logo in (assets.get("logos") or {}).values():
        if not isinstance(logo, dict):
            continue
        for variant in logo.get("variants") or []:
            if isinstance(variant, dict) and variant.get("asset_id"):
                asset_ids.append(str(variant["asset_id"]))
    for image in (assets.get("images") or {}).values():
        if isinstance(image, dict) and image.get("asset_id"):
            asset_ids.append(str(image["asset_id"]))

    manifest: JsonObject = {}
    if not asset_ids:
        return manifest

    try:
        from lumen_ingestion.describe import DescriptionStore

        descriptions = DescriptionStore(connection).get_many(asset_ids)
    except Exception:
        descriptions = {}

    for asset_id in dict.fromkeys(asset_ids):
        try:
            record = repo.require_asset_record(asset_id)
        except Exception:
            continue
        entry: JsonObject = {"record": record.get("asset") or record}
        described = descriptions.get(asset_id) or {}
        for field in ("title", "description", "usage"):
            if described.get(field):
                entry[field] = described[field]
        manifest[asset_id] = entry
    return manifest


# RC (reference-conditioned design) resolve constants.
REFERENCE_ASSETS_MAX = 4  # mirrors PLACED_PREVIEWS_MAX; more dilutes vision context (D1)


def _dedupe_and_cap_reference_ids(raw: Optional[List[str]]) -> List[str]:
    """De-dupe reference ids preserving first-occurrence order (the attachment
    order the user sees in the composer), drop empties, and enforce the per-turn
    cap with the RC 422. Shared by the agent-turn resolver and the
    /assets/generate route so both reject the same bad attachments identically."""
    asset_ids: List[str] = []
    seen: set[str] = set()
    for asset_id in raw or []:
        if asset_id and asset_id not in seen:
            seen.add(asset_id)
            asset_ids.append(asset_id)
    if len(asset_ids) > REFERENCE_ASSETS_MAX:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reference.too_many",
                "message": (
                    f"a turn accepts at most {REFERENCE_ASSETS_MAX} reference "
                    f"attachments, got {len(asset_ids)}"
                ),
                "diagnostics": [],
            },
        )
    return asset_ids


def resolve_reference_images_for_generate(
    repo: Repository, asset_ids: List[str], store_root: str
) -> Tuple[List[Tuple[bytes, str]], List[str]]:
    """RC (D-RC2.5): resolve already-deduped+capped reference ids into order-
    sorted (bytes, mime) reference images + their preview digests, via the SAME
    RC manifest machinery the agent turn uses — same hard 422s (unknown id /
    broken preview) and the same SVG rasterize. The manifest guarantees each
    preview blob exists (it 422s otherwise), so the bytes read is safe."""
    manifest = reference_asset_manifest(repo, repo.connection, asset_ids, store_root)
    images: List[Tuple[bytes, str]] = []
    digests: List[str] = []
    for entry in sorted(manifest.values(), key=lambda e: e.get("order", 0)):
        digest = entry["preview_digest"]
        blob = Path(store_root) / "sha256" / digest[:2] / digest
        images.append((blob.read_bytes(), entry.get("mime_type") or "image/png"))
        digests.append(digest)
    return images, digests


def resolve_agent_turn_references(
    payload: AgentTurnPreviewRequest,
) -> Optional[JsonObject]:
    """RC (D2): the user-attached references for THIS turn, resolved from the
    asset library into a by-value manifest so the runtime never reads the API
    database. Empty ids → None (the turn is byte-identical to today). Unlike the
    brand-kit manifest, a bad attachment is EXPLICIT user intent and fails
    LOUDLY with a 422 (unknown id / too many / broken preview) rather than a
    silent skip — a reference the user picked but the loop never saw is a worse
    failure than a rejected request."""
    asset_ids = _dedupe_and_cap_reference_ids(payload.reference_asset_ids)
    if not asset_ids:
        return None
    store_root = str(api_asset_store_root())
    connection = connect(settings.lumen_api_database_path)
    try:
        repo = Repository(connection)
        return reference_asset_manifest(repo, connection, asset_ids, store_root)
    finally:
        connection.close()


def reference_asset_manifest(
    repo: Repository,
    connection,
    asset_ids: List[str],
    store_root: str,
) -> JsonObject:
    """RC (D2): {asset_id: {record, preview_digest, mime_type, width, height,
    dominant_colors, title, description, order}} — EXACTLY the config.py
    reference_assets contract. Records come back VERBATIM from the library. A
    missing id is a hard 422 (never a silent skip — references are explicit
    user intent). SVG references are engine-rasterized to a 512px PNG written
    into the shared content-addressed store AT RESOLVE TIME, so the runtime
    only ever handles raster previews; a rasterize failure is a 422 (LUMI0804-
    class spirit — a broken preview on an explicit attachment fails the
    request, never degrades). dominant_colors/title/description are advisory."""
    import hashlib
    import io

    from PIL import Image

    from lumen_ingestion.capture.uploads import _dominant_colors
    from lumen_ingestion.pipeline import make_rasterize_svg

    try:
        descriptions = DescriptionStore(connection).get_many(asset_ids)
    except Exception:
        descriptions = {}

    rasterize_svg = make_rasterize_svg(repo, store_root)
    manifest: JsonObject = {}
    for order, asset_id in enumerate(asset_ids):
        try:
            stored = repo.require_asset_record(asset_id)
        except Exception:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "reference.asset_not_found",
                    "message": f"reference asset {asset_id} is not in the library",
                    "diagnostics": [],
                },
            )
        record = stored.get("asset") or stored
        media = record.get("media") or {}
        mime_type = media.get("mime_type")
        is_svg = mime_type == "image/svg+xml" or record.get("kind") == "vector"

        if is_svg:
            png_bytes = rasterize_svg(asset_id)
            if not png_bytes:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "reference.preview_unavailable",
                        "message": (
                            f"reference asset {asset_id} could not be rasterized to a preview"
                        ),
                        "diagnostics": [],
                    },
                )
            preview_bytes = png_bytes
            preview_digest = hashlib.sha256(png_bytes).hexdigest()
            blob_path = (
                Path(store_root) / "sha256" / preview_digest[:2] / preview_digest
            )
            if not blob_path.is_file():
                # Atomic write (review fix): a content-addressed blob must never
                # be observable half-written — a crash mid-write would park
                # corrupt bytes at a valid digest path forever. Write a tmp
                # sibling and rename into place (os.replace is atomic on POSIX).
                blob_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = blob_path.with_name(f".{preview_digest}.tmp-{os.getpid()}")
                tmp_path.write_bytes(png_bytes)
                os.replace(tmp_path, blob_path)
        else:
            digest = (media.get("digest") or {}).get("value")
            if not digest:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "reference.preview_unavailable",
                        "message": (
                            f"reference asset {asset_id} has no stored raster digest"
                        ),
                        "diagnostics": [],
                    },
                )
            preview_digest = str(digest)
            blob_path = Path(store_root) / "sha256" / preview_digest[:2] / preview_digest
            # Review fix (channel refuter, minor 1): a raster reference whose
            # store blob is gone fails HERE like the SVG branch does — D2 says
            # boundary 422, never a silent mid-run degrade to a pixel-less view.
            if not blob_path.is_file():
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "reference.preview_unavailable",
                        "message": (
                            f"reference asset {asset_id} bytes are missing from "
                            "the asset store"
                        ),
                        "diagnostics": [],
                    },
                )
            preview_bytes = blob_path.read_bytes()

        # dominant_colors is advisory: an empty list on any failure never blocks.
        dominant_colors: List[str] = []
        if preview_bytes:
            try:
                image = Image.open(io.BytesIO(preview_bytes)).convert("RGBA")
                dominant_colors = _dominant_colors(image)
            except Exception:
                dominant_colors = []

        width, height = _reference_dimensions(record)
        entry: JsonObject = {
            "record": record,
            "preview_digest": preview_digest,
            "mime_type": "image/png" if is_svg else mime_type,
            "width": width,
            "height": height,
            "dominant_colors": dominant_colors,
            "title": None,
            "description": None,
            "order": order,
        }
        described = descriptions.get(asset_id) or {}
        for field in ("title", "description"):
            if described.get(field):
                entry[field] = described[field]
        manifest[asset_id] = entry
    return manifest


def _reference_dimensions(record: JsonObject) -> Tuple[Optional[int], Optional[int]]:
    """Pixel dimensions from a library asset record's kind-specific metadata,
    where present — raster/logo carry pixel_width/pixel_height, vectors carry
    float width/height. None when the record declares no intrinsic size."""
    for key in ("raster", "logo"):
        meta = record.get(key)
        if isinstance(meta, dict):
            width = meta.get("pixel_width")
            height = meta.get("pixel_height")
            if width is not None and height is not None:
                return int(width), int(height)
    vector = record.get("vector")
    if isinstance(vector, dict):
        width = vector.get("width")
        height = vector.get("height")
        if width is not None and height is not None:
            return int(width), int(height)
    return None, None


def scene_brand_fonts(
    repo: Repository, scene: Optional[JsonObject], store_root: str
) -> Optional[JsonObject]:
    """K3 for stateless/scene-only paths: resolve the scene's own brand-kit
    reference (`meta.brand_kit`) to its font spec so shaping uses the kit's
    real faces. A scene without a resolvable kit reference shapes with the
    library + bundled set (the helper still reports substituted families via
    LUMS0100)."""
    if not isinstance(scene, dict):
        return None
    scene_brand_ref = (scene.get("meta") or {}).get("brand_kit")
    if not (isinstance(scene_brand_ref, dict) and scene_brand_ref.get("id")):
        return None
    try:
        referenced = repo.require_brand_kit(
            str(scene_brand_ref["id"]), scene_brand_ref.get("version")
        )["brand_kit"]
    except NotFoundError:
        return None
    return brand_kit_font_spec(repo, referenced, store_root)


def brand_kit_font_spec(
    repo: Repository, brand_kit: Optional[JsonObject], store_root: str
) -> Optional[JsonObject]:
    """K3: {store_root, faces: [{digest, family}]} for the kit's font faces,
    resolved from the asset library. The helper reads the bytes from the
    shared store and registers each face under BOTH its intrinsic name and
    the kit-DECLARED family — scenes request the declared name, which is
    routinely a `@font-face` alias over the bytes' intrinsic name (kit
    "Aeonik" over trial bytes named "Aeonik TRIAL"). Missing records are
    skipped — a partial font set beats a failed request, and the helper
    reports any face it cannot load (LUMS0101)."""
    if not isinstance(brand_kit, dict):
        return None
    fonts = (brand_kit.get("assets") or {}).get("fonts") or {}
    faces: list[JsonObject] = []
    seen: set[str] = set()
    for font in fonts.values():
        if not isinstance(font, dict):
            continue
        family = font.get("family") if isinstance(font.get("family"), str) else None
        for face in font.get("faces") or []:
            if not (isinstance(face, dict) and face.get("asset_id")):
                continue
            try:
                record = repo.require_asset_record(str(face["asset_id"]))
            except Exception:
                continue
            asset = record.get("asset") or record
            digest = (asset.get("media") or {}).get("digest") or {}
            if (
                str(digest.get("algorithm") or "").lower() == "sha256"
                and digest.get("value")
                and str(digest["value"]) not in seen
            ):
                seen.add(str(digest["value"]))
                faces.append({"digest": str(digest["value"]), "family": family})
    if not faces:
        return None
    return {"store_root": store_root, "faces": faces}


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
    # Honest turn outcome #3: the orchestrator asked the user to clarify the
    # brief before authoring. No operations, no artifacts — the envelope carries
    # the questions; the editor chat renders them (as text pre-R2, chips after).
    if result.get("outcome") == "clarification_requested":
        clarification = result.get("clarification")
        if not isinstance(clarification, dict):
            clarification = {"questions": []}
        return {
            "schema_version": 1,
            "status": "clarification_requested",
            "summary": result.get("summary")
            or "The agent needs a few decisions before it designs this.",
            "run_id": result.get("run_id"),
            "trace_dir": str(trace_dir),
            "preview_paths": [],
            "dsl_blocks": [],
            "operations": [],
            "draft_scene": None,
            "acceptance_scope": None,
            "stop_reason": "clarification_requested",
            "clarification": clarification,
            "diagnostics": [],
            "artifacts": [],
        }

    operations: List[JsonObject] = []
    dsl_blocks: List[str] = []
    diagnostics: List[JsonObject] = []
    # Phase 0b: the loop's keep-best snapshot can return an EARLIER iteration's
    # scene as the draft. Operations from later iterations are then not part of
    # that draft and must not be replayed by the editor.
    ops_valid_through = result.get("ops_valid_through_iteration")
    # K2 accept-seam: the runtime's operations ledger is THE op source of
    # truth — it carries every applied mutation (compile ops AND asset-tool
    # ops: upserts, placements, edits) in order, so nothing the runtime did
    # can vanish at accept. The legacy compile.json scrape below remains
    # only as the fallback for pre-ledger traces (it misses asset ops).
    ledger_path = trace_dir / "operations_ledger.json"
    ledger_operations: Optional[List[JsonObject]] = None
    if ledger_path.exists():
        try:
            entries = json.loads(ledger_path.read_text(encoding="utf-8")).get(
                "entries", []
            )
            ledger_operations = [
                entry["operation"]
                for entry in entries
                if isinstance(entry, dict)
                and "operation" in entry
                and (
                    not isinstance(ops_valid_through, int)
                    or int(entry.get("iteration") or 0) <= ops_valid_through
                )
            ]
        except (json.JSONDecodeError, TypeError, ValueError):
            ledger_operations = None
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
                if (
                    ledger_operations is None
                    and compile_summary.get("status") == "ok"
                    and iteration_in_ops_window(iteration_dir.name, ops_valid_through)
                ):
                    operations.extend(compile_payload.get("operations", []))
    if ledger_operations is not None:
        operations = ledger_operations

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
