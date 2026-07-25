"""Raw-SQL persistence for C3 ingestion jobs and segments."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import decode_jsonb, serialize_value_json
from clue_core.ingestion import (
    IngestionJobId,
    IngestionSegmentId,
    IngestionStatus,
    new_ingestion_job_id,
    new_ingestion_segment_id,
)
from clue_research.ingestion.models import (
    DeclaredMaterialContext,
    IngestionFailureCode,
    IngestionJob,
    IngestionResultRefs,
    IngestionSegment,
)
from clue_storage import ArtifactRecord

_JOB_COLUMNS = (
    "id, workspace_id, brand_id, product_id, project_id, artifact_key, content_sha256, "
    "declared_context_json, declared_context_hash, media_type, adapter_key, status, failure_code, "
    "failure_detail, segment_count, claim_refs_json, retry_count, created_by_actor, created_at, "
    "updated_at, completed_at, erased_at"
)
_SEGMENT_COLUMNS = (
    "id, ingestion_job_id, ordinal, locator_json, text_sha256, canonical_artifact_key, created_at"
)


def declared_context_hash(context: DeclaredMaterialContext) -> str:
    payload = json.dumps(
        context.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _job(row: Mapping[str, object]) -> IngestionJob:
    return IngestionJob(
        id=IngestionJobId(row["id"]),  # type: ignore[arg-type]
        workspace_id=str(row["workspace_id"]),
        brand_id=str(row["brand_id"]),
        product_id=str(row["product_id"]) if row["product_id"] is not None else None,
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        artifact_key=str(row["artifact_key"]),
        content_sha256=str(row["content_sha256"]),
        declared_context=DeclaredMaterialContext.model_validate(
            decode_jsonb(row["declared_context_json"])
        ),
        declared_context_hash=str(row["declared_context_hash"]),
        media_type=str(row["media_type"]),
        adapter_key=str(row["adapter_key"]),
        status=IngestionStatus(str(row["status"])),
        failure_code=(
            IngestionFailureCode(str(row["failure_code"]))
            if row["failure_code"] is not None
            else None
        ),
        failure_detail=str(row["failure_detail"]) if row["failure_detail"] is not None else None,
        segment_count=int(cast(int, row["segment_count"])),
        result_refs=IngestionResultRefs.model_validate(decode_jsonb(row["claim_refs_json"]) or {}),
        retry_count=int(cast(int, row["retry_count"])),
        created_by_actor=str(row["created_by_actor"]),
        created_at=row["created_at"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
        completed_at=row["completed_at"],  # type: ignore[arg-type]
        erased_at=row["erased_at"],  # type: ignore[arg-type]
    )


def _segment(row: Mapping[str, object]) -> IngestionSegment:
    return IngestionSegment(
        id=IngestionSegmentId(row["id"]),  # type: ignore[arg-type]
        ingestion_job_id=IngestionJobId(row["ingestion_job_id"]),  # type: ignore[arg-type]
        ordinal=int(cast(int, row["ordinal"])),
        locator=decode_jsonb(row["locator_json"]) or {},
        text_sha256=str(row["text_sha256"]),
        canonical_artifact_key=str(row["canonical_artifact_key"]),
        created_at=row["created_at"],  # type: ignore[arg-type]
    )


async def create_or_get_job(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    artifact: ArtifactRecord,
    context: DeclaredMaterialContext,
    adapter_key: str,
    actor: str,
) -> IngestionJob:
    context_hash = declared_context_hash(context)
    job_id = new_ingestion_job_id()
    result = await conn.execute(
        text(
            """
            INSERT INTO ingestion_job
                (id, workspace_id, brand_id, product_id, project_id, artifact_key,
                 content_sha256, declared_context_json, declared_context_hash, media_type,
                 adapter_key, created_by_actor)
            VALUES
                (:id, :workspace_id, :brand_id, :product_id, :project_id, :artifact_key,
                 :content_sha256, CAST(:context AS jsonb), :context_hash, :media_type,
                 :adapter_key, :actor)
            ON CONFLICT (workspace_id, content_sha256, declared_context_hash)
                WHERE erased_at IS NULL
            DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": job_id,
            "workspace_id": workspace_id,
            "brand_id": context.brand_id,
            "product_id": context.product_id,
            "project_id": context.project_id,
            "artifact_key": artifact.storage_key,
            "content_sha256": artifact.content_sha256,
            "context": serialize_value_json(context.model_dump(mode="json")),
            "context_hash": context_hash,
            "media_type": artifact.media_type,
            "adapter_key": adapter_key,
            "actor": actor,
        },
    )
    resolved_id = result.scalar_one_or_none()
    if resolved_id is None:
        found = await conn.execute(
            text(
                f"SELECT {_JOB_COLUMNS} FROM ingestion_job "
                "WHERE workspace_id = :workspace_id AND content_sha256 = :content_sha256 "
                "AND declared_context_hash = :context_hash AND erased_at IS NULL"
            ),
            {
                "workspace_id": workspace_id,
                "content_sha256": artifact.content_sha256,
                "context_hash": context_hash,
            },
        )
    else:
        found = await conn.execute(
            text(f"SELECT {_JOB_COLUMNS} FROM ingestion_job WHERE id = :id"),
            {"id": resolved_id},
        )
    return _job(dict(found.mappings().one()))


