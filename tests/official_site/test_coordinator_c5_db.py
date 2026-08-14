"""C5 PostgreSQL worker-pool, fairness, heartbeat, graph, and recovery acceptance."""

from __future__ import annotations

import asyncio
import hashlib
import multiprocessing
import os
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async

from clue_db import DATABASE_URL_ENV, db_lifespan
from clue_research.official_site import (
    ClaimNextRequest,
    ClaimReconciliationRequest,
    ConcurrentCrawlCoordinator,
    CoordinatorPhaseRequest,
    CostKind,
    CrawlMode,
    CrawlPhase,
    CrawlRunCreate,
    CrawlRunStatus,
    CrawlSafetyPolicy,
    LinkObservation,
    OfficialSiteArtifactStore,
    OfficialSiteCrawlContractConfig,
    OfficialSiteDiscoveryPolicy,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    PostgresCrawlRepository,
    RetryClass,
    SitemapEntry,
    SpendStatus,
    StaticAddressResolver,
    StaticRobotsAuthorizer,
    UrlPolicyConfig,
)
from clue_research.official_site.contracts import CrawlLease, DiscoveryBatch
from clue_research.official_site.url_policy import URL_POLICY_VERSION, ConservativeUrlPolicy
from clue_storage import FsStorage

pytestmark = pytest.mark.usefixtures("require_official_site_db")

_PUBLIC_IP = "93.184.216.34"


def _config(
    *,
    workers: int = 2,
    per_host: int = 2,
    fast_ceiling: int = 12,
    total_ceiling: int = 100,
) -> OfficialSiteCrawlContractConfig:
    return OfficialSiteCrawlContractConfig(
        crawl_mode=CrawlMode.SHADOW,
        provider_key="fixture",
        fast_deadline_seconds=40,
        fast_page_ceiling=fast_ceiling,
        total_page_ceiling=total_ceiling,
        worker_concurrency=workers,
        per_host_concurrency=per_host,
        lease_ttl_seconds=3,
        heartbeat_seconds=1,
        request_timeout_seconds=5,
        max_response_bytes=1_000_000,
        max_redirects=5,
        allow_subdomains=True,
        url_policy_version=URL_POLICY_VERSION,
        provider_policy_version="provider-v1",
        robots_policy_version="robots-v1",
    )


async def _seed_scope(conn: Any) -> tuple[str, str, UUID]:
    workspace_id = f"official-site-c5-{uuid4()}"
    brand_id = f"brand-{uuid4()}"
    recon_run_id = uuid4()
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:id, 'C5 Test')"),
        {"id": workspace_id},
    )
    await conn.execute(
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) "
            "VALUES (:brand_id, :workspace_id, 'C5 Brand')"
        ),
        {"brand_id": brand_id, "workspace_id": workspace_id},
    )
    await conn.execute(
        text(
            """
            INSERT INTO recon_run (
                id, workspace_id, brand_id, dedupe_hash, dedupe_expires_at,
                fast_run_id, background_run_id, fast_budget_cents,
                background_budget_cents, recipe_version, skill_version
            ) VALUES (
                :id, :workspace_id, :brand_id, :dedupe_hash, now() + interval '1 hour',
                :fast_run_id, :background_run_id, 0, 0, 'test-v1', 'test-v1'
            )
            """
        ),
        {
            "id": recon_run_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "dedupe_hash": hashlib.sha256(str(recon_run_id).encode()).hexdigest(),
            "fast_run_id": uuid4(),
            "background_run_id": uuid4(),
        },
    )
    return workspace_id, brand_id, recon_run_id


