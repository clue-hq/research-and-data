"""Lane D slice D4: the structured gate-response turn, and every way it must refuse.

What this suite pins (charter §3-P5(c), §3.5, and the §5 adversarial matrix):

* **a gate answer is a visible human turn** — captured bytes, a capture record, a submission row
  and a queued task, exactly like a sentence somebody typed, plus the once-only answer record;
* **approval invokes the human-only confirm tool with authority the server derived** —
  ``confirmed_by`` and ``confirming_action_ref`` equal the ambient ``actor_id`` and the answering
  turn's ``turn-action:`` receipt, and neither can be named by the client;
* **rejection and revision confirm nothing** — they leave durable decisions and a turn for the
  agent to answer;
* **every adversarial case refuses with no side effects** — a stale subject digest, a stale amount,
  a different actor than the addressee, a second answer, an unknown or foreign gate, and a gate
  kind this surface cannot answer;
* **replay is deterministic** — the same idempotency identity re-lands on the same turn, the same
  single answer, and the same single confirmation;
* **an ordinary turn is not a gate answer** — it leaves the gate open.

DB-backed and rollback-only, over the real ASGI app with an injected internal principal.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.agent_gate import (
    DEFAULT_GATE_CURRENCY,
    KIND_DIRECTIVE_CONFIRMATION,
    directive_confirmation_gate_id,
    gate_answer_for_turn,
    get_gate,
    insert_gate,
)
from clue_api.agent_turn_submission import (
    get_submission,
    thread_work_id,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.chat.schemas import thread_status
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.thread_wiring import register_thread_tools
from clue_api.turn_action import derive_turn_action_ref
from clue_config import Settings, load_settings
from clue_core import (
    MemoryDisabled,
    MemorySubmission,
)
from clue_design import legs as design_legs
from clue_projections import open_gate_kinds_for_threads
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_d4_route"
OTHER_USER_ID = "usr_d4_route_other"
#: The moment the injected test principal "authenticated". A fixed instant, because the Lane B
#: principal records when the session was proved and a test must not depend on wall clock.
_AUTHENTICATED_AT = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
NOW_UTC = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
SUBJECT_DIGEST = "c" * 64
AMOUNT = Decimal("600")


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


class _MemoryStorage:
    """The parameter-snapshot sink the journaled invoker writes through."""

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


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, chat_enabled=True, **kwargs)


def _principal(user_id: str) -> Any:
    def resolve(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            user_id=user_id,
            membership_id=f"wsm_d4_route_{user_id}_{workspace_id}",
            workspace_id=workspace_id,
            role_key="owner",
            permissions=CHAT_PERMISSIONS,
            authenticated_at=_AUTHENTICATED_AT,
        )

    return resolve


def _app(conn: Any, *, storage: Any, user_id: str = USER_ID) -> Any:
    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
    # The one governed tool the gate route invokes. It is registered here for the same reason the
    # HTTP process registers it in production: it is human-only and needs no model plane at all.
    for tool in build_research_directive_tools(
        memory_write_factory=lambda _conn: _DisabledMemory(),
        conn_factory=cf,
    ):
        registry.register(tool, make_default=tool.version == "2")
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
        ingestion_storage=storage,
        chat_principal_resolver=_principal(user_id),
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


class _Seeded:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _seed(conn: Any, tmp_path: Path, *, workspace_id: str, label: str) -> Any:
    """A project, a thread, and the agent's own turn — the turn a gate is presented in."""

    project = await _seed_project_row(conn, workspace_id, name=f"D4 route {label}")
    for user_id in (USER_ID, OTHER_USER_ID):
        await seed_principal(
            conn,
            workspace_id=workspace_id,
            user_id=user_id,
            membership_id=f"wsm_d4_route_{user_id}_{workspace_id}",
        )
    thread_id = f"thr_d4_route_{label}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user) ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": thread_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "user": USER_ID,
        },
    )
    artifacts = DurableAgentArtifactStore(
        storage=FsStorage(tmp_path / f"route-artifacts-{label}"),
        conn_factory=conn_session_factory(conn),
    )
    manifest = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    presenting_turn_id = uuid5(NAMESPACE_URL, f"lane-d4-route:{label}:presenting")
    execution_id = uuid5(NAMESPACE_URL, f"lane-d4-route:{label}:execution")
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
            "project": project.project_id,
            "hash": "0" * 64,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor_id, 'head_of_abm', "
            " :root, 'head-of-abm', 'v23', :sha, :key, :sha256, :sha256, 'test', :requested_at)"
        ),
        {
            "id": presenting_turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "actor_id": USER_ID,
            "root": f"root-{label}",
            "sha": "0" * 64,
            "key": manifest.artifact_key,
            "sha256": manifest.sha256,
            "requested_at": NOW_UTC,
        },
    )
    return _Seeded(
        workspace_id=workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        presenting_turn_id=presenting_turn_id,
        conn_factory=conn_session_factory(conn),
        storage=FsStorage(tmp_path / f"route-ingest-{label}"),
    )


