"""FI pilot budget-controls toggle (`CLUE_BUDGET_CONTROLS_ENABLED`) — both states.

The ruling (`docs/specs/FI-pilot-budget-controls.md`, ratified 2026-08-11): for the pilot, a user is
never shown a cost or budget number, and **nothing on the platform may stop a pre-approved action on
budget grounds** — hard spend control lives at the provider consoles. Spend *recording* stays
complete in both modes.

This suite is the acceptance record for that ruling, one test per criterion:

* **AC1 — flag on is today's behaviour.** The setting defaults to ``True`` and every existing
  budget-refusal suite stays green (they are the real proof; here we pin the default and the
  descriptor identity that makes "byte-identical" checkable).
* **AC2 — over-cap admitted and recorded.** The headline: an R9 atomic tool batch whose reservation
  exceeds the exact job budget is *admitted*, its handlers execute, and its reservation + settlement
  rows land, so the recorded spend honestly exceeds the cap instead of the work being refused.
  Paired against the same batch with the flag on, which still refuses with zero rows.
* **AC3 — an over-cap run advances.** A project run whose recorded spend is past its cap runs to
  completion through every budget-gated phase, with no graceful stop and no ``graceful_stop`` budget
  event.
* **AC4 — presentation off, integrity kept.** The immutable gate row still stores
  ``max_spend_cents``; the gates wire and the rich gate part carry no amount; an answer echoing an
  amount nobody was shown is accepted; a stale directive digest still refuses; and the launcher
  accepts any courier estimate while keeping every structural check.
* **AC5 — no descriptor movement.** The gate tool's input/output schema digests are identical in
  both modes, so ``head-of-abm/v23``'s pins (which record ``output_schema_sha256``) stay valid.

DB-backed tests are rollback-only per ``tests/api`` conventions and reuse the Lane D/M8D harnesses
rather than re-seeding their fixtures, so a drift in those flows fails here too.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_agents.model import ScriptedAgentChatModel
from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
    AccountResearchFleetState,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchError,
    AccountResearchFleetLaunchRequest,
)
from clue_api.agent_gate_tools import (
    AMOUNT_WITHHELD,
    OpenDirectiveConfirmationGateTool,
)
from clue_api.chat.turn_parts import PartKind
from clue_api.chat.turn_stream import TurnStreamEmitter, TurnStreamPolicy
from clue_api.entity_research_parallel import (
    DbEntityResearchToolBatchCoordinator,
    EntityResearchParallelAdmissionError,
    R9EntityResearchJobStore,
)
from clue_api.entity_research_runtime_wiring import DbEntityResearchAgentJournal
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_config import Settings, load_settings
from clue_core import ProjectPhase, ResearchQuestion
from clue_db import db_lifespan, transaction
from clue_research.durable import (
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunStatus,
)
from clue_research.durable.budget import BudgetEngine
from clue_research.durable.enums import BudgetEventKind
from clue_research.durable.project import PHASE_SEQUENCE
from clue_storage import FsStorage
from tests.agents.test_entity_research_runtime_r3 import Finalizer, Guard, Models
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_entity_research_parallel_r9_db import (
    _claim,
    _MemoryCheckpointers,
    _parallel_calls,
    _profile_authorized_envelope,
    _provider_result,
    _r9_definition,
    _release,
    _runtime_context,
)
from tests.db.conftest import _db_available, run_async
from tests.durable.conftest import (
    FakeBudgetStore,
    FakeProjectRunStore,
    RecordingPhaseHandler,
)
from tests.profiling.conftest import rollback_conn

# --- AC1 / AC5: the switch itself ------------------------------------------------------------


def test_budget_controls_default_to_on_so_an_unset_deployment_keeps_todays_behaviour() -> None:
    """AC1. The pilot posture must be opted into; forgetting the env var never disables control."""

    assert load_settings(_env_file=None).budget_controls_enabled is True
    assert Settings.model_fields["budget_controls_enabled"].default is True


def test_the_gate_tool_contract_is_byte_identical_in_both_modes() -> None:
    """AC5. Presentation is suppressed by the *value*, never by the shape.

    ``platform/agents/catalog/profiles/head-of-abm/v23/profile.yaml`` pins this tool's
    ``input_schema_sha256`` **and** ``output_schema_sha256``. A flag that moved either would make a
    deployment's own profile pins depend on an environment variable — the one failure mode worse
    than showing a number.
    """

    on = OpenDirectiveConfirmationGateTool(budget_controls_enabled=True).descriptor
    off = OpenDirectiveConfirmationGateTool(budget_controls_enabled=False).descriptor
    assert on.input_schema_sha256 == off.input_schema_sha256
    assert on.output_schema_sha256 == off.output_schema_sha256
    assert (on.name, on.version, on.effect_class) == (off.name, off.version, off.effect_class)
    assert on.model_description == off.model_description
    # The withheld spelling is not a number: "withheld" and "zero" must stay distinguishable.
    assert AMOUNT_WITHHELD == ""
    assert AMOUNT_WITHHELD != "0"


# --- AC2: over-cap admitted, executed, and recorded -------------------------------------------


_OVER_CAP_RESERVATION = Decimal("2.50")
"""Two of these (one per parallel call) is 5.00 against the fixture's 4.00 exact job cap."""


