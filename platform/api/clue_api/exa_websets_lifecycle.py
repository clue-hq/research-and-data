"""Durable D3 lifecycle for an already-submitted Exa Webset.

Webhooks only enqueue work.  The poller remains authoritative: it persists every page before
processing it, resumes from those receipts after a crash, performs a final idle poll, reconciles
the response against the immutable paid request, and settles cost once.  D4 alone may normalize
items into account candidates or claims.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, JsonValue, SecretStr, ValidationError

from clue_api.exa_websets_submit import (
    DEFAULT_EXA_WEBSETS_PRICING,
    ExaSubmitContractError,
    ExaWebsetsChargeBreakdown,
    ExaWebsetsPricingPolicy,
    assert_exa_response_matches_request,
)
from clue_core import (
    FIRST_PAGE_CURSOR,
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryEventDisposition,
    DiscoveryItemSnapshot,
    DiscoveryNormalizationState,
    DiscoveryOperation,
    DiscoveryOperationId,
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPageResource,
    DiscoveryProviderEvent,
    DiscoverySpendOutcome,
    DiscoveryWakeReason,
    DiscoveryWakeRequest,
    ProjectRunId,
    new_discovery_item_snapshot_id,
)
from clue_db import ConnFactory, transaction
from clue_obs.otel import apply_attributes, traced_step
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_API_BASE,
    EXA_WEBSETS_SOURCE_KEY,
    ExaCreateEnrichment,
    ExaCreateWebhookRequest,
    ExaCreateWebsetRequest,
    ExaEventPage,
    ExaItemPage,
    ExaWebhook,
    ExaWebhookEventType,
    ExaWebhookVerificationError,
    ExaWebset,
    ExaWebsetEnrichmentFormat,
    ExaWebsetEvent,
    ExaWebsetItem,
    ExaWebsetsContractDrift,
    ExaWebsetsError,
    ExaWebsetsLifecycleTransport,
    ExaWebsetsPreDispatchError,
    ExaWebsetsRateLimited,
    ExaWebsetsTransientError,
    ExaWebsetsWebhookAdminTransport,
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
    find_discovery_operation_by_provider_id,
    finish_discovery_event,
    get_discovery_batch,
    get_discovery_operation,
    get_discovery_page_row,
    get_discovery_plan,
    link_discovery_page_item,
    list_discovery_events,
    list_discovery_items,
    list_discovery_pages,
    mark_discovery_operation_reconciled,
    put_discovery_item,
    put_discovery_page,
    reconcile_discovery_batch_costs,
    reconcile_discovery_batch_state,
    record_discovery_event,
    schedule_discovery_wake,
    update_discovery_batch_state,
    update_discovery_operation,
)
from clue_storage import StorageBackend

CrashHook = Callable[[DiscoveryPageReceipt], Awaitable[None]]


class DiscoveryBatchMaterializer(Protocol):
    async def materialize(self, *, workspace_id: str, batch_id: DiscoveryBatchId) -> object: ...


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
    matched_operation: bool
    workspace_id: str | None = None
    operation_id: DiscoveryOperationId | None = None
    duplicate: bool
    wake_scheduled: bool


EXA_TEAM_WEBHOOK_EVENTS: tuple[ExaWebhookEventType, ...] = (
    ExaWebhookEventType.WEBSET_IDLE,
    ExaWebhookEventType.SEARCH_COMPLETED,
    ExaWebhookEventType.SEARCH_CANCELED,
    ExaWebhookEventType.ITEM_ENRICHED,
)


class ExaWebhookProvisionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    webhook_id: str
    created: bool
    # Present exactly once on creation; the deployment must put it in its secret manager.
    secret: SecretStr | None = None


class ExaTeamWebhookProvisioner:
    """Idempotently provision the one team-level endpoint used by this deployment.

    It deliberately refuses to update/delete a mismatching managed endpoint.  Secret rotation and
    URL changes are operator-visible external changes, not safe startup side effects.
    """

    def __init__(self, *, transport: ExaWebsetsWebhookAdminTransport) -> None:
        self._transport = transport

    async def ensure(self, *, url: str) -> ExaWebhookProvisionResult:
        cursor: str | None = None
        managed: list[ExaWebhook] = []
        while True:
            page = await self._transport.list_webhooks(cursor=cursor, limit=200)
            managed.extend(
                item for item in page.data if item.metadata.get("clueEndpoint") == "team-websets-v1"
            )
            if not page.has_more:
                break
            cursor = page.next_cursor
        if len(managed) > 1:
            raise ExaLifecycleReconciliationError(
                "multiple Exa webhooks claim the Clue team endpoint identity"
            )
        if managed:
            existing = managed[0]
            if (
                existing.url != url
                or existing.status != "active"
                or set(existing.events) != set(EXA_TEAM_WEBHOOK_EVENTS)
            ):
                raise ExaLifecycleReconciliationError(
                    "managed Exa team webhook differs from the deployment contract"
                )
            return ExaWebhookProvisionResult(webhook_id=existing.id, created=False)
        created = await self._transport.create_webhook(
            ExaCreateWebhookRequest(
                url=url,
                events=EXA_TEAM_WEBHOOK_EVENTS,
                metadata={"clueEndpoint": "team-websets-v1"},
            )
        )
        if created.secret is None:
            raise ExaLifecycleReconciliationError(
                "new Exa webhook did not return its one-time signing secret"
            )
        return ExaWebhookProvisionResult(
            webhook_id=created.id,
            created=True,
            secret=created.secret,
        )


class ExaLifecycleReconciliationError(RuntimeError):
    """Provider terminal state disagrees with the immutable request or persisted pages."""


_EMAIL_RESULT = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RESULT = re.compile(r"^\+?[0-9][0-9 ().-]{6,}[0-9]$")


def _validate_enrichment_result(
    requested: ExaCreateEnrichment,
    values: tuple[str, ...] | None,
) -> None:
    """Validate the documented string-array result under the requested logical format."""

    if requested.format is None or not values:
        return
    if (
        requested.format
        in {
            ExaWebsetEnrichmentFormat.EMAIL,
            ExaWebsetEnrichmentFormat.PHONE,
        }
        and len(values) > 1
    ):
        # Discovery asks for one general company contact value.  This also keeps the maximum paid
        # reservation sound because Exa bills contact formats per returned value.
        raise ExaLifecycleReconciliationError(
            "contact enrichment returned more values than the paid request permits"
        )
    if requested.format is ExaWebsetEnrichmentFormat.EMAIL:
        if any(_EMAIL_RESULT.fullmatch(value) is None for value in values):
            raise ExaLifecycleReconciliationError("email enrichment returned an invalid value")
    elif requested.format is ExaWebsetEnrichmentFormat.PHONE:
        if any(_PHONE_RESULT.fullmatch(value) is None for value in values):
            raise ExaLifecycleReconciliationError("phone enrichment returned an invalid value")
    elif requested.format is ExaWebsetEnrichmentFormat.URL:
        if any(
            urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).netloc
            for value in values
        ):
            raise ExaLifecycleReconciliationError("URL enrichment returned an invalid value")
    elif requested.format is ExaWebsetEnrichmentFormat.NUMBER:
        try:
            for value in values:
                if not Decimal(value).is_finite():
                    raise ArithmeticError
        except ArithmeticError as exc:
            raise ExaLifecycleReconciliationError(
                "number enrichment returned a non-decimal value"
            ) from exc
    elif requested.format is ExaWebsetEnrichmentFormat.DATE:
        try:
            for value in values:
                date.fromisoformat(value)
        except ValueError as exc:
            raise ExaLifecycleReconciliationError(
                "date enrichment returned a non-ISO date"
            ) from exc
    elif requested.format is ExaWebsetEnrichmentFormat.OPTIONS:
        labels = {option.label for option in requested.options}
        if any(value not in labels for value in values):
            raise ExaLifecycleReconciliationError(
                "options enrichment returned a value outside the requested vocabulary"
            )


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
        try:
            provider_event = ExaWebsetEvent.model_validate_json(raw_body)
        except (ValueError, TypeError) as exc:
            raise ExaWebsetsContractDrift(
                "Exa webhook payload does not match the pinned event contract",
                response_body=raw_body,
            ) from exc

        provider_webset_id = provider_event.webset_id
        if provider_webset_id is None:
            return ExaWebhookResult(
                provider_event_id=provider_event.id,
                matched_operation=False,
                duplicate=False,
                wake_scheduled=False,
            )
        async with self._conn_factory() as conn:
            operation = await find_discovery_operation_by_provider_id(
                conn,
                source_key=EXA_WEBSETS_SOURCE_KEY,
                provider_operation_id=provider_webset_id,
            )
            if operation is None:
                # A team webhook legitimately receives events for dashboard-created or unrelated
                # Websets.  Acknowledge them without creating a tenant artifact.
                return ExaWebhookResult(
                    provider_event_id=provider_event.id,
                    matched_operation=False,
                    duplicate=False,
                    wake_scheduled=False,
                )
            workspace_id = operation.workspace_id
            operation_id = operation.operation_id
            artifact_key = await capture_discovery_artifact(
                conn,
                self._storage,
                workspace_id=workspace_id,
                content=raw_body,
                media_type=_json_or_binary(raw_body),
                source_key=EXA_WEBSETS_SOURCE_KEY,
                source_url=f"{EXA_WEBSETS_API_BASE}/events/{provider_event.id}",
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
            wake_scheduled = False
            if created:
                batch = await get_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=operation.batch_id
                )
                if batch is None:
                    raise DiscoveryNotFound(f"discovery batch {operation.batch_id}")
                if batch.state not in {
                    DiscoveryBatchState.SEALED,
                    DiscoveryBatchState.FAILED_TERMINAL,
                    DiscoveryBatchState.CANCELLED_UNSEALED,
                }:
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
                    wake_scheduled = True
        return ExaWebhookResult(
            provider_event_id=provider_event.id,
            matched_operation=True,
            workspace_id=workspace_id,
            operation_id=operation_id,
            duplicate=not created,
            wake_scheduled=wake_scheduled,
        )


def build_exa_webhook_router(ingestor: ExaWebhookIngestor) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/v1/webhooks/exa-websets",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def receive_exa_event(
        request: Request,
        exa_signature: Annotated[str | None, Header(alias="Exa-Signature")] = None,
    ) -> dict[str, JsonValue]:
        if exa_signature is None:
            raise HTTPException(status_code=400, detail="missing Exa-Signature header")
        raw_body = await request.body()
        try:
            result = await ingestor.ingest(
                raw_body=raw_body,
                signature_header=exa_signature,
            )
        except (
            ExaWebhookVerificationError,
            ExaWebsetsContractDrift,
            ExaLifecycleReconciliationError,
        ) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
            batch = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=operation.batch_id
            )
            if batch is None:
                raise DiscoveryNotFound(f"discovery batch {operation.batch_id}")
            plan_row = await get_discovery_plan(
                conn, workspace_id=workspace_id, plan_id=batch.discovery_plan_id
            )
            if plan_row is None:
                raise DiscoveryNotFound(f"discovery plan {batch.discovery_plan_id}")
            if plan_row.plan.provider_policy_version != self._pricing.version:
                raise ExaLifecycleReconciliationError(
                    "discovery plan pricing policy does not match the configured Exa policy"
                )
            if operation.cost_cents_reserved != self._pricing.monetary_value(
                operation.provider_units_reserved
            ):
                raise ExaLifecycleReconciliationError(
                    "operation monetary reservation disagrees with the configured Exa policy"
                )
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
                stored_items, charge = await self._reconcile(
                    workspace_id=workspace_id,
                    operation=claimed,
                    request=request,
                    webset=final_poll.webset,
                )
                result = await self._succeed(
                    workspace_id=workspace_id,
                    operation=claimed,
                    webset=final_poll.webset,
                    item_count=len(stored_items),
                    charge=charge,
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
                raw = exchange.response_body
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
            await self._persist_items(workspace_id, operation, page_row.id, page, raw)
            if not page.has_more:
                return
            cursor = page.next_cursor

    async def _persist_items(
        self,
        workspace_id: str,
        operation: DiscoveryOperation,
        page_id: object,
        page: ExaItemPage,
        raw_page: bytes,
    ) -> None:
        from uuid import UUID

        if not isinstance(page_id, UUID):
            raise TypeError("page receipt id must be a UUID")
        raw_payload = json.loads(raw_page)
        if not isinstance(raw_payload, dict) or not isinstance(raw_payload.get("data"), list):
            raise ExaLifecycleReconciliationError("persisted Exa item page has no data array")
        raw_by_id: dict[str, dict[str, object]] = {}
        for raw_item in raw_payload["data"]:
            if not isinstance(raw_item, dict) or not isinstance(raw_item.get("id"), str):
                raise ExaLifecycleReconciliationError("persisted Exa page contains an invalid item")
            if raw_item["id"] in raw_by_id:
                raise ExaLifecycleReconciliationError("Exa page repeats an item id")
            raw_by_id[raw_item["id"]] = raw_item
        if set(raw_by_id) != {item.id for item in page.data}:
            raise ExaLifecycleReconciliationError("typed and raw Exa page items disagree")

        async with self._conn_factory() as conn:
            for ordinal, provider_item in enumerate(page.data):
                raw = json.dumps(
                    raw_by_id[provider_item.id],
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
    ) -> tuple[tuple[DiscoveryItemSnapshot, ...], ExaWebsetsChargeBreakdown]:
        if webset.id != operation.provider_operation_id:
            raise ExaLifecycleReconciliationError("provider Webset id changed")
        if webset.imports:
            raise ExaLifecycleReconciliationError("search-only Webset contains imports")
        if len(webset.searches) != 1 or webset.searches[0].status.value != "completed":
            raise ExaLifecycleReconciliationError("terminal Webset search is not completed")
        search = webset.searches[0]
        if search.webset_id != webset.id:
            raise ExaLifecycleReconciliationError("terminal search belongs to another Webset")
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
        found = search.progress.found
        if found != found.to_integral_value() or int(found) != len(items):
            raise ExaLifecycleReconciliationError(
                "terminal search found count disagrees with item pagination"
            )
        if search.progress.completion != 100:
            raise ExaLifecycleReconciliationError("completed search progress is not 100 percent")

        requested_by_field = {
            enrichment.metadata.get("clueFieldKey"): enrichment
            for enrichment in request.enrichments
        }
        provider_by_field = {
            enrichment.metadata.get("clueFieldKey"): enrichment for enrichment in webset.enrichments
        }
        if (
            None in requested_by_field
            or None in provider_by_field
            or len(requested_by_field) != len(request.enrichments)
            or len(provider_by_field) != len(webset.enrichments)
            or requested_by_field.keys() != provider_by_field.keys()
        ):
            raise ExaLifecycleReconciliationError(
                "terminal enrichment definitions do not map one-to-one to logical fields"
            )
        definition_by_id = {
            provider.id: (requested_by_field[field_key], provider)
            for field_key, provider in provider_by_field.items()
        }
        if len(definition_by_id) != len(provider_by_field):
            raise ExaLifecycleReconciliationError("terminal Webset repeats an enrichment id")

        expected_criteria = {criterion.description for criterion in request.search.criteria}
        item_ids = {item.provider_item_id for item in items}
        matching_search_results = 0
        ordinary_enrichment_rows = 0
        contact_values = 0
        for item in items:
            provider_item = ExaWebsetItem.model_validate_json(
                await self._storage.get(item.raw_artifact_key)
            )
            if provider_item.webset_id != webset.id:
                raise ExaLifecycleReconciliationError("item belongs to another Webset")
            if provider_item.source != "search":
                raise ExaLifecycleReconciliationError(
                    "search-only operation contains an import item"
                )
            if provider_item.source_id != search.id:
                raise ExaLifecycleReconciliationError("item belongs to another search")
            if provider_item.source_entity_id is not None or provider_item.scope_id is not None:
                raise ExaLifecycleReconciliationError("search item carries import/scope identity")
            requested_entity = request.search.entity
            if (
                requested_entity is None
                or provider_item.properties.type != requested_entity.type.value
            ):
                raise ExaLifecycleReconciliationError("item entity type differs from the request")

            evaluations = {
                evaluation.criterion: evaluation for evaluation in provider_item.evaluations
            }
            if (
                len(evaluations) != len(provider_item.evaluations)
                or evaluations.keys() != expected_criteria
            ):
                raise ExaLifecycleReconciliationError(
                    "item evaluations do not cover each requested criterion exactly once"
                )
            if all(evaluation.satisfied == "yes" for evaluation in evaluations.values()):
                matching_search_results += 1

            results = {result.enrichment_id: result for result in provider_item.enrichment_results}
            if (
                len(results) != len(provider_item.enrichment_results)
                or results.keys() != definition_by_id.keys()
            ):
                raise ExaLifecycleReconciliationError(
                    "item enrichments do not cover each requested field exactly once"
                )
            for enrichment_id, result in results.items():
                requested_enrichment, _provider_definition = definition_by_id[enrichment_id]
                if result.status != "completed":
                    raise ExaLifecycleReconciliationError(
                        "terminal item has an incomplete enrichment result"
                    )
                if (
                    requested_enrichment.format is None
                    or result.format != requested_enrichment.format
                ):
                    raise ExaLifecycleReconciliationError(
                        "item enrichment result format differs from the requested format"
                    )
                _validate_enrichment_result(requested_enrichment, result.result)
                if result.format in {
                    ExaWebsetEnrichmentFormat.EMAIL,
                    ExaWebsetEnrichmentFormat.PHONE,
                }:
                    contact_values += len(result.result or ())
                else:
                    ordinary_enrichment_rows += 1
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
        charge = self._pricing.realized_units(
            matching_search_results=matching_search_results,
            ordinary_enrichment_rows=ordinary_enrichment_rows,
            contact_values=contact_values,
        )
        return items, charge

    async def _succeed(
        self,
        *,
        workspace_id: str,
        operation: DiscoveryOperation,
        webset: ExaWebset,
        item_count: int,
        charge: ExaWebsetsChargeBreakdown,
        observed_at: datetime,
    ) -> ExaLifecycleResult:
        realized_units = charge.total_units
        if realized_units > operation.provider_units_reserved:
            raise ExaLifecycleReconciliationError("realized units exceed reserved units")
        realized_cost_cents = self._pricing.monetary_value(realized_units)
        if realized_cost_cents > operation.cost_cents_reserved:
            raise ExaLifecycleReconciliationError("realized monetary value exceeds reservation")
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
                    "costCentsAttributed": str(realized_cost_cents),
                    "costSemantics": "subscription-credit-allocation-equivalent",
                    "chargeBreakdown": charge.model_dump(mode="json"),
                    "settlementMethod": "public-credit-rules-applied-to-terminal-item-facts",
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
                    "cost_cents_charged": realized_cost_cents,
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
            batch = await reconcile_discovery_batch_state(
                conn, workspace_id=workspace_id, batch_id=operation.batch_id
            )
            if batch.state is DiscoveryBatchState.IDENTITY_RESOLUTION:
                await schedule_discovery_wake(
                    conn,
                    workspace_id=workspace_id,
                    request=DiscoveryWakeRequest(
                        workspace_id=workspace_id,
                        project_run_id=batch.project_run_id,
                        discovery_batch_id=batch.id,
                        operation_id=operation.operation_id,
                        reason=DiscoveryWakeReason.FIELD_MATERIALIZATION,
                        available_at=observed_at,
                        dedupe_key=f"d4-materialize:{batch.id}",
                    ),
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
            await reconcile_discovery_batch_state(
                conn, workspace_id=workspace_id, batch_id=operation.batch_id
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
        materializer: DiscoveryBatchMaterializer | None = None,
        project_run_waker: Callable[[ProjectRunId], Awaitable[object]] | None = None,
        conn_factory: ConnFactory = transaction,
        claim_stale_after: timedelta = timedelta(minutes=5),
    ) -> None:
        self._lifecycle = lifecycle
        self._materializer = materializer
        self._project_run_waker = project_run_waker
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
            if wake.reason == DiscoveryWakeReason.FIELD_MATERIALIZATION.value:
                if self._materializer is None:
                    raise RuntimeError("D4 materialization wake has no configured materializer")
                await self._materializer.materialize(
                    workspace_id=wake.workspace_id,
                    batch_id=wake.batch_id,
                )
                # D5: the durable project machine may be sleeping on WAITING_EXTERNAL. Re-offer
                # it only after D4 has made every field terminal; enqueue is idempotent. Do this
                # before completing the wake so a queue failure leaves a reclaimable retry.
                if self._project_run_waker is not None:
                    await self._project_run_waker(wake.project_run_id)
            else:
                await self._lifecycle.run_once(
                    workspace_id=wake.workspace_id,
                    operation_id=wake.operation_id,
                    now=now,
                )
            async with self._conn_factory() as conn:
                await complete_discovery_wake(conn, workspace_id=wake.workspace_id, wake_id=wake.id)
            completed += 1
        return completed


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
    "ExaTeamWebhookProvisioner",
    "ExaWebhookProvisionResult",
    "ExaWebhookResult",
    "EXA_TEAM_WEBHOOK_EVENTS",
    "build_exa_webhook_router",
]
