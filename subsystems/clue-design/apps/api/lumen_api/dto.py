from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


JsonObject = Dict[str, Any]
DTO_SCHEMA_VERSION = 1


def document_summary(document: JsonObject) -> JsonObject:
    # A WebDoc or a site has no `meta` wrapper, so it can't share the scene reader —
    # branch on the stored kind rather than sniffing the payload.
    if document.get("doc_kind") == "site":
        return site_document_summary(document)
    if document.get("doc_kind") == "web":
        return web_document_summary(document)
    scene = document["scene"]
    return {
        "id": document["id"],
        "title": document["title"],
        "status": document["status"],
        "doc_kind": document.get("doc_kind", "scene"),
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


def web_document_summary(document: JsonObject) -> JsonObject:
    web_doc = document["scene"]
    theme = web_doc.get("theme") or {}
    return {
        "id": document["id"],
        "title": document["title"],
        "status": document["status"],
        "doc_kind": "web",
        "current_version": document["current_version"],
        # Constants — a WebDoc carries no meta.artifact_type/medium.
        "artifact_type": "website",
        "medium": "web",
        "brand_kit": theme.get("brand_kit"),
        "effective_brand_kit": {
            "source": document.get("effective_brand_kit_source"),
            "id": document.get("effective_brand_kit_id"),
            "version": document.get("effective_brand_kit_version"),
            "mode": document.get("effective_brand_mode"),
        },
        "counts": web_doc_counts(web_doc),
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
    }


def site_document_summary(document: JsonObject) -> JsonObject:
    site = document["scene"]
    theme = site.get("theme") or {}
    pages = site.get("pages") or {}
    return {
        "id": document["id"],
        "title": document["title"],
        "status": document["status"],
        "doc_kind": "site",
        "current_version": document["current_version"],
        "artifact_type": "website",
        "medium": "web",
        "brand_kit": theme.get("brand_kit"),
        "effective_brand_kit": {
            "source": document.get("effective_brand_kit_source"),
            "id": document.get("effective_brand_kit_id"),
            "version": document.get("effective_brand_kit_version"),
            "mode": document.get("effective_brand_mode"),
        },
        "counts": {
            "pages": len(pages),
            "sections": sum(len((p or {}).get("content") or []) for p in pages.values()),
        },
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
        "brand_summary": record.get("brand_summary") or {},
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
    bake: Optional[JsonObject] = None,
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
        # K1.6(b): present only when freeze_layout was requested and the
        # preflight was clean — raw scene + raw operations for the editor's
        # accept envelope (the summaries above are display-only).
        **({"bake": bake} if bake is not None else {}),
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


def web_doc_counts(web_doc: JsonObject) -> JsonObject:
    # A WebDoc's pages are a list (each with its own node arena); it has no
    # slots or export_profiles. Same key set as scene_counts so consumers of
    # `counts` never special-case the kind.
    pages = web_doc.get("pages", [])
    return {
        "pages": len(pages),
        "nodes": sum(len(page.get("nodes", {})) for page in pages),
        "slots": 0,
        "assets": len(web_doc.get("assets", {})),
        "export_profiles": 0,
    }


def has_error_diagnostics(diagnostics: List[JsonObject]) -> bool:
    return any(diagnostic.get("severity") == "error" for diagnostic in diagnostics)


def ingestion_job_website_url(job: JsonObject) -> Optional[str]:
    """The website a ``kind == "website"`` job was submitted for — the ONE request field the
    public view names (brand-kit slice 4).

    Why it is safe to surface: it is the workspace's own submitted URL, and every ingestion
    route is workspace-scoped, so this tells a workspace something it already told us. Why it is
    needed: a workspace whose first-time auto-ingestion FAILED has no kit to re-extract from, so
    its failed job is the only record of which site to retry — the Brand-context page's manual
    Re-extract has nothing to send without it. Non-website kinds carry no URL and answer None
    (a PDF/asset job's request holds filenames and staged digests, which stay unpublished).
    """
    if job.get("kind") != "website":
        return None
    url = (job.get("request") or {}).get("url")
    return url if isinstance(url, str) and url else None


def ingestion_job_outcome(job: JsonObject) -> JsonObject | None:
    """The job's bounded top-level outcome summary, or ``None`` when it has none.

    W5/R2-C. The evidence BODY stays private — it holds staged digests and, for the ad-assets
    lane, an entire harvest report — but a caller polling this job the documented way still has
    to be able to tell a working lane from an inert one. `succeeded` alone could not: an empty
    harvest, a distillation skipped for a missing key, and a fully populated lane all landed on
    the same green row, with the difference buried under `evidence.steps`.

    So exactly one bounded, machine-readable member is lifted out — never the body. Only the
    ad-assets lane composes one today (see `ad_library.onboarding._outcome`); the three older
    kinds carry no `outcome` key and this stays ``None`` for them, so their DTO gains a field
    and loses nothing.
    """
    evidence = job.get("evidence")
    if not isinstance(evidence, dict):
        return None
    outcome = evidence.get("outcome")
    return outcome if isinstance(outcome, dict) else None


def ingestion_job_resolution(job: JsonObject) -> JsonObject | None:
    """The job's bounded advertiser-resolution provenance, or ``None`` when it has none.

    W5/R3-A. The acceptance report's minimum ask, in as many words: "surface the resolved
    `page_id` + `advertiser_name` in the job DTO". Before this, an operator polling the
    documented endpoint could not see WHICH LinkedIn page had been harvested — so a job that
    fetched a stranger's page (apollo.io resolving to 107285417 instead of 18511550) was
    indistinguishable from a brand that simply has no ads, and stayed that way for two rounds
    of testing.

    Bounded and machine-readable, lifted out of the evidence exactly as
    :func:`ingestion_job_outcome` is, and never the evidence body itself. Only the ad-assets
    lane composes one; the three older kinds carry no `resolution` key and this stays ``None``.
    """
    evidence = job.get("evidence")
    if not isinstance(evidence, dict):
        return None
    resolution = evidence.get("resolution")
    return resolution if isinstance(resolution, dict) else None


def ingestion_job_gaps(job: JsonObject) -> list[JsonObject]:
    evidence = job.get("evidence")
    gaps = evidence.get("gaps") if isinstance(evidence, dict) else None
    return [gap for gap in gaps if isinstance(gap, dict)] if isinstance(gaps, list) else []


def ingestion_job_dto(job: JsonObject) -> JsonObject:
    """Public view of an ingestion job row (no request/evidence bodies — one named URL, one
    bounded outcome summary and one bounded resolution block apart, see
    :func:`ingestion_job_website_url`, :func:`ingestion_job_outcome` and
    :func:`ingestion_job_resolution`)."""
    return {
        "job_id": job["job_id"],
        "kind": job["kind"],
        "status": job["status"],
        "stage": job.get("stage"),
        "progress": job.get("progress"),
        "outcome": ingestion_job_outcome(job),
        "asset_analysis": (job.get("evidence") or {}).get("description_progress")
            or ((job.get("evidence") or {}).get("steps") or {}).get("enrich")
            or ((job.get("error") or {}).get("progress"))
            or ((job.get("evidence") or {}) if job.get("kind") == "asset_enrichment" else None),
        "resolution": ingestion_job_resolution(job),
        # What a finished job did without (spec 2026-10-25 §5.1); ``[]`` for a clean or
        # unfinished one. Its presence is what makes ``succeeded_with_gaps`` the status.
        "gaps": ingestion_job_gaps(job),
        "website_url": ingestion_job_website_url(job),
        "brand_kit_id": job.get("brand_kit_id"),
        "brand_kit_version": job.get("brand_kit_version"),
        "error": job.get("error"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }
