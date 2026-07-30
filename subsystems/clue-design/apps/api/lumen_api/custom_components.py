"""Durable P6 custom-component artifact storage.

P6.1 provides the immutable persistence seam but intentionally exposes no HTTP
write endpoint. P6.2's constrained compiler will call
``persist_compiled_custom_component_artifact`` only after its compile/security
gate succeeds. Tests use the same seam with explicit fixture compiler
provenance; no alternate "mark this source successful" API exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import tempfile
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from .database import Repository
from .custom_component_contract import custom_component_slug_is_valid


JsonObject = Dict[str, Any]
MAX_SOURCE_FILE_COUNT = 32
MAX_SOURCE_FILE_BYTES = 256 * 1024
MAX_SOURCE_SNAPSHOT_BYTES = 1024 * 1024
SOURCE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}


def _canonical_json(value: JsonObject) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _store_content_addressed_blob(store_root: Path, data: bytes) -> JsonObject:
    digest = hashlib.sha256(data).hexdigest()
    opaque_ref = f"sha256/{digest[:2]}/{digest}"
    target = store_root / opaque_ref
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        if not target.is_file() or target.read_bytes() != data:
            raise RuntimeError(
                f"content-addressed store collision/corruption at {opaque_ref}"
            )
    else:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if not target.is_file() or target.read_bytes() != data:
                    raise RuntimeError(
                        f"content-addressed store collision/corruption at {opaque_ref}"
                    )
        finally:
            temporary.unlink(missing_ok=True)

    return {
        "algorithm": "sha256",
        "value": digest,
        "opaque_ref": opaque_ref,
        "byte_length": len(data),
    }


def _read_content_addressed_blob(store_root: Path, blob: JsonObject) -> bytes:
    digest = str(blob.get("value") or "")
    expected_ref = f"sha256/{digest[:2]}/{digest}"
    if blob.get("algorithm") != "sha256" or blob.get("opaque_ref") != expected_ref:
        raise RuntimeError(
            f"content-addressed blob has an invalid store record: {blob!r}"
        )
    path = Path(store_root) / expected_ref
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError) as error:
        raise RuntimeError(
            f"content-addressed blob is missing: {blob.get('opaque_ref')}"
        ) from error
    if (
        len(data) != blob.get("byte_length")
        or hashlib.sha256(data).hexdigest() != digest
    ):
        raise RuntimeError(
            f"content-addressed blob failed integrity check: {blob.get('opaque_ref')}"
        )
    return data


def _source_path_is_valid(path: str) -> bool:
    if (
        not path
        or len(path) > 240
        or "\\" in path
        or "\x00" in path
        or path.startswith("/")
    ):
        return False
    normalized = posixpath.normpath(path)
    return (
        normalized == path
        and normalized not in {".", ".."}
        and not normalized.startswith("../")
        and Path(normalized).suffix in SOURCE_EXTENSIONS
    )


def canonical_custom_component_source_snapshot(
    *, slug: str, files: Dict[str, str]
) -> Tuple[bytes, JsonObject]:
    """Validate and deterministically encode one component source tree."""

    if not custom_component_slug_is_valid(slug):
        raise ValueError(
            "custom component slug must be 1–64 lowercase kebab-case characters"
        )
    if not isinstance(files, dict) or not (1 <= len(files) <= MAX_SOURCE_FILE_COUNT):
        raise ValueError(
            f"custom component source must contain 1–{MAX_SOURCE_FILE_COUNT} files"
        )
    entry = f"{slug}.tsx"
    if entry not in files:
        raise ValueError(f"custom component entry file must be {entry}")
    total = 0
    file_records: Dict[str, JsonObject] = {}
    normalized_files: Dict[str, str] = {}
    for file_path, source in sorted(files.items()):
        if not isinstance(file_path, str) or not _source_path_is_valid(file_path):
            raise ValueError(
                f"custom component source path is invalid or escapes its directory: {file_path!r}"
            )
        if not isinstance(source, str):
            raise ValueError(
                f"custom component source file must contain UTF-8 text: {file_path}"
            )
        encoded = source.encode("utf-8")
        if len(encoded) > MAX_SOURCE_FILE_BYTES:
            raise ValueError(
                f"custom component source file exceeds {MAX_SOURCE_FILE_BYTES} bytes: {file_path}"
            )
        total += len(encoded)
        normalized_files[file_path] = source
        file_records[file_path] = {
            "algorithm": "sha256",
            "value": hashlib.sha256(encoded).hexdigest(),
            "byte_length": len(encoded),
        }
    if total > MAX_SOURCE_SNAPSHOT_BYTES:
        raise ValueError(
            f"custom component source exceeds {MAX_SOURCE_SNAPSHOT_BYTES} bytes"
        )
    snapshot = {
        "schema_version": 1,
        "entry": entry,
        "files": normalized_files,
    }
    return _canonical_json(snapshot), {
        "schema_version": 1,
        "entry": entry,
        "files": file_records,
        "total_byte_length": total,
    }


def persist_custom_component_source_revision(
    repository: Repository,
    store_root: Path,
    *,
    account_id: str,
    slug: str,
    expected_version: int,
    files: Dict[str, str],
    provenance: JsonObject,
) -> JsonObject:
    repository.require_web_account(account_id)
    if not isinstance(provenance, dict):
        raise ValueError("custom component source provenance must be an object")
    snapshot_bytes, files_manifest = canonical_custom_component_source_snapshot(
        slug=slug, files=files
    )
    snapshot_blob = _store_content_addressed_blob(store_root, snapshot_bytes)
    next_version = expected_version + 1
    revision_identity = {
        "schema_version": 1,
        "account_id": account_id,
        "slug": slug,
        "source_version": next_version,
        "snapshot_digest": snapshot_blob["value"],
    }
    revision_id = (
        "ccsrc_" + hashlib.sha256(_canonical_json(revision_identity)).hexdigest()
    )
    return repository.create_custom_component_source_revision(
        {
            "revision_id": revision_id,
            "account_id": account_id,
            "slug": slug,
            "entry_path": f"{slug}.tsx",
            "snapshot": snapshot_blob,
            "files_manifest": files_manifest,
            "provenance": provenance,
        },
        expected_version=expected_version,
    )


def resolve_custom_component_source_snapshot(
    repository: Repository,
    store_root: Path,
    *,
    account_id: str,
    revision_id: str,
) -> Tuple[JsonObject, Dict[str, str]]:
    revision = repository.require_custom_component_source_revision(
        account_id, revision_id
    )
    data = _read_content_addressed_blob(store_root, revision["snapshot"])
    try:
        snapshot = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"custom component source snapshot is invalid: {revision_id}"
        ) from error
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema_version") != 1
        or snapshot.get("entry") != revision["entry_path"]
        or not isinstance(snapshot.get("files"), dict)
    ):
        raise RuntimeError(
            f"custom component source snapshot contract is invalid: {revision_id}"
        )
    source_bytes, manifest = canonical_custom_component_source_snapshot(
        slug=revision["slug"], files=snapshot["files"]
    )
    if (
        source_bytes != data
        or manifest != revision["files_manifest"]
    ):
        raise RuntimeError(
            f"custom component source snapshot metadata is inconsistent: {revision_id}"
        )
    return revision, snapshot["files"]


def persist_compiled_custom_component_artifact(
    repository: Repository,
    store_root: Path,
    *,
    account_id: str,
    slug: str,
    source: bytes,
    bundle: bytes,
    css: Optional[bytes] = None,
    first_frame: Optional[bytes] = None,
    manifest: JsonObject,
    provenance: JsonObject,
) -> JsonObject:
    """Store one immutable successful compile and return its registry record.

    The identity includes account, slug, both byte digests, and canonical
    manifest/provenance records. Repeating the exact compile is idempotent;
    changing any identity input creates a different artifact. The repository
    rejects an attempt to reuse an artifact id with different metadata.
    """

    repository.require_web_account(account_id)
    if not custom_component_slug_is_valid(slug):
        raise ValueError(
            "custom component slug must be 1–64 lowercase kebab-case characters"
        )
    if not source:
        raise ValueError("compiled custom component source snapshot cannot be empty")
    if not bundle:
        raise ValueError("compiled custom component bundle cannot be empty")
    if (css is None) != (first_frame is None):
        raise ValueError("compiled css and first_frame must be supplied together")
    if not isinstance(manifest, dict):
        raise ValueError("compiled custom component manifest must be an object")
    if not isinstance(provenance, dict):
        raise ValueError("compiled custom component provenance must be an object")
    try:
        _canonical_json(manifest)
        _canonical_json(provenance)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "compiled custom component manifest and provenance must be JSON-safe"
        ) from error

    source_blob = _store_content_addressed_blob(Path(store_root), source)
    bundle_blob = _store_content_addressed_blob(Path(store_root), bundle)
    css_blob = (
        _store_content_addressed_blob(Path(store_root), css)
        if css is not None
        else None
    )
    first_frame_blob = (
        _store_content_addressed_blob(Path(store_root), first_frame)
        if first_frame is not None
        else None
    )
    identity = {
        "schema_version": 1,
        "account_id": account_id,
        "slug": slug,
        "source_digest": source_blob["value"],
        "bundle_digest": bundle_blob["value"],
        "css_digest": css_blob["value"] if css_blob else None,
        "first_frame_digest": (
            first_frame_blob["value"] if first_frame_blob else None
        ),
        "manifest": manifest,
        "provenance": provenance,
    }
    artifact_digest = hashlib.sha256(_canonical_json(identity)).hexdigest()
    artifact_id = f"ccart_{artifact_digest}"
    return repository.register_custom_component_artifact(
        {
            "artifact_id": artifact_id,
            "account_id": account_id,
            "slug": slug,
            "source": source_blob,
            "bundle": bundle_blob,
            "css": css_blob,
            "first_frame": first_frame_blob,
            "manifest": manifest,
            "provenance": provenance,
        }
    )


def resolve_custom_component_artifact_blob(
    repository: Repository,
    store_root: Path,
    *,
    account_id: str,
    artifact_id: str,
    member: Literal["source", "bundle", "css", "first_frame"],
) -> Tuple[JsonObject, bytes]:
    """Resolve and integrity-check one artifact member for its owning account."""

    artifact = repository.require_custom_component_artifact(account_id, artifact_id)
    blob = artifact[member]
    if blob is None:
        raise RuntimeError(
            f"custom component artifact has no {member} blob: {artifact_id}"
        )
    return artifact, _read_content_addressed_blob(Path(store_root), blob)
