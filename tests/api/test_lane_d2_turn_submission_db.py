"""Lane D slice D2: a turn is captured and queued by HTTP, and executed by the fleet worker.

What this suite pins (charter `docs/specs/FI-lane-D-production-chat-and-launch.md` §3-P3 / §3.5,
ratified §6-D1):

* **submission is durable before anything is queued** — the user's bytes, their ``actor='human'``
  capture, and the submitting principal's Clue-owned internal ids all exist before the
  ``AGENT_TURN`` task does, and the identity is written from the ambient principal, never from a
  request field;
* **duplicate submission is a replay** — one idempotency identity is one turn and one task;
* **per-thread single-flight and submission order** — a thread never has two non-terminal tasks,
  the next turn is offered only when the previous one is terminal, and it is always the *earliest*
  un-executed submission;
* **no cross-talk and no head-of-line blocking** — two workspaces queue independently, and a
  detached research task (a run drive, an entity-research job) never delays a chat turn;
* **crash converges on one committed outcome** — a killed attempt is re-claimed as a *distinct*
  attempt, and the shared engine's committed-outcome short-circuit returns the existing outcome
  instead of executing the turn a second time.

DB-backed and rollback-only, per ``tests/api`` conventions. Every submitter identity is a **real**
``platform_user`` + ``workspace_membership`` seeded through ``clue_auth`` (``tests/_identity``),
because D2's submission row carries real foreign keys onto both.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_agents import (
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentRole,
    AgentTurnRequest,
    FinalizeStatus,
)
from clue_agents.contracts import (
    AgentConstitution,
    DomainObjectRef,
    ExecutionId,
    ProjectContextArtifact,
)
from clue_api.agent_registry_wiring import (
    PROJECT_CONVERSATION_SURFACE,
    build_agent_profile_registry,
)
from clue_api.agent_turn_fleet_wiring import (
    AgentTurnWorkHandler,
    ProjectConversationTurnRunner,
    RequiredTurnArtifactMissing,
)
from clue_api.agent_turn_submission import (
    agent_turn_dedup_key,
    dispatch_next_thread_turn,
    get_submission,
    insert_submission,
    submission_context_refs,
    thread_work_id,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.chat.composer_context import PROJECT_CONVERSATION_AGENT_PROFILE_ID
from clue_api.chat.turn_events import TurnEventType, emit_turn_event
from clue_api.conversation_turns import ConversationTurnEngine
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings, load_settings
from clue_core import AccountStatus, ProjectRunId, decode_jsonb, operation_id_from_key
from clue_design import legs as design_legs
from clue_design.documents import create_document
from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    claim_next_task,
    enqueue_task,
    finish_task,
)
from clue_fleet.work_worker import WorkContext
from clue_research.identity import insert_account_entity
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

USER_ID = "usr_d2_test"
MEMBERSHIP_ID = "wsm_d2_test"
#: The moment the injected test principal "authenticated". A fixed instant, because the Lane B
#: principal records when the session was proved and a test must not depend on wall clock.
_AUTHENTICATED_AT = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
NOW_UTC = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


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


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, chat_enabled=True, **kwargs)


async def _seed(conn: Any, workspace_id: str, *, name: str) -> Any:
    """Seed the project plus the submitter's real Lane B identity rows."""

    project = await _seed_project_row(conn, workspace_id, name=name)
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
    )
    return project


def _principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=_AUTHENTICATED_AT,
    )


def _app(conn: Any, *, settings: Settings, storage: Any) -> Any:
    from clue_api.thread_wiring import register_thread_tools

    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
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
        ingestion_storage=storage,
        chat_principal_resolver=_principal,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _thread(conn: Any, *, workspace_id: str, project_id: str, label: str) -> str:
    thread_id = f"thr_d2_{label}"
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
    return thread_id


async def _tasks(conn: Any, *, workspace_id: str, thread_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT dedup_key, status, attempts FROM fleet_task "
                    "WHERE kind = 'agent_turn' AND work_id = :work_id "
                    "ORDER BY enqueue_seq"
                ),
                {"work_id": thread_work_id(workspace_id=workspace_id, thread_id=thread_id)},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def _submit(
    client: httpx.AsyncClient,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    message: str,
    key: str,
) -> httpx.Response:
    return await client.post(
        f"/api/v1/projects/{project_id}/threads/{thread_id}/turns",
        json={"message": message},
        headers={"X-Workspace-Id": workspace_id, "Idempotency-Key": key},
    )


# --- the route ---------------------------------------------------------------------------------


