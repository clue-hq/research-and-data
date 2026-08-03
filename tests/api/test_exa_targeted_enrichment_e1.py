"""E1 import-only targeted enrichment: contract, durability, costs, and replay."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_targeted_enrichment import (
    ExaTargetedEligibilityError,
    ExaTargetedEnrichmentCoordinator,
    ExaTargetedOutcome,
    build_exa_import_request,
    build_exa_import_webset_request,
    compile_exa_targeted_preflight,
)
from clue_core import (
    DiscoveryEnrichmentFormat,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    TargetedEnrichmentFieldPlan,
    account_claim,
)
from clue_research.adapters.exa_websets import (
    ExaCreateImportRequest,
    ExaCreateImportResponse,
    ExaCreateWebsetRequest,
    ExaImportExchange,
    ExaItemPageExchange,
    ExaWebset,
    ExaWebsetEntity,
    ExaWebsetEntityType,
    ExaWebsetExchange,
)
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim
from clue_research.discovery_scoring.discovery import REVENUE_BAND_OPTIONS
from clue_research.discovery_scoring.tiering import TIER_FIELD
from clue_research.durable import (
    append_targeted_enrichment_artifact,
    get_discovery_batch,
    get_targeted_enrichment_operation,
    list_targeted_enrichment_artifacts,
    list_targeted_enrichment_field_results,
    seal_discovery_batch,
)
from clue_research.identity import stamp_reuse
from clue_storage import FsStorage
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import _complete_batch, _start_batch

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _import_payload(request: ExaCreateImportRequest) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": "import_e1",
        "object": "import",
        "status": "pending",
        "format": "csv",
        "entity": request.entity.model_dump(mode="json"),
        "title": request.title,
        "count": request.count,
        "metadata": request.metadata,
        "failedReason": None,
        "failedAt": None,
        "failedMessage": None,
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        "uploadUrl": "https://uploads.example.invalid/object?secret=must-not-persist",
        "uploadValidUntil": (now + timedelta(hours=1)).isoformat(),
    }


def _webset_payload(
    request: ExaCreateWebsetRequest,
    *,
    status: str,
    import_status: str,
    target_url: str,
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    webset_id = "webset_e1"
    definitions = [
        {
            "id": f"enrichment_e1_{index}",
            "object": "webset_enrichment",
            "status": "completed" if status == "idle" else "pending",
            "websetId": webset_id,
            "title": enrichment.description,
            "description": enrichment.description,
            "format": enrichment.format.value if enrichment.format else None,
            "options": [option.model_dump(mode="json") for option in enrichment.options] or None,
            "instructions": None,
            "metadata": enrichment.metadata,
            "createdAt": now,
            "updatedAt": now,
        }
        for index, enrichment in enumerate(request.enrichments)
    ]
    imported = {
        "id": request.imports[0].id,
        "object": "import",
        "status": import_status,
        "format": "csv",
        "entity": {"type": "company"},
        "title": "E1 selected account import",
        "count": 1,
        "metadata": {},
        "failedReason": None,
        "failedAt": None,
        "failedMessage": None,
        "createdAt": now,
        "updatedAt": now,
    }
    return {
        "id": webset_id,
        "object": "webset",
        "status": status,
        "externalId": request.external_id,
        "title": "E1 targeted enrichment",
        "searches": [],
        "imports": [imported],
        "enrichments": definitions,
        "monitors": [],
        "excludes": [],
        "metadata": request.metadata,
        "dashboardUrl": f"https://websets.exa.ai/websets/{webset_id}",
        "createdAt": now,
        "updatedAt": now,
        "_targetUrl": target_url,
    }


def _webset_exchange(payload: dict[str, object], *, status_code: int) -> ExaWebsetExchange:
    provider = dict(payload)
    provider.pop("_targetUrl", None)
    body = json.dumps(provider, sort_keys=True).encode()
    return ExaWebsetExchange(
        status_code=status_code,
        request_id="req_e1_webset",
        response_body=body,
        webset=ExaWebset.model_validate(provider),
    )


class _ImportTransport:
    def __init__(self, *, target_url: str, resolved_url: str | None = None) -> None:
        self.target_url = target_url
        self.resolved_url = resolved_url or target_url
        self.import_calls = 0
        self.upload_calls = 0
        self.create_calls = 0
        self.lookup_calls = 0
        self.poll_calls = 0
        self.item_page_calls = 0
        self.import_request: ExaCreateImportRequest | None = None
        self.webset_request: ExaCreateWebsetRequest | None = None
        self.uploaded: bytes | None = None

    async def create_import(self, request: ExaCreateImportRequest) -> ExaImportExchange:
        self.import_calls += 1
        self.import_request = request
        payload = _import_payload(request)
        return ExaImportExchange(
            status_code=201,
            request_id="req_e1_import",
            response=ExaCreateImportResponse.model_validate(payload),
        )

    async def upload_import_csv(self, *, upload_url: SecretStr, content: bytes) -> None:
        self.upload_calls += 1
        assert "must-not-persist" in upload_url.get_secret_value()
        self.uploaded = content

    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange:
        self.create_calls += 1
        self.webset_request = request
        return _webset_exchange(
            _webset_payload(
                request,
                status="running",
                import_status="processing",
                target_url=self.target_url,
            ),
            status_code=201,
        )

    async def get_webset(self, webset_id_or_external_id: str) -> ExaWebsetExchange:
        self.lookup_calls += 1
        assert self.webset_request is not None
        assert webset_id_or_external_id in {
            self.webset_request.external_id,
            "webset_e1",
        }
        return await self.create_webset(self.webset_request)

    async def poll_webset(self, webset_id: str) -> ExaWebsetExchange:
        self.poll_calls += 1
        assert webset_id == "webset_e1"
        assert self.webset_request is not None
        return _webset_exchange(
            _webset_payload(
                self.webset_request,
                status="idle",
                import_status="completed",
                target_url=self.target_url,
            ),
            status_code=200,
        )

    async def list_items(
        self, webset_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> ExaItemPageExchange:
        self.item_page_calls += 1
        assert webset_id == "webset_e1" and cursor is None and limit == 100
        assert self.webset_request is not None
        now = datetime.now(UTC).isoformat()
        results = []
        for index, enrichment in enumerate(self.webset_request.enrichments):
            field_key = enrichment.metadata["clueFieldKey"]
            assert enrichment.format is not None
            results.append(
                {
                    "object": "enrichment_result",
                    "status": "completed",
                    "format": enrichment.format.value,
                    "result": ["10m_50m"] if field_key == "core.revenue_band" else None,
                    "reasoning": "Public company sources were checked.",
                    "references": [
                        {
                            "title": "Company site",
                            "snippet": "Firmographic information",
                            "url": self.target_url,
                        }
                    ],
                    "enrichmentId": f"enrichment_e1_{index}",
                }
            )
        item = {
            "id": "item_e1",
            "object": "webset_item",
            "source": "import",
            "sourceId": "import_e1",
            "sourceEntityId": self.target_url,
            "scopeId": None,
            "websetId": "webset_e1",
            "properties": {
                "type": "company",
                "url": self.resolved_url,
                "description": "Selected specialty practice",
                "content": None,
                "company": {
                    "name": "Insight Health AI",
                    "location": "United States",
                    "employees": 20,
                    "industry": "Healthcare AI",
                    "about": "AI phone agents for specialty practices.",
                    "logoUrl": None,
                    "foundedYear": None,
                    "headquarters": None,
                    "financials": None,
                    "webTraffic": None,
                },
            },
            "evaluations": [],
            "enrichments": results,
            "createdAt": now,
            "updatedAt": now,
        }
        body = json.dumps({"data": [item], "hasMore": False, "nextCursor": None}).encode()
        return ExaItemPageExchange(
            status_code=200,
            request_id="req_e1_items",
            response_body=body,
            page=json.loads(body),
        )


class _BlockingImportTransport(_ImportTransport):
    """Pause after the durable dispatch claim so a concurrent starter can join it."""

    def __init__(self, *, target_url: str) -> None:
        super().__init__(target_url=target_url)
        self.import_entered = asyncio.Event()
        self.import_release = asyncio.Event()

    async def create_import(self, request: ExaCreateImportRequest) -> ExaImportExchange:
        self.import_calls += 1
        self.import_request = request
        self.import_entered.set()
        await self.import_release.wait()
        return ExaImportExchange(
            status_code=201,
            request_id="req_e1_import",
            response=ExaCreateImportResponse.model_validate(_import_payload(request)),
        )


def _fields() -> tuple[TargetedEnrichmentFieldPlan, ...]:
    return (
        TargetedEnrichmentFieldPlan(
            field_key="core.company_linkedin_url",
            description="Find the official LinkedIn company URL.",
            format=DiscoveryEnrichmentFormat.URL,
        ),
        TargetedEnrichmentFieldPlan(
            field_key="core.revenue_band",
            description="Select the best supported annual revenue band.",
            format=DiscoveryEnrichmentFormat.OPTIONS,
            options=REVENUE_BAND_OPTIONS,
        ),
    )


def test_import_request_is_import_only_and_presigned_url_is_secret() -> None:
    request = ExaCreateImportRequest(
        size=26,
        count=1,
        entity=ExaWebsetEntity(type=ExaWebsetEntityType.COMPANY),
        title="Selected account",
    )
    exchange = ExaImportExchange(
        status_code=201,
        response=ExaCreateImportResponse.model_validate(_import_payload(request)),
    )
    assert "must-not-persist" not in repr(exchange)
    sanitized = exchange.response.sanitized_bytes()
    assert b"must-not-persist" not in sanitized
    assert b"REDACTED_PRESIGNED_URL" in sanitized


def test_e1_real_db_import_cost_materialization_and_zero_call_replay(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = "ws-e1-targeted"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            ready = await _complete_batch(conn, storage, started=started)
            seal = await seal_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=ready.draft,
            )
            tier = stamp_reuse(
                account_claim(
                    entity_id=EntityId(ready.account_id),
                    field_key=TIER_FIELD,
                    value_json={
                        "tier": "high",
                        "decision_basis": "discovery_criteria",
                        "selection_policy_version": "discovery-selection-v1",
                        "decision_version": "e1-test-decision",
                        "cutoff_version": "e1-test-decision",
                        "discovery_batch_id": str(started.batch_id),
                        "discovery_seal_sha256": seal.seal_sha256,
                        "project_run_id": str(started.project_run_id),
                        "disposition": "selected",
                        "evidence_claim_ids": [],
                        "icp_key": "independent-specialty-practices",
                        "icp_version": 1,
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=1,
                    run_id=RunId(started.project_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                ),
                workspace_id=workspace_id,
            )
            await insert_claim(conn, tier)
            original = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert original is not None
            original_charge = original.provider_units_charged

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            preflight = await compile_exa_targeted_preflight(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_ids=[EntityId(ready.account_id)],
                fields=_fields(),
                observation_window="2026-08-03",
                storage=storage,
                conn_factory=same_connection,
            )
            assert preflight.maximum_provider_credits == Decimal("6")
            assert preflight.maximum_cost_cents == Decimal("2.694")
            assert preflight.csv_bytes == b"url\nhttps://insighthealth.ai/\n"
            assert build_exa_import_request(preflight).size == len(preflight.csv_bytes)

            transport = _BlockingImportTransport(target_url="https://insighthealth.ai/")
            coordinator = ExaTargetedEnrichmentCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
                poll_after_seconds=1,
            )
            first_start = asyncio.create_task(coordinator.start(preflight))
            await transport.import_entered.wait()
            concurrent = await coordinator.start(preflight)
            assert concurrent.outcome is ExaTargetedOutcome.JOINED_IN_FLIGHT
            assert transport.import_calls == 1
            transport.import_release.set()
            started_result = await first_start
            assert started_result.outcome is ExaTargetedOutcome.CREATED
            assert (transport.import_calls, transport.upload_calls, transport.create_calls) == (
                1,
                1,
                1,
            )
            assert transport.uploaded == preflight.csv_bytes
            assert transport.webset_request is not None
            assert transport.webset_request.search is None
            assert len(transport.webset_request.imports) == 1
            assert (
                build_exa_import_webset_request(preflight.request, import_id="import_e1")
                == transport.webset_request
            )
            submitted_artifacts = await list_targeted_enrichment_artifacts(
                conn,
                workspace_id=workspace_id,
                operation_id=started_result.operation.operation_id,
            )
            create_artifact = next(
                artifact
                for artifact in submitted_artifacts
                if artifact.artifact_kind == "webset_create"
            )
            same_bytes_other_event = await append_targeted_enrichment_artifact(
                conn,
                workspace_id=workspace_id,
                operation_id=started_result.operation.operation_id,
                artifact_kind="same_bytes_other_lifecycle_event",
                artifact_key=create_artifact.artifact_key,
                content_sha256=create_artifact.content_sha256,
                provider_request_id="req_e1_same_body_different_event",
            )
            assert same_bytes_other_event.ordinal != create_artifact.ordinal
            assert (
                await append_targeted_enrichment_artifact(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=started_result.operation.operation_id,
                    artifact_kind="same_bytes_other_lifecycle_event",
                    artifact_key=create_artifact.artifact_key,
                    content_sha256=create_artifact.content_sha256,
                    provider_request_id="req_e1_same_body_different_event",
                )
                == same_bytes_other_event
            )

            completed = await coordinator.drive_once(
                workspace_id=workspace_id,
                operation_id=started_result.operation.operation_id,
            )
            assert completed.outcome is ExaTargetedOutcome.SUCCEEDED
            assert completed.operation.provider_units_charged == Decimal("6")
            assert completed.operation.cost_cents_charged == Decimal("2.694")
            assert completed.claims_created == 1
            assert completed.resolved_fields == 1
            assert completed.missing_fields == 1
            results = await list_targeted_enrichment_field_results(
                conn,
                workspace_id=workspace_id,
                operation_id=completed.operation.operation_id,
            )
            assert [result.state.value for result in results] == [
                "confirmed_missing",
                "resolved",
            ]
            terminal_write = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="field outcome is immutable"):
                await conn.execute(
                    text(
                        "UPDATE targeted_enrichment_field_result "
                        "SET reason_code='late_mutation' "
                        "WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": completed.operation.operation_id},
                )
            await terminal_write.rollback()
            receipt = json.loads(await storage.get(completed.operation.final_receipt_ref or ""))
            assert receipt["matching_search_results"] == 0
            assert receipt["search_credits"] == "0"
            assert receipt["import_credits"] == "2"
            assert receipt["ordinary_enrichment_credits"] == "4"

            after = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=started.batch_id
            )
            assert after is not None
            assert after.provider_units_charged == original_charge
            assert after.state.value == "sealed"

            artifacts = await list_targeted_enrichment_artifacts(
                conn,
                workspace_id=workspace_id,
                operation_id=completed.operation.operation_id,
            )
            sanitized = next(
                artifact
                for artifact in artifacts
                if artifact.artifact_kind == "import_create_sanitized"
            )
            assert b"must-not-persist" not in await storage.get(sanitized.artifact_key)

            calls = (
                transport.import_calls,
                transport.upload_calls,
                transport.create_calls,
                transport.lookup_calls,
                transport.poll_calls,
                transport.item_page_calls,
            )
            restarted = ExaTargetedEnrichmentCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
            )
            replay = await restarted.start(preflight)
            assert replay.outcome is ExaTargetedOutcome.REPLAYED
            assert (
                transport.import_calls,
                transport.upload_calls,
                transport.create_calls,
                transport.lookup_calls,
                transport.poll_calls,
                transport.item_page_calls,
            ) == calls
            scope = WorkspaceScope.for_workspace(workspace_id)
            revenue_claims = await claims_for(
                conn, EntityId(ready.account_id), "core.revenue_band", scope=scope
            )
            assert len(revenue_claims) == 1
            stored = await get_targeted_enrichment_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=completed.operation.operation_id,
            )
            assert stored == completed.operation

    run_async(scenario())


def test_paid_item_resolving_another_domain_fails_closed_without_claim(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = "ws-e1-provider-identity-drift"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            ready = await _complete_batch(conn, storage, started=started)
            seal = await seal_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=ready.draft,
            )
            tier = stamp_reuse(
                account_claim(
                    entity_id=EntityId(ready.account_id),
                    field_key=TIER_FIELD,
                    value_json={
                        "tier": "high",
                        "decision_basis": "discovery_criteria",
                        "selection_policy_version": "discovery-selection-v1",
                        "decision_version": "human-approved-drift-test",
                        "cutoff_version": "human-approved-drift-test",
                        "discovery_batch_id": str(started.batch_id),
                        "discovery_seal_sha256": seal.seal_sha256,
                        "project_run_id": str(started.project_run_id),
                        "disposition": "selected",
                        "evidence_claim_ids": [],
                        "icp_key": "independent-specialty-practices",
                        "icp_version": 1,
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=1,
                    run_id=RunId(started.project_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                ),
                workspace_id=workspace_id,
            )
            await insert_claim(conn, tier)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            preflight = await compile_exa_targeted_preflight(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_ids=[EntityId(ready.account_id)],
                fields=_fields(),
                observation_window="2026-08-03-domain-drift",
                storage=storage,
                conn_factory=same_connection,
            )
            transport = _ImportTransport(
                target_url="https://insighthealth.ai/",
                resolved_url="https://unrelated-company.example/",
            )
            coordinator = ExaTargetedEnrichmentCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
            )
            submitted = await coordinator.start(preflight)
            result = await coordinator.drive_once(
                workspace_id=workspace_id,
                operation_id=submitted.operation.operation_id,
            )
            assert result.outcome is ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN
            assert result.operation.state.value == "spend_outcome_unknown"
            assert result.operation.spend_outcome.value == "unknown"
            fields = await list_targeted_enrichment_field_results(
                conn,
                workspace_id=workspace_id,
                operation_id=submitted.operation.operation_id,
            )
            assert {field.state.value for field in fields} == {"pending"}
            scope = WorkspaceScope.for_workspace(workspace_id)
            linkedin = await claims_for(
                conn,
                EntityId(ready.account_id),
                "core.company_linkedin_url",
                scope=scope,
            )
            assert linkedin == []

    run_async(scenario())


def test_preflight_rejects_non_selected_account_before_provider_work(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = "ws-e1-hold-rejected"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started = await _start_batch(conn, storage, workspace_id=workspace_id)
            ready = await _complete_batch(conn, storage, started=started)
            seal = await seal_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=started.batch_id,
                draft=ready.draft,
            )
            machine_tier = stamp_reuse(
                account_claim(
                    entity_id=EntityId(ready.account_id),
                    field_key=TIER_FIELD,
                    value_json={
                        "tier": "high",
                        "decision_basis": "discovery_criteria",
                        "selection_policy_version": "discovery-selection-v1",
                        "decision_version": "machine-only",
                        "cutoff_version": "machine-only",
                        "discovery_batch_id": str(started.batch_id),
                        "discovery_seal_sha256": seal.seal_sha256,
                        "project_run_id": str(started.project_run_id),
                        "disposition": "selected",
                        "evidence_claim_ids": [],
                        "icp_key": "independent-specialty-practices",
                        "icp_version": 1,
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=1,
                    run_id=RunId(started.project_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="https://insighthealth.ai/",
                    evidence_span="Machine selection is not human checkpoint approval.",
                ),
                workspace_id=workspace_id,
            )
            await insert_claim(conn, machine_tier)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            with pytest.raises(ExaTargetedEligibilityError, match="human-selected"):
                await compile_exa_targeted_preflight(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_ids=[EntityId(ready.account_id)],
                    fields=_fields(),
                    observation_window="2026-08-03",
                    storage=storage,
                    conn_factory=same_connection,
                )
            count = (
                await conn.execute(text("SELECT count(*) FROM targeted_enrichment_operation"))
            ).scalar_one()
            assert count == 0

    run_async(scenario())
