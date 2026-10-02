"""M8D R11 (Lane F) — the DEEP-phase bridge, composed end to end in both toggle states.

F1–F4 each pinned their own slice against the substrate. This suite is the thing only a final
slice can assert: **one composed project run**, driven by the production
:class:`~clue_api.run_composition.ComposingRunDriver` (the per-run registry the fleet worker
drives), crossing the whole bridge —

    DEEP hold → confirmed launch → external wait → fleet suspension → fleet terminal →
    VERIFICATION → REVIEW → HANDOFF's doorstep

— against a live Postgres, with the M8D fleet as the *only* research record: no
``account_deep_launch`` row is ever written, and the committee lives solely in
``entity_research_account_coverage``.

Every scenario is parameterized over ``CLUE_VERIFICATION_ENABLED`` **true and false** (spec §1a /
AC8). The two modes share one composition path and one set of assertions; the only difference is
the judge: in enabled mode the gateway answers a real :class:`FaithfulnessJudgeImpl` call, and in
disabled mode the gateway is **never reached** (asserted two ways — the double raises *and* its
recorded call list is asserted empty, because the verification handler isolates per-account faults
and would otherwise swallow the raise into ``accounts_failed``).

Frozen acceptance matrix coverage (spec §5): AC1 (terminal count + no ``account_deep_launch``),
AC2 (durable hold + the §6b re-entrant-hold amendment), AC3 (suspension → PAUSED + diagnosis →
resume), AC4 (the R11.3 selection at the composed level), AC5 (no contact-research launch anywhere
in the bridge path), AC7 (crash/replay at both the wait and the finalize boundary), AC8 (both
toggle states), AC9 (the governed committee off M8D coverage, at the composed reader). AC6 is the
untouched R1 quarantine suite, re-run as a gate rather than re-implemented here.

Fixtures are F1's (fleet launch/finalize/scoping) and F4's (coverage + committee claims) — this
suite invents no fleet vocabulary of its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import AccountResearchFleetState
from clue_api.contact_eligibility import (
    AccountRunReferenceIndexSource,
    ChainedClaimReferenceSource,
    ContactEligibilityResolver,
    EntityResearchCoverageReferenceSource,
    build_contact_eligibility_resolver,
    build_production_handoff_committee_reader,
)
from clue_api.entity_research_deep_phase import (
    REASON_FLEET_NOT_LAUNCHED,
    REASON_FLEET_SUSPENDED,
    REASON_FLEET_TERMINAL,
)
from clue_api.entity_research_verification_resolver import (
    EntityResearchRunMissing,
    build_entity_research_account_resolver,
)
from clue_api.external_research_wake import (
    ExternalResearchWakeSource,
    registered_external_research_wake_sources,
)
from clue_api.fleet_main import _start_external_research_wake
from clue_api.run_composition import ComposedRun, ComposingRunDriver
from clue_config import Settings, load_settings
from clue_core import (
    Claim,
    Completion,
    DeepFleetExternalWait,
    EntityId,
    ExtractionMethod,
    ICPCreatedFrom,
    ICPSpec,
    Message,
    Persona,
    PhaseContext,
    PhaseResult,
    ProjectPhase,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
    new_run_id,
    phase_key,
)
from clue_core.entity_research import ResearchFinalizationOutcome
from clue_fleet import EntityResearchRunEnvelope
from clue_research.claimstore import insert_claim
from clue_research.durable import (
    REENTRANT_HOLD_KEY,
    BudgetEngine,
    DbBudgetStore,
    DbIdempotencyStore,
    DbProjectRunStore,
    NoPhaseHandlerRegistered,
    PhaseCheckpointStatus,
    ProjectRunStatus,
    ReentrantHoldNotSubmittable,
    get_idempotency_ledger,
)
from clue_research.identity import insert_account_entity, stamp_reuse
from clue_research.profiling.committee import PERSONA, load_committee_pack
from tests.api.test_r11_committee_bridge import (
    _account_runs,
    _contact,
    _coverage,
    _launch_for,
    _member_claims,
    _scope,
)
from tests.api.test_r11_deep_phase_bridge import (
    _account_deep_launches,
    _context,
    _finalize_all,
    _same_connection,
    _Scope,
    _service,
    _settle_spend,
)
from tests.api.test_storage_wiring import FakeStorage
from tests.profiling.conftest import rollback_conn, seed_packs

from .conftest import run_async

pytestmark = pytest.mark.usefixtures("require_integration_db")

#: The tier-4 account field the composed VERIFICATION phase actually judges. It is in the M8
#: deep-profiling pack (``rollback_conn`` seeds it), carries an evidence span, and is a direct
#: (non-derived) synthesis claim — the three properties that make the M9.3 judge run over it, which
#: is what gives the toggle something to switch off.
_JUDGED_FIELD = "account.operational_pain"

#: The two committee personas the coverage row seats. Two, not one, so "the committee resolved"
#: cannot be satisfied by an accidental single row.
_PERSONAS = (Persona.ECONOMIC_BUYER, Persona.TECHNICAL_EVALUATOR)


# --- doubles -------------------------------------------------------------------------------------


class _LaneFGateway:
    """The one LLM seam in the composed run: the M9.3 faithfulness judge.

    Records every call so the toggle assertion is positive in *both* directions — enabled mode
    proves the judge ran, disabled mode proves nothing reached the gateway. ``refuse`` additionally
    raises on any call (disabled mode), but the recorded list is the load-bearing assertion: the
    verification handler isolates per-account faults, so a raise alone would be swallowed into
    ``accounts_failed`` rather than failing the test.
    """

    def __init__(self, *, refuse: bool = False) -> None:
        self.calls: list[str] = []
        self._refuse = refuse

    def complete(self, *, model: str, messages: Sequence[Message], **opts: object) -> Completion:
        self.calls.append(model)
        if self._refuse:
            raise AssertionError(
                "the gateway was reached with CLUE_VERIFICATION_ENABLED=false — the disabled "
                "toggle must incur zero judge spend (spec §1a)"
            )
        return Completion(
            model=model,
            text='{"verdict": "supported", "score": 0.95, "rationale": "scripted"}',
            cost_cents=Decimal("0.2"),
            finish_reason="stop",
        )

    def embed(self, *, model: str, inputs: Sequence[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError("the bridge never embeds")


class _ExplodingDeepHandler:
    """A DEEP handler that must never run — swapped into the composed registry to prove a replayed
    finalize transitions off the durable ``COMMITTED`` checkpoint instead of re-entering the
    handler (AC7's second half)."""

    phase: ProjectPhase = ProjectPhase.DEEP

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        raise AssertionError(
            "the DEEP handler re-ran on a phase that had already committed — the replay must "
            "transition off the COMMITTED checkpoint, not re-evaluate the fleet"
        )


# --- the composed world ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _World:
    """One seeded project run whose research record is M8D-shaped and nothing else."""

    scope: _Scope
    accounts: tuple[EntityId, ...]
    members: tuple[EntityId, ...]
    committee_claims: tuple[Claim, ...]
    judged_claim: Claim
    run_id: RunId


async def _seed(conn: AsyncConnection) -> _World:
    """Two workspace-local accounts, a two-person committee on the first, and one judgeable
    tier-4 account claim — with **no** fleet run yet (the story starts at the AC2 hold)."""

    await seed_packs(conn)
    await load_committee_pack(conn)
    scope = await _scope(conn)
    accounts = tuple(
        [
            await insert_account_entity(
                conn,
                canonical_name=f"R11 Lane F Target {index}",
                primary_domain=f"lane-f-{index}-{scope.project_run_id}.example",
                workspace_id=scope.workspace_id,
            )
            for index in range(2)
        ]
    )
    run_id = new_run_id()
    members: list[EntityId] = []
    committee_claims: list[Claim] = []
    for persona in _PERSONAS:
        contact = await _contact(conn, accounts[0], name=f"{persona.value.title()} Person")
        members.append(contact)
        committee_claims.extend(
            await _member_claims(
                conn,
                contact=contact,
                workspace_id=scope.workspace_id,
                product_id=scope.product_id,
                run_id=run_id,
                persona=persona,
                # No hand-written use decision: the composed VERIFICATION phase's real M10.3 use
                # gate writes it, so the committee read below is governed by production machinery
                # rather than by a fixture row.
                facet_allowed=None,
            )
        )
    judged = stamp_reuse(
        account_claim(
            entity_id=accounts[0],
            field_key=_JUDGED_FIELD,
            value_json="peak-season picking cannot keep up with order volume",
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            confidence=0.8,
            run_id=run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://lane-f.example/press",
            evidence_span="peak-season picking cannot keep up with order volume",
        ),
        workspace_id=scope.workspace_id,
    )
    await insert_claim(conn, judged)
    return _World(
        scope=scope,
        accounts=accounts,
        members=tuple(members),
        committee_claims=tuple(committee_claims),
        judged_claim=judged,
        run_id=run_id,
    )


def _settings(*, verification_enabled: bool) -> Settings:
    """Production settings with the two knobs this suite is about: the M9 runtime toggle, and the
    default-off C7 handoff cutover (so HANDOFF stays fail-closed — spec §2 non-goal 3)."""

    return load_settings(
        _env_file=None,
        verification_enabled=verification_enabled,
        c7_production_handoff_enabled=False,
        gateway_allow_stub=True,
    )


def _spec(world: _World) -> ICPSpec:
    return ICPSpec(
        workspace_id=world.scope.workspace_id,
        icp_key="default",
        created_from=ICPCreatedFrom.SYNTHESIS,
        version=1,
        field_keys=(_JUDGED_FIELD,),
    )


def _driver(
    conn: AsyncConnection, world: _World, *, gateway: _LaneFGateway, verification_enabled: bool
) -> ComposingRunDriver:
    """The real ``ComposingRunDriver``, with every durable collaborator bound to the test's
    rolled-back connection. Only the ICP spec loader and the LLM gateway are doubles — the phase
    handlers, the ledger, the budget engine and the state machine are production objects."""

    factory = lambda: _same_connection(conn)  # noqa: E731 - a one-line ConnFactory

    async def spec_loader(workspace_id: str, icp_key: str, icp_version: int) -> ICPSpec | None:
        return _spec(world)

    return ComposingRunDriver(
        settings=_settings(verification_enabled=verification_enabled),
        store=DbProjectRunStore(conn_factory=factory),
        ledger=DbIdempotencyStore(conn_factory=factory),
        budget_engine=BudgetEngine(store=DbBudgetStore(conn_factory=factory)),
        gateway=gateway,  # type: ignore[arg-type]
        storage=FakeStorage(),  # type: ignore[arg-type]
        spec_loader=spec_loader,
        session_factory=factory,
    )


def _deep_source() -> ExternalResearchWakeSource:
    """The R11.2 source exactly as production compiles it with every provider flag off."""

    sources = registered_external_research_wake_sources(
        committee_enabled=False,
        contact_external_enabled=False,
        contact_channel_enabled=False,
    )
    assert len(sources) == 1
    return sources[0]


async def _due(conn: AsyncConnection) -> Sequence[ProjectRunId]:
    return await _deep_source()(conn, datetime.now(UTC), 100)


async def _park_at_deep(conn: AsyncConnection, world: _World) -> None:
    """Put the run at DEEP the way the approved TIER_CHECKPOINT leaves it.

    The pre-DEEP phases are not this lane's subject (``tests/fleet/test_b4_composed_run_db.py``
    drives them through the same composer); starting at DEEP keeps the story about the bridge.
    """

    await DbProjectRunStore(conn_factory=lambda: _same_connection(conn)).transition(
        world.scope.project_run_id, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE
    )


async def _contact_research_jobs(conn: AsyncConnection, world: _World) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM entity_research_job "
                    "WHERE project_run_id=:run_id AND subject_type='contact'"
                ),
                {"run_id": UUID(str(world.scope.project_run_id))},
            )
        ).scalar_one()
    )


