"""Lane D slice D4 — the Option-B kickoff **as the deepagent actually reaches it**.

The acceptance in ``test_lane_d4_option_b_acceptance_db`` proves the authority chain by calling the
launcher directly. This one proves the *path*: every step goes through the C5 interaction slot,
which is the second, independent ceiling a conversational tool call has to clear. A surface grant
alone was never enough — until ``recipe0-stage0@6`` the widened conversation surface would have
shown the model three tools that plan validation then refused with ``c5_tool_not_allowed``.

So this suite drives the real thing: a real promoted recipe revision, a real ``RecipeExecutor``, the
real ``Stage0StepPinProvider``, and the real ``C5AgentExecutionAdapter`` — everything except the
model, whose only job is to author the plan, which the test authors instead.

1. the agent **plans** ``open_directive_confirmation_gate@1``; plan validation admits it, the C5
   executor runs it, and the gate lands with the server-derived maximum spend;
2. the human answers through the production turn route (the structured gate response);
3. the agent — now woken on the **confirming** turn — **cannot** plan ``launch_account_research@1``
   any more: founder ruling 2 (2026-09-10) dropped the five old-research-lane tools from
   ``head-of-abm@v44``, so the same validation that admits the gate refuses that launch on both
   ceilings it has to clear (effective authority and effective profile). The launcher-driven
   acceptance in ``test_lane_d4_option_b_acceptance_db`` still proves the ambient-``action_ref``
   stamping this step used to prove here; what this step now pins is that no *conversational* path
   to the retired lane survived the drop;
4. and a plan proposing the human-only ``confirm_account_research_directive@2`` is still refused —
   structurally, by the same validation, with no execution and no confirmation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentPlan, AgentRole, AgentTurnRequest, ToolPin
from clue_agents.contracts import DomainObjectRef, ExecutionId, PlanToolStep
from clue_api.agent_execution_wiring import AgentPlanRejected, DbAgentPlanJournal
from clue_api.agent_gate import get_gate, money_text
from clue_api.agent_registry_wiring import (
    PROJECT_CONVERSATION_SURFACE,
    build_agent_profile_registry,
)
from clue_api.agent_turn_submission import get_submission, message_artifact_ref
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.contact_research_fleet import ContactResearchFleetService
from clue_api.contact_research_fleet_launch import (
    ContactResearchFleetLauncher,
    ContactResearchSelectionApprover,
)
from clue_api.conversation_turns import CONVERSATION_RECIPE_KEY, CONVERSATION_RECIPE_VERSION
from clue_api.entity_research_launch_tools import EntityResearchLaunchServices
from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_api.head_of_abm_wiring import build_head_of_abm_stage0_execution
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    seed_system_recipes,
)
from clue_api.stage0_trial import stage0_trial_recipe_definitions
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_action import derive_turn_action_ref
from clue_api.turn_binding import CapturedTurnBinder
from clue_config import load_settings
from clue_execution import (
    CompatibilityLoader,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    ExecutionStatus,
    RecipeExecutor,
    RecipeScopeType,
)
from clue_fleet import LeaseGeneration, WorkId, acquire_work_lease, release_work_lease
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore
from tests.agents.conftest import NOW, constitution
from tests.api.conftest import hermetic_flag_env
from tests.api.test_lane_d4_option_b_acceptance_db import (
    USER_ID,
    _seed_two_account_conversation,
)
from tests.api.test_lane_d4_option_b_acceptance_db import _app as _route_app
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

_WORKER_ID = "lane-d4-model-planned"
_PER_ACCOUNT_CAP = Decimal(300)


@pytest.fixture
def require_planning_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_planning_db")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, Any]]:
        return
        yield


class _Plane:
    """The C5 execution plane, composed once over the test's rolled-back connection."""

    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _build_plane(conn: AsyncConnection, tmp_path: Path, storage: Any = None) -> _Plane:
    """Everything a real conversational turn needs, minus the model.

    ``storage`` is the *conversation's* artifact backend when there is one: the turn the agent
    answers is bound to the human's captured bytes, and a second store would simply not have them.
    """

    cf = conn_session_factory(conn)
    storage = storage if storage is not None else FsStorage(tmp_path / "planned-artifacts")
    settings = load_settings(_env_file=None, chat_enabled=True)
    with hermetic_flag_env():
        tools = build_toolbelt(
            storage=storage,
            settings=settings,
            gateway=None,
            conn_factory=cf,
            # The launch tool is composed exactly as the fleet worker composes it. Its two account
            # collaborators are the real ones; the contact side is present because the services
            # bundle is all-or-nothing, and nothing in this suite touches it.
            entity_research_launches=EntityResearchLaunchServices(
                account_launcher=_account_launcher(cf),
                account_fleets=_account_fleets(cf),
                contact_approver=ContactResearchSelectionApprover(conn_factory=cf),
                contact_launcher=ContactResearchFleetLauncher(conn_factory=cf),
                contact_fleets=ContactResearchFleetService(conn_factory=cf),
            ),
        )
        profiles = build_agent_profile_registry(tools)
    pin_registry = build_recipe_pin_registry(tool_registry=tools, conn_factory=cf)
    compatibility = CompatibilityLoader(pin_registry)
    repository = DbRecipeRepository(conn_factory=cf)
    await seed_system_recipes(
        repository=repository,
        lifecycle=build_recipe_lifecycle(
            tool_registry=tools, conn_factory=cf, pin_registry=pin_registry
        ),
        # The recipe-0 family only: recipe1-classic pins legacy tools this toolbelt does not
        # register, and seeding it would fail promotion for reasons that have nothing to do with
        # the conversation. Same choice the trial makes, for the same reason.
        definitions=stage0_trial_recipe_definitions(),
    )
    journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
    parameters = StorageExecutionParameterStore(
        StorageParameterArtifactStore(storage=storage, conn_factory=cf)
    )
    tool_invoker = build_tool_invoker(
        registry=tools,
        idempotency_store=DbIdempotencyStore(conn_factory=cf),
        storage=_MemoryStorage(),
        settings=settings,
        conn_factory=cf,
    )
    recipes = DbRecipeReader(conn_factory=cf)
    return _Plane(
        conn_factory=cf,
        storage=storage,
        tools=tools,
        profiles=profiles,
        compatibility=compatibility,
        recipes=recipes,
        starter=DbExecutionStarter(
            conn_factory=cf, recipes=recipes, compatibility=compatibility, journal=journal
        ),
        executor=RecipeExecutor(
            conn_factory=cf,
            recipes=recipes,
            compatibility=compatibility,
            journal=journal,
            parameters=parameters,
            tool_invoker=tool_invoker,
            max_concurrency=2,
        ),
        parameters=parameters,
        tool_invoker=tool_invoker,
        artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=cf),
    )


