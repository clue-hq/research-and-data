"""FI Lane B ⇄ Lane D — **the join acceptance**: a real authenticated user drives D4 end to end.

Slices D1–D4 were built against an injected test ``RequestPrincipal`` by design (Lane B contract
§9 permits exactly that while B2/B3 are in flight). This module is the gate that says the
placeholder is gone: every identity in the path below is a real ``platform_user.user_id`` and a
real ``workspace_membership.membership_id``, provisioned through ``clue_auth``'s own CRUD, and the
app is built with Lane B's authenticated principal service — the same
``Authenticator → IdentityResolver → Authorizer`` chain production runs, with only the *provider
adapter* swapped for Lane B's own ``LocalFixtureAuthenticator`` (contract §4: "test and local
development adapters implement the same contract", and they still resolve a real internal
user/membership fixture from Postgres). No route, tool, gate, or receipt in this file is told who
anybody is by a test.

The positive path is charter D4's Option-B kickoff, reached the way a browser reaches it:

  authenticate as U → create a thread → POST a turn → the agent opens the directive-confirmation
  gate on that turn → U POSTs the structured ``gate_response`` → the server invokes the human-only
  ``confirm_account_research_directive@2`` outside the model surface → the deepagent launches with
  the turn-derived receipt.

and every durable identity it leaves behind is asserted to be U's real one: the thread's creator
*and* membership, the submission's submitter *and* membership, the gate's addressee, the answer's
answerer, the directive's ``confirmed_by``, and the launch's ``approval_refs`` — which are then
*resolved back* to U through the D1 receipt resolver rather than merely string-compared.

The three adversarial cases are the contract's §10 acceptance rows 4 and 10:

* **V — a second real member of the same workspace**, with a role that carries ``gate.respond``,
  may open the surface and submit turns of their own, and still cannot answer U's gate. Authority
  to participate is not authority to approve.
* **X — a real authenticated user with no membership in W** — is refused ``WORKSPACE_FORBIDDEN``
  before any write. The test counts rows on both sides of the refusal, because "denied" that still
  captured an artifact is not denied.
* and a **workspace-selector swap** — U, authenticated perfectly well, naming a workspace they are
  not a member of — is the same refusal, which is ruling 6 stated as a test: a selector is never a
  credential.

The heavy domain fixture (two tier-checkpointed accounts, one drafted directive over both) is
imported from the D4 acceptance rather than copied. That module is the owner of "what the
conversation is about"; this one is the owner of "who is having it", and duplicating 200 lines of
account seeding would only create two things to keep in step.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchRequest,
)
from clue_api.agent_gate import get_gate, money_text
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_wiring import LOCAL_SUBJECT_HEADER, WORKSPACE_HEADER, build_principal_service
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.thread_wiring import register_thread_tools
from clue_api.turn_action import (
    TurnActionUnresolvable,
    derive_turn_action_ref,
    resolve_gate_answer_action,
)
from clue_auth import (
    create_platform_user,
    create_workspace_member,
    get_workspace_membership,
    link_auth_identity,
)
from clue_config import Settings, load_settings
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests.api.test_lane_d4_option_b_acceptance_db import (  # the shared domain fixture
    USER_ID as OWNER_USER_ID,
)
from tests.api.test_lane_d4_option_b_acceptance_db import (
    _DisabledMemory,
    _MemoryStorage,
    _open_gate,
    _same_connection,
    _seed_two_account_conversation,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

#: The provider key Lane B's own local/test authenticator files its subjects under. It
#: authenticates nobody in production — ``build_principal_service`` refuses to construct it when
#: ``auth_environment == 'production'`` — but it resolves through the *real* ``auth_identity`` →
#: ``platform_user`` → ``workspace_membership`` chain, which is the point.
LOCAL_PROVIDER_KEY = "local_fixture"

#: U is the workspace owner the domain fixture already provisioned (a real ``platform_user`` with a
#: real active membership). This module gives that identity something it did not have: a way to
#: *authenticate*.
U_SUBJECT = "join-acceptance:owner"
#: V — a second real member of the same workspace. ``operator`` is deliberate: the role carries
#: ``gate.respond``, so V's refusal below cannot be mistaken for a missing permission.
V_USER_ID = "usr_join_second_member"
V_SUBJECT = "join-acceptance:second-member"
#: X — a real, authenticated, provisioned Clue user who is a member of no workspace at all.
X_USER_ID = "usr_join_outsider"
X_SUBJECT = "join-acceptance:outsider"

NOW_UTC = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def require_join_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_join_db")


def _settings(**kwargs: object) -> Settings:
    """The authenticated-principal deployment shape, not the local-header one.

    ``projections_auth_mode='authenticated_principal'`` is the half of the pair that says "the
    development principal is not in play here"; ``projections_main`` refuses the contradictory
    combination at startup, and ``install_chat_surface`` refuses a process handed both identity
    sources at composition.
    """

    return load_settings(
        _env_file=None,
        chat_enabled=True,
        auth_enabled=True,
        auth_environment="test",
        auth_mode="local_fixture",
        projections_auth_mode="authenticated_principal",
        **kwargs,
    )


class _Identity:
    def __init__(self, *, user_id: str, membership_id: str | None, subject: str) -> None:
        self.user_id = user_id
        self.membership_id = membership_id
        self.subject = subject

    def headers(self, workspace_id: str, **extra: str) -> dict[str, str]:
        """What a browser session actually sends: a session proof and a workspace *selection*.

        No user id, no membership id, no action reference. Everything durable in this file is
        derived server-side from these two values — which is contract ruling 7 as a test fixture.
        """

        return {
            LOCAL_SUBJECT_HEADER: self.subject,
            WORKSPACE_HEADER: workspace_id,
            **extra,
        }


async def _provision_identities(
    conn: AsyncConnection, *, workspace_id: str
) -> tuple[_Identity, _Identity, _Identity]:
    """Provision U, V, and X through ``clue_auth``, and give each one a way to authenticate.

    Every write here goes through Lane B's own CRUD. V in particular is created through the
    **governed** path — ``create_workspace_member`` with U's owner membership as the acting
    administrator — so this fixture exercises the same permission check a real invitation
    acceptance would, rather than inserting a membership row behind it.
    """

    owner_membership = await get_workspace_membership(
        conn, workspace_id=workspace_id, user_id=OWNER_USER_ID
    )
    assert owner_membership is not None, "the domain fixture must have provisioned its owner"
    await link_auth_identity(
        conn,
        user_id=OWNER_USER_ID,
        provider_key=LOCAL_PROVIDER_KEY,
        provider_subject=U_SUBJECT,
    )
    owner = _Identity(
        user_id=OWNER_USER_ID,
        membership_id=owner_membership.membership_id,
        subject=U_SUBJECT,
    )

    await create_platform_user(conn, user_id=V_USER_ID, display_name="Second member")
    await link_auth_identity(
        conn, user_id=V_USER_ID, provider_key=LOCAL_PROVIDER_KEY, provider_subject=V_SUBJECT
    )
    second_membership = await create_workspace_member(
        conn,
        acting_membership_id=owner_membership.membership_id,
        workspace_id=workspace_id,
        user_id=V_USER_ID,
        role_key="operator",
        status="active",
    )
    second = _Identity(
        user_id=V_USER_ID,
        membership_id=second_membership.membership_id,
        subject=V_SUBJECT,
    )

    # X exists and can authenticate. That is all X has: no membership anywhere.
    await create_platform_user(conn, user_id=X_USER_ID, display_name="Outsider")
    await link_auth_identity(
        conn, user_id=X_USER_ID, provider_key=LOCAL_PROVIDER_KEY, provider_subject=X_SUBJECT
    )
    outsider = _Identity(user_id=X_USER_ID, membership_id=None, subject=X_SUBJECT)
    return owner, second, outsider


def _app(conn: AsyncConnection, scenario: Any) -> Any:
    """The real projections app, wired with Lane B's real principal service.

    Note what is *absent*: ``chat_principal_resolver``. The chat surface takes its identity from
    ``auth_service`` and from nothing else — and supplying both would now be refused at
    composition rather than silently resolved by dependency-override ordering.
    """

    cf = scenario.conn_factory
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
    for tool in build_research_directive_tools(
        memory_write_factory=lambda _conn: _DisabledMemory(),
        conn_factory=cf,
    ):
        registry.register(tool, make_default=tool.version == "2")

    settings = _settings()
    service, closer = build_principal_service(settings=settings, conn_factory=cf)
    assert closer is None, "the local fixture adapter owns no provider connection to close"
    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=settings,
            conn_factory=cf,
        ),
        settings=settings,
        conn_factory=cf,
        manage_db_lifespan=False,
        ingestion_storage=scenario.storage,
        auth_service=service,
    )


@asynccontextmanager
async def _client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client


async def _worker_turn_row(
    conn: AsyncConnection,
    scenario: Any,
    *,
    thread_id: str,
    turn_id: UUID,
    actor_id: str,
    membership_id: str,
    label: str,
) -> None:
    """Write the *worker's* half of a turn identity for a turn the route already accepted.

    The HTTP route deliberately records only what it can prove — the user's bytes, the capture, and
    the submitter — and enqueues; the fleet worker creates the ``agent_turn`` row when it claims
    the work. ``agent_gate.turn_id`` foreign-keys that row, so a gate presented on a just-submitted
    turn needs it to exist. This is the worker's write, performed inline because this module runs
    no worker — the identity it carries is still U's, taken from the same principal the route
    resolved.
    """

    artifacts = DurableAgentArtifactStore(
        storage=scenario.storage, conn_factory=scenario.conn_factory
    )
    manifest = await artifacts.persist_body(
        workspace_id=scenario.workspace_id,
        data=b'{"resources": []}',
        media_type="application/json",
    )
    execution_id = uuid5(NAMESPACE_URL, f"lane-bd-join:execution:{label}")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "workspace": scenario.workspace_id,
            "project": scenario.project_id,
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
            " :root, 'head-of-abm', 'v23', :sha, :key, :sha256, :sha256, 'test', "
            " :requested_at, :user, :membership)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": scenario.workspace_id,
            "project": scenario.project_id,
            "thread": thread_id,
            "actor_id": actor_id,
            "root": f"root-join-{label}",
            "sha": "0" * 64,
            "key": manifest.artifact_key,
            "sha256": manifest.sha256,
            "requested_at": NOW_UTC,
            "user": actor_id,
            "membership": membership_id,
        },
    )


async def _submission_count(conn: AsyncConnection, *, workspace_id: str) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM agent_turn_submission WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
        ).scalar_one()
    )


# --- the acceptance ---------------------------------------------------------------------------


def test_a_real_authenticated_user_drives_the_whole_d4_flow(tmp_path: Path) -> None:
    """Session → thread → turn → gate → confirming turn → confirm → launch, all on real ids."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            owner, _second, _outsider = await _provision_identities(
                conn, workspace_id=scenario.workspace_id
            )
            app = _app(conn, scenario)

            async with _client(app) as client:
                # (1) A thread, created by an authenticated session and nothing else.
                created = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads",
                    json={"title": "Kickoff"},
                    headers=owner.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "join-thread"}
                    ),
                )
                assert created.status_code == 201, created.text
                thread_id = created.json()["data"]["id"]

                # (2) The opening turn — the turn the agent will be answering when it presents the
                #     gate, and therefore the turn whose submitter becomes the gate's addressee.
                opening = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{thread_id}/turns",
                    json={"message": "Please research both of those accounts properly."},
                    headers=owner.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "join-opening-turn"}
                    ),
                )
                assert opening.status_code == 202, opening.text
                opening_turn_id = UUID(opening.json()["data"]["turn_id"])

            # The thread's durable owner is U's *internal* pair — both halves, and the membership
            # half is a composite foreign key, so it is a membership of this workspace or nothing.
            thread_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT created_by_user_id, created_via_membership_id, workspace_id "
                            "FROM agent_thread WHERE id = :id"
                        ),
                        {"id": thread_id},
                    )
                )
                .mappings()
                .one()
            )
            assert thread_row["created_by_user_id"] == owner.user_id
            assert thread_row["created_via_membership_id"] == owner.membership_id
            assert thread_row["workspace_id"] == scenario.workspace_id

            submission_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT submitted_by_user_id, submitted_via_membership_id "
                            "FROM agent_turn_submission WHERE turn_id = :turn_id"
                        ),
                        {"turn_id": opening_turn_id},
                    )
                )
                .mappings()
                .one()
            )
            assert submission_row["submitted_by_user_id"] == owner.user_id
            assert submission_row["submitted_via_membership_id"] == owner.membership_id

            # The worker's half of that turn, so the gate has a turn row to anchor to.
            assert owner.membership_id is not None
            await _worker_turn_row(
                conn,
                scenario,
                thread_id=thread_id,
                turn_id=opening_turn_id,
                actor_id=owner.user_id,
                membership_id=owner.membership_id,
                label="opening",
            )

            # (3) The agent presents the gate on that turn. The addressee is derived from the
            #     durable submission — the model cannot name one.
            opened = await _open_gate(
                conn,
                _JoinGateScenario(scenario, thread_id=thread_id, turn_id=opening_turn_id),
            )
            gate_id = UUID(str(opened.references["gate_id"]))
            assert opened.references["addressee_user_id"] == owner.user_id

            view = await get_gate(conn, workspace_id=scenario.workspace_id, gate_id=gate_id)
            assert view is not None and view.is_open is True

            # (4) U's structured Approve: a visible human turn that also closes the gate and runs
            #     the human-only confirmation with server-derived authority.
            async with _client(app) as client:
                approved = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{thread_id}/turns",
                    json={
                        "gate_response": {
                            "gate_id": str(gate_id),
                            "decision": "approved",
                            "expected_subject_sha256": scenario.directive_sha256,
                            "expected_estimated_cost_cents": money_text(view.gate.max_spend_cents),
                        }
                    },
                    headers=owner.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "join-approve"}
                    ),
                )
            assert approved.status_code == 202, approved.text
            confirming_turn_id = UUID(approved.json()["data"]["turn_id"])
            confirming_ref = derive_turn_action_ref(confirming_turn_id)

            answered = await get_gate(conn, workspace_id=scenario.workspace_id, gate_id=gate_id)
            assert answered is not None and answered.answer is not None
            assert answered.answer.decision == "approved"
            assert answered.answer.answered_by_user_id == owner.user_id
            assert answered.answer.action_ref == confirming_ref

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
            # The whole point of the join: this value came from Lane B's authorizer, through the
            # ambient ToolContext, into a durable row — never from a request body.
            assert directive_row["confirmed_by"] == owner.user_id
            assert directive_row["confirming_turn_ref"] == confirming_ref

            # (5) The launch, carrying that receipt.
            def connection() -> AbstractAsyncContextManager[AsyncConnection]:
                return _same_connection(conn)

            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )
            projection = await launcher.launch(
                AccountResearchFleetLaunchRequest(
                    workspace_id=scenario.workspace_id,
                    project_run_id=UUID(str(scenario.fixture.project_run_id)),
                    research_directive_id=UUID(str(scenario.directive_id)),
                    account_entity_ids=tuple(UUID(str(value)) for value in scenario.account_ids),
                    approved_budget_cap_cents=view.gate.max_spend_cents,
                    expected_estimated_cost_cents=view.gate.max_spend_cents,
                    concurrency_limit=4,
                    supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
                ),
                actor=owner.user_id,
                source_action_ref=confirming_ref,
                source_operation_id=uuid4(),
            )
            assert projection.selected_accounts == 2

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
            assert tuple(selection["approval_refs"]) == (confirming_ref,)
            assert selection["confirmed_by"] == owner.user_id

            # And the refs are not merely equal strings: each one *resolves*, through the D1
            # receipt resolver, to this authenticated user and this gate. A receipt that cannot be
            # re-proved is decoration.
            for ref in selection["approval_refs"]:
                proved = await resolve_gate_answer_action(
                    ref,
                    workspace_id=scenario.workspace_id,
                    actor_id=owner.user_id,
                    gate_id=gate_id,
                    conn_factory=scenario.conn_factory,
                )
                assert proved.decision == "approved"
                assert proved.answered_by_user_id == owner.user_id
                assert proved.action.submitted_by_user_id == owner.user_id
                assert proved.action.submitted_via_membership_id == owner.membership_id

    run_async(scenario_body())


