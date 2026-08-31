"""M8D R11.3 — the fail-loud verification account selector over the M8D account-research fleet.

The headline here is the **silent-zero regression**: before R11.3 both verification consumers
resolved their account set from ``account_deep_launch``, a ledger only the R1-quarantined legacy
path ever wrote, so an M8D-researched project run verified nothing and reported
``accounts_processed=0`` as a clean COMPLETED. These tests pin the replacement — a missing fleet run
is a typed :class:`~clue_api.entity_research_verification_resolver.EntityResearchRunMissing` in both
``CLUE_VERIFICATION_ENABLED`` states (R11 §1a), the accepted terminal jobs of the **latest**
human-confirmed fleet run (§6c) are the account set, and the refused outcomes are censused rather
than silently folded in.

The fleet/job fixtures are F1's (``tests.api.test_r11_deep_phase_bridge``) — one launch helper, one
finalization helper — so the two slices exercise the same shape of run.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.entity_research_verification_resolver import (
    ENTITY_RESEARCH_SELECTION_TIER,
    METRIC_SELECTOR_EXCLUDED,
    METRIC_SELECTOR_SELECTED,
    EntityResearchRunMissing,
    build_entity_research_account_resolver,
)
from clue_api.handoff_retention import build_retention_sweeping_handoff_handler
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.verification import build_verification_phase_handler
from clue_config import Settings, load_settings
from clue_core import (
    ICPCreatedFrom,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    new_operation_id,
)
from clue_core.entity_research import ResearchFinalizationOutcome
from clue_core.gateway import Completion, Message
from clue_fleet import EntityResearchRunEnvelope
from clue_obs.otel.metrics import InMemorySink
from clue_research.durable import (
    AccountSpec,
    DbProjectRunStore,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunStatus,
)
from clue_research.icp import (
    ScoringRubric,
    TierBand,
    TierCutoffs,
    create_icp_spec,
    rubric_to_slot,
)
from clue_toolbelt import PreconditionFailed, ToolContext, invoke_tool
from tests.api.test_r11_deep_phase_bridge import (
    _age,
    _context,
    _finalize_all,
    _handler,
    _launch,
    _same_connection,
    _Scope,
    _seed_scope,
)
from tests.fleet.conftest import rollback_conn, run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_profiling_db")

TTL = 86400.0


class _NeverCalledGateway:
    """An ``LLMGateway`` the enabled-verification composition requires but no fixture reaches (the
    resolved accounts carry no claims, so neither corroboration nor the judge has work)."""

    def complete(self, *, model: str, messages: Sequence[Message], **opts: object) -> Completion:
        raise NotImplementedError

    def embed(self, *, model: str, inputs: Sequence[str]) -> object:
        raise NotImplementedError


def _resolver(conn: AsyncConnection, *, sink: InMemorySink | None = None):
    return build_entity_research_account_resolver(
        session_factory=lambda: _same_connection(conn), sink=sink
    )


def _verification(conn: AsyncConnection, *, enabled: bool) -> PhaseHandler:
    """The composed VERIFICATION handler over the R11.3 selector, in either toggle state.

    ``govern_contacts=False`` keeps the fixture account-only: the M10 use gate is a separate seam
    with its own suite, and including it here would only test workspace-policy loading.
    """

    return build_verification_phase_handler(
        gateway=_NeverCalledGateway() if enabled else None,
        account_resolver=_resolver(conn),
        session_factory=lambda: _same_connection(conn),
        verification_enabled=enabled,
        govern_contacts=False,
    )


async def _machine(conn: AsyncConnection, scope: _Scope, *, enabled: bool) -> ProjectRun:
    """A state machine parked at DEEP with the R11.1 adapter and the R11.3-fed VERIFICATION."""

    store = DbProjectRunStore(conn_factory=lambda: _same_connection(conn))
    await store.transition(
        scope.project_run_id, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE
    )
    registry = PhaseHandlerRegistry()
    registry.register(_handler(conn))
    registry.register(_verification(conn, enabled=enabled))
    return ProjectRun(store=store, registry=registry)


async def _terminal_fleet(
    conn: AsyncConnection,
    scope: _Scope,
    *,
    outcomes: tuple[ResearchFinalizationOutcome, ...],
) -> EntityResearchRunEnvelope:
    """Launch a fleet run of ``len(outcomes)`` accounts and finalize each with its outcome."""

    envelope = await _launch(conn, scope, accounts=len(outcomes))
    await _finalize_all(conn, envelope, outcomes=outcomes)
    return envelope


def _entity_ids(envelope: EntityResearchRunEnvelope, *indexes: int) -> set[UUID]:
    return {envelope.jobs[index].authorization.subject_entity_id for index in indexes}


# --- the headline: a missing fleet run is never an empty success -------------------------------


@pytest.mark.parametrize("verification_enabled", [True, False])
def test_a_run_with_no_fleet_run_fails_loud_instead_of_verifying_zero_accounts(
    verification_enabled: bool,
) -> None:
    """AC4/AC8: the silent-zero regression, in both toggle states.

    The superseded ``build_high_tier_resolver`` answered from ``account_deep_launch`` — unwritten
    since the R1 quarantine — so it returned ``()`` and the phase below reported a zero-account
    COMPLETED as a success. The first assertion pins that shape (an empty resolver *is* a clean
    success, which is exactly why the selector may not return one), and the rest prove the R11.3
    selector raises instead, identically with the judge on and off.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            ctx = _context(scope)

            async def empty_resolver(_: PhaseContext) -> Sequence[AccountSpec]:
                return ()

            silent = build_verification_phase_handler(
                gateway=_NeverCalledGateway() if verification_enabled else None,
                account_resolver=empty_resolver,
                session_factory=lambda: _same_connection(conn),
                verification_enabled=verification_enabled,
                govern_contacts=False,
            )
            defect: PhaseResult = await silent.run(ctx)
            assert defect.status is PhaseStatus.COMPLETED
            assert defect.accounts_processed == 0

            with pytest.raises(EntityResearchRunMissing) as excinfo:
                await _resolver(conn)(ctx)
            assert str(scope.project_run_id) in str(excinfo.value)
            assert "launch_account_research@1" in str(excinfo.value)

            # The composed phase inherits the refusal rather than converting it into a zero.
            with pytest.raises(EntityResearchRunMissing):
                await _verification(conn, enabled=verification_enabled).run(ctx)

    run_async(scenario())


