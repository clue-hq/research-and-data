"""C1 database exit gates: atomic claim, fencing, tenancy, persistence, and checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.db.conftest import run_async

from clue_db import db_lifespan
from clue_research.official_site import (
    ArtifactRef,
    ClaimNextRequest,
    ClaimPersistenceRequest,
    ClaimReconciliationRequest,
    CostKind,
    CrawlEligibility,
    CrawlMode,
    CrawlPhase,
    CrawlRunCreate,
    CrawlRunNotFoundError,
    CrawlRunStatus,
    DiscoveredVia,
    DiscoveryBatch,
    OfficialSiteCrawlContractConfig,
    PolicyOutcome,
    PostgresCrawlRepository,
    ProviderResultMetadata,
    RetryClass,
    SpendStatus,
    UrlObservation,
)
from clue_research.sources import SEED_MANIFESTS

pytestmark = pytest.mark.usefixtures("require_official_site_db")


def _config() -> OfficialSiteCrawlContractConfig:
    return OfficialSiteCrawlContractConfig(
        crawl_mode=CrawlMode.SHADOW,
        provider_key="fixture",
        fast_deadline_seconds=40,
        fast_page_ceiling=12,
        total_page_ceiling=100,
        worker_concurrency=10,
        per_host_concurrency=10,
        lease_ttl_seconds=90,
        heartbeat_seconds=20,
        request_timeout_seconds=30,
        max_response_bytes=1_000_000,
        max_redirects=5,
        url_policy_version="url-v1",
        provider_policy_version="provider-v1",
        robots_policy_version="robots-v1",
    )


async def _seed_scope(conn: object) -> tuple[str, str, UUID]:
    workspace_id = f"official-site-c1-{uuid4()}"
    brand_id = f"brand-{uuid4()}"
    recon_run_id = uuid4()
    await conn.execute(  # type: ignore[attr-defined]
        text("INSERT INTO workspace (workspace_id, name) VALUES (:id, 'C1 Test')"),
        {"id": workspace_id},
    )
    await conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) "
            "VALUES (:brand_id, :workspace_id, 'C1 Brand')"
        ),
        {"brand_id": brand_id, "workspace_id": workspace_id},
    )
    await conn.execute(  # type: ignore[attr-defined]
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


async def _cleanup_scope(conn: object, workspace_id: str) -> None:
    # Exact workspace predicate only; these UUID-named test scopes cannot overlap product data.
    run_ids = (
        (
            await conn.execute(  # type: ignore[attr-defined]
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
            # The page's latest-snapshot FK is deferred, so the snapshot can be removed before
            # the page while the reverse (snapshot -> page) immediate FK remains fail-closed.
            "official_site_page_snapshot",
            "official_site_fetch_attempt",
            "official_site_link_edge",
            "official_site_url_observation",
            "official_site_crawl_page",
        ):
            await conn.execute(  # type: ignore[attr-defined]
                text(f"DELETE FROM {table} WHERE crawl_run_id = ANY(CAST(:run_ids AS uuid[]))"),
                params,
            )
        await conn.execute(  # type: ignore[attr-defined]
            text("DELETE FROM official_site_crawl_run WHERE id = ANY(CAST(:run_ids AS uuid[]))"),
            params,
        )
    await conn.execute(  # type: ignore[attr-defined]
        text("DELETE FROM artifact WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(  # type: ignore[attr-defined]
        text("DELETE FROM recon_run WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(  # type: ignore[attr-defined]
        text("DELETE FROM brand WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    await conn.execute(  # type: ignore[attr-defined]
        text("DELETE FROM workspace WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )


async def _create_run_and_page(
    repository: PostgresCrawlRepository,
    *,
    workspace_id: str,
    brand_id: str,
    recon_run_id: UUID,
    url: str = "https://example.com/",
) -> UUID:
    run = await repository.create_or_get_run(
        CrawlRunCreate(
            workspace_id=workspace_id,
            brand_id=brand_id,
            recon_run_id=recon_run_id,
            root_discovered_url=url,
            root_fetch_key=url,
            allowed_registrable_domain="example.com",
            config=_config(),
        )
    )
    fetch_hash = hashlib.sha256(url.encode()).hexdigest()
    recorded = await repository.record_discoveries(
        DiscoveryBatch(
            workspace_id=workspace_id,
            crawl_run_id=run.crawl_run_id,
            observations=(
                UrlObservation(
                    discovered_url=url,
                    discovered_via=DiscoveredVia.ROOT,
                    fetch_key=url,
                    fetch_key_hash=fetch_hash,
                    graph_depth=0,
                    priority=0,
                    priority_reason=("root",),
                    eligibility=CrawlEligibility.BOTH,
                    policy_outcome=PolicyOutcome.ADMITTED,
                ),
            ),
        )
    )
    assert recorded.page_nodes_created == 1
    assert await repository.transition_run(
        workspace_id=workspace_id,
        crawl_run_id=run.crawl_run_id,
        expected=CrawlRunStatus.QUEUED,
        next_status=CrawlRunStatus.FAST_ACTIVE,
    )
    return run.crawl_run_id


def test_official_site_logical_source_is_provider_neutral_and_zero_cost() -> None:
    entry = next(item for item in SEED_MANIFESTS if item.manifest.source_key == "official_site")
    assert entry.provider == "clue"
    assert entry.manifest.tier == 2
    assert entry.manifest.cost_cents == 0
    assert entry.requires_adapter is None


def test_schema_contains_all_frozen_tables_and_recon_scope_anchor() -> None:
    async def _run() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            tables = set(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT tablename FROM pg_tables
                            WHERE schemaname = 'public' AND tablename LIKE 'official_site_%'
                            """
                        )
                    )
                ).scalars()
            )
            assert tables == {
                "official_site_crawl_run",
                "official_site_crawl_page",
                "official_site_url_observation",
                "official_site_link_edge",
                "official_site_fetch_attempt",
                "official_site_page_snapshot",
                "official_site_alias_observation",
                "official_site_corpus_checkpoint",
                "official_site_extraction_operation",
            }
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_constraint "
                        "WHERE conname = 'recon_run_scope_anchor'"
                    )
                )
            ).scalar_one() == 1

    run_async(_run())


