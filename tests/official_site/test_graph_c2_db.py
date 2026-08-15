"""C2 PostgreSQL graph, provenance, alias, and shorter-path re-expansion gates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async
from tests.official_site.test_repository_c1_db import _cleanup_scope, _config, _seed_scope

from clue_db import db_lifespan
from clue_research.official_site import (
    ArtifactRef,
    ClaimNextRequest,
    ConservativeUrlPolicy,
    CostKind,
    CrawlEligibility,
    CrawlPhase,
    CrawlRunCreate,
    CrawlRunStatus,
    DiscoveredVia,
    DiscoveryBatch,
    LinkObservation,
    LinkRelation,
    OfficialSiteDiscoveryPolicy,
    PolicyOutcome,
    PostgresCrawlRepository,
    ProviderResultMetadata,
    RetryClass,
    SitemapEntry,
    SpendStatus,
    UrlObservation,
    UrlPolicyConfig,
)

pytestmark = pytest.mark.usefixtures("require_official_site_db")


def _discovery() -> OfficialSiteDiscoveryPolicy:
    return OfficialSiteDiscoveryPolicy(
        url_policy=ConservativeUrlPolicy(
            UrlPolicyConfig(
                root_url="https://example.com/",
                allowed_registrable_domain="example.com",
            )
        )
    )


async def _create_run(
    repository: PostgresCrawlRepository,
    *,
    workspace_id: str,
    brand_id: str,
    recon_run_id: UUID,
    total_page_ceiling: int | None = None,
) -> UUID:
    config = _config()
    if total_page_ceiling is not None:
        config = config.model_copy(
            update={
                "fast_page_ceiling": min(config.fast_page_ceiling, total_page_ceiling),
                "total_page_ceiling": total_page_ceiling,
            }
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
    return run.crawl_run_id


def test_page_ceiling_admits_category_priority_before_provider_link_order() -> None:
    async def run() -> None:
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
                    total_page_ceiling=4,
                )
                discovery = _discovery()
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=(discovery.root("https://example.com/"),),
                    )
                )
                root_id = await _page_id(
                    engine,
                    run_id=run_id,
                    fetch_key="https://example.com/",
                )
                planned, dropped = discovery.plan_links(
                    (
                        LinkObservation(discovered_url="/legal", link_text="Legal"),
                        LinkObservation(discovered_url="/about-us", link_text="About us"),
                        LinkObservation(discovered_url="/pricing", link_text="Pricing"),
                        LinkObservation(discovered_url="/product", link_text="Product"),
                    ),
                    source_page_id=root_id,
                    source_url="https://example.com/",
                    source_graph_depth=0,
                )
                result = await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=planned,
                    )
                )
                assert dropped == 0
                assert result.page_nodes_created == 3

                async with engine.connect() as conn:
                    pages = tuple(
                        (
                            await conn.execute(
                                text(
                                    "SELECT fetch_key FROM official_site_crawl_page "
                                    "WHERE crawl_run_id = :run_id ORDER BY priority, fetch_key"
                                ),
                                {"run_id": run_id},
                            )
                        ).scalars()
                    )
                    refused = (
                        await conn.execute(
                            text(
                                "SELECT policy_reason FROM official_site_url_observation "
                                "WHERE crawl_run_id = :run_id AND discovered_url = '/legal'"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one()
                assert pages == (
                    "https://example.com/",
                    "https://example.com/product",
                    "https://example.com/pricing",
                    "https://example.com/about-us",
                )
                assert refused == "overall_page_ceiling_reached"
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(run())


async def _page_id(engine: object, *, run_id: UUID, fetch_key: str) -> UUID:
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        return cast(
            UUID,
            (
                await conn.execute(
                    text(
                        "SELECT id FROM official_site_crawl_page "
                        "WHERE crawl_run_id = :run_id AND fetch_key = :fetch_key"
                    ),
                    {"run_id": run_id, "fetch_key": fetch_key},
                )
            ).scalar_one(),
        )


async def _complete_page(
    engine: object,
    repository: PostgresCrawlRepository,
    *,
    workspace_id: str,
    crawl_run_id: UUID,
) -> UUID:
    lease = await repository.claim_next(
        ClaimNextRequest(
            workspace_id=workspace_id,
            crawl_run_id=crawl_run_id,
            worker_id="c2-fetcher",
            eligible_phase=CrawlPhase.FAST,
            lease_ttl_seconds=90,
        )
    )
    assert lease is not None
    attempt = await repository.begin_attempt(
        lease,
        provider_key="fixture",
        operation_key=f"c2:{crawl_run_id}:{lease.page_id}",
    )
    assert await repository.mark_attempt_dispatched(lease, attempt)
    body = b"captured C2 page"
    digest = hashlib.sha256(body).hexdigest()
    artifact = ArtifactRef(
        workspace_id=workspace_id,
        artifact_key=f"{workspace_id}/{digest}",
        content_sha256=digest,
        size_bytes=len(body),
    )
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(
            text(
                """
                INSERT INTO artifact (
                    storage_key, workspace_id, content_sha256, media_type,
                    size_bytes, source_key, source_url
                ) VALUES (
                    :key, :workspace_id, :digest, 'text/html', :size,
                    'official_site', :source_url
                )
                """
            ),
            {
                "key": artifact.artifact_key,
                "workspace_id": workspace_id,
                "digest": digest,
                "size": len(body),
                "source_url": lease.requested_url,
            },
        )
    metadata = ProviderResultMetadata(
        provider_key="fixture",
        provider_request_id=f"receipt-{uuid4()}",
        requested_url=lease.requested_url,
        final_url=lease.requested_url,
        provider_status="ok",
        http_status=200,
        media_type="text/html",
        size_bytes=len(body),
        fetched_at=datetime.now(UTC),
        cost_kind=CostKind.NONE,
        spend_status=SpendStatus.NO_SPEND,
        retry_class=RetryClass.SUCCESS,
    )
    assert await repository.record_provider_result(lease, attempt, metadata)
    snapshot = await repository.persist_snapshot(
        lease,
        attempt,
        artifact,
        metadata,
        outgoing_links=(),
    )
    assert snapshot is not None
    assert await repository.complete_page(
        lease, snapshot_id=snapshot.snapshot_id, outgoing_links=()
    )
    return lease.page_id


def test_sitemap_only_page_stays_unknown_depth_and_unknown_children_are_parked() -> None:
    async def run() -> None:
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
                )
                discovery = _discovery()
                sitemap_page = discovery.sitemap(
                    SitemapEntry(
                        "https://example.com/about",
                        "https://example.com/sitemap.xml",
                    )
                )
                created = await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=(sitemap_page,),
                    )
                )
                assert created.page_nodes_created == 1
                async with engine.connect() as conn:
                    page = (
                        (
                            await conn.execute(
                                text(
                                    "SELECT id, graph_depth, state FROM official_site_crawl_page "
                                    "WHERE crawl_run_id = :run_id"
                                ),
                                {"run_id": run_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    sitemap_url = (
                        await conn.execute(
                            text(
                                "SELECT sitemap_url FROM official_site_url_observation "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one()
                assert page["graph_depth"] is None and page["state"] == "queued"
                assert sitemap_url == "https://example.com/sitemap.xml"

                assert await repository.transition_run(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    expected=CrawlRunStatus.QUEUED,
                    next_status=CrawlRunStatus.FAST_ACTIVE,
                )
                source_id = await _complete_page(
                    engine,
                    repository,
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                )
                planned, dropped = discovery.plan_links(
                    (LinkObservation(discovered_url="/team", link_text="Our team"),),
                    source_page_id=source_id,
                    source_url="https://example.com/about",
                    source_graph_depth=None,
                )
                assert dropped == 0 and planned[0].graph_depth is None
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=planned,
                    )
                )
                async with engine.connect() as conn:
                    child = (
                        (
                            await conn.execute(
                                text(
                                    "SELECT graph_depth, state, representative_requested_url "
                                    "FROM official_site_crawl_page "
                                    "WHERE crawl_run_id = :run_id AND fetch_key = :fetch_key"
                                ),
                                {"run_id": run_id, "fetch_key": "https://example.com/team"},
                            )
                        )
                        .mappings()
                        .one()
                    )
                assert child["graph_depth"] is None and child["state"] == "discovered"
                assert child["representative_requested_url"] == "https://example.com/team"
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(run())


def test_shorter_path_reexpands_saved_edges_without_refetch_and_replay_is_idempotent() -> None:
    async def run() -> None:
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
                )
                discovery = _discovery()
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=(
                            discovery.sitemap(
                                SitemapEntry(
                                    "https://example.com/about",
                                    "https://example.com/sitemap.xml",
                                )
                            ),
                        ),
                    )
                )
                assert await repository.transition_run(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    expected=CrawlRunStatus.QUEUED,
                    next_status=CrawlRunStatus.FAST_ACTIVE,
                )
                about_id = await _complete_page(
                    engine,
                    repository,
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                )
                saved_links, _ = discovery.plan_links(
                    (LinkObservation(discovered_url="/team"),),
                    source_page_id=about_id,
                    source_url="https://example.com/about",
                    source_graph_depth=None,
                )
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=saved_links,
                    )
                )

                root_observation = discovery.root("https://example.com/")
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=(root_observation,),
                    )
                )
                root_id = await _page_id(engine, run_id=run_id, fetch_key="https://example.com/")
                shorter = discovery.link(
                    LinkObservation(discovered_url="/about"),
                    source_page_id=root_id,
                    source_url="https://example.com/",
                    source_graph_depth=0,
                )
                batch = DiscoveryBatch(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    observations=(shorter,),
                )
                expanded = await repository.record_discoveries(batch)
                replay = await repository.record_discoveries(batch)
                assert expanded.saved_links_reexpanded == 1
                assert replay.saved_links_reexpanded == 0
                async with engine.connect() as conn:
                    pages = {
                        row["fetch_key"]: row
                        for row in (
                            await conn.execute(
                                text(
                                    """
                                    SELECT fetch_key, graph_depth, state, attempt_count,
                                           expanded_min_depth
                                    FROM official_site_crawl_page
                                    WHERE crawl_run_id = :run_id
                                    """
                                ),
                                {"run_id": run_id},
                            )
                        ).mappings()
                    }
                assert pages["https://example.com/about"]["state"] == "fetched"
                assert pages["https://example.com/about"]["attempt_count"] == 1
                assert pages["https://example.com/about"]["graph_depth"] == 1
                assert pages["https://example.com/about"]["expanded_min_depth"] == 1
                assert pages["https://example.com/team"]["graph_depth"] == 2
                assert pages["https://example.com/team"]["state"] == "queued"
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(run())


def test_observations_edges_and_aliases_are_separate_and_external_canonical_is_rejected() -> None:
    async def run() -> None:
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
                )
                discovery = _discovery()
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=(discovery.root("https://example.com/"),),
                    )
                )
                root_id = await _page_id(engine, run_id=run_id, fetch_key="https://example.com/")
                anchor = discovery.link(
                    LinkObservation(discovered_url="/about"),
                    source_page_id=root_id,
                    source_url="https://example.com/",
                    source_graph_depth=0,
                )
                await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=(anchor,),
                    )
                )
                about_id = await _page_id(
                    engine, run_id=run_id, fetch_key="https://example.com/about"
                )
                aliases = (
                    discovery.link(
                        LinkObservation(
                            discovered_url="/about", relation=LinkRelation.CANONICAL_HINT
                        ),
                        source_page_id=root_id,
                        source_url="https://example.com/",
                        source_graph_depth=0,
                    ),
                    discovery.link(
                        LinkObservation(
                            discovered_url="https://evil.test/about",
                            relation=LinkRelation.CANONICAL_HINT,
                        ),
                        source_page_id=root_id,
                        source_url="https://example.com/",
                        source_graph_depth=0,
                    ),
                    discovery.link(
                        LinkObservation(discovered_url="/about", relation=LinkRelation.REDIRECT),
                        source_page_id=root_id,
                        source_url="https://example.com/",
                        source_graph_depth=0,
                    ),
                )
                first_alias_write = await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=aliases,
                    )
                )
                replay_alias_write = await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=aliases,
                    )
                )
                assert first_alias_write.observations_recorded == 3
                assert replay_alias_write.observations_recorded == 0
                async with engine.connect() as conn:
                    alias_rows = list(
                        (
                            await conn.execute(
                                text(
                                    """
                                    SELECT alias_url, kind, verification_status, target_page_id
                                    FROM official_site_alias_observation
                                    WHERE crawl_run_id = :run_id
                                    ORDER BY kind, alias_url
                                    """
                                ),
                                {"run_id": run_id},
                            )
                        ).mappings()
                    )
                    page_count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_crawl_page "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one()
                    observation_count = (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM official_site_url_observation "
                                "WHERE crawl_run_id = :run_id"
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one()
                    relations = set(
                        (
                            await conn.execute(
                                text(
                                    "SELECT link_relation FROM official_site_link_edge "
                                    "WHERE crawl_run_id = :run_id"
                                ),
                                {"run_id": run_id},
                            )
                        ).scalars()
                    )
                assert page_count == 2
                assert observation_count == 5
                assert relations == {"anchor", "canonical_hint", "redirect"}
                assert alias_rows == [
                    {
                        "alias_url": "/about",
                        "kind": "canonical_hint",
                        "verification_status": "observed",
                        "target_page_id": about_id,
                    },
                    {
                        "alias_url": "https://evil.test/about",
                        "kind": "canonical_hint",
                        "verification_status": "rejected_external",
                        "target_page_id": None,
                    },
                    {
                        "alias_url": "/about",
                        "kind": "redirect",
                        "verification_status": "verified_redirect",
                        "target_page_id": about_id,
                    },
                ]
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(run())


def test_fetch_key_hash_collision_never_collapses_distinct_full_keys() -> None:
    async def run() -> None:
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
                )
                forced_hash = "a" * 64
                observations = tuple(
                    UrlObservation(
                        discovered_url=url,
                        discovered_via=DiscoveredVia.SITEMAP,
                        fetch_key=url,
                        fetch_key_hash=forced_hash,
                        graph_depth=None,
                        eligibility=CrawlEligibility.BACKGROUND,
                        policy_outcome=PolicyOutcome.ADMITTED,
                    )
                    for url in ("https://example.com/a", "https://example.com/b")
                )
                result = await repository.record_discoveries(
                    DiscoveryBatch(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        observations=observations,
                    )
                )
                assert result.page_nodes_created == 2
                async with engine.connect() as conn:
                    keys = tuple(
                        (
                            await conn.execute(
                                text(
                                    "SELECT fetch_key FROM official_site_crawl_page "
                                    "WHERE crawl_run_id = :run_id ORDER BY fetch_key"
                                ),
                                {"run_id": run_id},
                            )
                        ).scalars()
                    )
                assert keys == ("https://example.com/a", "https://example.com/b")
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(run())
