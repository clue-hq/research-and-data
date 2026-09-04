"""R6 confirmed-direction compiler acceptance on an isolated Postgres transaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4, uuid5

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import account_research_fleet_launch
from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
    AccountResearchFleetState,
)
from clue_api.account_research_fleet_composition import (
    DbAccountResearchJobContextResolver,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchError,
    AccountResearchFleetLaunchRequest,
)
from clue_api.committee_eligibility import (
    CommitteeEligibilityService,
    CommitteeEnumerationSource,
)
from clue_api.comprehensive_research_contract import COMPREHENSIVE_ACCOUNT_FIELD_SOURCES
from clue_api.entity_research_provider_wiring import (
    EntityResearchProductionCompositionError,
    ProductionAccountResearchProviderActions,
)
from clue_api.entity_research_tools import EntityResearchGovernedRejection
from clue_api.sumble_account_gaps import (
    SumbleAccountGapCoordinator,
    SumbleAccountGapEligibilityError,
    compile_sumble_account_gap_preflight,
)
from clue_api.sumble_committee_acquisition import (
    SUMBLE_COMMITTEE_CONTRACT_VERSION,
    SUMBLE_COMMITTEE_POLICY_VERSION,
    SUMBLE_COMMITTEE_PRICING_VERSION,
    SumbleCommitteeAcquisitionCoordinator,
    compile_sumble_committee_preflight,
)
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_config import GatewayConfig, Secrets, Settings
from clue_core import (
    CommitteeAcquisitionRequest,
    CommitteeEligibilityCondition,
    CommitteeEligibilityOutcome,
    CommitteeExecutionAuthorization,
    EntityId,
    LLMGateway,
    PreSpendDecision,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ProjectPhase,
    ProjectRunId,
    ResearchAccountScope,
    ResearchDirectiveBody,
    ResearchQuestion,
    SourceTier,
    UseClass,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    GovernedResearchToolRequest,
    SealedDiscoveryLaunchReceipt,
)
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchExecutionFence,
    FleetTaskKind,
    WorkId,
    acquire_work_lease,
    claim_next_task,
)
from clue_research.directives import (
    ResearchDirectiveInvalid,
    validate_research_directive_draft,
)
from clue_research.durable import (
    find_account_runs_for_entity,
    get_discovery_batch_manifest,
    get_discovery_batch_seal,
)
from clue_research.durable.provider_spend import (
    ProviderSpendRunIneligible,
    require_provider_spend_capacity,
)
from clue_research.identity import insert_account_entity
from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS
from clue_research.resolvers.sumble import (
    SUMBLE_API_VERSION,
    SUMBLE_SOURCE_KEYS,
    SumbleClient,
    SumbleCreditBudget,
    sumble_action_supports_field,
)
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_storage import FsStorage
from tests._run_lineage import assert_run_registered
from tests.api.account_deep_test_support import (
    confirmed_account_research_direction,
    in_progress_discovery_run,
)
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_sumble_account_gaps_s1 import _SumbleHttp
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_HIRING = "account.hiring_velocity_eng"
_INDUSTRY = "core.industry"
_TECH = "core.primary_tech_stack"


def test_launcher_refuses_an_unsealed_discovery_without_writing_research_state(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r6-unsealed-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES, _HIRING),
                allowed_source_keys=("exa_deep", "sumble_jobs", "sumble_people"),
            )
            pin = account_spec.research_directive
            assert pin is not None
            pending_run_id = await in_progress_discovery_run(
                conn,
                workspace_id=fixture.discovery_fixture.workspace_id,
                template_project_run_id=fixture.project_run_id,
                template_discovery_plan_id=fixture.discovery_plan_id,
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            with pytest.raises(
                AccountResearchFleetLaunchError,
                match="Account discovery is still in progress",
            ):
                await launcher.launch(
                    AccountResearchFleetLaunchRequest(
                        workspace_id=fixture.discovery_fixture.workspace_id,
                        project_run_id=UUID(str(pending_run_id)),
                        research_directive_id=UUID(str(pin.directive_id)),
                        account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                        approved_budget_cap_cents=Decimal("300"),
                        expected_estimated_cost_cents=Decimal("300"),
                    ),
                    actor="human:account-owner",
                    source_action_ref="turn:r6-unsealed-launch",
                    source_operation_id=uuid4(),
                )

            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_run "
                        "WHERE project_run_id=:project_run_id"
                    ),
                    {"project_run_id": pending_run_id},
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM account_run WHERE project_run_id=:project_run_id"),
                    {"project_run_id": pending_run_id},
                )
            ).scalar_one() == 0

    run_async(scenario())


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    async with conn.begin_nested():
        yield conn


class _PassingPreSpendGate:
    async def check(self, request: PreSpendRequest) -> PreSpendDecision:
        del request
        return PreSpendDecision(verdict=PreSpendVerdict.PASS)


def test_confirmed_direction_compiles_exact_account_fleet_without_provider_or_contact_work(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r6-launch-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES, _HIRING),
                allowed_source_keys=("exa_deep", "sumble_jobs", "sumble_people"),
                questions=(
                    ResearchQuestion(
                        question_id="qualitative-burden",
                        text="Where is administrative work creating avoidable burden?",
                        target_field_key=_PAIN,
                    ),
                    ResearchQuestion(
                        question_id="strategic-change",
                        text="What strategic operational changes are visible?",
                        target_field_key=_MOVES,
                    ),
                    ResearchQuestion(
                        question_id="hiring-signal",
                        text="What is the hiring velocity for relevant operational roles?",
                        target_field_key=_HIRING,
                    ),
                ),
            )
            pin = account_spec.research_directive
            assert pin is not None
            # M8D launches are action-scoped. They must not restore the legacy requirement that
            # the outer project state machine happen to be sitting in its DEEP phase.
            await conn.execute(
                text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
                {"project_run_id": fixture.project_run_id},
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            fleets = AccountResearchFleetService(conn_factory=connection)
            launcher = AccountResearchFleetLauncher(
                fleets=fleets,
                conn_factory=connection,
            )
            request = AccountResearchFleetLaunchRequest(
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_run_id=UUID(str(fixture.project_run_id)),
                research_directive_id=UUID(str(pin.directive_id)),
                account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
                concurrency_limit=4,
                supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
            )
            launch_operation_id = uuid4()
            projection = await launcher.launch(
                request,
                actor="human:account-owner",
                source_action_ref="turn:r6-account-launch-confirmed",
                source_operation_id=launch_operation_id,
            )
            assert projection.fleet_state is AccountResearchFleetState.CANARY
            assert projection.selected_accounts == 1
            assert projection.queued_accounts == 1
            assert projection.contact_research_started is False
            assert projection.contact_research_request_count == 0
            job = projection.jobs[0]
            assert job.account_entity_id == UUID(str(fixture.selected_account_id))

            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT lifecycle_json, concurrency_limit FROM entity_research_run "
                            "WHERE research_run_id=:run_id"
                        ),
                        {"run_id": projection.research_run_id},
                    )
                )
                .mappings()
                .one()
            )
            selection = stored["lifecycle_json"]["selection"]
            authority = {
                item["field_key"]: tuple(item["source_keys"])
                for item in selection["field_source_authority"]
            }
            assert authority == {
                _PAIN: ("exa_deep",),
                _MOVES: ("exa_deep",),
                # §3.1 grants hiring velocity to Sumble Jobs alone; exa_deep's manifest no
                # longer yields it (B3 ownership narrowing), so no Exa fallback rides along.
                _HIRING: ("sumble_jobs",),
            }
            assert tuple(selection["committee_source_keys"]) == ("sumble_people",)
            assert stored["concurrency_limit"] == 4

            # FI-2 P2: the launched research run is attributed to its project at launch time.
            await assert_run_registered(
                conn,
                projection.research_run_id,
                kind="entity_research",
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                project_run_id=fixture.project_run_id,
            )

            account_runs = await find_account_runs_for_entity(
                conn,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
            )
            assert len(account_runs) == 1
            assert job.account_run_id == UUID(str(account_runs[0].id))
            assert account_runs[0].research_directive == pin
            assert account_runs[0].budget_cap_cents == Decimal("300")
            stored_job = await DbEntityResearchJobStore(conn_factory=connection).get_job(job.job_id)
            assert stored_job is not None
            assert await DbAccountResearchJobContextResolver(
                conn_factory=connection
            ).account_run_id(stored_job) == UUID(str(account_runs[0].id))
            counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM entity_research_provider_operation "
                            " WHERE target_entity_id=:account_id) AS provider_operations, "
                            "(SELECT count(*) FROM entity_research_job "
                            " WHERE research_run_id=:run_id AND subject_type='contact') "
                            " AS contact_jobs"
                            ", (SELECT count(*) FROM account_deep_launch "
                            " WHERE project_run_id=:project_run_id) AS legacy_launches"
                        ),
                        {
                            "account_id": fixture.selected_account_id,
                            "run_id": projection.research_run_id,
                            "project_run_id": fixture.project_run_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert counts == {
                "provider_operations": 0,
                "contact_jobs": 0,
                "legacy_launches": 0,
            }

            replay = await AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            ).launch(
                request,
                actor="human:account-owner",
                source_action_ref="turn:r6-account-launch-confirmed",
                source_operation_id=launch_operation_id,
            )
            assert replay == projection
            with pytest.raises(
                AccountResearchFleetLaunchError,
                match="action replay changed immutable launch authority",
            ):
                await launcher.launch(
                    request,
                    actor="human:account-owner",
                    source_action_ref="turn:r6-account-launch-confirmed",
                    source_operation_id=uuid4(),
                )
            row_counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM entity_research_run "
                            " WHERE research_run_id=:run_id) AS runs, "
                            "(SELECT count(*) FROM entity_research_job "
                            " WHERE research_run_id=:run_id) AS jobs, "
                            "(SELECT count(*) FROM fleet_task "
                            " WHERE kind='entity_research_job' AND work_id=:job_id) AS tasks, "
                            "(SELECT count(*) FROM account_run "
                            " WHERE project_run_id=:project_run_id "
                            " AND entity_id=:account_id) AS account_runs"
                        ),
                        {
                            "run_id": projection.research_run_id,
                            "job_id": job.job_id,
                            "project_run_id": fixture.project_run_id,
                            "account_id": fixture.selected_account_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert row_counts == {"runs": 1, "jobs": 1, "tasks": 1, "account_runs": 1}

            # M8D launches are action-scoped. Only the exact running entity job authority may
            # replace the reused provider ledgers' historical DEEP-phase requirement.
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                worker_id="r10-spend-authority",
                project_run_id=ProjectRunId(job.job_id),
            )
            assert task is not None
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(job.job_id),
                worker_id="r10-spend-authority",
                ttl=timedelta(seconds=60),
            )
            assert lease is not None
            fence = EntityResearchExecutionFence(
                task_id=task.task_id,
                worker_id="r10-spend-authority",
                lease_generation=lease.generation,
                task_attempt=1,
            )
            begun = await DbEntityResearchJobStore(conn_factory=connection).begin(
                job.job_id,
                fence=fence,
            )
            assert begun.admitted
            # An explicit R6 account launch is the human authority for this exact job. The
            # outer discovery flow may still be paused at its legacy tier checkpoint (for
            # example when every discovered account scored low); that checkpoint must not
            # prevent the selected job from reaching its providers.
            await conn.execute(
                text(
                    "UPDATE project_run SET phase='tier_checkpoint', status='paused' "
                    "WHERE id=:project_run_id"
                ),
                {"project_run_id": fixture.project_run_id},
            )
            providers = ProductionAccountResearchProviderActions(
                settings=Settings(
                    _env_file=None,
                    exa_account_deep_acquisition_enabled=True,
                    sumble_account_gap_enrichment_enabled=True,
                    sumble_committee_acquisition_enabled=True,
                ),
                secrets=Secrets(
                    _env_file=None,
                    exa_api_key=SecretStr("r10-test-exa"),
                    sumble_api_key=SecretStr("r10-test-sumble"),
                ),
                storage=storage,
                pre_spend_gate=cast(PreSpendGate, object()),
                gateway=cast(LLMGateway, object()),
                gateway_config=GatewayConfig(),
                conn_factory=connection,
            )
            bindings = await providers.resolve(begun.job)
            assert set(bindings) == {
                "research_account_deep",
                "enrich_account",
                "discover_buying_committee",
            }
            assert all(binding.provider_family for binding in bindings.values())
            assert all(binding.budget_reservation_cents > 0 for binding in bindings.values())
            capacity = await require_provider_spend_capacity(
                conn,
                project_run_id=fixture.project_run_id,
                proposed_cents=Decimal("1"),
                allowed_phases=frozenset({ProjectPhase.DEEP}),
                entity_research_job_id=job.job_id,
            )
            assert capacity.phase is ProjectPhase.TIER_CHECKPOINT

            # The same explicit job is also the tier authority for committee discovery. A
            # missing human tier claim and a paused tier checkpoint cannot reintroduce the
            # low/high-signal gate after account research has already been authorized.
            committee_request = CommitteeAcquisitionRequest(
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                project_run_id=fixture.project_run_id,
                entity_research_job_id=job.job_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                discovery_batch_id=fixture.discovery_batch_id,
                discovery_seal_sha256=fixture.discovery_seal_sha256,
                account_id=fixture.selected_account_id,
                tier_claim_id=None,
                committee_plan_ref=fixture.committee_plan_ref,
                research_direction_ref=pin.directive_ref,
                research_directive=pin,
                organization_identity_ref="account-gap-snapshot:r6-test:sumble_organizations",
                provider_organization_id="1726684",
                provider_api_version=SUMBLE_API_VERSION,
                provider_contract_version=SUMBLE_COMMITTEE_CONTRACT_VERSION,
                pricing_policy_version=SUMBLE_COMMITTEE_PRICING_VERSION,
                committee_policy_version=SUMBLE_COMMITTEE_POLICY_VERSION,
                observation_window=f"r6-test:{job.job_id}",
                team_limit=1,
                related_people_per_team=1,
                jobs_per_team=1,
                people_limit=1,
                provider_credit_cap=100,
                money_budget_cap_cents=Decimal("300"),
            )
            committee_authorization = CommitteeExecutionAuthorization(
                workspace_id=committee_request.workspace_id,
                project_id=committee_request.project_id,
                project_run_id=committee_request.project_run_id,
                account_id=committee_request.account_id,
                research_direction_ref=committee_request.research_direction_ref,
                research_directive=committee_request.research_directive,
                committee_plan_ref=committee_request.committee_plan_ref,
                confirmation_ref="turn:r6-explicit-account-launch",
                confirmed_by_human=True,
                personal_data_allowed=True,
                jurisdiction_policy_ref="jurisdiction-policy:r6-test",
                jurisdiction_allowed=True,
                allowed_use_classes=(UseClass.PROFESSIONAL_PUBLIC,),
                identity_policy_ref="identity-policy:r6-test",
                identity_acquisition_allowed=True,
                budget_authorization_ref=f"entity-research-job:{job.job_id}",
                contact_reveals_allowed=False,
            )
            committee_decision = await CommitteeEligibilityService(
                storage=storage,
                pre_spend_gate=_PassingPreSpendGate(),
                sources=(
                    CommitteeEnumerationSource(
                        source_key="sumble_teams", source_tier=SourceTier(1)
                    ),
                    CommitteeEnumerationSource(
                        source_key="sumble_people", source_tier=SourceTier(1)
                    ),
                ),
                conn_factory=connection,
            ).evaluate(
                committee_request,
                authorization=committee_authorization,
                proposed_cost_cents=Decimal("1"),
            )
            assert committee_decision.outcome is CommitteeEligibilityOutcome.ELIGIBLE
            pass_a_condition = next(
                item
                for item in committee_decision.conditions
                if item.condition is CommitteeEligibilityCondition.PASS_A_COMPLETE
            )
            assert pass_a_condition.passed
            assert pass_a_condition.evidence_refs == (f"entity-research-job:{job.job_id}",)
            must_have_condition = next(
                item
                for item in committee_decision.conditions
                if item.condition is CommitteeEligibilityCondition.MUST_HAVE_CRITERIA
            )
            assert must_have_condition.passed
            assert must_have_condition.evidence_refs == (f"entity-research-job:{job.job_id}",)
            tier_condition = next(
                item
                for item in committee_decision.conditions
                if item.condition is CommitteeEligibilityCondition.HUMAN_APPROVED_TIER
            )
            assert tier_condition.passed
            assert tier_condition.evidence_refs == (f"entity-research-job:{job.job_id}",)
            committee_transport = _CommitteeTransport()
            committee_acquisition = await SumbleCommitteeAcquisitionCoordinator(
                transport=committee_transport,
                storage=storage,
                cents_per_credit=Decimal(0),
                conn_factory=connection,
            ).start(
                compile_sumble_committee_preflight(
                    committee_request,
                    cents_per_credit=Decimal(0),
                )
            )
            assert committee_acquisition.operation.request.tier_claim_id is None
            assert (
                await conn.execute(
                    text(
                        "SELECT tier_claim_id FROM committee_acquisition_operation "
                        "WHERE id=:operation_id"
                    ),
                    {"operation_id": committee_acquisition.operation.operation_id},
                )
            ).scalar_one_or_none() is None
            preflight = await compile_sumble_account_gap_preflight(
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_run_id=fixture.project_run_id,
                account_id=fixture.selected_account_id,
                field_expected_value_credits={_HIRING: Decimal("25")},
                provider_credit_cap=25,
                allow_unbounded_tech=False,
                observation_window=f"r10-job:{job.job_id}",
                storage=storage,
                conn_factory=connection,
                entity_research_job_id=job.job_id,
            )
            assert preflight.request.entity_research_job_id == job.job_id
            assert preflight.request.tier_claim_id is None
            assert preflight.request.fields[0].field_key == _HIRING
            with pytest.raises(
                SumbleAccountGapEligibilityError,
                match="exact Account research job",
            ):
                await compile_sumble_account_gap_preflight(
                    workspace_id=fixture.discovery_fixture.workspace_id,
                    project_run_id=fixture.project_run_id,
                    account_id=EntityId(uuid4()),
                    field_expected_value_credits={_HIRING: Decimal("25")},
                    provider_credit_cap=25,
                    allow_unbounded_tech=False,
                    observation_window=f"r10-wrong-account:{job.job_id}",
                    storage=storage,
                    conn_factory=connection,
                    entity_research_job_id=job.job_id,
                )
            sumble_http = _SumbleHttp("insighthealth.ai")
            account_gap = await SumbleAccountGapCoordinator(
                api_key=SecretStr("r10-test-sumble"),
                storage=storage,
                conn_factory=connection,
                client_factory=lambda maximum, cents: SumbleClient(
                    api_key=SecretStr("r10-test-sumble"),
                    budget=SumbleCreditBudget(maximum=maximum),
                    http=sumble_http,
                    cents_per_credit=cents,
                ),
            ).start(preflight)
            assert account_gap.operation.request.tier_claim_id is None
            assert (
                await conn.execute(
                    text("SELECT tier_claim_id FROM account_gap_operation WHERE id=:operation_id"),
                    {"operation_id": account_gap.operation.operation_id},
                )
            ).scalar_one_or_none() is None
            with pytest.raises(
                ProviderSpendRunIneligible,
                match="exact live entity-research job authority",
            ):
                await require_provider_spend_capacity(
                    conn,
                    project_run_id=fixture.project_run_id,
                    proposed_cents=Decimal("1"),
                    allowed_phases=frozenset({ProjectPhase.DEEP}),
                    entity_research_job_id=uuid4(),
                )

    run_async(scenario())


def test_core_fields_survive_launch_and_are_not_silently_dropped(tmp_path: Path) -> None:
    """A confirmed directive's ``core.*`` account facts reach the launched selection.

    The launcher used to project the confirmed field authority with a raw ``account.`` prefix
    filter, so a comprehensive directive's ``core.industry`` / ``core.primary_tech_stack`` were
    silently dropped before source compilation — and a wholly ``core.*`` directive raised. The
    in-job Exa preparation already projects on the shared account axis, so launcher and runtime
    disagreed about the field universe.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r6-core-axis-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
                deep_field_keys=(_HIRING, _TECH, _PAIN, _MOVES, _INDUSTRY),
            )
            # No pass_kind workaround: validate_research_directive_draft now admits every field
            # of the fixed comprehensive profile (contract §3.1) regardless of its registered
            # pass_kind, so the scoring-era core.* rows are directive-valid as shipped.
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_INDUSTRY, _TECH, _HIRING, _PAIN),
                # No sumble_organizations here: under this ICP's authored source profile none of
                # these four fields canonically plans it, and the validator's allowed-source
                # coverage check is deliberately strict outside the full comprehensive profile.
                allowed_source_keys=(
                    "exa_deep",
                    "sumble_jobs",
                    "sumble_tech_stack",
                    "sumble_people",
                ),
                questions=(
                    ResearchQuestion(
                        question_id="industry-classification",
                        text="Which specialty-care category does this practice operate in?",
                        target_field_key=_INDUSTRY,
                    ),
                    ResearchQuestion(
                        question_id="tech-stack",
                        text="Which clinical and communication systems are in operational use?",
                        target_field_key=_TECH,
                    ),
                    ResearchQuestion(
                        question_id="hiring-signal",
                        text="What is the hiring velocity for relevant operational roles?",
                        target_field_key=_HIRING,
                    ),
                    ResearchQuestion(
                        question_id="qualitative-burden",
                        text="Where is administrative work creating avoidable burden?",
                        target_field_key=_PAIN,
                    ),
                ),
            )
            pin = account_spec.research_directive
            assert pin is not None
            await conn.execute(
                text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
                {"project_run_id": fixture.project_run_id},
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            projection = await launcher.launch(
                AccountResearchFleetLaunchRequest(
                    workspace_id=fixture.discovery_fixture.workspace_id,
                    project_run_id=UUID(str(fixture.project_run_id)),
                    research_directive_id=UUID(str(pin.directive_id)),
                    account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                    approved_budget_cap_cents=Decimal("300"),
                    expected_estimated_cost_cents=Decimal("300"),
                    concurrency_limit=4,
                    supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
                ),
                actor="human:account-owner",
                source_action_ref="turn:r6-core-axis-launch",
                source_operation_id=uuid4(),
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT lifecycle_json FROM entity_research_run "
                            "WHERE research_run_id=:run_id"
                        ),
                        {"run_id": projection.research_run_id},
                    )
                )
                .mappings()
                .one()
            )
            selection = EntityResearchSelection.model_validate(
                stored["lifecycle_json"]["selection"]
            )
            assert selection.discovery_receipt is not None
            assert selection.discovery_receipt.discovery_batch_id == UUID(
                str(fixture.discovery_batch_id)
            )
            assert selection.discovery_receipt.discovery_generation == 1
            assert "core.industry" in selection.admitted_field_keys
            assert "core.primary_tech_stack" in selection.admitted_field_keys
            assert set(selection.admitted_field_keys) == {_INDUSTRY, _TECH, _HIRING, _PAIN}
            authority = {
                item.field_key: tuple(item.source_keys) for item in selection.field_source_authority
            }
            assert set(authority) == {_INDUSTRY, _TECH, _HIRING, _PAIN}

    run_async(scenario())