async def get_job(
    conn: AsyncConnection,
    job_id: IngestionJobId,
    *,
    workspace_id: str,
    for_update: bool = False,
) -> IngestionJob | None:
    lock = " FOR UPDATE" if for_update else ""
    result = await conn.execute(
        text(
            f"SELECT {_JOB_COLUMNS} FROM ingestion_job "
            f"WHERE id = :id AND workspace_id = :workspace_id{lock}"
        ),
        {"id": job_id, "workspace_id": workspace_id},
    )
    row = result.mappings().first()
    return _job(dict(row)) if row is not None else None


async def list_segments(
    conn: AsyncConnection, job_id: IngestionJobId, *, workspace_id: str
) -> tuple[IngestionSegment, ...]:
    result = await conn.execute(
        text(
            f"SELECT s.{_SEGMENT_COLUMNS.replace(', ', ', s.')} "
            "FROM ingestion_segment AS s JOIN ingestion_job AS j ON j.id = s.ingestion_job_id "
            "WHERE s.ingestion_job_id = :job_id AND j.workspace_id = :workspace_id "
            "AND j.erased_at IS NULL ORDER BY s.ordinal"
        ),
        {"job_id": job_id, "workspace_id": workspace_id},
    )
    return tuple(_segment(dict(row)) for row in result.mappings().all())


