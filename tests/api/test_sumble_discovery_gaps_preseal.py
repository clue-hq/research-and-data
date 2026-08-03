"""P0-P3 repair: required-field Sumble waterfall before the immutable D5 seal."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.discovery_seal import DurableDiscoveryPhaseHandler
from clue_api.exa_websets_materialization import ExaD4Outcome, ExaWebsetsD4Materializer
from clue_api.sumble_discovery_gaps import (
    SumbleDiscoveryGapError,
    SumbleDiscoveryGapOutcome,
    SumbleDiscoveryGapResolver,
)
from clue_core import (
    DiscoveryBatchId,
    DiscoveryFieldResolutionState,
    EntityId,
    EntityType,
    ExtractionMethod,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    ResearchMode,
    RunId,
    account_claim,
    revalidate_with,
)
from clue_db import db_lifespan, transaction
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim, load_core_pack
from clue_research.durable import (
    DiscoveryGapBudgetExceeded,
    enumerate_discovery_subject_artifacts,
    get_discovery_batch,
    get_discovery_batch_manifest,
    get_discovery_field_resolution,
    get_project_run,
    link_discovery_page_item,
    list_discovery_gap_field_results,
    list_discovery_gap_operations,
    read_discovery_seal_readiness,
    reconcile_discovery_batch_costs,
    tombstone_discovery_subject_artifacts,
)
from clue_research.identity import insert_account_entity, mark_merged
from clue_research.resolvers.sumble import SumbleClient, SumbleCreditBudget
from clue_storage import FsStorage
from tests.api.test_exa_websets_materialization_d4 import (
    _company_item,
    _seed_terminal_batch,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _FallbackMustNotRun:
    phase = ProjectPhase.DISCOVERY

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        raise AssertionError(f"durable discovery {ctx.project_run_id} used its legacy fallback")


class _OrganizationsHttp:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append({"url": url, **kwargs})
        body = kwargs["json_body"]
        domain = body["organizations"][0]["url"]
        return {
            "id": "preseal-org-request-1",
            "credits_used": 2,
            "credits_remaining": 998,
            "organizations": [
                {
                    "input": {"url": domain},
                    "attributes": {
                        "id": 1726684,
                        "name": "Example Neuro",
                        "url": domain,
                        "sumble_url": "https://sumble.com/l/org/example-neuro",
                        "industry": "Medical Practices",
                    },
                    "entities": [],
                }
            ],
            "matched_count": 1,
            "total": 1,
        }


async def _phase_context(
    conn: Any, *, workspace_id: str, batch_id: DiscoveryBatchId
) -> PhaseContext:
    batch = await get_discovery_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
    assert batch is not None
    run = await get_project_run(conn, batch.project_run_id)
    assert run is not None
    return PhaseContext(
        project_run_id=run.id,
        project_id=run.project_id,
        brand_id=run.brand_id,
        phase=ProjectPhase.DISCOVERY,
        workspace_id=workspace_id,
        icp_key=run.icp_key,
        icp_version=run.icp_version,
        budget_cap_cents=run.budget_cap_cents,
    )


async def _seed_one_yes_gap(
    conn: Any, storage: FsStorage, *, workspace_id: str
) -> tuple[DiscoveryBatchId, EntityId, PhaseContext]:
    batch_id, item_ids, _ = await _seed_terminal_batch(
        conn,
        storage,
        workspace_id,
        item_payloads=[_company_item("item_preseal_yes", city="Austin", criterion_state="yes")],
        provider_operation_id=f"ws_d4_{workspace_id}",
    )
    item_page = (
        (
            await conn.execute(
                text(
                    "SELECT id, operation_id FROM discovery_page_receipt "
                    "WHERE workspace_id=:workspace_id AND resource_kind='items'"
                ),
                {"workspace_id": workspace_id},
            )
        )
        .mappings()
        .one()
    )
    for ordinal, item_id in enumerate(item_ids):
        await link_discovery_page_item(
            conn,
            workspace_id=workspace_id,
            operation_id=item_page["operation_id"],
            page_receipt_id=item_page["id"],
            item_snapshot_id=item_id,
            ordinal=ordinal,
        )
    await reconcile_discovery_batch_costs(conn, workspace_id=workspace_id, batch_id=batch_id)
    materialized = await ExaWebsetsD4Materializer(
        storage=storage,
        conn_factory=conn_session_factory(conn),
    ).materialize(workspace_id=workspace_id, batch_id=batch_id)
    assert materialized.outcome is ExaD4Outcome.MATERIALIZED
    assert len(materialized.account_ids) == 1
    return (
        batch_id,
        materialized.account_ids[0],
        await _phase_context(conn, workspace_id=workspace_id, batch_id=batch_id),
    )


def test_preseal_sumble_resolves_d4_gap_seals_and_replays_without_provider_call(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_id = "ws-preseal-sumble-happy"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            batch_id, account_id, ctx = await _seed_one_yes_gap(
                conn, storage, workspace_id=workspace_id
            )
            industry_before = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.industry",
            )
            assert industry_before is not None
            assert industry_before.state is DiscoveryFieldResolutionState.PENDING
            assert not (
                await read_discovery_seal_readiness(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
            ).required_fields_terminal

            http = _OrganizationsHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            resolver = SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=conn_session_factory(conn),
                client_factory=client_factory,
            )
            handler = DurableDiscoveryPhaseHandler(
                storage=storage,
                fallback=_FallbackMustNotRun(),
                required_field_resolver=resolver,
                conn_factory=conn_session_factory(conn),
            )
            gap_progress = await resolver.ensure_terminal(ctx, batch_id)
            assert gap_progress.outcome is SumbleDiscoveryGapOutcome.COMPLETE
            operation = (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
            )[0]
            batch_before_reconcile = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=batch_id
            )
            assert batch_before_reconcile is not None
            assert operation.provider_units_charged == Decimal(2)
            await reconcile_discovery_batch_costs(
                conn, workspace_id=workspace_id, batch_id=batch_id
            )
            batch_after_reconcile = await get_discovery_batch(
                conn, workspace_id=workspace_id, batch_id=batch_id
            )
            assert batch_after_reconcile is not None
            assert (
                batch_after_reconcile.provider_units_charged
                == batch_before_reconcile.provider_units_charged
            )
            assert (
                batch_after_reconcile.cost_cents_charged
                == batch_before_reconcile.cost_cents_charged
            )
            result = await handler.run(ctx)
            assert result.status is PhaseStatus.COMPLETED
            assert result.accounts_processed == 1
            assert len(http.calls) == 1
            assert http.calls[0]["json_body"] == {
                "organizations": [{"url": "example-neuro.com"}],
                "select": {"attributes": ["id", "name", "url", "sumble_url", "industry"]},
            }

            industry = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.industry",
            )
            assert industry is not None
            assert industry.state is DiscoveryFieldResolutionState.RESOLVED
            assert industry.winning_claim_id is not None
            provider_claims = await claims_for(
                conn,
                account_id,
                "core.industry",
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert len(provider_claims) == 1
            assert provider_claims[0].source_key == "sumble_organizations"
            assert provider_claims[0].value_json == "Medical Practices"

            operations = await list_discovery_gap_operations(
                conn, workspace_id=workspace_id, batch_id=batch_id
            )
            assert len(operations) == 1
            assert operations[0] == operation
            assert operation.state.value == "succeeded"
            assert operation.provider_units_reserved == Decimal(2)
            assert operation.provider_units_charged == Decimal(2)
            assert operation.cost_cents_charged == Decimal(1)
            manifest = await get_discovery_batch_manifest(
                conn, workspace_id=workspace_id, batch_id=batch_id
            )
            assert manifest is not None
            gap_operation_ids = manifest.coverage_payload["discovery_gap_operation_ids"]
            assert isinstance(gap_operation_ids, list)
            assert str(operation.operation_id) in gap_operation_ids
            assert industry.winning_claim_id in manifest.claim_ids
            assert operation.request_artifact_key in manifest.raw_artifact_keys
            assert operation.response_artifact_key in manifest.raw_artifact_keys
            assert operation.receipt_artifact_key in manifest.raw_artifact_keys

            subject_artifacts = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=account_id,
            )
            assert {
                edge.reference_kind
                for edge in subject_artifacts
                if edge.reference_kind.startswith("sumble_discovery_gap")
            } == {
                "sumble_discovery_gap_request",
                "sumble_discovery_gap_response",
                "sumble_discovery_gap_receipt",
            }

            def no_replay_client(maximum: int, cents: Decimal) -> SumbleClient:
                del maximum, cents
                raise AssertionError("sealed fresh-process replay attempted a Sumble call")

            replay_handler = DurableDiscoveryPhaseHandler(
                storage=storage,
                fallback=_FallbackMustNotRun(),
                required_field_resolver=SumbleDiscoveryGapResolver(
                    enabled=True,
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=conn_session_factory(conn),
                    client_factory=no_replay_client,
                ),
                conn_factory=conn_session_factory(conn),
            )
            replay = await replay_handler.run(ctx)
            assert replay == result
            assert len(http.calls) == 1
            assert (
                len(
                    await list_discovery_gap_operations(
                        conn, workspace_id=workspace_id, batch_id=batch_id
                    )
                )
                == 1
            )

            savepoint = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="terminal discovery-gap operation is immutable"):
                await conn.execute(
                    text(
                        "UPDATE discovery_gap_operation SET provider_units_charged=0 "
                        "WHERE id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            await savepoint.rollback()
            field_savepoint = await conn.begin_nested()
            with pytest.raises(
                DBAPIError, match="terminal discovery-gap field outcome is immutable"
            ):
                await conn.execute(
                    text(
                        "UPDATE discovery_gap_field_result SET reason_code='late_mutation' "
                        "WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            await field_savepoint.rollback()
            with pytest.raises(SumbleDiscoveryGapError, match="active current"):
                await resolver.ensure_terminal(ctx, batch_id)
            assert len(http.calls) == 1

            await tombstone_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=account_id,
            )
            assert (
                await enumerate_discovery_subject_artifacts(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind="account",
                    subject_entity_id=account_id,
                )
                == ()
            )

    run_async(scenario())


def test_preseal_sumble_fails_closed_on_budget_phase_tenant_and_unknown_spend(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "guard-artifacts")

        async with rollback_conn() as conn:
            workspace_id = "ws-preseal-sumble-budget"
            batch_id, _, ctx = await _seed_one_yes_gap(conn, storage, workspace_id=workspace_id)
            await conn.execute(
                text("UPDATE project_run SET budget_cap_cents=0 WHERE id=:run_id"),
                {"run_id": ctx.project_run_id},
            )
            http = _OrganizationsHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            resolver = SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=conn_session_factory(conn),
                client_factory=client_factory,
            )
            with pytest.raises(DiscoveryGapBudgetExceeded, match="project-run cap"):
                await resolver.ensure_terminal(ctx, batch_id)
            assert http.calls == []
            assert (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
                == ()
            )

            paused = await conn.begin_nested()
            await conn.execute(
                text("UPDATE project_run SET status='paused' WHERE id=:run_id"),
                {"run_id": ctx.project_run_id},
            )
            with pytest.raises(SumbleDiscoveryGapError, match="active current"):
                await resolver.ensure_terminal(ctx, batch_id)
            await paused.rollback()
            with pytest.raises(SumbleDiscoveryGapError, match="active current"):
                await resolver.ensure_terminal(
                    ctx.model_copy(update={"workspace_id": "foreign-workspace"}), batch_id
                )
            assert http.calls == []

        async with rollback_conn() as conn:
            workspace_id = "ws-preseal-sumble-unknown"
            batch_id, _, ctx = await _seed_one_yes_gap(conn, storage, workspace_id=workspace_id)
            calls = 0

            def fail_after_dispatch(maximum: int, cents: Decimal) -> SumbleClient:
                del maximum, cents

                class _FailingClient:
                    def resolve_organization(self, domain: str, *, field_keys: object) -> object:
                        nonlocal calls
                        del domain, field_keys
                        calls += 1
                        raise RuntimeError("connection lost after dispatch")

                return _FailingClient()  # type: ignore[return-value]

            resolver = SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                conn_factory=conn_session_factory(conn),
                client_factory=fail_after_dispatch,
            )
            first = await resolver.ensure_terminal(ctx, batch_id)
            assert first.outcome is SumbleDiscoveryGapOutcome.BLOCKED_REVIEW
            assert calls == 1
            operation = (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
            )[0]
            assert operation.state.value == "spend_outcome_unknown"
            assert operation.spend_outcome.value == "unknown"
            assert not (
                await read_discovery_seal_readiness(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
            ).spend_reconciled

            invalid_lineage = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="source item lineage mismatch"):
                await conn.execute(
                    text(
                        "UPDATE discovery_gap_field_result "
                        "SET source_item_ids=CAST(:items AS jsonb) "
                        "WHERE operation_id=:operation_id"
                    ),
                    {"items": f'["{uuid4()}"]', "operation_id": operation.operation_id},
                )
            await invalid_lineage.rollback()
            invalid_source = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="field lineage differs"):
                await conn.execute(
                    text(
                        "UPDATE discovery_gap_field_result SET source_key='wrong_source' "
                        "WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            await invalid_source.rollback()

            replay = await SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                conn_factory=conn_session_factory(conn),
                client_factory=fail_after_dispatch,
            ).ensure_terminal(ctx, batch_id)
            assert replay.outcome is SumbleDiscoveryGapOutcome.BLOCKED_REVIEW
            assert calls == 1

    run_async(scenario())


def test_d5_resumes_crash_after_field_reconciliation_without_second_sumble_call(
    tmp_path: Path,
) -> None:
    class _InjectedCrash(BaseException):
        pass

    async def scenario() -> None:
        workspace_id = "ws-preseal-sumble-materialization-resume"
        storage = FsStorage(tmp_path / "materialization-resume-artifacts")
        async with rollback_conn() as conn:
            batch_id, account_id, ctx = await _seed_one_yes_gap(
                conn, storage, workspace_id=workspace_id
            )
            http = _OrganizationsHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            interrupted = SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                conn_factory=conn_session_factory(conn),
                client_factory=client_factory,
            )

            async def crash_before_receipt(operation: object) -> str:
                del operation
                raise _InjectedCrash

            interrupted._receipt = crash_before_receipt  # type: ignore[method-assign]
            with pytest.raises(_InjectedCrash):
                await interrupted.ensure_terminal(ctx, batch_id)

            operation = (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
            )[0]
            assert operation.state.value == "materializing"
            resolution = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.industry",
            )
            assert resolution is not None
            assert resolution.state is DiscoveryFieldResolutionState.RESOLVED
            readiness = await read_discovery_seal_readiness(
                conn, workspace_id=workspace_id, batch_id=batch_id
            )
            assert readiness.required_fields_terminal
            assert not readiness.operations_terminal
            assert len(http.calls) == 1

            def no_second_dispatch(maximum: int, cents: Decimal) -> SumbleClient:
                del maximum, cents
                raise AssertionError("materialization replay attempted a second Sumble dispatch")

            handler = DurableDiscoveryPhaseHandler(
                storage=storage,
                fallback=_FallbackMustNotRun(),
                required_field_resolver=SumbleDiscoveryGapResolver(
                    enabled=True,
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    conn_factory=conn_session_factory(conn),
                    client_factory=no_second_dispatch,
                ),
                conn_factory=conn_session_factory(conn),
            )
            result = await handler.run(ctx)
            assert result.status is PhaseStatus.COMPLETED
            assert len(http.calls) == 1
            resumed = (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
            )[0]
            assert resumed.state.value == "succeeded"

    run_async(scenario())


def test_preseal_sumble_preserves_exa_and_sumble_claims_on_conflict(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = "ws-preseal-sumble-conflict"
        storage = FsStorage(tmp_path / "conflict-artifacts")
        async with rollback_conn() as conn:
            batch_id, account_id, ctx = await _seed_one_yes_gap(
                conn, storage, workspace_id=workspace_id
            )
            item_artifact_key = (
                await conn.execute(
                    text(
                        "SELECT item.raw_artifact_key FROM discovery_candidate_link candidate "
                        "JOIN discovery_item_snapshot item ON item.id=candidate.item_snapshot_id "
                        "AND item.workspace_id=candidate.workspace_id "
                        "WHERE candidate.workspace_id=:workspace_id "
                        "AND candidate.batch_id=:batch_id "
                        "AND candidate.survivor_entity_id=:account_id"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "batch_id": batch_id,
                        "account_id": account_id,
                    },
                )
            ).scalar_one()
            exa_claim_id = await insert_claim(
                conn,
                revalidate_with(
                    account_claim(
                        entity_id=account_id,
                        field_key="core.industry",
                        value_json="Hospitals",
                        source_tier=2,
                        extraction_method=ExtractionMethod.API,
                        confidence=0.95,
                        run_id=RunId(ctx.project_run_id),
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                        source_url="https://example-neuro.com",
                        evidence_span="Hospitals",
                    ),
                    source_key="exa_websets",
                    artifact_key=item_artifact_key,
                ),
            )
            http = _OrganizationsHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            resolver = SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                conn_factory=conn_session_factory(conn),
                client_factory=client_factory,
            )
            progress = await resolver.ensure_terminal(ctx, batch_id)
            assert progress.outcome is SumbleDiscoveryGapOutcome.COMPLETE
            assert len(http.calls) == 1
            operation = (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
            )[0]
            field_result = (
                await list_discovery_gap_field_results(
                    conn,
                    workspace_id=workspace_id,
                    operation_id=operation.operation_id,
                )
            )[0]
            assert field_result.state.value == "conflict"
            assert field_result.provider_claim_id is not None
            assert exa_claim_id in field_result.conflicting_claim_ids
            assert field_result.provider_claim_id in field_result.conflicting_claim_ids
            resolution = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.industry",
            )
            assert resolution is not None
            assert resolution.state is DiscoveryFieldResolutionState.CONFLICT
            assert resolution.winning_claim_id is None
            assert set(resolution.claim_ids) >= {
                exa_claim_id,
                field_result.provider_claim_id,
            }
            preserved = await claims_for(
                conn,
                account_id,
                "core.industry",
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert {claim.source_key for claim in preserved} == {
                "exa_websets",
                "sumble_organizations",
            }

    run_async(scenario())


def test_preseal_sumble_rejects_account_merged_after_d4_without_provider_call(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_id = "ws-preseal-sumble-merged-loser"
        storage = FsStorage(tmp_path / "merged-artifacts")
        async with rollback_conn() as conn:
            batch_id, account_id, ctx = await _seed_one_yes_gap(
                conn, storage, workspace_id=workspace_id
            )
            survivor_id = await insert_account_entity(
                conn,
                canonical_name="Canonical Neuro Group",
                primary_domain="canonical-neuro.example",
                workspace_id=workspace_id,
            )
            await mark_merged(conn, EntityType.ACCOUNT, account_id, survivor_id)
            http = _OrganizationsHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            resolver = SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                conn_factory=conn_session_factory(conn),
                client_factory=client_factory,
            )
            with pytest.raises(SumbleDiscoveryGapError, match="canonical survivor"):
                await resolver.ensure_terminal(ctx, batch_id)
            assert http.calls == []
            assert (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
                == ()
            )

    run_async(scenario())


@pytest.mark.skipif(
    os.getenv("CLUE_P0P3_COMMITTED_GATE") != "1",
    reason="set CLUE_P0P3_COMMITTED_GATE=1 only with a throwaway PostgreSQL database",
)
def test_two_processes_reserve_once_and_dispatch_sumble_at_most_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = f"ws-preseal-sumble-concurrent-{os.getpid()}"
        storage = FsStorage(tmp_path / "concurrent-artifacts")
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                batch_id, _, ctx = await _seed_one_yes_gap(conn, storage, workspace_id=workspace_id)
            http = _OrganizationsHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            def resolver() -> SumbleDiscoveryGapResolver:
                return SumbleDiscoveryGapResolver(
                    enabled=True,
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    conn_factory=transaction,
                    client_factory=client_factory,
                )

            await asyncio.gather(
                resolver().ensure_terminal(ctx, batch_id),
                resolver().ensure_terminal(ctx, batch_id),
            )
            replay = await resolver().ensure_terminal(ctx, batch_id)
            assert replay.outcome is SumbleDiscoveryGapOutcome.COMPLETE
            assert len(http.calls) == 1
            async with engine.begin() as conn:
                operations = await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
                assert len(operations) == 1
                assert operations[0].state.value == "succeeded"

    run_async(scenario())


def test_unclear_discovery_criteria_terminalize_gap_without_sumble_spend(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace_id = "ws-preseal-sumble-unclear"
        storage = FsStorage(tmp_path / "unclear-artifacts")
        async with rollback_conn() as conn:
            batch_id, _, _ = await _seed_terminal_batch(conn, storage, workspace_id)
            materialized = await ExaWebsetsD4Materializer(
                storage=storage,
                conn_factory=conn_session_factory(conn),
            ).materialize(workspace_id=workspace_id, batch_id=batch_id)
            assert len(materialized.account_ids) == 1
            account_id = materialized.account_ids[0]
            http = _OrganizationsHttp()

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            resolver = SumbleDiscoveryGapResolver(
                enabled=True,
                api_key=SecretStr("fixture"),
                storage=storage,
                conn_factory=conn_session_factory(conn),
                client_factory=client_factory,
            )
            ctx = await _phase_context(conn, workspace_id=workspace_id, batch_id=batch_id)
            progress = await resolver.ensure_terminal(ctx, batch_id)
            assert progress.outcome is SumbleDiscoveryGapOutcome.COMPLETE
            assert progress.provider_calls == 0
            assert progress.fields_blocked_by_policy == 1
            assert http.calls == []
            assert (
                await list_discovery_gap_operations(
                    conn, workspace_id=workspace_id, batch_id=batch_id
                )
                == ()
            )
            industry = await get_discovery_field_resolution(
                conn,
                workspace_id=workspace_id,
                batch_id=batch_id,
                account_entity_id=account_id,
                logical_field_key="discovery.industry",
            )
            assert industry is not None
            assert industry.state is DiscoveryFieldResolutionState.BLOCKED_BY_POLICY
            assert industry.reason_code == "required_field_waterfall_ineligible:criteria_unclear"

    run_async(scenario())