def test_a_submitted_turn_is_durable_and_queued_before_anything_runs(tmp_path: Path) -> None:
    """202 means captured and offered — not executed. Everything durable exists at that point."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-accept", name="D2 accept")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="accept",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                response = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="We sell to hospital operations teams.",
                    key="key-accept",
                )
            assert response.status_code == 202, response.text
            body = response.json()["data"]
            assert body["replayed"] is False
            turn_id = UUID(body["turn_id"])
            assert turn_id == turn_id_for_submission(
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                idempotency_key="key-accept",
            )

            submission = await get_submission(
                conn,
                workspace_id=project.workspace_id,
                turn_id=turn_id,
            )
            assert submission is not None
            # Ambient authority, from the principal — the request body carried no identity at all.
            assert submission.submitted_by_user_id == USER_ID
            assert submission.submitted_via_membership_id.startswith(MEMBERSHIP_ID)
            assert submission.thread_id == thread_id
            assert submission.agent_profile_id == PROJECT_CONVERSATION_AGENT_PROFILE_ID

            # Capture-before-spend: the human's words and their `actor='human'` record exist.
            capture = (
                (
                    await conn.execute(
                        text(
                            "SELECT actor, kind, artifact_key, content_sha256 "
                            "FROM onboarding_input WHERE id = :id"
                        ),
                        {"id": submission.onboarding_input_id},
                    )
                )
                .mappings()
                .one()
            )
            assert capture["actor"] == "human"
            assert capture["kind"] == "user_turn"
            assert capture["artifact_key"] == submission.message_artifact_key
            assert capture["content_sha256"] == submission.message_sha256

            # Exactly one offered task, named by the turn and keyed on the thread.
            tasks = await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id)
            assert tasks == [
                {
                    "dedup_key": agent_turn_dedup_key(turn_id),
                    "status": FleetTaskStatus.QUEUED.value,
                    "attempts": 0,
                }
            ]
            payload = (
                await conn.execute(
                    text("SELECT payload_json FROM fleet_task WHERE dedup_key = :key"),
                    {"key": agent_turn_dedup_key(turn_id)},
                )
            ).scalar_one()
            carried = payload if isinstance(payload, dict) else json.loads(payload)
            # References only. A session token in a queue payload is what Lane B §7 forbids.
            assert set(carried) == {"turn_id", "workspace_id", "project_id", "thread_id"}

    run_async(scenario())


def test_message_submission_persists_ordered_context_and_the_real_terra_profile(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-r8-composer", name="R8 composer")
            first_account = await insert_account_entity(
                conn,
                canonical_name="First account",
                primary_domain="first.example",
                status=AccountStatus.ACTIVE,
                workspace_id=project.workspace_id,
            )
            second_account = await insert_account_entity(
                conn,
                canonical_name="Second account",
                primary_domain="second.example",
                status=AccountStatus.ACTIVE,
                workspace_id=project.workspace_id,
            )
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="r8-composer",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            request = {
                "message": "Compare these accounts in this order.",
                "context_refs": [
                    {"object_type": "account", "object_id": str(second_account)},
                    {"object_type": "account", "object_id": str(first_account)},
                ],
                "attachment_refs": [],
                "agent_profile_id": PROJECT_CONVERSATION_AGENT_PROFILE_ID,
            }
            headers = {
                "X-Workspace-Id": project.workspace_id,
                "Idempotency-Key": "r8-composer-message",
            }
            async with _client(app) as client:
                accepted = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json=request,
                    headers=headers,
                )
                unavailable_profile = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json={**request, "agent_profile_id": "decorative-model@v1"},
                    headers={**headers, "Idempotency-Key": "r8-bad-profile"},
                )
                attachment = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json={
                        **request,
                        "attachment_refs": [
                            {
                                "upload_id": str(uuid4()),
                                "artifact_key": "browser-local://not-durable",
                                "sha256": "a" * 64,
                                "media_type": "text/plain",
                                "byte_count": 1,
                                "filename": "fake.txt",
                            }
                        ],
                    },
                    headers={**headers, "Idempotency-Key": "r8-attachment"},
                )

            assert accepted.status_code == 202, accepted.text
            turn_id = UUID(accepted.json()["data"]["turn_id"])
            submission = await get_submission(
                conn,
                workspace_id=project.workspace_id,
                turn_id=turn_id,
            )
            assert submission is not None
            assert submission.agent_profile_id == PROJECT_CONVERSATION_AGENT_PROFILE_ID
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT object_type, object_id FROM "
                            "agent_turn_submission_context_ref "
                            "WHERE workspace_id = :workspace AND turn_id = :turn "
                            "ORDER BY ordinal"
                        ),
                        {"workspace": project.workspace_id, "turn": turn_id},
                    )
                )
                .tuples()
                .all()
            )
            assert rows == [
                ("account", str(second_account)),
                ("account", str(first_account)),
            ]
            assert (
                unavailable_profile.status_code,
                unavailable_profile.json()["error"]["code"],
            ) == (409, "AGENT_PROFILE_UNAVAILABLE")
            # A receipt naming an upload this workspace never made is refused fail-closed.
            assert (attachment.status_code, attachment.json()["error"]["code"]) == (
                404,
                "ATTACHMENT_NOT_FOUND",
            )

    run_async(scenario())


def test_design_targets_are_validated_snapshotted_and_replay_after_the_scene_advances(
    tmp_path: Path,
) -> None:
    """The HTTP receipt freezes exact scene targets before the design worker sees them."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-edit-targets", name="Edit target chips")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="edit-targets",
            )
            document = await create_document(
                conn,
                workspace_id=project.workspace_id,
                scene={
                    "schema_version": 1,
                    "meta": {"id": "doc_edit_targets", "title": "Launch banner"},
                    "pages": {
                        "page_ad": {"id": "page_ad", "children": ["frame"]},
                    },
                    "nodes": {
                        "frame": {"id": "frame", "children": ["headline"]},
                        "headline": {"id": "headline", "children": []},
                    },
                    "slots": {},
                    "assets": {},
                    "export_profiles": [],
                },
            )
            await conn.execute(
                text(
                    "UPDATE design_document SET current_version = 4 "
                    "WHERE id = :document AND workspace_id = :workspace"
                ),
                {"document": document["id"], "workspace": project.workspace_id},
            )
            parent_execution_id = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": parent_execution_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "hash": "0" * 64,
                },
            )
            leg = await design_legs.open_leg(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                parent_execution_id=parent_execution_id,
                document_id=document["id"],
                document_version_guard=4,
            )
            # Spec §3.2: project containment is derived from the leg's document SET, and the
            # shipped tool writes the position-0 child row for every leg it opens. The DAL
            # writes only the column, so the seed adds what production guarantees — without
            # it the document belongs to no project and the ref is refused.
            await design_legs.add_leg_documents(
                conn,
                workspace_id=project.workspace_id,
                leg_id=str(leg["id"]),
                documents=[
                    design_legs.LegDocumentSpec(document_id=str(document["id"]), position=0)
                ],
            )
            refs = [
                {
                    "object_type": "design_document",
                    "object_id": document["id"],
                    "version": 4,
                },
                {
                    "object_type": "design_node",
                    "object_id": "headline",
                    "version": 4,
                },
            ]
            request = {
                "message": "Make this bolder.",
                "context_refs": refs,
            }
            headers = {
                "X-Workspace-Id": project.workspace_id,
                "Idempotency-Key": "edit-target-headline",
            }
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                accepted = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json=request,
                    headers=headers,
                )
                assert accepted.status_code == 202, accepted.text
                assert accepted.json()["data"]["routed_to"] == "design"

                turn_id = UUID(accepted.json()["data"]["turn_id"])
                durable = await submission_context_refs(
                    conn,
                    workspace_id=project.workspace_id,
                    turn_id=turn_id,
                )
                assert [(ref.object_type, ref.object_id, ref.version) for ref in durable] == [
                    ("design_document", document["id"], 4),
                    ("design_node", "headline", 4),
                ]

                # A later canvas edit cannot invalidate the immutable receipt on retry.
                await conn.execute(
                    text(
                        "UPDATE design_document SET current_version = 5 "
                        "WHERE id = :document AND workspace_id = :workspace"
                    ),
                    {"document": document["id"], "workspace": project.workspace_id},
                )
                replay = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json=request,
                    headers=headers,
                )
                stale_new_turn = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json=request,
                    headers={**headers, "Idempotency-Key": "edit-target-stale"},
                )

            assert replay.status_code == 202, replay.text
            assert replay.json()["data"]["replayed"] is True
            assert stale_new_turn.status_code == 409, stale_new_turn.text
            assert stale_new_turn.json()["error"]["code"] == "CONTEXT_REF_STALE"

    run_async(scenario())


