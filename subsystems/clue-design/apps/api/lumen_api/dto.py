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
            "mode": document.get("effective_brand_mode"),
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


def brand_kit_summary(record: JsonObject) -> JsonObject:
    brand_kit = record["brand_kit"]
    summary = record.get("brand_summary") or {}
    return {
        "id": record["brand_kit_id"],
        "version": record["version"],
        "name": record["name"],
        "approval_status": record.get("approval_status"),
        "product_ready": record.get("product_ready", False),
        "source": record.get("source"),
        "description": brand_kit.get("description"),
        "default_mode": brand_kit.get("default_mode"),
        "modes": summary.get("modes"),
        "tokens": summary.get("tokens"),
        "assets": summary.get("assets"),
        "authoring_rules": summary.get("authoring_rules", []),
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def brand_kit_created_dto(
    record: JsonObject, diagnostics: List[JsonObject]
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "status": "created",
        "brand_kit": brand_kit_summary(record),
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
    }


def brand_kit_detail_dto(record: JsonObject) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "brand_kit": brand_kit_summary(record),
        "brand_kit_json": record["brand_kit"],
        "diagnostics": diagnostic_views(record.get("diagnostics", [])),
    }


def brand_kit_validation_dto(
    brand_kit: JsonObject,
    diagnostics: List[JsonObject],
    product_ready: bool,
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "status": "failed" if has_error_diagnostics(diagnostics) else "ok",
        "brand_kit": {
            "id": brand_kit.get("id"),
            "version": brand_kit.get("version"),
            "name": brand_kit.get("name"),
            "approval_status": brand_kit.get("approval_status"),
        },
        "validation": {
            "product_ready": product_ready,
            "has_errors": has_error_diagnostics(diagnostics),
        },
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
    }


def brand_kit_generation_dto(
    record: Optional[JsonObject],
    brand_kit: JsonObject,
    brand_summary: Optional[JsonObject],
    generation: JsonObject,
    diagnostics: List[JsonObject],
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "status": "created" if record else "generated",
        "brand_kit": brand_kit_summary(record)
        if record
        else generated_brand_kit_summary(brand_kit, brand_summary),
        "brand_kit_json": brand_kit,
        "brand_generation": generation,
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
    }


def brand_compatibility_dto(
    report: JsonObject,
    diagnostics: List[JsonObject],
    stored_report: Optional[JsonObject] = None,
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "status": "failed" if has_error_diagnostics(diagnostics) else "ok",
        "report": report,
        "stored_report": stored_report,
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
    }


def brand_governance_dto(
    document: JsonObject,
    brand_kit: JsonObject,
    diagnostics: List[JsonObject],
    strictness: str,
) -> JsonObject:
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "document": document_summary(document),
        "status": "failed" if has_error_diagnostics(diagnostics) else "ok",
        "brand_kit": {
            "id": brand_kit.get("id"),
            "version": brand_kit.get("version"),
            "name": brand_kit.get("name"),
        },
        "governance": {
            "strictness": strictness,
            "has_errors": has_error_diagnostics(diagnostics),
        },
        "diagnostics": diagnostic_views(diagnostics, diagnostics),
    }


def generated_brand_kit_summary(
    brand_kit: JsonObject, brand_summary: Optional[JsonObject]
) -> JsonObject:
    summary = brand_summary or {}
    return {
        "id": brand_kit.get("id"),
        "version": brand_kit.get("version"),
        "name": brand_kit.get("name"),
        "approval_status": brand_kit.get("approval_status"),
        "product_ready": summary.get("product_ready", False),
        "source": "generated",
        "description": brand_kit.get("description"),
        "default_mode": brand_kit.get("default_mode"),
        "modes": summary.get("modes"),
        "tokens": summary.get("tokens"),
        "assets": summary.get("assets"),
        "authoring_rules": summary.get("authoring_rules", []),
        "created_at": None,
        "updated_at": None,
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
            "mode": document.get("effective_brand_mode"),
        },
    }


def preflight_preview_dto(
    scene: JsonObject,
    diagnostics: List[JsonObject],
    preflight: JsonObject,
    effective_brand_source: str,
    effective_brand_kit: Optional[JsonObject],
    mode: Optional[JsonObject],
) -> JsonObject:
    preflight_operations = (
        preflight.get("brand_ref_operations", [])
        + preflight.get("token_operations", [])
        + preflight.get("layout_operations", [])
    )
    meta = scene.get("meta", {})
    document = {
        "id": meta.get("id", "preview_document"),
        "title": meta.get("title", "Preview document"),
        "status": meta.get("status", {"kind": "draft"}),
        "current_version": None,
        "artifact_type": meta.get("artifact_type"),
        "medium": meta.get("medium"),
        "brand_kit": meta.get("brand_kit"),
        "effective_brand_kit": {
            "source": effective_brand_source,
            "id": effective_brand_kit.get("id") if effective_brand_kit else None,
            "version": effective_brand_kit.get("version") if effective_brand_kit else None,
            "mode": mode,
        },
        "counts": scene_counts(scene),
        "created_at": None,
        "updated_at": None,
    }
    return {
        "schema_version": DTO_SCHEMA_VERSION,
        "status": "failed" if has_error_diagnostics(diagnostics) else "applied",
        "document": document,
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
            "mode": mode,
        },
        "scene": scene,
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
        "assets": len(scene.get("assets", {})),
        "export_profiles": len(scene.get("export_profiles", [])),
    }


def has_error_diagnostics(diagnostics: List[JsonObject]) -> bool:
    return any(diagnostic.get("severity") == "error" for diagnostic in diagnostics)
