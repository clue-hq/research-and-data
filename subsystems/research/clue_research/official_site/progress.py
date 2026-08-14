"""C8 durable progress, metrics, and body-free operator recovery surfaces.

The crawl ledger remains authoritative.  ``run_event`` rows are an at-least-once visibility
stream: readers deduplicate stable event identities and combine the latest event with fresh row
counts.  Nothing in this module advances from elapsed UI time, and no read exposes page bodies,
query-bearing URLs, provider receipts, claim values, credentials, or user identities.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_obs.otel.metrics import MetricSink, get_metric_sink
from clue_research.official_site.contracts import (
    CrawlPhase,
    CrawlRunStatus,
    FrozenContractModel,
    ReclaimResult,
)

log = get_logger("clue_research.official_site.progress")

PROGRESS_SCHEMA_VERSION: Literal["stage0-official-site-c8-v1"] = "stage0-official-site-c8-v1"

METRIC_EVENTS_TOTAL = "stage0.official_site.events.total"
METRIC_FRONTIER_READY = "stage0.official_site.frontier.ready"
METRIC_FRONTIER_LEASED = "stage0.official_site.frontier.leased"
METRIC_FRONTIER_QUARANTINED = "stage0.official_site.frontier.quarantined"
METRIC_PROVIDER_ACTIVE = "stage0.official_site.provider.active"
METRIC_SPEND_UNKNOWN = "stage0.official_site.spend_unknown"
METRIC_PAGES_TOTAL = "stage0.official_site.pages.total"
METRIC_SNAPSHOTS_TOTAL = "stage0.official_site.snapshots.total"
METRIC_UNIQUE_BLOBS = "stage0.official_site.blobs.unique"
METRIC_DUPLICATE_CONTENT_RATIO = "stage0.official_site.content.duplicate_ratio"
METRIC_COST_CENTS = "stage0.official_site.provider.cost_cents"
METRIC_EXTRACTION_TERMINAL = "stage0.official_site.extraction.terminal"
METRIC_EXTRACTION_FAILURES = "stage0.official_site.extraction.failures"
METRIC_CHECKPOINTS = "stage0.official_site.checkpoints"
METRIC_RECOVERY_ITEMS = "stage0.official_site.recovery.items"
METRIC_CLAIM_LATENCY_SECONDS = "stage0.official_site.claim.latency_seconds"
METRIC_LEASE_CONTENTION = "stage0.official_site.lease.contention_pages"
METRIC_PROVIDER_CONCURRENCY = "stage0.official_site.provider.concurrency"
METRIC_PROVIDER_LATENCY_SECONDS = "stage0.official_site.provider.latency_seconds"
METRIC_PROVIDER_OUTCOMES = "stage0.official_site.provider.outcomes"
METRIC_SPEND_UNKNOWN_AGE_SECONDS = "stage0.official_site.spend_unknown.age_seconds"
METRIC_FAST_CHECKPOINT_LATENCY_SECONDS = "stage0.official_site.fast_checkpoint.latency_seconds"
METRIC_FAST_CATEGORY_COVERAGE = "stage0.official_site.fast_checkpoint.category_pages"
METRIC_EXTRACTION_OUTCOMES = "stage0.official_site.extraction.outcomes"
METRIC_BACKGROUND_COMPLETION_LATENCY_SECONDS = (
    "stage0.official_site.background_completion.latency_seconds"
)
METRIC_STALE_COMPLETION_REJECTIONS = "stage0.official_site.stale_completion_rejections"


class CrawlProgressEventKind(StrEnum):
    STARTED = "stage0.crawl.started"
    DISCOVERY_COMPLETED = "stage0.crawl.discovery_completed"
    PAGE_STARTED = "stage0.crawl.page_started"
    PAGE_FETCHED = "stage0.crawl.page_fetched"
    PAGE_REFUSED = "stage0.crawl.page_refused"
    FAST_CHECKPOINT_FROZEN = "stage0.crawl.fast_checkpoint_frozen"
    EXTRACTION_STARTED = "stage0.crawl.extraction_started"
    EXTRACTION_COMPLETED = "stage0.crawl.extraction_completed"
    BACKGROUND_STARTED = "stage0.crawl.background_started"
    BACKGROUND_COMPLETED = "stage0.crawl.background_completed"
    FAILED = "stage0.crawl.failed"


class OperatorState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    PROVIDER_ACTIVE = "provider-active"
    SPEND_UNKNOWN = "spend-unknown"
    PERSISTED = "persisted"
    EXTRACTED = "extracted"
    PARTIAL = "partial"
    COMPLETED = "completed"


class RecoveryKind(StrEnum):
    EXPIRED_LEASE = "expired-lease"
    PROVIDER_AMBIGUITY = "provider-ambiguity"
    PERSISTENCE_PENDING = "persistence-pending"
    EXTRACTION_AMBIGUITY = "extraction-ambiguity"


class CrawlProgressEvent(FrozenContractModel):
    """One privacy-safe, replay-stable visibility event."""

    schema_version: Literal["stage0-official-site-c8-v1"] = PROGRESS_SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=200)
    kind: CrawlProgressEventKind
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    recon_run_id: UUID
    phase: CrawlPhase | None = None
    page_id: UUID | None = None
    snapshot_id: UUID | None = None
    checkpoint_id: UUID | None = None
    lease_generation: int | None = Field(default=None, ge=1)
    url_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    host: str | None = Field(default=None, min_length=1, max_length=253)
    provider_key: str | None = Field(default=None, min_length=1, max_length=64)
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    provider_status: str | None = Field(default=None, min_length=1, max_length=100)
    http_status: int | None = Field(default=None, ge=100, le=599)
    graph_depth: int | None = Field(default=None, ge=0, le=2)
    duration_ms: int | None = Field(default=None, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)
    cost_cents: Decimal | None = Field(default=None, ge=0)
    spend_status: str | None = Field(default=None, min_length=1, max_length=32)
    retry_class: str | None = Field(default=None, min_length=1, max_length=64)
    artifact_key: str | None = Field(default=None, min_length=1, max_length=500)
    discovered_count: int | None = Field(default=None, ge=0)
    snapshot_count: int | None = Field(default=None, ge=0)
    filled_field_count: int | None = Field(default=None, ge=0)
    empty_field_count: int | None = Field(default=None, ge=0)
    failed_field_count: int | None = Field(default=None, ge=0)
    outcome: str | None = Field(default=None, min_length=1, max_length=100)
    failure_code: str | None = Field(default=None, min_length=1, max_length=200)


class CrawlProgressEnvelope(FrozenContractModel):
    seq: int = Field(ge=1)
    event: CrawlProgressEvent


class ReducedCrawlEvents(FrozenContractModel):
    event_count: int = Field(ge=0)
    last_seq: int | None = Field(default=None, ge=1)
    last_kind: CrawlProgressEventKind | None = None
    last_phase: CrawlPhase | None = None


class OfficialSiteProgressView(FrozenContractModel):
    """Rows-first progress safe for setup and operator reads."""

    schema_version: Literal["stage0-official-site-c8-v1"] = PROGRESS_SCHEMA_VERSION
    workspace_id: str = Field(min_length=1)
    crawl_run_id: UUID
    recon_run_id: UUID
    run_status: CrawlRunStatus
    phase: CrawlPhase | None
    message: str = Field(min_length=1, max_length=200)
    states: tuple[OperatorState, ...]
    queued: int = Field(ge=0)
    leased: int = Field(ge=0)
    provider_active: int = Field(ge=0)
    reconciliation_pending: int = Field(ge=0)
    persistence_pending: int = Field(ge=0)
    retry_wait: int = Field(ge=0)
    fetched: int = Field(ge=0)
    refused: int = Field(ge=0)
    failed: int = Field(ge=0)
    quarantined: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    snapshots: int = Field(ge=0)
    unique_blobs: int = Field(ge=0)
    fetch_spend_unknown: int = Field(ge=0)
    extraction_prepared: int = Field(ge=0)
    extraction_active: int = Field(ge=0)
    extraction_materialized: int = Field(ge=0)
    extraction_empty: int = Field(ge=0)
    extraction_failed: int = Field(ge=0)
    extraction_spend_unknown: int = Field(ge=0)
    checkpoint_count: int = Field(ge=0)
    provider_cost_cents: float = Field(ge=0)
    recovery_required: bool
    partial: bool
    completed: bool
    event_count: int = Field(ge=0)
    last_event_seq: int | None = Field(default=None, ge=1)
    last_event_kind: CrawlProgressEventKind | None = None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    average_claim_latency_seconds: float = Field(default=0, ge=0)
    lease_contention_pages: int = Field(default=0, ge=0)
    average_provider_latency_seconds: float = Field(default=0, ge=0)
    oldest_spend_unknown_age_seconds: int = Field(default=0, ge=0)
    fast_checkpoint_latency_seconds: float | None = Field(default=None, ge=0)
    background_completion_latency_seconds: float | None = Field(default=None, ge=0)


class OfficialSiteRecoveryItem(FrozenContractModel):
    """Body-free operator action target; IDs and bounded receipts only."""

    kind: RecoveryKind
    crawl_run_id: UUID
    page_id: UUID | None = None
    fetch_attempt_id: UUID | None = None
    extraction_operation_id: UUID | None = None
    page_state: str | None = Field(default=None, min_length=1, max_length=64)
    attempt_state: str | None = Field(default=None, min_length=1, max_length=64)
    lease_generation: int | None = Field(default=None, ge=0)
    lease_owner: str | None = Field(default=None, max_length=200)
    provider_key: str | None = Field(default=None, max_length=64)
    provider_request_id: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=64)
    field_key: str | None = Field(default=None, max_length=200)
    model_id: str | None = Field(default=None, max_length=200)
    failure_code: str | None = Field(default=None, max_length=120)
    age_seconds: int = Field(ge=0)
    permitted_action: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_target(self) -> OfficialSiteRecoveryItem:
        if self.kind is RecoveryKind.EXTRACTION_AMBIGUITY:
            if self.extraction_operation_id is None or self.page_id is not None:
                raise ValueError("extraction recovery requires only an extraction operation")
        elif self.page_id is None or self.extraction_operation_id is not None:
            raise ValueError("page recovery requires only a page target")
        return self


class OfficialSiteOperatorReport(FrozenContractModel):
    progress: OfficialSiteProgressView
    recovery_items: tuple[OfficialSiteRecoveryItem, ...]


def progress_event_id(
    kind: CrawlProgressEventKind,
    crawl_run_id: UUID,
    *,
    subject: str = "run",
) -> str:
    """Stable identity for at-least-once event deduplication."""

    return str(uuid5(NAMESPACE_URL, f"{PROGRESS_SCHEMA_VERSION}:{crawl_run_id}:{kind}:{subject}"))


def privacy_safe_log_label(value: str | None, *, max_length: int) -> str | None:
    """Keep opaque machine IDs; hash query/path-bearing or otherwise free-form values."""

    if value is None:
        return None
    if len(value) <= max_length and all(
        character.isalnum() or character in {"-", "_", ".", ":"} for character in value
    ):
        return value
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def privacy_safe_provider_status(value: str | None) -> str | None:
    """Expose only the coordinator's bounded status vocabulary; hash every unknown label."""

    if value is None:
        return None
    safe_exact = {
        "ok",
        "completed",
        "success",
        "temporary_unavailable",
        "not_found",
        "failed",
        "rate_limited",
    }
    safe_prefixes = (
        "preflight_refused:",
        "robots_refused:",
        "coordinator_policy_refused:",
    )
    restricted = privacy_safe_log_label(value, max_length=100)
    if restricted == value and (value in safe_exact or value.startswith(safe_prefixes)):
        return value
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def reduce_crawl_events(events: tuple[CrawlProgressEnvelope, ...]) -> ReducedCrawlEvents:
    """Idempotently reduce duplicates by stable identity, selecting the newest DB sequence."""

    latest_by_id: dict[str, CrawlProgressEnvelope] = {}
    for envelope in events:
        held = latest_by_id.get(envelope.event.event_id)
        if held is None or held.seq < envelope.seq:
            latest_by_id[envelope.event.event_id] = envelope
    if not latest_by_id:
        return ReducedCrawlEvents(event_count=0)
    latest = max(latest_by_id.values(), key=lambda item: item.seq)
    return ReducedCrawlEvents(
        event_count=len(latest_by_id),
        last_seq=latest.seq,
        last_kind=latest.event.kind,
        last_phase=latest.event.phase,
    )


