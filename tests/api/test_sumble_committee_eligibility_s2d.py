"""S2D seven-condition, zero-call, audit, budget and fresh-reuse acceptance."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.committee_eligibility import (
    CommitteeEligibilityService,
    CommitteeEnumerationSource,
)
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    SumbleCommitteeOutcome,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_launch import GatedSumbleCommitteeLauncher
from clue_core import (
    CommitteeAcquisitionRequest,
    CommitteeEligibilityCondition,
    CommitteeEligibilityOutcome,
    CommitteeExecutionAuthorization,
    UseClass,
    new_claim_id,
)
from clue_research.verification import PreSpendGateImpl
from clue_storage import FsStorage
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport, _setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _ForbiddenStarter:
    def __init__(self) -> None:
        self.calls = 0

    async def start(self, preflight):
        del preflight
        self.calls += 1
        raise AssertionError("ineligible S2D request reached the acquisition coordinator")


def _authorization(request: CommitteeAcquisitionRequest) -> CommitteeExecutionAuthorization:
    assert request.research_direction_ref is not None
    return CommitteeExecutionAuthorization(
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        project_run_id=request.project_run_id,
        account_id=request.account_id,
        research_direction_ref=request.research_direction_ref,
        research_directive=request.research_directive,
        committee_plan_ref=request.committee_plan_ref,
        confirmation_ref="turn:human-confirmation:s2d",
        confirmed_by_human=True,
        personal_data_allowed=True,
        jurisdiction_policy_ref="jurisdiction-policy:strict-default:v1",
        jurisdiction_allowed=True,
        allowed_use_classes=(UseClass.PROFESSIONAL_PUBLIC,),
        identity_policy_ref="identity-policy:linkedin-or-verified-email:v1",
        identity_acquisition_allowed=True,
        budget_authorization_ref="budget-authorization:s2d:v1",
        contact_reveals_allowed=False,
    )


def _sources() -> tuple[CommitteeEnumerationSource, ...]:
    return (
        CommitteeEnumerationSource(source_key="sumble_teams", source_tier=1),
        CommitteeEnumerationSource(source_key="sumble_people", source_tier=1),
    )


@pytest.mark.parametrize(
    ("case", "failed_condition"),
    (
        ("sealed_batch", CommitteeEligibilityCondition.SEALED_BATCH_MEMBERSHIP),
        ("pass_a", CommitteeEligibilityCondition.PASS_A_COMPLETE),
        ("must_haves", CommitteeEligibilityCondition.MUST_HAVE_CRITERIA),
        ("human_tier", CommitteeEligibilityCondition.HUMAN_APPROVED_TIER),
        ("committee_plan", CommitteeEligibilityCondition.CONFIRMED_COMMITTEE_PLAN),
        ("personal_data", CommitteeEligibilityCondition.GOVERNANCE_AND_BUDGET),
        ("jurisdiction", CommitteeEligibilityCondition.GOVERNANCE_AND_BUDGET),
        ("use_class", CommitteeEligibilityCondition.GOVERNANCE_AND_BUDGET),
        ("identity", CommitteeEligibilityCondition.GOVERNANCE_AND_BUDGET),
    ),
)
def test_s2d_each_ineligible_condition_is_independent_and_creates_no_paid_operation(
    tmp_path: Path,
    case: str,
    failed_condition: CommitteeEligibilityCondition,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(
                conn,
                storage,
                workspace_id=f"ws-s2d-{case}",
                strict_s2d=True,
                s2d_criterion_state="unclear" if case == "must_haves" else "yes",
            )
            authorization = _authorization(request)
            if case == "sealed_batch":
                request = request.model_copy(update={"discovery_seal_sha256": "0" * 64})
            elif case == "pass_a":
                await conn.execute(
                    text(
                        "UPDATE project_phase_checkpoint SET status='failed', committed_at=NULL "
                        "WHERE project_run_id=:run AND phase='scoring'"
                    ),
                    {"run": request.project_run_id},
                )
            elif case == "human_tier":
                request = request.model_copy(update={"tier_claim_id": new_claim_id()})
            elif case == "committee_plan":
                authorization = authorization.model_copy(update={"confirmed_by_human": False})
            elif case == "personal_data":
                authorization = authorization.model_copy(update={"personal_data_allowed": False})
            elif case == "jurisdiction":
                authorization = authorization.model_copy(update={"jurisdiction_allowed": False})
            elif case == "use_class":
                authorization = authorization.model_copy(
                    update={"allowed_use_classes": (UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,)}
                )
            elif case == "identity":
                authorization = authorization.model_copy(
                    update={"identity_acquisition_allowed": False}
                )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            gate = PreSpendGateImpl(conn_factory=same_connection)
            eligibility = CommitteeEligibilityService(
                storage=storage,
                pre_spend_gate=gate,
                sources=_sources(),
                conn_factory=same_connection,
            )
            starter = _ForbiddenStarter()
            launcher = GatedSumbleCommitteeLauncher(
                eligibility=eligibility,
                starter=starter,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            result = await launcher.start(preflight, authorization=authorization)
            assert result.eligibility.outcome is CommitteeEligibilityOutcome.INELIGIBLE
            assert result.acquisition is None
            assert starter.calls == 0
            failed = {item.condition for item in result.eligibility.conditions if not item.passed}
            assert failed == {failed_condition}
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM committee_acquisition_operation "
                        "WHERE workspace_id=:workspace_id AND account_id=:account_id"
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "account_id": request.account_id,
                    },
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM committee_eligibility_decision "
                        "WHERE workspace_id=:workspace_id AND account_id=:account_id"
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "account_id": request.account_id,
                    },
                )
            ).scalar_one() == 1
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM gate_decision WHERE run_id=:run "
                        "AND request_kind='enumeration' "
                        "AND enumeration_scope='committee'"
                    ),
                    {"run": request.project_run_id},
                )
            ).scalar_one() == 2

    run_async(scenario())


def test_s2d_project_budget_rejection_precedes_operation_reservation(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2d-budget", strict_s2d=True)
            await conn.execute(
                text(
                    "UPDATE project_run SET budget_cap_cents=spent_cents WHERE id=:project_run_id"
                ),
                {"project_run_id": request.project_run_id},
            )

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            eligibility = CommitteeEligibilityService(
                storage=storage,
                pre_spend_gate=PreSpendGateImpl(conn_factory=same_connection),
                sources=_sources(),
                conn_factory=same_connection,
            )
            starter = _ForbiddenStarter()
            result = await GatedSumbleCommitteeLauncher(
                eligibility=eligibility, starter=starter
            ).start(
                compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5")),
                authorization=_authorization(request),
            )
            condition = next(
                item
                for item in result.eligibility.conditions
                if item.condition is CommitteeEligibilityCondition.GOVERNANCE_AND_BUDGET
            )
            assert condition.passed is False
            assert any(
                reason.startswith("provider_budget_rejected:") for reason in condition.reason_codes
            )
            assert starter.calls == 0
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM committee_acquisition_operation "
                        "WHERE workspace_id=:workspace_id AND account_id=:account_id"
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "account_id": request.account_id,
                    },
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_s2d_eligible_acquires_resumes_and_fresh_replay_reuses_without_calls(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(
                conn,
                storage,
                workspace_id="ws-s2d-eligible",
                strict_s2d=True,
                account_tier="tier4",
                tier_claim_source_tier=4,
            )

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
            eligibility = CommitteeEligibilityService(
                storage=storage,
                pre_spend_gate=PreSpendGateImpl(conn_factory=same_connection),
                sources=_sources(),
                conn_factory=same_connection,
            )
            launcher = GatedSumbleCommitteeLauncher(
                eligibility=eligibility,
                starter=coordinator,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            first = await launcher.start(preflight, authorization=_authorization(request))
            assert first.eligibility.outcome is CommitteeEligibilityOutcome.ELIGIBLE
            assert first.acquisition is not None
            assert first.acquisition.outcome is SumbleCommitteeOutcome.WAITING_EXTERNAL
            assert transport.calls == ["teams", "people_submit"]

            for _ in range(2):
                await conn.execute(
                    text(
                        "UPDATE committee_acquisition_operation SET next_poll_at=:past "
                        "WHERE id=:operation_id"
                    ),
                    {
                        "operation_id": first.acquisition.operation.operation_id,
                        "past": datetime.now(UTC) - timedelta(seconds=1),
                    },
                )
                resumed = await launcher.start(preflight, authorization=_authorization(request))
            assert resumed.acquisition is not None
            assert resumed.acquisition.outcome is SumbleCommitteeOutcome.READY
            provider_calls = len(transport.calls)

            replay = await launcher.start(preflight, authorization=_authorization(request))
            assert replay.eligibility.outcome is CommitteeEligibilityOutcome.REUSABLE
            assert replay.eligibility.reusable_operation_id == (
                resumed.acquisition.operation.operation_id
            )
            assert replay.acquisition is None
            assert len(transport.calls) == provider_calls
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM committee_acquisition_operation "
                        "WHERE workspace_id=:workspace_id AND account_id=:account_id"
                    ),
                    {
                        "workspace_id": request.workspace_id,
                        "account_id": request.account_id,
                    },
                )
            ).scalar_one() == 1

            nested = await conn.begin_nested()
            with pytest.raises(DBAPIError, match="committee eligibility decisions are immutable"):
                await conn.execute(
                    text(
                        "UPDATE committee_eligibility_decision SET policy_version='tampered' "
                        "WHERE id=:decision_id"
                    ),
                    {"decision_id": replay.eligibility.decision_id},
                )
            await nested.rollback()

    run_async(scenario())
