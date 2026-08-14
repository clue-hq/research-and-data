"""C8 event reduction and observability contracts without provider or database access."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.db.conftest import run_async
from tests.official_site.test_lifecycle_c6 import (
    _BlockingMaterializer,
    _config,
    _ImmediateCoordinator,
    _Repository,
    _request,
)

from clue_obs.otel.metrics import InMemorySink
from clue_research.official_site import (
    CrawlMode,
    CrawlPhase,
    CrawlProgressEnvelope,
    CrawlProgressEvent,
    CrawlProgressEventKind,
    CrawlRunStatus,
    OfficialSiteCrawlLifecycle,
    OfficialSiteProgressView,
    OperatorState,
    privacy_safe_log_label,
    privacy_safe_provider_status,
    progress_event_id,
    record_official_site_metrics,
    reduce_crawl_events,
)


class _Sink:
    def __init__(self) -> None:
        self.events: list[CrawlProgressEvent] = []

    async def emit(self, event: CrawlProgressEvent) -> None:
        self.events.append(event)


def _event(*, event_id: str, kind: CrawlProgressEventKind) -> CrawlProgressEvent:
    return CrawlProgressEvent(
        event_id=event_id,
        kind=kind,
        workspace_id="ws-c8",
        crawl_run_id=uuid4(),
        recon_run_id=uuid4(),
        phase=CrawlPhase.FAST,
    )


def test_event_reducer_is_seq_ordered_and_stable_identity_idempotent() -> None:
    crawl_run_id = uuid4()
    recon_run_id = uuid4()
    started_id = progress_event_id(CrawlProgressEventKind.STARTED, crawl_run_id)
    started = CrawlProgressEvent(
        event_id=started_id,
        kind=CrawlProgressEventKind.STARTED,
        workspace_id="ws-c8",
        crawl_run_id=crawl_run_id,
        recon_run_id=recon_run_id,
        phase=CrawlPhase.FAST,
    )
    checkpoint = CrawlProgressEvent(
        event_id=progress_event_id(
            CrawlProgressEventKind.FAST_CHECKPOINT_FROZEN,
            crawl_run_id,
            subject="checkpoint",
        ),
        kind=CrawlProgressEventKind.FAST_CHECKPOINT_FROZEN,
        workspace_id="ws-c8",
        crawl_run_id=crawl_run_id,
        recon_run_id=recon_run_id,
        phase=CrawlPhase.FAST,
        checkpoint_id=uuid4(),
        snapshot_count=7,
    )
    reduced = reduce_crawl_events(
        (
            CrawlProgressEnvelope(seq=12, event=started),
            CrawlProgressEnvelope(seq=10, event=started),
            CrawlProgressEnvelope(seq=11, event=checkpoint),
        )
    )
    assert reduced.event_count == 2
    assert reduced.last_seq == 12
    assert reduced.last_kind is CrawlProgressEventKind.STARTED


def test_event_contract_has_no_raw_body_receipt_or_url_escape_hatch() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CrawlProgressEvent.model_validate(
            {
                **_event(event_id="safe", kind=CrawlProgressEventKind.STARTED).model_dump(),
                "requested_url": "https://example.com/?token=secret",
                "raw_body": "secret",
                "provider_receipt": {"authorization": "secret"},
            }
        )


def test_free_form_provider_identifiers_are_hashed_before_logging() -> None:
    assert privacy_safe_log_label("safe-request_1", max_length=200) == "safe-request_1"
    unsafe = privacy_safe_log_label("https://provider.test/job?token=secret", max_length=200)
    assert unsafe is not None
    assert unsafe.startswith("sha256:")
    assert "secret" not in unsafe
    status = privacy_safe_provider_status("my_secret_token")
    assert status is not None and status.startswith("sha256:")
    assert privacy_safe_provider_status("temporary_unavailable") == "temporary_unavailable"


def test_metrics_are_derived_from_row_counts_without_workspace_cardinality() -> None:
    sink = InMemorySink()
    view = OfficialSiteProgressView(
        workspace_id="ws-c8",
        crawl_run_id=uuid4(),
        recon_run_id=uuid4(),
        run_status=CrawlRunStatus.COMPLETED,
        phase=CrawlPhase.BACKGROUND,
        message="Company research completed with explicit partial results.",
        states=(
            OperatorState.SPEND_UNKNOWN,
            OperatorState.PERSISTED,
            OperatorState.EXTRACTED,
            OperatorState.PARTIAL,
            OperatorState.COMPLETED,
        ),
        queued=0,
        leased=0,
        provider_active=0,
        reconciliation_pending=1,
        persistence_pending=0,
        retry_wait=0,
        fetched=7,
        refused=0,
        failed=0,
        quarantined=0,
        total_pages=8,
        snapshots=7,
        unique_blobs=6,
        fetch_spend_unknown=1,
        extraction_prepared=0,
        extraction_active=0,
        extraction_materialized=8,
        extraction_empty=1,
        extraction_failed=1,
        extraction_spend_unknown=0,
        checkpoint_count=2,
        provider_cost_cents=12.5,
        recovery_required=True,
        partial=True,
        completed=True,
        event_count=10,
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        average_claim_latency_seconds=1.5,
        lease_contention_pages=2,
        average_provider_latency_seconds=0.75,
        oldest_spend_unknown_age_seconds=30,
        fast_checkpoint_latency_seconds=12,
        background_completion_latency_seconds=22,
    )
    record_official_site_metrics(view, recovery_items=1, sink=sink)
    attrs = {"phase": "background", "status": "completed"}
    assert sink.gauge_value("stage0.official_site.pages.total", **attrs) == 8
    assert sink.gauge_value("stage0.official_site.spend_unknown", **attrs) == 1
    assert sink.gauge_value("stage0.official_site.content.duplicate_ratio", **attrs) > 0
    assert sink.gauge_value("stage0.official_site.claim.latency_seconds", **attrs) == 1.5
    assert sink.gauge_value("stage0.official_site.lease.contention_pages", **attrs) == 2
    assert sink.gauge_value("stage0.official_site.spend_unknown.age_seconds", **attrs) == 30
    assert (
        sink.gauge_value(
            "stage0.official_site.extraction.outcomes", **attrs, outcome="materialized"
        )
        == 8
    )
    assert all("workspace_id" not in dict(key[1]) for key in sink.gauges)


def test_authoritative_lifecycle_emits_every_phase_event_from_real_transitions() -> None:
    async def scenario() -> None:
        repository = _Repository(_config(CrawlMode.AUTHORITATIVE), deadline_seconds=1)
        materializer = _BlockingMaterializer()
        materializer.release.set()
        sink = _Sink()
        lifecycle = OfficialSiteCrawlLifecycle(
            repository=repository,
            coordinator_factory=lambda **_: _ImmediateCoordinator(repository),
            materializer=materializer,
            progress_sink=sink,
        )
        result = await lifecycle.run(_request(repository))
        assert result.status is CrawlRunStatus.COMPLETED
        kinds = [event.kind for event in sink.events]
        assert kinds == [
            CrawlProgressEventKind.STARTED,
            CrawlProgressEventKind.DISCOVERY_COMPLETED,
            CrawlProgressEventKind.FAST_CHECKPOINT_FROZEN,
            CrawlProgressEventKind.EXTRACTION_STARTED,
            CrawlProgressEventKind.EXTRACTION_COMPLETED,
            CrawlProgressEventKind.BACKGROUND_STARTED,
            CrawlProgressEventKind.EXTRACTION_STARTED,
            CrawlProgressEventKind.EXTRACTION_COMPLETED,
            CrawlProgressEventKind.BACKGROUND_COMPLETED,
        ]
        assert all(event.workspace_id == "ws" for event in sink.events)
        assert all(event.recon_run_id == repository.recon_id for event in sink.events)
        assert all("example.com" not in event.model_dump_json() for event in sink.events)

    run_async(scenario())
