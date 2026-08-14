"""C6 lifecycle acceptance without a provider or database."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.db.conftest import run_async

from clue_research.official_site import (
    CoordinatorPhaseResult,
    CorpusCheckpointRef,
    CrawlMode,
    CrawlPhase,
    CrawlPhasePendingError,
    CrawlRunRef,
    CrawlRunRuntimeRef,
    CrawlRunStatus,
    OfficialSiteCrawlContractConfig,
    OfficialSiteCrawlLifecycle,
    OfficialSiteCrawlLifecycleRequest,
    OfficialSiteMaterializationResult,
    SitemapEntry,
    compute_snapshot_set_sha256,
)


def _config(mode: CrawlMode = CrawlMode.SHADOW, *, deadline: int = 1):
    return OfficialSiteCrawlContractConfig(
        crawl_mode=mode,
        provider_key="fixture",
        fast_deadline_seconds=deadline,
        fast_page_ceiling=4,
        total_page_ceiling=8,
        worker_concurrency=2,
        per_host_concurrency=1,
        lease_ttl_seconds=9,
        heartbeat_seconds=2,
        request_timeout_seconds=3,
        max_response_bytes=100_000,
        max_redirects=2,
        url_policy_version="official-site-url-v1",
        provider_policy_version="fixture-v1",
        robots_policy_version="official-site-robots-v1",
    )


class _Repository:
    def __init__(self, config: OfficialSiteCrawlContractConfig, *, deadline_seconds: float = 0.01):
        self.config = config
        self.deadline_seconds = deadline_seconds
        self.run_id = uuid4()
        self.recon_id = uuid4()
        self.client_entity_id: UUID | None = None
        self.status = CrawlRunStatus.QUEUED
        self.created = True
        self.discoveries: list[Any] = []
        self.snapshots: list[UUID] = [uuid4()]
        self.checkpoints: dict[CrawlPhase, CorpusCheckpointRef] = {}
        self.transitions: list[tuple[CrawlRunStatus, CrawlRunStatus]] = []
        self.phase_blockers = 0

    async def create_or_get_run(self, request: Any) -> CrawlRunRef:
        assert request.recon_run_id == self.recon_id
        if self.created:
            self.client_entity_id = request.client_entity_id
        result = CrawlRunRef(
            crawl_run_id=self.run_id,
            workspace_id=request.workspace_id,
            recon_run_id=request.recon_run_id,
            status=self.status,
            created=self.created,
        )
        self.created = False
        return result

    async def read_run_runtime(self, *, workspace_id: str, crawl_run_id: UUID):
        assert workspace_id == "ws" and crawl_run_id == self.run_id
        return CrawlRunRuntimeRef(
            crawl_run_id=self.run_id,
            workspace_id="ws",
            brand_id="brand",
            client_entity_id=self.client_entity_id,
            recon_run_id=self.recon_id,
            root_discovered_url="https://example.com/",
            root_fetch_key="https://example.com/",
            allowed_registrable_domain="example.com",
            status=self.status,
            fast_claim_deadline_at=datetime.now(UTC) + timedelta(seconds=1),
            config=self.config,
        )

    async def fast_deadline_remaining_seconds(self, **_: object) -> float:
        return self.deadline_seconds

    async def record_discoveries(self, batch: Any) -> object:
        self.discoveries.extend(batch.observations)
        return object()

    async def transition_run(
        self,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        expected: CrawlRunStatus,
        next_status: CrawlRunStatus,
    ) -> bool:
        assert workspace_id == "ws" and crawl_run_id == self.run_id
        if self.status is not expected:
            return False
        self.transitions.append((expected, next_status))
        self.status = next_status
        return True

    async def close_fast_and_freeze_checkpoint(self, **_: object) -> CorpusCheckpointRef:
        if self.status is CrawlRunStatus.FAST_ACTIVE:
            self.transitions.append((self.status, CrawlRunStatus.FAST_CLOSING))
            self.status = CrawlRunStatus.FAST_CLOSING
        return self._checkpoint(CrawlPhase.FAST)

    async def freeze_corpus_checkpoint_once(
        self, *, phase: CrawlPhase, **_: object
    ) -> CorpusCheckpointRef:
        return self._checkpoint(phase)

    async def read_latest_checkpoint(
        self, *, phase: CrawlPhase, **_: object
    ) -> CorpusCheckpointRef | None:
        return self.checkpoints.get(phase)

    async def count_phase_blockers(self, **_: object) -> int:
        return self.phase_blockers

    def _checkpoint(self, phase: CrawlPhase) -> CorpusCheckpointRef:
        existing = self.checkpoints.get(phase)
        if existing is not None:
            return existing
        ids = tuple(sorted(self.snapshots, key=str))
        checkpoint = CorpusCheckpointRef(
            checkpoint_id=uuid4(),
            workspace_id="ws",
            crawl_run_id=self.run_id,
            phase=phase,
            version=1,
            snapshot_ids=ids,
            snapshot_set_sha256=compute_snapshot_set_sha256(ids),
            coverage={"snapshot_count": len(ids)},
            created_at=datetime.now(UTC),
        )
        self.checkpoints[phase] = checkpoint
        return checkpoint


def _phase_result(repository: _Repository, phase: CrawlPhase, *, stopped: bool = False):
    return CoordinatorPhaseResult(
        workspace_id="ws",
        crawl_run_id=repository.run_id,
        phase=phase,
        ordinary_claims=1,
        persistence_claims=0,
        reconciliation_claims=0,
        pages_completed=1,
        observations_recorded=0,
        links_dropped=0,
        heartbeat_renewals=0,
        fenced_workers=0,
        worker_errors=0,
        stopped=stopped,
    )


class _DeadlineCoordinator:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.cancelled = False
        self.fast_started = asyncio.Event()
        self.fast_finished = asyncio.Event()
        self.calls: list[CrawlPhase] = []

    async def run_phase(self, request: Any, *, stop_event: asyncio.Event | None = None):
        self.calls.append(request.phase)
        if request.phase is CrawlPhase.BACKGROUND:
            return _phase_result(self.repository, CrawlPhase.BACKGROUND)
        assert stop_event is not None
        self.fast_started.set()
        try:
            await stop_event.wait()
            # Represents a paid call already dispatched at the cutoff. C6 must await it rather
            # than cancel it, but its late snapshot must not mutate the frozen fast corpus.
            await asyncio.sleep(0.01)
            self.repository.snapshots.append(uuid4())
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.fast_finished.set()
        return _phase_result(self.repository, CrawlPhase.FAST, stopped=True)


class _ImmediateCoordinator:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.calls: list[CrawlPhase] = []

    async def run_phase(self, request: Any, *, stop_event: asyncio.Event | None = None):
        del stop_event
        self.calls.append(request.phase)
        return _phase_result(self.repository, request.phase)


class _DrainAfterDeadlineCoordinator(_ImmediateCoordinator):
    def __init__(self, repository: _Repository) -> None:
        super().__init__(repository)
        self.fast_drain_started = asyncio.Event()
        self.fast_drain_release = asyncio.Event()
        self.fast_finished = asyncio.Event()

    async def run_phase(self, request: Any, *, stop_event: asyncio.Event | None = None):
        self.calls.append(request.phase)
        if request.phase is CrawlPhase.BACKGROUND:
            return _phase_result(self.repository, CrawlPhase.BACKGROUND)
        assert stop_event is not None
        await stop_event.wait()
        self.fast_drain_started.set()
        await self.fast_drain_release.wait()
        self.fast_finished.set()
        return _phase_result(self.repository, CrawlPhase.FAST, stopped=True)


class _FaultedCoordinator(_ImmediateCoordinator):
    async def run_phase(self, request: Any, *, stop_event: asyncio.Event | None = None):
        result = await super().run_phase(request, stop_event=stop_event)
        return replace(result, pages_completed=0, worker_errors=1)


class _ProviderOrderedSeedDiscoverer:
    async def discover(
        self,
        *,
        root_url: str,
        url_policy: Any,
        discovery_policy: Any,
    ) -> tuple[Any, ...]:
        del root_url, url_policy
        urls = (
            "https://example.com/legal",
            *(f"https://example.com/product/{index}" for index in range(6)),
            "https://example.com/pricing",
            "https://example.com/about-us",
        )
        return tuple(
            discovery_policy.sitemap(SitemapEntry(url, "https://example.com/sitemap.xml"))
            for url in urls
        )


def _request(repository: _Repository) -> OfficialSiteCrawlLifecycleRequest:
    authoritative = repository.config.crawl_mode is CrawlMode.AUTHORITATIVE
    return OfficialSiteCrawlLifecycleRequest(
        workspace_id="ws",
        brand_id="brand",
        recon_run_id=repository.recon_id,
        root_url="https://example.com/",
        allowed_registrable_domain="example.com",
        config=repository.config,
        client_entity_id=uuid4() if authoritative else None,
        fast_claim_run_id=uuid4() if authoritative else None,
        background_claim_run_id=uuid4() if authoritative else None,
    )


def test_deadline_freezes_fast_without_cancelling_inflight_and_background_reuses_run() -> None:
    async def scenario() -> None:
        repository = _Repository(_config(), deadline_seconds=0.01)
        coordinator = _DeadlineCoordinator(repository)
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=repository,
            coordinator_factory=lambda **_: coordinator,
        )
        result = await lifecycle.run(_request(repository))
        assert result.status is CrawlRunStatus.COMPLETED
        assert coordinator.calls == [CrawlPhase.FAST, CrawlPhase.BACKGROUND]
        assert not coordinator.cancelled
        assert coordinator.fast_finished.is_set()
        assert len(result.fast_checkpoint.snapshot_ids) == 1
        assert len(result.background_checkpoint.snapshot_ids) == 2
        assert (
            result.fast_checkpoint.checkpoint_id
            == repository.checkpoints[CrawlPhase.FAST].checkpoint_id
        )

        # A cold replay creates no run/checkpoint and does not execute either phase again.
        replay = await lifecycle.run(_request(repository))
        assert replay.crawl_run_id == result.crawl_run_id
        assert replay.fast_checkpoint.checkpoint_id == result.fast_checkpoint.checkpoint_id
        assert (
            replay.background_checkpoint.checkpoint_id == result.background_checkpoint.checkpoint_id
        )
        assert coordinator.calls == [CrawlPhase.FAST, CrawlPhase.BACKGROUND]

    run_async(scenario())


def test_initial_root_and_sitemap_batch_uses_the_shared_category_quota_prefix() -> None:
    async def scenario() -> None:
        repository = _Repository(_config(), deadline_seconds=1)
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=repository,
            coordinator_factory=lambda **_: _ImmediateCoordinator(repository),
            seed_discoverer=_ProviderOrderedSeedDiscoverer(),
        )

        await lifecycle.run(_request(repository))

        fetch_keys = tuple(observation.fetch_key for observation in repository.discoveries)
        assert fetch_keys[:6] == (
            "https://example.com/",
            "https://example.com/product/0",
            "https://example.com/product/1",
            "https://example.com/product/2",
            "https://example.com/pricing",
            "https://example.com/about-us",
        )
        assert len(fetch_keys) == 10

    run_async(scenario())


class _BlockingMaterializer:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[Any] = []

    async def materialize(self, request: Any) -> OfficialSiteMaterializationResult:
        self.calls.append(request)
        if request.phase is CrawlPhase.FAST:
            self.started.set()
            await self.release.wait()
        return OfficialSiteMaterializationResult(
            workspace_id=request.workspace_id,
            crawl_run_id=request.crawl_run_id,
            claim_run_id=request.claim_run_id,
            checkpoint_id=request.checkpoint_id,
            client_kb_version=1 if request.phase is CrawlPhase.FAST else 2,
            claim_ids=(),
            filled_fields=(),
            empty_fields=("client.product",),
            failed_fields=(),
        )


def test_fast_materialization_overlaps_safe_inflight_drain_after_deadline() -> None:
    async def scenario() -> None:
        repository = _Repository(_config(CrawlMode.AUTHORITATIVE), deadline_seconds=0.01)
        coordinator = _DrainAfterDeadlineCoordinator(repository)
        materializer = _BlockingMaterializer()
        materializer.release.set()
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=repository,
            coordinator_factory=lambda **_: coordinator,
            materializer=materializer,
        )

        task = asyncio.create_task(lifecycle.run(_request(repository)))
        await asyncio.wait_for(coordinator.fast_drain_started.wait(), timeout=1)
        await asyncio.wait_for(materializer.started.wait(), timeout=1)
        assert not coordinator.fast_finished.is_set()
        assert repository.status is CrawlRunStatus.FAST_CLOSING

        coordinator.fast_drain_release.set()
        result = await asyncio.wait_for(task, timeout=1)
        assert result.status is CrawlRunStatus.COMPLETED
        assert result.fast_materialization is not None

    run_async(scenario())


def test_fast_complete_is_not_published_before_authoritative_client_kb_commit() -> None:
    async def scenario() -> None:
        repository = _Repository(_config(CrawlMode.AUTHORITATIVE), deadline_seconds=1)
        coordinator = _ImmediateCoordinator(repository)
        materializer = _BlockingMaterializer()
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=repository,
            coordinator_factory=lambda **_: coordinator,
            materializer=materializer,
        )
        task = asyncio.create_task(lifecycle.run(_request(repository)))
        await asyncio.wait_for(materializer.started.wait(), timeout=1)
        assert repository.status is CrawlRunStatus.FAST_CLOSING
        assert CrawlRunStatus.FAST_COMPLETE not in {next_ for _, next_ in repository.transitions}
        materializer.release.set()
        result = await task
        assert result.fast_materialization is not None
        assert result.status is CrawlRunStatus.COMPLETED
        assert [call.phase for call in materializer.calls] == [
            CrawlPhase.FAST,
            CrawlPhase.BACKGROUND,
        ]

    run_async(scenario())


def test_off_and_authoritative_without_materializer_fail_before_any_crawl() -> None:
    async def scenario() -> None:
        off = _Repository(_config(CrawlMode.OFF))
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=off,
            coordinator_factory=lambda **_: _ImmediateCoordinator(off),
        )
        with pytest.raises(ValueError, match="off mode"):
            await lifecycle.run(_request(off))

        authoritative = _Repository(_config(CrawlMode.AUTHORITATIVE))
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=authoritative,
            coordinator_factory=lambda **_: _ImmediateCoordinator(authoritative),
        )
        with pytest.raises(ValueError, match="requires a corpus materializer"):
            await lifecycle.run(_request(authoritative))

    run_async(scenario())


def test_durable_worker_error_requeues_without_freezing_or_false_completion() -> None:
    async def scenario() -> None:
        repository = _Repository(_config(), deadline_seconds=1)
        repository.phase_blockers = 1
        faulted = _FaultedCoordinator(repository)
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=repository,
            coordinator_factory=lambda **_: faulted,
        )
        with pytest.raises(CrawlPhasePendingError, match="fast crawl phase") as raised:
            await lifecycle.run(_request(repository))
        assert raised.value.crawl_run_id == repository.run_id
        assert raised.value.blockers == 1
        assert repository.status is CrawlRunStatus.FAST_ACTIVE
        assert repository.checkpoints == {}

        repository.phase_blockers = 0
        resumed = OfficialSiteCrawlLifecycle(
            repository=repository,
            coordinator_factory=lambda **_: _ImmediateCoordinator(repository),
        )
        result = await resumed.run(_request(repository))
        assert result.status is CrawlRunStatus.COMPLETED

    run_async(scenario())


def test_lifecycle_contains_no_provider_branching() -> None:
    source = Path("subsystems/research/clue_research/official_site/lifecycle.py").read_text(
        encoding="utf-8"
    )
    assert "firecrawl" not in source.casefold()
    assert "scrapling" not in source.casefold()