def _account_launcher(cf: Any) -> Any:
    from clue_api.account_research_fleet import AccountResearchFleetService
    from clue_api.account_research_fleet_launch import AccountResearchFleetLauncher

    return AccountResearchFleetLauncher(
        fleets=AccountResearchFleetService(conn_factory=cf), conn_factory=cf
    )


def _account_fleets(cf: Any) -> Any:
    from clue_api.account_research_fleet import AccountResearchFleetService

    return AccountResearchFleetService(conn_factory=cf)


async def _drive(plane: _Plane, execution_id: ExecutionId) -> ExecutionStatus:
    async with plane.conn_factory() as conn:
        lease = await acquire_work_lease(conn, work_id=WorkId(execution_id), worker_id=_WORKER_ID)
    assert lease is not None
    try:
        result = await plane.executor.execute(
            execution_id, worker_id=_WORKER_ID, lease_generation=lease.generation
        )
        return result.status
    finally:
        async with plane.conn_factory() as conn:
            await release_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id=_WORKER_ID,
                generation=LeaseGeneration(lease.generation),
            )


async def _adapter(
    plane: _Plane,
    scenario: Any,
    *,
    turn_id: UUID,
    label: str,
) -> Any:
    """Start one conversational turn's C5 execution and bind the agent adapter to it.

    This is the production shape: the turn's recipe is the *pinned* revision
    (``CONVERSATION_RECIPE_KEY@CONVERSATION_RECIPE_VERSION``) — asserted, not hardcoded, so this
    suite fails loudly if the pin and the widened revision ever part company.
    """

    execution_id = ExecutionId(uuid5(turn_id, "c5-execution"))
    revision = await plane.recipes.get_by_identity(
        scope_type=RecipeScopeType.SYSTEM,
        workspace_id=None,
        recipe_key=CONVERSATION_RECIPE_KEY,
        version=CONVERSATION_RECIPE_VERSION,
    )
    assert revision is not None, "the pinned conversation recipe revision must be promoted"
    parameter_key, parameter_sha = await plane.parameters.snapshot(
        workspace_id=scenario.workspace_id, parameters={}
    )
    await plane.starter.start(
        workspace_id=scenario.workspace_id,
        recipe_revision_id=revision.recipe_revision_id,
        parameters={},
        parameter_artifact_key=parameter_key,
        parameter_manifest_hash=parameter_sha,
        actor="human",
        execution_id=execution_id,
        project_id=scenario.project_id,
    )
    assert await _drive(plane, execution_id) is ExecutionStatus.AWAITING_INPUT

    resolved = plane.profiles.resolve(AgentRole.HEAD_OF_ABM, surface=PROJECT_CONVERSATION_SURFACE)
    manifest_ref = await plane.artifacts.persist_body(
        workspace_id=scenario.workspace_id,
        data=resolved.resource_manifest.model_dump_json().encode(),
        media_type="application/vnd.clue.agent-resource-manifest+json",
    )
    card_ref = await plane.artifacts.persist_body(
        workspace_id=scenario.workspace_id,
        data=b'{"card":"stage0"}',
        media_type="application/json",
    )
    budget_ref = await plane.artifacts.persist_body(
        workspace_id=scenario.workspace_id,
        data=b'{"budget":"envelope"}',
        media_type="application/json",
    )
    # The turn's user message is the human's *captured* bytes, read back from the durable
    # submission — not a fresh blob. The gate tool's ``source_turn_ref`` is a TRUSTED_TURN_FIELD,
    # so the engine only serves it when the capture/artifact integrity join holds; a turn with
    # invented bytes is refused with ``turn_binding_unavailable``, which is the protection working.
    async with plane.conn_factory() as capture_conn:
        submission = await get_submission(
            capture_conn, workspace_id=scenario.workspace_id, turn_id=turn_id
        )
        assert submission is not None
        user_ref = await message_artifact_ref(capture_conn, submission)
    request = AgentTurnRequest(
        turn_id=turn_id,
        thread_id=scenario.thread_id,
        constitution=constitution(
            workspace_id=scenario.workspace_id,
            project_id=scenario.project_id,
            execution_id=execution_id,
            # The authenticated human this turn belongs to. The C5 seam stamps it as the ambient
            # ``actor_id`` and derives ``action_ref`` from the turn — neither is ever a plan field.
            actor_id=USER_ID,
            brand_id=scenario.fixture.discovery_fixture.brand_id,
            product_id=scenario.product_id,
            client_entity_id=None,
            workspace_root_id=f"root-{label}",
            profile_ref=resolved.profile_ref,
            project_card_ref=card_ref,
            budget_envelope_ref=budget_ref,
            resource_manifest_ref=manifest_ref,
            resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
            focus_refs=(
                DomainObjectRef(
                    workspace_id=scenario.workspace_id,
                    object_type="project",
                    object_id=scenario.project_id,
                ),
            ),
        ),
        user_message_artifact_ref=user_ref,
        requested_at=NOW,
    )
    # The turn row and its C5 execution are created together, by the same actor, with the same
    # execution id — which is not decoration: ``agent_plan`` foreign-keys
    # ``(turn_id, execution_id, workspace_id)`` onto ``agent_turn``, so a turn row minted against
    # some other execution could never hold a plan. This is exactly what the fleet worker does.
    await DbAgentTurnJournal(conn_factory=plane.conn_factory).create(
        request=request, profile=resolved.profile
    )
    return build_head_of_abm_stage0_execution(
        request=request,
        profiles=plane.profiles,
        tools=plane.tools,
        tool_invoker=plane.tool_invoker,
        executor=plane.executor,
        compatibility=plane.compatibility,
        artifacts=plane.artifacts,
        plans=DbAgentPlanJournal(conn_factory=plane.conn_factory),
        checkpointer_factory=lambda _execution_id: None,
        budget_limit_millicents=10_000_000,
        captured_turns=CapturedTurnBinder(
            artifacts=plane.artifacts, conn_factory=plane.conn_factory
        ),
        surface=PROJECT_CONVERSATION_SURFACE,
        conn_factory=plane.conn_factory,
    )


