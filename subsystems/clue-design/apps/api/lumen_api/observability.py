"""API-side observability helpers layered on the shared ``py_lumen_obs`` module.

All structlog configuration, formatting, redaction and the stdlib bridge live in
``py_lumen_obs`` (the ONE place that configures logging). This module keeps only
the API-specific pieces: the request-id header contract, business-shaped event
summaries, and the thin ``log_event`` adapter that every route uses to emit the
canonical structured events (``http_request_completed``, ``core_helper_*`` …)
through the shared pipeline.

``request_id`` is bound once per request into the obs contextvar by the HTTP
middleware (``py_lumen_obs.bind_request_id``); it is no longer threaded through
individual log calls — the ``merge_contextvars`` processor stamps it on every
event. Secret/blob redaction is handled by the shared ``redact`` processor, so
this module no longer carries its own formatter or redaction table.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

import structlog


JsonObject = Dict[str, Any]

REQUEST_ID_HEADER = "x-request-id"


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def current_request_id() -> Optional[str]:
    """The request_id bound into the ambient obs contextvar by the HTTP
    middleware. Read here for the one non-logging consumer: forwarding it to the
    core-helper subprocess env (``LUMEN_REQUEST_ID``)."""
    return structlog.contextvars.get_contextvars().get("request_id")


def duration_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def log_event(
    logger: Any,
    level: int,
    event: str,
    message: Optional[str] = None,
    **fields: Any,
) -> None:
    """Emit a structured event through the shared obs pipeline.

    ``logger`` is an obs (structlog) logger from ``py_lumen_obs.get_logger``.
    The event name is the structlog event; fields become event-dict keys. No
    request_id is injected here — it rides the obs contextvar.
    """
    if message is not None and message != event:
        fields.setdefault("message", message)
    logger.log(level, event, **fields)


def diagnostic_summary(diagnostics: Iterable[JsonObject]) -> JsonObject:
    diagnostics_list = [diagnostic for diagnostic in diagnostics if isinstance(diagnostic, dict)]
    error_count = sum(1 for diagnostic in diagnostics_list if diagnostic.get("severity") == "error")
    warning_count = sum(
        1 for diagnostic in diagnostics_list if diagnostic.get("severity") == "warning"
    )
    top_codes = []
    for diagnostic in diagnostics_list:
        code = diagnostic.get("code")
        if isinstance(code, str) and code not in top_codes:
            top_codes.append(code)
        if len(top_codes) >= 5:
            break
    return {
        "diagnostic_count": len(diagnostics_list),
        "error_count": error_count,
        "warning_count": warning_count,
        "top_diagnostic_codes": top_codes,
    }


def artifact_summary(export: JsonObject) -> JsonObject:
    artifacts = [
        artifact
        for artifact in export.get("artifacts", [])
        if isinstance(artifact, dict)
    ]
    return {
        "artifact_count": len(artifacts),
        "artifact_formats": sorted(
            {
                str(artifact.get("format"))
                for artifact in artifacts
                if artifact.get("format") is not None
            }
        ),
        "artifact_ids": [
            str(artifact.get("asset_id") or artifact.get("filename") or artifact.get("page_id"))
            for artifact in artifacts[:10]
        ],
    }


def helper_request_summary(request: JsonObject) -> JsonObject:
    action = str(request.get("action") or "unknown")
    summary: JsonObject = {"action": action}
    match action:
        case "apply_operations":
            operations = request.get("operations")
            summary["operation_count"] = len(operations) if isinstance(operations, list) else 0
        case "compile_dsl_into_scene":
            source = request.get("source")
            summary["source_line_count"] = len(str(source or "").splitlines())
            summary["has_dsl_session"] = request.get("dsl_session") is not None
        case "preflight_scene":
            summary["has_brand_kit"] = request.get("brand_kit") is not None
            summary["has_mode"] = request.get("mode") is not None
        case "export_preview":
            page_ids = request.get("page_ids")
            profile = request.get("profile")
            summary["format"] = request.get("format")
            summary["page_id_count"] = len(page_ids) if isinstance(page_ids, list) else 0
            summary["profile_name"] = profile.get("name") if isinstance(profile, dict) else None
        case "validate_brand_kit":
            summary["product_ready"] = request.get("product_ready")
        case "validate_scene_brand_governance":
            summary["strictness"] = request.get("strictness")
    return summary