def test_a_second_member_of_the_same_workspace_cannot_answer_that_gate(tmp_path: Path) -> None:
    """Contract §10.4. V is real, authenticated, a member, and holds ``gate.respond``."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            owner, second, _outsider = await _provision_identities(
                conn, workspace_id=scenario.workspace_id
            )
            app = _app(conn, scenario)

            async with _client(app) as client:
                created = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads",
                    json={"title": "Kickoff"},
                    headers=owner.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "bystander-thread"}
                    ),
                )
                assert created.status_code == 201, created.text
                thread_id = created.json()["data"]["id"]
                opening = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{thread_id}/turns",
                    json={"message": "Please research both of those accounts properly."},
                    headers=owner.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "bystander-opening"}
                    ),
                )
                assert opening.status_code == 202, opening.text
                opening_turn_id = UUID(opening.json()["data"]["turn_id"])

            assert owner.membership_id is not None
            await _worker_turn_row(
                conn,
                scenario,
                thread_id=thread_id,
                turn_id=opening_turn_id,
                actor_id=owner.user_id,
                membership_id=owner.membership_id,
                label="bystander",
            )
            opened = await _open_gate(
                conn,
                _JoinGateScenario(scenario, thread_id=thread_id, turn_id=opening_turn_id),
            )
            gate_id = UUID(str(opened.references["gate_id"]))
            view = await get_gate(conn, workspace_id=scenario.workspace_id, gate_id=gate_id)
            assert view is not None

            async with _client(app) as client:
                # V is a legitimate participant: an ordinary turn of their own is accepted, and its
                # durable submitter is V's own pair. This is what makes the refusal below specific.
                mine = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{thread_id}/turns",
                    json={"message": "Adding some context from my side."},
                    headers=second.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "bystander-own-turn"}
                    ),
                )
                assert mine.status_code == 202, mine.text

                refused = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads/{thread_id}/turns",
                    json={
                        "gate_response": {
                            "gate_id": str(gate_id),
                            "decision": "approved",
                            "expected_subject_sha256": scenario.directive_sha256,
                            "expected_estimated_cost_cents": money_text(view.gate.max_spend_cents),
                        }
                    },
                    headers=second.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "bystander-approve"}
                    ),
                )
            assert refused.status_code == 403, refused.text
            assert refused.json()["error"]["code"] == "GATE_FORBIDDEN"

            own_turn = (
                (
                    await conn.execute(
                        text(
                            "SELECT submitted_by_user_id, submitted_via_membership_id "
                            "FROM agent_turn_submission WHERE turn_id = :turn_id"
                        ),
                        {"turn_id": UUID(mine.json()["data"]["turn_id"])},
                    )
                )
                .mappings()
                .one()
            )
            assert own_turn["submitted_by_user_id"] == second.user_id
            assert own_turn["submitted_via_membership_id"] == second.membership_id

            # The gate is untouched, and the directive is still unconfirmed: a refusal that had
            # already burned the gate would be worse than none.
            after = await get_gate(conn, workspace_id=scenario.workspace_id, gate_id=gate_id)
            assert after is not None and after.answer is None and after.is_open is True
            status = (
                await conn.execute(
                    text("SELECT status FROM account_research_directive WHERE directive_id = :id"),
                    {"id": scenario.directive_id},
                )
            ).scalar_one()
            assert status == "draft"

            # And V cannot borrow the receipt either: their own turn is a turn, not a gate answer.
            with pytest.raises(TurnActionUnresolvable) as borrowed:
                await resolve_gate_answer_action(
                    derive_turn_action_ref(UUID(mine.json()["data"]["turn_id"])),
                    workspace_id=scenario.workspace_id,
                    actor_id=second.user_id,
                    gate_id=gate_id,
                    conn_factory=scenario.conn_factory,
                )
            assert borrowed.value.reason_code == "gate_answer_not_found"

    run_async(scenario_body())


def test_a_user_without_a_membership_is_refused_before_any_write(tmp_path: Path) -> None:
    """Contract §10.10. Deny by default, and deny *early* — the row count proves the ordering."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            owner, _second, outsider = await _provision_identities(
                conn, workspace_id=scenario.workspace_id
            )
            app = _app(conn, scenario)

            async with _client(app) as client:
                created = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads",
                    json={"title": "Kickoff"},
                    headers=owner.headers(
                        scenario.workspace_id, **{"Idempotency-Key": "outsider-thread"}
                    ),
                )
                assert created.status_code == 201, created.text
                thread_id = created.json()["data"]["id"]

                before = await _submission_count(conn, workspace_id=scenario.workspace_id)

                # X authenticates perfectly well. X has no membership in W.
                for path, body in (
                    (
                        f"/api/v1/projects/{scenario.project_id}/threads",
                        {"title": "Not mine"},
                    ),
                    (
                        f"/api/v1/projects/{scenario.project_id}/threads/{thread_id}/turns",
                        {"message": "Let me in."},
                    ),
                ):
                    response = await client.post(
                        path,
                        json=body,
                        headers=outsider.headers(
                            scenario.workspace_id, **{"Idempotency-Key": f"outsider-{path}"}
                        ),
                    )
                    assert response.status_code == 403, response.text
                    assert response.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"

                # Reading is refused on the same terms — a 403, never an empty business result.
                listed = await client.get(
                    f"/api/v1/projects/{scenario.project_id}/threads",
                    headers=outsider.headers(scenario.workspace_id),
                )
                assert listed.status_code == 403
                assert listed.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"

            assert await _submission_count(conn, workspace_id=scenario.workspace_id) == before
            threads = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_thread "
                        "WHERE workspace_id = :workspace_id AND created_by_user_id = :user_id"
                    ),
                    {"workspace_id": scenario.workspace_id, "user_id": outsider.user_id},
                )
            ).scalar_one()
            assert int(threads) == 0

    run_async(scenario_body())


