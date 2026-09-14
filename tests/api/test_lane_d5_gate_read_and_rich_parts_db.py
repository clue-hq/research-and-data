"""Lane D **D5-close**: the durable gate read, and the rich gate/task parts a turn close projects.

D5 shipped the frontend approval card and reported two blockers against a real backend: no HTTP
route served the ``thread_gates`` projection, and the ``gate`` part carried only a ref, the raw
object type and ``state="requested"`` — so a gate could be *shown* and never *answered*, because
answering echoes back the immutable subject digest and maximum spend the card never received. Both
were unimplemented already-ratified contract (charter §3.4's part floors), not new design.

What this suite pins:

* **the gates route is the answerable payload** — every ``GateView`` member on the wire under the
  path and the snake_case field names the shipped repository parses, the amount in its one
  canonical text spelling, the answer and its launches when there are any;
* **it is scoped like every other thread read** — a thread of another workspace or another project
  is *not found*, never forbidden, and a membership without ``thread.read`` is refused;
* **an open gate projects the §3.4 floor** — the *real* kind (``directive_confirmation``, never
  ``agent_gate``), the subject ref with its revision and digest, ``{amount_cents, currency}``, the
  addressee, and the permitted decisions;
* **an answered gate stays in history with its decision, actor and time**, as a completed part;
* **a ref with no durable row still renders** — the thin shape, never a stream failure;
* **a turn that launched research emits one task part**, its counts read off the run's own jobs and
  its terminal state derived from their finalization outcomes.

DB-backed and rollback-only per ``tests/api`` conventions.
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

from clue_agents import (
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentTurnOutcome,
    ArtifactRef,
    DomainObjectRef,
    FinalizeStatus,
)
from clue_api.agent_gate import (
    DECISIONS,
    DEFAULT_GATE_CURRENCY,
    GATE_OBJECT_TYPE,
    KIND_DIRECTIVE_CONFIRMATION,
    directive_confirmation_gate_id,
    insert_gate,
    insert_gate_answer,
)
from clue_api.agent_turn_submission import insert_submission, turn_id_for_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.chat.turn_events import list_turn_events
from clue_api.chat.turn_parts import PartKind, TaskState
from clue_api.chat.turn_stream import TurnStreamEmitter
from clue_api.conversation_capture import persist_user_turn
from clue_api.conversation_turns import ConversationTurnEngine
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_api.thread_wiring import register_thread_tools
from clue_api.turn_action import derive_turn_action_ref
from clue_auth import Permission
from clue_config import Settings, load_settings
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    ResearchFinalizationOutcome,
    ResearchRunKind,
    SelectedResearchSubject,
)
from clue_fleet import (
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
    launch_entity_research_run,
)
from clue_projections import research_tasks_for_action_refs, thread_gates
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import run_envelope
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_d5_gates"
_AUTHENTICATED_AT = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
NOW_UTC = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
DIGEST = "e" * 64
#: A ``numeric(20,4)`` amount whose text spelling and integer ceiling are both load-bearing below.
AMOUNT = Decimal("24000.0000")
SUBJECT_REF = "research-directive:33333333-3333-4333-8333-333333333333:v2"


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


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


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, chat_enabled=True, **kwargs)


def _principal(*, permissions: frozenset[Permission] | None = None) -> Any:
    def resolve(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            user_id=USER_ID,
            membership_id=f"wsm_d5_{USER_ID}_{workspace_id}",
            workspace_id=workspace_id,
            role_key="owner",
            permissions=CHAT_PERMISSIONS if permissions is None else permissions,
            authenticated_at=_AUTHENTICATED_AT,
        )

    return resolve


def _app(conn: Any, *, permissions: frozenset[Permission] | None = None) -> Any:
    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
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
        chat_principal_resolver=_principal(permissions=permissions),
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


class _Seeded:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _seed(conn: Any, tmp_path: Path, *, workspace_id: str, label: str) -> Any:
    """A project, a thread, and the agent turn a gate is presented in."""

    project = await _seed_project_row(conn, workspace_id, name=f"D5 gates {label}")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"wsm_d5_{USER_ID}_{workspace_id}",
    )
    thread_id = f"thr_d5_{label}"
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
        storage=FsStorage(tmp_path / f"d5-artifacts-{label}"),
        conn_factory=conn_session_factory(conn),
    )
    manifest = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    turn_id = uuid5(NAMESPACE_URL, f"lane-d5:{label}:presenting")
    execution_id = uuid5(NAMESPACE_URL, f"lane-d5:{label}:execution")
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
            "id": turn_id,
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
        brand_id=project.brand_id,
        product_id=project.product_id,
        thread_id=thread_id,
        turn_id=turn_id,
        artifacts=artifacts,
        conn_factory=conn_session_factory(conn),
    )


async def _answering_turn(conn: Any, seeded: Any, *, label: str) -> UUID:
    """The human turn that answers a gate — the durable submission its receipt is derived from.

    A gate answer is a real turn (charter §3-P5(c)), and ``agent_gate_answer`` has a foreign key
    onto ``agent_turn_submission``: the receipt on the answer must name an act the platform
    actually captured. So the answering turn is captured here exactly as the route captures it.
    """

    turn_id = turn_id_for_submission(
        workspace_id=seeded.workspace_id,
        thread_id=seeded.thread_id,
        idempotency_key=f"d5-answer-{label}",
    )
    captured = await persist_user_turn(
        conn,
        artifacts=seeded.artifacts,
        workspace_id=seeded.workspace_id,
        brand_id=seeded.brand_id,
        product_id=seeded.product_id,
        project_id=seeded.project_id,
        turn_id=turn_id,
        message=f'{{"kind":"gate_response","label":"{label}"}}',
    )
    await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"wsm_d5_{USER_ID}_{seeded.workspace_id}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=f"d5-answer-{label}",
    )
    return turn_id


async def _present(conn: Any, seeded: Any, *, directive_id: str | None = None) -> Any:
    gate_id = directive_confirmation_gate_id(
        workspace_id=seeded.workspace_id,
        turn_id=seeded.turn_id,
        subject_ref=SUBJECT_REF,
        expected_subject_sha256=DIGEST,
    )
    row, _ = await insert_gate(
        conn,
        gate_id=gate_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.turn_id,
        kind=KIND_DIRECTIVE_CONFIRMATION,
        subject_ref=SUBJECT_REF,
        subject_revision=2,
        expected_subject_sha256=DIGEST,
        subject_snapshot={
            "research_directive_id": directive_id or "44444444-4444-4444-8444-444444444444",
            "account_count": 2,
        },
        max_spend_cents=AMOUNT,
        currency=DEFAULT_GATE_CURRENCY,
        addressee_user_id=USER_ID,
    )
    return row


async def _emitter(conn: Any, seeded: Any) -> TurnStreamEmitter:
    return await TurnStreamEmitter.open(
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.turn_id,
        conn_factory=conn_session_factory(conn),
    )


async def _parts(conn: Any, seeded: Any, kind: PartKind) -> list[dict[str, Any]]:
    rows = await list_turn_events(conn, workspace_id=seeded.workspace_id, turn_id=seeded.turn_id)
    return [
        dict(row.payload["part"])  # type: ignore[arg-type]
        for row in rows
        if row.part_kind == kind.value and "part" in row.payload
    ]


def _gate_ref(seeded: Any, gate_id: UUID) -> DomainObjectRef:
    return DomainObjectRef(
        workspace_id=seeded.workspace_id,
        object_type=GATE_OBJECT_TYPE,
        object_id=str(gate_id),
    )


def _envelope_for(seeded: Any, *, accounts: int) -> EntityResearchRunEnvelope:
    """The R0 run fixture, re-parented onto this test's tenant and widened to ``accounts``.

    Re-parenting is a JSON rewrite of two identifiers because only those two matter here: the task
    projection filters on ``workspace_id`` and joins on the launch receipt, and everything else the
    run carries is opaque to it.
    """

    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH, concurrency_limit=2)
    original = base.lifecycle.selection
    base = EntityResearchRunEnvelope.model_validate_json(
        base.model_dump_json()
        .replace(original.workspace_id, seeded.workspace_id)
        .replace(original.project_id, seeded.project_id)
    )
    first = base.lifecycle.selection.subjects[0]
    subjects = (
        first,
        *(
            SelectedResearchSubject(subject_entity_id=uuid4(), basis=first.basis)
            for _ in range(accounts - 1)
        ),
    )
    selection = base.lifecycle.selection.model_copy(update={"subjects": subjects})
    lifecycle = base.lifecycle.model_copy(update={"selection": selection})
    template = base.jobs[0]
    jobs = tuple(
        EntityResearchJobEnvelope(
            authorization=EntityResearchJobAuthorization(
                **{
                    **template.authorization.model_dump(mode="python"),
                    "job_id": uuid4(),
                    "subject_entity_id": subject.subject_entity_id,
                    "selection": selection,
                    "checkpoint_thread_id": (
                        f"checkpoint:{lifecycle.run_id}:{subject.subject_entity_id}"
                    ),
                    "attempt_id": uuid4(),
                    "lease_id": uuid4(),
                }
            ),
            priority=priority,
            budget_envelope_ref=f"budget:job:{subject.subject_entity_id}",
            budget_cap_cents=Decimal("3.00"),
        )
        for priority, subject in enumerate(subjects)
    )
    return EntityResearchRunEnvelope(
        lifecycle=lifecycle,
        jobs=jobs,
        budget_cap_cents=Decimal("10.00"),
        concurrency_limit=2,
    )


async def _launch_run(
    conn: Any, seeded: Any, *, action_ref: str, accounts: int = 2
) -> EntityResearchRunEnvelope:
    """A real ``entity_research_run`` + jobs, plus the launch-control row carrying the receipt.

    The control row is written by hand for the same reason D3 writes its ``agent_turn`` row by
    hand: the production writer is the whole M8D fleet service, and this suite is about the *task
    projection*, not about composing a launcher.
    """

    envelope = _envelope_for(seeded, accounts=accounts)
    selection = envelope.lifecycle.selection
    await launch_entity_research_run(conn, envelope)
    await conn.execute(
        text(
            "INSERT INTO entity_research_account_fleet "
            "(research_run_id, workspace_id, project_id, product_id, project_run_id, "
            " canary_job_ids, supervisor_policy_ref, supervisor_policy_json, "
            " supervisor_policy_sha256, state, created_by, source_operation_id, "
            " source_action_ref) "
            "VALUES (:run_id, :workspace, :project, :product, :project_run, "
            " CAST(:canary AS uuid[]), 'supervisor-policy:v1', CAST('{}' AS jsonb), :sha, "
            " 'open', :created_by, :operation, :action_ref)"
        ),
        {
            "run_id": envelope.lifecycle.run_id,
            "workspace": seeded.workspace_id,
            "project": seeded.project_id,
            "product": selection.product_id,
            "project_run": selection.project_run_id,
            "canary": [str(envelope.jobs[0].authorization.job_id)],
            "sha": "f" * 64,
            "created_by": USER_ID,
            "operation": uuid4(),
            "action_ref": action_ref,
        },
    )
    return envelope


# --- the gates route -----------------------------------------------------------------------


def test_the_gates_route_serves_the_payload_an_approval_card_cannot_be_answered_without(
    tmp_path: Path,
) -> None:
    """Every ``GateView`` member, under the path and the field names the shipped card parses."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-read", label="read")
            gate = await _present(conn, seeded)
            async with _client(_app(conn)) as client:
                response = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/gates",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            assert response.status_code == 200
            body = response.json()
            assert list(body) == ["data"]
            assert len(body["data"]) == 1
            served = body["data"][0]

            assert served["gate_id"] == str(gate.gate_id)
            assert served["workspace_id"] == seeded.workspace_id
            assert served["project_id"] == seeded.project_id
            assert served["thread_id"] == seeded.thread_id
            assert served["turn_id"] == str(seeded.turn_id)
            assert served["kind"] == KIND_DIRECTIVE_CONFIRMATION
            assert served["subject_ref"] == SUBJECT_REF
            assert served["subject_revision"] == 2
            assert served["expected_subject_sha256"] == DIGEST
            assert served["subject_snapshot"]["account_count"] == 2
            assert tuple(served["permitted_decisions"]) == DECISIONS
            assert served["currency"] == DEFAULT_GATE_CURRENCY
            assert served["addressee_user_id"] == USER_ID
            assert served["created_at"] == gate.created_at.isoformat()
            # "Open" is the absence of an answer record, on the wire exactly as in the row.
            assert served["answer"] is None
            assert served["launches"] == []

            # The amount is the canonical text spelling, not a float: an approval is refused unless
            # it echoes the stored ``numeric(20,4)`` amount, and a float round-trip is the one way
            # a client could send back a number it never saw.
            assert served["max_spend_cents"] == "24000"
            assert Decimal(served["max_spend_cents"]) == gate.max_spend_cents

    run_async(scenario())