def test_duplicate_submission_replays_one_turn_and_enqueues_nothing_new(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-replay", name="D2 replay")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="replay",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                first = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Same message.",
                    key="key-replay",
                )
                second = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Same message.",
                    key="key-replay",
                )
                # A *different* message under the used key is a client bug, not a retry.
                conflict = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Actually, something else.",
                    key="key-replay",
                )
            assert first.status_code == 202
            assert second.status_code == 202
            assert second.json()["data"]["turn_id"] == first.json()["data"]["turn_id"]
            assert second.json()["data"]["replayed"] is True
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

            tasks = await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id)
            assert len(tasks) == 1
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_turn_submission "
                        "WHERE workspace_id = :ws AND thread_id = :thread"
                    ),
                    {"ws": project.workspace_id, "thread": thread_id},
                )
            ).scalar_one()
            assert int(count) == 1

    run_async(scenario())


def test_a_derived_submission_names_both_halves_or_neither(tmp_path: Path) -> None:
    """Spec 2026-09-20 §2.1: ``derivation`` and ``derived_from_turn_id`` travel together."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-derived", name="D2 derived")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="derived",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                accepted = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Which accounts should get this campaign?",
                    key="key-derived-source",
                )
            assert accepted.status_code == 202, accepted.text
            source = await get_submission(
                conn,
                workspace_id=project.workspace_id,
                turn_id=UUID(accepted.json()["data"]["turn_id"]),
            )
            assert source is not None

            # Half a derivation is not a derivation: the row model refuses before the CHECK does.
            with pytest.raises(ValueError, match="both its derivation"):
                await insert_submission(
                    conn,
                    turn_id=uuid4(),
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    submitted_by_user_id=USER_ID,
                    submitted_via_membership_id=source.submitted_via_membership_id,
                    onboarding_input_id=source.onboarding_input_id,
                    message_artifact_key=source.message_artifact_key,
                    message_sha256=source.message_sha256,
                    idempotency_key=None,
                    derivation="design_leg_first_turn",
                )

            derived_turn_id = turn_id_for_submission(
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                idempotency_key="derived:1",
            )
            derived, created = await insert_submission(
                conn,
                turn_id=derived_turn_id,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=thread_id,
                submitted_by_user_id=USER_ID,
                submitted_via_membership_id=source.submitted_via_membership_id,
                onboarding_input_id=source.onboarding_input_id,
                message_artifact_key=source.message_artifact_key,
                message_sha256=source.message_sha256,
                idempotency_key="derived:1",
                derivation="design_leg_first_turn",
                derived_from_turn_id=source.turn_id,
            )
            assert created is True
            assert derived.derivation == "design_leg_first_turn"
            assert derived.derived_from_turn_id == source.turn_id
            # And it reads back the same way the worker will read it.
            again = await get_submission(
                conn,
                workspace_id=project.workspace_id,
                turn_id=derived.turn_id,
            )
            assert again is not None and again.derivation == "design_leg_first_turn"
            assert again.derived_from_turn_id == source.turn_id
            # The human's own submission is derived from nothing.
            assert source.derivation is None and source.derived_from_turn_id is None

    run_async(scenario())


def test_the_route_refuses_what_it_cannot_honestly_accept(tmp_path: Path) -> None:
    """An archived thread, another project's thread, and a missing idempotency identity."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-refuse", name="D2 refuse")
            other = await _seed_project_row(conn, project.workspace_id, name="D2 other project")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="refuse",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                missing_key = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json={"message": "no key"},
                    headers={"X-Workspace-Id": project.workspace_id},
                )
                cross_project = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=other.project_id,
                    thread_id=thread_id,
                    message="wrong project",
                    key="key-cross",
                )
                empty = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="   ",
                    key="key-empty",
                )
                await conn.execute(
                    text("UPDATE agent_thread SET status='archived' WHERE id = :id"),
                    {"id": thread_id},
                )
                archived = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="after archive",
                    key="key-archived",
                )
            assert missing_key.status_code == 400
            assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
            # Another project's thread is *not found*, never "forbidden" — no existence leak.
            assert cross_project.status_code == 404
            assert cross_project.json()["error"]["code"] == "THREAD_NOT_FOUND"
            assert empty.status_code == 422
            assert archived.status_code == 409
            assert archived.json()["error"]["code"] == "THREAD_ARCHIVED"

    run_async(scenario())


