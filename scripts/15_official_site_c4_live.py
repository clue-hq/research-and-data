#!/usr/bin/env python3
"""One retained provider -> C4 ledger/blob/snapshot canary on an isolated database.

Required environment: ``CLUE_DATABASE_URL`` and a dedicated ``CLUE_C4_ARTIFACT_ROOT``.
``CLUE_FIRECRAWL_API_KEY`` is additionally required for the default Firecrawl adapter, but not for
``CLUE_C4_PAGE_FETCHER=scrapling``. Output is privacy-safe IDs, counters, state, receipt key names,
and hashes only; credentials, raw receipts, and captured page content are never printed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from clue_db import db_lifespan
from clue_research.adapters.firecrawl_page import FirecrawlPageFetcher
from clue_research.adapters.scrapling_page import ScraplingPageFetcher
from clue_research.official_site import (
    ClaimNextRequest,
    CrawlEligibility,
    CrawlMode,
    CrawlPhase,
    CrawlRunCreate,
    CrawlRunStatus,
    DiscoveredVia,
    DiscoveryBatch,
    DurablePageAcquirer,
    OfficialSiteArtifactStore,
    OfficialSiteCrawlContractConfig,
    PageFetchRequest,
    PageFetchResult,
    PolicyOutcome,
    PostgresCrawlRepository,
    UrlObservation,
)
from clue_research.official_site.seams import PageFetcher
from clue_storage import FsStorage, content_address

_URL = "https://example.com/"


class _CountingFetcher:
    def __init__(self, delegate: PageFetcher) -> None:
        self._delegate = delegate
        self.capabilities = delegate.capabilities
        self.calls = 0

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        self.calls += 1
        return await self._delegate.fetch_one(request)


def _config(provider_key: str) -> OfficialSiteCrawlContractConfig:
    return OfficialSiteCrawlContractConfig(
        crawl_mode=CrawlMode.SHADOW,
        provider_key=provider_key,
        fast_deadline_seconds=40,
        fast_page_ceiling=1,
        total_page_ceiling=1,
        worker_concurrency=1,
        per_host_concurrency=1,
        lease_ttl_seconds=90,
        heartbeat_seconds=20,
        request_timeout_seconds=30,
        max_response_bytes=1_000_000,
        max_redirects=3,
        url_policy_version="official-site-url-v1",
        provider_policy_version="official-site-provider-v1",
        robots_policy_version="official-site-robots-v1",
    )


async def _seed_scope(conn: Any, *, provider_key: str) -> tuple[str, str, UUID]:
    workspace_id = f"official-site-c4-live-{provider_key}-{uuid4()}"
    brand_id = f"brand-{uuid4()}"
    recon_run_id = uuid4()
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:id, 'C4 Live Canary')"),
        {"id": workspace_id},
    )
    await conn.execute(
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) "
            "VALUES (:brand_id, :workspace_id, 'C4 Live Canary')"
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
                :fast_run_id, :background_run_id, 100, 0, 'c4-live-v1', 'c4-live-v1'
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


async def _run() -> dict[str, Any]:
    provider_key = os.environ.get("CLUE_C4_PAGE_FETCHER", "firecrawl").strip().casefold()
    api_key = os.environ.get("CLUE_FIRECRAWL_API_KEY")
    artifact_root_value = os.environ.get("CLUE_C4_ARTIFACT_ROOT")
    if provider_key not in {"firecrawl", "scrapling"}:
        raise RuntimeError("CLUE_C4_PAGE_FETCHER must be firecrawl or scrapling")
    if provider_key == "firecrawl" and not api_key:
        raise RuntimeError("CLUE_FIRECRAWL_API_KEY is required")
    if not artifact_root_value:
        raise RuntimeError("CLUE_C4_ARTIFACT_ROOT is required")
    artifact_root = Path(artifact_root_value).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)

    async with db_lifespan() as engine:
        async with engine.begin() as conn:
            workspace_id, brand_id, recon_run_id = await _seed_scope(
                conn, provider_key=provider_key
            )
        repository = PostgresCrawlRepository()
        run = await repository.create_or_get_run(
            CrawlRunCreate(
                workspace_id=workspace_id,
                brand_id=brand_id,
                recon_run_id=recon_run_id,
                root_discovered_url=_URL,
                root_fetch_key=_URL,
                allowed_registrable_domain="example.com",
                config=_config(provider_key),
            )
        )
        await repository.record_discoveries(
            DiscoveryBatch(
                workspace_id=workspace_id,
                crawl_run_id=run.crawl_run_id,
                observations=(
                    UrlObservation(
                        discovered_url=_URL,
                        discovered_via=DiscoveredVia.ROOT,
                        fetch_key=_URL,
                        fetch_key_hash=hashlib.sha256(_URL.encode()).hexdigest(),
                        graph_depth=0,
                        priority=0,
                        priority_reason=("live_c4_canary",),
                        eligibility=CrawlEligibility.BOTH,
                        policy_outcome=PolicyOutcome.ADMITTED,
                    ),
                ),
            )
        )
        assert await repository.transition_run(
            workspace_id=workspace_id,
            crawl_run_id=run.crawl_run_id,
            expected=CrawlRunStatus.QUEUED,
            next_status=CrawlRunStatus.FAST_ACTIVE,
        )
        lease = await repository.claim_next(
            ClaimNextRequest(
                workspace_id=workspace_id,
                crawl_run_id=run.crawl_run_id,
                worker_id="c4-live-worker",
                eligible_phase=CrawlPhase.FAST,
                lease_ttl_seconds=90,
            )
        )
        if lease is None:
            raise RuntimeError("live C4 page was not claimable")
        if provider_key == "firecrawl":
            assert api_key is not None
            provider: PageFetcher = FirecrawlPageFetcher(api_key=api_key)
        else:
            provider = ScraplingPageFetcher()
        fetcher = _CountingFetcher(provider)
        storage = FsStorage(artifact_root)
        operation_key = f"c4-live:{run.crawl_run_id}:{lease.page_id}:1"
        acquisition = await DurablePageAcquirer(
            repository=repository,
            artifacts=OfficialSiteArtifactStore(storage=storage),
            fetcher=fetcher,
        ).acquire(
            lease,
            PageFetchRequest(
                operation_key=operation_key,
                requested_url=_URL,
                allowed_hosts=("example.com",),
                timeout_seconds=30,
                max_response_bytes=1_000_000,
                accepted_mime_types=("text/html",),
                max_redirects=3,
                robots_decision_ref="live:example.com:robots-not-fetched-c4-only",
            ),
        )
        async with engine.connect() as conn:
            attempt = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT state, provider_request_id, provider_receipt_json, spend_status,
                               retry_class, artifact_key, content_sha256
                        FROM official_site_fetch_attempt WHERE id = :attempt_id
                        """
                        ),
                        {"attempt_id": acquisition.attempt.fetch_attempt_id},
                    )
                )
                .mappings()
                .one()
            )
            page_state = (
                await conn.execute(
                    text("SELECT state FROM official_site_crawl_page WHERE id = :page_id"),
                    {"page_id": lease.page_id},
                )
            ).scalar_one()
            snapshot_count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM official_site_page_snapshot "
                        "WHERE crawl_run_id = :run_id"
                    ),
                    {"run_id": run.crawl_run_id},
                )
            ).scalar_one()
            artifact_count = (
                await conn.execute(
                    text("SELECT count(*) FROM artifact WHERE workspace_id = :workspace_id"),
                    {"workspace_id": workspace_id},
                )
            ).scalar_one()

        blob_verified = False
        if acquisition.artifact is not None:
            blob = await storage.get(acquisition.artifact.artifact_key)
            blob_verified = (
                content_address(blob) == acquisition.artifact.content_sha256
                and len(blob) == acquisition.artifact.size_bytes
            )
        receipt = attempt["provider_receipt_json"] or {}
        return {
            "artifact_count": artifact_count,
            "artifact_key": attempt["artifact_key"],
            "artifact_root": str(artifact_root),
            "attempt_id": str(acquisition.attempt.fetch_attempt_id),
            "attempt_state": attempt["state"],
            "blob_verified": blob_verified,
            "content_sha256": attempt["content_sha256"],
            "crawl_run_id": str(run.crawl_run_id),
            "fetch_calls": fetcher.calls,
            "page_id": str(lease.page_id),
            "page_state": page_state,
            "provider_request_id_present": attempt["provider_request_id"] is not None,
            "provider_key": provider_key,
            "receipt_keys": sorted(receipt),
            "retry_class": attempt["retry_class"],
            "snapshot_count": snapshot_count,
            "snapshot_id": (
                str(acquisition.snapshot.snapshot_id) if acquisition.snapshot is not None else None
            ),
            "spend_status": attempt["spend_status"],
            "workspace_id": workspace_id,
        }


def main() -> None:
    print(json.dumps(asyncio.run(_run()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
