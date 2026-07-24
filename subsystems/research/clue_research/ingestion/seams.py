"""Injected routing seams for C3 outputs and integration-owned claim scope."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clue_core import Claim, ClaimDraft, ClaimId, FieldDef, RunId
from clue_core.ingestion import IngestionJobId, IngestionSegmentId
from clue_research.ingestion.models import (
    DeclaredMaterialContext,
    IngestionJob,
    IngestionTarget,
)


@runtime_checkable
class ClaimConstructionRoute(Protocol):
    """Construct a born-correct claim across the temporary C3/C4 contract boundary."""

    def build(
        self,
        *,
        job: IngestionJob,
        target: IngestionTarget,
        field: FieldDef,
        draft: ClaimDraft,
        segment_id: str,
        canonical_key: str,
        run_id: RunId,
    ) -> Claim: ...


@runtime_checkable
class ProposalSink(Protocol):
    """Idempotent by ``(job_id, target)`` so a crash-safe retry cannot duplicate a proposal."""

    async def preserve_unmapped(
        self,
        *,
        job_id: IngestionJobId,
        segment_ids: tuple[IngestionSegmentId, ...],
        target: IngestionTarget,
    ) -> str: ...


@runtime_checkable
class MemoryRoute(Protocol):
    """Idempotent by ``job_id`` and segment refs."""

    async def write_from_segments(
        self,
        *,
        job_id: IngestionJobId,
        segment_ids: tuple[IngestionSegmentId, ...],
        context: DeclaredMaterialContext,
    ) -> tuple[str, ...]: ...


@runtime_checkable
class ProjectStateRoute(Protocol):
    """Idempotent by ``job_id`` and segment refs."""

    async def write_from_segments(
        self,
        *,
        job_id: IngestionJobId,
        segment_ids: tuple[IngestionSegmentId, ...],
        context: DeclaredMaterialContext,
    ) -> tuple[str, ...]: ...


@runtime_checkable
class ClaimErasureRoute(Protocol):
    """Idempotent claim tombstoning delegated to the existing compliance/DSAR authority."""

    async def erase_claims(self, *, workspace_id: str, claim_ids: tuple[ClaimId, ...]) -> None: ...
