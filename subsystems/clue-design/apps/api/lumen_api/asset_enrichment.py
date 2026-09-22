"""Asset custody/enrichment composition: atomic upload offers and retryable fleet execution."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from clue_design import assets, descriptions, ingestion
from clue_design.asset_context import PROMPT_VERSION, SCHEMA_VERSION, AssetOverrides, fingerprint
from clue_design.envelopes import DesignIngestionEnvelope
from clue_design.enums import DesignIngestionKind
from clue_design.errors import DesignJobFencedError
from lumen_ingestion.jobs import IngestionJobStore, create_and_offer
from py_lumen_config import settings
from sqlalchemy import text

from .design_store import DesignStoreBridge, HybridRepository


class UploadKeyConflict(ValueError):
    pass


def register_upload(workspace_id: str, record: dict, enrichment: dict) -> dict:
    """Called only by the governed registry tool; bytes already have durable custody."""
    bridge = DesignStoreBridge(workspace_id)

    async def write(conn):
        key = enrichment["idempotency_key"]
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"asset-upload:{workspace_id}:{key}"},
        )
        existing = (
            await conn.execute(
                text("""
            SELECT * FROM design_asset_upload_request WHERE workspace_id = :w AND idempotency_key = :key
        """),
                {"w": workspace_id, "key": key},
            )
        ).first()
        if existing:
            if existing.request_digest != enrichment["request_digest"]:
                raise UploadKeyConflict(
                    "This upload key was already used with different file or metadata"
                )
            return await assets.get_asset_record(
                conn, workspace_id=workspace_id, asset_id=existing.asset_id
            )
        stored = await assets.create_asset_record(conn, workspace_id=workspace_id, record=record)
        asset_id = record["id"]
        overrides = AssetOverrides.model_validate(enrichment.get("overrides", {})).model_dump(
            exclude_none=True, exclude_unset=True
        )
        if overrides:
            await descriptions.patch_overrides(
                conn, workspace_id=workspace_id, asset_id=asset_id, values=overrides
            )
        job_id = ingestion.new_id("ingest")
        work_id = uuid4()
        occurrence = {
            "source": "user_upload",
            "brand_kit_id": enrichment.get("brand_kit_id"),
            "user_note": overrides.get("user_note"),
            "occurrence_id": fingerprint({"workspace": workspace_id, "upload": key}),
        }
        # An explicit association must name an existing kit in this workspace.
        if occurrence["brand_kit_id"]:
            from clue_design import brand

            await brand.get_brand_kit(
                conn, workspace_id=workspace_id, brand_kit_id=occurrence["brand_kit_id"]
            )
        request = {"targets": {asset_id: {"source_occurrences": [occurrence]}}}
        envelope = DesignIngestionEnvelope(
            work_id=work_id,
            workspace_id=workspace_id,
            kind="ingestion",
            job_id=job_id,
            ingestion_kind=DesignIngestionKind.ASSET_ENRICHMENT,
        )
        await create_and_offer(
            conn,
            workspace_id=workspace_id,
            kind="asset_enrichment",
            request=request,
            job_id=job_id,
            work_id=work_id,
            envelope=envelope.model_dump(mode="json"),
        )
        await descriptions.prepare_analysis(
            conn,
            workspace_id=workspace_id,
            asset_id=asset_id,
            analysis_input={
                "source_occurrences": [occurrence],
                "model": settings.lumen_ingestion_describe_model,
                "schema_version": SCHEMA_VERSION,
                "prompt_version": PROMPT_VERSION,
            },
            job_id=job_id,
        )
        await conn.execute(
            text("""
            INSERT INTO design_asset_upload_request
              (workspace_id, idempotency_key, request_digest, asset_id, job_id)
            VALUES (:w, :key, :digest, :a, :job)
        """),
            {
                "w": workspace_id,
                "key": key,
                "digest": enrichment["request_digest"],
                "a": asset_id,
                "job": job_id,
            },
        )
        return stored

    return bridge._run(write)


def offer_retry(
    workspace_id: str,
    request: dict,
    *,
    job_id: str,
    work_id: UUID,
    envelope: dict,
    priority: int = 0,
) -> dict:
    bridge = DesignStoreBridge(workspace_id)

    async def write(conn):
        targets = request["targets"]
        if not targets or len(targets) > 200:
            raise ValueError("An enrichment retry must name between 1 and 200 assets")
        for asset_id in targets:
            await assets.get_asset_record(conn, workspace_id=workspace_id, asset_id=asset_id)
        job = await create_and_offer(
            conn,
            workspace_id=workspace_id,
            kind="asset_enrichment",
            request=request,
            job_id=job_id,
            work_id=work_id,
            envelope=envelope,
            priority=priority,
        )
        for asset_id in targets:
            row = await descriptions._locked(conn, workspace_id, asset_id)
            if row.analysis_status in {"queued", "analyzing"}:
                raise ValueError("An analysis is already queued or running for this asset")
            await conn.execute(
                text("""
                UPDATE design_asset_description SET analysis_status = 'queued',
                  analysis_job_id = :job, analysis_token = NULL, updated_at = now()
                WHERE workspace_id = :w AND asset_id = :a
            """),
                {"w": workspace_id, "a": asset_id, "job": job_id},
            )
        return job

    return bridge._run(write)


def run_asset_enrichment(
    engine_cache_dir: str,
    job_id: str,
    *,
    workspace_id: str,
    storage: Any = None,
    expected_generation: int | None = None,
) -> None:
    from lumen_api.design_store import DesignBlobStore
    from lumen_ingestion.asset_enrichment import enrich_assets
    from lumen_ingestion.pipeline import (
        _make_rasterize_svg,
        _make_resolve_bytes,
        _make_resolve_thumbnail_bytes,
        resolve_describer,
    )
    from clue_storage import storage_from_settings

    store = IngestionJobStore(workspace_id=workspace_id, expected_generation=expected_generation)
    repo = HybridRepository(workspace_id=workspace_id)
    blobs = DesignBlobStore(storage or storage_from_settings(), workspace_id)
    try:
        store.set_running(job_id)
        request = store.require(job_id)["request"]
        summary = enrich_assets(
            request["targets"],
            workspace_id=workspace_id,
            describer=resolve_describer(),
            resolve_bytes=_make_resolve_bytes(repo, blobs),
            resolve_thumbnail=_make_resolve_thumbnail_bytes(repo, blobs),
            rasterize_svg=_make_rasterize_svg(repo, blobs, engine_cache_dir),
            reporter=lambda stage, progress: store.set_stage(job_id, stage, progress),
            job_id=job_id,
        )
        counts = {key: value for key, value in summary.items() if key != "results"}
        if summary["ready"] != summary["total"]:
            store.fail(
                job_id,
                {
                    "code": "asset_enrichment.partial",
                    "message": "Some assets remain unanalyzed",
                    "progress": counts,
                },
            )
        else:
            store.complete(job_id, None, None, json.dumps(counts))
    except DesignJobFencedError:
        return
    except Exception as error:
        try:
            store.fail(job_id, {"code": "asset_enrichment.failed", "message": str(error)[:500]})
        except DesignJobFencedError:
            return