def test_ten_concurrent_claimers_acquire_one_page_once_and_stale_generation_is_fenced() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                crawl_run_id = await _create_run_and_page(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                )
                claims = await asyncio.gather(
                    *(
                        repository.claim_next(
                            ClaimNextRequest(
                                workspace_id=workspace_id,
                                crawl_run_id=crawl_run_id,
                                worker_id=f"worker-{index}",
                                eligible_phase=CrawlPhase.FAST,
                                lease_ttl_seconds=90,
                            )
                        )
                        for index in range(10)
                    )
                )
                leases = [claim for claim in claims if claim is not None]
                assert len(leases) == 1
                stale = leases[0]
                attempt = await repository.begin_attempt(
                    stale, provider_key="fixture", operation_key=f"op:{crawl_run_id}:1"
                )
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
                        {"page_id": stale.page_id},
                    )
                reclaimed = await repository.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=crawl_run_id
                )
                assert reclaimed.requeued_pre_dispatch == 1
                fresh = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        worker_id="replacement",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert fresh is not None
                assert fresh.lease_generation == stale.lease_generation + 1
                assert not await repository.renew_lease(stale, lease_ttl_seconds=90)
                assert not await repository.mark_attempt_dispatched(stale, attempt)
                assert not await repository.complete_page(stale, snapshot_id=uuid4())
                async with engine.connect() as conn:
                    state = (
                        await conn.execute(
                            text("SELECT state FROM official_site_fetch_attempt WHERE id = :id"),
                            {"id": attempt.fetch_attempt_id},
                        )
                    ).scalar_one()
                    assert state == "failed"
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_cross_workspace_repository_access_fails_closed() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                crawl_run_id = await _create_run_and_page(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                )
                with pytest.raises(CrawlRunNotFoundError):
                    await repository.read_progress(
                        workspace_id=f"other-{workspace_id}", crawl_run_id=crawl_run_id
                    )
                with pytest.raises(CrawlRunNotFoundError):
                    await repository.record_discoveries(
                        DiscoveryBatch(
                            workspace_id=f"other-{workspace_id}",
                            crawl_run_id=crawl_run_id,
                            observations=(
                                UrlObservation(
                                    discovered_url="https://example.com/about",
                                    discovered_via=DiscoveredVia.SITEMAP,
                                    sitemap_url="https://example.com/sitemap.xml",
                                    fetch_key="https://example.com/about",
                                    fetch_key_hash=hashlib.sha256(
                                        b"https://example.com/about"
                                    ).hexdigest(),
                                    graph_depth=None,
                                    eligibility=CrawlEligibility.BOTH,
                                    policy_outcome=PolicyOutcome.ADMITTED,
                                ),
                            ),
                        )
                    )
                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=crawl_run_id
                )
                assert progress.queued == 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_phase_blockers_report_db_clock_lease_and_retry_boundaries() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                crawl_run_id = await _create_run_and_page(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                )

                fast_queued = await repository.read_phase_blockers(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                    phase=CrawlPhase.FAST,
                )
                background_queued = await repository.read_phase_blockers(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                    phase=CrawlPhase.BACKGROUND,
                )
                assert fast_queued.count == 0
                assert fast_queued.retry_after_seconds is None
                assert background_queued.count == 1
                assert background_queued.retry_after_seconds is None

                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        worker_id="lease-worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE official_site_crawl_page "
                            "SET lease_expires_at = now() + interval '17 seconds' "
                            "WHERE id = :page_id"
                        ),
                        {"page_id": lease.page_id},
                    )
                leased = await repository.read_phase_blockers(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                    phase=CrawlPhase.FAST,
                )
                assert leased.count == 1
                assert leased.retry_after_seconds is not None
                assert 15 <= leased.retry_after_seconds <= 17

                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE official_site_crawl_page
                            SET state = 'retry_wait', lease_owner = NULL,
                                lease_acquired_at = NULL, lease_expires_at = NULL,
                                next_attempt_at = now() + interval '9 seconds'
                            WHERE id = :page_id
                            """
                        ),
                        {"page_id": lease.page_id},
                    )
                retry_wait = await repository.read_phase_blockers(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                    phase=CrawlPhase.BACKGROUND,
                )
                assert retry_wait.count == 1
                assert retry_wait.retry_after_seconds is not None
                assert 7 <= retry_wait.retry_after_seconds <= 9
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_discovery_replay_deduplicates_a_batch_without_collapsing_its_provenance() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                run = await repository.create_or_get_run(
                    CrawlRunCreate(
                        workspace_id=workspace_id,
                        brand_id=brand_id,
                        recon_run_id=recon_run_id,
                        root_discovered_url="https://example.com/",
                        root_fetch_key="https://example.com/",
                        allowed_registrable_domain="example.com",
                        config=_config(),
                    )
                )
                observation = UrlObservation(
                    discovered_url="https://example.com/pricing",
                    discovered_via=DiscoveredVia.SITEMAP,
                    sitemap_url="https://example.com/sitemap.xml",
                    fetch_key="https://example.com/pricing",
                    fetch_key_hash=hashlib.sha256(b"https://example.com/pricing").hexdigest(),
                    graph_depth=None,
                    priority=5,
                    priority_reason=("pricing",),
                    eligibility=CrawlEligibility.BOTH,
                    policy_outcome=PolicyOutcome.ADMITTED,
                )
                batch = DiscoveryBatch(
                    workspace_id=workspace_id,
                    crawl_run_id=run.crawl_run_id,
                    observations=(observation, observation),
                )
                first = await repository.record_discoveries(batch)
                replay = await repository.record_discoveries(batch)
                assert first.observations_recorded == 2
                assert first.page_nodes_created == 1
                assert replay.observations_recorded == 0
                assert replay.page_nodes_created == 0
                async with engine.connect() as conn:
                    assert (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_url_observation "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run.crawl_run_id},
                        )
                    ).scalar_one() == 2
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_discovery_page_ceiling_preserves_overflow_provenance_without_rolling_back() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                config = _config().model_copy(
                    update={"fast_page_ceiling": 2, "total_page_ceiling": 2}
                )
                run = await repository.create_or_get_run(
                    CrawlRunCreate(
                        workspace_id=workspace_id,
                        brand_id=brand_id,
                        recon_run_id=recon_run_id,
                        root_discovered_url="https://example.com/",
                        root_fetch_key="https://example.com/",
                        allowed_registrable_domain="example.com",
                        config=config,
                    )
                )
                root = UrlObservation(
                    discovered_url="https://example.com/",
                    discovered_via=DiscoveredVia.ROOT,
                    fetch_key="https://example.com/",
                    fetch_key_hash=hashlib.sha256(b"https://example.com/").hexdigest(),
                    graph_depth=0,
                    priority=0,
                    priority_reason=("ceiling-test",),
                    eligibility=CrawlEligibility.BOTH,
                    policy_outcome=PolicyOutcome.ADMITTED,
                )
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run.crawl_run_id,
                        observations=(root,),
                    )
                )
                async with engine.connect() as conn:
                    root_page_id = (
                        await conn.execute(
                            text(
                                "SELECT id FROM official_site_crawl_page "
                                "WHERE crawl_run_id = :run_id AND graph_depth = 0"
                            ),
                            {"run_id": run.crawl_run_id},
                        )
                    ).scalar_one()
                observations = tuple(
                    UrlObservation(
                        discovered_url=url,
                        discovered_via=DiscoveredVia.LINK,
                        fetch_key=url,
                        fetch_key_hash=hashlib.sha256(url.encode()).hexdigest(),
                        source_page_id=root_page_id,
                        graph_depth=1,
                        priority=index,
                        priority_reason=("ceiling-test",),
                        eligibility=CrawlEligibility.BOTH,
                        policy_outcome=PolicyOutcome.ADMITTED,
                    )
                    for index, url in enumerate(
                        (
                            "https://example.com/product",
                            "https://example.com/pricing",
                        )
                    )
                )
                result = await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run.crawl_run_id,
                        observations=observations,
                    )
                )
                assert result.page_nodes_created == 1
                assert result.observations_recorded == 2
                async with engine.connect() as conn:
                    page_count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_crawl_page "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run.crawl_run_id},
                        )
                    ).scalar_one()
                    overflow = (
                        (
                            await conn.execute(
                                text(
                                    """
                                    SELECT discovered_url, policy_outcome, policy_reason
                                    FROM official_site_url_observation
                                    WHERE crawl_run_id = :run_id AND page_id IS NULL
                                    """
                                ),
                                {"run_id": run.crawl_run_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                assert page_count == 2
                assert overflow["discovered_url"] == "https://example.com/pricing"
                assert overflow["policy_outcome"] == PolicyOutcome.REFUSED.value
                assert overflow["policy_reason"] == "overall_page_ceiling_reached"
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_expiry_recovery_separates_paid_ambiguity_from_recorded_success() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                crawl_run_id = await _create_run_and_page(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                )

                ambiguous_lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        worker_id="ambiguous-worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert ambiguous_lease is not None
                ambiguous_attempt = await repository.begin_attempt(
                    ambiguous_lease,
                    provider_key="fixture",
                    operation_key=f"op:{crawl_run_id}:ambiguous",
                )
                assert await repository.mark_attempt_dispatched(ambiguous_lease, ambiguous_attempt)
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
                        {"page_id": ambiguous_lease.page_id},
                    )
                reclaimed = await repository.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=crawl_run_id
                )
                assert reclaimed.moved_to_reconciliation_pending == 1
                reconciliation = await repository.claim_reconciliation(
                    ClaimReconciliationRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        worker_id="reconciler",
                        lease_ttl_seconds=90,
                    )
                )
                assert reconciliation is not None
                assert reconciliation.lease.lease_generation > ambiguous_lease.lease_generation
                assert reconciliation.attempt.lease_generation == ambiguous_attempt.lease_generation
                assert reconciliation.attempt.state.value == "spend_unknown"
                still_ambiguous = ProviderResultMetadata(
                    provider_key="fixture",
                    requested_url="https://example.com/",
                    final_url=None,
                    provider_status="lookup_ambiguous",
                    fetched_at=datetime.now(UTC),
                    cost_kind=CostKind.NONE,
                    spend_status=SpendStatus.SPEND_UNKNOWN,
                    retry_class=RetryClass.AMBIGUOUS,
                )
                assert await repository.record_provider_result(
                    reconciliation.lease, reconciliation.attempt, still_ambiguous
                )
                ambiguous_progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=crawl_run_id
                )
                assert ambiguous_progress.quarantined == 1
                assert ambiguous_progress.spend_unknown == 1

                success_url = "https://example.com/about"
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        observations=(
                            UrlObservation(
                                discovered_url=success_url,
                                discovered_via=DiscoveredVia.SITEMAP,
                                fetch_key=success_url,
                                fetch_key_hash=hashlib.sha256(success_url.encode()).hexdigest(),
                                graph_depth=None,
                                priority=1,
                                priority_reason=("company",),
                                eligibility=CrawlEligibility.BOTH,
                                policy_outcome=PolicyOutcome.ADMITTED,
                            ),
                        ),
                    )
                )
                success_lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        worker_id="success-worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert success_lease is not None
                success_attempt = await repository.begin_attempt(
                    success_lease,
                    provider_key="fixture",
                    operation_key=f"op:{crawl_run_id}:success",
                )
                assert await repository.mark_attempt_dispatched(success_lease, success_attempt)
                success = ProviderResultMetadata(
                    provider_key="fixture",
                    provider_request_id=f"receipt-{uuid4()}",
                    requested_url=success_url,
                    final_url=success_url,
                    provider_status="ok",
                    http_status=200,
                    media_type="text/html",
                    size_bytes=7,
                    fetched_at=datetime.now(UTC),
                    cost_kind=CostKind.NONE,
                    spend_status=SpendStatus.NO_SPEND,
                    retry_class=RetryClass.SUCCESS,
                )
                assert await repository.record_provider_result(
                    success_lease, success_attempt, success
                )
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
                        {"page_id": success_lease.page_id},
                    )
                reclaimed = await repository.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=crawl_run_id
                )
                assert reclaimed.released_persistence_pending == 1
                persistence = await repository.claim_persistence(
                    ClaimPersistenceRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        worker_id="persister",
                        lease_ttl_seconds=90,
                    )
                )
                assert persistence is not None
                assert persistence.lease.lease_generation > success_lease.lease_generation
                assert persistence.attempt.lease_generation == success_attempt.lease_generation
                assert persistence.attempt.state.value == "provider_succeeded"
                assert not await repository.renew_lease(success_lease, lease_ttl_seconds=90)
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_success_persists_url_snapshot_and_freezes_immutable_checkpoint() -> None:
    async def _run() -> None:
        workspace_id = ""
        checkpoint_id: UUID | None = None
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                crawl_run_id = await _create_run_and_page(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                )
                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        worker_id="snapshot-worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=90,
                    )
                )
                assert lease is not None
                attempt = await repository.begin_attempt(
                    lease, provider_key="fixture", operation_key=f"op:{crawl_run_id}:snapshot"
                )
                assert await repository.mark_attempt_dispatched(lease, attempt)
                body = b"official page"
                digest = hashlib.sha256(body).hexdigest()
                artifact = ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=f"{workspace_id}/{digest}",
                    content_sha256=digest,
                    size_bytes=len(body),
                )
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO artifact (
                                storage_key, workspace_id, content_sha256, media_type,
                                size_bytes, source_key, source_url
                            ) VALUES (
                                :key, :workspace_id, :digest, 'text/html', :size,
                                'official_site', 'https://example.com/'
                            )
                            """
                        ),
                        {
                            "key": artifact.artifact_key,
                            "workspace_id": workspace_id,
                            "digest": digest,
                            "size": len(body),
                        },
                    )
                metadata = ProviderResultMetadata(
                    provider_key="fixture",
                    provider_request_id=f"receipt-{uuid4()}",
                    requested_url="https://example.com/",
                    final_url="https://example.com/",
                    provider_status="ok",
                    http_status=200,
                    media_type="text/html",
                    size_bytes=len(body),
                    fetched_at=datetime.now(UTC),
                    cost_kind=CostKind.NONE,
                    spend_status=SpendStatus.NO_SPEND,
                    retry_class=RetryClass.SUCCESS,
                    receipt={"kind": "fixture"},
                )
                assert await repository.record_provider_result(lease, attempt, metadata)
                snapshot = await repository.persist_snapshot(
                    lease, attempt, artifact, metadata, outgoing_links=()
                )
                assert snapshot is not None
                assert await repository.complete_page(lease, snapshot_id=snapshot.snapshot_id)
                checkpoint = await repository.freeze_corpus_checkpoint(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                    phase=CrawlPhase.FAST,
                )
                checkpoint_id = checkpoint.checkpoint_id
                assert checkpoint.snapshot_ids == (snapshot.snapshot_id,)
                assert checkpoint.snapshot_set_sha256
                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=crawl_run_id
                )
                assert progress.fetched == 1

                with pytest.raises(DBAPIError):
                    async with engine.begin() as conn:
                        await conn.execute(
                            text(
                                "UPDATE official_site_corpus_checkpoint "
                                "SET coverage_json = '{}'::jsonb WHERE id = :id"
                            ),
                            {"id": checkpoint_id},
                        )
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_c6_db_deadline_rehydration_and_fast_checkpoint_are_cold_replay_safe() -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                crawl_run_id = await _create_run_and_page(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                )
                runtime = await repository.read_run_runtime(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                )
                assert runtime.status is CrawlRunStatus.FAST_ACTIVE
                assert runtime.config == _config()
                remaining = await repository.fast_deadline_remaining_seconds(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                )
                assert 0 < remaining <= _config().fast_deadline_seconds

                first = await repository.close_fast_and_freeze_checkpoint(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                )
                replay = await repository.close_fast_and_freeze_checkpoint(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                )
                assert replay.checkpoint_id == first.checkpoint_id
                assert replay.version == 1
                assert (
                    await repository.read_run_runtime(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                    )
                ).status is CrawlRunStatus.FAST_CLOSING
                assert (
                    await repository.read_latest_checkpoint(
                        workspace_id=workspace_id,
                        crawl_run_id=crawl_run_id,
                        phase=CrawlPhase.FAST,
                    )
                ) == first
                with pytest.raises(CrawlRunNotFoundError):
                    await repository.read_run_runtime(
                        workspace_id=f"other-{workspace_id}",
                        crawl_run_id=crawl_run_id,
                    )
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())