def _pin(plane: _Plane, name: str, version: str) -> ToolPin:
    descriptor = plane.tools.descriptor(name, version)
    return ToolPin(
        name=descriptor.name,
        version=descriptor.version,
        input_schema_sha256=descriptor.input_schema_sha256,
        output_schema_sha256=descriptor.output_schema_sha256,
    )


def _plan(adapter: Any, *steps: PlanToolStep) -> AgentPlan:
    return AgentPlan(
        plan_id=uuid4(),
        execution_id=adapter._constitution.execution_id,
        role=AgentRole.HEAD_OF_ABM,
        goal_ref=adapter._constitution.project_card_ref,
        steps=steps,
        proposed_at=NOW,
    )


async def _run(adapter: Any, *steps: PlanToolStep) -> list[Any]:
    """Validate the agent's plan, then execute it through the C5 slot.

    ``validate_plan`` returning at all is the admission proof this suite exists for: it is where a
    tool absent from the promoted revision's allowlist raises ``c5_tool_not_allowed``, and where a
    pin kind the provider failed to supply raises ``missing_tool_requirement``.
    """

    try:
        validated = await adapter.validate_plan(
            plan=_plan(adapter, *steps), constitution=adapter._constitution
        )
    except AgentPlanRejected as exc:  # pragma: no cover - only on a failing assertion
        raise AssertionError(
            "plan validation refused the kickoff: "
            + "; ".join(f"{i.code}@{i.location}: {i.message}" for i in exc.review.issues)
        ) from exc
    assert {operation.node_key for operation in validated.operations} == {
        step.node_key for step in steps
    }
    progress = [item async for item in adapter.execute(plan=validated)]
    assert progress[-1].status == "completed", progress[-1]
    return progress


