"""C0: provider/network/DB-free executable official-site crawl contracts."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_research.official_site import (
    ATTEMPT_TRANSITIONS,
    CONTRACT_VERSION,
    HISTORICAL_OFFICIAL_SITE_SOURCE_KEYS,
    OFFICIAL_SITE_SOURCE_KEY,
    OFFICIAL_SITE_TABLE_NAMES,
    PAGE_TRANSITIONS,
    RUN_TRANSITIONS,
    ArtifactRef,
    AttemptDisposition,
    AttemptOutcome,
    ClaimNextRequest,
    ClaimPersistenceRequest,
    ClaimReconciliationRequest,
    CorpusCheckpointRef,
    CostKind,
    CrawlEligibility,
    CrawlLease,
    CrawlMode,
    CrawlPageState,
    CrawlPhase,
    CrawlProgress,
    CrawlRepository,
    CrawlRunCreate,
    CrawlRunRef,
    CrawlRunStatus,
    DiscoveredVia,
    DiscoveryBatch,
    DiscoveryBatchResult,
    FetchAttemptRef,
    FetchAttemptState,
    OfficialSiteCorpusMaterializer,
    OfficialSiteCrawlContractConfig,
    OfficialSiteMaterializationRequest,
    OfficialSiteMaterializationResult,
    PageFetcher,
    PageFetcherCapabilities,
    PageFetchRequest,
    PageFetchResult,
    PageSnapshotRef,
    PersistenceClaim,
    PolicyOutcome,
    ProviderResultMetadata,
    ReclaimResult,
    ReconciliationClaim,
    RetryClass,
    SpendStatus,
    UrlObservation,
    enum_manifest,
    transition_manifest,
)

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "official_site" / "c0_contract_fixture.json"
_PACKAGE = Path(__file__).parents[2] / "subsystems" / "research" / "clue_research" / "official_site"


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_FIXTURE.read_text()))


def test_canonical_fixture_pins_names_enums_and_transition_graphs(
    fixture: dict[str, Any],
) -> None:
    assert fixture["contract_version"] == CONTRACT_VERSION
    assert fixture["source_keys"] == {
        "logical": OFFICIAL_SITE_SOURCE_KEY,
        "historical": list(HISTORICAL_OFFICIAL_SITE_SOURCE_KEYS),
    }
    assert fixture["table_names"] == list(OFFICIAL_SITE_TABLE_NAMES)
    assert fixture["enums"] == enum_manifest()
    assert fixture["transitions"] == transition_manifest()


def test_canonical_fixture_validates_every_cross_component_payload(
    fixture: dict[str, Any],
) -> None:
    config = OfficialSiteCrawlContractConfig.model_validate(fixture["config"])
    PageFetcherCapabilities.model_validate(fixture["fetcher_capabilities"])
    CrawlRunCreate.model_validate(fixture["crawl_run_create"])
    CrawlRunRef.model_validate(fixture["crawl_run_ref"])
    UrlObservation.model_validate(fixture["url_observation"])
    DiscoveryBatch.model_validate(fixture["discovery_batch"])
    DiscoveryBatchResult.model_validate(fixture["discovery_batch_result"])
    ClaimNextRequest.model_validate(fixture["claim_next_request"])
    CrawlLease.model_validate(fixture["crawl_lease"])
    FetchAttemptRef.model_validate(fixture["fetch_attempt_ref"])
    ClaimReconciliationRequest.model_validate(fixture["claim_reconciliation_request"])
    ReconciliationClaim.model_validate(fixture["reconciliation_claim"])
    ClaimPersistenceRequest.model_validate(fixture["claim_persistence_request"])
    PersistenceClaim.model_validate(fixture["persistence_claim"])
    request = PageFetchRequest.model_validate(fixture["fetch_request"])
    result = PageFetchResult.model_validate(fixture["fetch_result"])
    ArtifactRef.model_validate(fixture["artifact_ref"])
    PageSnapshotRef.model_validate(fixture["page_snapshot_ref"])
    CorpusCheckpointRef.model_validate(fixture["corpus_checkpoint_ref"])
    AttemptOutcome.model_validate(fixture["attempt_outcome"])
    ReclaimResult.model_validate(fixture["reclaim_result"])
    CrawlProgress.model_validate(fixture["crawl_progress"])
    materialization_request = OfficialSiteMaterializationRequest.model_validate(
        fixture["materialization_request"]
    )
    materialization_result = OfficialSiteMaterializationResult.model_validate(
        fixture["materialization_result"]
    )

    assert config.max_graph_depth == 2 and config.crawl_mode is CrawlMode.SHADOW
    assert request.requested_url.endswith("/pricing/")
    assert result.content == b"# Pricing\n\nContact sales."
    metadata = result.metadata()
    assert metadata.size_bytes == len(result.content)
    assert "content" not in type(metadata).model_fields
    assert "outgoing_links" not in type(metadata).model_fields
    assert result.cost_kind is CostKind.ACTUAL
    assert result.spend_status is SpendStatus.SPEND_CONFIRMED
    assert materialization_request.phase is CrawlPhase.FAST
    assert materialization_result.source_key == OFFICIAL_SITE_SOURCE_KEY


def test_config_fails_closed_for_unsafe_or_incoherent_bounds(fixture: dict[str, Any]) -> None:
    base = dict(fixture["config"])
    invalid = (
        {**base, "max_graph_depth": 3},
        {**base, "fast_deadline_seconds": 41},
        {**base, "fast_page_ceiling": 101},
        {**base, "per_host_concurrency": 9},
        {**base, "lease_ttl_seconds": 40, "heartbeat_seconds": 20},
    )
    for payload in invalid:
        with pytest.raises(ValidationError):
            OfficialSiteCrawlContractConfig.model_validate(payload)


def test_sitemap_origin_cannot_masquerade_as_graph_depth() -> None:
    with pytest.raises(ValidationError, match="sitemap discovery cannot assign graph depth"):
        UrlObservation(
            discovered_url="https://example.com/pricing",
            discovered_via=DiscoveredVia.SITEMAP,
            fetch_key="https://example.com/pricing",
            fetch_key_hash="a" * 64,
            graph_depth=1,
            eligibility=CrawlEligibility.FAST,
            policy_outcome=PolicyOutcome.ADMITTED,
        )


def test_artifact_reference_cannot_escape_its_workspace() -> None:
    with pytest.raises(ValidationError, match="workspace/content-sha256 addressed"):
        ArtifactRef(
            workspace_id="workspace-1",
            artifact_key=f"workspace-2/{'a' * 64}",
            content_sha256="a" * 64,
            size_bytes=10,
        )


def test_checkpoint_hash_covers_the_exact_ordered_snapshot_set(fixture: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="does not match snapshot_ids"):
        CorpusCheckpointRef.model_validate(
            {**fixture["corpus_checkpoint_ref"], "snapshot_set_sha256": "d" * 64}
        )


def test_paid_ambiguity_is_not_a_retry_class(fixture: dict[str, Any]) -> None:
    base = dict(fixture["fetch_result"])
    ambiguous = PageFetchResult.model_validate(
        {
            **base,
            "content": None,
            "final_url": None,
            "media_type": None,
            "cost_cents": None,
            "cost_kind": "none",
            "spend_status": "spend_unknown",
            "retry_class": "ambiguous",
        }
    )
    assert ambiguous.retry_class is RetryClass.AMBIGUOUS
    assert "retryable_charged" not in enum_manifest()["RetryClass"]

    with pytest.raises(ValidationError, match="spend_unknown requires ambiguous"):
        PageFetchResult.model_validate(
            {
                **base,
                "content": None,
                "final_url": None,
                "media_type": None,
                "cost_cents": None,
                "cost_kind": "none",
                "spend_status": "spend_unknown",
                "retry_class": "permanent",
            }
        )


def test_empty_success_body_is_a_valid_single_page_result(fixture: dict[str, Any]) -> None:
    base = dict(fixture["fetch_result"])
    result = PageFetchResult.model_validate({**base, "content": ""})
    assert result.content == b""
    assert result.metadata().size_bytes == 0


def test_transition_graphs_are_total_and_terminal_states_stay_terminal() -> None:
    assert set(RUN_TRANSITIONS) == set(CrawlRunStatus)
    assert set(PAGE_TRANSITIONS) == set(CrawlPageState)
    assert set(ATTEMPT_TRANSITIONS) == set(FetchAttemptState)

    for terminal_run in (
        CrawlRunStatus.COMPLETED,
        CrawlRunStatus.FAILED,
        CrawlRunStatus.CANCELLED,
    ):
        assert not RUN_TRANSITIONS[terminal_run]
    for terminal_page in (
        CrawlPageState.FETCHED,
        CrawlPageState.FAILED,
        CrawlPageState.QUARANTINED,
        CrawlPageState.REFUSED,
    ):
        assert not PAGE_TRANSITIONS[terminal_page]
    assert FetchAttemptState.DISPATCHED not in ATTEMPT_TRANSITIONS[FetchAttemptState.SPEND_UNKNOWN]


def test_attempt_dispositions_cannot_encode_an_impossible_state_pair() -> None:
    with pytest.raises(ValidationError, match="incompatible attempt/page state"):
        AttemptOutcome(
            disposition=AttemptDisposition.RECONCILE,
            attempt_state=FetchAttemptState.SPEND_UNKNOWN,
            page_state=CrawlPageState.QUARANTINED,
            reason_code="wrong_terminal_state",
        )


def test_contract_modules_have_no_provider_network_or_database_imports() -> None:
    forbidden_roots = {
        "aiohttp",
        "asyncpg",
        "firecrawl",
        "httpx",
        "requests",
        "scrapling",
        "sqlalchemy",
    }
    found: set[str] = set()
    # C1 adds the PostgreSQL repository beside these frozen C0 modules. Keep the purity guard on
    # the contracts/seams/state graphs themselves rather than accidentally banning the planned
    # implementation from its package.
    for source_file in (
        _PACKAGE / "contracts.py",
        _PACKAGE / "seams.py",
        _PACKAGE / "transitions.py",
    ):
        tree = ast.parse(source_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".", 1)[0])
    assert not found & forbidden_roots


class _FetcherDouble:
    capabilities = PageFetcherCapabilities(
        provider_key="fake",
        supports_operation_lookup=False,
        supports_idempotency_key=False,
        reports_redirect_chain=True,
        reports_outgoing_links=True,
        reports_actual_cost=False,
        reports_provider_receipt=False,
        proves_no_spend_before_dispatch=True,
    )

    async def fetch_one(self, request: PageFetchRequest) -> PageFetchResult:
        raise NotImplementedError(request.operation_key)


class _RepositoryDouble:
    async def create_or_get_run(self, request: Any) -> Any:
        raise NotImplementedError(request)

    async def record_discoveries(self, batch: Any) -> Any:
        raise NotImplementedError(batch)

    async def claim_next(self, request: ClaimNextRequest) -> CrawlLease | None:
        raise NotImplementedError(request)

    async def claim_reconciliation(
        self, request: ClaimReconciliationRequest
    ) -> ReconciliationClaim | None:
        raise NotImplementedError(request)

    async def claim_persistence(self, request: ClaimPersistenceRequest) -> PersistenceClaim | None:
        raise NotImplementedError(request)

    async def renew_lease(self, lease: CrawlLease, *, lease_ttl_seconds: int) -> bool:
        raise NotImplementedError(lease, lease_ttl_seconds)

    async def begin_attempt(self, lease: CrawlLease, **kwargs: Any) -> FetchAttemptRef:
        raise NotImplementedError(lease, kwargs)

    async def mark_attempt_dispatched(self, lease: CrawlLease, attempt: FetchAttemptRef) -> bool:
        raise NotImplementedError(lease, attempt)

    async def record_provider_result(
        self, lease: CrawlLease, attempt: FetchAttemptRef, result: ProviderResultMetadata
    ) -> bool:
        raise NotImplementedError(lease, attempt, result)

    async def persist_snapshot(
        self,
        lease: CrawlLease,
        attempt: FetchAttemptRef,
        artifact: Any,
        result: ProviderResultMetadata,
        outgoing_links: tuple[Any, ...],
    ) -> Any:
        raise NotImplementedError(lease, attempt, artifact, result, outgoing_links)

    async def complete_page(self, lease: CrawlLease, *, snapshot_id: Any) -> bool:
        raise NotImplementedError(lease, snapshot_id)

    async def disposition_attempt(self, lease: Any, attempt: Any, outcome: AttemptOutcome) -> bool:
        raise NotImplementedError(lease, attempt, outcome)

    async def reclaim_expired_leases(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> ReclaimResult:
        raise NotImplementedError(workspace_id, crawl_run_id)

    async def freeze_corpus_checkpoint(
        self, *, workspace_id: str, crawl_run_id: UUID, phase: CrawlPhase
    ) -> Any:
        raise NotImplementedError(workspace_id, crawl_run_id, phase)

    async def transition_run(self, **kwargs: Any) -> bool:
        raise NotImplementedError(kwargs)

    async def read_progress(self, *, workspace_id: str, crawl_run_id: UUID) -> Any:
        raise NotImplementedError(workspace_id, crawl_run_id)


class _MaterializerDouble:
    async def materialize(
        self, request: OfficialSiteMaterializationRequest
    ) -> OfficialSiteMaterializationResult:
        raise NotImplementedError(request.checkpoint_id)


def test_protocols_are_structural_and_provider_neutral() -> None:
    assert isinstance(_FetcherDouble(), PageFetcher)
    assert isinstance(_RepositoryDouble(), CrawlRepository)
    assert isinstance(_MaterializerDouble(), OfficialSiteCorpusMaterializer)

    outcome = AttemptOutcome(
        disposition=AttemptDisposition.QUARANTINE,
        attempt_state=FetchAttemptState.QUARANTINED,
        page_state=CrawlPageState.QUARANTINED,
        reason_code="provider_outcome_ambiguous",
    )
    assert outcome.page_state is CrawlPageState.QUARANTINED


def test_reconciliation_claim_uses_a_new_page_fence_without_rewriting_attempt_identity() -> None:
    run_id = UUID("10000000-0000-4000-8000-000000000001")
    page_id = UUID("20000000-0000-4000-8000-000000000001")
    lease = CrawlLease(
        workspace_id="workspace-1",
        crawl_run_id=run_id,
        page_id=page_id,
        worker_id="reconciler-2",
        lease_generation=2,
        phase=CrawlPhase.BACKGROUND,
        fetch_key="https://example.com/pricing/",
        requested_url="https://example.com/pricing/",
        host="example.com",
        graph_depth=1,
        expires_at=datetime.now(UTC),
    )
    attempt = FetchAttemptRef(
        fetch_attempt_id=UUID("30000000-0000-4000-8000-000000000001"),
        workspace_id="workspace-1",
        crawl_run_id=run_id,
        page_id=page_id,
        attempt_number=1,
        lease_generation=1,
        operation_key="crawl:run-1:page-1:attempt-1",
        provider_key="fake",
        state=FetchAttemptState.SPEND_UNKNOWN,
    )

    claim = ReconciliationClaim(lease=lease, attempt=attempt)

    assert claim.lease.lease_generation > claim.attempt.lease_generation


def test_persistence_claim_resumes_recorded_success_without_rewriting_attempt_identity() -> None:
    run_id = UUID("10000000-0000-4000-8000-000000000001")
    page_id = UUID("20000000-0000-4000-8000-000000000001")
    lease = CrawlLease(
        workspace_id="workspace-1",
        crawl_run_id=run_id,
        page_id=page_id,
        worker_id="persistence-worker-2",
        lease_generation=2,
        phase=CrawlPhase.BACKGROUND,
        fetch_key="https://example.com/pricing/",
        requested_url="https://example.com/pricing/",
        host="example.com",
        graph_depth=1,
        expires_at=datetime.now(UTC),
    )
    attempt = FetchAttemptRef(
        fetch_attempt_id=UUID("30000000-0000-4000-8000-000000000001"),
        workspace_id="workspace-1",
        crawl_run_id=run_id,
        page_id=page_id,
        attempt_number=1,
        lease_generation=1,
        operation_key="crawl:run-1:page-1:attempt-1",
        provider_key="fake",
        state=FetchAttemptState.PROVIDER_SUCCEEDED,
    )

    claim = PersistenceClaim(lease=lease, attempt=attempt)

    assert claim.lease.lease_generation > claim.attempt.lease_generation
