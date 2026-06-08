from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


JsonObject = Dict[str, Any]
DTO_SCHEMA_VERSION = 1


def document_summary(document: JsonObject) -> JsonObject:
    scene = document["scene"]
    return {
        "id": document["id"],
        "title": document["title"],
        "status": document["status"],
        "current_version": document["current_version"],
        "artifact_type": scene.get("meta", {}).get("artifact_type"),
        "medium": scene.get("meta", {}).get("medium"),
        "brand_kit": scene.get("meta", {}).get("brand_kit"),
        "effective_brand_kit": {
            "source": document.get("effective_brand_kit_source"),
            "id": document.get("effective_brand_kit_id"),
            "version": document.get("effective_brand_kit_version"),
        },
        "counts": scene_counts(scene),
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
    }


def document_created_dto(document: JsonObject) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "status": "created",
        "document": document_summary(document),
    }


def scene_replaced_dto(document: JsonObject, diagnostics: List[JsonObject]) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "status": "applied",
        "document": document_summary(document),
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
    }


def operation_application_dto(
    document: JsonObject,
    applied_operations: int,
    operations: List[JsonObject],
    diagnostics: List[JsonObject],
    snapshot: Optional[JsonObject],
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "document_id": document["id"],
        "status": "applied",
        "document": document_summary(document),
        "operation_application": {
            "applied_operations": applied_operations,
            "preflight_operations": 0,
        },
        "operations": operation_summaries(operations),
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
        "snapshot": snapshot_summary(snapshot) if snapshot else None,
    }


def preflight_dto(
    document: JsonObject,
    diagnostics: List[JsonObject],
    preflight: JsonObject,
    effective_brand_source: str,
    effective_brand_kit: Optional[JsonObject],
) -> JsonObject:
    preflight_operations = (
        preflight.get("brand_ref_operations", [])
        + preflight.get("token_operations", [])
        + preflight.get("layout_operations", [])
    )
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "document_id": document["id"],
        "status": "failed" if has_error_diagnostics(diagnostics) else "applied",
        "document": document_summary(document),
        "operation_application": {
            "applied_operations": 0,
            "preflight_operations": len(preflight_operations),
        },
        "operations": operation_summaries(preflight_operations),
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
        "preflight": {
            "has_errors": preflight.get("has_errors", False),
            "brand_ref_operations": len(preflight.get("brand_ref_operations", [])),
            "token_operations": len(preflight.get("token_operations", [])),
            "layout_operations": len(preflight.get("layout_operations", [])),
        },
        "brand_kit": {
            "source": effective_brand_source,
            "id": effective_brand_kit.get("id") if effective_brand_kit else None,
            "version": effective_brand_kit.get("version") if effective_brand_kit else None,
            "name": effective_brand_kit.get("name") if effective_brand_kit else None,
        },
    }


def finalize_dto(
    document: JsonObject,
    revision: JsonObject,
    diagnostics: List[JsonObject],
    operation: JsonObject,
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "document_id": document["id"],
        "status": "applied",
        "document": document_summary(document),
        "template_revision": template_revision_summary(revision),
        "operation_application": {
            "applied_operations": 1,
            "preflight_operations": 0,
        },
        "operations": operation_summaries([operation]),
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
    }


def snapshot_summary(snapshot: JsonObject) -> JsonObject:
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "document_id": snapshot["document_id"],
        "version": snapshot["version"],
        "reason": snapshot["reason"],
        "scene_counts": scene_counts(snapshot["scene"]),
        "created_at": snapshot["created_at"],
    }


def template_revision_summary(revision: JsonObject) -> JsonObject:
    return {
        "template_revision_id": revision["template_revision_id"],
        "document_id": revision["document_id"],
        "source_snapshot_id": revision["source_snapshot_id"],
        "version": revision["version"],
        "export_profile_count": len(revision.get("export_profiles", [])),
        "slot_count": len(revision.get("slot_summary", [])),
        "brand_ref": revision.get("brand_ref"),
        "scene_counts": scene_counts(revision["scene"]),
        "created_at": revision["created_at"],
    }


def operation_summaries(operations: Iterable[JsonObject]) -> List[JsonObject]:
    return [
        {"sequence": index, "kind": operation.get("kind", "unknown")}
        for index, operation in enumerate(operations, start=1)
    ]


def diagnostics_response(
    document_id: str,
    kind: Optional[str],
    diagnostics: List[JsonObject],
    created_at: Optional[str],
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "document_id": document_id,
        "kind": kind,
        "diagnostics": diagnostics,
        "views": diagnostic_views(diagnostics, diagnostics),
        "created_at": created_at,
    }


def diagnostic_views(
    audit: List[JsonObject], current: Optional[List[JsonObject]] = None
) -> JsonObject:
    audit_dtos = [diagnostic_dto(diagnostic) for diagnostic in audit]
    current_dtos = [diagnostic_dto(diagnostic) for diagnostic in (current or [])]
    return {
        "audit": audit_dtos,
        "current": current_dtos,
        "latest": latest_diagnostics(audit_dtos),
    }


def diagnostic_dto(diagnostic: JsonObject) -> JsonObject:
    return {
        "source": diagnostic.get("source", "engine"),
        "severity": diagnostic.get("severity"),
        "phase": diagnostic.get("phase"),
        "code": diagnostic.get("code"),
        "message": diagnostic.get("message"),
        "subject": diagnostic.get("subject"),
        "hint": diagnostic.get("hint"),
        "line": diagnostic.get("line"),
        "column": diagnostic.get("column"),
    }


def latest_diagnostics(audit: List[JsonObject]) -> List[JsonObject]:
    latest_by_key: Dict[str, JsonObject] = {}
    for diagnostic in audit:
        latest_by_key[diagnostic_key(diagnostic)] = diagnostic
    return list(latest_by_key.values())


def diagnostic_key(diagnostic: JsonObject) -> str:
    return ":".join(
        [
            str(diagnostic.get("source")),
            str(diagnostic.get("severity")),
            str(diagnostic.get("code")),
            json.dumps(diagnostic.get("subject"), sort_keys=True),
            str(diagnostic.get("line") or 0),
            str(diagnostic.get("column") or 0),
        ]
    )


def scene_counts(scene: JsonObject) -> JsonObject:
    return {
        "pages": len(scene.get("pages", {})),
        "nodes": len(scene.get("nodes", {})),
        "slots": len(scene.get("slots", {})),
        "export_profiles": len(scene.get("export_profiles", [])),
    }


def has_error_diagnostics(diagnostics: List[JsonObject]) -> bool:
    return any(diagnostic.get("severity") == "error" for diagnostic in diagnostics)
