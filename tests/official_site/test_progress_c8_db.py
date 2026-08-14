"""C8 real-PostgreSQL progress, event, tenancy, and operator recovery acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from tests.db.conftest import run_async
from tests.official_site.test_coordinator_c5_db import (
    _config as _coordinator_config,
)
from tests.official_site.test_coordinator_c5_db import (
    _coordinator,
    _create_run,
    _phase_request,
    _ScenarioFetcher,
)
from tests.official_site.test_coordinator_c5_db import (
    _seed_scope as _seed_coordinator_scope,
)
from tests.official_site.test_materialization_c7_db import _seed_scope

from clue_api.official_site_progress import DbOfficialSiteProgressEmitter
from clue_db import db_lifespan, transaction
from clue_obs.otel.metrics import InMemorySink, get_metric_sink, set_metric_sink
from clue_research.official_site import (
    CrawlPhase,
    CrawlProgressEvent,
    CrawlProgressEventKind,
    CrawlRunStatus,
    OperatorState,
    PostgresCrawlRepository,
    PostgresOfficialSiteOperations,
    progress_event_id,
)
from clue_storage import FsStorage

pytestmark = pytest.mark.usefixtures("require_official_site_db")


class _EventSink:
    def __init__(self) -> None:
        self.events: list[CrawlProgressEvent] = []

    async def emit(self, event: CrawlProgressEvent) -> None:
        self.events.append(event)


async def _seed_partial_scope(tmp_path: Path) -> tuple[object, UUID, UUID, UUID]:
    scope = await _seed_scope(FsStorage(tmp_path / "c8-artifacts"))
    ambiguous_page_id = uuid4()
    ambiguous_attempt_id = uuid4()
    ambiguous_extraction_id = uuid4()
    provider_request_id = f"safe-request-{ambiguous_attempt_id}"
    async with transaction() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO official_site_extraction_operation (
                    id, workspace_id, crawl_run_id, checkpoint_id, recon_run_id,
                    claim_run_id, client_entity_id, phase, category, field_key,
                    model_id, prompt_version, schema_version, corpus_version,
                    input_sha256, snapshot_ids_json, state, completed_at
                ) VALUES (
                    :id, :workspace_id, :crawl_run_id, :checkpoint_id, :recon_run_id,
                    :claim_run_id, :client_entity_id, 'fast', 'product_value',
                    'client.value_prop', 'fixture', 'c8-prompt', 'c8-schema', 'c8-corpus',
                    :input_sha256, '[]'::jsonb, 'empty', now()
                )
                """
            ),
            {
                "id": uuid4(),
                "workspace_id": scope.workspace_id,
                "crawl_run_id": scope.crawl_run_id,
                "checkpoint_id": scope.checkpoint_id,
                "recon_run_id": scope.recon_run_id,
                "claim_run_id": scope.claim_run_id,
                "client_entity_id": scope.client_entity_id,
                "input_sha256": "a" * 64,
            },
        )
        url = "https://example.com/ambiguous"
        await conn.execute(
            text(
                """
                INSERT INTO official_site_crawl_page (
                    id, workspace_id, crawl_run_id, fetch_key, fetch_key_hash,
                    representative_requested_url, host, graph_depth, priority,
                    priority_reason_json, eligibility, state, lease_generation,
                    attempt_count, discovered_at, queued_at
                ) VALUES (
                    :id, :workspace_id, :crawl_run_id, :url, :fetch_hash, :url,
                    'example.com', 1, 1, '[]'::jsonb, 'both',
                    'reconciliation_pending', 3, 1, now(), now()
                )
                """
            ),
            {
                "id": ambiguous_page_id,
                "workspace_id": scope.workspace_id,
                "crawl_run_id": scope.crawl_run_id,
                "url": url,
                "fetch_hash": hashlib.sha256(url.encode()).hexdigest(),
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO official_site_fetch_attempt (
                    id, workspace_id, crawl_run_id, page_id, attempt_number,
                    lease_generation, worker_id, operation_key, provider_key, state,
                    provider_request_id, requested_url, redirect_chain_json,
                    cost_cents, cost_kind, spend_status, retry_class, started_at, dispatched_at
                ) VALUES (
                    :id, :workspace_id, :crawl_run_id, :page_id, 1, 3, 'c8-worker',
                    :operation_key, 'fixture', 'spend_unknown', :provider_request_id, :url,
                    '[]'::jsonb, 0, 'estimated', 'spend_unknown', 'ambiguous', now(), now()
                )
                """
            ),
            {
                "id": ambiguous_attempt_id,
                "workspace_id": scope.workspace_id,
                "crawl_run_id": scope.crawl_run_id,
                "page_id": ambiguous_page_id,
                "operation_key": f"c8-ambiguous:{ambiguous_attempt_id}",
                "provider_request_id": provider_request_id,
                "url": url,
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO official_site_extraction_operation (
                    id, workspace_id, crawl_run_id, checkpoint_id, recon_run_id,
                    claim_run_id, client_entity_id, phase, category, field_key,
                    model_id, prompt_version, schema_version, corpus_version,
                    input_sha256, snapshot_ids_json, state, failure_code,
                    dispatched_at, completed_at
                ) VALUES (
                    :id, :workspace_id, :crawl_run_id, :checkpoint_id, :recon_run_id,
                    :claim_run_id, :client_entity_id, 'fast', 'pricing_proof',
                    'client.pricing_posture', 'fixture/model', 'c8-prompt', 'c8-schema',
                    'c8-corpus', :input_sha256, '[]'::jsonb, 'spend_unknown',
                    'TimeoutError', now() - interval '30 seconds', now()
                )
                """
            ),
            {
                "id": ambiguous_extraction_id,
                "workspace_id": scope.workspace_id,
                "crawl_run_id": scope.crawl_run_id,
                "checkpoint_id": scope.checkpoint_id,
                "recon_run_id": scope.recon_run_id,
                "claim_run_id": scope.claim_run_id,
                "client_entity_id": scope.client_entity_id,
                "input_sha256": "b" * 64,
            },
        )
    return scope, ambiguous_page_id, ambiguous_attempt_id, ambiguous_extraction_id