# --- single-flight, order, and isolation -------------------------------------------------------


def test_one_thread_offers_one_turn_at_a_time_in_submission_order(tmp_path: Path) -> None:
    """The §3.5 invariant: two turns of a thread never run at once, and never out of order."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-order", name="D2 order")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="order",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                first = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="First question.",
                    key="key-1",
                )
                second = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Second question, while the first is still queued.",
                    key="key-2",
                )
            assert first.status_code == 202
            # The later turn is accepted and durable — it is simply not offered yet.
            assert second.status_code == 202
            first_turn = UUID(first.json()["data"]["turn_id"])
            second_turn = UUID(second.json()["data"]["turn_id"])
            assert (
                await get_submission(conn, workspace_id=project.workspace_id, turn_id=second_turn)
                is not None
            )
            assert [
                task["dedup_key"]
                for task in await _tasks(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
            ] == [agent_turn_dedup_key(first_turn)]

            # Finishing the first turn's task is what releases the second — in submission order.
            work_id = thread_work_id(workspace_id=project.workspace_id, thread_id=thread_id)
            claimed = await claim_next_task(
                conn,
                kind=FleetTaskKind.AGENT_TURN,
                worker_id="worker-a",
                project_run_id=ProjectRunId(work_id),
            )
            assert claimed is not None
            # While it is claimed, nothing new is offered: that is the single-flight fence.
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
                is None
            )
            await finish_task(
                conn,
                task_id=claimed.task_id,
                worker_id="worker-a",
                status=FleetTaskStatus.DONE,
                result_ref={"outcome": "completed"},
            )
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
                == second_turn
            )
            assert [
                task["dedup_key"]
                for task in await _tasks(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
            ] == [agent_turn_dedup_key(first_turn), agent_turn_dedup_key(second_turn)]

    run_async(scenario())


def test_two_workspaces_queue_without_cross_talk(tmp_path: Path) -> None:
    """A busy thread in one workspace neither blocks nor is confused with another's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            left = await _seed(conn, "ws-d2-left", name="D2 left")
            right = await _seed(conn, "ws-d2-right", name="D2 right")
            left_thread = await _thread(
                conn,
                workspace_id=left.workspace_id,
                project_id=left.project_id,
                label="left",
            )
            right_thread = await _thread(
                conn,
                workspace_id=right.workspace_id,
                project_id=right.project_id,
                label="right",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                for workspace, project, thread in (
                    (left.workspace_id, left.project_id, left_thread),
                    (left.workspace_id, left.project_id, left_thread),
                    (right.workspace_id, right.project_id, right_thread),
                ):
                    response = await _submit(
                        client,
                        workspace_id=workspace,
                        project_id=project,
                        thread_id=thread,
                        message=f"hello from {thread}",
                        key=f"key-{thread}-{uuid4().hex[:6]}",
                    )
                    assert response.status_code == 202, response.text

            # The left thread holds one offer (its second turn waits); the right thread is
            # unaffected — a queued turn elsewhere is never at the head of anyone else's queue.
            left_tasks = await _tasks(conn, workspace_id=left.workspace_id, thread_id=left_thread)
            assert len(left_tasks) == 1
            assert (
                len(await _tasks(conn, workspace_id=right.workspace_id, thread_id=right_thread))
                == 1
            )
            # Two threads, two work ids: the driver lease can never conflate them.
            assert thread_work_id(
                workspace_id=left.workspace_id, thread_id=left_thread
            ) != thread_work_id(workspace_id=right.workspace_id, thread_id=right_thread)

    run_async(scenario())


def test_detached_research_work_does_not_block_a_new_chat_turn(tmp_path: Path) -> None:
    """Research runs on its own kinds and its own work ids; a chat turn is offered regardless."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-detached", name="D2 detached")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="detached",
            )
            research_run = ProjectRunId(uuid4())
            for kind in (FleetTaskKind.DRIVE_RUN, FleetTaskKind.ENTITY_RESEARCH_JOB):
                await enqueue_task(
                    conn,
                    kind=kind,
                    project_run_id=research_run,
                    dedup_key=f"detached:{kind.value}",
                )
            # …and claim them, so the research work is genuinely in flight, not merely queued.
            for kind in (FleetTaskKind.DRIVE_RUN, FleetTaskKind.ENTITY_RESEARCH_JOB):
                assert (
                    await claim_next_task(conn, kind=kind, worker_id="research-worker") is not None
                )

            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                response = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="A question asked while research is running.",
                    key="key-detached",
                )
            assert response.status_code == 202, response.text
            tasks = await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id)
            assert [task["status"] for task in tasks] == [FleetTaskStatus.QUEUED.value]

    run_async(scenario())


# --- the worker handler ------------------------------------------------------------------------


class _RecordingRunner:
    """A stand-in for the composed turn runner: records calls, optionally fails."""

    def __init__(self, *, fail: bool = False, error: Exception | None = None) -> None:
        self.calls: list[UUID] = []
        self._fail = fail
        self._error = error

    async def run(self, *, turn_id: UUID, workspace_id: str, fence: Any = None) -> Any:
        del workspace_id
        self.calls.append(turn_id)
        if self._error is not None:
            raise self._error
        if self._fail:
            raise RuntimeError("the model round failed")
        return SimpleNamespace(
            outcome=SimpleNamespace(status=AgentExecutionStatus.COMPLETED),
            replayed=False,
        )


class _ConnWorkQueue:
    """A ``WorkQueue`` over the *test's* rolled-back connection.

    ``DbWorkQueue`` opens its own ``transaction()``, which would commit outside the test's
    savepoint (and read a database that does not yet contain the fixture's rows). The handler only
    finishes tasks, so this adapter is exactly the two calls it makes.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.finished: list[tuple[UUID, FleetTaskStatus]] = []

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, Any] | None = None,
    ) -> bool:
        self.finished.append((task_id, status))
        return await finish_task(
            self._conn,
            task_id=task_id,
            worker_id=worker_id,
            status=status,
            result_ref=result_ref,
        )

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool:
        del task_id, worker_id
        return True

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool:
        del task_id, worker_id
        return True