def test_the_gates_route_reports_the_answer_and_the_run_that_answer_launched(
    tmp_path: Path,
) -> None:
    """A closed gate stays in history with its decision — and with what the decision spent."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-answered", label="answered")
            gate = await _present(conn, seeded)
            answering_turn_id = await _answering_turn(conn, seeded, label="answered")
            action_ref = derive_turn_action_ref(answering_turn_id)
            await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=seeded.workspace_id,
                turn_id=answering_turn_id,
                action_ref=action_ref,
                decision="approved",
                expected_subject_sha256=gate.expected_subject_sha256,
                answered_by_user_id=USER_ID,
            )
            envelope = await _launch_run(conn, seeded, action_ref=action_ref)

            async with _client(_app(conn)) as client:
                response = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/gates",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            served = response.json()["data"][0]
            assert served["answer"] == {
                "turn_id": str(answering_turn_id),
                "action_ref": action_ref,
                "decision": "approved",
                "expected_subject_sha256": gate.expected_subject_sha256,
                "decision_payload": {},
                "selected_option_ref": None,
                "answered_by_user_id": USER_ID,
                "answered_at": served["answer"]["answered_at"],
            }
            assert len(served["launches"]) == 1
            launch = served["launches"][0]
            assert launch["research_run_id"] == str(envelope.lifecycle.run_id)
            assert launch["run_kind"] == "account_research"
            assert launch["source_action_ref"] == action_ref

    run_async(scenario())


def test_the_gates_route_refuses_a_thread_it_cannot_see_without_confirming_it_exists(
    tmp_path: Path,
) -> None:
    """Another workspace, another project, and no thread at all are the *same* 404."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-scope-a", label="scope_a")
            other = await _seed(conn, tmp_path, workspace_id="ws-d5-scope-b", label="scope_b")
            await _present(conn, seeded)
            app = _app(conn)
            async with _client(app) as client:
                # The other workspace's principal asking for *this* workspace's thread.
                cross = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/gates",
                    headers={"X-Workspace-Id": other.workspace_id},
                )
                # The right workspace, the wrong project.
                wrong_project = await client.get(
                    f"/api/v1/projects/{other.project_id}/threads/{seeded.thread_id}/gates",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
                missing = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads/thr_nope/gates",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            for response in (cross, wrong_project, missing):
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "THREAD_NOT_FOUND"

    run_async(scenario())


def test_the_gates_route_requires_thread_read_on_the_active_membership(tmp_path: Path) -> None:
    """§3.5's floor: every request re-checks its own permission, not just surface entry."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-perm", label="perm")
            await _present(conn, seeded)
            without_read = frozenset(
                permission for permission in CHAT_PERMISSIONS if permission != "thread.read"
            )
            async with _client(_app(conn, permissions=without_read)) as client:
                response = await client.get(
                    f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/gates",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    run_async(scenario())


# --- the rich gate part --------------------------------------------------------------------


def test_an_open_gate_projects_the_whole_part_floor_and_its_real_kind(tmp_path: Path) -> None:
    """The blocker D5 reported: ``gate_kind`` was literally ``agent_gate`` and nothing else came."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-open", label="open")
            gate = await _present(conn, seeded)
            emitter = await _emitter(conn, seeded)
            await emitter.emit_gate_parts(refs=(_gate_ref(seeded, gate.gate_id),))
            assert emitter.emission_failures == []

            parts = await _parts(conn, seeded, PartKind.GATE)
            assert len(parts) == 1
            part = parts[0]
            assert part["gate_kind"] == KIND_DIRECTIVE_CONFIRMATION
            assert part["gate_kind"] != GATE_OBJECT_TYPE
            assert part["state"] == "requested"
            assert part["gate_ref"]["object_id"] == str(gate.gate_id)
            assert part["part_id"] == f"gate:{GATE_OBJECT_TYPE}:{gate.gate_id}"
            assert part["expected_subject_sha256"] == DIGEST
            assert part["amount_cents"] == 24_000
            assert part["currency"] == DEFAULT_GATE_CURRENCY
            assert part["addressee_user_id"] == USER_ID
            assert tuple(part["permitted_decisions"]) == DECISIONS
            assert part["subject_refs"] == [
                {
                    "workspace_id": seeded.workspace_id,
                    "object_type": "research_directive",
                    "object_id": "44444444-4444-4444-8444-444444444444",
                    "sha256": DIGEST,
                    "version": 2,
                }
            ]
            # No decision yet, and no display copy: the adapter writes the words (§3.1/§3.4).
            assert "decision" not in part
            assert "title" not in part
            assert "summary" not in part

    run_async(scenario())


