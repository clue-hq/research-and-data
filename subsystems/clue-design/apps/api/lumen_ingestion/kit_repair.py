"""The ``kit_repair`` ingestion job: heal a brand kit an outage left incomplete (spec 2026-10-25).

A workspace repair (``clue_api.workspace_ops``) plans what is missing and offers ONE job of this
kind. Its request names exactly that plan::

    {"targets": {"<asset_id>": {}}, "republish_brand_kit_id": "<id>" | null,
     "offer_card": bool, "actor": "...", "reason": "...", "operation_id": "<uuid>"}

and the job does three things, in order:

1. **Describe the planned assets as one batch.** The same ``enrich_assets`` a normal ingestion
   runs: inside a coordinator job it fans out one child task per asset to the analysis pool, so
   357 assets take minutes, not one-job-per-asset hours.
2. **Republish the kit with the descriptions stamped**, through the same step the
   ``describe-assets`` backfill route runs, with an inactive describer: it only stamps what step 1
   (or anything before it) already described. Nothing changed means no new version, so a
   re-driven job never publishes twice.
3. **Re-offer a missing ad-DNA card** from the existing harvest (``retry=True``), never
   re-harvesting.

What is still missing afterwards is listed as the evidence ``gaps``, which makes the job
``succeeded_with_gaps`` rather than ``succeeded``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Optional

from lumen_api.design_store import DesignBlobStore, HybridRepository
from py_lumen_obs import get_logger

from . import pipeline
from .ad_library import auto_card
from .asset_enrichment import enrich_assets
from .jobs import IngestionJobStore, StageReporter, run_ingestion_job
from .kit_republish import republish_kit_with_descriptions

JsonObject = dict[str, Any]

logger = get_logger("lumen_ingestion.kit_repair")

__all__ = ["run_kit_repair"]

#: Stamps only what is already described; never makes a vision call of its own.
_STAMP_ONLY = SimpleNamespace(active=False)


def run_kit_repair(
    engine_cache_dir: str,
    job_id: str,
    *,
    workspace_id: str,
    storage: Any = None,
    expected_generation: Optional[int] = None,
) -> None:
    """Drive one ``kit_repair`` job to a terminal row. Never raises (``run_ingestion_job``)."""
    from clue_storage import storage_from_settings

    storage = storage or storage_from_settings()
    store = IngestionJobStore(workspace_id=workspace_id, expected_generation=expected_generation)
    repo = HybridRepository(workspace_id=workspace_id)
    blobs = DesignBlobStore(storage, workspace_id)

    def publish(kit: JsonObject, summary: JsonObject, diagnostics: list, base: int) -> JsonObject:
        ref = pipeline._worker_design_tools(storage).invoke(
            "design_publish_brand_kit_version",
            {
                "brand_kit": kit,
                "brand_summary": summary,
                "diagnostics": diagnostics,
                "source": "manual",
                "expected_base_version": base,
            },
            workspace_id=workspace_id,
            actor="agent",
        ).references
        return repo.require_brand_kit(ref["brand_kit_id"], ref["version"])

    def work(report: StageReporter) -> tuple[Optional[str], Optional[int], Optional[str]]:
        request = store.require(job_id)["request"]
        evidence: JsonObject = {
            "phase": "kit_repair",
            "actor": request.get("actor"),
            "reason": request.get("reason"),
            "operation_id": request.get("operation_id"),
        }
        gaps: list[JsonObject] = []
        targets = request.get("targets") or {}
        if targets:
            summary = enrich_assets(
                targets,
                workspace_id=workspace_id,
                describer=pipeline.resolve_describer(),
                resolve_bytes=pipeline._make_resolve_bytes(repo, blobs),
                resolve_thumbnail=pipeline._make_resolve_thumbnail_bytes(repo, blobs),
                rasterize_svg=pipeline._make_rasterize_svg(repo, blobs, engine_cache_dir),
                reporter=lambda stage, progress: report(stage, 0.8 * progress),
                job_id=job_id,
            )
            counts = {key: value for key, value in summary.items() if key != "results"}
            evidence["description_progress"] = counts
            missing = counts["total"] - counts["ready"] - counts.get("unsupported", 0)
            if missing > 0:
                gaps.append({"area": "descriptions", "failed": missing, "reason": "analysis failed"})

        kit_id: Optional[str] = request.get("republish_brand_kit_id")
        version: Optional[int] = None
        if kit_id:
            report("Republishing the brand kit with its descriptions", 0.85)
            result = republish_kit_with_descriptions(
                repo,
                brand_kit_id=kit_id,
                blobs=blobs,
                describer=_STAMP_ONLY,
                core=pipeline._core_client(),
                publish=publish,
                cache_dir=engine_cache_dir,
            )
            created = result["created"] or repo.require_brand_kit(kit_id)
            version = int(created["version"])
            evidence["republish"] = {"published": result["published"], "counts": result["counts"]}

        if request.get("offer_card"):
            report("Offering the ad-DNA card", 0.95)
            evidence["card_job_id"] = auto_card.offer_card_if_ready(
                workspace_id, tools=pipeline._worker_design_tools(storage), retry=True
            )
        evidence["gaps"] = gaps
        logger.info("kit_repair.done", job_id=job_id, workspace_id=workspace_id, gaps=len(gaps))
        return kit_id, version, json.dumps(evidence)

    run_ingestion_job(store, job_id, work)
