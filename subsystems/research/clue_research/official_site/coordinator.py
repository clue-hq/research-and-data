"""Bounded PostgreSQL-driven concurrent official-site crawl coordinator (C5).

The coordinator owns worker lifecycle, safety/robots admission, heartbeat, recovery-claim routing,
and durable depth expansion. It never owns a second frontier: every work decision is a fenced
PostgreSQL claim and every provider invocation passes through C4's one-page acquisition protocol.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar, runtime_checkable
from urllib.parse import urlsplit
from uuid import UUID

from clue_obs import get_logger
from clue_research.official_site.artifacts import OfficialSiteArtifactStore
from clue_research.official_site.contracts import (
    ClaimLinkExpansionRequest,
    ClaimNextRequest,
    ClaimPersistenceRequest,
    ClaimReconciliationRequest,
    CostKind,
    CrawlLease,
    CrawlMode,
    CrawlPhase,
    DiscoveryBatch,
    LinkExpansionLease,
    LinkExpansionState,
    LinkObservation,
    LinkRelation,
    OfficialSiteCrawlContractConfig,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    RetryClass,
    SpendStatus,
)
from clue_research.official_site.discovery import OfficialSiteDiscoveryPolicy
from clue_research.official_site.progress import (
    CrawlProgressEvent,
    CrawlProgressEventKind,
    privacy_safe_log_label,
    privacy_safe_provider_status,
    progress_event_id,
    record_stale_completion_rejection,
)
from clue_research.official_site.reconciliation import (
    AcquisitionFenceLostError,
    AcquisitionPersistencePendingError,
    DurableAcquisitionResult,
    DurablePageAcquirer,
    ProviderOperationLookup,
)
from clue_research.official_site.safety import (
    AddressResolver,
    CrawlSafetyPolicy,
    SafetyDecision,
    bound_outgoing_links,
    preflight_target,
    validate_redirects,
    validate_response_content,
)
from clue_research.official_site.seams import (
    CrawlProgressSink,
    CrawlRepository,
    NullCrawlProgressSink,
    PageFetcher,
)
from clue_research.official_site.url_policy import ConservativeUrlPolicy

_ResultT = TypeVar("_ResultT")
log = get_logger("clue_research.official_site.coordinator")


class CoordinatorLeaseLostError(RuntimeError):
    """A heartbeat lost the page fence; this logical worker may not claim more work."""


@dataclass(frozen=True, slots=True)
class RobotsAuthorization:
    allowed: bool
    decision_ref: str
    reason: str

    def __post_init__(self) -> None:
        if not self.decision_ref or not self.reason:
            raise ValueError("robots authorization requires a decision reference and reason")


@runtime_checkable
class RobotsAuthorizer(Protocol):
    """Already-bounded robots authority supplied by C6 composition."""

    policy_version: str

    async def authorize(self, url: str) -> RobotsAuthorization: ...


class StaticRobotsAuthorizer:
    """Deterministic authorizer for offline composition and coordinator acceptance tests."""

    def __init__(self, *, policy_version: str, allowed: bool = True) -> None:
        if not policy_version:
            raise ValueError("robots policy version is required")
        self.policy_version = policy_version
        self._allowed = allowed

    async def authorize(self, url: str) -> RobotsAuthorization:
        del url
        return RobotsAuthorization(
            allowed=self._allowed,
            decision_ref=f"robots:{self.policy_version}:{'allow' if self._allowed else 'refuse'}",
            reason="robots_allowed" if self._allowed else "robots_refused",
        )


@dataclass(frozen=True, slots=True)
class CoordinatorPhaseRequest:
    workspace_id: str
    crawl_run_id: UUID
    phase: CrawlPhase
    config: OfficialSiteCrawlContractConfig
    recon_run_id: UUID | None = None
    worker_id_prefix: str = "official-site"
    idle_poll_seconds: float = 0.05
    max_idle_polls: int = 4

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id is required")
        if not self.worker_id_prefix or len(self.worker_id_prefix) > 160:
            raise ValueError("worker_id_prefix must contain 1-160 characters")
        if self.idle_poll_seconds <= 0 or self.max_idle_polls < 1:
            raise ValueError("idle polling bounds must be positive")
        if self.config.crawl_mode is CrawlMode.OFF:
            raise ValueError("the coordinator cannot run with crawl mode off")


@dataclass(frozen=True, slots=True)
class CoordinatorPhaseResult:
    workspace_id: str
    crawl_run_id: UUID
    phase: CrawlPhase
    ordinary_claims: int
    persistence_claims: int
    reconciliation_claims: int
    pages_completed: int
    observations_recorded: int
    links_dropped: int
    heartbeat_renewals: int
    fenced_workers: int
    worker_errors: int
    stopped: bool
    link_expansion_claims: int = 0
    link_expansions_completed: int = 0
    link_expansions_retried: int = 0
    link_expansions_failed: int = 0


@dataclass(slots=True)
class _Counters:
    ordinary_claims: int = 0
    persistence_claims: int = 0
    reconciliation_claims: int = 0
    link_expansion_claims: int = 0
    link_expansions_completed: int = 0
    link_expansions_retried: int = 0
    link_expansions_failed: int = 0
    pages_completed: int = 0
    observations_recorded: int = 0
    links_dropped: int = 0
    heartbeat_renewals: int = 0
    fenced_workers: int = 0
    worker_errors: int = 0
    active_operations: int = 0


class _RefusalFetcher:
    def __init__(
        self,
        *,
        capabilities: PageFetcherCapabilities,
        reason: str,
        retry_class: RetryClass,
    ) -> None:
        self.capabilities = capabilities
        self._reason = reason
        self._retry_class = retry_class

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        return PageFetchResult(
            provider_key=self.capabilities.provider_key,
            requested_url=request.requested_url,
            provider_status=self._reason,
            fetched_at=datetime.now(UTC),
            cost_kind=CostKind.NONE,
            spend_status=SpendStatus.NO_SPEND,
            retry_class=self._retry_class,
        )


class _ValidatedFetcher:
    """Apply C2 post-response policy before C4 can persist a successful result."""

    def __init__(
        self,
        *,
        delegate: PageFetcher,
        url_policy: ConservativeUrlPolicy,
        resolver: AddressResolver,
        safety: CrawlSafetyPolicy,
    ) -> None:
        self._delegate = delegate
        self._url_policy = url_policy
        self._resolver = resolver
        self._safety = safety
        self.capabilities = delegate.capabilities

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        result = await self._delegate.fetch_one(request)
        return await _validate_provider_result(
            result,
            request=request,
            expected_provider_key=self.capabilities.provider_key,
            url_policy=self._url_policy,
            resolver=self._resolver,
            safety=self._safety,
        )


class _ValidatedOperationLookup:
    """Apply the same coordinator policy to a recovered provider result as a live fetch."""

    def __init__(
        self,
        *,
        delegate: ProviderOperationLookup,
        url_policy: ConservativeUrlPolicy,
        resolver: AddressResolver,
        safety: CrawlSafetyPolicy,
    ) -> None:
        self._delegate = delegate
        self._url_policy = url_policy
        self._resolver = resolver
        self._safety = safety
        self.capabilities = delegate.capabilities

    async def lookup_operation(
        self,
        request: PageFetchRequest,
        *,
        provider_request_id: str | None,
    ) -> PageFetchResult:
        result = await self._delegate.lookup_operation(
            request,
            provider_request_id=provider_request_id,
        )
        return await _validate_provider_result(
            result,
            request=request,
            expected_provider_key=self.capabilities.provider_key,
            url_policy=self._url_policy,
            resolver=self._resolver,
            safety=self._safety,
        )


async def _validate_provider_result(
    result: PageFetchResult,
    *,
    request: PageFetchRequest,
    expected_provider_key: str,
    url_policy: ConservativeUrlPolicy,
    resolver: AddressResolver,
    safety: CrawlSafetyPolicy,
) -> PageFetchResult:
    """Fail closed over every successful result, including operation-lookup recovery."""

    if result.retry_class is not RetryClass.SUCCESS:
        return result
    if (
        result.provider_key != expected_provider_key
        or result.requested_url != request.requested_url
    ):
        # A provider receipt is evidence, never authority over which provider/URL Clue asked for.
        # Refuse the bytes and restore the coordinator-owned identities before persistence so a
        # hostile or malformed lookup response cannot forge URL/provider provenance.
        return _refuse_provider_result(
            result.model_copy(
                update={
                    "provider_key": expected_provider_key,
                    "requested_url": request.requested_url,
                }
            ),
            SafetyDecision(False, "provider_identity_mismatch"),
        )
    assert result.final_url is not None
    redirect_decision = await validate_redirects(
        requested_url=request.requested_url,
        final_url=result.final_url,
        redirect_chain=result.redirect_chain,
        url_policy=url_policy,
        resolver=resolver,
        safety=safety,
    )
    if not redirect_decision.allowed:
        return _refuse_provider_result(result, redirect_decision)
    content_decision = validate_response_content(
        media_type=result.media_type,
        content=result.content,
        safety=safety,
    )
    if not content_decision.allowed:
        return _refuse_provider_result(result, content_decision)
    bounded = bound_outgoing_links(result.outgoing_links, safety=safety)
    return result.model_copy(update={"outgoing_links": bounded.links})


def _refuse_provider_result(result: PageFetchResult, decision: SafetyDecision) -> PageFetchResult:
    return result.model_copy(
        update={
            "content": None,
            "outgoing_links": (),
            "provider_status": f"coordinator_policy_refused:{decision.reason}",
            "retry_class": RetryClass.POLICY_REFUSED,
        }
    )


class ConcurrentCrawlCoordinator:
    """Drain one fast or background phase through a bounded set of logical workers."""

    def __init__(
        self,
        *,
        repository: CrawlRepository,
        artifacts: OfficialSiteArtifactStore,
        fetcher: PageFetcher,
        discovery_policy: OfficialSiteDiscoveryPolicy,
        url_policy: ConservativeUrlPolicy,
        resolver: AddressResolver,
        safety: CrawlSafetyPolicy,
        robots: RobotsAuthorizer,
        operation_lookup: ProviderOperationLookup | None = None,
        progress_sink: CrawlProgressSink | None = None,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._fetcher = fetcher
        self._discovery_policy = discovery_policy
        self._url_policy = url_policy
        self._resolver = resolver
        self._safety = safety
        self._robots = robots
        self._operation_lookup = (
            _ValidatedOperationLookup(
                delegate=operation_lookup,
                url_policy=url_policy,
                resolver=resolver,
                safety=safety,
            )
            if operation_lookup is not None
            else None
        )
        self._progress_sink = progress_sink or NullCrawlProgressSink()

    async def run_phase(
        self,
        request: CoordinatorPhaseRequest,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> CoordinatorPhaseResult:
        self._validate_composition(request.config)
        stop = stop_event or asyncio.Event()
        counters = _Counters()
        tasks = tuple(
            asyncio.create_task(
                self._worker(
                    request,
                    worker_id=f"{request.worker_id_prefix}:{index}",
                    stop=stop,
                    counters=counters,
                )
            )
            for index in range(request.config.worker_concurrency)
        )
        group = asyncio.gather(*tasks)
        try:
            # Shielding is essential: graceful caller cancellation stops new claims but lets an
            # already-dispatched paid call finish and publish/reconcile under its current fence.
            await asyncio.shield(group)
        except asyncio.CancelledError:
            stop.set()
            await asyncio.shield(group)
            raise
        return CoordinatorPhaseResult(
            workspace_id=request.workspace_id,
            crawl_run_id=request.crawl_run_id,
            phase=request.phase,
            ordinary_claims=counters.ordinary_claims,
            persistence_claims=counters.persistence_claims,
            reconciliation_claims=counters.reconciliation_claims,
            link_expansion_claims=counters.link_expansion_claims,
            link_expansions_completed=counters.link_expansions_completed,
            link_expansions_retried=counters.link_expansions_retried,
            link_expansions_failed=counters.link_expansions_failed,
            pages_completed=counters.pages_completed,
            observations_recorded=counters.observations_recorded,
            links_dropped=counters.links_dropped,
            heartbeat_renewals=counters.heartbeat_renewals,
            fenced_workers=counters.fenced_workers,
            worker_errors=counters.worker_errors,
            stopped=stop.is_set(),
        )

    def _validate_composition(self, config: OfficialSiteCrawlContractConfig) -> None:
        if self._fetcher.capabilities.provider_key != config.provider_key:
            raise ValueError("fetcher provider does not match the run-pinned provider key")
        if self._url_policy.config.version != config.url_policy_version:
            raise ValueError("URL policy does not match the run-pinned version")
        if self._url_policy.config.allow_subdomains != config.allow_subdomains:
            raise ValueError("subdomain policy does not match the run-pinned configuration")
        if self._robots.policy_version != config.robots_policy_version:
            raise ValueError("robots policy does not match the run-pinned version")
        if (
            self._safety.max_redirects != config.max_redirects
            or self._safety.max_response_bytes != config.max_response_bytes
        ):
            raise ValueError("response safety ceilings do not match the run-pinned configuration")

    async def _worker(
        self,
        request: CoordinatorPhaseRequest,
        *,
        worker_id: str,
        stop: asyncio.Event,
        counters: _Counters,
    ) -> None:
        idle_polls = 0
        while not stop.is_set():
            try:
                handled = await self._claim_and_handle(
                    request, worker_id=worker_id, counters=counters
                )
            except asyncio.CancelledError:
                raise
            except (AcquisitionFenceLostError, CoordinatorLeaseLostError):
                counters.fenced_workers += 1
                record_stale_completion_rejection(
                    phase=request.phase,
                    provider_key=self._fetcher.capabilities.provider_key,
                )
                return
            except Exception as exc:
                # The durable page/attempt state owns recovery. Exiting this logical worker avoids
                # an error loop or a new external call under suspect local state.
                counters.worker_errors += 1
                log.warning(
                    "stage0_official_site.worker_failed",
                    workspace_id=request.workspace_id,
                    crawl_run_id=str(request.crawl_run_id),
                    phase=request.phase.value,
                    worker_id=worker_id,
                    failure_stage="worker_loop",
                    failure_class=type(exc).__name__[:200],
                )
                return
            if handled:
                idle_polls = 0
                continue
            # Keep idle siblings available while another local worker may still discover new
            # depth work. Once the local pool is truly idle, bounded polls let the phase return.
            idle_polls = 0 if counters.active_operations else idle_polls + 1
            if idle_polls >= request.max_idle_polls:
                return
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=request.idle_poll_seconds)

    async def _claim_and_handle(
        self,
        request: CoordinatorPhaseRequest,
        *,
        worker_id: str,
        counters: _Counters,
    ) -> bool:
        persistence = await self._repository.claim_persistence(
            ClaimPersistenceRequest(
                workspace_id=request.workspace_id,
                crawl_run_id=request.crawl_run_id,
                worker_id=worker_id,
                lease_ttl_seconds=request.config.lease_ttl_seconds,
            )
        )
        if persistence is not None:
            counters.persistence_claims += 1
            acquirer = self._acquirer(counters=counters)
            operation_started = time.monotonic()
            result = await self._while_active(
                counters,
                action=lambda: self._with_heartbeat(
                    persistence.lease,
                    request=request,
                    counters=counters,
                    action=lambda: acquirer.resume_persistence(persistence),
                ),
            )
            if result is not None and result.page_completed:
                counters.pages_completed += 1
                assert result.snapshot is not None
                await self._emit_page_event(
                    request,
                    persistence.lease,
                    kind=CrawlProgressEventKind.PAGE_FETCHED,
                    subject=str(result.snapshot.snapshot_id),
                    snapshot_id=result.snapshot.snapshot_id,
                    outcome="persistence_recovered",
                    provider_result=result.provider_result,
                    artifact_key=(
                        result.artifact.artifact_key if result.artifact is not None else None
                    ),
                    duration_ms=int((time.monotonic() - operation_started) * 1000),
                )
            elif result is None:
                await self._emit_page_event(
                    request,
                    persistence.lease,
                    kind=CrawlProgressEventKind.PAGE_REFUSED,
                    subject=f"{persistence.lease.page_id}:g{persistence.lease.lease_generation}",
                    outcome="persistence_artifact_unrecoverable",
                    duration_ms=int((time.monotonic() - operation_started) * 1000),
                )
            return True

        expansion = await self._repository.claim_link_expansion(
            ClaimLinkExpansionRequest(
                workspace_id=request.workspace_id,
                crawl_run_id=request.crawl_run_id,
                worker_id=worker_id,
                eligible_phase=request.phase,
                lease_ttl_seconds=request.config.lease_ttl_seconds,
            )
        )
        if expansion is not None:
            counters.link_expansion_claims += 1
            await self._emit_expansion_event(
                request,
                expansion,
                kind=CrawlProgressEventKind.LINK_EXPANSION_STARTED,
                outcome="claimed",
            )
            await self._while_active(
                counters,
                action=lambda: self._with_link_expansion_heartbeat(
                    expansion,
                    request=request,
                    counters=counters,
                    action=lambda: self._handle_link_expansion(
                        expansion,
                        request=request,
                        counters=counters,
                    ),
                ),
            )
            return True

        reconciliation = await self._repository.claim_reconciliation(
            ClaimReconciliationRequest(
                workspace_id=request.workspace_id,
                crawl_run_id=request.crawl_run_id,
                worker_id=worker_id,
                lease_ttl_seconds=request.config.lease_ttl_seconds,
            )
        )
        if reconciliation is not None:
            counters.reconciliation_claims += 1
            acquirer = self._acquirer(counters=counters)
            operation_started = time.monotonic()
            fetch_request = self._fetch_request(
                reconciliation.lease,
                config=request.config,
                operation_key=reconciliation.attempt.operation_key,
                robots_decision_ref=(
                    f"reconciliation:{request.config.robots_policy_version}:original-operation"
                ),
            )
            result = await self._while_active(
                counters,
                action=lambda: self._with_heartbeat(
                    reconciliation.lease,
                    request=request,
                    counters=counters,
                    action=lambda: acquirer.reconcile(
                        reconciliation,
                        fetch_request,
                        lookup=self._operation_lookup,
                        provider_request_id=reconciliation.attempt.provider_request_id,
                    ),
                ),
            )
            if result is not None and result.page_completed:
                counters.pages_completed += 1
                assert result.snapshot is not None
                await self._emit_page_event(
                    request,
                    reconciliation.lease,
                    kind=CrawlProgressEventKind.PAGE_FETCHED,
                    subject=str(result.snapshot.snapshot_id),
                    snapshot_id=result.snapshot.snapshot_id,
                    outcome="reconciled_persisted",
                    provider_result=result.provider_result,
                    artifact_key=(
                        result.artifact.artifact_key if result.artifact is not None else None
                    ),
                    duration_ms=int((time.monotonic() - operation_started) * 1000),
                )
            elif result is None:
                await self._emit_page_event(
                    request,
                    reconciliation.lease,
                    kind=CrawlProgressEventKind.PAGE_REFUSED,
                    subject=(
                        f"{reconciliation.lease.page_id}:g{reconciliation.lease.lease_generation}"
                    ),
                    outcome="reconciliation_quarantined",
                    duration_ms=int((time.monotonic() - operation_started) * 1000),
                )
            return True

        lease = await self._repository.claim_next(
            ClaimNextRequest(
                workspace_id=request.workspace_id,
                crawl_run_id=request.crawl_run_id,
                worker_id=worker_id,
                eligible_phase=request.phase,
                lease_ttl_seconds=request.config.lease_ttl_seconds,
            )
        )
        if lease is None:
            return False
        counters.ordinary_claims += 1
        await self._emit_page_event(
            request,
            lease,
            kind=CrawlProgressEventKind.PAGE_STARTED,
            subject=f"{lease.page_id}:g{lease.lease_generation}",
        )
        operation_started = time.monotonic()
        result = await self._while_active(
            counters,
            action=lambda: self._with_heartbeat(
                lease,
                request=request,
                counters=counters,
                action=lambda: self._acquire_ordinary(lease, request=request, counters=counters),
            ),
        )
        if result.page_completed:
            counters.pages_completed += 1
            assert result.snapshot is not None
            await self._emit_page_event(
                request,
                lease,
                kind=CrawlProgressEventKind.PAGE_FETCHED,
                subject=str(result.snapshot.snapshot_id),
                snapshot_id=result.snapshot.snapshot_id,
                outcome="persisted",
                provider_result=result.provider_result,
                artifact_key=(
                    result.artifact.artifact_key if result.artifact is not None else None
                ),
                duration_ms=int((time.monotonic() - operation_started) * 1000),
            )
        elif result.provider_result.retry_class in {
            RetryClass.POLICY_REFUSED,
            RetryClass.ROBOTS_REFUSED,
        }:
            await self._emit_page_event(
                request,
                lease,
                kind=CrawlProgressEventKind.PAGE_REFUSED,
                subject=f"{lease.page_id}:g{lease.lease_generation}",
                outcome=result.provider_result.retry_class.value,
                provider_result=result.provider_result,
                duration_ms=int((time.monotonic() - operation_started) * 1000),
            )
        return True

    async def _acquire_ordinary(
        self,
        lease: CrawlLease,
        *,
        request: CoordinatorPhaseRequest,
        counters: _Counters,
    ) -> DurableAcquisitionResult:
        preflight = await preflight_target(
            lease.requested_url,
            url_policy=self._url_policy,
            resolver=self._resolver,
            safety=self._safety,
        )
        if not preflight.allowed:
            fetcher: PageFetcher = _RefusalFetcher(
                capabilities=self._fetcher.capabilities,
                reason=f"preflight_refused:{preflight.reason}",
                retry_class=RetryClass.POLICY_REFUSED,
            )
            robots_ref = f"preflight:{preflight.reason}"
        else:
            # Robots acquisition/authorization is allowed only after the target has cleared the
            # coordinator's network boundary. A live C6 authorizer may itself consult the host.
            robots = await self._robots.authorize(lease.requested_url)
            if not robots.allowed:
                fetcher = _RefusalFetcher(
                    capabilities=self._fetcher.capabilities,
                    reason=f"robots_refused:{robots.reason}",
                    retry_class=RetryClass.ROBOTS_REFUSED,
                )
            else:
                fetcher = _ValidatedFetcher(
                    delegate=self._fetcher,
                    url_policy=self._url_policy,
                    resolver=self._resolver,
                    safety=self._safety,
                )
            robots_ref = robots.decision_ref
        acquirer = self._acquirer(counters=counters, fetcher=fetcher)
        fetch_request = self._fetch_request(
            lease,
            config=request.config,
            operation_key=self.operation_key(lease),
            robots_decision_ref=robots_ref,
        )
        try:
            return await acquirer.acquire(lease, fetch_request)
        except AcquisitionPersistencePendingError as pending:
            # One immediate retry is persistence-only. A second failure remains durably claimable
            # by a fresh worker; it never falls back to ``fetch_one``.
            return await acquirer.retry_persistence(pending)

    def _acquirer(
        self,
        *,
        counters: _Counters,
        fetcher: PageFetcher | None = None,
    ) -> DurablePageAcquirer:
        del counters
        return DurablePageAcquirer(
            repository=self._repository,
            artifacts=self._artifacts,
            fetcher=fetcher or self._fetcher,
        )

    async def _handle_link_expansion(
        self,
        lease: LinkExpansionLease,
        *,
        request: CoordinatorPhaseRequest,
        counters: _Counters,
    ) -> None:
        """Expand one saved snapshot; never alter its already-fetched page outcome."""

        try:
            links = (
                tuple(
                    LinkObservation(discovered_url=hop.to_url, relation=LinkRelation.REDIRECT)
                    for hop in lease.redirect_chain
                )
                + lease.outgoing_links
            )
            observations, dropped = self._discovery_policy.plan_links(
                links,
                source_page_id=lease.page_id,
                source_url=lease.source_url,
                source_graph_depth=lease.source_graph_depth,
            )
            counters.links_dropped += dropped
            if observations:
                recorded = await self._repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=lease.workspace_id,
                        crawl_run_id=lease.crawl_run_id,
                        observations=observations,
                    )
                )
                counters.observations_recorded += recorded.observations_recorded
            if not await self._repository.complete_link_expansion(lease):
                raise CoordinatorLeaseLostError(
                    "link expansion completion lost its generation fence"
                )
        except (asyncio.CancelledError, CoordinatorLeaseLostError):
            raise
        except Exception as exc:
            retry_after = min(30.0, float(2 ** max(lease.attempt_number - 1, 0)))
            state = await self._repository.fail_link_expansion(
                lease,
                failure_code="discovery_write_failed",
                failure_class=type(exc).__name__[:200],
                retry_after_seconds=retry_after,
            )
            if state is None:
                raise CoordinatorLeaseLostError(
                    "link expansion failure disposition lost its generation fence"
                ) from exc
            if state is LinkExpansionState.FAILED:
                counters.link_expansions_failed += 1
                kind = CrawlProgressEventKind.LINK_EXPANSION_FAILED
            else:
                counters.link_expansions_retried += 1
                kind = CrawlProgressEventKind.LINK_EXPANSION_RETRYING
            log.warning(
                "stage0_official_site.link_expansion_failed",
                workspace_id=lease.workspace_id,
                crawl_run_id=str(lease.crawl_run_id),
                page_id=str(lease.page_id),
                snapshot_id=str(lease.snapshot_id),
                lease_generation=lease.lease_generation,
                attempt_number=lease.attempt_number,
                failure_stage="link_expansion",
                failure_code="discovery_write_failed",
                failure_class=type(exc).__name__[:200],
                disposition=state.value,
                retry_after_seconds=(
                    retry_after if state is LinkExpansionState.RETRY_WAIT else None
                ),
            )
            await self._emit_expansion_event(
                request,
                lease,
                kind=kind,
                outcome=state.value,
                failure_code="discovery_write_failed",
            )
            return

        counters.link_expansions_completed += 1
        await self._emit_expansion_event(
            request,
            lease,
            kind=CrawlProgressEventKind.LINK_EXPANSION_COMPLETED,
            outcome="completed",
        )

    @staticmethod
    async def _while_active(
        counters: _Counters,
        *,
        action: Callable[[], Awaitable[_ResultT]],
    ) -> _ResultT:
        counters.active_operations += 1
        try:
            return await action()
        finally:
            counters.active_operations -= 1

    async def _with_heartbeat(
        self,
        lease: CrawlLease,
        *,
        request: CoordinatorPhaseRequest,
        counters: _Counters,
        action: Callable[[], Awaitable[_ResultT]],
    ) -> _ResultT:
        finished = asyncio.Event()
        fence_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(
                lease,
                request=request,
                counters=counters,
                finished=finished,
                fence_lost=fence_lost,
            )
        )
        try:
            result = await action()
        finally:
            finished.set()
            await heartbeat
        if fence_lost.is_set():
            raise CoordinatorLeaseLostError("lease heartbeat lost its generation fence")
        return result

    async def _with_link_expansion_heartbeat(
        self,
        lease: LinkExpansionLease,
        *,
        request: CoordinatorPhaseRequest,
        counters: _Counters,
        action: Callable[[], Awaitable[_ResultT]],
    ) -> _ResultT:
        finished = asyncio.Event()
        fence_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_link_expansion(
                lease,
                request=request,
                counters=counters,
                finished=finished,
                fence_lost=fence_lost,
            )
        )
        try:
            result = await action()
        finally:
            finished.set()
            await heartbeat
        if fence_lost.is_set():
            raise CoordinatorLeaseLostError("link expansion heartbeat lost its generation fence")
        return result

    async def _heartbeat(
        self,
        lease: CrawlLease,
        *,
        request: CoordinatorPhaseRequest,
        counters: _Counters,
        finished: asyncio.Event,
        fence_lost: asyncio.Event,
    ) -> None:
        while not finished.is_set():
            try:
                await asyncio.wait_for(finished.wait(), timeout=request.config.heartbeat_seconds)
                return
            except TimeoutError:
                renewed = await self._repository.renew_lease(
                    lease, lease_ttl_seconds=request.config.lease_ttl_seconds
                )
                if not renewed:
                    fence_lost.set()
                    return
                counters.heartbeat_renewals += 1

    async def _heartbeat_link_expansion(
        self,
        lease: LinkExpansionLease,
        *,
        request: CoordinatorPhaseRequest,
        counters: _Counters,
        finished: asyncio.Event,
        fence_lost: asyncio.Event,
    ) -> None:
        while not finished.is_set():
            try:
                await asyncio.wait_for(finished.wait(), timeout=request.config.heartbeat_seconds)
                return
            except TimeoutError:
                renewed = await self._repository.renew_link_expansion(
                    lease, lease_ttl_seconds=request.config.lease_ttl_seconds
                )
                if not renewed:
                    fence_lost.set()
                    return
                counters.heartbeat_renewals += 1

    def _fetch_request(
        self,
        lease: CrawlLease,
        *,
        config: OfficialSiteCrawlContractConfig,
        operation_key: str,
        robots_decision_ref: str,
    ) -> PageFetchRequest:
        allowed_hosts = tuple(
            sorted(
                {
                    lease.host,
                    self._url_policy.root_host,
                    self._url_policy.allowed_registrable_domain,
                }
            )
        )
        return PageFetchRequest(
            operation_key=operation_key,
            requested_url=lease.requested_url,
            allowed_hosts=allowed_hosts,
            allowed_registrable_domain=self._url_policy.allowed_registrable_domain,
            allow_subdomains=config.allow_subdomains,
            timeout_seconds=config.request_timeout_seconds,
            max_response_bytes=config.max_response_bytes,
            accepted_mime_types=tuple(sorted(self._safety.effective_mime_types)),
            max_redirects=config.max_redirects,
            robots_decision_ref=robots_decision_ref,
        )

    @staticmethod
    def operation_key(lease: CrawlLease) -> str:
        """Stable for one generation and distinct for a proven-no-spend retry generation."""

        return f"official-site:{lease.crawl_run_id}:{lease.page_id}:g{lease.lease_generation}"

    async def _emit_expansion_event(
        self,
        request: CoordinatorPhaseRequest,
        lease: LinkExpansionLease,
        *,
        kind: CrawlProgressEventKind,
        outcome: str,
        failure_code: str | None = None,
    ) -> None:
        if request.recon_run_id is None:
            return
        try:
            await self._progress_sink.emit(
                CrawlProgressEvent(
                    event_id=progress_event_id(
                        kind,
                        lease.crawl_run_id,
                        subject=f"{lease.expansion_id}:g{lease.lease_generation}",
                    ),
                    kind=kind,
                    workspace_id=lease.workspace_id,
                    crawl_run_id=lease.crawl_run_id,
                    recon_run_id=request.recon_run_id,
                    phase=request.phase,
                    page_id=lease.page_id,
                    snapshot_id=lease.snapshot_id,
                    lease_generation=lease.lease_generation,
                    url_hash=hashlib.sha256(lease.source_url.encode("utf-8")).hexdigest(),
                    host=urlsplit(lease.source_url).hostname,
                    graph_depth=lease.source_graph_depth,
                    discovered_count=len(lease.outgoing_links),
                    outcome=outcome,
                    failure_code=failure_code,
                )
            )
        except Exception:
            # Visibility never changes expansion disposition or retries discovery work.
            return

    async def _emit_page_event(
        self,
        request: CoordinatorPhaseRequest,
        lease: CrawlLease,
        *,
        kind: CrawlProgressEventKind,
        subject: str,
        snapshot_id: UUID | None = None,
        outcome: str | None = None,
        provider_result: PageFetchResult | None = None,
        artifact_key: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        if request.recon_run_id is None:
            return
        try:
            await self._progress_sink.emit(
                CrawlProgressEvent(
                    event_id=progress_event_id(kind, lease.crawl_run_id, subject=subject),
                    kind=kind,
                    workspace_id=lease.workspace_id,
                    crawl_run_id=lease.crawl_run_id,
                    recon_run_id=request.recon_run_id,
                    phase=request.phase,
                    page_id=lease.page_id,
                    snapshot_id=snapshot_id,
                    lease_generation=lease.lease_generation,
                    url_hash=hashlib.sha256(lease.fetch_key.encode("utf-8")).hexdigest(),
                    host=lease.host,
                    provider_key=self._fetcher.capabilities.provider_key,
                    provider_request_id=privacy_safe_log_label(
                        (
                            provider_result.provider_request_id
                            if provider_result is not None
                            else None
                        ),
                        max_length=200,
                    ),
                    provider_status=privacy_safe_provider_status(
                        provider_result.provider_status if provider_result is not None else None
                    ),
                    http_status=(
                        provider_result.http_status if provider_result is not None else None
                    ),
                    graph_depth=lease.graph_depth,
                    duration_ms=duration_ms,
                    size_bytes=(
                        len(provider_result.content)
                        if provider_result is not None and provider_result.content is not None
                        else None
                    ),
                    cost_cents=(
                        provider_result.cost_cents if provider_result is not None else None
                    ),
                    spend_status=(
                        provider_result.spend_status.value if provider_result is not None else None
                    ),
                    retry_class=(
                        provider_result.retry_class.value if provider_result is not None else None
                    ),
                    artifact_key=artifact_key,
                    outcome=outcome,
                )
            )
        except Exception:
            # Visibility cannot fail or retry a provider operation.
            return


__all__ = [
    "ConcurrentCrawlCoordinator",
    "CoordinatorLeaseLostError",
    "CoordinatorPhaseRequest",
    "CoordinatorPhaseResult",
    "RobotsAuthorization",
    "RobotsAuthorizer",
    "StaticRobotsAuthorizer",
]