def test_a_workspace_selector_is_not_a_credential(tmp_path: Path) -> None:
    """Contract ruling 6 / §10.10: U is authentic, and still cannot select their way elsewhere."""

    async def scenario_body() -> None:
        async with rollback_conn() as conn:
            scenario = await _seed_two_account_conversation(conn, tmp_path, create_turn_row=False)
            owner, _second, _outsider = await _provision_identities(
                conn, workspace_id=scenario.workspace_id
            )
            app = _app(conn, scenario)

            async with _client(app) as client:
                response = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads",
                    json={"title": "Elsewhere"},
                    headers=owner.headers(
                        "ws-join-not-mine", **{"Idempotency-Key": "selector-swap"}
                    ),
                )
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"

            # And the same request without any selection at all is refused, not defaulted to the
            # user's only workspace: a surface that guessed would make the selector meaningless.
            async with _client(app) as client:
                unselected = await client.post(
                    f"/api/v1/projects/{scenario.project_id}/threads",
                    json={"title": "Unselected"},
                    headers={
                        LOCAL_SUBJECT_HEADER: owner.subject,
                        "Idempotency-Key": "selector-absent",
                    },
                )
            assert unselected.status_code == 403
            assert unselected.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"

    run_async(scenario_body())


class _JoinGateScenario:
    """Re-point the shared fixture's gate helper at *this* module's thread and presenting turn.

    ``_open_gate`` reads ``thread_id``/``presenting_turn_id`` off the scenario; everything else it
    needs (workspace, directive, accounts, connection factory) is unchanged. A thin view beats
    either copying the helper or mutating a fixture another suite also owns.
    """

    def __init__(self, scenario: Any, *, thread_id: str, turn_id: UUID) -> None:
        self._scenario = scenario
        self.thread_id = thread_id
        self.presenting_turn_id = turn_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._scenario, name)
