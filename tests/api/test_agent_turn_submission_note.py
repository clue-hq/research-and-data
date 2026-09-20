"""A per-ref annotation is captured with the submission and survives replay and re-offer.

The web editor lets a marketer annotate one element on the page and send the annotated selection
to chat. What this suite pins:

* the note reaches the durable ``agent_turn_submission_context_ref`` row through the real HTTP
  submit route, in the ref's own position, and never leaks onto its neighbours;
* both readers return it — the single-turn rehydration the design worker uses and the batched
  transcript reader — so a replayed turn is composed against the same words;
* the out-of-scope leg-close **re-offer** (which reads a turn's refs and re-inserts them under a
  derived identity) carries the note across, including on a clone-scoped ``{node}#{path}`` id;
* the note is part of the submission's identity: an identical resubmit replays, and the same
  idempotency key with different words is refused rather than silently keeping the first note.

DB-backed and rollback-only, per ``tests/api`` conventions; the submitter is a real seeded
``platform_user`` + ``workspace_membership``, because the submission row has FKs onto both.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.agent_turn_submission import (
    insert_submission,
    submission_context_refs,
    submission_context_refs_for_turns,
)
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_config import Settings, load_settings
from clue_design import legs as design_legs
from clue_design.documents import create_document
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

USER_ID = "usr_note_test"
MEMBERSHIP_ID = "wsm_note_test"
_AUTHENTICATED_AT = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)

NOTE = "1. Make this shorter"


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


async def _seed(conn: Any, workspace_id: str, *, name: str) -> Any:
    project = await _seed_project_row(conn, workspace_id, name=name)
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
    )
    return project


async def _thread(conn: Any, *, workspace_id: str, project_id: str, label: str) -> str:
    thread_id = f"thr_note_{label}"
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


async def _open_design_leg(conn: Any, *, workspace_id: str, project_id: str, thread_id: str) -> str:
    """A scene document at a known version, with a leg open on the thread."""

    document = await create_document(
        conn,
        workspace_id=workspace_id,
        scene={
            "schema_version": 1,
            "meta": {"id": "doc_note_targets", "title": "Landing page"},
            "pages": {"page_web": {"id": "page_web", "children": ["frame"]}},
            "nodes": {
                "frame": {"id": "frame", "children": ["headline", "subhead"]},
                "headline": {"id": "headline", "children": []},
                "subhead": {"id": "subhead", "children": []},
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
        {"document": document["id"], "workspace": workspace_id},
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
            "workspace": workspace_id,
            "project": project_id,
            "hash": "0" * 64,
        },
    )
    leg = await design_legs.open_leg(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        parent_execution_id=parent_execution_id,
        document_id=document["id"],
        document_version_guard=4,
    )
    # Spec §3.2: project containment is derived from the leg's document SET, and the shipped
    # tool writes the position-0 child row for every leg it opens. The DAL writes only the
    # column, so the seed adds what production guarantees — without it the document belongs
    # to no project and the annotated ref is refused.
    await design_legs.add_leg_documents(
        conn,
        workspace_id=workspace_id,
        leg_id=str(leg["id"]),
        documents=[design_legs.LegDocumentSpec(document_id=str(document["id"]), position=0)],
    )
    return str(document["id"])


def test_an_annotated_ref_is_captured_read_back_and_re_offered_with_its_note(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-ref-note", name="Annotated refs")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="annotated",
            )
            document_id = await _open_design_leg(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=thread_id,
            )
            request = {
                "message": "Apply my notes.",
                "context_refs": [
                    {"object_type": "design_document", "object_id": document_id, "version": 4},
                    {
                        "object_type": "design_node",
                        "object_id": "headline",
                        "version": 4,
                        "note": NOTE,
                    },
                    {"object_type": "design_node", "object_id": "subhead", "version": 4},
                ],
            }
            headers = {
                "X-Workspace-Id": project.workspace_id,
                "Idempotency-Key": "note-first-submit",
            }
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "artifacts"))
            async with _client(app) as client:
                accepted = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json=request,
                    headers=headers,
                )
                assert accepted.status_code == 202, accepted.text
                turn_id = UUID(accepted.json()["data"]["turn_id"])

                # The note reached the durable row, in its own ref's position only.
                durable = await submission_context_refs(
                    conn,
                    workspace_id=project.workspace_id,
                    turn_id=turn_id,
                )
                assert [(ref.object_type, ref.object_id, ref.note) for ref in durable] == [
                    ("design_document", document_id, None),
                    ("design_node", "headline", NOTE),
                    ("design_node", "subhead", None),
                ]

                # The batched transcript reader tells the same story.
                batched = await submission_context_refs_for_turns(
                    conn,
                    workspace_id=project.workspace_id,
                    turn_ids=[turn_id],
                )
                assert batched[turn_id] == durable

                # An identical resubmit is a replay, not a conflict.
                replay = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json=request,
                    headers=headers,
                )
                assert replay.status_code == 202, replay.text
                assert replay.json()["data"]["replayed"] is True

                # The same identity with different words is refused: the note is part of what
                # was submitted, so silently keeping the first one would misquote the human.
                reworded = [dict(ref) for ref in request["context_refs"]]
                reworded[1]["note"] = "1. Make this longer"
                conflict = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    json={**request, "context_refs": reworded},
                    headers=headers,
                )
                assert conflict.status_code == 409, conflict.text
                assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

            # The out-of-scope leg close re-offers the captured refs under a derived turn id.
            # It reads them with the same reader and re-inserts them verbatim; a clone-scoped
            # element id is opaque here, so the note must survive it unchanged.
            submission = await conn.execute(
                text(
                    "SELECT project_id, thread_id, submitted_by_user_id, "
                    "submitted_via_membership_id, onboarding_input_id, message_artifact_key, "
                    "message_sha256 FROM agent_turn_submission "
                    "WHERE turn_id = :turn AND workspace_id = :workspace"
                ),
                {"turn": turn_id, "workspace": project.workspace_id},
            )
            original = dict(submission.mappings().one())
            clone_scoped = durable[1].model_copy(
                update={"object_id": "frg_a#:nth-child(2)", "note": NOTE}
            )
            redelivered_id = uuid4()
            _row, created = await insert_submission(
                conn,
                turn_id=redelivered_id,
                workspace_id=project.workspace_id,
                project_id=str(original["project_id"]),
                thread_id=str(original["thread_id"]),
                submitted_by_user_id=str(original["submitted_by_user_id"]),
                submitted_via_membership_id=str(original["submitted_via_membership_id"]),
                onboarding_input_id=original["onboarding_input_id"],
                message_artifact_key=str(original["message_artifact_key"]),
                message_sha256=str(original["message_sha256"]),
                idempotency_key=f"design-leg-redelivery:{turn_id}",
                context_refs=(durable[0], clone_scoped),
            )
            assert created is True
            re_offered = await submission_context_refs(
                conn,
                workspace_id=project.workspace_id,
                turn_id=redelivered_id,
            )
            assert [(ref.object_id, ref.note) for ref in re_offered] == [
                (document_id, None),
                ("frg_a#:nth-child(2)", NOTE),
            ]

    run_async(scenario())