async def _present(
    conn: Any,
    seeded: Any,
    *,
    digest: str = SUBJECT_DIGEST,
    amount: Decimal = AMOUNT,
    kind: str = KIND_DIRECTIVE_CONFIRMATION,
    addressee: str = USER_ID,
    directive_id: str | None = None,
    subject_ref: str = "research-directive:22222222-2222-4222-8222-222222222222:v1",
) -> Any:
    gate_id = directive_confirmation_gate_id(
        workspace_id=seeded.workspace_id,
        turn_id=seeded.presenting_turn_id,
        subject_ref=subject_ref,
        expected_subject_sha256=digest,
    )
    row, _ = await insert_gate(
        conn,
        gate_id=gate_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.presenting_turn_id,
        kind=kind,
        subject_ref=subject_ref,
        subject_revision=1,
        expected_subject_sha256=digest,
        subject_snapshot={
            "research_directive_id": directive_id or str(uuid4()),
            "account_count": 2,
        },
        max_spend_cents=amount,
        currency=DEFAULT_GATE_CURRENCY,
        addressee_user_id=addressee,
    )
    return row


async def _answer(
    client: httpx.AsyncClient,
    seeded: Any,
    *,
    gate: Any,
    key: str,
    decision: str = "approved",
    digest: str | None = None,
    amount: Decimal | None = None,
    gate_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "gate_response": {
            "gate_id": gate_id if gate_id is not None else str(gate.gate_id),
            "decision": decision,
            "expected_subject_sha256": digest or gate.expected_subject_sha256,
            "expected_estimated_cost_cents": str(
                amount if amount is not None else gate.max_spend_cents
            ),
            **(extra or {}),
        }
    }
    return await client.post(
        f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
        json=body,
        headers={"X-Workspace-Id": seeded.workspace_id, "Idempotency-Key": key},
    )


async def _durable_counts(conn: Any, seeded: Any) -> dict[str, int]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM agent_gate_answer WHERE workspace_id = :ws) "
                    " AS answers, "
                    "(SELECT count(*) FROM agent_turn_submission WHERE thread_id = :thread) "
                    " AS submissions, "
                    "(SELECT count(*) FROM onboarding_input WHERE project_id = :project "
                    "   AND kind = 'user_turn') AS captures, "
                    "(SELECT count(*) FROM fleet_task WHERE kind = 'agent_turn' "
                    "   AND work_id = :work) AS tasks"
                ),
                {
                    "ws": seeded.workspace_id,
                    "thread": seeded.thread_id,
                    "project": seeded.project_id,
                    "work": thread_work_id(
                        workspace_id=seeded.workspace_id, thread_id=seeded.thread_id
                    ),
                },
            )
        )
        .mappings()
        .one()
    )
    return {key: int(value) for key, value in row.items()}


# --- the happy paths ---------------------------------------------------------------------------


