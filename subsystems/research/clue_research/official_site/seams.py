"""Injected C0 seams; implementations begin in C1/C3/C7, never in this contract slice."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from clue_research.official_site.contracts import (
    ArtifactRef,
    AttemptOutcome,
    ClaimNextRequest,
    ClaimPersistenceRequest,
    ClaimReconciliationRequest,
    CorpusCheckpointRef,
    CrawlLease,
    CrawlPhase,
    CrawlProgress,
    CrawlRunCreate,
    CrawlRunRef,
    CrawlRunStatus,
    DiscoveryBatch,
    DiscoveryBatchResult,
    FetchAttemptRef,
    LinkObservation,
    OfficialSiteMaterializationRequest,
    OfficialSiteMaterializationResult,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    PageSnapshotRef,
    PersistenceClaim,
    ProviderResultMetadata,
    ReclaimResult,
    ReconciliationClaim,
)


@runtime_checkable
class PageFetcher(Protocol):
    """One approved URL in, one typed acquisition result out; never recursive."""

    capabilities: PageFetcherCapabilities

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult: ...


@runtime_checkable
class CrawlRepository(Protocol):
    """PostgreSQL frontier/ledger authority expressed as transaction-sized operations."""

    async def create_or_get_run(self, request: CrawlRunCreate) -> CrawlRunRef: ...

    async def record_discoveries(self, batch: DiscoveryBatch) -> DiscoveryBatchResult: ...

    async def claim_next(self, request: ClaimNextRequest) -> CrawlLease | None: ...

    async def claim_reconciliation(
        self, request: ClaimReconciliationRequest
    ) -> ReconciliationClaim | None: ...

    async def claim_persistence(
        self, request: ClaimPersistenceRequest
    ) -> PersistenceClaim | None: ...

    async def renew_lease(self, lease: CrawlLease, *, lease_ttl_seconds: int) -> bool: ...

    async def begin_attempt(
        self, lease: CrawlLease, *, provider_key: str, operation_key: str
    ) -> FetchAttemptRef: ...

    async def mark_attempt_dispatched(
        self, lease: CrawlLease, attempt: FetchAttemptRef
    ) -> bool: ...

    async def record_provider_result(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        result: ProviderResultMetadata,
    ) -> bool: ...

    async def persist_snapshot(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        artifact: ArtifactRef,
        result: ProviderResultMetadata,
        outgoing_links: tuple[LinkObservation, ...],
    ) -> PageSnapshotRef | None: ...

    async def complete_page(self, lease: CrawlLease, *, snapshot_id: UUID) -> bool: ...

    async def disposition_attempt(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        outcome: AttemptOutcome,
    ) -> bool: ...

    async def reclaim_expired_leases(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> ReclaimResult: ...

    async def freeze_corpus_checkpoint(
        self, *, workspace_id: str, crawl_run_id: UUID, phase: CrawlPhase
    ) -> CorpusCheckpointRef: ...

    async def transition_run(
        self,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        expected: CrawlRunStatus,
        next_status: CrawlRunStatus,
    ) -> bool: ...

    async def read_progress(self, *, workspace_id: str, crawl_run_id: UUID) -> CrawlProgress: ...


@runtime_checkable
class OfficialSiteCorpusMaterializer(Protocol):
    """Materialize one immutable corpus checkpoint into claims and return references only."""

    async def materialize(
        self, request: OfficialSiteMaterializationRequest
    ) -> OfficialSiteMaterializationResult: ...


__all__ = ["CrawlRepository", "OfficialSiteCorpusMaterializer", "PageFetcher"]
