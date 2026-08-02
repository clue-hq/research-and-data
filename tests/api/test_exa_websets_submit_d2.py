"""D2 durable Exa submit integration against real Postgres and filesystem storage."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_websets_submit import (
    DurableExaWebsetSubmitter,
    ExaSubmitOutcome,
)
from clue_core import (
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryCriterionPlan,
    DiscoveryEntityKind,
    DiscoveryPlan,
    DiscoverySearchPlan,
    ICPCreatedFrom,
    ProjectPhase,
    new_discovery_batch_id,
    new_discovery_plan_id,
    new_project_run_id,
)
from clue_db import db_lifespan
from clue_obs.otel import collect_spans
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_CONTRACT_VERSION,
    ExaCreateWebsetRequest,
    ExaWebsetDuplicateExternalId,
    ExaWebsetExchange,
    ExaWebsetsAuthenticationError,
    ExaWebsetsPreDispatchError,
)
from clue_research.claimstore import load_core_pack
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.durable import (
    DiscoveryBudgetExceeded,
    create_discovery_batch,
    ensure_project_run,
    get_discovery_batch,
    get_discovery_operation,
    put_discovery_plan,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.icp import create_icp_spec
from clue_storage import FsStorage
from tests._workspace import seed_project
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")


@asynccontextmanager
async def rollback_conn(*, seed_pack: bool = True) -> AsyncIterator[AsyncConnection]:
    async with db_lifespan() as engine:
        conn = await engine.connect()
        outer = await conn.begin()
        try:
            if seed_pack:
                await load_core_pack(conn)
            yield conn
        finally:
            await outer.rollback()
            await conn.close()


def _response_payload(request: ExaCreateWebsetRequest) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    enrichments = [
        {
            "id": f"enrichment_{index}",
            "object": "webset_enrichment",
            "status": "pending",
            "websetId": "webset_d2_integration",
            "title": None,
            "description": item.description,
            "format": item.format.value if item.format else None,
            "options": [option.model_dump() for option in item.options] or None,
            "instructions": None,
            "metadata": item.metadata,
            "createdAt": now,
            "updatedAt": now,
        }
        for index, item in enumerate(request.enrichments)
    ]
    return {
        "id": "webset_d2_integration",
        "object": "webset",
        "status": "running",
        "externalId": request.external_id,
        "title": "D2 integration",
        "searches": [
            {
                "id": "search_d2_integration",
                "object": "webset_search",
                "websetId": "webset_d2_integration",
                "status": "running",
                "query": request.search.query,
                "entity": request.search.entity.model_dump(exclude_none=True)
                if request.search.entity
                else None,
                "criteria": [
                    {"description": item.description, "successRate": 0}
                    for item in request.search.criteria
                ],
                "count": request.search.count,
                "maxPeoplePerCompany": request.search.max_people_per_company,
                "behavior": "override",
                "exclude": [],
                "scope": [],
                "progress": {"found": 0, "analyzed": 0, "completion": 0, "timeLeft": None},
                "recall": None,
                "metadata": {},
                "canceledAt": None,
                "canceledReason": None,
                "createdAt": now,
                "updatedAt": now,
            }
        ],
        "imports": [],
        "enrichments": enrichments,
        "monitors": [],
        "excludes": [],
        "metadata": request.metadata,
        "dashboardUrl": "https://websets.exa.ai/websets/webset_d2_integration",
        "createdAt": now,
        "updatedAt": now,
    }


def _exchange(request: ExaCreateWebsetRequest, *, status_code: int = 201) -> ExaWebsetExchange:
    body = json.dumps(_response_payload(request), sort_keys=True).encode()
    return ExaWebsetExchange(
        status_code=status_code,
        request_id="req_d2_integration",
        response_body=body,
        webset=json.loads(body),
    )


class _RecordingTransport:
    def __init__(self, *, mode: str = "success") -> None:
        self.mode = mode
        self.create_calls = 0
        self.lookup_calls = 0
        self.request: ExaCreateWebsetRequest | None = None

    async def create_webset(self, request: ExaCreateWebsetRequest) -> ExaWebsetExchange:
        self.create_calls += 1
        self.request = request
        if self.mode == "predispatch":
            raise ExaWebsetsPreDispatchError("connection unavailable")
        if self.mode == "authentication":
            raise ExaWebsetsAuthenticationError(
                "authentication failed",
                status_code=401,
                request_id="req_authentication",
                response_body=b'{"error":"Unauthorized"}',
            )
        if self.mode == "duplicate":
            raise ExaWebsetDuplicateExternalId(
                "duplicate",
                status_code=409,
                request_id="req_duplicate",
                response_body=b'{"error":"duplicate","tag":"external_id_conflict"}',
            )
        return _exchange(request)

    async def get_webset(self, webset_id_or_external_id: str) -> ExaWebsetExchange:
        del webset_id_or_external_id
        self.lookup_calls += 1
        assert self.request is not None
        return _exchange(self.request, status_code=200)


async def _start_batch(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    provider_credit_cap: int = 20,
) -> tuple[DiscoveryPlan, DiscoveryBatchId]:
    project = await seed_project(conn, workspace_id, name="D2 Exa submit integration")
    icp = await create_icp_spec(
        conn,
        workspace_id=workspace_id,
        icp_key="independent-neurosurgery-practices",
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
    plan = DiscoveryPlan(
        discovery_plan_id=new_discovery_plan_id(),
        plan_version=1,
        workspace_id=workspace_id,
        project_id=project.project_id,
        project_run_id=run_id,
        icp_key=icp.icp_key,
        icp_version=icp.version,
        provider_policy_version="exa-websets-public-credit-policy-2026-08-02",
        field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
        provider_contract_version=EXA_WEBSETS_CONTRACT_VERSION,
        channels=("exa_websets",),
        searches=(
            DiscoverySearchPlan(
                search_key="account-discovery",
                channel_key="exa_websets",
                normalized_query=(
                    "Independent neurosurgery and spine practices in the United States"
                ),
                entity_type=DiscoveryEntityKind.COMPANY,
                requested_count=2,
                criteria=(
                    DiscoveryCriterionPlan(
                        description="Is an independent neurosurgery or spine practice"
                    ),
                ),
            ),
        ),
        required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
        optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
        provider_credit_cap=provider_credit_cap,
        money_budget_cap_cents=Decimal("100"),
        stopping_policy={"requested_count": 2},
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
    return plan, batch_id


def test_real_db_submit_persists_receipts_costs_traces_and_restart_replay(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = "ws_d2_submit_success"
        storage = FsStorage(tmp_path / "artifacts")
        transport = _RecordingTransport()
        async with rollback_conn(seed_pack=True) as conn:
            _, batch_id = await _start_batch(conn, workspace_id=workspace_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            with collect_spans() as exporter:
                first_submitter = DurableExaWebsetSubmitter(
                    transport=transport,
                    storage=storage,
                    conn_factory=same_connection,
                )
                first = await first_submitter.submit(
                    workspace_id=workspace_id,
                    batch_id=batch_id,
                    search_key="account-discovery",
                    observation_window="2026-08-02",
                )
                # A new submitter instance represents a process restart. It has no in-memory
                # knowledge of the first call and must reuse PostgreSQL/object-storage state.
                restarted_submitter = DurableExaWebsetSubmitter(
                    transport=transport,
                    storage=storage,
                    conn_factory=same_connection,
                )
                replay = await restarted_submitter.submit(
                    workspace_id=workspace_id,
                    batch_id=batch_id,
                    search_key="account-discovery",
                    observation_window="2026-08-02",
                )

            assert first.outcome is ExaSubmitOutcome.CREATED
            assert replay.outcome is ExaSubmitOutcome.REPLAYED
            assert first.operation.operation_id == replay.operation.operation_id
            assert transport.create_calls == 1
            assert transport.lookup_calls == 0
            assert replay.create_calls == 0
            assert replay.lookup_calls == 0
            assert first.operation.provider_units_reserved == Decimal("20")
            assert first.operation.provider_units_charged == 0
            assert first.operation.submitted_receipt_ref is not None
            assert first.operation.raw_request_artifact_key is not None
            assert await storage.get(first.operation.raw_request_artifact_key) == (
                transport.request.canonical_bytes() if transport.request else b""
            )
            receipt = await storage.get(first.operation.submitted_receipt_ref)
            assert json.loads(receipt)["id"] == "webset_d2_integration"

            stored = await get_discovery_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=first.operation.operation_id,
            )
            assert stored == first.operation
            batch = await get_discovery_batch(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
            )
            assert batch is not None
            assert batch.state is DiscoveryBatchState.WAITING_EXTERNAL
            assert batch.provider_units_reserved == Decimal("20")
            assert batch.provider_units_charged == 0

            spans = exporter.get_finished_spans()
            submit_spans = [span for span in spans if span.name == "discovery.exa_websets.submit"]
            assert len(submit_spans) == 2
            first_attrs = submit_spans[0].attributes
            replay_attrs = submit_spans[1].attributes
            assert first_attrs is not None
            assert replay_attrs is not None
            assert first_attrs["provider.units_reserved"] == "20"
            assert replay_attrs["replay.hit"] == "True"

    run_async(_run())


def test_duplicate_external_id_is_looked_up_and_reconciled_once(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = "ws_d2_duplicate_reconcile"
        storage = FsStorage(tmp_path / "artifacts")
        transport = _RecordingTransport(mode="duplicate")
        async with rollback_conn(seed_pack=True) as conn:
            _, batch_id = await _start_batch(conn, workspace_id=workspace_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            result = await DurableExaWebsetSubmitter(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
            ).submit(
                workspace_id=workspace_id,
                batch_id=batch_id,
                search_key="account-discovery",
                observation_window="2026-08-02",
            )
            assert result.outcome is ExaSubmitOutcome.RECONCILED_DUPLICATE
            assert transport.create_calls == 1
            assert transport.lookup_calls == 1
            receipt = json.loads(await storage.get(result.operation.submitted_receipt_ref or ""))
            assert receipt["kind"] == "duplicate_reconciled"
            assert receipt["create"]["status"] == 409
            assert receipt["lookup"]["status"] == 200

    run_async(_run())


def test_predispatch_failure_is_retryable_on_same_operation_without_unknown_spend(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        workspace_id = "ws_d2_predispatch"
        storage = FsStorage(tmp_path / "artifacts")
        transport = _RecordingTransport(mode="predispatch")
        async with rollback_conn(seed_pack=True) as conn:
            _, batch_id = await _start_batch(conn, workspace_id=workspace_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            submitter = DurableExaWebsetSubmitter(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
            )
            first = await submitter.submit(
                workspace_id=workspace_id,
                batch_id=batch_id,
                search_key="account-discovery",
                observation_window="2026-08-02",
            )
            assert first.outcome is ExaSubmitOutcome.FAILED_RETRYABLE
            assert first.operation.spend_outcome.value == "not_dispatched"
            assert first.operation.submitted_receipt_ref is None
            transport.mode = "success"
            second = await submitter.submit(
                workspace_id=workspace_id,
                batch_id=batch_id,
                search_key="account-discovery",
                observation_window="2026-08-02",
            )
            assert second.outcome is ExaSubmitOutcome.CREATED
            assert second.operation.operation_id == first.operation.operation_id
            assert transport.create_calls == 2

    run_async(_run())


def test_pre_spend_cap_blocks_before_transport_or_operation_insert(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = "ws_d2_budget_block"
        storage = FsStorage(tmp_path / "artifacts")
        transport = _RecordingTransport()
        async with rollback_conn(seed_pack=True) as conn:
            _, batch_id = await _start_batch(
                conn,
                workspace_id=workspace_id,
                provider_credit_cap=19,
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            with pytest.raises(DiscoveryBudgetExceeded):
                await DurableExaWebsetSubmitter(
                    transport=transport,
                    storage=storage,
                    conn_factory=same_connection,
                ).submit(
                    workspace_id=workspace_id,
                    batch_id=batch_id,
                    search_key="account-discovery",
                    observation_window="2026-08-02",
                )
            assert transport.create_calls == 0

    run_async(_run())


def test_terminal_auth_failure_replays_without_create_or_lookup(tmp_path: Path) -> None:
    async def _run() -> None:
        workspace_id = "ws_d2_terminal_auth_replay"
        storage = FsStorage(tmp_path / "artifacts")
        transport = _RecordingTransport(mode="authentication")
        async with rollback_conn(seed_pack=True) as conn:
            _, batch_id = await _start_batch(conn, workspace_id=workspace_id)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            submitter = DurableExaWebsetSubmitter(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
            )
            first = await submitter.submit(
                workspace_id=workspace_id,
                batch_id=batch_id,
                search_key="account-discovery",
                observation_window="2026-08-02",
            )
            replay = await DurableExaWebsetSubmitter(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
            ).submit(
                workspace_id=workspace_id,
                batch_id=batch_id,
                search_key="account-discovery",
                observation_window="2026-08-02",
            )
            assert first.outcome is ExaSubmitOutcome.FAILED_TERMINAL
            assert replay.outcome is ExaSubmitOutcome.FAILED_TERMINAL
            assert replay.operation.operation_id == first.operation.operation_id
            assert replay.create_calls == 0
            assert replay.lookup_calls == 0
            assert transport.create_calls == 1
            assert transport.lookup_calls == 0

    run_async(_run())
