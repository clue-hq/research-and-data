"""Shared Phase-C ingestion references and lifecycle vocabulary.

Only cross-package shapes live here.  The mutable job/segment row models remain in
``clue_research.ingestion`` as required by the C0 ownership treaty.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

IngestionJobId = NewType("IngestionJobId", UUID)
IngestionSegmentId = NewType("IngestionSegmentId", UUID)


def new_ingestion_job_id() -> IngestionJobId:
    return IngestionJobId(uuid4())


def new_ingestion_segment_id() -> IngestionSegmentId:
    return IngestionSegmentId(uuid4())


class IngestionStatus(StrEnum):
    """Durable lifecycle of one raw-material ingestion job."""

    QUEUED = "queued"
    SNAPSHOTTED = "snapshotted"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    ERASED = "erased"


class IngestionJobRef(BaseModel):
    """Reference-only result shared by tools, recipes, and projections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ingestion_job_id: IngestionJobId
    artifact_key: str
    status: IngestionStatus