def test_an_answered_gate_projects_its_decision_actor_and_time_as_a_completed_part(
    tmp_path: Path,
) -> None:
    """§3.4: a closed gate remains in history with its answer, not deleted and not still open."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-closed", label="closed")
            gate = await _present(conn, seeded)
            answering_turn_id = await _answering_turn(conn, seeded, label="closed")
            answer = await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=seeded.workspace_id,
                turn_id=answering_turn_id,
                action_ref=derive_turn_action_ref(answering_turn_id),
                decision="revised",
                expected_subject_sha256=gate.expected_subject_sha256,
                answered_by_user_id=USER_ID,
            )
            emitter = await _emitter(conn, seeded)
            await emitter.emit_gate_parts(refs=(_gate_ref(seeded, gate.gate_id),))

            rows = [
                row
                for row in await list_turn_events(
                    conn, workspace_id=seeded.workspace_id, turn_id=seeded.turn_id
                )
                if row.part_kind == PartKind.GATE.value
            ]
            assert [row.event_type for row in rows] == ["part.completed"]
            part = rows[0].payload["part"]
            assert part["state"] == "responded"
            assert part["decision"] == "revised"
            assert part["answered_by_user_id"] == USER_ID
            assert part["answered_at"] == answer.answered_at.isoformat()
            # The card is still answer*able*-shaped: the floor does not shrink once it closes.
            assert part["expected_subject_sha256"] == DIGEST
            assert part["amount_cents"] == 24_000

    run_async(scenario())


def test_a_gate_ref_with_no_durable_row_still_renders_as_the_thin_shape(tmp_path: Path) -> None:
    """``open_gate_refs`` is an open vocabulary; an unknown flavour must not fail the stream."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-thin", label="thin")
            emitter = await _emitter(conn, seeded)
            await emitter.emit_gate_parts(
                refs=(
                    DomainObjectRef(
                        workspace_id=seeded.workspace_id,
                        object_type="some_future_gate",
                        object_id=str(uuid4()),
                    ),
                )
            )
            assert emitter.emission_failures == []
            parts = await _parts(conn, seeded, PartKind.GATE)
            assert len(parts) == 1
            assert parts[0]["gate_kind"] == "some_future_gate"
            assert parts[0]["state"] == "requested"
            assert "amount_cents" not in parts[0]

    run_async(scenario())


