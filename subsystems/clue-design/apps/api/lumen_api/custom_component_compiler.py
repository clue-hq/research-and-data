"""P6.2 constrained custom-component compiler orchestration.

The Python API never parses or executes component source. It sends one
versioned JSON request to a separate, memory-capped Node process and accepts
only a validated protocol response. Deterministic authoring failures are
returned as ``failed``; process crashes, protocol corruption, and wall-clock
timeouts are ``transient_error`` and can never create an artifact.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict


JsonObject = Dict[str, Any]
COMPILER_PROTOCOL_VERSION = 1
DEFAULT_COMPILER_TIMEOUT_SECONDS = 12.0
MAX_COMPILER_RESPONSE_BYTES = 16 * 1024 * 1024


def default_compiler_worker_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "custom-component-compiler"
        / "compiler.mjs"
    )


def _infrastructure_result(message: str) -> JsonObject:
    return {
        "protocol_version": COMPILER_PROTOCOL_VERSION,
        "compiler_version": "unavailable",
        "status": "transient_error",
        "diagnostics": [
            {
                "code": "CCI0002",
                "severity": "error",
                "category": "infrastructure",
                "message": message,
                "file": None,
                "line": None,
                "column": None,
            }
        ],
    }


def compile_custom_component(
    *,
    node_binary: str,
    worker_path: Path,
    timeout_seconds: float,
    slug: str,
    entry: str,
    files: Dict[str, str],
    component_artifacts: Dict[str, str],
) -> JsonObject:
    request = {
        "protocol_version": COMPILER_PROTOCOL_VERSION,
        "slug": slug,
        "entry": entry,
        "files": files,
        "component_artifacts": component_artifacts,
    }
    payload = json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    command = [
        node_binary,
        "--max-old-space-size=192",
        "--permission",
        f"--allow-fs-read={worker_path.parent}",
        "--allow-child-process",
        str(worker_path),
    ]
    environment = {
        "NODE_ENV": "production",
        "NO_COLOR": "1",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "TZ": "UTC",
    }
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=worker_path.parent,
            env=environment,
            start_new_session=True,
        )
    except OSError as error:
        return _infrastructure_result(
            f"custom-component compiler could not start: {error}"
        )
    try:
        stdout, stderr = process.communicate(payload, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        return _infrastructure_result(
            f"custom-component compiler exceeded {timeout_seconds:g}s"
        )

    if len(stdout) > MAX_COMPILER_RESPONSE_BYTES:
        return _infrastructure_result(
            "custom-component compiler response exceeded its size limit"
        )
    try:
        result = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        detail = stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail[:500]}" if detail else ""
        return _infrastructure_result(
            f"custom-component compiler returned invalid JSON{suffix}"
        )
    if not isinstance(result, dict):
        return _infrastructure_result(
            "custom-component compiler returned a non-object response"
        )
    if (
        result.get("protocol_version") != COMPILER_PROTOCOL_VERSION
        or result.get("status") not in {"success", "failed", "transient_error"}
        or not isinstance(result.get("compiler_version"), str)
        or not isinstance(result.get("diagnostics"), list)
    ):
        return _infrastructure_result(
            "custom-component compiler violated protocol version 1"
        )
    if process.returncode != 0 and result["status"] != "transient_error":
        return _infrastructure_result(
            "custom-component compiler exited abnormally"
        )
    if result["status"] == "success":
        outputs = result.get("outputs")
        manifest = result.get("manifest")
        compiler_contract = (
            manifest.get("compiler") if isinstance(manifest, dict) else None
        )
        dependencies = (
            manifest.get("dependency_artifacts")
            if isinstance(manifest, dict)
            else None
        )
        if (
            not isinstance(outputs, dict)
            or not isinstance(outputs.get("browser_bundle"), str)
            or not outputs["browser_bundle"]
            or not isinstance(outputs.get("component_css"), str)
            or not isinstance(outputs.get("first_frame_html"), str)
            or not outputs["first_frame_html"]
            or not isinstance(manifest, dict)
            or not isinstance(compiler_contract, dict)
            or compiler_contract.get("protocol_version")
            != COMPILER_PROTOCOL_VERSION
            or compiler_contract.get("version") != result["compiler_version"]
            or not isinstance(manifest.get("meta"), dict)
            or not isinstance(manifest.get("props_schema"), dict)
            or not isinstance(manifest.get("defaults"), dict)
            or not isinstance(manifest.get("warnings"), list)
            or not isinstance(dependencies, dict)
            or any(
                not isinstance(dependency, str)
                or not isinstance(artifact_id, str)
                or component_artifacts.get(dependency) != artifact_id
                for dependency, artifact_id in (
                    dependencies.items() if isinstance(dependencies, dict) else []
                )
            )
        ):
            return _infrastructure_result(
                "custom-component compiler success response is incomplete"
            )
    return result