def _over_cap_batch_runtime(
    context: Any,
    *,
    exa: Any,
    sumble: Any,
    enforce_budget: bool,
) -> tuple[Any, Any]:
    """One scripted two-call parallel wave over a coordinator in the requested enforcement mode."""

    definition = _r9_definition(
        context,
        exa=exa,
        sumble=sumble,
        reservation_cents=_OVER_CAP_RESERVATION,
    )
    journal = DbEntityResearchAgentJournal()
    runtime = EntityResearchAgentRuntime(
        factory=EntityResearchAgentFactory(
            models=Models(
                ScriptedAgentChatModel(
                    responses=(AIMessage(content="", tool_calls=_parallel_calls()),)
                )
            ),
            journal=journal,
            guard=Guard(),
            batches=DbEntityResearchToolBatchCoordinator(enforce_budget=enforce_budget),
        ),
        checkpointers=_MemoryCheckpointers(),
        journal=journal,
        finalizer=Finalizer(),
    )
    return runtime, definition


async def _batch_ledger(*, turn_id: UUID, job_id: UUID, run_id: UUID) -> dict[str, Any]:
    async with transaction() as conn:
        return dict(
            (
                await conn.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM entity_research_tool_batch "
                        " WHERE agent_turn_id=:turn_id) AS batches, "
                        "(SELECT count(*) FROM entity_research_budget_reservation "
                        " WHERE job_id=:job_id) AS reservations, "
                        "(SELECT COALESCE(sum(reserved_cents), 0) "
                        " FROM entity_research_budget_reservation "
                        " WHERE job_id=:job_id) AS reserved_cents, "
                        "(SELECT count(*) FROM entity_research_budget_reservation_release release "
                        " JOIN entity_research_budget_reservation reservation "
                        "   USING (reservation_id) "
                        " WHERE reservation.job_id=:job_id) AS settlements, "
                        "(SELECT COALESCE(sum(release.settled_cost_cents), 0) "
                        " FROM entity_research_budget_reservation_release release "
                        " JOIN entity_research_budget_reservation reservation "
                        "   USING (reservation_id) "
                        " WHERE reservation.job_id=:job_id) AS settled_cents, "
                        "(SELECT count(*) FROM entity_research_job "
                        " WHERE research_run_id=:run_id "
                        "   AND finalization_outcome='budget_stopped') AS budget_stopped"
                    ),
                    {"turn_id": turn_id, "job_id": job_id, "run_id": run_id},
                )
            )
            .mappings()
            .one()
        )


def test_an_over_cap_tool_batch_is_refused_with_controls_on() -> None:
    """AC1/AC2 (the paired half). With controls on the batch is refused and nothing is written."""

    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    async def scenario() -> None:
        envelope, profile_body, profile_sha = _profile_authorized_envelope()
        dispatches = 0

        async def forbidden(_values: dict[str, Any]) -> dict[str, Any]:
            nonlocal dispatches
            dispatches += 1
            raise AssertionError("an enforced refusal must precede handler dispatch")

        async with db_lifespan():
            store = R9EntityResearchJobStore()
            await store.launch(envelope)
            job_id = envelope.jobs[0].authorization.job_id
            fence = await _claim(job_id, worker_id="pilot-budget-on")
            begun = await store.begin(job_id, fence=fence)
            assert begun.admitted
            context = _runtime_context(
                job=begun.job, profile_body=profile_body, profile_sha=profile_sha
            )
            runtime, definition = _over_cap_batch_runtime(
                context, exa=forbidden, sumble=forbidden, enforce_budget=True
            )
            with pytest.raises(
                EntityResearchParallelAdmissionError,
                match="atomic tool batch exceeds the exact job budget",
            ):
                await runtime.run(definition=definition)
            assert dispatches == 0
            ledger = await _batch_ledger(
                turn_id=context.agent_turn_id,
                job_id=job_id,
                run_id=envelope.lifecycle.run_id,
            )
            assert ledger["batches"] == 0
            assert ledger["reservations"] == 0
            await _release(job_id, fence)

    run_async(scenario())


