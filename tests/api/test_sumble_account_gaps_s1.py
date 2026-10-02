"""S1 Sumble account-gap durability, provider wire, claims, conflict, and replay."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.comprehensive_research_contract import COMPREHENSIVE_ACCOUNT_FIELD_SOURCES
from clue_api.sumble_account_gaps import (
    _SOURCE_BY_FIELD,
    SumbleAccountGapCoordinator,
    SumbleAccountGapEligibilityError,
    SumbleAccountGapFieldsUnrequestable,
    SumbleAccountGapNotEligible,
    SumbleAccountGapOutcome,
    SumbleAccountGapStarter,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import (
    AccountGapOperationId,
    AccountGapOperationState,
    AccountGapSnapshotState,
    AccountGapSpendOutcome,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
    new_operation_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for, current_value, insert_claim
from clue_research.discovery_scoring.tiering import TIER_FIELD
from clue_research.durable import (
    enumerate_discovery_subject_artifacts,
    get_account_gap_operation,
    list_account_gap_field_results,
    list_account_gap_snapshots,
    seal_discovery_batch,
    tombstone_discovery_subject_artifacts,
)
from clue_research.identity import stamp_reuse
from clue_research.resolvers.http import ProviderResponseError
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    ORGANIZATIONS_SOURCE_KEY,
    SUMBLE_SOURCE_KEYS,
    SUMBLE_SUPPORTED_FIELD_KEYS_BY_SOURCE,
    TECH_STACK_SOURCE_KEY,
    SumbleClient,
    SumbleCreditBudget,
)
from clue_storage import FsStorage
from clue_toolbelt import PreconditionFailed, ToolContext, invoke_tool
from tests._run_lineage import assert_written_claims_are_attributable
from tests.api.test_exa_targeted_enrichment_e1 import _advance_sealed_run_to_deep
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.durable.test_discovery_batch_d1 import _complete_batch, _start_batch

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "clue_trial" / "sumble"


class _SumbleHttp:
    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append({"url": url, **kwargs})
        if url.endswith("/organizations"):
            return {
                "id": "s1-org-request",
                "credits_used": 1,
                "credits_remaining": 999,
                "organizations": [
                    {
                        "input": {"url": self.domain},
                        "attributes": {
                            "id": 1726684,
                            "name": "Insight Health AI",
                            "url": self.domain,
                            "sumble_url": "https://sumble.com/l/org/insight-health-ai",
                        },
                        "entities": [],
                    }
                ],
                "matched_count": 1,
                "total": 1,
            }
        if url.endswith("/jobs"):
            return json.loads((_FIXTURES / "jobs_engineering.json").read_text())
        if url.endswith("/techs"):
            return json.loads((_FIXTURES / "tech_stack_confirmed.json").read_text())
        raise AssertionError(f"unexpected Sumble URL: {url}")


async def _seed_selected_high_tier_account(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    workspace_id: str,
    account_tier: str = "high",
    tier_claim_source_tier: int = 1,
) -> tuple[Any, Any]:
    """Seal one discovered account, advance its run to deep, and record the human tier decision."""

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
                "tier": account_tier,
                "decision_basis": "discovery_criteria",
                "selection_policy_version": "discovery-selection-v1",
                "decision_version": "s1-test-decision",
                "cutoff_version": "s1-test-decision",
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
    return started, ready


def test_s1_real_db_three_snapshots_conflict_preservation_and_zero_call_replay(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_id = "ws-s1-sumble"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn,
                storage,
                workspace_id=workspace_id,
                account_tier="tier4",
                tier_claim_source_tier=4,
            )
            exa_tech = account_claim(
                entity_id=EntityId(ready.account_id),
                field_key="core.primary_tech_stack",
                value_json=["Legacy Platform"],
                source_tier=2,
                extraction_method=ExtractionMethod.API,
                confidence=0.5,
                run_id=RunId(started.project_run_id),
                research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                source_url="https://insighthealth.ai/technology",
                evidence_span="Exa returned Legacy Platform as a possible technology.",
            ).model_copy(update={"source_key": "exa_websets"})
            exa_claim_id = await insert_claim(conn, exa_tech)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _SumbleHttp("insighthealth.ai")

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            coordinator = SumbleAccountGapCoordinator(
                api_key=SecretStr("fixture"),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                client_factory=client_factory,
            )
            starter = SumbleAccountGapStarter(
                coordinator=coordinator,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            with pytest.raises(
                SumbleAccountGapEligibilityError,
                match="already confidently resolved",
            ):
                await starter.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={"core.primary_domain": Decimal(1)},
                    provider_credit_cap=1,
                    allow_unbounded_tech=False,
                )
            with pytest.raises(
                SumbleAccountGapEligibilityError,
                match="does not justify",
            ):
                await starter.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={"account.hiring_velocity_eng": Decimal("0.5")},
                    provider_credit_cap=2,
                    allow_unbounded_tech=False,
                )
            with pytest.raises(
                SumbleAccountGapEligibilityError,
                match="explicit unbounded-call approval",
            ):
                await starter.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={"core.primary_tech_stack": Decimal(3)},
                    provider_credit_cap=3,
                    allow_unbounded_tech=False,
                )
            assert http.calls == []
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0
            registry = build_toolbelt(
                storage=storage,
                gateway=None,
                conn_factory=same_connection,
                account_gap_enrichment_starter=starter,
            )
            body = {
                "project_run_id": str(started.project_run_id),
                "account_entity_id": str(ready.account_id),
                "field_expected_value_credits": {
                    "account.hiring_velocity_eng": "5",
                    "core.primary_tech_stack": "5",
                },
                "provider_credit_cap": 5,
                "allow_unbounded_tech": True,
            }
            with pytest.raises(PreconditionFailed) as quarantine:
                await invoke_tool(
                    registry,
                    "enrich_account_gaps",
                    body,
                    ToolContext(
                        workspace_id=workspace_id,
                        actor="agent",
                        conn_factory=same_connection,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=86400,
                )
            assert quarantine.value.reason_codes == ("entity_research_agent_not_composed",)
            assert http.calls == []

            # R1 quarantines only new-run composition. The provider/durability/claim service stays
            # directly testable and is the infrastructure the governed R4 action reuses.
            result = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={
                    "account.hiring_velocity_eng": Decimal(5),
                    "core.primary_tech_stack": Decimal(5),
                },
                provider_credit_cap=5,
                allow_unbounded_tech=True,
            )
            assert result.outcome is SumbleAccountGapOutcome.COMPLETED
            assert len(http.calls) == 3
            operation_id = AccountGapOperationId(result.operation.operation_id)
            operation = await get_account_gap_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=operation_id,
            )
            assert operation is not None
            assert operation.provider_units_reserved == Decimal(5)
            assert operation.provider_units_charged == Decimal(5)
            assert operation.cost_cents_charged == Decimal("2.5")
            snapshots = await list_account_gap_snapshots(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            assert {row.source_key for row in snapshots} == {
                ORGANIZATIONS_SOURCE_KEY,
                JOBS_SOURCE_KEY,
                TECH_STACK_SOURCE_KEY,
            }
            assert all(row.response_artifact_key for row in snapshots)

            fields = await list_account_gap_field_results(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            by_field = {str(row.field_key): row for row in fields}
            assert by_field["account.hiring_velocity_eng"].state.value == "resolved"
            tech_result = by_field["core.primary_tech_stack"]
            assert tech_result.state.value == "conflict"
            assert exa_claim_id in tech_result.conflicting_claim_ids
            assert tech_result.sumble_claim_id in tech_result.conflicting_claim_ids

            tech_claims = await claims_for(
                conn,
                EntityId(ready.account_id),
                "core.primary_tech_stack",
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert {claim.source_key for claim in tech_claims} == {
                "exa_websets",
                TECH_STACK_SOURCE_KEY,
            }
            merged = await current_value(
                conn,
                EntityId(ready.account_id),
                "core.primary_tech_stack",
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert merged is not None and merged.conflict is True

            # FI-2 P2: every Sumble claim carries the project run as its run_id, and that run is
            # registered so the project lens can back-join it.
            await assert_written_claims_are_attributable(
                conn,
                started.project_run_id,
                kind="enrichment",
                workspace_id=workspace_id,
                project_id=started.project_id,
                project_run_id=started.project_run_id,
            )

            spent = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": started.project_run_id},
                    )
                ).scalar_one()
            )
            assert spent == Decimal("2.5")

            replay = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={
                    "account.hiring_velocity_eng": Decimal(5),
                    "core.primary_tech_stack": Decimal(5),
                },
                provider_credit_cap=5,
                allow_unbounded_tech=True,
            )
            assert replay.outcome is SumbleAccountGapOutcome.REPLAYED
            assert len(http.calls) == 3
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 1
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim WHERE entity_id=:entity_id "
                        "AND source_key LIKE 'sumble_%'"
                    ),
                    {"entity_id": ready.account_id},
                )
            ).scalar_one() == 2

            terminal_operation = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="terminal account-gap operation is immutable"):
                await conn.execute(
                    text(
                        "UPDATE account_gap_operation SET provider_units_charged=0 "
                        "WHERE id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            await terminal_operation.rollback()
            terminal_field = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="terminal account-gap field outcome is immutable"):
                await conn.execute(
                    text(
                        "UPDATE account_gap_field_result SET reason_code='late_mutation' "
                        "WHERE operation_id=:operation_id"
                    ),
                    {"operation_id": operation.operation_id},
                )
            await terminal_field.rollback()

            subject_artifacts = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=workspace_id,
                subject_kind="account",
                subject_entity_id=EntityId(ready.account_id),
            )
            s1_edges = {
                item.reference_kind
                for item in subject_artifacts
                if item.reference_kind.startswith("sumble_")
            }
            assert s1_edges == {
                "sumble_gap_request",
                "sumble_org_request",
                "sumble_organizations_response",
                "sumble_jobs_request",
                "sumble_jobs_response",
                "sumble_tech_stack_request",
                "sumble_tech_stack_response",
                "sumble_gap_receipt",
            }
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
            erased_replay = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={
                    "account.hiring_velocity_eng": Decimal(5),
                    "core.primary_tech_stack": Decimal(5),
                },
                provider_credit_cap=5,
                allow_unbounded_tech=True,
            )
            assert erased_replay.outcome is SumbleAccountGapOutcome.REPLAYED
            assert len(http.calls) == 3

    run_async(scenario())


def test_the_sumble_field_source_map_agrees_with_the_31_ownership_contract() -> None:
    """Slice-A carry-forward: one field->source truth, not two that can drift.

    ``_SOURCE_BY_FIELD`` is the gap compiler's routing table and
    ``COMPREHENSIVE_ACCOUNT_FIELD_SOURCES`` is the frozen §3.1 ownership table. Every shared row
    must agree, and every §3.1 row a Sumble source owns must be routable here — otherwise a
    contract-authorized field reaches the compiler and dies on a ``KeyError``.
    """

    owned_by_sumble = {
        field: next(source for source in sources if source in SUMBLE_SOURCE_KEYS)
        for field, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items()
        if any(source in SUMBLE_SOURCE_KEYS for source in sources)
    }
    assert owned_by_sumble  # the table is not empty, so the agreement below is not vacuous
    for field, source_key in owned_by_sumble.items():
        assert _SOURCE_BY_FIELD[field] == source_key
    for field, source_key in _SOURCE_BY_FIELD.items():
        assert source_key in SUMBLE_SOURCE_KEYS
        contract_sources = COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.get(field)
        if contract_sources is not None:
            assert source_key in contract_sources
    # core.primary_domain is identity truth outside the 21-field profile; Sumble has always
    # answered it, so it stays routable and is the one deliberate extra row.
    assert set(_SOURCE_BY_FIELD) - set(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES) == {
        "core.primary_domain"
    }


class _AttributeSumbleHttp:
    """Return only the attributes the pinned v9 ``select`` list actually requested."""

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append({"url": url, **kwargs})
        if not url.endswith("/organizations"):
            raise AssertionError(f"unexpected Sumble URL: {url}")
        body = kwargs["json_body"]
        requested = set(body["select"]["attributes"])
        attributes: dict[str, Any] = {
            "id": 1726684,
            "name": "Insight Health AI",
            "url": self.domain,
            "sumble_url": "https://sumble.com/l/org/insight-health-ai",
        }
        available = {"employee_count": 240, "headquarters_country": "US", "industry": "Healthcare"}
        attributes.update({key: value for key, value in available.items() if key in requested})
        return {
            "id": "s1-org-attributes",
            "credits_used": 3,
            "credits_remaining": 997,
            "organizations": [
                {"input": {"url": self.domain}, "attributes": attributes, "entities": []}
            ],
            "matched_count": 1,
            "total": 1,
        }


def test_s1_organization_action_materializes_only_the_fields_its_v9_request_supports(
    tmp_path: Path,
) -> None:
    """§3.1 ownership is not the same as v9 requestability.

    ``sumble_organizations`` owns seven §3.1 rows but its pinned v9 action can request only three
    of them (plus ``core.primary_domain``). The supported ones materialize governed claims from the
    already-paid payload; the unsupported ones are settled honestly as ``confirmed_missing`` with
    ``source_cannot_request_field`` — never faked, never a ``ValueError`` at dispatch, never a
    suspended job.
    """

    async def scenario() -> None:
        workspace_id = "ws-s1-org-attributes"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _AttributeSumbleHttp("insighthealth.ai")

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            coordinator = SumbleAccountGapCoordinator(
                api_key=SecretStr("fixture"),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                client_factory=client_factory,
            )
            starter = SumbleAccountGapStarter(
                coordinator=coordinator,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            supported = ("core.employee_count", "core.hq_location")
            unsupported = (
                "account.recent_funding",
                "account.total_funding",
                "core.company_about",
                "core.company_linkedin_url",
            )
            result = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={
                    key: Decimal(5) for key in (*supported, *unsupported)
                },
                provider_credit_cap=3,
                allow_unbounded_tech=False,
            )
            assert result.outcome is SumbleAccountGapOutcome.COMPLETED
            # One paid organization call; jobs/tech were never selected.
            assert len(http.calls) == 1
            assert http.calls[0]["json_body"]["select"]["attributes"] == [
                "id",
                "name",
                "url",
                "sumble_url",
                "employee_count",
                "headquarters_country",
            ]

            fields = await list_account_gap_field_results(
                conn,
                workspace_id=workspace_id,
                operation_id=result.operation.operation_id,
            )
            by_field = {str(row.field_key): row for row in fields}
            assert set(by_field) == {*supported, *unsupported}
            for field_key in supported:
                assert by_field[field_key].state.value == "resolved"
                assert by_field[field_key].sumble_claim_id is not None
            for field_key in unsupported:
                assert by_field[field_key].state.value == "confirmed_missing"
                assert by_field[field_key].reason_code == "source_cannot_request_field"
                assert by_field[field_key].sumble_claim_id is None
                assert (
                    await claims_for(
                        conn,
                        EntityId(ready.account_id),
                        field_key,
                        scope=WorkspaceScope.for_workspace(workspace_id),
                    )
                    == []
                )

            headcount = await claims_for(
                conn,
                EntityId(ready.account_id),
                "core.employee_count",
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert len(headcount) == 1
            assert headcount[0].source_key == ORGANIZATIONS_SOURCE_KEY
            assert headcount[0].value_json == 240
            assert headcount[0].evidence_span == '"employee_count":240'
            assert headcount[0].artifact_key is not None
            location = await claims_for(
                conn,
                EntityId(ready.account_id),
                "core.hq_location",
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert len(location) == 1
            assert location[0].evidence_span == '"headquarters_country":"US"'

    run_async(scenario())


def test_s1_a_request_of_only_unrequestable_fields_is_refused_before_any_spend(
    tmp_path: Path,
) -> None:
    """No Sumble call may be paid for a field the action cannot even ask about."""

    async def scenario() -> None:
        workspace_id = "ws-s1-unrequestable"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _AttributeSumbleHttp("insighthealth.ai")

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            starter = SumbleAccountGapStarter(
                coordinator=SumbleAccountGapCoordinator(
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                    client_factory=client_factory,
                ),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            with pytest.raises(
                SumbleAccountGapFieldsUnrequestable,
                match="cannot request",
            ):
                await starter.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits={"core.company_linkedin_url": Decimal(5)},
                    provider_credit_cap=1,
                    allow_unbounded_tech=False,
                )
            assert http.calls == []
            assert (
                await conn.execute(text("SELECT count(*) FROM account_gap_operation"))
            ).scalar_one() == 0
            assert SUMBLE_SUPPORTED_FIELD_KEYS_BY_SOURCE[ORGANIZATIONS_SOURCE_KEY] == frozenset(
                {
                    "core.employee_count",
                    "core.industry",
                    "core.hq_location",
                    "core.primary_domain",
                }
            )

    run_async(scenario())


class _RejectingSumbleHttp:
    """Refuse every Sumble call the way the live wrapper reports a provider response fault."""

    def __init__(self, *, status_code: int | None, body_excerpt: str | None) -> None:
        self.calls: list[str] = []
        self._status_code = status_code
        self._body_excerpt = body_excerpt

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append(url)
        raise ProviderResponseError(
            f"{ORGANIZATIONS_SOURCE_KEY}: HTTP {self._status_code} from {url}",
            status_code=self._status_code,
            body_excerpt=self._body_excerpt,
        )


def _rejecting_starter(
    *,
    storage: FsStorage,
    conn_factory: Any,
    http: _RejectingSumbleHttp,
) -> SumbleAccountGapStarter:
    def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
        return SumbleClient(
            api_key=SecretStr("fixture"),
            budget=SumbleCreditBudget(maximum=maximum),
            http=http,
            cents_per_credit=cents,
        )

    coordinator = SumbleAccountGapCoordinator(
        api_key=SecretStr("fixture"),
        storage=storage,
        cents_per_credit=Decimal("0.5"),
        conn_factory=conn_factory,
        client_factory=client_factory,
    )
    return SumbleAccountGapStarter(
        coordinator=coordinator,
        storage=storage,
        cents_per_credit=Decimal("0.5"),
        conn_factory=conn_factory,
    )


def test_s1_deterministic_provider_rejection_is_terminal_uncharged_and_retains_the_body(
    tmp_path: Path,
) -> None:
    """A hard 4xx is a zero-credit refusal, not an unknown spend, and keeps its diagnostic."""

    async def scenario() -> None:
        workspace_id = "ws-s1-sumble-rejected"
        storage = FsStorage(tmp_path / "artifacts")
        body_excerpt = (
            '{"detail":[{"loc":["body","filter","query"],'
            '"msg":"Input should be a valid dictionary"}]}'
        )
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _RejectingSumbleHttp(status_code=422, body_excerpt=body_excerpt)
            starter = _rejecting_starter(storage=storage, conn_factory=same_connection, http=http)
            result = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={"account.hiring_velocity_eng": Decimal(5)},
                provider_credit_cap=2,
                allow_unbounded_tech=False,
            )
            assert result.outcome is SumbleAccountGapOutcome.FAILED_TERMINAL
            assert len(http.calls) == 1

            failure_code = f"{ORGANIZATIONS_SOURCE_KEY}_provider_rejected_http_422"
            operation = await get_account_gap_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=AccountGapOperationId(result.operation.operation_id),
            )
            assert operation is not None
            assert operation.state is AccountGapOperationState.FAILED_TERMINAL
            assert operation.spend_outcome is AccountGapSpendOutcome.NOT_CHARGED
            assert operation.provider_units_charged == Decimal(0)
            assert operation.cost_cents_charged == Decimal(0)
            assert operation.failure_code == failure_code

            snapshots = await list_account_gap_snapshots(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            org = next(row for row in snapshots if row.source_key == ORGANIZATIONS_SOURCE_KEY)
            assert org.state is AccountGapSnapshotState.FAILED_TERMINAL
            assert org.spend_outcome is AccountGapSpendOutcome.NOT_CHARGED
            assert org.failure_code == failure_code
            assert org.response_artifact_key is not None
            assert json.loads(await storage.get(org.response_artifact_key)) == {
                "provider_rejection": {
                    "source_key": ORGANIZATIONS_SOURCE_KEY,
                    "http_status": 422,
                    "body_excerpt": body_excerpt,
                }
            }

            fields = await list_account_gap_field_results(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            assert {row.state.value for row in fields} == {"failed_terminal"}
            assert Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": started.project_run_id},
                    )
                ).scalar_one()
            ) == Decimal(0)
            rejection_edges = {
                item.reference_kind
                for item in await enumerate_discovery_subject_artifacts(
                    conn,
                    workspace_id=workspace_id,
                    subject_kind="account",
                    subject_entity_id=EntityId(ready.account_id),
                )
                if item.reference_kind.endswith("_provider_rejection")
            }
            assert rejection_edges == {f"{ORGANIZATIONS_SOURCE_KEY}_provider_rejection"}

            replay = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={"account.hiring_velocity_eng": Decimal(5)},
                provider_credit_cap=2,
                allow_unbounded_tech=False,
            )
            assert replay.outcome is SumbleAccountGapOutcome.FAILED_TERMINAL
            assert len(http.calls) == 1

    run_async(scenario())


def test_s1_provider_response_fault_without_a_status_stays_spend_outcome_unknown(
    tmp_path: Path,
) -> None:
    """A malformed 2xx body may already have been charged; only a hard 4xx is a clean refusal."""

    async def scenario() -> None:
        workspace_id = "ws-s1-sumble-ambiguous"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _RejectingSumbleHttp(status_code=None, body_excerpt=None)
            starter = _rejecting_starter(storage=storage, conn_factory=same_connection, http=http)
            result = await starter.start(
                workspace_id=workspace_id,
                project_run_id=ProjectRunId(started.project_run_id),
                account_id=EntityId(ready.account_id),
                field_expected_value_credits={"account.hiring_velocity_eng": Decimal(5)},
                provider_credit_cap=2,
                allow_unbounded_tech=False,
            )
            assert result.outcome is SumbleAccountGapOutcome.SPEND_OUTCOME_UNKNOWN
            operation = await get_account_gap_operation(
                conn,
                workspace_id=workspace_id,
                operation_id=AccountGapOperationId(result.operation.operation_id),
            )
            assert operation is not None
            assert operation.spend_outcome is AccountGapSpendOutcome.UNKNOWN
            assert operation.failure_code == "sumble_paid_dispatch_unreconciled"
            snapshots = await list_account_gap_snapshots(
                conn, workspace_id=workspace_id, operation_id=operation.operation_id
            )
            org = next(row for row in snapshots if row.source_key == ORGANIZATIONS_SOURCE_KEY)
            assert org.state is AccountGapSnapshotState.SPEND_OUTCOME_UNKNOWN
            assert org.response_artifact_key is None

    run_async(scenario())


def test_s1_the_nine_field_comprehensive_sumble_set_passes_the_count_gate(
    tmp_path: Path,
) -> None:
    """All nine §3.1 Sumble-owned rows in one call clear the per-call cap.

    Only requestable fields consume ``maximum_fields`` (default 6): the four rows the pinned v9
    actions cannot request cost no provider call and settle as honest unresolved plan rows, so a
    comprehensive request naming all nine must not be refused on raw count — that refusal was a
    suspending trap for the account agent, which sees nine Sumble-authorized fields in its state.
    """

    async def scenario() -> None:
        workspace_id = "ws-s1-nine-field-count"
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            started, ready = await _seed_selected_high_tier_account(
                conn, storage, workspace_id=workspace_id
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            http = _AttributeSumbleHttp("insighthealth.ai")

            def client_factory(maximum: int, cents: Decimal) -> SumbleClient:
                return SumbleClient(
                    api_key=SecretStr("fixture"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=http,
                    cents_per_credit=cents,
                )

            starter = SumbleAccountGapStarter(
                coordinator=SumbleAccountGapCoordinator(
                    api_key=SecretStr("fixture"),
                    storage=storage,
                    cents_per_credit=Decimal("0.5"),
                    conn_factory=same_connection,
                    client_factory=client_factory,
                ),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
            )
            nine = {
                "core.employee_count": Decimal(5),
                "core.industry": Decimal(5),
                "core.hq_location": Decimal(5),
                "core.company_about": Decimal(5),
                "core.company_linkedin_url": Decimal(5),
                "account.total_funding": Decimal(5),
                "account.recent_funding": Decimal(5),
                "account.hiring_velocity_eng": Decimal(5),
                "core.primary_tech_stack": Decimal(5),
            }
            # Tech requires its explicit unbounded approval and rides its own action; the count
            # gate is what this test pins, so request the eight organization/jobs-shaped rows.
            del nine["core.primary_tech_stack"]
            # The request must travel PAST the count gate: the fixture account already holds a
            # fresh governed core.industry claim, so the next gate in line — the freshness
            # ladder's honest reuse refusal — is the expected outcome. Before the fix this raised
            # "invalid Sumble account-gap field count" without ever reaching it.
            with pytest.raises(SumbleAccountGapNotEligible, match="already confidently resolved"):
                await starter.start(
                    workspace_id=workspace_id,
                    project_run_id=ProjectRunId(started.project_run_id),
                    account_id=EntityId(ready.account_id),
                    field_expected_value_credits=nine,
                    provider_credit_cap=8,
                    allow_unbounded_tech=False,
                )

    run_async(scenario())