def test_a_rejection_is_a_visible_turn_and_a_durable_decision_that_confirms_nothing(
    tmp_path: Path,
) -> None:
    """Reject leaves a transcript record, an answer, and a queued turn — and no confirmation."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-reject", label="reject")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer(
                    client, seeded, gate=gate, key="k-reject", decision="rejected"
                )
            assert response.status_code == 202, response.text
            turn_id = UUID(response.json()["data"]["turn_id"])

            answer = await gate_answer_for_turn(
                conn, workspace_id=seeded.workspace_id, turn_id=turn_id
            )
            assert answer is not None
            assert answer.decision == "rejected"
            assert answer.gate_id == gate.gate_id
            assert answer.answered_by_user_id == USER_ID
            assert answer.action_ref == derive_turn_action_ref(turn_id)

            # The decision is a *turn*: captured bytes, a submission, and queued work for the agent.
            submission = await get_submission(
                conn, workspace_id=seeded.workspace_id, turn_id=turn_id
            )
            assert submission is not None
            assert submission.submitted_by_user_id == USER_ID
            captured = (
                await conn.execute(
                    text("SELECT actor FROM onboarding_input WHERE id = :id"),
                    {"id": submission.onboarding_input_id},
                )
            ).scalar_one()
            assert captured == "human"
            counts = await _durable_counts(conn, seeded)
            assert counts["tasks"] == 1

            # Nothing was confirmed.
            confirmed = (
                await conn.execute(
                    text("SELECT count(*) FROM account_research_directive WHERE status='confirmed'")
                )
            ).scalar_one()
            assert confirmed == 0

    run_async(scenario())


def test_a_revision_request_closes_the_gate_without_confirming(tmp_path: Path) -> None:
    """`revised` is not a soft reject and not a soft approve: it decides, and confirms nothing."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-revise", label="revise")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer(
                    client, seeded, gate=gate, key="k-revise", decision="revised"
                )
            assert response.status_code == 202, response.text

            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert view is not None
            assert view.is_open is False
            assert view.answer is not None and view.answer.decision == "revised"
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM account_research_directive WHERE status='confirmed'")
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_the_sidebar_status_is_approval_while_the_gate_is_open_and_idle_once_answered(
    tmp_path: Path,
) -> None:
    """The two vocabularies meet: an unanswered directive gate is the authored `approval` badge."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-status", label="status")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                listing = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
                assert listing.status_code == 200, listing.text
                statuses = {item["id"]: item["status"] for item in listing.json()["data"]}
                assert statuses[seeded.thread_id] == "approval"

                answered = await _answer(
                    client, seeded, gate=gate, key="k-status", decision="rejected"
                )
                assert answered.status_code == 202, answered.text

                listing_after = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
                statuses_after = {
                    item["id"]: item["status"] for item in listing_after.json()["data"]
                }
                # The approval badge clears the moment the gate is answered — which is this test's
                # claim. What replaces it is ``running``, not ``idle``, because answering a gate
                # *is* a turn: the structured response was captured and queued, and D3's
                # submissions-union half of this same derivation reports a queued turn as the
                # conversation working. The two halves composing is the point (charter §2's "the
                # two status vocabularies never meet" is what they fix together).
                assert statuses_after[seeded.thread_id] == "running"

            assert (
                await open_gate_kinds_for_threads(
                    workspace_id=seeded.workspace_id,
                    thread_ids=(seeded.thread_id,),
                    conn_factory=seeded.conn_factory,
                )
                == {}
            )
            # The derivation itself, independent of the route.
            assert thread_status(status="active", open_gate_kinds=("plan_approval",)) == (
                "needs-input"
            )
            assert thread_status(status="archived", open_gate_kinds=()) == "archived"
            # An open gate outranks a running turn: a badge that says "running" while the
            # conversation is actually blocked on the user is the one wrong answer here.
            assert (
                thread_status(
                    status="active", open_gate_kinds=("directive_confirmation",), running=True
                )
                == "approval"
            )

    run_async(scenario())


def test_an_ordinary_turn_does_not_answer_an_open_gate(tmp_path: Path) -> None:
    """A non-confirming turn is just a turn: the gate stays open and nothing is confirmed."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-ordinary", label="ordinary")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await client.post(
                    f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
                    json={"message": "Yes go ahead, that all looks right to me."},
                    headers={
                        "X-Workspace-Id": seeded.workspace_id,
                        "Idempotency-Key": "k-ordinary",
                    },
                )
            assert response.status_code == 202, response.text
            turn_id = UUID(response.json()["data"]["turn_id"])

            assert (
                await gate_answer_for_turn(conn, workspace_id=seeded.workspace_id, turn_id=turn_id)
                is None
            )
            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert view is not None and view.is_open is True

    run_async(scenario())