def test_an_over_cap_tool_batch_is_admitted_executed_and_recorded_with_controls_off() -> None:
    """AC2, the headline.

    The same wave the enforced coordinator refuses is admitted here: both provider handlers run,
    both reservations are written, both settle, and the recorded spend (5.00) honestly exceeds the
    job's exact 4.00 cap. Nothing is silently forgiven — the ledger is the record a pilot deployment
    reconciles against, and no job reaches the ``budget_stopped`` terminal outcome.
    """

    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    async def scenario() -> None:
        envelope, profile_body, profile_sha = _profile_authorized_envelope()
        job_cap = envelope.jobs[0].budget_cap_cents
        dispatched: list[str] = []

        async def exa(_values: dict[str, Any]) -> dict[str, Any]:
            dispatched.append("exa")
            return _provider_result(result_ref="exa-result:over-cap", cost_cents="2.50")

        async def sumble(_values: dict[str, Any]) -> dict[str, Any]:
            dispatched.append("sumble")
            return _provider_result(result_ref="sumble-result:over-cap", cost_cents="2.50")

        async with db_lifespan():
            store = R9EntityResearchJobStore()
            await store.launch(envelope)
            job_id = envelope.jobs[0].authorization.job_id
            fence = await _claim(job_id, worker_id="pilot-budget-off")
            begun = await store.begin(job_id, fence=fence)
            assert begun.admitted
            context = _runtime_context(
                job=begun.job, profile_body=profile_body, profile_sha=profile_sha
            )
            runtime, definition = _over_cap_batch_runtime(
                context, exa=exa, sumble=sumble, enforce_budget=False
            )
            # The scripted model returns no finalization proposal, so the run ends on the
            # finalizer's own refusal — long after the admission that is under test here.
            with pytest.raises(Exception) as terminal:  # noqa: PT011 -- the finalizer owns the type
                await runtime.run(definition=definition)
            assert not isinstance(terminal.value, EntityResearchParallelAdmissionError)

            assert sorted(dispatched) == ["exa", "sumble"]
            ledger = await _batch_ledger(
                turn_id=context.agent_turn_id,
                job_id=job_id,
                run_id=envelope.lifecycle.run_id,
            )
            assert ledger["batches"] == 1
            assert ledger["reservations"] == 2
            assert ledger["settlements"] == 2
            # Recording is untouched: the reserved and settled totals both exceed the exact cap.
            assert Decimal(str(ledger["reserved_cents"])) == 2 * _OVER_CAP_RESERVATION
            assert Decimal(str(ledger["reserved_cents"])) > job_cap
            assert Decimal(str(ledger["settled_cents"])) > job_cap
            assert ledger["budget_stopped"] == 0
            await _release(job_id, fence)

    run_async(scenario())


# --- AC3: an over-cap run advances through every budget-gated phase ----------------------------


def _phase_registry() -> tuple[PhaseHandlerRegistry, dict[ProjectPhase, RecordingPhaseHandler]]:
    registry = PhaseHandlerRegistry()
    handlers: dict[ProjectPhase, RecordingPhaseHandler] = {}
    events: list[str] = []
    for phase in PHASE_SEQUENCE:
        handler = RecordingPhaseHandler(phase, events=events)
        registry.register(handler)
        handlers[phase] = handler
    return registry, handlers


