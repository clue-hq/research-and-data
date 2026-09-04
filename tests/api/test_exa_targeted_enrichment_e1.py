"""E1 import-only targeted enrichment: contract, durability, costs, and replay."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_targeted_enrichment import (
    DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY,
    ExaTargetedEligibilityError,
    ExaTargetedEnrichmentCoordinator,
    ExaTargetedEnrichmentStarter,
    ExaTargetedEnrichmentWorker,
    ExaTargetedOutcome,
    ExaTargetedResult,
    build_exa_import_request,
    build_exa_import_webset_request,
    compile_exa_targeted_preflight,
)
from clue_core import (
    DiscoveryEnrichmentFormat,
    EntityId,
    ExtractionMethod,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    RunId,
    TargetedEnrichmentFieldPlan,
    TargetedEnrichmentOperationId,
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
    PhaseCheckpointStatus,
    TargetedEnrichmentBudgetExceeded,
    append_targeted_enrichment_artifact,
    enumerate_discovery_subject_artifacts,
    get_discovery_batch,
    get_targeted_enrichment_operation,
    list_targeted_enrichment_artifacts,
    list_targeted_enrichment_field_results,
    seal_discovery_batch,
    tombstone_discovery_subject_artifacts,
    upsert_checkpoint,
)
from clue_research.identity import insert_account_entity, stamp_reuse
from clue_storage import FsStorage
from tests._run_lineage import assert_written_claims_are_attributable
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import _complete_batch, _start_batch

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _advance_sealed_run_to_deep(conn: AsyncConnection, project_run_id: ProjectRunId) -> None:
    seal = (
        (
            await conn.execute(
                text(
                    "SELECT batch_id, seal_sha256 FROM discovery_batch_seal "
                    "WHERE project_run_id=:project_run_id"
                ),
                {"project_run_id": project_run_id},
            )
        )
        .mappings()
        .one()
    )
    await upsert_checkpoint(
        conn,
        project_run_id=project_run_id,
        phase=ProjectPhase.DISCOVERY,
        idempotency_key=f"e1-discovery-seal:{project_run_id}",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={
            "discovery_batch_id": str(seal["batch_id"]),
            "discovery_batch_seal_ref": str(seal["seal_sha256"]),
        },
    )
    await conn.execute(
        text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
        {"project_run_id": project_run_id},
    )
    await upsert_checkpoint(
        conn,
        project_run_id=project_run_id,
        phase=ProjectPhase.SCORING,
        idempotency_key=f"e1-scoring-bypass:{project_run_id}",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={"scoring_mode": "disabled", "numeric_scores_written": 0},
    )
    await conn.execute(
        text("UPDATE project_run SET phase='tier_checkpoint' WHERE id=:project_run_id"),
        {"project_run_id": project_run_id},
    )
    await upsert_checkpoint(
        conn,
        project_run_id=project_run_id,
        phase=ProjectPhase.TIER_CHECKPOINT,
        idempotency_key=f"e1-tier-approval:{project_run_id}",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={"checkpoint_status": "resumed", "decision_action": "approve"},
    )
    await conn.execute(
        text("UPDATE project_run SET phase='deep' WHERE id=:project_run_id"),
        {"project_run_id": project_run_id},
    )


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


class _CapturingCoordinator(ExaTargetedEnrichmentCoordinator):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.last_result: ExaTargetedResult | None = None

    async def drive_once(
        self, *, workspace_id: str, operation_id: TargetedEnrichmentOperationId
    ) -> ExaTargetedResult:
        self.last_result = await super().drive_once(
            workspace_id=workspace_id, operation_id=operation_id
        )
        return self.last_result


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
            await _advance_sealed_run_to_deep(conn, ProjectRunId(started.project_run_id))
            tier = stamp_reuse(
                account_claim(
                    entity_id=EntityId(ready.account_id),
                    field_key=TIER_FIELD,
                    value_json={
                        "tier": "tier4",
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
                    source_tier=4,
                    extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                    source_url="https://example.com/tier-decision",
                    evidence_span="Tier-4 source supports this exact selected account tier.",
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
                observation_window=(
                    f"project-run:{started.project_run_id}:targeted:"
                    f"{DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY.version}"
                ),
                storage=storage,
                conn_factory=same_connection,
            )
            assert preflight.maximum_provider_credits == Decimal("6")
            assert preflight.maximum_cost_cents == Decimal("2.694")
            assert preflight.csv_bytes == b"url\nhttps://insighthealth.ai/\n"
            assert build_exa_import_request(preflight).size == len(preflight.csv_bytes)
            spent_before_e1 = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:project_run_id"),
                        {"project_run_id": started.project_run_id},
                    )
                ).scalar_one()
            )

            transport = _BlockingImportTransport(target_url="https://insighthealth.ai/")

            @asynccontextmanager
            async def transport_factory() -> AsyncIterator[_BlockingImportTransport]:
                yield transport

            # M8D R1/R10 retired the `enrich_selected_accounts@1` tool address (exact-replay-only;
            # the refusal itself is pinned by the toolbelt matrix). The preserved E1 engine —
            # starter, coordinator, snapshots, spend — is exercised directly here.
            starter = ExaTargetedEnrichmentStarter(
                transport_factory=transport_factory,
                storage=storage,
                conn_factory=same_connection,
            )
            start_kwargs: dict[str, Any] = {
                "workspace_id": workspace_id,
                "project_run_id": started.project_run_id,
                "account_ids": (EntityId(ready.account_id),),
                "field_keys": (
                    "core.company_linkedin_url",
                    "core.revenue_band",
                ),
            }
            coordinator = _CapturingCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
                poll_after_seconds=1,
            )
            first_start = asyncio.create_task(starter.start(**start_kwargs))
            # Race the dispatch entry against the start task so an early refusal surfaces as a
            # test failure instead of parking the suite on an event nobody will ever set (the
            # exact shape of the R10 full-suite hang this rewrite fixes).
            entered = asyncio.create_task(transport.import_entered.wait())
            done, _pending = await asyncio.wait(
                {first_start, entered},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if first_start in done and not entered.done():
                entered.cancel()
                raise AssertionError(
                    "E1 start settled before dispatching: "
                    f"{first_start.exception() or first_start.result()!r}"
                )
            concurrent = await starter.start(**start_kwargs)
            assert concurrent.outcome is ExaTargetedOutcome.JOINED_IN_FLIGHT
            assert transport.import_calls == 1
            transport.import_release.set()
            started_result = await first_start
            assert started_result.outcome is ExaTargetedOutcome.CREATED
            operation_id = started_result.operation.operation_id
            started_operation = await get_targeted_enrichment_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )
            assert started_operation is not None
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
            wrong_field_claim = stamp_reuse(
                account_claim(
                    entity_id=EntityId(ready.account_id),
                    field_key="core.company_email",
                    value_json="contact@insighthealth.ai",
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=1,
                    run_id=RunId(started.project_run_id),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                ),
                workspace_id=workspace_id,
            )
            wrong_field_claim_id = await insert_claim(conn, wrong_field_claim)
            other_account_id = await insert_account_entity(
                conn,
                canonical_name="Other Account",
                primary_domain="other-account.example",
                workspace_id=workspace_id,
            )
            wrong_tier_savepoint = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="tier claim must be live and match"):
                await conn.execute(
                    text(
                        "INSERT INTO targeted_enrichment_target ("
                        "operation_id, workspace_id, account_id, identifier_url, "
                        "tier_claim_id, ordinal) VALUES ("
                        ":operation_id, :workspace_id, :account_id, :url, :wrong_claim, 1)"
                    ),
                    {
                        "wrong_claim": wrong_field_claim_id,
                        "operation_id": started_operation.operation_id,
                        "workspace_id": workspace_id,
                        "account_id": other_account_id,
                        "url": "https://other-account.example/",
                    },
                )
            await wrong_tier_savepoint.rollback()

            wrong_result_savepoint = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="result claim must match"):
                await conn.execute(
                    text(
                        "UPDATE targeted_enrichment_field_result SET claim_id=:wrong_claim "
                        "WHERE operation_id=:operation_id "
                        "AND field_key='core.company_linkedin_url'"
                    ),
                    {
                        "wrong_claim": wrong_field_claim_id,
                        "operation_id": started_operation.operation_id,
                    },
                )
            await wrong_result_savepoint.rollback()
            submitted_artifacts = await list_targeted_enrichment_artifacts(
                conn,
                workspace_id=workspace_id,
                operation_id=started_operation.operation_id,
            )
            create_artifact = next(
                artifact
                for artifact in submitted_artifacts
                if artifact.artifact_kind == "webset_create"
            )
            same_bytes_other_event = await append_targeted_enrichment_artifact(
                conn,
                workspace_id=workspace_id,
                operation_id=started_operation.operation_id,
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
                    operation_id=started_operation.operation_id,
                    artifact_kind="same_bytes_other_lifecycle_event",
                    artifact_key=create_artifact.artifact_key,
                    content_sha256=create_artifact.content_sha256,
                    provider_request_id="req_e1_same_body_different_event",
                )
                == same_bytes_other_event
            )

            await conn.execute(
                text(
                    "UPDATE targeted_enrichment_operation "
                    "SET next_poll_at=now() - interval '1 second' "
                    "WHERE id=:operation_id"
                ),
                {"operation_id": started_operation.operation_id},
            )
            worker = ExaTargetedEnrichmentWorker(
                coordinator=coordinator,
                conn_factory=same_connection,
            )
            assert await worker.run_due() == 1
            completed = coordinator.last_result
            assert completed is not None
            assert completed.outcome is ExaTargetedOutcome.SUCCEEDED
            assert completed.operation.provider_units_charged == Decimal("6")
            assert completed.operation.cost_cents_charged == Decimal("2.694")
            spent_after_e1 = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:project_run_id"),
                        {"project_run_id": started.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_after_e1 == spent_before_e1 + Decimal("2.694")
            assert completed.claims_created == 1
            assert completed.resolved_fields == 1
            assert completed.missing_fields == 1
            # FI-2 P2: enrichment claims carry the project run as their run_id, and that run is
            # registered so the project lens can back-join them.
            await assert_written_claims_are_attributable(
                conn,
                started.project_run_id,
                kind="enrichment",
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=started.project_run_id,
            )
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
            terminal_operation_write = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="terminal targeted enrichment operation"):
                await conn.execute(
                    text(
                        "UPDATE targeted_enrichment_operation "
                        "SET state='waiting_external', provider_units_charged=0, "
                        "cost_cents_charged=0, final_receipt_ref=NULL, "
                        "raw_response_manifest_key=NULL, terminal_at=NULL "
                        "WHERE id=:operation_id"
                    ),
                    {"operation_id": completed.operation.operation_id},
                )
            await terminal_operation_write.rollback()
            receipt = json.loads(await storage.get(completed.operation.final_receipt_ref or ""))
            assert receipt["matching_search_results"] == 0
            assert receipt["search_credits"] == "0"
            assert receipt["import_credits"] == "2"
            assert receipt["ordinary_enrichment_credits"] == "4"
            assert receipt["cost_semantics"] == "subscription-credit-allocation-equivalent"
            assert (
                receipt["settlement_method"] == "public-credit-rules-applied-to-terminal-item-facts"
            )

            subject_artifacts = (
                (
                    await conn.execute(
                        text(
                            "SELECT reference_kind, artifact_key FROM discovery_artifact_subject "
                            "WHERE workspace_id=:workspace_id "
                            "AND subject_kind='account' AND subject_entity_id=:account_id "
                            "AND reference_kind LIKE 'targeted_enrichment_%' "
                            "AND tombstoned_at IS NULL"
                        ),
                        {"workspace_id": workspace_id, "account_id": ready.account_id},
                    )
                )
                .mappings()
                .all()
            )
            by_kind = {
                str(row["reference_kind"]): str(row["artifact_key"]) for row in subject_artifacts
            }
            assert by_kind["targeted_enrichment_request"] == completed.operation.input_artifact_key
            assert by_kind["targeted_enrichment_csv"] == completed.operation.csv_artifact_key
            assert (
                by_kind["targeted_enrichment_final_receipt"]
                == completed.operation.final_receipt_ref
            )
            assert (
                by_kind["targeted_enrichment_manifest"]
                == completed.operation.raw_response_manifest_key
            )
            enumerated = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=EntityId(ready.account_id),
            )
            assert {
                row.reference_kind
                for row in enumerated
                if row.reference_kind.startswith("targeted_enrichment_")
            } >= {
                "targeted_enrichment_request",
                "targeted_enrichment_csv",
                "targeted_enrichment_item",
                "targeted_enrichment_final_receipt",
                "targeted_enrichment_manifest",
            }

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
                Decimal(
                    (
                        await conn.execute(
                            text("SELECT spent_cents FROM project_run WHERE id=:project_run_id"),
                            {"project_run_id": started.project_run_id},
                        )
                    ).scalar_one()
                )
                == spent_after_e1
            )
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

            # A differently bundled request cannot repurchase a field already covered in the same
            # stable observation window. The database rejects it before any provider dispatch.
            overlapping = await compile_exa_targeted_preflight(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_ids=[EntityId(ready.account_id)],
                fields=(_fields()[0],),
                observation_window=preflight.request.observation_window,
                storage=storage,
                conn_factory=same_connection,
            )
            overlap_transport = _ImportTransport(target_url="https://insighthealth.ai/")
            overlap_coordinator = ExaTargetedEnrichmentCoordinator(
                transport=overlap_transport,
                storage=storage,
                conn_factory=same_connection,
            )
            overlap_savepoint = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="already reserved in this observation window"):
                await overlap_coordinator.start(overlapping)
            await overlap_savepoint.rollback()
            assert overlap_transport.import_calls == 0

            # The shared project cap includes settled spend and rejects a new observation window
            # before import creation/upload/Webset creation.
            await conn.execute(
                text("UPDATE project_run SET budget_cap_cents=:cap WHERE id=:project_run_id"),
                {"cap": spent_after_e1, "project_run_id": started.project_run_id},
            )
            over_budget = await compile_exa_targeted_preflight(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_ids=[EntityId(ready.account_id)],
                fields=(_fields()[0],),
                observation_window="2026-08-04",
                storage=storage,
                conn_factory=same_connection,
            )
            budget_transport = _ImportTransport(target_url="https://insighthealth.ai/")
            with pytest.raises(TargetedEnrichmentBudgetExceeded, match="project-run cap"):
                await ExaTargetedEnrichmentCoordinator(
                    transport=budget_transport,
                    storage=storage,
                    conn_factory=same_connection,
                ).start(over_budget)
            assert budget_transport.import_calls == 0

            # Paused runs cannot compile fresh paid work, even if all account eligibility evidence
            # remains present. Existing accepted operations still drain through the worker path.
            paused_savepoint = await conn.begin_nested()
            await conn.execute(
                text("UPDATE project_run SET status='paused' WHERE id=:project_run_id"),
                {"project_run_id": started.project_run_id},
            )
            with pytest.raises(ExaTargetedEligibilityError, match="active project run in deep"):
                await compile_exa_targeted_preflight(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_ids=[EntityId(ready.account_id)],
                    fields=(_fields()[0],),
                    observation_window="2026-08-05",
                    storage=storage,
                    conn_factory=same_connection,
                )
            await paused_savepoint.rollback()

            # The subject index makes every E1 artifact reachable by DSAR. A terminal production
            # retry after tombstoning is a DB-only replay: it neither resurrects the serving edges
            # nor recaptures bytes or invokes Exa.
            await tombstone_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=EntityId(ready.account_id),
            )
            assert (
                await enumerate_discovery_subject_artifacts(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind="account",
                    subject_entity_id=EntityId(ready.account_id),
                )
                == ()
            )
            calls_before_erased_replay = (
                transport.import_calls,
                transport.upload_calls,
                transport.create_calls,
                transport.lookup_calls,
                transport.poll_calls,
                transport.item_page_calls,
            )
            erased_replay = await restarted.start(preflight)
            assert erased_replay.outcome is ExaTargetedOutcome.REPLAYED
            with pytest.raises(ExaTargetedEligibilityError, match="intact sealed discovery"):
                await starter.start(**start_kwargs)
            assert (
                transport.import_calls,
                transport.upload_calls,
                transport.create_calls,
                transport.lookup_calls,
                transport.poll_calls,
                transport.item_page_calls,
            ) == calls_before_erased_replay
            assert (
                await enumerate_discovery_subject_artifacts(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind="account",
                    subject_entity_id=EntityId(ready.account_id),
                )
                == ()
            )

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
            await _advance_sealed_run_to_deep(conn, ProjectRunId(started.project_run_id))
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
            calls = (
                transport.import_calls,
                transport.upload_calls,
                transport.create_calls,
                transport.lookup_calls,
                transport.poll_calls,
                transport.item_page_calls,
            )
            quarantined_replay = await coordinator.start(preflight)
            assert quarantined_replay.outcome is ExaTargetedOutcome.SPEND_OUTCOME_UNKNOWN
            assert quarantined_replay.operation == result.operation
            assert (
                transport.import_calls,
                transport.upload_calls,
                transport.create_calls,
                transport.lookup_calls,
                transport.poll_calls,
                transport.item_page_calls,
            ) == calls

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
            await _advance_sealed_run_to_deep(conn, ProjectRunId(started.project_run_id))
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
                        "disposition": "held",
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
                    evidence_span="This account was held rather than selected.",
                ),
                workspace_id=workspace_id,
            )
            await insert_claim(conn, machine_tier)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            with pytest.raises(ExaTargetedEligibilityError, match="selected tier decision"):
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
