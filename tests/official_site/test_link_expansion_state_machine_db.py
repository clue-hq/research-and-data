"""Acquisition/expansion decoupling, fencing, retry, and checkpoint acceptance."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async
from tests.official_site.test_coordinator_c5_db import (
    _cleanup_scope,
    _config,
    _coordinator,
    _create_run,
    _phase_request,
    _ScenarioFetcher,
    _seed_scope,
)

from clue_db import db_lifespan
from clue_research.official_site import (
    ClaimLinkExpansionRequest,
    ClaimNextRequest,
    CrawlPhase,
    CrawlRunStatus,
    DurablePageAcquirer,
    LinkExpansionState,
    OfficialSiteArtifactStore,
    PageFetchRequest,
    PostgresCrawlRepository,
)
from clue_storage import FsStorage

pytestmark = pytest.mark.usefixtures("require_official_site_db")


def _fetch_request(url: str, operation_key: str) -> PageFetchRequest:
    return PageFetchRequest(
        operation_key=operation_key,
        requested_url=url,
        allowed_hosts=("example.com",),
        allowed_registrable_domain="example.com",
        allow_subdomains=True,
        timeout_seconds=5,
        max_response_bytes=1_000_000,
        accepted_mime_types=("text/html",),
        max_redirects=5,
        robots_decision_ref="robots:test-v1:allow",
    )


class _FailDiscoveryRepository:
    def __init__(self, delegate: PostgresCrawlRepository, *, failures: int) -> None:
        self.delegate = delegate
        self.remaining_failures = failures

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def record_discoveries(self, batch: Any) -> Any:
        if self.remaining_failures:
            self.remaining_failures -= 1
            raise RuntimeError("injected discovery persistence failure")
        return await self.delegate.record_discoveries(batch)


def test_page_publication_atomically_queues_one_independently_fenced_expansion(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                config = _config(workers=2, per_host=2)
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                    config=config,
                )
                lease = await repository.claim_next(
                    ClaimNextRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="acquisition-worker",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=3,
                    )
                )
                assert lease is not None
                fetcher = _ScenarioFetcher(
                    links={"https://example.com/": ("https://example.com/product",)}
                )
                artifacts = OfficialSiteArtifactStore(storage=FsStorage(tmp_path / "artifacts"))
                acquirer = DurablePageAcquirer(
                    repository=repository,
                    artifacts=artifacts,
                    fetcher=fetcher,
                )
                result = await acquirer.acquire(
                    lease,
                    _fetch_request(lease.requested_url, f"expansion:{lease.page_id}:g1"),
                )
                assert result.page_completed
                assert fetcher.calls == ["https://example.com/"]

                async with engine.connect() as conn:
                    row = (
                        (
                            await conn.execute(
                                text(
                                    """
                                    SELECT page.state AS page_state,
                                           expansion.state AS expansion_state,
                                           expansion.snapshot_id,
                                           jsonb_array_length(expansion.outgoing_links_json)
                                               AS outgoing_count
                                    FROM official_site_crawl_page AS page
                                    JOIN official_site_link_expansion AS expansion
                                      ON expansion.page_id = page.id
                                     AND expansion.crawl_run_id = page.crawl_run_id
                                     AND expansion.workspace_id = page.workspace_id
                                    WHERE page.id = :page_id
                                    """
                                ),
                                {"page_id": lease.page_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                assert row["page_state"] == "fetched"
                assert row["expansion_state"] == "queued"
                assert row["snapshot_id"] == result.snapshot.snapshot_id
                assert row["outgoing_count"] == 1
                reach = await artifacts.evidence_reach(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert reach.link_expansion_ids == (result.snapshot.snapshot_id,)

                claims = await asyncio.gather(
                    *(
                        repository.claim_link_expansion(
                            ClaimLinkExpansionRequest(
                                workspace_id=workspace_id,
                                crawl_run_id=run_id,
                                worker_id=f"expander-{index}",
                                eligible_phase=CrawlPhase.FAST,
                                lease_ttl_seconds=3,
                            )
                        )
                        for index in range(10)
                    )
                )
                winners = [claim for claim in claims if claim is not None]
                assert len(winners) == 1
                original = winners[0]

                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE official_site_crawl_run
                            SET fast_claim_deadline_at = now() + interval '200 milliseconds'
                            WHERE id = :run_id
                            """
                        ),
                        {"run_id": run_id},
                    )
                blockers = await repository.read_phase_blockers(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    phase=CrawlPhase.FAST,
                )
                assert blockers.count == 1
                assert blockers.retry_after_seconds is not None
                assert blockers.retry_after_seconds < 0.5
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE official_site_crawl_run
                            SET fast_claim_deadline_at = now() + interval '40 seconds'
                            WHERE id = :run_id
                            """
                        ),
                        {"run_id": run_id},
                    )

                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE official_site_link_expansion
                            SET lease_acquired_at = now() - interval '2 seconds',
                                lease_expires_at = now() - interval '1 second'
                            WHERE id = :expansion_id
                            """
                        ),
                        {"expansion_id": original.expansion_id},
                    )
                reclaimed = await repository.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert reclaimed.released_link_expansions == 1
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE official_site_link_expansion
                            SET next_attempt_at = now() - interval '1 second'
                            WHERE id = :expansion_id AND state = 'retry_wait'
                            """
                        ),
                        {"expansion_id": original.expansion_id},
                    )
                await repository.reclaim_expired_leases(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                replacement = await repository.claim_link_expansion(
                    ClaimLinkExpansionRequest(
                        workspace_id=workspace_id,
                        crawl_run_id=run_id,
                        worker_id="replacement-expander",
                        eligible_phase=CrawlPhase.FAST,
                        lease_ttl_seconds=3,
                    )
                )
                assert replacement is not None
                assert replacement.lease_generation == original.lease_generation + 1
                assert not await repository.renew_link_expansion(original, lease_ttl_seconds=3)
                assert not await repository.complete_link_expansion(original)
                assert (
                    await repository.fail_link_expansion(
                        original,
                        failure_code="stale",
                        failure_class="StaleWorker",
                        retry_after_seconds=1,
                    )
                    is None
                )
                assert await repository.complete_link_expansion(replacement)
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_expansion_failure_never_hides_snapshot_or_refetches_provider_and_retries(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                config = _config(workers=1, per_host=1)
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                    config=config,
                )
                fetcher = _ScenarioFetcher(
                    links={"https://example.com/": ("https://example.com/product",)}
                )
                failing_repository = _FailDiscoveryRepository(repository, failures=1)
                coordinator = _coordinator(
                    repository=failing_repository,
                    storage_path=tmp_path / "artifacts",
                    root="https://example.com/",
                    fetcher=fetcher,
                )
                first = await coordinator.run_phase(
                    _phase_request(workspace_id, run_id, config, idle_polls=4)
                )
                assert first.pages_completed == 1
                assert first.link_expansions_retried == 1
                assert first.worker_errors == 0
                assert fetcher.calls == ["https://example.com/"]

                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert progress.fetched == 1
                assert progress.persistence_pending == 0
                assert progress.expansion_retry_wait == 1
                checkpoint = await repository.freeze_corpus_checkpoint(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    phase=CrawlPhase.FAST,
                )
                assert len(checkpoint.snapshot_ids) == 1
                assert checkpoint.coverage["expansion_retry_wait"] == 1
                assert checkpoint.coverage["discovery_complete"] is False
                closed = await repository.close_fast_and_freeze_checkpoint(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert closed.checkpoint_id == checkpoint.checkpoint_id
                assert await repository.transition_run(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    expected=CrawlRunStatus.FAST_CLOSING,
                    next_status=CrawlRunStatus.FAST_COMPLETE,
                )
                assert await repository.transition_run(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    expected=CrawlRunStatus.FAST_COMPLETE,
                    next_status=CrawlRunStatus.BACKGROUND_ACTIVE,
                )

                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            UPDATE official_site_link_expansion
                            SET next_attempt_at = now() - interval '1 second'
                            WHERE crawl_run_id = :run_id AND state = 'retry_wait'
                            """
                        ),
                        {"run_id": run_id},
                    )
                second = await coordinator.run_phase(
                    _phase_request(
                        workspace_id,
                        run_id,
                        config,
                        phase=CrawlPhase.BACKGROUND,
                        idle_polls=4,
                    )
                )
                assert second.link_expansions_completed >= 1
                assert Counter(fetcher.calls)["https://example.com/"] == 1
                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert progress.expansion_retry_wait == 0
                assert progress.expansion_completed >= 1
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())


