"""M8D R11.1/R11.4 — the join-only DEEP phase bridge over the R6 account-research fleet.

Postgres acceptance for the ratified state table: no fleet run holds durably; a working fleet waits
externally behind the R11.4 fleet-shaped payload; a suspended fleet pauses with its diagnosis (never
FAILED); a terminal fleet completes DEEP with the fleet's terminal account count and settled spend
and advances the run to VERIFICATION. Nothing here launches research, and no ``account_deep_launch``
row is ever written (AC1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
    AccountResearchFleetState,
    read_latest_account_fleet_for_project_run,
)
from clue_api.entity_research_deep_phase import (
    DEEP_FLEET_POLL_INTERVAL,
    REASON_FLEET_NOT_LAUNCHED,
    REASON_FLEET_SUSPENDED,
    REASON_FLEET_TERMINAL,
    EntityResearchDeepPhaseHandler,
)
from clue_core import (
    DeepFleetExternalWait,
    PhaseContext,
    PhaseHandler,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    new_project_run_id,
    phase_key,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchRunKind,
    SelectedResearchSubject,
)
from clue_fleet import EntityResearchJobEnvelope, EntityResearchRunEnvelope
from clue_research.durable import (
    REENTRANT_HOLD_KEY,
    DbProjectRunStore,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunStatus,
)
from tests._workspace import seed_project, seed_run
from tests.api.test_account_research_fleet_r6_db import _claim_begin_finalize
from tests.fleet.conftest import rollback_conn, run_async
from tests.fleet.entity_research_r2_helpers import run_envelope

pytestmark = pytest.mark.usefixtures("require_profiling_db")


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    yield conn


class _Scope:
    """One seeded project run plus the identifiers a bound fleet run must agree with."""

    def __init__(self, *, workspace_id: str, project_id: str, project_run_id: ProjectRunId) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.project_run_id = project_run_id
        self.product_id = f"product-{project_run_id}"


async def _seed_scope(conn: AsyncConnection, *, workspace_id: str = "acme") -> _Scope:
    project = await seed_project(conn, workspace_id, name=f"R11 {uuid4().hex[:8]}")
    project_run_id = new_project_run_id()
    await seed_run(
        conn,
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        project_id=project.project_id,
    )
    return _Scope(
        workspace_id=workspace_id,
        project_id=project.project_id,
        project_run_id=project_run_id,
    )


def _context(scope: _Scope) -> PhaseContext:
    return PhaseContext(
        project_run_id=scope.project_run_id,
        project_id=scope.project_id,
        brand_id="brand-r11",
        phase=ProjectPhase.DEEP,
        workspace_id=scope.workspace_id,
        icp_key="default",
        icp_version=1,
    )


def _envelope(
    scope: _Scope, *, accounts: int = 3, project_id: str | None = None
) -> EntityResearchRunEnvelope:
    """An account-research launch envelope pinned to ``scope``'s exact workspace/project/run.

    ``project_id`` overrides only the project, so a test can construct the one shape the adapter's
    scoping guard defends against: a fleet run bound to this project run but owned by another
    project.
    """

    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH, concurrency_limit=2)
    first = base.lifecycle.selection.subjects[0]
    subjects = (
        first,
        *(
            SelectedResearchSubject(subject_entity_id=uuid4(), basis=first.basis)
            for _ in range(accounts - 1)
        ),
    )
    scoped = {
        "workspace_id": scope.workspace_id,
        "project_id": project_id if project_id is not None else scope.project_id,
        "product_id": scope.product_id,
        "project_run_id": UUID(str(scope.project_run_id)),
    }
    selection = base.lifecycle.selection.model_copy(update={**scoped, "subjects": subjects})
    lifecycle = base.lifecycle.model_copy(update={"selection": selection})
    template = base.jobs[0]
    jobs: list[EntityResearchJobEnvelope] = []
    for priority, subject in enumerate(subjects):
        authorization = EntityResearchJobAuthorization(
            **{
                **template.authorization.model_dump(mode="python"),
                **scoped,
                "job_id": uuid4(),
                "subject_entity_id": subject.subject_entity_id,
                "selection": selection,
                "checkpoint_thread_id": (
                    f"checkpoint:{lifecycle.run_id}:{subject.subject_entity_id}"
                ),
                "attempt_id": uuid4(),
                "lease_id": uuid4(),
            }
        )
        jobs.append(
            EntityResearchJobEnvelope(
                authorization=authorization,
                priority=priority,
                budget_envelope_ref=f"budget:job:{authorization.job_id}",
                budget_cap_cents=Decimal("3.00"),
            )
        )
    return EntityResearchRunEnvelope(
        lifecycle=lifecycle,
        jobs=tuple(jobs),
        budget_cap_cents=Decimal("10.00"),
        concurrency_limit=2,
    )


def _service(conn: AsyncConnection) -> AccountResearchFleetService:
    return AccountResearchFleetService(conn_factory=lambda: _same_connection(conn))


def _handler(conn: AsyncConnection) -> EntityResearchDeepPhaseHandler:
    return EntityResearchDeepPhaseHandler(conn_factory=lambda: _same_connection(conn))


async def _launch(
    conn: AsyncConnection,
    scope: _Scope,
    *,
    accounts: int = 3,
    project_id: str | None = None,
) -> EntityResearchRunEnvelope:
    """Launch a fleet run the way the confirmed ``launch_account_research@1`` tool does."""

    envelope = _envelope(scope, accounts=accounts, project_id=project_id)
    await _service(conn).launch(
        envelope,
        # Every job is a canary, so the whole set is admitted and the canary health gate (which
        # only fires while some remainder is still held) never colours these scenarios.
        policy=AccountResearchFleetPolicy(canary_size=accounts),
        actor="user:owner",
        source_operation_id=envelope.lifecycle.run_id,
        source_action_ref=f"agent-action:launch-account-research:{uuid4()}",
    )
    return envelope


async def _machine(conn: AsyncConnection, scope: _Scope) -> ProjectRun:
    """A state machine over the test connection, with the run parked at DEEP."""

    store = DbProjectRunStore(conn_factory=lambda: _same_connection(conn))
    await store.transition(
        scope.project_run_id, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE
    )
    registry = PhaseHandlerRegistry()
    registry.register(_handler(conn))
    return ProjectRun(store=store, registry=registry)


async def _settle_spend(
    conn: AsyncConnection, envelope: EntityResearchRunEnvelope, cents: str
) -> Decimal:
    """Stand in for the R2 spend reconciliation that settles a run's cost before it terminates."""

    await conn.execute(
        text("UPDATE entity_research_run SET spent_cents=:cents WHERE research_run_id=:run_id"),
        {"cents": Decimal(cents), "run_id": envelope.lifecycle.run_id},
    )
    return Decimal(cents)