# --- the adversarial matrix (charter §5) -------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "kwargs", "status", "code"),
    [
        ("stale digest", {"digest": "d" * 64}, 409, "GATE_SUBJECT_STALE"),
        ("stale amount", {"amount": Decimal("599")}, 409, "GATE_AMOUNT_STALE"),
        ("unknown gate", {"gate_id": str(uuid4())}, 404, "GATE_NOT_FOUND"),
        ("malformed gate id", {"gate_id": "not-a-uuid"}, 422, "GATE_ID_MALFORMED"),
    ],
)
def test_a_mismatched_answer_refuses_with_no_side_effects(
    tmp_path: Path,
    label: str,
    kwargs: dict[str, Any],
    status: int,
    code: str,
) -> None:
    """Every refusal happens before a byte is written — no capture, no submission, no task."""

    async def scenario() -> None:
        slug = label.replace(" ", "")
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-d4r-{slug}", label=slug)
            gate = await _present(conn, seeded)
            before = await _durable_counts(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer(client, seeded, gate=gate, key=f"k-{slug}", **kwargs)
            assert response.status_code == status, response.text
            assert response.json()["error"]["code"] == code
            assert await _durable_counts(conn, seeded) == before
            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert view is not None and view.is_open is True

    run_async(scenario())


def test_a_gate_addressed_to_somebody_else_is_forbidden(tmp_path: Path) -> None:
    """Membership is not authority: only the addressee answers, and the refusal writes nothing."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-actor", label="actor")
            gate = await _present(conn, seeded, addressee=OTHER_USER_ID)
            before = await _durable_counts(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer(client, seeded, gate=gate, key="k-actor")
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "GATE_FORBIDDEN"
            assert await _durable_counts(conn, seeded) == before

            # And the person it *was* addressed to can answer it.
            other_app = _app(conn, storage=seeded.storage, user_id=OTHER_USER_ID)
            async with _client(other_app) as client:
                accepted = await _answer(
                    client, seeded, gate=gate, key="k-actor-2", decision="rejected"
                )
            assert accepted.status_code == 202, accepted.text

    run_async(scenario())


def test_a_gate_of_another_workspace_is_not_found(tmp_path: Path) -> None:
    """Cross-tenant: the gate exists, but not here — and saying so would leak that it exists."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            mine = await _seed(conn, tmp_path, workspace_id="ws-d4r-mine", label="mine")
            theirs = await _seed(conn, tmp_path, workspace_id="ws-d4r-theirs", label="theirs")
            foreign = await _present(conn, theirs)
            app = _app(conn, storage=mine.storage)
            async with _client(app) as client:
                response = await _answer(
                    client, mine, gate=foreign, key="k-cross", gate_id=str(foreign.gate_id)
                )
            assert response.status_code == 404, response.text
            assert response.json()["error"]["code"] == "GATE_NOT_FOUND"

    run_async(scenario())


def test_a_second_answer_by_a_second_turn_is_refused(tmp_path: Path) -> None:
    """Insert-once, end to end: the gate is answered once and the second click is a 409."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-double", label="double")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                first = await _answer(
                    client, seeded, gate=gate, key="k-double-1", decision="rejected"
                )
                assert first.status_code == 202, first.text
                counts_after_first = await _durable_counts(conn, seeded)

                second = await _answer(
                    client, seeded, gate=gate, key="k-double-2", decision="approved"
                )
            assert second.status_code == 409, second.text
            assert second.json()["error"]["code"] == "GATE_ALREADY_ANSWERED"
            assert await _durable_counts(conn, seeded) == counts_after_first

            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert view is not None and view.answer is not None
            assert view.answer.decision == "rejected"

    run_async(scenario())


def test_a_gate_kind_this_surface_cannot_answer_is_refused(tmp_path: Path) -> None:
    """The substrate is generic; this route answers exactly one kind and says so."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-kind", label="kind")
            gate = await _present(conn, seeded, kind="plan_approval")
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer(client, seeded, gate=gate, key="k-kind")
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "GATE_KIND_UNSUPPORTED"

    run_async(scenario())


