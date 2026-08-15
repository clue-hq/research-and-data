"""C8 composition-root bridge from official-site progress events to ``run_event``."""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from clue_core import ProjectRunId, ReconRunId
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_research.durable import RunEventTopic, emit_run_event
from clue_research.official_site import (
    CrawlProgressEvent,
    CrawlProgressEventKind,
    record_crawl_event_metric,
)
from clue_research.stage0 import ReconLaneStatus, transition_recon_lane

log = get_logger("clue_api.official_site_progress")


class DbOfficialSiteProgressEmitter:
    """Append body-free events and project background activation into durable recon truth.

    The crawl run remains authoritative for phase activation. Its idempotent
    ``BACKGROUND_STARTED`` event is the first composition-root boundary that also owns the
    user-facing recon row, so that event advances the recon background lane in the same
    transaction as its durable progress record. Completion remains owned by the authoritative
    Client-KB committer after extraction and materialization succeed.
    """

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def emit(self, event: CrawlProgressEvent) -> None:
        payload = cast(dict[str, JsonValue], event.model_dump(mode="json"))
        async with self._conn_factory() as conn:
            if event.kind is CrawlProgressEventKind.BACKGROUND_STARTED:
                await transition_recon_lane(
                    conn,
                    recon_run_id=ReconRunId(event.recon_run_id),
                    workspace_id=event.workspace_id,
                    lane="background",
                    status=ReconLaneStatus.RUNNING,
                )
            row = await emit_run_event(
                conn,
                workspace_id=event.workspace_id,
                run_id=ProjectRunId(event.recon_run_id),
                topic=RunEventTopic.STEP_PROGRESS.value,
                payload=payload,
            )
        record_crawl_event_metric(event)
        log.info(
            "stage0_official_site_progress.emitted",
            workspace_id=event.workspace_id,
            recon_run_id=str(event.recon_run_id),
            crawl_run_id=str(event.crawl_run_id),
            event_id=event.event_id,
            event_seq=row.seq,
            kind=event.kind.value,
            phase=event.phase.value if event.phase is not None else None,
            page_id=str(event.page_id) if event.page_id is not None else None,
            snapshot_id=str(event.snapshot_id) if event.snapshot_id is not None else None,
            checkpoint_id=str(event.checkpoint_id) if event.checkpoint_id is not None else None,
            lease_generation=event.lease_generation,
            url_hash=event.url_hash,
            host=event.host,
            provider_key=event.provider_key,
            provider_request_id=event.provider_request_id,
            provider_status=event.provider_status,
            http_status=event.http_status,
            duration_ms=event.duration_ms,
            size_bytes=event.size_bytes,
            cost_cents=float(event.cost_cents) if event.cost_cents is not None else None,
            spend_status=event.spend_status,
            retry_class=event.retry_class,
            artifact_key=event.artifact_key,
            outcome=event.outcome,
        )


__all__ = ["DbOfficialSiteProgressEmitter"]