def test_a_run_past_its_cap_advances_through_every_budget_gated_phase_with_controls_off() -> None:
    """AC3.

    The mirror of ``test_over_cap_run_graceful_stops_before_first_spend_phase``: the identical
    over-cap run, on the identical real :class:`BudgetEngine`, driven by a machine built with
    ``enforce_budget=False``. It must reach ``HANDOFF``/``COMPLETED`` having actually run DISCOVERY,
    SCORING, DEEP and VERIFICATION — and the engine must never have recorded a ``graceful_stop``,
    because with controls off the pre-gate is not consulted at all rather than consulted-and-ignored
    (a consulted gate would write the event and lie about what happened).
    """

    async def scenario() -> None:
        store = FakeProjectRunStore()
        budget_store = FakeBudgetStore()
        registry, handlers = _phase_registry()
        machine = ProjectRun(
            store=store,
            registry=registry,
            budget_engine=BudgetEngine(store=budget_store),
            enforce_budget=False,
        )
        run_id = await machine.start(
            project_id="prj-pilot", workspace_id="ws-pilot", icp_key="default", icp_version=1
        )
        # Spend well past a cap that has since been lowered beneath it — the exact condition the
        # enforced machine graceful-stops on.
        budget_store.set_run(run_id, spent=Decimal("900"), cap=Decimal("500"))

        run = await machine.run_to_completion(run_id)

        assert run.status is ProjectRunStatus.COMPLETED
        assert run.phase is ProjectPhase.HANDOFF
        for phase in (
            ProjectPhase.DISCOVERY,
            ProjectPhase.SCORING,
            ProjectPhase.DEEP,
            ProjectPhase.VERIFICATION,
        ):
            assert handlers[phase].calls == 1, f"{phase.value} was stopped on budget grounds"
        assert BudgetEventKind.GRACEFUL_STOP not in budget_store.kinds()
        # The cap and the spend are both still there to be reported on: recording is untouched.
        state = await budget_store.run_state(run_id)
        assert state is not None
        assert (state.cap_cents, state.spent_cents) == (Decimal("500"), Decimal("900"))

    run_async(scenario())


def test_the_same_run_still_graceful_stops_with_controls_on() -> None:
    """AC1. The paired half of AC3 — the enforced machine is unchanged by this branch."""

    async def scenario() -> None:
        store = FakeProjectRunStore()
        budget_store = FakeBudgetStore()
        registry, handlers = _phase_registry()
        machine = ProjectRun(
            store=store,
            registry=registry,
            budget_engine=BudgetEngine(store=budget_store),
        )
        run_id = await machine.start(
            project_id="prj-pilot", workspace_id="ws-pilot", icp_key="default", icp_version=1
        )
        budget_store.set_run(run_id, spent=Decimal("900"), cap=Decimal("500"))

        run = await machine.run_to_completion(run_id)

        assert run.status is ProjectRunStatus.PAUSED
        assert run.phase is ProjectPhase.DISCOVERY
        assert handlers[ProjectPhase.DISCOVERY].calls == 0
        assert BudgetEventKind.GRACEFUL_STOP in budget_store.kinds()

    run_async(scenario())


# --- AC4: presentation off, approval integrity kept -------------------------------------------


def _budget_off_settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, chat_enabled=True, budget_controls_enabled=False, **kwargs)


