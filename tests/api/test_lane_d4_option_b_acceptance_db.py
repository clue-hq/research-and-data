"""Lane D slice D4 — **the Option-B acceptance**, on the canonical two-account fixture.

Charter slice D4's acceptance criterion, end to end in one conversation:

1. the agent drafts a directive and calls ``open_directive_confirmation_gate@1``;
2. the gate carries the **exact server-derived maximum spend** — the same Σ per-account
   ``effort_policy.budget_cap_cents`` the launcher will verify, computed once and stored
   immutably, with no estimate tool anywhere (ratified §6-D5);
3. the user's structured **Approve** is a visible human turn, and the server invokes the human-only
   ``confirm_account_research_directive@2`` outside the model surface, so
   ``confirmed_by`` / ``confirming_turn_ref`` come out equal to the ambient ``actor_id`` and the
   answering turn's ``turn-action:`` receipt;
4. the platform deepagent then launches with **that** turn-derived ``action_ref``, and
   ``entity_research_run``'s fleet row records it as ``source_action_ref`` while the run's frozen
   selection carries both refs in ``approval_refs``;
5. the launch verifies the gate's number by exact match — an amount that is not the gate's is
   refused;
6. and the whole chain is legible afterwards as one join: gate → confirming turn → launched run.

The fixture is the A1 Insight Health account plus a second workspace-local account with its own
human tier checkpoint, both carried by one drafted directive — the charter's "two accounts with
approved tier checkpoints".
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_estimate import compute_account_research_estimate
from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchError,
    AccountResearchFleetLaunchRequest,
)
from clue_api.agent_gate import get_gate, money_text
from clue_api.agent_gate_tools import OpenDirectiveConfirmationGateTool, gate_ref
from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.conversation_capture import persist_user_turn
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.thread_wiring import register_thread_tools
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_api.turn_action import derive_turn_action_ref, resolve_gate_answer_action
from clue_config import Settings, load_settings
from clue_core import (
    EntityId,
    MemoryDisabled,
    MemorySubmission,
    ProjectRunId,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchEffortPolicy,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
    RunId,
    new_operation_id,
)
from clue_projections import thread_gates
from clue_research.discovery_scoring.tiering import persist_discovery_selection_tier
from clue_research.discovery_scoring.tiering.selection import (
    DiscoveryCriteriaAccountView,
    DiscoverySelectionDisposition,
)
from clue_research.identity import insert_account_entity
from clue_storage import FsStorage
from clue_toolbelt import (
    DbIdempotencyStore,
    PreconditionFailed,
    ToolContext,
    ToolRegistry,
    invoke_tool,
)
from tests._identity import seed_principal
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_d4_optionb"
NOW_UTC = datetime(2026, 8, 9, 11, 0, tzinfo=UTC)

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_HIRING = "account.hiring_velocity_eng"
_PER_ACCOUNT_CAP = Decimal(300)


@pytest.fixture
def require_acceptance_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_acceptance_db")


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

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


class _DisabledMemory:
    async def submit(self, _submission: MemorySubmission) -> MemoryDisabled:
        return MemoryDisabled()


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    async with conn.begin_nested():
        yield conn


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, chat_enabled=True, **kwargs)


class _Scenario:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _seed_two_account_conversation(
    conn: AsyncConnection,
    tmp_path: Path,
    *,
    create_turn_row: bool = True,
) -> _Scenario:
    """The canonical fixture: two tier-checkpointed accounts, one thread, one drafted directive.

    ``create_turn_row`` writes the worker's half of the opening turn's identity. It defaults on
    because a gate's presenting-turn FK needs it and this module never runs a real C5 execution;
    the model-planned suite turns it off so the adapter can create the execution and the turn row
    together, exactly as the fleet worker does.
    """

    storage = FsStorage(tmp_path / "optionb-artifacts")
    fixture = await seed_insight_health_account_deep_fixture(conn, pages=_pages(), storage=storage)
    workspace_id = fixture.discovery_fixture.workspace_id
    project_id = fixture.discovery_fixture.project_id
    product_id = fixture.discovery_fixture.product_id
    conn_factory = conn_session_factory(conn)

    # A second account of the same workspace, with its own *human* tier checkpoint written by the
    # real writer rather than hand-inserted — the launcher's proof of approval is exactly this row.
    second_account_id = await insert_account_entity(
        conn,
        canonical_name="Northwind Care Group",
        primary_domain="northwindcare.example",
        workspace_id=workspace_id,
    )
    await persist_discovery_selection_tier(
        conn,
        view=DiscoveryCriteriaAccountView(
            account_id=second_account_id,
            disposition=DiscoverySelectionDisposition.SELECTED,
            criteria=(),
            required_field_states={},
        ),
        tier="high",
        selection_policy_version="d4-acceptance-v1",
        decision_version="d4-acceptance-v1",
        discovery_batch_id=str(fixture.discovery_batch_id),
        discovery_seal_sha256=fixture.discovery_seal_sha256,
        project_run_id=fixture.project_run_id,
        run_id=RunId(uuid5(NAMESPACE_URL, "lane-d4:optionb:second-tier-run")),
        workspace_id=workspace_id,
        icp_key=fixture.deep_icp_key,
        icp_version=fixture.deep_icp_version,
    )

    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"wsm_d4_optionb_{workspace_id}",
    )
    thread_id = "thr_d4_optionb"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user) ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": thread_id,
            "workspace": workspace_id,
            "project": project_id,
            "user": USER_ID,
        },
    )

    # The turn the user opened the conversation with — the turn the agent is answering when it
    # presents the gate, and therefore the turn whose submitter becomes the gate's addressee.
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    presenting_turn_id = uuid5(NAMESPACE_URL, "lane-d4:optionb:presenting-turn")
    captured = await persist_user_turn(
        conn,
        artifacts=artifacts,
        workspace_id=workspace_id,
        brand_id=fixture.discovery_fixture.brand_id,
        product_id=product_id,
        project_id=project_id,
        turn_id=presenting_turn_id,
        message="Please research both of those accounts properly.",
    )
    await insert_submission(
        conn,
        turn_id=presenting_turn_id,
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"wsm_d4_optionb_{workspace_id}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key="optionb-opening-turn",
    )
    if create_turn_row:
        # The worker's half of that same turn identity: in production the fleet worker creates the
        # ``agent_turn`` row before it runs the graph, so by the time the agent presents a gate the
        # row the gate's presenting-turn FK needs already exists.
        manifest = await artifacts.persist_body(
            workspace_id=workspace_id,
            data=json.dumps({"resources": []}).encode(),
            media_type="application/json",
        )
        execution_id = uuid5(NAMESPACE_URL, "lane-d4:optionb:execution")
        await conn.execute(
            text(
                "INSERT INTO execution "
                "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                " pin_manifest_hash) "
                "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
            ),
            {
                "id": execution_id,
                "workspace": workspace_id,
                "project": project_id,
                "hash": "0" * 64,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO agent_turn "
                "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                " workspace_root_id, profile_name, profile_version, profile_sha256, "
                " resource_manifest_key, resource_manifest_artifact_sha256, "
                " resource_manifest_sha256, retention_class, requested_at, "
                " submitted_by_user_id, submitted_via_membership_id) "
                "VALUES (:id, :execution, :workspace, :project, :thread, :actor_id, 'head_of_abm', "
                " 'root-optionb', 'head-of-abm', 'v23', :sha, :key, :sha256, :sha256, 'test', "
                " :requested_at, :user, :membership)"
            ),
            {
                "id": presenting_turn_id,
                "execution": execution_id,
                "workspace": workspace_id,
                "project": project_id,
                "thread": thread_id,
                "actor_id": USER_ID,
                "sha": "0" * 64,
                "key": manifest.artifact_key,
                "sha256": manifest.sha256,
                "requested_at": NOW_UTC,
                "user": USER_ID,
                "membership": f"wsm_d4_optionb_{workspace_id}",
            },
        )

    # The agent's draft — a DRAFT directive over *both* accounts. Nothing is confirmed yet.
    directive_registry = ToolRegistry()
    for tool in build_research_directive_tools(
        memory_write_factory=lambda _conn: _DisabledMemory(),
        conn_factory=conn_factory,
    ):
        directive_registry.register(tool, make_default=tool.version == "2")
    body = ResearchDirectiveBody(
        account_scope=ResearchAccountScope(
            explicit_account_ids=(fixture.selected_account_id, second_account_id)
        ),
        field_keys=(_PAIN, _MOVES, _HIRING),
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
        committee_plan=ResearchCommitteePlan(
            functions=("Operations",),
            levels=("Director",),
            personas=("champion",),
            candidate_cap=4,
        ),
        source_policy=ResearchSourcePolicy(
            allowed_source_keys=("exa_deep", "sumble_jobs", "sumble_people"),
            preferred_source_keys=("exa_deep",),
        ),
        privacy_policy=ResearchPrivacyPolicy(
            contact_profiling_allowed=False,
            contact_reveals_allowed=False,
        ),
        effort_policy=ResearchEffortPolicy(
            tier="high",
            max_depth=2,
            max_fanout=6,
            budget_cap_cents=_PER_ACCOUNT_CAP,
            budget_envelope_ref="budget:lane-d4-optionb",
            recursion_policy_ref="recursion:lane-d4-optionb",
            freshness_policy_ref="freshness:lane-d4-optionb",
        ),
    )
    draft_operation = new_operation_id()
    drafted = await invoke_tool(
        directive_registry,
        "draft_account_research_directive",
        {
            "project_id": project_id,
            "product_id": product_id,
            "icp_key": fixture.deep_icp_key,
            "icp_version": fixture.deep_icp_version,
            "body": body.model_dump(mode="json"),
            "user_instruction": "Research both accounts against the confirmed direction.",
            "source_turn_ref": derive_turn_action_ref(presenting_turn_id),
        },
        ToolContext(
            workspace_id=workspace_id,
            actor="agent",
            conn_factory=conn_factory,
            operation_id=draft_operation,
        ),
        idempotency_ttl_s=60,
    )
    # M8D launches are action-scoped, not phase-scoped: the outer run need not sit in DEEP.
    await conn.execute(
        text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
        {"project_run_id": fixture.project_run_id},
    )
    return _Scenario(
        fixture=fixture,
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        thread_id=thread_id,
        presenting_turn_id=presenting_turn_id,
        account_ids=(fixture.selected_account_id, second_account_id),
        directive_id=ResearchDirectiveId(draft_operation),
        directive_body=body.model_dump(mode="json"),
        directive_sha256=str(drafted.references["canonical_json_sha256"]),
        conn_factory=conn_factory,
        storage=storage,
    )


def _gate_tool_registry(conn_factory: Any) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        OpenDirectiveConfirmationGateTool(conn_factory=conn_factory), make_default=True
    )
    return registry


def _app(conn: AsyncConnection, scenario: _Scenario) -> Any:
    cf = scenario.conn_factory
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
    for tool in build_research_directive_tools(
        memory_write_factory=lambda _conn: _DisabledMemory(),
        conn_factory=cf,
    ):
        registry.register(tool, make_default=tool.version == "2")

    def resolve(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            principal_kind="human",
            user_id=USER_ID,
            membership_id=f"wsm_d4_optionb_{workspace_id}",
            workspace_id=workspace_id,
            role_key="owner",
            permissions=CHAT_PERMISSIONS,
        )

    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=_settings(),
            conn_factory=cf,
        ),
        settings=_settings(),
        conn_factory=cf,
        manage_db_lifespan=False,
        ingestion_storage=scenario.storage,
        chat_principal_resolver=resolve,
    )


async def _open_gate(conn: AsyncConnection, scenario: _Scenario) -> Any:
    """The agent's own act: present the gate through the governed tool."""

    result = await invoke_tool(
        _gate_tool_registry(scenario.conn_factory),
        "open_directive_confirmation_gate",
        {
            "project_run_id": str(scenario.fixture.project_run_id),
            "research_directive_id": str(scenario.directive_id),
            "account_entity_ids": [str(value) for value in scenario.account_ids],
            "source_turn_ref": derive_turn_action_ref(scenario.presenting_turn_id),
        },
        ToolContext(
            workspace_id=scenario.workspace_id,
            actor="agent",
            conn_factory=scenario.conn_factory,
            operation_id=new_operation_id(),
        ),
        idempotency_ttl_s=60,
    )
    return result


