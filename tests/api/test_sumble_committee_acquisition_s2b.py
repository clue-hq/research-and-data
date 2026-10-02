"""S2B real-DB durability, wait, replay, spend, privacy, and DSAR acceptance."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.sumble_account_gaps import SUMBLE_V9_CONTRACT_VERSION
from clue_api.sumble_committee_acquisition import (
    SUMBLE_COMMITTEE_CONTRACT_VERSION,
    SUMBLE_COMMITTEE_POLICY_VERSION,
    SUMBLE_COMMITTEE_PRICING_VERSION,
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_wake import SumbleCommitteeWakeWorker
from clue_core import (
    CommitteeAcquisitionRequest,
    CommitteeAcquisitionState,
    CommitteeSpendOutcome,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchDirectivePin,
    ResearchEffortPolicy,
    ResearchMode,
    ResearchPrivacyPolicy,
    ResearchSourcePolicy,
    RunId,
    account_claim,
    research_directive_digest,
)
from clue_research.claimstore import insert_claim
from clue_research.discovery_scoring.tiering import TIER_FIELD, DiscoverySelectionPolicy
from clue_research.durable import (
    enumerate_discovery_subject_artifacts,
    insert_account_run,
    list_committee_acquisition_attempts,
    list_committee_acquisition_snapshots,
    pin_account_run_research_directive,
    seal_discovery_batch,
    tombstone_discovery_subject_artifacts,
)
from clue_research.identity import stamp_reuse
from clue_research.resolvers.http import ProviderResponseError
from clue_research.resolvers.sumble import SUMBLE_API_VERSION
from clue_research.resolvers.sumble.committee_transport import SumbleRawPayload
from clue_research.resolvers.sumble.people import SumblePeopleResponse
from clue_research.resolvers.sumble.teams import SumbleTeamsResponse
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_spine import confirm_project_product, create_product
from clue_storage import FsStorage
from tests.api.test_exa_targeted_enrichment_e1 import _advance_sealed_run_to_deep
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import _complete_batch, _start_batch

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers" / "sumble" / "v9"


def test_s2_uses_the_same_reviewed_v9_contract_as_s1() -> None:
    assert SUMBLE_COMMITTEE_CONTRACT_VERSION == SUMBLE_V9_CONTRACT_VERSION


def _payload(name: str) -> SumbleRawPayload:
    return json.loads((_FIXTURES / name).read_text())


class _CommitteeTransport:
    def __init__(self, *, crash_on_teams: BaseException | None = None) -> None:
        self.calls: list[str] = []
        # Provider operation ids are globally unique in the durable substrate.  Recorded fixture
        # ids describe the response shape, but reusing them for every fake operation makes this
        # transport invalid on a realistically pre-populated V0 database.  Give each transport
        # instance provider-like unique ids while retaining every other captured field.
        self._teams_operation_id = str(uuid4())
        self._people_request_id = str(uuid4())
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
        payload["id"] = self._teams_operation_id
        return SumbleTeamsResponse.model_validate(payload), payload

    def submit_people(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        del body
        assert maximum_credits == 16
        self.calls.append("people_submit")
        payload = next(self._people)
        payload["request_id"] = self._people_request_id
        return SumblePeopleResponse.model_validate(payload), payload

    def poll_people(
        self, request_id: str, *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        assert request_id == self._people_request_id
        assert maximum_credits == 16
        self.calls.append("people_poll")
        payload = next(self._people)
        payload["request_id"] = self._people_request_id
        return SumblePeopleResponse.model_validate(payload), payload


class _ProcessCrash(BaseException):
    pass


class _CrashBeforeDispatchRateLimiter:
    async def acquire(self, source_key: str, *, tokens: int = 1) -> bool:
        assert source_key == "sumble"
        assert tokens == 1
        raise _ProcessCrash()


class _CrashAfterResponseCoordinator(SumbleCommitteeAcquisitionCoordinator):
    """Simulate SIGKILL after the raw response commit but before snapshot folding."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._crashed = False

    async def _persist_response_snapshot(self, *args: Any, **kwargs: Any) -> None:
        if not self._crashed:
            self._crashed = True
            raise _ProcessCrash()
        await super()._persist_response_snapshot(*args, **kwargs)