def test_the_gate_row_keeps_the_amount_while_the_wire_and_the_card_carry_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4, the presentation half.

    Drives the shipped D5 read harness with budget controls off: the immutable row still carries the
    server-derived ``max_spend_cents`` (audit + approval integrity), the gates route serves ``null``
    rather than a number or a misleading ``"0"``, and the rich ``gate`` part omits
    ``amount_cents``/``currency`` entirely — the shape §3.4 already declares for a thin gate part.
    Everything that makes the card *answerable* still crosses.
    """

    import tests.api.test_lane_d5_gate_read_and_rich_parts_db as d5

    monkeypatch.setattr(d5, "_settings", _budget_off_settings)

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await d5._seed(
                conn, tmp_path, workspace_id="ws-pilot-gate", label="pilot-gate"
            )
            gate = await d5._present(conn, seeded)
            # The durable row is unchanged — this is what keeps approval auditable.
            assert gate.max_spend_cents == d5.AMOUNT

            async with d5._client(d5._app(conn)) as client:
                response = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/gates",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            assert response.status_code == 200
            served = response.json()["data"][0]
            assert served["max_spend_cents"] is None
            assert served["gate_id"] == str(gate.gate_id)
            assert served["expected_subject_sha256"] == d5.DIGEST
            assert served["addressee_user_id"] == d5.USER_ID

            emitter = await TurnStreamEmitter.open(
                workspace_id=seeded.workspace_id,
                project_id=seeded.project_id,
                thread_id=seeded.thread_id,
                turn_id=seeded.turn_id,
                conn_factory=d5.conn_session_factory(conn),
                policy=TurnStreamPolicy(gate_amount_visible=False),
            )
            await emitter.emit_gate_parts(refs=(d5._gate_ref(seeded, gate.gate_id),))
            assert emitter.emission_failures == []
            parts = await d5._parts(conn, seeded, PartKind.GATE)
            assert len(parts) == 1
            part = parts[0]
            assert "amount_cents" not in part
            assert "currency" not in part
            # The card is still a card: kind, state, subject digest, addressee, decisions.
            assert part["gate_kind"] == d5.KIND_DIRECTIVE_CONFIRMATION
            assert part["state"] == "requested"
            assert part["expected_subject_sha256"] == d5.DIGEST
            assert part["addressee_user_id"] == d5.USER_ID
            assert tuple(part["permitted_decisions"]) == d5.DECISIONS

    run_async(scenario())


def test_an_answer_echoing_any_amount_is_accepted_but_a_stale_digest_still_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4, the integrity half.

    With the amount withheld, the client has no number to echo, so the amount-staleness check is the
    *courier* half of the guard and is skipped. The **directive-digest** binding is the load-bearing
    half and stays armed: an answer aimed at a since-redrafted directive is still refused 409, so a
    decision still means the card that was on the screen.

    The accepted answer is a ``rejected`` decision on purpose: it exercises the identical
    ``_checked_gate`` staleness path (that is where both echoes are compared) without also dragging
    in ``confirm_account_research_directive@2``, which needs a seeded directive row and belongs to
    the Lane D option-B acceptance suite rather than to this one.
    """

    import tests.api.test_lane_d4_gate_response_route_db as route

    monkeypatch.setattr(route, "_settings", _budget_off_settings)

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await route._seed(
                conn, tmp_path, workspace_id="ws-pilot-answer", label="pilotanswer"
            )
            gate = await route._present(conn, seeded)
            app = route._app(conn, storage=seeded.storage)
            async with route._client(app) as client:
                stale_digest = await route._answer(
                    client,
                    seeded,
                    gate=gate,
                    key="pilot-stale-digest",
                    decision="rejected",
                    digest="d" * 64,
                )
                assert stale_digest.status_code == 409, stale_digest.text
                assert stale_digest.json()["error"]["code"] == "GATE_SUBJECT_STALE"

                # An amount nobody was ever shown — and deliberately not the stored one.
                accepted = await route._answer(
                    client,
                    seeded,
                    gate=gate,
                    key="pilot-any-amount",
                    decision="rejected",
                    amount=Decimal("1"),
                )
            assert accepted.status_code == 202, accepted.text
            assert Decimal("1") != gate.max_spend_cents

    run_async(scenario())


def test_the_same_answer_is_refused_on_a_stale_amount_with_controls_on(
    tmp_path: Path,
) -> None:
    """AC1. The paired half: with controls on, the courier check is exactly as strict as before."""

    import tests.api.test_lane_d4_gate_response_route_db as route

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await route._seed(
                conn, tmp_path, workspace_id="ws-pilot-answer-on", label="pilotanswron"
            )
            gate = await route._present(conn, seeded)
            app = route._app(conn, storage=seeded.storage)
            async with route._client(app) as client:
                refused = await route._answer(
                    client,
                    seeded,
                    gate=gate,
                    key="pilot-on-amount",
                    decision="rejected",
                    amount=Decimal("1"),
                )
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "GATE_AMOUNT_STALE"

    run_async(scenario())


# --- AC4: the launcher ignores the courier field and keeps every structural check ---------------


_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_HIRING = "account.hiring_velocity_eng"


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    async with conn.begin_nested():
        yield conn


def _direction_questions() -> tuple[ResearchQuestion, ...]:
    return (
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
    )