# --- the acceptance ------------------------------------------------------------------------


def test_the_option_b_kickoff_flow_end_to_end(tmp_path: Path) -> None:
    """Draft → gate → approve → confirm → launch, with one number and one receipt throughout."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path)

            # (1)+(2) The agent presents the gate. The amount on it is the server's, computed by
            # the launcher's own Σ — two accounts × the per-account cap.
            opened = await _open_gate(conn, scenario)
            gate_id = UUID(str(opened.references["gate_id"]))
            assert opened.references["created"] is True
            assert opened.references["gate_kind"] == "directive_confirmation"
            assert opened.references["account_count"] == 2
            assert opened.references["max_spend_cents"] == money_text(2 * _PER_ACCOUNT_CAP)
            assert opened.references["expected_subject_sha256"] == scenario.directive_sha256
            assert opened.references["gate_ref"] == gate_ref(gate_id)
            # Derived, never proposed: the addressee is the human who submitted the turn.
            assert opened.references["addressee_user_id"] == USER_ID

            view = await get_gate(conn, workspace_id=scenario.workspace_id, gate_id=gate_id)
            assert view is not None
            assert view.is_open is True

            # (3) The user's structured Approve. A visible human turn, and the confirmation runs
            # with authority the server derived from it.
            app = _app(conn, scenario)
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                response = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{scenario.thread_id}/turns",
                    json={
                        "gate_response": {
                            "gate_id": str(gate_id),
                            "decision": "approved",
                            "expected_subject_sha256": scenario.directive_sha256,
                            "expected_estimated_cost_cents": money_text(view.gate.max_spend_cents),
                        }
                    },
                    headers={
                        "X-Workspace-Id": scenario.workspace_id,
                        "Idempotency-Key": "optionb-approve",
                    },
                )
            assert response.status_code == 202, response.text
            confirming_turn_id = UUID(response.json()["data"]["turn_id"])
            confirming_ref = derive_turn_action_ref(confirming_turn_id)

            directive_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT status, confirmed_by, confirming_turn_ref "
                            "FROM account_research_directive WHERE directive_id = :id"
                        ),
                        {"id": scenario.directive_id},
                    )
                )
                .mappings()
                .one()
            )
            assert directive_row["status"] == "confirmed"
            # The AC's exact wording: the receipt equals the ambient values, not anything a client
            # or a model chose.
            assert directive_row["confirmed_by"] == USER_ID
            assert directive_row["confirming_turn_ref"] == confirming_ref

            # One source, across the draft→confirmed boundary: the number written on the gate
            # while the directive was a *draft* is the number the launcher's own computation
            # produces over the *confirmed* directive. Recomputed here through the exact function
            # the launcher calls, with the launcher's own (non-draft) strictness.
            estimate = await compute_account_research_estimate(
                conn,
                workspace_id=scenario.workspace_id,
                project_run_id=ProjectRunId(UUID(str(scenario.fixture.project_run_id))),
                directive_id=scenario.directive_id,
                account_ids=tuple(EntityId(value) for value in scenario.account_ids),
            )
            assert view.gate.max_spend_cents == estimate.total_cents

            answered = await get_gate(conn, workspace_id=scenario.workspace_id, gate_id=gate_id)
            assert answered is not None
            assert answered.answer is not None
            assert answered.answer.decision == "approved"
            assert answered.answer.turn_id == confirming_turn_id
            assert answered.answer.action_ref == confirming_ref

            # The gate receipt is now spendable, and proves *which* gate was answered.
            proved = await resolve_gate_answer_action(
                confirming_ref,
                workspace_id=scenario.workspace_id,
                actor_id=USER_ID,
                gate_id=gate_id,
                conn_factory=scenario.conn_factory,
            )
            assert proved.gate_id == gate_id
            assert proved.decision == "approved"

            # (4) The deepagent launches with that turn-derived action ref.
            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            request = AccountResearchFleetLaunchRequest(
                workspace_id=scenario.workspace_id,
                project_run_id=UUID(str(scenario.fixture.project_run_id)),
                research_directive_id=UUID(str(scenario.directive_id)),
                account_entity_ids=tuple(UUID(str(value)) for value in scenario.account_ids),
                approved_budget_cap_cents=view.gate.max_spend_cents,
                # The gate's number, verified by exact match inside the launcher.
                expected_estimated_cost_cents=view.gate.max_spend_cents,
                concurrency_limit=4,
                supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
            )
            projection = await launcher.launch(
                request,
                actor=USER_ID,
                source_action_ref=confirming_ref,
                source_operation_id=uuid4(),
            )
            assert projection.selected_accounts == 2

            fleet_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_action_ref FROM entity_research_account_fleet "
                            "WHERE research_run_id = :run_id"
                        ),
                        {"run_id": projection.research_run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert fleet_row["source_action_ref"] == confirming_ref

            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT lifecycle_json FROM entity_research_run "
                            "WHERE research_run_id = :run_id"
                        ),
                        {"run_id": projection.research_run_id},
                    )
                )
                .mappings()
                .one()
            )
            selection = stored["lifecycle_json"]["selection"]
            # "``approval_refs`` carries both refs": under Option B the launching action and the
            # directive's confirming turn are deliberately the *same* act — the user's structured
            # approval both confirms the direction and is the turn the agent launches from — so the
            # pair resolves to one receipt rather than being padded into a false pair.
            assert tuple(selection["approval_refs"]) == (confirming_ref,)
            assert directive_row["confirming_turn_ref"] == confirming_ref
            assert fleet_row["source_action_ref"] == confirming_ref
            assert selection["confirmed_by"] == USER_ID

            # (6) The chain is legible as one join, with no reconstruction.
            gates = await thread_gates(
                workspace_id=scenario.workspace_id,
                thread_id=scenario.thread_id,
                conn_factory=scenario.conn_factory,
            )
            assert len(gates) == 1
            assert gates[0].is_open is False
            assert gates[0].max_spend_cents == estimate.total_cents
            assert gates[0].answer is not None
            assert gates[0].answer.turn_id == str(confirming_turn_id)
            assert [item.research_run_id for item in gates[0].launches] == [
                str(projection.research_run_id)
            ]
            assert gates[0].launches[0].approval_refs == (confirming_ref,)
            assert gates[0].launches[0].source_action_ref == confirming_ref

    run_async(scenario_body())


def test_the_gate_amount_is_the_number_the_launcher_verifies(tmp_path: Path) -> None:
    """(5) One source: an amount that is not the gate's is refused by the launcher's exact match."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path)
            opened = await _open_gate(conn, scenario)
            gate_id = UUID(str(opened.references["gate_id"]))
            gate_amount = Decimal(str(opened.references["max_spend_cents"]))

            app = _app(conn, scenario)
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                response = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{scenario.thread_id}/turns",
                    json={
                        "gate_response": {
                            "gate_id": str(gate_id),
                            "decision": "approved",
                            "expected_subject_sha256": scenario.directive_sha256,
                            "expected_estimated_cost_cents": money_text(gate_amount),
                        }
                    },
                    headers={
                        "X-Workspace-Id": scenario.workspace_id,
                        "Idempotency-Key": "optionb-amount-approve",
                    },
                )
            assert response.status_code == 202, response.text
            confirming_ref = derive_turn_action_ref(UUID(response.json()["data"]["turn_id"]))

            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )

            async def launch(expected: Decimal) -> Any:
                return await launcher.launch(
                    AccountResearchFleetLaunchRequest(
                        workspace_id=scenario.workspace_id,
                        project_run_id=UUID(str(scenario.fixture.project_run_id)),
                        research_directive_id=UUID(str(scenario.directive_id)),
                        account_entity_ids=tuple(
                            UUID(str(value)) for value in scenario.account_ids
                        ),
                        approved_budget_cap_cents=gate_amount,
                        expected_estimated_cost_cents=expected,
                        concurrency_limit=4,
                        supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
                    ),
                    actor=USER_ID,
                    source_action_ref=confirming_ref,
                    source_operation_id=uuid4(),
                )

            # An amount one cent away from the gate's cannot launch — even though the caller says
            # it approved that amount. There is exactly one authoritative number, and it is the
            # one the gate stored.
            with pytest.raises(AccountResearchFleetLaunchError, match="approved estimate differs"):
                async with conn.begin_nested():
                    await launch(gate_amount - Decimal(1))

            # The gate's own number launches.
            projection = await launch(gate_amount)
            assert projection.selected_accounts == 2

    run_async(scenario_body())