class _ChargedSchemaDriftTransport(_CommitteeTransport):
    def search_teams(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumbleTeamsResponse, SumbleRawPayload]:
        del body
        assert maximum_credits == 12
        self.calls.append("teams")
        payload = _payload("teams_succeeded.json")
        payload["id"] = self._teams_operation_id
        payload["teams"][0]["team_id"] = None
        return SumbleTeamsResponse.model_validate(payload), payload


async def _setup(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    strict_s2d: bool = False,
    s2d_criterion_state: str = "yes",
    account_tier: str = "high",
    tier_claim_source_tier: int = 1,
) -> CommitteeAcquisitionRequest:
    # Production composition seeds the shared source registry before any provider path is
    # reachable. S2D's real pre-spend gate now validates the exact Teams/People keys, so this
    # shared fixture must reproduce that bootstrap rather than relying on tier-only admission.
    await load_client_knowledge_pack(conn)
    await seed_source_manifests(conn)
    strategy = (
        {
            "scoring_mode": "disabled",
            "selection_mode": "discovery_criteria",
            "must_have_criteria": ["is an independent practice"],
            "approved_tier": account_tier,
        }
        if strict_s2d
        else None
    )
    started = await _start_batch(
        conn,
        storage,
        workspace_id=workspace_id,
        discovery_strategy=strategy,
    )
    brand_id = str(
        (
            await conn.execute(
                text(
                    "SELECT brand_id FROM project WHERE project_id=:project_id "
                    "AND workspace_id=:workspace_id"
                ),
                {"project_id": started.project_id, "workspace_id": workspace_id},
            )
        ).scalar_one()
    )
    product = await create_product(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        name="S2B committee test product",
    )
    confirmed_project = await confirm_project_product(
        conn,
        workspace_id=workspace_id,
        project_id=started.project_id,
        product_id=product.product_id,
    )
    assert confirmed_project is not None
    ready = await _complete_batch(
        conn,
        storage,
        started=started,
        criterion_state=s2d_criterion_state if strict_s2d else None,
        resolve_all_required_fields=strict_s2d,
    )
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
                "tier": account_tier,
                "decision_basis": "discovery_criteria",
                "selection_policy_version": (
                    DiscoverySelectionPolicy.from_slot(strategy).policy_version
                    if strategy is not None
                    else "discovery-selection-v1"
                ),
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
            source_tier=tier_claim_source_tier,
            extraction_method=(
                ExtractionMethod.LLM_SYNTHESIS
                if tier_claim_source_tier == 4
                else ExtractionMethod.HUMAN
            ),
            source_url=(
                "https://example.com/tier-decision" if tier_claim_source_tier == 4 else None
            ),
            evidence_span=(
                "Tier-4 source supports this exact selected account tier."
                if tier_claim_source_tier == 4
                else None
            ),
            confidence=1,
            run_id=RunId(started.project_run_id),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        ),
        workspace_id=workspace_id,
    )
    await insert_claim(conn, tier)
    account_id = EntityId(ready.account_id)
    directive_id = ResearchDirectiveId(
        uuid5(UUID("99c38cee-483a-5b14-b9fb-edba3222edb9"), workspace_id)
    )
    product_id = product.product_id
    directive_body = ResearchDirectiveBody(
        account_scope=ResearchAccountScope(explicit_account_ids=(account_id,)),
        field_keys=("core.employee_count",),
        committee_plan=ResearchCommitteePlan(
            functions=("Operations", "Administration"),
            levels=("Director", "VP"),
            personas=("champion", "economic_buyer"),
            candidate_cap=2,
        ),
        source_policy=ResearchSourcePolicy(allowed_source_keys=("sumble_teams", "sumble_people")),
        privacy_policy=ResearchPrivacyPolicy(),
        effort_policy=ResearchEffortPolicy(
            tier="high",
            max_depth=1,
            max_fanout=2,
            budget_cap_cents=Decimal(14),
            budget_envelope_ref="budget:s2b-test-v1",
            recursion_policy_ref="recursion:s2b-test-v1",
            freshness_policy_ref="freshness:s2b-test-v1",
        ),
    )
    source_turn_ref = "turn:s2b-test-directive"
    digest = research_directive_digest(
        directive_id=directive_id,
        workspace_id=workspace_id,
        project_id=started.project_id,
        product_id=product_id,
        icp_key="independent-specialty-practices",
        icp_version=1,
        version=1,
        body=directive_body,
        memory_refs=(),
        source_turn_ref=source_turn_ref,
        predecessor_id=None,
    )
    draft_operation_id = uuid5(directive_id, "draft")
    confirmation_operation_id = uuid5(directive_id, "confirm")
    await conn.execute(
        text(
            "INSERT INTO account_research_directive "
            "(directive_id, workspace_id, project_id, product_id, icp_key, icp_version, "
            "version, status, content_json, memory_refs, created_by, source_turn_ref, "
            "draft_operation_id, draft_request_sha256, confirmation_operation_id, "
            "confirmed_by, confirming_turn_ref, canonical_json_sha256, confirmed_at) "
            "VALUES (:directive_id, :workspace_id, :project_id, :product_id, :icp_key, 1, "
            "1, 'confirmed', CAST(:content_json AS jsonb), '[]'::jsonb, 'test-fixture', "
            ":source_turn_ref, :draft_operation_id, :draft_request_sha256, "
            ":confirmation_operation_id, 'human:s2b-test', 'turn:s2b-test-confirm', "
            ":digest, now())"
        ),
        {
            "directive_id": directive_id,
            "workspace_id": workspace_id,
            "project_id": started.project_id,
            "product_id": product_id,
            "icp_key": "independent-specialty-practices",
            "content_json": directive_body.model_dump_json(),
            "source_turn_ref": source_turn_ref,
            "draft_operation_id": draft_operation_id,
            "draft_request_sha256": "b" * 64,
            "confirmation_operation_id": confirmation_operation_id,
            "digest": digest,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO account_research_directive_account "
            "(directive_id, workspace_id, account_id, scope_kind) "
            "VALUES (:directive_id, :workspace_id, :account_id, 'explicit')"
        ),
        {
            "directive_id": directive_id,
            "workspace_id": workspace_id,
            "account_id": account_id,
        },
    )
    directive_pin = ResearchDirectivePin(
        directive_id=directive_id,
        directive_ref=f"research-directive:{directive_id}:v1",
        version=1,
        canonical_json_sha256=digest,
        account_id=account_id,
    )
    account_run_id = RunId(started.project_run_id)
    await insert_account_run(
        conn,
        account_run_id=account_run_id,
        project_run_id=ProjectRunId(started.project_run_id),
        entity_id=account_id,
        tier="high",
    )
    await pin_account_run_research_directive(
        conn,
        account_run_id=account_run_id,
        pin=directive_pin,
    )
    return CommitteeAcquisitionRequest(
        workspace_id=workspace_id,
        project_id=started.project_id,
        project_run_id=ProjectRunId(started.project_run_id),
        icp_key="independent-specialty-practices",
        icp_version=1,
        discovery_batch_id=started.batch_id,
        discovery_seal_sha256=seal.seal_sha256,
        account_id=account_id,
        tier_claim_id=tier.id,
        committee_plan_ref="committee-plan:s2b-test:v1",
        research_direction_ref=directive_pin.directive_ref,
        research_directive=directive_pin,
        organization_identity_ref="account-gap-snapshot:sumble_organizations:test",
        provider_organization_id="1726684",
        provider_api_version=SUMBLE_API_VERSION,
        provider_contract_version=SUMBLE_COMMITTEE_CONTRACT_VERSION,
        pricing_policy_version=SUMBLE_COMMITTEE_PRICING_VERSION,
        committee_policy_version=SUMBLE_COMMITTEE_POLICY_VERSION,
        observation_window=f"project-run:{started.project_run_id}:committee:s2b-test",
        provider_filter_expression="job_function EQ 'Operations'",
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

            offered: set[ProjectRunId] = set()

            async def wake(project_run_id: ProjectRunId) -> bool:
                # A developer may intentionally run this rollback-isolated test against a
                # database that also contains real pending fleet work.  Model queue ownership
                # for this fixture only: unrelated project runs are not this test's offers and
                # must not affect its wake count.
                if project_run_id != request.project_run_id:
                    return False
                if project_run_id in offered:
                    return False
                offered.add(project_run_id)
                return True

            wake_worker = SumbleCommitteeWakeWorker(
                project_run_waker=wake,
                conn_factory=same_connection,
            )
            assert await wake_worker.run_due(now=datetime.now(UTC)) == 0

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
            assert await wake_worker.run_due(now=datetime.now(UTC)) == 1
            assert offered == {request.project_run_id}
            assert await wake_worker.run_due(now=datetime.now(UTC)) == 0
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
            erased_replay = await coordinator.start(preflight)
            assert erased_replay.outcome is SumbleCommitteeOutcome.REPLAYED
            assert len(transport.calls) == 4
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


def test_s2b_recovers_a_committed_response_without_repeating_the_dispatch(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2b-response-crash")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _CommitteeTransport()
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            crashed = _CrashAfterResponseCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            with pytest.raises(_ProcessCrash):
                await crashed.start(preflight)
            assert transport.calls == ["teams"]
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=request.workspace_id,
                operation_id=(
                    await conn.execute(
                        text(
                            "SELECT id FROM committee_acquisition_operation "
                            "WHERE workspace_id=:workspace_id"
                        ),
                        {"workspace_id": request.workspace_id},
                    )
                ).scalar_one(),
            )
            assert len(attempts) == 1
            assert attempts[0].state.value == "responded"
            assert attempts[0].response_artifact_key is not None
            assert await storage.exists(attempts[0].response_artifact_key)

            recovered = await SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            ).start(preflight)
            assert recovered.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            assert recovered.provider_calls == 1
            assert transport.calls == ["teams", "people_submit"]
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=request.workspace_id,
                operation_id=recovered.operation.operation_id,
            )
            teams = next(item for item in snapshots if item.source_key == "sumble_teams")
            assert teams.state.value == "succeeded"
            assert teams.response_artifact_key == attempts[0].response_artifact_key

    run_async(scenario())


