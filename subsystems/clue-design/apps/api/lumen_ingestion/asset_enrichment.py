"""Continuous per-image enrichment inside the existing durable ingestion execution."""

from __future__ import annotations

import base64
import hashlib
import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import ContextVar, copy_context
from io import BytesIO
from typing import Any, Callable
from uuid import uuid4

from clue_design import descriptions
from clue_design.asset_context import PROMPT_VERSION, SCHEMA_VERSION, validate_analysis
from lumen_api.design_store import DesignStoreBridge
from py_lumen_config import settings


JOB_CONTEXT: ContextVar[tuple[str, int | None] | None] = ContextVar(
    "asset_enrichment_job", default=None
)
ASSET_WORK_CONTEXT: ContextVar[Any] = ContextVar("asset_work_context", default=None)


class EnrichmentStore:
    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self.bridge = DesignStoreBridge(workspace_id)

    def _run(self, call):
        async def guarded(conn):
            work = ASSET_WORK_CONTEXT.get()
            if work is not None:
                from lumen_api.ingestion_tasks import require_asset_lease

                await require_asset_lease(conn, work)
            context = JOB_CONTEXT.get()
            if context and context[1] is not None:
                from sqlalchemy import text
                from clue_design.errors import DesignJobFencedError

                row = (
                    await conn.execute(
                        text(
                            "SELECT lease_generation FROM design_ingestion_job "
                            "WHERE workspace_id = :w AND job_id = :j FOR SHARE"
                        ),
                        {"w": self.workspace_id, "j": context[0]},
                    )
                ).first()
                if row is None or (
                    row.lease_generation is not None and row.lease_generation > context[1]
                ):
                    raise DesignJobFencedError(
                        context[0], context[1], row.lease_generation if row else None
                    )
            return await call(conn)

        return self.bridge._run(guarded)

    def prepare(self, asset_id: str, inputs: dict, job_id: str | None) -> dict:
        return self._run(
            lambda conn: descriptions.prepare_analysis(
                conn,
                workspace_id=self.workspace_id,
                asset_id=asset_id,
                analysis_input=inputs,
                job_id=job_id,
            )
        )

    def begin(self, asset_id: str, fingerprint: str, token: str, job_id: str | None) -> bool:
        return self._run(
            lambda conn: descriptions.begin_analysis(
                conn,
                workspace_id=self.workspace_id,
                asset_id=asset_id,
                input_fingerprint=fingerprint,
                token=token,
                job_id=job_id,
            )
        )

    def finish(self, asset_id: str, token: str, **result: Any) -> bool:
        return self._run(
            lambda conn: descriptions.finish_analysis(
                conn,
                workspace_id=self.workspace_id,
                asset_id=asset_id,
                token=token,
                **result,
            )
        )

    def fail_queued(self, asset_ids: list[str], job_id: str, reason: str) -> None:
        self._run(
            lambda conn: descriptions.fail_queued_analysis(
                conn,
                workspace_id=self.workspace_id,
                asset_ids=asset_ids,
                job_id=job_id,
                reason=reason,
            )
        )

    def read(self, asset_id: str) -> dict:
        return self._run(
            lambda conn: descriptions.get_many(
                conn,
                workspace_id=self.workspace_id,
                asset_ids=[asset_id],
            )
        ).get(asset_id, {})