# --- the model-planned kickoff -----------------------------------------------------------------


def test_the_deepagent_plans_the_whole_kickoff_through_the_c5_slot(tmp_path: Path) -> None:
    """Draft + gate in one planned turn, then launch in the confirming turn's planned turn."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            plane = await _build_plane(conn, tmp_path, scenario.storage)

            # (1) The presenting turn: the agent plans its confirmation gate over the directive
            # it drafted. The address clears the C5 allowlist and every pin kind it requires —
            # `project_run` and `research_directive` — is supplied by the real Stage-0 pin
            # provider; `validate_plan` returning at all is what proves both.
            drafting = await _adapter(
                plane, scenario, turn_id=scenario.presenting_turn_id, label="present"
            )
            await _run(
                drafting,
                PlanToolStep(
                    node_key="present_gate",
                    tool=_pin(plane, "open_directive_confirmation_gate", "1"),
                    arguments={
                        "project_run_id": str(scenario.fixture.project_run_id),
                        "research_directive_id": str(scenario.directive_id),
                        "account_entity_ids": [str(v) for v in scenario.account_ids],
                        # ``source_turn_ref`` is a TRUSTED_TURN_FIELD: stripped from the model's
                        # schema and injected by the engine, so the plan deliberately omits it.
                    },
                    purpose="Ask the client to confirm the drafted research direction.",
                ),
            )

            gates = (
                (
                    await conn.execute(
                        text(
                            "SELECT gate_id, max_spend_cents, addressee_user_id, "
                            "expected_subject_sha256 FROM agent_gate WHERE workspace_id = :ws"
                        ),
                        {"ws": scenario.workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(gates) == 1
            gate_id = UUID(str(gates[0]["gate_id"]))
            assert gates[0]["max_spend_cents"] == 2 * _PER_ACCOUNT_CAP
            assert gates[0]["addressee_user_id"] == USER_ID
            assert gates[0]["expected_subject_sha256"] == scenario.directive_sha256

            # (2) The human answers through the production turn route.
            app = _route_app(conn, scenario)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                response = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{scenario.thread_id}/turns",
                    json={
                        "gate_response": {
                            "gate_id": str(gate_id),
                            "decision": "approved",
                            "expected_subject_sha256": scenario.directive_sha256,
                            "expected_estimated_cost_cents": money_text(2 * _PER_ACCOUNT_CAP),
                        }
                    },
                    headers={
                        "X-Workspace-Id": scenario.workspace_id,
                        "Idempotency-Key": "planned-approve",
                    },
                )
            assert response.status_code == 202, response.text
            confirming_turn_id = UUID(response.json()["data"]["turn_id"])
            confirming_ref = derive_turn_action_ref(confirming_turn_id)

            view = await get_gate(conn, workspace_id=scenario.workspace_id, gate_id=gate_id)
            assert view is not None and view.answer is not None
            assert view.answer.decision == "approved"

            # (3) The agent is woken on that confirming turn — and the old lane's launch is no
            # longer plannable. Founder ruling 2 (2026-09-10) dropped it from `head-of-abm@v44`, so
            # the two ceilings a conversational tool call must clear both refuse it: it is absent
            # from the effective authority AND from the bound profile's effective tools. The
            # refusal is structural (nothing executed, nothing spent), which is the whole point:
            # retiring the lane from the model surface cannot leave a planning path open.
            launching = await _adapter(plane, scenario, turn_id=confirming_turn_id, label="confirm")
            retired = PlanToolStep(
                node_key="launch",
                tool=_pin(plane, "launch_account_research", "1"),
                arguments={
                    "project_run_id": str(scenario.fixture.project_run_id),
                    "research_directive_id": str(scenario.directive_id),
                    "account_entity_ids": [str(v) for v in scenario.account_ids],
                    "approved_budget_cap_cents": str(2 * _PER_ACCOUNT_CAP),
                    "expected_estimated_cost_cents": str(2 * _PER_ACCOUNT_CAP),
                    "concurrency_limit": 4,
                },
                purpose="Launch the research the client just confirmed.",
            )
            with pytest.raises(AgentPlanRejected) as rejected:
                await launching.validate_plan(
                    plan=_plan(launching, retired),
                    constitution=launching._constitution,
                )
            assert {issue.code for issue in rejected.value.review.issues} == {
                "tool_not_allowed",
                "tool_not_effective",
            }
            # The confirming turn's own receipt is still what a launch on the CURRENT lane would be
            # stamped with; nothing here consumed it, and nothing was launched.
            assert confirming_ref
            launched = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_account_fleet "
                        "WHERE workspace_id = :ws"
                    ),
                    {"ws": scenario.workspace_id},
                )
            ).scalar_one()
            assert launched == 0

    run_async(scenario_body())


def test_a_plan_proposing_the_human_only_confirm_tool_is_refused(tmp_path: Path) -> None:
    """The one thing widening the slot must not have done: hand the model the human's authority."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            plane = await _build_plane(conn, tmp_path, scenario.storage)
            adapter = await _adapter(
                plane, scenario, turn_id=scenario.presenting_turn_id, label="refuse"
            )

            with pytest.raises(AgentPlanRejected) as caught:
                await adapter.validate_plan(
                    plan=_plan(
                        adapter,
                        PlanToolStep(
                            node_key="confirm",
                            tool=_pin(plane, "confirm_account_research_directive", "2"),
                            arguments={
                                "directive_id": str(scenario.directive_id),
                                "expected_sha256": scenario.directive_sha256,
                            },
                            purpose="Confirm the direction on the client's behalf.",
                        ),
                    ),
                    constitution=adapter._constitution,
                )
            codes = {issue.code for issue in caught.value.review.issues}
            # Refused by *both* ceilings independently: the profile/surface never granted it, and
            # the promoted recipe revision never allowlisted it. Widening one could not have
            # reached it.
            assert codes & {"tool_not_allowed", "tool_not_in_profile", "c5_tool_not_allowed"}

            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM account_research_directive "
                        "WHERE status = 'confirmed' AND workspace_id = :ws"
                    ),
                    {"ws": scenario.workspace_id},
                )
            ).scalar_one() == 0

    run_async(scenario_body())


