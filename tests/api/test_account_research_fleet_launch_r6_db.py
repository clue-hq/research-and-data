"""R6 confirmed-direction compiler acceptance on an isolated Postgres transaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

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
from clue_api.entity_research_provider_wiring import ProductionAccountResearchProviderActions
from clue_api.sumble_account_gaps import compile_sumble_account_gap_preflight
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_config import GatewayConfig, Secrets, Settings
from clue_core import LLMGateway, PreSpendGate, ProjectPhase, ProjectRunId, ResearchQuestion
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchExecutionFence,
    FleetTaskKind,
    WorkId,
    acquire_work_lease,
    claim_next_task,
)
from clue_research.durable import find_account_runs_for_entity
from clue_research.durable.provider_spend import (
    ProviderSpendRunIneligible,
    require_provider_spend_capacity,
)
from clue_storage import FsStorage
from tests._run_lineage import assert_run_registered
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_HIRING = "account.hiring_velocity_eng"


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    async with conn.begin_nested():
        yield conn


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
                _HIRING: ("sumble_jobs", "exa_deep"),
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
            stored_job = await DbEntityResearchJobStore(conn_factory=connection).get_job(
                job.job_id
            )
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
            )
            begun = await DbEntityResearchJobStore(conn_factory=connection).begin(
                job.job_id,
                fence=fence,
            )
            assert begun.admitted
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
            assert capacity.phase is ProjectPhase.SCORING
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
            assert preflight.request.fields[0].field_key == _HIRING
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