def record_crawl_event_metric(event: CrawlProgressEvent, *, sink: MetricSink | None = None) -> None:
    (sink or get_metric_sink()).add(
        METRIC_EVENTS_TOTAL,
        1,
        {
            "kind": event.kind.value,
            "phase": event.phase.value if event.phase is not None else "none",
            "provider": event.provider_key or "none",
        },
    )


def record_official_site_metrics(
    view: OfficialSiteProgressView,
    *,
    recovery_items: int = 0,
    sink: MetricSink | None = None,
) -> None:
    """Emit bounded-cardinality gauges from the authoritative row projection."""

    target = sink or get_metric_sink()
    attributes = {
        "phase": view.phase.value if view.phase is not None else "none",
        "status": view.run_status.value,
    }
    terminal_extractions = (
        view.extraction_materialized
        + view.extraction_empty
        + view.extraction_failed
        + view.extraction_spend_unknown
    )
    target.gauge(METRIC_FRONTIER_READY, view.queued + view.retry_wait, attributes)
    target.gauge(METRIC_FRONTIER_LEASED, view.leased, attributes)
    target.gauge(METRIC_FRONTIER_QUARANTINED, view.quarantined, attributes)
    target.gauge(METRIC_PROVIDER_ACTIVE, view.provider_active, attributes)
    target.gauge(
        METRIC_SPEND_UNKNOWN,
        view.fetch_spend_unknown + view.extraction_spend_unknown,
        attributes,
    )
    target.gauge(METRIC_PAGES_TOTAL, view.total_pages, attributes)
    target.gauge(METRIC_SNAPSHOTS_TOTAL, view.snapshots, attributes)
    target.gauge(METRIC_UNIQUE_BLOBS, view.unique_blobs, attributes)
    ratio = (view.snapshots - view.unique_blobs) / view.snapshots if view.snapshots else 0.0
    target.gauge(METRIC_DUPLICATE_CONTENT_RATIO, ratio, attributes)
    target.gauge(METRIC_COST_CENTS, view.provider_cost_cents, attributes)
    target.gauge(METRIC_EXTRACTION_TERMINAL, terminal_extractions, attributes)
    target.gauge(
        METRIC_EXTRACTION_FAILURES,
        view.extraction_failed + view.extraction_spend_unknown,
        attributes,
    )
    target.gauge(METRIC_CHECKPOINTS, view.checkpoint_count, attributes)
    target.gauge(METRIC_RECOVERY_ITEMS, recovery_items, attributes)
    target.gauge(METRIC_CLAIM_LATENCY_SECONDS, view.average_claim_latency_seconds, attributes)
    target.gauge(METRIC_LEASE_CONTENTION, view.lease_contention_pages, attributes)
    target.gauge(
        METRIC_PROVIDER_LATENCY_SECONDS,
        view.average_provider_latency_seconds,
        {**attributes, "provider": "all"},
    )
    target.gauge(
        METRIC_SPEND_UNKNOWN_AGE_SECONDS,
        view.oldest_spend_unknown_age_seconds,
        attributes,
    )
    if view.fast_checkpoint_latency_seconds is not None:
        target.gauge(
            METRIC_FAST_CHECKPOINT_LATENCY_SECONDS,
            view.fast_checkpoint_latency_seconds,
            attributes,
        )
    if view.background_completion_latency_seconds is not None:
        target.gauge(
            METRIC_BACKGROUND_COMPLETION_LATENCY_SECONDS,
            view.background_completion_latency_seconds,
            attributes,
        )
    for outcome, count in (
        ("materialized", view.extraction_materialized),
        ("empty", view.extraction_empty),
        ("failed", view.extraction_failed),
        ("spend_unknown", view.extraction_spend_unknown),
    ):
        target.gauge(METRIC_EXTRACTION_OUTCOMES, count, {**attributes, "outcome": outcome})