def test_rows_and_duplicate_events_produce_body_free_operator_truth(tmp_path: Path) -> None:
    async def scenario() -> None:
        (
            scope,
            ambiguous_page_id,
            ambiguous_attempt_id,
            ambiguous_extraction_id,
        ) = await _seed_partial_scope(tmp_path)
        emitter = DbOfficialSiteProgressEmitter()
        event = CrawlProgressEvent(
            event_id=progress_event_id(
                CrawlProgressEventKind.EXTRACTION_COMPLETED,
                scope.crawl_run_id,
                subject=str(scope.checkpoint_id),
            ),
            kind=CrawlProgressEventKind.EXTRACTION_COMPLETED,
            workspace_id=scope.workspace_id,
            crawl_run_id=scope.crawl_run_id,
            recon_run_id=scope.recon_run_id,
            phase=CrawlPhase.FAST,
            checkpoint_id=scope.checkpoint_id,
            empty_field_count=1,
            outcome="partial",
        )
        await emitter.emit(event)
        await emitter.emit(event)

        operations = PostgresOfficialSiteOperations(conn_factory=transaction)
        metric_sink = InMemorySink()
        previous_sink = get_metric_sink()
        set_metric_sink(metric_sink)
        try:
            report = await operations.read_report(
                workspace_id=scope.workspace_id,
                crawl_run_id=scope.crawl_run_id,
            )
        finally:
            set_metric_sink(previous_sink)
        assert report.progress.event_count == 1
        assert report.progress.last_event_kind is CrawlProgressEventKind.EXTRACTION_COMPLETED
        assert report.progress.snapshots == 4
        assert report.progress.extraction_empty == 1
        assert report.progress.extraction_spend_unknown == 1
        assert report.progress.fetch_spend_unknown == 1
        assert report.progress.recovery_required
        assert report.progress.partial
        assert report.progress.completed
        assert set(report.progress.states) >= {
            OperatorState.SPEND_UNKNOWN,
            OperatorState.PERSISTED,
            OperatorState.EXTRACTED,
            OperatorState.PARTIAL,
            OperatorState.COMPLETED,
        }
        assert len(report.recovery_items) == 2
        item = next(
            candidate
            for candidate in report.recovery_items
            if candidate.fetch_attempt_id == ambiguous_attempt_id
        )
        assert item.page_id == ambiguous_page_id
        assert item.fetch_attempt_id == ambiguous_attempt_id
        assert item.provider_request_id == f"safe-request-{ambiguous_attempt_id}"
        extraction_item = next(
            candidate
            for candidate in report.recovery_items
            if candidate.extraction_operation_id == ambiguous_extraction_id
        )
        assert extraction_item.page_id is None
        assert extraction_item.field_key == "client.pricing_posture"
        assert extraction_item.permitted_action == "review-billing-no-auto-retry"
        serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True)
        assert "ambiguous" not in serialized
        assert "<html" not in serialized
        assert "provider_receipt" not in serialized
        assert "requested_url" not in serialized

        with pytest.raises(ValueError, match="does not exist"):
            await operations.read_progress(
                workspace_id=f"other-{scope.workspace_id}",
                crawl_run_id=scope.crawl_run_id,
            )

        assert not await operations.quarantine_spend_unknown(
            workspace_id=f"other-{scope.workspace_id}",
            crawl_run_id=scope.crawl_run_id,
            fetch_attempt_id=ambiguous_attempt_id,
            expected_lease_generation=3,
        )
        assert await operations.quarantine_spend_unknown(
            workspace_id=scope.workspace_id,
            crawl_run_id=scope.crawl_run_id,
            fetch_attempt_id=ambiguous_attempt_id,
            expected_lease_generation=3,
        )
        assert not await operations.quarantine_spend_unknown(
            workspace_id=scope.workspace_id,
            crawl_run_id=scope.crawl_run_id,
            fetch_attempt_id=ambiguous_attempt_id,
            expected_lease_generation=3,
        )
        settled = await operations.read_report(
            workspace_id=scope.workspace_id,
            crawl_run_id=scope.crawl_run_id,
        )
        assert len(settled.recovery_items) == 1
        assert settled.recovery_items[0].extraction_operation_id == ambiguous_extraction_id
        assert settled.progress.recovery_required
        assert OperatorState.SPEND_UNKNOWN in settled.progress.states
        assert settled.progress.quarantined == 1
        metric_attrs = {"phase": "background", "status": "completed"}
        assert (
            metric_sink.gauge_value(
                "stage0.official_site.provider.outcomes",
                **metric_attrs,
                provider="fixture",
                outcome="success",
            )
            == 4
        )
        assert (
            metric_sink.gauge_value(
                "stage0.official_site.fast_checkpoint.category_pages",
                **metric_attrs,
                category="homepage",
            )
            == 1
        )

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_expired_lease_reclaim_is_db_timed_and_provider_free(tmp_path: Path) -> None:
    async def scenario() -> None:
        scope = await _seed_scope(FsStorage(tmp_path / "reclaim-artifacts"))
        page_id = uuid4()
        url = "https://example.com/stuck"
        async with transaction() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO official_site_crawl_page (
                        id, workspace_id, crawl_run_id, fetch_key, fetch_key_hash,
                        representative_requested_url, host, graph_depth, priority,
                        priority_reason_json, eligibility, state, lease_owner,
                        lease_generation, lease_acquired_at, lease_expires_at,
                        attempt_count, discovered_at, queued_at
                    ) VALUES (
                        :id, :workspace_id, :crawl_run_id, :url, :fetch_hash, :url,
                        'example.com', 1, 2, '[]'::jsonb, 'both', 'leased', 'dead-worker',
                        5, now() - interval '2 minutes', now() - interval '1 minute',
                        0, now(), now()
                    )
                    """
                ),
                {
                    "id": page_id,
                    "workspace_id": scope.workspace_id,
                    "crawl_run_id": scope.crawl_run_id,
                    "url": url,
                    "fetch_hash": hashlib.sha256(url.encode()).hexdigest(),
                },
            )
        operations = PostgresOfficialSiteOperations(conn_factory=transaction)
        before = await operations.read_report(
            workspace_id=scope.workspace_id, crawl_run_id=scope.crawl_run_id
        )
        assert any(item.page_id == page_id for item in before.recovery_items)
        assert before.progress.lease_contention_pages >= 1
        assert before.progress.average_claim_latency_seconds >= 0
        result = await operations.reclaim_expired_leases(
            workspace_id=scope.workspace_id, crawl_run_id=scope.crawl_run_id
        )
        assert result.requeued_pre_dispatch == 1
        async with transaction() as conn:
            state, owner, generation = (
                await conn.execute(
                    text(
                        "SELECT state, lease_owner, lease_generation "
                        "FROM official_site_crawl_page WHERE id = :page_id"
                    ),
                    {"page_id": page_id},
                )
            ).one()
        assert (state, owner, generation) == ("queued", None, 5)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_coordinator_page_events_carry_hash_and_host_without_full_url(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with transaction() as conn:
            workspace_id, brand_id, recon_run_id = await _seed_coordinator_scope(conn)
        config = _coordinator_config(workers=1, per_host=1)
        repository = PostgresCrawlRepository()
        root = f"https://example.com/c8-{uuid4()}?utm_source=private-campaign"
        crawl_run_id = await _create_run(
            repository,
            workspace_id=workspace_id,
            brand_id=brand_id,
            recon_run_id=recon_run_id,
            urls=(root,),
            config=config,
        )
        sink = _EventSink()
        result = await _coordinator(
            repository=repository,
            storage_path=tmp_path / "event-artifacts",
            root=root,
            fetcher=_ScenarioFetcher(),
            progress_sink=sink,
        ).run_phase(
            _phase_request(
                workspace_id,
                crawl_run_id,
                config,
                recon_run_id=recon_run_id,
            )
        )
        assert result.pages_completed == 1
        assert [event.kind for event in sink.events] == [
            CrawlProgressEventKind.PAGE_STARTED,
            CrawlProgressEventKind.PAGE_FETCHED,
        ]
        assert all(event.url_hash is not None for event in sink.events)
        assert all(event.host == "example.com" for event in sink.events)
        assert all("https://" not in event.model_dump_json() for event in sink.events)
        completed = sink.events[-1]
        assert completed.provider_request_id is not None
        assert completed.provider_status == "ok"
        assert completed.http_status == 200
        assert completed.size_bytes is not None and completed.size_bytes > 0
        assert completed.spend_status == "no_spend"
        assert completed.retry_class == "success"
        assert completed.artifact_key is not None
        progress = await repository.read_progress(
            workspace_id=workspace_id, crawl_run_id=crawl_run_id
        )
        assert progress.fetched == 1
        assert progress.status is CrawlRunStatus.FAST_ACTIVE

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())