async def _age(conn: AsyncConnection, envelope: EntityResearchRunEnvelope) -> None:
    """Backdate a fleet launch so "the latest run" is unambiguous inside one test transaction."""

    await conn.execute(
        text(
            "UPDATE entity_research_account_fleet SET created_at=created_at - interval '1 hour' "
            "WHERE research_run_id=:run_id"
        ),
        {"run_id": envelope.lifecycle.run_id},
    )


async def _account_deep_launches(conn: AsyncConnection) -> int:
    return int((await conn.execute(text("SELECT count(*) FROM account_deep_launch"))).scalar_one())


async def _finalize_all(
    conn: AsyncConnection,
    envelope: EntityResearchRunEnvelope,
    *,
    outcomes: tuple[ResearchFinalizationOutcome, ...],
) -> None:
    assert len(outcomes) == len(envelope.jobs)
    for job, outcome in zip(envelope.jobs, outcomes, strict=True):
        await _claim_begin_finalize(conn, envelope, job.authorization.job_id, outcome=outcome)
    await _service(conn).reconcile(envelope.lifecycle.run_id)


# --- the ratified state table ------------------------------------------------------------------


def test_a_run_with_no_fleet_launch_holds_durably_and_resumes_once_research_lands() -> None:
    """AC2: no failure, no silent completion — a plain hold the confirmed launch clears."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            machine = await _machine(conn, scope)

            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.PAUSED)
            checkpoint = await machine.await_checkpoint(scope.project_run_id)
            assert checkpoint is not None
            assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
            assert checkpoint.payload["reason_code"] == REASON_FLEET_NOT_LAUNCHED
            assert checkpoint.payload["resume_action"] == "launch_account_research@1"
            # A plain hold, not a decision gate: resuming re-runs the handler rather than needing
            # an approval that would finalize a DEEP phase which researched nothing.
            assert checkpoint.payload[REENTRANT_HOLD_KEY] is True

            # The operator launches account research through the confirmed tool and resumes; the
            # fleet is still working, so DEEP re-enters and waits instead of completing.
            envelope = await _launch(conn, scope)
            await machine.resume(scope.project_run_id)
            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)
            waiting = await machine.await_checkpoint(scope.project_run_id)
            assert waiting is not None
            assert waiting.status is PhaseCheckpointStatus.WAITING_EXTERNAL

            outcomes = (ResearchFinalizationOutcome.COMPLETED,) * len(envelope.jobs)
            await _finalize_all(conn, envelope, outcomes=outcomes)
            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.VERIFICATION, ProjectRunStatus.ACTIVE)
            assert await _account_deep_launches(conn) == 0

    run_async(scenario())


def test_a_working_fleet_waits_externally_behind_the_r11_4_payload() -> None:
    """Mixed live job states become a reference-only census; the run stays ACTIVE."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            envelope = await _launch(conn, scope)
            # One account finishes; the rest are still queued — a genuinely mixed census.
            await _claim_begin_finalize(conn, envelope, envelope.jobs[0].authorization.job_id)
            projection = await _service(conn).reconcile(envelope.lifecycle.run_id)
            assert projection.fleet_state is AccountResearchFleetState.CANARY

            before = datetime.now(UTC)
            result = await _handler(conn).run(_context(scope))
            assert result.status is PhaseStatus.WAITING_EXTERNAL
            assert result.accounts_processed == 0
            assert result.cost_cents == Decimal(0)

            wait = DeepFleetExternalWait.model_validate(result.payload)
            assert wait.research_run_id == envelope.lifecycle.run_id
            assert wait.job_state_counts == {
                ResearchJobState.QUEUED.value: len(envelope.jobs) - 1,
                ResearchJobState.TERMINAL.value: 1,
            }
            assert before + DEEP_FLEET_POLL_INTERVAL <= wait.next_poll_at

            machine = await _machine(conn, scope)
            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)
            checkpoint = await machine.await_checkpoint(scope.project_run_id)
            assert checkpoint is not None
            assert checkpoint.status is PhaseCheckpointStatus.WAITING_EXTERNAL
            DeepFleetExternalWait.model_validate(checkpoint.payload)

    run_async(scenario())