async def artifact_has_live_ingestion_ref(conn: AsyncConnection, storage_key: str) -> bool:
    """Lock an artifact and report whether another live C3 job/segment still cites it."""
    await conn.execute(
        text("SELECT storage_key FROM artifact WHERE storage_key = :key FOR UPDATE"),
        {"key": storage_key},
    )
    result = await conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM ingestion_job
                WHERE artifact_key = :key AND erased_at IS NULL
                UNION ALL
                SELECT 1
                FROM ingestion_segment AS segment
                JOIN ingestion_job AS job ON job.id = segment.ingestion_job_id
                WHERE segment.canonical_artifact_key = :key AND job.erased_at IS NULL
            )
            """
        ),
        {"key": storage_key},
    )
    return bool(result.scalar_one())


async def replace_segments(
    conn: AsyncConnection,
    *,
    job_id: IngestionJobId,
    segments: tuple[tuple[int, dict[str, object], str, str], ...],
) -> tuple[IngestionSegmentId, ...]:
    """Replace only a pre-claim segment set; callers hold the job row lock."""
    await conn.execute(
        text("DELETE FROM ingestion_segment WHERE ingestion_job_id = :job_id"),
        {"job_id": job_id},
    )
    ids: list[IngestionSegmentId] = []
    for ordinal, locator, text_sha256, canonical_key in segments:
        segment_id = new_ingestion_segment_id()
        await conn.execute(
            text(
                """
                INSERT INTO ingestion_segment
                    (id, ingestion_job_id, ordinal, locator_json, text_sha256,
                     canonical_artifact_key)
                VALUES
                    (:id, :job_id, :ordinal, CAST(:locator AS jsonb), :text_sha256,
                     :canonical_key)
                """
            ),
            {
                "id": segment_id,
                "job_id": job_id,
                "ordinal": ordinal,
                "locator": serialize_value_json(locator),
                "text_sha256": text_sha256,
                "canonical_key": canonical_key,
            },
        )
        ids.append(segment_id)
    await conn.execute(
        text(
            "UPDATE ingestion_job SET status = 'snapshotted', segment_count = :count, "
            "failure_code = NULL, failure_detail = NULL, updated_at = now() WHERE id = :id"
        ),
        {"id": job_id, "count": len(ids)},
    )
    return tuple(ids)


async def mark_extracting(conn: AsyncConnection, job_id: IngestionJobId) -> None:
    await conn.execute(
        text(
            "UPDATE ingestion_job SET status = 'extracting', updated_at = now() "
            "WHERE id = :id AND status IN ('snapshotted', 'extracting')"
        ),
        {"id": job_id},
    )


async def complete_job(
    conn: AsyncConnection, job_id: IngestionJobId, refs: IngestionResultRefs
) -> None:
    await conn.execute(
        text(
            "UPDATE ingestion_job SET status = 'completed', "
            "claim_refs_json = CAST(:refs AS jsonb), "
            "completed_at = now(), updated_at = now(), failure_code = NULL, failure_detail = NULL "
            "WHERE id = :id"
        ),
        {"id": job_id, "refs": serialize_value_json(refs.model_dump(mode="json"))},
    )


async def fail_job(
    conn: AsyncConnection,
    job_id: IngestionJobId,
    *,
    code: IngestionFailureCode,
    detail: str,
) -> None:
    await conn.execute(
        text(
            "UPDATE ingestion_job SET status = 'failed', failure_code = :code, "
            "failure_detail = :detail, updated_at = now() WHERE id = :id AND erased_at IS NULL"
        ),
        {"id": job_id, "code": code.value, "detail": detail[:500]},
    )


async def increment_retry(
    conn: AsyncConnection, job_id: IngestionJobId, *, workspace_id: str
) -> IngestionJob | None:
    result = await conn.execute(
        text(
            f"UPDATE ingestion_job SET retry_count = retry_count + 1, "
            "status = CASE WHEN EXISTS (SELECT 1 FROM ingestion_segment s "
            "WHERE s.ingestion_job_id = ingestion_job.id) THEN 'snapshotted'::ingestion_status "
            "ELSE 'queued'::ingestion_status END, updated_at = now(), "
            "failure_code = NULL, failure_detail = NULL "
            "WHERE id = :id AND workspace_id = :workspace_id AND status = 'failed' "
            f"RETURNING {_JOB_COLUMNS}"
        ),
        {"id": job_id, "workspace_id": workspace_id},
    )
    row = result.mappings().first()
    return _job(dict(row)) if row is not None else None


async def mark_erased(conn: AsyncConnection, job_id: IngestionJobId, *, workspace_id: str) -> bool:
    result = await conn.execute(
        text(
            "UPDATE ingestion_job SET status = 'erased', erased_at = COALESCE(erased_at, now()), "
            "failure_detail = NULL, claim_refs_json = '{}'::jsonb, updated_at = now() "
            "WHERE id = :id AND workspace_id = :workspace_id AND erased_at IS NULL"
        ),
        {"id": job_id, "workspace_id": workspace_id},
    )
    if result.rowcount:
        await conn.execute(
            text("DELETE FROM ingestion_segment WHERE ingestion_job_id = :id"), {"id": job_id}
        )
    return bool(result.rowcount)
