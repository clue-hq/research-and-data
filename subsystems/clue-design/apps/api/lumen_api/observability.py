from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import traceback
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from py_lumen_config import settings


JsonObject = Dict[str, Any]

REQUEST_ID_HEADER = "x-request-id"
_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "lumen_request_id", default=None
)
_LOGGING_CONFIGURED = False

SECRET_FIELD_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
}


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: JsonObject = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "lumen_event", record.getMessage()),
            "message": record.getMessage(),
        }

        fields = getattr(record, "lumen_fields", None)
        if isinstance(fields, dict):
            payload.update(redact(fields))

        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_structured_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    level_name = settings.lumen_log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    setattr(handler, "_lumen_json_handler", True)

    root = logging.getLogger()
    if not any(getattr(existing, "_lumen_json_handler", False) for existing in root.handlers):
        root.addHandler(handler)

    logging.getLogger("lumen_api").setLevel(level)
    _LOGGING_CONFIGURED = True


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def current_request_id() -> Optional[str]:
    return _request_id.get()


def bind_request_id(request_id: str) -> contextvars.Token[Optional[str]]:
    return _request_id.set(request_id)


def reset_request_id(token: contextvars.Token[Optional[str]]) -> None:
    _request_id.reset(token)


def duration_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: Optional[str] = None,
    **fields: Any,
) -> None:
    request_id = current_request_id()
    if request_id and "request_id" not in fields:
        fields["request_id"] = request_id
    logger.log(
        level,
        message or event,
        extra={"lumen_event": event, "lumen_fields": fields},
    )


def redact(value: Any, key: Optional[str] = None) -> Any:
    if key and is_secret_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_FIELD_PARTS)


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