async def _handle_next(
    conn: Any,
    *,
    workspace_id: str,
    thread_id: str,
    runner: _RecordingRunner,
    worker_id: str = "worker-1",
    queue: Any = None,
) -> None:
    """Claim this thread's offered task and run the real handler over it."""

    cf = conn_session_factory(conn)
    queue = queue if queue is not None else _ConnWorkQueue(conn)
    work_id = thread_work_id(workspace_id=workspace_id, thread_id=thread_id)
    claimed = await claim_next_task(
        conn,
        kind=FleetTaskKind.AGENT_TURN,
        worker_id=worker_id,
        project_run_id=ProjectRunId(work_id),
    )
    assert claimed is not None
    handler = AgentTurnWorkHandler(runner=runner, queue=queue, conn_factory=cf)  # type: ignore[arg-type]
    await handler.handle(
        WorkContext(
            task_id=claimed.task_id,
            work_id=work_id,
            worker_id=worker_id,
            lease_generation=claimed.attempts,  # type: ignore[arg-type]
            payload=claimed.payload,
            stop_requested=_never(),
            lease_lost=_never(),
        )
    )


def _never() -> Any:
    import asyncio

    return asyncio.Event()


def test_the_handler_finishes_its_task_and_hands_the_thread_to_the_next_turn(
    tmp_path: Path,
) -> None:
    """Finish first, dispatch second — the ordering that keeps the chain alive without overlap."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-chain", name="D2 chain")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="chain",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                first = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="First.",
                    key="chain-1",
                )
                second = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Second.",
                    key="chain-2",
                )
            runner = _RecordingRunner()
            await _handle_next(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                runner=runner,
            )
            assert runner.calls == [UUID(first.json()["data"]["turn_id"])]
            tasks = await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id)
            assert [(task["dedup_key"], task["status"]) for task in tasks] == [
                (
                    agent_turn_dedup_key(UUID(first.json()["data"]["turn_id"])),
                    FleetTaskStatus.DONE.value,
                ),
                (
                    agent_turn_dedup_key(UUID(second.json()["data"]["turn_id"])),
                    FleetTaskStatus.QUEUED.value,
                ),
            ]

    run_async(scenario())


def test_a_failed_turn_is_recorded_failed_and_does_not_wedge_the_thread(tmp_path: Path) -> None:
    """A turn that cannot succeed must not sit at the head of the conversation forever."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-fail", name="D2 fail")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="fail",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                for key in ("fail-1", "fail-2"):
                    assert (
                        await _submit(
                            client,
                            workspace_id=project.workspace_id,
                            project_id=project.project_id,
                            thread_id=thread_id,
                            message=f"message {key}",
                            key=key,
                        )
                    ).status_code == 202
            await _handle_next(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                runner=_RecordingRunner(fail=True),
            )
            statuses = [
                task["status"]
                for task in await _tasks(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
            ]
            assert statuses == [FleetTaskStatus.FAILED.value, FleetTaskStatus.QUEUED.value]

    run_async(scenario())


def test_a_missing_required_artifact_is_not_retried_and_releases_the_next_turn(
    tmp_path: Path,
) -> None:
    """Lost exact input is terminal for A; the handler still offers B in acceptance order."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-missing-input", name="D2 missing input")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="missing-input",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                first = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="The unrecoverable first prompt.",
                    key="missing-1",
                )
                second = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="The next prompt must still run.",
                    key="missing-2",
                )
            runner = _RecordingRunner(
                error=RequiredTurnArtifactMissing("required turn context is gone")
            )
            await _handle_next(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                runner=runner,
            )
            first_id = UUID(first.json()["data"]["turn_id"])
            second_id = UUID(second.json()["data"]["turn_id"])
            assert runner.calls == [first_id]
            tasks = await _tasks(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
            )
            assert [(task["dedup_key"], task["status"], task["attempts"]) for task in tasks] == [
                (agent_turn_dedup_key(first_id), FleetTaskStatus.FAILED.value, 1),
                (agent_turn_dedup_key(second_id), FleetTaskStatus.QUEUED.value, 0),
            ]

    run_async(scenario())


def test_a_crashed_attempt_is_reclaimed_as_a_distinct_attempt(tmp_path: Path) -> None:
    """A killed worker leaves its task claimed; the staleness window hands it to the next one."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-crash", name="D2 crash")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="crash",
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                accepted = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="A turn whose worker dies mid-flight.",
                    key="crash-1",
                )
            work_id = ProjectRunId(
                thread_work_id(workspace_id=project.workspace_id, thread_id=thread_id)
            )
            first = await claim_next_task(
                conn,
                kind=FleetTaskKind.AGENT_TURN,
                worker_id="worker-doomed",
                project_run_id=work_id,
            )
            assert first is not None and first.attempts == 1
            # The worker dies here: no finish, no requeue — the claim simply goes stale.
            retry = await claim_next_task(
                conn,
                kind=FleetTaskKind.AGENT_TURN,
                worker_id="worker-takeover",
                project_run_id=work_id,
                stale_after=timedelta(0),
            )
            assert retry is not None
            assert retry.task_id == first.task_id
            # A *distinct* attempt over the same turn — not a second turn, and not a lost one.
            assert retry.attempts == 2
            assert retry.claimed_by == "worker-takeover"
            assert retry.dedup_key == agent_turn_dedup_key(UUID(accepted.json()["data"]["turn_id"]))

    run_async(scenario())