# --- the task part -------------------------------------------------------------------------


def test_a_launched_run_becomes_one_task_part_counted_off_its_own_jobs(tmp_path: Path) -> None:
    """One run stays one visible task, and the counts are the job rows — never a guess."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-task", label="task")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope = await _launch_run(conn, seeded, action_ref=action_ref)

            tasks = await research_tasks_for_action_refs(
                workspace_id=seeded.workspace_id,
                action_refs=(action_ref,),
                conn_factory=seeded.conn_factory,
            )
            assert len(tasks) == 1
            assert tasks[0].counts.total == len(envelope.jobs)
            assert tasks[0].counts.queued == len(envelope.jobs)

            emitter = await _emitter(conn, seeded)
            await emitter.emit_launched_task_parts()
            assert emitter.emission_failures == []
            parts = await _parts(conn, seeded, PartKind.TASK)
            assert len(parts) == 1
            part = parts[0]
            assert part["part_id"] == f"task:{envelope.lifecycle.run_id}"
            assert part["state"] == TaskState.QUEUED.value
            assert part["run_ref"] == {
                "object_type": "entity_research_run",
                "object_id": str(envelope.lifecycle.run_id),
                "workspace_id": seeded.workspace_id,
            }
            assert part["counts"]["total"] == len(envelope.jobs)
            assert part["counts"]["queued"] == len(envelope.jobs)

    run_async(scenario())


def test_a_turn_that_launched_nothing_emits_no_task_part(tmp_path: Path) -> None:
    """An honest gap beats an invented card: no launch receipt, no task."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-notask", label="notask")
            emitter = await _emitter(conn, seeded)
            await emitter.emit_launched_task_parts()
            assert emitter.emission_failures == []
            assert await _parts(conn, seeded, PartKind.TASK) == []

    run_async(scenario())