def test_expansion_retry_exhaustion_is_partial_terminal_not_page_failure(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = ""
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    workspace_id, brand_id, recon_run_id = await _seed_scope(conn)
                repository = PostgresCrawlRepository()
                config = _config(workers=1, per_host=1)
                run_id = await _create_run(
                    repository,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    recon_run_id=recon_run_id,
                    urls=("https://example.com/",),
                    config=config,
                )
                fetcher = _ScenarioFetcher(
                    links={"https://example.com/": ("https://example.com/product",)}
                )
                failing_repository = _FailDiscoveryRepository(repository, failures=3)
                coordinator = _coordinator(
                    repository=failing_repository,
                    storage_path=tmp_path / "artifacts",
                    root="https://example.com/",
                    fetcher=fetcher,
                )
                terminal_state = None
                for attempt in range(3):
                    await coordinator.run_phase(
                        _phase_request(workspace_id, run_id, config, idle_polls=4)
                    )
                    async with engine.connect() as conn:
                        terminal_state = (
                            await conn.execute(
                                text(
                                    "SELECT state FROM official_site_link_expansion "
                                    "WHERE crawl_run_id = :run_id"
                                ),
                                {"run_id": run_id},
                            )
                        ).scalar_one()
                    if attempt < 2:
                        assert terminal_state == LinkExpansionState.RETRY_WAIT.value
                        async with engine.begin() as conn:
                            await conn.execute(
                                text(
                                    """
                                    UPDATE official_site_link_expansion
                                    SET next_attempt_at = now() - interval '1 second'
                                    WHERE crawl_run_id = :run_id
                                    """
                                ),
                                {"run_id": run_id},
                            )
                assert terminal_state == LinkExpansionState.FAILED.value
                assert Counter(fetcher.calls)["https://example.com/"] == 1
                progress = await repository.read_progress(
                    workspace_id=workspace_id, crawl_run_id=run_id
                )
                assert progress.fetched == 1
                assert progress.failed == 0
                assert progress.expansion_failed == 1
                blockers = await repository.read_phase_blockers(
                    workspace_id=workspace_id,
                    crawl_run_id=run_id,
                    phase=CrawlPhase.FAST,
                )
                assert blockers.count == 0
            finally:
                if workspace_id:
                    async with engine.begin() as conn:
                        await _cleanup_scope(conn, workspace_id)

    run_async(_run())
