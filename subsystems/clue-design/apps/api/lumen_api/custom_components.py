"""Durable P6 custom-component artifact storage.

P6.1 provides the immutable persistence seam but intentionally exposes no HTTP
write endpoint. P6.2's constrained compiler will call
``persist_compiled_custom_component_artifact`` only after its compile/security
gate succeeds. Tests use the same seam with explicit fixture compiler
provenance; no alternate "mark this source successful" API exists.

**D4 (design-integration Part II): the bytes live in platform storage.** The
API-local ``custom-components/sha256/{ab}/{digest}`` tree is gone; every blob is
written through :class:`~lumen_api.design_store.DesignBlobStore` into
``clue_storage`` under ``{workspace_id}/design/{sha256}``, with an ``artifact``
row recorded before the blob. So these functions take a blob-store handle where
they used to take a ``store_root: Path``. The blob descriptor a registry row
carries keeps its exact shape — ``{algorithm, value, opaque_ref, byte_length}``
— but ``opaque_ref`` now holds the platform storage key. Readers **never parse
that ref as a path**: they resolve by ``value`` (the digest) against the
caller's workspace, which is why a legacy row written by the old store (whose
ref is ``sha256/{ab}/{digest}``) still reads correctly.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

from clue_design.storage import SOURCE_KEY_CUSTOM_COMPONENT

from .database import NotFoundError
from .design_store import DesignBlobStore, HybridRepository
from .custom_component_contract import custom_component_slug_is_valid


JsonObject = Dict[str, Any]
MAX_SOURCE_FILE_COUNT = 32
MAX_SOURCE_FILE_BYTES = 256 * 1024
MAX_SOURCE_SNAPSHOT_BYTES = 1024 * 1024
SOURCE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}

# The media type each artifact member is stored AND served as. This is the ONE table: the
# member-serving route reads it, and it is what lands on the blob's `artifact` row.
#
# It has to be the member's TRUE type, not a blanket `application/octet-stream`, because D4 put
# component blobs and publish delivery assets in ONE content-addressed namespace (R-D4-3): a
# compiled first frame and the publish asset minted from those same bytes are the same key and
# therefore the same row, and `record_artifact` keeps the FIRST writer's media type. Storing a
# member honestly is what makes the two writers agree instead of racing.
CUSTOM_COMPONENT_MEMBER_MEDIA_TYPES: Dict[str, str] = {
    "source": "application/json",
    "bundle": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "first_frame": "text/html; charset=utf-8",
}
# A component SOURCE snapshot (the canonical-JSON file tree) — the same bytes the artifact's
# `source` member carries, hence the same media type.
SOURCE_SNAPSHOT_MEDIA_TYPE = CUSTOM_COMPONENT_MEMBER_MEDIA_TYPES["source"]


def _canonical_json(value: JsonObject) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _store_content_addressed_blob(
    blobs: DesignBlobStore, data: bytes, *, media_type: str
) -> JsonObject:
    storage_key = blobs.register(
        data, media_type=media_type, source_key=SOURCE_KEY_CUSTOM_COMPONENT
    )
    return {
        "algorithm": "sha256",
        "value": hashlib.sha256(data).hexdigest(),
        "opaque_ref": storage_key,
        "byte_length": len(data),
    }


def _read_content_addressed_blob(blobs: DesignBlobStore, blob: JsonObject) -> bytes:
    """Resolve one stored blob by DIGEST and re-verify it end to end.

    The stored ``opaque_ref`` is never used as a lookup path — the key is derived from the
    digest and the reader's workspace — so this accepts both a D4 storage-key ref and a
    legacy ``sha256/{ab}/{digest}`` one. The digest + byte-length re-check survives the move
    unchanged: platform storage is content-addressed too, but the descriptor is the registry's
    own claim about the bytes and is still verified against them.
    """
    digest = str(blob.get("value") or "")
    if blob.get("algorithm") != "sha256" or not blob.get("opaque_ref"):
        raise RuntimeError(
            f"content-addressed blob has an invalid store record: {blob!r}"
        )
    try:
        data = blobs.read(digest)
    except (NotFoundError, ValueError) as error:
        # NotFoundError: no live artifact row for this digest in this workspace, or its bytes
        # are gone. ValueError: the descriptor's `value` is not a sha256 (a key is data — the
        # seam refuses to mint a key from it). Both are "the blob is not there", as before.
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
    repository: HybridRepository,
    blobs: DesignBlobStore,
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
    snapshot_blob = _store_content_addressed_blob(
        blobs, snapshot_bytes, media_type=SOURCE_SNAPSHOT_MEDIA_TYPE
    )
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
    repository: HybridRepository,
    blobs: DesignBlobStore,
    *,
    account_id: str,
    revision_id: str,
) -> Tuple[JsonObject, Dict[str, str]]:
    revision = repository.require_custom_component_source_revision(
        account_id, revision_id
    )
    data = _read_content_addressed_blob(blobs, revision["snapshot"])
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
    repository: HybridRepository,
    blobs: DesignBlobStore,
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

    def store(member: str, data: bytes) -> JsonObject:
        return _store_content_addressed_blob(
            blobs, data, media_type=CUSTOM_COMPONENT_MEMBER_MEDIA_TYPES[member]
        )

    source_blob = store("source", source)
    bundle_blob = store("bundle", bundle)
    css_blob = store("css", css) if css is not None else None
    first_frame_blob = (
        store("first_frame", first_frame) if first_frame is not None else None
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
    repository: HybridRepository,
    blobs: DesignBlobStore,
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
    return artifact, _read_content_addressed_blob(blobs, blob)