def test_an_ended_run_reports_partial_when_some_subjects_did_not_finish_everything(
    tmp_path: Path,
) -> None:
    """``terminal`` is not ``completed``: the outcome column is where "partial" actually lives."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-partial", label="partial")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope = await _launch_run(conn, seeded, action_ref=action_ref)
            outcomes = (
                ResearchFinalizationOutcome.COMPLETED,
                ResearchFinalizationOutcome.EXHAUSTED,
            )
            assert len(envelope.jobs) == len(outcomes)
            for job, outcome in zip(envelope.jobs, outcomes, strict=True):
                await conn.execute(
                    text(
                        "UPDATE entity_research_job SET state='terminal', "
                        " finalization_outcome=:outcome, "
                        " finalization_receipt_ref=:receipt, terminal_at=now() "
                        "WHERE job_id = :job_id"
                    ),
                    {
                        "outcome": outcome.value,
                        "receipt": f"finalization-receipt:{job.authorization.job_id}",
                        "job_id": job.authorization.job_id,
                    },
                )
            await conn.execute(
                text(
                    "UPDATE entity_research_run SET state='terminal', terminal_at=now() "
                    "WHERE research_run_id = :run_id"
                ),
                {"run_id": envelope.lifecycle.run_id},
            )

            emitter = await _emitter(conn, seeded)
            await emitter.emit_launched_task_parts()
            parts = await _parts(conn, seeded, PartKind.TASK)
            assert len(parts) == 1
            assert parts[0]["state"] == TaskState.PARTIAL.value
            assert parts[0]["counts"]["completed"] == 1
            assert parts[0]["counts"]["partial"] == 1

    run_async(scenario())


def test_a_subject_routed_to_review_is_counted_as_needs_review_not_as_partial(
    tmp_path: Path,
) -> None:
    """ "Routed to review" is its own answer: a reviewable subject is not a budget casualty.

    ``needs_review`` used to be folded into ``partial``, which made the two indistinguishable to
    every consumer — yet only one of them is a queue a human can work. The count is split; the
    *rendered* state is not: an ended run carrying a reviewable subject is still ``partial``,
    because it still did not finish everything asked of it.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-review", label="review")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope = await _launch_run(conn, seeded, action_ref=action_ref)
            outcomes = (
                ResearchFinalizationOutcome.COMPLETED,
                ResearchFinalizationOutcome.NEEDS_REVIEW,
            )
            assert len(envelope.jobs) == len(outcomes)
            for job, outcome in zip(envelope.jobs, outcomes, strict=True):
                await conn.execute(
                    text(
                        "UPDATE entity_research_job SET state='terminal', "
                        " finalization_outcome=:outcome, "
                        " finalization_receipt_ref=:receipt, terminal_at=now() "
                        "WHERE job_id = :job_id"
                    ),
                    {
                        "outcome": outcome.value,
                        "receipt": f"finalization-receipt:{job.authorization.job_id}",
                        "job_id": job.authorization.job_id,
                    },
                )
            await conn.execute(
                text(
                    "UPDATE entity_research_run SET state='terminal', terminal_at=now() "
                    "WHERE research_run_id = :run_id"
                ),
                {"run_id": envelope.lifecycle.run_id},
            )

            tasks = await research_tasks_for_action_refs(
                workspace_id=seeded.workspace_id,
                action_refs=(action_ref,),
                conn_factory=seeded.conn_factory,
            )
            assert len(tasks) == 1
            assert tasks[0].counts.needs_review == 1
            assert tasks[0].counts.partial == 0
            assert tasks[0].counts.completed == 1

            emitter = await _emitter(conn, seeded)
            await emitter.emit_launched_task_parts()
            assert emitter.emission_failures == []
            parts = await _parts(conn, seeded, PartKind.TASK)
            assert len(parts) == 1
            assert parts[0]["counts"]["needs_review"] == 1
            assert parts[0]["counts"]["partial"] == 0
            assert parts[0]["counts"]["completed"] == 1
            # The split lives in the counts; the card the human sees does not move.
            assert parts[0]["state"] == TaskState.PARTIAL.value

    run_async(scenario())