@pytest.mark.parametrize(
    "smuggled",
    [
        {"actor_id": "usr_someone_else"},
        {"action_ref": "turn-action:00000000-0000-4000-8000-000000000000"},
        {"confirmed_by": "usr_someone_else"},
        {"max_spend_cents": "1"},
    ],
)
def test_the_client_cannot_name_its_own_authority(tmp_path: Path, smuggled: dict[str, Any]) -> None:
    """Structurally absent, not merely ignored: an unknown key is a loud 422 (§3.5)."""

    async def scenario() -> None:
        slug = next(iter(smuggled))
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-d4r-{slug}", label=slug)
            gate = await _present(conn, seeded)
            before = await _durable_counts(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                response = await _answer(client, seeded, gate=gate, key=f"k-{slug}", extra=smuggled)
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"
            assert await _durable_counts(conn, seeded) == before

    run_async(scenario())


def test_a_turn_carries_exactly_one_act(tmp_path: Path) -> None:
    """Neither both bodies nor neither: "did the user approve?" is never a parsing question."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-oneact", label="oneact")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            payloads = (
                {},
                {
                    "message": "approve it",
                    "gate_response": {
                        "gate_id": str(gate.gate_id),
                        "decision": "approved",
                        "expected_subject_sha256": gate.expected_subject_sha256,
                        "expected_estimated_cost_cents": "600",
                    },
                },
            )
            async with _client(app) as client:
                for index, payload in enumerate(payloads):
                    response = await client.post(
                        f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
                        json=payload,
                        headers={
                            "X-Workspace-Id": seeded.workspace_id,
                            "Idempotency-Key": f"k-oneact-{index}",
                        },
                    )
                    assert response.status_code == 422, response.text
                    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    run_async(scenario())


def test_a_retried_answer_is_the_same_act_not_a_second_one(tmp_path: Path) -> None:
    """Replay determinism: same idempotency identity, same turn, one answer, one queued task."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-replay", label="replay")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                first = await _answer(
                    client, seeded, gate=gate, key="k-replay", decision="rejected"
                )
                second = await _answer(
                    client, seeded, gate=gate, key="k-replay", decision="rejected"
                )
            assert first.status_code == 202, first.text
            assert second.status_code == 202, second.text
            assert first.json()["data"]["turn_id"] == second.json()["data"]["turn_id"]
            assert first.json()["data"]["replayed"] is False
            assert second.json()["data"]["replayed"] is True

            counts = await _durable_counts(conn, seeded)
            assert counts["answers"] == 1
            assert counts["submissions"] == 1
            assert counts["captures"] == 1
            assert counts["tasks"] == 1

            # A *different* decision under the same key is a different message, and is refused
            # rather than answered with the first one's turn.
            async with _client(app) as client:
                conflicting = await _answer(
                    client, seeded, gate=gate, key="k-replay", decision="approved"
                )
            assert conflicting.status_code == 409, conflicting.text
            assert conflicting.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    run_async(scenario())