def test_a_suspended_fleet_pauses_with_its_diagnosis_and_never_fails() -> None:
    """AC3: the fleet's suspension is honest, not broken — a human decision point, not a failure."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            envelope = await _launch(conn, scope)
            suspended_job = envelope.jobs[0].authorization.job_id
            projection = await _service(conn).pause_job(
                suspended_job,
                workspace_id=scope.workspace_id,
                actor="user:owner",
                reason_code="operator_hold",
            )
            assert projection.fleet_state is AccountResearchFleetState.SUSPENDED

            result = await _handler(conn).run(_context(scope))
            assert result.status is PhaseStatus.PAUSED
            assert result.payload["reason_code"] == REASON_FLEET_SUSPENDED
            assert result.payload["research_run_id"] == str(envelope.lifecycle.run_id)
            assert result.payload["diagnosis"] == {
                "reason_code": "account_jobs_suspended",
                "job_ids": [str(suspended_job)],
            }
            assert result.payload["suspended_at"] is not None

            machine = await _machine(conn, scope)
            run = await machine.advance(scope.project_run_id)
            assert run.status is ProjectRunStatus.PAUSED
            assert run.status is not ProjectRunStatus.FAILED
            checkpoint = await machine.await_checkpoint(scope.project_run_id)
            assert checkpoint is not None
            assert checkpoint.status is PhaseCheckpointStatus.AWAITING_INPUT
            assert checkpoint.payload["reason_code"] == REASON_FLEET_SUSPENDED

            # The operator resumes the fleet job, then the run: DEEP re-reads and moves on.
            await _service(conn).resume_job(
                suspended_job, workspace_id=scope.workspace_id, actor="user:owner"
            )
            await machine.resume(scope.project_run_id)
            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)
            resumed = await machine.await_checkpoint(scope.project_run_id)
            assert resumed is not None
            assert resumed.status is PhaseCheckpointStatus.WAITING_EXTERNAL

    run_async(scenario())


def test_a_terminal_fleet_completes_deep_with_its_counts_and_settled_spend() -> None:
    """AC1: the run reaches VERIFICATION with the fleet's terminal account count and settled cost,
    and no ``account_deep_launch`` row exists anywhere in the flow."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            envelope = await _launch(conn, scope)
            await _finalize_all(
                conn,
                envelope,
                outcomes=(
                    ResearchFinalizationOutcome.COMPLETED,
                    ResearchFinalizationOutcome.COMPLETED,
                    ResearchFinalizationOutcome.NEEDS_REVIEW,
                ),
            )
            spent = await _settle_spend(conn, envelope, "4.25")
            fleet = await read_latest_account_fleet_for_project_run(
                conn, UUID(str(scope.project_run_id)), workspace_id=scope.workspace_id
            )
            assert fleet is not None
            assert fleet.state is AccountResearchFleetState.TERMINAL

            result = await _handler(conn).run(_context(scope))
            assert result.status is PhaseStatus.COMPLETED
            assert result.accounts_processed == len(envelope.jobs)
            assert result.cost_cents == spent
            assert result.payload["reason_code"] == REASON_FLEET_TERMINAL
            assert result.payload["research_run_id"] == str(envelope.lifecycle.run_id)
            assert result.payload["selection_id"] == str(envelope.lifecycle.selection.selection_id)
            assert result.payload["finalization_outcome_counts"] == {
                ResearchFinalizationOutcome.COMPLETED.value: 2,
                ResearchFinalizationOutcome.NEEDS_REVIEW.value: 1,
            }

            machine = await _machine(conn, scope)
            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.VERIFICATION, ProjectRunStatus.ACTIVE)
            committed = await machine.await_checkpoint(
                scope.project_run_id, phase=ProjectPhase.DEEP
            )
            assert committed is not None
            assert committed.status is PhaseCheckpointStatus.COMMITTED
            assert await _account_deep_launches(conn) == 0

    run_async(scenario())