def test_account_only_research_composes_without_committee_configuration(tmp_path: Path) -> None:
    """A directive that selected no committee discovery composes with committee acquisition off.

    The gate used to raise for *every* account job, so an account-only run could not be composed
    at all unless no-reveal Sumble committee acquisition happened to be configured. The gate is a
    property of what the confirmed directive selected: no committee sources → the tool is a
    governed ``provider_not_selected`` refusal; committee sources selected but unconfigured →
    still a loud composition failure.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r6-account-only-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES),
                allowed_source_keys=("exa_deep",),
                questions=(
                    ResearchQuestion(
                        question_id="qualitative-burden",
                        text="Where is administrative work creating avoidable burden?",
                        target_field_key=_PAIN,
                    ),
                    ResearchQuestion(
                        question_id="strategic-change",
                        text="What strategic operational changes are visible?",
                        target_field_key=_MOVES,
                    ),
                ),
            )
            pin = account_spec.research_directive
            assert pin is not None
            await conn.execute(
                text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
                {"project_run_id": fixture.project_run_id},
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            projection = await launcher.launch(
                AccountResearchFleetLaunchRequest(
                    workspace_id=fixture.discovery_fixture.workspace_id,
                    project_run_id=UUID(str(fixture.project_run_id)),
                    research_directive_id=UUID(str(pin.directive_id)),
                    account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                    approved_budget_cap_cents=Decimal("300"),
                    expected_estimated_cost_cents=Decimal("300"),
                    concurrency_limit=4,
                    supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
                ),
                actor="human:account-owner",
                source_action_ref="turn:r6-account-only-launch",
                source_operation_id=uuid4(),
            )
            job = projection.jobs[0]
            task = await claim_next_task(
                conn,
                kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                worker_id="b5-account-only",
                project_run_id=ProjectRunId(job.job_id),
            )
            assert task is not None
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(job.job_id),
                worker_id="b5-account-only",
                ttl=timedelta(seconds=60),
            )
            assert lease is not None
            jobs = DbEntityResearchJobStore(conn_factory=connection)
            begun = await jobs.begin(
                job.job_id,
                fence=EntityResearchExecutionFence(
                    task_id=task.task_id,
                    worker_id="b5-account-only",
                    lease_generation=lease.generation,
                    task_attempt=1,
                ),
            )
            assert begun.admitted
            assert begun.job.authorization.selection.committee_source_keys == ()

            providers = ProductionAccountResearchProviderActions(
                settings=Settings(
                    _env_file=None,
                    exa_account_deep_acquisition_enabled=True,
                    sumble_account_gap_enrichment_enabled=False,
                    sumble_committee_acquisition_enabled=False,
                ),
                secrets=Secrets(
                    _env_file=None,
                    exa_api_key=SecretStr("b5-test-exa"),
                ),
                storage=storage,
                pre_spend_gate=cast(PreSpendGate, object()),
                gateway=cast(LLMGateway, object()),
                gateway_config=GatewayConfig(),
                conn_factory=connection,
            )
            bindings = await providers.resolve(begun.job)
            assert set(bindings) == {
                "research_account_deep",
                "enrich_account",
                "discover_buying_committee",
            }
            with pytest.raises(EntityResearchGovernedRejection) as rejection:
                await bindings["discover_buying_committee"].action.execute(
                    cast(GovernedResearchToolRequest, object()),
                    before_dispatch=None,
                    settle_terminal=None,
                )
            assert rejection.value.code == "provider_not_selected"

            # A directive that DID select committee discovery must still fail loudly when the
            # no-reveal committee provider is unconfigured.
            selection = begun.job.authorization.selection
            committee_selection = EntityResearchSelection.model_validate(
                selection.model_copy(
                    update={
                        "committee_source_keys": (PEOPLE_SOURCE_KEY,),
                        "admitted_source_keys": (
                            *selection.admitted_source_keys,
                            PEOPLE_SOURCE_KEY,
                        ),
                    }
                ).model_dump(mode="python")
            )
            authorization = EntityResearchJobAuthorization.model_validate(
                begun.job.authorization.model_copy(
                    update={"selection": committee_selection}
                ).model_dump(mode="python")
            )
            committee_job = begun.job.model_copy(update={"authorization": authorization})
            with pytest.raises(EntityResearchProductionCompositionError, match="committee"):
                await providers.resolve(committee_job)

    run_async(scenario())


def test_comprehensive_directive_validates_and_launches_all_acquisition_fields(
    tmp_path: Path,
) -> None:
    """The fixed 21-field profile is directive-valid and launches end to end.

    Contract §3.2/§3.3: a comprehensive directive carries all 21 ``PROSE_ACCOUNT_FIELDS`` —
    including the scoring-era ``core.*`` firmographics the DEEP-only validator used to refuse
    and the three zero-acquisition rows (``core.account_name``, ``core.employee_range``,
    ``core.revenue_band``). The launch selection admits exactly the acquisition subset: a field
    with no §3.1 source is reused or derived, never bought, so it carries no source authority
    (EntityResearchSelection requires an authority entry for every admitted field, though that
    entry may authorize no source at all — see the settlement-F3 assertions below). Fields outside
    the fixed profile keep the strict validator unchanged. Directional questions are optional in
    the durable directive contract; this case intentionally omits them to prove that the fixed
    field profile is sufficient launch authority by itself.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r6-comprehensive-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
                deep_field_keys=(_HIRING, _TECH, _PAIN, _MOVES, _INDUSTRY),
            )
            directive_body, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=PROSE_ACCOUNT_FIELDS,
                allowed_source_keys=(
                    "exa_deep",
                    "sumble_jobs",
                    "sumble_organizations",
                    "sumble_tech_stack",
                    "sumble_people",
                ),
                questions=(),
                # The browser's comprehensive-profile default intentionally shares one opaque
                # policy reference across freshness and recursion. The flattened selection must
                # retain it once, rather than rejecting the launch as internally duplicated.
                freshness_policy_ref="default",
                recursion_policy_ref="default",
            )
            pin = account_spec.research_directive
            assert pin is not None
            assert set(directive_body.field_keys) == set(PROSE_ACCOUNT_FIELDS)
            await conn.execute(
                text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
                {"project_run_id": fixture.project_run_id},
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            projection = await launcher.launch(
                AccountResearchFleetLaunchRequest(
                    workspace_id=fixture.discovery_fixture.workspace_id,
                    project_run_id=UUID(str(fixture.project_run_id)),
                    research_directive_id=UUID(str(pin.directive_id)),
                    account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                    approved_budget_cap_cents=Decimal("300"),
                    expected_estimated_cost_cents=Decimal("300"),
                    concurrency_limit=4,
                    supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
                ),
                actor="human:account-owner",
                source_action_ref="turn:r6-comprehensive-launch",
                source_operation_id=uuid4(),
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT lifecycle_json FROM entity_research_run "
                            "WHERE research_run_id=:run_id"
                        ),
                        {"run_id": projection.research_run_id},
                    )
                )
                .mappings()
                .one()
            )
            selection = EntityResearchSelection.model_validate(
                stored["lifecycle_json"]["selection"]
            )
            assert selection.research_questions == ()
            assert selection.policy_refs.count("default") == 1
            zero_acquisition = {"core.account_name", "core.employee_range", "core.revenue_band"}
            expected_acquisition = set(PROSE_ACCOUNT_FIELDS) - zero_acquisition
            assert set(selection.admitted_field_keys) == expected_acquisition
            authority = {
                item.field_key: tuple(item.source_keys) for item in selection.field_source_authority
            }
            assert set(authority) == expected_acquisition
            for field_key, sources in authority.items():
                assert set(sources) <= set(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES[field_key]), (
                    field_key
                )

            # Settlement F3: every compiled (field, source) pair must be one a real dispatch could
            # actually make. Ownership and wire-requestability are different facts — Sumble
            # Organizations *owns* seven §3.1 rows and its pinned v9 action can ask for three —
            # so an un-intersected authority minted pairs no attempt could ever settle, and the
            # execution-completeness reader then waited on them forever: the account could never
            # reach a terminal disposition. Asserted against the resolver's own support predicate,
            # so the launcher cannot drift from the wire it plans for.
            unrequestable = tuple(
                (field_key, source_key)
                for field_key, sources in authority.items()
                for source_key in sources
                if source_key in SUMBLE_SOURCE_KEYS
                and not sumble_action_supports_field(field_key, source_key)
            )
            assert not unrequestable
            # The three rows that carry the defect. Two keep a second, requestable owner; the
            # third has none and is admitted with *no* authority at all — nothing outstanding,
            # so a fully-attempted account settles with it as an honest gap instead of deadlocking
            # (the coverage ledger still reports the row; §5.1's zero-acquisition disposition).
            assert authority["account.total_funding"] == ("exa_deep",)
            assert authority["account.recent_funding"] == ("exa_deep",)
            assert authority["core.company_linkedin_url"] == ()
            # An empty authority is still exact authority: it authorizes nothing, so the run-wide
            # admitted source set never gains a source on that field's behalf.
            assert "core.company_linkedin_url" in selection.admitted_field_keys
            assert set(selection.admitted_source_keys) == {
                source for sources in authority.values() for source in sources
            } | set(selection.committee_source_keys)

            # Outside the fixed profile the strict validator is unchanged: a reserved scoring
            # field is still refused as a directive field.
            with pytest.raises(ResearchDirectiveInvalid, match="not a registered deep field"):
                await validate_research_directive_draft(
                    conn,
                    workspace_id=fixture.discovery_fixture.workspace_id,
                    project_id=fixture.discovery_fixture.project_id,
                    product_id=fixture.discovery_fixture.product_id,
                    icp_key=fixture.deep_icp_key,
                    icp_version=fixture.deep_icp_version,
                    body=ResearchDirectiveBody(
                        account_scope=ResearchAccountScope(
                            explicit_account_ids=(fixture.selected_account_id,)
                        ),
                        field_keys=("account.scoring.fit",),
                        questions=(),
                        committee_plan=directive_body.committee_plan,
                        source_policy=directive_body.source_policy,
                        privacy_policy=directive_body.privacy_policy,
                        effort_policy=directive_body.effort_policy,
                    ),
                    overrides={},
                )

    run_async(scenario())