def test_a_gate_cannot_be_presented_for_an_account_without_a_human_tier_checkpoint(
    tmp_path: Path,
) -> None:
    """The gate's precondition is the launcher's: an unapproved account earns no gate at all."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path)
            stranger_id = await insert_account_entity(
                conn,
                canonical_name="Unapproved Health Partners",
                primary_domain="unapproved.example",
                workspace_id=scenario.workspace_id,
            )
            with pytest.raises(PreconditionFailed) as caught:
                await invoke_tool(
                    _gate_tool_registry(scenario.conn_factory),
                    "open_directive_confirmation_gate",
                    {
                        "project_run_id": str(scenario.fixture.project_run_id),
                        "research_directive_id": str(scenario.directive_id),
                        "account_entity_ids": [str(stranger_id)],
                        "source_turn_ref": derive_turn_action_ref(scenario.presenting_turn_id),
                    },
                    ToolContext(
                        workspace_id=scenario.workspace_id,
                        actor="agent",
                        conn_factory=scenario.conn_factory,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=60,
                )
            assert caught.value.failures[0].reason_code in {
                "account_tier_checkpoint_missing",
                "research_directive_invalid",
            }
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_gate WHERE workspace_id = :ws"),
                    {"ws": scenario.workspace_id},
                )
            ).scalar_one() == 0

    run_async(scenario_body())


def test_an_agent_cannot_address_a_gate_to_a_turn_it_did_not_answer(tmp_path: Path) -> None:
    """The addressee is derived from a durable submission; a made-up turn ref proves nobody."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path)
            with pytest.raises(PreconditionFailed) as caught:
                await invoke_tool(
                    _gate_tool_registry(scenario.conn_factory),
                    "open_directive_confirmation_gate",
                    {
                        "project_run_id": str(scenario.fixture.project_run_id),
                        "research_directive_id": str(scenario.directive_id),
                        "account_entity_ids": [str(value) for value in scenario.account_ids],
                        "source_turn_ref": f"turn-action:{uuid4()}",
                    },
                    ToolContext(
                        workspace_id=scenario.workspace_id,
                        actor="agent",
                        conn_factory=scenario.conn_factory,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=60,
                )
            assert caught.value.failures[0].reason_code == "gate_turn_not_found"

    run_async(scenario_body())


def test_presenting_the_same_gate_twice_in_one_turn_is_one_gate(tmp_path: Path) -> None:
    """A retried plan step re-presents; it does not ask the same person twice."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path)
            first = await _open_gate(conn, scenario)
            second = await _open_gate(conn, scenario)
            assert first.references["gate_id"] == second.references["gate_id"]
            assert first.references["created"] is True
            assert second.references["created"] is False
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_gate WHERE workspace_id = :ws"),
                    {"ws": scenario.workspace_id},
                )
            ).scalar_one() == 1

    run_async(scenario_body())