# --- the wiring ----------------------------------------------------------------------------


def test_turn_close_projects_the_rich_gate_and_the_task_the_turn_launched(
    tmp_path: Path,
) -> None:
    """The production seam, not the emitter in isolation: ``_project_turn_close`` does both."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-close", label="close")
            gate = await _present(conn, seeded)
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope_row = await _launch_run(conn, seeded, action_ref=action_ref)
            emitter = await _emitter(conn, seeded)

            finalization = ArtifactRef(
                workspace_id=seeded.workspace_id,
                artifact_key=f"{seeded.workspace_id}/{'0' * 64}",
                sha256="0" * 64,
                media_type="application/json",
                byte_count=2,
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid4(),
                execution_id=uuid5(NAMESPACE_URL, "lane-d5:close:execution"),
                status=FinalizeStatus.AWAITING_INPUT,
                open_gate_refs=(_gate_ref(seeded, gate.gate_id),),
                finalized_at=NOW_UTC,
            )
            outcome = AgentTurnOutcome(
                turn_id=seeded.turn_id,
                execution_id=envelope.execution_id,
                status=AgentExecutionStatus.AWAITING_INPUT,
                finalization_ref=finalization,
            )
            await ConversationTurnEngine._project_turn_close(
                None,  # type: ignore[arg-type] -- the method reads only its keyword arguments
                stream=emitter,
                outcome=outcome,
                envelope=envelope,
                assistant_message=None,
                replayed=False,
            )

            gate_parts = await _parts(conn, seeded, PartKind.GATE)
            task_parts = await _parts(conn, seeded, PartKind.TASK)
            assert [part["gate_kind"] for part in gate_parts] == [KIND_DIRECTIVE_CONFIRMATION]
            assert gate_parts[0]["amount_cents"] == 24_000
            assert [part["part_id"] for part in task_parts] == [
                f"task:{envelope_row.lifecycle.run_id}"
            ]
            # And the durable gate the route serves agrees with the part that announced it.
            served = await thread_gates(
                workspace_id=seeded.workspace_id,
                thread_id=seeded.thread_id,
                conn_factory=seeded.conn_factory,
            )
            assert [view.gate_id for view in served] == [str(gate.gate_id)]

    run_async(scenario())


def test_turn_close_projects_a_written_project_plan_as_the_plan_card(tmp_path: Path) -> None:
    """A plan-3 receipt: a ``project_document`` ref with no title still renders under its own name.

    The set of ``domain_refs`` object types that become a plan part is closed on purpose, so the
    plan being in it is the whole reason a written plan is visible in the chat at all. A ref
    recorded before documents carried their own titles has none to give, and the card falls back to
    the name that surface used — ``Plan`` / ``v3`` rather than ``project document`` / ``3`` — so a
    replayed turn draws the card the human saw.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-plan", label="plan")
            emitter = await _emitter(conn, seeded)
            document_id = uuid5(NAMESPACE_URL, "lane-d5:plan:document")
            message = ArtifactRef(
                workspace_id=seeded.workspace_id,
                artifact_key=f"{seeded.workspace_id}/{'1' * 64}",
                sha256="1" * 64,
                media_type="text/markdown",
                byte_count=2,
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid4(),
                execution_id=uuid5(NAMESPACE_URL, "lane-d5:plan:execution"),
                status=FinalizeStatus.COMPLETED,
                user_message_artifact_ref=message,
                domain_refs=(
                    DomainObjectRef(
                        workspace_id=seeded.workspace_id,
                        object_type="project_document",
                        object_id=str(document_id),
                        version=3,
                    ),
                ),
                finalized_at=NOW_UTC,
            )
            outcome = AgentTurnOutcome(
                turn_id=seeded.turn_id,
                execution_id=envelope.execution_id,
                status=AgentExecutionStatus.COMPLETED,
                finalization_ref=ArtifactRef(
                    workspace_id=seeded.workspace_id,
                    artifact_key=f"{seeded.workspace_id}/{'0' * 64}",
                    sha256="0" * 64,
                    media_type="application/json",
                    byte_count=2,
                ),
            )
            await ConversationTurnEngine._project_turn_close(
                None,  # type: ignore[arg-type] -- the method reads only its keyword arguments
                stream=emitter,
                outcome=outcome,
                envelope=envelope,
                assistant_message=None,
                replayed=False,
            )

            parts = await _parts(conn, seeded, PartKind.PLAN)
            assert len(parts) == 1
            assert parts[0]["title"] == "Plan"
            assert parts[0]["revision_label"] == "v3"
            assert parts[0]["plan_ref"]["object_type"] == "project_document"
            assert parts[0]["plan_ref"]["object_id"] == str(document_id)

    run_async(scenario())