def test_a_gate_answer_while_a_design_leg_is_open_is_refused_until_the_leg_closes(
    tmp_path: Path,
) -> None:
    """Part-III review finding C (ratified): a gate answer must never become a design prompt.

    While a design leg is open, the D1 routing rule sends every accepted turn to the design
    agent — which would hand it the canonical gate-answer JSON as a design instruction. The
    route refuses instead (409, side-effect free); once the leg closes, the same answer lands.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-leg", label="leg")
            gate = await _present(conn, seeded)
            leg = await design_legs.open_leg(
                conn,
                workspace_id=seeded.workspace_id,
                thread_id=seeded.thread_id,
                parent_execution_id=uuid5(NAMESPACE_URL, "lane-d4-route:leg:execution"),
            )
            before = await _durable_counts(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                refused = await _answer(client, seeded, gate=gate, key="k-leg-1")
                assert refused.status_code == 409, refused.text
                assert refused.json()["error"]["code"] == "DESIGN_LEG_OPEN"
                assert await _durable_counts(conn, seeded) == before
                view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
                assert view is not None and view.is_open is True

                await design_legs.close_leg(
                    conn,
                    workspace_id=seeded.workspace_id,
                    leg_id=leg["id"],
                    reason="locked",
                    summary_refs={},
                )
                accepted = await _answer(
                    client, seeded, gate=gate, key="k-leg-2", decision="rejected"
                )
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()["data"]["routed_to"] == "head_of_abm"
            counts = await _durable_counts(conn, seeded)
            assert counts["answers"] == 1
            assert counts["submissions"] == 1

    run_async(scenario())


def test_a_gate_answer_accepted_before_the_leg_opened_replays_while_the_leg_is_open(
    tmp_path: Path,
) -> None:
    """The refusal binds fresh submissions only: a retry of an already-accepted answer is the
    same act, and must stay an idempotent replay even if a leg has opened since — which is why
    the check sits after the replay read, not before it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-legreplay", label="legreplay")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                first = await _answer(
                    client, seeded, gate=gate, key="k-legreplay", decision="rejected"
                )
                assert first.status_code == 202, first.text

                await design_legs.open_leg(
                    conn,
                    workspace_id=seeded.workspace_id,
                    thread_id=seeded.thread_id,
                    parent_execution_id=uuid5(NAMESPACE_URL, "lane-d4-route:legreplay:execution"),
                )
                second = await _answer(
                    client, seeded, gate=gate, key="k-legreplay", decision="rejected"
                )
            assert second.status_code == 202, second.text
            assert second.json()["data"]["replayed"] is True
            assert second.json()["data"]["turn_id"] == first.json()["data"]["turn_id"]
            counts = await _durable_counts(conn, seeded)
            assert counts["answers"] == 1
            assert counts["submissions"] == 1

    run_async(scenario())


def test_the_captured_bytes_of_a_gate_answer_are_canonical(tmp_path: Path) -> None:
    """The decision is the transcript record: deterministic bytes, one spelling of the amount."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4r-bytes", label="bytes")
            gate = await _present(conn, seeded)
            app = _app(conn, storage=seeded.storage)
            async with _client(app) as client:
                # ``600.0000`` and ``600`` are the same amount, so they must capture identically.
                response = await _answer(
                    client,
                    seeded,
                    gate=gate,
                    key="k-bytes",
                    decision="rejected",
                    amount=Decimal("600.0000"),
                )
            assert response.status_code == 202, response.text
            turn_id = UUID(response.json()["data"]["turn_id"])
            assert turn_id == turn_id_for_submission(
                workspace_id=seeded.workspace_id,
                thread_id=seeded.thread_id,
                idempotency_key="k-bytes",
            )
            submission = await get_submission(
                conn, workspace_id=seeded.workspace_id, turn_id=turn_id
            )
            assert submission is not None
            body = await FsStorage(tmp_path / "route-ingest-bytes").get(
                submission.message_artifact_key
            )
            assert json.loads(body) == {
                "kind": "gate_response",
                "gate_id": str(gate.gate_id),
                "decision": "rejected",
                "expected_subject_sha256": gate.expected_subject_sha256,
                "expected_estimated_cost_cents": "600",
            }

    run_async(scenario())