# --- the committed-outcome replay short-circuit ------------------------------------------------


class _RuntimeThatMustNotRun:
    """If a committed turn is executed again, this is what says so."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, **kwargs: Any) -> Any:
        del kwargs
        self.calls += 1
        raise AssertionError("a committed turn must never be executed a second time")


class _ReplayBeforeCompositionEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str]] = []

    async def replay_committed(self, **kwargs: Any) -> Any:
        self.calls.append(
            (
                kwargs["turn_id"],
                kwargs["workspace_id"],
                kwargs["thread_id"],
            )
        )
        return SimpleNamespace(
            outcome=SimpleNamespace(status=AgentExecutionStatus.COMPLETED),
            assistant_message="Committed answer",
            replayed=True,
        )


class _ReplayBeforeCompositionRunner(ProjectConversationTurnRunner):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.completed: list[ExecutionId] = []

    async def _load_scope(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("committed replay must happen before current scope/card composition")

    async def _complete_recipe(
        self, execution_id: ExecutionId, *, turn_id: Any, actor_id: str | None
    ) -> None:
        del turn_id, actor_id
        self.completed.append(execution_id)


def test_worker_replays_before_recipe_or_current_context_composition(tmp_path: Path) -> None:
    """A current vN+1 can never be composed into a committed vN turn retry."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-early-replay", name="D2 early replay")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="early-replay",
            )
            storage = FsStorage(tmp_path / "artifacts")
            app = _app(conn, settings=_settings(), storage=storage)
            async with _client(app) as client:
                accepted = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Replay the already committed answer.",
                    key="early-replay",
                )
            turn_id = UUID(accepted.json()["data"]["turn_id"])
            engine = _ReplayBeforeCompositionEngine()
            runner = _ReplayBeforeCompositionRunner(
                engine=engine,
                executor=None,
                recipes=None,
                starter=None,
                parameters=None,
                conn_factory=conn_session_factory(conn),
                streaming=False,
            )
            result = await runner.run(turn_id=turn_id, workspace_id=project.workspace_id)
            assert result.replayed is True
            assert engine.calls == [(turn_id, project.workspace_id, thread_id)]
            assert runner.completed == [
                ExecutionId(operation_id_from_key(str(turn_id), "project-conversation@1"))
            ]

    run_async(scenario())


