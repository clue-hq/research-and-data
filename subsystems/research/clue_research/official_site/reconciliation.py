"""Durable one-page acquisition and paid-call recovery orchestration (C4).

This module owns the attempt protocol, not crawl scheduling.  It invokes ``PageFetcher`` only for
a freshly prepared ordinary claim.  Persistence claims and reconciliation claims have separate
entry points whose types do not expose a fetch operation, preventing a recovery worker from
blindly repeating a possibly charged call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from clue_research.official_site.artifacts import (
    OfficialSiteArtifactStore,
    RetainedPageSuccess,
    sanitize_fetch_result,
)
from clue_research.official_site.contracts import (
    ArtifactRef,
    AttemptDisposition,
    AttemptOutcome,
    CrawlLease,
    CrawlPageState,
    FetchAttemptRef,
    FetchAttemptState,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    PageSnapshotRef,
    PersistenceClaim,
    ReconciliationClaim,
    RetryClass,
)
from clue_research.official_site.models import CrawlStateConflictError
from clue_research.official_site.seams import CrawlRepository, PageFetcher


class AcquisitionFenceLostError(RuntimeError):
    """The lease generation became stale before the result could be published."""


class AcquisitionPersistencePendingError(RuntimeError):
    """Provider I/O completed; retry only persistence with the retained result."""

    def __init__(
        self,
        *,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        retained_result: PageFetchResult,
    ) -> None:
        super().__init__(
            "provider result is recorded; retry artifact/snapshot persistence without fetching"
        )
        self.lease = lease
        self.attempt = attempt
        self.retained_result = retained_result


@dataclass(frozen=True, slots=True)
class DurableAcquisitionResult:
    attempt: FetchAttemptRef
    provider_result: PageFetchResult
    artifact: ArtifactRef | None = None
    snapshot: PageSnapshotRef | None = None

    @property
    def page_completed(self) -> bool:
        """A returned snapshot is published; failed completion raises before a result exists."""

        return self.snapshot is not None


@runtime_checkable
class ProviderOperationLookup(Protocol):
    """Receipt/status lookup for an already-dispatched operation; never a new acquisition."""

    capabilities: PageFetcherCapabilities

    async def lookup_operation(
        self,
        request: PageFetchRequest,
        *,
        provider_request_id: str | None,
    ) -> PageFetchResult: ...


class DurablePageAcquirer:
    """Execute one fenced attempt and its persistence/reconciliation recovery paths."""

    def __init__(
        self,
        *,
        repository: CrawlRepository,
        artifacts: OfficialSiteArtifactStore,
        fetcher: PageFetcher,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._fetcher = fetcher

    async def acquire(
        self, lease: CrawlLease, request: PageFetchRequest
    ) -> DurableAcquisitionResult:
        """Prepare, dispatch exactly once, record the result, and persist a successful page."""

        if request.requested_url != lease.requested_url:
            raise ValueError("fetch request URL must equal the leased representative URL")
        if request.operation_key == "":  # model validation normally makes this unreachable
            raise ValueError("operation key is required")
        attempt = await self._repository.begin_attempt(
            lease,
            provider_key=self._fetcher.capabilities.provider_key,
            operation_key=request.operation_key,
        )
        if not await self._repository.mark_attempt_dispatched(lease, attempt):
            raise AcquisitionFenceLostError("lease expired before provider dispatch")
        # Cancellation deliberately leaves the committed attempt at ``dispatched``. Expiry then
        # enters reconciliation/spend_unknown; it is never converted into a new provider call.
        result = sanitize_fetch_result(await self._fetcher.fetch_one(request))
        if result.provider_key != self._fetcher.capabilities.provider_key:
            raise CrawlStateConflictError("fetcher returned a different provider identity")
        if not await self._repository.record_provider_result(lease, attempt, result.metadata()):
            raise AcquisitionFenceLostError("lease expired before provider result publication")
        if result.retry_class is not RetryClass.SUCCESS:
            return DurableAcquisitionResult(attempt=attempt, provider_result=result)
        try:
            return await self.persist_retained(lease, attempt, result)
        except (asyncio.CancelledError, AcquisitionFenceLostError):
            raise
        except Exception as exc:
            raise AcquisitionPersistencePendingError(
                lease=lease, attempt=attempt, retained_result=result
            ) from exc

    async def persist_retained(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        result: PageFetchResult,
    ) -> DurableAcquisitionResult:
        """Retry only artifact/snapshot persistence for bytes already held by the caller."""

        retained = await self._artifacts.persist_success(lease, attempt, result)
        return await self._finish_persistence(lease, attempt, result, retained)

    async def retry_persistence(
        self, pending: AcquisitionPersistencePendingError
    ) -> DurableAcquisitionResult:
        """Convenience replay for a process that still holds the successful provider bytes."""

        return await self.persist_retained(pending.lease, pending.attempt, pending.retained_result)

    async def resume_persistence(self, claim: PersistenceClaim) -> DurableAcquisitionResult | None:
        """Finish from a staged PB-B2 blob under a fresh generation; never invoke ``fetch_one``."""

        retained = await self._artifacts.load_success(claim.lease, claim.attempt)
        if retained is None:
            outcome = AttemptOutcome(
                disposition=AttemptDisposition.QUARANTINE,
                attempt_state=FetchAttemptState.QUARANTINED,
                page_state=CrawlPageState.QUARANTINED,
                reason_code="provider_success_artifact_unrecoverable",
            )
            if not await self._repository.disposition_attempt(claim.lease, claim.attempt, outcome):
                raise AcquisitionFenceLostError("persistence quarantine lost its lease")
            return None
        result = self._result_from_retained(retained)
        return await self._finish_persistence(claim.lease, claim.attempt, result, retained)

    async def reconcile(
        self,
        claim: ReconciliationClaim,
        request: PageFetchRequest,
        *,
        lookup: ProviderOperationLookup | None,
        provider_request_id: str | None = None,
    ) -> DurableAcquisitionResult | None:
        """Resolve one ambiguous dispatch by lookup or quarantine, never by page fetch."""

        if request.operation_key != claim.attempt.operation_key:
            raise ValueError("reconciliation request must reuse the durable operation key")
        if request.requested_url != claim.lease.requested_url:
            raise ValueError("reconciliation request URL must match the leased page")
        if (
            lookup is None
            or not lookup.capabilities.supports_operation_lookup
            or lookup.capabilities.provider_key != claim.attempt.provider_key
        ):
            outcome = AttemptOutcome(
                disposition=AttemptDisposition.QUARANTINE,
                attempt_state=FetchAttemptState.QUARANTINED,
                page_state=CrawlPageState.QUARANTINED,
                reason_code="provider_operation_lookup_unavailable",
            )
            if not await self._repository.disposition_attempt(claim.lease, claim.attempt, outcome):
                raise AcquisitionFenceLostError("reconciliation quarantine lost its lease")
            return None

        result = sanitize_fetch_result(
            await lookup.lookup_operation(request, provider_request_id=provider_request_id)
        )
        if result.provider_key != claim.attempt.provider_key:
            raise CrawlStateConflictError("lookup returned a different provider identity")
        if not await self._repository.record_provider_result(
            claim.lease, claim.attempt, result.metadata()
        ):
            raise AcquisitionFenceLostError("reconciliation result lost its lease")
        if result.retry_class is not RetryClass.SUCCESS:
            return DurableAcquisitionResult(attempt=claim.attempt, provider_result=result)
        try:
            return await self.persist_retained(claim.lease, claim.attempt, result)
        except (asyncio.CancelledError, AcquisitionFenceLostError):
            raise
        except Exception as exc:
            raise AcquisitionPersistencePendingError(
                lease=claim.lease,
                attempt=claim.attempt,
                retained_result=result,
            ) from exc

    async def _finish_persistence(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        result: PageFetchResult,
        retained: RetainedPageSuccess,
    ) -> DurableAcquisitionResult:
        snapshot = await self._repository.persist_snapshot(
            lease,
            attempt,
            retained.artifact,
            retained.metadata,
            retained.outgoing_links,
        )
        if snapshot is None:
            raise AcquisitionFenceLostError("snapshot persistence lost its lease")
        if not await self._repository.complete_page(lease, snapshot_id=snapshot.snapshot_id):
            raise AcquisitionFenceLostError("page completion lost its lease")
        return DurableAcquisitionResult(
            attempt=attempt,
            provider_result=result,
            artifact=retained.artifact,
            snapshot=snapshot,
        )

    @staticmethod
    def _result_from_retained(retained: RetainedPageSuccess) -> PageFetchResult:
        metadata = retained.metadata
        return PageFetchResult(
            provider_key=metadata.provider_key,
            provider_request_id=metadata.provider_request_id,
            requested_url=metadata.requested_url,
            final_url=metadata.final_url,
            redirect_chain=metadata.redirect_chain,
            provider_status=metadata.provider_status,
            http_status=metadata.http_status,
            content=retained.content,
            media_type=metadata.media_type,
            outgoing_links=retained.outgoing_links,
            fetched_at=metadata.fetched_at,
            cost_cents=metadata.cost_cents,
            cost_kind=metadata.cost_kind,
            spend_status=metadata.spend_status,
            retry_class=metadata.retry_class,
            receipt=metadata.receipt,
        )


__all__ = [
    "AcquisitionFenceLostError",
    "AcquisitionPersistencePendingError",
    "DurableAcquisitionResult",
    "DurablePageAcquirer",
    "ProviderOperationLookup",
]