async def _contact_research_runs(conn: AsyncConnection, world: _World) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM entity_research_run "
                    "WHERE project_run_id=:run_id AND run_kind='contact_research'"
                ),
                {"run_id": UUID(str(world.scope.project_run_id))},
            )
        ).scalar_one()
    )


async def _contact_launches(conn: AsyncConnection) -> int:
    return int(
        (
            await conn.execute(text("SELECT count(*) FROM entity_research_contact_launch"))
        ).scalar_one()
    )


async def _faithfulness_verdicts(conn: AsyncConnection, claim: Claim) -> int:
    return int(
        (
            await conn.execute(
                text("SELECT count(*) FROM faithfulness_verdict WHERE claim_id=:claim_id"),
                {"claim_id": str(claim.id)},
            )
        ).scalar_one()
    )


async def _use_decisions_for(conn: AsyncConnection, claims: Sequence[Claim]) -> int:
    facets = [
        str(claim.id) for claim in claims if str(claim.field_key).startswith("contact.facet.")
    ]
    assert facets, "the committee fixture must carry a personal hook for the use gate to govern"
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(DISTINCT claim_id) FROM use_decision WHERE claim_id = ANY(:ids)"
                ),
                {"ids": facets},
            )
        ).scalar_one()
    )


# --- the composed story ---------------------------------------------------------------------------