def test_s2b_charged_schema_drift_retains_response_charge_and_never_retries(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2b-charged-drift")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            spent_before = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": request.project_run_id},
                    )
                ).scalar_one()
            )
            transport = _ChargedSchemaDriftTransport()
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            unknown = await coordinator.start(preflight)
            assert unknown.outcome is SumbleCommitteeOutcome.SPEND_OUTCOME_UNKNOWN
            assert unknown.operation.provider_units_charged == Decimal(12)
            assert unknown.operation.cost_cents_charged == Decimal(6)
            assert transport.calls == ["teams"]
            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=request.workspace_id,
                operation_id=unknown.operation.operation_id,
            )
            assert len(attempts) == 1
            assert attempts[0].state.value == "responded"
            assert attempts[0].provider_units_charged == Decimal(12)
            assert attempts[0].response_artifact_key is not None
            assert await storage.exists(attempts[0].response_artifact_key)
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=request.workspace_id,
                operation_id=unknown.operation.operation_id,
            )
            teams = next(item for item in snapshots if item.source_key == "sumble_teams")
            assert teams.state.value == "spend_outcome_unknown"
            assert teams.response_artifact_key == attempts[0].response_artifact_key
            assert teams.provider_units_charged == Decimal(12)
            spent_after = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": request.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent_after - spent_before == Decimal(6)

            replay = await coordinator.start(preflight)
            assert replay.outcome is SumbleCommitteeOutcome.SPEND_OUTCOME_UNKNOWN
            assert transport.calls == ["teams"]

    run_async(scenario())


