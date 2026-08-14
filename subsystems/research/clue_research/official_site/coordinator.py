"""Bounded PostgreSQL-driven concurrent official-site crawl coordinator (C5).

The coordinator owns worker lifecycle, safety/robots admission, heartbeat, recovery-claim routing,
and durable depth expansion. It never owns a second frontier: every work decision is a fenced
PostgreSQL claim and every provider invocation passes through C4's one-page acquisition protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar, cast, runtime_checkable
from uuid import UUID

from clue_research.official_site.artifacts import OfficialSiteArtifactStore, RetainedPageSuccess
from clue_research.official_site.contracts import (
    ClaimNextRequest,
    ClaimPersistenceRequest,
    ClaimReconciliationRequest,
    CostKind,
    CrawlLease,
    CrawlMode,
    CrawlPhase,
    DiscoveryBatch,
    LinkObservation,
    LinkRelation,
    OfficialSiteCrawlContractConfig,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    PageSnapshotRef,
    RetryClass,
    SpendStatus,
)
from clue_research.official_site.discovery import OfficialSiteDiscoveryPolicy
from clue_research.official_site.reconciliation import (
    AcquisitionFenceLostError,
    AcquisitionPersistencePendingError,
    DurableAcquisitionResult,
    DurablePageAcquirer,
    ProviderOperationLookup,
    SnapshotBeforeCompleteHook,
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
from clue_research.official_site.seams import CrawlRepository, PageFetcher
from clue_research.official_site.url_policy import ConservativeUrlPolicy

_ResultT = TypeVar("_ResultT")


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


@dataclass(slots=True)
class _Counters:
    ordinary_claims: int = 0
    persistence_claims: int = 0
    reconciliation_claims: int = 0
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
        if result.retry_class is not RetryClass.SUCCESS:
            return result
        assert result.final_url is not None
        redirect_decision = await validate_redirects(
            requested_url=request.requested_url,
            final_url=result.final_url,
            redirect_chain=result.redirect_chain,
            url_policy=self._url_policy,
            resolver=self._resolver,
            safety=self._safety,
        )
        if not redirect_decision.allowed:
            return self._refuse(result, redirect_decision)
        content_decision = validate_response_content(
            media_type=result.media_type,
            content=result.content,
            safety=self._safety,
        )
        if not content_decision.allowed:
            return self._refuse(result, content_decision)
        bounded = bound_outgoing_links(result.outgoing_links, safety=self._safety)
        return result.model_copy(update={"outgoing_links": bounded.links})

    @staticmethod
    def _refuse(result: PageFetchResult, decision: SafetyDecision) -> PageFetchResult:
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
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._fetcher = fetcher
        self._discovery_policy = discovery_policy
        self._url_policy = url_policy
        self._resolver = resolver
        self._safety = safety
        self._robots = robots
        self._operation_lookup = operation_lookup

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
                return
            except Exception:
                # The durable page/attempt state owns recovery. Exiting this logical worker avoids
                # an error loop or a new external call under suspect local state.
                counters.worker_errors += 1
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
                        provider_request_id=None,
                    ),
                ),
            )
            if result is not None and result.page_completed:
                counters.pages_completed += 1
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
        async def before_complete(
            current_lease: CrawlLease,
            snapshot: PageSnapshotRef,
            retained: RetainedPageSuccess,
        ) -> None:
            del snapshot
            links = (
                tuple(
                    LinkObservation(discovered_url=hop.to_url, relation=LinkRelation.REDIRECT)
                    for hop in retained.metadata.redirect_chain
                )
                + retained.outgoing_links
            )
            observations, dropped = self._discovery_policy.plan_links(
                links,
                source_page_id=current_lease.page_id,
                source_url=retained.metadata.final_url or current_lease.requested_url,
                source_graph_depth=current_lease.graph_depth,
            )
            counters.links_dropped += dropped
            if not observations:
                return
            recorded = await self._repository.record_discoveries(
                DiscoveryBatch(
                    workspace_id=current_lease.workspace_id,
                    crawl_run_id=current_lease.crawl_run_id,
                    observations=observations,
                )
            )
            counters.observations_recorded += recorded.observations_recorded

        return DurablePageAcquirer(
            repository=self._repository,
            artifacts=self._artifacts,
            fetcher=fetcher or self._fetcher,
            before_complete=cast(SnapshotBeforeCompleteHook, before_complete),
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


__all__ = [
    "ConcurrentCrawlCoordinator",
    "CoordinatorLeaseLostError",
    "CoordinatorPhaseRequest",
    "CoordinatorPhaseResult",
    "RobotsAuthorization",
    "RobotsAuthorizer",
    "StaticRobotsAuthorizer",
]
