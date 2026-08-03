"""S2B real-DB durability, wait, replay, spend, privacy, and DSAR acceptance."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.sumble_committee_acquisition import (
    SUMBLE_COMMITTEE_CONTRACT_VERSION,
    SUMBLE_COMMITTEE_POLICY_VERSION,
    SUMBLE_COMMITTEE_PRICING_VERSION,
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    compile_sumble_committee_preflight,
)
from clue_core import (
    CommitteeAcquisitionRequest,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
)
from clue_research.claimstore import insert_claim
from clue_research.discovery_scoring.tiering import TIER_FIELD
from clue_research.durable import (
    enumerate_discovery_subject_artifacts,
    list_committee_acquisition_attempts,
    list_committee_acquisition_snapshots,
    seal_discovery_batch,
    tombstone_discovery_subject_artifacts,
)
from clue_research.identity import stamp_reuse
from clue_research.resolvers.sumble import SUMBLE_API_VERSION
from clue_research.resolvers.sumble.committee_transport import SumbleRawPayload
from clue_research.resolvers.sumble.people import SumblePeopleResponse
from clue_research.resolvers.sumble.teams import SumbleTeamsResponse
from clue_storage import FsStorage
from tests.api.test_exa_targeted_enrichment_e1 import _advance_sealed_run_to_deep
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import _complete_batch, _start_batch

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers" / "sumble" / "v9"


def _payload(name: str) -> SumbleRawPayload:
    return json.loads((_FIXTURES / name).read_text())


class _CommitteeTransport:
    def __init__(self, *, crash_on_teams: BaseException | None = None) -> None:
        self.calls: list[str] = []
        self._people = iter(
            (
                _payload("people_pending.json"),
                _payload("people_running.json"),
                _payload("people_succeeded.json"),
            )
        )
        self._crash_on_teams = crash_on_teams

    def search_teams(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumbleTeamsResponse, SumbleRawPayload]:
        del body
        assert maximum_credits == 12
        self.calls.append("teams")
        if self._crash_on_teams is not None:
            raise self._crash_on_teams
        payload = _payload("teams_succeeded.json")
        return SumbleTeamsResponse.model_validate(payload), payload

    def submit_people(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        del body
        assert maximum_credits == 16
        self.calls.append("people_submit")
        payload = next(self._people)
        return SumblePeopleResponse.model_validate(payload), payload

    def poll_people(
        self, request_id: str, *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        assert request_id == "019fc850-0000-7000-8000-000000000101"
        assert maximum_credits == 16
        self.calls.append("people_poll")
        payload = next(self._people)
        return SumblePeopleResponse.model_validate(payload), payload


class _ProcessCrash(BaseException):
    pass


async def _setup(
    conn: AsyncConnection, storage: FsStorage, *, workspace_id: str
) -> CommitteeAcquisitionRequest:
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
                "decision_version": "s2b-test-decision",
                "cutoff_version": "s2b-test-decision",
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
    return CommitteeAcquisitionRequest(
        workspace_id=workspace_id,
        project_id=started.project_id,
        project_run_id=ProjectRunId(started.project_run_id),
        icp_key="independent-specialty-practices",
        icp_version=1,
        discovery_batch_id=started.batch_id,
        discovery_seal_sha256=seal.seal_sha256,
        account_id=EntityId(ready.account_id),
        tier_claim_id=tier.id,
        committee_plan_ref="committee-plan:s2b-test:v1",
        research_direction_ref="research-direction:s2b-test:v3",
        organization_identity_ref="account-gap-snapshot:sumble_organizations:test",
        provider_organization_id="1726684",
        provider_api_version=SUMBLE_API_VERSION,
        provider_contract_version=SUMBLE_COMMITTEE_CONTRACT_VERSION,
        pricing_policy_version=SUMBLE_COMMITTEE_PRICING_VERSION,
        committee_policy_version=SUMBLE_COMMITTEE_POLICY_VERSION,
        observation_window=f"project-run:{started.project_run_id}:committee:s2b-test",
        provider_filter_expression="job_function IN ('Operations', 'Administration')",
        team_limit=1,
        related_people_per_team=2,
        jobs_per_team=2,
        people_limit=2,
        provider_credit_cap=28,
        money_budget_cap_cents=Decimal(14),
    )


def test_s2b_async_wait_charge_settlement_zero_call_replay_and_dsar(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2b-committee")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _CommitteeTransport()
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            spent_before = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": request.project_run_id},
                    )
                ).scalar_one()
            )
            pending = await coordinator.start(preflight)
            assert pending.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            assert transport.calls == ["teams", "people_submit"]
            assert pending.operation.provider_units_charged == Decimal(12)

            not_due = await coordinator.start(preflight)
            assert not_due.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            assert transport.calls == ["teams", "people_submit"]

            await conn.execute(
                text("UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"),
                {
                    "id": pending.operation.operation_id,
                    "past": datetime.now(UTC) - timedelta(seconds=1),
                },
            )
            running = await coordinator.start(preflight)
            assert running.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            assert transport.calls[-1] == "people_poll"
            await conn.execute(
                text("UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"),
                {
                    "id": pending.operation.operation_id,
                    "past": datetime.now(UTC) - timedelta(seconds=1),
                },
            )
            ready = await coordinator.start(preflight)
            assert ready.outcome is SumbleCommitteeOutcome.READY
            assert ready.operation.provider_units_reserved == Decimal(28)
            assert ready.operation.provider_units_charged == Decimal(28)
            assert ready.operation.cost_cents_charged == Decimal(14)
            assert ready.operation.receipt_manifest_key is not None
            assert transport.calls == [
                "teams",
                "people_submit",
                "people_poll",
                "people_poll",
            ]

            replay = await coordinator.start(preflight)
            assert replay.outcome is SumbleCommitteeOutcome.REPLAYED
            assert len(transport.calls) == 4
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=request.workspace_id,
                operation_id=ready.operation.operation_id,
            )
            assert {item.source_key for item in snapshots} == {"sumble_teams", "sumble_people"}
            assert all(item.state.value == "succeeded" for item in snapshots)
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=request.workspace_id,
                operation_id=ready.operation.operation_id,
            )
            assert [item.kind.value for item in attempts] == [
                "teams_search",
                "people_submit",
                "people_poll",
                "people_poll",
            ]
            assert [item.provider_units_charged for item in attempts] == [
                Decimal(12),
                Decimal(0),
                Decimal(0),
                Decimal(16),
            ]
            spent_after = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": request.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_after - spent_before == Decimal(14)

            artifacts = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=request.workspace_id,
                subject_kind="account",
                subject_entity_id=request.account_id,
            )
            s2b_edges = {
                item.reference_kind
                for item in artifacts
                if item.reference_kind.startswith("sumble_")
            }
            assert s2b_edges == {
                "sumble_committee_input",
                "sumble_teams_request",
                "sumble_people_request",
                "sumble_teams_response",
                "sumble_people_response",
                "sumble_people_poll_request",
                "sumble_committee_receipt",
            }
            await tombstone_discovery_subject_artifacts(
                conn,
                workspace_id=request.workspace_id,
                subject_kind="account",
                subject_entity_id=request.account_id,
            )
            assert (
                await enumerate_discovery_subject_artifacts(
                    conn,
                    workspace_id=request.workspace_id,
                    subject_kind="account",
                    subject_entity_id=request.account_id,
                )
                == ()
            )
            terminal = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="terminal committee acquisition operation"):
                await conn.execute(
                    text(
                        "UPDATE committee_acquisition_operation SET provider_units_charged=0 "
                        "WHERE id=:id"
                    ),
                    {"id": ready.operation.operation_id},
                )
            await terminal.rollback()

    run_async(scenario())


def test_s2b_process_crash_quarantines_dispatch_and_never_retries(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2b-crash")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _CommitteeTransport(crash_on_teams=_ProcessCrash())
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            with pytest.raises(_ProcessCrash):
                await coordinator.start(preflight)
            assert transport.calls == ["teams"]
            recovered = await coordinator.start(preflight)
            assert recovered.outcome is SumbleCommitteeOutcome.SPEND_OUTCOME_UNKNOWN
            assert transport.calls == ["teams"]
            replay = await coordinator.start(preflight)
            assert replay.outcome is SumbleCommitteeOutcome.SPEND_OUTCOME_UNKNOWN
            assert transport.calls == ["teams"]
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=request.workspace_id,
                operation_id=recovered.operation.operation_id,
            )
            assert len(attempts) == 1
            assert attempts[0].state.value == "spend_outcome_unknown"
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=request.workspace_id,
                operation_id=recovered.operation.operation_id,
            )
            assert next(
                item for item in snapshots if item.source_key == "sumble_teams"
            ).state.value == ("spend_outcome_unknown")

    run_async(scenario())