@pytest.mark.parametrize("verification_enabled", [True, False])
def test_the_bridge_carries_a_composed_run_from_deep_to_handoffs_doorstep(
    verification_enabled: bool,
) -> None:
    """The whole Lane F bridge, once, over the real composition — identically in both toggle
    states (AC1/AC2/AC3/AC4/AC5/AC7/AC8/AC9)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            world = await _seed(conn)
            run_id = world.scope.project_run_id
            gateway = _LaneFGateway(refuse=not verification_enabled)
            driver = _driver(
                conn, world, gateway=gateway, verification_enabled=verification_enabled
            )
            await _park_at_deep(conn, world)

            # 1 — a composed run at DEEP with no fleet run holds durably, and the hold is not an
            # approvable gate card (AC2 + the §6b re-entrant-hold amendment).
            run = await driver.advance(run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.PAUSED)
            composed: ComposedRun = await driver.composed(run)
            held = await composed.run.await_checkpoint(run_id)
            assert held is not None
            assert held.status is PhaseCheckpointStatus.AWAITING_INPUT
            assert held.payload["reason_code"] == REASON_FLEET_NOT_LAUNCHED
            assert held.payload[REENTRANT_HOLD_KEY] is True
            with pytest.raises(ReentrantHoldNotSubmittable):
                await composed.run.submit_checkpoint(run_id, decision={"action": "approve"})
            after = await driver.status(run_id)
            assert (after.phase, after.status) == (ProjectPhase.DEEP, ProjectRunStatus.PAUSED)
            assert await composed.run.await_checkpoint(run_id) == held

            # 2 — the operator launches through the confirmed tool and resumes: DEEP waits on the
            # fleet, and the R11.2 wake source leaves a working run alone.
            envelope = await _launch_for(conn, world.scope, world.accounts)
            await composed.run.resume(run_id)
            run = await driver.advance(run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)
            waiting = await composed.run.await_checkpoint(run_id)
            assert waiting is not None
            assert waiting.status is PhaseCheckpointStatus.WAITING_EXTERNAL
            wait = DeepFleetExternalWait.model_validate(waiting.payload)
            assert wait.research_run_id == envelope.lifecycle.run_id
            assert datetime.now(UTC) < wait.next_poll_at
            assert run_id not in await _due(conn)

            # AC7 (first half) — re-entering a parked wait is idempotent: the same payload, the
            # same checkpoint, no transition.
            for _ in range(2):
                again = await driver.advance(run_id)
                assert (again.phase, again.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)
            re_entered = await composed.run.await_checkpoint(run_id)
            assert re_entered is not None
            assert re_entered.status is PhaseCheckpointStatus.WAITING_EXTERNAL
            assert (
                DeepFleetExternalWait.model_validate(re_entered.payload).research_run_id
                == wait.research_run_id
            )

            # 3 — a fleet suspension is a human decision point: the wake source offers the run, the
            # phase pauses carrying the diagnosis, and never fails (AC3).
            suspended_job = envelope.jobs[0].authorization.job_id
            projection = await _service(conn).pause_job(
                suspended_job,
                workspace_id=world.scope.workspace_id,
                actor="user:owner",
                reason_code="operator_hold",
            )
            assert projection.fleet_state is AccountResearchFleetState.SUSPENDED
            assert run_id in await _due(conn)
            run = await driver.advance(run_id)
            assert run.status is ProjectRunStatus.PAUSED
            assert run.status is not ProjectRunStatus.FAILED
            paused = await composed.run.await_checkpoint(run_id)
            assert paused is not None
            assert paused.payload["reason_code"] == REASON_FLEET_SUSPENDED
            assert paused.payload["diagnosis"] == {
                "reason_code": "account_jobs_suspended",
                "job_ids": [str(suspended_job)],
            }
            await _service(conn).resume_job(
                suspended_job, workspace_id=world.scope.workspace_id, actor="user:owner"
            )
            await composed.run.resume(run_id)
            run = await driver.advance(run_id)
            assert (run.phase, run.status) == (ProjectPhase.DEEP, ProjectRunStatus.ACTIVE)

            # 4 — the fleet goes terminal (completed + needs_review): the wake source offers the
            # run, DEEP commits the fleet's counts and settled spend, and the run leaves for
            # VERIFICATION with no ``account_deep_launch`` row anywhere (AC1).
            await _finalize_all(
                conn,
                envelope,
                outcomes=(
                    ResearchFinalizationOutcome.COMPLETED,
                    ResearchFinalizationOutcome.NEEDS_REVIEW,
                ),
            )
            await _coverage(
                conn,
                envelope,
                account_entity_id=world.accounts[0],
                workspace_id=world.scope.workspace_id,
                claims=world.committee_claims,
                members=world.members,
            )
            spent = await _settle_spend(conn, envelope, "6.50")
            assert run_id in await _due(conn)
            run = await driver.advance(run_id)
            assert (run.phase, run.status) == (ProjectPhase.VERIFICATION, ProjectRunStatus.ACTIVE)
            deep_checkpoint = await composed.run.await_checkpoint(run_id, phase=ProjectPhase.DEEP)
            assert deep_checkpoint is not None
            assert deep_checkpoint.status is PhaseCheckpointStatus.COMMITTED
            assert deep_checkpoint.payload["reason_code"] == REASON_FLEET_TERMINAL
            assert deep_checkpoint.payload["finalization_outcome_counts"] == {
                ResearchFinalizationOutcome.COMPLETED.value: 1,
                ResearchFinalizationOutcome.NEEDS_REVIEW.value: 1,
            }
            ledger = await get_idempotency_ledger(conn, phase_key(run_id, ProjectPhase.DEEP))
            assert ledger is not None
            # The fleet's settled spend is reported into the M7.4 phase charge, never re-gated
            # (§6d): budget enforcement happened once, at fleet admission.
            assert ledger.cost_cents_charged == spent
            assert await _account_deep_launches(conn) == 0
            # The whole committee record is the fleet's: zero legacy account runs exist.
            assert await _account_runs(conn) == 0
            # ``accounts_processed`` is not a durable column, so read it off the composed handler
            # itself — a pure fleet read, safe to repeat (AC1's count, at the composed handler the
            # machine just drove).
            settled = await composed.deep.run(_context(world.scope))
            assert settled.accounts_processed == len(envelope.jobs)
            assert settled.cost_cents == spent

            # AC7 (second half) — a crash between the DEEP commit and the transition replays off
            # the COMMITTED checkpoint without re-running the handler.
            composed.registry.register(_ExplodingDeepHandler())
            await DbProjectRunStore(conn_factory=lambda: _same_connection(conn)).transition(
                run_id, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE
            )
            replayed = await driver.advance(run_id)
            assert replayed.phase is ProjectPhase.VERIFICATION
            composed.registry.register(composed.deep)

            # 5 — VERIFICATION runs over exactly the R11.3 selection (both accepted accounts) and
            # records the honest toggle state; the judge is reached only when it is enabled (AC4 +
            # AC8).
            run = await driver.advance(run_id)
            verification = await composed.run.await_checkpoint(
                run_id, phase=ProjectPhase.VERIFICATION
            )
            assert verification is not None
            assert verification.status is PhaseCheckpointStatus.COMMITTED
            assert verification.payload["verification_enabled"] is verification_enabled
            assert verification.payload["accounts_failed"] == 0
            if verification_enabled:
                assert verification.payload["verified_accounts"] == len(world.accounts)
                assert verification.payload["accounts_skipped"] == 0
                assert gateway.calls, "the enabled judge never reached the gateway"
                # Not just a call: the M9.3 judge recorded its durable verdict for the one
                # judgeable tier-4 claim on the researched account.
                assert await _faithfulness_verdicts(conn, world.judged_claim) == 1
            else:
                assert verification.payload["verified_accounts"] == 0
                assert verification.payload["accounts_skipped"] == len(world.accounts)
                assert gateway.calls == []
                assert await _faithfulness_verdicts(conn, world.judged_claim) == 0
            # The M10 use gate stays on in both modes (spec §1a: structural protections never
            # follow the toggle), so every personal hook now carries a real decision.
            assert await _use_decisions_for(conn, world.committee_claims) == len(
                [c for c in world.committee_claims if str(c.field_key).startswith("contact.facet.")]
            )

            # 6 — REVIEW opens no session on an M8D-shaped run: its readiness set is the legacy
            # ``DurableHandoffReadinessReader`` one (``account_run`` DONE + CONTACTS_COMPLETE),
            # which the R1 quarantine left with no writer — so the phase is a clean COMPLETED
            # no-op and the run reaches HANDOFF's doorstep, where the default-off C7 cutover
            # leaves no handler and dispatch refuses loudly, exactly as before R11 (spec §2
            # non-goal 3: HANDOFF becomes *reachable*; the cutover is unchanged). REVIEW is the one
            # composed handler ``register_boot_handlers`` builds with the process-default
            # connection rather than the driver's factory, so here it reads committed state — the
            # readiness set is empty either way, which is why the assertion holds honestly.
            assert run.phase is ProjectPhase.REVIEW
            run = await driver.advance(run_id)
            assert (run.phase, run.status) == (ProjectPhase.HANDOFF, ProjectRunStatus.ACTIVE)
            assert ProjectPhase.HANDOFF not in composed.phases
            with pytest.raises(NoPhaseHandlerRegistered):
                await driver.advance(run_id)
            assert (await driver.status(run_id)).phase is ProjectPhase.HANDOFF

            # 7 — the governed committee at HANDOFF's doorstep resolves out of the fleet's coverage
            # row (AC9 at the composed level). The reader is built exactly as
            # ``ComposingRunDriver._compose`` builds it once the cutover is enabled; the product id
            # comes from the fleet run because a run without Stage-0 pins carries none of its own
            # (the FI-2/C7-owned product-pin gap, ratified out of Lane F by §6f).
            reader = build_production_handoff_committee_reader(
                build_contact_eligibility_resolver(
                    project_run_id=run_id,
                    product_id=world.scope.product_id,
                    conn_factory=lambda: _same_connection(conn),
                )
            )
            committee = await reader.committee_for(
                account_entity_id=world.accounts[0], workspace_id=world.scope.workspace_id
            )
            assert {member.contact_entity_id for member in committee} == set(world.members)
            assert [member.persona for member in committee] == list(_PERSONAS)
            # The account the fleet researched but seated no committee on stays honestly empty.
            assert (
                await reader.committee_for(
                    account_entity_id=world.accounts[1], workspace_id=world.scope.workspace_id
                )
                == ()
            )

            # 8 — AC5: nothing on the bridge path launched contact research. Contact research stays
            # separately authorized (``approve_contact_research_selection@2`` →
            # ``launch_contact_research@1``), which no part of this flow called.
            assert await _contact_research_jobs(conn, world) == 0
            assert await _contact_research_runs(conn, world) == 0
            assert await _contact_launches(conn) == 0

    run_async(scenario())


@pytest.mark.parametrize("verification_enabled", [True, False])
def test_the_r11_3_selector_refuses_a_composed_run_with_no_fleet_run(
    verification_enabled: bool,
) -> None:
    """AC4/AC8 at the composed level: the toggle bypasses *judging*, never the selector's honesty.

    A run whose DEEP hold was cleared some other way (an operator forcing the phase forward, a
    relaunch that never happened) must not verify zero accounts and call it success — the pre-R11
    silent-zero. The composed VERIFICATION handler inherits the typed refusal in both modes.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            world = await _seed(conn)
            run_id = world.scope.project_run_id
            gateway = _LaneFGateway(refuse=not verification_enabled)
            driver = _driver(
                conn, world, gateway=gateway, verification_enabled=verification_enabled
            )
            await DbProjectRunStore(conn_factory=lambda: _same_connection(conn)).transition(
                run_id, phase=ProjectPhase.VERIFICATION, status=ProjectRunStatus.ACTIVE
            )
            with pytest.raises(EntityResearchRunMissing) as excinfo:
                await driver.advance(run_id)
            assert str(run_id) in str(excinfo.value)
            assert "launch_account_research@1" in str(excinfo.value)
            assert gateway.calls == []
            # Nothing committed: the run is still at VERIFICATION with no COMMITTED checkpoint.
            row = await driver.status(run_id)
            assert row.phase is ProjectPhase.VERIFICATION
            composed = await driver.composed(row)
            checkpoint = await composed.run.await_checkpoint(
                run_id, phase=ProjectPhase.VERIFICATION
            )
            assert checkpoint is None or checkpoint.status is not PhaseCheckpointStatus.COMMITTED

    run_async(scenario())