def test_the_turn_that_opened_a_leg_replays_as_head_of_abm(tmp_path: Path) -> None:
    """Incident 2026-09-29: the head-of-abm turn that OPENED a design leg was re-claimed after
    its worker died, saw the leg open on its thread, and was routed to the leg — where it
    collided with its own durable rows and failed. Its retry must replay as head-of-abm."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-leg-opener", name="D2 leg opener")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="leg-opener",
            )
            storage = FsStorage(tmp_path / "artifacts")
            app = _app(conn, settings=_settings(), storage=storage)
            async with _client(app) as client:
                accepted = await _submit(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    message="Make a LinkedIn ad for this account.",
                    key="leg-opener",
                )
            turn_id = UUID(accepted.json()["data"]["turn_id"])
            parent_execution_id = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": parent_execution_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "hash": "0" * 64,
                },
            )
            await design_legs.open_leg(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                parent_execution_id=parent_execution_id,
                opened_by_turn_id=turn_id,
            )
            engine = _ReplayBeforeCompositionEngine()
            runner = _ReplayBeforeCompositionRunner(
                engine=engine,
                executor=None,
                recipes=None,
                starter=None,
                parameters=None,
                conn_factory=conn_session_factory(conn),
                streaming=False,
            )
            # No design-leg runner is composed: routing this turn to the leg would raise.
            result = await runner.run(turn_id=turn_id, workspace_id=project.workspace_id)
            assert result.replayed is True
            assert engine.calls == [(turn_id, project.workspace_id, thread_id)]

    run_async(scenario())


def test_a_committed_turn_is_replayed_never_re_executed(tmp_path: Path) -> None:
    """The convergence guarantee, over real durable rows.

    A retried task re-enters the same engine with the same turn. Because the turn already holds an
    authoritative finalization commit, the engine returns *that* outcome and never reaches the
    model — so however many attempts a crash produces, the conversation has one committed answer.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d2-replay-engine", name="D2 replay engine")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="engine",
            )
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=cf,
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            resolved = registry.resolve(
                AgentRole.HEAD_OF_ABM,
                surface=PROJECT_CONVERSATION_SURFACE,
            )
            manifest_ref = await artifacts.persist_body(
                workspace_id=project.workspace_id,
                data=json.dumps(resolved.resource_manifest.model_dump(mode="json")).encode(),
                media_type="application/json",
            )
            message_ref = await artifacts.persist_body(
                workspace_id=project.workspace_id,
                data=b"Already answered.",
                media_type="text/plain",
            )
            turn_id = uuid5(NAMESPACE_URL, "lane-d2:replay:turn")
            execution_id = uuid5(NAMESPACE_URL, "lane-d2:replay:execution")
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": execution_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "hash": "0" * 64,
                },
            )
            constitution = AgentConstitution(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                execution_id=ExecutionId(execution_id),
                actor_id=USER_ID,
                role=AgentRole.HEAD_OF_ABM,
                brand_id=project.brand_id,
                workspace_root_id="root-d2-replay",
                project_card_ref=manifest_ref,
                budget_envelope_ref=manifest_ref,
                profile_ref=resolved.profile_ref,
                resource_manifest_ref=manifest_ref,
                resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                focus_refs=(
                    DomainObjectRef(
                        workspace_id=project.workspace_id,
                        object_type="project",
                        object_id=project.project_id,
                        version=None,
                    ),
                ),
                project_context_artifacts=(
                    ProjectContextArtifact(
                        name="client_knowledge",
                        artifact_ref=manifest_ref,
                        domain_ref=DomainObjectRef(
                            workspace_id=project.workspace_id,
                            object_type="client_knowledge",
                            object_id="client-replay",
                            version=1,
                        ),
                    ),
                    ProjectContextArtifact(
                        name="stage0_project_state",
                        artifact_ref=manifest_ref,
                        domain_ref=DomainObjectRef(
                            workspace_id=project.workspace_id,
                            object_type="stage0_project_state",
                            object_id=project.project_id,
                            version=None,
                        ),
                    ),
                ),
                client_entity_id="client-replay",
            )
            request = AgentTurnRequest(
                turn_id=turn_id,
                thread_id=thread_id,
                constitution=constitution,
                user_message_artifact_ref=message_ref,
                requested_at=NOW_UTC,
            )
            turns = DbAgentTurnJournal(conn_factory=cf)
            await turns.create(
                request=request,
                profile=resolved.profile,
                submitted_by_user_id=USER_ID,
                submitted_via_membership_id=f"{MEMBERSHIP_ID}-{project.workspace_id}",
            )
            context_refs = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM agent_artifact_ref "
                            "WHERE turn_id=:turn_id AND owner_kind='context' "
                            "AND owner_id=:turn_id AND ref_role='context_materialization'"
                        ),
                        {"turn_id": turn_id},
                    )
                ).scalar_one()
            )
            assert context_refs == len(constitution.project_context_artifacts)

            # The committed outcome of the *first* attempt: an envelope artifact, its finalization,
            # and the immutable commit that makes it authoritative.
            answer_ref = await artifacts.persist_body(
                workspace_id=project.workspace_id,
                data=b"Here is the answer.",
                media_type="text/plain",
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid5(NAMESPACE_URL, "lane-d2:replay:finalization"),
                execution_id=ExecutionId(execution_id),
                status=FinalizeStatus.COMPLETED,
                user_message_artifact_ref=answer_ref,
                finalized_at=NOW_UTC,
            )
            await turns.record_finalization(
                turn_id=turn_id,
                workspace_id=project.workspace_id,
                envelope=envelope,
            )
            envelope_ref = await artifacts.persist_body(
                workspace_id=project.workspace_id,
                data=envelope.model_dump_json().encode(),
                media_type="application/json",
            )
            await turns.commit_finalization_authority(
                turn_id=turn_id,
                workspace_id=project.workspace_id,
                envelope=envelope,
                envelope_ref=envelope_ref,
            )

            runtime = _RuntimeThatMustNotRun()
            engine = ConversationTurnEngine(
                surface=PROJECT_CONVERSATION_SURFACE,
                resolved=resolved,
                components=SimpleNamespace(  # type: ignore[arg-type]
                    artifacts=artifacts,
                    turns=turns,
                    history=DbAgentHistoryStore(conn_factory=cf),
                ),
                tools=ToolRegistry(),
                tool_invoker=None,  # type: ignore[arg-type]
                executor=None,  # type: ignore[arg-type]
                compatibility=None,  # type: ignore[arg-type]
                contexts=None,  # type: ignore[arg-type]
                runtime=runtime,  # type: ignore[arg-type]
                captured_turns=None,  # type: ignore[arg-type]
                plans=None,  # type: ignore[arg-type]
                conn_factory=cf,
            )
            early = await engine.replay_committed(
                turn_id=turn_id,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=thread_id,
                actor_id=USER_ID,
                user_message_artifact_ref=message_ref,
            )
            assert early is not None
            assert early.replayed is True
            assert early.assistant_message == "Here is the answer."
            result = await engine.execute(
                request=request,
                lease=None,  # type: ignore[arg-type]
                budget_limit_millicents=1,
            )
            assert runtime.calls == 0
            assert result.replayed is True
            assert result.outcome.status is AgentExecutionStatus.COMPLETED
            assert result.assistant_message == "Here is the answer."
            # Exactly one authoritative outcome, and the transcript is not duplicated by the replay.
            commits = (
                await conn.execute(
                    text("SELECT count(*) FROM agent_finalization_commit WHERE turn_id = :turn"),
                    {"turn": turn_id},
                )
            ).scalar_one()
            assert int(commits) == 1
            messages = (
                await conn.execute(
                    text(
                        "SELECT role FROM agent_thread_message "
                        "WHERE workspace_id = :ws AND thread_id = :thread ORDER BY sequence"
                    ),
                    {"ws": project.workspace_id, "thread": thread_id},
                )
            ).scalars()
            assert list(messages) == ["user", "assistant"]

    run_async(scenario())


