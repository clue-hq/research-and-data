"""D3 mechanical acceptance against real PostgreSQL and filesystem artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text

from clue_api.exa_websets_lifecycle import (
    EXA_TEAM_WEBHOOK_EVENTS,
    DurableExaWebsetLifecycle,
    ExaLifecycleOutcome,
    ExaLifecycleReconciliationError,
    ExaTeamWebhookProvisioner,
    ExaWebhookIngestor,
    build_exa_webhook_router,
)
from clue_api.exa_websets_submit import DurableExaWebsetSubmitter
from clue_core import (
    DiscoveryBatchState,
    DiscoveryCriterionPlan,
    DiscoveryEnrichmentFormat,
    DiscoveryEnrichmentPlan,
    DiscoveryEntityKind,
    DiscoveryOperation,
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPlan,
    DiscoverySearchPlan,
    ICPCreatedFrom,
    ProjectPhase,
    new_discovery_batch_id,
    new_discovery_plan_id,
    new_project_run_id,
)
from clue_db import db_lifespan, transaction
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_CONTRACT_VERSION,
    ExaCreateWebhookRequest,
    ExaCreateWebsetRequest,
    ExaEventPage,
    ExaEventPageExchange,
    ExaItemPage,
    ExaItemPageExchange,
    ExaWebhook,
    ExaWebhookPage,
    ExaWebsetExchange,
    ExaWebsetItem,
    ExaWebsetItemCompanyProperties,
    ExaWebsetsContractDrift,
    ExaWebsetsRateLimited,
)
from clue_research.claimstore import load_core_pack
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.durable import (
    claim_due_discovery_wakes,
    complete_discovery_wake,
    create_discovery_batch,
    ensure_project_run,
    get_discovery_batch,
    get_discovery_operation,
    list_discovery_events,
    list_discovery_items,
    list_discovery_pages,
    put_discovery_plan,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.icp import create_icp_spec
from clue_storage import FsStorage
from tests._workspace import seed_project
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/discovery/exa_websets"
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


async def _with_db(coro: Awaitable[None]) -> None:
    async with db_lifespan():
        await coro


def _webset_payload(request: ExaCreateWebsetRequest, *, status: str) -> dict[str, object]:
    search_status = "completed" if status == "idle" else "running"
    enrichment_status = "completed" if status == "idle" else "pending"
    enrichments = []
    enrichment_ids = (
        "enr_fixture_linkedin",
        "enr_fixture_email",
        "enr_fixture_phone",
    )
    for item, enrichment_id in zip(request.enrichments, enrichment_ids, strict=True):
        enrichments.append(
            {
                "id": enrichment_id,
                "object": "webset_enrichment",
                "status": enrichment_status,
                "websetId": "ws_fixture_running",
                "title": item.description,
                "description": item.description,
                "format": (
                    "text"
                    if item.format and item.format.value in {"email", "phone"}
                    else item.format.value
                    if item.format
                    else None
                ),
                "options": [option.model_dump() for option in item.options] or None,
                "instructions": "Synthetic terminal fixture instructions",
                "metadata": item.metadata,
                "createdAt": "2026-08-02T08:00:00Z",
                "updatedAt": "2026-08-02T08:05:00Z",
            }
        )
    return {
        "id": "ws_fixture_running",
        "object": "webset",
        "status": status,
        "externalId": request.external_id,
        "title": "D3 mechanical fixture",
        "searches": [
            {
                "id": "ws_search_fixture_1",
                "object": "webset_search",
                "websetId": "ws_fixture_running",
                "status": search_status,
                "query": request.search.query,
                "entity": request.search.entity.model_dump(exclude_none=True)
                if request.search.entity
                else None,
                "criteria": [
                    {"description": criterion.description, "successRate": 33.3}
                    for criterion in request.search.criteria
                ],
                "count": request.search.count,
                "maxPeoplePerCompany": request.search.max_people_per_company,
                "behavior": "override",
                "exclude": [],
                "scope": [],
                "progress": {"found": 3.0, "analyzed": 12, "completion": 100, "timeLeft": 0},
                "recall": None,
                "metadata": {},
                "canceledAt": None,
                "canceledReason": None,
                "createdAt": "2026-08-02T08:00:00Z",
                "updatedAt": "2026-08-02T08:05:00Z",
            }
        ],
        "imports": [],
        "enrichments": enrichments,
        "monitors": [],
        "excludes": [],
        "metadata": request.metadata,
        "dashboardUrl": "https://websets.exa.ai/websets/ws_fixture_running",
        "createdAt": "2026-08-02T08:00:00Z",
        "updatedAt": "2026-08-02T08:05:00Z",
    }


def _webset_exchange(
    request: ExaCreateWebsetRequest, *, status: str, status_code: int = 200
) -> ExaWebsetExchange:
    body = json.dumps(_webset_payload(request, status=status), sort_keys=True).encode()
    return ExaWebsetExchange(
        status_code=status_code,
        request_id=f"req_{status}",
        response_body=body,
        webset=json.loads(body),
    )


class _SubmitTransport:
    def __init__(self) -> None:
        self.request: ExaCreateWebsetRequest | None = None
        self.create_calls = 0

    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange:
        self.request = request
        self.create_calls += 1
        return _webset_exchange(request, status="running", status_code=201)

    async def get_webset(self, _: str) -> ExaWebsetExchange:
        assert self.request is not None
        return _webset_exchange(self.request, status="running")


class _WebhookAdminTransport:
    def __init__(self, existing: tuple[ExaWebhook, ...] = ()) -> None:
        self.existing = existing
        self.create_calls = 0
        self.created_request: ExaCreateWebhookRequest | None = None

    async def list_webhooks(self, *, cursor: str | None = None, limit: int = 200) -> ExaWebhookPage:
        assert cursor is None
        assert limit == 200
        return ExaWebhookPage(data=self.existing, hasMore=False, nextCursor=None)

    async def create_webhook(self, request: ExaCreateWebhookRequest) -> ExaWebhook:
        self.create_calls += 1
        self.created_request = request
        return ExaWebhook(
            id="webhook_fixture",
            object="webhook",
            status="active",
            events=EXA_TEAM_WEBHOOK_EVENTS,
            url="https://api.example.test/v1/webhooks/exa-websets",
            secret=SecretStr("one-time-secret"),
            metadata={"clueEndpoint": "team-websets-v1"},
            createdAt=_NOW,
            updatedAt=_NOW,
        )


class _LifecycleTransport:
    def __init__(
        self,
        request: ExaCreateWebsetRequest,
        *,
        rate_limit_once: bool = False,
    ) -> None:
        self.request = request
        self.rate_limit_once = rate_limit_once
        self.poll_calls = 0
        self.item_calls: list[str | None] = []
        self.event_calls: list[str | None] = []

    async def poll_webset(self, _: str) -> ExaWebsetExchange:
        self.poll_calls += 1
        if self.rate_limit_once:
            self.rate_limit_once = False
            raise ExaWebsetsRateLimited(
                "rate limited",
                status_code=429,
                response_body=b'{"error":"slow down"}',
                retry_after_seconds=7,
            )
        return _webset_exchange(self.request, status="idle")

    async def list_items(
        self, _: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange:
        assert limit == 100
        self.item_calls.append(cursor)
        name = "items-page-1.json" if cursor is None else "items-page-2.json"
        raw = (_FIXTURES / name).read_bytes()
        return ExaItemPageExchange(
            status_code=200,
            response_body=raw,
            page=ExaItemPage.model_validate_json(raw),
        )

    async def list_events(
        self, *, cursor: str | None = None, limit: int = 200
    ) -> ExaEventPageExchange:
        assert limit == 200
        self.event_calls.append(cursor)
        raw = (_FIXTURES / "events-duplicate-out-of-order.json").read_bytes()
        return ExaEventPageExchange(
            status_code=200,
            response_body=raw,
            page=ExaEventPage.model_validate_json(raw),
        )


class _MutatingLifecycleTransport(_LifecycleTransport):
    def __init__(
        self,
        request: ExaCreateWebsetRequest,
        *,
        mutate_item_page: Callable[[dict[str, object]], None] | None = None,
        mutate_webset: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        super().__init__(request)
        self._mutate_item_page = mutate_item_page
        self._mutate_webset = mutate_webset

    async def poll_webset(self, _: str) -> ExaWebsetExchange:
        self.poll_calls += 1
        payload = _webset_payload(self.request, status="idle")
        if self._mutate_webset is not None:
            self._mutate_webset(payload)
        raw = json.dumps(payload, sort_keys=True).encode()
        return ExaWebsetExchange(status_code=200, response_body=raw, webset=payload)

    async def list_items(
        self, _: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange:
        assert limit == 100
        self.item_calls.append(cursor)
        name = "items-page-1.json" if cursor is None else "items-page-2.json"
        payload = json.loads((_FIXTURES / name).read_bytes())
        if cursor is None and self._mutate_item_page is not None:
            self._mutate_item_page(payload)
        raw = json.dumps(payload, sort_keys=True).encode()
        return ExaItemPageExchange(
            status_code=200,
            response_body=raw,
            page=ExaItemPage.model_validate(payload),
        )


async def _create_submitted_operation(
    workspace_id: str, storage: FsStorage, *, include_second_search: bool = False
) -> tuple[DiscoveryOperation, ExaCreateWebsetRequest]:
    async with transaction() as conn:
        await load_core_pack(conn)
        project = await seed_project(conn, workspace_id, name="D3 mechanical acceptance")
        icp = await create_icp_spec(
            conn,
            workspace_id=workspace_id,
            icp_key="independent-specialty-practices",
            created_from=ICPCreatedFrom.SYNTHESIS,
            field_keys=("core.primary_domain", "core.employee_count"),
            activate=True,
        )
        run_id = new_project_run_id()
        await ensure_project_run(
            conn,
            project_run_id=run_id,
            project_id=project.project_id,
            workspace_id=workspace_id,
            icp_key=icp.icp_key,
            icp_version=icp.version,
            phase=ProjectPhase.DISCOVERY,
            status=ProjectRunStatus.ACTIVE,
        )
        first_search = DiscoverySearchPlan(
            search_key="account-discovery",
            channel_key="exa_websets",
            normalized_query="Independent specialty practices in the United States",
            entity_type=DiscoveryEntityKind.COMPANY,
            requested_count=3,
            criteria=(
                DiscoveryCriterionPlan(
                    description="Organization is an independent specialty practice"
                ),
            ),
            enrichments=(
                DiscoveryEnrichmentPlan(
                    field_key="core.company_linkedin_url",
                    description="Find the canonical LinkedIn company page URL",
                    format=DiscoveryEnrichmentFormat.URL,
                ),
                DiscoveryEnrichmentPlan(
                    field_key="core.company_email",
                    description="Find the general company email address",
                    format=DiscoveryEnrichmentFormat.EMAIL,
                ),
                DiscoveryEnrichmentPlan(
                    field_key="core.company_phone",
                    description="Find the general company phone number",
                    format=DiscoveryEnrichmentFormat.PHONE,
                ),
            ),
        )
        searches = (first_search,)
        if include_second_search:
            searches += (
                first_search.model_copy(
                    update={
                        "search_key": "account-discovery-second",
                        "normalized_query": ("Independent spine practices in the United States"),
                    }
                ),
            )
        plan = DiscoveryPlan(
            discovery_plan_id=new_discovery_plan_id(),
            plan_version=1,
            workspace_id=workspace_id,
            project_id=project.project_id,
            project_run_id=run_id,
            icp_key=icp.icp_key,
            icp_version=icp.version,
            provider_policy_version=(
                "exa-websets-public-credit-policy-2026-08-03+pro-usd-allocation"
            ),
            field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
            provider_contract_version=EXA_WEBSETS_CONTRACT_VERSION,
            channels=("exa_websets",),
            searches=searches,
            required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
            optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
            provider_credit_cap=66 * len(searches),
            money_budget_cap_cents=Decimal("100"),
            stopping_policy={"requested_count": 3},
            snapshot_reuse_policy="same_observation_window",
        )
        await put_discovery_plan(conn, workspace_id=workspace_id, plan=plan)
        batch_id = new_discovery_batch_id()
        await create_discovery_batch(
            conn,
            workspace_id=workspace_id,
            batch_id=batch_id,
            plan_id=plan.discovery_plan_id,
            generation=1,
        )
    submit_transport = _SubmitTransport()
    submitted = await DurableExaWebsetSubmitter(
        transport=submit_transport,
        storage=storage,
    ).submit(
        workspace_id=workspace_id,
        batch_id=batch_id,
        search_key="account-discovery",
        observation_window="2026-08-03",
    )
    assert submit_transport.request is not None
    return submitted.operation, submit_transport.request


async def _cleanup(workspace_id: str) -> None:
    async with transaction() as conn:
        # D1 deliberately makes plans/pages immutable. This is a disposable integration-fixture
        # teardown, scoped to one random workspace and one transaction; production paths never
        # bypass these triggers.
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        for statement in (
            "DELETE FROM discovery_provider_event WHERE workspace_id=:workspace_id",
            "DELETE FROM discovery_page_item WHERE workspace_id=:workspace_id",
            "DELETE FROM discovery_item_snapshot WHERE workspace_id=:workspace_id",
            "DELETE FROM discovery_page_receipt WHERE workspace_id=:workspace_id",
            "DELETE FROM discovery_wake_outbox WHERE workspace_id=:workspace_id",
            "DELETE FROM discovery_operation WHERE workspace_id=:workspace_id",
            "DELETE FROM discovery_batch WHERE workspace_id=:workspace_id",
            "DELETE FROM discovery_plan WHERE workspace_id=:workspace_id",
            "DELETE FROM artifact WHERE workspace_id=:workspace_id",
            "DELETE FROM project_run WHERE workspace_id=:workspace_id",
            "DELETE FROM icp_spec WHERE workspace_id=:workspace_id",
            "DELETE FROM project WHERE workspace_id=:workspace_id",
            "DELETE FROM brand WHERE workspace_id=:workspace_id",
            "DELETE FROM workspace WHERE workspace_id=:workspace_id",
        ):
            await conn.execute(text(statement), {"workspace_id": workspace_id})


def _signed(secret: str, raw: bytes, at: datetime) -> str:
    timestamp = str(int(at.timestamp()))
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_real_db_webhooks_are_verified_deduped_and_only_enqueue(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"ws_d3_webhook_{uuid4().hex}"
        storage = FsStorage(tmp_path / "webhook-artifacts")
        try:
            operation, _ = await _create_submitted_operation(workspace_id, storage)
            ingestor = ExaWebhookIngestor(
                secret=SecretStr("fixture-webhook-secret"), storage=storage
            )
            payload = json.loads((_FIXTURES / "events-duplicate-out-of-order.json").read_bytes())
            enriched = json.dumps(payload["data"][0], separators=(",", ":")).encode()
            created = json.dumps(payload["data"][1], separators=(",", ":")).encode()
            first = await ingestor.ingest(
                raw_body=enriched,
                signature_header=_signed("fixture-webhook-secret", enriched, _NOW),
                received_at=_NOW,
            )
            duplicate = await ingestor.ingest(
                raw_body=enriched,
                signature_header=_signed("fixture-webhook-secret", enriched, _NOW),
                received_at=_NOW,
            )
            await ingestor.ingest(
                raw_body=created,
                signature_header=_signed("fixture-webhook-secret", created, _NOW),
                received_at=_NOW,
            )
            assert first.wake_scheduled is True
            assert first.matched_operation is True
            assert first.workspace_id == workspace_id
            assert first.operation_id == operation.operation_id
            assert duplicate.duplicate is True
            async with transaction() as conn:
                events = await list_discovery_events(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                )
                current = await get_discovery_operation(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                )
                wake_count = int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM discovery_wake_outbox "
                                "WHERE workspace_id=:workspace_id"
                            ),
                            {"workspace_id": workspace_id},
                        )
                    ).scalar_one()
                )
            assert [event.provider_event_id for event in events] == [
                "evt_fixture_item_created",
                "evt_fixture_item_enriched",
            ]
            assert wake_count == 3
            assert current is not None
            assert current.state is DiscoveryOperationState.PROVIDER_RUNNING

            app = FastAPI()
            app.include_router(build_exa_webhook_router(ingestor))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                invalid = await client.post(
                    "/v1/webhooks/exa-websets",
                    content=created,
                    headers={"Exa-Signature": "t=1,v1=bad"},
                )
            assert invalid.status_code == 400
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def test_signed_unrelated_team_webhook_is_acknowledged_without_tenant_persistence(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        storage = FsStorage(tmp_path / "unrelated-webhook-artifacts")
        ingestor = ExaWebhookIngestor(secret=SecretStr("fixture-webhook-secret"), storage=storage)
        payload = json.loads((_FIXTURES / "events-duplicate-out-of-order.json").read_bytes())
        unrelated = deepcopy(payload["data"][0])
        unrelated["id"] = f"evt_unrelated_{uuid4().hex}"
        unrelated["data"]["websetId"] = f"ws_unrelated_{uuid4().hex}"
        raw = json.dumps(unrelated, separators=(",", ":")).encode()
        result = await ingestor.ingest(
            raw_body=raw,
            signature_header=_signed("fixture-webhook-secret", raw, _NOW),
            received_at=_NOW,
        )
        assert result.matched_operation is False
        assert result.workspace_id is None
        assert result.operation_id is None
        assert result.wake_scheduled is False
        async with transaction() as conn:
            event_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM discovery_provider_event "
                            "WHERE provider_event_id=:event_id"
                        ),
                        {"event_id": unrelated["id"]},
                    )
                ).scalar_one()
            )
            artifact_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM artifact WHERE content_sha256=:sha"),
                        {"sha": hashlib.sha256(raw).hexdigest()},
                    )
                ).scalar_one()
            )
        assert event_count == 0
        assert artifact_count == 0

    run_async(_with_db(_run()))


def test_team_webhook_provisioning_is_one_endpoint_and_refuses_silent_reconfiguration() -> None:
    async def _run() -> None:
        url = "https://api.example.test/v1/webhooks/exa-websets"
        empty = _WebhookAdminTransport()
        created = await ExaTeamWebhookProvisioner(transport=empty).ensure(url=url)
        assert created.created is True
        assert created.secret is not None
        assert empty.create_calls == 1
        assert empty.created_request is not None
        assert empty.created_request.url == url
        assert empty.created_request.events == EXA_TEAM_WEBHOOK_EVENTS
        assert empty.created_request.metadata == {"clueEndpoint": "team-websets-v1"}

        existing = ExaWebhook(
            id="webhook_fixture",
            object="webhook",
            status="active",
            events=EXA_TEAM_WEBHOOK_EVENTS,
            url=url,
            secret=None,
            metadata={"clueEndpoint": "team-websets-v1"},
            createdAt=_NOW,
            updatedAt=_NOW,
        )
        present = _WebhookAdminTransport((existing,))
        replay = await ExaTeamWebhookProvisioner(transport=present).ensure(url=url)
        assert replay.created is False
        assert replay.secret is None
        assert present.create_calls == 0

        mismatched = existing.model_copy(update={"url": "https://wrong.example.test/hook"})
        with pytest.raises(ExaLifecycleReconciliationError, match="differs"):
            await ExaTeamWebhookProvisioner(transport=_WebhookAdminTransport((mismatched,))).ensure(
                url=url
            )

    run_async(_run())


def test_missed_webhook_polling_paginates_reconciles_cost_and_replays_zero_calls(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = f"ws_d3_poll_{uuid4().hex}"
        storage = FsStorage(tmp_path / "poll-artifacts")
        try:
            operation, request = await _create_submitted_operation(workspace_id, storage)
            transport = _LifecycleTransport(request)
            lifecycle = DurableExaWebsetLifecycle(transport=transport, storage=storage)
            result = await lifecycle.run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW,
            )
            replay = await DurableExaWebsetLifecycle(transport=transport, storage=storage).run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW + timedelta(minutes=1),
            )

            assert result.outcome is ExaLifecycleOutcome.SUCCEEDED
            assert result.stored_item_count == 3
            assert result.operation.provider_units_charged == 31
            assert result.operation.provider_units_reserved == 66
            assert result.operation.cost_cents_reserved == Decimal("29.634")
            assert result.operation.cost_cents_charged == Decimal("13.919")
            assert transport.poll_calls == 2
            assert transport.item_calls == [None, "cursor_fixture_page_2"]
            assert transport.event_calls == [None]
            assert replay.outcome is ExaLifecycleOutcome.REPLAYED
            assert replay.poll_calls == replay.item_page_calls == replay.event_page_calls == 0
            receipt = json.loads(
                await storage.get(result.operation.final_receipt_ref or "missing-receipt")
            )
            assert receipt["providerUnitsCharged"] == "31"
            assert receipt["costCentsAttributed"] == "13.919"
            assert receipt["costSemantics"] == "subscription-credit-allocation-equivalent"
            assert receipt["chargeBreakdown"] == {
                "contact_enrichment_credits": "15",
                "contact_values": 3,
                "import_credits": "0",
                "matching_search_results": 1,
                "ordinary_enrichment_credits": "6",
                "ordinary_enrichment_rows": 3,
                "resolved_import_results": 0,
                "search_credits": "10",
            }

            async with transaction() as conn:
                items = await list_discovery_items(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                )
                pages = await list_discovery_pages(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                )
                batch = await get_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=operation.batch_id
                )
                candidate_count = int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM discovery_candidate_link "
                                "WHERE workspace_id=:workspace_id"
                            ),
                            {"workspace_id": workspace_id},
                        )
                    ).scalar_one()
                )
            assert len(items) == 3
            assert all(item.normalization_state.value == "raw" for item in items)
            northstar_snapshot = next(
                item for item in items if item.provider_item_id == "wsi_fixture_northstar"
            )
            northstar_raw = await storage.get(northstar_snapshot.raw_artifact_key)
            northstar_payload = json.loads(northstar_raw)
            company = northstar_payload["properties"]["company"]
            assert company["financials"]["revenueAnnual"] == 12_500_000
            assert company["financials"]["fundingTotal"] == 3_500_000
            assert company["financials"]["fundingLatestRound"]["amount"] == 3_500_000
            assert company["headquarters"]["countryCode"] == "US"
            projected = ExaWebsetItem.model_validate_json(northstar_raw).properties
            assert isinstance(projected, ExaWebsetItemCompanyProperties)
            discovery_fields = projected.discovery_fields()
            assert discovery_fields["employees"] == 42
            assert "foundedYear" not in discovery_fields
            assert "webTraffic" not in discovery_fields
            assert {page.receipt.resource_kind.value for page in pages} == {
                "websets",
                "searches",
                "enrichments",
                "items",
                "events",
            }
            assert batch is not None
            assert batch.state is DiscoveryBatchState.IDENTITY_RESOLUTION
            assert batch.provider_units_reserved == 66
            assert batch.provider_units_charged == 31
            assert batch.cost_cents_reserved == Decimal("29.634")
            assert batch.cost_cents_charged == Decimal("13.919")
            assert candidate_count == 0
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def test_one_successful_operation_cannot_advance_a_multi_search_batch(tmp_path: Path) -> None:
    class _SecondSubmitTransport:
        def __init__(self) -> None:
            self.request: ExaCreateWebsetRequest | None = None

        async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange:
            self.request = request
            payload = _webset_payload(request, status="running")
            payload["id"] = "ws_fixture_second"
            payload["dashboardUrl"] = "https://websets.exa.ai/websets/ws_fixture_second"
            searches = payload["searches"]
            enrichments = payload["enrichments"]
            assert isinstance(searches, list) and len(searches) == 1
            assert isinstance(enrichments, list)
            searches[0]["id"] = "ws_search_fixture_second"
            searches[0]["websetId"] = "ws_fixture_second"
            for index, enrichment in enumerate(enrichments):
                enrichment["id"] = f"enr_fixture_second_{index}"
                enrichment["websetId"] = "ws_fixture_second"
            raw = json.dumps(payload, sort_keys=True).encode()
            return ExaWebsetExchange(status_code=201, response_body=raw, webset=payload)

        async def get_webset(self, _: str) -> ExaWebsetExchange:
            raise AssertionError("duplicate lookup is not expected")

    async def _run() -> None:
        workspace_id = f"ws_d3_multi_{uuid4().hex}"
        storage = FsStorage(tmp_path / "multi-search-artifacts")
        try:
            first_operation, first_request = await _create_submitted_operation(
                workspace_id, storage, include_second_search=True
            )
            second_submit = await DurableExaWebsetSubmitter(
                transport=_SecondSubmitTransport(), storage=storage
            ).submit(
                workspace_id=workspace_id,
                batch_id=first_operation.batch_id,
                search_key="account-discovery-second",
                observation_window="2026-08-03",
            )
            assert second_submit.operation.state is DiscoveryOperationState.PROVIDER_RUNNING

            first_result = await DurableExaWebsetLifecycle(
                transport=_LifecycleTransport(first_request), storage=storage
            ).run_once(
                workspace_id=workspace_id,
                operation_id=first_operation.operation_id,
                now=_NOW,
            )
            assert first_result.outcome is ExaLifecycleOutcome.SUCCEEDED
            async with transaction() as conn:
                batch = await get_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=first_operation.batch_id
                )
                states = tuple(
                    (
                        await conn.execute(
                            text(
                                "SELECT state FROM discovery_operation "
                                "WHERE workspace_id=:workspace_id ORDER BY id"
                            ),
                            {"workspace_id": workspace_id},
                        )
                    ).scalars()
                )
            assert batch is not None
            assert batch.state is DiscoveryBatchState.PROVIDER_RUNNING
            assert set(states) == {"succeeded", "provider_running"}
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def _mutate_first_item(payload: dict[str, object], case: str) -> None:
    data = payload["data"]
    assert isinstance(data, list) and data
    item = data[0]
    assert isinstance(item, dict)
    if case == "foreign_webset":
        item["websetId"] = "ws_foreign"
    elif case == "import_source":
        item["source"] = "import"
    elif case == "foreign_search":
        item["sourceId"] = "search_foreign"
    elif case == "wrong_entity":
        properties = item["properties"]
        assert isinstance(properties, dict)
        properties["type"] = "person"
    elif case == "import_identity":
        item["sourceEntityId"] = "imported-entity"
    else:
        evaluations = item["evaluations"]
        enrichments = item["enrichments"]
        assert isinstance(evaluations, list)
        assert isinstance(enrichments, list)
        if case == "missing_criterion":
            evaluations.clear()
        elif case == "duplicate_criterion":
            evaluations.append(deepcopy(evaluations[0]))
        elif case == "invalid_criterion_status":
            evaluations[0]["satisfied"] = "maybe"
        elif case == "missing_enrichment":
            enrichments.pop()
        elif case == "duplicate_enrichment":
            enrichments.append(deepcopy(enrichments[0]))
        elif case == "incomplete_enrichment":
            enrichments[0]["status"] = "pending"
        elif case == "wrong_result_format":
            enrichments[0]["format"] = "number"
        elif case == "invalid_email":
            enrichments[1]["result"] = ["not-an-email"]
        elif case == "invalid_phone":
            enrichments[2]["result"] = ["phone"]
        else:  # pragma: no cover - protects the parametrization itself
            raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    (
        "foreign_webset",
        "import_source",
        "foreign_search",
        "wrong_entity",
        "import_identity",
        "missing_criterion",
        "duplicate_criterion",
        "invalid_criterion_status",
        "missing_enrichment",
        "duplicate_enrichment",
        "incomplete_enrichment",
        "wrong_result_format",
        "invalid_email",
        "invalid_phone",
    ),
)
def test_terminal_item_contract_violations_fail_closed_without_charge(
    tmp_path: Path, case: str
) -> None:
    async def _run() -> None:
        workspace_id = f"ws_d3_adversarial_item_{case}_{uuid4().hex}"
        storage = FsStorage(tmp_path / case)
        try:
            operation, request = await _create_submitted_operation(workspace_id, storage)
            transport = _MutatingLifecycleTransport(
                request,
                mutate_item_page=lambda payload: _mutate_first_item(payload, case),
            )
            result = await DurableExaWebsetLifecycle(transport=transport, storage=storage).run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW,
            )
            assert result.outcome is ExaLifecycleOutcome.FAILED_RETRYABLE
            assert result.operation.provider_units_charged == 0
            assert result.operation.cost_cents_charged == 0
            async with transaction() as conn:
                batch = await get_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=operation.batch_id
                )
            assert batch is not None
            assert batch.state is DiscoveryBatchState.FAILED_RETRYABLE
            assert batch.provider_units_charged == 0
            assert batch.cost_cents_charged == 0
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def _mutate_terminal_webset(payload: dict[str, object], case: str) -> None:
    searches = payload["searches"]
    enrichments = payload["enrichments"]
    assert isinstance(searches, list) and searches
    assert isinstance(enrichments, list) and enrichments
    search = searches[0]
    assert isinstance(search, dict)
    if case == "found_mismatch":
        search["progress"]["found"] = 4.0
    elif case == "completion_not_terminal":
        search["progress"]["completion"] = 99
    elif case == "foreign_search_webset":
        search["websetId"] = "ws_foreign"
    elif case == "import_present":
        payload["imports"] = [{"id": "import_foreign"}]
    elif case == "enrichment_pending":
        enrichments[0]["status"] = "pending"
    elif case == "wrong_logical_field":
        enrichments[0]["metadata"] = {"clueFieldKey": "core.wrong_field"}
    else:  # pragma: no cover - protects the parametrization itself
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    (
        "found_mismatch",
        "completion_not_terminal",
        "foreign_search_webset",
        "import_present",
        "enrichment_pending",
        "wrong_logical_field",
    ),
)
def test_terminal_webset_contract_violations_fail_closed_without_charge(
    tmp_path: Path, case: str
) -> None:
    async def _run() -> None:
        workspace_id = f"ws_d3_adversarial_webset_{case}_{uuid4().hex}"
        storage = FsStorage(tmp_path / case)
        try:
            operation, request = await _create_submitted_operation(workspace_id, storage)
            transport = _MutatingLifecycleTransport(
                request,
                mutate_webset=lambda payload: _mutate_terminal_webset(payload, case),
            )
            result = await DurableExaWebsetLifecycle(transport=transport, storage=storage).run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW,
            )
            assert result.outcome is ExaLifecycleOutcome.FAILED_RETRYABLE
            assert result.operation.provider_units_charged == 0
            assert result.operation.cost_cents_charged == 0
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def test_process_death_after_page_commit_resumes_without_refetch_or_duplicate_cost(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = f"ws_d3_crash_{uuid4().hex}"
        storage = FsStorage(tmp_path / "crash-artifacts")
        crashed = False

        async def crash_once(page: DiscoveryPageReceipt) -> None:
            nonlocal crashed
            if page.resource_kind.value == "items" and not crashed:
                crashed = True
                raise RuntimeError("synthetic process death after durable page commit")

        try:
            operation, request = await _create_submitted_operation(workspace_id, storage)
            transport = _LifecycleTransport(request)
            with pytest.raises(RuntimeError, match="process death"):
                await DurableExaWebsetLifecycle(
                    transport=transport,
                    storage=storage,
                    crash_after_page_persisted=crash_once,
                ).run_once(
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                    now=_NOW,
                )
            async with transaction() as conn:
                committed_page = await conn.execute(
                    text(
                        "SELECT count(*) FROM discovery_page_receipt "
                        "WHERE workspace_id=:workspace_id AND resource_kind='items'"
                    ),
                    {"workspace_id": workspace_id},
                )
                item_count_before = int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM discovery_item_snapshot "
                                "WHERE workspace_id=:workspace_id"
                            ),
                            {"workspace_id": workspace_id},
                        )
                    ).scalar_one()
                )
                assert int(committed_page.scalar_one()) == 1
                assert item_count_before == 0

            resumed = await DurableExaWebsetLifecycle(
                transport=transport, storage=storage
            ).run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW + timedelta(minutes=3),
            )
            assert resumed.outcome is ExaLifecycleOutcome.SUCCEEDED
            assert transport.item_calls == [None, "cursor_fixture_page_2"]
            assert resumed.operation.provider_units_charged == 31
            async with transaction() as conn:
                items = await list_discovery_items(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                )
            assert len(items) == 3
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def test_rate_limit_is_durable_wait_then_same_operation_completes(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"ws_d3_rate_{uuid4().hex}"
        storage = FsStorage(tmp_path / "rate-artifacts")
        try:
            operation, request = await _create_submitted_operation(workspace_id, storage)
            transport = _LifecycleTransport(request, rate_limit_once=True)
            lifecycle = DurableExaWebsetLifecycle(transport=transport, storage=storage)
            first = await lifecycle.run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW,
            )
            assert first.outcome is ExaLifecycleOutcome.RETRY_SCHEDULED
            assert first.operation.operation_id == operation.operation_id
            assert first.operation.next_poll_at == _NOW + timedelta(seconds=7)
            second = await lifecycle.run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW + timedelta(seconds=8),
            )
            assert second.outcome is ExaLifecycleOutcome.SUCCEEDED
            assert second.operation.operation_id == operation.operation_id
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def test_breaking_schema_drift_preserves_body_and_fails_retryably(tmp_path: Path) -> None:
    class _DriftTransport(_LifecycleTransport):
        async def poll_webset(self, _: str) -> ExaWebsetExchange:
            self.poll_calls += 1
            raise ExaWebsetsContractDrift(
                "breaking fixture drift",
                status_code=200,
                response_body=b'{"object":"webset","future":"missing-required-fields"}',
            )

    async def _run() -> None:
        workspace_id = f"ws_d3_drift_{uuid4().hex}"
        storage = FsStorage(tmp_path / "drift-artifacts")
        raw = b'{"object":"webset","future":"missing-required-fields"}'
        try:
            operation, request = await _create_submitted_operation(workspace_id, storage)
            result = await DurableExaWebsetLifecycle(
                transport=_DriftTransport(request), storage=storage
            ).run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW,
            )
            assert result.outcome is ExaLifecycleOutcome.FAILED_RETRYABLE
            assert result.operation.state is DiscoveryOperationState.FAILED_RETRYABLE
            async with transaction() as conn:
                artifact_key = (
                    await conn.execute(
                        text(
                            "SELECT storage_key FROM artifact "
                            "WHERE workspace_id=:workspace_id AND content_sha256=:sha"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "sha": hashlib.sha256(raw).hexdigest(),
                        },
                    )
                ).scalar_one()
                batch = await get_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=operation.batch_id
                )
            assert await storage.get(str(artifact_key)) == raw
            assert batch is not None
            assert batch.state is DiscoveryBatchState.FAILED_RETRYABLE
            assert batch.provider_units_charged == 0
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def test_cancelled_provider_work_never_enters_item_ingestion(tmp_path: Path) -> None:
    class _CancelledTransport(_LifecycleTransport):
        async def poll_webset(self, _: str) -> ExaWebsetExchange:
            self.poll_calls += 1
            payload = _webset_payload(self.request, status="idle")
            searches = payload["searches"]
            assert isinstance(searches, list)
            searches[0]["status"] = "canceled"
            body = json.dumps(payload, sort_keys=True).encode()
            return ExaWebsetExchange(
                status_code=200,
                response_body=body,
                webset=json.loads(body),
            )

    async def _run() -> None:
        workspace_id = f"ws_d3_cancel_{uuid4().hex}"
        storage = FsStorage(tmp_path / "cancel-artifacts")
        try:
            operation, request = await _create_submitted_operation(workspace_id, storage)
            transport = _CancelledTransport(request)
            result = await DurableExaWebsetLifecycle(transport=transport, storage=storage).run_once(
                workspace_id=workspace_id,
                operation_id=operation.operation_id,
                now=_NOW,
            )
            assert result.outcome is ExaLifecycleOutcome.CANCELLED
            assert result.operation.state is DiscoveryOperationState.CANCELLED
            assert transport.item_calls == []
            async with transaction() as conn:
                batch = await get_discovery_batch(
                    conn, workspace_id=workspace_id, batch_id=operation.batch_id
                )
            assert batch is not None
            assert batch.state is DiscoveryBatchState.CANCELLED_UNSEALED
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))


def test_claimed_poll_wake_is_reclaimed_only_after_stale_lease(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = f"ws_d3_wake_{uuid4().hex}"
        storage = FsStorage(tmp_path / "wake-artifacts")
        try:
            operation, _ = await _create_submitted_operation(workspace_id, storage)
            far_future = datetime.now(UTC) + timedelta(hours=1)
            async with transaction() as conn:
                first = await claim_due_discovery_wakes(
                    conn,
                    limit=10,
                    now=far_future,
                    claim_stale_after=timedelta(minutes=5),
                    source_key="exa_websets",
                    workspace_id=workspace_id,
                )
            assert len(first) == 1
            assert first[0].operation_id == operation.operation_id
            async with transaction() as conn:
                early = await claim_due_discovery_wakes(
                    conn,
                    limit=10,
                    now=far_future + timedelta(minutes=4),
                    claim_stale_after=timedelta(minutes=5),
                    source_key="exa_websets",
                    workspace_id=workspace_id,
                )
                assert early == ()
                reclaimed = await claim_due_discovery_wakes(
                    conn,
                    limit=10,
                    now=far_future + timedelta(minutes=6),
                    claim_stale_after=timedelta(minutes=5),
                    source_key="exa_websets",
                    workspace_id=workspace_id,
                )
                assert [wake.id for wake in reclaimed] == [first[0].id]
                await complete_discovery_wake(conn, workspace_id=workspace_id, wake_id=first[0].id)
        finally:
            await _cleanup(workspace_id)

    run_async(_with_db(_run()))
