"""C4 durable acquisition, artifact, recovery, spend, and DSAR acceptance."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async

from clue_db import db_lifespan
from clue_research.official_site import (
    AcquisitionFenceLostError,
    AcquisitionPersistencePendingError,
    ClaimNextRequest,
    ClaimPersistenceRequest,
    ClaimReconciliationRequest,
    CostKind,
    CrawlEligibility,
    CrawlMode,
    CrawlPhase,
    CrawlRunCreate,
    CrawlRunStatus,
    DiscoveredVia,
    DurablePageAcquirer,
    OfficialSiteArtifactStore,
    OfficialSiteCrawlContractConfig,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    PolicyOutcome,
    PostgresCrawlRepository,
    RetryClass,
    SpendStatus,
    UrlObservation,
)
from clue_research.official_site.contracts import DiscoveryBatch
from clue_storage import FsStorage, StorageBackend, StorageError

pytestmark = pytest.mark.usefixtures("require_official_site_db")


def _config(*, provider_key: str = "fixture") -> OfficialSiteCrawlContractConfig:
    return OfficialSiteCrawlContractConfig(
        crawl_mode=CrawlMode.SHADOW,
        provider_key=provider_key,
        fast_deadline_seconds=40,
        fast_page_ceiling=12,
        total_page_ceiling=100,
        worker_concurrency=4,
        per_host_concurrency=4,
        lease_ttl_seconds=90,
        heartbeat_seconds=20,
        request_timeout_seconds=30,
        max_response_bytes=1_000_000,
        max_redirects=5,
        url_policy_version="url-v1",
        provider_policy_version="provider-v1",
        robots_policy_version="robots-v1",
    )


async def _seed_scope(conn: Any) -> tuple[str, str, UUID]:
    workspace_id = f"official-site-c4-{uuid4()}"
    brand_id = f"brand-{uuid4()}"
    recon_run_id = uuid4()
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:id, 'C4 Test')"),
        {"id": workspace_id},
    )
    await conn.execute(
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) "
            "VALUES (:brand_id, :workspace_id, 'C4 Brand')"
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


async def _create_run(
    repository: PostgresCrawlRepository,
    *,
    workspace_id: str,
    brand_id: str,
    recon_run_id: UUID,
    urls: tuple[str, ...],
) -> UUID:
    root = urls[0]
    run = await repository.create_or_get_run(
        CrawlRunCreate(
            workspace_id=workspace_id,
            brand_id=brand_id,
            recon_run_id=recon_run_id,
            root_discovered_url=root,
            root_fetch_key=root,
            allowed_registrable_domain="example.com",
            config=_config(),
        )
    )
    observations = []
    for index, url in enumerate(urls):
        observations.append(
            UrlObservation(
                discovered_url=url,
                discovered_via=DiscoveredVia.ROOT if index == 0 else DiscoveredVia.SITEMAP,
                sitemap_url=None if index == 0 else "https://example.com/sitemap.xml",
                fetch_key=url,
                fetch_key_hash=hashlib.sha256(url.encode()).hexdigest(),
                graph_depth=0 if index == 0 else None,
                priority=index,
                priority_reason=("c4",),
                eligibility=CrawlEligibility.BOTH,
                policy_outcome=PolicyOutcome.ADMITTED,
            )
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
    return run.crawl_run_id


def _request(url: str, *, operation_key: str) -> PageFetchRequest:
    return PageFetchRequest(
        operation_key=operation_key,
        requested_url=url,
        allowed_hosts=("example.com",),
        timeout_seconds=30,
        max_response_bytes=1_000_000,
        accepted_mime_types=("text/html", "text/plain"),
        max_redirects=5,
        robots_decision_ref="robots:example.com:v1",
    )


class _CountingFetcher:
    capabilities = PageFetcherCapabilities(
        provider_key="fixture",
        supports_operation_lookup=False,
        supports_idempotency_key=False,
        reports_redirect_chain=True,
        reports_outgoing_links=True,
        reports_actual_cost=True,
        reports_provider_receipt=True,
        proves_no_spend_before_dispatch=False,
    )

    def __init__(self, *, body: bytes = b"<html><a href='/about'>About</a></html>") -> None:
        self.body = body
        self.calls = 0
        self.raise_after_dispatch: BaseException | None = None

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        self.calls += 1
        if self.raise_after_dispatch is not None:
            raise self.raise_after_dispatch
        return PageFetchResult(
            provider_key="fixture",
            provider_request_id=f"receipt-{uuid4()}",
            requested_url=request.requested_url,
            final_url=request.requested_url,
            provider_status="ok",
            http_status=200,
            content=self.body,
            media_type="text/html",
            fetched_at=datetime.now(UTC),
            cost_cents=Decimal("1"),
            cost_kind=CostKind.ACTUAL,
            spend_status=SpendStatus.SPEND_CONFIRMED,
            retry_class=RetryClass.SUCCESS,
            receipt={
                "request_id": "safe-receipt",
                "credits_used": 1,
                "authorization": "Bearer secret",
                "request_headers": {"cookie": "secret"},
                "response_body": "never persist page bytes here",
            },
        )


class _FailPutOnceStorage:
    def __init__(self, delegate: StorageBackend) -> None:
        self.delegate = delegate
        self.remaining_failures = 1

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        if self.remaining_failures:
            self.remaining_failures -= 1
            raise StorageError("injected storage failure")
        await self.delegate.put(key, data, media_type=media_type)

    async def get(self, key: str) -> bytes:
        return await self.delegate.get(key)

    async def delete(self, key: str) -> None:
        await self.delegate.delete(key)

    async def exists(self, key: str) -> bool:
        return await self.delegate.exists(key)

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return await self.delegate.presign(key, expires_in=expires_in)

    def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return self.delegate.list_blobs()


class _FailSnapshotOnceRepository:
    def __init__(self, delegate: PostgresCrawlRepository) -> None:
        self.delegate = delegate
        self.remaining_failures = 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def persist_snapshot(self, *args: Any, **kwargs: Any) -> Any:
        if self.remaining_failures:
            self.remaining_failures -= 1
            raise RuntimeError("injected DB snapshot failure")
        return await self.delegate.persist_snapshot(*args, **kwargs)


class _LoseCompletionOnceRepository:
    def __init__(self, delegate: PostgresCrawlRepository) -> None:
        self.delegate = delegate
        self.remaining_failures = 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def complete_page(self, *args: Any, **kwargs: Any) -> bool:
        if self.remaining_failures:
            self.remaining_failures -= 1
            return False
        return await self.delegate.complete_page(*args, **kwargs)


class _Lookup:
    capabilities = PageFetcherCapabilities(
        provider_key="fixture",
        supports_operation_lookup=True,
        supports_idempotency_key=True,
        reports_redirect_chain=True,
        reports_outgoing_links=True,
        reports_actual_cost=True,
        reports_provider_receipt=True,
        proves_no_spend_before_dispatch=False,
    )

    def __init__(self, result: PageFetchResult) -> None:
        self.result = result
        self.calls = 0

    async def lookup_operation(
        self,
        request: PageFetchRequest,
        *,
        provider_request_id: str | None,
    ) -> PageFetchResult:
        del request, provider_request_id
        self.calls += 1
        return self.result


async def _expire_page(engine: Any, page_id: UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE official_site_crawl_page
                SET lease_acquired_at = now() - interval '2 minutes',
                    lease_expires_at = now() - interval '1 minute'
                WHERE id = :page_id
                """
            ),
            {"page_id": page_id},
        )