def test_s2b_people_failed_is_terminal_uncharged_and_replays_without_poll(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2b-people-failed")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _CommitteeTransport()
            transport._people = iter(  # noqa: SLF001 - recorded provider state fixture
                (_payload("people_pending.json"), _payload("people_failed.json"))
            )
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            pending = await coordinator.start(preflight)
            assert pending.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            await conn.execute(
                text("UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"),
                {
                    "id": pending.operation.operation_id,
                    "past": datetime.now(UTC) - timedelta(seconds=1),
                },
            )
            failed = await coordinator.start(preflight)
            assert failed.outcome is SumbleCommitteeOutcome.FAILED_TERMINAL
            assert failed.operation.provider_units_charged == Decimal(12)
            assert failed.operation.cost_cents_charged == Decimal(6)
            assert transport.calls == ["teams", "people_submit", "people_poll"]
            replay = await coordinator.start(preflight)
            assert replay.outcome is SumbleCommitteeOutcome.FAILED_TERMINAL
            assert transport.calls == ["teams", "people_submit", "people_poll"]

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


def test_s2b_process_crash_before_dispatch_resumes_without_false_spend_or_duplicate(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2b-pre-dispatch-crash")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _CommitteeTransport()
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            crashed = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                rate_limiter=_CrashBeforeDispatchRateLimiter(),
            )
            with pytest.raises(_ProcessCrash):
                await crashed.start(preflight)
            assert transport.calls == []
            operation_id = (
                await conn.execute(
                    text(
                        "SELECT id FROM committee_acquisition_operation "
                        "WHERE workspace_id=:workspace_id"
                    ),
                    {"workspace_id": request.workspace_id},
                )
            ).scalar_one()
            assert (
                await list_committee_acquisition_attempts(
                    conn,
                    workspace_id=request.workspace_id,
                    operation_id=operation_id,
                )
                == ()
            )

            resumed = await SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            ).start(preflight)
            assert resumed.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            assert resumed.operation.provider_units_charged == Decimal(12)
            assert transport.calls == ["teams", "people_submit"]

    run_async(scenario())


