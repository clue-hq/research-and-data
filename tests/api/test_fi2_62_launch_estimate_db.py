"""FI-2 §6.2 — the launch estimate stays **gross**, on purpose, and that is pinned.

Spec §6.2 lists "recompute the launch estimate net of skips" as a should-have (§11 open item 3).
It is deliberately not done, for reasons argued in full at the check itself in
``account_research_fleet_launch.py``; the short version is that
``expected_estimated_cost_cents`` is a *caller-supplied* number with no server-side proposal
surface, and the same per-account figure is each job's spend authority — so netting the sum alone
would approve a launch for less authority than it hands out.

That makes "gross" a contract, not an accident, so it gets a test: an account whose admitted
neutral fields are already answered — the very account the fresh-skip will make nearly free —
still launches at the full directive estimate, and a caller who "helpfully" nets the number is
refused. Whoever implements netting later will fail this test, read the argument, and change both
sides together.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_entity_research import born_complete_account_field_keys
from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchError,
    AccountResearchFleetLaunchRequest,
)
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ResearchQuestion,
    ReuseScope,
    RunId,
)
from clue_research.claimstore import insert_claim
from clue_storage import FsStorage
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_HIRING = "account.hiring_velocity_eng"
#: The whole directive estimate for the one-account fleet: ``effort_policy.budget_cap_cents``.
_GROSS = Decimal("300")


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    async with conn.begin_nested():
        yield conn


async def _already_answered(
    conn: AsyncConnection, *, account_id: EntityId, field_key: str, value: Any
) -> None:
    """A fresh, evidence-backed, conflict-free neutral claim: born complete, so free to reuse."""

    now = datetime.now(UTC) - timedelta(days=2)
    await insert_claim(
        conn,
        Claim(
            entity_id=account_id,
            entity_type=EntityType.ACCOUNT,
            field_key=field_key,
            value_json=value,
            source_url="https://insighthealth.ai/about",
            source_key="sumble_jobs",
            source_tier=cast(Any, 2),
            extraction_method=ExtractionMethod.API,
            evidence_span="An earlier project's own sourced evidence.",
            confidence=cast(Any, 0.9),
            observed_at=now,
            collected_at=now,
            run_id=RunId(uuid4()),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id="ws_fixture_insight_health_aura",
        ),
    )


def test_fi2_62_an_already_answered_account_still_launches_at_the_gross_estimate(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "fi2-62-launch-artifacts")
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn, pages=_pages(), storage=storage
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
            await _already_answered(
                conn,
                account_id=fixture.selected_account_id,
                field_key=_PAIN,
                value="Referral intake still depends on manual fax reconciliation.",
            )
            await _already_answered(
                conn,
                account_id=fixture.selected_account_id,
                field_key=_MOVES,
                value="The practice is centralising its referral program.",
            )
            await _already_answered(
                conn,
                account_id=fixture.selected_account_id,
                field_key=_HIRING,
                value=6,
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            # Premise: every admitted field really is borrowed, so a netted estimate would be 0 and
            # the assertions below are about a *real* skip, not an empty one.
            assert await born_complete_account_field_keys(
                conn,
                workspace_id=workspace_id,
                account_entity_id=fixture.selected_account_id,
                field_keys=(_PAIN, _MOVES, _HIRING),
            ) == frozenset({_PAIN, _MOVES, _HIRING})

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )

            def _request(expected: Decimal) -> AccountResearchFleetLaunchRequest:
                return AccountResearchFleetLaunchRequest(
                    workspace_id=workspace_id,
                    project_run_id=UUID(str(fixture.project_run_id)),
                    research_directive_id=UUID(str(pin.directive_id)),
                    account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                    approved_budget_cap_cents=_GROSS,
                    expected_estimated_cost_cents=expected,
                    concurrency_limit=4,
                    supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
                )

            # A caller who nets the estimate against the borrowed set is refused: the launch
            # authority is the directive's gross figure, and both sides must agree on it.
            with pytest.raises(
                AccountResearchFleetLaunchError,
                match="approved estimate differs from the current effective directives",
            ):
                await launcher.launch(
                    _request(Decimal(0)),
                    actor="human:fi2-62",
                    source_action_ref="turn:fi2-62-netted",
                    source_operation_id=uuid4(),
                )

            projection = await launcher.launch(
                _request(_GROSS),
                actor="human:fi2-62",
                source_action_ref="turn:fi2-62-gross",
                source_operation_id=uuid4(),
            )
            assert projection.selected_accounts == 1
            assert projection.budget_cap_cents == _GROSS
            # Nothing has been spent by launching: the skip shows up as under-spend, not as a
            # smaller ceiling.
            assert projection.spent_cents == Decimal(0)

    run_async(scenario())