def test_frozen_v2_remains_replayable_while_the_current_slot_uses_comprehensive_v4(
    tmp_path: Path,
) -> None:
    """The historical schemas are unchanged; only their immutable successor is newly promoted."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            plane = await _build_plane(conn, tmp_path, scenario.storage)

            definition = next(
                item
                for item in stage0_trial_recipe_definitions()
                if item.version == CONVERSATION_RECIPE_VERSION
            )
            slot = next(
                node for node in definition.graph.nodes if node.node_key == "stage0_interactions"
            )
            assert "draft_account_research_directive@2" not in slot.dynamic_tool_allowlist
            assert "draft_account_research_directive@3" not in slot.dynamic_tool_allowlist
            assert "draft_account_research_directive@4" not in slot.dynamic_tool_allowlist
            assert "draft_account_research_directive@5" in slot.dynamic_tool_allowlist
            assert (
                "body"
                in plane.tools.descriptor(
                    "draft_account_research_directive", "2"
                ).input_model.model_fields
            )
            assert (
                "directive"
                in plane.tools.descriptor(
                    "draft_account_research_directive", "3"
                ).input_model.model_fields
            )
            # The promoted contract adds the breadth declaration §3.3 row 1 needs.
            assert (
                "profile"
                in plane.tools.descriptor(
                    "draft_account_research_directive", "5"
                ).input_model.model_fields
            )

    run_async(scenario_body())


def test_comprehensive_directive_v5_can_ride_the_current_conversation_plan(tmp_path: Path) -> None:
    """The promoted successor keeps v3's plan-safe shape and adds the breadth declaration.

    The scripted plan states an explicit field list, so it must declare ``profile="custom"`` —
    exactly the narrower request §3.3 row 1 reserves for an explicit human ask.
    """

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            plane = await _build_plane(conn, tmp_path, scenario.storage)
            adapter = await _adapter(
                plane, scenario, turn_id=scenario.presenting_turn_id, label="draftplan-v3"
            )

            validated = await adapter.validate_plan(
                plan=_plan(
                    adapter,
                    PlanToolStep(
                        node_key="draft_direction_v4",
                        tool=_pin(plane, "draft_account_research_directive", "5"),
                        arguments={
                            "product_id": scenario.product_id,
                            "icp_key": scenario.fixture.deep_icp_key,
                            "icp_version": scenario.fixture.deep_icp_version,
                            "profile": "custom",
                            "directive": scenario.directive_body,
                        },
                        purpose="Draft the selected-account research direction.",
                    ),
                ),
                constitution=adapter._constitution,
            )

            assert validated.operations[0].address == "draft_account_research_directive@5"

    run_async(scenario_body())


def test_the_widened_slot_grants_the_trial_nothing(tmp_path: Path) -> None:
    """The recipe ceiling is shared; the trial's own surface still withholds all three tools."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            plane = await _build_plane(conn, tmp_path)
            from clue_api.agent_registry_wiring import STAGE0_CONVERSATION_TRIAL_SURFACE

            trial = plane.profiles.resolve(
                AgentRole.HEAD_OF_ABM, surface=STAGE0_CONVERSATION_TRIAL_SURFACE
            )
            production = plane.profiles.resolve(
                AgentRole.HEAD_OF_ABM, surface=PROJECT_CONVERSATION_SURFACE
            )
            trial_names = {pin.name for pin in trial.profile.tools}
            production_names = {pin.name for pin in production.profile.tools}

            # The recipe ceiling is shared by both surfaces, so raising it had to be safe for the
            # one that must never launch. It is: a ceiling grants nothing a surface withholds, and
            # the trial's policy still subtracts the two tools that turn direction into spend.
            for name in (
                "draft_account_research_directive",
                "open_directive_confirmation_gate",
                # Founder ruling 2 (2026-09-10) retired `launch_account_research` from the role;
                # the ARV2 launch is what the production surface spends through now, and the same
                # sentence still keeps it off the trial.
                "launch_arv2_account_research",
            ):
                assert name in production_names
            assert "open_directive_confirmation_gate" not in trial_names
            assert "launch_arv2_account_research" not in trial_names
            assert "launch_account_research" not in production_names
            assert "launch_account_research" not in trial_names
            # Drafting was always the trial's — it writes a non-spending draft and nothing else.
            # Without a gate to present it at and a launch to spend it, the widened revision leaves
            # the trial exactly as capable as it was.
            assert "draft_account_research_directive" in trial_names

    run_async(scenario_body())