def test_success_is_one_dispatch_one_blob_one_snapshot_and_dsar_reachable(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                storage = FsStorage(tmp_path / "success")
                artifacts = OfficialSiteArtifactStore(storage=storage)
                result = await DurablePageAcquirer(
                    repository=repository, artifacts=artifacts, fetcher=fetcher
                ).acquire(lease, _request(lease.requested_url, operation_key=f"op:{run_id}:1"))
                assert fetcher.calls == 1
                assert result.page_completed and result.snapshot is not None
                assert result.artifact is not None
                assert await storage.get(result.artifact.artifact_key) == fetcher.body
                reach = await artifacts.evidence_reach(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert reach.crawl_run_ids == (run_id,)
                assert reach.attempt_ids == (result.attempt.fetch_attempt_id,)
                assert reach.snapshot_ids == (result.snapshot.snapshot_id,)
                assert reach.artifact_keys == (result.artifact.artifact_key,)
                assert not (
                    await artifacts.evidence_reach(workspace_id="other-workspace")
                ).crawl_run_ids
                async with engine.connect() as conn:
                    receipt = (
                        await conn.execute(
                            text(
                                "SELECT provider_receipt_json "
                                "FROM official_site_fetch_attempt WHERE id = :id"
                            ),
                            {"id": result.attempt.fetch_attempt_id},
                        )
                    ).scalar_one()
                    assert receipt == {"credits_used": 1, "request_id": "safe-receipt"}
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_storage_failure_and_snapshot_failure_retry_persistence_without_refetch(
    tmp_path: Path,
) -> None:
    async def _case(*, fail_storage: bool) -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                base_repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    base_repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await base_repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                base_storage = FsStorage(tmp_path / str(recon_run_id))
                storage: StorageBackend = (
                    _FailPutOnceStorage(base_storage) if fail_storage else base_storage
                )
                repository: Any = (
                    base_repository
                    if fail_storage
                    else _FailSnapshotOnceRepository(base_repository)
                )
                acquirer = DurablePageAcquirer(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(storage=storage),
                    fetcher=fetcher,
                )
                with pytest.raises(AcquisitionPersistencePendingError) as raised:
                    await acquirer.acquire(
                        lease,
                        _request(lease.requested_url, operation_key=f"op:{run_id}:failure"),
                    )
                completed = await acquirer.retry_persistence(raised.value)
                assert completed.page_completed
                assert fetcher.calls == 1
                async with engine.connect() as conn:
                    row = (
                        await conn.execute(
                            text(
                                "SELECT state, artifact_key FROM official_site_fetch_attempt "
                                "WHERE id = :id"
                            ),
                            {"id": completed.attempt.fetch_attempt_id},
                        )
                    ).one()
                    assert row[0] == "persisted"
                    assert row[1] is not None
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_case(fail_storage=True))
    run_async(_case(fail_storage=False))


def test_unrecoverable_success_is_quarantined_without_refetch(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                durable_storage = FsStorage(tmp_path / "unrecoverable")
                acquirer = DurablePageAcquirer(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(
                        storage=_FailPutOnceStorage(durable_storage)
                    ),
                    fetcher=fetcher,
                )
                with pytest.raises(AcquisitionPersistencePendingError):
                    await acquirer.acquire(
                        lease,
                        _request(lease.requested_url, operation_key=f"op:{run_id}:lost-body"),
                    )
                await _expire_page(engine, lease.page_id)
                assert (
                    await repository.reclaim_expired_leases(
                        workspace_id=workspace_id, crawl_run_id=run_id
                    )
                ).released_persistence_pending == 1
                claim = await repository.claim_persistence(
                    ClaimPersistenceRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="fresh-process",
                        lease_ttl_seconds=90,
                    )
                )
                assert claim is not None
                recovered = await DurablePageAcquirer(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(storage=durable_storage),
                    fetcher=fetcher,
                ).resume_persistence(claim)
                assert recovered is None
                assert fetcher.calls == 1
                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert progress.quarantined == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_missing_staged_blob_is_quarantined_without_refetch(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                base = PostgresCrawlRepository()
                run_id = await _create_run(
                    base,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await base.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                storage = FsStorage(tmp_path / "missing-staged-blob")
                failing = _FailSnapshotOnceRepository(base)
                with pytest.raises(AcquisitionPersistencePendingError):
                    await DurablePageAcquirer(
                        repository=failing,
                        artifacts=OfficialSiteArtifactStore(storage=storage),
                        fetcher=fetcher,
                    ).acquire(
                        lease,
                        _request(lease.requested_url, operation_key=f"op:{run_id}:missing-blob"),
                    )
                staged_key = (
                    await OfficialSiteArtifactStore(storage=storage).evidence_reach(
                        workspace_id=workspace_id, crawl_run_id=run_id
                    )
                ).artifact_keys
                assert len(staged_key) == 1
                await storage.delete(staged_key[0])
                await _expire_page(engine, lease.page_id)
                assert (
                    await base.reclaim_expired_leases(
                        workspace_id=workspace_id, crawl_run_id=run_id
                    )
                ).released_persistence_pending == 1
                claim = await base.claim_persistence(
                    ClaimPersistenceRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="recovery",
                        lease_ttl_seconds=90,
                    )
                )
                assert claim is not None
                recovered = await DurablePageAcquirer(
                    repository=base,
                    artifacts=OfficialSiteArtifactStore(storage=storage),
                    fetcher=fetcher,
                ).resume_persistence(claim)
                assert recovered is None
                assert fetcher.calls == 1
                progress = await base.read_progress(workspace_id=workspace_id, crawl_run_id=run_id)
                assert progress.quarantined == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_lost_completion_resumes_existing_snapshot_without_refetch(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                base = PostgresCrawlRepository()
                run_id = await _create_run(
                    base,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await base.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                storage = FsStorage(tmp_path / "lost-completion")
                failing = _LoseCompletionOnceRepository(base)
                with pytest.raises(AcquisitionFenceLostError):
                    await DurablePageAcquirer(
                        repository=failing,
                        artifacts=OfficialSiteArtifactStore(storage=storage),
                        fetcher=fetcher,
                    ).acquire(
                        lease,
                        _request(lease.requested_url, operation_key=f"op:{run_id}:complete"),
                    )
                await _expire_page(engine, lease.page_id)
                reclaimed = await base.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert reclaimed.released_persistence_pending == 1
                claim = await base.claim_persistence(
                    ClaimPersistenceRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="recovery",
                        lease_ttl_seconds=90,
                    )
                )
                assert claim is not None and claim.attempt.state.value == "persisted"
                recovered = await DurablePageAcquirer(
                    repository=base,
                    artifacts=OfficialSiteArtifactStore(storage=storage),
                    fetcher=fetcher,
                ).resume_persistence(claim)
                assert recovered is not None and recovered.page_completed
                assert fetcher.calls == 1
                async with engine.connect() as conn:
                    assert (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_page_snapshot "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one() == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_crash_after_dispatch_quarantines_without_lookup_or_reconciles_by_lookup(
    tmp_path: Path,
) -> None:
    async def _case(*, with_lookup: bool) -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="crashed",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                fetcher.raise_after_dispatch = RuntimeError("simulated process loss")
                storage = FsStorage(tmp_path / str(recon_run_id))
                acquirer = DurablePageAcquirer(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(storage=storage),
                    fetcher=fetcher,
                )
                with pytest.raises(RuntimeError, match="simulated process loss"):
                    await acquirer.acquire(
                        lease,
                        _request(lease.requested_url, operation_key=f"op:{run_id}:crash"),
                    )
                await _expire_page(engine, lease.page_id)
                reclaimed = await repository.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert reclaimed.moved_to_reconciliation_pending == 1
                claim = await repository.claim_reconciliation(
                    ClaimReconciliationRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="reconciler",
                        lease_ttl_seconds=90,
                    )
                )
                assert claim is not None
                lookup = None
                if with_lookup:
                    lookup = _Lookup(
                        PageFetchResult(
                            provider_key="fixture",
                            provider_request_id="recovered-receipt",
                            requested_url=lease.requested_url,
                            final_url=lease.requested_url,
                            provider_status="lookup_succeeded",
                            http_status=200,
                            content=b"recovered body",
                            media_type="text/html",
                            fetched_at=datetime.now(UTC),
                            cost_cents=Decimal("1"),
                            cost_kind=CostKind.ACTUAL,
                            spend_status=SpendStatus.SPEND_CONFIRMED,
                            retry_class=RetryClass.SUCCESS,
                            receipt={"request_id": "recovered-receipt"},
                        )
                    )
                recovered = await acquirer.reconcile(
                    claim,
                    _request(lease.requested_url, operation_key=claim.attempt.operation_key),
                    lookup=lookup,
                )
                assert fetcher.calls == 1
                if lookup is None:
                    assert recovered is None
                    progress = await repository.read_progress(
                        workspace_id=workspace_id, crawl_run_id=run_id
                    )
                    # Quarantine ends scheduling but deliberately preserves the honest unresolved
                    # spend classification for operator/cost audit.
                    assert progress.quarantined == 1 and progress.spend_unknown == 1
                else:
                    assert lookup.calls == 1
                    assert recovered is not None and recovered.page_completed
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_case(with_lookup=False))
    run_async(_case(with_lookup=True))


@pytest.mark.parametrize(
    ("retry_class", "spend_status", "expected_attempt_state", "expected_page_state"),
    (
        (RetryClass.RETRYABLE_NO_SPEND, SpendStatus.NO_SPEND, "reconciled_no_spend", "retry_wait"),
        (RetryClass.AMBIGUOUS, SpendStatus.SPEND_UNKNOWN, "quarantined", "quarantined"),
        (RetryClass.PERMANENT, SpendStatus.NO_SPEND, "quarantined", "quarantined"),
        (RetryClass.ROBOTS_REFUSED, SpendStatus.NO_SPEND, "quarantined", "quarantined"),
        (RetryClass.POLICY_REFUSED, SpendStatus.NO_SPEND, "quarantined", "quarantined"),
    ),
)
def test_reconciliation_lookup_non_successes_never_redispatch(
    tmp_path: Path,
    retry_class: RetryClass,
    spend_status: SpendStatus,
    expected_attempt_state: str,
    expected_page_state: str,
) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                )
                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="crashed",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                fetcher = _CountingFetcher()
                fetcher.raise_after_dispatch = RuntimeError("simulated process loss")
                acquirer = DurablePageAcquirer(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(storage=FsStorage(tmp_path / str(run_id))),
                    fetcher=fetcher,
                )
                request = _request(lease.requested_url, operation_key=f"op:{run_id}:lookup")
                with pytest.raises(RuntimeError, match="simulated process loss"):
                    await acquirer.acquire(lease, request)

                await _expire_page(engine, lease.page_id)
                reclaimed = await repository.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert reclaimed.moved_to_reconciliation_pending == 1
                claim = await repository.claim_reconciliation(
                    ClaimReconciliationRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="reconciler",
                        lease_ttl_seconds=90,
                    )
                )
                assert claim is not None
                lookup = _Lookup(
                    PageFetchResult(
                        provider_key="fixture",
                        provider_request_id="lookup-receipt",
                        requested_url=lease.requested_url,
                        provider_status=f"lookup_{retry_class.value}",
                        fetched_at=datetime.now(UTC),
                        cost_cents=None,
                        cost_kind=CostKind.NONE,
                        spend_status=spend_status,
                        retry_class=retry_class,
                    )
                )
                result = await acquirer.reconcile(claim, request, lookup=lookup)
                assert result is not None and not result.page_completed
                assert fetcher.calls == 1 and lookup.calls == 1
                async with engine.connect() as conn:
                    attempt_state = (
                        await conn.execute(
                            text("SELECT state FROM official_site_fetch_attempt WHERE id = :id"),
                            {"id": claim.attempt.fetch_attempt_id},
                        )
                    ).scalar_one()
                    page_state = (
                        await conn.execute(
                            text("SELECT state FROM official_site_crawl_page WHERE id = :id"),
                            {"id": lease.page_id},
                        )
                    ).scalar_one()
                    assert attempt_state == expected_attempt_state
                    assert page_state == expected_page_state
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_identical_content_is_one_workspace_blob_and_two_url_snapshots(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                urls = ("https://example.com/", "https://example.com/about")
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=urls,
                )
                storage = FsStorage(tmp_path / "identical")
                fetcher = _CountingFetcher(body=b"identical official page")
                acquirer = DurablePageAcquirer(
                    repository=repository,
                    artifacts=OfficialSiteArtifactStore(storage=storage),
                    fetcher=fetcher,
                )
                results = []
                for index in range(2):
                    lease = await repository.claim_next(
                        ClaimNextRequest(
                            workspace_id=workspace_id,
                            crawl_run_id=run_id,
                            worker_id=f"worker-{index}",
                            eligible_phase=CrawlPhase.FAST,
                            lease_ttl_seconds=90,
                        )
                    )
                    assert lease is not None
                    results.append(
                        await acquirer.acquire(
                            lease,
                            _request(
                                lease.requested_url,
                                operation_key=f"op:{run_id}:{index}",
                            ),
                        )
                    )
                assert fetcher.calls == 2
                assert results[0].artifact == results[1].artifact
                assert results[0].snapshot != results[1].snapshot
                blobs = [key async for key, _ in storage.list_blobs()]
                assert len(blobs) == 1
                async with engine.connect() as conn:
                    assert (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM artifact WHERE workspace_id = :workspace_id"
                            ),
                            {"workspace_id": workspace_id},
                        )
                    ).scalar_one() == 1
                    assert (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_page_snapshot "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one() == 2
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())
