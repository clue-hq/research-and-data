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
import tempfile
from pathlib import Path
from typing import Any, Dict, Literal, Tuple

from .database import Repository
from .custom_component_contract import custom_component_slug_is_valid


JsonObject = Dict[str, Any]
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


def persist_compiled_custom_component_artifact(
    repository: Repository,
    store_root: Path,
    *,
    account_id: str,
    slug: str,
    source: bytes,
    bundle: bytes,
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
    identity = {
        "schema_version": 1,
        "account_id": account_id,
        "slug": slug,
        "source_digest": source_blob["value"],
        "bundle_digest": bundle_blob["value"],
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
    member: Literal["source", "bundle"],
) -> Tuple[JsonObject, bytes]:
    """Resolve and integrity-check one artifact member for its owning account."""

    artifact = repository.require_custom_component_artifact(account_id, artifact_id)
    blob = artifact[member]
    expected_ref = f"sha256/{blob['value'][:2]}/{blob['value']}"
    if blob["algorithm"] != "sha256" or blob["opaque_ref"] != expected_ref:
        raise RuntimeError(
            f"custom component artifact has an invalid blob record: {artifact_id}"
        )
    path = Path(store_root) / expected_ref
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError) as error:
        raise RuntimeError(
            f"custom component artifact blob is missing: {blob['opaque_ref']}"
        ) from error
    if (
        len(data) != blob["byte_length"]
        or hashlib.sha256(data).hexdigest() != blob["value"]
    ):
        raise RuntimeError(
            f"custom component artifact blob failed integrity check: {blob['opaque_ref']}"
        )
    return artifact, data
