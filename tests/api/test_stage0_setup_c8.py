"""C8 additive setup projection contract without database or provider access."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from clue_api.stage0_setup import _setup_official_site
from clue_research.official_site import (
    CrawlPhase,
    CrawlProgressEventKind,
    CrawlRunStatus,
    OfficialSiteProgressView,
    OperatorState,
)


def test_setup_projection_is_additive_body_free_and_preserves_operational_states() -> None:
    view = OfficialSiteProgressView(
        workspace_id="ws-c8",
        crawl_run_id=uuid4(),
        recon_run_id=uuid4(),
        run_status=CrawlRunStatus.BACKGROUND_ACTIVE,
        phase=CrawlPhase.BACKGROUND,
        message="Fast research complete; deeper research is continuing.",
        states=(
            OperatorState.QUEUED,
            OperatorState.PERSISTED,
            OperatorState.EXTRACTED,
            OperatorState.PARTIAL,
        ),
        queued=2,
        leased=1,
        provider_active=1,
        reconciliation_pending=0,
        persistence_pending=0,
        retry_wait=1,
        fetched=6,
        refused=1,
        failed=0,
        quarantined=0,
        total_pages=10,
        snapshots=6,
        unique_blobs=5,
        fetch_spend_unknown=0,
        extraction_prepared=1,
        extraction_active=1,
        extraction_materialized=5,
        extraction_empty=1,
        extraction_failed=1,
        extraction_spend_unknown=0,
        checkpoint_count=1,
        provider_cost_cents=2,
        recovery_required=False,
        partial=True,
        completed=False,
        event_count=9,
        last_event_seq=14,
        last_event_kind=CrawlProgressEventKind.EXTRACTION_COMPLETED,
        created_at=datetime.now(UTC),
    )

    wire = _setup_official_site(view)
    assert wire is not None
    assert wire.queued == 3  # ready plus proven-no-spend retry wait
    assert wire.extraction_active == 2  # prepared plus dispatched/retained
    assert wire.states == ["queued", "persisted", "extracted", "partial"]
    assert wire.last_event_kind == "stage0.crawl.extraction_completed"
    encoded = json.dumps(wire.model_dump(mode="json"), sort_keys=True)
    for forbidden in ("requested_url", "provider_receipt", "raw_body", "authorization"):
        assert forbidden not in encoded


def test_setup_projection_is_honestly_null_before_a_crawl_row_exists() -> None:
    assert _setup_official_site(None) is None