# --- a failed turn tells the person (2026-10-22): one ``turn.failed``, from the owner only ----


async def _turn_endings(conn: Any, *, workspace_id: str, thread_id: str) -> list[dict[str, Any]]:
    rows = (
        await conn.execute(
            text(
                "SELECT turn_id, event_type, payload FROM agent_turn_event_stream "
                "WHERE workspace_id = :ws AND thread_id = :thread AND event_type IN "
                "('turn.completed', 'turn.failed', 'turn.cancelled', 'turn.awaiting_input') "
                "ORDER BY sequence"
            ),
            {"ws": workspace_id, "thread": thread_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def _one_failing_turn(conn: Any, tmp_path: Path, label: str) -> tuple[Any, str]:
    project = await _seed(conn, f"ws-d2-{label}", name=f"D2 {label}")
    thread_id = await _thread(
        conn, workspace_id=project.workspace_id, project_id=project.project_id, label=label
    )
    app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
    async with _client(app) as client:
        response = await _submit(
            client,
            workspace_id=project.workspace_id,
            project_id=project.project_id,
            thread_id=thread_id,
            message="this turn fails",
            key=f"{label}-1",
        )
        assert response.status_code == 202
    return project, thread_id


def test_a_failed_turn_ends_with_one_turn_failed_event(tmp_path: Path) -> None:
    """Without it the person sees the reasoning stop and nothing else, even after a reload; the
    chat already renders a code-less ``turn.failed`` as "Response failed"."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id = await _one_failing_turn(conn, tmp_path, "ends-failed")
            await _handle_next(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                runner=_RecordingRunner(fail=True),
            )
            endings = await _turn_endings(
                conn, workspace_id=project.workspace_id, thread_id=thread_id
            )
            assert [row["event_type"] for row in endings] == ["turn.failed"]
            assert "failure_code" not in decode_jsonb(endings[0]["payload"])

    run_async(scenario())


class _FencedOutQueue(_ConnWorkQueue):
    """Another worker took the task over while this attempt ran: its finish is refused."""

    async def finish(self, **kwargs: Any) -> bool:
        del kwargs
        return False


def test_a_fenced_out_failed_attempt_writes_no_ending(tmp_path: Path) -> None:
    """A stale worker must never paint "failed" over a takeover that may still succeed."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id = await _one_failing_turn(conn, tmp_path, "fenced-out")
            await _handle_next(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                runner=_RecordingRunner(fail=True),
                queue=_FencedOutQueue(conn),
            )
            assert (
                await _turn_endings(conn, workspace_id=project.workspace_id, thread_id=thread_id)
                == []
            )

    run_async(scenario())


class _EndsThenFails:
    """A run that writes its own ending (as the missing-context path does) and then raises."""

    def __init__(self, conn: Any, *, project_id: str, thread_id: str) -> None:
        self._conn = conn
        self._project_id = project_id
        self._thread_id = thread_id

    async def run(self, *, turn_id: UUID, workspace_id: str, fence: Any = None) -> Any:
        del fence
        await emit_turn_event(
            self._conn,
            workspace_id=workspace_id,
            project_id=self._project_id,
            thread_id=self._thread_id,
            turn_id=turn_id,
            event_type=TurnEventType.TURN_FAILED,
            payload={"status": "failed", "failure_code": "required_context_artifact_missing"},
        )
        raise RuntimeError("required turn context is no longer available")


def test_a_turn_that_already_ended_is_not_ended_twice(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id = await _one_failing_turn(conn, tmp_path, "ended-once")
            await _handle_next(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                runner=_EndsThenFails(  # type: ignore[arg-type]
                    conn, project_id=project.project_id, thread_id=thread_id
                ),
            )
            endings = await _turn_endings(
                conn, workspace_id=project.workspace_id, thread_id=thread_id
            )
            assert [row["event_type"] for row in endings] == ["turn.failed"]
            assert decode_jsonb(endings[0]["payload"])["failure_code"] == (
                "required_context_artifact_missing"
            )

    run_async(scenario())
