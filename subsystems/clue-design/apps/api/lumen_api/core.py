from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


JsonObject = Dict[str, Any]


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

    def apply_operations(self, scene: JsonObject, operations: List[JsonObject]) -> JsonObject:
        return self._run(
            {"action": "apply_operations", "scene": scene, "operations": operations}
        )

    def compile_dsl_into_scene(self, scene: JsonObject, source: str) -> JsonObject:
        return self._run(
            {"action": "compile_dsl_into_scene", "scene": scene, "source": source}
        )

    def preflight_scene(
        self, scene: JsonObject, brand_kit: Optional[JsonObject]
    ) -> JsonObject:
        return self._run(
            {"action": "preflight_scene", "scene": scene, "brand_kit": brand_kit}
        )

    def export_preview(
        self,
        scene: JsonObject,
        export_format: str = "svg",
        page_ids: Optional[List[str]] = None,
    ) -> JsonObject:
        return self._run(
            {
                "action": "export_preview",
                "scene": scene,
                "format": export_format,
                "page_ids": page_ids or [],
            }
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

    def layout_geometry(self, scene: JsonObject) -> JsonObject:
        return self._run({"action": "layout_geometry", "scene": scene})

    def _run(self, request: JsonObject) -> JsonObject:
        command = self._command()
        process = subprocess.run(
            command,
            input=json.dumps(request),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.repo_root),
            check=False,
        )
        if process.returncode != 0:
            raise CoreError("helper.process", process.stderr.strip() or process.stdout)

        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise CoreError("helper.response", str(error)) from error

        if not response.get("ok"):
            error = response.get("error") or {}
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


def has_error_diagnostics(diagnostics: List[JsonObject]) -> bool:
    return any(diagnostic.get("severity") == "error" for diagnostic in diagnostics)
