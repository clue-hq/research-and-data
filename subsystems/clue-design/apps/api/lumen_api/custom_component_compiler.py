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

# D2.5B: kept only for `sqlite3.Error`, the API's constraint-violation exception family (the
# bridge raises `sqlite3.IntegrityError` for Postgres constraint failures — see design_store.py).
# There is no SQLite database behind it.
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict
from uuid import uuid4

from .custom_components import (
    canonical_custom_component_source_snapshot,
    persist_compiled_custom_component_artifact,
    resolve_custom_component_source_snapshot,
)
from .design_store import DesignBlobStore, HybridRepository


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


def compile_and_persist_custom_component(
    *,
    repository: HybridRepository,
    blobs: DesignBlobStore,
    node_binary: str,
    worker_path: Path,
    timeout_seconds: float,
    account_id: str,
    slug: str,
    source_version: int,
    actor: JsonObject,
    compile_fn: Callable[..., JsonObject] = compile_custom_component,
) -> JsonObject:
    """Compile one exact durable source revision and persist its outcome.

    This is the single orchestration seam shared by the HTTP endpoint and the
    Deep Agent registry gateway. It preserves the P6.2 guarantees: the worker
    receives only the requested account's durable source/dependency pins, an
    optimistic version check is repeated after the out-of-transaction compile,
    only a protocol-valid success can create an immutable artifact, and every
    outcome gets a durable compilation record.

    The returned ``compile_status`` is one of ``success``, ``failed``, or
    ``transient_error``. Callers decide how to expose/retry those states; this
    function performs exactly one worker attempt.
    """

    component = repository.require_custom_component(account_id, slug)
    current_version = int(component["source_version"])
    if current_version != source_version:
        from .database import CustomComponentSourceVersionConflict

        raise CustomComponentSourceVersionConflict(
            slug, source_version, current_version
        )
    revision = repository.get_current_custom_component_source(account_id, slug)
    if revision is None:
        from .database import NotFoundError

        raise NotFoundError("custom_component_source", slug)
    _, files = resolve_custom_component_source_snapshot(
        repository,
        blobs,
        account_id=account_id,
        revision_id=revision["revision_id"],
    )
    component_artifacts = {
        item["slug"]: item["latest_artifact_id"]
        for item in repository.list_custom_components(account_id)
        if item["slug"] != slug and item["latest_artifact_id"] is not None
    }
    result = compile_fn(
        node_binary=node_binary,
        worker_path=worker_path,
        timeout_seconds=timeout_seconds,
        slug=slug,
        entry=revision["entry_path"],
        files=files,
        component_artifacts=component_artifacts,
    )

    # The compiler runs outside the database transaction. An older compile may
    # finish after a source write, so re-check before it can become attachable.
    current_version = int(
        repository.require_custom_component(account_id, slug)["source_version"]
    )
    if current_version != source_version:
        from .database import CustomComponentSourceVersionConflict

        raise CustomComponentSourceVersionConflict(
            slug, source_version, current_version
        )

    compilation_id = f"cccmp_{uuid4().hex}"
    compiler_version = str(result.get("compiler_version") or "unavailable")
    diagnostics = result.get("diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = []
    artifact = None
    status = result["status"]
    if status == "success":
        snapshot_bytes, _ = canonical_custom_component_source_snapshot(
            slug=slug, files=files
        )
        outputs = result["outputs"]
        manifest = result["manifest"]
        try:
            artifact = persist_compiled_custom_component_artifact(
                repository,
                blobs,
                account_id=account_id,
                slug=slug,
                source=snapshot_bytes,
                bundle=outputs["browser_bundle"].encode("utf-8"),
                css=outputs["component_css"].encode("utf-8"),
                first_frame=outputs["first_frame_html"].encode("utf-8"),
                manifest=manifest,
                provenance={
                    "kind": "lumen_custom_component_compiler",
                    "compiler_protocol_version": COMPILER_PROTOCOL_VERSION,
                    "compiler_version": compiler_version,
                    "source_revision_id": revision["revision_id"],
                    "source_version": revision["source_version"],
                    "dependency_artifacts": manifest.get(
                        "dependency_artifacts", {}
                    ),
                    "actor": actor,
                },
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            status = "transient_error"
            diagnostics = [
                *diagnostics,
                {
                    "code": "CCI0003",
                    "severity": "error",
                    "category": "infrastructure",
                    "message": (
                        "compiled artifact could not be persisted: "
                        f"{type(error).__name__}"
                    ),
                    "file": None,
                    "line": None,
                    "column": None,
                },
            ]
            artifact = None

    compilation = repository.record_custom_component_compilation(
        {
            "compilation_id": compilation_id,
            "account_id": account_id,
            "slug": slug,
            "source_revision_id": revision["revision_id"],
            "source_version": revision["source_version"],
            "status": "succeeded" if status == "success" else status,
            "compiler_protocol_version": COMPILER_PROTOCOL_VERSION,
            "compiler_version": compiler_version,
            "diagnostics": diagnostics,
            "artifact_id": artifact["artifact_id"] if artifact else None,
        }
    )
    return {
        "schema_version": 1,
        "compile_status": status,
        "compilation": compilation,
        "artifact": artifact,
    }
