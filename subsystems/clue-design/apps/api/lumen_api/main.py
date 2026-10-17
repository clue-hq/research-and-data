from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import inspect
import io
import json
import logging
import os
import re

# D2.5B: SQLite is DELETED from this API. `sqlite3` survives here only as the API's
# constraint-violation EXCEPTION TYPE — `design_store.DesignStoreBridge` translates Postgres
# IntegrityError/DataError into `sqlite3.IntegrityError` so the 409 DTOs below are unchanged.
# See the import comment in design_store.py. Renaming it to a design-native error is a
# follow-up, not part of the deletion slice.
import sqlite3
import time
import zipfile
import contextlib
from collections.abc import Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    Response,
    StreamingResponse,
)

from . import (
    ad_runtime,
    document_thumbnails,
    image_cache,
    image_provider,
    logo_search,
    web_export,
    web_pdf,
)
from .asset_custody import (
    ensure_materialized,
    materialize_scene_assets,
    read_asset_bytes,
    record_digests,
    register_engine_write,
    register_scene_asset_backstop,
    register_web_asset_backstop,
    write_cache_blob,
)
from .core import CoreClient, CoreError, has_error_diagnostics
from .custom_component_compiler import (
    DEFAULT_COMPILER_TIMEOUT_SECONDS,
    compile_custom_component,
    default_compiler_worker_path,
)
from .export_policy import (
    draft_verification_note,
    export_warning_views,
    has_blocking_export_diagnostics,
    partition_export_diagnostics,
)
from .agent_account_logos import DurableAgentAccountLogoBinder
from .agent_logo_family_cache import DurableLogoFamilyCache
from .agent_cloned_sections import DurableAgentClonedSectionRegistry
from .agent_custom_components import DurableAgentCustomComponentRegistry
from .custom_component_runtime import (
    build_custom_component_runtime_frames,
    default_runtime_host_path,
    web_doc_uses_custom_components,
)
from .fragments.paths import resolve_structural_path
from .fragments.render import (
    build_fragment_render_package,
    build_fragment_render_package_for_document,
    empty_fragment_render_package,
    fragment_collision_diagnostics,
    fragment_css_sheet,
    fragment_render_map,
    web_doc_all_fragment_ids,
    web_doc_fragment_ids,
)
from .fragments import (
    ISOLATION_PREVIEW_MEDIA_TYPE,
    IsolationRenderFailed,
    attach_web_fragment_preview,
    read_web_fragment,
    render_isolation_preview,
    screenshot_isolation_page,
    set_web_fragment_status,
)
from .fragment_inspector import (
    FRAGMENT_CARD_SCHEMA_VERSION,
    activation_target,
    dormant_fragment_cards,
    fragment_card,
    retirement_verdict,
)
from .custom_components import (
    CUSTOM_COMPONENT_MEMBER_MEDIA_TYPES,
    resolve_custom_component_artifact_blob,
    resolve_custom_component_source_snapshot,
)
from .database import (
    CustomComponentArtifactConflict,
    CustomComponentReferenceError,
    CustomComponentSourceVersionConflict,
    DesignResourceVersionConflict,
    FragmentReferenceError,
    NotFoundError,
    WebDocumentVersionConflict,
    WebPublishRevisionConflict,
    fragment_references,
    utc_now,
)
from . import run_stream
from .spend import drain_safely as _drain_spend
from .design_store import (
    DesignBlobStore,
    HybridRepository,
    api_engine_cache_root,
    read_public_design_blob,
    resolve_workspace_id,
)
from .font_library import manifest as font_library_manifest
from .font_library import shared_library_font_bytes
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
from .public_pages import (
    custom_public_origin,
    custom_site_address,
    site_address,
    system_public_origin,
)
from .web_bridge import render_bridge_script
from .models import (
    AgentTurnPreviewRequest,
    WebTurnRequest,
    WebOperationsRequest,
    WebPublishRequest,
    RenameDocumentRequest,
    SetAgentInstructionsRequest,
    SetDocumentArchivedRequest,
    SetLayoutManagedEditingRequest,
    SetWebNoindexRequest,
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
    CreateWebAccountRequest,
    CompileCustomComponentRequest,
    PutCustomComponentSourceRequest,
    UpdateWebAccountRequest,
    SaveWebTemplateRequest,
    DeriveWebRequest,
    WebBatchRequest,
    DeriveInstanceRequest,
    InstancePreviewRequest,
    ExportDocumentRequest,
    ExportPreviewRequest,
    FinalizeTemplateRequest,
    GenerateAssetRequest,
    GenerateQrRequest,
    GenerateBrandKitRequest,
    LogoSaveRequest,
    LogoSearchRequest,
    IngestWebsiteRequest,
    OnboardAdAssetsRequest,
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
from lumen_ingestion.jobs import new_id as ingestion_new_id
from lumen_ingestion.logo_policy import extend_allowed_backgrounds
from lumen_ingestion.ad_library.onboarding import run_ad_assets_onboarding
from lumen_ingestion.pipeline import (
    run_asset_ingestion,
    run_pdf_ingestion,
    run_website_ingestion,
)
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider

from clue_config import Secrets, load_settings
from clue_db import db_lifespan, get_engine
from clue_obs.production import (
    install_production_langfuse,
    install_production_sentry,
    install_production_tracing,
    production_tracing_lifespan,
)
from clue_design import storage as design_storage
from clue_design.envelopes import DesignIngestionEnvelope, DesignTurnEnvelope
from clue_design.enums import DesignIngestionKind
from clue_design.errors import DesignFragmentActivationError, DesignFragmentPreviewError
from clue_design.leg_context import render_leg_turn_prompt
from clue_design.runs import work_id_for_run as design_work_id_for_run
from clue_design.sessions import design_session_id, render_document_drift_note
from clue_design.storage import location_digest
from clue_storage import StorageBackend, storage_from_settings

from py_lumen_config import settings
from py_lumen_obs import bind_request_id, configure, get_logger, unbind_context

from clue_execution import OperationConflict
from clue_toolbelt import IdempotencyConflict, PreconditionFailed
from pydantic import ValidationError

from .toolbelt.wiring import DesignRunSubject, DesignToolInvocations, design_tool_host
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

# The run-event SSE cadence constants moved to ``lumen_api.run_stream`` at D7, with the rest of the
# stream: it is one seam now (emit, auth, replay, frame), and a cadence knob two modules away from
# the loop it paces is how the two drift.


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


def conflicted_agent_turn_response(
    base_version: int, current_version: int
) -> JsonObject:
    """Terminal result for a LEG scene turn that lost its version race (genad Task 5).

    The scene twin of ``conflicted_web_turn_response``, and it exists for the same reason: once
    the executor owns the persist, "the document moved under me" is a real terminal outcome that
    is neither a success nor a runtime failure, and the human needs to be told which two versions
    disagreed. Direct editor turns never reach it — they propose, and the editor's own route
    commits under its own CAS.

    The two versions are named in the PROSE (``summary`` AND ``stop_reason``), not only in the
    structured keys — but be honest about who reads that prose TODAY: nobody. The builder is
    leg-only, so the editor's own panel never sees it, and on the platform side a conflicted
    turn comes back with run status ``failed``, which ``design_leg_wiring`` short-circuits into
    ``_fail_turn`` — a typed unfinalized turn with NO assistant message, so the scene branch of
    ``_assistant_summary`` (the only ``stop_reason`` reader) never runs on it. The prose is
    therefore durable RESULT-PAYLOAD content: it makes the run row self-explanatory to an
    operator reading it, and it is ready for the first surface that renders it.

    That surface arrives with the **genad founder item: conflict routing** — whether a
    CAS-conflicted turn stays a typed failed turn (today's ratified honest-terminal shape, web
    parity) or is rewired to land back in the thread with a message. Until that is decided, a
    marketer who loses the race sees a failed turn with no inline prose. Whichever way it goes,
    the sentence must keep naming BOTH versions and saying their own edit survived — a bare
    "Design turn conflicted." is technically true and practically useless."""

    message = (
        f"This design moved from version {base_version} to version {current_version} while "
        "the AI turn was running, so the turn's changes were not applied. Your newer edits "
        "were preserved — send the instruction again to design against the current version."
    )
    return {
        **failed_agent_turn_response(
            "agent_turn.version_conflict",
            message,
            (
                f"The turn started at version {base_version}; the stored "
                f"document is now version {current_version}."
            ),
        ),
        "status": "conflicted",
        # The platform's scene summarizer reads ONLY this key for its sentence; the scene result
        # shape has no other prose slot it consumes.
        "stop_reason": message,
        "base_version": base_version,
        "current_version": current_version,
    }


# The engine's own verdict on a scene with no page/artboard ("document must contain at least one
# page/artboard", `validate_scene`). A turn whose applied result is page-less trips it during the
# replay, so the engine refuses the operations before the gate below ever sees a scene — the code
# is matched to name that refusal for what it is rather than as "could not be replayed".
PAGELESS_SCENE_DIAGNOSTIC = "LUMV0100"


def is_pageless_scene_refusal(diagnostics: List[JsonObject]) -> bool:
    """Is this ``CoreError``'s diagnostic list the engine's page-less verdict?

    ``CoreError.diagnostics`` is normalized to a list by its constructor (``core.py``:
    ``diagnostics or []``), so the list-ness is a type, not a thing to re-check — the per-item
    ``isinstance`` stays because the ITEMS are engine JSON this process did not build.
    """

    return any(
        isinstance(diagnostic, dict)
        and diagnostic.get("code") == PAGELESS_SCENE_DIAGNOSTIC
        for diagnostic in diagnostics
    )


def pageless_agent_turn_response(engine_message: str | None = None) -> JsonObject:
    """Terminal result for a LEG scene turn that produced no page (genad2 Task 3).

    Since the zero-page birth (genad2 ruling 1) a chat-born scene document starts with NO pages
    — `open_design_leg@4` mints none, and the design trio authors the page itself. That makes a
    turn which generated nothing look exactly like a turn which generated a design at this seam:
    the document is still page-less either way, and a "proposed" result would tell a marketer
    their ad is ready while the gallery has nothing to open. A page-less result is therefore a
    terminal FAILURE with nothing written, in the same shape as the replay refusal beside it.

    The sentence rides BOTH prose slots for the reason ``conflicted_agent_turn_response`` spells
    out: the platform's scene summarizer (``_assistant_summary``, design_leg_wiring) reads only
    ``stop_reason``, and ``failed_agent_turn_response`` leaves it None, so a refusal built naively
    from it is contentless by construction. Be honest about who reads it TODAY: a failed run is
    short-circuited by ``_fail_turn`` before that summarizer runs, so this is durable
    result-payload prose — legible to an operator reading the run row, and ready for whichever
    surface the genad founder item on failure/conflict routing hands it to.

    ``engine_message`` is the engine's OWN text, passed through on the arm where the ENGINE is
    the one that refused (its ``LUMV0100`` validation of the applied scene). Its replay-failure
    sibling has always forwarded ``error.message`` and this arm dropped it, so an operator
    reading the run row could not tell the engine's verdict from this function's generic
    sentence. Today that text is terse ("operation batch produced an invalid scene") — the
    value is that it is the ENGINE speaking, and it improves for free when the engine's wording
    does. It rides the DETAIL, never the summary: the marketer-facing prose is founder copy and
    stays one fixed sentence. Absent on the post-replay gate below, where no engine complained
    and quoting one would be an invention.
    """

    message = (
        "Design finished without creating a page — nothing was saved; "
        "send another message to try again."
    )
    detail = (
        "The turn's result contains no page, so there would be nothing to show; "
        "the design was not saved and the document is unchanged."
    )
    if engine_message:
        detail = f"{detail} The engine reported: {engine_message}"
    return {
        **failed_agent_turn_response(
            "agent_turn.pageless_result",
            message,
            detail,
        ),
        "stop_reason": message,
    }


def with_web_turn_failure_diagnostic(response: JsonObject) -> JsonObject:
    """Guarantee a non-applied website turn carries its reason as a real diagnostic.

    The web twin of the scene path's ``agent_runtime.no_proposal`` synthesis (see
    ``run_agent_turn_preview``): a turn that dies inside the runtime — the reviewer's
    vision call refused, a recursion limit, an orchestrator crash — comes back with the
    reason only in ``summary`` and an EMPTY ``diagnostics``, so every surface that reads
    diagnostics (the editor's panel, the platform's leg projections) reports an
    unexplained failure. Observed live: OpenRouter's "image dimensions exceed max
    allowed size: 8000 pixels" refusal discarded 84 authored nodes with nothing in
    ``diagnostics`` to say why.

    Never overwrites diagnostics that already exist (``failed_agent_turn_response`` and
    ``conflicted_web_turn_response`` author their own) and never invents a message: the
    text IS the runtime's own summary.
    """
    if response.get("status") == "applied":
        return response
    existing = response.get("diagnostics")
    if isinstance(existing, list) and existing:
        return response
    summary = response.get("summary")
    message = (
        str(summary).strip()
        if isinstance(summary, str) and summary.strip()
        else "The website turn ended without applying any change, and gave no reason."
    )
    outcome = response.get("outcome")
    return {
        **response,
        "diagnostics": [
            agent_diagnostic(
                "web_turn.no_result",
                message,
                "validation",
                "error",
                f"The runtime reported outcome {outcome!r}." if outcome else None,
            )
        ],
    }


def conflicted_web_turn_response(
    base_version: int, current_version: int
) -> JsonObject:
    """Terminal result for an async website turn that lost its version race."""
    message = (
        "This website changed while the AI turn was running. Your newer edits "
        "were preserved; run the instruction again from the current version."
    )
    return {
        "schema_version": 1,
        "status": "conflicted",
        "outcome": "conflicted",
        "summary": message,
        "base_version": base_version,
        "current_version": current_version,
        "operations": [],
        "preview_paths": [],
        "diagnostics": [
            agent_diagnostic(
                "web_turn.version_conflict",
                message,
                "validation",
                "error",
                (
                    f"The turn started at version {base_version}; the stored "
                    f"document is now version {current_version}."
                ),
            )
        ],
    }


# D5 Round B: the startup orphan sweep (``_fail_orphaned_runs``) is DELETED with the daemon
# threads it existed for. Turns ran inside this process, so a restart silently killed every
# in-flight one and left its row ``running`` forever; the sweep failed them at boot so the
# editor's SSE stream would settle instead of hanging. Leased fleet work needs none of it: a dead
# worker's lease expires, and a takeover worker re-claims the SAME run through the D5 CAS and
# runs it. Keeping the sweep would now actively destroy recoverable work at every deploy.


def _build_embedded_fleet_worker(app: FastAPI) -> Any:
    """The design API's own :class:`~clue_fleet.work_worker.LeasedWorkWorker`, or ``None``.

    Registers ONLY the design handler — the API drains design work and nothing else; project
    runs and recipe executions remain the platform worker's business. The handler reads its host
    capabilities from ``app.state`` at execution time (not construction time), so a test that
    installs an ``agent_turn_runner`` stub after the app is built is still honoured.

    Returns ``None`` when the switch is off, or when the fleet/handler imports are unavailable —
    the same degradation contract the agent runtime itself has: a machine missing the extras gets
    an API that serves everything except turns, never an import crash at startup.

    **OPERATIONAL HAZARD — an embedded worker drains the WHOLE queue, not its own app's work
    (diagnosed live 2026-08-19/20).** The queue is a shared Postgres table, and the worker leases
    by work KIND, not by which process offered the job. So every design API pointed at one
    database competes for the same design jobs, and the winner is whoever polls first (0.1s). A
    developer machine that still has a hours-old design API running on another port therefore
    executes today's jobs against yesterday's code — and because ingestion imports its capture
    tiers lazily, that stale process happily served static ingests while failing every rendered
    one at the import edge (`ImportError: cannot import name 'GeometryEvidence' from
    'lumen_ingestion.evidence'`), from a process nobody was looking at. There is no code fence
    for this today: before verifying anything through the UI, check that exactly ONE design API
    with `LUMEN_EMBEDDED_FLEET_WORKER=1` is running against your database. A real fence (the
    lease carrying the worker's code identity) belongs to the fleet, not here.
    """
    if not settings.lumen_embedded_fleet_worker:
        return None
    try:
        from clue_fleet.work_worker import LeasedWorkWorker

        from .fleet_handler import DesignTurnHost, build_design_job_handler
    except Exception:
        log_event(
            api_logger,
            logging.WARNING,
            "embedded_fleet_worker_unavailable",
            detail="design fleet dependencies are not importable; turns will not be drained",
        )
        return None

    def host() -> Any:
        return DesignTurnHost(
            agent_turn_runner=app.state.agent_turn_runner,
            web_turn_runner=app.state.web_turn_runner,
            core=app.state.core,
            compiler_node_bin=app.state.custom_component_compiler_node_bin,
            compiler_worker=app.state.custom_component_compiler_worker,
            compiler_timeout_seconds=(
                app.state.custom_component_compiler_timeout_seconds
            ),
            storage=app.state.storage,
            # D5 Round C: the app's engine-cache tree, so worker-path materialization mirrors
            # into the SAME place the request paths read (a suite that builds the app with an
            # explicit root would otherwise have its worker writing into the settings default).
            engine_cache_root=app.state.engine_cache_root,
            preference_resolver_factory=getattr(app.state, "preference_resolver_factory", None),
            # Design note 2026-09-19: composed by the PLATFORM's composition root, which this
            # app is not — so the design API's own embedded worker normally has none, and its
            # leg turns simply design without the platform's reads.
            platform_reads_factory=getattr(app.state, "platform_reads_factory", None),
        )

    worker = LeasedWorkWorker(
        handlers=(build_design_job_handler(host_provider=host),),
        # Poll briskly: a human is watching an SSE stream for this turn to start, and the drain
        # is one indexed query. The lease TTL/heartbeat keep the platform defaults' 2:1 ratio.
        poll_interval=0.1,
        worker_id=f"lumen-api-embedded:{uuid4()}",
    )
    log_event(
        api_logger,
        logging.INFO,
        "embedded_fleet_worker_started",
        worker_id=worker.worker_id,
    )
    return worker


#: Ingestion kind -> the governed enqueue tool that offers it (D6 Round C). Three tools rather
#: than one kind-parameterized tool, so the journal names the gesture without an operator having
#: to decode the envelope — the same reading that kept undo and redo apart in Round B.
_INGESTION_TOOLS = {
    "website": "design_ingest_website",
    "pdf": "design_ingest_pdf",
    "asset_upload": "design_ingest_assets",
    "ad_assets": "design_ingest_ad_assets",
    "asset_enrichment": "design_enrich_assets",
}


def _ingestion_offer_payload(
    repo: HybridRepository, kind: str, request: JsonObject
) -> JsonObject:
    """Build ONE ingestion enqueue body: the ids, the durable request and the frozen envelope.

    The WRITE — the ``design_ingestion_job`` row and its ``design_job`` fleet task, in one
    transaction — is the D5 Round C shape and the exact mirror of the turn half
    (``HybridRepository.create_run_and_offer``, R-D5-B5): together or not at all, because a job
    row with no task never starts and never fails, and a task with no job row is a worker that
    claims work it cannot find. Since D6 Round C that write lives in the governed tool; what
    stays here is the payload it needs.

    Both ids are minted HERE rather than server-side inside the INSERT, because the frozen
    envelope names the job it dispatches — an id discovered only after the insert could not have
    ridden the payload it was enqueued with. The envelope carries no copy of ``request``: the
    staged inputs already live durably on the job row (``design_ingestion_job.request_json``,
    platform-storage digests since D4), and :func:`clue_design.ingestion.read_staged_request` is
    the side-effect-free read a requeued worker recovers them with. Duplicating them into the
    task payload would create a second, divergeable copy of the same truth.
    """
    job_id = ingestion_new_id("ingest")
    work_id = uuid4()
    envelope = DesignIngestionEnvelope(
        work_id=work_id,
        workspace_id=repo.workspace_id,
        kind="ingestion",
        job_id=job_id,
        ingestion_kind=DesignIngestionKind(kind),
    ).model_dump(mode="json")
    return {
        "job_id": job_id,
        "work_id": str(work_id),
        "request": request,
        "envelope": envelope,
    }


def resolve_web_page_id(web_doc: JsonObject, requested: Optional[str]) -> str:
    """The page a web read targets: the caller's page when it exists, else the first page.

    Multi-page (F5) retires the assumption that a WebDoc's page is called ``home``: a
    document's pages are an ORDERED list, so "no page named" means the first one, not a
    literal id that a real multi-page site may not even contain. A caller that DID name a
    page and got it wrong is told so — a silent fallback to page one would render the
    wrong page under the right URL.
    """
    pages = [p for p in (web_doc.get("pages") or []) if isinstance(p, dict)]
    if requested:
        if any(p.get("id") == requested for p in pages):
            return requested
        raise HTTPException(
            status_code=404,
            detail={
                "code": "web_render.page_missing",
                "message": f"page {requested!r} is not in this document",
            },
        )
    first = pages[0].get("id") if pages else None
    return first if isinstance(first, str) and first else "home"


# Asset bytes are revalidated by their content digest, never cached as immutable: re-registering
# an asset id replaces its record, so the same URL can serve new bytes. A browser re-asks after
# five minutes and a matching digest is a 304 with no storage read (brand-context fix, 2026-10-04:
# the page re-downloaded every full-size image on every load — 899 downloads in 30 minutes).
ASSET_BYTES_CACHE_CONTROL = "private, max-age=300"


def asset_cache_headers(digest: str) -> Dict[str, str]:
    return {"ETag": f'"{digest}"', "Cache-Control": ASSET_BYTES_CACHE_CONTROL}


def not_modified(request: Request, digest: str) -> bool:
    """Whether the request's If-None-Match already names this digest."""
    header = request.headers.get("if-none-match")
    if not header:
        return False
    etag = f'"{digest}"'
    return any(tag.strip() in (etag, f"W/{etag}", "*") for tag in header.split(","))


def create_app(
    engine_cache_root: Optional[Path] = None,
    *,
    storage: Optional[StorageBackend] = None,
) -> FastAPI:
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
        # D5 Round B (R-D5-B5): the embedded design fleet worker. Turns are leased fleet work
        # now, so without a drain an offered turn would sit `queued` forever. In production the
        # detached clue_api.fleet_main worker drains it; in development (and under this suite)
        # there is no second process, so the API runs the SAME handler on its own event loop.
        # One execution path, two hosts.
        #
        # Started as a lifespan task, so it exists only while the app is serving: FastAPI runs
        # lifespan only under `with TestClient(...)`, which is exactly the boundary a test wants
        # — a test that never enters the context manager gets no worker and no background DB
        # traffic. Cancelled on shutdown and awaited, so nothing outlives the app.
        worker = _build_embedded_fleet_worker(_app)
        async with contextlib.AsyncExitStack() as stack:
            # Lane 3 slice 5: OUTERMOST, so the provider is flushed and stopped only after the
            # embedded worker and the reaper are done producing spans. Entered only when THIS
            # app owns a runtime — an app built by `create_app()` directly (a test, or a host
            # embedding it) installed nothing, and `production_tracing_lifespan`'s exit calls the
            # PROCESS-GLOBAL `shutdown_langfuse()`, which such an app must not do to its host.
            _tracing_runtime = getattr(_app.state, "tracing_runtime", None)
            if _tracing_runtime is not None:
                await stack.enter_async_context(production_tracing_lifespan(_tracing_runtime))
            task = None
            reaper = None
            if worker is not None:
                # The fleet queue/lease repositories read the PROCESS-GLOBAL engine
                # (``clue_db.transaction``), which only ``db_lifespan`` installs. The design
                # store deliberately does not use it (``DesignStoreBridge`` owns a private
                # engine per call — the O5 rule), so the design API has never entered it. The
                # embedded worker is the first thing here that needs it.
                #
                # Entered conditionally because ``db_lifespan`` refuses re-entry: a process that
                # already has an engine (a platform host embedding this app) keeps its own.
                try:
                    get_engine()
                except RuntimeError:
                    await stack.enter_async_context(db_lifespan())
                task = asyncio.create_task(worker.run())
                # D5 Round C: the stranded-work reaper rides with the embedded worker — same
                # process-global engine, same "in development nothing else is running" argument.
                # Gated on the worker existing rather than on its own switch alone: a reaper with
                # no drain could re-offer work that nothing would then claim.
                from .fleet_reaper import start_reaper

                reaper = start_reaper(interval_s=settings.lumen_design_reaper_interval_s)
            try:
                yield
            finally:
                if reaper is not None:
                    from .fleet_reaper import stop_reaper

                    await stop_reaper(reaper)
                if task is not None:
                    assert worker is not None
                    worker.stop()
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(title="ABM Design Engine Persistence API", lifespan=lifespan)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness for Railway's health check, the uptime monitors and the boot smoke test
        (first deployment spec §9.5). Touches no database or Redis; needs no auth or workspace."""
        return {"status": "ok"}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # D4 (R-D4-1): NOT a store — the root of the Rust engine's TRANSIENT materialization cache.
    # Durable custody of every design byte is platform storage (below); the engine only ever
    # sees `{root}/{workspace_id}/sha256/{ab}/{digest}`, which Python writes back from after an
    # engine write and materializes into before an engine read. Wiping this tree loses nothing.
    # Resolution order (unchanged in spirit from the old asset-store anchor): an explicit
    # LUMEN_ASSET_STORE_ROOT wins, then this parameter (how a suite keeps its cache in tmp_path),
    # then the git-ignored repo-local default. The old `database_path` vestige is GONE with it —
    # it named no database since D2.5B and anchored nothing else.
    app.state.engine_cache_root = Path(
        settings.lumen_asset_store_root
        or engine_cache_root
        or settings.effective_asset_store_root
    )
    # D4: design BYTES live in platform storage (clue_storage), not under the asset-store tree.
    # ONE process-wide backend, selected by settings alone (fs vs S3) — no caller learns which
    # it holds. The parameter exists so a test can inject an `FsStorage(tmp_path)` and keep its
    # blobs disposable; production always takes the configured default. The
    # `custom-components/` sub-tree this replaced is deleted, not deprecated.
    app.state.storage = (
        storage if storage is not None else storage_from_settings()
    )
    app.state.custom_component_compiler_node_bin = "node"
    app.state.custom_component_compiler_worker = default_compiler_worker_path()
    app.state.custom_component_compiler_timeout_seconds = (
        DEFAULT_COMPILER_TIMEOUT_SECONDS
    )
    app.state.custom_component_runtime_host = default_runtime_host_path()
    app.state.core = CoreClient()
    # The isolation render's BROWSER half, injected at the composition root (F3.4, ledger
    # T18-M-13). Production takes the Playwright shutter; a test hands in its own callable and
    # gets the real render — the real engine page, the real fail-closed asset route — without a
    # Chromium. Previously a test reached in and rebound `main.render_isolation_preview`, which
    # worked and taught nothing about how the browser dependency is actually supplied.
    app.state.isolation_shooter = screenshot_isolation_page
    app.state.agent_turn_runner = None
    # Website-mode turn test seam: a callable (document, prompt, model, root) ->
    # envelope that replaces the real run_web_agent_turn in tests. None = live.
    app.state.web_turn_runner = None
    # Website-mode static-export node binary; the export/publish paths shell out
    # to scripts/web_static_css.mjs with it. A test overrides this (e.g. "false")
    # to exercise the honest compile-failure path.
    app.state.web_export_node_bin = "node"
    # Part II D6: THE governed design write path. Every converted domain's mutation runs through
    # this invoker — the platform's own `ToolInvoker`, over the platform's own `tool_invocation`
    # + execution-journal tables (see `lumen_api.toolbelt.wiring`). The host's members are
    # THUNKS, not snapshots, because the suites above override `app.state.*` (and monkeypatch
    # `main.compile_custom_component`) after `create_app` returns; a snapshotting host would
    # silently ignore those seams.
    app.state.design_tools = DesignToolInvocations(
        host=design_tool_host(
            storage=app.state.storage,
            core=lambda: app.state.core,
            # A thunk, not the function object: ``engine_cache_dir`` is defined further down
            # this factory, so binding it eagerly here would be a NameError.
            engine_cache_dir=lambda ws: engine_cache_dir(ws),
            web_export_node_bin=lambda: app.state.web_export_node_bin,
            compiler_node_bin=lambda: app.state.custom_component_compiler_node_bin,
            compiler_worker_path=lambda: Path(app.state.custom_component_compiler_worker),
            compiler_timeout_seconds=(
                lambda: app.state.custom_component_compiler_timeout_seconds
            ),
            # Read through the module global on every call: the compiler suites replace
            # `main.compile_custom_component` to drive fake compiler responses.
            compile_fn=lambda: compile_custom_component,
        ),
        storage=app.state.storage,
    )

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

    @app.exception_handler(CustomComponentReferenceError)
    def custom_component_reference_handler(
        _request: Request, error: CustomComponentReferenceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": error.code,
                    "message": error.message,
                    "node_id": error.node_id,
                    "artifact_id": error.artifact_id,
                }
            },
        )

    @app.exception_handler(FragmentReferenceError)
    def fragment_reference_handler(
        _request: Request, error: FragmentReferenceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": error.code,
                    "message": error.message,
                    "node_id": error.node_id,
                    "fragment_id": error.fragment_id,
                }
            },
        )

    @app.exception_handler(DesignFragmentActivationError)
    def fragment_activation_handler(
        _request: Request, error: DesignFragmentActivationError
    ) -> JSONResponse:
        """D-F8's refusal, worded for the person who has to act on it (T16 §6.6).

        409 rather than 422: nothing about the request is malformed — the section simply is not
        in a state where waking it is a decision anybody could make. The ``reason`` code is the
        whole point of the mapping: a human must read "get a preview first", never a 500 and
        never a sentence a surface has to parse to find the button it should offer.
        """
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": f"fragment.activation_{error.reason}",
                    "reason": error.reason,
                    "message": str(error),
                    "fragment_id": error.fragment_id,
                }
            },
        )

    @app.exception_handler(DesignFragmentPreviewError)
    def fragment_preview_handler(
        _request: Request, error: DesignFragmentPreviewError
    ) -> JSONResponse:
        """A preview is attached once (F3.2). Its sibling refusal, mapped on the same terms."""
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": f"fragment.preview_{error.reason}",
                    "reason": error.reason,
                    "message": str(error),
                    "fragment_id": error.fragment_id,
                }
            },
        )

    @app.exception_handler(CustomComponentArtifactConflict)
    def custom_component_artifact_conflict_handler(
        _request: Request, error: CustomComponentArtifactConflict
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "custom_component.artifact_conflict",
                    "message": str(error),
                    "artifact_id": error.artifact_id,
                }
            },
        )

    @app.exception_handler(CustomComponentSourceVersionConflict)
    def custom_component_source_version_conflict_handler(
        _request: Request, error: CustomComponentSourceVersionConflict
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "custom_component.source_version_conflict",
                    "message": str(error),
                    "slug": error.slug,
                    "expected_version": error.expected,
                    "current_version": error.current,
                }
            },
        )

    @app.exception_handler(WebPublishRevisionConflict)
    def web_publish_revision_conflict_handler(
        _request: Request, error: WebPublishRevisionConflict
    ) -> JSONResponse:
        """D6 Round C: a publish-revision content-address collision is a 409, not a 500.

        ``register_web_publish_revision`` compares the stored package against the one being
        registered and used to raise a bare ``ValueError`` that nothing caught. It is the same
        species the component registry already names — a content-addressed id re-used with
        different content — so it gets the same treatment: a typed refusal with the id on it.
        """
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "web_publish.revision_conflict",
                    "message": str(error),
                    "publish_id": error.publish_id,
                }
            },
        )

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

    def engine_cache_dir(workspace_id: str) -> str:
        """This workspace's engine materialization cache (D4 / R-D4-1), created on demand.

        Everything the engine reads or writes goes through a per-WORKSPACE cache dir, never a
        shared one: the engine resolves purely by digest, so a single global tree would let one
        tenant's export silently read another tenant's bytes for any digest they both happen to
        hold. The per-workspace split makes that unexpressible without touching the engine's
        layout below the workspace segment (a fixed contract).
        """
        path = Path(app.state.engine_cache_root) / workspace_id
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def request_cache_dir(repo: HybridRepository) -> str:
        """The engine cache for the request's own tenant — the O4-safe spelling."""
        return engine_cache_dir(repo.workspace_id)

    def blob_store(repo: HybridRepository) -> DesignBlobStore:
        """The design BYTE store for a request, scoped to the same tenant as its row store (D4).

        Storage keys are workspace-scoped (``{workspace_id}/design/{sha256}``), so byte custody
        follows the O4 seam automatically: a handle built from the request's repository can only
        read and write that tenant's blobs.
        """
        return DesignBlobStore(app.state.storage, repo.workspace_id)

    def repository(request: Request) -> HybridRepository:
        # D2.5B: SQLite is deleted; every store domain is Postgres via clue_design. The O4 seam is
        # STRICT — resolve_workspace_id 401s when X-Workspace-Id is absent instead of falling
        # back to the dev workspace. Two routes are exempt because they cannot receive a
        # header and take no tenant state: /build-info (engine handshake) and /asset-store/{digest}
        # (content-addressed public bytes the PUBLISHED page and the origin-"null" preview
        # iframe load — a custom header there would fail CORS preflight). A third — the
        # /w/{workspace_id}/... O6b public serving group — is GONE: custom-domain publishing S1
        # deleted it, and the page origin serves published pages now.
        # The run-event SSE stream WAS a fourth ("?workspace_id=", because EventSource cannot send
        # headers); D7 closed it — the stream is opened with a single-use token minted through this
        # very dependency, and its workspace is read off the token row.
        return HybridRepository(workspace_id=resolve_workspace_id(request))

    # --- D6: the ONE shim from a design route to the governed write path ------------------- #

    def run_design_tool(
        name: str,
        body: JsonObject,
        *,
        workspace_id: str,
        idempotency_key: Optional[str] = None,
        actor: str = "human",
        refusals: Optional[Dict[str, Any]] = None,
    ) -> JsonObject:
        """Invoke one design tool through the real ToolInvoker and return its REFERENCES.

        Part II D6, ruling R-D6-2. Three things happen here and nowhere else:

        * **Operation identity.** An ``Idempotency-Key`` header derives a stable operation id (so
          a retry replays the journal's terminal node and the A9 record instead of re-executing);
          without one the id is fresh per request, which is exactly the pre-D6 semantics. Same
          derivation as the platform's own ``POST /tools/{name}`` route.
        * **Refusal mapping.** A tool refuses with machine-readable ``reason_code``s. ``refusals``
          maps the ones a route has always had a *specific* wire contract for back to that exact
          HTTPException/domain error, so the editor's error bodies are unchanged. Anything
          unmapped falls through to the platform's generic ``precondition_failed`` 422 — loud, and
          never a silent-empty success.
        * **Conflict mapping.** A9/journal conflicts are 409, a malformed body is 422.

        Everything a tool *raises* (NotFoundError, CustomComponentSourceVersionConflict,
        WebExportError, sqlite3.IntegrityError …) propagates untouched to the app-level exception
        handlers — the journal records the failed attempt on the way past.
        """
        try:
            result = app.state.design_tools.invoke(
                name,
                body,
                workspace_id=workspace_id,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        except PreconditionFailed as refused:
            for failure in refused.failures:
                handler = (refusals or {}).get(failure.reason_code)
                if handler is not None:
                    raise handler(failure.message) from refused
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "precondition_failed",
                    "reason_codes": list(refused.reason_codes),
                    "failures": [
                        {"reason_code": item.reason_code, "message": item.message}
                        for item in refused.failures
                    ],
                },
            ) from refused
        except IdempotencyConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "idempotency_conflict",
                    "reason": conflict.reason,
                    "key": conflict.key,
                },
            ) from conflict
        except OperationConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={"error": "idempotency_conflict", "reason": "operation"},
            ) from conflict
        except ValidationError as invalid:
            raise HTTPException(status_code=422, detail=invalid.errors()) from invalid
        return dict(result.references)

    # --- D6 Round B: the shared refusal/conflict wire contracts for document writes --------- #

    def _document_refusals(document_id: str) -> Dict[str, Any]:
        """The exact bodies the editor has always seen for a refused document write.

        Defence in depth, like ``_publish_refusals``: every converted route resolves and gates the
        document itself (it needs the row to build its response), so from HTTP these are
        unreachable — only a non-HTTP caller (the batch loop, the fleet worker, a future agent)
        can trip them. ``document.exists`` is the one genuinely NEW body: a caller-supplied
        duplicate ``document_id`` used to reach the store and surface as a 500
        ``database.error`` (an IntegrityError through the sqlite3 handler). It is now a loud,
        typed 409 that writes nothing.
        """
        kind_conflict = lambda message: HTTPException(  # noqa: E731 - one shape, two reason codes
            status_code=409,
            detail={"code": "document.kind_unsupported", "message": message},
        )
        return {
            "design_document_not_found": lambda _message: NotFoundError(
                "document", document_id
            ),
            "design_document_not_scene": kind_conflict,
            "design_document_not_web": kind_conflict,
            "design_document_finalized": lambda message: HTTPException(
                status_code=409,
                detail={"code": "document.finalized", "message": message},
            ),
            "design_document_exists": lambda message: HTTPException(
                status_code=409,
                detail={
                    "code": "document.exists",
                    "message": message,
                    "resource_id": document_id,
                },
            ),
            "design_document_kind_unsupported": lambda message: HTTPException(
                status_code=422,
                detail={"code": "document.kind_unsupported", "message": message},
            ),
        }

    def _base_version_conflict(conflict: WebDocumentVersionConflict) -> HTTPException:
        """The 409 the in-transaction CAS produces (R-D6-B1).

        Byte-identical to ``require_base_version``'s body: the handler pre-check and the DAL's
        row-locked CAS are two statements of ONE contract, and a caller must not be able to tell
        which of them refused. The pre-check is the fast, friendly path; this is what closes the
        window between it and the write, across the engine round-trip in between.
        """
        return HTTPException(
            status_code=409,
            detail={
                "code": "edits.base_version_mismatch",
                "message": (
                    f"base_version {conflict.expected} does not match current document "
                    f"version {conflict.current}; reload the document and rebuild the edit"
                ),
                "current_version": conflict.current,
            },
        )

    def _snapshot_refusals(document_id: str, snapshot_id: str) -> Dict[str, Any]:
        """``_document_refusals`` plus the snapshot domain key's own conflict.

        Also a NEW body: a caller-supplied duplicate ``snapshot_id`` used to reach the store and
        surface as a 500 ``database.error``; it is now a typed 409 that writes nothing.
        """
        return {
            **_document_refusals(document_id),
            "design_snapshot_exists": lambda message: HTTPException(
                status_code=409,
                detail={
                    "code": "snapshot.exists",
                    "message": message,
                    "resource_id": snapshot_id,
                },
            ),
        }

    def _finalize_refusals(document_id: str, template_revision_id: str) -> Dict[str, Any]:
        """``_document_refusals`` plus the finalize domain key's own conflict (new 409, as for
        snapshots: a caller-supplied duplicate revision id used to reach the store as a 500)."""
        return {
            **_document_refusals(document_id),
            "design_template_revision_exists": lambda message: HTTPException(
                status_code=409,
                detail={
                    "code": "template_revision.exists",
                    "message": message,
                    "resource_id": template_revision_id,
                },
            ),
        }

    def _apply_scene_operations(
        repo: HybridRepository,
        tool: str,
        document_id: str,
        *,
        scene: JsonObject,
        diagnostics: List[JsonObject],
        operations: List[JsonObject],
        source: str,
        actor: Any,
        envelope: Optional[JsonObject],
        base_version: Optional[int],
    ) -> JsonObject:
        """One governed scene-state advance, then the row the caller's DTO is built from.

        The ONE call shape for `design_apply_operations` / `design_apply_edits`: the tool
        returns references, so the document row is re-read (the same `get_document` projection
        `update_document_state` returned pre-D6, so every response body is unchanged).
        """
        try:
            run_design_tool(
                tool,
                {
                    "document_id": document_id,
                    "scene": scene,
                    "diagnostics": diagnostics,
                    "operations": operations,
                    "source": source,
                    "actor_kind": actor.kind,
                    "actor_id": actor.id,
                    "envelope": envelope,
                    "expected_base_version": base_version,
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
        except WebDocumentVersionConflict as conflict:
            raise _base_version_conflict(conflict) from conflict
        return repo.require_document(document_id)

    def _effective_brand_payload(
        source: str,
        brand_kit: Optional[JsonObject],
        mode: Optional[JsonObject],
        *,
        persist: bool,
    ) -> Optional[JsonObject]:
        """The store's ``(source, brand_kit, mode)`` triple as the tool's named object.

        The ported rule, verbatim: persist the effective brand when the caller asked for it, and
        ALWAYS when the resolution had no document-level opinion to preserve.
        """
        if not (persist or source in {"platform_default", "none"}):
            return None
        return {"source": source, "brand_kit": brand_kit, "mode": mode}

    def _persist_preflight(
        repo: HybridRepository,
        document_id: str,
        *,
        scene: JsonObject,
        diagnostics: List[JsonObject],
        operations: List[JsonObject],
        actor_id: str,
        effective_brand: Optional[JsonObject],
        base_version: Optional[int] = None,
    ) -> JsonObject:
        """The ONE preflight-persist call shape — POST /preflight and POST /export share it.

        The two routes' writes were already identical apart from the envelope ``actor_id``
        (``preflight`` vs ``export_preflight``): same scene, same diagnostics, same operation
        list shape, same ``system`` source and ``system`` actor kind, same ``preflight``
        diagnostic kind, same effective-brand rule. So the cores DO genuinely unify (R-D6-B2's
        "check"), and ``design_persist_preflight`` takes that one string as a parameter rather
        than existing twice.
        """
        try:
            run_design_tool(
                "design_persist_preflight",
                {
                    "document_id": document_id,
                    "scene": scene,
                    "diagnostics": diagnostics,
                    "operations": operations,
                    "actor_id": actor_id,
                    "effective_brand": effective_brand,
                    "expected_base_version": base_version,
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
        except WebDocumentVersionConflict as conflict:
            raise _base_version_conflict(conflict) from conflict
        return repo.require_document(document_id)

    def _record_diagnostics(
        repo: HybridRepository,
        document_id: str,
        kind: str,
        diagnostics: List[JsonObject],
    ) -> None:
        """The ONE diagnostics-append call shape (six callers across five report kinds)."""
        run_design_tool(
            "design_record_diagnostics",
            {
                "document_id": document_id,
                "kind": kind,
                "diagnostics": diagnostics,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )

    def _derive_web_document(
        repo: HybridRepository,
        new_document_id: str,
        *,
        web_doc: JsonObject,
        template: JsonObject,
        account_id: Optional[str],
    ) -> JsonObject:
        """The ONE derive-persist call shape — the HTTP route and the batch loop share it.

        Same reasoning as `_publish_web` in Round A: the batch loop used to reproduce the whole
        derive persist inline, so the write now exists once and a batch derivation is journaled
        exactly like a manual one.
        """
        derived = run_design_tool(
            "design_derive_web_document",
            {
                "document_id": new_document_id,
                "web_doc": web_doc,
                "template_document_id": template["id"],
                "template_doc_version": template["current_version"],
                "account_id": account_id,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(new_document_id),
        )
        return {"id": derived["document_id"], "title": derived["title"]}

    def _redrive_web_document(
        repo: HybridRepository,
        existing: JsonObject,
        *,
        web_doc: JsonObject,
        title: str,
    ) -> JsonObject:
        """Re-derive ONTO the document an account already owns (clone-fidelity F4.3, R25-8).

        ``design_derive_web_document`` is create-only — it refuses an id that exists, which is
        correct for a first derivation and useless for a second one. A re-run has to be a state
        WRITE, so it takes the same governed web-document advance an editor edit takes: one
        history envelope, the CAS on the version it read, the fragment-reference gate. The page
        keeps its id (and therefore its slug, and therefore the URL somebody already sent out)
        and gains a revision rather than a twin.

        The whole document is replaced, deliberately: a derivation is a projection of the
        template plus one account's values, so the forward operation is a bare replace. The
        INVERSE carries the document as it stood (T25 review I-1) — the exact shape the undo
        path replays for a replace envelope — so a re-run that overwrote a manual edit is one
        undo away instead of an irrecoverable overwrite that also sealed the page's undo stack
        (the reviewer reproduced both: the destroyed edit, and the 409 on undo).
        """
        run_design_tool(
            "design_apply_web_operations",
            {
                "document_id": existing["id"],
                "web_doc": web_doc,
                "operations": [{"kind": "replace_web_doc"}],
                "inverse_operations": [
                    {"kind": "replace_web_doc", "web_doc": existing["scene"]}
                ],
                "intent": f"re-derive: {title}"[:120],
                "checkpoint_label": "Account re-derive",
                # `system`, not `editor`/`agent`: no human wrote this revision and no model did
                # — the batch re-projected the template. (`design_op_source` has exactly four
                # values; a fifth would be a migration for a label.)
                "actor_kind": "system",
                "source": "system",
                "expected_base_version": existing["current_version"],
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(existing["id"]),
        )
        return {"id": existing["id"], "title": title}

    # --- D6 Round C: brand kits, ingestion, assets, personalization ------------------------ #

    def _brand_kit_refusals(
        brand_kit: Optional[JsonObject] = None, brand_kit_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """The exact bodies a refused brand-kit write has always produced.

        ``brand_kit.version_exists`` used to come from catching ``sqlite3.IntegrityError`` on the
        composite primary key; it is a typed precondition now and writes nothing. The 404 is the
        same ``NotFoundError`` the store raised.
        """
        resolved_id = brand_kit_id or str((brand_kit or {}).get("id") or "")
        return {
            "design_brand_kit_exists": lambda _message: duplicate_brand_kit_error(
                brand_kit or {"id": resolved_id}
            ),
            "design_brand_kit_not_found": lambda _message: NotFoundError(
                "brand_kit", resolved_id
            ),
        }

    def _brand_kit_version_moved(conflict: DesignResourceVersionConflict) -> HTTPException:
        """The 409 the in-transaction version allocator's CAS produces (D6 Round C).

        A curation that was built against version N cannot be published on top of version M — it
        would silently discard whatever M added. The client reloads the kit and re-curates.
        """
        return HTTPException(
            status_code=409,
            detail={
                "code": "brand_kit.version_moved",
                "message": (
                    f"brand kit {conflict.key} moved from version {conflict.expected} to "
                    f"{conflict.current} while this change was being prepared; reload the kit "
                    "and re-apply it"
                ),
                "current_version": conflict.current,
            },
        )

    def _create_brand_kit(
        repo: HybridRepository,
        brand_kit: JsonObject,
        brand_summary: JsonObject,
        diagnostics: List[JsonObject],
        source: str,
    ) -> JsonObject:
        """The ONE 'publish a kit version the caller already numbered' call shape.

        Four callers share it: POST /brand-kits, the /generate and /compile-styles persist
        halves, and (with ``on_conflict='adopt'``, from the worker) the ingestion pipeline.
        """
        ref = run_design_tool(
            "design_create_brand_kit",
            {
                "brand_kit": brand_kit,
                "brand_summary": brand_summary,
                "diagnostics": diagnostics,
                "source": source,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_brand_kit_refusals(brand_kit),
        )
        return repo.require_brand_kit(ref["brand_kit_id"], ref["version"])

    def _publish_brand_kit_version(
        repo: HybridRepository,
        brand_kit: JsonObject,
        brand_summary: JsonObject,
        diagnostics: List[JsonObject],
        source: str,
        *,
        expected_base_version: int,
    ) -> JsonObject:
        """The ONE 'publish the next version of this kit' call shape (logo, describe-assets).

        The version is allocated inside the write transaction, so two concurrent curations
        serialize instead of racing to the same number; a stale base is a typed 409.
        """
        try:
            ref = run_design_tool(
                "design_publish_brand_kit_version",
                {
                    "brand_kit": brand_kit,
                    "brand_summary": brand_summary,
                    "diagnostics": diagnostics,
                    "source": source,
                    "expected_base_version": expected_base_version,
                },
                workspace_id=store_workspace_id(repo),
                refusals=_brand_kit_refusals(brand_kit),
            )
        except DesignResourceVersionConflict as conflict:
            raise _brand_kit_version_moved(conflict) from conflict
        return repo.require_brand_kit(ref["brand_kit_id"], ref["version"])

    def _offer_ingestion(repo: HybridRepository, kind: str, request: JsonObject) -> JsonObject:
        """The ONE ingestion-enqueue call shape — the three ingest routes share it.

        The job row and its ``design_job`` fleet task are written in one transaction inside the
        tool; the ids and the frozen envelope are minted here because the envelope names the job
        it dispatches (see ``_ingestion_offer_payload``).
        """
        payload = _ingestion_offer_payload(repo, kind, request)
        job_ref = run_design_tool(
            _INGESTION_TOOLS[kind],
            payload,
            workspace_id=store_workspace_id(repo),
        )
        log_event(
            api_logger,
            logging.INFO,
            "ingestion_job_offered",
            job_id=job_ref["job_id"],
            work_id=job_ref["work_id"],
            kind=kind,
            workspace_id=repo.workspace_id,
        )
        return IngestionJobStore(workspace_id=repo.workspace_id).require(job_ref["job_id"])

    def _asset_refusals(asset_id: str) -> Dict[str, Any]:
        """The exact bodies a refused asset write has always produced."""
        return {
            "design_asset_not_found": lambda _message: NotFoundError("asset", asset_id),
            "design_asset_referenced": lambda message: HTTPException(
                status_code=409, detail=message
            ),
            "design_asset_status_invalid": lambda message: HTTPException(
                status_code=422,
                detail={"code": "asset.status_unsupported", "message": message},
            ),
        }

    def _set_asset_status(
        repo: HybridRepository, asset_id: str, status: str
    ) -> JsonObject:
        """The ONE archive/restore call shape — one tool, both directions.

        Kept a single status-assignment tool rather than an ``archive`` and a ``restore``: unlike
        Round B's undo/redo (two different durable gestures over a history stack) these are one
        column taking one of two values, and naming them separately would claim a distinction the
        write does not have.
        """
        run_design_tool(
            "design_set_asset_status",
            {"asset_id": asset_id, "status": status},
            workspace_id=store_workspace_id(repo),
            refusals=_asset_refusals(asset_id),
        )
        return repo.require_asset_record(asset_id)

    def _register_asset_record(
        repo: HybridRepository, record: JsonObject, *, tool: str = "design_register_asset_record",
        enrichment: JsonObject | None = None
    ) -> JsonObject:
        """The ONE 'persist an engine-produced asset record' call shape.

        Three callers: the upload route, the QR route (which passes the content-keyed tool) and
        the registered-provider branch of the generate route.
        """
        ref = run_design_tool(
            tool,
            {"record": record, **({"enrichment": enrichment} if enrichment is not None else {})},
            workspace_id=store_workspace_id(repo),
        )
        return repo.require_asset_record(ref["asset_id"])

    def _persist_instance(
        repo: HybridRepository,
        instance: JsonObject,
        *,
        generated_records: Optional[List[JsonObject]] = None,
        repair_requests: Optional[List[JsonObject]] = None,
    ) -> JsonObject:
        """The ONE derived-instance persist call shape (the derive route and both batch loops).

        The tool returns references, so the instance row is re-read — the same
        ``get_instance`` projection ``upsert_instance`` returned pre-D6, so every response body
        and every manifest entry is unchanged.
        """
        ref = run_design_tool(
            "design_derive_instance",
            {
                "instance": instance,
                "generated_records": generated_records or [],
                "repair_requests": repair_requests or [],
            },
            workspace_id=store_workspace_id(repo),
        )
        return repo.require_instance(ref["instance_id"])

    def _advance_batch(
        repo: HybridRepository, tool: str, body: JsonObject
    ) -> JsonObject:
        """One chunk of batch progress through the governed tool. Returns the tool's reference.

        ``advanced=False`` means a concurrent resumer already moved the cursor past this chunk;
        the caller stops and reports where the batch actually is (never an error — a resume that
        discovers the work is already being done has nothing to complain about).
        """
        return run_design_tool(
            tool,
            body,
            workspace_id=store_workspace_id(repo),
            refusals={
                "design_batch_not_found": lambda _message: NotFoundError(
                    "batch", str(body["batch_id"])
                )
            },
        )

    def _snapshot_after_write(
        repo: HybridRepository, document_id: str, reason: Optional[str]
    ) -> Optional[JsonObject]:
        """The optional post-write snapshot the mutating scene routes take.

        A SECOND governed invocation rather than a field on the state tool: it is a second
        durable write with its own domain key (the snapshot id), and folding it into the state
        advance would make that advance's replay policy a lie about one of its two effects.
        """
        if not reason:
            return None
        snapshot_id = new_id("snap")
        run_design_tool(
            "design_create_snapshot",
            {
                "document_id": document_id,
                "snapshot_id": snapshot_id,
                "reason": reason,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_snapshot_refusals(document_id, snapshot_id),
        )
        return repo.require_snapshot(document_id, snapshot_id)

    # O4-exempt (no X-Workspace-Id): a process-wide engine stamp with no tenant state, read by
    # the editor's version handshake before any workspace context exists.
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

    # Tenant-free payload, but an editor-only route: it carries the header like every other
    # authenticated call so the strict O4 seam has exactly three exemptions, not four.
    @app.get("/font-library", dependencies=[Depends(resolve_workspace_id)])
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
        payload: CreateBrandKitRequest, repo: HybridRepository = Depends(repository)
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
        record = _create_brand_kit(
            repo,
            brand_kit,
            summary_response.get("brand_summary") or {},
            diagnostics,
            payload.source,
        )
        return brand_kit_created_dto(record, diagnostics)

    @app.post("/brand-kits/generate")
    def generate_brand_kit(
        payload: GenerateBrandKitRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        try:
            result = app.state.core.generate_brand_kit(payload.seed)
        except CoreError as error:
            raise core_http_error(error) from error

        brand_kit = result["brand_kit"]
        diagnostics = result.get("diagnostics", [])
        record = None
        if payload.persist:
            record = _create_brand_kit(
                repo,
                brand_kit,
                result.get("brand_summary") or {},
                diagnostics,
                "generated",
            )
        return brand_kit_generation_dto(
            record,
            brand_kit,
            result.get("brand_summary"),
            result.get("brand_generation") or {},
            diagnostics,
        )

    @app.post("/brand-kits/compile-styles")
    def compile_styles_brand_kit(
        payload: CompileStylesBrandKitRequest, repo: HybridRepository = Depends(repository)
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
            record = _create_brand_kit(
                repo,
                brand_kit,
                result.get("brand_summary") or {},
                diagnostics,
                "styles",
            )
        return brand_kit_generation_dto(
            record,
            brand_kit,
            result.get("brand_summary"),
            {},
            diagnostics,
        )

    @app.post("/brand-kits/validate")
    def validate_brand_kit(
        payload: ValidateBrandKitRequest, repo: HybridRepository = Depends(repository)
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
        payload: BrandCompatibilityRequest, repo: HybridRepository = Depends(repository)
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
            report_id = new_id("brand_report")
            run_design_tool(
                "design_create_brand_compatibility_report",
                {
                    "report_id": report_id,
                    "from_brand_kit": from_record["brand_kit"],
                    "to_brand_kit": to_record["brand_kit"],
                    "report": result.get("brand_compatibility") or {},
                    "diagnostics": diagnostics,
                },
                workspace_id=store_workspace_id(repo),
            )
            stored_report = repo.require_brand_compatibility_report(report_id)
        return brand_compatibility_dto(
            result.get("brand_compatibility") or {},
            diagnostics,
            stored_report,
        )

    @app.get("/brand-kits")
    def list_brand_kits(
        all_versions: bool = Query(default=False),
        repo: HybridRepository = Depends(repository),
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        guard = _resolve_guard_url()
        try:
            await guard(payload.url)
        except Exception as error:  # CaptureError / ValueError from the guard
            raise ingest_url_rejected(payload.url, error) from error

        # D5 Round C: the ingestion is OFFERED, not started. The route creates the job row and
        # its ``design_job`` fleet task in ONE transaction and returns; a leased worker (detached
        # or embedded) claims and executes it. This replaces ``BackgroundTasks``, which ran the
        # pipeline inside the API process — so a restart silently killed it and left the job
        # ``running`` forever, with nothing to re-offer it.
        #
        # The ``run_in_threadpool`` dance that used to wrap the store call is gone with it: it
        # existed because this is the one ASYNC ingestion endpoint and the sync store facade
        # cannot ``asyncio.run`` inside a live loop. ``design_store.run_isolated`` has
        # handled exactly that since D2.3 by handing the coroutine to a one-shot worker thread,
        # so the extra hop was doing nothing the bridge does not already do.
        job = _offer_ingestion(repo, "website", payload.model_dump())
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

    @app.post("/brand-kits/ingest/pdf")
    def ingest_pdf(
        file: UploadFile = File(...),
        name: Optional[str] = Form(None),
        brand_kit_id: Optional[str] = Form(None),
        repo: HybridRepository = Depends(repository),
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

        # D4 (R-D4-5): the uploaded bytes are STAGED IN PLATFORM STORAGE, not in an
        # `ingest_tmp/` directory beside a cache. A background job may outlive the process that
        # accepted the upload, so its input has to be durable — a tmp file under a wipeable
        # materialization cache was the one place these bytes could not safely live. The job
        # request carries the staged DIGEST; `run_pdf_ingestion` reads it back through the blob
        # store and the `finally` cleanup deletes it unless it was promoted to a live asset.
        #
        # D5 Round C reorders this: the bytes are staged BEFORE the job row exists, so the row
        # can be created with its complete request AND its fleet task in one transaction. Under
        # ``BackgroundTasks`` the order had to be create → stage → update_request → dispatch,
        # which left a job row briefly claiming inputs it did not yet have; staging first is
        # free (the register is content-addressed and idempotent, and an abandoned staged blob
        # is exactly what the orphan sweep already collects).
        blobs = blob_store(repo)
        blobs.register(
            data,
            media_type="application/pdf",
            source_key=design_storage.SOURCE_KEY_INGEST_STAGING,
        )
        job = _offer_ingestion(
            repo,
            "pdf",
            {
                "filename": file.filename,
                "name": name,
                "brand_kit_id": brand_kit_id,
                "size_bytes": len(data),
                "staged_digest": hashlib.sha256(data).hexdigest(),
                "media_type": "application/pdf",
            },
        )
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

    @app.post("/brand-kits/ingest/assets")
    def ingest_assets(
        files: List[UploadFile] = File(...),
        name: Optional[str] = Form(None),
        brand_kit_id: Optional[str] = Form(None),
        repo: HybridRepository = Depends(repository),
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

        # D4 (R-D4-5): each uploaded file is STAGED IN PLATFORM STORAGE (see the PDF route for
        # why a tmp file under the engine cache is not a safe home for a background job's
        # input). The job request carries each file's staged DIGEST; `run_asset_ingestion` reads
        # them back through the blob store and cleans up the ones that were not promoted.
        # D5 Round C: staged first, then the job row and its fleet task in ONE transaction — see
        # the PDF route for why the order flipped.
        blobs = blob_store(repo)

        file_specs: List[JsonObject] = []
        for upload, data in payloads:
            media_type = upload.content_type or "application/octet-stream"
            blobs.register(
                data,
                media_type=media_type,
                source_key=design_storage.SOURCE_KEY_INGEST_STAGING,
            )
            file_specs.append(
                {
                    "filename": upload.filename,
                    "content_type": upload.content_type,
                    "staged_digest": hashlib.sha256(data).hexdigest(),
                    "media_type": media_type,
                }
            )

        job = _offer_ingestion(
            repo,
            "asset_upload",
            {
                "name": name,
                "brand_kit_id": brand_kit_id,
                "file_count": len(payloads),
                "files": file_specs,
            },
        )
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

    # --- Brand Ad Assets v1 W2 (flag-gated: LUMEN_BRAND_AD_ASSETS) ---------------------------
    #
    # The routes below are REGISTERED ONLY WHEN THE FLAG IS ON. That is deliberately stronger
    # than a 403 inside a live handler: with the flag off the paths do not exist, so the app's
    # surface — its route table, its OpenAPI schema, every 404 — is byte-identical to an app
    # built without this lane at all. Nothing else in the app reads the lane's tables, so flag
    # off is genuinely zero behaviour change and not merely a refusal.
    if settings.lumen_brand_ad_assets:

        @app.post("/brand-ad-assets/onboard")
        def onboard_ad_assets(
            payload: OnboardAdAssetsRequest,
            repo: HybridRepository = Depends(repository),
        ) -> JsonObject:
            """Offer one ad-assets onboarding job (harvest → distil → pre-generate).

            Like the three brand-kit ingest routes, this does not do the work: it writes the
            job row and its ``design_job`` fleet task in one transaction and returns the job
            reference. A leased worker runs the pipeline; poll it at
            ``GET /brand-kits/ingest/{job_id}`` — it is an ingestion job, of a fourth kind.

            Own ads only (D2): exactly one of ``company_domain`` / ``page_id``, both naming the
            CLIENT's own advertiser. There is no competitor input in v1.
            """
            if payload.phase == "card":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "ad_assets.card_phase_is_internal",
                        "message": (
                            "the card phase is offered by the worker once a harvest and a brand "
                            "kit both exist; request phase 'full' to run everything at once"
                        ),
                    },
                )
            domain = (payload.company_domain or "").strip()
            page = (payload.page_id or "").strip()
            if bool(domain) == bool(page):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "ad_assets.advertiser_ambiguous",
                        "message": (
                            "supply exactly one of company_domain or page_id — the advertiser "
                            "must be unambiguous before any vendor credit is spent"
                        ),
                    },
                )
            if payload.max_pages < 1 or payload.max_creatives < 1:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "ad_assets.bad_bounds",
                        "message": "max_pages and max_creatives must both be at least 1",
                    },
                )
            if payload.phase == "full":
                if payload.brand_kit_id is None or payload.brand_kit_version is None:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "ad_assets.brand_kit_required",
                            "message": (
                                "a full run pins its card to a brand kit; name one, or request "
                                "phase 'harvest' to collect the ads before any kit exists"
                            ),
                        },
                    )
                # Fail here rather than in the worker: an unknown kit would only surface as a
                # foreign-key error at the very end, after the harvest had already been paid for.
                repo.require_brand_kit(payload.brand_kit_id, payload.brand_kit_version)

            job = _offer_ingestion(repo, "ad_assets", payload.model_dump())
            return {"schema_version": 1, "job": ingestion_job_dto(job)}

        @app.get("/brand-ad-assets/{brand_kit_id}")
        def get_ad_assets_lane(
            brand_kit_id: str, repo: HybridRepository = Depends(repository)
        ) -> JsonObject:
            """The lane's current state for one brand kit: latest card + its pre-generated assets.

            An un-harvested brand answers ``card: null`` with an empty asset list rather than a
            404: "this brand has no ad DNA yet" is an ordinary state of the world for every
            consumer of this lane, and a 404 would make it look like a mistake.
            """
            from lumen_ingestion.ad_library.store import AdAssetsStore

            store = AdAssetsStore(workspace_id=repo.workspace_id)
            card = store.latest_card(brand_kit_id=brand_kit_id)
            pregenerated = (
                store.list_pregenerated(
                    card_id=card["card_id"], card_version=int(card["version"])
                )
                if card
                else []
            )
            return {
                "schema_version": 1,
                "brand_kit_id": brand_kit_id,
                "card": card,
                "pregenerated_assets": pregenerated,
                "creatives": store.list_creatives(limit=50),
            }

    @app.get("/brand-kits/ingest")
    def list_ingestion_jobs(
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Most-recent 50 ingestion jobs (public dto — no request/evidence
        bodies). Registered adjacent to the param route; the literal segment
        only matches when the path has no trailing job id."""
        jobs = IngestionJobStore(workspace_id=repo.workspace_id).list_recent(50)
        return {
            "schema_version": 1,
            "jobs": [ingestion_job_dto(job) for job in jobs],
        }

    @app.get("/brand-kits/ingest/{job_id}")
    def get_ingestion_job(
        job_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        job = IngestionJobStore(workspace_id=repo.workspace_id).get(job_id)
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
        brand_kit_id: str, repo: HybridRepository = Depends(repository)
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
        brand_kit_id: str, version: int, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return brand_kit_detail_dto(repo.require_brand_kit(brand_kit_id, version))

    @app.post("/brand-kits/{brand_kit_id}/approval")
    def set_brand_kit_approval(
        brand_kit_id: str,
        payload: SetBrandKitApprovalRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Flip the approval state on the latest version of a kit (approve /
        revert to draft). Unknown kit → 404; invalid status → 422 (model)."""
        ref = run_design_tool(
            "design_set_brand_kit_approval",
            {"brand_kit_id": brand_kit_id, "approval_status": payload.approval_status},
            workspace_id=store_workspace_id(repo),
            refusals=_brand_kit_refusals(brand_kit_id=brand_kit_id),
        )
        record = repo.require_brand_kit(ref["brand_kit_id"], ref["version"])
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
        repo: HybridRepository = Depends(repository),
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
        # W1.6: the slot now holds a different mark, so its background policy must
        # cover it. Promoting a reversed logo into a slot that ingestion wrote as
        # light-only would otherwise leave the kit saying that mark may never sit
        # on a dark field — the exact vocabulary gap the Cursor pilot hit. Widening
        # only: an existing allowance is never dropped, and an empty list (which
        # means "do not check this slot") is left empty.
        slot["allowed_backgrounds"] = extend_allowed_backgrounds(
            slot.get("allowed_backgrounds"), [payload.color_mode]
        )
        slot["provenance"] = {
            "confidence": 1.0,
            "source": f"manual :: human-selected {asset.get('label') or payload.asset_id}",
        }
        logos[payload.slot] = slot
        # The version this kit will carry is ALLOCATED by the write (D6 Round C) — the number
        # set here is provisional, only so the engine validates the same shape it always has.
        base_version = int(record["version"])
        brand_kit["version"] = base_version + 1

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
        created = _publish_brand_kit_version(
            repo,
            brand_kit,
            summary_response.get("brand_summary") or {},
            diagnostics,
            "manual",
            expected_base_version=base_version,
        )
        log_event(
            api_logger,
            logging.INFO,
            "brand_kit_logo_set",
            brand_kit_id=brand_kit_id,
            slot=payload.slot,
            asset_id=payload.asset_id,
            version=created["version"],
        )
        return brand_kit_created_dto(created, diagnostics)

    @app.post("/brand-kits/{brand_kit_id}/describe-assets")
    def describe_brand_kit_assets(
        brand_kit_id: str, repo: HybridRepository = Depends(repository)
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
        # D4: byte reads resolve durably (`make_resolve_bytes` reads through the blob store);
        # only the SVG rasterizer touches the engine, and it materializes what it needs.
        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        describe_diagnostics: list = []
        # Glyph-coverage audit backfill (same pattern as the ramp): kits ingested
        # before the audit get fonts.*.metrics.missing_glyphs stamped from their
        # stored face bytes, so the honesty note reaches the agent's brand card
        # on republish without a full re-ingestion. Advisory LUMI0806 warnings.
        ensure_glyph_coverage(
            brand_kit,
            make_resolve_bytes(repo, blobs),
            describe_diagnostics,
        )
        counts = describe_kit_assets(
            brand_kit,
            describer=resolve_describer(),
            resolve_bytes=make_resolve_bytes(repo, blobs),
            rasterize_svg=make_rasterize_svg(repo, blobs, cache_dir),
            diagnostics=describe_diagnostics,
            brand_name=record.get("name"),
            workspace_id=repo.workspace_id,
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
        # Provisional, as on the logo route: the write allocates the real number (D6 Round C).
        base_version = int(record["version"])
        brand_kit["version"] = base_version + 1
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
        created = _publish_brand_kit_version(
            repo,
            brand_kit,
            summary_response.get("brand_summary") or {},
            diagnostics,
            "manual",
            expected_base_version=base_version,
        )
        log_event(
            api_logger,
            logging.INFO,
            "brand_kit_assets_described",
            brand_kit_id=brand_kit_id,
            version=created["version"],
            **counts,
        )
        response = brand_kit_created_dto(created, diagnostics)
        response["published"] = True
        response["counts"] = counts
        return response

    @app.get("/brand-compatibility-reports/{report_id}")
    def get_brand_compatibility_report(
        report_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return repo.require_brand_compatibility_report(report_id)

    @app.post("/documents")
    def create_document(
        payload: CreateDocumentRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        if payload.doc_kind not in ("scene", "web"):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "document.kind_unsupported",
                    "message": (
                        f"unsupported doc_kind {payload.doc_kind!r}; "
                        "expected 'scene' or 'web'"
                    ),
                },
            )
        # D6 Round B: the id is minted HERE when the client omits one, so the durable identity
        # `design_create_document` claims is always one its caller named (the DOMAIN_IDEMPOTENT
        # key). The engine round-trip below stays in the route — the tool governs only the write
        # (R-D6-B4).
        document_id = payload.document_id or new_id("doc")
        try:
            if payload.doc_kind == "web":
                result = app.state.core.web_new_doc(
                    document_id, payload.title, payload.brand_kit_ref
                )
                run_design_tool(
                    "design_create_document",
                    {
                        "document_id": document_id,
                        "scene": result["web_doc"],
                        "doc_kind": "web",
                    },
                    workspace_id=store_workspace_id(repo),
                    refusals=_document_refusals(document_id),
                )
                document = repo.require_document(document_id)
                log_event(
                    api_logger,
                    logging.INFO,
                    "document_created",
                    document_id=document["id"],
                    title=document["title"],
                    version=document["current_version"],
                    doc_kind="web",
                    has_brand_kit=(
                        (document["scene"].get("theme") or {}).get("brand_kit")
                        is not None
                    ),
                )
                return document_created_dto(document)
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
            run_design_tool(
                "design_create_document",
                {
                    "document_id": document_id,
                    "scene": scene,
                    "doc_kind": "scene",
                    "brand_kit": payload.brand_kit,
                    "effective_brand_source": (
                        "document" if payload.brand_kit else None
                    ),
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
            document = repo.require_document(document_id)
            log_event(
                api_logger,
                logging.INFO,
                "document_created",
                document_id=document["id"],
                title=document["title"],
                version=document["current_version"],
                doc_kind="scene",
                has_brand_kit=payload.brand_kit is not None,
            )
            return document_created_dto(document)
        except CoreError as error:
            raise core_http_error(error) from error

    @app.get("/documents/{document_id}")
    def get_document(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        result = public_document(document)
        # Only the READ route carries it. A create response and an operations response
        # both describe a document the caller is holding, and this map is a snapshot of a
        # registry that moves independently of it — served where it is read, not echoed
        # where it is written. ``list_web_fragments`` is workspace-scoped through ``repo``,
        # which is exactly the scoping a label needs — and it is read ONLY for a web
        # document, so a scene GET does not pay for a registry scan whose answer it throws
        # away.
        is_web = document.get("doc_kind") == "web"
        if not is_web:
            result["render_context"] = document_render_context(app.state.core, repo, document)
        rows = repo.list_web_fragments() if is_web else ()
        meta = fragment_meta_for_document(document, rows)
        if meta is not None:
            result["fragment_meta"] = meta
        return result

    @app.get("/documents/{document_id}/agent-run")
    def get_document_agent_run(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """The document-scoped agent-busy signal (scene live-streaming rung A follow-up).

        The standalone artifact route has no turn stream to derive the editor lock from, so it
        asks HERE — the same ``active_design_run_for_document`` predicate the manual-write routes'
        409 reads, so the page's lock and the server's refusal cannot disagree. ``current_version``
        rides along so a poller can reload the canvas when the run's commits move the document,
        without a second request.
        """
        document = require_document(repo, document_id)
        run_id = repo.active_design_run_for_document(document_id)
        return {
            "schema_version": 1,
            "document_id": document_id,
            "active": run_id is not None,
            "run_id": run_id,
            "current_version": document["current_version"],
        }

    @app.put("/documents/{document_id}/agent-instructions")
    def set_agent_instructions(
        document_id: str,
        payload: SetAgentInstructionsRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """2e: per-document standing instructions for the agent. Stored on the
        document (they survive reloads) and sent by the editor with every
        turn; an empty/blank body clears them."""
        require_scene_document(require_document(repo, document_id))
        instructions = (payload.instructions or "").strip() or None
        written = run_design_tool(
            "design_set_agent_instructions",
            {"document_id": document_id, "instructions": instructions},
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        return {
            "schema_version": 1,
            "document_id": document_id,
            # The tool returns the stored value as a reference, so no re-read is needed.
            "agent_instructions": written["value"],
        }

    @app.put("/documents/{document_id}/layout-managed-editing")
    def set_layout_managed_editing(
        document_id: str,
        payload: SetLayoutManagedEditingRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Per-document advanced opt-out from handoff-absolute: when enabled,
        the editor skips both freeze seams (Accept and first gesture) so agent
        auto-layout stays live. Forward-only — enabling never un-freezes
        containers that are already Free."""
        require_scene_document(require_document(repo, document_id))
        written = run_design_tool(
            "design_set_layout_managed_editing",
            {"document_id": document_id, "enabled": payload.enabled},
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        return {
            "schema_version": 1,
            "document_id": document_id,
            "layout_managed_editing": written["value"],
        }

    @app.put("/documents/{document_id}/web-noindex")
    def set_web_noindex(
        document_id: str,
        payload: SetWebNoindexRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """THE explicit action ruling R-F1 asks for, in both directions.

        `noindex` is stored on the DOCUMENT, so every publish route emits the robots meta on a
        stamped page whether or not it knows the flag exists. This is the only surface that can
        take it off again — and the field is required, so a caller who names no value gets a 422
        rather than a silent clear. (The ABM batch is the stamp's first writer; a human turning
        an account page back into an indexable one is what this route serves.)
        """
        require_web_document(require_document(repo, document_id))
        written = run_design_tool(
            "design_set_web_noindex",
            {"document_id": document_id, "enabled": payload.noindex},
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        return {
            "schema_version": 1,
            "document_id": document_id,
            "web_noindex": written["value"],
        }

    @app.put("/documents/{document_id}/title")
    def rename_document(
        document_id: str,
        payload: RenameDocumentRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Artifacts page (2026-09-15): rename from the library preview or the editor header."""
        require_document(repo, document_id)
        written = run_design_tool(
            "design_rename_document",
            {"document_id": document_id, "title": payload.title},
            workspace_id=store_workspace_id(repo),
            refusals={
                **_document_refusals(document_id),
                # A blank title is refused by the tool gate, BEFORE the DAL's own ValueError, so
                # the caller gets this typed 422 rather than a 500 out of the store.
                "design_document_title_blank": lambda message: HTTPException(
                    status_code=422,
                    detail={"code": "document.title_blank", "message": message},
                ),
            },
        )
        return {"schema_version": 1, "document_id": document_id, "title": written["value"]}

    @app.put("/documents/{document_id}/archived")
    def set_document_archived(
        document_id: str,
        payload: SetDocumentArchivedRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Artifacts page (2026-09-15): archive/restore; publish is independent by ruling."""
        require_document(repo, document_id)
        written = run_design_tool(
            "design_set_document_archived",
            {"document_id": document_id, "enabled": payload.archived},
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        return {"schema_version": 1, "document_id": document_id, "archived_at": written["value"]}

    @app.put("/documents/{document_id}/scene")
    def replace_scene(
        document_id: str,
        payload: ReplaceSceneRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
        require_draft_document(document, "replace the current scene")
        _refuse_if_agent_running(document_id, repo)
        try:
            validation = app.state.core.validate_scene(payload.scene)
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = validation.get("diagnostics", [])
        if has_error_diagnostics(diagnostics):
            _record_diagnostics(repo, document_id, "structural", diagnostics)
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
        # D4 backstop (R-D4-1): this is an ACCEPT seam — an outside author (the editor, an
        # agent turn) hands us a whole scene, and any asset it generated mid-turn exists only in
        # the engine's wipeable cache until now. Give those bytes durable custody before the
        # write promotes their records into the registry, so the registry can never outlive the
        # bytes it points at. One pass; skip-if-already-durable, so it is normally all skips.
        register_scene_asset_backstop(blob_store(repo), request_cache_dir(repo), scene)
        # D6 Round B (R-D6-B1), honest window recorded AT THE SITE: this route's request
        # contract (`ReplaceSceneRequest`) carries NO base_version, so there is nothing to CAS
        # against and the tool is invoked with `expected_base_version=None`. The DAL's row lock
        # still serializes concurrent replaces, but two whole-scene replaces racing each other
        # remain last-writer-wins — as they were pre-D6. Closing it means adding a base_version
        # to the wire contract (an editor change, out of D6's scope); D6 does not invent a
        # request field, and does not pretend the window is closed.
        run_design_tool(
            "design_replace_scene",
            {
                "document_id": document_id,
                "scene": scene,
                "diagnostics": diagnostics,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        document = repo.require_document(document_id)
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        if not payload.operations:
            raise HTTPException(
                status_code=422,
                detail={"code": "operations.empty", "message": "operations cannot be empty"},
            )
        document = require_document(repo, document_id)
        require_scene_document(document)
        require_draft_document(document, "apply operations")
        # Before the base-version check on purpose: a document a run is driving has almost
        # certainly moved under the caller, and "an agent is working on this" is the honest
        # answer to that, not "your base version is stale".
        _refuse_if_agent_running(document_id, repo)
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
        # D4 backstop — see PUT /scene: an `upsert_asset` operation can carry a record whose
        # bytes the caller only ever wrote into the engine cache.
        register_scene_asset_backstop(
            blob_store(repo), request_cache_dir(repo), result["scene"]
        )
        # D6 Round B: the engine round-trip above is the ROUTE's (R-D6-B4); the tool governs the
        # durable write, with `base_version` threaded through to the DAL's row-locked CAS —
        # which is what closes the window `require_base_version` above cannot (it read the
        # version BEFORE the engine call).
        updated = _apply_scene_operations(
            repo,
            "design_apply_operations",
            document_id,
            scene=result["scene"],
            diagnostics=diagnostics,
            operations=payload.operations,
            source=payload.source,
            actor=payload.actor,
            envelope=envelope,
            base_version=payload.base_version,
        )
        snapshot = _snapshot_after_write(repo, document_id, payload.snapshot_reason)
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
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> List[JsonObject]:
        return repo.list_operations(document_id)

    @app.get("/documents/{document_id}/history")
    def list_history(
        document_id: str,
        limit: int = 50,
        offset: int = 0,
        repo: HybridRepository = Depends(repository),
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
        document_id: str, repo: HybridRepository = Depends(repository)
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

    def perform_undo_step(repo: HybridRepository, document_id: str) -> JsonObject:
        """Apply one document-level undo as a new appended envelope."""
        document = require_document(repo, document_id)
        require_scene_document(document)
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
        # D6 Round B: the version the route just read is threaded into the DAL's row-locked CAS.
        # Undo is a read-then-write loop over the stacks, so a concurrent edit landing between
        # the read and this write used to interleave silently (the undo would rewind a scene it
        # never saw); it is now the same `edits.base_version_mismatch` 409 every other scene
        # write produces.
        try:
            run_design_tool(
                "design_undo_document",
                {
                    "document_id": document_id,
                    "scene": result["scene"],
                    "diagnostics": diagnostics,
                    "operations": target["inverse_operations"],
                    "envelope": {
                        "intent": f"undo:{target['intent'] or target['batch_id']}",
                        "reverts_batch_id": target["batch_id"],
                        "touched_targets": target["touched_targets"],
                        "inverse_operations": target["operations"],
                    },
                    "expected_base_version": document["current_version"],
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
        except WebDocumentVersionConflict as conflict:
            raise _base_version_conflict(conflict) from conflict
        return target

    @app.post("/documents/{document_id}/undo")
    def undo_document(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        # On the ROUTE rather than inside `perform_undo_step`, which `/revert` also drives: each
        # guarded route states its own lock, so no route inherits one by accident from a shared
        # helper (`/revert` states its own, right after its draft gate). The document gates
        # therefore run one step later here than in the neighbouring routes — they live inside
        # the step.
        _refuse_if_agent_running(document_id, repo)
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
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
        require_draft_document(document, "redo")
        _refuse_if_agent_running(document_id, repo)
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
        try:
            run_design_tool(
                "design_redo_document",
                {
                    "document_id": document_id,
                    "scene": result["scene"],
                    "diagnostics": diagnostics,
                    "operations": target["operations"],
                    "envelope": {
                        "intent": f"redo:{target['intent'] or target['batch_id']}",
                        "reapplies_batch_id": target["batch_id"],
                        "touched_targets": target["touched_targets"],
                        "inverse_operations": target["inverse_operations"],
                    },
                    "expected_base_version": document["current_version"],
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
        except WebDocumentVersionConflict as conflict:
            raise _base_version_conflict(conflict) from conflict
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
        require_draft_document(document, "revert")
        _refuse_if_agent_running(document_id, repo)
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
        # D6 Round B — DEVIATION from R-D6-B2's suggested `design_revert_document`, argued at the
        # site: revert owns NO durable mutation of its own. It is N undo steps, and each step's
        # engine round-trip depends on the scene the previous step wrote, so a single tool would
        # have to run N engine calls inside itself (forbidden by R-D6-B4) or write N envelopes
        # from a scene chain computed off-store. Instead each step goes through the SAME governed
        # `design_undo_document` the /undo route uses, with its own operation id and its own
        # base version — so a concurrent edit mid-revert stops the revert with the standard 409
        # instead of quietly rewinding past it.
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
        require_draft_document(document, "apply structured edit")
        # Before the base-version check, for the reason stated at the /operations call site.
        _refuse_if_agent_running(document_id, repo)
        require_base_version(document, payload.base_version)
        try:
            # Preserve the same pinned typography the editor's preview resolves.
            # A missing pin must not silently become the platform default.
            has_brand_pin = (document["scene"].get("meta") or {}).get("brand_kit") is not None
            _, brand_kit = choose_effective_brand(
                app.state.core, repo, document,
                PreflightRequest(strict_no_fallback=has_brand_pin),
            )
            mode = choose_effective_brand_mode(document, brand_kit, None)
            result = app.state.core.apply_structured_edit(
                document["scene"],
                payload.edit,
                scope=payload.scope.model_dump() if payload.scope else None,
                brand_kit=brand_kit,
                mode=mode,
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
        updated = _apply_scene_operations(
            repo,
            "design_apply_edits",
            document_id,
            scene=result["scene"],
            diagnostics=diagnostics,
            operations=operations,
            source=payload.source,
            actor=payload.actor,
            envelope=envelope,
            base_version=payload.base_version,
        )
        snapshot = _snapshot_after_write(repo, document_id, payload.snapshot_reason)
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        require_scene_document(require_document(repo, document_id))
        # D6 Round B: minted HERE when the client omits one, so the tool's DOMAIN key is always
        # a caller-named identity (see `design_create_snapshot`'s replay note).
        snapshot_id = payload.snapshot_id or new_id("snap")
        run_design_tool(
            "design_create_snapshot",
            {
                "document_id": document_id,
                "snapshot_id": snapshot_id,
                "reason": payload.reason,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_snapshot_refusals(document_id, snapshot_id),
        )
        return {
            "schema_version": 1,
            "status": "created",
            "snapshot": snapshot_summary(repo.require_snapshot(document_id, snapshot_id)),
        }

    @app.get("/documents/{document_id}/snapshots")
    def list_snapshots(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> List[JsonObject]:
        return [snapshot_summary(snapshot) for snapshot in repo.list_snapshots(document_id)]

    @app.get("/documents/{document_id}/snapshots/{snapshot_id}")
    def get_snapshot(
        document_id: str, snapshot_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return repo.require_snapshot(document_id, snapshot_id)

    @app.post("/documents/{document_id}/preflight")
    def preflight_document(
        document_id: str,
        payload: PreflightRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
        require_draft_document(document, "preflight the current scene")
        try:
            source, brand_kit = choose_effective_brand(app.state.core, repo, document, payload)
            mode = choose_effective_brand_mode(document, brand_kit, payload.mode)
            result = app.state.core.preflight_scene(
                document["scene"],
                brand_kit,
                mode,
                brand_fonts=brand_kit_font_spec(
                    repo, brand_kit, blob_store(repo), request_cache_dir(repo)
                ),
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
            updated_document = _persist_preflight(
                repo,
                document_id,
                scene=result["scene"],
                diagnostics=diagnostics,
                operations=operations,
                actor_id="preflight",
                effective_brand=_effective_brand_payload(
                    source,
                    brand_kit,
                    mode,
                    persist=payload.persist_effective_brand,
                ),
            )
        else:
            _record_diagnostics(repo, document_id, "preflight", diagnostics)

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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # K3: a stateless export still shapes text with the scene's kit fonts
        # — the scene ref is the only kit signal this route carries.
        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        brand_fonts = scene_brand_fonts(repo, payload.scene, blobs, cache_dir)
        # D4 read-through: the engine resolves image pixels from its cache by digest, so every
        # asset this scene names must be materialized before the export runs (a durably-absent
        # digest is left out and the engine reports LUME0210, exactly as before).
        materialize_scene_assets(blobs, cache_dir, [payload.scene])
        try:
            result = app.state.core.export_preview(
                payload.scene,
                payload.format,
                payload.page_ids,
                payload.profile,
                raise_on_error=False,
                asset_store_root=cache_dir,
                brand_fonts=brand_fonts,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        export = result.get("export") or {}
        diagnostics = result.get("diagnostics", [])
        if not result.get("ok", False) and not diagnostics:
            diagnostics = diagnostics_from_helper_error(result.get("error"))
        # P0.3: same severity split as /documents/{id}/export. A policy lint
        # must not report a rendered preview as failed.
        status = (
            "failed"
            if not result.get("ok", False)
            or has_blocking_export_diagnostics(diagnostics)
            else "ok"
        )
        warnings = export_warning_views(diagnostics)
        log_event(
            api_logger,
            logging.INFO,
            "export_preview_completed",
            status=status,
            format=payload.format,
            page_id_count=len(payload.page_ids or []),
            advisory_diagnostics=len(warnings),
            **artifact_summary(export),
            **diagnostic_summary(diagnostics),
        )
        return {
            "schema_version": 1,
            "status": status,
            "diagnostics": diagnostics,
            "warnings": warnings,
            "export": compact_export_result(export),
        }

    # Synchronous turn preview: stores nothing, but it is an editor call like any other, so it
    # sits inside the strict seam rather than becoming a headerless hole beside /agent/turns.
    @app.post("/agent/turn-preview")
    def agent_turn_preview(
        payload: AgentTurnPreviewRequest,
        workspace_id: str = Depends(resolve_workspace_id),
    ) -> JsonObject:
        override = app.state.agent_turn_runner
        # The test seam's stubs take (payload, root); only the real runner takes the tenant,
        # which since D4 decides which engine materialization cache the turn uses.
        result = (
            override(payload, repo_root())
            if override is not None
            else run_agent_turn_preview(
                payload, repo_root(), workspace_id=workspace_id
            )
        )
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
        payload: AgentTurnPreviewRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        # D5 Round B: the turn is OFFERED, not started. The route creates the run row and its
        # ``design_job`` fleet task in one transaction and returns; a leased fleet worker (the
        # detached one, or the embedded one this app runs in development) claims and executes it.
        # The editor's contract is unchanged — it POSTs, takes ``run_id``, and subscribes to the
        # SSE stream, which polls the same durable run/event rows the worker writes through.
        #
        # RC (adversarial-gate ship-blocker 1): validate + resolve reference attachments HERE,
        # before the run row exists — inside the worker the catch-all would swallow the
        # resolver's 422s into a generic agent_runtime.failed and the client would never see
        # reference.asset_not_found / too_many / preview_unavailable. The resolved manifest rides
        # into the envelope so SVG rasterization is not paid twice.
        resolved_reference_assets = resolve_agent_turn_references(payload, blob_store(repo))
        run_id = f"run_{uuid4().hex}"
        work_id = design_work_id_for_run(run_id)
        # The FROZEN by-value work description. It captures exactly what the pre-D5 worker
        # closure captured (the request, the resolved references, the workspace) so a takeover
        # worker replays the same turn instead of re-reading state that has since moved. Brand
        # kit, fonts and the engine cache are resolved from it inside the runner, exactly as
        # before — they were never closure state.
        envelope = DesignTurnEnvelope(
            work_id=work_id,
            workspace_id=repo.workspace_id,
            kind="agent_turn",
            run_id=run_id,
            # The D5 ruling: the design run IS the LangGraph thread.
            checkpoint_thread_id=run_id,
            document_id=payload.document_id,
            config={
                "request": payload.model_dump(mode="json"),
                "reference_assets": resolved_reference_assets,
                # W4 offer-time freeze (Wave-C fix #1): the ad lane rides the envelope BY
                # VALUE, decided by THIS process's flag and database — the claiming worker
                # consumes it verbatim, so a flag-off claimant can no longer silently strip
                # the turn's auto-references (the Wave-B W-B2 failure). A frozen None is a
                # decision too: "this turn has no lane".
                "ad_lane": ad_runtime.frozen_lane_payload(repo.workspace_id),
            },
        ).model_dump(mode="json")
        # D6 Round B: the ENQUEUE is the durable mutation, so it is the tool. Everything above
        # stays in the handler on purpose — the 422-before-a-row-exists comment above is exactly
        # why a tool precondition cannot own reference resolution.
        run_design_tool(
            "design_start_agent_turn",
            {
                "run_id": run_id,
                "work_id": str(work_id),
                "document_id": payload.document_id,
                "envelope": envelope,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(payload.document_id or ""),
        )
        log_event(
            api_logger,
            logging.INFO,
            "agent_turn_offered",
            run_id=run_id,
            work_id=str(work_id),
            document_id=payload.document_id,
            active_page_id=payload.active_page_id,
            target_node_ids=payload.target_node_ids,
        )
        # ``queued`` is the honest status of a run nobody has claimed yet. The editor's
        # agentRunner.ts reads only ``run_id`` from this response, so no client behaviour changes.
        return {"schema_version": 1, "run_id": run_id, "status": "queued"}

    @app.get("/agent/runs/{run_id}")
    def get_agent_run(
        run_id: str, repo: HybridRepository = Depends(repository)
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
            "events": repo.list_run_events(run_id),
            "result": run["result"],
        }

    @app.post("/agent/runs/{run_id}/cancel")
    def cancel_agent_run(
        run_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """Ask an in-flight design run to stop (A3, defect R3-D).

        WHAT THIS DOES: stamps a durable cancellation request on the run row and returns. It does
        NOT stop anything itself. The run is driven by a fleet worker in another process, and the
        only thing this process and that one share is Postgres — so the request is a row, and the
        worker honours it.

        **THE V1 BOUNDARY, STATED PLAINLY: cancellation takes effect at the next model-call
        boundary. A call already in flight is not killed.** Python cannot interrupt the thread a
        synchronous turn body runs on (the fleet handler has said the same about its own
        cooperative stop since D5), so the honest promise is "no further model calls will be
        paid for", not "this stops right now". Worst-case latency is one model call, bounded by
        ``agent_llm_timeout_s``. If a run must die faster than that, the lever is the lease, not
        this route.

        WHAT SURVIVES: everything already durable. P0.4 commits each accepted authoring round to
        the document as it happens, so a cancelled run keeps every round it finished and loses
        only the round in flight. The worker then takes the SAME graceful-finalize path the
        budget backstop uses and lands an honest terminal result whose ``stop_reason`` is
        ``cancelled_by_request``.

        IDEMPOTENT, three honest answers, all HTTP 200 — see ``cancellation`` in the body:
        ``requested`` (the ask landed), ``already_requested`` (someone asked first; the original
        timestamp is returned unchanged), ``already_terminal`` (the run had already finished —
        not an error, just a race a human lost). A refusal here would only invite a retry loop
        against a row that will never move again.

        404 on an unknown or cross-tenant run, indistinguishable — the same fail-closed posture
        as the run snapshot and the stream-token mint above.
        """
        outcome = repo.request_run_cancellation(run_id)
        log_event(
            api_logger,
            logging.INFO,
            "agent_run_cancel_requested",
            run_id=run_id,
            outcome=outcome["outcome"],
            run_status=outcome["status"],
        )
        return {
            "schema_version": 1,
            "run_id": run_id,
            # The run's status as it stands RIGHT NOW, not what it will become. The worker owns
            # the terminal write; announcing an outcome here would be a guess, and a guess that
            # races the only writer entitled to make it.
            "status": outcome["status"],
            "cancellation": outcome["outcome"],
            "cancel_requested_at": outcome["cancel_requested_at"],
        }

    @app.post("/agent/runs/{run_id}/stream-token")
    def mint_agent_run_stream_token(
        run_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """Mint the single-use token that opens this run's event stream (D7, R-D7-B4).

        Header-authenticated like every other design route — that is the whole point. The stream
        itself cannot carry ``X-Workspace-Id`` (the browser opens it with a bare GET), and until
        D7 it took ``?workspace_id=`` instead: a tenant *claim* in a query string, strict about
        being present but unable to be strict about being true. Now the tenant is proven HERE,
        recorded on the token row, and read back out of it when the stream opens.

        404 on an unknown or cross-tenant run, indistinguishable — the same posture as the run
        snapshot above, and it is what stops an authenticated caller from holding open live tails
        against arbitrary ids.
        """
        if repo.get_run(run_id) is None:
            raise HTTPException(
                status_code=404, detail=f"agent_run {run_id} was not found"
            )
        return {
            "schema_version": 1,
            "stream_token": repo.mint_run_stream_token(run_id),
        }

    @app.get("/agent/runs/{run_id}/events")
    async def stream_agent_run_events(
        run_id: str,
        request: Request,
        stream_token: str = Query(...),
    ):
        """This run's activity, as Server-Sent Events. Token-gated; NO workspace parameter.

        The token is consumed up front — single-use, subject-bound, and the only statement of
        tenancy this route accepts. A used / expired / wrong-run / unknown token is one 401 with
        one message: they must be indistinguishable, or the refusal itself becomes an oracle for
        which runs exist.

        Framing is unchanged from the polled era (R-D7-B1): ``progress`` frames carrying
        ``{seq, type, data, created_at}`` and one terminal ``done`` frame carrying the run's result
        envelope. ``?after=`` still wins over ``Last-Event-ID``; both are now cursors into the
        platform outbox's global seq rather than a per-run counter.
        """
        try:
            token = UUID(stream_token)
        except (AttributeError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "stream.token_invalid",
                    "message": "A valid single-use stream token is required.",
                },
            ) from exc
        workspace_id = await run_stream.consume_run_stream_token_isolated(
            token=token, run_id=run_id
        )
        if workspace_id is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "stream.token_invalid",
                    "message": "A valid single-use stream token is required.",
                },
            )

        # Resume point: the streaming client re-sends Last-Event-ID on reconnect; an explicit
        # ?after= (resume-on-mount after a snapshot fetch) still takes precedence.
        header_id = request.headers.get("last-event-id")
        after_param = request.query_params.get("after")
        try:
            cursor: Optional[int] = int(
                after_param if after_param is not None else header_id or 0
            )
        except (TypeError, ValueError):
            cursor = 0

        return StreamingResponse(
            run_stream.stream_run_events(
                workspace_id=workspace_id, run_id=run_id, cursor=cursor
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/documents/{document_id}/web/turns")
    def start_web_turn(
        document_id: str,
        payload: WebTurnRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # D5 Round B: offered, not started (see start_agent_turn). The web EXECUTOR still owns
        # the persist — on an applied result it replaces the stored WebDoc through
        # update_web_document (the scene path defers the write to a separate Accept) — but it now
        # runs on a fleet worker instead of a daemon thread. Gate to web docs up front: every
        # check below happens before the run row exists, so a bad request still 4xx's the caller
        # rather than dying inside a worker where only a failed envelope would reach the editor.
        document = require_document(repo, document_id)
        require_web_document(document)
        require_draft_document(document, "start an AI turn")
        require_base_version(document, payload.base_version)
        # P5 (D6): resolve the target account BEFORE the run is created so an
        # unknown id 404s cleanly. Precedence: the request's account_id, else
        # the document row's own (a derived doc personalizes for its account
        # automatically). The card is the compact by-value context the runtime
        # gets (notes are agent-only; never a substitution value).
        account_id = payload.account_id or document.get("account_id")
        account_card: Optional[JsonObject] = None
        if account_id:
            try:
                account = repo.require_web_account(account_id)
            except NotFoundError as error:
                raise HTTPException(
                    status_code=404, detail=not_found_detail(error)
                ) from error
            account_card = {
                "name": account["name"],
                "domain": account["domain"],
                "logo_asset_id": account["logo_asset_id"],
                "data": account["data"],
                "notes": account["notes"],
            }
        run_id = f"run_{uuid4().hex}"
        work_id = design_work_id_for_run(run_id)
        # Same frozen-envelope discipline as the scene turn. ``account_card`` rides by value
        # because it was resolved (and 404'd) BEFORE the run row existed and must not be re-read
        # by a takeover worker; ``base_version`` rides because the turn is defined against one
        # exact stored revision and a retry must still refuse to clobber newer human edits.
        envelope = DesignTurnEnvelope(
            work_id=work_id,
            workspace_id=repo.workspace_id,
            kind="web_turn",
            run_id=run_id,
            checkpoint_thread_id=run_id,
            document_id=document_id,
            config={
                "request": payload.model_dump(mode="json"),
                "account_card": account_card,
            },
        ).model_dump(mode="json")
        run_design_tool(
            "design_start_web_turn",
            {
                "run_id": run_id,
                "work_id": str(work_id),
                "document_id": document_id,
                "envelope": envelope,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        log_event(
            api_logger,
            logging.INFO,
            "web_turn_offered",
            run_id=run_id,
            work_id=str(work_id),
            document_id=document_id,
        )
        return {"schema_version": 1, "run_id": run_id, "status": "queued"}

    @app.get("/documents/{document_id}/web/render")
    def render_web_document(
        document_id: str,
        request: Request,
        mode: str = "editor",
        runtime_src: Optional[str] = None,
        bridge: int = 0,
        nonce: Optional[str] = None,
        page_id: Optional[str] = None,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # Render the stored WebDoc to HTML for the editor iframe (editor mode,
        # instrumented) or a delivery snapshot. Assets resolve against this
        # request's own origin so a preview works regardless of deploy host.
        # `bridge=1&nonce=...` additionally injects the selection bridge (v0):
        # the nonce is minted by the shell per render and validated against a
        # strict charset so the interpolation can never become script
        # injection; the bridge only makes sense in editor mode.
        document = require_document(repo, document_id)
        require_web_document(document)
        web_doc = document["scene"]
        # F5: every page-shaped read below targets THIS page — `?page_id=` when the
        # caller named one, else the document's first page. Unknown page => typed 404.
        page = resolve_web_page_id(web_doc, page_id)
        brand_kit, _source, _assets, brand_fonts = resolve_web_turn_brand_kit(
            web_doc, blob_store(repo)
        )
        # Kit @font-face: emit rules that point the browser at the kit's stored
        # faces (served from the /asset-store origin the browser can reach) so the
        # editor preview renders in the brand's real fonts, not the fallback.
        font_face_css = build_web_font_face_css(brand_fonts, public_api_origin(request))
        runtime_frames: Dict[str, JsonObject] = {}
        if web_doc_uses_custom_components(web_doc, page):
            try:
                theme_response = app.state.core.web_validate(web_doc, brand_kit)
            except CoreError as error:
                raise core_http_error(error) from error
            override_variables: Dict[str, str] = {}
            account_id = document.get("account_id")
            if isinstance(account_id, str):
                try:
                    values, _records = account_values(
                        repo.require_web_account(account_id), repo
                    )
                    override_variables = {
                        key: str(value.get("value") or "")
                        for key, value in values.items()
                        if isinstance(value, dict)
                        and value.get("kind") == "text"
                    }
                except NotFoundError:
                    override_variables = {}
            runtime_frames = build_custom_component_runtime_frames(
                repo,
                blob_store(repo),
                account_id=account_id if isinstance(account_id, str) else None,
                web_doc=web_doc,
                page_id=page,
                theme=theme_response.get("web_theme"),
                override_variables=override_variables,
                runtime_host_path=Path(app.state.custom_component_runtime_host),
            )
        bridge_script = None
        if bridge:
            if mode != "editor":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "web_render.bridge_mode",
                        "message": "the selection bridge is editor-mode only",
                    },
                )
            try:
                # R-A5: the same registry facts the GET route serves as `fragment_meta`,
                # so the hover chip inside the iframe names a cloned band with the exact
                # words the layers panel does. Read only for a bridge render — a
                # delivery snapshot has no chip to name.
                bridge_script = render_bridge_script(
                    nonce or "",
                    web_doc,
                    page,
                    fragment_meta=fragment_meta_for_document(
                        document, repo.list_web_fragments()
                    ),
                )
            except ValueError as error:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "web_render.bad_nonce", "message": str(error)},
                ) from error
        asset_base_url = public_api_origin(request) + "/asset-store"
        # F1.3: resolve the page's cloned-section artifacts out of durable custody and hand the
        # engine the markup map + the concatenated scoped CSS. An id that will not resolve is
        # left OUT of the map on purpose — the engine renders its placeholder and says so
        # (LUMW0412), which is what keeps a document with a dead pin editable.
        fragment_ids = web_doc_fragment_ids(web_doc, page)
        fragment_package = (
            build_fragment_render_package(
                app.state.storage,
                workspace_id=store_workspace_id(repo),
                web_doc=web_doc,
                page_id=page,
            )
            if fragment_ids
            else empty_fragment_render_package()
        )
        try:
            response = app.state.core.web_render(
                web_doc,
                page,
                mode=mode,
                asset_base_url=asset_base_url,
                tailwind_runtime_src=runtime_src,
                bridge_script=bridge_script,
                custom_component_runtimes=runtime_frames,
                brand_kit=brand_kit,
                font_face_css=font_face_css,
                # The artifact's OWN byte references are rebased onto THIS request's origin
                # (F1.5 fix wave): they are stored root-relative, which the editor's srcDoc
                # iframe has no origin to resolve, so every image inside a cloned section
                # rendered broken while slot-bound assets — which go through the engine's
                # asset_base_url — worked.
                fragments=fragment_render_map(
                    fragment_package, fragment_ids, asset_base_url=asset_base_url
                ),
                fragment_css=fragment_css_sheet(
                    fragment_package, fragment_ids, asset_base_url=asset_base_url
                ),
            )
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = list(response.get("diagnostics", []))
        # The ledgered cascade risk, reported not refused: compiled utilities land after fragment
        # CSS, so a cloned class the document also authors is overruled.
        diagnostics.extend(
            fragment_collision_diagnostics(fragment_package, web_doc, page)
        )
        return {
            "schema_version": 1,
            "html": response.get("html"),
            "diagnostics": diagnostics,
        }

    @app.get("/documents/{document_id}/thumbnail", response_class=Response)
    def get_document_thumbnail(
        document_id: str,
        request: Request,
        v: Optional[str] = None,
        repo: HybridRepository = Depends(repository),
    ) -> Response:
        # Gallery-card preview (2026-08-31 ruling): PNG for both kinds, built
        # LAZILY here on first read — never in the write path — and cached by
        # (document, version) in the blob store. Sync route => threadpool, so the
        # Playwright capture blocks a worker thread, not the event loop (NOT the
        # [slice3xstage0] class of bug).
        document = require_document(repo, document_id)
        version = int(document["current_version"])
        blobs = blob_store(repo)

        cached = repo.get_document_thumbnail(document_id, version)
        data: Optional[bytes] = None
        if cached is not None:
            try:
                _media, data = blobs.read_blob(cached["sha256"])
            except NotFoundError:
                data = None  # dangling index row — regenerate below

        if data is None:
            # The KIND decides the generator, never the shape of the payload: a
            # scene's pages are a map and a web doc's are a list, and the scene
            # page picker answers None on a list QUIETLY, so shape-sniffing would
            # mis-route without ever erroring. Same default as the two
            # `require_*_document` gates.
            kind = document.get("doc_kind", "scene")
            try:
                if kind == "web":
                    # Called in-process so the composed HTML carries THIS request's
                    # origin for its asset URLs — the capture page fetches them.
                    rendered = render_web_document(
                        document_id,
                        request,
                        mode="editor",
                        runtime_src=None,
                        bridge=0,
                        nonce=None,
                        repo=repo,
                    )
                    html = rendered.get("html")
                    if not isinstance(html, str) or not html:
                        # A render that returned no html would screenshot the
                        # literal text "None" and CACHE it under this version —
                        # a poisoned card that never expires. Refuse instead.
                        raise document_thumbnails.ThumbnailUnavailable(
                            "thumbnail.render_failed", "web render returned no html"
                        )
                    data = document_thumbnails.web_thumbnail_png(html)
                else:
                    scene = document["scene"]
                    cache_dir = request_cache_dir(repo)
                    materialize_scene_assets(blobs, cache_dir, [scene])
                    # 2026-09-06: render what the editor and the export show, not the
                    # raw stored scene. Agent-authored ads carry brand TOKENS and
                    # hug/fill sizes with no stored geometry; exported raw they fail
                    # LUME0209 / LUME0205 on every node and the PNG came back white
                    # — a 200 with nothing in it. So: the document's effective brand
                    # (the export route's own chooser, default request = the pinned
                    # kit, platform default as the last resort), its mode and fonts,
                    # one preflight, and the PREFLIGHTED scene goes to the renderer.
                    # Best-effort by contract — preflight diagnostics are logged,
                    # never a refusal (a card is a preview, not a deliverable) — and
                    # READ-ONLY: nothing here persists (no `_persist_preflight`),
                    # keeping the route's never-in-the-write-path rule.
                    source, brand_kit = choose_effective_brand(
                        app.state.core,
                        repo,
                        document,
                        PreflightRequest(persist_effective_brand=False),
                    )
                    mode = choose_effective_brand_mode(document, brand_kit, None)
                    brand_fonts = (
                        brand_kit_font_spec(repo, brand_kit, blobs, cache_dir)
                        if brand_kit is not None
                        else scene_brand_fonts(repo, scene, blobs, cache_dir)
                    )
                    preflight_result = app.state.core.preflight_scene(
                        scene, brand_kit, mode, brand_fonts=brand_fonts
                    )
                    preflight_diagnostics = preflight_result.get("diagnostics", [])
                    log_event(
                        api_logger,
                        logging.INFO,
                        "document_thumbnail_preflight",
                        document_id=document_id,
                        version=version,
                        effective_brand_source=source,
                        **diagnostic_summary(preflight_diagnostics),
                    )
                    export_scene = preflight_result.get("scene") or scene
                    result = app.state.core.export_preview(
                        export_scene,
                        "png",
                        document_thumbnails.first_page_ids(export_scene),
                        default_export_profile("png"),
                        raise_on_error=False,
                        asset_store_root=cache_dir,
                        brand_fonts=brand_fonts,
                    )
                    data = document_thumbnails.downscale_png(
                        document_thumbnails.png_from_export_result(result)
                    )
            except document_thumbnails.ThumbnailUnavailable as error:
                raise HTTPException(
                    status_code=502,
                    detail={"code": error.code, "message": str(error)},
                ) from error
            except (CoreError, NotFoundError) as error:
                # The helper can fail BEFORE `raise_on_error` is consulted (a dead
                # subprocess, an unparseable response), so `raise_on_error=False`
                # above does not make this unreachable — `/export-preview` catches
                # CoreError for the same reason. A thumbnail's contract is 502
                # `thumbnail.*`, so it is normalized here rather than left to
                # `core_http_error`'s 422.
                # `NotFoundError` (a KeyError, NOT a CoreError) joins it because the
                # scene branch's `choose_effective_brand` reads the brand-kit library:
                # a document pinned to a kit version that is gone would otherwise
                # escape as an untyped 500.
                raise HTTPException(
                    status_code=502,
                    detail={
                        # Kind-aware: only the scene branch exports. A CoreError from
                        # the web branch escaped a RENDER, so labelling it
                        # `export_failed` would name a step that never ran.
                        "code": (
                            "thumbnail.render_failed"
                            if kind == "web"
                            else "thumbnail.export_failed"
                        ),
                        "message": str(error),
                    },
                ) from error
            except HTTPException as error:
                # The in-process `render_web_document` above answers ITS OWN
                # failures with `core_http_error`'s 422 `web_render.*`, which
                # would otherwise escape this route as a 422 the frozen contract
                # never promises. Catching HTTPException broadly is safe HERE and
                # only here: the 404 (`require_document`) is raised ABOVE this try,
                # and the render call is the only thing inside it that raises one.
                # DO NOT widen this try upward — it would swallow the 404.
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "thumbnail.render_failed",
                        "message": str(error.detail),
                    },
                ) from error
            sha256 = hashlib.sha256(data).hexdigest()
            # `register` returns the workspace-scoped STORAGE KEY; the index row and
            # `read_blob` both speak the bare digest, which registration is addressed
            # by, so the local one is the authoritative spelling.
            blobs.register(data, media_type="image/png", source_key="document_thumbnail")
            repo.record_document_thumbnail(
                document_id, version, sha256=sha256, media_type="image/png"
            )
            log_event(
                api_logger,
                logging.INFO,
                "document_thumbnail_generated",
                document_id=document_id,
                version=version,
                kind=kind,
                byte_count=len(data),
            )

        # A caller that named the version it wants may cache the answer forever —
        # the key changes on the next edit. Anyone else gets the current bytes and
        # no permission to keep them under a key that does not identify them.
        fresh = v == str(version)
        return Response(
            content=data,
            media_type="image/png",
            headers={
                "Cache-Control": (
                    "private, max-age=31536000, immutable" if fresh else "no-store"
                )
            },
        )

    def _refuse_dead_override_paths(
        repo: HybridRepository, web_doc: JsonObject, operations: List[JsonObject]
    ) -> None:
        """Spec §3.6: "a path that does not resolve in the fragment's HTML at apply time is
        refused".

        The ENGINE checks only that an override's path is a *structural* address
        (`op.override_path_invalid`); whether it lands on anything is a question about the
        artifact's markup, which the op arena has never read. Nobody else asks it either — the
        render pass keeps the clone's own words and warns — so an override stored against a
        dead path is a human edit that silently does nothing. This is where it is caught.

        Only a SET is checked. A clear (`override` absent or null) is the human taking their
        edit back, and refusing that because the address has since died would trap the override
        in the document with no way out. Anything else the op names wrongly — a missing node, a
        node that is not a clone, a fragment this workspace cannot read — is left to the
        engine's own refusal codes rather than pre-empted here in different words.
        """
        pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
        if not isinstance(pages, list):
            return
        sources: Dict[str, Optional[JsonObject]] = {}
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            if operation.get("kind") != "set_fragment_text_override":
                continue
            if operation.get("override") is None:
                continue
            path = operation.get("path")
            node_id = operation.get("id")
            page_id = operation.get("page_id")
            if not isinstance(path, str) or not isinstance(node_id, str):
                continue
            page = next(
                (
                    candidate
                    for candidate in pages
                    if isinstance(candidate, dict) and candidate.get("id") == page_id
                ),
                None,
            )
            nodes = page.get("nodes") if isinstance(page, dict) else None
            node = nodes.get(node_id) if isinstance(nodes, dict) else None
            if not isinstance(node, dict) or node.get("kind") != "fragment":
                continue
            fragment_id = node.get("fragment_id")
            if not isinstance(fragment_id, str) or not fragment_id:
                continue
            if fragment_id not in sources:
                try:
                    loaded = read_web_fragment(
                        app.state.storage,
                        workspace_id=store_workspace_id(repo),
                        fragment_id=fragment_id,
                    )
                    sources[fragment_id] = loaded.payload
                except Exception:
                    # An unreadable artifact is not this check's refusal to make: the pin may be
                    # one the gate already tolerates (an existing dead reference), and the write
                    # path will say so in its own words.
                    sources[fragment_id] = None
            payload = sources[fragment_id]
            if payload is None:
                continue
            resolved = resolve_structural_path(
                str(payload.get("html") or ""),
                path,
                hidden_slot_keys=_fragment_hidden_slot_keys(node),
            )
            if resolved is not None:
                continue
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "web_operations.invalid",
                    "engine_code": "op.override_path_unresolved",
                    "message": (
                        f"the text override path `{path}` does not resolve to an element in "
                        f"the cloned section pinned at node `{node_id}` — the band was probably "
                        "regenerated after the edit was made"
                    ),
                    "diagnostics": [],
                },
            )

    @app.post("/documents/{document_id}/web/operations")
    def apply_web_operations(
        document_id: str,
        payload: WebOperationsRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # Manual website-mode edit: run the batch through the checked-apply
        # helper (a batch that would leave the doc invalid is rejected with
        # ok:false + diagnostics — the mutated doc is never returned) and, on
        # success, persist the new doc + its inverse as an undoable envelope.
        if not payload.operations:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "web_operations.empty",
                    "message": "operations cannot be empty",
                },
            )
        document = require_document(repo, document_id)
        require_web_document(document)
        require_draft_document(document, "apply operations")
        require_base_version(document, payload.base_version)
        web_doc = document["scene"]
        _refuse_dead_override_paths(repo, web_doc, payload.operations)
        try:
            result = app.state.core.web_apply_ops(
                web_doc, payload.operations, raise_on_error=False
            )
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = result.get("diagnostics", []) or []
        if not result.get("ok"):
            error = result.get("error") or {}
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "web_operations.invalid",
                    # The envelope code stays the one flattened code every existing
                    # client branches on; the engine's OWN refusal code (e.g.
                    # `op.route_invalid`, `op.route_exists`) rides alongside it so a
                    # caller can tell WHICH refusal this was without parsing prose.
                    "engine_code": error.get("code"),
                    "message": error.get("message")
                    or "the operation batch would leave the document invalid",
                    "diagnostics": diagnostics,
                },
            )
        try:
            run_design_tool(
                "design_apply_web_operations",
                {
                    "document_id": document_id,
                    "web_doc": result["web_doc"],
                    "operations": payload.operations,
                    "inverse_operations": result.get("inverse_operations"),
                    "intent": payload.intent or "Manual edit",
                    "checkpoint_label": "Manual edit",
                    "actor_kind": "editor",
                    "source": "editor",
                    "expected_base_version": payload.base_version,
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
        except WebDocumentVersionConflict as conflict:
            raise _base_version_conflict(conflict) from conflict
        updated = repo.require_document(document_id)
        log_event(
            api_logger,
            logging.INFO,
            "web_operation_batch_applied",
            document_id=document_id,
            operation_count=len(payload.operations),
            applied_operations=result.get("applied_operations", 0),
            version=updated["current_version"],
            **diagnostic_summary(diagnostics),
        )
        return {
            "schema_version": 1,
            "document": {
                "id": updated["id"],
                "current_version": updated["current_version"],
                "doc_kind": updated.get("doc_kind", "web"),
            },
            "diagnostics": diagnostics,
        }

    def _apply_web_undo_step(
        repo: HybridRepository, document: JsonObject, target: JsonObject
    ) -> JsonObject:
        """Compute the pre-undo → reverted WebDoc for one undo, handling both
        envelope shapes: a legacy whole-document `replace_web_doc` marker swaps
        in the inverse's carried doc directly; a current WebOperation batch
        replays its inverse_operations through the checked-apply helper. Returns
        {web_doc, inverse_operations} where inverse_operations is the forward op
        set that a future redo re-applies (a replace_web_doc carrying the
        pre-undo doc, or the envelope's own forward operations)."""
        current_doc = document["scene"]
        inverse_ops = target["inverse_operations"]
        if _is_replace_web_doc(inverse_ops):
            # Legacy agent-turn envelope: the inverse carries the prior whole doc, so
            # the undo is a whole-document swap. The revert envelope records the
            # restored doc as its forward op and the pre-undo doc as its inverse
            # (so redo can reinstall doc-after-B via this envelope's inverse).
            restored = inverse_ops[0]["web_doc"]
            return {
                "web_doc": restored,
                "operations": [{"kind": "replace_web_doc", "web_doc": restored}],
                "inverse_operations": [
                    {"kind": "replace_web_doc", "web_doc": current_doc}
                ],
            }
        try:
            result = app.state.core.web_apply_ops(
                current_doc, inverse_ops, raise_on_error=False
            )
        except CoreError as error:
            raise core_http_error(error) from error
        if not result.get("ok"):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "web_history.not_invertible",
                    "message": (
                        f"inverse of batch {target['batch_id']} could not be "
                        "applied cleanly and blocks undo"
                    ),
                    "diagnostics": result.get("diagnostics", []) or [],
                },
            )
        # The revert envelope applied the inverse ops; a redo of THIS revert
        # would re-apply the original batch's forward operations.
        return {
            "web_doc": result["web_doc"],
            "operations": inverse_ops,
            "inverse_operations": target["operations"],
        }

    @app.post("/documents/{document_id}/web/undo")
    def undo_web_document(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_web_document(document)
        require_draft_document(document, "undo")
        undo_stack = list(document.get("undo_stack") or [])
        if not undo_stack:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "undo.empty",
                    "message": "no undoable batches in document history",
                },
            )
        target = repo.require_envelope(document_id, undo_stack[-1])
        if target["inverse_operations"] is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "undo.not_invertible",
                    "message": (
                        f"batch {target['batch_id']} ({target['intent'] or 'unknown'}) "
                        "is not invertible and blocks undo"
                    ),
                    "batch_id": target["batch_id"],
                },
            )
        step = _apply_web_undo_step(repo, document, target)
        try:
            run_design_tool(
                "design_undo_web_document",
                {
                    "document_id": document_id,
                    "web_doc": step["web_doc"],
                    "operations": step["operations"],
                    "inverse_operations": step["inverse_operations"],
                    "intent": f"undo:{target['intent'] or target['batch_id']}",
                    "batch_id": target["batch_id"],
                    "expected_base_version": document["current_version"],
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
            updated = repo.require_document(document_id)
        except WebDocumentVersionConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "edits.base_version_mismatch",
                    "message": (
                        "the website changed while undo was being prepared; "
                        "reload and try again"
                    ),
                    "current_version": conflict.current,
                },
            ) from conflict
        log_event(
            api_logger,
            logging.INFO,
            "web_undo_applied",
            document_id=document_id,
            reverted_batch_id=target["batch_id"],
            version=updated["current_version"],
        )
        return {
            "schema_version": 1,
            "document": {
                "id": updated["id"],
                "current_version": updated["current_version"],
            },
            "undone_batch_id": target["batch_id"],
        }

    @app.post("/documents/{document_id}/web/redo")
    def redo_web_document(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_web_document(document)
        require_draft_document(document, "redo")
        redo_stack = list(document.get("redo_stack") or [])
        if not redo_stack:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "redo.empty",
                    "message": "no redoable batches in document history",
                },
            )
        target = repo.require_envelope(document_id, redo_stack[-1])
        current_doc = document["scene"]
        forward_ops = target["operations"]
        if _has_replace_web_doc_kind(forward_ops):
            # Legacy agent-turn redo: the batch's forward op is a bare replace_web_doc
            # MARKER (no doc payload — web_apply_ops does not understand it), so
            # reinstall the doc it originally installed as a whole-document swap.
            # A marker carries no doc; the doc lives in the revert envelope's
            # inverse_operations (written when this batch was undone). A full
            # replace_web_doc that already carries its doc is used directly.
            restored = _replace_web_doc_payload(forward_ops)
            if restored is None:
                reverting = _web_revert_envelope_for(
                    repo, document_id, target["batch_id"]
                )
                restored = _replace_web_doc_payload(reverting["inverse_operations"])
            if restored is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "redo.not_reapplicable",
                        "message": (
                            f"batch {target['batch_id']} cannot be re-applied; its "
                            "forward document snapshot is unavailable"
                        ),
                    },
                )
            new_doc = restored
            inverse_ops = [{"kind": "replace_web_doc", "web_doc": current_doc}]
        else:
            try:
                result = app.state.core.web_apply_ops(
                    current_doc, forward_ops, raise_on_error=False
                )
            except CoreError as error:
                raise core_http_error(error) from error
            if not result.get("ok"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "redo.not_reapplicable",
                        "message": (
                            f"batch {target['batch_id']} could not be re-applied "
                            "cleanly"
                        ),
                        "diagnostics": result.get("diagnostics", []) or [],
                    },
                )
            new_doc = result["web_doc"]
            inverse_ops = result.get("inverse_operations")
        try:
            run_design_tool(
                "design_redo_web_document",
                {
                    "document_id": document_id,
                    "web_doc": new_doc,
                    "operations": forward_ops,
                    "inverse_operations": inverse_ops,
                    "intent": f"redo:{target['intent'] or target['batch_id']}",
                    "batch_id": target["batch_id"],
                    "expected_base_version": document["current_version"],
                },
                workspace_id=store_workspace_id(repo),
                refusals=_document_refusals(document_id),
            )
            updated = repo.require_document(document_id)
        except WebDocumentVersionConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "edits.base_version_mismatch",
                    "message": (
                        "the website changed while redo was being prepared; "
                        "reload and try again"
                    ),
                    "current_version": conflict.current,
                },
            ) from conflict
        log_event(
            api_logger,
            logging.INFO,
            "web_redo_applied",
            document_id=document_id,
            reapplied_batch_id=target["batch_id"],
            version=updated["current_version"],
        )
        return {
            "schema_version": 1,
            "document": {
                "id": updated["id"],
                "current_version": updated["current_version"],
            },
            "reapplied_batch_id": target["batch_id"],
        }

    @app.get("/documents/{document_id}/web/theme")
    def get_web_theme(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        # The compiled theme's inspector surface: the resolved token map +
        # families the editor's Appearance panel reads. Diagnostics are the
        # error-severity ones only — a sanity surface, not the full lint.
        document = require_document(repo, document_id)
        require_web_document(document)
        web_doc = document["scene"]
        brand_kit, _source, _assets, _fonts = resolve_web_turn_brand_kit(
            web_doc, blob_store(repo)
        )
        try:
            response = app.state.core.web_validate(web_doc, brand_kit)
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = [
            diagnostic
            for diagnostic in response.get("diagnostics", []) or []
            if diagnostic.get("severity") == "error"
        ]
        return {
            "schema_version": 1,
            "theme": response.get("web_theme"),
            "diagnostics": diagnostics,
        }

    @app.get("/documents/{document_id}/web/export")
    def export_web_document(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> Response:
        # Build a self-contained static-site zip (delivery html + statically
        # compiled site.css + embedded fonts + copied image bytes + SEO +
        # manifest). A compile failure fails the request honestly (502) rather
        # than shipping an unstyled zip.
        document = require_document(repo, document_id)
        require_web_document(document)
        try:
            bundle = web_export.build_export_bundle(
                app.state.core,
                repo,
                document,
                blobs=blob_store(repo),
                generated_at=utc_now(),
                node_bin=app.state.web_export_node_bin,
            )
        except web_export.WebExportCompileError as error:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "web_export.compile_failed",
                    "message": error.stderr or "static css compile failed",
                },
            ) from error
        except web_export.WebExportError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "web_export.failed", "message": str(error)},
            ) from error

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.files):
                archive.writestr(path, bundle.files[path])
        buffer.seek(0)
        filename = f"{web_slugify(document['title'])}-{document_id[:8]}.zip"
        log_event(
            api_logger,
            logging.INFO,
            "web_export_completed",
            document_id=document_id,
            file_count=len(bundle.files),
            warning_count=len(bundle.warnings),
        )
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/documents/{document_id}/web/export.pdf")
    def export_web_document_pdf(
        document_id: str,
        repo: HybridRepository = Depends(repository),
    ) -> Response:
        # The whole SITE as one PDF: every page rendered by Chromium from the same
        # delivery bytes a publish would serve, concatenated in document order.
        # Nothing is persisted — no revision, no pointer — so exporting a PDF never
        # puts a site on the air. A render or compile failure fails the request
        # honestly (502) rather than shipping a blank or unstyled document.
        document = require_document(repo, document_id)
        require_web_document(document)
        try:
            content = web_pdf.build_web_pdf(
                app.state.core,
                repo,
                document,
                blobs=blob_store(repo),
                workspace_id=store_workspace_id(repo),
                node_bin=app.state.web_export_node_bin,
                runtime=document_thumbnails.resolve_tailwind_runtime(),
            )
        except web_pdf.WebPdfUnavailable as error:
            raise HTTPException(
                status_code=502,
                detail={"code": error.code, "message": str(error)},
            ) from error
        except web_export.WebExportCompileError as error:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "web_export.compile_failed",
                    "message": error.stderr or "static css compile failed",
                },
            ) from error
        except web_export.WebExportError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "web_export.failed", "message": str(error)},
            ) from error

        filename = f"{web_slugify(document['title'])}-{document_id[:8]}.pdf"
        log_event(
            api_logger,
            logging.INFO,
            "web_pdf_export_completed",
            document_id=document_id,
            byte_count=len(content),
        )
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def _publish_refusals(slug: str, document_id: str) -> Dict[str, Any]:
        """The exact wire contract the editor has always seen for a refused publish.

        The document refusals are defence in depth: the HTTP route resolves and kind-checks the
        document itself (it needs the title for the default slug), so only a non-HTTP caller —
        the batch loop, or a future agent — can reach them.
        """
        return {
            "design_publish_slug_invalid": lambda message: HTTPException(
                status_code=422,
                detail={"code": "web_publish.bad_slug", "message": message},
            ),
            "design_publish_slug_taken": lambda message: HTTPException(
                status_code=409,
                detail={"code": "web_publish.slug_taken", "message": message},
            ),
            "design_document_not_found": lambda _message: NotFoundError(
                "document", document_id
            ),
            "design_document_not_web": lambda message: HTTPException(
                status_code=409,
                detail={"code": "document.kind_unsupported", "message": message},
            ),
        }

    def _publish_web(
        repo: HybridRepository,
        document: JsonObject,
        *,
        slug: str,
        idempotency_key: Optional[str] = None,
        noindex: bool = False,
    ) -> JsonObject:
        """Publish through the governed tool. The ONE call site shape for both callers.

        The node static-css compile lives inside the tool; its two honest failures still surface
        as the pre-D6 502s (the tool re-raises them, the journal records the failed attempt).

        ``noindex`` (clone-fidelity F4.3, ruling R25-4) is a PER-PAGE option, defaulting off:
        the batch's ABM account pages ask for it and nothing else does, so an ordinary homepage
        publish is byte-identical to what it produced before this task.
        """
        try:
            return run_design_tool(
                "design_publish_web",
                {
                    "document_id": document["id"],
                    "slug": slug,
                    "noindex": noindex,
                },
                workspace_id=store_workspace_id(repo),
                idempotency_key=idempotency_key,
                refusals=_publish_refusals(slug, document["id"]),
            )
        except web_export.WebExportUnresolvedMarkers as error:
            # R25-7: the un-derived TEMPLATE renders its `{{account.…}}` markers to a visitor.
            # A 422, not a 502: nothing broke — the wrong document was handed to publish, and the
            # right one is one derive away.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "web_publish.unresolved_markers",
                    "message": str(error),
                    "markers": list(error.markers),
                },
            ) from error
        except web_export.WebExportCompileError as error:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "web_export.compile_failed",
                    "message": error.stderr or "static css compile failed",
                },
            ) from error
        except web_export.WebExportError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "web_export.failed", "message": str(error)},
            ) from error

    @app.post("/documents/{document_id}/web/publish")
    def publish_web_document(
        document_id: str,
        payload: WebPublishRequest,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_web_document(document)
        slug = (payload.slug or "").strip() or web_default_slug(
            document["title"], document_id
        )
        publish = _publish_web(
            repo,
            document,
            slug=slug,
            idempotency_key=idempotency_key,
            noindex=payload.noindex,
        )
        log_event(
            api_logger,
            logging.INFO,
            "web_publish_completed",
            document_id=document_id,
            slug=slug,
            doc_version=publish["doc_version"],
        )
        address = site_address(repo, slug)
        custom = custom_site_address(repo, slug)
        routes = list(publish.get("routes") or []) or ["/"]
        return {
            "schema_version": 1,
            "slug": slug,
            "url": address.page_url("/"),
            "custom_url": None if custom is None else custom.page_url("/"),
            "public_origin": address.origin,
            "custom_origin": None if custom is None else custom.origin,
            "doc_version": publish["doc_version"],
            "runtime_version": publish["runtime_version"],
            "publish_id": publish["publish_id"],
            "manifest_digest": publish.get("manifest_digest"),
            "package_digest": publish.get("package_digest"),
            "html_digest": publish.get("html_digest"),
            "previous_available": publish["previous_available"],
            # F5: every route this publish just put on the air, in document order.
            "routes": list(publish.get("routes") or []),
            # F5/R-F5-1: and their ABSOLUTE addresses, built by the ONE builder that knows where
            # sites live (the hostname registry). The share menu shows exactly these — joining a
            # site root to a route is the server's job, so the links the marketer copies move
            # with the workspace's addresses. One map per origin: the always-live system
            # hostname, and the active custom domain when there is one.
            "page_urls": {route: address.page_url(route) for route in routes},
            "custom_page_urls": (
                {} if custom is None else {route: custom.page_url(route) for route in routes}
            ),
        }

    @app.get("/documents/{document_id}/web/publish")
    def get_web_publish_state(
        document_id: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_web_document(document)
        publish = repo.get_web_publish_for_document(document_id)
        if publish is None:
            # Even unpublished, the state names WHERE this document would publish — the
            # workspace's always-live system origin, and its custom origin when it has one.
            return {
                "schema_version": 1,
                "published": False,
                "public_origin": system_public_origin(repo),
                "custom_origin": custom_public_origin(repo),
            }
        # F5/R-F5-1: the site's public address, from the hostname registry — never the request.
        address = site_address(repo, publish["slug"])
        custom = custom_site_address(repo, publish["slug"])
        pages = repo.list_web_publish_pages(publish["slug"])
        # A pre-F5 publish has no page rows and still serves its one page at `/`.
        routes = [page["route"] for page in pages] or ["/"]
        return {
            "schema_version": 1,
            "published": True,
            "slug": publish["slug"],
            "url": address.page_url("/"),
            "custom_url": None if custom is None else custom.page_url("/"),
            "public_origin": address.origin,
            "custom_origin": None if custom is None else custom.origin,
            "doc_version": publish["doc_version"],
            "status": publish["status"],
            "publish_id": publish.get("publish_id"),
            "manifest_digest": publish.get("manifest_digest"),
            "package_digest": publish.get("package_digest"),
            "html_digest": publish.get("html_digest"),
            "previous_available": publish["previous_html"] is not None,
            "updated_at": publish["updated_at"],
            # F5: the routes the SITE currently serves — route/page_id/html_digest, no markup.
            # A pre-F5 publish has no page rows and answers with an empty list; it still serves
            # its single page at `/` from the publish row's own html.
            "pages": pages,
            # F5: the absolute address of EVERY route this site serves. The editor shows exactly
            # these — there is no host constant on the client. One map per origin.
            "page_urls": {route: address.page_url(route) for route in routes},
            "custom_page_urls": (
                {} if custom is None else {route: custom.page_url(route) for route in routes}
            ),
        }

    def _publish_not_found(slug: str) -> HTTPException:
        return HTTPException(
            status_code=404,
            detail={
                "code": "web_publish.not_found",
                "message": f"no publish for slug {slug!r}",
            },
        )

    @app.delete("/web/publishes/{slug}")
    def unpublish_web_document(
        slug: str,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        publish = run_design_tool(
            "design_unpublish_web",
            {"slug": slug},
            workspace_id=store_workspace_id(repo),
            idempotency_key=idempotency_key,
            refusals={
                "design_publish_not_found": lambda _m: _publish_not_found(slug),
            },
        )
        log_event(
            api_logger,
            logging.INFO,
            "web_publish_unpublished",
            slug=slug,
        )
        return {"schema_version": 1, "slug": slug, "status": publish["status"]}

    @app.post("/web/publishes/{slug}/rollback")
    def rollback_web_document(
        slug: str,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        # D6: rollback is a current<->previous SWAP, so a blind retry is actively destructive —
        # this is THE design route an `Idempotency-Key` matters most on. With one, the journal's
        # terminal node + the A9 record replay the first outcome instead of swapping back.
        result = run_design_tool(
            "design_rollback_web_publish",
            {"slug": slug},
            workspace_id=store_workspace_id(repo),
            idempotency_key=idempotency_key,
            refusals={
                "design_publish_not_found": lambda _m: _publish_not_found(slug),
                "design_publish_no_previous": lambda message: HTTPException(
                    status_code=409,
                    detail={"code": "web_publish.no_previous", "message": message},
                ),
            },
        )
        log_event(
            api_logger,
            logging.INFO,
            "web_publish_rolled_back",
            slug=slug,
            document_id=result["document_id"],
            publish_id=result.get("publish_id"),
            package_digest=result.get("package_digest"),
        )
        return {
            "schema_version": 1,
            "slug": slug,
            "doc_version": result["doc_version"],
            "status": result["status"],
            "publish_id": result.get("publish_id"),
            "manifest_digest": result.get("manifest_digest"),
            "package_digest": result.get("package_digest"),
            "html_digest": result.get("html_digest"),
        }

    # --- P5 personalization accounts (D3) --------------------------------- #

    def _account_refusals(account_id: str, logo_asset_id: Optional[str]) -> Dict[str, Any]:
        """The ported ``_require_logo_resolves`` / duplicate-id wire contracts (D3 → 422/409)."""
        return {
            "design_account_exists": lambda message: HTTPException(
                status_code=409,
                detail={
                    "code": "web_account.exists",
                    "message": message,
                    "resource_id": account_id,
                },
            ),
            "design_account_logo_unresolved": lambda message: HTTPException(
                status_code=422,
                detail={
                    "code": "web_account.logo_unresolved",
                    "message": message,
                    "resource_id": logo_asset_id,
                },
            ),
            "design_account_not_found": lambda _message: NotFoundError(
                "web_account", account_id
            ),
        }

    @app.post("/web/accounts")
    def create_web_account(
        payload: CreateWebAccountRequest,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        # D6: the id is minted HERE when the client omits one, so the tool's durable identity is
        # always one its caller named — which is what makes `design_create_web_account`
        # domain-idempotent (R-D6-3) instead of an unkeyed write.
        account_id = payload.account_id or new_web_account_id()
        run_design_tool(
            "design_create_web_account",
            {
                "account_id": account_id,
                "name": payload.name,
                "domain": payload.domain,
                "logo_asset_id": payload.logo_asset_id,
                "data": dict(payload.data),
                "notes": payload.notes,
            },
            workspace_id=store_workspace_id(repo),
            idempotency_key=idempotency_key,
            refusals=_account_refusals(account_id, payload.logo_asset_id),
        )
        log_event(
            api_logger,
            logging.INFO,
            "web_account_created",
            account_id=account_id,
            has_logo=payload.logo_asset_id is not None,
        )
        # The tool returns references; the account DTO the editor reads is re-read from the row
        # the tool just wrote (same `require_web_account` projection `create_web_account`
        # returned pre-D6, so the response body is unchanged).
        return repo.require_web_account(account_id)

    @app.get("/web/accounts")
    def list_web_accounts(repo: HybridRepository = Depends(repository)) -> JsonObject:
        return {"accounts": repo.list_web_accounts()}

    @app.get("/web/accounts/{account_id}")
    def get_web_account(
        account_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        try:
            return repo.require_web_account(account_id)
        except NotFoundError as error:
            raise HTTPException(
                status_code=404, detail=not_found_detail(error)
            ) from error

    @app.get("/web/accounts/{account_id}/custom-components")
    def list_custom_components(
        account_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """List account-local component families without exposing another tenant."""
        repo.require_web_account(account_id)
        components = repo.list_custom_components(account_id)
        for component in components:
            latest_id = component.get("latest_artifact_id")
            component["latest_artifact"] = (
                repo.require_custom_component_artifact(account_id, latest_id)
                if isinstance(latest_id, str)
                else None
            )
        return {
            "schema_version": 1,
            "account_id": account_id,
            "components": components,
        }

    @app.get("/web/accounts/{account_id}/custom-components/{slug}")
    def get_custom_component(
        account_id: str,
        slug: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        repo.require_web_account(account_id)
        return {
            "schema_version": 1,
            "component": repo.require_custom_component(account_id, slug),
        }

    @app.get(
        "/web/accounts/{account_id}/custom-component-artifacts/{artifact_id}"
    )
    def get_custom_component_artifact(
        account_id: str,
        artifact_id: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        repo.require_web_account(account_id)
        return {
            "schema_version": 1,
            "artifact": repo.require_custom_component_artifact(
                account_id, artifact_id
            ),
        }

    @app.get(
        "/web/accounts/{account_id}/custom-component-artifacts/"
        "{artifact_id}/{member}"
    )
    def get_custom_component_artifact_member(
        account_id: str,
        artifact_id: str,
        member: str,
        repo: HybridRepository = Depends(repository),
    ) -> Response:
        if member not in {"source", "bundle", "css", "first_frame"}:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "custom_component.artifact_member_not_found",
                    "message": f"unknown custom component artifact member {member!r}",
                },
            )
        artifact = repo.require_custom_component_artifact(
            account_id, artifact_id
        )
        if artifact[member] is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "custom_component.artifact_member_not_found",
                    "message": (
                        f"custom component artifact {artifact_id!r} has no "
                        f"{member!r} member"
                    ),
                },
            )
        _, data = resolve_custom_component_artifact_blob(
            repo,
            blob_store(repo),
            account_id=account_id,
            artifact_id=artifact_id,
            member=member,  # type: ignore[arg-type]
        )
        # D4: the ONE member↔media-type table, shared with the write path — a member is served
        # as exactly the type its blob's `artifact` row records.
        return Response(
            content=data,
            media_type=CUSTOM_COMPONENT_MEMBER_MEDIA_TYPES[member],
        )

    @app.put("/web/accounts/{account_id}/custom-components/{slug}/source")
    def put_custom_component_source(
        account_id: str,
        slug: str,
        payload: PutCustomComponentSourceRequest,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        written = run_design_tool(
            "design_write_component_source",
            {
                "account_id": account_id,
                "slug": slug,
                "expected_version": payload.expected_version,
                "files": dict(payload.files),
                "provenance": {
                    "kind": "custom_component_source_write",
                    "actor": payload.actor.model_dump(),
                },
            },
            workspace_id=store_workspace_id(repo),
            idempotency_key=idempotency_key,
            refusals={
                "design_account_not_found": lambda _m: NotFoundError(
                    "web_account", account_id
                ),
                "design_component_source_invalid": lambda message: HTTPException(
                    status_code=422,
                    detail={
                        "code": "custom_component.source_invalid",
                        "message": message,
                        "slug": slug,
                    },
                ),
            },
        )
        return {
            "schema_version": 1,
            "component": repo.require_custom_component(account_id, slug),
            "source": repo.require_custom_component_source_revision(
                account_id, written["revision_id"]
            ),
        }

    @app.get("/web/accounts/{account_id}/custom-components/{slug}/source")
    def get_custom_component_source(
        account_id: str,
        slug: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        repo.require_web_account(account_id)
        revision = repo.get_current_custom_component_source(account_id, slug)
        if revision is None:
            raise NotFoundError("custom_component_source", slug)
        _, files = resolve_custom_component_source_snapshot(
            repo,
            blob_store(repo),
            account_id=account_id,
            revision_id=revision["revision_id"],
        )
        return {
            "schema_version": 1,
            "source": revision,
            "files": files,
        }

    @app.get(
        "/web/accounts/{account_id}/custom-components/{slug}/source-revisions"
    )
    def list_custom_component_source_revisions(
        account_id: str,
        slug: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        repo.require_custom_component(account_id, slug)
        return {
            "schema_version": 1,
            "revisions": repo.list_custom_component_source_revisions(
                account_id, slug
            ),
        }

    @app.post("/web/accounts/{account_id}/custom-components/{slug}/compile")
    def compile_custom_component_source(
        account_id: str,
        slug: str,
        payload: CompileCustomComponentRequest,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> Any:
        # The compiler node binary / worker path / timeout and the injectable
        # `main.compile_custom_component` seam all reach the core through the tool host's
        # thunks, so operators and the compiler suites keep the exact same overrides.
        compiled = run_design_tool(
            "design_compile_component",
            {
                "account_id": account_id,
                "slug": slug,
                "source_version": payload.source_version,
                "actor": payload.actor.model_dump(),
            },
            workspace_id=store_workspace_id(repo),
            idempotency_key=idempotency_key,
            refusals={
                "design_component_not_found": lambda _m: NotFoundError(
                    "custom_component", slug
                ),
            },
        )
        artifact_id = compiled["artifact_id"]
        response = {
            "schema_version": 1,
            "compilation": repo.require_custom_component_compilation(
                account_id, compiled["compilation_id"]
            ),
            "artifact": (
                repo.require_custom_component_artifact(account_id, artifact_id)
                if artifact_id is not None
                else None
            ),
        }
        status = compiled["compile_status"]
        if status == "failed":
            return JSONResponse(status_code=422, content=response)
        if status == "transient_error":
            return JSONResponse(status_code=503, content=response)
        return response

    @app.get(
        "/web/accounts/{account_id}/custom-components/{slug}/compilations"
    )
    def list_custom_component_compilations(
        account_id: str,
        slug: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        repo.require_custom_component(account_id, slug)
        return {
            "schema_version": 1,
            "compilations": repo.list_custom_component_compilations(
                account_id, slug
            ),
        }

    @app.patch("/web/accounts/{account_id}")
    def update_web_account(
        account_id: str,
        payload: UpdateWebAccountRequest,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        # Partial update: only the fields the client actually sent are written.
        patch = payload.model_dump(exclude_unset=True)
        run_design_tool(
            "design_update_web_account",
            {"account_id": account_id, "patch": patch},
            workspace_id=store_workspace_id(repo),
            idempotency_key=idempotency_key,
            refusals=_account_refusals(account_id, patch.get("logo_asset_id")),
        )
        return repo.require_web_account(account_id)

    @app.delete("/web/accounts/{account_id}")
    def delete_web_account(
        account_id: str,
        repo: HybridRepository = Depends(repository),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonObject:
        run_design_tool(
            "design_delete_web_account",
            {"account_id": account_id},
            workspace_id=store_workspace_id(repo),
            idempotency_key=idempotency_key,
            refusals=_account_refusals(account_id, None),
        )
        return {"deleted": True}

    # --- P5 templates (D4) ------------------------------------------------ #

    @app.post("/documents/{document_id}/web/template")
    def save_web_template(
        document_id: str,
        payload: SaveWebTemplateRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # Clone the CURRENT web doc payload into a NEW template row: fresh
        # undo/redo stacks, version 0, is_template=1, same theme/brand ref.
        document = require_document(repo, document_id)
        require_web_document(document)
        web_doc = copy.deepcopy(document["scene"])
        new_document_id = new_id("doc")
        title = (payload.title or "").strip() or f"{document['title']} — template"
        web_doc["id"] = new_document_id
        web_doc["title"] = title
        created = run_design_tool(
            "design_create_web_template",
            {
                "document_id": new_document_id,
                "web_doc": web_doc,
                "account_id": document.get("account_id"),
                # F2.2: this template is a COPY of `document_id`, so its fragment pins are
                # inherited, not chosen. Without saying so, retiring one cloned section would
                # block saving a document that has pinned it since before the retirement.
                "source_document_id": document_id,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(new_document_id),
        )
        template = {"id": created["document_id"], "title": created["title"]}
        log_event(
            api_logger,
            logging.INFO,
            "web_template_created",
            document_id=new_document_id,
            source_document_id=document_id,
        )
        return {"document_id": template["id"], "title": template["title"]}

    @app.get("/web/templates")
    def list_web_templates(repo: HybridRepository = Depends(repository)) -> JsonObject:
        templates = [
            {
                "document_id": doc["id"],
                "title": doc["title"],
                "version": doc["current_version"],
                "updated_at": doc["updated_at"],
                "brand_kit_ref": (doc["scene"].get("theme") or {}).get("brand_kit"),
            }
            for doc in repo.list_web_templates()
        ]
        return {"templates": templates}

    # --- the fragment inspector card (clone-fidelity F3.2) ------------------------------------
    # Four thin routes over machinery that already exists: the registry reads, the F3.0
    # activation gate, the F3.1 lineage resolver, and P-7's isolation render. No rule is
    # restated here — the routes are a surface, and every refusal below is somebody else's,
    # translated into a status code.
    #
    # The literal-segment route is registered BEFORE the `{fragment_id}` one for the same reason
    # the ingestion routes are (FastAPI matches in registration order).

    @app.get("/web/fragments/dormant")
    def list_dormant_fragments(repo: HybridRepository = Depends(repository)) -> JsonObject:
        """Every section the source site HIDES (D-F8).

        Dormant sections are on no page, so nothing can select one — and D-F8 makes the inspector
        the one place a human sees and activates them. This is how the inspector reaches them.
        """
        return {
            "schema_version": FRAGMENT_CARD_SCHEMA_VERSION,
            "sections": dormant_fragment_cards(
                app.state.storage, workspace_id=store_workspace_id(repo)
            ),
        }

    @app.get("/web/fragments/{fragment_id}")
    def read_fragment_card(
        fragment_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return fragment_card(
            app.state.storage,
            workspace_id=store_workspace_id(repo),
            fragment_id=fragment_id,
        )

    @app.post("/web/fragments/{fragment_id}/preview")
    def generate_fragment_preview(
        fragment_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """Photograph this section's own bytes in isolation, and keep the picture (P-7).

        The two rows that reach here are the two nothing ever photographed: a hidden-on-source
        clone (D-F8 asks for a preview before a human may activate it) and a composed repair
        (ruling R17-2 — otherwise the human releasing it is approving a section nobody can see).
        A row that already has a preview is refused: a preview is attached once, because a
        decision was made against the picture that is there.
        """
        workspace_id = store_workspace_id(repo)
        loaded = read_web_fragment(
            app.state.storage, workspace_id=workspace_id, fragment_id=fragment_id
        )
        # Asked BEFORE the render, off the row that was just read. The attach refuses this
        # anyway, but discovering it there means a browser launch and up to
        # ISOLATION_TIMEOUT_MS of work whose only possible outcome is a 409 and an orphan blob.
        # The verdict is free here; the picture is not.
        if loaded.row.get("preview_digest"):
            raise DesignFragmentPreviewError(
                fragment_id,
                "already_present",
                f"fragment {fragment_id} already carries a preview: a preview is attached once "
                "and never replaced, because a human's decision was made against the picture "
                "that is there",
            )
        # No brand kit is threaded in: a harvested clone carries all of its own styling, and a
        # repair's artifact carries a stylesheet compiled against its kit at repair time —
        # including the theme's own custom properties (F3.1 §1.3). Handing a kit here would be a
        # second opinion about how the section looks.
        try:
            png, page = render_isolation_preview(
                app.state.core,
                loaded,
                read_blob=blob_store(repo).read_blob,
                shoot=app.state.isolation_shooter,
            )
        except IsolationRenderFailed as failure:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": failure.code,
                    "message": failure.message,
                    "fragment_id": fragment_id,
                },
            ) from failure
        attach_web_fragment_preview(
            app.state.storage,
            workspace_id=workspace_id,
            fragment_id=fragment_id,
            preview=png,
            # P-7's labelling clause, made durable: the kind of picture comes from the thing
            # that MADE it, and lands on the row beside the digest — never inferred later from
            # the mint's provenance, which is about the mint's own crop and would say nothing
            # for a repair and "measured" for a section the capture measured but never cropped.
            preview_basis=page.basis,
            media_type=ISOLATION_PREVIEW_MEDIA_TYPE,
        )
        return fragment_card(
            app.state.storage, workspace_id=workspace_id, fragment_id=fragment_id
        )

    @app.post("/web/fragments/{fragment_id}/activate")
    def activate_fragment(
        fragment_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """A human wakes a hidden-on-source section (D-F8). The gate is the DAL's, not this.

        Straight to ``approved``, deliberately: the person pressing this IS the approval D-F8
        asks for, and leaving it ``draft`` would mean the next brand-kit approval released it as
        a side effect of an unrelated decision — the automatic release dormancy exists to prevent.
        """
        workspace_id = store_workspace_id(repo)
        row = read_web_fragment(
            app.state.storage, workspace_id=workspace_id, fragment_id=fragment_id
        ).row
        target = activation_target(row)
        if target is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "fragment.not_dormant",
                    "message": (
                        f"fragment {fragment_id} is {row.get('status')!r}, not a section the "
                        "source site hides — there is nothing to activate."
                    ),
                    "fragment_id": fragment_id,
                },
            )
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=fragment_id, status=target
        )
        return fragment_card(
            app.state.storage, workspace_id=workspace_id, fragment_id=fragment_id
        )

    @app.post("/web/fragments/{fragment_id}/retire")
    def retire_fragment(
        fragment_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """Retire a REPAIR (ruling R17-2). Never the harvested original (ruling R17-3).

        The only in-product way out of a lineage holding two released repairs, which the recreate
        walk refuses to assemble — correctly, since ranking two deliberate repairs of the same
        band silently would discard one. Retire is not release: no new approval granularity is
        introduced, this is the ``deprecated`` move every section has always had.

        The original is refused because it is the EVIDENCE D-F6 preserves: retiring it to settle
        an argument between two of its repairs throws away the thing the argument is about.
        """
        workspace_id = store_workspace_id(repo)
        row = read_web_fragment(
            app.state.storage, workspace_id=workspace_id, fragment_id=fragment_id
        ).row
        verdict = retirement_verdict(row)
        if not verdict["retirable"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": f"fragment.{verdict['reason']}",
                    "message": verdict["message"],
                    "fragment_id": fragment_id,
                },
            )
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=fragment_id, status="deprecated"
        )
        return fragment_card(
            app.state.storage, workspace_id=workspace_id, fragment_id=fragment_id
        )

    @app.post("/documents/{document_id}/web/derive")
    def derive_web_document(
        document_id: str,
        payload: DeriveWebRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # Derive a personalized copy of a web doc (D4 + editor-wave amendment):
        # account_id is OPTIONAL. Absent → an empty value map (a plain,
        # marker-preserving copy, default title "… — copy"); present → the
        # account's D1 value map (default title "… — {account name}"). The
        # source may be any web doc (template is the convention). Unknown
        # doc/account → 404; engine rejection → 422 with coverage passthrough.
        document = require_document(repo, document_id)
        require_web_document(document)
        account: Optional[JsonObject] = None
        if payload.account_id is not None:
            try:
                account = repo.require_web_account(payload.account_id)
            except NotFoundError as error:
                raise HTTPException(
                    status_code=404, detail=not_found_detail(error)
                ) from error

        if account is not None:
            values, asset_records = account_values(account, repo)
            default_title = f"{document['title']} — {account['name']}"
        else:
            values, asset_records = {}, []
            default_title = f"{document['title']} — copy"
        title = (payload.title or "").strip() or default_title
        new_document_id = new_id("doc")
        try:
            result = app.state.core.web_derive(
                doc=document["scene"],
                values=values,
                assets=asset_records,
                new_doc_id=new_document_id,
                new_title=title,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        coverage = result.get("coverage") or {}
        diagnostics = result.get("diagnostics") or []
        if not result.get("ok", False):
            error = result.get("error") or {}
            raise HTTPException(
                status_code=422,
                detail={
                    "code": error.get("code", "web_derive.rejected"),
                    "message": error.get("message", "derivation was rejected"),
                    "diagnostics": diagnostics,
                    "coverage": coverage,
                },
            )

        derived = _derive_web_document(
            repo,
            new_document_id,
            web_doc=result["web_doc"],
            template=document,
            account_id=payload.account_id,
        )
        log_event(
            api_logger,
            logging.INFO,
            "web_document_derived",
            document_id=derived["id"],
            template_document_id=document["id"],
            account_id=payload.account_id,
            bound=len(coverage.get("bound") or []),
        )
        return {
            "document_id": derived["id"],
            "title": derived["title"],
            "coverage": coverage,
            "diagnostics": diagnostics,
        }

    # --- P5 batch generate + publish (D5) --------------------------------- #

    def _account_logo_state(
        account: JsonObject, asset_records: List[JsonObject]
    ) -> JsonObject:
        """What the manifest says about this account's logo (ruling R25-2).

        The batch NEVER fetches: it uses whatever ``design_account.logo_asset_id`` already holds,
        because populating logos for N accounts is an explicit per-account act somebody performs
        first (``bind_account_logo``), never a fan-out this route starts. So the honest thing a
        run owes its reader is a per-account statement of what it FOUND — and *empty is CORRECT*,
        never a failure row.
        """
        logo_asset_id = account.get("logo_asset_id")
        if not logo_asset_id:
            return {"bound": False, "reason": "no_logo_on_account"}
        if not asset_records:
            # The column names an asset whose registry row is gone (a DELETE detaches it via the
            # FK, but a row can also be archived out from under an old stamp). The derive leaves
            # the template's own fallback; say WHY rather than reporting a bound logo that is not.
            return {"bound": False, "reason": "asset_unresolvable", "asset_id": str(logo_asset_id)}
        return {"bound": True, "asset_id": str(logo_asset_id)}

    def _derive_publish_account(
        repo: HybridRepository,
        template: JsonObject,
        account_id: str,
        publish: bool,
        slug_base: str,
    ) -> JsonObject:
        """Derive (and optionally publish) one account against `template`.
        Never raises: any failure is captured on the manifest row (status
        "failed" + error) so a bad account can never kill the batch."""
        abm = slug_base == ABM_SLUG_BASE
        account = repo.get_web_account(account_id)
        row: JsonObject = {
            "account_id": account_id,
            "account_name": account["name"] if account else account_id,
            "document_id": None,
            "slug": None,
            "url": None,
            "status": "failed",
            "unbound": [],
            # R25-5: publish state per account, readable off the persisted manifest rather than
            # only in the POST's response. `logo` is R25-2's half; `noindex` is R25-4's.
            "logo": {"bound": False, "reason": "account_not_found"},
            "noindex": False,
            "error": None,
        }
        try:
            if account is None:
                raise ValueError(f"account {account_id!r} not found")
            values, asset_records = account_values(account, repo)
            row["logo"] = _account_logo_state(account, asset_records)
            title = f"{template['title']} — {account['name']}"
            # R25-8: an ABM run addresses ONE document per (template, account) so a re-run
            # converges instead of doubling the page count; a generic run keeps its per-run id.
            new_document_id = (
                abm_derived_document_id(template["id"], account_id)
                if abm
                else new_id("doc")
            )
            existing: Optional[JsonObject] = None
            if abm:
                try:
                    existing = repo.require_document(new_document_id)
                except NotFoundError:
                    existing = None
            result = app.state.core.web_derive(
                doc=template["scene"],
                values=values,
                assets=asset_records,
                new_doc_id=new_document_id,
                new_title=title,
                raise_on_error=False,
            )
            coverage = result.get("coverage") or {}
            row["unbound"] = coverage_unbound_keys(coverage)
            if not result.get("ok", False):
                error = result.get("error") or {}
                row["error"] = error.get("message") or error.get(
                    "code", "web_derive.rejected"
                )
                return row
            if existing is not None:
                # The re-derive: commit the new derivation ONTO the document this account already
                # owns, through the same governed web write an editor edit takes, so the page
                # keeps its id, its slug and its history instead of being replaced by a twin.
                derived = _redrive_web_document(
                    repo, existing, web_doc=result["web_doc"], title=title
                )
            else:
                # D6 Round B: the batch derive used to reproduce the persist inline. It now calls
                # the SAME governed tool the HTTP route does (see `_derive_web_document`).
                derived = _derive_web_document(
                    repo,
                    new_document_id,
                    web_doc=result["web_doc"],
                    template=template,
                    account_id=account_id,
                )
            row["document_id"] = derived["id"]
            row["status"] = "derived"
            # R-F1, corrected placement (T27 review C-1, reproduced live): the stamp rides the
            # DERIVE, not the publish. It used to sit inside `if publish:`, so an
            # `{"abm": true, "publish": false}` run derived real ABM account pages with
            # `web_noindex = False` — and the next publish was the editor's plain button, which
            # carries no noindex field, serving the account page INDEXED. An ABM page is born
            # stamped (create AND redrive — a redrive also heals a pre-stamp document), publish
            # or not; a stamp with no publish behind it is inert, which is exactly why it is
            # safe to write here and wrong to defer.
            if abm:
                run_design_tool(
                    "design_set_web_noindex",
                    {"document_id": derived["id"], "enabled": True},
                    workspace_id=store_workspace_id(repo),
                )
            if publish:
                slug = _unique_batch_slug(
                    repo,
                    f"{slug_base}-{web_slugify(account['name'])}",
                    derived["id"],
                )
                # D6: the batch path used to reproduce the whole publish sequence inline. It now
                # calls the SAME governed tool the HTTP route does, so a batch publish is
                # journaled exactly like a manual one and the sequence exists once.
                #
                # R25-4: an ABM account page is reachable by its explicit URL and by nothing else
                # — absent from every navigation (F4.1's shells have no way out) and out of the
                # index. `noindex` is asked for HERE, per page, rather than flipped globally.
                #
                # R-F1: the durable stamp was written at DERIVE time above (T27 review C-1);
                # the publish tool resolves the document itself, so it reads the row that
                # stamp just wrote. The explicit `noindex=abm` below is belt to that braces.
                _publish_web(repo, derived, slug=slug, noindex=abm)
                row["slug"] = slug
                row["url"] = site_address(repo, slug).page_url("/")
                row["noindex"] = abm
                row["status"] = "published"
            return row
        except Exception as error:  # noqa: BLE001 — one account never kills a batch
            row["error"] = str(error) or "derive failed"
            log_event(
                api_logger,
                logging.WARNING,
                "web_batch_account_failed",
                account_id=account_id,
                template_document_id=template["id"],
                error=row["error"],
            )
            return row

    def _process_web_batch(repo: HybridRepository, batch: JsonObject) -> JsonObject:
        """Synchronous-chunked processing (chunk 5): the cursor persists after
        every chunk so an interrupted batch resumes exactly where it stopped.
        Status is "partial" mid-way and "completed" when the cursor reaches the
        account count; "failed" only when the batch itself cannot run (the
        template is gone)."""
        def _advance(
            batch_id: str, expected: int, cursor: int, status: str, manifest: List[JsonObject]
        ) -> JsonObject:
            return _advance_batch(
                repo,
                "design_advance_web_batch",
                {
                    "batch_id": batch_id,
                    "expected_cursor": expected,
                    "cursor": cursor,
                    "status": status,
                    "manifest": manifest,
                },
            )

        try:
            template = repo.require_document(batch["template_document_id"])
        except NotFoundError:
            _advance(
                batch["batch_id"],
                batch["cursor"],
                batch["cursor"],
                "failed",
                batch["manifest"],
            )
            return repo.require_web_batch(batch["batch_id"])

        account_ids = batch["account_ids"]
        total = len(account_ids)
        manifest = list(batch.get("manifest") or [])
        cursor = batch["cursor"]

        while cursor < total:
            # D6 Round C single-flight, half one — see ``_process_batch``. It matters more here:
            # a duplicate instance derivation converges on its deterministic id, but a duplicate
            # web derivation mints a fresh doc_ and may publish a second slug.
            if int(repo.require_web_batch(batch["batch_id"])["cursor"]) != cursor:
                return repo.require_web_batch(batch["batch_id"])
            chunk_end = min(cursor + WEB_BATCH_CHUNK_SIZE, total)
            for index in range(cursor, chunk_end):
                manifest.append(
                    _derive_publish_account(
                        repo,
                        template,
                        account_ids[index],
                        batch["publish"],
                        batch["slug_base"],
                    )
                )
            status = "completed" if chunk_end >= total else "partial"
            if not _advance(batch["batch_id"], cursor, chunk_end, status, manifest)["advanced"]:
                return repo.require_web_batch(batch["batch_id"])
            cursor = chunk_end
            batch = repo.require_web_batch(batch["batch_id"])
        if cursor >= total and batch["status"] != "completed":
            # Empty account set (the while loop never ran): still terminal.
            _advance(batch["batch_id"], cursor, cursor, "completed", manifest)
            batch = repo.require_web_batch(batch["batch_id"])
        return batch

    @app.post("/documents/{document_id}/web/batch")
    def create_web_batch(
        document_id: str,
        payload: WebBatchRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_web_document(document)
        # Unknown accounts are NOT pre-validated: a missing account is a
        # per-account failure on its manifest row, never a batch-level error.
        requested_base = (payload.slug_base or "").strip()
        if payload.abm and requested_base and requested_base != ABM_SLUG_BASE:
            # Two slug bases in one request is two different runs. Overriding one silently would
            # publish pages at URLs the caller did not ask for — and, because the persisted slug
            # base IS the ABM mode, would also decide `noindex` and document convergence behind
            # their back. Refuse and name both.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "web_batch.slug_base_conflict",
                    "message": (
                        f"this batch asks for ABM slugs ({ABM_SLUG_BASE!r}) and for slug_base "
                        f"{requested_base!r}. An ABM run publishes at "
                        f"'{ABM_SLUG_BASE}-<account>' and nowhere else — drop slug_base, or drop "
                        "abm and name the base you want."
                    ),
                },
            )
        slug_base = (
            ABM_SLUG_BASE
            if payload.abm
            else requested_base or web_slugify(document["title"])
        )
        if not payload.abm and slug_base == ABM_SLUG_BASE:
            # `abm: true` is the ONLY door into ABM semantics (T25 review I-3). The persisted
            # slug base IS the mode, so a template merely TITLED "ABM" (title-slugged to
            # "abm") or a hand-passed slug_base="abm" would otherwise switch a plain batch
            # into noindex + in-place convergence nobody asked for — silently, and durably,
            # because a resumed batch reads the persisted base.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "web_batch.slug_base_reserved",
                    "message": (
                        f"slug base {ABM_SLUG_BASE!r} is reserved for ABM runs, and this "
                        "request did not ask for one. If you want ABM account pages "
                        f"('{ABM_SLUG_BASE}-<account>', noindex, one converging document per "
                        "account), say `abm: true`; otherwise pass a different slug_base — "
                        "nothing was derived or published."
                    ),
                },
            )
        batch_ref = run_design_tool(
            "design_create_web_batch",
            {
                "batch": {
                    "batch_id": new_id("wbatch"),
                    "template_document_id": document["id"],
                    "template_doc_version": document["current_version"],
                    "status": "partial",
                    "account_ids": payload.account_ids,
                    "publish": payload.publish,
                    "slug_base": slug_base,
                    "cursor": 0,
                    "manifest": [],
                }
            },
            workspace_id=store_workspace_id(repo),
        )
        batch = _process_web_batch(repo, repo.require_web_batch(batch_ref["batch_id"]))
        log_event(
            api_logger,
            logging.INFO,
            "web_batch_completed",
            batch_id=batch["batch_id"],
            template_document_id=document["id"],
            status=batch["status"],
            cursor=batch["cursor"],
            total=len(batch["account_ids"]),
        )
        return web_batch_response(batch)

    @app.post("/web/batches/{batch_id}/resume")
    def resume_web_batch(
        batch_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        batch = repo.require_web_batch(batch_id)
        if batch["status"] == "completed":
            return web_batch_response(batch)
        batch = _process_web_batch(repo, batch)
        return web_batch_response(batch)

    @app.get("/web/batches/{batch_id}")
    def get_web_batch(
        batch_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return web_batch_response(repo.require_web_batch(batch_id))

    @app.post("/documents/{document_id}/export")
    def export_document(
        document_id: str,
        payload: ExportDocumentRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
        profile = resolve_document_export_profile(document["scene"], payload)
        export_format = profile.get("format") or payload.format

        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        try:
            source, brand_kit = choose_effective_brand(app.state.core, repo, document, payload)
            mode = choose_effective_brand_mode(document, brand_kit, payload.mode)
            document_brand_fonts = brand_kit_font_spec(repo, brand_kit, blobs, cache_dir)
            preflight_result = app.state.core.preflight_scene(
                document["scene"], brand_kit, mode, brand_fonts=document_brand_fonts
            )
        except CoreError as error:
            raise core_http_error(error) from error

        preflight_diagnostics = preflight_result.get("diagnostics", [])
        preflight = preflight_result.get("preflight") or {}
        preflight_operations = preflight_operation_list(preflight)
        # P0.3 severity split. `preflight.has_errors` is the engine's own
        # `any(severity == Error)` over THIS same diagnostics list (see the
        # helper's PreflightScene arm), so it carries no information the list
        # does not — and consulting it here would re-block the advisory codes
        # the split exists to let through. The blocking predicate is now the
        # single source of truth; `has_errors` still rides the response as the
        # raw engine signal.
        blocking_diagnostics, advisory_diagnostics = partition_export_diagnostics(
            preflight_diagnostics
        )
        if blocking_diagnostics:
            _record_diagnostics(repo, document_id, "export", preflight_diagnostics)
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
                blocking_diagnostics=len(blocking_diagnostics),
                advisory_diagnostics=len(advisory_diagnostics),
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
        # Advisory-only diagnostics do NOT return here: the export proceeds and
        # the render runs. They are recorded with the export-phase diagnostics
        # below (that call already includes `preflight_diagnostics`, so there is
        # nothing to record separately) and surfaced on the response as
        # `warnings` for the editor's export menu — ruling R5, editor surface
        # only, never the end client.

        export_scene = preflight_result.get("scene", document["scene"])
        updated_document = document
        if payload.persist_preflight and document["status"] == "draft":
            # D6 Round B: /export's persist half is the SAME governed write /preflight uses —
            # only the envelope `source` string differs (see `_persist_preflight`). Its read
            # half (the engine's preflight + the export render) stays a route concern.
            updated_document = _persist_preflight(
                repo,
                document_id,
                scene=export_scene,
                diagnostics=preflight_diagnostics,
                operations=preflight_operations,
                actor_id="export_preflight",
                effective_brand=_effective_brand_payload(
                    source,
                    brand_kit,
                    mode,
                    persist=payload.persist_effective_brand,
                ),
            )
            export_scene = updated_document["scene"]

        # D4 read-through: the export renders real pixels, so materialize every digest the
        # scene names into the engine cache first (the preflight above may have rewritten the
        # scene, hence both).
        materialize_scene_assets(blobs, cache_dir, [export_scene, document["scene"]])
        try:
            export_result = app.state.core.export_preview(
                export_scene,
                export_format,
                payload.page_ids,
                profile,
                raise_on_error=False,
                asset_store_root=cache_dir,
                brand_fonts=document_brand_fonts,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        export = export_result.get("export") or {}
        export_diagnostics = export_result.get("diagnostics", [])
        if not export_result.get("ok", False) and not export_diagnostics:
            export_diagnostics = diagnostics_from_helper_error(export_result.get("error"))
        diagnostics = preflight_diagnostics + export_diagnostics
        _record_diagnostics(repo, document_id, "export", diagnostics)
        # P0.3: an advisory-only diagnostic must not flip a rendered export to
        # "failed" here either — the bytes exist and are correct. Export-phase
        # diagnostics (licence refusals, missing pages) are unclassified and so
        # block by default, which is the fail-closed behavior we want.
        status = (
            "failed"
            if not export_result.get("ok", False)
            or has_blocking_export_diagnostics(diagnostics)
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
            advisory_diagnostics=len(advisory_diagnostics),
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
        repo: HybridRepository = Depends(repository),
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
                brand_fonts=brand_kit_font_spec(
                    repo, brand_kit, blob_store(repo), request_cache_dir(repo)
                ),
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
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
        run_design_tool(
            "design_attach_brand_kit",
            {
                "document_id": document_id,
                "scene": result["scene"],
                "diagnostics": diagnostics,
                "operations": [operation],
                "actor_kind": payload.actor.kind,
                "actor_id": payload.actor.id,
                "effective_brand": {
                    "source": "brand_kit_library",
                    "brand_kit": brand_kit,
                    "mode": mode,
                },
            },
            workspace_id=store_workspace_id(repo),
            refusals=_document_refusals(document_id),
        )
        updated = repo.require_document(document_id)
        snapshot = _snapshot_after_write(repo, document_id, payload.snapshot_reason)
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
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
        _record_diagnostics(repo, document_id, "brand_governance", diagnostics)
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
        require_draft_document(document, "finalize the document")
        source_snapshot_id = payload.snapshot_id
        scene = document["scene"]
        if source_snapshot_id:
            scene = repo.require_snapshot(document_id, source_snapshot_id)["scene"]
        template_revision_id = payload.template_revision_id or new_id("tmpl")

        try:
            result = app.state.core.finalize_template(scene, template_revision_id)
        except CoreError as error:
            _record_diagnostics(
                repo, document_id, "finalize", diagnostics_from_core_error(error)
            )
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        finalized_scene = result["scene"]
        # D6 Round B: the revision row and the document's finalize advance are ONE operation
        # (a revision without the finalized document, or the reverse, is a broken template), so
        # they are one tool — keyed on the caller-named template_revision_id.
        run_design_tool(
            "design_finalize_document",
            {
                "document_id": document_id,
                "template_revision_id": template_revision_id,
                "source_snapshot_id": source_snapshot_id,
                "scene": finalized_scene,
                "slot_summary": slot_summary(finalized_scene),
                "diagnostics": diagnostics,
                "actor_kind": payload.actor.kind,
                "actor_id": payload.actor.id,
            },
            workspace_id=store_workspace_id(repo),
            refusals=_finalize_refusals(document_id, template_revision_id),
        )
        operation = {
            "kind": "finalize_template",
            "template_revision_id": template_revision_id,
        }
        return finalize_dto(
            repo.require_document(document_id),
            repo.require_template_revision(template_revision_id),
            diagnostics,
            operation,
        )

    @app.get("/template-revisions/{template_revision_id}")
    def get_template_revision(
        template_revision_id: str, repo: HybridRepository = Depends(repository)
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

    def _binding_asset_records(repo: HybridRepository, binding: JsonObject) -> list:
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
        repo: HybridRepository,
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
        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        # D4 read-through: derive renders the template scene AND the per-binding asset records
        # (an account logo the binding substitutes in), so both sets of digests must be in the
        # engine cache before the call.
        materialize_scene_assets(blobs, cache_dir, [revision["scene"]])
        ensure_materialized(
            blobs,
            cache_dir,
            (digest for record in records for digest, _mime in record_digests(record)),
        )
        result = app.state.core.derive_instance(
            scene=revision["scene"],
            binding_set=binding,
            asset_records=records,
            store_root=cache_dir,
            export_formats=export_formats,
            export_dpi=export_dpi,
            export_profile=export_profile,
            # Bulk runs shape with the template's kit faces — without this
            # every instance silently substituted bundled Inter.
            brand_fonts=scene_brand_fonts(repo, revision["scene"], blobs, cache_dir),
            raise_on_error=False,
        )

        if not result.get("ok", False):
            diagnostics = result.get("diagnostics", [])
            if not diagnostics:
                diagnostics = diagnostics_from_helper_error(result.get("error"))
            return _persist_instance(
                repo,
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
                },
            )

        payload = result.get("instance") or {}
        fit_report = payload.get("fit_report") or {}
        status = "failed" if payload.get("has_errors") else "derived"
        generated = payload.get("generated") or {}
        # D4 write-back, BEFORE anything is persisted. Derive writes two kinds of bytes into the
        # cache: rendered EXPORT ARTIFACTS (the per-instance png/svg the row then references)
        # and GENERATED asset records (e.g. a re-fit crop). Both get durable custody here, and
        # the generated records are re-pointed at their storage keys so the registry rows the
        # loop below writes never advertise a cache path.
        register_engine_write(
            blobs,
            cache_dir,
            relative_paths=payload.get("artifacts") or [],
            source_key=design_storage.SOURCE_KEY_ENGINE_ARTIFACT,
        )
        for entry in generated.values():
            record = (entry or {}).get("record")
            if record:
                register_engine_write(
                    blobs,
                    cache_dir,
                    record=record,
                    source_key=design_storage.SOURCE_KEY_ASSET,
                )
        # D6 Round C: the instance row, the library records for the assets the derivation
        # generated, and the repair-queue rows for the slots it could not fit are ONE
        # derivation's durable footprint — all keyed off the same deterministic instance id —
        # so they are one governed write, not three. A partial application (an instance whose
        # generated crop was never registered) is exactly the state nobody can repair.
        return _persist_instance(
            repo,
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
            },
            generated_records=[
                record
                for entry in generated.values()
                if (record := (entry or {}).get("record"))
            ],
            repair_requests=[
                {
                    "repair_id": "rep_"
                    + _sanitize_id_component(
                        f"{revision_id}_{request_['slot_key']}_{binding_set_id}"
                    ),
                    "template_revision_id": revision_id,
                    "slot_key": request_["slot_key"],
                    "node_id": request_["node_id"],
                    "binding_set_id": request_["binding_set_id"],
                    "instance_id": instance_id,
                    "reason": request_["reason"],
                    "status": "open",
                }
                for request_ in payload.get("repair_requests", [])
            ],
        )

    def _public_instance(instance: JsonObject, include_scene: bool = True) -> JsonObject:
        public = dict(instance)
        if not include_scene:
            public.pop("derived_scene", None)
        return public

    @app.post("/binding-sets")
    def create_binding_set(
        payload: CreateBindingSetRequest,
        repo: HybridRepository = Depends(repository),
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
        run_design_tool(
            "design_upsert_binding_set",
            {"binding": binding, "status": "valid", "diagnostics": diagnostics},
            workspace_id=store_workspace_id(repo),
        )
        stored = repo.require_binding_set(binding_set_id)
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
        binding_set_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return repo.require_binding_set(binding_set_id)

    @app.get("/binding-sets")
    def list_binding_sets(
        template_revision_id: Optional[str] = Query(None),
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        return {
            "binding_sets": repo.list_binding_sets(template_revision_id),
        }

    @app.delete("/binding-sets/{binding_set_id}")
    def delete_binding_set(
        binding_set_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        run_design_tool(
            "design_delete_binding_set",
            {"binding_set_id": binding_set_id},
            workspace_id=store_workspace_id(repo),
        )
        return {"deleted": binding_set_id}

    @app.post("/template-revisions/{template_revision_id}/instances")
    def derive_instance_route(
        template_revision_id: str,
        payload: DeriveInstanceRequest,
        repo: HybridRepository = Depends(repository),
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        return _public_instance(
            repo.require_instance(instance_id), include_scene
        )

    @app.get("/template-revisions/{template_revision_id}/instances")
    def list_revision_instances(
        template_revision_id: str, repo: HybridRepository = Depends(repository)
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
        repo: HybridRepository, revision: JsonObject, batch: JsonObject
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
            # D6 Round C single-flight, half one: re-read the cursor before spending a chunk on
            # the engine. It shrinks the double-derive window to one chunk; the compare-and-set
            # on the write below is what makes double-WRITING impossible.
            if int(repo.require_batch(batch["batch_id"])["cursor"]) != cursor:
                return repo.require_batch(batch["batch_id"])
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
            status = "completed" if chunk_end >= len(binding_set_ids) else "running"
            progress = _advance_batch(
                repo,
                "design_advance_instance_batch",
                {
                    "batch_id": batch["batch_id"],
                    "expected_cursor": cursor,
                    "cursor": chunk_end,
                    "status": status,
                    "counts": counts,
                    "manifest": manifest,
                    "diagnostics": diagnostics,
                },
            )
            if not progress["advanced"]:
                # Another resumer owns this batch. Stop and report where it actually is —
                # a resume that discovers the work is already being done is not an error.
                return repo.require_batch(batch["batch_id"])
            cursor = chunk_end
            batch = repo.require_batch(batch["batch_id"])
        return batch

    @app.post("/template-revisions/{template_revision_id}/batches")
    def create_instance_batch(
        template_revision_id: str,
        payload: CreateInstanceBatchRequest,
        repo: HybridRepository = Depends(repository),
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
        batch_ref = run_design_tool(
            "design_create_instance_batch",
            {
                "batch": {
                    "batch_id": new_id("batch"),
                    "template_revision_id": template_revision_id,
                    "status": "running",
                    "binding_set_ids": payload.binding_set_ids,
                    "export_formats": payload.export_formats,
                    "export_profile": export_profile,
                    "chunk_size": chunk_size,
                    "cursor": 0,
                }
            },
            workspace_id=store_workspace_id(repo),
        )
        batch = _process_batch(repo, revision, repo.require_batch(batch_ref["batch_id"]))
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
        batch_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        batch = repo.require_batch(batch_id)
        if batch["status"] == "completed":
            return {"schema_version": 1, **batch}
        revision = repo.require_template_revision(batch["template_revision_id"])
        batch = _process_batch(repo, revision, batch)
        return {"schema_version": 1, **batch}

    @app.get("/batches/{batch_id}")
    def get_instance_batch(
        batch_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return repo.require_batch(batch_id)

    @app.post("/instances/preview")
    def preview_instance(
        payload: InstancePreviewRequest, repo: HybridRepository = Depends(repository)
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
        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        materialize_scene_assets(blobs, cache_dir, [scene])
        try:
            result = app.state.core.derive_instance(
                scene=scene,
                binding_set=payload.binding_set,
                asset_records=[],
                store_root=cache_dir,
                export_formats=[export_format],
                export_dpi=96,
                brand_fonts=scene_brand_fonts(repo, scene, blobs, cache_dir),
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
        # D4 write-back: nothing about this preview persists, but the engine still put its
        # rendered artifact into the cache — register it so a cache wipe between here and the
        # read below cannot lose it, and so repeat previews of identical output dedup.
        register_engine_write(
            blobs,
            cache_dir,
            relative_paths=payload_instance.get("artifacts") or [],
            source_key=design_storage.SOURCE_KEY_ENGINE_ARTIFACT,
        )
        artifact_payload: Optional[JsonObject] = None
        for artifact in payload_instance.get("artifacts", []):
            relative = artifact.get("relative_path")
            if not relative:
                continue
            artifact_path = Path(cache_dir) / relative
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
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        repo.require_template_revision(template_revision_id)
        return {
            "repairs": repo.list_repair_queue(template_revision_id, status),
        }

    def public_asset_record(record: JsonObject) -> JsonObject:
        """DTO-boundary enrichment: stamp the content digests the editor's
        public serving needs (`/asset-store/{digest}` — the only URL an
        `<img src>` can use, since it cannot send `X-Workspace-Id`) as
        explicit fields. Ref parsing stays server-owned policy
        (`clue_design.storage.location_digest`); no client ever takes the
        tail of an `opaque_ref`. Read-time and non-mutating — stored rows
        keep their written shape.
        """
        media = record.get("media")
        if not isinstance(media, dict):
            return record
        enriched = None
        thumbnail = media.get("thumbnail")
        if isinstance(thumbnail, dict) and not thumbnail.get("digest"):
            thumb_digest = location_digest(thumbnail.get("location"))
            if thumb_digest:
                enriched = {
                    **media,
                    "thumbnail": {
                        **thumbnail,
                        "digest": {"algorithm": "sha256", "value": thumb_digest},
                    },
                }
        if not (enriched or media).get("digest"):
            full_digest = location_digest(media.get("location"))
            if full_digest:
                enriched = {
                    **(enriched or media),
                    "digest": {"algorithm": "sha256", "value": full_digest},
                }
        if enriched is None:
            return record
        return {**record, "media": enriched}

    @app.post("/assets")
    def upload_asset(
        file: UploadFile = File(...),
        label: Optional[str] = Form(None),
        kind: Optional[str] = Form(None),
        uploaded_by: Optional[str] = Form(None),
        license_json: Optional[str] = Form(None),
        tags: Optional[str] = Form(None),
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", min_length=1, max_length=200),
        creative_type: Optional[str] = Form(None),
        usage_roles: Optional[str] = Form(None),
        user_note: Optional[str] = Form(None),
        brand_kit_id: Optional[str] = Form(None),
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        from clue_design.asset_context import AssetOverrides, fingerprint
        from .asset_enrichment import UploadKeyConflict
        from pydantic import ValidationError
        try:
            overrides = AssetOverrides.model_validate({
                **({"creative_type": creative_type} if creative_type else {}),
                **({"usage_roles": json.loads(usage_roles)} if usage_roles else {}),
                **({"user_note": user_note} if user_note else {}),
            }).model_dump(exclude_none=True, exclude_unset=True)
        except (ValueError, ValidationError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if brand_kit_id:
            repo.require_brand_kit(brand_kit_id)
        data = file.file.read(asset_max_bytes() + 1)
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
        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        try:
            result = app.state.core.ingest_asset(
                store_root=cache_dir,
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
        # D4 write-back BEFORE the registry row: the engine wrote the bytes (and a thumbnail)
        # into its cache; give them durable custody and re-point the record's locations at the
        # storage keys (R-D4-4), so the row that lands — and the response the editor caches —
        # never advertises a path under a wipeable tree.
        register_engine_write(
            blobs, cache_dir, record=record, source_key=design_storage.SOURCE_KEY_ASSET
        )
        enrichment = None
        if str((record.get("media") or {}).get("mime_type", "")).startswith("image/"):
            enrichment = {
                "idempotency_key": idempotency_key or uuid4().hex,
                "request_digest": fingerprint({"file": hashlib.sha256(data).hexdigest(),
                                               "filename": file.filename, "label": label,
                                               "mime_type": file.content_type, "uploaded_by": uploaded_by,
                                               "kind": kind, "license": license_payload,
                                               "tags": tag_list, "overrides": overrides,
                                               "brand_kit_id": brand_kit_id}),
                "overrides": overrides, "brand_kit_id": brand_kit_id,
            }
        try:
            stored = _register_asset_record(repo, record, enrichment=enrichment)
        except UploadKeyConflict as error:
            raise HTTPException(status_code=409, detail={"code": "asset_upload.key_conflict", "message": str(error)}) from error
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
            "asset": public_asset_record(stored["asset"]),
            "deduplicated": asset_payload.get("deduplicated", False),
            "diagnostics": diagnostics,
            "enrichment": DescriptionStore(workspace_id=repo.workspace_id).get_many(
                [stored["asset"]["id"]]).get(stored["asset"]["id"]),
        }

    def _logo_search_outcome(repo: HybridRepository, url: str):
        """The shared logo lookup for one request: cache, Brandfetch, the official-site ladder,
        the arbiter. None when no source could be reached or attributed to the company."""
        try:
            from lumen_agent.tools import logo_fetch
        except ImportError as error:  # the API can be deployed without the agent runtime
            raise HTTPException(
                status_code=503,
                detail={"code": "logo_search.unavailable", "message": "Logo search is not available here."},
            ) from error
        from lumen_ingestion.capture.net import CaptureError

        try:
            return logo_fetch.fetch_logo_family(
                url, cache=DurableLogoFamilyCache(blobs=blob_store(repo))
            )
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "logo_search.bad_url", "message": "Enter a website, like stripe.com."},
            ) from error
        except CaptureError as error:
            log_event(api_logger, logging.INFO, "logo_search_unreachable", code=error.code)
            return None

    @app.post("/assets/logo-search")
    def search_logos(
        payload: LogoSearchRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """The asset library's Logo search: every version the lookup found, as inline previews.
        Saves nothing (`logo_search.py`). A sync def, so the slow lookup runs in the threadpool;
        the Brandfetch call it may make lands on this request's spend scope."""
        with _request_spend_scope(store_workspace_id(repo)):
            outcome = _logo_search_outcome(repo, payload.url)
        return {"schema_version": 1, **logo_search.search_payload(outcome, query=payload.url)}

    @app.post("/assets/logo-search/save")
    def save_searched_logo(
        payload: LogoSaveRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Register the ONE version the person clicked as a workspace asset; the caller places it.
        The lookup re-runs and the family cache answers it, so the id the search showed resolves
        to the same bytes."""
        with _request_spend_scope(store_workspace_id(repo)):
            outcome = _logo_search_outcome(repo, payload.url)
        prepared = logo_search.find_logo(outcome, payload.asset_id)
        if prepared is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "logo_search.stale",
                    "message": "That logo is no longer in the search results. Search again.",
                },
            )
        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        try:
            result = app.state.core.ingest_asset(**prepared.ingest_kwargs(cache_dir))
        except CoreError as error:
            raise core_http_error(error) from error
        if not result.get("ok", False):
            error = result.get("error") or {}
            raise HTTPException(
                status_code=400,
                detail={"code": error.get("code"), "message": error.get("message")},
            )
        record = (result.get("asset") or {}).get("record") or {}
        register_engine_write(
            blobs, cache_dir, record=record, source_key=design_storage.SOURCE_KEY_ASSET
        )
        stored = _register_asset_record(repo, record)
        return {"schema_version": 1, "asset": public_asset_record(stored["asset"])}

    @app.post("/assets/generate/qr")
    def generate_qr_asset(
        payload: GenerateQrRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # D6 Round C: the row id is DERIVED from the request, not minted. A QR is a pure
        # function of its payload — the engine already reports ``deduplicated`` on the second
        # call because the rendered bytes are identical — so a random id was the only thing
        # making an identical repeat accumulate library rows that all point at one blob. With a
        # content-derived id the registry write is a real upsert and
        # ``design_register_qr_asset`` can honestly declare DOMAIN_IDEMPOTENT.
        asset_id = "asset_qr_" + hashlib.sha256(
            json.dumps(
                {
                    "data": payload.data,
                    "label": payload.label,
                    "ec_level": payload.ec_level,
                    "print_media": payload.print_media,
                    "target_width_mm": payload.target_width_mm,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:12]
        blobs = blob_store(repo)
        cache_dir = request_cache_dir(repo)
        try:
            result = app.state.core.generate_qr(
                store_root=cache_dir,
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
        # D4 write-back before the registry row (see POST /assets).
        register_engine_write(
            blobs, cache_dir, record=record, source_key=design_storage.SOURCE_KEY_ASSET
        )
        stored = _register_asset_record(repo, record, tool="design_register_qr_asset")
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
            "asset": public_asset_record(stored["asset"]),
            "qr": asset_payload.get("qr") or {},
            "deduplicated": asset_payload.get("deduplicated", False),
            "diagnostics": diagnostics,
        }

    @app.post("/assets/generate")
    def generate_asset(
        payload: GenerateAssetRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Public Phase E provider-registry surface (lands with Phase G):
        run any registered generation provider and persist the normalized
        asset record."""
        # Lane 3 slice 5: this REQUEST is the unit of work — the image model call it makes
        # runs through this scope's ProviderCaller and its rows land on provider_call_ledger
        # before the response goes out. The route is a sync def (FastAPI runs it in the
        # threadpool), so the drain owns its own loop.
        with _request_spend_scope(store_workspace_id(repo)):
            if not image_provider.is_image_model_provider(payload.provider) and any(
                value is not None
                for value in (payload.reference_roles, payload.reference_framing, payload.operation)
            ):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "image_model.unsupported_reference_semantics",
                        "message": (
                            "reference roles, framing and operation labels require "
                            "the image model provider"
                        ),
                        "diagnostics": [],
                    },
                )
            asset_id = f"asset_gen_{uuid4().hex[:12]}"
            cache_key: Optional[str] = None
            blobs = blob_store(repo)
            cache_dir = request_cache_dir(repo)
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
                    # D4: a pure-Python read — go straight to durable storage. Routing it through
                    # the engine cache would mean materializing bytes no engine call will read.
                    source_bytes = read_asset_bytes(blobs, source_digest)
                    if source_bytes is None:
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
                        (source_bytes, source_media.get("mime_type") or "image/png")
                    ]
                # RC (D-RC2.5): reference-conditioned GENERATION — resolve the
                # request's reference_asset_ids into real bytes (the field was inert
                # before) so the editor's generate flow conditions on attached style
                # references. Only on the pure-generation path (an edit already rides
                # its source pixels). Empty ids → None → byte-identical to today.
                reference_images: Optional[list] = None
                reference_digests: Optional[List[str]] = None
                ref_ids = payload.reference_asset_ids
                if source_images is None:
                    ref_ids = _dedupe_and_cap_reference_ids(payload.reference_asset_ids)
                    if ref_ids:
                        reference_images, reference_digests = (
                            resolve_reference_images_for_generate(
                                repo, blobs, cache_dir, ref_ids
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
                    reference_asset_ids=ref_ids,
                    reference_digests=reference_digests,
                    source_digest=source_digest,
                    operation=payload.operation,
                    reference_roles=payload.reference_roles,
                    reference_framing=payload.reference_framing,
                )
                # D6 Round C: the ledger is Postgres (``design_generation_result``), not the JSON
                # sidecar under the wipeable engine cache. This probe is a READ and deliberately not
                # a tool — it is what AVOIDS the provider spend, and it has to run before it. The
                # write that claims the key is governed (``design_register_generated_asset``) and
                # re-checks the ledger inside its own transaction, so two requests that both reach
                # here on a miss still converge on one asset.
                cached = repo.get_generation_result(cache_key)
                if cached:
                    cached_record = cached["asset"]
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
                        "asset": public_asset_record(cached_record),
                        "provider": {"id": payload.provider},
                        "deduplicated": True,
                        "diagnostics": [],
                        **image_provider.image_request_receipt_fields(cached_record),
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
                            operation=payload.operation,
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
                            reference_asset_ids=ref_ids,
                            reference_images=reference_images,
                            request_id=asset_id,
                            operation=payload.operation,
                            reference_roles=payload.reference_roles,
                            reference_framing=payload.reference_framing,
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
                        store_root=cache_dir,
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
                        store_root=cache_dir,
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
            # D4 write-back before the registry row (see POST /assets). Covers both branches: the
            # Python image provider's bytes re-ingested through the engine, and a registered
            # provider's `generate_asset`.
            register_engine_write(
                blobs, cache_dir, record=record, source_key=design_storage.SOURCE_KEY_ASSET
            )
            if cache_key is not None:
                # One governed write: the registry row AND the ledger claim, in one transaction, so
                # an identical repeat re-places this asset instead of re-paying the model.
                ref = run_design_tool(
                    "design_register_generated_asset",
                    {"record": record, "generation_key": cache_key},
                    workspace_id=store_workspace_id(repo),
                )
                stored = repo.require_asset_record(ref["asset_id"])
            else:
                stored = _register_asset_record(repo, record)
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
                "asset": public_asset_record(stored["asset"]),
                "provider": asset_payload.get("provider") or {"id": payload.provider},
                "deduplicated": asset_payload.get("deduplicated", False),
                "diagnostics": diagnostics,
                **image_provider.image_request_receipt_fields(stored["asset"]),
            }

    @app.get("/assets")
    def list_assets(
        kind: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
        include_archived: bool = Query(False),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        repo: HybridRepository = Depends(repository),
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
            "assets": [public_asset_record(row["asset"]) for row in rows],
            "count": len(rows),
            "limit": limit,
            "offset": offset,
        }

    @app.post("/assets/{asset_id}/archive")
    def archive_asset(
        asset_id: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        stored = _set_asset_status(repo, asset_id, "archived")
        log_event(
            api_logger,
            logging.INFO,
            "asset_archived",
            asset_id=asset_id,
        )
        return {"schema_version": 1, "asset": public_asset_record(stored["asset"])}

    @app.post("/assets/{asset_id}/restore")
    def restore_asset(
        asset_id: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        stored = _set_asset_status(repo, asset_id, "ready")
        log_event(
            api_logger,
            logging.INFO,
            "asset_restored",
            asset_id=asset_id,
        )
        return {"schema_version": 1, "asset": public_asset_record(stored["asset"])}

    @app.delete("/assets/{asset_id}")
    def hard_delete_asset(
        asset_id: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        # D6 Round C: the reference check (archive-first lifecycle — a hard delete is refused
        # while any document scene still names the asset) is the tool's PRECONDITION, and the
        # row delete plus the digest-by-digest byte GC are its one operation core. They are not
        # separable: a window in which the row is gone and the bytes are not is a leak nothing
        # records as owed.
        deletion = run_design_tool(
            "design_delete_asset",
            {"asset_id": asset_id},
            workspace_id=store_workspace_id(repo),
            refusals=_asset_refusals(asset_id),
        )
        removed_digests: List[str] = list(deletion["removed_digests"])

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

    # D6 Round C: ``record_digest_values`` and ``delete_stored_digest`` moved INTO the delete
    # tool's operation core (``toolbelt.assets.delete_asset_and_orphaned_bytes``), verbatim —
    # the reference counting and the durable-custody-then-cache-mirror ordering are part of the
    # one destructive operation, not route glue. They had no other caller.

    # GET /assets/records — like /assets/descriptions, registered before /assets/{asset_id}.
    # The brand-context page read every kit asset's record one request at a time (27 per
    # load, each queueing on the design API — production 2026-10-03); this is the same
    # envelope GET /assets/{asset_id} serves, for many ids in one statement. An id that is
    # not visible in this workspace is absent, not an error.
    @app.get("/assets/records")
    def get_asset_records(
        asset_ids: str = Query(..., description="comma-separated asset ids"),
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        ids = [ident.strip() for ident in (asset_ids or "").split(",") if ident.strip()][:200]
        stored = repo.get_asset_records(ids)
        return {
            "schema_version": 1,
            "assets": {
                asset_id: {
                    "schema_version": 1,
                    "asset": public_asset_record(row["asset"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for asset_id, row in stored.items()
            },
        }

    # GET /assets/descriptions is registered BEFORE GET /assets/{asset_id} so
    # the literal "descriptions" segment is not captured as an asset id (FastAPI
    # matches routes in registration order at the same path depth).
    @app.get("/assets/descriptions")
    def get_asset_descriptions(
        asset_ids: str = Query(..., description="comma-separated asset ids"),
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        ids = [ident for ident in (asset_ids or "").split(",") if ident.strip()]
        ids = [ident.strip() for ident in ids][:200]
        store = DescriptionStore(workspace_id=repo.workspace_id)
        return {
            "schema_version": 1,
            "descriptions": store.get_many(ids),
        }

    @app.put("/assets/{asset_id}/description")
    def set_asset_description(
        asset_id: str,
        payload: SetAssetDescriptionRequest,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        """Human-author an asset's library metadata (partial merge with the
        existing row). 404 only when the asset RECORD doesn't exist.

        D6 Round C: the merge moved INTO the write. It used to happen here — read the row,
        substitute the caller's non-``None`` fields, write the whole record back — which is a
        read-modify-write across two transactions with no lock between them, so two concurrent
        patches of *different* fields each wrote the view they had read and the later one
        silently reverted the earlier one's field. It is a single ``COALESCE`` upsert now,
        evaluated under the conflicting row's own lock.
        """
        run_design_tool(
            "design_set_asset_description",
            {"asset_id": asset_id, **payload.model_dump(exclude_none=True)},
            workspace_id=store_workspace_id(repo),
            refusals=_asset_refusals(asset_id),
        )
        return DescriptionStore(workspace_id=repo.workspace_id).get_many([asset_id])[asset_id]

    @app.get("/assets/upload-capabilities")
    def asset_upload_capabilities() -> JsonObject:
        return {"max_bytes": asset_max_bytes(), "formats": ["png", "jpeg", "webp", "svg", "gif"]}

    @app.post("/assets/{asset_id}/analysis/retry")
    def retry_asset_analysis(asset_id: str, repo: HybridRepository = Depends(repository)) -> JsonObject:
        repo.require_asset_record(asset_id)
        try:
            job = _offer_ingestion(repo, "asset_enrichment", {"targets": {asset_id: {}}})
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"schema_version": 1, "job": ingestion_job_dto(job)}

    @app.get("/assets/{asset_id}")
    def get_asset(
        asset_id: str,
        repo: HybridRepository = Depends(repository),
    ) -> JsonObject:
        stored = repo.require_asset_record(asset_id)
        return {
            "schema_version": 1,
            "asset": public_asset_record(stored["asset"]),
            "created_at": stored["created_at"],
            "updated_at": stored["updated_at"],
        }

    @app.get("/assets/{asset_id}/bytes")
    def get_asset_bytes(
        asset_id: str,
        request: Request,
        repo: HybridRepository = Depends(repository),
    ) -> Response:
        # D4: a pure-Python read straight from durable storage — resolved BY DIGEST, so the
        # three historical `opaque_ref` shapes (and their three provider labels) all serve, and
        # no stored ref is ever interpreted as a filesystem path.
        try:
            stored = repo.require_asset_record(asset_id)
        except NotFoundError:
            shared_font = shared_library_font_bytes(asset_id, app.state.storage)
            if shared_font is None:
                raise
            media_type, data = shared_font
            return Response(content=data, media_type=media_type)
        record = stored["asset"]
        media = record.get("media") or {}
        digest = location_digest(media.get("location"))
        if digest is None:
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} has no locally stored bytes",
            )
        headers = asset_cache_headers(digest)
        if not_modified(request, digest):
            return Response(status_code=304, headers=headers)
        data = read_asset_bytes(blob_store(repo), digest)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} bytes are missing from the store",
            )
        media_type = media.get("mime_type") or "application/octet-stream"
        return Response(content=data, media_type=media_type, headers=headers)

    # O4-exempt (no X-Workspace-Id), RULED at D2.5A: the PUBLISHED page loads its images and
    # @font-face bytes from here (lumen-web's delivery render emits /asset-store/{digest} URLs),
    # and so does the editor's origin-"null" srcdoc preview iframe — neither can send a header,
    # and a custom header would turn these into preflighted requests the wildcard CORS response
    # cannot satisfy. The bytes are content-addressed and immutable, so serving them without a
    # tenant leaks nothing an unguessable sha256 did not already gate.
    # RESIDUAL (matches the platform's [B2×presign] follow-up): content addressing is not
    # authorization. D4 gave every design byte per-tenant durable custody, but this route still
    # resolves ACROSS tenants (ruling R-D4-7) so the public/preview surfaces keep working —
    # Part-IV auth owns the serving policy for workspace-scoped blobs.
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
        # D4 (R-D4-7): resolved through the `artifact` table — any LIVE row in the design
        # namespace holding this content hash, deterministically picked. Deliberately
        # workspace-UNSCOPED (see `clue_design.storage.read_public_design_blob`): the route is
        # O4-exempt and used to serve one global content-addressed tree, so scoping it would
        # break the published page and the origin-"null" preview iframe it exists for.
        try:
            media_type, data = read_public_design_blob(app.state.storage, digest)
        except NotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail=f"no stored bytes for digest {digest}",
            ) from error
        # The row's media type is authoritative EXCEPT when the producer had nothing better to
        # say; then fall back to sniffing, which is what this route always did.
        if media_type == "application/octet-stream":
            media_type = sniff_mime(data[:512]) or "application/octet-stream"
        return Response(
            content=data,
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                # Content-addressed public bytes, CDN-style. Required because
                # @font-face fetches are CORS-mode requests and the web
                # editor's sandboxed srcdoc iframe has origin "null" — without
                # this, kit fonts silently fall back to system stacks (images
                # are no-cors and never hit it).
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.get("/assets/{asset_id}/thumbnail")
    def get_asset_thumbnail(
        asset_id: str,
        request: Request,
        repo: HybridRepository = Depends(repository),
    ) -> Response:
        # D4: same shape as /bytes — durable read, resolved by digest.
        stored = repo.require_asset_record(asset_id)
        record = stored["asset"]
        thumbnail = (record.get("media") or {}).get("thumbnail") or {}
        digest = location_digest(thumbnail.get("location"))
        if digest is None:
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} has no thumbnail",
            )
        headers = asset_cache_headers(digest)
        if not_modified(request, digest):
            return Response(status_code=304, headers=headers)
        data = read_asset_bytes(blob_store(repo), digest)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"asset {asset_id} thumbnail bytes are missing from the store",
            )
        media_type = thumbnail.get("mime_type") or "application/octet-stream"
        return Response(content=data, media_type=media_type, headers=headers)

    def asset_max_bytes() -> int:
        return settings.lumen_asset_max_bytes

    @app.post("/asset-metadata")
    def create_asset_metadata(
        payload: AssetMetadataRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        # Retired by design-integration Part II (ratified decision O3,
        # docs/specs/PD-part2-design-substrate.md §6): the legacy asset_metadata
        # surface is gone; the asset registry (/assets) is the only writer.
        raise HTTPException(
            status_code=410,
            detail={
                "code": "asset_metadata.gone",
                "message": (
                    "the legacy asset_metadata surface was retired by "
                    "design-integration Part II (PD contract O3); use the asset "
                    "registry (/assets)"
                ),
            },
        )

    @app.get("/asset-metadata/{asset_id}")
    def get_asset_metadata(
        asset_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        return repo.require_asset_metadata(asset_id)

    @app.get("/documents/{document_id}/summary")
    def get_summary(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
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
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> List[JsonObject]:
        document = require_document(repo, document_id)
        require_scene_document(document)
        return slot_summary(document["scene"])

    @app.get("/documents/{document_id}/geometry")
    def get_geometry(
        document_id: str, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_scene_document(document)
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
        repo: HybridRepository = Depends(repository),
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


def install_design_api_telemetry(app: FastAPI) -> Any:
    """OTel + Sentry + Langfuse at this root, from the same .env the fleet reads.

    The dev stack sources the repo-root .env for this process; the CLUE_OTEL_*/CLUE_SENTRY_*/
    CLUE_LANGFUSE_* keys are the fleet's. Missing Langfuse keys skip with a warning; Sentry off by
    default; no OTLP endpoint means spans are created and dropped — same as the fleet.

    Called once, on the module-level ``app`` below — the object `uvicorn lumen_api.main:app`
    serves. NOT inside ``create_app()``: OTel takes one global provider per process and the httpx
    instrumentation is process-wide, so a suite that builds hundreds of apps would install
    hundreds of providers, Langfuse clients and exporters.
    """

    settings = load_settings()
    secrets = Secrets()
    runtime = install_production_tracing(settings, secrets, service_name="clue-design-api")
    install_production_sentry(settings, secrets, service_name="clue-design-api")
    install_production_langfuse(settings, secrets, runtime=runtime, service_name="clue-design-api")
    if settings.otel_instrument_fastapi:
        runtime.instrument_app(app)
    app.state.tracing_runtime = runtime
    return runtime


app = create_app()

# Installed only when THIS module is the process ROOT — i.e. nothing has claimed the process's
# tracer provider yet. `uvicorn lumen_api.main:app` reaches here first and installs.
#
# The guard is not defensive dressing: `lumen_api.fleet_handler` lazily imports `.main` to execute
# a design job, and that handler runs inside the PLATFORM fleet worker, which has already
# installed its own provider, Sentry and Langfuse client under `clue-worker-fleet`. A second
# install there would re-point `clue_obs.otel.tracing`, re-instrument httpx and replace the
# process's Langfuse client mid-run — the fleet's own traces would start reporting as
# `clue-design-api`. OTel's global provider is the exact question "does this process already have
# a root?", so it is what is asked.
if not isinstance(otel_trace.get_tracer_provider(), SdkTracerProvider):
    install_design_api_telemetry(app)


def store_workspace_id(repo: HybridRepository) -> str:
    """The workspace the store is bound to."""
    return repo.workspace_id


def require_document(repo: HybridRepository, document_id: str) -> JsonObject:
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


def require_scene_document(document: JsonObject) -> None:
    """Gate the Rust scene-engine endpoints to scene documents.

    A 'web' (WebDoc) document reuses the same storage but is driven by the
    web pipeline, not the scene engine — every scene mutation/read below
    would misinterpret its payload, so reject it up front with 409."""
    kind = document.get("doc_kind", "scene")
    if kind != "scene":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document.kind_unsupported",
                "message": (
                    f"document {document['id']} is a {kind!r} document; this "
                    "endpoint operates only on scene documents"
                ),
            },
        )


def require_web_document(document: JsonObject) -> None:
    """Gate the website-mode endpoints to WebDoc documents.

    The mirror of require_scene_document: a scene (or any non-web) document
    reuses the same storage but is driven by the Rust scene engine, so the web
    render/turn endpoints would misinterpret its payload — reject it with 409."""
    kind = document.get("doc_kind", "scene")
    if kind != "web":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document.kind_unsupported",
                "message": (
                    f"document {document['id']} is a {kind!r} document; this "
                    "endpoint operates only on web documents"
                ),
            },
        )


# Public publish-slug contract: a lowercase alnum/dash token, 3..64 chars,
# starting with an alnum. Shared by the default-slug builder and the endpoint's
# validation so both agree.
WEB_SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")


def web_slugify(value: str) -> str:
    """Lowercase, replace any non-alnum run with a single dash, and trim dashes.
    An empty result falls back to 'site' so a slug is always emittable."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "site"


def web_default_slug(title: str, document_id: str) -> str:
    """The default publish slug: the slugified title plus a short document-id
    suffix for uniqueness, clamped to the public-slug charset + length."""
    base = web_slugify(title)
    suffix = re.sub(r"[^a-z0-9]+", "", document_id[-4:].lower()) or "0000"
    slug = f"{base}-{suffix}"
    if len(slug) < 3:
        slug = (slug + "site")[:3]
    return slug[:64]


# P5 batch (D5): a bulk derive/publish run processes accounts in fixed-size
# chunks and persists the cursor after each chunk, so an interrupted batch
# resumes exactly where it stopped (the synchronous-chunked job seam).
WEB_BATCH_CHUNK_SIZE = 5


# --- CP2: the ABM batch (clone-fidelity F4.3, rulings D-F5 / R25-3) ---------
#
# An ABM batch derives ONE page per target account off a campaign TEMPLATE and publishes each at
# a flat `abm-<account>` slug. Three behaviours ride together and they all key off ONE fact —
# `slug_base == ABM_SLUG_BASE` — deliberately:
#
#   * the slug shape (`abm_account_slug`, D-F5);
#   * `noindex` on every published account page (R25-4 — these pages are reachable by explicit
#     URL only and must never be indexed);
#   * one derived document per (template, account), converged rather than re-minted (R25-8).
#
# The persisted `slug_base` IS the mode, rather than a second column that could disagree with it,
# so a RESUMED batch behaves exactly like the run that started it with no schema change. The
# consequence is stated rather than hidden: a caller who passes `slug_base="abm"` by hand gets
# ABM semantics, which is the same thing they asked for — `abm-<account>` pages ARE account
# pages. `abm: true` on the request is the named way to ask, and it refuses a conflicting
# `slug_base` instead of quietly overriding it.
ABM_SLUG_BASE = "abm"


def abm_account_slug(account_name: str) -> str:
    """The CP2 account slug: ``abm-`` + the account's display name, slugified (D-F5).

    Deterministic and stated exactly, because these URLs get sent to real people: lowercase, any
    non-alphanumeric run collapsed to one dash, leading/trailing dashes trimmed
    (:func:`web_slugify`), an unslugifiable name falling back to ``site``. Collisions — two
    accounts with the same display name — are suffixed ``-2``, ``-3``, … by
    :func:`_unique_batch_slug`, which also REUSES a slug already owned by the same document, so a
    re-run keeps the URL somebody already sent out.

    ``"Goodman Campbell Brain & Spine"`` → ``"abm-goodman-campbell-brain-spine"``.
    """
    return f"{ABM_SLUG_BASE}-{web_slugify(account_name)}"


def abm_derived_document_id(template_document_id: str, account_id: str) -> str:
    """The ONE derived document a (template, account) pair owns — R25-8's convergence.

    The generic batch mints ``new_id("doc")`` per account, so re-running it after a template edit
    doubles the document count AND takes a fresh ``-2`` slug (the old document still owns the
    first one) — fifty accounts become a hundred pages at ninety-nine URLs. An ABM run addresses
    a deterministic id instead, exactly as the INSTANCE batch's ``inst_<rev>_<bind>`` already
    does (the web batch's own single-flight comment names that asymmetry as the reason it
    matters more here). Existing ⇒ the derivation is committed onto it; absent ⇒ it is created.
    """
    digest = hashlib.sha256(
        f"{template_document_id}\0{account_id}".encode("utf-8")
    ).hexdigest()
    return f"doc_abm_{digest[:24]}"


def coverage_unbound_keys(coverage: JsonObject) -> List[str]:
    """A manifest row's `unbound` = the union of the derive coverage's
    unbound_slots + unbound_vars KEYS (deduped, sorted). Each entry is a
    `{key, node_ids}` UnboundEntry; the batch surfaces only the keys."""
    keys = set()
    for field in ("unbound_slots", "unbound_vars"):
        for entry in coverage.get(field) or []:
            if isinstance(entry, dict) and entry.get("key"):
                keys.add(str(entry["key"]))
    return sorted(keys)


def _unique_batch_slug(repo: HybridRepository, base_slug: str, document_id: str) -> str:
    """The account's publish slug, with collision suffixing: if `base_slug` is
    already owned by a DIFFERENT document, append -2, -3, … until free. A slug
    already owned by THIS document is reused (a re-publish). The batch never
    409s on a taken slug."""
    slug = base_slug
    suffix = 2
    while True:
        existing = repo.get_web_publish(slug)
        if existing is None or existing["document_id"] == document_id:
            return slug
        slug = f"{base_slug}-{suffix}"
        suffix += 1


def web_batch_response(batch: JsonObject) -> JsonObject:
    """The batch DTO shared by POST/resume/GET: `cursor` and `status` echo
    top-level (the editor's Resume button keys off cursor < counts.total or a
    non-terminal status), and counts tally the manifest row statuses."""
    account_ids = batch.get("account_ids") or []
    manifest = batch.get("manifest") or []
    counts = {
        "total": len(account_ids),
        "derived": 0,
        "published": 0,
        "failed": 0,
    }
    for row in manifest:
        status = row.get("status")
        if status in ("derived", "published", "failed"):
            counts[status] += 1
    return {
        "batch_id": batch["batch_id"],
        "status": batch["status"],
        "cursor": batch["cursor"],
        "counts": counts,
        "manifest": manifest,
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


def _refuse_if_agent_running(document_id: str, store: HybridRepository) -> None:
    """Refuse a MANUAL scene write while a design run is driving this document.

    The founder's rule for live-streamed design runs: while the agent is working, the document is
    not editable by hand. Two authors on one scene interleave badly — the run commits mid-flight
    (the P0.4 checkpoints), so a human edit landing between them is either clobbered by the next
    checkpoint or turns the run's remaining operations into a conflict nobody asked for.

    The 409 names the run, which is the only thing the caller can act on: watch it, or cancel it.

    It guards the SIX manual scene-write routes — ``PUT /scene``, ``POST /operations``, ``/undo``,
    ``/redo``, ``/edits`` (the inspector's structured edit) and ``/revert`` (N composed undos).
    The rule is about authorship, not about any one route's shape: every path a human can move a
    scene through is closed while the agent is moving it.

    The agent's own writes go through the governed ``design_apply_operations`` tool
    (``_LegSceneCommitter``), never through these routes — a lock that reached the tool would
    deadlock every run against itself.
    """
    run_id = store.active_design_run_for_document(document_id)
    if run_id is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "document.agent_run_active", "run_id": run_id},
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


def latest_envelope_summary(repo: HybridRepository, document_id: str) -> Optional[JsonObject]:
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


# P5 (D4): the personalization provenance columns are meaningful only for web
# documents. The three below pass through GET /documents/{id} for web docs;
# template_doc_version stays internal (the derive path in B2 reads it, but it is
# not part of the public document shape).
_WEB_PERSONALIZATION_PUBLIC = ("is_template", "template_document_id", "account_id")
_PERSONALIZATION_COLUMNS = _WEB_PERSONALIZATION_PUBLIC + ("template_doc_version",)


def public_document(document: JsonObject) -> JsonObject:
    is_web = document.get("doc_kind") == "web"
    result: JsonObject = {}
    for key, value in document.items():
        if key == "brand_kit":
            continue
        if key == "template_doc_version":
            # Internal — never part of the public document shape.
            continue
        if key in _PERSONALIZATION_COLUMNS and not is_web:
            continue
        result[key] = value
    return result


def fragment_meta_for_document(
    document: JsonObject, fragment_rows: Sequence[JsonObject]
) -> Optional[JsonObject]:
    """Ruling R-A5 (founder, 2026-09-04): the registry facts a human name is made of —
    ``label`` + ``section_role`` — for every fragment the document pins, on every page. A
    pinned id the registry does not hold (unreleased, another workspace's) gets honest
    nulls, so the frontend names it "Cloned section" instead of guessing. None for a scene
    document.

    This rides BESIDE the document rather than inside it: the body a client sends back is
    the body it was served, byte for byte, and a registry label is not a document fact.
    The walk is :func:`lumen_api.database.fragment_references` — the one reader of a web
    document's pins in this codebase — so a page shape it accepts cannot mean two different
    things here and there.
    """
    if document.get("doc_kind") != "web":
        return None
    by_id: JsonObject = {}
    for row in fragment_rows:
        fragment_id = row.get("fragment_id")
        if isinstance(fragment_id, str):
            label = row.get("label")
            section_role = row.get("section_role")
            by_id[fragment_id] = {
                "label": label if isinstance(label, str) else None,
                "section_role": section_role
                if isinstance(section_role, str)
                else None,
            }
    scene = document.get("scene")
    if not isinstance(scene, dict):
        return {}
    meta: JsonObject = {}
    for _node_id, fragment_id in fragment_references(scene).values():
        if fragment_id not in meta:
            meta[fragment_id] = by_id.get(
                fragment_id, {"label": None, "section_role": None}
            )
    return meta


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
    repo: HybridRepository,
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
    repo: HybridRepository,
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
    repo: HybridRepository,
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
    repo: HybridRepository,
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


def document_render_context(
    core: CoreClient, repo: HybridRepository, document: JsonObject
) -> JsonObject:
    """Fresh normal-export inputs, projected only at the saved scene READ seam.

    This is neither persisted metadata nor an attach/rebind operation. A fallback
    chosen by export stays identifiable as that fallback, never as an exact pin.
    """
    meta = document["scene"].get("meta", {})
    pin = meta.get("brand_kit")
    diagnostics: List[JsonObject] = []
    source, kit = "unavailable", None
    try:
        source, kit = choose_effective_brand(core, repo, document, PreflightRequest())
    except (NotFoundError, CoreError) as error:
        diagnostics.append({"severity": "error", "phase": "brand",
            "code": "EDITOR_RENDER_CONTEXT_UNAVAILABLE", "message": str(error),
            "subject": {"kind": "document"}, "hint": None})
    if pin and kit and (pin.get("id"), pin.get("version")) != (kit.get("id"), kit.get("version")):
        diagnostics.append({"severity": "error", "phase": "brand", "code": "LUMB0101",
            "message": "Selected export Brand Kit does not match the scene's exact pinned kit.",
            "subject": {"kind": "document"},
            "hint": "Restore the exact version or use the explicit attach/rebind path."})
    context = {"document_id": document["id"],
        "document_version": document["current_version"], "scene_brand_ref": pin,
        "scene_medium": meta.get("medium"), "source": source, "brand_kit": kit,
        "mode": choose_effective_brand_mode(document, kit, None), "diagnostics": diagnostics}
    context["context_key"] = hashlib.sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return context


def choose_effective_brand_for_scene_preview(
    core: CoreClient,
    repo: HybridRepository,
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
        # P0.3 / ruling R5. Error-severity diagnostics that are policy lints
        # rather than render blockers: the export SUCCEEDED with these present.
        # An editor-surface channel only — the export menu renders them; the
        # end client who receives the artifact never sees them.
        "warnings": export_warning_views(diagnostics),
        "preflight": {
            # The raw engine signal — `any(severity == Error)`. Deliberately
            # NOT the export gate any more: consult `warnings` and `status` to
            # tell "refused" from "exported with advisories".
            "has_errors": preflight.get("has_errors", False),
            "advisory_warnings": len(export_warning_views(diagnostics)),
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

#: P3.7 TOCTOU fix: a leg-pinned turn's brand kit is resolved ONCE, fail-loud, at the
#: dispatch gate and handed to the runtime BY VALUE. This sentinel means 'not a pinned
#: turn — resolve tolerantly from the scene ref as always'.
_BRAND_KIT_UNRESOLVED = object()


def _stamp_session_manifest(
    response: JsonObject,
    *,
    session_dir: Path | None,
    history_file: Path | None,
    session_id: str | None,
    blobs: DesignBlobStore,
    snapshot_session: Any,
) -> JsonObject:
    """Give this session's folder durable custody and name the manifest on the turn's result.

    Session continuity (2026-09-18). ``result_json['session_manifest_sha256']`` is the ONLY
    durable pointer to a session's memory — the next turn reads it back
    (``latest_session_manifest_sha256``) and restores the folder wherever it happens to run.

    Runs on every SESSION turn the runtime returns from — including one that returns a refusal,
    because the workspace it left is still this session's memory of what it tried. A turn whose
    runtime CRASHED snapshots nothing and keeps the previous turn's manifest as the session's
    last good memory. Non-session turns (``session_dir is None``) are untouched, so every
    editor/CLI/fixture path stays byte-identical.

    BEST-EFFORT and loud: the work really happened and its result is really returned, so a
    storage failure must not turn a finished turn into a failed one — but it must not be silent
    either, because a swallowed snapshot is a session that will wake up with amnesia.
    """
    if session_dir is None:
        return response
    try:
        manifest = snapshot_session(
            session_dir,
            register=lambda data, media_type, source_key: blobs.register(
                data, media_type=media_type, source_key=source_key
            ),
            history_file=history_file,
        )
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        # ``register`` returns a storage KEY while ``read_blob`` takes a DIGEST, so the digest is
        # what the result carries — the key would be unreadable to the restore path.
        blobs.register(
            manifest_bytes,
            media_type="application/json",
            source_key="design-session/manifest",
        )
        response["session_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    except Exception as error:  # noqa: BLE001 - a lost snapshot is never a lost turn
        api_logger.error(
            "design_session.snapshot_failed",
            session_id=session_id,
            error=str(error),
            exc_info=True,
        )
    return response


def run_agent_turn_preview(
    payload: AgentTurnPreviewRequest,
    root: Path,
    event_sink=None,
    resolved_reference_assets=_REFERENCES_UNRESOLVED,
    frozen_ad_lane=ad_runtime.FROZEN_LANE_ABSENT,
    *,
    workspace_id: str,
    blobs: Optional[DesignBlobStore] = None,
    engine_cache_root: Optional[Path] = None,
    checkpointer: Any = None,
    thread_id: Optional[str] = None,
    session_id: str | None = None,
    run_id: str | None = None,
    session_manifest: dict | None = None,
    resolved_brand_kit: Any = _BRAND_KIT_UNRESOLVED,
    resolved_asset_library: JsonObject | None = None,
    scene_checkpoint: Any = None,
    cancel_requested: Any = None,
    scoped_preferences: Any = None,
    runtime_workspace_guard: Any = None,
    callbacks: Any = None,
    platform_reads: Any = None,
) -> JsonObject:
    # D4: the turn's tenant. It decides which engine materialization cache the runtime reads and
    # writes — and the accept seam that gives those bytes durable custody looks in that same
    # cache, so a turn pointed at the wrong workspace would silently lose everything it
    # generated. D5 Round C made it REQUIRED: the old `workspace_id or default_workspace_id()`
    # meant a caller that simply forgot ran against the dev tenant instead of failing.
    #
    # `blobs` / `engine_cache_root` (D5 Round C) are the dispatching app's byte backend and
    # engine-cache tree. Omitted (the CLI and direct callers) they are re-derived from settings,
    # which is exactly what a detached fleet worker has; the embedded worker passes the app's,
    # so an injected backend cannot stage bytes in one place and read them from another.
    turn_workspace_id = workspace_id
    turn_blobs = blobs if blobs is not None else api_blob_store(turn_workspace_id)
    turn_cache_root = (
        engine_cache_root
        if engine_cache_root is not None
        else api_engine_cache_root(turn_workspace_id)
    )
    try:
        from lumen_agent.config import AgentRuntimeConfig
        from lumen_agent.harness import effective_runtime_config, run_deepagent_turn
        from lumen_agent.session_sync import restore_session, snapshot_session
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
        reference_assets = resolve_agent_turn_references(payload, turn_blobs)
    else:
        reference_assets = resolved_reference_assets

    # W4 (Brand Ad Assets v1 §5): the lane the turn runs with, resolved ONCE, here, for both
    # of the things a turn takes out of it — the auto-attached references below and the
    # described card that rides the frame payload further down. Since the Wave-C offer-time
    # freeze, a fleet-claimed turn arrives with the lane FROZEN in its envelope and this line
    # consumes it verbatim (no flag check, no database read — the offering process decided);
    # only a legacy envelope, or a direct in-process caller like the sync preview route,
    # composes at claim time — and a flag-off process doing that now says so loudly instead
    # of silently declining (the Wave-B W-B2 failure shape).
    ad_lane = ad_runtime.resolve_turn_ad_lane(frozen_ad_lane, workspace_id=turn_workspace_id)
    if ad_lane is not None and not reference_assets:
        # MANUAL REFERENCES ALWAYS WIN. The platform suggests; the human decides (the
        # minimum-input / client-has-the-wheel rule). A turn that already carries attachments
        # is left exactly as the human composed it — no top-up to the cap, no reordering.
        with _setup_step(run_id or "preview", "auto_ad_references"):
            reference_assets = resolve_auto_ad_references(
                payload, turn_blobs, turn_cache_root, ad_lane
            )

    try:
        config = AgentRuntimeConfig.from_env(root)
        if session_id:
            # Session continuity (2026-09-18): this turn belongs to a DOCUMENT's design session,
            # so the runtime's per-turn files land under that session's folder and its agent
            # workspace survives across turns. The run id rides along so a retried run reuses its
            # own turn folder and stamps the same id on its human message — which is what lets
            # the checkpoint seam resume it instead of appending a second turn (ruling T5-1).
            # Absent (the editor preview route, the CLI, fixtures) the runtime keeps its
            # per-run folder and its own generated id, byte-identical to before.
            config = replace(config, session_id=session_id, run_id=run_id)
        if platform_reads is not None:
            # Design note 2026-09-19: what this LEG turn may read from the platform — the target
            # account's research through the governed tools, and the seller's pinned knowledge.
            # Composed by the platform and passed BY VALUE, the same rule as every other
            # capability here: the runtime never opens the platform database. Absent (a direct
            # editor turn, the CLI, fixtures) the config is byte-identical to before the note.
            config = replace(config, platform_reads=platform_reads)
        if payload.max_iterations is not None:
            # v0 harness does not consume max_iterations (no Python-loop cap);
            # kept set for config parity + offline/CLI paths that still read it.
            config = replace(config, max_iterations=payload.max_iterations)
        if payload.model:
            config = replace(config, model=payload.model)
        if config.asset_store_root is None:
            # D4: the runtime's engine reads and writes the SAME per-workspace materialization
            # cache the API's own engine calls use — a seeded scene's imagery is materialized
            # there, and anything the turn generates lands there and is given durable custody at
            # the accept seam (the scene-persist backstop). Pointing the runtime anywhere else
            # fails seeded imagery with LUME0210. LUMEN_AGENT_ASSET_STORE still overrides.
            config = replace(config, asset_store_root=turn_cache_root)
        # Vendor-first logo family cache (decision #4): per workspace, keyed by registrable
        # domain; the tool degrades to uncached fetching when this is None.
        config = replace(config, logo_family_cache=DurableLogoFamilyCache(blobs=turn_blobs))
        if resolved_brand_kit is _BRAND_KIT_UNRESOLVED:
            brand_kit, brand_kit_source, brand_kit_assets, brand_fonts = (
                resolve_agent_turn_brand_kit(payload, turn_blobs)
            )
        else:
            # P3.7 TOCTOU fix: a leg-pinned turn's kit was resolved once, fail-loud, at the
            # dispatch gate. Re-resolving here would reopen the exact window the pin exists
            # to close — the tolerant resolver's except returns None and the runtime falls
            # back to the platform default kit, silently, in the wrong brand.
            brand_kit, brand_kit_source, brand_kit_assets, brand_fonts = resolved_brand_kit
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
        asset_library = resolved_asset_library if resolved_asset_library is not None else resolve_scene_turn_asset_library(turn_blobs, turn_cache_root)
        if asset_library is not None:
            # W1.1 (Brand Ad Assets v1 §5): the bounded workspace ASSET LIBRARY rides
            # the run BY VALUE — the same rule as brand_kit_assets and
            # reference_assets, and the same manifest website mode has always had.
            # Without it a scene turn could view and place only kit assets and this
            # turn's reference attachments, so a pre-generated background was
            # unusable (Apollo POC 2026-08-26). The store root is pinned for the same
            # reason the reference branch pins it: the read-through staged those
            # bytes in THIS cache, so pointing the runtime elsewhere would blind
            # `view("asset:…")` and render placed library imagery as an empty chip.
            config = replace(
                config,
                asset_library=asset_library,
                asset_materializer=asset_materializer(asset_library, turn_blobs, str(turn_cache_root)),
                asset_store_root=turn_cache_root,
            )
        for manifest in (config.brand_kit_assets or {},):
            for aid, entry in manifest.items():
                if aid in (asset_library or {}):
                    entry.update({key: value for key, value in asset_library[aid].items() if key != "record"})
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
                reference_assets={aid: {**entry, **{k: v for k, v in (asset_library or {}).get(aid, {}).items() if k != "record"}} for aid, entry in reference_assets.items()},
                asset_store_root=turn_cache_root,
            )
        ad_dna_card = ad_runtime.context_card(ad_lane)
        if ad_dna_card:
            # W4: the brand's published-ad styles, DESCRIBED, ride the run BY VALUE next to
            # the brand card — the same rule as brand_kit and reference_assets. It is advisory
            # context and nothing more: no gate, no required structure, no refusal (D5). It
            # rides whether or not this turn's references were auto-attached, because a human
            # who attached their own references still benefits from knowing what this brand's
            # published ads look like.
            config = replace(config, ad_dna_card=ad_dna_card)
        ad_pregenerated = ad_runtime.context_pregenerated(ad_lane)
        if ad_pregenerated:
            # W5/R2-D: and the grounds pre-generation made from that description, BY VALUE for
            # the same reason. Rides independently of the card block above (a lane can hold
            # imagery whose prose failed to render) and independently of references, because
            # the reason this list exists is that nothing else in the turn ever names these
            # ids — not the asset index, which is kit-only, and not `view`, which lists library
            # ids only once the author has already guessed one wrong.
            config = replace(config, ad_pregenerated_assets=ad_pregenerated)
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
        # Session continuity (2026-09-18): WHERE this session's memory lives, resolved through the
        # same rule the harness uses, so the candidate bundle's rebound root can never leave the
        # two looking in different folders. Computed before the run because the restore below must
        # happen before `materialize_agent_workspace` and the tools touch the workspace, and reused
        # after it for the snapshot.
        effective = effective_runtime_config(config)
        session_dir = effective.session_dir()
        history_file = (
            None
            if session_dir is None
            else effective.trace_dir / "conversation_history" / f"{session_id}.md"
        )
        if session_dir is not None and not session_dir.exists() and session_manifest is not None:
            # A DIFFERENT worker ran this session's last turn (or this one's disk was reclaimed).
            # Rebuild the folder before anything reads it, or the agent would continue a
            # conversation about files it cannot open.
            with _setup_step(run_id or "preview", "session_restore"):
                restored = restore_session(
                    session_dir,
                    session_manifest,
                    read_blob=turn_blobs.read_blob,
                    history_file=history_file,
                )
            api_logger.info(
                "design_session.restored", session_id=session_id, files=restored
            )
        payload_result, tools = run_deepagent_turn(
            prompt,
            config,
            initial_scene=agent_seed_scene(payload),
            event_sink=event_sink,
            clarification_already_requested=clarification_already_requested,
            # D5 Round B: durable graph state keyed on the DESIGN RUN. Both are None on every
            # non-fleet path (CLI, fixtures, the synchronous /agent/turn-preview route), which
            # keeps those turns byte-identical to pre-D5.
            checkpointer=checkpointer,
            thread_id=thread_id,
            # P0.4: the checkpoint-commit sink. Supplied only by a leg turn (the one turn kind
            # that owns a persist), so every other caller keeps save-on-finalize-only.
            scene_checkpoint=scene_checkpoint,
            # A3 (defect R3-D): the run's durable cancel probe. Supplied only by the fleet
            # executor, which is the only caller whose turn has a run row to be cancelled
            # THROUGH — the synchronous preview route holds the request open and has no id a
            # second caller could name.
            cancel_requested=cancel_requested,
            # Lane 3 slice 5: the platform's injected handlers and the executor's receipt
            # collector, attached by the harness at the graph's invoke config. None on every
            # non-fleet path, which still collects — the harness always opens a collector.
            callbacks=callbacks,
            **({"scoped_preferences": scoped_preferences} if scoped_preferences is not None else {}),
            **({"runtime_workspace_guard": runtime_workspace_guard} if runtime_workspace_guard is not None else {}),
        )
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.failed",
            "Agent runtime failed before returning a proposal.",
            str(error),
        )

    # ``turn_dir``, not ``trace_dir``: since the session folder landed (2026-09-18) the
    # operations ledger and the iteration folders live under THIS turn's folder, so a
    # session turn read from the session root would report zero operations.
    response = agent_response_from_trace(payload_result, tools.turn_dir, tools.scene)
    return _stamp_session_manifest(
        response,
        session_dir=session_dir,
        history_file=history_file,
        session_id=session_id,
        blobs=turn_blobs,
        snapshot_session=snapshot_session,
    )


def _web_node_label(
    node: JsonObject,
    nodes: Optional[JsonObject] = None,
    fragment_meta: Optional[JsonObject] = None,
) -> Optional[str]:
    """A cheap human label for a WebDoc node, in the SAME order of precedence the
    shell shows a human (``displayNameForNode``, ruling R-A5): its own name, else a
    clone's registry name, else a section's sole clone child's name, else its text/
    button/alt copy (inline markup stripped), truncated. None when nothing cheap is
    available — the caller then prints the bare kind, as it always has.

    The two mirrors must stay in step: the user says "make the hero tighter" about a
    band the layers panel calls "Hero — Stripe homepage hero", and the agent's TURN
    TARGET line has to name that same band with those same words, or the two of them
    are discussing different things. ``nodes`` (the page's node map) and
    ``fragment_meta`` (the registry facts, :func:`fragment_meta_for_document`) are
    optional so a caller with neither still gets the old text/name answer.
    """
    name = node.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()[:40]
    kind = node.get("kind")
    if kind == "fragment":
        meta = (fragment_meta or {}).get(node.get("fragment_id") or "") or {}
        role = meta.get("section_role")
        label = meta.get("label")
        role = role.strip().capitalize() if isinstance(role, str) and role.strip() else None
        label = label.strip() if isinstance(label, str) and label.strip() else None
        # A pin the registry does not hold (unreleased, or another workspace's) is named
        # honestly rather than guessed at — the frontend's fallback, word for word.
        return (f"{role} — {label}" if role and label else role or label) or "Cloned section"
    if kind == "section" and nodes is not None:
        children = node.get("children") or []
        only = nodes.get(children[0]) if len(children) == 1 else None
        if isinstance(only, dict) and only.get("kind") == "fragment":
            return _web_node_label(only, nodes, fragment_meta)
    for key in ("content", "label", "alt"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            text = re.sub(r"<[^>]+>", "", value).strip()
            if text:
                return text[:40]
    return None


#: A human numbers their own annotations ("1. …", "2. …") in the composer, and those numbers
#: are what the badges in the iframe show them. When a note carries one, it wins over the
#: submission order — the agent and the marketer must be able to say "annotation 2" and mean
#: the same element.
_ANNOTATION_NUMBER_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]\s")

#: How much of an annotated element's current copy to quote back. Enough to recognize the
#: element by; not so much that a long paragraph crowds out the brief.
_ANNOTATED_TEXT_CHARS = 160


def _fragment_hidden_slot_keys(node: JsonObject) -> List[str]:
    """The node's slot keys bound `{"visible": false}` — the elements the render DROPS.

    A structural path is measured in the browser, against the rendered clone, so any element a
    slot has hidden was never in the count. Every server-side walk over the STORED artifact
    therefore needs this set, or it counts siblings the page does not have (spec §3.1). The wire
    shape is the engine's externally-tagged `FragmentSlotValue` — `{"text": …}` / `{"asset": …}`
    / `{"visible": false}` — so only the third form, and only when false, hides anything.
    """
    slots = node.get("slots")
    if not isinstance(slots, dict):
        return []
    return [
        key
        for key, value in slots.items()
        if isinstance(key, str) and isinstance(value, dict) and value.get("visible") is False
    ]


def _annotation_number(note: str, order: int) -> int:
    """The number this annotation should be called by: the human's own leading `N.` when
    they wrote one, else its 1-based position in the submission."""
    match = _ANNOTATION_NUMBER_RE.match(note)
    return int(match.group(1)) if match else order


def _describe_annotated_element(
    node: JsonObject,
    path: str,
    read_source: Optional[Any],
    cache: Dict[str, Optional[JsonObject]],
) -> str:
    """The `, element …` clause of an ANNOTATION line: what the path lands on inside the
    clone's REAL stored markup, or an honest statement that it lands on nothing.

    The path is only meaningful inside a cloned band (the bridge emits one only under
    `data-fragment-root`), so a path on any other node kind is treated as dead rather than
    resolved against markup that does not exist.

    The walk is told THIS NODE's hidden slot keys, because the path was counted over what the
    browser rendered and a hidden slot's element is not in that render — without them a note on
    the headline of a clone whose badge is switched off names the badge instead."""
    fragment_id = node.get("fragment_id")
    resolved: Optional[JsonObject] = None
    if node.get("kind") == "fragment" and isinstance(fragment_id, str) and fragment_id:
        if fragment_id not in cache:
            source: Optional[JsonObject] = None
            if read_source is not None:
                try:
                    candidate = read_source(fragment_id)
                    source = candidate if isinstance(candidate, dict) else None
                except Exception:
                    # A registry miss (unreleased pin, another workspace's artifact, storage
                    # hiccup) must never take the prompt build down: the annotation degrades to
                    # "the path no longer resolves", which is the same honest answer a genuinely
                    # dead path gets.
                    source = None
            cache[fragment_id] = source
        source = cache[fragment_id]
        if source is not None:
            resolved = resolve_structural_path(
                str(source.get("html") or ""),
                path,
                hidden_slot_keys=_fragment_hidden_slot_keys(node),
            )
    if resolved is None:
        return ""
    name = (
        f"{resolved['tag']} · {resolved['slot']}"
        if resolved.get("slot")
        else str(resolved["tag"])
    )
    text = str(resolved.get("text") or "")
    if len(text) > _ANNOTATED_TEXT_CHARS:
        text = text[:_ANNOTATED_TEXT_CHARS].rstrip() + "…"
    reading = f' reading "{text}"' if text else ""
    return f", element `{name}` at path `{path}`{reading}"


def _describe_web_turn_targets(
    web_doc: JsonObject,
    target_node_ids: List[str],
    fragment_meta: Optional[JsonObject] = None,
    target_notes: Optional[List[JsonObject]] = None,
    read_source: Optional[Any] = None,
) -> str:
    """Build the TURN TARGET / ANNOTATION brief addendum for a scoped edit turn: one line
    per selected node, naming the node, its kind, the PAGE it sits on, and the
    enclosing section the turn should be scoped to. A selection that no longer
    exists in the document yields a line telling the agent to fall back to its
    own judgment.

    F5: every page is searched, not the one spelled `home`. A selection made on
    a second page used to resolve against the home page's node map and come
    back as "that element no longer exists" — the agent then rebuilt on its own
    judgment instead of editing what the user had actually clicked.

    R-A5: `fragment_meta` (this workspace's registry facts, keyed by fragment id)
    is what lets a selected clone be named the way the human's layers panel names
    it. Omitted, a clone still reads as `fragment "Cloned section"` — honest, just
    less useful.

    R-A2: `target_notes` is what the marketer actually WROTE — one entry per
    annotation they made, in submission order, each naming the owning node, the
    optional inner element (a `:nth-child` path, spec §3.1) and their words. A
    target that carries a note gets a numbered ANNOTATION line INSTEAD of its
    TURN TARGET line — the annotation already names the node, its page and its
    section, and saying it twice would only invite the agent to treat one
    selection as two. Targets with no note keep the TURN TARGET line they have
    always had, byte for byte.

    `read_source` is the registry seam (`DurableAgentClonedSectionRegistry.read_source`)
    used to resolve an inner path against the clone's REAL stored HTML, so the line can
    name the element and quote what it currently says. Without it — or when the path is
    dead — the line says the path no longer resolves rather than describing markup nobody
    checked."""
    # (page id, nodes, that page's top-level band ids, child -> parent) per page,
    # in document order. Built once; a target is then looked up across all of them.
    pages: List[Tuple[str, Dict[str, Any], set, Dict[str, str]]] = []
    for candidate in web_doc.get("pages") or []:
        if not isinstance(candidate, dict):
            continue
        nodes = candidate.get("nodes")
        if not isinstance(nodes, dict):
            continue
        page_id = candidate.get("id") if isinstance(candidate.get("id"), str) else ""
        root = nodes.get(candidate.get("root")) or {}
        root_child_set = set(root.get("children") or []) if isinstance(root, dict) else set()
        parent_of: Dict[str, str] = {}
        for nid, node in nodes.items():
            if isinstance(node, dict):
                for child in node.get("children") or []:
                    parent_of[child] = nid
        pages.append((page_id, nodes, root_child_set, parent_of))

    def locate(target: str):
        """(page id, nodes, node, enclosing section id) for a target, or None when the
        document no longer holds it."""
        # First page carrying the id wins. Node ids are document-unique, so this is a
        # lookup rather than a choice; ordering it makes the tie deterministic anyway.
        found = next(
            (entry for entry in pages if isinstance(entry[1].get(target), dict)),
            None,
        )
        if found is None:
            return None
        page_id, nodes, root_child_set, parent_of = found
        section: Optional[str] = None
        if target in root_child_set:
            section = target
        else:
            current = target
            seen: set[str] = set()
            while current in parent_of and current not in seen:
                seen.add(current)
                current = parent_of[current]
                if current in root_child_set:
                    section = current
                    break
        return page_id, nodes, nodes[target], section

    # One entry per annotation the human actually wrote. An entry with no words is a
    # selection, not an annotation — the platform sends one ref per selected node whether
    # or not it carries a note — so it contributes nothing here and its target keeps its
    # ordinary TURN TARGET line.
    annotations: List[Tuple[str, Optional[str], str]] = []
    for entry in target_notes or []:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target")
        note = entry.get("note")
        if not isinstance(target, str) or not target:
            continue
        if not isinstance(note, str) or not note.strip():
            continue
        path = entry.get("path")
        annotations.append(
            (target, path if isinstance(path, str) and path else None, note.strip())
        )
    annotated = {target for target, _path, _note in annotations}

    lines: List[str] = []
    for target in target_node_ids:
        if target in annotated:
            continue
        found = locate(target)
        if found is None:
            lines.append(
                f"\n\nTURN TARGET: the user selected `{target}`, but that element no "
                "longer exists in the page — use your own judgment about what to edit."
            )
            continue
        page_id, nodes, node, section = found
        kind = node.get("kind") or "node"
        label = _web_node_label(node, nodes, fragment_meta)
        descriptor = f'{kind} "{label}"' if label else str(kind)
        section_str = f"`{section}`" if section else "the page"
        # A page with no id is not addressable, so it is named by saying nothing rather
        # than by an invented index — the line then reads exactly as it did pre-F5.
        page_clause = f" on page `{page_id}`" if page_id else ""
        lines.append(
            f"\n\nTURN TARGET: the user selected `{target}` ({descriptor}){page_clause} "
            f"inside section {section_str}. Scope this turn to that section unless the "
            "brief clearly requires more."
        )

    source_cache: Dict[str, Optional[JsonObject]] = {}
    for order, (target, path, note) in enumerate(annotations, start=1):
        number = _annotation_number(note, order)
        found = locate(target)
        if found is None:
            lines.append(
                f"\n\nANNOTATION {number}: the user annotated `{target}`, but that element "
                f'no longer exists in the page — "{note}". Use your own judgment about '
                "what to edit."
            )
            continue
        page_id, nodes, node, section = found
        kind = node.get("kind") or "node"
        label = _web_node_label(node, nodes, fragment_meta)
        descriptor = f'{kind} "{label}"' if label else str(kind)
        where_parts: List[str] = []
        if page_id:
            where_parts.append(f"page `{page_id}`")
        where_parts.append(f"section `{section}`" if section else "the page")
        where = f" ({', '.join(where_parts)})"
        inner = (
            _describe_annotated_element(node, path, read_source, source_cache)
            if path
            else ""
        )
        if path and not inner:
            lines.append(
                f"\n\nANNOTATION {number}: on {descriptor}{where}, element at path "
                f'`{path}` — "{note}". That path no longer resolves in this section, so '
                "use your judgment about which element they meant."
            )
            continue
        lines.append(f'\n\nANNOTATION {number}: on {descriptor}{where}{inner} — "{note}"')
    return "".join(lines)


def run_web_agent_turn(
    document: JsonObject,
    prompt: str,
    model: Optional[str],
    root: Path,
    event_sink=None,
    target_node_ids: Optional[List[str]] = None,
    target_notes: Optional[List[JsonObject]] = None,
    account_card: Optional[JsonObject] = None,
    asset_library: Optional[JsonObject] = None,
    custom_component_registry: Any = None,
    account_logo_binder: Any = None,
    *,
    workspace_id: str,
    blobs: Optional[DesignBlobStore] = None,
    engine_cache_root: Optional[Path] = None,
    checkpointer: Any = None,
    thread_id: Optional[str] = None,
    session_id: str | None = None,
    run_id: str | None = None,
    session_manifest: dict | None = None,
    cancel_requested: Any = None,
    callbacks: Any = None,
    platform_reads: Any = None,
) -> JsonObject:
    """Run one website-mode turn against a WebDoc document. Mirrors
    run_agent_turn_preview's config assembly (env config + model override +
    pinned asset store + by-value brand kit) but drives the web harness and
    returns the web turn envelope. Never raises: any failure folds into a
    failed envelope so the worker records it cleanly.

    `target_node_ids` (a scoped edit turn): each selected node is resolved to
    its enclosing section in Python and appended to the brief as a TURN TARGET
    line so the orchestrator scopes the turn to that section. R-A5: the line
    NAMES that node the way the human's layers panel names it, which for a
    cloned band means reading this workspace's fragment registry here.

    `target_notes` (R-A2): what the human WROTE about those targets — one entry
    per submitted reference, in submission order, each optionally naming an
    element INSIDE a cloned band by structural path. Each note becomes a numbered
    ANNOTATION line, and the path is resolved HERE against the artifact's real
    stored HTML (the same registry read the agent's own inspect tool uses), so
    the brief can name the element and quote the words it currently reads instead
    of handing the agent a bare `:nth-child` chain to guess at.

    `account_card` (a 1:1 personalized turn, P5 D6): the target account card
    {name, domain, logo_asset_id, data, notes}, resolved to 404 before the run
    started. It rides the runtime config BY VALUE (same rule as brand_kit) and
    its logo AssetRecord is resolved here into config.account_assets so
    use_account_asset can register it.

    `asset_library`: the API-resolved non-archived workspace records and their
    descriptions, passed BY VALUE. This is the only source search_assets and
    use_library_asset can use; the runtime never reads the API database.

    `custom_component_registry`: an account/document-bound capability. Unlike
    brand/assets it is not passed by value because source/compile operations
    must be durable between runs; the runtime receives typed methods, never
    database/store paths.

    `account_logo_binder` (F4.3): the G1+G2 bridge, the same kind of capability
    and passed in for the same reason — its two durable writes are the GOVERNED
    asset/account tools, and the invoker that runs them lives at the worker
    seam. None means this turn cannot bind a fetched mark to an account; the
    tool says so and refuses, and an empty account logo stays correct.

    The workspace's CLONED SECTIONS (F2.3) ride the same way, and are built here
    rather than taken as an argument: unlike the component registry they need no
    account and no document, only this turn's tenant and its engine cache, both
    of which are already resolved below."""
    try:
        from lumen_agent.config import AgentRuntimeConfig
        from lumen_agent.harness_web import run_deepagent_web_turn
        from lumen_agent.session_sync import restore_session, snapshot_session
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.unavailable",
            "Agent runtime dependencies are not available to the API process.",
            str(error),
        )

    # D4: see run_agent_turn_preview — the turn's tenant picks its engine cache. REQUIRED since
    # D5 Round C; the old fallback chain ended at the dev workspace, which meant a caller that
    # forgot silently read and wrote another tenant's data. The custom-component registry carries
    # a workspace of its own and the two must not disagree — assert rather than prefer one, so a
    # mismatch is a loud bug instead of a silent re-scope.
    registry_workspace_id = getattr(
        getattr(custom_component_registry, "blobs", None), "workspace_id", None
    )
    if registry_workspace_id is not None and registry_workspace_id != workspace_id:
        raise ValueError(
            "web turn workspace disagrees with its custom-component registry's: "
            f"{workspace_id!r} vs {registry_workspace_id!r}"
        )
    turn_workspace_id = workspace_id
    turn_blobs = blobs if blobs is not None else api_blob_store(turn_workspace_id)
    turn_cache_root = (
        engine_cache_root
        if engine_cache_root is not None
        else api_engine_cache_root(turn_workspace_id)
    )
    web_doc = document["scene"]
    try:
        # F2.3: the workspace's cloned-section registry. Built once, up here, because two
        # things now need it: the brief's ANNOTATION lines resolve an annotated inner path
        # against the artifact's stored HTML through `read_source`, and the runtime gets the
        # whole registry as a capability further down (see the F2.3 note at its `replace`).
        cloned_section_registry = DurableAgentClonedSectionRegistry(
            blobs=turn_blobs, cache_dir=turn_cache_root
        )
        if target_node_ids:
            # R-A5: the TURN TARGET lines name the selection the way the human's layers
            # panel does. A selected CLONE is named from the registry, so the rows are
            # read here — where the database is — exactly as the read route reads them
            # (`GET /documents/{id}`), and only when this document pins something, so a
            # clone-free turn pays for no registry scan. The build happens inside this
            # try for the same reason everything else does: a turn that cannot reach the
            # registry must fold into a failed envelope, not raise out of this function.
            fragment_meta = (
                fragment_meta_for_document(
                    {"doc_kind": "web", "scene": web_doc},
                    HybridRepository(workspace_id=turn_workspace_id).list_web_fragments(),
                )
                if web_doc_all_fragment_ids(web_doc)
                else None
            )
            prompt = prompt + _describe_web_turn_targets(
                web_doc,
                target_node_ids,
                fragment_meta=fragment_meta,
                target_notes=list(target_notes) if target_notes else None,
                read_source=cloned_section_registry.read_source,
            )
        config = AgentRuntimeConfig.from_env(root)
        if session_id:
            # Session continuity (2026-09-18): see run_agent_turn_preview. The document's session
            # owns the runtime's folder; the run id rides along so a retried run resumes rather
            # than opening a second turn on the thread.
            config = replace(config, session_id=session_id, run_id=run_id)
        if platform_reads is not None:
            # Design note 2026-09-19: see run_agent_turn_preview — a leg turn's platform reads,
            # by value, and nothing on any other path.
            config = replace(config, platform_reads=platform_reads)
        if model:
            config = replace(config, model=model)
        if config.asset_store_root is None:
            # D4: generated imagery must land in (and export from) the request workspace's
            # engine cache, exactly as the scene path pins it.
            config = replace(config, asset_store_root=turn_cache_root)
        # Vendor-first logo family cache (decision #4): per workspace, keyed by registrable
        # domain; the tool degrades to uncached fetching when this is None.
        config = replace(config, logo_family_cache=DurableLogoFamilyCache(blobs=turn_blobs))
        # The agent's in-loop preview resolves every `<img data-asset=…>` against
        # `config.asset_base_url`. Unlike the HTTP render route above (which derives it from
        # `request.base_url`), this path has NO request: a web turn is leased fleet work and
        # runs in a detached worker. So the value is CONFIGURED — `AgentRuntimeConfig.from_env`
        # reads `settings.asset_base_url` (LUMEN_API_ORIGIN), and it is asserted here rather
        # than re-derived so there is exactly one home for it. It used to be a hardcoded
        # `http://127.0.0.1:8000/asset-store` inside the agent substrate, pointing at a port
        # nothing has listened on since the design API moved to 8010 — which is why the agent
        # saw broken images in its own screenshots and stripped every asset it placed.
        if not config.asset_base_url:
            raise ValueError(
                "web turn has no asset_base_url — the agent's preview would render every "
                "placed image broken. Set LUMEN_API_ORIGIN to the design API's origin."
            )
        if asset_library is not None:
            config = replace(config, asset_library=asset_library,
                             asset_materializer=asset_materializer(asset_library, turn_blobs, str(turn_cache_root)))
        for aid, entry in (config.brand_kit_assets or {}).items():
            if aid in (asset_library or {}):
                entry.update({key: value for key, value in asset_library[aid].items() if key != "record"})
        # F1.3: resolve the artifacts this document ALREADY pins HERE, where the database is, and
        # hand them to the runtime BY VALUE — the same rule asset_library follows, because a fleet
        # worker never reads the API database.
        #
        # This is the turn's STARTING package, not its final one (amended F2.3). Nothing in a turn
        # can mint a fragment, but a turn CAN now pin one: `insert_cloned_section` adds the
        # artifact it just resolved to this package (`_admit_fragment_artifact`), so a band the
        # agent placed renders in its own screenshots instead of coming back as the engine's
        # placeholder for the visual reviewer to judge. A pin that reaches the document by any
        # OTHER route mid-turn — hand-built ops naming an id nothing resolved — still renders the
        # placeholder, which is the honest answer rather than an improvised one.
        #
        # F5: EVERY page's pins, not the home page's. A turn is of a DOCUMENT — the agent can
        # author on any page during it — so a package scoped to one page would render a band
        # pinned on `/pricing` as the engine's placeholder in the agent's own screenshots, and
        # the visual reviewer would judge the hole.
        if web_doc_all_fragment_ids(web_doc):
            config = replace(
                config,
                fragment_render_package=build_fragment_render_package_for_document(
                    turn_blobs.storage,
                    workspace_id=turn_workspace_id,
                    web_doc=web_doc,
                ),
            )
        # F2.3: the WORKSPACE's released cloned sections, as a capability rather than a value —
        # the rule `custom_component_registry` follows, for the same reason. The package above
        # answers "what does this document already pin?"; this answers "what may it pin next?",
        # and that second question is a PERMISSION question whose answer must come from the
        # document write's own gate at the moment it is asked, not from a snapshot of the
        # registry taken when the turn was composed.
        config = replace(config, cloned_section_registry=cloned_section_registry)
        if account_logo_binder is not None:
            # F4.3 (ruling R25-1): the G1+G2 bridge. Passed IN rather than built here — unlike
            # the cloned-section registry it needs the governed tool invoker, which lives at the
            # worker seam (the `custom_component_registry` shape, and for the same reason).
            #
            # It is NOT gated on `account_card`: an ABM template is authored for the whole
            # campaign rather than for one account, so the turn that fetches a target's mark
            # usually carries no card — and refusing to bind then would leave exactly the gap
            # this closes. The binder's own doors (the account must exist in THIS workspace, the
            # bytes must be durably readable) are the permission answer, taken when it is asked.
            config = replace(config, account_logo_binder=account_logo_binder)
        if custom_component_registry is not None:
            config = replace(
                config,
                custom_component_registry=custom_component_registry,
                custom_component_account_id=(
                    custom_component_registry.account_id
                ),
                custom_component_document_id=(
                    custom_component_registry.document_id
                ),
            )
        if target_node_ids:
            config = replace(
                config, turn_target_node_ids=list(target_node_ids)
            )
        if target_notes:
            # The runtime's own prompt block reads these; the brief addendum above is the
            # API's rendering of the same facts, so both sides see one submission order.
            config = replace(config, turn_target_notes=list(target_notes))
        brand_kit, brand_kit_source, brand_kit_assets, brand_fonts = (
            resolve_web_turn_brand_kit(web_doc, turn_blobs)
        )
        if brand_kit is not None:
            config = replace(
                config,
                brand_kit=brand_kit,
                brand_kit_source=brand_kit_source,
                brand_kit_assets=brand_kit_assets,
                brand_fonts=brand_fonts,
            )
            # Web-fonts runtime seam (closed in P2.5): the runtime substrate
            # builds its own data-URL @font-face CSS from config.brand_fonts
            # (LumenWebTools._font_face_css) for its in-loop previews —
            # Playwright renders via set_content with no asset server, so the
            # URL-based CSS this endpoint builds would not resolve there.
        if account_card:
            # BY VALUE, mirroring brand_kit: the card for the prompts/view, plus
            # its logo AssetRecord manifest so use_account_asset can upsert it.
            config = replace(
                config,
                account_card=account_card,
                account_assets=resolve_account_assets(
                    account_card, turn_workspace_id
                ),
            )
        # Mandatory-multimodal (the reviewer attaches screenshots): fail loud
        # before authoring if the configured model is text-only.
        from lumen_agent.llm import assert_model_supports_image_input

        assert_model_supports_image_input(
            config.model,
            base_url=config.agent_base_url,
            api_key=config.agent_api_key,
        )
        # Session continuity (2026-09-18): the WEB harness has no candidate-bundle rebase, so the
        # session folder is exactly where this config says it is. Restored before the runtime
        # touches the workspace; snapshotted on the way out.
        session_dir = config.session_dir()
        history_file = (
            None
            if session_dir is None
            else config.trace_dir / "conversation_history" / f"{session_id}.md"
        )
        if session_dir is not None and not session_dir.exists() and session_manifest is not None:
            restored = restore_session(
                session_dir,
                session_manifest,
                read_blob=turn_blobs.read_blob,
                history_file=history_file,
            )
            api_logger.info(
                "design_session.restored", session_id=session_id, files=restored
            )
        result = run_deepagent_web_turn(
            prompt=prompt,
            config=config,
            initial_web_doc=web_doc,
            event_sink=event_sink,
            # D5 Round B: see run_agent_turn_preview.
            checkpointer=checkpointer,
            thread_id=thread_id,
            # A3 (defect R3-D): see run_agent_turn_preview. A web turn's cancelled outcome is
            # `failed` with nothing applied — website mode persists once at the end, so there
            # is no partial work a stop could keep.
            cancel_requested=cancel_requested,
            # Lane 3 slice 5: see run_agent_turn_preview.
            callbacks=callbacks,
        )
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.failed",
            "Agent runtime failed before returning a result.",
            str(error),
        )

    return _stamp_session_manifest(
        {
            "schema_version": 1,
            "status": result.get("status"),
            "outcome": result.get("outcome"),
            "summary": result.get("summary"),
            "web_doc": result.get("web_doc"),
            "operations": result.get("operations", []),
            "grounding": result.get(
                "grounding", {"schema_version": 1, "sources": [], "citations": []}
            ),
            "preview_paths": result.get("preview_paths", []),
            "doc_kind": "web",
        },
        session_dir=session_dir,
        history_file=history_file,
        session_id=session_id,
        blobs=turn_blobs,
        snapshot_session=snapshot_session,
    )


# --- fleet turn executors (D5 Round B) --------------------------------------------------------
#
# These are the pre-D5 daemon-thread worker closures, promoted to module functions and driven
# from the frozen envelope instead of from captured locals. They live HERE, in main.py, because
# every by-value resolver they need (brand kit, fonts, references, the asset library, the engine
# cache root, the custom-component registry) already lives here; ``fleet_handler`` imports them
# lazily to avoid the import cycle that direction would otherwise create.
#
# Contract: return ``(run_status, response, event_type, event_data)`` and NEVER raise — the caller
# lands all four in one fenced ``complete_run``. An executor that raised would leave a claimed run
# with no terminal row, which is the one failure the whole slice exists to make impossible.


def _turn_blob_store(host: Any, workspace_id: str) -> DesignBlobStore:
    """The turn's byte store. Prefers the host's injected backend (a test's throwaway
    ``FsStorage``) and falls back to the process-wide configured one, which is what a detached
    fleet worker always has."""
    return (
        DesignBlobStore(host.storage, workspace_id)
        if host.storage is not None
        else api_blob_store(workspace_id)
    )


def _turn_design_tools(
    host: Any, subject: Optional[DesignRunSubject] = None
) -> DesignToolInvocations:
    """The governed design write path for one turn (Part II D6, ruling R-D6-5).

    The deep agent's two durable component writes (source + compile) go through the SAME tools
    the HTTP routes do, so an agent-authored component is journaled and A9-keyed exactly like a
    human-authored one — with ``actor="agent"`` on the invocation span (REQ-20 parity). The host
    here is whichever one is driving the turn (the live ``app.state`` under the embedded worker,
    the fleet handler's frozen turn host under a detached one), so a test's injected storage and
    stubbed compiler reach the tools unchanged.

    ``subject`` (D7) names the run these invocations belong to and the lease generation they are
    fenced by, so each one's journal events also reach that run's event stream. It is ``None`` for
    any caller with no run in flight — the tools then journal exactly as before and emit nothing.
    """
    storage = host.storage if host.storage is not None else storage_from_settings()
    return DesignToolInvocations(
        host=design_tool_host(
            storage=storage,
            core=lambda: _turn_core(host),
            engine_cache_dir=lambda ws: str(_host_engine_cache_root(host, ws)),
            web_export_node_bin=lambda: "node",
            compiler_node_bin=lambda: host.compiler_node_bin,
            compiler_worker_path=lambda: Path(
                host.compiler_worker
                if host.compiler_worker is not None
                else default_compiler_worker_path()
            ),
            compiler_timeout_seconds=lambda: (
                host.compiler_timeout_seconds
                if host.compiler_timeout_seconds is not None
                else DEFAULT_COMPILER_TIMEOUT_SECONDS
            ),
            compile_fn=lambda: compile_custom_component,
        ),
        storage=storage,
        run_subject=subject,
    )


def _host_engine_cache_root(host: Any, workspace_id: str) -> Path:
    """The job's engine materialization cache, preferring the dispatching app's tree.

    D5 Round C closes the last "re-derived default" on the worker path. ``api_engine_cache_root``
    resolves the root from ``settings``; an app built with an explicit ``engine_cache_root`` (the
    whole design suite, and any deployment that overrides it) would then have its worker write
    into a DIFFERENT tree from the one its request paths read. Byte custody is durable either way
    since D4, but the mirror divergence is exactly the kind of invisible split this round exists
    to remove — so when the host carries the app's root, that is the one used.
    """
    if host.engine_cache_root is not None:
        path = Path(host.engine_cache_root) / workspace_id
        path.mkdir(parents=True, exist_ok=True)
        return path
    return api_engine_cache_root(workspace_id)


def _turn_core(host: Any) -> CoreClient:
    """The Rust engine client. The detached fleet worker has no ``app.state`` to take one from,
    so it builds the same client ``create_app`` would."""
    return host.core if host.core is not None else CoreClient()


def _page_dimensions(page: JsonObject) -> Optional[tuple[str, str, str]]:
    """``("1200", "1200", "pt")`` for a page whose size the scene states, else ``None``."""

    size = page.get("size")
    if not isinstance(size, dict):
        return None
    rendered: list[str] = []
    for key in ("width", "height"):
        value = size.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        rendered.append(str(int(value)) if float(value).is_integer() else f"{float(value):g}")
    unit = size.get("unit")
    return rendered[0], rendered[1], unit if isinstance(unit, str) else ""


def _quotable_page_name(page: JsonObject) -> Optional[str]:
    """The page's own name, iff it can ride a DSL string literal verbatim.

    The example below restates this name to keep the page-modify line legal (see
    :func:`_empty_page_steering_note`), so it must be reproduced EXACTLY — a name carrying a
    quote, a backslash or a newline would need escaping this note cannot verify against the
    grammar, and a guessed escape in an instruction block is worse than no instruction. Every
    engine-minted page has a plain name (the ad birth's format label; ``lower_page`` names a
    DSL-born page after its id), so this is a guard, not a common path.
    """

    name = page.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if any(character in name for character in ('"', "\\", "\n", "\r")):
        return None
    return name


def _empty_page_steering_note(scene: Any) -> Optional[str]:
    """The document-state block a LEG turn gets when every page of its scene is EMPTY.

    A chat-born ad (genad) is BORN with one empty artboard page — the leg-open birth mints
    ``new_scene`` plus one ``add_page`` at the resolved format — where every scene leg before
    it pinned a document that already had content. The author model's from-scratch habit is to
    open the turn with a top-level ``page ...`` block, and on this shape that cannot work: the
    page id already exists, so a page line that parses is refused by the engine (``page <id>
    already exists``, ``operations.rs::add_page``) and one that does not parse leaves its
    indented elements without a parent (``LUMD0402``). The acceptance walk watched five runs
    thrash the repair loop on exactly that, across two different author models, until the
    request died upstream.

    So the turn states the document's shape as DATA and quotes the form that works. Every
    quoted form was verified against the real engine before it was written here:

    * ``#page:<page_id> name("<its current name>")`` + an indented subtree is the empty-page
      compose path (``dsl.rs``'s "Empty-page compose gap": a top-level page modification opens
      that page as the parent frame). The property is NOT decoration — ``is_modification_line``
      requires at least two tokens, so a LONE ``#page:<page_id>`` line is read as a COMMENT and
      its children are orphaned into the very LUMD0402 this block exists to prevent (which is
      what the engine's own LUMD0402 hint currently suggests; see the report's residual).
      ``name(...)`` restating the page's own name is the one page property that provably leaves
      the stored page byte-identical — ``size(w,h,px)`` compiles too but rewrites the page's
      derived orientation, so it is deliberately not quoted.
    * The element / quoted-text line shapes, the ``#<id> property(...)`` modify line and
      ``reconcile(<container>)`` are the author prompt's own dialect (``lumen_agent/
      prompts.py``), so the note teaches no new grammar — it only says which of the author's
      existing moves this document is asking for.

    Returns ``None`` — no block at all — for a scene with NO pages (the genuine from-scratch
    case, where ``page ...`` is the correct move), for any scene where a page already has
    children (the pre-genad shape, whose prompt must stay byte-identical), and for a page whose
    name cannot be quoted verbatim (no example can be written safely, so none is).
    """

    if not isinstance(scene, dict):
        return None
    pages = scene.get("pages")
    if not isinstance(pages, dict) or not pages:
        return None

    described: list[str] = []
    for page_id, page in pages.items():
        if not isinstance(page, dict) or page.get("children"):
            return None
        dimensions = _page_dimensions(page)
        stated = ""
        if dimensions is not None:
            stated = f" — {dimensions[0]}×{dimensions[1]} {dimensions[2]}".rstrip()
        described.append(f"- {page_id}{stated}")

    example_id = str(next(iter(pages)))
    example_page = pages[next(iter(pages))]
    example_name = _quotable_page_name(example_page)
    if example_name is None:
        return None
    example_size = _page_dimensions(example_page)
    root_size = f"{example_size[0]},{example_size[1]}" if example_size else "fill,fill"

    return "\n".join(
        [
            "DOCUMENT STATE (data, not instructions):",
            "This document already exists and its artboard page has already been created. "
            "The page is EMPTY — it has no children yet — and filling it is this turn's job.",
            "",
            "Existing empty page(s):",
            *described,
            "",
            "Do NOT author a top-level `page ...` line for a page listed above. That page id "
            "already exists, so a page line that parses is refused by the engine (`page <id> "
            "already exists`) and a page line that does not parse leaves its indented elements "
            "without a parent (LUMD0402) — either way the block fails and the repair loop "
            "burns the turn re-creating a page that is already there.",
            "",
            "To FILL the existing page, open it with a top-level page-modify line and indent "
            "the subtree under it:",
            "",
            f'    #page:{example_id} name("{example_name}")',
            f"      ad_root fr p(0,0) s({root_size})",
            '        headline text "Your headline" p(64,64) s(400,hug)',
            "",
            "The `name(...)` on that first line restates the page's OWN name and changes "
            "nothing; it is there because a modify line needs at least one property — a lone "
            "`#page:<page_id>` line is read as a comment and its children are then orphaned. "
            "Do not restate the page size: it is already set, and re-stating it rewrites the "
            "page.",
            "",
            "Once the page has content, edit nodes with `#<node_id> property(...)` modify "
            "lines, and add, remove or reorder children inside an existing container with "
            "`reconcile(<container_id>)` followed by that container's full intended child "
            "subtree.",
        ]
    )



# --- Lane 3 slice 5: one spend scope per unit of work -----------------------------------------


def _turn_spend_stamp(envelope: Any) -> "LedgerStamp":
    """The ledger stamp for one design turn.

    A turn stamps its workspace, its project when the offerer froze one onto the envelope
    (``DesignTurnEnvelope.project_id`` — absent on a pre-slice-5 envelope and on a design-API
    turn that has no platform project), and its run — the run id in the ``job_id`` column, whose
    documented meaning is "the job that spent". A run id that is not a UUID stamps without the
    job rather than failing the turn: an unstampable row is still a row, and losing the money
    trail to a parse error would be the worse answer.

    ``getattr`` rather than an attribute read because this executor also runs envelopes replayed
    verbatim from rows frozen before the field existed.
    """
    from clue_spend import LedgerStamp

    try:
        job_id = UUID(str(envelope.run_id))
    except (TypeError, ValueError):
        job_id = None
    return LedgerStamp(
        workspace_id=envelope.workspace_id,
        project_id=getattr(envelope, "project_id", None),
        job_id=job_id,
    )


@contextmanager
def _setup_step(run_id: str, step: str):
    """Log how long one step of a design turn's setup took, before the agent starts.

    A follow-up edit spent ~100 s here with one silent minute (2026-10-16); these lines make
    each step's share visible in the worker log as ``design_turn.setup_step``.
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        api_logger.info(
            "design_turn.setup_step",
            run_id=run_id,
            step=step,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )


@contextmanager
def _request_spend_scope(workspace_id: str):
    """One request's spend scope, drained on the way out. For a route that spends.

    A request carries no project or run of its own, so the stamp is the workspace alone — the
    shape ``LedgerStamp`` documents for "a display page or a chat-turn tool".
    """
    from clue_spend import LedgerStamp

    from . import spend as _spend

    with _spend.spend_scope(LedgerStamp(workspace_id=workspace_id)) as scope:
        try:
            yield scope
        finally:
            _drain_spend(scope)


def _turn_model_call_collector(callbacks: Any) -> Tuple[Any, Any]:
    """The turn's ONE model-call collector, and the ``TurnCallbacks`` to hand the harness.

    Lane 3 slice 5. The collector is opened HERE, at the executor, rather than inside the harness,
    because this is the only frame that sees every terminal-status return — including the ones
    that REPLACE the harness's response dict (a pageless proposal, an un-replayable web operation
    history). A turn that spent money and then failed validation must still come back with its
    receipts.

    Returns ``(None, callbacks)`` when the agent runtime is not importable in this process: the
    design API is deployed without it in some shapes, and a missing collector must degrade to "no
    receipts", never to a failed turn.
    """
    try:
        from lumen_agent.usage_collector import ModelCallCollector, TurnCallbacks
    except Exception:  # pragma: no cover - deployment shape, not logic
        return None, callbacks
    langfuse_ids = getattr(callbacks, "langfuse_ids", None)
    collector = ModelCallCollector(langfuse_ids=langfuse_ids)
    injected = tuple(getattr(callbacks, "handlers", ()) or ())
    return collector, TurnCallbacks(
        handlers=(collector, *injected), langfuse_ids=langfuse_ids
    )


def _with_model_calls(response: JsonObject, collector: Any) -> JsonObject:
    """Stamp the turn's per-call receipts onto the dict that becomes the run's ``result_json``.

    Always present when a collector exists, even as ``[]`` — "this turn made no model calls" is a
    fact a cost reader needs to be able to read, and an absent key would be indistinguishable
    from an executor that forgot.
    """
    if collector is None or not isinstance(response, dict):
        return response
    return {**response, "model_calls": [call.as_json() for call in collector.calls]}


def _document_drift_note(
    store: HybridRepository, *, document_id: str, current_version: int
) -> str | None:
    """What moved under this document's session since the agent last wrote it, or ``None``.

    Session continuity (2026-09-18): a continued session holds the scene IT wrote, so anything a
    human (or another leg) committed in between has to be SAID — as data, never as instructions.

    ``None`` means nothing moved, no agent turn has ever written this document, or the read itself
    failed: the note is advisory context, so an unreadable history costs the agent one paragraph
    and never a paid turn. Shared by both executors so the two can never disagree on what drift is.
    """
    try:
        last_written = store.latest_agent_written_version(document_id)
        if last_written is None or last_written >= current_version:
            return None
        return render_document_drift_note(
            previous_version=last_written,
            current_version=current_version,
            envelopes=store.list_envelopes(document_id, newest_first=False),
        )
    except Exception as error:  # noqa: BLE001 - advisory context never fails a turn
        api_logger.warning(
            "design_turn.drift_note_unavailable",
            document_id=document_id,
            current_version=current_version,
            error=str(error),
        )
        return None


def _session_manifest(
    store: HybridRepository, blobs: DesignBlobStore, *, document_id: str
) -> JsonObject | None:
    """This document's session-folder manifest from its last synced turn, or ``None``.

    Session continuity (2026-09-18): the runtime restores the session folder from this when the
    turn lands on a worker that has never run this session. Read HERE, at the executor, because
    this is the frame that has the database; the runtime is handed the manifest BY VALUE, the
    same rule the brand kit and the asset library follow.

    ``None`` means no turn has synced this session yet, or the read itself failed. A missing
    manifest is not a failure: the runtime simply starts the session's folder fresh, which is
    what the very first turn of every session does anyway. Shared by both executors so the two
    can never disagree on where a session's memory comes from.
    """
    try:
        sha = store.latest_session_manifest_sha256(document_id)
        if sha is None:
            return None
        _, data = blobs.read_blob(sha)
        manifest = json.loads(data)
        return manifest if isinstance(manifest, dict) else None
    except Exception as error:  # noqa: BLE001 - an unreadable manifest costs memory, not the turn
        api_logger.warning(
            "design_session.manifest_unavailable",
            document_id=document_id,
            error=str(error),
        )
        return None


def execute_agent_turn_job(
    envelope: Any,
    *,
    store: HybridRepository,
    host: Any,
    event_sink: Any,
    checkpointer: Any = None,
    lease_generation: Optional[int] = None,
    spend_drain: Any = None,
    callbacks: Any = None,
    session_continued: bool = False,
) -> Tuple[str, JsonObject, str, JsonObject]:
    """One scene-mode turn under its own spend scope — see :func:`_execute_agent_turn_job`.

    Every paid call the turn makes (image generation, the ad style-group tie-break) runs through
    this scope's ``ProviderCaller`` and lands on ``provider_call_ledger`` when the turn ends.
    ``spend_drain`` is the injected drain (PRE-1b): the platform passes one that also records a
    provider incident, so that bookkeeping lives once on its side.

    ``callbacks`` (lane 3 slice 5) is the platform's injected ``TurnCallbacks`` — its Langfuse
    handler and the run-id registry that handler fills. This frame adds the turn's own
    ``ModelCallCollector`` to them and stamps what it collected onto the response, which is what
    ``complete_run`` persists as the run's ``result_json``.
    """
    from . import spend as _spend

    collector, turn_callbacks = _turn_model_call_collector(callbacks)
    with _spend.spend_scope(_turn_spend_stamp(envelope), drain_fn=spend_drain) as scope:
        try:
            status, response, event_type, event_data = _execute_agent_turn_job(
                envelope,
                store=store,
                host=host,
                event_sink=event_sink,
                checkpointer=checkpointer,
                lease_generation=lease_generation,
                callbacks=turn_callbacks,
                session_continued=session_continued,
            )
            return status, _with_model_calls(response, collector), event_type, event_data
        finally:
            _drain_spend(scope)


def _execute_agent_turn_job(
    envelope: Any,
    *,
    store: HybridRepository,
    host: Any,
    event_sink: Any,
    checkpointer: Any = None,
    lease_generation: Optional[int] = None,
    callbacks: Any = None,
    session_continued: bool = False,
) -> Tuple[str, JsonObject, str, JsonObject]:
    """One scene-mode turn, executed from its frozen envelope.

    A LEG turn (genad Task 5) OWNS its persist, exactly as the web executor has since D6: the
    proposal is replayed against the stored document and committed under the leg block's frozen
    ``document_base_version``, so a turn that took minutes can never silently clobber a human
    edit made while it ran. A DIRECT editor turn carries no ``leg`` block, keeps proposing, and
    its result envelope stays byte-identical — the editor still owns that commit through
    ``POST /documents/{id}/operations``.

    ``lease_generation`` (D7) fences the governed tool invocation that persist makes, exactly as
    it fences the web executor's.
    """
    run_subject = DesignRunSubject(
        run_id=envelope.run_id, lease_generation=lease_generation
    )
    payload = AgentTurnPreviewRequest.model_validate(envelope.config.get("request") or {})
    scoped_preferences = None
    runtime_workspace_guard = None
    if "design_memory" in envelope.config:
        # The platform verifies this opaque selection against its durable scope,
        # run and journal authority. Never treat a queued body-free pin as access.
        factory = getattr(host, "preference_resolver_factory", None)
        try:
            if not callable(factory):
                raise RuntimeError("preference authority unavailable")
            scoped_preferences = factory(envelope)
            if scoped_preferences is not None and not callable(scoped_preferences):
                raise RuntimeError("invalid preference resolver")
        except Exception:
            failed = failed_agent_turn_response(
                "scoped_preferences.unavailable",
                "Saved design preferences could not be authorized for this turn.",
                "The platform must resolve this turn's original scoped selection before retrying.",
            )
            return "failed", failed, "error", {"message": "scoped preferences unavailable"}
        if scoped_preferences is not None:
            from .runtime_privacy import bind_runtime_workspace

            def runtime_workspace_guard(inner_run_id, trace_dir):
                return bind_runtime_workspace(
                    workspace_id=envelope.workspace_id, outer_run_id=envelope.run_id,
                    inner_run_id=inner_run_id, trace_dir=trace_dir,
                    emit=lambda event, data: store.emit_run_event(
                        envelope.run_id, event, data, expected_generation=lease_generation,
                    ),
                )
    # G9: the USER's own words, captured BEFORE the leg prompt render below composes the brief
    # and the history into them. This is the human-facing ``intent`` on the durable edit
    # envelope, so it must never become the rendered brief block.
    user_message = payload.prompt
    # An explicit None means "resolved: this turn has no references" — distinct from a missing
    # key. Platform LEG envelopes carry the frozen reference ids in ``request`` and deliberately
    # do not assemble or rasterize this worker's runtime manifest while accepting the turn, so a
    # missing manifest must take the normal in-worker resolution path. Using ``.get`` without the
    # sentinel made every accepted platform reference silently inert.
    reference_assets = envelope.config.get("reference_assets", _REFERENCES_UNRESOLVED)
    # W4 offer-time freeze: same missing-key-vs-null discipline as the reference manifest
    # above. A missing key is a LEGACY envelope (claim-time compose, now loud when this
    # process's flag is off); a present key — even null — is the offerer's decision, consumed
    # verbatim so the claiming process's env cannot change what the turn sees.
    frozen_ad_lane = envelope.config.get("ad_lane", ad_runtime.FROZEN_LANE_ABSENT)

    # --- P3.7: consume the platform leg envelope's frozen context ------------------------------
    # A design-leg turn (PD-part3 §2.3/§2.4) carries the delegation bundle, the leg history,
    # and the leg's pins on ``config``. Non-leg turns carry none of these and stay
    # byte-identical.
    leg_block = envelope.config.get("leg") or {}
    delegation_bundle = envelope.config.get("delegation_bundle")
    leg_history = envelope.config.get("history")

    # --- design note 2026-09-19: what this turn may read from the platform ---------------------
    # A LEG turn only. The factory is the platform's (composed at its composition root with the
    # journaled tool invoker); this side calls it and never assembles it. Reads are a CAPABILITY,
    # not a precondition — unlike the scoped preferences above, which are the human's explicit
    # selection and so refuse the turn when they cannot be authorized, a turn that cannot compose
    # these still designs from the brief, exactly as it did before this note.
    platform_reads = None
    if leg_block:
        reads_factory = getattr(host, "platform_reads_factory", None)
        if callable(reads_factory):
            try:
                with _setup_step(envelope.run_id, "platform_reads"):
                    platform_reads = reads_factory(envelope)
            except Exception:
                api_logger.warning(
                    "design_turn.platform_reads_unavailable",
                    run_id=envelope.run_id,
                    exc_info=True,
                )
                platform_reads = None

    # --- genad Task 5: is this turn's proposal ours to commit? ---------------------------------
    # ALL of: a leg block, a pinned document, and the leg's frozen CAS base. A direct editor turn
    # fails the first; a legacy (AD4.R-era) document-less leg fails the second and third. A
    # missing ``document_base_version`` is read as "preview-only", never as version zero — a
    # fabricated base would CAS against whatever happens to sit at the head and clobber it.
    document_id = payload.document_id
    base_version = leg_block.get("document_base_version") if isinstance(leg_block, dict) else None
    leg_persist = bool(leg_block) and bool(document_id) and base_version is not None
    workspace_id = envelope.workspace_id

    # --- session continuity (2026-09-18): the DOCUMENT is this turn's scene and its CAS base ---
    # The envelope froze a scene and a version when the leg dispatched; by the time a worker runs
    # the turn a human may have edited, and the agent's OWN previous turn certainly did. So the
    # document is re-read HERE, and what it holds is what the trio designs from and what the
    # write CAS's against. This REPLACES the pre-run conflict: "the document moved" is the normal
    # condition of a continued session, not a terminal failure. The write-time CAS (inside the
    # committer) still refuses the human edit that lands WHILE the turn runs — that window is the
    # one an early check never could close, and it is the only one worth failing for.
    doc: JsonObject | None = None
    drift_note: str | None = None
    if leg_persist:
        try:
            with _setup_step(envelope.run_id, "document_read"):
                doc = store.require_document(document_id)
        except Exception as error:  # noqa: BLE001 - mirrors the executor's own outer handler
            # Same shape the outer handler below mints, minted here because this read happens
            # before it opens: a turn that cannot read its own document has not begun.
            failed = failed_agent_turn_response(
                "agent_runtime.failed",
                "Agent turn crashed before returning a proposal.",
                str(error),
            )
            return "failed", failed, "error", {"message": str(error)}
        base_version = int(doc["current_version"])
        with _setup_step(envelope.run_id, "drift_note"):
            drift_note = _document_drift_note(
                store, document_id=str(document_id), current_version=base_version
            )
        payload = payload.model_copy(update={"scene": doc["scene"]})

    pinned_kit_id = leg_block.get("brand_kit_id") if isinstance(leg_block, dict) else None
    resolved_brand_kit: Any = _BRAND_KIT_UNRESOLVED
    if pinned_kit_id:
        # The D5 fail-closed brand pin, TOCTOU-free (adversarial-review fix): ONE read owns
        # both the check and the value. The kit is resolved fully here — kit, asset
        # manifest, font spec — fail-loud, and handed to the runtime BY VALUE, so the
        # tolerant resolver (whose except falls back to the platform default kit) never
        # runs for a pinned turn. A pin is (id, version): a version-less pin is refused
        # here rather than injecting a scene ref the engine cannot deserialize mid-turn.
        pinned_version = leg_block.get("brand_kit_version")
        try:
            if pinned_version is None:
                raise ValueError(
                    "the leg's brand pin carries no version; a pin is (id, version)"
                )
            pinned_version = int(pinned_version)
            with _setup_step(envelope.run_id, "brand_kit"):
                resolved_brand_kit = load_brand_kit_by_value(
                    workspace_id=envelope.workspace_id,
                    brand_kit_id=str(pinned_kit_id),
                    version=pinned_version,
                    blobs=_turn_blob_store(host, envelope.workspace_id),
                    source="leg_pin",
                    ensure_workspace=False,
                )
        except Exception as error:
            failed = failed_agent_turn_response(
                "design_leg.brand_pin_unresolvable",
                "The design leg pins a brand kit this workspace cannot resolve.",
                f"brand_kit_id={pinned_kit_id} version={pinned_version}: {error}",
            )
            return "failed", failed, "error", {"message": "brand pin unresolvable"}
        pinned_scene = dict(payload.scene or {})
        pinned_meta = dict(pinned_scene.get("meta") or {})
        pinned_meta["brand_kit"] = {"id": str(pinned_kit_id), "version": pinned_version}
        pinned_scene["meta"] = pinned_meta
        payload = payload.model_copy(update={"scene": pinned_scene})

    # genad walk F1: a LEG turn on an all-empty-paged scene (the chat-born ad at birth) is
    # steered to FILL its existing artboard rather than author a `page ...` line the engine
    # cannot accept. LEG-ONLY and shape-gated: a direct editor turn (no leg block) and a leg
    # turn on a content-bearing or page-less scene compose byte-identically to before. The
    # block sits AFTER the brief and history and immediately before the user's message, so
    # the prefill-cached prefix those two form (P3.7's block order) is untouched.
    steering_note = _empty_page_steering_note(payload.scene) if leg_block else None
    composed_prompt = f"{steering_note}\n\n{payload.prompt}" if steering_note else payload.prompt
    # Session continuity (2026-09-18): on a CONTINUED thread the agent already holds every earlier
    # turn of this session, so re-sending the history block says the same thing twice. The
    # immutable delegation brief still opens each NEW leg — a new leg is a new assignment even on
    # a thread that has run before — which is what ``first_turn_of_leg`` (frozen by the platform's
    # leg runner) names. A fresh thread sends both, exactly as it always has.
    first_turn_of_leg = (
        bool(leg_block.get("first_turn_of_leg", True)) if isinstance(leg_block, dict) else True
    )
    bundle_block = (
        delegation_bundle
        if (delegation_bundle and (not session_continued or first_turn_of_leg))
        else None
    )
    history_block = None if session_continued else leg_history
    if bundle_block or history_block or drift_note:
        composed_prompt = render_leg_turn_prompt(
            bundle=bundle_block if isinstance(bundle_block, dict) else None,
            history=history_block if isinstance(history_block, list) else None,
            prompt=composed_prompt,
            drift_note=drift_note,
        )
    if composed_prompt != payload.prompt:
        payload = payload.model_copy(update={"prompt": composed_prompt})

    override = host.agent_turn_runner
    root = repo_root()
    # The session this turn belongs to: one document, one design session (2026-09-18). A SESSION IS
    # A LEG-TURN CONCEPT (ruling T6-1): it takes both a leg block and a pinned document. A direct
    # editor turn carries no leg block — the design API's own routes still thread it on its run id
    # (``main.py`` /agent/turns) — so it keeps today's per-run folder, joins no session, and its
    # prompt stays byte-identical. Note this is deliberately ONE step looser than ``leg_persist``:
    # a legacy leg that pins a document but froze no CAS base is still that document's session,
    # even though it commits nothing (and, reading no document, notices no drift).
    session_id = (
        design_session_id(workspace_id, str(document_id))
        if (leg_block and document_id)
        else None
    )
    try:
        committer: Optional[_LegSceneCommitter] = None
        if leg_persist:
            committer = _LegSceneCommitter(
                doc=doc,
                document_id=str(document_id),
                host=host,
                store=store,
                run_subject=run_subject,
                workspace_id=workspace_id,
                run_id=envelope.run_id,
                intent=user_message,
            )
        turn_asset_library = None
        turn_session_manifest = None
        if override is None:
            with _setup_step(envelope.run_id, "asset_library"):
                turn_asset_library = pinned_asset_library(store, envelope.run_id)
            if session_id:
                with _setup_step(envelope.run_id, "session_manifest"):
                    turn_session_manifest = _session_manifest(
                        store,
                        _turn_blob_store(host, envelope.workspace_id),
                        document_id=str(document_id),
                    )
        if override is not None:
            response = _call_turn_override(
                override, payload, root, scene_checkpoint=_checkpoint_sink(committer),
                scoped_preferences=scoped_preferences,
            )
        else:
            response = run_agent_turn_preview(
                payload,
                root,
                event_sink=event_sink,
                resolved_reference_assets=reference_assets,
                resolved_asset_library=turn_asset_library,
                frozen_ad_lane=frozen_ad_lane,
                workspace_id=envelope.workspace_id,
                # D5 Round C: the dispatching app's byte backend + engine-cache tree, so an
                # injected backend cannot stage bytes in one place and read them from another.
                blobs=_turn_blob_store(host, envelope.workspace_id),
                engine_cache_root=_host_engine_cache_root(host, envelope.workspace_id),
                checkpointer=checkpointer,
                thread_id=envelope.checkpoint_thread_id,
                # Session continuity (2026-09-18): the runtime's per-turn substrate lives under
                # this document's session folder, and the run id rides with it so a RETRIED run
                # reuses its own turn folder and is recognised as a resume rather than a new
                # turn on the thread (ruling T5-1).
                session_id=session_id,
                run_id=envelope.run_id if session_id else None,
                # ...and the memory that session left behind, so a turn on a worker that has
                # never run it rebuilds the folder instead of opening a continued thread over
                # an empty workspace.
                session_manifest=turn_session_manifest,
                resolved_brand_kit=resolved_brand_kit,
                # P0.4: only a LEG turn owns a persist, so only a leg turn checkpoints. A direct
                # editor turn passes None and stays save-nothing, exactly as before.
                scene_checkpoint=_checkpoint_sink(committer),
                # A3 (defect R3-D): every fleet-driven turn is cancellable, leg or not — the
                # doomed W5 run was a plain editor turn, and "you can only stop it if it came
                # from chat" would be an arbitrary line to draw through a paid run.
                cancel_requested=_run_cancel_probe(store, envelope.run_id),
                # Lane 3 slice 5: the platform's handlers plus this turn's receipt collector,
                # attached at the graph's invoke config by the harness.
                callbacks=callbacks,
                # Design note 2026-09-19: the platform's reads for this leg turn; None on every
                # other path, which leaves the runtime config as it was.
                platform_reads=platform_reads,
                **({"scoped_preferences": scoped_preferences} if scoped_preferences is not None else {}),
                **({"runtime_workspace_guard": runtime_workspace_guard} if runtime_workspace_guard is not None else {}),
            )
        operations = response.get("operations")
        if committer is not None and doc is not None and response.get("status") == "proposed":
            # ``doc`` is set together with ``leg_persist``, above — so everything in here is
            # LEG-ONLY, and a direct editor turn still falls straight through untouched.
            if isinstance(operations, list) and operations:
                response = _persist_leg_scene_proposal(
                    response,
                    committer=committer,
                    operations=operations,
                    document_id=str(document_id),
                    base_version=int(base_version),
                    store=store,
                )
            elif not (committer.scene.get("pages") or {}):
                # genad2 Task 3, the empty-proposal half of the >=1-page gate. A proposal with
                # nothing in it never reaches the persist function (there is nothing to replay),
                # so the gate is repeated here over the STORED scene — which, after P0.4, means
                # the scene this turn's last checkpoint left there, not the one it started from.
                # On a document that HAS a page an empty proposal is what it always was — a pure
                # clarification, a real outcome with nothing to commit, still a success. On a
                # page-less newborn it is a generation that produced nothing, and calling that a
                # finished design is exactly the lie the gate exists to refuse.
                response = pageless_agent_turn_response()
        # ``conflicted`` is minted ONLY by the leg-persist path above; a direct editor turn can
        # never produce it, so this mapping stays byte-identical for non-leg turns.
        status = (
            "failed"
            if response.get("status") in ("failed", "error", "conflicted")
            else "succeeded"
        )
        if (
            status == "failed"
            and committer is not None
            and committer.committed_operations
            and "current_version" not in response
        ):
            # P0.4 — the whole point, stated on the way out. The turn failed (a quota 403 at
            # finalize, a crash, a budget ceiling), but checkpoints made real work durable while
            # it ran. Naming the saved version keeps the result honest: the run failed AND the
            # gallery moved, which is strictly better than the old "nothing was saved".
            response = _leg_scene_version_stamp(
                response, str(document_id), int(base_version), store
            )
        return status, response, "result", {"status": response.get("status")}
    except Exception as error:  # pragma: no cover - defensive; the runner already folds failures
        failed = failed_agent_turn_response(
            "agent_runtime.failed",
            "Agent turn crashed before returning a proposal.",
            str(error),
        )
        return "failed", failed, "error", {"message": str(error)}


#: The durable mark one P0.4 checkpoint commit leaves on its run's event stream: the frontend's
#: mid-run progress signal, so the canvas can pin a real version instead of waiting out the whole
#: generation on version 0. It used to be a replay guard's evidence too — a redrive read it back
#: to tell a document its OWN earlier attempt had advanced apart from one a human had edited —
#: which session continuity (2026-09-18) retired along with the pre-run conflict: the executor
#: now re-reads the document and designs from where it actually is, so neither mover is a refusal.
SCENE_CHECKPOINT_EVENT = "scene_checkpoint_committed"


class _LegSceneCommitter:
    """Every durable scene write ONE leg turn makes, in ledger order, through the one governed
    write path — the P0.4 mid-run checkpoints and the final commit alike.

    Before P0.4 a leg turn wrote once, at finalize, so a run that died on the last call (the
    2026-08-24 quota 403 at 20m42s) discarded a fully valid, reviewer-accepted scene and left the
    document at version 0. Now each verified authoring round commits, and a terminal failure
    costs one round instead of the run.

    The arithmetic is what makes checkpoints *strictly additive*. Each write applies only the
    operations not yet durable onto the scene the previous write produced, and CAS's on the
    version that write left behind; ``update_document_state`` advances the version by exactly
    ``len(ops)``. So a turn proposing N operations ends at ``base + N`` whether it checkpointed
    five times or not at all — same destination, same final scene, just visible on the way.

    A checkpoint is BEST-EFFORT and a commit is not: :meth:`checkpoint` swallows every failure
    (a lost version is never a lost run, and the un-committed tail is simply re-offered inside
    the next checkpoint), while :meth:`commit` raises so the finalize path can keep minting the
    exact honest refusals it always has.
    """

    def __init__(
        self,
        *,
        doc: JsonObject,
        document_id: str,
        host: Any,
        store: HybridRepository,
        run_subject: DesignRunSubject,
        workspace_id: str,
        run_id: str,
        intent: str,
    ) -> None:
        self._document_id = document_id
        self._host = host
        self._store = store
        self._run_subject = run_subject
        self._workspace_id = workspace_id
        self._run_id = run_id
        self._intent = intent
        #: The version the next write CAS's against — the leg's frozen base until we move it.
        self.version = int(doc["current_version"])
        #: The scene the next write applies its operations onto.
        self.scene: JsonObject = doc["scene"]
        #: How much of the run's operation ledger is already durable.
        self.committed_operations = 0

    def pending(self, operations: List[JsonObject]) -> List[JsonObject]:
        """The ledger tail this turn has not yet made durable."""
        return list(operations)[self.committed_operations :]

    def replay(self, delta: List[JsonObject]) -> JsonObject:
        """Reproduce ``delta`` through the engine against the scene the next write overwrites.

        The agent's operation history is a CLAIM until this succeeds — an unreplayable history
        would otherwise be committed as a scene nobody can undo — and the inverse operations the
        edit envelope carries come out of this same call. Raises :class:`CoreError`.
        """
        return _turn_core(self._host).apply_operations(self.scene, delta)

    def commit(self, delta: List[JsonObject], applied: JsonObject, label: str) -> None:
        """Write one already-replayed operation batch, then advance our bookkeeping.

        The caller replays and vets ``delta`` first (the engine reproducing the agent's claimed
        history against the scene we are about to overwrite is the precondition for trusting it),
        so this is only the write. Raises on conflict or write failure — nothing is advanced when
        it does, which is what lets a refused checkpoint be re-offered whole.
        """
        # D4 backstop, unchanged and now per-commit: imagery a turn generated lives only in the
        # engine's wipeable cache until an accept seam gives it durable custody. A checkpoint IS
        # an accept seam, so custody must happen here too — otherwise a checkpointed scene could
        # reference bytes that the next cache wipe takes with it.
        register_scene_asset_backstop(
            _turn_blob_store(self._host, self._workspace_id),
            _host_engine_cache_root(self._host, self._workspace_id),
            applied["scene"],
        )
        _turn_design_tools(self._host, self._run_subject).invoke(
            "design_apply_operations",
            {
                "document_id": self._document_id,
                "scene": applied["scene"],
                "diagnostics": applied.get("diagnostics", []),
                "operations": delta,
                "source": "agent",
                "actor_kind": "agent",
                "actor_id": self._run_id,
                "envelope": {
                    # The USER's words, never the composed runtime prompt (G9).
                    "intent": self._intent[:120],
                    "checkpoint_label": label,
                    "inverse_operations": (applied.get("edit") or {}).get(
                        "inverse_operations"
                    ),
                },
                "expected_base_version": self.version,
            },
            workspace_id=self._workspace_id,
            actor="agent",
            actor_id=self._run_id,
        )
        self.version += len(delta)
        self.scene = applied["scene"]
        self.committed_operations += len(delta)

    def checkpoint(self, operations: List[JsonObject], meta: JsonObject) -> None:
        """The runtime's checkpoint sink (see ``LumenDesignTools.checkpoint_scene``).

        Contains everything. A checkpoint that cannot be taken — the engine refuses the replay, a
        human edit moved the document under us, the write fails — is logged and dropped, and the
        run continues to its own finalize, which is still the turn's authority.
        """
        delta = self.pending(operations)
        if not delta:
            return
        try:
            applied = self.replay(delta)
            if has_error_diagnostics(applied.get("diagnostics") or []):
                # The same precondition finalize enforces: an operation history the engine cannot
                # reproduce is not committed. Here it is simply skipped — finalize will say so.
                return self._skip(delta, meta, "the engine refused the round's operations")
            if not (applied["scene"].get("pages") or {}):
                # genad2's >=1-page gate: a page-less scene is not a design yet, so there is
                # nothing worth a version. Not an error — just too early to checkpoint.
                return
            self.commit(delta, applied, "Design turn (in progress)")
        except Exception as error:  # noqa: BLE001 - a checkpoint never fails a run
            return self._skip(delta, meta, str(error))
        try:
            self._store.emit_run_event(
                self._run_id,
                SCENE_CHECKPOINT_EVENT,
                {
                    "document_id": self._document_id,
                    "version": self.version,
                    "operations": self.committed_operations,
                    "reason": meta.get("reason"),
                    "preflight_clean": meta.get("preflight_clean"),
                },
                expected_generation=self._run_subject.lease_generation,
            )
        except Exception as error:  # noqa: BLE001 - the commit already landed; the mark is extra
            # Losing the mark costs the frontend one progress frame and costs a redrive its
            # self-recognition (it will read the moved document as a human conflict, which is
            # wrong but safe — it refuses rather than double-commits).
            api_logger.warning(
                "leg_scene_turn.checkpoint_mark_failed",
                document_id=self._document_id,
                run_id=self._run_id,
                version=self.version,
                error=str(error),
            )

    def _skip(self, delta: List[JsonObject], meta: JsonObject, reason: str) -> None:
        """Record a checkpoint that could not be taken. The operations stay un-acknowledged, so
        the next checkpoint (or finalize) carries them again."""
        api_logger.warning(
            "leg_scene_turn.checkpoint_skipped",
            document_id=self._document_id,
            run_id=self._run_id,
            base_version=self.version,
            pending_operations=len(delta),
            trigger=meta.get("reason"),
            error=reason,
        )


def _checkpoint_sink(committer: Optional["_LegSceneCommitter"]):
    """The runtime's P0.4 sink for this turn, or None when the turn owns no persist."""
    return None if committer is None else committer.checkpoint


def _run_cancel_probe(store: HybridRepository, run_id: str):
    """This run's cancellation probe (A3, defect R3-D): the runtime's read of a durable stamp.

    The whole cross-process seam in one closure. The human's cancel arrives on a web process; the
    turn is driven by a fleet worker that shares nothing with it but Postgres, so the ONLY way
    the two can meet is a row the asker writes and the driver reads. This is the driver's half.

    Wrapped in :class:`~lumen_agent.cancellation.CancellationProbe`, which makes it sticky (a
    cancel never un-cancels), throttled on the negative answer (one read per model call would be
    fine; one per retry storm is wasteful), and FAIL-OPEN — a database blip reads as "not
    cancelled" rather than becoming the run's cause of death. Durability is what makes this
    survive a worker restart or a lease takeover: the redrive re-reads the same stamp.
    """
    from lumen_agent.cancellation import CancellationProbe

    return CancellationProbe(lambda: store.cancellation_requested(run_id))


def _call_turn_override(
    override: Any, payload: Any, root: Path, *, scene_checkpoint: Any,
    scoped_preferences: Any = None,
):
    """Call the injected turn-runner test seam, handing it the checkpoint sink only if it wants it.

    ``DesignTurnHost.agent_turn_runner`` is a test double whose shipped contract is
    ``(payload, root)``. P0.4 needs a stub to be *able* to checkpoint (that is the only way to
    drive the mid-run path without a live model), so the sink is offered as a keyword — and every
    existing two-argument stub keeps working untouched, which is the point of asking first.
    """
    try:
        parameters = inspect.signature(override).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins/C callables
        parameters = {}
    wants_sink = "scene_checkpoint" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs = {"scene_checkpoint": scene_checkpoint} if wants_sink else {}
    if scoped_preferences is not None:
        # The legacy override seam has no enforceable runtime-workspace custody
        # contract. A keyword declaration alone cannot prove binding before use.
        raise RuntimeError("scoped_preferences.override_unsupported")
    return override(payload, root, **kwargs)


def _persist_leg_scene_proposal(
    response: JsonObject,
    *,
    committer: "_LegSceneCommitter",
    operations: List[JsonObject],
    document_id: str,
    base_version: int,
    store: HybridRepository,
) -> JsonObject:
    """Commit ONE leg scene turn's proposal, or refuse honestly. Never both, never neither.

    Exactly one durable write happens here, and only on the path where the engine reproduced the
    agent's own operation history against the stored scene.

    P0.4: "the proposal" now means *the part of it that is not durable yet*. The committer has
    been taking checkpoints of verified rounds while the turn ran, so this replays and writes
    only the tail, onto the scene the last checkpoint produced and CAS'd on the version it left.
    The destination is unchanged — ``base + len(operations)``, the same final scene — and a turn
    whose last checkpoint already carried everything writes nothing at all, because there is
    nothing left to write, not because anything was dropped.
    """

    delta = committer.pending(operations)
    if not delta:
        # Fully checkpointed: every operation is already durable at the head, and the scene there
        # is byte-for-byte the one a single finalize write would have produced. Reporting the
        # version is all that is left.
        return _leg_scene_version_stamp(response, document_id, base_version, store)
    try:
        # The agent's operation history is a CLAIM until the engine reproduces it HERE, against
        # the scene we are about to overwrite. This is a precondition on trusting it, not a
        # formality: an unreplayable history would otherwise be committed as a scene nobody can
        # undo, and the inverse operations the checkpoint needs come out of this same call.
        applied = committer.replay(delta)
    except CoreError as error:
        if is_pageless_scene_refusal(error.diagnostics):
            # Not an unreplayable history — the operations replayed fine and simply did not
            # amount to a page, which the engine refuses as an invalid scene. Same fact as the
            # gate below, reached first because the engine validates the result for us — so the
            # engine's own text rides the detail, exactly as the replay refusal beside it does.
            return pageless_agent_turn_response(error.message)
        return failed_agent_turn_response(
            "agent_turn.operations_replay_failed",
            "The AI turn's operations could not be replayed.",
            error.message,
        )
    if has_error_diagnostics(applied.get("diagnostics") or []):
        return failed_agent_turn_response(
            "agent_turn.operations_replay_failed",
            "The AI turn's operations could not be replayed.",
            "The engine reported errors replaying the turn's operations; "
            "the proposal was not committed.",
        )
    # genad2 Task 3 — the >=1-page success gate, read off the scene that would be written. The
    # engine's own LUMV0100 refusal above is what fires today, but the authoritative statement of
    # the contract is this one (it survives an engine that ever admits a page-less scene): a leg
    # turn only succeeds if what it applied has somewhere to be seen.
    if not (applied["scene"].get("pages") or {}):
        return pageless_agent_turn_response()
    try:
        # The SAME governed write the /documents/{id}/operations route makes, with
        # ``actor="agent"`` on the invocation (REQ-20 parity) and — through the committer — the
        # leg's frozen base (or the version this turn's last checkpoint left) as the CAS that
        # closes the window the early check cannot. The D4 asset-custody backstop rides inside
        # `commit`, so every accept seam this turn opens gets it, not only the last one.
        committer.commit(delta, applied, "Design turn")
    except WebDocumentVersionConflict as conflict:
        # The race window between the early check and this write — the DAL's row-locked CAS is
        # what actually decides it, and losing is an honest terminal outcome, not a crash.
        return conflicted_agent_turn_response(conflict.expected, conflict.current)
    # PAST THE POINT OF NO RETURN. The governed write above has COMMITTED; everything below only
    # describes it.
    return _leg_scene_version_stamp(response, document_id, base_version, store)


def _leg_scene_version_stamp(
    response: JsonObject,
    document_id: str,
    base_version: int,
    store: HybridRepository,
) -> JsonObject:
    """Stamp the committed document's version onto the turn's result.

    A convenience (it lets the platform's projection pin the new version), so its failure must
    not propagate to the executor's outer handler, which would fold a committed turn into
    `agent_runtime.failed` and tell a marketer nothing was saved while their ad sits changed in
    the gallery. A missing `current_version` is the honest degradation — the same shape a
    preview-only leg turn returns — and readers already treat the key as optional. The write's
    OWN failure stays fatal/conflicted, in the caller.
    """
    try:
        current_version = store.require_document(document_id)["current_version"]
    except Exception as error:  # pragma: no cover - exercised by the stub-store test
        api_logger.warning(
            "leg_scene_turn.version_reread_failed",
            document_id=document_id,
            base_version=base_version,
            error=str(error),
        )
        return response
    return {**response, "current_version": current_version}


def execute_web_turn_job(
    envelope: Any,
    *,
    store: HybridRepository,
    host: Any,
    event_sink: Any,
    checkpointer: Any = None,
    lease_generation: Optional[int] = None,
    spend_drain: Any = None,
    callbacks: Any = None,
    session_continued: bool = False,
) -> Tuple[str, JsonObject, str, JsonObject]:
    """One website-mode turn under its own spend scope — see :func:`_execute_web_turn_job`.

    ``callbacks`` (lane 3 slice 5): the platform's injected ``TurnCallbacks``. Same treatment as
    the scene executor — the turn's own collector is added here and its receipts are stamped onto
    whatever response this frame returns, which is what lands in ``result_json``.
    """
    from . import spend as _spend

    collector, turn_callbacks = _turn_model_call_collector(callbacks)
    with _spend.spend_scope(_turn_spend_stamp(envelope), drain_fn=spend_drain) as scope:
        try:
            status, response, event_type, event_data = _execute_web_turn_job(
                envelope,
                store=store,
                host=host,
                event_sink=event_sink,
                checkpointer=checkpointer,
                lease_generation=lease_generation,
                callbacks=turn_callbacks,
                session_continued=session_continued,
            )
            return status, _with_model_calls(response, collector), event_type, event_data
        finally:
            _drain_spend(scope)


def _execute_web_turn_job(
    envelope: Any,
    *,
    store: HybridRepository,
    host: Any,
    event_sink: Any,
    checkpointer: Any = None,
    lease_generation: Optional[int] = None,
    callbacks: Any = None,
    session_continued: bool = False,
) -> Tuple[str, JsonObject, str, JsonObject]:
    """One website-mode turn, executed from its frozen envelope.

    Unlike the scene path this executor OWNS the persist: an applied result is replayed against
    the stored document and committed under the envelope's ``base_version``, so a turn that took
    minutes can never silently clobber a human edit made while it ran.

    ``lease_generation`` (D7) fences the run-event side of this turn's governed tool invocations,
    exactly as it fences the executor's progress sink and its terminal write.
    """
    run_subject = DesignRunSubject(
        run_id=envelope.run_id, lease_generation=lease_generation
    )
    request = envelope.config.get("request") or {}
    payload = WebTurnRequest.model_validate(request)
    account_card = envelope.config.get("account_card")
    document_id = envelope.document_id

    # --- G9: consume the platform leg envelope's frozen context --------------------------------
    # A design-leg turn (PD-part3 §2.3/§2.4) carries the delegation bundle and the leg history on
    # ``config``; the scene executor has composed both into its prompt since P3.7, and this one
    # read only ``config.request`` — so a chat-born generation ran on the raw text of the user's
    # LATEST message alone ("go ahead" generated from almost nothing, and every iteration turn
    # lost the standing brief). Same renderer, same block order (brief, history, message), so
    # both executors reassemble the session identically. A direct BFF turn carries neither block
    # and its prompt stays byte-identical.
    delegation_bundle = envelope.config.get("delegation_bundle")
    leg_history = envelope.config.get("history")
    leg_block = envelope.config.get("leg") or {}

    # --- design note 2026-09-19: what this turn may read from the platform ---------------------
    # The scene executor's rule verbatim: a LEG turn only, resolved through the host's factory,
    # and a CAPABILITY rather than a precondition — a turn that cannot compose these still
    # generates from the brief, exactly as it did before this note.
    platform_reads = None
    if leg_block:
        reads_factory = getattr(host, "platform_reads_factory", None)
        if callable(reads_factory):
            try:
                platform_reads = reads_factory(envelope)
            except Exception:
                api_logger.warning(
                    "design_turn.platform_reads_unavailable",
                    run_id=envelope.run_id,
                    exc_info=True,
                )
                platform_reads = None

    user_message = payload.prompt
    # Session continuity (2026-09-18), the scene executor's rule verbatim: a CONTINUED thread
    # already holds every earlier turn of this session, so the history block would say it all
    # twice; the immutable brief still opens each NEW leg. The composition itself happens below,
    # after the document read, because the drift note is part of it.
    first_turn_of_leg = (
        bool(leg_block.get("first_turn_of_leg", True)) if isinstance(leg_block, dict) else True
    )
    bundle_block = (
        delegation_bundle
        if (delegation_bundle and (not session_continued or first_turn_of_leg))
        else None
    )
    history_block = None if session_continued else leg_history

    model = payload.model
    target_node_ids = payload.target_node_ids
    # R-A2: back to plain dicts at this seam. The envelope is frozen JSON and
    # `_describe_web_turn_targets` / the runtime config both take mappings, so the model is
    # the validation gate on the way in and nothing downstream depends on the class.
    target_notes = (
        [note.model_dump(mode="json") for note in payload.target_notes]
        if payload.target_notes
        else None
    )
    override = host.web_turn_runner
    root = repo_root()
    workspace_id = envelope.workspace_id
    try:
        # Session continuity (2026-09-18): the DOCUMENT decides, not the frozen envelope. The
        # request's ``base_version`` was pinned when the turn was submitted; the turn designs
        # against — and CAS's on — the version it actually reads here, and a session that wrote
        # this document before is TOLD what moved since instead of being refused. The write-time
        # CAS below still refuses the human edit that lands while the turn runs, which is the
        # only window an early check never could close.
        doc = store.require_document(document_id)
        base_version = int(doc["current_version"])
        # Ruling T6-1: drift is something a SESSION is told, and only a leg turn has one. A direct
        # BFF turn (no leg block) carries the human's words verbatim, exactly as it always has.
        drift_note = (
            _document_drift_note(
                store, document_id=str(document_id), current_version=base_version
            )
            if leg_block
            else None
        )
        prompt = (
            render_leg_turn_prompt(
                bundle=bundle_block if isinstance(bundle_block, dict) else None,
                history=history_block if isinstance(history_block, list) else None,
                prompt=user_message,
                drift_note=drift_note,
            )
            if (bundle_block or history_block or drift_note)
            else user_message
        )
        if override is not None:
            # Backward-compatible seam: existing stubs take four positional args; only pass the
            # scoped-target ids when the request carried them (a five-arg stub), and only pass
            # account_card as a keyword when the turn is personalized (so the un-personalized
            # 4/5-arg stubs are untouched).
            account_kwargs = {"account_card": account_card} if account_card else {}
            if target_node_ids:
                response = override(
                    doc, prompt, model, root, target_node_ids, **account_kwargs
                )
            else:
                response = override(doc, prompt, model, root, **account_kwargs)
        else:
            asset_library = pinned_asset_library(store, envelope.run_id)
            component_account_id = doc.get("account_id")
            custom_component_registry = (
                DurableAgentCustomComponentRegistry(
                    blobs=_turn_blob_store(host, workspace_id),
                    account_id=component_account_id,
                    document_id=document_id,
                    # D6 (R-D6-5): the registry's two durable writes route through the governed
                    # design tools. The compiler knobs it used to hold are now the tool host's
                    # thunks, resolved the same way off-request as on it.
                    invocations=_turn_design_tools(host, run_subject),
                )
                if isinstance(component_account_id, str) and component_account_id
                else None
            )
            response = run_web_agent_turn(
                doc,
                prompt,
                model,
                root,
                event_sink=event_sink,
                target_node_ids=target_node_ids,
                target_notes=target_notes,
                account_card=account_card,
                asset_library=asset_library,
                custom_component_registry=custom_component_registry,
                # F4.3 (R25-1): composed HERE, beside the component registry, because like it
                # this capability's durable writes go through the governed design tools and the
                # invoker is only assemblable at this seam. Unlike it there is no account or
                # document to gate on — the binder's own workspace-scoped doors decide.
                account_logo_binder=DurableAgentAccountLogoBinder(
                    blobs=_turn_blob_store(host, workspace_id),
                    cache_dir=_host_engine_cache_root(host, workspace_id),
                    invocations=_turn_design_tools(host, run_subject),
                ),
                workspace_id=workspace_id,
                # D5 Round C: see the scene executor.
                blobs=_turn_blob_store(host, workspace_id),
                engine_cache_root=_host_engine_cache_root(host, workspace_id),
                checkpointer=checkpointer,
                thread_id=envelope.checkpoint_thread_id,
                # Session continuity (2026-09-18), ruling T6-1: a web turn is always OF a
                # document, but only a LEG turn is of that document's session — a direct BFF turn
                # keeps its per-run folder and its own generated id, as before.
                session_id=(
                    design_session_id(workspace_id, str(document_id)) if leg_block else None
                ),
                run_id=envelope.run_id if leg_block else None,
                # See the scene executor: the session's synced folder, by value.
                session_manifest=(
                    _session_manifest(
                        store,
                        _turn_blob_store(host, workspace_id),
                        document_id=str(document_id),
                    )
                    if leg_block
                    else None
                ),
                # A3 (defect R3-D): the same durable probe the scene executor builds, so ONE
                # route can honestly stop either kind of design run.
                cancel_requested=_run_cancel_probe(store, envelope.run_id),
                # Lane 3 slice 5: see the scene executor.
                callbacks=callbacks,
                # Design note 2026-09-19: see the scene executor.
                platform_reads=platform_reads,
            )
        if response.get("status") == "applied":
            operations = response.get("operations")
            if not isinstance(operations, list):
                response = failed_agent_turn_response(
                    "web_turn.operations_missing",
                    "The AI turn did not return a replayable operation history.",
                    "The candidate document was not committed.",
                )
            elif not operations:
                if response.get("web_doc") != doc["scene"]:
                    response = failed_agent_turn_response(
                        "web_turn.operations_incomplete",
                        "The AI turn's operation history did not describe its result.",
                        "The candidate document was not committed.",
                    )
            else:
                try:
                    replay = _turn_core(host).web_apply_ops(
                        doc["scene"], operations, raise_on_error=False
                    )
                except CoreError as error:
                    response = failed_agent_turn_response(
                        "web_turn.operations_replay_failed",
                        "The AI turn's operations could not be replayed.",
                        error.message,
                    )
                else:
                    if not replay.get("ok") or replay.get("web_doc") != response.get("web_doc"):
                        response = failed_agent_turn_response(
                            "web_turn.operations_incomplete",
                            "The AI turn's operation history did not reproduce its result.",
                            "The candidate document was not committed.",
                        )
                    else:
                        try:
                            # Durable custody BEFORE the governed write, mirroring the
                            # scene accept seam. An agent tool can ingest bytes mid-turn
                            # (a fetched account logo), and until this ran the web lane
                            # had no backstop at all — the document committed citing
                            # bytes that lived only in a wipeable engine cache.
                            register_web_asset_backstop(
                                _turn_blob_store(host, workspace_id),
                                _host_engine_cache_root(host, workspace_id),
                                replay["web_doc"],
                            )
                            # D6 Round B: the worker's persist is the SAME governed write the
                            # /web/operations route makes, with `actor="agent"` on the
                            # invocation (REQ-20 parity) and the envelope's frozen
                            # `base_version` as the CAS. The operation-replay verification
                            # above stays HERE and stays loud: it is a precondition on trusting
                            # the agent's own history, and it needs the engine.
                            _turn_design_tools(host, run_subject).invoke(
                                "design_apply_web_operations",
                                {
                                    "document_id": document_id,
                                    "web_doc": replay["web_doc"],
                                    "operations": operations,
                                    "inverse_operations": replay.get(
                                        "inverse_operations"
                                    ),
                                    # The USER's words, never the composed runtime prompt: this
                                    # is the human-facing label on the durable edit envelope,
                                    # and a leg turn's composed prompt opens with the fenced
                                    # brief block (G9).
                                    "intent": user_message[:120],
                                    "checkpoint_label": "Website turn",
                                    "actor_kind": "agent",
                                    "source": "agent",
                                    "expected_base_version": base_version,
                                },
                                workspace_id=workspace_id,
                                actor="agent",
                                actor_id=envelope.run_id,
                            )
                            updated = store.require_document(document_id)
                        except WebDocumentVersionConflict as conflict:
                            response = conflicted_web_turn_response(
                                conflict.expected, conflict.current
                            )
                        except CustomComponentReferenceError as error:
                            response = failed_agent_turn_response(
                                error.code,
                                error.message,
                                (
                                    f"Node {error.node_id} references "
                                    f"artifact {error.artifact_id}."
                                ),
                            )
                        except FragmentReferenceError as error:
                            response = failed_agent_turn_response(
                                error.code,
                                error.message,
                                (
                                    f"Node {error.node_id} references "
                                    f"fragment {error.fragment_id}."
                                ),
                            )
                        else:
                            response["current_version"] = updated["current_version"]
        status = "succeeded" if response.get("status") == "applied" else "failed"
        return (
            status,
            {**with_web_turn_failure_diagnostic(response), "doc_kind": "web"},
            "result",
            {"status": response.get("status")},
        )
    except Exception as error:  # pragma: no cover - defensive
        failed = failed_agent_turn_response(
            "agent_runtime.failed",
            "Website turn crashed before returning a result.",
            str(error),
        )
        return "failed", {**failed, "doc_kind": "web"}, "error", {"message": str(error)}


def execute_ingestion_job(
    envelope: Any,
    *,
    host: Any,
    expected_generation: Optional[int] = None,
    spend_drain: Any = None,
) -> str:
    """One brand-kit ingestion under its own spend scope — see :func:`_execute_ingestion_job`.

    Every model call the pipeline makes (describe, assist, PDF vision, ad-DNA) and every vendor
    credit it spends (the logo vendor, the ad-library vendor) runs through this scope's
    ``ProviderCaller`` and lands
    on ``provider_call_ledger`` stamped with this job's id. ``spend_drain`` is the injected drain
    (PRE-1b).
    """
    from clue_spend import LedgerStamp

    from . import spend as _spend

    try:
        job_id = UUID(str(envelope.job_id))
    except (TypeError, ValueError):
        job_id = None
    stamp = LedgerStamp(workspace_id=envelope.workspace_id, job_id=job_id)
    from lumen_ingestion.asset_enrichment import JOB_CONTEXT
    job_context = JOB_CONTEXT.set((envelope.job_id, expected_generation))
    with _spend.spend_scope(stamp, drain_fn=spend_drain) as scope:
        try:
            return _execute_ingestion_job(
                envelope, host=host, expected_generation=expected_generation
            )
        finally:
            try:
                _drain_spend(scope)
            finally:
                JOB_CONTEXT.reset(job_context)


def _execute_ingestion_job(
    envelope: Any,
    *,
    host: Any,
    expected_generation: Optional[int] = None,
) -> str:
    """One brand-kit ingestion, executed from its frozen envelope. Returns the job's status.

    The ingestion sibling of :func:`execute_agent_turn_job` / :func:`execute_web_turn_job`, and
    it lives here for the same two reasons: the workspace-scoped engine-cache root it needs is a
    ``main`` concern, and the three ``run_*_ingestion`` names are resolved from THIS module's
    namespace at call time — which is the seam the ingestion route suites patch to inject their
    capture/extract/analyze stubs. Calling ``lumen_ingestion.pipeline`` directly from the handler
    would silently bypass every one of those tests.

    Never raises: the pipeline drives the job to a terminal row itself (``run_ingestion_job``
    captures any exception onto it) and a fenced write is dropped rather than propagated. The
    status is read back afterwards so the fleet's ``WorkResult`` reports the real outcome instead
    of assuming success.
    """
    workspace_id = envelope.workspace_id
    kind = DesignIngestionKind(envelope.ingestion_kind)
    from .asset_enrichment import run_asset_enrichment
    runner = {
        DesignIngestionKind.ASSET_ENRICHMENT: run_asset_enrichment,
        DesignIngestionKind.WEBSITE: run_website_ingestion,
        DesignIngestionKind.PDF: run_pdf_ingestion,
        DesignIngestionKind.ASSET_UPLOAD: run_asset_ingestion,
        # Brand Ad Assets v1 W2. Same signature, same never-raises contract, same fence — the
        # lane is a fourth ingestion kind rather than a second job system (see the enum).
        DesignIngestionKind.AD_ASSETS: run_ad_assets_onboarding,
    }[kind]
    runner(
        str(_host_engine_cache_root(host, workspace_id)),
        envelope.job_id,
        # The tenant is the envelope's, never a re-derived default: a worker-path write that
        # silently picks a workspace is the D2.5A residual this round closes.
        workspace_id=workspace_id,
        # The dispatching app's byte backend when there is one (the embedded worker + the design
        # suite); the detached worker has none and falls back to the configured backend, which is
        # what staged the upload in that deployment anyway.
        storage=host.storage,
        expected_generation=expected_generation,
    )
    job = IngestionJobStore(workspace_id=workspace_id).get(envelope.job_id)
    return str((job or {}).get("status") or "unknown")


# D5 Round B (R-D5-B1): ``ensure_agent_runtime_path`` is DELETED. It inserted
# apps/agent_runtime, apps/api and the design-tree root into ``sys.path`` at call time so the
# lazy ``lumen_agent`` import below could resolve. That trick is unavailable to an out-of-process
# fleet worker, which is why ``lumen-agent-runtime``, ``py-lumen-obs`` and ``py-lumen-config`` are
# now installed uv workspace members. The lazy import and its ``agent_runtime.unavailable``
# degradation stay exactly as they were — a machine without the runtime extras must still get an
# honest failure envelope rather than an import crash at module load.


def api_blob_store(workspace_id: str) -> DesignBlobStore:
    """A design blob-store handle for code that has no request to take one from.

    D5 Round C closed the D2.5A residual this carried: ``workspace_id`` was optional and fell
    back to the configured dev workspace, so any off-request caller that simply forgot to thread
    a tenant read and wrote the dev tenant's bytes instead of failing. It is now REQUIRED, and
    every worker-path caller passes the job's own workspace out of its frozen envelope.

    What SURVIVES, deliberately: the backend comes from ``settings``, not ``app.state.storage``,
    because this function has no app handle by construction — its callers are the ones with no
    request. On the worker path that residual is gone a different way: the executors pass the
    host's ``DesignBlobStore`` (built from ``app.state.storage`` for the embedded worker) into
    the turn/ingestion runners, so this function is reached only by the CLI, fixtures, and the
    off-request resolver defaults. A suite that injects a throwaway backend into ``create_app``
    and then drives one of THOSE paths must point ``CLUE_STORAGE_FS_ROOT`` at the same place
    (the conftest fixture does).
    """
    return DesignBlobStore(storage_from_settings(), workspace_id)


def resolve_agent_turn_brand_kit(
    payload: AgentTurnPreviewRequest,
    blobs: DesignBlobStore,
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
    try:
        # D5 Round C: `blobs` is REQUIRED and names the caller's tenant. It used to default to
        # `api_blob_store()` — the configured dev workspace — which meant an off-request caller
        # that forgot to thread a workspace resolved another tenant's kit.
        return load_brand_kit_by_value(
            workspace_id=blobs.workspace_id,
            brand_kit_id=str(ref["id"]),
            version=ref.get("version"),
            blobs=blobs,
            source="document",
        )
    except Exception:
        return None, None, None, None


def load_brand_kit_by_value(
    *,
    workspace_id: str,
    brand_kit_id: str,
    version: Optional[int],
    blobs: DesignBlobStore,
    source: str,
    ensure_workspace: bool = True,
) -> Tuple[JsonObject, str, JsonObject, Optional[JsonObject]]:
    """One read that owns both the check and the value: kit + asset manifest + font spec,
    fail-LOUD (P3.7 TOCTOU fix). The tolerant `resolve_agent_turn_brand_kit` wraps this for
    unpinned turns; the leg-pin gate calls it directly and fails the turn on ANY error —
    an unreachable database refuses rather than silently designing in the default kit."""

    repo = HybridRepository(workspace_id, ensure_workspace=ensure_workspace)
    record = repo.require_brand_kit(brand_kit_id, version)
    brand_kit = record["brand_kit"]
    cache_dir = str(api_engine_cache_root(workspace_id))
    manifest = brand_kit_asset_manifest(repo, brand_kit, blobs, cache_dir)
    font_spec = brand_kit_font_spec(repo, brand_kit, blobs, cache_dir)
    return brand_kit, source, manifest, font_spec


def _is_replace_web_doc(operations: Any) -> bool:
    """True when `operations` is exactly one replace_web_doc marker carrying a
    whole web_doc payload — the historical agent-turn shape (a marker the
    checked-apply helper does NOT understand). Current editor and agent batches
    are real typed WebOperations and never match, so undo/redo can branch on
    this solely for backward compatibility."""
    return (
        isinstance(operations, list)
        and len(operations) == 1
        and isinstance(operations[0], dict)
        and operations[0].get("kind") == "replace_web_doc"
        and isinstance(operations[0].get("web_doc"), dict)
    )


def _has_replace_web_doc_kind(operations: Any) -> bool:
    """True when `operations` is a single replace_web_doc entry, WHETHER OR NOT
    it carries a web_doc payload. Historical agent-turn forward ops are a bare
    marker while inverses carry the doc; legacy redo branches on the kind and
    sources the doc separately when it is a marker."""
    return (
        isinstance(operations, list)
        and len(operations) == 1
        and isinstance(operations[0], dict)
        and operations[0].get("kind") == "replace_web_doc"
    )


def _replace_web_doc_payload(operations: Any) -> Optional[JsonObject]:
    if _is_replace_web_doc(operations):
        return operations[0]["web_doc"]
    return None


def _web_revert_envelope_for(
    repo: HybridRepository, document_id: str, batch_id: str
) -> JsonObject:
    """The most recent revert envelope that undid `batch_id`. Its
    inverse_operations carries the whole doc that historical batch installed —
    which legacy redo reinstalls because the batch's own forward op is only a
    replace_web_doc marker without a doc payload."""
    for envelope in repo.list_envelopes(document_id, newest_first=True):
        if envelope.get("reverts_batch_id") == batch_id:
            return envelope
    raise HTTPException(
        status_code=409,
        detail={
            "code": "redo.not_reapplicable",
            "message": (
                f"batch {batch_id} cannot be re-applied; no revert record holds "
                "its forward document snapshot"
            ),
        },
    )


def _valid_font_weight(value: Any) -> bool:
    """A per-face CSS weight: an int in 1..=1000 (bool excluded — it is an int
    subclass but never a real weight)."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1000


def _valid_font_style(value: Any) -> bool:
    return value in ("normal", "italic")


def public_api_origin(request: Request) -> str:
    """The origin a BROWSER can reach this API at, for URLs written into served markup.

    Behind the platform's server-side proxy ``request.base_url`` is the private service host
    (``http://design-api.railway.internal:8010/``), so every ``/asset-store/{digest}`` image and
    kit-font URL the web render derived from it was unreachable from the browser: in production
    (2026-10-14) seeded web pages rendered broken images and fallback fonts. ``LUMEN_API_ORIGIN``
    names the public origin — the same setting the web turn already uses for the agent's own
    previews — and wins when set. Unset (the dev stack, where the browser reaches the API
    directly), the request's own base is the origin, exactly as before. No trailing slash.
    """
    configured = (os.environ.get("LUMEN_API_ORIGIN") or "").strip()
    return (configured or str(request.base_url)).rstrip("/")


def build_web_font_face_css(
    brand_fonts: Optional[JsonObject], request_base_url: str
) -> Optional[str]:
    """@font-face CSS that points the browser at the kit's stored font faces so
    the web render displays the brand's real fonts, not the fallback stack.

    Input is the kit font spec resolve_web_turn_brand_kit returns —
    ``{store_root, faces: [{digest, family, weight?, style?}]}`` — whose faces
    resolve to content-addressed asset-store bytes served at
    ``{base}/asset-store/{digest}`` (the same digest route the canvas/export
    paths use).

    Per-face weight/style: brand_kit_font_spec now carries each face's
    ``weight`` (int 1..=1000) and ``style`` ("normal"|"italic") when the kit
    recorded them, so a multi-weight kit emits one correctly-weighted rule per
    face instead of collapsing every face to normal 400. (Previously the K3
    spec dropped these fields, so a genuine multi-weight kit rendered as
    whichever face the browser resolved.) A spec-less face — one whose weight/
    style is absent or out of range — still defaults to font-weight:400/
    font-style:normal. Returns None when there is nothing resolvable to
    emit."""
    if not isinstance(brand_fonts, dict):
        return None
    faces = brand_fonts.get("faces")
    if not isinstance(faces, list):
        return None
    base = request_base_url.rstrip("/")
    rules: List[str] = []
    seen: set[Tuple[str, str]] = set()
    for face in faces:
        if not isinstance(face, dict):
            continue
        digest = face.get("digest")
        family = face.get("family")
        if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
            continue
        if not (isinstance(family, str) and family.strip()):
            continue
        key = (family, digest)
        if key in seen:
            continue
        seen.add(key)
        url = f"{base}/asset-store/{digest}"
        weight_value = face.get("weight")
        weight = weight_value if _valid_font_weight(weight_value) else 400
        style_value = face.get("style")
        style = style_value if _valid_font_style(style_value) else "normal"
        # json.dumps supplies CSS-safe double-quoted strings for both the family
        # name and the URL, so a crafted family/digest cannot break out of the
        # rule (digest is already hex-gated above). weight/style are validated
        # numerics/enums above, safe to interpolate.
        rules.append(
            "@font-face{"
            f"font-family:{json.dumps(family)};"
            f"font-style:{style};font-weight:{weight};font-display:swap;"
            f"src:url({json.dumps(url)});"
            "}"
        )
    if not rules:
        return None
    return "\n".join(rules)


def resolve_web_turn_brand_kit(
    web_doc: JsonObject, blobs: DesignBlobStore
) -> Tuple[
    Optional[JsonObject], Optional[str], Optional[JsonObject], Optional[JsonObject]
]:
    """The Brand Kit a WebDoc references, loaded from the kit library so it can
    ride the runtime config BY VALUE (the runtime never reads the API database)
    — plus the kit-asset manifest and font spec, exactly like
    resolve_agent_turn_brand_kit. The only difference is WHERE the ref lives: a
    WebDoc carries it at ["theme"]["brand_kit"] (no scene `meta` wrapper).

    Resolution failures never fail the turn: no ref, an unknown kit id, or an
    unreadable database all return (None, None, None, None) and the pipeline
    falls back to the platform default kit — the same silent-fallback contract
    the scene path has. `blobs` (D4) is the tenant's byte store, used to materialize the kit's
    font faces AND its asset/thumbnail bytes into the engine cache; REQUIRED since D5 Round C,
    because a defaulted one named the dev workspace and quietly resolved the wrong tenant's
    kit."""
    theme = web_doc.get("theme") if isinstance(web_doc, dict) else None
    ref = theme.get("brand_kit") if isinstance(theme, dict) else None
    if not isinstance(ref, dict) or not ref.get("id"):
        return None, None, None, None
    try:
        # D5 Round C: `blobs` is REQUIRED and names the caller's tenant — see the scene twin.
        repo = HybridRepository(blobs.workspace_id)
        record = repo.require_brand_kit(str(ref["id"]), ref.get("version"))
        brand_kit = record["brand_kit"]
        cache_dir = str(api_engine_cache_root(blobs.workspace_id))
        manifest = brand_kit_asset_manifest(repo, brand_kit, blobs, cache_dir)
        font_spec = brand_kit_font_spec(repo, brand_kit, blobs, cache_dir)
        return brand_kit, "document", manifest, font_spec
    except Exception:
        return None, None, None, None


def account_values(
    account: JsonObject, repo: HybridRepository
) -> Tuple[Dict[str, JsonObject], List[JsonObject]]:
    """Project a personalization account (P5 D3) into the flat `account.*` value
    namespace (D1) + the logo's engine AssetRecord for the derive call.

    The account IS the binding set — no separate binding-set authoring exists in
    v0. Values are kind-tagged snake_case WebBoundValue dicts mirroring
    `lumen_core::binding::BoundValue`:
      - account.name  → Text
      - account.domain → Text (present only when the account carries one)
      - account.logo  → Asset (present only when the account carries a logo)
      - account.<key> → Text, one per `data` entry
    (notes are agent context, NEVER a substitution value). asset_records is the
    logo AssetRecord list (empty when there is no logo or its row is gone — a
    DELETE keeps derived docs' account_id but the asset may be absent)."""
    values: Dict[str, JsonObject] = {
        "account.name": {"kind": "text", "value": str(account.get("name") or "")},
    }
    domain = account.get("domain")
    if domain:
        values["account.domain"] = {"kind": "text", "value": str(domain)}
    logo_asset_id = account.get("logo_asset_id")
    asset_records: List[JsonObject] = []
    if logo_asset_id:
        # Alt rides the binding: without it a derived page keeps the TEMPLATE's
        # alt text (the seed account's name) — the a11y leak the P5 e2e caught.
        values["account.logo"] = {
            "kind": "asset",
            "asset_id": str(logo_asset_id),
            "alt": f"{account.get('name') or 'Account'} logo",
        }
        try:
            record = repo.require_asset_record(str(logo_asset_id))
            asset_records.append(record.get("asset") or record)
        except NotFoundError:
            # The logo row is gone; the value still points at it (unbound at
            # derive → template fallback, reported in coverage).
            pass
    for key, value in (account.get("data") or {}).items():
        values[f"account.{key}"] = {"kind": "text", "value": str(value)}
    return values, asset_records


def resolve_account_assets(
    account_card: JsonObject, workspace_id: str
) -> Optional[JsonObject]:
    """The account-logo manifest a personalized turn hands the runtime BY VALUE
    (mirrors resolve_web_turn_brand_kit / brand_kit_asset_manifest): the account
    card names its logo by `logo_asset_id`, and `use_account_asset` needs the
    engine AssetRecord to upsert it (the runtime never reads the API database).
    Shape: {asset_id: {"record": <engine asset record>}}. Returns None when there
    is no logo or its row cannot be read — the turn still personalizes name/text,
    and use_account_asset errors honestly with no logo."""
    logo_asset_id = account_card.get("logo_asset_id")
    if not logo_asset_id:
        return None
    try:
        # D2.3: the asset registry lives on Postgres. `workspace_id` is the turn's tenant, and
        # REQUIRED since D5 Round C — a None used to mean the dev workspace.
        repo = HybridRepository(workspace_id)
        record = repo.require_asset_record(str(logo_asset_id))
        return {str(logo_asset_id): {"record": record.get("asset") or record}}
    except Exception:
        return None


ASSET_LIBRARY_PAGE_SIZE = 500
# Compatibility constants describe page/response sizes, never total inventory coverage.
WEB_AGENT_ASSET_LIBRARY_MAX = ASSET_LIBRARY_PAGE_SIZE
SCENE_TURN_ASSET_LIBRARY_MAX = 24
SCENE_TURN_ASSET_LIBRARY_SCAN = ASSET_LIBRARY_PAGE_SIZE
SCENE_TURN_ASSET_LIBRARY_KINDS = frozenset({"raster_image", "logo", "vector"})


def asset_metadata_entry(described: dict) -> dict:
    if not described:
        return {}
    return {
        **{key: described.get(key) for key in ("title", "description", "usage", "tags", "creative_type", "usage_roles", "revision")},
        "analysis_status": described.get("status", "stale"),
        "sources": sorted({item["source"] for item in described.get("source_occurrences", [])}),
        "asset_context": {key: described.get(key) for key in (
            "asset_id", "revision", "status", "title", "description", "creative_type",
            "usage_roles", "classification_origin", "classification_reason", "overrides",
            "source_occurrences", "agent_context", "model", "input_fingerprint",
        )},
    }


def workspace_asset_library_manifest(repo: HybridRepository) -> JsonObject:
    """All non-archived records, paginated metadata only. No image bytes or prompt dump."""
    manifest = {}
    offset = 0
    while True:
        rows = repo.list_asset_records(include_archived=False, limit=ASSET_LIBRARY_PAGE_SIZE, offset=offset)
        ids = [str(row["asset"]["id"]) for row in rows if (row.get("asset") or {}).get("id")]
        descriptions = DescriptionStore(workspace_id=repo.workspace_id).get_many(ids)
        for row in rows:
            record = row.get("asset") or {}
            asset_id = record.get("id")
            if asset_id and record.get("status") != "archived":
                manifest[str(asset_id)] = {
                    "record": record, "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    **asset_metadata_entry(descriptions.get(str(asset_id)) or {}),
                }
        if len(rows) < ASSET_LIBRARY_PAGE_SIZE:
            return manifest
        offset += len(rows)


def pinned_asset_library(repo: HybridRepository, run_id: str) -> JsonObject:
    """First execution pins one metadata revision; takeover never reads newer guidance."""
    from clue_design.runs import asset_context_snapshot, pin_asset_context_snapshot
    stored = repo._bridge._run(lambda conn: asset_context_snapshot(conn, workspace_id=repo.workspace_id, run_id=run_id))
    if stored is not None:
        return stored
    snapshot = workspace_asset_library_manifest(repo)
    return repo._bridge._run(lambda conn: pin_asset_context_snapshot(
        conn, workspace_id=repo.workspace_id, run_id=run_id, snapshot=snapshot))


def asset_materializer(manifest: dict, blobs: DesignBlobStore, cache_dir: str):
    """Only records already authorized in this run can cause a durable byte read."""
    def materialize(asset_id: str):
        entry = manifest.get(asset_id)
        if entry is not None:
            ensure_materialized(blobs, cache_dir, (digest for digest, _mime in record_digests(entry["record"])))
    return materialize


def scene_turn_asset_library_manifest(repo: HybridRepository, blobs: DesignBlobStore, cache_dir: str) -> JsonObject:
    return {asset_id: entry for asset_id, entry in workspace_asset_library_manifest(repo).items()
            if entry["record"].get("status") == "ready"
            and entry["record"].get("kind") in SCENE_TURN_ASSET_LIBRARY_KINDS}


def resolve_scene_turn_asset_library(
    blobs: DesignBlobStore,
    cache_dir: Path,
) -> Optional[JsonObject]:
    """The scene turn's library manifest, or None when it cannot be built.

    Tolerant on purpose, exactly like `resolve_agent_turn_brand_kit`: an unreachable
    database or an empty library must never fail a turn — the run simply designs
    without the library, which is the pre-W1.1 behaviour. An EMPTY manifest returns
    None too, so a workspace with no library assets leaves `config.asset_library`
    unset and its turn stays byte-identical to before.

    `cache_dir` is the TURN's engine cache, threaded in rather than re-derived: a
    fleet worker injects its own, and staging bytes in one tree while the runtime
    reads another is exactly the split D5 Round C closed elsewhere."""
    try:
        repo = HybridRepository(blobs.workspace_id)
        manifest = scene_turn_asset_library_manifest(repo, blobs, str(cache_dir))
    except Exception:
        return None
    return manifest or None


def brand_kit_asset_manifest(
    repo: HybridRepository,
    brand_kit: JsonObject,
    blobs: DesignBlobStore,
    cache_dir: str,
) -> JsonObject:
    """K2: {asset_id: {record, title, description, usage}} for the kit's logo
    variants and brand images. Records come back VERBATIM from the library
    (they were engine-built at ingestion) — the runtime rewrites only the
    scene copy's provenance. Missing records are skipped silently: a kit may
    reference assets whose bytes/rows never landed, and a partial manifest
    beats a failed turn.

    D4 read-through (fast-loop v1 §4 P0.1): the runtime resolves each record's
    preview BY DIGEST out of the per-workspace engine cache (`_asset_preview_path`
    → `blob_path_for_digest`), so the kit's asset and thumbnail bytes have to be
    pulled out of durable storage into that cache first — exactly as
    `brand_kit_font_spec` does for faces and `reference_asset_manifest` does for
    attachment previews. Without it a fleet worker (or any process whose cache
    was never the ingesting one's) sees the manifest but none of the pixels.
    Fail-soft like every other read-through: a digest with no durable bytes is
    left absent and `view("asset:…")` degrades to its honest missing-file text."""
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

        descriptions = DescriptionStore(workspace_id=repo.workspace_id).get_many(asset_ids)
    except Exception:
        descriptions = {}

    for asset_id in dict.fromkeys(asset_ids):
        try:
            record = repo.require_asset_record(asset_id)
        except Exception:
            continue
        entry: JsonObject = {"record": record.get("asset") or record}
        described = descriptions.get(asset_id) or {}
        entry.update(asset_metadata_entry(described))
        manifest[asset_id] = entry

    ensure_materialized(
        blobs,
        cache_dir,
        (
            digest
            for entry in manifest.values()
            for digest, _mime in record_digests(entry["record"])
        ),
    )
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
    repo: HybridRepository,
    blobs: DesignBlobStore,
    cache_dir: str,
    asset_ids: List[str],
) -> Tuple[List[Tuple[bytes, str]], List[str]]:
    """RC (D-RC2.5): resolve already-deduped+capped reference ids into order-
    sorted (bytes, mime) reference images + their preview digests, via the SAME
    RC manifest machinery the agent turn uses — same hard 422s (unknown id /
    broken preview) and the same SVG rasterize. The manifest guarantees each
    preview blob is durable (it 422s otherwise), so the read is safe."""
    manifest = reference_asset_manifest(repo, blobs, cache_dir, asset_ids)
    images: List[Tuple[bytes, str]] = []
    digests: List[str] = []
    for entry in sorted(manifest.values(), key=lambda e: e.get("order", 0)):
        digest = entry["preview_digest"]
        images.append((blobs.read(digest), entry.get("mime_type") or "image/png"))
        digests.append(digest)
    return images, digests


def resolve_auto_ad_references(
    payload: AgentTurnPreviewRequest,
    blobs: DesignBlobStore,
    cache_dir: Path,
    lane: Any,
) -> Optional[JsonObject]:
    """W4: the brand's OWN published ads, attached when the human attached none.

    Brand Ad Assets v1 §4 ("the platform auto-attaches the ≤4 most relevant harvested
    references"). Selection lives in `lumen_api.ad_runtime` and states its own reasoning; this
    function is only the bridge from selected asset ids to the by-value manifest, built by the
    SAME `reference_asset_manifest` the manual path uses — one definition of what a reference
    is, so an auto-attached one and a hand-attached one are indistinguishable to the runtime.

    THE ONE DELIBERATE ASYMMETRY AGAINST THE MANUAL PATH: this never raises. A bad manual
    attachment is a loud 422 because it is explicit user intent (D2) and a reference the user
    picked but the loop never saw is worse than a rejected request. An AUTO attachment is the
    platform's own suggestion — a stale creative row or an unreadable preview must cost the
    turn its references, never the turn itself. Hence the bare except around a resolver whose
    whole contract is to throw.

    Consequence worth stating rather than discovering: attaching references makes this a
    REFERENCE turn, so the runtime's existing reference machinery switches on (the author
    views `reference:<n>`, the typed `reference_fidelity` is stamped, and a finalize-accept
    needs a fidelity judgment). That is the intended behaviour for an ad turn on a brand whose
    ads we harvested — it is why W1.5 exists — and it is exactly what W5 measures.
    """
    # The brief the selector matches against is `payload.prompt` as it stands HERE. On a leg
    # turn that is already the composed prompt (the leg's frozen brief, then the history, then
    # the user's message, in that order), so the truncation inside the selector keeps the
    # brief — which is the part that actually describes the ad — and drops the tail.
    asset_ids = ad_runtime.select_reference_asset_ids(payload.prompt or "", lane)
    if not asset_ids:
        return None
    try:
        return reference_asset_manifest(
            HybridRepository(blobs.workspace_id), blobs, str(cache_dir), asset_ids
        )
    except Exception:  # noqa: BLE001 - an auto-attachment may never fail a turn
        api_logger.warning("auto_ad_references_unresolvable")
        return None


def resolve_agent_turn_references(
    payload: AgentTurnPreviewRequest, blobs: DesignBlobStore
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
    # D5 Round C: `blobs` is REQUIRED and names the caller's tenant (it defaulted to the dev
    # workspace, which made an unthreaded call read another tenant's library).
    return reference_asset_manifest(
        HybridRepository(blobs.workspace_id),
        blobs,
        str(api_engine_cache_root(blobs.workspace_id)),
        asset_ids,
    )


def reference_asset_manifest(
    repo: HybridRepository,
    blobs: DesignBlobStore,
    cache_dir: str,
    asset_ids: List[str],
) -> JsonObject:
    """RC (D2): {asset_id: {record, preview_digest, mime_type, width, height,
    dominant_colors, title, description, order}} — EXACTLY the config.py
    reference_assets contract. Records come back VERBATIM from the library. A
    missing id is a hard 422 (never a silent skip — references are explicit
    user intent). SVG references are engine-rasterized to a 512px PNG that is
    given DURABLE custody and mirrored into the engine cache AT RESOLVE TIME, so
    the runtime (which reads the cache) only ever handles raster previews; a
    rasterize failure is a 422 (LUMI0804-class spirit — a broken preview on an
    explicit attachment fails the request, never degrades).
    dominant_colors/title/description are advisory."""
    import io

    from PIL import Image

    from lumen_ingestion.capture.uploads import _dominant_colors
    from lumen_ingestion.pipeline import make_rasterize_svg

    try:
        # D5 Round C: workspace-scoped — see workspace_asset_library_manifest for the same fix.
        descriptions = DescriptionStore(workspace_id=repo.workspace_id).get_many(asset_ids)
    except Exception:
        descriptions = {}

    rasterize_svg = make_rasterize_svg(repo, blobs, cache_dir)
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
            # D4: the rasterized preview is a real derived artifact — durable custody first
            # (idempotent on identical bytes), then the engine-cache mirror the runtime reads
            # through `view("reference:<n>")`. Registering before mirroring is the same
            # row-before-blob ordering the seam itself uses.
            blobs.register(
                png_bytes,
                media_type="image/png",
                source_key=design_storage.SOURCE_KEY_ENGINE_ARTIFACT,
            )
            write_cache_blob(cache_dir, preview_digest, png_bytes)
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
            # Review fix (channel refuter, minor 1): a raster reference whose
            # bytes are gone fails HERE like the SVG branch does — D2 says
            # boundary 422, never a silent mid-run degrade to a pixel-less view.
            # D4: "gone" is now a DURABLE-storage miss, and the bytes are mirrored into the
            # engine cache so the runtime can view them.
            preview_bytes = read_asset_bytes(blobs, preview_digest)
            if preview_bytes is None:
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
            write_cache_blob(cache_dir, preview_digest, preview_bytes)

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
        entry.update(asset_metadata_entry(described))
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
    repo: HybridRepository,
    scene: Optional[JsonObject],
    blobs: DesignBlobStore,
    cache_dir: str,
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
    return brand_kit_font_spec(repo, referenced, blobs, cache_dir)


def brand_kit_font_spec(
    repo: HybridRepository,
    brand_kit: Optional[JsonObject],
    blobs: DesignBlobStore,
    cache_dir: str,
) -> Optional[JsonObject]:
    """K3: {store_root, faces: [{digest, family, weight?, style?}]} for the
    kit's font faces, resolved from the asset library. The helper reads the
    bytes from the shared store and registers each face under BOTH its
    intrinsic name and the kit-DECLARED family — scenes request the declared
    name, which is routinely a `@font-face` alias over the bytes' intrinsic
    name (kit "Aeonik" over trial bytes named "Aeonik TRIAL"). Missing records
    are skipped — a partial font set beats a failed request, and the helper
    reports any face it cannot load (LUMS0101).

    Each face carries its per-face ``weight`` (int 1..=1000) and ``style``
    ("normal"|"italic") when the kit recorded them (the ingestion normalizer
    always does — emit.add_font stamps every face). The keys are omitted when
    the kit face lacks them or the value is out of range; the consumer
    (the Rust helper's BrandFontFaceSpec / build_web_font_face_css) defaults to
    400/normal, so no default is invented here."""
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
                spec_face: JsonObject = {
                    "digest": str(digest["value"]),
                    "family": family,
                }
                weight = face.get("weight")
                if _valid_font_weight(weight):
                    spec_face["weight"] = weight
                style = face.get("style")
                if _valid_font_style(style):
                    spec_face["style"] = style
                faces.append(spec_face)
    if not faces:
        return None
    # D4 read-through: the helper loads each face's BYTES from `store_root`, which is now the
    # engine's per-workspace materialization cache — so every face has to be pulled out of
    # durable storage before the spec is handed over. Fail-soft: a face whose bytes are durably
    # absent is left un-materialized and the helper reports it (LUMS0101), exactly as it did
    # when the byte was missing from the local tree.
    ensure_materialized(blobs, cache_dir, (face["digest"] for face in faces))
    return {"store_root": str(cache_dir), "faces": faces}


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
    # Harness alignment I1 (founder ruling 2026-10-17): the editor context carries facts only. How
    # much a turn may change is decided once, in the scene agent's system prompt, from the kind of
    # request; the old `editor_instruction` (touch as little as possible, preserve the layout) rode
    # every message, revamps included, and is gone.
    context = {
        "document_id": payload.document_id,
        "active_page_id": payload.active_page_id,
        "target_node_ids": targets,
        "scene_summary": scene_context_summary(payload.scene),
        "current_diagnostics": payload.diagnostics[:20],
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
    diagnostic_history: List[JsonObject] = []
    verification = result.get("draft_verification")
    if not isinstance(verification, dict):
        verification = None
    if verification:
        preflight = verification.get("preflight")
        if isinstance(preflight, dict) and preflight.get("status") == "current":
            diagnostics.extend(agent_diagnostics_from_summaries(
                preflight.get("diagnostics", []), "preflight"
            ))
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
                attempt_diagnostics = agent_diagnostics_from_summaries(
                    compile_summary.get("diagnostics", []), "dsl"
                )
                if attempt_diagnostics:
                    diagnostic_history.append({
                        "iteration": int(iteration_dir.name) if iteration_dir.name.isdigit() else iteration_dir.name,
                        "phase": "dsl",
                        "diagnostics": attempt_diagnostics,
                    })
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
    # A warning result retains editable work. It does not certify current
    # preflight, preview, or visual acceptance; the runtime receipts below
    # describe those separately. Preserve the existing proposal policy.
    best_draft = result.get("status") == "completed_with_warnings"
    status = (
        "proposed" if (accepted or edit_scoped or best_draft) and operations else "failed"
    )
    review = (verification or {}).get("review")
    review_current = isinstance(review, dict) and review.get("status") == "current"
    if (edit_scoped or best_draft) and status == "proposed" and review_current:
        diagnostics.extend(
            advisory_critique_diagnostics(result.get("critique"))
        )
    summary = result.get("summary") or "Agent run completed."
    if best_draft and not review_current:
        summary = draft_verification_note(verification)
    historical_critique = result.get("historical_critique")
    if not review_current and not historical_critique and result.get("critique"):
        historical_critique = {
            "critique": result["critique"],
            "status": "unbound",
            "scene_stamp": None,
            "iteration": None,
        }
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
        "summary": summary,
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
        "diagnostic_history": diagnostic_history,
        "draft_verification": verification,
        "historical_critique": historical_critique,
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


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def new_web_account_id() -> str:
    # P5 (D3): `acc_{uuid4hex}` minted when the client provides no explicit id.
    return f"acc_{uuid4().hex}"


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
