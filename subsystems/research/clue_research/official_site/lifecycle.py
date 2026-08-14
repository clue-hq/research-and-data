"""C6 one-run fast/background lifecycle over the durable official-site frontier.

This module owns phase sequencing and immutable checkpoint publication.  It does not choose a
provider, perform HTTP composition, enqueue fleet work, or implement semantic extraction.  Those
remain injected composition/materialization seams.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from clue_research.official_site.contracts import (
    CorpusCheckpointRef,
    CrawlMode,
    CrawlPhase,
    CrawlRunCreate,
    CrawlRunRef,
    CrawlRunRuntimeRef,
    CrawlRunStatus,
    DiscoveryBatch,
    OfficialSiteCrawlContractConfig,
    OfficialSiteMaterializationRequest,
    OfficialSiteMaterializationResult,
    UrlObservation,
)
from clue_research.official_site.coordinator import (
    CoordinatorPhaseRequest,
    CoordinatorPhaseResult,
)
from clue_research.official_site.discovery import OfficialSiteDiscoveryPolicy
from clue_research.official_site.models import CrawlStateConflictError
from clue_research.official_site.seams import OfficialSiteCorpusMaterializer
from clue_research.official_site.url_policy import ConservativeUrlPolicy, UrlPolicyConfig


class CrawlPhaseRunner(Protocol):
    async def run_phase(
        self,
        request: CoordinatorPhaseRequest,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> CoordinatorPhaseResult: ...


class CrawlCoordinatorFactory(Protocol):
    def __call__(
        self,
        *,
        url_policy: ConservativeUrlPolicy,
        discovery_policy: OfficialSiteDiscoveryPolicy,
    ) -> CrawlPhaseRunner: ...


class CrawlSeedDiscoverer(Protocol):
    """Optional bounded sitemap/robots inventory supplied by live C6 composition."""

    async def discover(
        self,
        *,
        root_url: str,
        url_policy: ConservativeUrlPolicy,
        discovery_policy: OfficialSiteDiscoveryPolicy,
    ) -> tuple[UrlObservation, ...]: ...


class CrawlLifecycleRepository(Protocol):
    async def create_or_get_run(self, request: CrawlRunCreate) -> CrawlRunRef: ...

    async def read_run_runtime(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> CrawlRunRuntimeRef: ...

    async def fast_deadline_remaining_seconds(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> float: ...

    async def record_discoveries(self, batch: DiscoveryBatch) -> object: ...

    async def transition_run(
        self,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        expected: CrawlRunStatus,
        next_status: CrawlRunStatus,
    ) -> bool: ...

    async def close_fast_and_freeze_checkpoint(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> CorpusCheckpointRef: ...

    async def freeze_corpus_checkpoint_once(
        self, *, workspace_id: str, crawl_run_id: UUID, phase: CrawlPhase
    ) -> CorpusCheckpointRef: ...

    async def read_latest_checkpoint(
        self, *, workspace_id: str, crawl_run_id: UUID, phase: CrawlPhase
    ) -> CorpusCheckpointRef | None: ...

    async def count_phase_blockers(
        self, *, workspace_id: str, crawl_run_id: UUID, phase: CrawlPhase
    ) -> int: ...


class CrawlPhasePendingError(RuntimeError):
    """A durable phase has recoverable work and must be requeued, not falsely completed."""

    def __init__(self, *, crawl_run_id: UUID, phase: CrawlPhase, blockers: int) -> None:
        super().__init__(f"{phase.value} crawl phase has {blockers} durable blocker(s)")
        self.crawl_run_id = crawl_run_id
        self.phase = phase
        self.blockers = blockers


@dataclass(frozen=True, slots=True)
class OfficialSiteCrawlLifecycleRequest:
    workspace_id: str
    brand_id: str
    recon_run_id: UUID
    root_url: str
    allowed_registrable_domain: str
    config: OfficialSiteCrawlContractConfig
    client_entity_id: UUID | None = None
    fast_claim_run_id: UUID | None = None
    background_claim_run_id: UUID | None = None
    extraction_model_id: str = "not-materialized"
    extraction_prompt_version: str = "not-materialized"
    extraction_schema_version: str = "not-materialized"

    def __post_init__(self) -> None:
        if not self.workspace_id or not self.brand_id or not self.root_url:
            raise ValueError("workspace, brand, and root URL are required")
        if not self.allowed_registrable_domain:
            raise ValueError("allowed registrable domain is required")
        if self.config.crawl_mode is CrawlMode.AUTHORITATIVE and (
            self.client_entity_id is None
            or self.fast_claim_run_id is None
            or self.background_claim_run_id is None
        ):
            raise ValueError("authoritative crawling requires client and both claim-run identities")


@dataclass(frozen=True, slots=True)
class OfficialSiteCrawlLifecycleResult:
    workspace_id: str
    crawl_run_id: UUID
    recon_run_id: UUID
    status: CrawlRunStatus
    fast_checkpoint: CorpusCheckpointRef
    background_checkpoint: CorpusCheckpointRef
    fast_phase: CoordinatorPhaseResult | None
    background_phase: CoordinatorPhaseResult | None
    fast_materialization: OfficialSiteMaterializationResult | None
    background_materialization: OfficialSiteMaterializationResult | None


class OfficialSiteCrawlLifecycle:
    """Cold-resumable C6 phase state machine for one recon-owned crawl run."""

    def __init__(
        self,
        *,
        repository: CrawlLifecycleRepository,
        coordinator_factory: CrawlCoordinatorFactory,
        seed_discoverer: CrawlSeedDiscoverer | None = None,
        materializer: OfficialSiteCorpusMaterializer | None = None,
    ) -> None:
        self._repository = repository
        self._coordinator_factory = coordinator_factory
        self._seed_discoverer = seed_discoverer
        self._materializer = materializer

    async def run(
        self, request: OfficialSiteCrawlLifecycleRequest
    ) -> OfficialSiteCrawlLifecycleResult:
        if request.config.crawl_mode is CrawlMode.OFF:
            raise ValueError("crawl lifecycle cannot execute in off mode")
        if request.config.crawl_mode is CrawlMode.AUTHORITATIVE and self._materializer is None:
            raise ValueError("authoritative crawl composition requires a corpus materializer")

        url_policy = ConservativeUrlPolicy(
            UrlPolicyConfig(
                root_url=request.root_url,
                allowed_registrable_domain=request.allowed_registrable_domain,
                allow_subdomains=request.config.allow_subdomains,
                version=request.config.url_policy_version,
            )
        )
        discovery = OfficialSiteDiscoveryPolicy(url_policy=url_policy)
        root = discovery.root(request.root_url)
        if root.fetch_key is None:
            raise ValueError(f"root URL was refused by the pinned policy: {root.policy_reason}")
        run = await self._repository.create_or_get_run(
            CrawlRunCreate(
                workspace_id=request.workspace_id,
                brand_id=request.brand_id,
                client_entity_id=request.client_entity_id,
                recon_run_id=request.recon_run_id,
                root_discovered_url=request.root_url,
                root_fetch_key=root.fetch_key,
                allowed_registrable_domain=request.allowed_registrable_domain,
                config=request.config,
            )
        )
        if run.created:
            observations = [root]
            if self._seed_discoverer is not None:
                observations.extend(
                    await self._seed_discoverer.discover(
                        root_url=request.root_url,
                        url_policy=url_policy,
                        discovery_policy=discovery,
                    )
                )
            await self._repository.record_discoveries(
                DiscoveryBatch(
                    workspace_id=request.workspace_id,
                    crawl_run_id=run.crawl_run_id,
                    observations=tuple(observations),
                )
            )

        runtime = await self._repository.read_run_runtime(
            workspace_id=request.workspace_id,
            crawl_run_id=run.crawl_run_id,
        )
        self._assert_replay(request, runtime)
        coordinator = self._coordinator_factory(
            url_policy=url_policy,
            discovery_policy=discovery,
        )
        fast_phase: CoordinatorPhaseResult | None = None
        background_phase: CoordinatorPhaseResult | None = None
        fast_materialization: OfficialSiteMaterializationResult | None = None
        background_materialization: OfficialSiteMaterializationResult | None = None

        if runtime.status is CrawlRunStatus.QUEUED:
            transitioned = await self._repository.transition_run(
                workspace_id=request.workspace_id,
                crawl_run_id=run.crawl_run_id,
                expected=CrawlRunStatus.QUEUED,
                next_status=CrawlRunStatus.FAST_ACTIVE,
            )
            if not transitioned:
                raise CrawlStateConflictError("queued crawl lost its fast activation fence")
            runtime = await self._runtime(request.workspace_id, run.crawl_run_id)

        if runtime.status is CrawlRunStatus.FAST_ACTIVE:
            fast_phase, fast_checkpoint = await self._run_fast(
                request=request,
                crawl_run_id=run.crawl_run_id,
                coordinator=coordinator,
            )
            runtime = await self._runtime(request.workspace_id, run.crawl_run_id)
        else:
            fast_checkpoint = await self._required_checkpoint(
                request.workspace_id, run.crawl_run_id, CrawlPhase.FAST
            )

        if runtime.status is CrawlRunStatus.FAST_CLOSING:
            if fast_phase is None:
                # A previous process may have frozen the deadline checkpoint and then failed while
                # publishing a retained result. FAST_CLOSING permits recovery claims, but never a
                # new ordinary URL claim, so replay settles C4 work without mutating the fast set.
                fast_phase = await coordinator.run_phase(
                    CoordinatorPhaseRequest(
                        workspace_id=request.workspace_id,
                        crawl_run_id=run.crawl_run_id,
                        phase=CrawlPhase.FAST,
                        config=runtime.config,
                        worker_id_prefix=f"official-site:{run.crawl_run_id}:fast-recovery",
                    )
                )
            await self._ensure_phase_ready(
                workspace_id=request.workspace_id,
                crawl_run_id=run.crawl_run_id,
                phase=CrawlPhase.FAST,
                result=fast_phase,
            )
            if request.config.crawl_mode is CrawlMode.AUTHORITATIVE:
                fast_materialization = await self._materialize(
                    request=request,
                    crawl_run_id=run.crawl_run_id,
                    checkpoint=fast_checkpoint,
                    phase=CrawlPhase.FAST,
                )
            transitioned = await self._repository.transition_run(
                workspace_id=request.workspace_id,
                crawl_run_id=run.crawl_run_id,
                expected=CrawlRunStatus.FAST_CLOSING,
                next_status=CrawlRunStatus.FAST_COMPLETE,
            )
            if not transitioned:
                raise CrawlStateConflictError("fast materialization lost its run-state fence")
            runtime = await self._runtime(request.workspace_id, run.crawl_run_id)

        if runtime.status is CrawlRunStatus.FAST_COMPLETE:
            transitioned = await self._repository.transition_run(
                workspace_id=request.workspace_id,
                crawl_run_id=run.crawl_run_id,
                expected=CrawlRunStatus.FAST_COMPLETE,
                next_status=CrawlRunStatus.BACKGROUND_ACTIVE,
            )
            if not transitioned:
                raise CrawlStateConflictError("background activation lost its run-state fence")
            runtime = await self._runtime(request.workspace_id, run.crawl_run_id)

        if runtime.status is CrawlRunStatus.BACKGROUND_ACTIVE:
            background_phase = await coordinator.run_phase(
                CoordinatorPhaseRequest(
                    workspace_id=request.workspace_id,
                    crawl_run_id=run.crawl_run_id,
                    phase=CrawlPhase.BACKGROUND,
                    config=runtime.config,
                    worker_id_prefix=f"official-site:{run.crawl_run_id}:background",
                )
            )
            await self._ensure_phase_ready(
                workspace_id=request.workspace_id,
                crawl_run_id=run.crawl_run_id,
                phase=CrawlPhase.BACKGROUND,
                result=background_phase,
            )
            background_checkpoint = await self._repository.freeze_corpus_checkpoint_once(
                workspace_id=request.workspace_id,
                crawl_run_id=run.crawl_run_id,
                phase=CrawlPhase.BACKGROUND,
            )
            if request.config.crawl_mode is CrawlMode.AUTHORITATIVE:
                background_materialization = await self._materialize(
                    request=request,
                    crawl_run_id=run.crawl_run_id,
                    checkpoint=background_checkpoint,
                    phase=CrawlPhase.BACKGROUND,
                )
            transitioned = await self._repository.transition_run(
                workspace_id=request.workspace_id,
                crawl_run_id=run.crawl_run_id,
                expected=CrawlRunStatus.BACKGROUND_ACTIVE,
                next_status=CrawlRunStatus.COMPLETED,
            )
            if not transitioned:
                raise CrawlStateConflictError("background completion lost its run-state fence")
            runtime = await self._runtime(request.workspace_id, run.crawl_run_id)
        else:
            background_checkpoint = await self._required_checkpoint(
                request.workspace_id, run.crawl_run_id, CrawlPhase.BACKGROUND
            )

        if runtime.status is not CrawlRunStatus.COMPLETED:
            raise CrawlStateConflictError(
                f"crawl lifecycle cannot resume terminal/non-runnable state {runtime.status.value}"
            )
        return OfficialSiteCrawlLifecycleResult(
            workspace_id=request.workspace_id,
            crawl_run_id=run.crawl_run_id,
            recon_run_id=request.recon_run_id,
            status=runtime.status,
            fast_checkpoint=fast_checkpoint,
            background_checkpoint=background_checkpoint,
            fast_phase=fast_phase,
            background_phase=background_phase,
            fast_materialization=fast_materialization,
            background_materialization=background_materialization,
        )

    async def _run_fast(
        self,
        *,
        request: OfficialSiteCrawlLifecycleRequest,
        crawl_run_id: UUID,
        coordinator: CrawlPhaseRunner,
    ) -> tuple[CoordinatorPhaseResult, CorpusCheckpointRef]:
        stop = asyncio.Event()
        runtime = await self._runtime(request.workspace_id, crawl_run_id)
        phase_task = asyncio.create_task(
            coordinator.run_phase(
                CoordinatorPhaseRequest(
                    workspace_id=request.workspace_id,
                    crawl_run_id=crawl_run_id,
                    phase=CrawlPhase.FAST,
                    config=runtime.config,
                    worker_id_prefix=f"official-site:{crawl_run_id}:fast",
                ),
                stop_event=stop,
            )
        )
        deadline_task = asyncio.create_task(
            self._close_at_deadline(
                workspace_id=request.workspace_id,
                crawl_run_id=crawl_run_id,
                stop=stop,
            )
        )
        try:
            done, _ = await asyncio.wait(
                {phase_task, deadline_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if deadline_task in done:
                checkpoint = deadline_task.result()
                # The coordinator shields already-dispatched calls while the stop signal prevents
                # every subsequent claim.  Late safe results belong to background, never fast.
                phase_result = await phase_task
            else:
                phase_result = phase_task.result()
                deadline_task.cancel()
                await asyncio.gather(deadline_task, return_exceptions=True)
                await self._ensure_phase_ready(
                    workspace_id=request.workspace_id,
                    crawl_run_id=crawl_run_id,
                    phase=CrawlPhase.FAST,
                    result=phase_result,
                )
                checkpoint = await self._repository.close_fast_and_freeze_checkpoint(
                    workspace_id=request.workspace_id,
                    crawl_run_id=crawl_run_id,
                )
                stop.set()
            return phase_result, checkpoint
        except asyncio.CancelledError:
            stop.set()
            # C5 converts cancellation into graceful stop and shields a dispatched paid request.
            await asyncio.gather(phase_task, return_exceptions=True)
            raise
        finally:
            if not deadline_task.done():
                deadline_task.cancel()
            await asyncio.gather(deadline_task, return_exceptions=True)

    async def _ensure_phase_ready(
        self,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        phase: CrawlPhase,
        result: CoordinatorPhaseResult,
    ) -> None:
        blockers = await self._repository.count_phase_blockers(
            workspace_id=workspace_id,
            crawl_run_id=crawl_run_id,
            phase=phase,
        )
        if blockers:
            raise CrawlPhasePendingError(
                crawl_run_id=crawl_run_id,
                phase=phase,
                blockers=blockers,
            )
        if result.worker_errors or result.fenced_workers:
            raise CrawlStateConflictError(
                f"{phase.value} coordinator stopped with "
                f"{result.worker_errors} worker error(s) and "
                f"{result.fenced_workers} fenced worker(s)"
            )

    async def _close_at_deadline(
        self, *, workspace_id: str, crawl_run_id: UUID, stop: asyncio.Event
    ) -> CorpusCheckpointRef:
        remaining = await self._repository.fast_deadline_remaining_seconds(
            workspace_id=workspace_id,
            crawl_run_id=crawl_run_id,
        )
        if remaining > 0:
            await asyncio.sleep(remaining)
        checkpoint = await self._repository.close_fast_and_freeze_checkpoint(
            workspace_id=workspace_id,
            crawl_run_id=crawl_run_id,
        )
        stop.set()
        return checkpoint

    async def _materialize(
        self,
        *,
        request: OfficialSiteCrawlLifecycleRequest,
        crawl_run_id: UUID,
        checkpoint: CorpusCheckpointRef,
        phase: CrawlPhase,
    ) -> OfficialSiteMaterializationResult:
        assert self._materializer is not None and request.client_entity_id is not None
        claim_run_id = (
            request.fast_claim_run_id
            if phase is CrawlPhase.FAST
            else request.background_claim_run_id
        )
        assert claim_run_id is not None
        return await self._materializer.materialize(
            OfficialSiteMaterializationRequest(
                workspace_id=request.workspace_id,
                crawl_run_id=crawl_run_id,
                recon_run_id=request.recon_run_id,
                claim_run_id=claim_run_id,
                client_entity_id=request.client_entity_id,
                checkpoint_id=checkpoint.checkpoint_id,
                phase=phase,
                model_id=request.extraction_model_id,
                prompt_version=request.extraction_prompt_version,
                schema_version=request.extraction_schema_version,
            )
        )

    async def _runtime(self, workspace_id: str, crawl_run_id: UUID) -> CrawlRunRuntimeRef:
        return await self._repository.read_run_runtime(
            workspace_id=workspace_id, crawl_run_id=crawl_run_id
        )

    async def _required_checkpoint(
        self, workspace_id: str, crawl_run_id: UUID, phase: CrawlPhase
    ) -> CorpusCheckpointRef:
        checkpoint = await self._repository.read_latest_checkpoint(
            workspace_id=workspace_id,
            crawl_run_id=crawl_run_id,
            phase=phase,
        )
        if checkpoint is None:
            if phase is CrawlPhase.FAST:
                return await self._repository.close_fast_and_freeze_checkpoint(
                    workspace_id=workspace_id,
                    crawl_run_id=crawl_run_id,
                )
            raise CrawlStateConflictError("advanced run is missing its background checkpoint")
        return checkpoint

    @staticmethod
    def _assert_replay(
        request: OfficialSiteCrawlLifecycleRequest, runtime: CrawlRunRuntimeRef
    ) -> None:
        if (
            runtime.recon_run_id != request.recon_run_id
            or runtime.brand_id != request.brand_id
            or runtime.root_discovered_url != request.root_url
            or runtime.allowed_registrable_domain != request.allowed_registrable_domain
            or runtime.config != request.config
            or runtime.client_entity_id != request.client_entity_id
        ):
            raise ValueError("crawl lifecycle replay disagrees with the pinned run")


__all__ = [
    "CrawlCoordinatorFactory",
    "CrawlLifecycleRepository",
    "CrawlPhaseRunner",
    "CrawlPhasePendingError",
    "CrawlSeedDiscoverer",
    "OfficialSiteCrawlLifecycle",
    "OfficialSiteCrawlLifecycleRequest",
    "OfficialSiteCrawlLifecycleResult",
]