def test_an_account_outside_the_sealed_membership_is_refused_before_any_write(
    tmp_path: Path,
) -> None:
    """Plan §6 Slice-5 case 4: the seal is the launch's account authority, checked first.

    An explicitly selected Account that the sealed generation does not contain has no lineage to
    research against — its claims could not cite the seal the whole run is authorized by. The
    refusal happens inside the launch transaction *before* the estimate, the run, the jobs, or any
    account_run row, so a mis-scoped selection leaves no durable trace at all.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r6-outside-seal-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            workspace_id = fixture.discovery_fixture.workspace_id
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES),
                allowed_source_keys=("exa_deep",),
                questions=(
                    ResearchQuestion(
                        question_id="qualitative-burden",
                        text="Where is administrative work creating avoidable burden?",
                        target_field_key=_PAIN,
                    ),
                    ResearchQuestion(
                        question_id="strategic-change",
                        text="What strategic operational changes are visible?",
                        target_field_key=_MOVES,
                    ),
                ),
            )
            pin = account_spec.research_directive
            assert pin is not None
            # A real, workspace-local account that simply was not part of the sealed generation —
            # so the refusal is about membership, not about a missing entity.
            unsealed_account_id = await insert_account_entity(
                conn,
                canonical_name="Outside The Seal Clinics",
                primary_domain="outside-the-seal.test",
                workspace_id=workspace_id,
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            with pytest.raises(
                AccountResearchFleetLaunchError,
                match="outside the exact sealed",
            ):
                await launcher.launch(
                    AccountResearchFleetLaunchRequest(
                        workspace_id=workspace_id,
                        project_run_id=UUID(str(fixture.project_run_id)),
                        research_directive_id=UUID(str(pin.directive_id)),
                        account_entity_ids=(
                            UUID(str(fixture.selected_account_id)),
                            UUID(str(unsealed_account_id)),
                        ),
                        approved_budget_cap_cents=Decimal("300"),
                        expected_estimated_cost_cents=Decimal("300"),
                    ),
                    actor="human:account-owner",
                    source_action_ref="turn:r6-outside-seal-launch",
                    source_operation_id=uuid4(),
                )

            for table in ("entity_research_run", "entity_research_job", "account_run"):
                assert (
                    await conn.execute(
                        text(  # noqa: S608 - fixed table names from this test's own tuple
                            f"SELECT count(*) FROM {table} WHERE project_run_id=:project_run_id"
                        ),
                        {"project_run_id": fixture.project_run_id},
                    )
                ).scalar_one() == 0

    run_async(scenario())


def test_the_launch_receipt_pins_the_whole_seal_and_fixes_replay_identity(
    tmp_path: Path,
) -> None:
    """Plan §6 Slice-5 case 5: the complete receipt is pinned *and* it is part of the identity.

    Two halves, both required. The stored selection must carry every field of the immutable
    receipt — generation, seal hash, and both manifest ref/sha pairs — because downstream provider
    work reads its discovery authority from exactly that receipt instead of re-deriving present-day
    membership. And the receipt must enter ``request_sha``, which is what the run/job ids are
    derived from: the same selection against the same seal replays onto the same run, while the
    same selection against a *different* seal is a different launch, not an idempotent repeat.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r6-receipt-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            workspace_id = fixture.discovery_fixture.workspace_id
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_PAIN, _MOVES),
                allowed_source_keys=("exa_deep",),
                questions=(
                    ResearchQuestion(
                        question_id="qualitative-burden",
                        text="Where is administrative work creating avoidable burden?",
                        target_field_key=_PAIN,
                    ),
                    ResearchQuestion(
                        question_id="strategic-change",
                        text="What strategic operational changes are visible?",
                        target_field_key=_MOVES,
                    ),
                ),
            )
            pin = account_spec.research_directive
            assert pin is not None

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            recorded: list[dict[str, object]] = []
            real_sha = account_research_fleet_launch._sha

            def recording_sha(value: object) -> str:
                if isinstance(value, dict) and "discovery_receipt" in value:
                    recorded.append(value)
                return real_sha(value)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            request = AccountResearchFleetLaunchRequest(
                workspace_id=workspace_id,
                project_run_id=UUID(str(fixture.project_run_id)),
                research_directive_id=UUID(str(pin.directive_id)),
                account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
            )
            launch_operation_id = uuid4()
            account_research_fleet_launch._sha = recording_sha
            try:
                projection = await launcher.launch(
                    request,
                    actor="human:account-owner",
                    source_action_ref="turn:r6-receipt-launch",
                    source_operation_id=launch_operation_id,
                )
                replayed = await launcher.launch(
                    request,
                    actor="human:account-owner",
                    source_action_ref="turn:r6-receipt-launch",
                    source_operation_id=launch_operation_id,
                )
            finally:
                account_research_fleet_launch._sha = real_sha

            seal = await get_discovery_batch_seal(
                conn, workspace_id=workspace_id, batch_id=fixture.discovery_batch_id
            )
            bundle = await get_discovery_batch_manifest(
                conn, workspace_id=workspace_id, batch_id=fixture.discovery_batch_id
            )
            assert seal is not None and bundle is not None
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT lifecycle_json FROM entity_research_run "
                            "WHERE research_run_id=:run_id"
                        ),
                        {"run_id": projection.research_run_id},
                    )
                )
                .mappings()
                .one()
            )
            selection = EntityResearchSelection.model_validate(
                stored["lifecycle_json"]["selection"]
            )
            receipt = selection.discovery_receipt
            assert receipt is not None
            assert receipt == SealedDiscoveryLaunchReceipt(
                discovery_batch_id=UUID(str(fixture.discovery_batch_id)),
                discovery_generation=bundle.generation,
                discovery_seal_sha256=seal.seal_sha256,
                account_manifest_ref=bundle.account_manifest_artifact_key,
                account_manifest_sha256=bundle.account_manifest_sha256,
                claim_manifest_ref=bundle.claim_manifest_artifact_key,
                claim_manifest_sha256=bundle.claim_manifest_sha256,
            )

            # Replay identity: one durable run, and the second confirmation of the same request
            # against the same seal lands on it rather than minting a second paid fleet.
            assert replayed.research_run_id == projection.research_run_id
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_run "
                        "WHERE project_run_id=:project_run_id"
                    ),
                    {"project_run_id": fixture.project_run_id},
                )
            ).scalar_one() == 1

            # The receipt is *inside* that identity: the run id is uuid5 over the request hash the
            # launcher actually built, and swapping only the seal hash in it moves the run id.
            assert len(recorded) == 2
            request_payload = recorded[0]
            assert request_payload["discovery_receipt"] == receipt.model_dump(mode="json")
            assert projection.research_run_id == uuid5(
                account_research_fleet_launch._RUN_NAMESPACE, real_sha(request_payload)
            )
            other_seal = {
                **request_payload,
                "discovery_receipt": {
                    **cast(dict[str, object], request_payload["discovery_receipt"]),
                    "discovery_seal_sha256": "0" * 64,
                },
            }
            assert (
                uuid5(account_research_fleet_launch._RUN_NAMESPACE, real_sha(other_seal))
                != projection.research_run_id
            )

    run_async(scenario())