def test_a_fleet_run_owned_by_another_project_is_as_missing_as_none() -> None:
    """Fail closed: a fleet row bound to this project run but owned by another project cannot
    stand in for research nobody launched here."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            await _launch(conn, scope, project_id="prj-somewhere-else")

            with pytest.raises(EntityResearchRunMissing):
                await _resolver(conn)(_context(scope))

    run_async(scenario())


# --- the accepted-outcome selection ------------------------------------------------------------


def test_only_accepted_terminal_jobs_become_verification_accounts() -> None:
    """Completed + needs_review accounts are verified; a cancelled one is excluded and censused."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            envelope = await _terminal_fleet(
                conn,
                scope,
                outcomes=(
                    ResearchFinalizationOutcome.COMPLETED,
                    ResearchFinalizationOutcome.COMPLETED,
                    ResearchFinalizationOutcome.NEEDS_REVIEW,
                    ResearchFinalizationOutcome.CANCELLED,
                ),
            )
            sink = InMemorySink()
            specs = await _resolver(conn, sink=sink)(_context(scope))

            assert {spec.entity_id for spec in specs} == _entity_ids(envelope, 0, 1, 2)
            # Deterministic: entity-id order, so both consumers of the shared instance agree.
            assert [str(spec.entity_id) for spec in specs] == sorted(
                str(spec.entity_id) for spec in specs
            )

            by_entity = {str(spec.entity_id): spec for spec in specs}
            for job in envelope.jobs[:3]:
                spec = by_entity[str(job.authorization.subject_entity_id)]
                assert spec.workspace_id == scope.workspace_id
                assert spec.tier == ENTITY_RESEARCH_SELECTION_TIER
                assert spec.field_keys == job.authorization.effective_admitted_field_keys
                assert spec.budget_cap_cents == Decimal("3.00")
                # An account job authorizes no contact axis — contact research is separately
                # confirmed, so the model's permissive default would be a false authorization.
                assert spec.contact_profiling_allowed is False
                # M8D pins its directive by ref+sha on the selection, never as the legacy pin.
                assert spec.research_directive is None

            selected = {
                key[1]: value
                for key, value in sink.counters.items()
                if key[0] == METRIC_SELECTOR_SELECTED
            }
            excluded = {
                key[1]: value
                for key, value in sink.counters.items()
                if key[0] == METRIC_SELECTOR_EXCLUDED
            }
            assert sum(selected.values()) == 3
            assert sum(excluded.values()) == 1
            assert any("cancelled" in dict(attributes).values() for attributes in excluded)

    run_async(scenario())


