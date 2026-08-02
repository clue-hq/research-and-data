"""Durable D3 lifecycle for an already-submitted Exa Webset.

Webhooks only enqueue work.  The poller remains authoritative: it persists every page before
processing it, resumes from those receipts after a crash, performs a final idle poll, reconciles
the response against the immutable paid request, and settles cost once.  D4 alone may normalize
items into account candidates or claims.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, JsonValue, SecretStr, ValidationError

from clue_api.exa_websets_submit import (
    DEFAULT_EXA_WEBSETS_PRICING,
    ExaSubmitContractError,
    ExaWebsetsPricingPolicy,
    assert_exa_response_matches_request,
)
from clue_core import (
    FIRST_PAGE_CURSOR,
    DiscoveryBatchState,
    DiscoveryEnrichmentFormat,
    DiscoveryEnrichmentPlan,
    DiscoveryEntityKind,
    DiscoveryEventDisposition,
    DiscoveryItemSnapshot,
    DiscoveryNormalizationState,
    DiscoveryOperation,
    DiscoveryOperationId,
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPageResource,
    DiscoveryProviderEvent,
    DiscoverySearchPlan,
    DiscoverySpendOutcome,
    DiscoveryWakeReason,
    DiscoveryWakeRequest,
    new_discovery_item_snapshot_id,
)
from clue_db import ConnFactory, transaction
from clue_obs.otel import apply_attributes, traced_step
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_API_BASE,
    EXA_WEBSETS_SOURCE_KEY,
    ExaCreateWebsetRequest,
    ExaEventPage,
    ExaItemPage,
    ExaWebhookVerificationError,
    ExaWebset,
    ExaWebsetEvent,
    ExaWebsetItem,
    ExaWebsetsContractDrift,
    ExaWebsetsError,
    ExaWebsetsLifecycleTransport,
    ExaWebsetsPreDispatchError,
    ExaWebsetsRateLimited,
    ExaWebsetsTransientError,
    verify_exa_webhook_signature,
)
from clue_research.durable import (
    DiscoveryNotFound,
    DiscoveryPageRow,
    DiscoveryReplayConflict,
    capture_discovery_artifact,
    claim_discovery_operation_reconciliation,
    claim_due_discovery_wakes,
    complete_discovery_wake,
    finish_discovery_event,
    get_discovery_batch,
    get_discovery_operation,
    get_discovery_page_row,
    link_discovery_page_item,
    list_discovery_events,
    list_discovery_items,
    list_discovery_pages,
    mark_discovery_operation_reconciled,
    put_discovery_item,
    put_discovery_page,
    reconcile_discovery_batch_costs,
    record_discovery_event,
    schedule_discovery_wake,
    update_discovery_batch_state,
    update_discovery_operation,
)
from clue_storage import StorageBackend

CrashHook = Callable[[DiscoveryPageReceipt], Awaitable[None]]


class ExaLifecycleOutcome(StrEnum):
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED_RETRYABLE = "failed_retryable"
    REPLAYED = "replayed"
    JOINED_IN_FLIGHT = "joined_in_flight"


class ExaLifecycleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ExaLifecycleOutcome
    operation: DiscoveryOperation
    poll_calls: int = 0
    item_page_calls: int = 0
    event_page_calls: int = 0
    stored_item_count: int = 0


class ExaWebhookResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_event_id: str
    duplicate: bool
    wake_scheduled: bool


class ExaLifecycleReconciliationError(RuntimeError):
    """Provider terminal state disagrees with the immutable request or persisted pages."""


class ExaWebhookIngestor:
    """Verify and durably enqueue an Exa event; never infer provider completion from it."""

    def __init__(
        self,
        *,
        secret: SecretStr,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        tolerance_seconds: int = 300,
    ) -> None:
        self._secret = secret
        self._storage = storage
        self._conn_factory = conn_factory
        self._tolerance_seconds = tolerance_seconds

    async def ingest(
        self,
        *,
        workspace_id: str,
        operation_id: DiscoveryOperationId,
        raw_body: bytes,
        signature_header: str,
        received_at: datetime | None = None,
    ) -> ExaWebhookResult:
        observed_at = received_at or datetime.now(UTC)
        verify_exa_webhook_signature(
            raw_body=raw_body,
            signature_header=signature_header,
            secret=self._secret,
            now=observed_at,
            tolerance_seconds=self._tolerance_seconds,
        )
        async with self._conn_factory() as conn:
            operation = await get_discovery_operation(
                conn, workspace_id=workspace_id, operation_id=operation_id
            )
            if operation is None:
                raise DiscoveryNotFound(f"discovery operation {operation_id}")
            artifact_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=raw_body,
                media_type=_json_or_binary(raw_body),
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=(
                    f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_operation_id}/events"
                ),
            )
        try:
            provider_event = ExaWebsetEvent.model_validate_json(raw_body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa webhook payload does not match the pinned event contract",
                response_body=raw_body,
            ) from exc

        async with self._conn_factory() as conn:
            operation = await get_discovery_operation(
                conn, workspace_id=workspace_id, operation_id=operation_id
            )
            if operation is None:
                raise DiscoveryNotFound(f"discovery operation {operation_id}")
            if provider_event.webset_id != operation.provider_operation_id:
                raise ExaLifecycleReconciliationError(
                    "webhook event does not target the durable provider operation"
                )
            _, created = await record_discovery_event(
                conn,
                workspace_id=workspace_id,
                event=DiscoveryProviderEvent(
                    operation_id=operation_id,
                    provider_event_id=provider_event.id,
                    event_type=provider_event.type,
                    signature_verified=True,
                    payload_artifact_key=artifact_key,
                    provider_created_at=provider_event.created_at,
                    received_at=observed_at,
                ),
            )
            if created:
                batch = await get_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=operation.batch_id
                )
                if batch is None:
                    raise DiscoveryNotFound(f"discovery batch {operation.batch_id}")
                await schedule_discovery_wake(
                    conn,
                    workspace_id=workspace_id,
                    request=DiscoveryWakeRequest(
                        workspace_id=workspace_id,
                        project_run_id=batch.project_run_id,
                        discovery_batch_id=batch.id,
                        operation_id=operation_id,
                        reason=DiscoveryWakeReason.PROVIDER_EVENT,
                        available_at=observed_at,
                        dedupe_key=f"exa-event:{operation_id}:{provider_event.id}",
                    ),
                )
                await finish_discovery_event(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation_id,
                    provider_event_id=provider_event.id,
                    disposition=DiscoveryEventDisposition.PROCESSED,
                )
        return ExaWebhookResult(
            provider_event_id=provider_event.id,
            duplicate=not created,
            wake_scheduled=created,
        )


def build_exa_webhook_router(ingestor: ExaWebhookIngestor) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/v1/webhooks/exa-websets/{workspace_id}/{operation_id}",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def receive_exa_event(
        workspace_id: str,
        operation_id: DiscoveryOperationId,
        request: Request,
        exa_signature: Annotated[str | None, Header(alias="Exa-Signature")] = None,
    ) -> dict[str, JsonValue]:
        if exa_signature is None:
            raise HTTPException(status_code=400, detail="missing Exa-Signature header")
        raw_body = await request.body()
        try:
            result = await ingestor.ingest(
                workspace_id=workspace_id,
                operation_id=operation_id,
                raw_body=raw_body,
                signature_header=exa_signature,
            )
        except (
            ExaWebhookVerificationError,
            ExaWebsetsContractDrift,
            ExaLifecycleReconciliationError,
        ) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DiscoveryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    return router


class DurableExaWebsetLifecycle:
    """Poll, ingest, reconcile, settle, and safely replay one submitted Webset."""

    def __init__(
        self,
        *,
        transport: ExaWebsetsLifecycleTransport,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        pricing: ExaWebsetsPricingPolicy = DEFAULT_EXA_WEBSETS_PRICING,
        poll_after_seconds: int = 15,
        maximum_retry_after_seconds: int = 300,
        crash_after_page_persisted: CrashHook | None = None,
    ) -> None:
        if poll_after_seconds < 1 or maximum_retry_after_seconds < 1:
            raise ValueError("Exa lifecycle timing values must be positive")
        self._transport = transport
        self._storage = storage
        self._conn_factory = conn_factory
        self._pricing = pricing
        self._poll_after = timedelta(seconds=poll_after_seconds)
        self._maximum_retry_after = timedelta(seconds=maximum_retry_after_seconds)
        self._crash_hook = crash_after_page_persisted

    async def run_once(
        self,
        *,
        workspace_id: str,
        operation_id: DiscoveryOperationId,
        now: datetime | None = None,
    ) -> ExaLifecycleResult:
        observed_at = now or datetime.now(UTC)
        counters = {"poll": 0, "items": 0, "events": 0}
        async with self._conn_factory() as conn:
            operation = await get_discovery_operation(
                conn, workspace_id=workspace_id, operation_id=operation_id
            )
            if operation is None:
                raise DiscoveryNotFound(f"discovery operation {operation_id}")
            if operation.state is DiscoveryOperationState.SUCCEEDED:
                items = await list_discovery_items(
                    conn, workspace_id=workspace_id, operation_id=operation_id
                )
                return ExaLifecycleResult(
                    outcome=ExaLifecycleOutcome.REPLAYED,
                    operation=operation,
                    stored_item_count=len(items),
                )
            if operation.state is DiscoveryOperationState.CANCELLED:
                return ExaLifecycleResult(outcome=ExaLifecycleOutcome.REPLAYED, operation=operation)
            claimed = await claim_discovery_operation_reconciliation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
                now=observed_at,
            )
        if claimed is None:
            async with self._conn_factory() as conn:
                current = await get_discovery_operation(
                    conn, workspace_id=workspace_id, operation_id=operation_id
                )
            if current is None:
                raise DiscoveryNotFound(f"discovery operation {operation_id}")
            return ExaLifecycleResult(
                outcome=ExaLifecycleOutcome.JOINED_IN_FLIGHT, operation=current
            )

        with traced_step(
            "discovery.exa_websets.lifecycle",
            provider=EXA_WEBSETS_SOURCE_KEY,
            discovery_operation_id=str(operation_id),
        ) as span:
            try:
                request = await self._load_request(claimed)
                poll = await self._transport.poll_webset(claimed.provider_operation_id or "")
                counters["poll"] += 1
                await self._persist_webset_poll(
                    workspace_id, claimed, poll.response_body, poll.webset
                )
                assert_exa_response_matches_request(request, poll)
                if poll.webset.status.value != "idle":
                    result = await self._schedule_wait(
                        workspace_id=workspace_id,
                        operation=claimed,
                        available_at=observed_at + self._poll_after,
                        reason=DiscoveryWakeReason.SCHEDULED_POLL,
                        outcome=ExaLifecycleOutcome.WAITING,
                    )
                    return result.model_copy(update={"poll_calls": counters["poll"]})
                if any(search.status.value == "canceled" for search in poll.webset.searches):
                    return await self._cancel(
                        workspace_id, claimed, observed_at, poll.response_body
                    )

                await self._persist_terminal_collections(workspace_id, claimed, poll.webset)
                await self._ingest_item_pages(workspace_id, claimed, counters)
                await self._ingest_event_pages(workspace_id, claimed, counters)

                final_poll = await self._transport.poll_webset(claimed.provider_operation_id or "")
                counters["poll"] += 1
                await self._persist_webset_poll(
                    workspace_id, claimed, final_poll.response_body, final_poll.webset
                )
                assert_exa_response_matches_request(request, final_poll)
                if final_poll.webset.status.value != "idle":
                    raise ExaLifecycleReconciliationError(
                        "final authoritative poll no longer reports idle"
                    )
                stored_items = await self._reconcile(
                    workspace_id=workspace_id,
                    operation=claimed,
                    request=request,
                    webset=final_poll.webset,
                )
                result = await self._succeed(
                    workspace_id=workspace_id,
                    operation=claimed,
                    request=request,
                    webset=final_poll.webset,
                    item_count=len(stored_items),
                    observed_at=observed_at,
                )
                apply_attributes(
                    span,
                    {
                        "provider.poll_calls": counters["poll"],
                        "provider.item_page_calls": counters["items"],
                        "provider.event_page_calls": counters["events"],
                        "discovery.item_count": len(stored_items),
                    },
                )
                return result.model_copy(
                    update={
                        "poll_calls": counters["poll"],
                        "item_page_calls": counters["items"],
                        "event_page_calls": counters["events"],
                    }
                )
            except (
                ExaWebsetsPreDispatchError,
                ExaWebsetsRateLimited,
                ExaWebsetsTransientError,
            ) as exc:
                delay = self._poll_after
                if exc.retry_after_seconds is not None:
                    delay = min(
                        timedelta(seconds=exc.retry_after_seconds), self._maximum_retry_after
                    )
                result = await self._schedule_wait(
                    workspace_id=workspace_id,
                    operation=claimed,
                    available_at=observed_at + delay,
                    reason=DiscoveryWakeReason.SCHEDULED_POLL,
                    outcome=ExaLifecycleOutcome.RETRY_SCHEDULED,
                    provider_error=exc,
                )
                return result.model_copy(
                    update={
                        "poll_calls": counters["poll"],
                        "item_page_calls": counters["items"],
                        "event_page_calls": counters["events"],
                    }
                )
            except (
                ExaWebsetsContractDrift,
                ExaWebsetsError,
                ExaLifecycleReconciliationError,
                ExaSubmitContractError,
                DiscoveryReplayConflict,
                ValidationError,
            ) as exc:
                return await self._fail_retryable(
                    workspace_id=workspace_id,
                    operation=claimed,
                    observed_at=observed_at,
                    error=exc,
                    counters=counters,
                )

    async def _load_request(self, operation: DiscoveryOperation) -> ExaCreateWebsetRequest:
        if operation.raw_request_artifact_key is None:
            raise ExaLifecycleReconciliationError("operation has no durable request artifact")
        raw = await self._storage.get(operation.raw_request_artifact_key)
        return ExaCreateWebsetRequest.model_validate_json(raw)

    async def _persist_webset_poll(
        self,
        workspace_id: str,
        operation: DiscoveryOperation,
        raw_body: bytes,
        webset: ExaWebset,
    ) -> None:
        digest = hashlib.sha256(raw_body).hexdigest()
        await self._persist_page(
            workspace_id=workspace_id,
            operation=operation,
            resource=DiscoveryPageResource.WEBSETS,
            request_cursor=f"poll:{webset.status.value}:{digest}",
            raw_body=raw_body,
            has_more=False,
            next_cursor=None,
            item_count=1,
            source_url=f"{EXA_WEBSETS_API_BASE}/websets/{webset.id}",
        )

    async def _persist_terminal_collections(
        self, workspace_id: str, operation: DiscoveryOperation, webset: ExaWebset
    ) -> None:
        for resource, values in (
            (DiscoveryPageResource.SEARCHES, webset.searches),
            (DiscoveryPageResource.ENRICHMENTS, webset.enrichments),
        ):
            raw = json.dumps(
                [value.model_dump(mode="json", by_alias=True) for value in values],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            await self._persist_page(
                workspace_id=workspace_id,
                operation=operation,
                resource=resource,
                request_cursor=FIRST_PAGE_CURSOR,
                raw_body=raw,
                has_more=False,
                next_cursor=None,
                item_count=len(values),
                source_url=f"{EXA_WEBSETS_API_BASE}/websets/{webset.id}",
            )

    async def _ingest_item_pages(
        self,
        workspace_id: str,
        operation: DiscoveryOperation,
        counters: dict[str, int],
    ) -> None:
        cursor: str | None = None
        while True:
            cursor_key = cursor or FIRST_PAGE_CURSOR
            async with self._conn_factory() as conn:
                stored = await get_discovery_page_row(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                    resource_kind=DiscoveryPageResource.ITEMS.value,
                    request_cursor=cursor_key,
                )
            if stored is None:
                exchange = await self._transport.list_items(
                    operation.provider_operation_id or "", cursor=cursor, limit=100
                )
                counters["items"] += 1
                page = exchange.page
                page_row = await self._persist_page(
                    workspace_id=workspace_id,
                    operation=operation,
                    resource=DiscoveryPageResource.ITEMS,
                    request_cursor=cursor_key,
                    raw_body=exchange.response_body,
                    has_more=page.has_more,
                    next_cursor=page.next_cursor,
                    item_count=len(page.data),
                    source_url=(
                        f"{EXA_WEBSETS_API_BASE}/websets/{operation.provider_operation_id}/items"
                    ),
                )
            else:
                page_row = stored
                raw = await self._storage.get(stored.receipt.payload_artifact_key)
                page = ExaItemPage.model_validate_json(raw)
            if self._crash_hook is not None:
                await self._crash_hook(page_row.receipt)
            await self._persist_items(workspace_id, operation, page_row.id, page)
            if not page.has_more:
                return
            cursor = page.next_cursor

    async def _persist_items(
        self,
        workspace_id: str,
        operation: DiscoveryOperation,
        page_id: object,
        page: ExaItemPage,
    ) -> None:
        from uuid import UUID

        if not isinstance(page_id, UUID):
            raise TypeError("page receipt id must be a UUID")
        async with self._conn_factory() as conn:
            for ordinal, provider_item in enumerate(page.data):
                raw = json.dumps(
                    provider_item.model_dump(mode="json", by_alias=True),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                key = await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=workspace_id,
                    content=raw,
                    media_type="application/json",
                    source_key=EXA_WEBSETS_SOURCE_KEY,
                    source_url=(
                        f"{EXA_WEBSETS_API_BASE}/websets/"
                        f"{operation.provider_operation_id}/items/{provider_item.id}"
                    ),
                )
                item = await put_discovery_item(
                    conn,
                    workspace_id=workspace_id,
                    item=DiscoveryItemSnapshot(
                        item_snapshot_id=new_discovery_item_snapshot_id(),
                        operation_id=operation.operation_id,
                        provider_item_id=provider_item.id,
                        source_kind=provider_item.source,
                        source_id=provider_item.source_id,
                        raw_artifact_key=key,
                        item_sha256=hashlib.sha256(raw).hexdigest(),
                        observed_at=provider_item.updated_at,
                        normalization_state=DiscoveryNormalizationState.RAW,
                    ),
                )
                await link_discovery_page_item(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                    page_receipt_id=page_id,
                    item_snapshot_id=item.item_snapshot_id,
                    ordinal=ordinal,
                )

    async def _ingest_event_pages(
        self,
        workspace_id: str,
        operation: DiscoveryOperation,
        counters: dict[str, int],
    ) -> None:
        cursor: str | None = None
        while True:
            cursor_key = cursor or FIRST_PAGE_CURSOR
            async with self._conn_factory() as conn:
                stored = await get_discovery_page_row(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                    resource_kind=DiscoveryPageResource.EVENTS.value,
                    request_cursor=cursor_key,
                )
            if stored is not None:
                raw = await self._storage.get(stored.receipt.payload_artifact_key)
                page = ExaEventPage.model_validate_json(raw)
            else:
                exchange = await self._transport.list_events(cursor=cursor, limit=200)
                counters["events"] += 1
                target_events = tuple(
                    event
                    for event in exchange.page.data
                    if event.webset_id == operation.provider_operation_id
                )
                # The team-level event endpoint may contain other tenants' Websets. Persist only
                # the target operation's events while retaining the upstream page hash.
                filtered = {
                    "data": [
                        event.model_dump(mode="json", by_alias=True) for event in target_events
                    ],
                    "hasMore": exchange.page.has_more,
                    "nextCursor": exchange.page.next_cursor,
                    "upstreamPageSha256": hashlib.sha256(exchange.response_body).hexdigest(),
                }
                raw = json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode()
                page = ExaEventPage.model_validate(filtered)
                await self._persist_page(
                    workspace_id=workspace_id,
                    operation=operation,
                    resource=DiscoveryPageResource.EVENTS,
                    request_cursor=cursor_key,
                    raw_body=raw,
                    has_more=page.has_more,
                    next_cursor=page.next_cursor,
                    item_count=len(page.data),
                    source_url=f"{EXA_WEBSETS_API_BASE}/events",
                )
            if not page.has_more:
                return
            cursor = page.next_cursor

    async def _persist_page(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        resource: DiscoveryPageResource,
        request_cursor: str,
        raw_body: bytes,
        has_more: bool,
        next_cursor: str | None,
        item_count: int,
        source_url: str,
    ) -> DiscoveryPageRow:
        async with self._conn_factory() as conn:
            artifact_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=raw_body,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=source_url,
            )
            receipt = DiscoveryPageReceipt(
                operation_id=operation.operation_id,
                resource_kind=resource,
                request_cursor=request_cursor,
                next_cursor=next_cursor,
                has_more=has_more,
                payload_artifact_key=artifact_key,
                payload_sha256=hashlib.sha256(raw_body).hexdigest(),
                item_count=item_count,
                fetched_at=datetime.now(UTC),
            )
            await put_discovery_page(conn, workspace_id=workspace_id, page=receipt)
            row = await get_discovery_page_row(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                resource_kind=resource.value,
                request_cursor=request_cursor,
            )
            if row is None:
                raise DiscoveryNotFound(f"discovery page {operation.operation_id}:{request_cursor}")
            return DiscoveryPageRow(id=row.id, receipt=row.receipt)

    async def _reconcile(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        request: ExaCreateWebsetRequest,
        webset: ExaWebset,
    ) -> tuple[DiscoveryItemSnapshot, ...]:
        if webset.id != operation.provider_operation_id:
            raise ExaLifecycleReconciliationError("provider Webset id changed")
        if len(webset.searches) != 1 or webset.searches[0].status.value != "completed":
            raise ExaLifecycleReconciliationError("terminal Webset search is not completed")
        if any(enrichment.status != "completed" for enrichment in webset.enrichments):
            raise ExaLifecycleReconciliationError("terminal Webset enrichment is not completed")
        async with self._conn_factory() as conn:
            items = await list_discovery_items(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            events = await list_discovery_events(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            pages = await list_discovery_pages(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
        if len({item.provider_item_id for item in items}) != len(items):
            raise ExaLifecycleReconciliationError("multiple current snapshots exist for one item")
        if len(items) > request.search.count:
            raise ExaLifecycleReconciliationError("provider returned more items than requested")
        progress = (webset.searches[0].model_extra or {}).get("progress")
        if isinstance(progress, dict):
            found = progress.get("found")
            if isinstance(found, int) and found != len(items):
                raise ExaLifecycleReconciliationError(
                    "terminal search found count disagrees with item pagination"
                )
        provider_enrichment_ids = {enrichment.id for enrichment in webset.enrichments}
        item_ids = {item.provider_item_id for item in items}
        for item in items:
            provider_item = ExaWebsetItem.model_validate_json(
                await self._storage.get(item.raw_artifact_key)
            )
            for result in provider_item.enrichments:
                enrichment_id = result.get("enrichmentId")
                if enrichment_id not in provider_enrichment_ids:
                    raise ExaLifecycleReconciliationError(
                        "item references an unknown Webset enrichment"
                    )
        for event in events:
            raw_event = ExaWebsetEvent.model_validate_json(
                await self._storage.get(event.payload_artifact_key)
            )
            if event.event_type.startswith("webset.item."):
                event_item_id = raw_event.data.get("id")
                if event_item_id not in item_ids:
                    raise ExaLifecycleReconciliationError(
                        "webhook event references an item absent from pagination"
                    )
        for page in pages:
            if page.receipt.resource_kind is not DiscoveryPageResource.EVENTS:
                continue
            event_page = ExaEventPage.model_validate_json(
                await self._storage.get(page.receipt.payload_artifact_key)
            )
            for paged_event in event_page.data:
                if (
                    paged_event.type.startswith("webset.item.")
                    and paged_event.data.get("id") not in item_ids
                ):
                    raise ExaLifecycleReconciliationError(
                        "event pagination references an item absent from item pagination"
                    )
        return items

    async def _succeed(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        request: ExaCreateWebsetRequest,
        webset: ExaWebset,
        item_count: int,
        observed_at: datetime,
    ) -> ExaLifecycleResult:
        per_row = self._pricing.maximum_units(
            # The ratio is stable because maximum_units is linear in requested count.
            # Avoid a second pricing implementation while settling only returned rows.
            _search_plan_for_pricing(request)
        )
        realized_units = (
            per_row / Decimal(request.search.count) * Decimal(item_count)
            if request.search.count
            else Decimal(0)
        )
        if realized_units > operation.provider_units_reserved:
            raise ExaLifecycleReconciliationError("realized units exceed reserved units")
        async with self._conn_factory() as conn:
            pages = await list_discovery_pages(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            items = await list_discovery_items(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            manifest_raw = json.dumps(
                {
                    "contract": "exa-websets-d3-raw-manifest-v1",
                    "operationId": str(operation.operation_id),
                    "providerOperationId": webset.id,
                    "pageArtifacts": sorted({page.receipt.payload_artifact_key for page in pages}),
                    "itemArtifacts": sorted({item.raw_artifact_key for item in items}),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            manifest_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=manifest_raw,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
            )
            receipt_raw = json.dumps(
                {
                    "contract": "exa-websets-d3-final-receipt-v1",
                    "providerOperationId": webset.id,
                    "providerStatus": webset.status.value,
                    "itemCount": item_count,
                    "providerUnitsCharged": str(realized_units),
                    "settlementMethod": "public-credit-formula-times-durable-item-count",
                    "pricingPolicyVersion": self._pricing.version,
                    "reconciledAt": observed_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            receipt_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=receipt_raw,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
            )
            succeeded = operation.model_copy(
                update={
                    "state": DiscoveryOperationState.SUCCEEDED,
                    "spend_outcome": DiscoverySpendOutcome.CHARGED,
                    "next_poll_at": None,
                    "final_receipt_ref": receipt_key,
                    "raw_response_manifest_key": manifest_key,
                    "provider_units_charged": realized_units,
                    "terminal_at": observed_at,
                }
            )
            succeeded = await update_discovery_operation(
                conn, workspace_id=workspace_id, operation=succeeded
            )
            await mark_discovery_operation_reconciled(
                conn,
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
            )
            await reconcile_discovery_batch_costs(
                conn, workspace_id=workspace_id, batch_id=operation.batch_id
            )
            await update_discovery_batch_state(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
                state=DiscoveryBatchState.IDENTITY_RESOLUTION,
            )
        return ExaLifecycleResult(
            outcome=ExaLifecycleOutcome.SUCCEEDED,
            operation=succeeded,
            stored_item_count=item_count,
        )

    async def _schedule_wait(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        available_at: datetime,
        reason: DiscoveryWakeReason,
        outcome: ExaLifecycleOutcome,
        provider_error: ExaWebsetsError | None = None,
    ) -> ExaLifecycleResult:
        async with self._conn_factory() as conn:
            batch = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=operation.batch_id
            )
            if batch is None:
                raise DiscoveryNotFound(f"discovery batch {operation.batch_id}")
            if provider_error is not None and provider_error.response_body is not None:
                error_key = await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=workspace_id,
                    content=provider_error.response_body,
                    media_type=_json_or_binary(provider_error.response_body),
                    source_key=EXA_WEBSETS_SOURCE_KEY,
                )
            else:
                error_key = None
            waiting = operation.model_copy(
                update={
                    "state": DiscoveryOperationState.WAITING_EXTERNAL,
                    "next_poll_at": available_at,
                    "final_receipt_ref": error_key or operation.final_receipt_ref,
                }
            )
            waiting = await update_discovery_operation(
                conn, workspace_id=workspace_id, operation=waiting
            )
            await update_discovery_batch_state(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
                state=DiscoveryBatchState.WAITING_EXTERNAL,
            )
            await schedule_discovery_wake(
                conn,
                workspace_id=workspace_id,
                request=DiscoveryWakeRequest(
                    workspace_id=workspace_id,
                    project_run_id=batch.project_run_id,
                    discovery_batch_id=batch.id,
                    operation_id=operation.operation_id,
                    reason=reason,
                    available_at=available_at,
                    dedupe_key=(
                        f"exa-poll:{operation.operation_id}:"
                        f"{int(available_at.timestamp() * 1_000_000)}"
                    ),
                ),
            )
        return ExaLifecycleResult(outcome=outcome, operation=waiting)

    async def _fail_retryable(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        observed_at: datetime,
        error: Exception,
        counters: dict[str, int],
    ) -> ExaLifecycleResult:
        async with self._conn_factory() as conn:
            body = error.response_body if isinstance(error, ExaWebsetsError) else None
            if body is not None:
                await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=workspace_id,
                    content=body,
                    media_type=_json_or_binary(body),
                    source_key=EXA_WEBSETS_SOURCE_KEY,
                )
            failure_raw = json.dumps(
                {
                    "contract": "exa-websets-d3-failure-receipt-v1",
                    "errorType": type(error).__name__,
                    "message": str(error),
                    "observedAt": observed_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            failure_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=failure_raw,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
            )
            failed = operation.model_copy(
                update={
                    "state": DiscoveryOperationState.FAILED_RETRYABLE,
                    "next_poll_at": observed_at + self._poll_after,
                    "final_receipt_ref": failure_key,
                }
            )
            failed = await update_discovery_operation(
                conn, workspace_id=workspace_id, operation=failed
            )
            await update_discovery_batch_state(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
                state=DiscoveryBatchState.FAILED_RETRYABLE,
                failure_code="exa_d3_reconciliation_failed",
            )
        return ExaLifecycleResult(
            outcome=ExaLifecycleOutcome.FAILED_RETRYABLE,
            operation=failed,
            poll_calls=counters["poll"],
            item_page_calls=counters["items"],
            event_page_calls=counters["events"],
        )

    async def _cancel(
        self,
        workspace_id: str,
        operation: DiscoveryOperation,
        observed_at: datetime,
        raw_body: bytes,
    ) -> ExaLifecycleResult:
        async with self._conn_factory() as conn:
            receipt = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=raw_body,
                media_type="application/json",
                source_key=EXA_WEBSETS_SOURCE_KEY,
            )
            cancelled = operation.model_copy(
                update={
                    "state": DiscoveryOperationState.CANCELLED,
                    "next_poll_at": None,
                    "final_receipt_ref": receipt,
                    "terminal_at": observed_at,
                }
            )
            cancelled = await update_discovery_operation(
                conn, workspace_id=workspace_id, operation=cancelled
            )
            await update_discovery_batch_state(
                conn,
                workspace_id=workspace_id,
                batch_id=operation.batch_id,
                state=DiscoveryBatchState.CANCELLED_UNSEALED,
                failure_code="exa_webset_cancelled",
            )
        return ExaLifecycleResult(
            outcome=ExaLifecycleOutcome.CANCELLED, operation=cancelled, poll_calls=1
        )


class ExaDiscoveryWakeWorker:
    """Drain only Exa operation wakes; stale claims are reclaimed by the repository lease."""

    def __init__(
        self,
        *,
        lifecycle: DurableExaWebsetLifecycle,
        conn_factory: ConnFactory = transaction,
        claim_stale_after: timedelta = timedelta(minutes=5),
    ) -> None:
        self._lifecycle = lifecycle
        self._conn_factory = conn_factory
        self._claim_stale_after = claim_stale_after

    async def run_due(self, *, limit: int = 25, now: datetime | None = None) -> int:
        async with self._conn_factory() as conn:
            wakes = await claim_due_discovery_wakes(
                conn,
                limit=limit,
                now=now,
                claim_stale_after=self._claim_stale_after,
                source_key=EXA_WEBSETS_SOURCE_KEY,
            )
        completed = 0
        for wake in wakes:
            if wake.operation_id is None:
                continue
            await self._lifecycle.run_once(
                workspace_id=wake.workspace_id,
                operation_id=wake.operation_id,
                now=now,
            )
            async with self._conn_factory() as conn:
                await complete_discovery_wake(conn, workspace_id=wake.workspace_id, wake_id=wake.id)
            completed += 1
        return completed


def _search_plan_for_pricing(request: ExaCreateWebsetRequest) -> DiscoverySearchPlan:
    """Rebuild the provider-neutral subset consumed by the shared linear pricing policy."""

    return DiscoverySearchPlan(
        search_key=request.metadata.get("clueSearchKey", "exa-webset"),
        channel_key=EXA_WEBSETS_SOURCE_KEY,
        normalized_query=request.search.query,
        entity_type=DiscoveryEntityKind(request.search.entity.type.value)
        if request.search.entity is not None
        else DiscoveryEntityKind.COMPANY,
        custom_entity_description=(
            request.search.entity.description
            if request.search.entity is not None and request.search.entity.type.value == "custom"
            else None
        ),
        requested_count=request.search.count,
        enrichments=tuple(
            DiscoveryEnrichmentPlan(
                field_key=item.metadata.get("clueFieldKey", f"exa.unmapped.{index}"),
                description=item.description,
                format=DiscoveryEnrichmentFormat(
                    item.format.value if item.format is not None else "text"
                ),
            )
            for index, item in enumerate(request.enrichments)
        ),
        max_people_per_company=request.search.max_people_per_company,
    )


def _json_or_binary(content: bytes) -> str:
    try:
        json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "application/octet-stream"
    return "application/json"


__all__ = [
    "DurableExaWebsetLifecycle",
    "ExaDiscoveryWakeWorker",
    "ExaLifecycleOutcome",
    "ExaLifecycleReconciliationError",
    "ExaLifecycleResult",
    "ExaWebhookIngestor",
    "ExaWebhookResult",
    "build_exa_webhook_router",
]
