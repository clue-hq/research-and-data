"""Read-only C3 ingestion status projection."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from clue_core.ingestion import IngestionJobId, IngestionStatus
from clue_db import ConnFactory
from clue_research.ingestion import get_job


class IngestionStatusView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_job_id: IngestionJobId
    artifact_key: str
    media_type: str
    adapter_key: str
    status: IngestionStatus
    segment_count: int
    claim_count: int
    proposal_count: int
    retry_count: int
    failure_code: str | None = None
    progress: float


_PROGRESS = {
    IngestionStatus.QUEUED: 0.0,
    IngestionStatus.SNAPSHOTTED: 0.5,
    IngestionStatus.EXTRACTING: 0.75,
    IngestionStatus.COMPLETED: 1.0,
    IngestionStatus.FAILED: 0.0,
    IngestionStatus.ERASED: 1.0,
}


async def ingestion_status(
    *,
    conn_factory: ConnFactory,
    workspace_id: str,
    ingestion_job_id: IngestionJobId,
) -> IngestionStatusView | None:
    """Absent and foreign jobs both resolve to None; erased jobs have no serving reach."""
    async with conn_factory() as conn:
        job = await get_job(conn, ingestion_job_id, workspace_id=workspace_id)
    if job is None or job.status is IngestionStatus.ERASED:
        return None
    return IngestionStatusView(
        ingestion_job_id=job.id,
        artifact_key=job.artifact_key,
        media_type=job.media_type,
        adapter_key=job.adapter_key,
        status=job.status,
        segment_count=job.segment_count,
        claim_count=len(job.result_refs.claims),
        proposal_count=len(job.result_refs.proposals),
        retry_count=job.retry_count,
        failure_code=job.failure_code.value if job.failure_code is not None else None,
        progress=(
            0.5
            if job.status is IngestionStatus.FAILED and job.segment_count > 0
            else _PROGRESS[job.status]
        ),
    )


__all__ = ["IngestionStatusView", "ingestion_status"]