def enrich_assets(
    targets: dict[str, dict],
    *,
    workspace_id: str,
    describer: Any,
    resolve_bytes: Callable,
    reporter: Callable[[str, float], None],
    resolve_thumbnail: Callable | None = None,
    rasterize_svg: Callable | None = None,
    job_id: str | None = None,
    store: Any = None,
    concurrency: int | None = None,
) -> dict:
    """Each slot takes the next distinct asset immediately. Persist before reporting progress.

    The outer ingestion job is durable/reaped. Replaying reuses completed input fingerprints;
    missing previews and exhausted retries persist per-asset failures without losing custody.
    Context copies carry the existing spend/trace scope into every worker thread.
    """
    from .describe import DescribeItem, _downscale_preview, _vector_raster

    context = JOB_CONTEXT.get()
    if (
        store is None
        and context is not None
        and context[1] is not None
        and ASSET_WORK_CONTEXT.get() is None
    ):
        from lumen_api.ingestion_tasks import enqueue_and_collect

        return enqueue_and_collect(
            targets,
            workspace_id=workspace_id,
            job_id=context[0],
            generation=context[1],
            reporter=reporter,
        )

    store = store or EnrichmentStore(workspace_id)
    limit = concurrency or settings.lumen_ingestion_describe_concurrency
    if limit < 1:
        raise ValueError("description concurrency must be positive")
    summary: dict = {
        "total": len(targets),
        "ready": 0,
        "failed": 0,
        "unsupported": 0,
        "pending": 0,
        "cached": 0,
        "concurrency": limit,
        "results": {},
    }
    if not getattr(describer, "active", True):
        summary.update(
            status="partial",
            pending=len(targets),
            reason="Asset analysis is disabled or has no provider key",
        )
        if job_id and hasattr(store, "fail_queued"):
            store.fail_queued(list(targets), job_id, summary["reason"])
        reporter(f"Asset descriptions: 0/{len(targets)}; {summary['reason']}", 0.85)
        return summary

    def one(asset_id: str) -> tuple[str, dict, bool]:
        target = targets[asset_id]
        resolved = resolve_bytes(asset_id)
        preview = None
        preview_info: dict = {"policy": "first_frame", "transformations": []}
        original_digest = None
        mime = None
        reason = None
        if resolved is None:
            reason = "Original asset bytes are unavailable"
        else:
            data, mime = resolved
            original_digest = hashlib.sha256(data).hexdigest()
            if mime == "image/svg+xml":
                data = _vector_raster(asset_id, resolve_thumbnail, rasterize_svg)
                preview_info["transformations"].append("svg_raster_preview")
            if data:
                try:
                    from PIL import Image

                    with Image.open(BytesIO(data)) as image:
                        preview_info.update(
                            original_dimensions=list(image.size),
                            animated=bool(getattr(image, "is_animated", False)),
                        )
                        if preview_info["animated"]:
                            preview_info["transformations"].append("first_animation_frame_only")
                    preview = _downscale_preview(data)
                except Exception:
                    pass
            if not preview:
                reason = "No supported raster preview is available; original is retained"
        if preview:
            preview_info["digest"] = hashlib.sha256(base64.b64decode(preview)).hexdigest()
            preview_info["transformations"].append("downscaled_to_512px")
        inputs = {
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "model": getattr(describer, "model", settings.lumen_ingestion_describe_model),
            "original_digest": original_digest,
            "mime_type": mime,
            "preview": preview_info,
            "source_occurrences": target.get("source_occurrences", []),
        }
        row = store.prepare(asset_id, inputs, job_id)
        if row.get("status") == "ready":
            return asset_id, row, True
        token = uuid4().hex
        if not store.begin(asset_id, row["input_fingerprint"], token, job_id):
            return asset_id, store.read(asset_id), False
        if reason:
            status = "unsupported" if resolved is not None else "failed"
            store.finish(
                asset_id,
                token,
                status=status,
                diagnostic={"code": "preview_unavailable", "message": reason, "retryable": True},
            )
            return asset_id, store.read(asset_id), False
        item = DescribeItem(
            asset_id=asset_id,
            kind=target.get("kind", "image"),
            image_b64=preview,
            filename=target.get("filename"),
            context=json.dumps(
                {
                    "preview": preview_info,
                    "human_context": row["analysis_input"].get("human_context", {}),
                }
            ),
            source_occurrences=row["analysis_input"]["source_occurrences"],
        )
        # The provider wrapper owns HTTP retries; this second attempt is only schema/validation
        # recovery. A provider halt propagates its reason and never starts another paid call.
        completed_analysis = None
        for attempt in range(2):
            try:
                results = describer.describe([item])
                result = results[0] if results else None
                if result is None or not result.analysis:
                    raise ValueError(
                        getattr(describer, "last_failure_reason", None)
                        or "No valid structured asset analysis returned"
                    )
                completed_analysis = validate_analysis(result.analysis, item.source_occurrences)
                break
            except Exception as error:
                from clue_spend import ProviderHalted

                reason = f"{type(error).__name__}: {error}"[:500]
                if isinstance(error, ProviderHalted) or attempt == 1:
                    break
        if completed_analysis is not None:
            store.finish(asset_id, token, analysis=completed_analysis)
            return asset_id, store.read(asset_id), False
        store.finish(
            asset_id,
            token,
            status="failed",
            diagnostic={
                "code": "analysis_failed",
                "message": reason,
                "retryable": True,
            },
        )
        return asset_id, store.read(asset_id), False

    remaining = iter(targets)
    with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="asset-analysis") as pool:
        active = {}

        def submit() -> bool:
            asset_id = next(remaining, None)
            if asset_id is None:
                return False
            active[pool.submit(copy_context().run, one, asset_id)] = asset_id
            return True

        for _ in range(min(limit, len(targets))):
            submit()
        while active:
            completed, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in completed:
                asset_id = active.pop(future)
                try:
                    _, row, cached = future.result()
                except Exception as error:
                    # Store/custody errors cannot be counted as success. The durable parent
                    # records this diagnostic and can replay the same input without reupload.
                    row = {
                        "status": "failed",
                        "diagnostic": {
                            "code": "enrichment_storage_failed",
                            "message": str(error)[:500],
                            "retryable": True,
                        },
                    }
                    cached = False
                state = row.get("status")
                summary[state if state in {"ready", "failed", "unsupported"} else "pending"] += 1
                summary["cached"] += int(cached)
                summary["results"][asset_id] = row
                done = len(summary["results"])
                reporter(
                    f"Asset descriptions: {summary['ready']}/{len(targets)} ready; "
                    f"{summary['failed'] + summary['unsupported']} failed; "
                    f"{limit} concurrent request slots",
                    0.80 + 0.05 * done / max(1, len(targets)),
                )
                submit()
    summary["status"] = "ready" if summary["ready"] == summary["total"] else "partial"
    return summary