# --- scoping, currency, and re-entry ------------------------------------------------------------


def test_only_the_latest_fleet_run_bound_to_the_project_run_drives_the_phase() -> None:
    """§6c: earlier fleet runs remain visible history; a foreign-project run reads as absent."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            first = await _launch(conn, scope)
            await _finalize_all(
                conn, first, outcomes=(ResearchFinalizationOutcome.COMPLETED,) * len(first.jobs)
            )
            # Postgres freezes ``now()`` for the whole test transaction, so age the earlier launch
            # explicitly to reproduce two launches made minutes apart in production.
            await _age(conn, first)
            second = await _launch(conn, scope, accounts=2)

            fleet = await read_latest_account_fleet_for_project_run(
                conn, UUID(str(scope.project_run_id)), workspace_id=scope.workspace_id
            )
            assert fleet is not None
            assert fleet.research_run_id == second.lifecycle.run_id

            # The latest run is still working, so the phase waits rather than completing off the
            # older terminal run.
            result = await _handler(conn).run(_context(scope))
            assert result.status is PhaseStatus.WAITING_EXTERNAL
            assert (
                DeepFleetExternalWait.model_validate(result.payload).research_run_id
                == second.lifecycle.run_id
            )

            # A different workspace never sees this project run's fleet.
            assert (
                await read_latest_account_fleet_for_project_run(
                    conn, UUID(str(scope.project_run_id)), workspace_id="other-workspace"
                )
                is None
            )

    run_async(scenario())


def test_a_fleet_bound_to_another_project_is_treated_as_absent() -> None:
    """Fail closed: a fleet row whose project does not match the phase context holds the run."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            await _launch(conn, scope, project_id="prj-somewhere-else")

            result = await _handler(conn).run(_context(scope))
            assert result.status is PhaseStatus.PAUSED
            assert result.payload["reason_code"] == REASON_FLEET_NOT_LAUNCHED

    run_async(scenario())


def test_re_entry_is_a_pure_read_that_repeats_its_result() -> None:
    """AC7: the adapter owns no spend, so a replayed phase evaluates to the same terminal state."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            envelope = await _launch(conn, scope)
            await _finalize_all(
                conn,
                envelope,
                outcomes=(ResearchFinalizationOutcome.COMPLETED,) * len(envelope.jobs),
            )
            await _settle_spend(conn, envelope, "2.50")
            handler = _handler(conn)
            first = await handler.run(_context(scope))
            second = await handler.run(_context(scope))
            assert first == second

            # A crash between the IN_PROGRESS stage and the commit replays to the same result: the
            # machine re-runs the not-yet-committed phase, then the COMMITTED checkpoint
            # short-circuits any further re-entry without re-running the handler.
            machine = await _machine(conn, scope)
            store = DbProjectRunStore(conn_factory=lambda: _same_connection(conn))
            await store.put_checkpoint(
                project_run_id=scope.project_run_id,
                phase=ProjectPhase.DEEP,
                idempotency_key=phase_key(scope.project_run_id, ProjectPhase.DEEP),
                status=PhaseCheckpointStatus.IN_PROGRESS,
                payload={},
            )
            run = await machine.advance(scope.project_run_id)
            assert run.phase is ProjectPhase.VERIFICATION
            committed = await machine.await_checkpoint(
                scope.project_run_id, phase=ProjectPhase.DEEP
            )
            assert committed is not None
            assert committed.payload["finalization_outcome_counts"] == {
                ResearchFinalizationOutcome.COMPLETED.value: len(envelope.jobs)
            }

    run_async(scenario())


# --- composition (AC8's composition half) -------------------------------------------------------


def test_the_deep_adapter_composes_with_verification_disabled_and_needs_no_gateway() -> None:
    """R11 §1a: nothing in the bridge constructs a judge or gateway, so the adapter is identical
    under ``CLUE_VERIFICATION_ENABLED`` true and false."""

    handler = EntityResearchDeepPhaseHandler()
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is ProjectPhase.DEEP
    assert timedelta(seconds=60) == DEEP_FLEET_POLL_INTERVAL