def test_a_fleet_that_accepted_nothing_yields_an_honest_empty_set() -> None:
    """An empty set is still a legitimate *answer* once a fleet run exists — the refusal is about a
    missing run, not about a run that researched nothing acceptable."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            await _terminal_fleet(
                conn,
                scope,
                outcomes=(
                    ResearchFinalizationOutcome.CANCELLED,
                    ResearchFinalizationOutcome.FAILED,
                ),
            )
            assert await _resolver(conn)(_context(scope)) == ()

    run_async(scenario())


def test_only_the_latest_fleet_run_selects_the_verification_accounts() -> None:
    """§6c: a relaunch supersedes; the earlier run stays visible history and never selects."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            first = await _terminal_fleet(
                conn, scope, outcomes=(ResearchFinalizationOutcome.COMPLETED,) * 3
            )
            # Postgres freezes ``now()`` inside the test transaction, so age the earlier launch to
            # reproduce two launches made minutes apart in production.
            await _age(conn, first)
            second = await _terminal_fleet(
                conn, scope, outcomes=(ResearchFinalizationOutcome.COMPLETED,) * 2
            )

            specs = await _resolver(conn)(_context(scope))
            assert {spec.entity_id for spec in specs} == _entity_ids(second, 0, 1)
            assert not {spec.entity_id for spec in specs} & _entity_ids(first, 0, 1, 2)

    run_async(scenario())


# --- the composed phase, in both toggle states -------------------------------------------------