def test_the_launcher_ignores_the_courier_estimate_but_keeps_every_structural_check(
    tmp_path: Path,
) -> None:
    """AC4, the launch half.

    With controls off the launcher accepts *any* ``expected_estimated_cost_cents`` (the agent has no
    number to echo, because no surface carries one) and any approved cap — but it still recomputes
    the estimate for the record, still demands the current human-confirmed directive, and still
    launches each job with the directive's own per-account ``budget_cap_cents``, so spend stays
    attributed. The structural refusal is proved by re-running the same request against a directive
    the launcher cannot accept.
    """

    if not _db_available():
        pytest.skip("CLUE_DATABASE_URL unset or database unreachable")

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "pilot-launch-artifacts")
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
                questions=_direction_questions(),
            )
            pin = account_spec.research_directive
            assert pin is not None
            await conn.execute(
                text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
                {"project_run_id": fixture.project_run_id},
            )

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            fleets = AccountResearchFleetService(conn_factory=connection)
            request = AccountResearchFleetLaunchRequest(
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_run_id=UUID(str(fixture.project_run_id)),
                research_directive_id=UUID(str(pin.directive_id)),
                account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                # Both numbers are nonsense on purpose: nothing showed the human an amount, so
                # nothing may be asked to echo one back.
                approved_budget_cap_cents=Decimal("1"),
                expected_estimated_cost_cents=Decimal("1"),
                concurrency_limit=4,
                supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
            )

            # Controls ON: the same request is refused on its estimate — unchanged behaviour.
            with pytest.raises(
                AccountResearchFleetLaunchError,
                match="approved estimate differs from the current effective directives",
            ):
                await AccountResearchFleetLauncher(fleets=fleets, conn_factory=connection).launch(
                    request,
                    actor="human:account-owner",
                    source_action_ref="turn:pilot-launch-on",
                    source_operation_id=uuid4(),
                )

            # Controls OFF: it launches, and the job carries the directive's real per-account cap.
            projection = await AccountResearchFleetLauncher(
                fleets=fleets, conn_factory=connection, enforce_budget=False
            ).launch(
                request,
                actor="human:account-owner",
                source_action_ref="turn:pilot-launch-off",
                source_operation_id=uuid4(),
            )
            assert projection.fleet_state is AccountResearchFleetState.CANARY
            assert projection.selected_accounts == 1
            job_cap = (
                await conn.execute(
                    text(
                        "SELECT budget_cap_cents FROM entity_research_job "
                        "WHERE research_run_id=:run_id"
                    ),
                    {"run_id": projection.research_run_id},
                )
            ).scalar_one()
            # The launched authority is the directive's, never the caller's ignored "1".
            assert Decimal(str(job_cap)) > Decimal("1")

            # Structural authority is untouched: an unknown directive is still refused.
            with pytest.raises(
                AccountResearchFleetLaunchError,
                match="account research requires the current human-confirmed directive",
            ):
                await AccountResearchFleetLauncher(
                    fleets=fleets, conn_factory=connection, enforce_budget=False
                ).launch(
                    request.model_copy(update={"research_directive_id": uuid4()}),
                    actor="human:account-owner",
                    source_action_ref="turn:pilot-launch-unknown",
                    source_operation_id=uuid4(),
                )

    run_async(scenario())


# --- the composition roots actually thread the switch ------------------------------------------


def test_every_composition_root_threads_the_switch_rather_than_reading_it_globally() -> None:
    """The seam contract: the flag enters at a root and is injected, never read mid-stack.

    Guards the property that makes both modes testable at all — a coordinator, machine, launcher or
    gate tool that read ``load_settings()`` itself could not be exercised in both states from one
    process, and would make the deployment switch invisible at its own call site.
    """

    import inspect

    from clue_api import account_research_fleet_composition as accounts
    from clue_api import agent_gate_wiring, entity_research_fleet_composition, phase_wiring
    from clue_api import contact_research_fleet_composition as contacts

    for builder, parameter in (
        (accounts.build_account_research_fleet_composition, "enforce_budget"),
        (contacts.build_contact_research_fleet_composition, "enforce_budget"),
        (
            entity_research_fleet_composition.build_entity_research_fleet_composition,
            "enforce_budget",
        ),
        (phase_wiring.build_tier_checkpoint_handler, "enforce_budget"),
        (phase_wiring.register_tier_checkpoint_handler, "enforce_budget"),
        (agent_gate_wiring.register_agent_gate_tools, "budget_controls_enabled"),
    ):
        signature = inspect.signature(builder)
        assert parameter in signature.parameters, f"{builder.__qualname__} lost its switch"
        assert signature.parameters[parameter].default is True, (
            f"{builder.__qualname__} must default to today's enforced behaviour"
        )

    for module in (
        "clue_api.entity_research_parallel",
        "clue_api.account_research_fleet_launch",
        "clue_api.contact_research_fleet_launch",
        "clue_api.agent_gate_tools",
        "clue_research.durable.project",
        "clue_research.discovery_scoring.phases",
    ):
        source = inspect.getsource(__import__(module, fromlist=["_"]))
        assert "load_settings" not in source, f"{module} reads settings instead of being injected"


def test_the_r9_coordinator_and_project_machine_default_to_enforcing() -> None:
    """A collaborator constructed without the switch must behave exactly as it did at BASE."""

    assert DbEntityResearchToolBatchCoordinator()._enforce_budget is True
    assert ProjectRun(store=FakeProjectRunStore(), registry=PhaseHandlerRegistry())._enforce_budget

    assert OpenDirectiveConfirmationGateTool()._budget_controls_enabled is True
