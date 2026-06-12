from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .observability import (
    current_request_id,
    diagnostic_summary,
    duration_ms,
    helper_request_summary,
    log_event,
)


JsonObject = Dict[str, Any]
core_logger = logging.getLogger("lumen_api.core")
helper_logger = logging.getLogger("lumen_api.core.helper")


class CoreError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        diagnostics: Optional[List[JsonObject]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or []


class CoreClient:
    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[3]

    def new_scene(
        self,
        document_id: str,
        title: str,
        artifact_type: Optional[str] = None,
        medium: Optional[Any] = None,
    ) -> JsonObject:
        response = self._run(
            {
                "action": "new_scene",
                "document_id": document_id,
                "title": title,
                "artifact_type": artifact_type,
                "medium": medium,
            }
        )
        return response["scene"]

    def validate_scene(self, scene: JsonObject) -> JsonObject:
        return self._run({"action": "validate_scene", "scene": scene})

    def apply_operations(
        self,
        scene: JsonObject,
        operations: List[JsonObject],
        scope: Optional[JsonObject] = None,
    ) -> JsonObject:
        request = {"action": "apply_operations", "scene": scene, "operations": operations}
        if scope is not None:
            request["scope"] = scope
        return self._run(request)

    def apply_structured_edit(
        self,
        scene: JsonObject,
        edit: JsonObject,
        scope: Optional[JsonObject] = None,
    ) -> JsonObject:
        request = {"action": "apply_structured_edit", "scene": scene, "edit": edit}
        if scope is not None:
            request["scope"] = scope
        return self._run(request)

    def compile_dsl_into_scene(
        self,
        scene: JsonObject,
        source: str,
        dsl_session: Optional[JsonObject] = None,
    ) -> JsonObject:
        return self._run(
            {
                "action": "compile_dsl_into_scene",
                "scene": scene,
                "source": source,
                "dsl_session": dsl_session,
            }
        )

    def preflight_scene(
        self,
        scene: JsonObject,
        brand_kit: Optional[JsonObject],
        mode: Optional[JsonObject] = None,
    ) -> JsonObject:
        return self._run(
            {
                "action": "preflight_scene",
                "scene": scene,
                "brand_kit": brand_kit,
                "mode": mode,
            }
        )

    def export_preview(
        self,
        scene: JsonObject,
        export_format: str = "svg",
        page_ids: Optional[List[str]] = None,
        profile: Optional[JsonObject] = None,
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "export_preview",
                "scene": scene,
                "format": export_format,
                "page_ids": page_ids or [],
                "profile": profile,
            },
            raise_on_error=raise_on_error,
        )

    def finalize_template(
        self, scene: JsonObject, template_revision_id: str
    ) -> JsonObject:
        return self._run(
            {
                "action": "finalize_template",
                "scene": scene,
                "template_revision_id": template_revision_id,
            }
        )

    def platform_default_brand_kit(self) -> JsonObject:
        response = self._run({"action": "platform_default_brand_kit"})
        return response["brand_kit"]

    def validate_brand_kit(
        self,
        brand_kit: JsonObject,
        product_ready: bool = True,
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "validate_brand_kit",
                "brand_kit": brand_kit,
                "product_ready": product_ready,
            },
            raise_on_error=raise_on_error,
        )

    def compile_styles_brand_kit(
        self,
        source: str,
        brand_kit_id: str,
        version: int,
        name: str,
    ) -> JsonObject:
        return self._run(
            {
                "action": "compile_styles_brand_kit",
                "source": source,
                "brand_kit_id": brand_kit_id,
                "version": version,
                "name": name,
            }
        )

    def generate_brand_kit(self, seed: JsonObject) -> JsonObject:
        return self._run({"action": "generate_brand_kit", "seed": seed})

    def summarize_brand_kit(
        self, brand_kit: JsonObject, raise_on_error: bool = True
    ) -> JsonObject:
        return self._run(
            {"action": "summarize_brand_kit", "brand_kit": brand_kit},
            raise_on_error=raise_on_error,
        )

    def validate_scene_brand_governance(
        self,
        scene: JsonObject,
        brand_kit: JsonObject,
        strictness: str = "strict",
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "validate_scene_brand_governance",
                "scene": scene,
                "brand_kit": brand_kit,
                "strictness": strictness,
            },
            raise_on_error=raise_on_error,
        )

    def compare_brand_kit_compatibility(
        self,
        from_brand_kit: JsonObject,
        to_brand_kit: JsonObject,
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "compare_brand_kit_compatibility",
                "from": from_brand_kit,
                "to": to_brand_kit,
            },
            raise_on_error=raise_on_error,
        )

    def layout_geometry(self, scene: JsonObject) -> JsonObject:
        return self._run({"action": "layout_geometry", "scene": scene})

    def _run(self, request: JsonObject, raise_on_error: bool = True) -> JsonObject:
        command = self._command()
        action = str(request.get("action") or "unknown")
        helper_call_id = f"core_{uuid4().hex}"
        start = time.perf_counter()
        env = os.environ.copy()
        env.setdefault("LUMEN_CORE_HELPER_LOG", "1")
        env["LUMEN_CORE_CALL_ID"] = helper_call_id
        if current_request_id():
            env["LUMEN_REQUEST_ID"] = current_request_id() or ""
        log_event(
            core_logger,
            logging.INFO,
            "core_helper_started",
            helper_call_id=helper_call_id,
            **helper_request_summary(request),
        )
        process = subprocess.run(
            command,
            input=json.dumps(request),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.repo_root),
            env=env,
            check=False,
        )
        forward_helper_logs(process.stderr, helper_call_id, action)
        if process.returncode != 0:
            log_event(
                core_logger,
                logging.ERROR,
                "core_helper_process_failed",
                helper_call_id=helper_call_id,
                action=action,
                returncode=process.returncode,
                duration_ms=duration_ms(start),
                stderr_line_count=len([line for line in process.stderr.splitlines() if line]),
            )
            raise CoreError("helper.process", process.stderr.strip() or process.stdout)

        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            log_event(
                core_logger,
                logging.ERROR,
                "core_helper_response_invalid",
                helper_call_id=helper_call_id,
                action=action,
                duration_ms=duration_ms(start),
                stdout_length=len(process.stdout),
            )
            raise CoreError("helper.response", str(error)) from error

        diagnostics = response.get("diagnostics") or []
        error = response.get("error") or {}
        log_event(
            core_logger,
            logging.INFO,
            "core_helper_completed",
            helper_call_id=helper_call_id,
            action=action,
            ok=bool(response.get("ok")),
            duration_ms=duration_ms(start),
            applied_operations=response.get("applied_operations"),
            error_code=error.get("code") if isinstance(error, dict) else None,
            **diagnostic_summary(diagnostics if isinstance(diagnostics, list) else []),
        )
        if not response.get("ok") and raise_on_error:
            raise CoreError(
                error.get("code", "helper.error"),
                error.get("message", "core helper returned an error"),
                response.get("diagnostics") or [],
            )
        return response

    def _command(self) -> List[str]:
        helper = os.environ.get("LUMEN_CORE_HELPER")
        if helper:
            return [helper]
        return [
            "cargo",
            "run",
            "--quiet",
            "--manifest-path",
            str(self.repo_root / "Cargo.toml"),
            "-p",
            "lumen-api-helper",
        ]


def forward_helper_logs(stderr: str, helper_call_id: str, action: str) -> None:
    for line in stderr.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            log_event(
                helper_logger,
                logging.WARNING,
                "core_helper_stderr",
                helper_call_id=helper_call_id,
                action=action,
                stderr_length=len(line),
            )
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("source") != "lumen-api-helper":
            log_event(
                helper_logger,
                logging.DEBUG,
                "core_helper_stderr_json",
                helper_call_id=helper_call_id,
                action=action,
                helper_payload_keys=sorted(str(key) for key in payload.keys()),
                helper_payload_source=payload.get("source"),
            )
            continue
        event = str(payload.get("event") or "core_helper_boundary")
        level_name = str(payload.get("level") or "info").upper()
        level = getattr(logging, level_name, logging.INFO)
        fields = {
            key: value
            for key, value in payload.items()
            if key not in {"source", "event", "level"}
        }
        fields.setdefault("helper_call_id", helper_call_id)
        fields.setdefault("action", action)
        log_event(helper_logger, level, event, **fields)


def has_error_diagnostics(diagnostics: List[JsonObject]) -> bool:
    return any(diagnostic.get("severity") == "error" for diagnostic in diagnostics)
