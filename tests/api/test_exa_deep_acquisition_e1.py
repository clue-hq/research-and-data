"""M8B E1 acceptance: durable Exa acquisition, no live provider and no claim materialization."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepAcquisitionOutcome,
    ExaDeepAcquisitionPreflight,
    _json_bytes,
    _sha256,
    compile_exa_deep_acquisition_plan,
    load_exa_deep_snapshot,
)
from clue_core import ExternalResearchCostDisposition, ProjectPhase, ProjectRunId
from clue_research.durable import (
    list_ready_external_research_snapshots,
    reconcile_external_research_cost,
)
from clue_research.durable.provider_spend import (
    ProviderSpendBudgetExceeded,
    require_provider_spend_capacity,
)
from clue_research.identity import get_account
from clue_research.resolvers.exa import ExaDeepRequestFailure
from clue_research.resolvers.exa.deep_contract import (
    ExaDeepFailureClass,
    ExaDeepFieldSpec,
    ExaDeepSearchRequest,
    legacy_exa_field_alias,
)
from clue_storage import FsStorage
from tests.api.test_sumble_committee_acquisition_s2b import _setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "providers" / "exa" / "search"


def _payload(name: str = "deep_response.json") -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _fields() -> tuple[ExaDeepFieldSpec, ...]:
    return (
        ExaDeepFieldSpec(field_key="account.operational_pain", value_schema={"type": "string"}),
        ExaDeepFieldSpec(field_key="account.strategic_moves", value_schema={"type": "string"}),
    )


class _Transport:
    def __init__(self, payload: Mapping[str, Any] | BaseException) -> None:
        self.payload = payload
        self.calls = 0

    def search(self, request: object) -> Mapping[str, Any]:
        del request
        self.calls += 1
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class _NoReplayTransport:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, request: object) -> Mapping[str, Any]:
        del request
        self.calls += 1
        raise AssertionError("fresh replay must not perform provider HTTP")


class _ProcessCrash(BaseException):
    pass


class _FailingPutStorage:
    def __init__(self, delegate: FsStorage, *, fail_on_put: int) -> None:
        self._delegate = delegate
        self._fail_on_put = fail_on_put
        self.puts = 0

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.puts += 1
        if self.puts == self._fail_on_put:
            raise RuntimeError("synthetic durable storage failure")
        await self._delegate.put(key, data, media_type=media_type)

    async def get(self, key: str) -> bytes:
        return await self._delegate.get(key)

    async def delete(self, key: str) -> None:
        await self._delegate.delete(key)

    async def exists(self, key: str) -> bool:
        return await self._delegate.exists(key)

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return await self._delegate.presign(key, expires_in=expires_in)

    def list_blobs(self):
        return self._delegate.list_blobs()


async def _preflight(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    observation_window: str,
    reservation: Decimal = Decimal(10),
):
    seed = await _setup(conn, storage, workspace_id=workspace_id)
    account = await get_account(conn, seed.account_id)
    assert account is not None
    return seed, _compile_preflight(seed, account, observation_window, reservation=reservation)


def _compile_preflight(
    seed: Any, account: Any, observation_window: str, *, reservation: Decimal = Decimal(10)
):
    plan = compile_exa_deep_acquisition_plan(
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        project_run_id=seed.project_run_id,
        account=account,
        icp_key=seed.icp_key,
        icp_version=seed.icp_version,
        research_directive=seed.research_directive,
        fields=_fields(),
        research_intent="operational workflow pain and strategic change evidence",
        additional_queries=(
            "referral intake fax workflow",
            "patient access expansion official source",
        ),
        observation_window=observation_window,
        freshness_policy_ref="freshness:exa-deep-e1-test-v1",
        freshness_seconds=3600,
        cost_cents_reserved_per_bundle=reservation,
    )
    assert len(plan.bundles) == 1
    assert plan.field_count == 2
    return plan.bundles[0]


def test_e1_coalesces_settles_once_persists_all_artifacts_and_replays_offline(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            seed, preflight = await _preflight(
                conn,
                storage,
                workspace_id="ws-exa-e1-success",
                observation_window="window:exa-e1-success",
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            payload = _payload()
            payload["costDollars"]["total"] = 0.07
            transport = _Transport(payload)
            coordinator = ExaDeepAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
            )
            spent_before = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": seed.project_run_id},
                    )
                ).scalar_one()
            )
            claims_before = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM claim WHERE entity_id=:account_id"),
                        {"account_id": seed.account_id},
                    )
                ).scalar_one()
            )
            ready = await coordinator.acquire(preflight)
            assert ready.outcome is ExaDeepAcquisitionOutcome.READY
            assert ready.provider_calls == 1
            assert ready.snapshot is not None
            assert transport.calls == 1
            assert ready.snapshot.provider_reported_cost_cents == Decimal(7)
            assert not ready.snapshot.all_null

            counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM external_research_operation WHERE id=:id) "
                            "AS operations, "
                            "(SELECT count(*) FROM external_research_attempt WHERE "
                            "operation_id=:id) AS attempts, "
                            "(SELECT count(*) FROM external_research_snapshot WHERE "
                            "operation_id=:id) AS snapshots, "
                            "(SELECT count(*) FROM external_research_receipt WHERE "
                            "operation_id=:id) AS receipts, "
                            "(SELECT count(*) FROM external_research_result_artifact WHERE "
                            "snapshot_id=:snapshot_id) AS results"
                        ),
                        {
                            "id": ready.operation.operation_id,
                            "snapshot_id": ready.snapshot.snapshot_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert dict(counts) == {
                "operations": 1,
                "attempts": 1,
                "snapshots": 1,
                "receipts": 1,
                "results": 2,
            }
            attempt = (
                (
                    await conn.execute(
                        text(
                            "SELECT state::text, provider_request_id, response_artifact_key "
                            "FROM external_research_attempt WHERE operation_id=:id"
                        ),
                        {"id": ready.operation.operation_id},
                    )
                )
                .mappings()
                .one()
            )
            assert attempt["state"] == "responded"
            assert attempt["provider_request_id"] == "exa-deep-fixture-request-1"
            assert attempt["response_artifact_key"] == ready.snapshot.response_artifact_key
            immutable = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="terminal external research attempt"):
                await conn.execute(
                    text(
                        "UPDATE external_research_attempt SET failure_code='tampered' "
                        "WHERE operation_id=:id"
                    ),
                    {"id": ready.operation.operation_id},
                )
            await immutable.rollback()
            spent_after = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": seed.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_after - spent_before == Decimal(7)
            claims_after = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM claim WHERE entity_id=:account_id"),
                        {"account_id": seed.account_id},
                    )
                ).scalar_one()
            )
            assert claims_after == claims_before, "E1 must not materialize E2 claims"

            replay_transport = _NoReplayTransport()
            fresh_process = ExaDeepAcquisitionCoordinator(
                transport=replay_transport,
                storage=storage,
                conn_factory=same_connection,
            )
            replay = await fresh_process.acquire(preflight)
            assert replay.outcome is ExaDeepAcquisitionOutcome.REPLAYED
            assert replay.operation.operation_id == ready.operation.operation_id
            assert replay.snapshot == ready.snapshot
            assert replay_transport.calls == 0
            spent_replayed = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": seed.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_replayed == spent_after
            stored_response, stored_normalization = await load_exa_deep_snapshot(
                storage=storage, snapshot=replay.snapshot
            )
            assert stored_response.request_id == "exa-deep-fixture-request-1"
            assert len(stored_normalization["synthesis"]["fields"]) == 2

            next_window = _compile_preflight(
                seed,
                await get_account(conn, seed.account_id),
                "window:exa-e1-fresh-reuse",
            )
            freshness_reuse = await fresh_process.acquire(next_window)
            assert freshness_reuse.outcome is ExaDeepAcquisitionOutcome.REPLAYED
            assert freshness_reuse.operation.operation_id == ready.operation.operation_id
            assert replay_transport.calls == 0

            second_run_id = ProjectRunId(uuid4())
            await conn.execute(
                text(
                    "INSERT INTO project_run ("
                    "id, workspace_id, icp_key, icp_version, phase, status, budget_cap_cents, "
                    "spent_cents, tier_cutoffs_json, project_id, brand_id, client_entity_id, "
                    "client_kb_version, product_id, product_context_version_id, "
                    "readiness_decision_id) SELECT :new_id, workspace_id, icp_key, icp_version, "
                    "phase, status, budget_cap_cents, 0, tier_cutoffs_json, project_id, brand_id, "
                    "client_entity_id, client_kb_version, product_id, product_context_version_id, "
                    "readiness_decision_id FROM project_run WHERE id=:source_id"
                ),
                {"new_id": second_run_id, "source_id": seed.project_run_id},
            )
            second_seed = seed.model_copy(update={"project_run_id": second_run_id})
            second_preflight = _compile_preflight(
                second_seed,
                await get_account(conn, seed.account_id),
                "window:exa-e1-second-run",
            )
            cross_run = await fresh_process.acquire(second_preflight)
            assert cross_run.outcome is ExaDeepAcquisitionOutcome.REPLAYED
            assert cross_run.operation.operation_id == ready.operation.operation_id
            assert replay_transport.calls == 0
            adopted = await list_ready_external_research_snapshots(
                conn,
                workspace_id=seed.workspace_id,
                project_run_id=second_run_id,
                account_id=seed.account_id,
                source_key="exa_deep",
                research_directive_id=seed.research_directive.directive_id,
                research_directive_version=seed.research_directive.version,
                research_directive_sha256=seed.research_directive.canonical_json_sha256,
                research_override_id=None,
                research_override_sha256=None,
            )
            assert adopted == (ready.snapshot,)
            uses = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM external_research_snapshot_use "
                            "WHERE snapshot_id=:snapshot_id"
                        ),
                        {"snapshot_id": ready.snapshot.snapshot_id},
                    )
                ).scalar_one()
            )
            assert uses == 2

    run_async(scenario())


def test_e1_active_dispatch_joins_then_expired_lease_quarantines_without_retry(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            _, preflight = await _preflight(
                conn,
                storage,
                workspace_id="ws-exa-e1-crash",
                observation_window="window:exa-e1-crash",
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            start = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
            transport = _Transport(_ProcessCrash())
            crashed = ExaDeepAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
                dispatch_lease_seconds=60,
                clock=lambda: start,
            )
            with pytest.raises(_ProcessCrash):
                await crashed.acquire(preflight)
            assert transport.calls == 1
            joined = await crashed.acquire(preflight)
            assert joined.outcome is ExaDeepAcquisitionOutcome.JOINED_IN_FLIGHT
            assert joined.retry_after == start + timedelta(seconds=60)
            assert transport.calls == 1

            recovered = ExaDeepAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=same_connection,
                dispatch_lease_seconds=60,
                clock=lambda: start + timedelta(seconds=61),
            )
            quarantined = await recovered.acquire(preflight)
            assert quarantined.outcome is ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN
            assert quarantined.operation.failure_code == "dispatch_lease_expired"
            assert transport.calls == 1
            replay = await recovered.acquire(preflight)
            assert replay.outcome is ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN
            assert transport.calls == 1

    run_async(scenario())


def test_e1_classifies_pre_dispatch_malformed_and_all_null_outcomes(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            seed, hard_preflight = await _preflight(
                conn,
                storage,
                workspace_id="ws-exa-e1-outcomes",
                observation_window="window:exa-e1-hard",
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            spent_before = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": seed.project_run_id},
                    )
                ).scalar_one()
            )
            hard = ExaDeepAcquisitionCoordinator(
                transport=_Transport(
                    ExaDeepRequestFailure(
                        "credential missing",
                        failure_class=ExaDeepFailureClass.HARD,
                        dispatched=False,
                    )
                ),
                storage=storage,
                conn_factory=same_connection,
            )
            failed = await hard.acquire(hard_preflight)
            assert failed.outcome is ExaDeepAcquisitionOutcome.FAILED_TERMINAL
            assert failed.operation.spend_outcome.value == "not_charged"

            account = await get_account(conn, seed.account_id)
            assert account is not None
            rejected_preflight = _compile_preflight(
                seed, account, "window:exa-e1-known-http-rejection"
            )
            rejected = ExaDeepAcquisitionCoordinator(
                transport=_Transport(
                    ExaDeepRequestFailure(
                        "provider rejected request",
                        failure_class=ExaDeepFailureClass.HARD,
                        dispatched=True,
                        status_code=400,
                    )
                ),
                storage=storage,
                conn_factory=same_connection,
            )
            rejected_result = await rejected.acquire(rejected_preflight)
            assert rejected_result.outcome is ExaDeepAcquisitionOutcome.FAILED_TERMINAL
            assert rejected_result.operation.spend_outcome.value == "not_charged"
            assert rejected_result.provider_calls == 1

            malformed_preflight = _compile_preflight(seed, account, "window:exa-e1-malformed")
            malformed = ExaDeepAcquisitionCoordinator(
                transport=_Transport({"requestId": "missing-cost-and-output"}),
                storage=storage,
                conn_factory=same_connection,
            )
            unknown = await malformed.acquire(malformed_preflight)
            assert unknown.outcome is ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN
            assert unknown.operation.spend_outcome.value == "unknown"
            malformed_attempt = (
                (
                    await conn.execute(
                        text(
                            "SELECT response_artifact_key, provider_request_id FROM "
                            "external_research_attempt WHERE operation_id=:operation_id"
                        ),
                        {"operation_id": unknown.operation.operation_id},
                    )
                )
                .mappings()
                .one()
            )
            assert malformed_attempt["response_artifact_key"] is not None
            assert malformed_attempt["provider_request_id"] == "missing-cost-and-output"
            assert await storage.exists(malformed_attempt["response_artifact_key"])

            await conn.execute(
                text("UPDATE project_run SET budget_cap_cents=10 WHERE id=:id"),
                {"id": seed.project_run_id},
            )
            with pytest.raises(ProviderSpendBudgetExceeded):
                await require_provider_spend_capacity(
                    conn,
                    project_run_id=seed.project_run_id,
                    proposed_cents=Decimal("0.01"),
                    allowed_phases=frozenset({ProjectPhase.DEEP}),
                )
            reconciled = await reconcile_external_research_cost(
                conn,
                workspace_id=seed.workspace_id,
                operation_id=unknown.operation.operation_id,
                disposition=ExternalResearchCostDisposition.NOT_CHARGED,
                settled_cost_cents=Decimal(0),
                evidence_artifact_key=malformed_attempt["response_artifact_key"],
                actor_ref="provider-billing:test-confirmed-not-charged",
                now=datetime.now(UTC),
            )
            assert reconciled.disposition is ExternalResearchCostDisposition.NOT_CHARGED
            capacity = await require_provider_spend_capacity(
                conn,
                project_run_id=seed.project_run_id,
                proposed_cents=Decimal(10),
                allowed_phases=frozenset({ProjectPhase.DEEP}),
            )
            assert capacity.outstanding_cents == 0

            exception_preflight = _compile_preflight(
                seed, account, "window:exa-e1-transport-exception"
            )
            exception_coordinator = ExaDeepAcquisitionCoordinator(
                transport=_Transport(RuntimeError("socket closed after dispatch")),
                storage=storage,
                conn_factory=same_connection,
            )
            exception_unknown = await exception_coordinator.acquire(exception_preflight)
            assert exception_unknown.outcome is ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN
            await reconcile_external_research_cost(
                conn,
                workspace_id=seed.workspace_id,
                operation_id=exception_unknown.operation.operation_id,
                disposition=ExternalResearchCostDisposition.NOT_CHARGED,
                settled_cost_cents=Decimal(0),
                evidence_artifact_key=exception_unknown.operation.request_artifact_key,
                actor_ref="provider-billing:test-confirmed-not-charged",
                now=datetime.now(UTC),
            )

            null_preflight = _compile_preflight(seed, account, "window:exa-e1-null")
            aliases = null_preflight.exa_request.output_schema["properties"]
            assert isinstance(aliases, dict)
            null_payload = {
                "requestId": "exa-e1-all-null",
                "results": [],
                "output": {
                    "content": dict.fromkeys(aliases),
                    "grounding": [],
                },
                "costDollars": {"total": 0.02},
            }
            null_coordinator = ExaDeepAcquisitionCoordinator(
                transport=_Transport(null_payload),
                storage=storage,
                conn_factory=same_connection,
            )
            paid_miss = await null_coordinator.acquire(null_preflight)
            assert paid_miss.outcome is ExaDeepAcquisitionOutcome.READY
            assert paid_miss.snapshot is not None
            assert paid_miss.snapshot.all_null
            assert paid_miss.snapshot.provider_reported_cost_cents == Decimal(2)
            spent_after = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": seed.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_after - spent_before == Decimal(2)

    run_async(scenario())


def test_e1_bundle_compiler_splits_only_at_provider_schema_limit() -> None:
    from uuid import uuid4

    from clue_core import AccountEntity, ProjectRunId, ResearchDirectivePin, new_entity_id
    from clue_core.research_directive import ResearchDirectiveId

    account = AccountEntity(
        id=new_entity_id(),
        canonical_name="Cascade Gastroenterology",
        primary_domain="cascade.example",
        workspace_id="ws-exa-e1-pack",
    )
    directive_id = ResearchDirectiveId(uuid4())
    pin = ResearchDirectivePin(
        directive_id=directive_id,
        directive_ref=f"research-directive:{directive_id}:v1",
        version=1,
        canonical_json_sha256="a" * 64,
        account_id=account.id,
    )
    fields = tuple(
        ExaDeepFieldSpec(field_key=f"account.deep_field_{index}", value_schema={"type": "string"})
        for index in range(10)
    )
    plan = compile_exa_deep_acquisition_plan(
        workspace_id=account.workspace_id,
        project_id="project-exa-e1-pack",
        project_run_id=ProjectRunId(uuid4()),
        account=account,
        icp_key="pack-test",
        icp_version=1,
        research_directive=pin,
        fields=fields,
        research_intent="bounded deep evidence",
        additional_queries=(),
        observation_window="window:pack",
        freshness_policy_ref="freshness:pack",
        freshness_seconds=60,
        cost_cents_reserved_per_bundle=Decimal(10),
    )
    assert [len(bundle.exa_request.output_schema["properties"]) for bundle in plan.bundles] == [
        8,
        2,
    ]
    assert plan.field_count == 10


def _as_legacy_alias_preflight(
    preflight: ExaDeepAcquisitionPreflight,
) -> ExaDeepAcquisitionPreflight:
    """Restate one compiled preflight in the frozen v1 hex-alias generation.

    Every operation reserved before the short-alias cutover carries a v1 wire request in
    ``request_json``, and its retained response names the v1 aliases. Durable acquisition, replay
    and the one-shot retained-response recovery all have to keep reading those, so this rewrites a
    live-compiled preflight rather than pinning a hand-written legacy body.
    """

    request = preflight.exa_request
    rename = {
        alias: legacy_exa_field_alias(field_key)
        for alias, field_key in request.field_key_by_alias.items()
    }
    raw = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    schema = raw["outputSchema"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    schema["properties"] = {rename[alias]: value for alias, value in properties.items()}
    schema["required"] = [rename[alias] for alias in properties]
    prompt = raw["systemPrompt"]
    assert isinstance(prompt, str)
    for alias, legacy in rename.items():
        prompt = prompt.replace(f"{alias}=", f"{legacy}=")
    raw["systemPrompt"] = prompt
    legacy_request = ExaDeepSearchRequest.model_validate(raw)
    payload = legacy_request.model_dump(mode="json", by_alias=True, exclude_none=True)
    return preflight.model_copy(
        update={
            "exa_request": legacy_request,
            "request": preflight.request.model_copy(
                update={
                    "request_payload": payload,
                    "wire_request_sha256": _sha256(_json_bytes(payload)),
                }
            ),
        }
    )


def test_e1_quarantines_success_persistence_failure_immediately(tmp_path: Path) -> None:
    """The one-shot retained-response recovery still reads a v1 request and a v1 response.

    The prefix salvage this exercises is a legacy-generation rescue: it identifies a corrupted
    property name by its intact byte-aligned hex prefix, which only a v1 alias has. Driving it
    through a legacy preflight is also the end-to-end proof that a pre-cutover operation still
    dispatches, quarantines, replays and recovers after the compiler moved to short aliases.
    """

    async def scenario() -> None:
        base_storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            seed = await _setup(conn, base_storage, workspace_id="ws-exa-e1-persist-failure")
            account = await get_account(conn, seed.account_id)
            assert account is not None
            preflight = _as_legacy_alias_preflight(
                _compile_preflight(seed, account, "window:exa-e1-persist-failure")
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            storage = _FailingPutStorage(base_storage, fail_on_put=3)
            payload = _payload("legacy_alias_deep_response.json")
            payload["costDollars"]["total"] = 0.07
            canonical = legacy_exa_field_alias("account.operational_pain")
            corrupted = f"{canonical[:26]}ெரrational_pain"
            content = payload["output"]["content"]
            content[corrupted] = content.pop(canonical)
            for grounding in payload["output"]["grounding"]:
                if grounding["field"] == canonical:
                    grounding["field"] = corrupted
            result = await ExaDeepAcquisitionCoordinator(
                transport=_Transport(payload),
                storage=storage,
                conn_factory=same_connection,
            ).acquire(preflight)
            assert result.outcome is ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN
            assert result.operation.failure_code == "success_persistence_failed"
            assert result.operation.dispatch_lease_expires_at is None
            attempt = (
                (
                    await conn.execute(
                        text(
                            "SELECT state::text, response_artifact_key FROM "
                            "external_research_attempt WHERE operation_id=:operation_id"
                        ),
                        {"operation_id": result.operation.operation_id},
                    )
                )
                .mappings()
                .one()
            )
            assert attempt["state"] == "spend_outcome_unknown"
            assert attempt["response_artifact_key"] is not None

            replay_transport = _NoReplayTransport()
            replay = await ExaDeepAcquisitionCoordinator(
                transport=replay_transport,
                storage=base_storage,
                conn_factory=same_connection,
            ).acquire(preflight)
            assert replay.outcome is ExaDeepAcquisitionOutcome.REPLAYED
            assert replay.provider_calls == 0
            assert replay.snapshot is not None
            assert replay_transport.calls == 0
            loaded_response, _ = await load_exa_deep_snapshot(
                storage=base_storage,
                snapshot=replay.snapshot,
            )
            assert canonical in loaded_response.output.content
            recovered_attempt = (
                (
                    await conn.execute(
                        text(
                            "SELECT state::text, failure_code, failure_detail FROM "
                            "external_research_attempt WHERE operation_id=:operation_id"
                        ),
                        {"operation_id": result.operation.operation_id},
                    )
                )
                .mappings()
                .one()
            )
            assert dict(recovered_attempt) == {
                "state": "responded",
                "failure_code": None,
                "failure_detail": None,
            }
            recovery = (
                (
                    await conn.execute(
                        text(
                            "SELECT response_artifact_key, provider_request_id, parser_version, "
                            "actor_ref FROM external_research_response_recovery "
                            "WHERE operation_id=:operation_id"
                        ),
                        {"operation_id": result.operation.operation_id},
                    )
                )
                .mappings()
                .one()
            )
            assert recovery["response_artifact_key"] == attempt["response_artifact_key"]
            assert recovery["provider_request_id"] == "exa-deep-fixture-request-1"
            assert recovery["parser_version"] == "exa-deep-unique-alias-recovery-v1"
            assert recovery["actor_ref"] == "engine:exa-deep-retained-response-recovery"

    run_async(scenario())