@pytest.mark.parametrize("verification_enabled", [True, False])
def test_the_composed_verification_phase_processes_exactly_the_accepted_accounts(
    verification_enabled: bool,
) -> None:
    """AC1/AC8: DEEP completes off the terminal fleet and VERIFICATION runs over the accepted
    accounts — reporting the honest skip, not a fake verification, when the toggle is off."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            await _terminal_fleet(
                conn,
                scope,
                outcomes=(
                    ResearchFinalizationOutcome.COMPLETED,
                    ResearchFinalizationOutcome.NEEDS_REVIEW,
                    ResearchFinalizationOutcome.CANCELLED,
                ),
            )
            machine = await _machine(conn, scope, enabled=verification_enabled)

            run = await machine.advance(scope.project_run_id)
            assert (run.phase, run.status) == (ProjectPhase.VERIFICATION, ProjectRunStatus.ACTIVE)
            run = await machine.advance(scope.project_run_id)
            assert run.phase is ProjectPhase.REVIEW

            checkpoint = await machine.await_checkpoint(
                scope.project_run_id, phase=ProjectPhase.VERIFICATION
            )
            assert checkpoint is not None
            assert checkpoint.status is PhaseCheckpointStatus.COMMITTED
            # Two of the three fleet accounts were accepted; the cancelled one is not verified.
            assert checkpoint.payload["accounts_failed"] == 0
            assert checkpoint.payload["verification_enabled"] is verification_enabled
            if verification_enabled:
                assert checkpoint.payload["verified_accounts"] == 2
                assert checkpoint.payload["accounts_skipped"] == 0
            else:
                assert checkpoint.payload["verified_accounts"] == 0
                assert checkpoint.payload["accounts_skipped"] == 2

    run_async(scenario())


# --- the tool consumer -------------------------------------------------------------------------


async def _seed_tool_run(conn: AsyncConnection, scope: _Scope) -> None:
    """The pinned ICP the ``run_verification@1`` preconditions require before the fleet check."""

    await create_icp_spec(
        conn,
        workspace_id=scope.workspace_id,
        icp_key="default",
        created_from=ICPCreatedFrom.SYNTHESIS,
        scoring_rubric=rubric_to_slot(
            ScoringRubric(
                tier_cutoffs=TierCutoffs(
                    bands=(TierBand(tier="high", min_fit=0.4, min_intent=0.5),)
                )
            )
        ),
        activate=True,
    )


@pytest.mark.parametrize("verification_enabled", [True, False])
def test_run_verification_refuses_a_project_run_with_no_fleet_run(
    verification_enabled: bool,
) -> None:
    """AC4/AC8: the tool fails loud with a typed precondition — never ``accounts_processed=0``."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            scope = await _seed_scope(conn)
            await _seed_tool_run(conn, scope)
            cf = conn_session_factory(conn)
            settings: Settings = load_settings().model_copy(
                update={"verification_enabled": verification_enabled}
            )
            registry = build_toolbelt(
                storage=None,
                settings=settings,
                gateway=_NeverCalledGateway() if verification_enabled else None,
                conn_factory=cf,
            )
            ctx = ToolContext(
                workspace_id=scope.workspace_id,
                actor="human",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )
            body = {"project_run_id": str(scope.project_run_id)}

            with pytest.raises(PreconditionFailed) as excinfo:
                await invoke_tool(registry, "run_verification", body, ctx, idempotency_ttl_s=TTL)
            assert excinfo.value.reason_codes == ("entity_research_run_missing",)

            # Once research exists the same call passes its preconditions and verifies the
            # fleet's accepted accounts (proving the refusal above was absence-driven).
            await _terminal_fleet(
                conn, scope, outcomes=(ResearchFinalizationOutcome.COMPLETED,) * 2
            )
            result = await invoke_tool(
                registry, "run_verification", body, ctx, idempotency_ttl_s=TTL
            )
            assert result.references["accounts_processed"] == 2
            # The references are exactly ``PhaseAccountsOutput``: the tool's long-standing extra
            # ``verification_enabled`` key was a contract violation that only became reachable once
            # this slice gave the tool a non-empty account set (the reviewed agent profiles pin the
            # output schema, so widening it is a governed change).
            assert set(result.references) == {"status", "accounts_processed"}

    run_async(scenario())


# --- the shared HANDOFF consumer ---------------------------------------------------------------


def test_the_handoff_retention_sweep_composes_over_the_same_resolver() -> None:
    """The flag-gated HANDOFF sweep shares the VERIFICATION selector instance (run_composition);
    this pins that the wrapper still composes over it."""

    class _Inner:
        phase = ProjectPhase.HANDOFF

        async def run(self, ctx: PhaseContext) -> PhaseResult:  # pragma: no cover - never driven
            return PhaseResult(status=PhaseStatus.COMPLETED)

    handler = build_retention_sweeping_handoff_handler(
        inner=_Inner(),
        account_resolver=build_entity_research_account_resolver(),
        storage=None,
    )
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is ProjectPhase.HANDOFF
