from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .core import CoreClient, CoreError, has_error_diagnostics
from .database import NotFoundError, Repository, connect, run_migrations
from .dto import (
    brand_compatibility_dto,
    brand_governance_dto,
    brand_kit_created_dto,
    brand_kit_detail_dto,
    brand_kit_generation_dto,
    brand_kit_summary,
    brand_kit_validation_dto,
    diagnostic_views,
    diagnostics_response,
    document_created_dto,
    finalize_dto,
    operation_application_dto,
    preflight_dto,
    scene_replaced_dto,
    snapshot_summary,
)
from .models import (
    AttachBrandKitRequest,
    ApplyOperationsRequest,
    AssetMetadataRequest,
    BrandCompatibilityRequest,
    CompileStylesBrandKitRequest,
    CreateDocumentRequest,
    CreateBrandKitRequest,
    CreateSnapshotRequest,
    FinalizeTemplateRequest,
    GenerateBrandKitRequest,
    PreflightRequest,
    ReplaceSceneRequest,
    ValidateBrandKitRequest,
    ValidateDocumentBrandGovernanceRequest,
)


JsonObject = Dict[str, Any]


def create_app(database_path: Optional[Path] = None, migrate: bool = True) -> FastAPI:
    app = FastAPI(title="ABM Design Engine Persistence API")
    app.state.database_path = database_path or Path(
        os.environ.get("LUMEN_API_DATABASE_PATH", "apps/api/lumen-api.sqlite3")
    )
    app.state.core = CoreClient()
    if migrate:
        run_migrations(app.state.database_path)

    @app.exception_handler(NotFoundError)
    def not_found_handler(_request: Request, error: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": not_found_detail(error)})

    def repository() -> Repository:
        connection = connect(app.state.database_path)
        try:
            yield Repository(connection)
        finally:
            connection.close()

    @app.post("/brand-kits")
    def create_brand_kit(
        payload: CreateBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        try:
            validation = app.state.core.validate_brand_kit(
                payload.brand_kit, product_ready=payload.product_ready
            )
            brand_kit = validation["brand_kit"]
            summary_response = app.state.core.summarize_brand_kit(
                brand_kit, raise_on_error=False
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = summary_response.get("diagnostics") or validation.get(
            "diagnostics", []
        )
        try:
            record = repo.create_brand_kit(
                brand_kit,
                summary_response.get("brand_summary") or {},
                diagnostics,
                payload.source,
            )
        except sqlite3.IntegrityError as error:
            raise duplicate_brand_kit_error(brand_kit) from error
        return brand_kit_created_dto(record, diagnostics)

    @app.post("/brand-kits/generate")
    def generate_brand_kit(
        payload: GenerateBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        try:
            result = app.state.core.generate_brand_kit(payload.seed)
        except CoreError as error:
            raise core_http_error(error) from error

        brand_kit = result["brand_kit"]
        diagnostics = result.get("diagnostics", [])
        record = None
        if payload.persist:
            try:
                record = repo.create_brand_kit(
                    brand_kit,
                    result.get("brand_summary") or {},
                    diagnostics,
                    "generated",
                )
            except sqlite3.IntegrityError as error:
                raise duplicate_brand_kit_error(brand_kit) from error
        return brand_kit_generation_dto(
            record,
            brand_kit,
            result.get("brand_summary"),
            result.get("brand_generation") or {},
            diagnostics,
        )

    @app.post("/brand-kits/compile-styles")
    def compile_styles_brand_kit(
        payload: CompileStylesBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        try:
            result = app.state.core.compile_styles_brand_kit(
                payload.source,
                payload.brand_kit_id,
                payload.version,
                payload.name,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        brand_kit = result["brand_kit"]
        diagnostics = result.get("diagnostics", [])
        record = None
        if payload.persist:
            try:
                record = repo.create_brand_kit(
                    brand_kit,
                    result.get("brand_summary") or {},
                    diagnostics,
                    "styles",
                )
            except sqlite3.IntegrityError as error:
                raise duplicate_brand_kit_error(brand_kit) from error
        return brand_kit_generation_dto(
            record,
            brand_kit,
            result.get("brand_summary"),
            {},
            diagnostics,
        )

    @app.post("/brand-kits/validate")
    def validate_brand_kit(
        payload: ValidateBrandKitRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        brand_kit = resolve_brand_kit_payload(
            repo,
            payload.brand_kit,
            payload.brand_kit_id,
            payload.version,
        )
        try:
            result = app.state.core.validate_brand_kit(
                brand_kit,
                product_ready=payload.product_ready,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error
        return brand_kit_validation_dto(
            brand_kit,
            result.get("diagnostics", []),
            payload.product_ready,
        )

    @app.post("/brand-kits/compatibility")
    def compare_brand_kit_compatibility(
        payload: BrandCompatibilityRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        from_brand_kit, from_record = resolve_brand_kit_for_compatibility(
            repo, payload.from_brand_kit, payload.from_ref
        )
        to_brand_kit, to_record = resolve_brand_kit_for_compatibility(
            repo, payload.to_brand_kit, payload.to_ref
        )
        try:
            result = app.state.core.compare_brand_kit_compatibility(
                from_brand_kit, to_brand_kit, raise_on_error=False
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        stored_report = None
        if payload.persist_report and from_record is not None and to_record is not None:
            stored_report = repo.create_brand_compatibility_report(
                new_id("brand_report"),
                from_record["brand_kit"],
                to_record["brand_kit"],
                result.get("brand_compatibility") or {},
                diagnostics,
            )
        return brand_compatibility_dto(
            result.get("brand_compatibility") or {},
            diagnostics,
            stored_report,
        )

    @app.get("/brand-kits")
    def list_brand_kits(
        all_versions: bool = Query(default=False),
        repo: Repository = Depends(repository),
    ) -> List[JsonObject]:
        return [
            brand_kit_summary(record)
            for record in repo.list_brand_kits(all_versions=all_versions)
        ]

    @app.get("/brand-kits/{brand_kit_id}")
    def get_latest_brand_kit(
        brand_kit_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return brand_kit_detail_dto(repo.require_brand_kit(brand_kit_id))

    @app.get("/brand-kits/{brand_kit_id}/versions/{version}")
    def get_brand_kit_version(
        brand_kit_id: str, version: int, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return brand_kit_detail_dto(repo.require_brand_kit(brand_kit_id, version))

    @app.get("/brand-compatibility-reports/{report_id}")
    def get_brand_compatibility_report(
        report_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_brand_compatibility_report(report_id)

    @app.post("/documents")
    def create_document(
        payload: CreateDocumentRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        document_id = payload.document_id or new_id("doc")
        try:
            if payload.scene is None:
                scene = app.state.core.new_scene(
                    document_id,
                    payload.title,
                    payload.artifact_type,
                    payload.medium,
                )
            else:
                scene = payload.scene
                scene.setdefault("meta", {})["id"] = scene.get("meta", {}).get(
                    "id", document_id
                )
                validation = app.state.core.validate_scene(scene)
                if has_error_diagnostics(validation.get("diagnostics", [])):
                    diagnostics = validation.get("diagnostics", [])
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "scene.validation_failed",
                            "diagnostics": diagnostics,
                            "views": diagnostic_views(diagnostics, diagnostics),
                        },
                    )
                scene = validation["scene"]
                reject_finalized_scene_status(scene)

            if scene["meta"]["id"] != document_id:
                document_id = scene["meta"]["id"]
            document = repo.create_document(
                scene,
                brand_kit=payload.brand_kit,
                effective_brand_source="document" if payload.brand_kit else None,
            )
            return document_created_dto(document)
        except CoreError as error:
            raise core_http_error(error) from error

    @app.get("/documents/{document_id}")
    def get_document(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return public_document(require_document(repo, document_id))

    @app.put("/documents/{document_id}/scene")
    def replace_scene(
        document_id: str,
        payload: ReplaceSceneRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "replace the current scene")
        try:
            validation = app.state.core.validate_scene(payload.scene)
        except CoreError as error:
            raise core_http_error(error) from error
        diagnostics = validation.get("diagnostics", [])
        if has_error_diagnostics(diagnostics):
            repo.store_diagnostics(document_id, "structural", diagnostics)
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "scene.validation_failed",
                    "diagnostics": diagnostics,
                    "views": diagnostic_views(diagnostics, diagnostics),
                },
            )
        scene = validation["scene"]
        reject_finalized_scene_status(scene)
        if scene["meta"]["id"] != document_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "scene.document_id_mismatch",
                    "message": "scene.meta.id must match the route document id",
                },
            )
        document = repo.replace_scene(document_id, scene, diagnostics)
        return scene_replaced_dto(document, diagnostics)

    @app.post("/documents/{document_id}/operations")
    def apply_operations(
        document_id: str,
        payload: ApplyOperationsRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        if not payload.operations:
            raise HTTPException(
                status_code=422,
                detail={"code": "operations.empty", "message": "operations cannot be empty"},
            )
        document = require_document(repo, document_id)
        require_draft_document(document, "apply operations")
        try:
            result = app.state.core.apply_operations(
                document["scene"], payload.operations
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        updated = repo.update_document_state(
            document_id,
            result["scene"],
            diagnostics,
            payload.operations,
            payload.source,
            payload.actor.kind,
            payload.actor.id,
            "structural",
            effective_brand=None,
        )
        snapshot = None
        if payload.snapshot_reason:
            snapshot = repo.create_snapshot(
                document_id, new_id("snap"), payload.snapshot_reason
            )
        return operation_application_dto(
            updated,
            result.get("applied_operations", 0),
            payload.operations,
            diagnostics,
            snapshot,
        )

    @app.get("/documents/{document_id}/operations")
    def list_operations(
        document_id: str, repo: Repository = Depends(repository)
    ) -> List[JsonObject]:
        return repo.list_operations(document_id)

    @app.post("/documents/{document_id}/snapshots")
    def create_snapshot(
        document_id: str,
        payload: CreateSnapshotRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        require_document(repo, document_id)
        snapshot = repo.create_snapshot(
            document_id, payload.snapshot_id or new_id("snap"), payload.reason
        )
        return {
            "schema_version": 1,
            "status": "created",
            "snapshot": snapshot_summary(snapshot),
        }

    @app.get("/documents/{document_id}/snapshots")
    def list_snapshots(
        document_id: str, repo: Repository = Depends(repository)
    ) -> List[JsonObject]:
        return [snapshot_summary(snapshot) for snapshot in repo.list_snapshots(document_id)]

    @app.get("/documents/{document_id}/snapshots/{snapshot_id}")
    def get_snapshot(
        document_id: str, snapshot_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_snapshot(document_id, snapshot_id)

    @app.post("/documents/{document_id}/preflight")
    def preflight_document(
        document_id: str,
        payload: PreflightRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "preflight the current scene")
        try:
            source, brand_kit = choose_effective_brand(app.state.core, repo, document, payload)
            mode = choose_effective_brand_mode(document, brand_kit, payload.mode)
            result = app.state.core.preflight_scene(document["scene"], brand_kit, mode)
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        preflight = result.get("preflight") or {}
        operations = (
            preflight.get("brand_ref_operations", [])
            + preflight.get("token_operations", [])
            + preflight.get("layout_operations", [])
        )
        updated_document = document
        if not has_error_diagnostics(diagnostics):
            effective = (
                (source, brand_kit, mode)
                if payload.persist_effective_brand or source in {"platform_default", "none"}
                else None
            )
            updated_document = repo.update_document_state(
                document_id,
                result["scene"],
                diagnostics,
                operations,
                "system",
                "system",
                "preflight",
                "preflight",
                effective_brand=effective,
            )
        else:
            repo.store_diagnostics(document_id, "preflight", diagnostics)

        return preflight_dto(
            updated_document,
            diagnostics,
            preflight,
            source,
            brand_kit,
        )

    @app.post("/documents/{document_id}/brand-kit")
    def attach_brand_kit_to_document(
        document_id: str,
        payload: AttachBrandKitRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "attach a Brand Kit")
        record = repo.require_brand_kit(payload.brand_kit_id, payload.version)
        brand_kit = record["brand_kit"]
        mode = choose_effective_brand_mode(document, brand_kit, payload.mode)
        operation = update_document_brand_operation(document["scene"], brand_kit, mode)
        try:
            result = app.state.core.apply_operations(document["scene"], [operation])
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        updated = repo.update_document_state(
            document_id,
            result["scene"],
            diagnostics,
            [operation],
            "api",
            payload.actor.kind,
            payload.actor.id,
            "structural",
            effective_brand=("brand_kit_library", brand_kit, mode),
        )
        snapshot = None
        if payload.snapshot_reason:
            snapshot = repo.create_snapshot(
                document_id, new_id("snap"), payload.snapshot_reason
            )
        return operation_application_dto(
            updated,
            result.get("applied_operations", 0),
            [operation],
            diagnostics,
            snapshot,
        )

    @app.post("/documents/{document_id}/brand-governance")
    def validate_document_brand_governance(
        document_id: str,
        payload: ValidateDocumentBrandGovernanceRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        brand_kit = resolve_document_governance_brand(repo, document, payload)
        try:
            result = app.state.core.validate_scene_brand_governance(
                document["scene"],
                brand_kit,
                strictness=payload.strictness,
                raise_on_error=False,
            )
        except CoreError as error:
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        repo.store_diagnostics(document_id, "brand_governance", diagnostics)
        return brand_governance_dto(
            document,
            brand_kit,
            diagnostics,
            payload.strictness,
        )

    @app.post("/documents/{document_id}/finalize")
    def finalize_document(
        document_id: str,
        payload: FinalizeTemplateRequest,
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        document = require_document(repo, document_id)
        require_draft_document(document, "finalize the document")
        source_snapshot_id = payload.snapshot_id
        scene = document["scene"]
        if source_snapshot_id:
            scene = repo.require_snapshot(document_id, source_snapshot_id)["scene"]
        template_revision_id = payload.template_revision_id or new_id("tmpl")

        try:
            result = app.state.core.finalize_template(scene, template_revision_id)
        except CoreError as error:
            repo.store_diagnostics(document_id, "finalize", diagnostics_from_core_error(error))
            raise core_http_error(error) from error

        diagnostics = result.get("diagnostics", [])
        finalized_scene = result["scene"]
        revision = repo.create_template_revision(
            document_id,
            template_revision_id,
            source_snapshot_id,
            finalized_scene,
            slot_summary(finalized_scene),
        )
        operation = {
            "kind": "finalize_template",
            "template_revision_id": template_revision_id,
        }
        updated = repo.update_document_state(
            document_id,
            finalized_scene,
            diagnostics,
            [operation],
            "system",
            payload.actor.kind,
            payload.actor.id,
            "finalize",
            effective_brand=None,
        )
        return finalize_dto(updated, revision, diagnostics, operation)

    @app.get("/template-revisions/{template_revision_id}")
    def get_template_revision(
        template_revision_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_template_revision(template_revision_id)

    @app.post("/asset-metadata")
    def create_asset_metadata(
        payload: AssetMetadataRequest, repo: Repository = Depends(repository)
    ) -> JsonObject:
        data = (
            payload.model_dump()
            if hasattr(payload, "model_dump")
            else payload.dict()
        )
        data["asset_id"] = data["asset_id"] or new_id("asset")
        if data.get("document_id"):
            require_document(repo, data["document_id"])
        return repo.create_asset_metadata(data)

    @app.get("/asset-metadata/{asset_id}")
    def get_asset_metadata(
        asset_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        return repo.require_asset_metadata(asset_id)

    @app.get("/documents/{document_id}/summary")
    def get_summary(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        scene = document["scene"]
        return {
            "document": {
                "id": document["id"],
                "title": document["title"],
                "status": document["status"],
                "current_version": document["current_version"],
                "artifact_type": scene.get("meta", {}).get("artifact_type"),
                "medium": scene.get("meta", {}).get("medium"),
                "brand_kit": scene.get("meta", {}).get("brand_kit"),
            },
            "pages": page_summary(scene),
            "nodes": node_summary(scene),
            "slots": slot_summary(scene),
            "export_profiles": scene.get("export_profiles", []),
        }

    @app.get("/documents/{document_id}/slots")
    def get_slots(
        document_id: str, repo: Repository = Depends(repository)
    ) -> List[JsonObject]:
        document = require_document(repo, document_id)
        return slot_summary(document["scene"])

    @app.get("/documents/{document_id}/geometry")
    def get_geometry(
        document_id: str, repo: Repository = Depends(repository)
    ) -> JsonObject:
        document = require_document(repo, document_id)
        scene = document["scene"]
        return {
            "document_id": document_id,
            "geometry": computed_geometry(scene),
            "pages": page_summary(scene),
        }

    @app.get("/documents/{document_id}/diagnostics")
    def get_diagnostics(
        document_id: str,
        kind: Optional[str] = Query(default=None),
        repo: Repository = Depends(repository),
    ) -> JsonObject:
        latest = repo.latest_diagnostics(document_id, kind)
        if latest:
            return diagnostics_response(
                latest["document_id"],
                latest["kind"],
                latest["diagnostics"],
                latest["created_at"],
            )
        return diagnostics_response(document_id, kind, [], None)

    return app


app = create_app()


def require_document(repo: Repository, document_id: str) -> JsonObject:
    try:
        return repo.require_document(document_id)
    except NotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=not_found_detail(error),
        ) from error


def not_found_detail(error: NotFoundError) -> JsonObject:
    return {
        "code": f"{error.resource_type}.not_found",
        "message": str(error),
        "resource_id": error.resource_id,
    }


def require_draft_document(document: JsonObject, action: str) -> None:
    if is_finalized_document(document):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document.finalized",
                "message": (
                    f"cannot {action} because document {document['id']} is finalized; "
                    "create a new draft revision before mutating it"
                ),
            },
        )


def reject_finalized_scene_status(scene: JsonObject) -> None:
    if is_finalized_scene(scene):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "scene.finalized_status_forbidden",
                "message": (
                    "scene replacement cannot set finalized status; use "
                    "POST /documents/{id}/finalize so core finalization and "
                    "template revision persistence stay in sync"
                ),
            },
        )


def is_finalized_document(document: JsonObject) -> bool:
    return document.get("status") == "finalized" or is_finalized_scene(
        document.get("scene", {})
    )


def is_finalized_scene(scene: JsonObject) -> bool:
    return scene_status_kind(scene) == "finalized"


def scene_status_kind(scene: JsonObject) -> str:
    status = scene.get("meta", {}).get("status", {})
    if isinstance(status, dict):
        return str(status.get("kind", "draft"))
    return str(status)


def public_document(document: JsonObject) -> JsonObject:
    return {
        key: value
        for key, value in document.items()
        if key != "brand_kit"
    }


def duplicate_brand_kit_error(brand_kit: JsonObject) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "brand_kit.version_exists",
            "message": (
                f"Brand Kit {brand_kit.get('id')} version "
                f"{brand_kit.get('version')} already exists"
            ),
            "brand_kit_id": brand_kit.get("id"),
            "version": brand_kit.get("version"),
        },
    )


def resolve_brand_kit_payload(
    repo: Repository,
    brand_kit: Optional[JsonObject],
    brand_kit_id: Optional[str],
    version: Optional[int],
) -> JsonObject:
    if brand_kit is not None and brand_kit_id is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "brand_kit.ambiguous_source",
                "message": "provide either an inline Brand Kit or a stored Brand Kit reference, not both",
            },
        )
    if brand_kit is not None:
        return brand_kit
    if brand_kit_id is not None:
        return repo.require_brand_kit(brand_kit_id, version)["brand_kit"]
    raise HTTPException(
        status_code=422,
        detail={
            "code": "brand_kit.missing",
            "message": "provide brand_kit or brand_kit_id",
        },
    )


def resolve_brand_kit_for_compatibility(
    repo: Repository,
    brand_kit: Optional[JsonObject],
    brand_ref: Optional[Any],
) -> Tuple[JsonObject, Optional[JsonObject]]:
    if brand_kit is not None and brand_ref is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "brand_kit.ambiguous_source",
                "message": "provide either an inline Brand Kit or a stored Brand Kit reference, not both",
            },
        )
    if brand_kit is not None:
        return brand_kit, None
    if brand_ref is not None:
        record = repo.require_brand_kit(brand_ref.brand_kit_id, brand_ref.version)
        return record["brand_kit"], record
    raise HTTPException(
        status_code=422,
        detail={
            "code": "brand_kit.missing",
            "message": "provide an inline Brand Kit or a stored Brand Kit reference",
        },
    )


def resolve_document_governance_brand(
    repo: Repository,
    document: JsonObject,
    payload: ValidateDocumentBrandGovernanceRequest,
) -> JsonObject:
    if payload.brand_kit is not None or payload.brand_kit_id is not None:
        return resolve_brand_kit_payload(
            repo,
            payload.brand_kit,
            payload.brand_kit_id,
            payload.version,
        )
    if document.get("brand_kit") is not None:
        return document["brand_kit"]
    raise HTTPException(
        status_code=422,
        detail={
            "code": "brand_kit.missing",
            "message": "attach a Brand Kit to the document or pass one in the request",
        },
    )


def update_document_brand_operation(
    scene: JsonObject,
    brand_kit: JsonObject,
    mode: Optional[JsonObject],
) -> JsonObject:
    return {
        "kind": "update_document",
        "patch": {
            "title": {"kind": "unchanged"},
            "artifact_type": {"kind": "unchanged"},
            "medium": medium_patch_from_mode(scene, mode),
            "brand_kit": {
                "kind": "set",
                "value": {"id": brand_kit["id"], "version": brand_kit["version"]},
            },
        },
    }


def medium_patch_from_mode(scene: JsonObject, mode: Optional[JsonObject]) -> JsonObject:
    medium = selected_medium(mode)
    if medium is None or medium == scene.get("meta", {}).get("medium"):
        return {"kind": "unchanged"}
    return {"kind": "set", "value": medium}


def selected_medium(mode: Optional[JsonObject]) -> Optional[str]:
    if not mode:
        return None
    values = mode.get("values") if isinstance(mode.get("values"), dict) else mode
    medium = values.get("medium") if isinstance(values, dict) else None
    return str(medium) if medium else None


def choose_effective_brand_mode(
    document: JsonObject,
    brand_kit: Optional[JsonObject],
    requested_mode: Optional[JsonObject],
) -> Optional[JsonObject]:
    if brand_kit is None:
        return None

    values: JsonObject = {}
    modes = brand_kit.get("modes") if isinstance(brand_kit.get("modes"), dict) else {}
    defaults = modes.get("defaults") if isinstance(modes.get("defaults"), dict) else {}
    values.update({str(axis): str(value) for axis, value in defaults.items()})

    stored_mode = document.get("effective_brand_mode")
    stored_values = mode_values(stored_mode)
    values.update(stored_values)

    requested_values = mode_values(requested_mode)
    values.update(requested_values)

    if "medium" not in requested_values:
        scene_medium = scene_medium_mode_value(document["scene"])
        if scene_medium:
            values["medium"] = scene_medium

    return {"values": values}


def mode_values(mode: Optional[JsonObject]) -> JsonObject:
    if not mode:
        return {}
    values = mode.get("values") if isinstance(mode.get("values"), dict) else mode
    if not isinstance(values, dict):
        return {}
    return {str(axis): str(value) for axis, value in values.items() if value is not None}


def scene_medium_mode_value(scene: JsonObject) -> Optional[str]:
    medium = scene.get("meta", {}).get("medium")
    if medium in {"print", "direct_mail"}:
        return "print"
    if medium in {"digital", "email", "ad"}:
        return "digital"
    return None


def choose_effective_brand(
    core: CoreClient,
    repo: Repository,
    document: JsonObject,
    payload: PreflightRequest,
) -> Tuple[str, Optional[JsonObject]]:
    if payload.brand_kit is not None:
        return "request", payload.brand_kit
    if payload.brand_kit_id is not None:
        return (
            "brand_kit_library",
            repo.require_brand_kit(payload.brand_kit_id, payload.brand_kit_version)[
                "brand_kit"
            ],
        )
    if document.get("brand_kit") is not None:
        return "document", document["brand_kit"]
    if payload.generated_default_brand_kit is not None:
        return "generated_default", payload.generated_default_brand_kit
    if payload.strict_no_fallback:
        return "none", None
    return "platform_default", core.platform_default_brand_kit()


def core_http_error(error: CoreError) -> HTTPException:
    diagnostics = diagnostics_from_core_error(error)
    return HTTPException(
        status_code=422,
        detail={
            "code": error.code,
            "message": error.message,
            "diagnostics": diagnostics,
            "views": diagnostic_views(diagnostics, diagnostics),
        },
    )


def diagnostics_from_core_error(error: CoreError) -> List[JsonObject]:
    if error.diagnostics:
        return error.diagnostics
    return [
        {
            "severity": "error",
            "phase": "operation",
            "code": error.code,
            "message": error.message,
            "subject": None,
            "hint": None,
        }
    ]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def parent_map(scene: JsonObject) -> Dict[str, JsonObject]:
    parents: Dict[str, JsonObject] = {}
    for page_id, page in scene.get("pages", {}).items():
        for child_id in page.get("children", []):
            parents[child_id] = {"kind": "page", "id": page_id}
    for node_id, node in scene.get("nodes", {}).items():
        for child_id in node.get("children", []):
            parents[child_id] = {"kind": "node", "id": node_id}
    return parents


def page_summary(scene: JsonObject) -> List[JsonObject]:
    return [
        {
            "id": page_id,
            "name": page.get("name"),
            "size": page.get("size"),
            "child_count": len(page.get("children", [])),
            "children": page.get("children", []),
        }
        for page_id, page in scene.get("pages", {}).items()
    ]


def node_summary(scene: JsonObject) -> List[JsonObject]:
    parents = parent_map(scene)
    slots_by_node: Dict[str, List[str]] = {}
    for slot in scene.get("slots", {}).values():
        for node_id in slot.get("bound_nodes", []):
            slots_by_node.setdefault(node_id, []).append(slot.get("key"))

    return [
        {
            "id": node_id,
            "name": node.get("name"),
            "kind": node.get("kind", {}).get("kind"),
            "parent": parents.get(node_id),
            "child_count": len(node.get("children", [])),
            "slot_keys": slots_by_node.get(node_id, []),
            "locked": node.get("locked", False),
            "has_computed_geometry": node.get("computed") is not None,
        }
        for node_id, node in scene.get("nodes", {}).items()
    ]


def slot_summary(scene: JsonObject) -> List[JsonObject]:
    return [
        {
            "id": slot_id,
            "key": slot.get("key"),
            "label": slot.get("label"),
            "content_type": slot.get("content_type"),
            "required": slot.get("required"),
            "scope": slot.get("scope"),
            "bound_nodes": slot.get("bound_nodes", []),
            "overflow": slot.get("overflow"),
            "editability": slot.get("editability"),
        }
        for slot_id, slot in scene.get("slots", {}).items()
    ]


def computed_geometry(scene: JsonObject) -> Dict[str, JsonObject]:
    return {
        node_id: node["computed"]
        for node_id, node in scene.get("nodes", {}).items()
        if node.get("computed") is not None
    }