@pytest.mark.parametrize("verification_enabled", [True, False])
def test_the_deployment_composes_and_wakes_with_every_provider_flag_off(
    verification_enabled: bool,
) -> None:
    """The deployment shape Lane F ships into: no provider flag set, the C7 cutover off, and the
    verification toggle in either state.

    Composition must succeed (nothing in the bridge constructs a judge/gateway dependency that
    fails with the toggle off — spec §1a), the composed registry must hold the R11.1 DEEP bridge
    and no HANDOFF handler, and ``fleet_main`` must still start the wake loop — otherwise a run
    parked on a DEEP wait would have nothing to re-enter it (the F2 change).
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            world = await _seed(conn)
            gateway = _LaneFGateway(refuse=True)
            driver = _driver(
                conn, world, gateway=gateway, verification_enabled=verification_enabled
            )
            row = await driver.status(world.scope.project_run_id)
            composed = await driver.composed(row)
            assert ProjectPhase.DEEP in composed.phases
            assert ProjectPhase.VERIFICATION in composed.phases
            assert ProjectPhase.HANDOFF not in composed.phases
            assert composed.deep.phase is ProjectPhase.DEEP
            assert gateway.calls == []

            # The R11.3 selector and the R11.5 committee source are constructible with no gateway
            # in scope at all — the disabled-mode composition constraint, asserted directly.
            assert build_entity_research_account_resolver() is not None

            settings = _settings(verification_enabled=verification_enabled)
            assert not settings.sumble_committee_acquisition_enabled
            assert not settings.exa_contact_deep_acquisition_enabled
            assert not settings.contact_channel_enrichment_enabled
            task = _start_external_research_wake(settings)
            assert isinstance(task, asyncio.Task)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    run_async(scenario())


def test_the_committee_personas_the_bridge_serves_come_from_the_coverage_row() -> None:
    """A guard on the fixture itself: the committee this suite proves is seated by
    ``entity_research_account_coverage``, not by a stray persona claim the reader could have found
    without the bridge. (Deleting the coverage row must empty the committee.)

    2026-09-09 (ARV2 R3 Task 7) — the guard now reads through the **legacy chain explicitly**.
    Finding a committee from a live ``contact.persona`` claim is no longer the accident this test
    was written to catch: it is what ``Arv2CommitteeReferenceSource`` deliberately does, and it now
    leads the default chain. Asserting the coverage bridge therefore means naming the sources this
    assertion is about; the default chain's own order is proven in
    ``tests/api/test_r11_committee_bridge.py``.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            world = await _seed(conn)
            envelope: EntityResearchRunEnvelope = await _launch_for(
                conn, world.scope, world.accounts
            )
            resolver = ContactEligibilityResolver(
                project_run_id=world.scope.project_run_id,
                product_id=world.scope.product_id,
                conn_factory=lambda: _same_connection(conn),
                claim_reference_source=ChainedClaimReferenceSource(
                    (EntityResearchCoverageReferenceSource(), AccountRunReferenceIndexSource())
                ),
            )
            # Before any coverage row exists the fleet run has published nothing, so the read is
            # the honest empty committee (and, with zero account runs, cannot come from the legacy
            # references index either).
            assert await _account_runs(conn) == 0
            assert (
                await resolver.resolve_account(
                    account_entity_id=world.accounts[0], workspace_id=world.scope.workspace_id
                )
                == ()
            )
            await _coverage(
                conn,
                envelope,
                account_entity_id=world.accounts[0],
                workspace_id=world.scope.workspace_id,
                claims=world.committee_claims,
                members=world.members,
            )
            governed = await resolver.resolve_account(
                account_entity_id=world.accounts[0], workspace_id=world.scope.workspace_id
            )
            assert [member.contact_entity_id for member in governed] == list(world.members)
            assert {str(item.claim.field_key) for member in governed for item in member.claims} >= {
                PERSONA
            }

    run_async(scenario())