def test_turn_close_titles_a_document_card_from_the_document_itself(tmp_path: Path) -> None:
    """The card says what the document says it is (founder ruling 2026-09-14).

    Any markdown path under ``project/`` is a document now, so "Plan" is no longer a name the
    platform can supply for one: the write carries the document's own title onto the ref, and the
    card reads it. The version is still a file revision the human can open, so it is ``v2``.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-titled", label="titled")
            emitter = await _emitter(conn, seeded)
            document_id = uuid5(NAMESPACE_URL, "lane-d5:titled:document")
            message = ArtifactRef(
                workspace_id=seeded.workspace_id,
                artifact_key=f"{seeded.workspace_id}/{'3' * 64}",
                sha256="3" * 64,
                media_type="text/markdown",
                byte_count=2,
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid4(),
                execution_id=uuid5(NAMESPACE_URL, "lane-d5:titled:execution"),
                status=FinalizeStatus.COMPLETED,
                user_message_artifact_ref=message,
                domain_refs=(
                    DomainObjectRef(
                        workspace_id=seeded.workspace_id,
                        object_type="project_document",
                        object_id=str(document_id),
                        version=2,
                        title="Who else is in this deal",
                    ),
                ),
                finalized_at=NOW_UTC,
            )
            outcome = AgentTurnOutcome(
                turn_id=seeded.turn_id,
                execution_id=envelope.execution_id,
                status=AgentExecutionStatus.COMPLETED,
                finalization_ref=ArtifactRef(
                    workspace_id=seeded.workspace_id,
                    artifact_key=f"{seeded.workspace_id}/{'0' * 64}",
                    sha256="0" * 64,
                    media_type="application/json",
                    byte_count=2,
                ),
            )
            await ConversationTurnEngine._project_turn_close(
                None,  # type: ignore[arg-type] -- the method reads only its keyword arguments
                stream=emitter,
                outcome=outcome,
                envelope=envelope,
                assistant_message=None,
                replayed=False,
            )

            parts = await _parts(conn, seeded, PartKind.PLAN)
            assert [(part["title"], part["revision_label"]) for part in parts] == [
                ("Who else is in this deal", "v2")
            ]
            assert parts[0]["plan_ref"]["object_id"] == str(document_id)

    run_async(scenario())


def test_turn_close_names_the_written_icp_and_personas_on_their_own_cards(
    tmp_path: Path,
) -> None:
    """The two older object types still render, because plan-3 receipts are still replayed.

    The versioned mount briefly had three object types, one per document it admitted, and turns
    were finalized against them. Those receipts are immutable: replaying one must still show the
    human ``ICP`` / ``v2`` and ``Personas`` / ``v1``, not ``project icp document`` / ``2``. Nothing
    writes these types any more — a document written today carries its own title instead.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d5-docs", label="docs")
            emitter = await _emitter(conn, seeded)
            icp_id = uuid5(NAMESPACE_URL, "lane-d5:docs:icp")
            persona_id = uuid5(NAMESPACE_URL, "lane-d5:docs:persona")
            message = ArtifactRef(
                workspace_id=seeded.workspace_id,
                artifact_key=f"{seeded.workspace_id}/{'2' * 64}",
                sha256="2" * 64,
                media_type="text/markdown",
                byte_count=2,
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid4(),
                execution_id=uuid5(NAMESPACE_URL, "lane-d5:docs:execution"),
                status=FinalizeStatus.COMPLETED,
                user_message_artifact_ref=message,
                domain_refs=(
                    DomainObjectRef(
                        workspace_id=seeded.workspace_id,
                        object_type="project_icp_document",
                        object_id=str(icp_id),
                        version=2,
                    ),
                    DomainObjectRef(
                        workspace_id=seeded.workspace_id,
                        object_type="project_persona_document",
                        object_id=str(persona_id),
                        version=1,
                    ),
                ),
                finalized_at=NOW_UTC,
            )
            outcome = AgentTurnOutcome(
                turn_id=seeded.turn_id,
                execution_id=envelope.execution_id,
                status=AgentExecutionStatus.COMPLETED,
                finalization_ref=ArtifactRef(
                    workspace_id=seeded.workspace_id,
                    artifact_key=f"{seeded.workspace_id}/{'0' * 64}",
                    sha256="0" * 64,
                    media_type="application/json",
                    byte_count=2,
                ),
            )
            await ConversationTurnEngine._project_turn_close(
                None,  # type: ignore[arg-type] -- the method reads only its keyword arguments
                stream=emitter,
                outcome=outcome,
                envelope=envelope,
                assistant_message=None,
                replayed=False,
            )

            parts = await _parts(conn, seeded, PartKind.PLAN)
            assert [(part["title"], part["revision_label"]) for part in parts] == [
                ("ICP", "v2"),
                ("Personas", "v1"),
            ]
            assert [part["plan_ref"]["object_id"] for part in parts] == [
                str(icp_id),
                str(persona_id),
            ]

    run_async(scenario())