def test_s2b_deterministic_http_rejection_is_terminal_uncharged_with_retained_diagnostic(
    tmp_path: Path,
) -> None:
    """A validated provider 400/422 is a zero-credit refusal, never an unknown spend.

    The live R10 Teams HTTP 400 was collapsed into ``spend_outcome_unknown`` and had to be
    replayed manually just to read the status. The coordinator now persists the status and the
    provider's own bounded error body as durable rejection evidence.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2b-http-400")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            rejection = ProviderResponseError(
                "sumble_teams: HTTP 400 from https://api.sumble.com/v9/teams",
                status_code=400,
                body_excerpt='{"detail":[{"loc":["filter","query"],"msg":"invalid filter"}]}',
            )
            transport = _CommitteeTransport(crash_on_teams=rejection)
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            rejected = await coordinator.start(preflight)
            assert rejected.outcome is SumbleCommitteeOutcome.FAILED_TERMINAL
            assert rejected.operation.state is CommitteeAcquisitionState.FAILED_TERMINAL
            assert rejected.operation.spend_outcome is CommitteeSpendOutcome.NOT_CHARGED
            assert rejected.operation.provider_units_charged == Decimal(0)
            assert rejected.operation.failure_code == "sumble_teams_provider_rejected_http_400"

            attempts = await list_committee_acquisition_attempts(
                conn,
                workspace_id=request.workspace_id,
                operation_id=rejected.operation.operation_id,
            )
            terminal = [item for item in attempts if item.state.value == "responded"]
            assert len(terminal) == 1
            assert terminal[0].failure_code == "sumble_teams_provider_rejected_http_400"
            assert terminal[0].response_artifact_key is not None
            stored = await storage.get(terminal[0].response_artifact_key)
            evidence = json.loads(stored)
            assert evidence["provider_rejection"]["http_status"] == 400
            assert "invalid filter" in evidence["provider_rejection"]["body_excerpt"]

            # The deterministic rejection is durable: a replay makes no further provider call.
            replay = await coordinator.start(preflight)
            assert replay.outcome is SumbleCommitteeOutcome.FAILED_TERMINAL
            assert transport.calls == ["teams"]

    run_async(scenario())