async def _cleanup_scope(conn: Any, workspace_id: str) -> None:
    run_ids = (
        (
            await conn.execute(
                text("SELECT id FROM official_site_crawl_run WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            )
        )
        .scalars()
        .all()
    )
    if run_ids:
        params = {"run_ids": run_ids}
        for table in (
            "official_site_corpus_checkpoint",
            "official_site_alias_observation",
            "official_site_page_snapshot",
            "official_site_fetch_attempt",
            "official_site_link_edge",
            "official_site_url_observation",
            "official_site_crawl_page",
        ):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE crawl_run_id = ANY(CAST(:run_ids AS uuid[]))"),
                params,
            )
        await conn.execute(
            text("DELETE FROM official_site_crawl_run WHERE id = ANY(CAST(:run_ids AS uuid[]))"),
            params,
        )
    await conn.execute(
        text("DELETE FROM artifact WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(
        text("DELETE FROM recon_run WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(
        text("DELETE FROM brand WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(
        text("DELETE FROM workspace WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )


def _url_policy(root: str) -> ConservativeUrlPolicy:
    return ConservativeUrlPolicy(
        UrlPolicyConfig(
            root_url=root,
            allowed_registrable_domain="example.com",
            allow_subdomains=True,
        )
    )


async def _create_run(
    repository: PostgresCrawlRepository,
    *,
    workspace_id: str,
    brand_id: str,
    recon_run_id: UUID,
    urls: tuple[str, ...],
    config: OfficialSiteCrawlContractConfig,
    background: bool = False,
) -> UUID:
    policy = _url_policy(urls[0])
    discovery = OfficialSiteDiscoveryPolicy(url_policy=policy)
    root_observation = discovery.root(urls[0])
    assert root_observation.fetch_key is not None
    run = await repository.create_or_get_run(
        CrawlRunCreate(
            workspace_id=workspace_id,
            brand_id=brand_id,
            recon_run_id=recon_run_id,
            root_discovered_url=urls[0],
            root_fetch_key=root_observation.fetch_key,
            allowed_registrable_domain="example.com",
            config=config,
        )
    )
    observations = [root_observation]
    observations.extend(
        discovery.sitemap(
            SitemapEntry(discovered_url=url, sitemap_url="https://example.com/sitemap.xml")
        )
        for url in urls[1:]
    )
    await repository.record_discoveries(
        DiscoveryBatch(
            workspace_id=workspace_id,
            crawl_run_id=run.crawl_run_id,
            observations=tuple(observations),
        )
    )
    assert await repository.transition_run(
        workspace_id=workspace_id,
        crawl_run_id=run.crawl_run_id,
        expected=CrawlRunStatus.QUEUED,
        next_status=CrawlRunStatus.FAST_ACTIVE,
    )
    if background:
        for expected, next_status in (
            (CrawlRunStatus.FAST_ACTIVE, CrawlRunStatus.FAST_CLOSING),
            (CrawlRunStatus.FAST_CLOSING, CrawlRunStatus.FAST_COMPLETE),
            (CrawlRunStatus.FAST_COMPLETE, CrawlRunStatus.BACKGROUND_ACTIVE),
        ):
            assert await repository.transition_run(
                workspace_id=workspace_id,
                crawl_run_id=run.crawl_run_id,
                expected=expected,
                next_status=next_status,
            )
    return run.crawl_run_id


class _ScenarioFetcher:
    capabilities = PageFetcherCapabilities(
        provider_key="fixture",
        supports_operation_lookup=False,
        supports_idempotency_key=False,
        reports_redirect_chain=True,
        reports_outgoing_links=True,
        reports_actual_cost=False,
        reports_provider_receipt=True,
        proves_no_spend_before_dispatch=False,
    )

    def __init__(
        self,
        *,
        links: dict[str, tuple[str, ...]] | None = None,
        delays: dict[str, float] | None = None,
        retry_no_spend: bool = False,
    ) -> None:
        self.links = links or {}
        self.delays = delays or {}
        self.retry_no_spend = retry_no_spend
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.active_by_host: Counter[str] = Counter()
        self.max_by_host: Counter[str] = Counter()
        self.started = asyncio.Event()

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        from urllib.parse import urlsplit

        self.calls.append(request.requested_url)
        call_number = len(self.calls)
        host = urlsplit(request.requested_url).hostname or ""
        self.active += 1
        self.active_by_host[host] += 1
        self.max_active = max(self.max_active, self.active)
        self.max_by_host[host] = max(self.max_by_host[host], self.active_by_host[host])
        self.started.set()
        try:
            await asyncio.sleep(self.delays.get(request.requested_url, 0))
            if self.retry_no_spend:
                return PageFetchResult(
                    provider_key="fixture",
                    requested_url=request.requested_url,
                    provider_status="temporary_unavailable",
                    fetched_at=datetime.now(UTC),
                    cost_kind=CostKind.NONE,
                    spend_status=SpendStatus.NO_SPEND,
                    retry_class=RetryClass.RETRYABLE_NO_SPEND,
                )
            outgoing = tuple(
                LinkObservation(discovered_url=url, link_text="link")
                for url in self.links.get(request.requested_url, ())
            )
            anchors = "".join(f'<a href="{link.discovered_url}">link</a>' for link in outgoing)
            return PageFetchResult(
                provider_key="fixture",
                provider_request_id=f"fixture-{call_number}-{hashlib.sha256(request.requested_url.encode()).hexdigest()[:12]}",
                requested_url=request.requested_url,
                final_url=request.requested_url,
                provider_status="ok",
                http_status=200,
                content=f"<html>{request.requested_url}{anchors}</html>".encode(),
                media_type="text/html",
                outgoing_links=outgoing,
                fetched_at=datetime.now(UTC),
                cost_cents=Decimal(0),
                cost_kind=CostKind.ESTIMATED,
                spend_status=SpendStatus.NO_SPEND,
                retry_class=RetryClass.SUCCESS,
                receipt={"request_id": f"fixture-{call_number}"},
            )
        finally:
            self.active -= 1
            self.active_by_host[host] -= 1


class _CountingRobots:
    policy_version = "robots-v1"

    def __init__(self) -> None:
        self.calls = 0

    async def authorize(self, url: str) -> Any:
        from clue_research.official_site import RobotsAuthorization

        self.calls += 1
        return RobotsAuthorization(True, f"robots:{url}", "allowed")


class _LoseCompletionOnceRepository:
    def __init__(self, delegate: PostgresCrawlRepository) -> None:
        self.delegate = delegate
        self.remaining = 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def complete_page(self, lease: CrawlLease, *, snapshot_id: UUID) -> bool:
        if self.remaining:
            self.remaining -= 1
            return False
        return await self.delegate.complete_page(lease, snapshot_id=snapshot_id)


def _coordinator(
    *,
    repository: Any,
    storage_path: Path,
    root: str,
    fetcher: _ScenarioFetcher,
    resolver_answers: dict[str, tuple[str, ...]] | None = None,
    robots: Any | None = None,
) -> ConcurrentCrawlCoordinator:
    policy = _url_policy(root)
    answers: dict[str, tuple[str, ...] | Exception]
    if resolver_answers is not None:
        answers = cast(dict[str, tuple[str, ...] | Exception], resolver_answers)
    else:
        answers = {
            "example.com": (_PUBLIC_IP,),
            "a.example.com": (_PUBLIC_IP,),
            "b.example.com": (_PUBLIC_IP,),
            "c.example.com": (_PUBLIC_IP,),
        }
    return ConcurrentCrawlCoordinator(
        repository=repository,
        artifacts=OfficialSiteArtifactStore(storage=FsStorage(storage_path)),
        fetcher=fetcher,
        discovery_policy=OfficialSiteDiscoveryPolicy(url_policy=policy),
        url_policy=policy,
        resolver=StaticAddressResolver(answers),
        safety=CrawlSafetyPolicy(max_response_bytes=1_000_000, max_redirects=5),
        robots=robots or StaticRobotsAuthorizer(policy_version="robots-v1"),
    )


def _phase_request(
    workspace_id: str,
    run_id: UUID,
    config: OfficialSiteCrawlContractConfig,
    *,
    phase: CrawlPhase = CrawlPhase.FAST,
    idle_polls: int = 12,
) -> CoordinatorPhaseRequest:
    return CoordinatorPhaseRequest(
        workspace_id=workspace_id,
        crawl_run_id=run_id,
        phase=phase,
        config=config,
        worker_id_prefix=f"c5-{uuid4()}",
        idle_poll_seconds=0.03,
        max_idle_polls=idle_polls,
    )


def _claim_process(
    database_url: str,
    workspace_id: str,
    run_id: UUID,
    worker_id: str,
    start: Any,
    output: Any,
) -> None:
    os.environ[DATABASE_URL_ENV] = database_url
    start.wait(timeout=10)

    async def _run() -> None:
        async with db_lifespan():
            lease = await PostgresCrawlRepository().claim_next(
                ClaimNextRequest(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    worker_id=worker_id,
                    eligible_phase=CrawlPhase.FAST,
                    lease_ttl_seconds=30,
                )
            )
        output.put(None if lease is None else lease.requested_url)

    asyncio.run(_run())


def _multiprocess_claims(workspace_id: str, run_id: UUID, *, count: int = 4) -> list[str | None]:
    database_url = os.environ[DATABASE_URL_ENV]
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    output = context.Queue()
    processes = [
        context.Process(
            target=_claim_process,
            args=(database_url, workspace_id, run_id, f"process-{index}", start, output),
        )
        for index in range(count)
    ]
    for process in processes:
        process.start()
    start.set()
    results = [output.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    return results


def test_fast_category_quotas_are_deterministic() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                config = _config(workers=10, per_host=10)
                urls = (
                    "https://example.com/",
                    "https://example.com/product/one",
                    "https://example.com/product/two",
                    "https://example.com/product/three",
                    "https://example.com/product/four",
                    "https://example.com/product/five",
                    "https://example.com/pricing",
                    "https://example.com/customers/acme",
                    "https://example.com/about",
                )
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=urls,
                    config=config,
                )
                claimed = []
                for index in range(6):
                    lease = await repository.claim_next(
                        ClaimNextRequest(
                            workspace_id=workspace_id,
                            crawl_run_id=run_id,
                            worker_id=f"quota-{index}",
                            eligible_phase=CrawlPhase.FAST,
                            lease_ttl_seconds=30,
                        )
                    )
                    assert lease is not None
                    claimed.append(lease.requested_url)
                assert claimed[0] == urls[0]
                assert set(claimed[1:4]).issubset(set(urls[1:6]))
                assert len(set(claimed[1:4])) == 3
                assert claimed[4:] == [urls[6], urls[7]]
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_multiprocess_claims_enforce_global_and_per_host_capacity() -> None:
    async def _seed(
        urls: tuple[str, ...], config: OfficialSiteCrawlContractConfig
    ) -> tuple[str, UUID]:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
            run_id = await _create_run(
                PostgresCrawlRepository(),
                workspace_id=workspace_id,
                brand_id=brand_id,
                recon_run_id=recon_run_id,
                urls=urls,
                config=config,
            )
            return workspace_id, run_id

    async def _cleanup(workspace_id: str) -> None:
        async with db_lifespan() as engine, engine.begin() as conn:
            await _cleanup_scope(conn, workspace_id)

    global_workspace, global_run = run_async(
        _seed(
            (
                "https://example.com/",
                "https://a.example.com/product/a",
                "https://b.example.com/product/b",
                "https://c.example.com/product/c",
            ),
            _config(workers=2, per_host=2),
        )
    )
    try:
        global_results = _multiprocess_claims(global_workspace, global_run)
        assert len([result for result in global_results if result is not None]) == 2
    finally:
        run_async(_cleanup(global_workspace))

    host_workspace, host_run = run_async(
        _seed(
            (
                "https://example.com/",
                "https://example.com/product/a",
                "https://example.com/product/b",
                "https://example.com/product/c",
            ),
            _config(workers=4, per_host=1),
        )
    )
    try:
        host_results = _multiprocess_claims(host_workspace, host_run)
        assert len([result for result in host_results if result is not None]) == 1
    finally:
        run_async(_cleanup(host_workspace))


def test_background_claim_yields_to_claimable_fast_work_across_runs() -> None:
    async def _run() -> None:
        workspaces: list[str] = []
        async with db_lifespan() as engine:
            try:
                repository = PostgresCrawlRepository()
                runs = []
                for is_background in (False, True):
                    async with engine.begin() as conn:
                        workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                    workspaces.append(workspace_id)
                    run_id = await _create_run(
                        repository,
                        workspace_id=workspace_id,
                        brand_id=brand_id,
                        recon_run_id=recon_run_id,
                        urls=("https://example.com/",),
                        config=_config(workers=2, per_host=2),
                        background=is_background,
                    )
                    runs.append((workspace_id, run_id))
                fast_scope, fast_run = runs[0]
                background_scope, background_run = runs[1]
                assert (
                    await repository.claim_next(
                        ClaimNextRequest(
                            workspace_id=background_scope,
                            crawl_run_id=background_run,
                            worker_id="background-first",
                            eligible_phase=CrawlPhase.BACKGROUND,
                            lease_ttl_seconds=30,
                        )
                    )
                    is None
                )
                fast = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=fast_scope,
                        crawl_run_id=fast_run,
                        worker_id="fast",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=30,
                    )
                )
                assert fast is not None
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE official_site_crawl_page "
                            "SET lease_acquired_at = now() - interval '2 seconds', "
                            "lease_expires_at = now() - interval '1 second' "
                            "WHERE id = :page_id"
                        ),
                        {"page_id": fast.page_id},
                    )
                assert (
                    await repository.claim_next(
                        ClaimNextRequest(
                            workspace_id=background_scope,
                            crawl_run_id=background_run,
                            worker_id="background-after-fast-expiry",
                            eligible_phase=CrawlPhase.BACKGROUND,
                            lease_ttl_seconds=30,
                        )
                    )
                    is None
                )
                reclaimed_fast = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=fast_scope,
                        crawl_run_id=fast_run,
                        worker_id="fast-replacement",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=30,
                    )
                )
                assert reclaimed_fast is not None
                assert reclaimed_fast.lease_generation == fast.lease_generation + 1
                background = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=background_scope,
                        crawl_run_id=background_run,
                        worker_id="background-second",
                        eligible_phase=CrawlPhase.BACKGROUND,
                        lease_ttl_seconds=30,
                    )
                )
                assert background is not None
            finally:
                for workspace_id in workspaces:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_background_reconciliation_yields_to_claimable_fast_work() -> None:
    async def _run() -> None:
        workspaces: list[str] = []
        async with db_lifespan() as engine:
            try:
                repository = PostgresCrawlRepository()
                async with engine.begin() as conn:
                    background_scope, background_brand, background_recon = await _seed_scope(conn)
                workspaces.append(background_scope)
                background_run = await _create_run(
                    repository,
                    workspace_id=background_scope,
                    brand_id=background_brand,
                    recon_run_id=background_recon,
                    urls=("https://example.com/",),
                    config=_config(workers=2, per_host=2),
                    background=True,
                )
                ambiguous_lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=background_scope,
                        crawl_run_id=background_run,
                        worker_id="background-ambiguous",
                        eligible_phase=CrawlPhase.BACKGROUND,
                        lease_ttl_seconds=30,
                    )
                )
                assert ambiguous_lease is not None
                attempt = await repository.begin_attempt(
                    ambiguous_lease,
                    provider_key="fixture",
                    operation_key=f"ambiguous:{uuid4()}",
                )
                assert await repository.mark_attempt_dispatched(ambiguous_lease, attempt)
                ambiguous = PageFetchResult(
                    provider_key="fixture",
                    requested_url=ambiguous_lease.requested_url,
                    provider_status="unknown",
                    fetched_at=datetime.now(UTC),
                    cost_kind=CostKind.NONE,
                    spend_status=SpendStatus.SPEND_UNKNOWN,
                    retry_class=RetryClass.AMBIGUOUS,
                )
                assert await repository.record_provider_result(
                    ambiguous_lease, attempt, ambiguous.metadata()
                )

                async with engine.begin() as conn:
                    fast_scope, fast_brand, fast_recon = await _seed_scope(conn)
                workspaces.append(fast_scope)
                await _create_run(
                    repository,
                    workspace_id=fast_scope,
                    brand_id=fast_brand,
                    recon_run_id=fast_recon,
                    urls=("https://example.com/",),
                    config=_config(workers=2, per_host=2),
                )
                assert (
                    await repository.claim_reconciliation(
                        ClaimReconciliationRequest(
                            workspace_id=background_scope,
                            crawl_run_id=background_run,
                            worker_id="background-reconciliation",
                            lease_ttl_seconds=30,
                        )
                    )
                    is None
                )
            finally:
                for workspace_id in workspaces:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_coordinator_heartbeats_and_shorter_path_expands_without_refetch(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                config = _config(workers=2, per_host=2)
                root = "https://example.com/"
                company = "https://example.com/about"
                team = "https://example.com/team"
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root, company),
                    config=config,
                )
                fetcher = _ScenarioFetcher(
                    links={root: (company,), company: (team,)},
                    delays={root: 1.15, company: 0.05},
                )
                result = await _coordinator(
                    repository=repository,
                    storage_path=tmp_path / "shorter-path",
                    root=root,
                    fetcher=fetcher,
                ).run_phase(_phase_request(workspace_id, run_id, config, idle_polls=60))
                async with engine.connect() as conn:
                    rows = (
                        (
                            await conn.execute(
                                text(
                                    "SELECT fetch_key, graph_depth, state "
                                    "FROM official_site_crawl_page "
                                    "WHERE crawl_run_id = :run_id ORDER BY fetch_key"
                                ),
                                {"run_id": run_id},
                            )
                        )
                        .mappings()
                        .all()
                    )
                by_url = {row["fetch_key"]: (row["graph_depth"], row["state"]) for row in rows}
                assert Counter(fetcher.calls) == Counter({root: 1, company: 1, team: 1}), (
                    result,
                    by_url,
                )
                assert result.heartbeat_renewals >= 1
                assert result.pages_completed == 3
                assert fetcher.max_active <= 2
                assert by_url[company] == (1, "fetched")
                assert by_url[team] == (2, "fetched")
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_idle_workers_stay_available_for_links_discovered_by_a_slow_page(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                config = _config(workers=3, per_host=3)
                root = "https://example.com/"
                first = "https://example.com/product/first"
                second = "https://example.com/product/second"
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root,),
                    config=config,
                )
                fetcher = _ScenarioFetcher(
                    links={root: (first, second)},
                    delays={root: 0.3, first: 0.2, second: 0.2},
                )
                result = await _coordinator(
                    repository=repository,
                    storage_path=tmp_path / "late-links",
                    root=root,
                    fetcher=fetcher,
                ).run_phase(_phase_request(workspace_id, run_id, config, idle_polls=4))
                assert Counter(fetcher.calls) == Counter({root: 1, first: 1, second: 1})
                assert fetcher.max_active == 2
                assert result.pages_completed == 3
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_graceful_shutdown_finishes_active_call_and_stops_new_claims(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                config = _config(workers=1, per_host=1)
                root = "https://example.com/"
                second = "https://example.com/product/second"
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root, second),
                    config=config,
                )
                fetcher = _ScenarioFetcher(delays={root: 0.25})
                coordinator = _coordinator(
                    repository=repository,
                    storage_path=tmp_path / "shutdown",
                    root=root,
                    fetcher=fetcher,
                )
                stop = asyncio.Event()
                task = asyncio.create_task(
                    coordinator.run_phase(
                        _phase_request(workspace_id, run_id, config), stop_event=stop
                    )
                )
                await asyncio.wait_for(fetcher.started.wait(), timeout=2)
                stop.set()
                result = await task
                assert result.stopped
                assert fetcher.calls == [root]
                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert progress.fetched == 1
                assert progress.queued == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_retryable_no_spend_is_bounded_and_preflight_refusal_never_calls_provider(
    tmp_path: Path,
) -> None:
    async def _run_retry() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                config = _config(workers=1, per_host=1)
                root = "https://example.com/"
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root,),
                    config=config,
                )
                fetcher = _ScenarioFetcher(retry_no_spend=True)
                await _coordinator(
                    repository=repository,
                    storage_path=tmp_path / "retry",
                    root=root,
                    fetcher=fetcher,
                ).run_phase(_phase_request(workspace_id, run_id, config, idle_polls=20))
                assert fetcher.calls == [root, root, root]
                async with engine.connect() as conn:
                    state, attempts, reason = (
                        await conn.execute(
                            text(
                                "SELECT state, attempt_count, terminal_reason "
                                "FROM official_site_crawl_page WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).one()
                assert (state, attempts, reason) == ("failed", 3, "no_spend_retry_exhausted")
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    async def _run_refusal() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                config = _config(workers=1, per_host=1)
                root = "https://example.com/"
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root,),
                    config=config,
                )
                fetcher = _ScenarioFetcher()
                robots = _CountingRobots()
                await _coordinator(
                    repository=repository,
                    storage_path=tmp_path / "refusal",
                    root=root,
                    fetcher=fetcher,
                    resolver_answers={"example.com": ("127.0.0.1",)},
                    robots=robots,
                ).run_phase(_phase_request(workspace_id, run_id, config))
                assert fetcher.calls == []
                assert robots.calls == 0
                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert progress.refused == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run_retry())
    run_async(_run_refusal())