def record_stale_completion_rejection(
    *, phase: CrawlPhase, provider_key: str, sink: MetricSink | None = None
) -> None:
    """Count a worker fenced before it could publish completion."""

    (sink or get_metric_sink()).add(
        METRIC_STALE_COMPLETION_REJECTIONS,
        1,
        {"phase": phase.value, "provider": provider_key},
    )


class PostgresOfficialSiteOperations:
    """Workspace-scoped progress read and narrowly fenced operator recovery."""

    def __init__(self, *, conn_factory: ConnFactory) -> None:
        # Local import breaks the intentional repository -> seam -> progress type cycle while
        # keeping the operator service over the one existing PostgreSQL authority.
        from clue_research.official_site.repository import PostgresCrawlRepository

        self._conn_factory = conn_factory
        self._repository = PostgresCrawlRepository(conn_factory=conn_factory)

    async def read_progress_for_recon(
        self, *, workspace_id: str, recon_run_id: UUID
    ) -> OfficialSiteProgressView | None:
        async with self._conn_factory() as conn:
            run = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM official_site_crawl_run "
                            "WHERE workspace_id = :workspace_id AND recon_run_id = :recon_run_id "
                            "ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"workspace_id": workspace_id, "recon_run_id": recon_run_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return None
            return await self._read_progress(conn, dict(run))

    async def read_progress(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> OfficialSiteProgressView:
        async with self._conn_factory() as conn:
            run = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM official_site_crawl_run "
                            "WHERE workspace_id = :workspace_id AND id = :crawl_run_id"
                        ),
                        {"workspace_id": workspace_id, "crawl_run_id": crawl_run_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                raise ValueError("official-site crawl run does not exist in this workspace")
            return await self._read_progress(conn, dict(run))

    async def read_report(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> OfficialSiteOperatorReport:
        progress = await self.read_progress(workspace_id=workspace_id, crawl_run_id=crawl_run_id)
        recovery_items = await self.read_recovery_items(
            workspace_id=workspace_id, crawl_run_id=crawl_run_id
        )
        try:
            record_official_site_metrics(progress, recovery_items=len(recovery_items))
            await self._record_breakdown_metrics(
                workspace_id=workspace_id,
                crawl_run_id=crawl_run_id,
                phase=progress.phase,
                run_status=progress.run_status,
            )
        except Exception:
            # Metrics are visibility, never authority for an operator read.
            pass
        return OfficialSiteOperatorReport(progress=progress, recovery_items=recovery_items)

    async def read_recovery_items(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> tuple[OfficialSiteRecoveryItem, ...]:
        async with self._conn_factory() as conn:
            page_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT page.id AS page_id, page.state AS page_state,
                                   page.lease_generation, page.lease_owner,
                                   attempt.id AS attempt_id, attempt.state AS attempt_state,
                                   attempt.provider_key, attempt.provider_request_id,
                                   CASE
                                     WHEN attempt.spend_status = 'spend_unknown'
                                       THEN 'provider-ambiguity'
                                     WHEN page.state = 'persistence_pending'
                                       THEN 'persistence-pending'
                                     ELSE 'expired-lease'
                                   END AS recovery_kind,
                                   GREATEST(0, floor(extract(epoch FROM (
                                     now() - COALESCE(
                                       attempt.dispatched_at, page.lease_expires_at,
                                       page.updated_at
                                     )
                                   )))::int) AS age_seconds
                            FROM official_site_crawl_page AS page
                            LEFT JOIN LATERAL (
                                SELECT candidate.*
                                FROM official_site_fetch_attempt AS candidate
                                WHERE candidate.workspace_id = page.workspace_id
                                  AND candidate.crawl_run_id = page.crawl_run_id
                                  AND candidate.page_id = page.id
                                ORDER BY candidate.attempt_number DESC
                                LIMIT 1
                            ) AS attempt ON true
                            WHERE page.workspace_id = :workspace_id
                              AND page.crawl_run_id = :crawl_run_id
                              AND (
                                (
                                  attempt.state = 'spend_unknown'
                                  AND attempt.spend_status = 'spend_unknown'
                                  AND (
                                    page.lease_owner IS NULL
                                    OR page.lease_expires_at <= now()
                                  )
                                )
                                OR (
                                  page.state = 'persistence_pending'
                                  AND (
                                    page.lease_owner IS NULL
                                    OR page.lease_expires_at <= now()
                                  )
                                )
                                OR (
                                  page.state IN ('leased', 'provider_started',
                                    'reconciliation_pending')
                                  AND page.lease_expires_at <= now()
                                )
                              )
                            ORDER BY recovery_kind, page.id
                            """
                        ),
                        {"workspace_id": workspace_id, "crawl_run_id": crawl_run_id},
                    )
                )
                .mappings()
                .all()
            )
            extraction_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, category, field_key, model_id, failure_code,
                                   GREATEST(0, floor(extract(epoch FROM (
                                     now() - COALESCE(completed_at, dispatched_at, created_at)
                                   )))::int) AS age_seconds
                            FROM official_site_extraction_operation
                            WHERE workspace_id = :workspace_id
                              AND crawl_run_id = :crawl_run_id
                              AND state = 'spend_unknown'
                            ORDER BY id
                            """
                        ),
                        {"workspace_id": workspace_id, "crawl_run_id": crawl_run_id},
                    )
                )
                .mappings()
                .all()
            )
        actions = {
            RecoveryKind.EXPIRED_LEASE: "reclaim-expired",
            RecoveryKind.PROVIDER_AMBIGUITY: "provider-lookup-or-quarantine",
            RecoveryKind.PERSISTENCE_PENDING: "resume-persistence",
        }
        page_items = tuple(
            OfficialSiteRecoveryItem(
                kind=kind,
                crawl_run_id=crawl_run_id,
                page_id=row["page_id"],
                fetch_attempt_id=row["attempt_id"],
                page_state=row["page_state"],
                attempt_state=row["attempt_state"],
                lease_generation=row["lease_generation"],
                lease_owner=row["lease_owner"],
                provider_key=row["provider_key"],
                provider_request_id=privacy_safe_log_label(
                    row["provider_request_id"], max_length=200
                ),
                age_seconds=row["age_seconds"],
                permitted_action=actions[kind],
            )
            for row in page_rows
            for kind in (RecoveryKind(row["recovery_kind"]),)
        )
        extraction_items = tuple(
            OfficialSiteRecoveryItem(
                kind=RecoveryKind.EXTRACTION_AMBIGUITY,
                crawl_run_id=crawl_run_id,
                extraction_operation_id=row["id"],
                category=row["category"],
                field_key=row["field_key"],
                model_id=privacy_safe_log_label(row["model_id"], max_length=200),
                failure_code=privacy_safe_log_label(row["failure_code"], max_length=120),
                age_seconds=row["age_seconds"],
                permitted_action="review-billing-no-auto-retry",
            )
            for row in extraction_rows
        )
        return page_items + extraction_items

    async def _record_breakdown_metrics(
        self,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        phase: CrawlPhase | None,
        run_status: CrawlRunStatus,
    ) -> None:
        """Emit provider/host/category series without exposing tenant IDs as labels."""

        params = {"workspace_id": workspace_id, "crawl_run_id": crawl_run_id}
        async with self._conn_factory() as conn:
            active_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT page.host, COALESCE(attempt.provider_key, 'unknown') AS provider,
                                   count(*)::int AS count
                            FROM official_site_crawl_page AS page
                            LEFT JOIN LATERAL (
                                SELECT candidate.provider_key
                                FROM official_site_fetch_attempt AS candidate
                                WHERE candidate.workspace_id = page.workspace_id
                                  AND candidate.crawl_run_id = page.crawl_run_id
                                  AND candidate.page_id = page.id
                                ORDER BY candidate.attempt_number DESC
                                LIMIT 1
                            ) AS attempt ON true
                            WHERE page.workspace_id = :workspace_id
                              AND page.crawl_run_id = :crawl_run_id
                              AND page.state = 'provider_started'
                            GROUP BY page.host, attempt.provider_key
                            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            provider_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT provider_key, COALESCE(retry_class, 'active') AS outcome,
                                   count(*)::int AS count,
                                   COALESCE(avg(GREATEST(0, extract(epoch FROM (
                                     provider_completed_at - dispatched_at
                                   )))) FILTER (
                                     WHERE provider_completed_at IS NOT NULL
                                       AND dispatched_at IS NOT NULL
                                   ), 0)::float8 AS average_latency_seconds
                            FROM official_site_fetch_attempt
                            WHERE workspace_id = :workspace_id
                              AND crawl_run_id = :crawl_run_id
                            GROUP BY provider_key, COALESCE(retry_class, 'active')
                            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            category_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            WITH latest_fast AS (
                                SELECT snapshot_ids_json
                                FROM official_site_corpus_checkpoint
                                WHERE workspace_id = :workspace_id
                                  AND crawl_run_id = :crawl_run_id
                                  AND phase = 'fast'
                                ORDER BY version DESC
                                LIMIT 1
                            )
                            SELECT reason.value AS reason, count(DISTINCT page.id)::int AS count
                            FROM latest_fast AS checkpoint
                            CROSS JOIN LATERAL jsonb_array_elements_text(
                                checkpoint.snapshot_ids_json
                            ) AS snapshot_id(value)
                            JOIN official_site_page_snapshot AS snapshot
                              ON snapshot.id = snapshot_id.value::uuid
                             AND snapshot.workspace_id = :workspace_id
                             AND snapshot.crawl_run_id = :crawl_run_id
                            JOIN official_site_crawl_page AS page
                              ON page.id = snapshot.page_id
                             AND page.workspace_id = snapshot.workspace_id
                             AND page.crawl_run_id = snapshot.crawl_run_id
                            CROSS JOIN LATERAL jsonb_array_elements_text(
                                page.priority_reason_json
                            ) AS reason(value)
                            WHERE reason.value IN (
                                'category:homepage', 'category:product', 'category:pricing',
                                'category:customer_proof', 'category:company',
                                'category:partner', 'category:trust', 'category:blog',
                                'category:remaining'
                            )
                            GROUP BY reason.value
                            """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
        target = get_metric_sink()
        base = {
            "phase": phase.value if phase is not None else "none",
            "status": run_status.value,
        }
        provider_totals: Counter[str] = Counter()
        for row in active_rows:
            provider = str(row["provider"])
            count = int(row["count"])
            provider_totals[provider] += count
            host_hash = hashlib.sha256(str(row["host"]).encode("utf-8")).hexdigest()[:16]
            target.gauge(
                METRIC_PROVIDER_CONCURRENCY,
                count,
                {**base, "scope": "host", "key": host_hash, "provider": provider},
            )
        for provider, count in provider_totals.items():
            target.gauge(
                METRIC_PROVIDER_CONCURRENCY,
                count,
                {**base, "scope": "provider", "key": provider, "provider": provider},
            )
        for row in provider_rows:
            provider = str(row["provider_key"])
            outcome = str(row["outcome"])
            target.gauge(
                METRIC_PROVIDER_OUTCOMES,
                int(row["count"]),
                {**base, "provider": provider, "outcome": outcome},
            )
            target.gauge(
                METRIC_PROVIDER_LATENCY_SECONDS,
                float(row["average_latency_seconds"]),
                {**base, "provider": provider, "outcome": outcome},
            )
        for row in category_rows:
            target.gauge(
                METRIC_FAST_CATEGORY_COVERAGE,
                int(row["count"]),
                {**base, "category": str(row["reason"]).removeprefix("category:")},
            )

    async def reclaim_expired_leases(
        self, *, workspace_id: str, crawl_run_id: UUID
    ) -> ReclaimResult:
        result = await self._repository.reclaim_expired_leases(
            workspace_id=workspace_id, crawl_run_id=crawl_run_id
        )
        log.info(
            "stage0_official_site_recovery.reclaimed",
            workspace_id=workspace_id,
            crawl_run_id=str(crawl_run_id),
            requeued_pre_dispatch=result.requeued_pre_dispatch,
            moved_to_reconciliation_pending=result.moved_to_reconciliation_pending,
            released_persistence_pending=result.released_persistence_pending,
        )
        return result

    async def quarantine_spend_unknown(
        self,
        *,
        workspace_id: str,
        crawl_run_id: UUID,
        fetch_attempt_id: UUID,
        expected_lease_generation: int,
    ) -> bool:
        """Explicitly quarantine one unleased ambiguous attempt; never dispatch a provider."""

        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT attempt.page_id
                            FROM official_site_fetch_attempt AS attempt
                            JOIN official_site_crawl_page AS page
                              ON page.id = attempt.page_id
                             AND page.crawl_run_id = attempt.crawl_run_id
                             AND page.workspace_id = attempt.workspace_id
                            WHERE attempt.id = :attempt_id
                              AND attempt.workspace_id = :workspace_id
                              AND attempt.crawl_run_id = :crawl_run_id
                              AND attempt.state = 'spend_unknown'
                              AND attempt.spend_status = 'spend_unknown'
                              AND page.state = 'reconciliation_pending'
                              AND page.lease_owner IS NULL
                              AND page.lease_generation = :lease_generation
                            FOR UPDATE OF attempt, page
                            """
                        ),
                        {
                            "attempt_id": fetch_attempt_id,
                            "workspace_id": workspace_id,
                            "crawl_run_id": crawl_run_id,
                            "lease_generation": expected_lease_generation,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return False
            updated_attempt = await conn.execute(
                text(
                    """
                    UPDATE official_site_fetch_attempt
                    SET state = 'quarantined', finished_at = COALESCE(finished_at, now())
                    WHERE id = :attempt_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id AND state = 'spend_unknown'
                    """
                ),
                {
                    "attempt_id": fetch_attempt_id,
                    "workspace_id": workspace_id,
                    "crawl_run_id": crawl_run_id,
                },
            )
            updated_page = await conn.execute(
                text(
                    """
                    UPDATE official_site_crawl_page
                    SET state = 'quarantined', terminal_reason = 'operator_spend_unknown',
                        updated_at = now()
                    WHERE id = :page_id AND workspace_id = :workspace_id
                      AND crawl_run_id = :crawl_run_id
                      AND state = 'reconciliation_pending' AND lease_owner IS NULL
                      AND lease_generation = :lease_generation
                    """
                ),
                {
                    "page_id": row["page_id"],
                    "workspace_id": workspace_id,
                    "crawl_run_id": crawl_run_id,
                    "lease_generation": expected_lease_generation,
                },
            )
            changed = updated_attempt.rowcount == 1 and updated_page.rowcount == 1
            if not changed:
                raise RuntimeError("spend-unknown quarantine lost its fenced state")
        log.warning(
            "stage0_official_site_recovery.spend_unknown_quarantined",
            workspace_id=workspace_id,
            crawl_run_id=str(crawl_run_id),
            fetch_attempt_id=str(fetch_attempt_id),
            lease_generation=expected_lease_generation,
            outcome="quarantined_no_provider_retry",
        )
        return True

    async def _read_progress(
        self, conn: AsyncConnection, run: dict[str, object]
    ) -> OfficialSiteProgressView:
        execute = conn.execute
        params = {"workspace_id": run["workspace_id"], "crawl_run_id": run["id"]}
        page_rows = (
            (
                await execute(
                    text(
                        "SELECT state, count(*)::int AS count FROM official_site_crawl_page "
                        "WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id "
                        "GROUP BY state"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        pages = Counter({row["state"]: row["count"] for row in page_rows})
        page_timing = (
            (
                await execute(
                    text(
                        """
                        SELECT COALESCE(avg(GREATEST(0, extract(epoch FROM (
                                 COALESCE(page.lease_acquired_at, attempt.first_started_at)
                                   - page.discovered_at
                               )))) FILTER (
                                 WHERE COALESCE(
                                   page.lease_acquired_at, attempt.first_started_at
                                 ) IS NOT NULL
                               ), 0)::float8
                                 AS average_claim_latency_seconds,
                               count(*) FILTER (
                                 WHERE page.lease_generation > 1 OR page.attempt_count > 1
                               )::int AS lease_contention_pages
                        FROM official_site_crawl_page AS page
                        LEFT JOIN LATERAL (
                            SELECT min(candidate.started_at) AS first_started_at
                            FROM official_site_fetch_attempt AS candidate
                            WHERE candidate.workspace_id = page.workspace_id
                              AND candidate.crawl_run_id = page.crawl_run_id
                              AND candidate.page_id = page.id
                        ) AS attempt ON true
                        WHERE page.workspace_id = :workspace_id
                          AND page.crawl_run_id = :crawl_run_id
                        """
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
        attempt = (
            (
                await execute(
                    text(
                        """
                        SELECT count(*) FILTER (
                                 WHERE state = 'spend_unknown'
                                   AND spend_status = 'spend_unknown'
                               )::int
                                 AS spend_unknown,
                               COALESCE(sum(cost_cents), 0)::float8 AS cost_cents,
                               COALESCE(avg(GREATEST(0, extract(epoch FROM (
                                 provider_completed_at - dispatched_at
                               )))) FILTER (
                                 WHERE provider_completed_at IS NOT NULL
                                   AND dispatched_at IS NOT NULL
                               ), 0)::float8 AS average_provider_latency_seconds,
                               COALESCE(max(GREATEST(0, extract(epoch FROM (
                                 now() - dispatched_at
                               )))) FILTER (
                                 WHERE state = 'spend_unknown'
                                   AND spend_status = 'spend_unknown'
                                   AND dispatched_at IS NOT NULL
                               ), 0)::int AS oldest_spend_unknown_age_seconds
                        FROM official_site_fetch_attempt
                        WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                        """
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
        snapshot = (
            (
                await execute(
                    text(
                        """
                        SELECT count(*)::int AS snapshots,
                               count(DISTINCT content_sha256)::int AS unique_blobs
                        FROM official_site_page_snapshot
                        WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                        """
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
        extraction_rows = (
            (
                await execute(
                    text(
                        "SELECT state, count(*)::int AS count "
                        "FROM official_site_extraction_operation "
                        "WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id "
                        "GROUP BY state"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        extractions = Counter({row["state"]: row["count"] for row in extraction_rows})
        extraction_spend_age = int(
            (
                await execute(
                    text(
                        """
                        SELECT COALESCE(max(GREATEST(0, extract(epoch FROM (
                                 now() - COALESCE(completed_at, dispatched_at, created_at)
                               )))) FILTER (WHERE state = 'spend_unknown'), 0)::int
                        FROM official_site_extraction_operation
                        WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                        """
                    ),
                    params,
                )
            ).scalar_one()
        )
        checkpoints = (
            (
                await execute(
                    text(
                        """
                        SELECT count(*)::int AS count,
                               min(created_at) FILTER (WHERE phase = 'fast') AS fast_created_at
                        FROM official_site_corpus_checkpoint
                        WHERE workspace_id = :workspace_id AND crawl_run_id = :crawl_run_id
                        """
                        # The checkpoint table's validation trigger makes every committed row
                        # verified; there is deliberately no separate mutable verified flag.
                    ),
                    params,
                )
            )
            .mappings()
            .one()
        )
        event_rows = (
            (
                await execute(
                    text(
                        """
                        SELECT seq, payload
                        FROM run_event
                        WHERE workspace_id = :workspace_id
                          AND run_id = :recon_run_id
                          AND payload->>'crawl_run_id' = :crawl_run_id_text
                          AND payload->>'kind' LIKE 'stage0.crawl.%'
                        ORDER BY seq DESC LIMIT 1000
                        """
                    ),
                    {
                        **params,
                        "recon_run_id": run["recon_run_id"],
                        "crawl_run_id_text": str(run["id"]),
                    },
                )
            )
            .mappings()
            .all()
        )
        envelopes: list[CrawlProgressEnvelope] = []
        for row in event_rows:
            try:
                envelopes.append(
                    CrawlProgressEnvelope(
                        seq=row["seq"], event=CrawlProgressEvent.model_validate(row["payload"])
                    )
                )
            except (TypeError, ValueError):
                # A malformed/foreign event never invalidates row-derived setup truth.
                continue
        reduced = reduce_crawl_events(tuple(envelopes))
        return _build_progress(
            run=run,
            pages=pages,
            fetch_spend_unknown=int(attempt["spend_unknown"]),
            provider_cost_cents=float(attempt["cost_cents"]),
            snapshots=int(snapshot["snapshots"]),
            unique_blobs=int(snapshot["unique_blobs"]),
            extractions=extractions,
            checkpoint_count=int(checkpoints["count"]),
            events=reduced,
            average_claim_latency_seconds=float(page_timing["average_claim_latency_seconds"]),
            lease_contention_pages=int(page_timing["lease_contention_pages"]),
            average_provider_latency_seconds=float(attempt["average_provider_latency_seconds"]),
            oldest_spend_unknown_age_seconds=max(
                int(attempt["oldest_spend_unknown_age_seconds"]), extraction_spend_age
            ),
            fast_checkpoint_created_at=checkpoints["fast_created_at"],
        )


def _build_progress(
    *,
    run: dict[str, object],
    pages: Counter[str],
    fetch_spend_unknown: int,
    provider_cost_cents: float,
    snapshots: int,
    unique_blobs: int,
    extractions: Counter[str],
    checkpoint_count: int,
    events: ReducedCrawlEvents,
    average_claim_latency_seconds: float = 0,
    lease_contention_pages: int = 0,
    average_provider_latency_seconds: float = 0,
    oldest_spend_unknown_age_seconds: int = 0,
    fast_checkpoint_created_at: UtcDatetime | None = None,
) -> OfficialSiteProgressView:
    run_status = CrawlRunStatus(str(run["status"]))
    queued = pages["discovered"] + pages["queued"]
    leased = pages["leased"]
    provider_active = pages["provider_started"]
    reconciliation = pages["reconciliation_pending"]
    persistence = pages["persistence_pending"]
    retry_wait = pages["retry_wait"]
    fetched = pages["fetched"]
    refused = pages["refused"]
    failed = pages["failed"]
    quarantined = pages["quarantined"]
    total_pages = sum(pages.values())
    extraction_active = extractions["dispatched"] + extractions["response_retained"]
    extraction_spend_unknown = extractions["spend_unknown"]
    recovery_required = bool(
        fetch_spend_unknown or extraction_spend_unknown or reconciliation or persistence
    )
    has_success = bool(snapshots or extractions["materialized"] or extractions["empty"])
    has_gap = bool(
        failed
        or quarantined
        or refused
        or fetch_spend_unknown
        or extractions["failed"]
        or extraction_spend_unknown
    )
    partial = has_success and has_gap
    completed = run_status is CrawlRunStatus.COMPLETED
    created_at = cast(datetime, run["created_at"])
    completed_at = cast(datetime | None, run["completed_at"])
    fast_checkpoint_latency_seconds = (
        max(0.0, (fast_checkpoint_created_at - created_at).total_seconds())
        if fast_checkpoint_created_at is not None
        else None
    )
    background_completion_latency_seconds = (
        max(0.0, (completed_at - created_at).total_seconds()) if completed_at is not None else None
    )
    states: list[OperatorState] = []
    if queued or retry_wait:
        states.append(OperatorState.QUEUED)
    if leased:
        states.append(OperatorState.LEASED)
    if provider_active:
        states.append(OperatorState.PROVIDER_ACTIVE)
    if fetch_spend_unknown or extraction_spend_unknown:
        states.append(OperatorState.SPEND_UNKNOWN)
    if snapshots:
        states.append(OperatorState.PERSISTED)
    if sum(extractions.values()):
        states.append(OperatorState.EXTRACTED)
    if partial:
        states.append(OperatorState.PARTIAL)
    if completed:
        states.append(OperatorState.COMPLETED)

    if run_status in {CrawlRunStatus.FAST_ACTIVE, CrawlRunStatus.FAST_CLOSING}:
        phase: CrawlPhase | None = CrawlPhase.FAST
    elif run_status in {
        CrawlRunStatus.FAST_COMPLETE,
        CrawlRunStatus.BACKGROUND_ACTIVE,
        CrawlRunStatus.COMPLETED,
    }:
        phase = CrawlPhase.BACKGROUND
    else:
        phase = events.last_phase

    if recovery_required:
        message = "Research needs operator recovery before it can continue."
    elif extraction_active or extractions["prepared"]:
        message = "Validating sourced company facts."
    elif provider_active or leased:
        message = f"Scraping selected company pages ({fetched}/{total_pages})."
    elif queued or retry_wait:
        message = "Discovering company pages."
    elif run_status in {CrawlRunStatus.FAST_COMPLETE, CrawlRunStatus.BACKGROUND_ACTIVE}:
        message = "Fast research complete; deeper research is continuing."
    elif completed and partial:
        message = "Company research completed with explicit partial results."
    elif completed:
        message = "Company research complete."
    elif snapshots:
        message = "Understanding products, pricing, and customer proof."
    else:
        message = "Company research is queued."

    return OfficialSiteProgressView(
        workspace_id=str(run["workspace_id"]),
        crawl_run_id=UUID(str(run["id"])),
        recon_run_id=UUID(str(run["recon_run_id"])),
        run_status=run_status,
        phase=phase,
        message=message,
        states=tuple(states),
        queued=queued,
        leased=leased,
        provider_active=provider_active,
        reconciliation_pending=reconciliation,
        persistence_pending=persistence,
        retry_wait=retry_wait,
        fetched=fetched,
        refused=refused,
        failed=failed,
        quarantined=quarantined,
        total_pages=total_pages,
        snapshots=snapshots,
        unique_blobs=unique_blobs,
        fetch_spend_unknown=fetch_spend_unknown,
        extraction_prepared=extractions["prepared"],
        extraction_active=extraction_active,
        extraction_materialized=extractions["materialized"],
        extraction_empty=extractions["empty"],
        extraction_failed=extractions["failed"],
        extraction_spend_unknown=extraction_spend_unknown,
        checkpoint_count=checkpoint_count,
        provider_cost_cents=provider_cost_cents,
        recovery_required=recovery_required,
        partial=partial,
        completed=completed,
        event_count=events.event_count,
        last_event_seq=events.last_seq,
        last_event_kind=events.last_kind,
        created_at=created_at,
        completed_at=completed_at,
        average_claim_latency_seconds=average_claim_latency_seconds,
        lease_contention_pages=lease_contention_pages,
        average_provider_latency_seconds=average_provider_latency_seconds,
        oldest_spend_unknown_age_seconds=oldest_spend_unknown_age_seconds,
        fast_checkpoint_latency_seconds=fast_checkpoint_latency_seconds,
        background_completion_latency_seconds=background_completion_latency_seconds,
    )


__all__ = [
    "CrawlProgressEnvelope",
    "CrawlProgressEvent",
    "CrawlProgressEventKind",
    "OfficialSiteOperatorReport",
    "OfficialSiteProgressView",
    "OfficialSiteRecoveryItem",
    "OperatorState",
    "PostgresOfficialSiteOperations",
    "PROGRESS_SCHEMA_VERSION",
    "RecoveryKind",
    "ReducedCrawlEvents",
    "privacy_safe_log_label",
    "privacy_safe_provider_status",
    "progress_event_id",
    "record_crawl_event_metric",
    "record_official_site_metrics",
    "record_stale_completion_rejection",
    "reduce_crawl_events",
]
