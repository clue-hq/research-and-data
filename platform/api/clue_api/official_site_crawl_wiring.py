"""C6 production composition for durable Stage-0 official-site acquisition.

Provider selection lives only here. The research lifecycle/coordinator receive the frozen
``PageFetcher`` seam and therefore never branch on Firecrawl, Scrapling, or SDK-specific values.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import text

from clue_api.official_site_progress import DbOfficialSiteProgressEmitter
from clue_config import Secrets, Settings
from clue_core import EntityId, ReconRunId, RunId
from clue_core.gateway import LLMGateway
from clue_db import ConnFactory, transaction
from clue_fleet import DbWorkQueue, FleetTaskKind, WorkContext, WorkId, WorkQueue, WorkResult
from clue_obs import get_logger
from clue_research.adapters.firecrawl_page import FirecrawlPageFetcher
from clue_research.adapters.page_fetcher_common import header, media_type
from clue_research.adapters.scrapling_page import (
    ScraplingPageFetcher,
    ScraplingPinnedTransport,
    ScraplingTransportResponse,
)
from clue_research.identity import registrable_domain
from clue_research.official_site import (
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    ROBOTS_POLICY_VERSION,
    ConcurrentCrawlCoordinator,
    CrawlMode,
    CrawlPhase,
    CrawlPhasePendingError,
    CrawlProgressEvent,
    CrawlProgressEventKind,
    CrawlProgressSink,
    CrawlSafetyPolicy,
    GroundedOfficialSiteMaterializer,
    NullCrawlProgressSink,
    OfficialSiteArtifactStore,
    OfficialSiteClientKbCommitter,
    OfficialSiteCrawlContractConfig,
    OfficialSiteCrawlLifecycle,
    OfficialSiteCrawlLifecycleRequest,
    OfficialSiteDiscoveryPolicy,
    OfficialSiteExtractionPending,
    OfficialSiteMaterializationRequest,
    PageFetcher,
    PageFetchRequest,
    PostgresCrawlRepository,
    PostgresOfficialSiteOperations,
    RobotsAuthorization,
    RobotsDocument,
    RobotsParsePolicy,
    SitemapEntry,
    SitemapParsePolicy,
    SitemapPayload,
    SystemAddressResolver,
    UrlObservation,
    parse_robots,
    parse_sitemap,
    progress_event_id,
)
from clue_research.official_site.url_policy import ConservativeUrlPolicy
from clue_research.stage0 import (
    ReconLaneStatus,
    finalize_client_kb_version,
    transition_recon_lane,
)
from clue_storage import StorageBackend

log = get_logger("clue_api.official_site_crawl")

_RECOVERY_BACKOFF_BASE_SECONDS = 1.0
_RECOVERY_BACKOFF_MAX_SECONDS = 30.0
_RECOVERY_LEASE_GRACE_SECONDS = 0.25
_RECOVERY_LEASE_DELAY_MAX_SECONDS = 120.0


def _recovery_requeue_delay(*, task_attempt: int, retry_after_seconds: float | None) -> timedelta:
    """Return a bounded exponential delay that never races a known page-lease boundary."""

    exponent = min(max(task_attempt - 1, 0), 20)
    exponential = min(
        _RECOVERY_BACKOFF_MAX_SECONDS,
        _RECOVERY_BACKOFF_BASE_SECONDS * (2**exponent),
    )
    if retry_after_seconds is None:
        delay_seconds = exponential
    else:
        lease_aware = min(
            _RECOVERY_LEASE_DELAY_MAX_SECONDS,
            max(0.0, retry_after_seconds) + _RECOVERY_LEASE_GRACE_SECONDS,
        )
        delay_seconds = max(exponential, lease_aware)
    return timedelta(seconds=delay_seconds)


_PROVIDER_POLICY_VERSION = "official-site-single-page-v1"
_CONTROL_DOCUMENT_MAX_BYTES = 1_000_000
_CONTROL_DOCUMENT_MIME_TYPES = (
    "application/octet-stream",
    "application/xml",
    "text/plain",
    "text/robots",
    "text/xml",
)


@dataclass(frozen=True, slots=True)
class _ReconScope:
    brand_id: str
    client_entity_id: UUID | None
    fast_run_id: UUID
    background_run_id: UUID
    fast_status: str
    fast_client_kb_version: int | None
    company_website: str


class _AuthoritativeClientKbCommitter(OfficialSiteClientKbCommitter):
    """Publish recon lane truth only after checkpoint-grounded claims are committed."""

    def __init__(self, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def product_id(self, request: OfficialSiteMaterializationRequest) -> str | None:
        row = await self._scope(request)
        return cast(str | None, row["product_id"])

    async def commit(
        self,
        request: OfficialSiteMaterializationRequest,
        *,
        filled_fields: set[str],
        attempted_fields: set[str],
    ) -> int:
        row = await self._scope(request)
        async with self._conn_factory() as conn:
            version = await finalize_client_kb_version(
                conn,
                client_entity_id=EntityId(request.client_entity_id),
                workspace_id=request.workspace_id,
                run_id=RunId(request.claim_run_id),
                filled_fields=filled_fields,
                attempted_fields=attempted_fields,
                product_id=cast(str | None, row["product_id"]),
            )
            lane = "fast" if request.phase is CrawlPhase.FAST else "background"
            if lane == "background":
                await transition_recon_lane(
                    conn,
                    recon_run_id=ReconRunId(request.recon_run_id),
                    workspace_id=request.workspace_id,
                    lane=lane,
                    status=ReconLaneStatus.RUNNING,
                    client_entity_id=EntityId(request.client_entity_id),
                )
            await transition_recon_lane(
                conn,
                recon_run_id=ReconRunId(request.recon_run_id),
                workspace_id=request.workspace_id,
                lane=lane,
                status=ReconLaneStatus.COMPLETED,
                client_kb_version=version,
                client_entity_id=EntityId(request.client_entity_id),
            )
        return version

    async def _scope(self, request: OfficialSiteMaterializationRequest) -> dict[str, Any]:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT product_id, fast_run_id, background_run_id, client_entity_id
                            FROM recon_run
                            WHERE id = :recon_run_id AND workspace_id = :workspace_id
                            """
                        ),
                        {
                            "recon_run_id": request.recon_run_id,
                            "workspace_id": request.workspace_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or row["client_entity_id"] != request.client_entity_id:
            raise ValueError("official-site materialization is outside its recon client scope")
        expected_run = (
            row["fast_run_id"] if request.phase is CrawlPhase.FAST else row["background_run_id"]
        )
        if expected_run != request.claim_run_id:
            raise ValueError("official-site materialization claim run disagrees with its phase")
        return dict(row)


def crawl_contract_config(
    settings: Settings, *, provider_key: str
) -> OfficialSiteCrawlContractConfig:
    return OfficialSiteCrawlContractConfig(
        crawl_mode=CrawlMode(settings.stage0_official_site_crawl_mode),
        provider_key=provider_key,
        max_graph_depth=settings.stage0_crawl_max_depth,
        fast_deadline_seconds=settings.stage0_crawl_fast_deadline_seconds,
        fast_page_ceiling=settings.stage0_crawl_fast_page_ceiling,
        total_page_ceiling=settings.stage0_crawl_total_page_ceiling,
        worker_concurrency=settings.stage0_crawl_worker_concurrency,
        per_host_concurrency=settings.stage0_crawl_per_host_concurrency,
        lease_ttl_seconds=settings.stage0_crawl_lease_ttl_seconds,
        heartbeat_seconds=settings.stage0_crawl_heartbeat_seconds,
        request_timeout_seconds=settings.stage0_crawl_request_timeout_seconds,
        max_response_bytes=settings.stage0_crawl_max_response_bytes,
        allow_subdomains=settings.stage0_crawl_allow_subdomains,
        url_policy_version=settings.stage0_crawl_url_policy_version,
        provider_policy_version=_PROVIDER_POLICY_VERSION,
        robots_policy_version=ROBOTS_POLICY_VERSION,
    )


class _BoundedControlDocumentClient:
    """Fetch robots/sitemap documents through C3's DNS-pinned local transport."""

    def __init__(
        self,
        *,
        timeout_seconds: int,
        max_redirects: int = 5,
        allow_subdomains: bool = False,
    ) -> None:
        self._transport = ScraplingPinnedTransport()
        self._timeout_seconds = timeout_seconds
        self._max_redirects = max_redirects
        self._allow_subdomains = allow_subdomains

    async def fetch(self, url: str, *, allowed_domain: str) -> ScraplingTransportResponse:
        host = urlsplit(url).hostname
        if host is None:
            raise ValueError("control document URL has no host")
        allowed_hosts = {host, allowed_domain}
        # The common apex -> www canonical redirect remains an explicit same-registrable-domain
        # admission, and only when the run-pinned subdomain policy opts in. Arbitrary subdomains
        # are still admitted only when they are themselves the requested sitemap/robots host.
        if self._allow_subdomains:
            allowed_hosts.add(f"www.{allowed_domain}")
        return await self._transport.fetch(
            PageFetchRequest(
                operation_key=f"official-site-control:{uuid5(NAMESPACE_URL, url)}",
                requested_url=url,
                allowed_hosts=tuple(sorted(allowed_hosts)),
                timeout_seconds=self._timeout_seconds,
                max_response_bytes=_CONTROL_DOCUMENT_MAX_BYTES,
                accepted_mime_types=_CONTROL_DOCUMENT_MIME_TYPES,
                max_redirects=self._max_redirects,
                robots_decision_ref="control-document-preflight",
            )
        )


class LiveRobotsAuthorizer:
    """Lazy, bounded robots policy shared by seed discovery and every page admission."""

    policy_version = ROBOTS_POLICY_VERSION

    def __init__(self, *, client: _BoundedControlDocumentClient, allowed_domain: str) -> None:
        self._client = client
        self._allowed_domain = allowed_domain
        self._documents: dict[str, RobotsDocument] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def authorize(self, url: str) -> RobotsAuthorization:
        document = await self.document_for(url)
        decision = document.decide(user_agent="ClueBot", target_url=url)
        return RobotsAuthorization(
            allowed=decision.allowed,
            decision_ref=decision.decision_ref,
            reason=decision.reason,
        )

    async def document_for(self, url: str) -> RobotsDocument:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.hostname is None:
            raise ValueError("robots target must be an absolute HTTP(S) URL")
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        cached = self._documents.get(origin)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            cached = self._documents.get(origin)
            if cached is not None:
                return cached
            robots_url = f"{origin}/robots.txt"
            try:
                response = await self._client.fetch(robots_url, allowed_domain=self._allowed_domain)
                document = parse_robots(
                    response.content,
                    robots_url=robots_url,
                    media_type=media_type(header(response.headers, "content-type")),
                    http_status=response.http_status,
                    policy=RobotsParsePolicy(),
                )
            except Exception:  # fail closed; caller records a robots refusal, never spends
                document = parse_robots(
                    b"",
                    robots_url=robots_url,
                    media_type="text/plain",
                    http_status=503,
                    policy=RobotsParsePolicy(),
                )
            self._documents[origin] = document
            return document


class LiveSitemapSeedDiscoverer:
    """Bounded sitemap/index acquisition; emitted pages keep unknown graph depth."""

    def __init__(
        self,
        *,
        client: _BoundedControlDocumentClient,
        robots: LiveRobotsAuthorizer,
        allowed_domain: str,
        max_urls: int,
    ) -> None:
        self._client = client
        self._robots = robots
        self._allowed_domain = allowed_domain
        self._policy = SitemapParsePolicy(max_urls=max_urls)

    async def discover(
        self,
        *,
        root_url: str,
        url_policy: ConservativeUrlPolicy,
        discovery_policy: OfficialSiteDiscoveryPolicy,
    ) -> tuple[UrlObservation, ...]:
        document = await self._robots.document_for(root_url)
        parts = urlsplit(root_url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        roots = document.sitemap_urls or (f"{origin}/sitemap.xml",)
        pending = [(url, 0) for url in reversed(roots)]
        seen: set[str] = set()
        observations: list[UrlObservation] = []
        documents = 0
        while pending and documents < self._policy.max_index_documents:
            sitemap_url, depth = pending.pop()
            decision = url_policy.decide(sitemap_url)
            if not decision.admitted or decision.fetch_key is None:
                continue
            if decision.fetch_key in seen:
                continue
            seen.add(decision.fetch_key)
            try:
                response = await self._client.fetch(
                    decision.fetch_key, allowed_domain=self._allowed_domain
                )
                if not 200 <= response.http_status <= 299:
                    continue
                parsed = parse_sitemap(
                    SitemapPayload(
                        body=response.content,
                        media_type=(
                            media_type(header(response.headers, "content-type")) or "text/xml"
                        ),
                    ),
                    sitemap_url=decision.fetch_key,
                    policy=self._policy,
                )
            except Exception:
                continue
            documents += 1
            for page_url in parsed.page_urls:
                observations.append(
                    discovery_policy.sitemap(
                        SitemapEntry(
                            discovered_url=page_url,
                            sitemap_url=decision.fetch_key,
                        )
                    )
                )
                if len(observations) >= self._policy.max_urls:
                    return tuple(observations)
            if depth < self._policy.max_index_depth:
                pending.extend((child, depth + 1) for child in reversed(parsed.child_sitemap_urls))
        return tuple(observations)


class DbOfficialSiteCrawlEnqueuer:
    """Allowlist-gated, reference-only wake for one recon-owned crawl."""

    def __init__(self, *, settings: Settings, queue: WorkQueue | None = None) -> None:
        self._settings = settings
        self._queue = queue if queue is not None else DbWorkQueue()

    async def enqueue(self, *, workspace_id: str, recon_run_id: UUID) -> bool:
        if self._settings.stage0_official_site_crawl_mode == "off":
            return False
        if workspace_id not in self._settings.stage0_official_site_crawl_workspace_allowlist:
            return False
        work_id = WorkId(uuid5(NAMESPACE_URL, f"official-site-crawl:{recon_run_id}"))
        return bool(
            await self._queue.enqueue(
                kind=FleetTaskKind.OFFICIAL_SITE_CRAWL,
                work_id=work_id,
                dedup_key=f"official-site-crawl:{recon_run_id}",
                priority=-100,
                payload={"workspace_id": workspace_id, "recon_run_id": str(recon_run_id)},
                reopen_terminal=True,
            )
        )


class OfficialSiteCrawlWorkHandler:
    kind = FleetTaskKind.OFFICIAL_SITE_CRAWL

    def __init__(
        self,
        *,
        settings: Settings,
        lifecycle: OfficialSiteCrawlLifecycle,
        provider_key: str,
        conn_factory: ConnFactory = transaction,
        progress_sink: CrawlProgressSink | None = None,
    ) -> None:
        self._settings = settings
        self._lifecycle = lifecycle
        self._provider_key = provider_key
        self._conn_factory = conn_factory
        self._progress_sink = progress_sink or NullCrawlProgressSink()
        self._operations = PostgresOfficialSiteOperations(conn_factory=conn_factory)

    async def handle(self, context: WorkContext) -> WorkResult:
        workspace_id, recon_run_id = self._payload(context.payload)
        expected = uuid5(NAMESPACE_URL, f"official-site-crawl:{recon_run_id}")
        if UUID(str(context.work_id)) != expected:
            raise ValueError("official-site crawl work id disagrees with its recon reference")
        if self._settings.stage0_official_site_crawl_mode == "off":
            return WorkResult(outcome="disabled", references={})
        if workspace_id not in self._settings.stage0_official_site_crawl_workspace_allowlist:
            return WorkResult(outcome="not_allowlisted", references={})
        row = await self._recon_scope(workspace_id, recon_run_id)
        authoritative_ready = (
            self._settings.stage0_official_site_crawl_mode == "authoritative"
            and row.fast_status in {"running", "completed"}
            and row.client_entity_id is not None
        )
        shadow_ready = (
            self._settings.stage0_official_site_crawl_mode == "shadow"
            and row.fast_status == "completed"
            and row.fast_client_kb_version is not None
            and row.client_entity_id is not None
        )
        if not (authoritative_ready or shadow_ready):
            return WorkResult(
                outcome="awaiting_fast_client_kb",
                references={"recon_run_id": str(recon_run_id)},
                requeue=True,
            )
        assert row.client_entity_id is not None
        root_url = row.company_website
        if "://" not in root_url:
            root_url = f"https://{root_url}"
        domain = registrable_domain(root_url)
        if domain is None:
            raise ValueError("provisioned company website has no registrable domain")
        try:
            result = await self._lifecycle.run(
                OfficialSiteCrawlLifecycleRequest(
                    workspace_id=workspace_id,
                    brand_id=row.brand_id,
                    recon_run_id=recon_run_id,
                    root_url=root_url,
                    allowed_registrable_domain=domain,
                    config=crawl_contract_config(self._settings, provider_key=self._provider_key),
                    client_entity_id=row.client_entity_id,
                    fast_claim_run_id=row.fast_run_id,
                    background_claim_run_id=row.background_run_id,
                    extraction_model_id=self._settings.stage0_extraction_model,
                    extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                    extraction_schema_version=EXTRACTION_SCHEMA_VERSION,
                )
            )
        except OfficialSiteExtractionPending as pending:
            requeue_after = _recovery_requeue_delay(
                task_attempt=context.task_attempt,
                retry_after_seconds=None,
            )
            log.info(
                "stage0_official_site_crawl.extraction_pending",
                workspace_id=workspace_id,
                recon_run_id=str(recon_run_id),
                detail=str(pending),
                task_attempt=context.task_attempt,
                requeue_after_seconds=requeue_after.total_seconds(),
                scheduling_basis="exponential",
            )
            return WorkResult(
                outcome="extraction_pending",
                references={
                    "recon_run_id": str(recon_run_id),
                    "requeue_after_seconds": requeue_after.total_seconds(),
                },
                requeue=True,
                requeue_after=requeue_after,
            )
        except CrawlPhasePendingError as pending:
            requeue_after = _recovery_requeue_delay(
                task_attempt=context.task_attempt,
                retry_after_seconds=pending.retry_after_seconds,
            )
            log.info(
                "stage0_official_site_crawl.recovery_pending",
                workspace_id=workspace_id,
                recon_run_id=str(recon_run_id),
                crawl_run_id=str(pending.crawl_run_id),
                phase=pending.phase.value,
                blocker_count=pending.blockers,
                task_attempt=context.task_attempt,
                requeue_after_seconds=requeue_after.total_seconds(),
                scheduling_basis=(
                    "lease_or_retry_deadline"
                    if pending.retry_after_seconds is not None
                    else "exponential"
                ),
            )
            return WorkResult(
                outcome="recovery_pending",
                references={
                    "recon_run_id": str(recon_run_id),
                    "crawl_run_id": str(pending.crawl_run_id),
                    "phase": pending.phase.value,
                    "requeue_after_seconds": requeue_after.total_seconds(),
                },
                requeue=True,
                requeue_after=requeue_after,
            )
        except Exception as exc:
            try:
                progress = await self._operations.read_progress_for_recon(
                    workspace_id=workspace_id, recon_run_id=recon_run_id
                )
                if progress is not None:
                    kind = CrawlProgressEventKind.FAILED
                    await self._progress_sink.emit(
                        CrawlProgressEvent(
                            event_id=progress_event_id(
                                kind,
                                progress.crawl_run_id,
                                subject=type(exc).__name__,
                            ),
                            kind=kind,
                            workspace_id=workspace_id,
                            crawl_run_id=progress.crawl_run_id,
                            recon_run_id=recon_run_id,
                            phase=progress.phase,
                            failure_code=type(exc).__name__,
                            outcome="failed",
                        )
                    )
            except Exception:
                # A visibility/read failure must never replace the worker's original exception.
                pass
            raise
        log.info(
            "stage0_official_site_crawl.completed",
            workspace_id=workspace_id,
            recon_run_id=str(recon_run_id),
            crawl_run_id=str(result.crawl_run_id),
            outcome=result.status.value,
            fast_checkpoint_id=str(result.fast_checkpoint.checkpoint_id),
            background_checkpoint_id=str(result.background_checkpoint.checkpoint_id),
            fast_snapshot_count=len(result.fast_checkpoint.snapshot_ids),
            background_snapshot_count=len(result.background_checkpoint.snapshot_ids),
        )
        return WorkResult(
            outcome=result.status.value,
            references={
                "recon_run_id": str(recon_run_id),
                "crawl_run_id": str(result.crawl_run_id),
                "fast_checkpoint_id": str(result.fast_checkpoint.checkpoint_id),
                "background_checkpoint_id": str(result.background_checkpoint.checkpoint_id),
            },
        )

    async def _recon_scope(self, workspace_id: str, recon_run_id: UUID) -> _ReconScope:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT recon.brand_id, recon.client_entity_id, recon.fast_run_id,
                                   recon.background_run_id, recon.fast_status,
                                   recon.fast_client_kb_version, provisioning.company_website
                            FROM recon_run AS recon
                            JOIN self_serve_provisioning AS provisioning
                              ON provisioning.workspace_id = recon.workspace_id
                             AND provisioning.brand_id = recon.brand_id
                            WHERE recon.id = :recon_run_id
                              AND recon.workspace_id = :workspace_id
                            """
                        ),
                        {"workspace_id": workspace_id, "recon_run_id": recon_run_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ValueError("official-site crawl cannot rehydrate its recon scope")
        return _ReconScope(
            brand_id=row["brand_id"],
            client_entity_id=row["client_entity_id"],
            fast_run_id=row["fast_run_id"],
            background_run_id=row["background_run_id"],
            fast_status=row["fast_status"],
            fast_client_kb_version=row["fast_client_kb_version"],
            company_website=row["company_website"],
        )

    @staticmethod
    def _payload(payload: dict[str, JsonValue]) -> tuple[str, UUID]:
        workspace_id = payload.get("workspace_id")
        recon_run_id = payload.get("recon_run_id")
        if not isinstance(workspace_id, str) or not isinstance(recon_run_id, str):
            raise ValueError("invalid official-site crawl task payload")
        return workspace_id, UUID(recon_run_id)


@dataclass(frozen=True, slots=True)
class OfficialSiteCrawlFleetComposition:
    enqueuer: DbOfficialSiteCrawlEnqueuer
    handler: OfficialSiteCrawlWorkHandler | None


def build_official_site_crawl_fleet(
    *,
    settings: Settings,
    secrets: Secrets,
    storage: StorageBackend,
    gateway: LLMGateway | None = None,
    conn_factory: ConnFactory = transaction,
    queue: WorkQueue | None = None,
) -> OfficialSiteCrawlFleetComposition:
    """Build C6 or return an off-mode enqueuer that originates no crawl work."""

    enqueuer = DbOfficialSiteCrawlEnqueuer(settings=settings, queue=queue)
    if settings.stage0_official_site_crawl_mode == "off":
        return OfficialSiteCrawlFleetComposition(enqueuer=enqueuer, handler=None)
    if settings.stage0_official_site_crawl_mode == "authoritative" and gateway is None:
        raise RuntimeError("authoritative Stage-0 official-site crawling requires a model gateway")
    if (
        settings.stage0_official_site_crawl_mode == "authoritative"
        and secrets.openrouter_api_key is None
    ):
        raise RuntimeError(
            "authoritative Stage-0 official-site crawling requires an OpenRouter key"
        )
    if settings.stage0_page_fetcher == "firecrawl":
        secret = secrets.firecrawl_api_key
        if secret is None:
            raise RuntimeError("enabled Firecrawl official-site crawling requires its API key")
        fetcher: PageFetcher = FirecrawlPageFetcher(api_key=secret.get_secret_value())
    else:
        fetcher = ScraplingPageFetcher()

    repository = PostgresCrawlRepository(conn_factory=conn_factory)
    progress_emitter = DbOfficialSiteProgressEmitter(conn_factory=conn_factory)
    artifacts = OfficialSiteArtifactStore(storage=storage, conn_factory=conn_factory)
    resolver = SystemAddressResolver()
    config = crawl_contract_config(settings, provider_key=fetcher.capabilities.provider_key)
    safety = CrawlSafetyPolicy(
        max_redirects=config.max_redirects,
        max_response_bytes=config.max_response_bytes,
    )
    control_client = _BoundedControlDocumentClient(
        timeout_seconds=config.request_timeout_seconds,
        max_redirects=config.max_redirects,
        allow_subdomains=config.allow_subdomains,
    )

    def coordinator_factory(
        *,
        url_policy: ConservativeUrlPolicy,
        discovery_policy: OfficialSiteDiscoveryPolicy,
    ) -> ConcurrentCrawlCoordinator:
        robots = LiveRobotsAuthorizer(
            client=control_client,
            allowed_domain=url_policy.allowed_registrable_domain,
        )
        return ConcurrentCrawlCoordinator(
            repository=repository,
            artifacts=artifacts,
            fetcher=fetcher,
            discovery_policy=discovery_policy,
            url_policy=url_policy,
            resolver=resolver,
            safety=safety,
            robots=robots,
            progress_sink=progress_emitter,
        )

    # One robots cache must serve both seeding and page authorization. The lifecycle constructs
    # its URL policy later, so the seed authorizer is rooted at the admitted workspace domain by
    # the discoverer's call; coordinator instances keep a separate equivalent bounded cache.
    class _RunScopedSeedDiscoverer:
        async def discover(
            self,
            *,
            root_url: str,
            url_policy: ConservativeUrlPolicy,
            discovery_policy: OfficialSiteDiscoveryPolicy,
        ) -> tuple[UrlObservation, ...]:
            robots = LiveRobotsAuthorizer(
                client=control_client,
                allowed_domain=url_policy.allowed_registrable_domain,
            )
            return await LiveSitemapSeedDiscoverer(
                client=control_client,
                robots=robots,
                allowed_domain=url_policy.allowed_registrable_domain,
                max_urls=min(config.total_page_ceiling * 4, 10_000),
            ).discover(
                root_url=root_url,
                url_policy=url_policy,
                discovery_policy=discovery_policy,
            )

    lifecycle = OfficialSiteCrawlLifecycle(
        repository=repository,
        coordinator_factory=coordinator_factory,
        seed_discoverer=_RunScopedSeedDiscoverer(),
        materializer=(
            GroundedOfficialSiteMaterializer(
                gateway=gateway,
                storage=storage,
                conn_factory=conn_factory,
                extraction_concurrency=settings.stage0_extraction_concurrency,
                client_kb_committer=_AuthoritativeClientKbCommitter(conn_factory),
            )
            if settings.stage0_official_site_crawl_mode == "authoritative" and gateway is not None
            else None
        ),
        progress_sink=progress_emitter,
    )
    return OfficialSiteCrawlFleetComposition(
        enqueuer=enqueuer,
        handler=OfficialSiteCrawlWorkHandler(
            settings=settings,
            lifecycle=lifecycle,
            provider_key=fetcher.capabilities.provider_key,
            conn_factory=conn_factory,
            progress_sink=progress_emitter,
        ),
    )


__all__ = [
    "DbOfficialSiteCrawlEnqueuer",
    "LiveRobotsAuthorizer",
    "LiveSitemapSeedDiscoverer",
    "OfficialSiteCrawlFleetComposition",
    "OfficialSiteCrawlWorkHandler",
    "build_official_site_crawl_fleet",
    "crawl_contract_config",
]