def test_link_discovery_replays_after_completion_crash_without_provider_refetch(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                config = _config(workers=1, per_host=1)
                root = "https://example.com/"
                linked = "https://example.com/about"
                base = PostgresCrawlRepository()
                run_id = await _create_run(
                    base,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=(root,),
                    config=config,
                )
                fetcher = _ScenarioFetcher(links={root: (linked,)})
                failing = _LoseCompletionOnceRepository(base)
                first = await _coordinator(
                    repository=failing,
                    storage_path=tmp_path / "completion-crash",
                    root=root,
                    fetcher=fetcher,
                ).run_phase(_phase_request(workspace_id, run_id, config))
                assert first.fenced_workers == 1
                assert fetcher.calls == [root]
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE official_site_crawl_page "
                            "SET lease_acquired_at = now() - interval '2 seconds', "
                            "lease_expires_at = now() - interval '1 second' "
                            "WHERE crawl_run_id = :run_id "
                            "AND state = 'persistence_pending'"
                        ),
                        {"run_id": run_id},
                    )
                second = await _coordinator(
                    repository=base,
                    storage_path=tmp_path / "completion-crash",
                    root=root,
                    fetcher=fetcher,
                ).run_phase(_phase_request(workspace_id, run_id, config))
                assert second.persistence_claims == 1
                assert Counter(fetcher.calls)[root] == 1
                async with engine.connect() as conn:
                    snapshots = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_page_snapshot "
                                "WHERE crawl_run_id = :run_id AND requested_url = :root"
                            ),
                            {"run_id": run_id, "root": root},
                        )
                    ).scalar_one()
                    linked_observations = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_url_observation "
                                "WHERE crawl_run_id = :run_id AND discovered_url = :url"
                            ),
                            {"run_id": run_id, "url": linked},
                        )
                    ).scalar_one()
                assert snapshots == 1
                assert linked_observations == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())
