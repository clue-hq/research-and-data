"""Lane D slice D3: the turn stream, end to end (charter §§3.2-3.6, ratified §6-D2).

The charter is explicit that this "is not a superficial 'received some SSE' test" (§5), so this
suite proves the properties rather than the plumbing:

* **genuine streaming** — the first delta is durable *while the model is still generating*, proved
  by a fake provider whose later chunks refuse to be produced until that delta has landed. A
  post-hoc animation of a completed string cannot pass this test; it deadlocks.
* **byte equality** — the deltas the outbox actually holds, joined, are byte-identical to the
  durable assistant message, and a mismatch resets the stream instead of rewriting the turn.
* **attempt isolation** — a crash mid-generation and the retry that follows use different part
  identities, and the dead attempt's open parts are explicitly reset. Deltas of two generations are
  never joined.
* **reconnect** — a disconnect at *every* event boundary followed by a cursor replay reconstructs
  the same stream exactly once; duplicate delivery deduplicates on ``event_id``; a cursor past the
  retention horizon resets to zero rather than tailing from a cursor that matches nothing.
* **the negatives** — no provider content token, no surrounding finalize JSON, and no other tool's
  arguments reach the wire.
* **the controls** — stop cancels one attempt and can never look like a finished message; retry is
  a new turn and never mutates the prior transcript.
* **the inherited follow-ups** — queued submissions are visible in the union read, a stranded
  thread heals, and the hydrated cold-load read is correct and bounded.

DB-backed and rollback-only per ``tests/api`` conventions; every submitter is a real Lane B
``platform_user`` + ``workspace_membership`` (``tests/_identity``), because D3's control rows carry
foreign keys onto both.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from sqlalchemy import text

from clue_api.agent_turn_fleet_wiring import (
    REQUIRED_CONTEXT_ARTIFACT_MISSING,
    ProjectConversationTurnRunner,
    RequiredTurnArtifactMissing,
    TurnStopped,
    sweep_thread_dispatch,
    sweep_turn_stream_retention,
)
from clue_api.agent_turn_submission import (
    AGENT_TURN_DEDUP_PREFIX,
    agent_turn_dedup_key,
    dispatch_next_thread_turn,
    insert_submission,
    thread_work_id,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.chat.finalize_stream import FINALIZE_TOOL_NAME
from clue_api.chat.interrupted_turn import commit_interrupted_turn
from clue_api.chat.schemas import thread_status
from clue_api.chat.turn_controls import get_control_request, stop_requested
from clue_api.chat.turn_events import (
    TURN_EVENT_TYPES,
    TurnEventRow,
    TurnEventType,
    emit_turn_event,
    list_turn_events,
    prune_turn_events,
)
from clue_api.chat.turn_parts import PartKind, ToolPartState
from clue_api.chat.turn_stream import (
    TurnStreamCallbackHandler,
    TurnStreamEmitter,
    TurnStreamPolicy,
)
from clue_api.conversation_capture import persist_user_turn
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_config import Settings, load_settings
from clue_core import ProjectRunId
from clue_db import db_lifespan
from clue_fleet import FleetTaskKind, FleetTaskStatus, claim_next_task, finish_task
from clue_projections import (
    AGENT_TURN_TASK_DEDUP_PREFIX,
    thread_turns,
    threads_running,
)
from clue_storage import ArtifactNotFound, FsStorage, StorageError
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

USER_ID = "usr_d3_test"
MEMBERSHIP_ID = "wsm_d3_test"
#: The moment the injected test principal "authenticated". A fixed instant, because the Lane B
#: principal records when the session was proved and a test must not depend on wall clock.
_AUTHENTICATED_AT = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


# --- harness ------------------------------------------------------------------------------------


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
    thread_id = f"thr_d3_{label}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": thread_id, "workspace": workspace_id, "project": project_id, "user": USER_ID},
    )
    return thread_id


async def _submit_turn(
    conn: Any,
    *,
    project: Any,
    thread_id: str,
    message: str,
    key: str,
    storage: Any,
    dispatch: bool = True,
) -> UUID:
    """Capture + record one submission exactly the way the production route does."""

    turn_id = turn_id_for_submission(
        workspace_id=project.workspace_id, thread_id=thread_id, idempotency_key=key
    )
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    captured = await persist_user_turn(
        conn,
        artifacts=artifacts,
        workspace_id=project.workspace_id,
        brand_id=project.brand_id,
        product_id=project.product_id,
        project_id=project.project_id,
        turn_id=turn_id,
        message=message,
    )
    await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"{MEMBERSHIP_ID}-{project.workspace_id}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=key,
    )
    if dispatch:
        await dispatch_next_thread_turn(
            conn, workspace_id=project.workspace_id, thread_id=thread_id
        )
    return turn_id


def _app(conn: Any, *, settings: Settings, storage: Any, live_tail: bool = False) -> Any:
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
        chat_stream_live_tail=live_tail,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _agent_turn_row(conn: Any, *, project: Any, thread_id: str, turn_id: UUID) -> None:
    """The ``agent_turn`` row the worker writes — the half a durable thread message hangs off.

    Written by hand here (execution + manifest artifact + turn) because the real writer needs the
    whole agent plane, and this suite is about the *stream*, not about composing a model.
    """

    execution_id = uuid4()
    manifest_key = f"{project.workspace_id}/{'0' * 64}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'application/json', 2) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": manifest_key, "ws": project.workspace_id, "sha": "0" * 64},
    )
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "ws": project.workspace_id,
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
            " retention_class, requested_at, submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :ws, :project, :thread, :actor, 'head_of_abm', "
            " :root, 'head-of-abm', 'v22', :sha, :key, :sha, :sha, 'standard', now(), "
            " :user, :membership)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "actor": USER_ID,
            "root": f"root-{turn_id}",
            "sha": "0" * 64,
            "key": manifest_key,
            "user": USER_ID,
            "membership": f"{MEMBERSHIP_ID}-{project.workspace_id}",
        },
    )


async def _emitter(
    conn: Any,
    *,
    project: Any,
    thread_id: str,
    turn_id: UUID,
    policy: TurnStreamPolicy | None = None,
) -> TurnStreamEmitter:
    return await TurnStreamEmitter.open(
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        conn_factory=conn_session_factory(conn),
        # Zero-length batching: every delta is its own frame, so the ordering and boundary
        # assertions below are about the mechanism and not about a buffer's timing.
        policy=policy or TurnStreamPolicy(batch_max_chars=1, batch_interval_s=0.0),
    )


async def _frames(conn: Any, *, workspace_id: str, turn_id: UUID) -> list[Any]:
    return list(await list_turn_events(conn, workspace_id=workspace_id, turn_id=turn_id))


def _of_type(frames: list[Any], event_type: TurnEventType) -> list[Any]:
    return [frame for frame in frames if frame.event_type == event_type.value]


def test_turn_event_sequence_allocator_serializes_concurrent_emitters() -> None:
    """Legitimate emitters for one generation must never race on ``max(sequence) + 1``."""

    async def scenario() -> None:
        schema = f"turn_event_lock_{uuid4().hex}"
        turn_id = uuid4()
        async with db_lifespan() as engine:
            try:
                async with engine.begin() as conn:
                    # A private clone lets independent committed transactions exercise the exact
                    # production SQL without leaving turn/workspace fixtures in the shared test
                    # database. LIKE does not copy foreign keys; it does copy the per-turn unique
                    # index and the wire-shape constraints this test needs.
                    await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                    await conn.execute(
                        text(
                            f'CREATE TABLE "{schema}".agent_turn_event_stream '
                            "(LIKE public.agent_turn_event_stream INCLUDING ALL)"
                        )
                    )

                async def append(index: int) -> TurnEventRow:
                    async with engine.begin() as conn:
                        await conn.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
                        return await emit_turn_event(
                            conn,
                            workspace_id="ws_turn_event_lock",
                            project_id="prj_turn_event_lock",
                            thread_id="thr_turn_event_lock",
                            turn_id=turn_id,
                            event_type=TurnEventType.PART_UPDATED,
                            part_id=f"part:{index}",
                            part_kind=PartKind.AGENT_ACTIVITY.value,
                            payload={"index": index},
                        )

                rows = await asyncio.gather(*(append(index) for index in range(32)))
                assert sorted(row.sequence for row in rows) == list(range(1, 33))
                assert len({row.event_id for row in rows}) == 32

                async with engine.begin() as conn:
                    count, minimum, maximum = (
                        await conn.execute(
                            text(
                                f'SELECT count(*), min(sequence), max(sequence) FROM "{schema}".'
                                "agent_turn_event_stream WHERE turn_id=:turn_id"
                            ),
                            {"turn_id": turn_id},
                        )
                    ).one()
                assert (count, minimum, maximum) == (32, 1, 32)
            finally:
                async with engine.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

    run_async(scenario())


class _FakeStreamingModel(BaseChatModel):
    """A provider that streams a ``finalize_turn`` tool call in fragments.

    Its second chunk *waits* for a signal the test only sets once the first delta is durable. That
    is what makes "genuine token streaming" testable rather than assertable: an implementation that
    animated a finished string would never set the signal, and this model would never finish.
    """

    fragments: list[str]
    gate: Any = None
    content_tokens: list[str] = []
    decoy_tool: str | None = None

    @property
    def _llm_type(self) -> str:
        return "fake-streaming"

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        raise AssertionError("the streaming path must be taken when a turn stream is attached")

    async def _astream(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        del messages, stop, run_manager, kwargs
        for token in self.content_tokens:
            # Provider prose *outside* the finalize argument: the negative assertion's bait.
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))
        if self.decoy_tool is not None:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": self.decoy_tool,
                            "args": '{"user_message": "a decoy argument"}',
                            "id": "call_decoy",
                            "index": 9,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )
        for position, fragment in enumerate(self.fragments):
            if position == 1 and self.gate is not None:
                await asyncio.wait_for(self.gate.wait(), timeout=5.0)
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": FINALIZE_TOOL_NAME if position == 0 else None,
                            "args": fragment,
                            "id": "call_finalize" if position == 0 else None,
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )


# --- genuine streaming (§3.3(1), ratified §6-D2) ------------------------------------------------


def test_the_first_delta_is_durable_while_the_model_is_still_generating(tmp_path: Path) -> None:
    """The ratified requirement, proved by construction rather than by assertion.

    The provider will not produce its second fragment until the test has seen delta ``0`` in the
    outbox. If deltas were written after generation finished — a replay, an animation, a batch
    flushed at ``on_llm_end`` — the model would wait forever and this test would time out.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-first", name="D3 first delta")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="fst"
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-first",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()

            gate = asyncio.Event()

            async def _watch_for_the_first_delta() -> None:
                for _ in range(200):
                    frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
                    if _of_type(frames, TurnEventType.TEXT_DELTA):
                        gate.set()
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError("no delta was durable while the model was still generating")

            model = _FakeStreamingModel(
                fragments=['{"user_message": "Hel', "lo, ", 'world"}'],
                gate=gate,
            )
            watcher = asyncio.create_task(_watch_for_the_first_delta())
            await model.ainvoke(
                [("human", "hi")],
                config={"callbacks": [TurnStreamCallbackHandler(emitter=emitter)]},
            )
            await watcher

            assert emitter.emission_failures == []
            reconciled = await emitter.reconcile_text(assistant_message="Hello, world")
            assert reconciled is True

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            deltas = _of_type(frames, TurnEventType.TEXT_DELTA)
            # More than one frame: the text really arrived in pieces, in order, indexed.
            assert len(deltas) > 1
            assert [frame.delta_index for frame in deltas] == list(range(len(deltas)))
            assert "".join(str(frame.payload["delta"]) for frame in deltas) == "Hello, world"
            starts = _of_type(frames, TurnEventType.TEXT_START)
            ends = _of_type(frames, TurnEventType.TEXT_END)
            assert len(starts) == 1 and len(ends) == 1
            # A consumer must see text.start before any delta and exactly one text.end after them.
            assert starts[0].event_id < deltas[0].event_id < ends[0].event_id

    run_async(scenario())


def test_no_provider_content_or_surrounding_json_reaches_the_wire(tmp_path: Path) -> None:
    """§3.3's closing rule, as a durable-row assertion over the whole stream.

    The provider emits plain content tokens (what a chatty or reasoning-leaking model produces) and
    a *second* tool call whose arguments happen to contain a ``user_message`` field. Neither may
    appear anywhere in the outbox.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-leak", name="D3 leak")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="lk"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-leak",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            model = _FakeStreamingModel(
                fragments=[
                    '{"status": "completed", "user_message": "Th',
                    'e answer.", "domain_refs": [{"object_id": "prj_secret"}]}',
                ],
                content_tokens=[
                    "Let me think about this step by step. ",
                    "The user probably wants ",
                ],
                decoy_tool="draft_account_research_directive",
            )
            await model.ainvoke(
                [("human", "hi")],
                config={"callbacks": [TurnStreamCallbackHandler(emitter=emitter)]},
            )
            assert emitter.emission_failures == []

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            deltas = _of_type(frames, TurnEventType.TEXT_DELTA)
            assert "".join(str(frame.payload["delta"]) for frame in deltas) == "The answer."
            # Nothing else, anywhere in the stream: not the reasoning-shaped content tokens, not
            # the surrounding JSON, not the other call's arguments.
            whole = json.dumps([frame.envelope() for frame in frames])
            for forbidden in (
                "step by step",
                "The user probably wants",
                "a decoy argument",
                "prj_secret",
                "domain_refs",
            ):
                assert forbidden not in whole, forbidden
            # And no delta ever carries JSON syntax from the document it was decoded out of.
            for frame in deltas:
                delta = str(frame.payload["delta"])
                assert not any(character in delta for character in '{}[]"'), delta

    run_async(scenario())


# --- byte equality and reconciliation (§3.3(5)) -------------------------------------------------


def test_a_reconciliation_mismatch_resets_the_stream_and_never_rewrites_the_turn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-recon", name="D3 reconcile")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="rc"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-recon",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="what the stream said")

            # The durable message says something else — a projection fault, however it arose.
            assert (
                await emitter.reconcile_text(assistant_message="what the turn committed") is False
            )

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            assert _of_type(frames, TurnEventType.TEXT_END) == []
            resets = _of_type(frames, TurnEventType.STREAM_RESET)
            assert len(resets) == 1
            assert resets[0].payload["reason"] == "delta_reconciliation_mismatch"
            assert resets[0].payload["rehydrate"] == "message"
            part_resets = _of_type(frames, TurnEventType.PART_RESET)
            assert [frame.part_kind for frame in part_resets] == [PartKind.TEXT.value]

    run_async(scenario())


def test_byte_equality_holds_for_multibyte_and_markdown_messages(tmp_path: Path) -> None:
    """The join is compared on **UTF-8 bytes**, from the rows the outbox actually holds."""

    async def scenario() -> None:
        message = "## Résumé\n\n- 日本語 😀\n- `code`\n"
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-bytes", name="D3 bytes")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="by"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-bytes",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            model = _FakeStreamingModel(
                fragments=[
                    json.dumps({"user_message": message})[index : index + 3]
                    for index in range(0, len(json.dumps({"user_message": message})), 3)
                ]
            )
            await model.ainvoke(
                [("human", "hi")],
                config={"callbacks": [TurnStreamCallbackHandler(emitter=emitter)]},
            )
            assert await emitter.reconcile_text(assistant_message=message) is True

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            deltas = _of_type(frames, TurnEventType.TEXT_DELTA)
            joined = "".join(str(frame.payload["delta"]) for frame in deltas)
            assert joined.encode() == message.encode()
            end = _of_type(frames, TurnEventType.TEXT_END)[0]
            assert end.payload["byte_count"] == len(message.encode())

    run_async(scenario())


def test_an_empty_assistant_message_still_starts_and_ends_its_part(tmp_path: Path) -> None:
    """``{"user_message": ""}`` is a message. It streams zero deltas and still reconciles."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-empty", name="D3 empty")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="em"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-empty",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            model = _FakeStreamingModel(fragments=['{"user_message": ', '""}'])
            await model.ainvoke(
                [("human", "hi")],
                config={"callbacks": [TurnStreamCallbackHandler(emitter=emitter)]},
            )
            # No delta was produced, so there is no text part to reconcile — and the durable
            # message is empty too, which is the only case where "no stream" is faithful.
            assert await emitter.reconcile_text(assistant_message="") is True
            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            assert _of_type(frames, TurnEventType.TEXT_DELTA) == []
            assert _of_type(frames, TurnEventType.STREAM_RESET) == []

    run_async(scenario())


def test_malformed_streamed_arguments_stop_the_deltas_and_reset_the_projection(
    tmp_path: Path,
) -> None:
    """§5's "malformed streamed tool arguments", end to end.

    The parser fails closed, so the stream stops mid-message; reconciliation then catches the
    divergence from the durable text and tells consumers to re-fetch it. Nothing invents the rest
    of the sentence, and the turn's committed outcome is untouched.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-bad", name="D3 malformed")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="bx"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-bad",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            model = _FakeStreamingModel(
                fragments=['{"user_message": "good so far', ' then \\q broken", "x": 1}']
            )
            await model.ainvoke(
                [("human", "hi")],
                config={"callbacks": [TurnStreamCallbackHandler(emitter=emitter)]},
            )
            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            deltas = _of_type(frames, TurnEventType.TEXT_DELTA)
            streamed = "".join(str(frame.payload["delta"]) for frame in deltas)
            assert streamed == "good so far then "
            assert "\\q" not in streamed and "broken" not in streamed

            assert await emitter.reconcile_text(assistant_message="good so far then  broken") is (
                False
            )
            after = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            assert _of_type(after, TurnEventType.TEXT_END) == []
            assert len(_of_type(after, TurnEventType.STREAM_RESET)) == 1

    run_async(scenario())


def test_an_outbox_failure_is_counted_and_never_raised_into_the_turn(tmp_path: Path) -> None:
    """§3-P4's absolute rule: stream loss never changes the durable outcome.

    A transport that cannot write must not be able to end a turn, so every emission is best-effort
    and failures are *counted* rather than raised — which is also why the happy-path tests assert
    ``emission_failures == []`` instead of trusting silence.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-lossy", name="D3 lossy")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="lo"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-lossy",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)

            class _BrokenFactory:
                def __call__(self) -> Any:
                    raise RuntimeError("the outbox is unreachable")

            emitter._conn_factory = _BrokenFactory()  # type: ignore[assignment]
            await emitter.turn_started()
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="anything")
            await emitter.turn_finished(status="completed")
            assert len(emitter.emission_failures) >= 3
            assert all("RuntimeError" in failure for failure in emitter.emission_failures)

    run_async(scenario())


# --- attempts, resets and retries (§3.3(6)) -----------------------------------------------------


def test_worker_death_after_partial_text_opens_a_distinct_attempt_without_splicing(
    tmp_path: Path,
) -> None:
    """A crashed attempt is closed, not continued.

    The second attempt gets a new id and new part ids, and the dead attempt's open text part is
    explicitly ``part.reset`` *before* ``turn.retrying`` — so no consumer can concatenate the two
    continuations into one message.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-crash", name="D3 crash")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="cr"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-crash",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            first = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await first.turn_started()
            await first.text_delta(round_ordinal=1, call_index=0, delta="half a sen")
            # ... and the worker dies here: no text.end, no terminal event.

            second = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await second.turn_started()
            await second.text_delta(round_ordinal=1, call_index=0, delta="the whole answer")
            assert await second.reconcile_text(assistant_message="the whole answer") is True

            assert second.attempt_ordinal == 2
            assert second.generation_attempt_id != first.generation_attempt_id

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            reset = _of_type(frames, TurnEventType.PART_RESET)
            retrying = _of_type(frames, TurnEventType.TURN_RETRYING)
            assert len(reset) == 1 and len(retrying) == 1
            assert reset[0].payload["reason"] == "generation_attempt_superseded"
            # Ordering is the contract: void the old cards before announcing the new generation.
            assert reset[0].event_id < retrying[0].event_id
            assert retrying[0].payload["superseded_attempt_id"] == str(first.generation_attempt_id)

            # The two attempts' deltas live on different parts and are never joined.
            deltas = _of_type(frames, TurnEventType.TEXT_DELTA)
            parts = {frame.part_id for frame in deltas}
            assert len(parts) == 2
            end = _of_type(frames, TurnEventType.TEXT_END)
            assert len(end) == 1
            assert end[0].generation_attempt_id == second.generation_attempt_id

    run_async(scenario())


def test_a_repaired_finalize_call_resets_the_superseded_text_part(tmp_path: Path) -> None:
    """Multiple model rounds: a rejected ``finalize_turn`` is repaired by a *second* call, whose
    prose is a different continuation — so the first call's part is reset, not extended."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-repair", name="D3 repair")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="rp"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-repair",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.round_started(round_ordinal=1)
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="first try")
            await emitter.round_finished(round_ordinal=1, requested_tool_calls=1)
            await emitter.round_started(round_ordinal=2)
            await emitter.text_delta(round_ordinal=2, call_index=0, delta="repaired answer")
            await emitter.round_finished(round_ordinal=2, requested_tool_calls=1)
            assert await emitter.reconcile_text(assistant_message="repaired answer") is True

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            resets = _of_type(frames, TurnEventType.PART_RESET)
            assert len(resets) == 1
            assert resets[0].payload["reason"] == "finalize_call_superseded"
            starts = _of_type(frames, TurnEventType.TEXT_START)
            assert len({frame.part_id for frame in starts}) == 2
            # Reconciliation only ever judges the surviving part.
            end = _of_type(frames, TurnEventType.TEXT_END)[0]
            assert end.part_id == starts[-1].part_id
            # Two rounds, two safe reasoning cards; no model text on either.
            reasoning = [
                frame
                for frame in frames
                if frame.part_kind == PartKind.REASONING.value
                and frame.event_type == TurnEventType.PART_COMPLETED.value
            ]
            assert len(reasoning) == 2
            assert all("text" not in json.dumps(frame.payload) for frame in reasoning)

    run_async(scenario())


# --- tool parts project durable receipts (§3.4) -------------------------------------------------


def test_tool_parts_carry_the_lifecycle_and_the_durable_receipt(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-tool", name="D3 tool")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="tl"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-tool",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            operation_id = uuid4()
            await emitter.tool_started(
                node_key="agent_create_thread_abc",
                tool_name="create_thread",
                tool_version="1",
                tool_call_id="call_1",
                arguments={"project_id": project.project_id},
            )
            await emitter.tool_finished(
                node_key="agent_create_thread_abc",
                tool_name="create_thread",
                tool_version="1",
                tool_call_id="call_1",
                operation_id=operation_id,
                output={"node_key": "agent_create_thread_abc", "status": "completed"},
            )
            # A refused call is still a call: its card opens at ``input-available`` (the plan was
            # proposed) and then fails, exactly as the governed tool path emits it.
            await emitter.tool_started(
                node_key="agent_other_def",
                tool_name="other_tool",
                tool_version="2",
                tool_call_id="call_2",
                arguments={},
            )
            await emitter.tool_failed(
                node_key="agent_other_def",
                tool_name="other_tool",
                tool_version="2",
                tool_call_id="call_2",
                error_code="plan_rejected",
                reasons=("steps.0: c5_tool_not_allowed: not on this surface",),
            )

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            tools = [frame for frame in frames if frame.part_kind == PartKind.TOOL.value]
            created = [f for f in tools if f.event_type == TurnEventType.PART_CREATED.value]
            completed = [f for f in tools if f.event_type == TurnEventType.PART_COMPLETED.value]
            failed = [f for f in tools if f.event_type == TurnEventType.PART_FAILED.value]
            assert len(created) == 2 and len(completed) == 1 and len(failed) == 1

            # The part id derives from the durable plan-operation node key, so the same card is
            # replaced rather than duplicated across its lifecycle.
            assert created[0].part_id == completed[0].part_id == "tool:agent_create_thread_abc"
            first = created[0].payload["part"]
            assert isinstance(first, dict)
            assert first["state"] == ToolPartState.INPUT_AVAILABLE.value
            done = completed[0].payload["part"]
            assert isinstance(done, dict)
            assert done["state"] == ToolPartState.OUTPUT_AVAILABLE.value
            assert done["operation_id"] == str(operation_id)
            assert done["revision"] > first["revision"]
            # Structured output, not pre-rendered prose.
            assert isinstance(done["output"], dict)
            broken = failed[0].payload["part"]
            assert isinstance(broken, dict)
            assert broken["state"] == ToolPartState.OUTPUT_ERROR.value
            assert broken["error_code"] == "plan_rejected"

            # ... and the activity part accumulates the same observed steps, replaced whole.
            activity = [
                frame for frame in frames if frame.part_kind == PartKind.AGENT_ACTIVITY.value
            ]
            last = activity[-1].payload["part"]
            assert isinstance(last, dict)
            steps = last["steps"]
            assert isinstance(steps, list)
            assert [step["status"] for step in steps] == ["complete", "error"]

    run_async(scenario())


# --- the clarification card (spec 2026-09-20 §2.1) ----------------------------------------------


def test_a_clarification_part_lands_on_the_outbox_with_its_questions(tmp_path: Path) -> None:
    """A design document's opening questions reach the transcript field for field.

    The part id derives from the document, so a re-emission replaces the same card; the payload
    carries exactly what ``request_clarification`` asked, including a question with no options at
    all — an open question is a legal question, not a malformed one.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-clarify", name="D3 clarify")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="clr"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="make me an ad",
                key="k-clarify",
                storage=FsStorage(tmp_path / "artifacts"),
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            run_id = str(uuid4())
            await emitter.emit_clarification_part(
                document_id="doc_x",
                document_title="Acme launch ad",
                doc_kind="ad",
                account_name="Acme",
                run_id=run_id,
                questions=[
                    {
                        "id": "q1",
                        "question": "Which offer should lead?",
                        "why_it_matters": "It sets the headline.",
                        "options": ["Free trial", "Demo"],
                        "default": "Free trial",
                        "allow_freeform": False,
                    },
                    {
                        "id": "q2",
                        "question": "Any proof point to feature?",
                        "default": "the 40% figure",
                    },
                ],
            )

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            cards = [frame for frame in frames if frame.part_kind == PartKind.CLARIFICATION.value]
            assert len(cards) == 1
            card = cards[0]
            assert card.event_type == TurnEventType.PART_CREATED.value
            assert card.part_kind == "clarification"
            assert card.part_id == "clarification:doc_x"

            part = card.payload["part"]
            assert isinstance(part, dict)
            assert part["document_id"] == "doc_x"
            assert part["document_title"] == "Acme launch ad"
            assert part["doc_kind"] == "ad"
            assert part["account_name"] == "Acme"
            assert part["run_id"] == run_id
            questions = part["questions"]
            assert isinstance(questions, list)
            assert questions == [
                {
                    "id": "q1",
                    "question": "Which offer should lead?",
                    "why_it_matters": "It sets the headline.",
                    "options": ["Free trial", "Demo"],
                    "default": "Free trial",
                    "allow_freeform": False,
                },
                {
                    "id": "q2",
                    "question": "Any proof point to feature?",
                    "why_it_matters": "",
                    "options": [],
                    "default": "the 40% figure",
                    "allow_freeform": True,
                },
            ]

    run_async(scenario())


# --- the SSE surface: attach, replay, dedup, reset (§3.6) ---------------------------------------


async def _open_stream(
    client: httpx.AsyncClient,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    turn_id: UUID,
    last_event_id: int | None = None,
) -> list[tuple[int | None, str, dict[str, Any]]]:
    """Mint a token, attach, and parse the replay-then-close body into frames."""

    minted = await client.post(
        f"/api/v1/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/stream_token",
        headers={"X-Workspace-Id": workspace_id},
    )
    assert minted.status_code == 200, minted.text
    token = minted.json()["data"]["stream_token"]
    headers = {"X-Workspace-Id": workspace_id}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    response = await client.get(
        f"/api/v1/projects/{project_id}/threads/{thread_id}/turns/{turn_id}/events",
        params={"stream_token": token},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return _parse_sse(response.text)


def _parse_sse(body: str) -> list[tuple[int | None, str, dict[str, Any]]]:
    frames: list[tuple[int | None, str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event_id: int | None = None
        event = ""
        data: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = int(line[4:])
            elif line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        frames.append((event_id, event, data))
    return frames


def test_a_disconnect_at_every_event_boundary_replays_the_same_stream_exactly_once(
    tmp_path: Path,
) -> None:
    """§5's "a disconnect at every event boundary followed by cursor replay".

    For every cursor a consumer could have reached, the first delivery plus the replayed remainder
    equal the whole stream, in order, with no gap and no duplicate.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-replay", name="D3 replay")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="rl"
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-replay",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            for piece in ("a", "b", "c", "d"):
                await emitter.text_delta(round_ordinal=1, call_index=0, delta=piece)
            assert await emitter.reconcile_text(assistant_message="abcd") is True
            await emitter.turn_finished(status="completed")

            app = _app(conn, settings=_settings(), storage=storage)
            async with _client(app) as client:
                whole = await _open_stream(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
                # frame 0 is stream.hello (no id); the rest carry cursors.
                assert whole[0][1] == "stream.hello"
                assert whole[0][2] == {
                    "schema_version": "1",
                    "type": "stream.hello",
                    "turn_id": str(turn_id),
                    "thread_id": thread_id,
                    "project_id": project.project_id,
                }
                assert all(event == data["type"] for _, event, data in whole)
                persisted = whole[1:]
                assert [row[0] for row in persisted] == sorted(
                    row[0] for row in persisted if row[0] is not None
                )

                for cut in range(len(persisted) + 1):
                    cursor = persisted[cut - 1][0] if cut else None
                    resumed = await _open_stream(
                        client,
                        workspace_id=project.workspace_id,
                        project_id=project.project_id,
                        thread_id=thread_id,
                        turn_id=turn_id,
                        last_event_id=cursor,
                    )
                    assert resumed[0][1] == "stream.hello"
                    assert [frame[1] for frame in resumed] != ["stream.reset"]
                    # Delivered-before + replayed-after == the whole stream, exactly once.
                    assert persisted[:cut] + resumed[1:] == persisted, f"cut at {cut}"

    run_async(scenario())


def test_duplicate_delivery_deduplicates_on_event_id(tmp_path: Path) -> None:
    """At-least-once delivery is honest: two attaches deliver the same frames, and a consumer
    that keys on ``event_id`` ends up with one copy of each."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-dup", name="D3 duplicate")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="dp"
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-dup",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="x")
            await emitter.turn_finished(status="completed")

            app = _app(conn, settings=_settings(), storage=storage)
            async with _client(app) as client:
                first = await _open_stream(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
                second = await _open_stream(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
            assert first == second
            merged = {frame[0]: frame for frame in first + second if frame[0] is not None}
            assert len(merged) == len([frame for frame in first if frame[0] is not None])

    run_async(scenario())


def test_a_cursor_beyond_the_replay_horizon_resets_and_restarts_from_zero(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-horizon", name="D3 horizon")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="hz"
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-horizon",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="x")
            await emitter.turn_finished(status="completed")

            # A horizon of zero makes every existing cursor un-replayable.
            app = _app(conn, settings=_settings(sse_replay_horizon_s=0.0), storage=storage)
            async with _client(app) as client:
                frames = await _open_stream(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    last_event_id=1,
                )
            assert frames[0][1] == "stream.hello"
            assert frames[1][1] == "stream.reset"
            assert frames[1][2] == {
                "schema_version": "1",
                "type": "stream.reset",
                "turn_id": str(turn_id),
                "thread_id": thread_id,
                "project_id": project.project_id,
                "reason": "cursor_older_than_horizon",
                "rehydrate": "transcript",
            }
            # The tail floor drops to zero: the backlog restarts from the first frame, never from
            # the unusable cursor (which as a floor would match nothing forever).
            assert frames[2][1] == "turn.accepted"

            # An unknown cursor (another environment's, a corrupted one) is treated the same way.
            app_ok = _app(conn, settings=_settings(), storage=storage)
            async with _client(app_ok) as client:
                frames = await _open_stream(
                    client,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    last_event_id=99_999_999,
                )
            assert frames[1][1] == "stream.reset"

    run_async(scenario())


def test_a_terminal_backlog_closes_even_when_live_tailing_is_enabled(tmp_path: Path) -> None:
    """A completed turn is a finite response, not a socket kept alive until proxy timeout."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-finite", name="D3 finite")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="finite",
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="finish",
                key="k-finite",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            await emitter.turn_finished(status="completed")

            app = _app(conn, settings=_settings(), storage=storage, live_tail=True)
            async with _client(app) as client:
                frames = await asyncio.wait_for(
                    _open_stream(
                        client,
                        workspace_id=project.workspace_id,
                        project_id=project.project_id,
                        thread_id=thread_id,
                        turn_id=turn_id,
                    ),
                    timeout=2.0,
                )

            assert frames[-1][1] == "turn.completed"
            assert all(event == data["type"] for _, event, data in frames)

    run_async(scenario())


def test_a_terminal_live_batch_is_emitted_through_and_then_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The polling path has the same finite-terminal boundary as replay."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-live-finite", name="D3 live finite")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="live-finite",
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="finish live",
                key="k-live-finite",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()

            terminal = TurnEventRow(
                event_id=9_999_999,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=thread_id,
                turn_id=turn_id,
                sequence=3,
                event_type=TurnEventType.TURN_COMPLETED.value,
                payload={"status": "completed", "replayed": False},
                occurred_at=datetime.now(UTC),
            )

            async def terminal_batch(*_: Any, **__: Any) -> tuple[TurnEventRow, ...]:
                return (terminal,)

            monkeypatch.setattr("clue_api.chat.stream.list_turn_events", terminal_batch)
            app = _app(
                conn,
                settings=_settings(chat_stream_poll_interval_s=0.001),
                storage=storage,
                live_tail=True,
            )
            async with _client(app) as client:
                frames = await asyncio.wait_for(
                    _open_stream(
                        client,
                        workspace_id=project.workspace_id,
                        project_id=project.project_id,
                        thread_id=thread_id,
                        turn_id=turn_id,
                    ),
                    timeout=2.0,
                )

            assert frames[-1][1] == "turn.completed"
            assert frames[-1][0] == terminal.event_id
            assert all(event == data["type"] for _, event, data in frames)

    run_async(scenario())


def test_a_stream_token_is_single_use_workspace_and_turn_scoped(tmp_path: Path) -> None:
    """Lane B §5.5: one token, one stream, one use — and no authority beyond that."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-token", name="D3 token")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="tk"
            )
            storage = FsStorage(tmp_path / "artifacts")
            first_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="one",
                key="k-token-1",
                storage=storage,
            )
            second_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="two",
                key="k-token-2",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=first_turn)
            await emitter.turn_started()

            app = _app(conn, settings=_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                minted = await client.post(f"{base}/{first_turn}/stream_token", headers=headers)
                token = minted.json()["data"]["stream_token"]

                opened = await client.get(
                    f"{base}/{first_turn}/events",
                    params={"stream_token": token},
                    headers=headers,
                )
                assert opened.status_code == 200
                # Single use.
                reused = await client.get(
                    f"{base}/{first_turn}/events",
                    params={"stream_token": token},
                    headers=headers,
                )
                assert reused.status_code == 401
                assert reused.json()["error"]["code"] == "INVALID_STREAM_TOKEN"

                # Turn-scoped: a token minted for one turn opens no other.
                minted2 = await client.post(f"{base}/{first_turn}/stream_token", headers=headers)
                other = await client.get(
                    f"{base}/{second_turn}/events",
                    params={"stream_token": minted2.json()["data"]["stream_token"]},
                    headers=headers,
                )
                assert other.status_code == 401

                # Garbage is refused as such, not as a 500.
                bad = await client.get(
                    f"{base}/{first_turn}/events",
                    params={"stream_token": "not-a-uuid"},
                    headers=headers,
                )
                assert bad.status_code == 401

                # A turn of another workspace is not found, never forbidden (no existence leak).
                foreign = await client.post(
                    f"{base}/{uuid4()}/stream_token",
                    headers=headers,
                )
                assert foreign.status_code == 404
                assert foreign.json()["error"]["code"] == "TURN_NOT_FOUND"

    run_async(scenario())


def test_a_slow_consumer_never_blocks_the_writer(tmp_path: Path) -> None:
    """§3.3(7): the outbox is the buffer.

    A consumer holds a live-tail stream open and reads *nothing*. The writer keeps appending, at
    full speed, with no failures — because the two are joined by a table, not by a socket.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-slow", name="D3 slow")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="sl"
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-slow",
                storage=storage,
            )
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            app = _app(conn, settings=_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                minted = await client.post(f"{base}/{turn_id}/stream_token", headers=headers)
                token = minted.json()["data"]["stream_token"]
                async with client.stream(
                    "GET",
                    f"{base}/{turn_id}/events",
                    params={"stream_token": token},
                    headers=headers,
                ) as response:
                    assert response.status_code == 200
                    started = asyncio.get_running_loop().time()
                    for index in range(200):
                        await emitter.text_delta(
                            round_ordinal=1, call_index=0, delta=f"{index:03d}"
                        )
                    elapsed = asyncio.get_running_loop().time() - started
            assert emitter.emission_failures == []
            # Generous, because this is a DB-bound assertion about *coupling*, not throughput: the
            # writer must not be waiting on a consumer that is reading nothing at all.
            assert elapsed < 20.0
            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            assert len(_of_type(frames, TurnEventType.TEXT_DELTA)) == 200

    run_async(scenario())


# --- the controls (§3.5) ------------------------------------------------------------------------


class _SleepingEngine:
    """An engine whose turn never finishes on its own — so only a stop can end it."""

    def __init__(self) -> None:
        self.cancelled = False
        self.cancelled_turns: list[tuple[UUID, str]] = []
        self.components = SimpleNamespace(
            turns=SimpleNamespace(mark_cancelled=self._mark_cancelled)
        )

    async def _mark_cancelled(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
    ) -> None:
        self.cancelled_turns.append((turn_id, workspace_id))

    async def execute(self, **kwargs: Any) -> Any:
        del kwargs
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("the stopped turn should never have completed")


class _MissingArtifactEngine:
    """The exact-message read failed before any model call could legally begin."""

    def __init__(self, *, turns: DbAgentTurnJournal) -> None:
        self.components = SimpleNamespace(turns=turns)
        self.calls = 0

    async def execute(self, **kwargs: Any) -> Any:
        del kwargs
        self.calls += 1
        raise ArtifactNotFound("the durable artifact row outlived its blob")


def test_missing_required_artifact_is_a_terminal_failed_turn(tmp_path: Path) -> None:
    """The model stays closed, the journal is terminal, and SSE closes with a stable code."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-missing-input", name="D3 missing input")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="mi",
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="bytes that later disappeared",
                key="k-missing-input",
                storage=storage,
            )
            await _agent_turn_row(
                conn,
                project=project,
                thread_id=thread_id,
                turn_id=turn_id,
            )
            cf = conn_session_factory(conn)
            journal = DbAgentTurnJournal(conn_factory=cf)
            engine = _MissingArtifactEngine(turns=journal)
            runner = ProjectConversationTurnRunner(
                engine=engine,  # type: ignore[arg-type]
                executor=None,  # type: ignore[arg-type]
                recipes=None,  # type: ignore[arg-type]
                starter=None,  # type: ignore[arg-type]
                parameters=None,  # type: ignore[arg-type]
                conn_factory=cf,
                stop_poll_interval_s=0,
            )
            emitter = await _emitter(
                conn,
                project=project,
                thread_id=thread_id,
                turn_id=turn_id,
            )
            submission = SimpleNamespace(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                submitted_by_user_id=USER_ID,
                submitted_via_membership_id=f"{MEMBERSHIP_ID}-{project.workspace_id}",
            )
            with pytest.raises(RequiredTurnArtifactMissing):
                # P3.4 made the watched wrapper body-agnostic (the routing rule selects the
                # turn body); this drives it exactly as the head-of-abm path composes it.
                await runner._execute_watched(
                    run=lambda: engine.execute(),
                    submission=submission,  # type: ignore[arg-type]
                    turn_id=turn_id,
                    stream=emitter,
                )
            assert engine.calls == 1

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            failed = _of_type(frames, TurnEventType.TURN_FAILED)
            assert len(failed) == 1
            assert failed[0].payload["failure_code"] == REQUIRED_CONTEXT_ARTIFACT_MISSING
            latest = (
                (
                    await conn.execute(
                        text(
                            "SELECT status, reason_code FROM agent_turn_event "
                            "WHERE workspace_id=:workspace AND turn_id=:turn "
                            "ORDER BY seq DESC LIMIT 1"
                        ),
                        {"workspace": project.workspace_id, "turn": turn_id},
                    )
                )
                .mappings()
                .one()
            )
            assert (latest["status"], latest["reason_code"]) == (
                "failed",
                REQUIRED_CONTEXT_ARTIFACT_MISSING,
            )

    run_async(scenario())


def test_stop_cancels_the_active_attempt_and_cannot_look_like_a_finished_message(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-stop", name="D3 stop")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="st"
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="hello",
                key="k-stop",
                storage=storage,
            )
            app = _app(conn, settings=_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                queued_stop = await client.post(f"{base}/{turn_id}/stop", headers=headers)
            assert queued_stop.status_code == 409, queued_stop.text
            assert queued_stop.json()["error"]["code"] == "TURN_NOT_RUNNING"
            assert (
                await get_control_request(
                    conn, workspace_id=project.workspace_id, turn_id=turn_id, kind="stop"
                )
                is None
            )

            cf = conn_session_factory(conn)
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="I was saying som")

            async with _client(app) as client:
                stopped = await client.post(f"{base}/{turn_id}/stop", headers=headers)
                assert stopped.status_code == 202, stopped.text
                assert stopped.json()["data"]["already_requested"] is False
                # Insert-once: a double click is a replay of one durable request.
                again = await client.post(f"{base}/{turn_id}/stop", headers=headers)
                assert again.json()["data"]["already_requested"] is True

            control = await get_control_request(
                conn, workspace_id=project.workspace_id, turn_id=turn_id, kind="stop"
            )
            assert control is not None
            # Ambient authority: the durable row names the authenticated human, not a request field.
            assert control.requested_by_user_id == USER_ID
            assert await stop_requested(
                conn,
                workspace_id=project.workspace_id,
                turn_id=turn_id,
                generation_attempt_id=emitter.generation_attempt_id,
            )

            await _agent_turn_row(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            engine = _SleepingEngine()
            engine.artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            runner = ProjectConversationTurnRunner(
                engine=engine,  # type: ignore[arg-type]
                executor=None,  # type: ignore[arg-type]
                recipes=None,  # type: ignore[arg-type]
                starter=None,  # type: ignore[arg-type]
                parameters=None,  # type: ignore[arg-type]
                conn_factory=cf,
                stop_poll_interval_s=0.01,
            )
            submission = type(
                "_S",
                (),
                {
                    "workspace_id": project.workspace_id,
                    "project_id": project.project_id,
                    "thread_id": thread_id,
                    "submitted_by_user_id": USER_ID,
                    "submitted_via_membership_id": f"{MEMBERSHIP_ID}-{project.workspace_id}",
                },
            )()
            with pytest.raises(TurnStopped):
                # P3.4 made the watched wrapper body-agnostic (the routing rule selects the
                # turn body); this drives it exactly as the head-of-abm path composes it.
                await runner._execute_watched(
                    run=lambda: engine.execute(),
                    submission=submission,  # type: ignore[arg-type]
                    turn_id=turn_id,
                    stream=emitter,
                )
            assert engine.cancelled is True
            assert (
                await conn.scalar(
                    text(
                        "SELECT status FROM agent_turn_event WHERE turn_id=:turn "
                        "ORDER BY seq DESC LIMIT 1"
                    ),
                    {"turn": turn_id},
                )
                == "cancelled"
            )
            async with _client(app) as client:
                history = await client.get(
                    base.removesuffix("/turns") + "/messages?include=bodies", headers=headers
                )
            bodies = [
                item.get("body") for item in history.json()["data"] if item["role"] == "assistant"
            ]
            assert bodies == ["I was saying som"]
            assert (
                await conn.scalar(
                    text("SELECT count(*) FROM agent_finalization_commit WHERE turn_id=:turn"),
                    {"turn": turn_id},
                )
                == 0
            )

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            cancelled = _of_type(frames, TurnEventType.TURN_CANCELLED)
            assert len(cancelled) == 1
            # The partial text survives for audit ...
            deltas = _of_type(frames, TurnEventType.TEXT_DELTA)
            assert "".join(str(f.payload["delta"]) for f in deltas) == "I was saying som"
            # ... and can never be mistaken for a completed message.
            assert _of_type(frames, TurnEventType.TEXT_END) == []
            assert _of_type(frames, TurnEventType.TURN_COMPLETED) == []
            partial = [
                frame
                for frame in _of_type(frames, TurnEventType.PART_FAILED)
                if frame.part_kind == PartKind.TEXT.value
            ]
            assert partial and partial[0].payload["partial"] is True

    run_async(scenario())


def test_stop_holds_queue_until_explicit_idempotent_resume(
    tmp_path: Path,
) -> None:
    """Stop holds B/C durably; Resume releases FIFO without submitting another message."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-r5-three-turn", name="R5 three turn")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="r5q",
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_ids = [
                await _submit_turn(
                    conn,
                    project=project,
                    thread_id=thread_id,
                    message=message,
                    key=f"r5-{index}",
                    storage=storage,
                )
                for index, message in enumerate(("Turn A", "Turn B", "Turn C"), start=1)
            ]
            turn_a, turn_b, turn_c = turn_ids
            work_id = thread_work_id(
                workspace_id=project.workspace_id,
                thread_id=thread_id,
            )

            async def claim(worker_id: str) -> Any:
                task = await claim_next_task(
                    conn,
                    kind=FleetTaskKind.AGENT_TURN,
                    worker_id=worker_id,
                    project_run_id=ProjectRunId(work_id),
                )
                assert task is not None
                return task

            async def finish(task: Any, worker_id: str, outcome: str) -> None:
                assert await finish_task(
                    conn,
                    task_id=task.task_id,
                    worker_id=worker_id,
                    status=FleetTaskStatus.DONE,
                    result_ref={"outcome": outcome},
                )

            app = _app(conn, settings=_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns"
            headers = {"X-Workspace-Id": project.workspace_id}

            task_a = await claim("worker-a")
            emitter_a = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_a)
            await emitter_a.turn_started()
            async with _client(app) as client:
                before_stop = await client.get(base, headers=headers)
                queued_stop = await client.post(f"{base}/{turn_c}/stop", headers=headers)
                stopped = await client.post(f"{base}/{turn_a}/stop", headers=headers)
            assert [item["state"] for item in before_stop.json()["data"]] == [
                "running",
                "queued",
                "queued",
            ]
            assert queued_stop.status_code == 409
            assert queued_stop.json()["error"]["code"] == "TURN_NOT_RUNNING"
            assert stopped.status_code == 202
            assert stopped.json()["data"]["turn_id"] == str(turn_a)

            hold_id = stopped.json()["data"]["control_id"]
            resume_path = base.removesuffix("/turns") + "/queue/resume"
            async with _client(app) as client:
                pending = await client.post(
                    resume_path, headers=headers, json={"hold_control_id": hold_id}
                )
            assert pending.status_code == 409 and pending.json()["error"]["code"] == "STOP_PENDING"
            await commit_interrupted_turn(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                turn_id=turn_a,
                body_ref=None,
            )
            await emitter_a.turn_cancelled()
            await finish(task_a, "worker-a", "cancelled")
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
                is None
            )
            turn_d = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="Turn D while held",
                key="r5-4",
                storage=storage,
            )
            assert (
                await conn.scalar(
                    text("SELECT 1 FROM fleet_task WHERE dedup_key=:key"),
                    {"key": agent_turn_dedup_key(turn_d)},
                )
                is None
            )
            async with _client(app) as client:
                held = await client.get(base, headers=headers)
                assert held.json()["meta"]["queue_control"]["paused"] is True
                assert [t["state"] for t in held.json()["data"]] == [
                    "cancelled",
                    "queued",
                    "queued",
                    "queued",
                ]
                resumed = await client.post(
                    resume_path, headers=headers, json={"hold_control_id": hold_id}
                )
                assert resumed.status_code == 202, resumed.text
                assert resumed.json()["data"]["dispatched_turn_id"] == str(turn_b)
                again = await client.post(
                    resume_path, headers=headers, json={"hold_control_id": hold_id}
                )
                assert again.json()["data"]["replayed"] is True
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
                is None
            )

            task_b = await claim("worker-b")
            emitter_b = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_b)
            await emitter_b.turn_started()
            async with _client(app) as client:
                # This GET is the cold/reload authority, not an in-memory worker view.
                during_b = await client.get(base, headers=headers)
            assert [item["turn_id"] for item in during_b.json()["data"]] == [
                str(turn_a),
                str(turn_b),
                str(turn_c),
                str(turn_d),
            ]
            assert [item["state"] for item in during_b.json()["data"]] == [
                "cancelled",
                "running",
                "queued",
                "queued",
            ]

            await emitter_b.turn_finished(status="completed")
            async with _client(app) as client:
                terminal_stop = await client.post(f"{base}/{turn_b}/stop", headers=headers)
            assert terminal_stop.status_code == 409
            assert terminal_stop.json()["error"]["code"] == "TURN_NOT_RUNNING"
            await finish(task_b, "worker-b", "completed")
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
                == turn_c
            )

            await claim("worker-c")
            emitter_c = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_c)
            await emitter_c.turn_started()
            async with _client(app) as client:
                during_c = await client.get(base, headers=headers)
            assert [item["state"] for item in during_c.json()["data"]] == [
                "cancelled",
                "completed",
                "running",
                "queued",
            ]

            async with _client(app) as client:
                newer_stop = await client.post(f"{base}/{turn_c}/stop", headers=headers)
                assert newer_stop.status_code == 202
                newer_hold = newer_stop.json()["data"]["control_id"]
                stale_resume = await client.post(
                    resume_path, headers=headers, json={"hold_control_id": hold_id}
                )
                assert stale_resume.status_code == 409
                assert stale_resume.json()["error"]["code"] == "QUEUE_HOLD_CHANGED"
                still_held = await client.get(base, headers=headers)
                assert still_held.json()["meta"]["queue_control"]["hold_control_id"] == newer_hold
                assert still_held.json()["data"][-1]["turn_id"] == str(turn_d)
                assert still_held.json()["data"][-1]["state"] == "queued"

    run_async(scenario())


def test_retry_creates_a_new_turn_and_never_mutates_the_prior_transcript(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-retry", name="D3 retry")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="rt"
            )
            storage = FsStorage(tmp_path / "artifacts")
            original = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="Who are our best accounts?",
                key="k-retry",
                storage=storage,
            )
            # The first turn failed; its task is terminal, so the thread has moved on.
            await conn.execute(
                text("UPDATE fleet_task SET status = 'failed' WHERE dedup_key = :key"),
                {"key": agent_turn_dedup_key(original)},
            )

            app = _app(conn, settings=_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                retried = await client.post(f"{base}/{original}/retry", headers=headers)
                assert retried.status_code == 202, retried.text
                body = retried.json()["data"]
                assert body["replayed"] is False
                new_turn = UUID(body["turn_id"])
                assert new_turn != original
                # Idempotent: retrying again resolves to the retry that already exists.
                once_more = await client.post(f"{base}/{original}/retry", headers=headers)
                assert once_more.json()["data"]["turn_id"] == str(new_turn)
                assert once_more.json()["data"]["replayed"] is True

            control = await get_control_request(
                conn, workspace_id=project.workspace_id, turn_id=original, kind="retry"
            )
            assert control is not None and control.retry_turn_id == new_turn
            # The prior turn's durable record is untouched — a retry adds, never rewrites.
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT turn_id, message_sha256 FROM agent_turn_submission "
                            "WHERE workspace_id = :ws AND thread_id = :thread "
                            "ORDER BY requested_at, turn_id"
                        ),
                        {"ws": project.workspace_id, "thread": thread_id},
                    )
                )
                .mappings()
                .all()
            )
            assert {UUID(str(row["turn_id"])) for row in rows} == {original, new_turn}
            # Same words, re-captured under the new identity.
            assert len({row["message_sha256"] for row in rows}) == 1

    run_async(scenario())


# --- the inherited follow-ups -------------------------------------------------------------------


def test_the_turn_read_surface_unions_queued_submissions_with_turn_events(
    tmp_path: Path,
) -> None:
    """The two-phase turn identity, made visible.

    A queued turn exists only as a submission row; a running turn has frames; a finished one has a
    terminal frame. All three must appear, in submission order, with the right state.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-union", name="D3 union")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="un"
            )
            storage = FsStorage(tmp_path / "artifacts")
            done_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="first",
                key="k-union-1",
                storage=storage,
            )
            running_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="second",
                key="k-union-2",
                storage=storage,
            )
            queued_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="third",
                key="k-union-3",
                storage=storage,
            )
            finished = await _emitter(conn, project=project, thread_id=thread_id, turn_id=done_turn)
            await finished.turn_started()
            await finished.turn_finished(status="completed")
            live = await _emitter(conn, project=project, thread_id=thread_id, turn_id=running_turn)
            await live.turn_started()

            cf = conn_session_factory(conn)
            turns = await thread_turns(
                workspace_id=project.workspace_id, thread_id=thread_id, conn_factory=cf
            )
            states = {item.turn_id: item.state for item in turns}
            assert states[done_turn] == "completed"
            assert states[running_turn] == "running"
            # The one that has no execution evidence at all is still visible — and honest.
            assert states[queued_turn] == "queued"
            # Acceptance assigns monotonic timestamps under the thread lock, even within
            # one transaction. Visible and execution order both follow submission order.
            assert [item.turn_id for item in turns] == [done_turn, running_turn, queued_turn]
            # Each carries the cursor a client attaches after.
            assert next(i for i in turns if i.turn_id == running_turn).last_event_id is not None
            assert next(i for i in turns if i.turn_id == queued_turn).last_event_id is None

            # The sidebar badge derives from exactly this union.
            busy = await threads_running(
                workspace_id=project.workspace_id,
                thread_ids=[thread_id],
                conn_factory=cf,
            )
            assert thread_id in busy
            assert thread_status(status="active", running=True) == "running"
            # An open gate outranks it; an archived thread outranks everything.
            assert (
                thread_status(
                    status="active", running=True, open_gate_kinds=("directive_confirmation",)
                )
                == "approval"
            )
            assert thread_status(status="archived", running=True) == "archived"

            # And the HTTP read surface says the same thing.
            app = _app(conn, settings=_settings(), storage=storage)
            async with _client(app) as client:
                listed = await client.get(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
                    headers={"X-Workspace-Id": project.workspace_id},
                )
            assert listed.status_code == 200, listed.text
            payload = listed.json()
            assert {row["turn_id"] for row in payload["data"]} == {
                str(done_turn),
                str(running_turn),
                str(queued_turn),
            }
            assert payload["meta"]["thread_status"] == "running"

    run_async(scenario())


def test_the_route_announces_acceptance_once_and_the_worker_does_not_repeat_it(
    tmp_path: Path,
) -> None:
    """``turn.accepted`` is emitted where acceptance happens — and exactly once.

    The route writes it in the same transaction as the capture and the submission, so a queued turn
    is announced while it waits; a duplicate POST announces nothing new; and the worker's emitter,
    which still announces a turn accepted off-route, finds the frame and stays quiet.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-accepted", name="D3 accepted")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="ac"
            )
            storage = FsStorage(tmp_path / "artifacts")
            app = _app(conn, settings=_settings(), storage=storage)
            path = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns"
            headers = {"X-Workspace-Id": project.workspace_id, "Idempotency-Key": "k-accepted"}
            async with _client(app) as client:
                accepted = await client.post(path, json={"message": "hello"}, headers=headers)
                assert accepted.status_code == 202, accepted.text
                turn_id = UUID(accepted.json()["data"]["turn_id"])
                # The same POST again is a replay: same turn, and no second announcement.
                replayed = await client.post(path, json={"message": "hello"}, headers=headers)
                assert replayed.json()["data"]["replayed"] is True

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            announced = _of_type(frames, TurnEventType.TURN_ACCEPTED)
            assert len(announced) == 1
            assert announced[0].payload["source"] == "route"
            assert announced[0].payload["kind"] == "message"
            # No attempt has begun, so the frame carries no generation identity ...
            assert announced[0].generation_attempt_id is None
            # ... and the worker opening attempt 1 does not announce it a second time.
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            assert emitter.attempt_ordinal == 1
            after = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            assert len(_of_type(after, TurnEventType.TURN_ACCEPTED)) == 1

            # A turn accepted off-route (the dev trial, a harness) is still announced by the worker.
            offroute = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="off route",
                key="k-offroute",
                storage=storage,
                dispatch=False,
            )
            worker_side = await _emitter(
                conn, project=project, thread_id=thread_id, turn_id=offroute
            )
            del worker_side
            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=offroute)
            announced = _of_type(frames, TurnEventType.TURN_ACCEPTED)
            assert len(announced) == 1
            assert announced[0].payload["source"] == "worker"

    run_async(scenario())


def test_the_thread_listing_reports_running_from_the_submissions_union(tmp_path: Path) -> None:
    """The sidebar badge, end to end: idle → running → idle as the turn's state changes."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-badge", name="D3 badge")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="bg"
            )
            storage = FsStorage(tmp_path / "artifacts")
            app = _app(conn, settings=_settings(), storage=storage)
            listing = f"/api/v1/projects/{project.project_id}/threads"
            headers = {"X-Workspace-Id": project.workspace_id}

            async def _status() -> str:
                async with _client(app) as client:
                    listed = await client.get(listing, headers=headers)
                assert listed.status_code == 200, listed.text
                rows = [row for row in listed.json()["data"] if row["id"] == thread_id]
                assert len(rows) == 1
                return str(rows[0]["status"])

            assert await _status() == "idle"

            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="are we running?",
                key="k-badge",
                storage=storage,
            )
            # Queued counts as running: the conversation is working, not idle.
            assert await _status() == "running"

            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            assert await _status() == "running"

            await emitter.turn_finished(status="completed")
            assert await _status() == "idle"

    run_async(scenario())


def test_a_stranded_queued_turn_heals_on_attach_and_on_the_sweep(tmp_path: Path) -> None:
    """The D2 review's stranded-dispatch gap, closed from both sides."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-strand", name="D3 strand")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="sd"
            )
            storage = FsStorage(tmp_path / "artifacts")
            # A submission whose dispatch never happened — the process died in the gap between
            # finalizing the previous task and offering this one.
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="stranded",
                key="k-strand",
                storage=storage,
                dispatch=False,
            )
            work_id = thread_work_id(workspace_id=project.workspace_id, thread_id=thread_id)

            async def _tasks() -> list[str]:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT status FROM fleet_task WHERE kind = 'agent_turn' "
                            "AND work_id = :work_id"
                        ),
                        {"work_id": work_id},
                    )
                ).scalars()
                return [str(value) for value in rows]

            assert await _tasks() == []

            # 1. attaching a stream heals it ...
            app = _app(conn, settings=_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                minted = await client.post(f"{base}/{turn_id}/stream_token", headers=headers)
                opened = await client.get(
                    f"{base}/{turn_id}/events",
                    params={"stream_token": minted.json()["data"]["stream_token"]},
                    headers=headers,
                )
                assert opened.status_code == 200
            assert await _tasks() == [FleetTaskStatus.QUEUED.value]

            # ... and 2. the worker's sweep would have healed it for a user who is not watching.
            await conn.execute(
                text("DELETE FROM fleet_task WHERE work_id = :work_id"), {"work_id": work_id}
            )
            assert await _tasks() == []
            cf = conn_session_factory(conn)
            assert await sweep_thread_dispatch(cf) >= 1
            assert await _tasks() == [FleetTaskStatus.QUEUED.value]
            # Idempotent: a second sweep offers nothing, because a task is already in flight.
            assert await sweep_thread_dispatch(cf) == 0

    run_async(scenario())


def test_include_bodies_hydrates_the_page_and_stays_bounded(tmp_path: Path) -> None:
    """The cold-load read: real bodies, workspace-scoped, bounded by the page and by bytes."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-bodies", name="D3 bodies")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="bd"
            )
            storage = FsStorage(tmp_path / "artifacts")
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            messages = ["first question", "second question", "third question"]
            stored_keys: list[str] = []
            for index, body in enumerate(messages):
                turn_id = await _submit_turn(
                    conn,
                    project=project,
                    thread_id=thread_id,
                    message=body,
                    key=f"k-body-{index}",
                    storage=storage,
                    dispatch=False,
                )
                await _agent_turn_row(conn, project=project, thread_id=thread_id, turn_id=turn_id)
                ref = await artifacts.persist_body(
                    workspace_id=project.workspace_id, data=body.encode(), media_type="text/plain"
                )
                stored_keys.append(ref.artifact_key)
                await conn.execute(
                    text(
                        "INSERT INTO agent_thread_message "
                        "(id, workspace_id, thread_id, turn_id, sequence, role, "
                        " body_artifact_key, body_sha256, retention_class) "
                        "VALUES (:id, :ws, :thread, :turn, :seq, 'user', :key, :sha, 'standard')"
                    ),
                    {
                        "id": uuid4(),
                        "ws": project.workspace_id,
                        "thread": thread_id,
                        "turn": turn_id,
                        "seq": index + 1,
                        "key": ref.artifact_key,
                        "sha": ref.sha256,
                    },
                )

            # Reproduce a database that outlived its disposable fs root: metadata and the other
            # messages remain, but one exact physical blob is gone.
            (tmp_path / "artifacts" / stored_keys[1]).unlink()

            app = _app(conn, settings=_settings(), storage=storage)
            path = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/messages"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                plain = await client.get(path, headers=headers)
                hydrated = await client.get(path, params={"include": "bodies"}, headers=headers)
                paged = await client.get(
                    path, params={"include": "bodies", "limit": 2}, headers=headers
                )
                bogus = await client.get(path, params={"include": "refs"}, headers=headers)
            assert plain.status_code == 200
            # The default listing stays body-free (D0's decision is unchanged).
            assert all(item["body"] is None for item in plain.json()["data"])
            assert hydrated.status_code == 200, hydrated.text
            assert [item["body"] for item in hydrated.json()["data"]] == [
                messages[0],
                None,
                messages[2],
            ]
            assert [item["body_unavailable_reason"] for item in hydrated.json()["data"]] == [
                None,
                "artifact_missing",
                None,
            ]
            # Bounded by the page: the fan-out limit *is* the pagination limit.
            page = paged.json()
            assert len(page["data"]) == 2
            assert page["meta"]["next_cursor"] is not None
            # An unknown ``include`` is a loud 422, never a silently ignored parameter.
            assert bogus.status_code == 422
            assert bogus.json()["error"]["code"] == "VALIDATION_ERROR"

    run_async(scenario())


def test_include_bodies_reports_a_storage_outage_as_typed_503(tmp_path: Path) -> None:
    """A backend outage is not evidence that one historical message is permanently missing."""

    class _UnavailableStorage(FsStorage):
        async def get(self, key: str) -> bytes:
            del key
            raise StorageError("storage service unavailable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-storage-down", name="D3 storage down")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="sd",
            )
            healthy = FsStorage(tmp_path / "healthy-artifacts")
            await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="still durably recorded",
                key="k-storage-down",
                storage=healthy,
                dispatch=False,
            )
            turn = await thread_turns(
                workspace_id=project.workspace_id,
                thread_id=thread_id,
                conn_factory=conn_session_factory(conn),
            )
            await _agent_turn_row(
                conn,
                project=project,
                thread_id=thread_id,
                turn_id=turn[0].turn_id,
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_thread_message "
                    "(id, workspace_id, thread_id, turn_id, sequence, role, "
                    " body_artifact_key, body_sha256, retention_class) "
                    "VALUES (:id, :ws, :thread, :turn, 1, 'user', :key, :sha, 'standard')"
                ),
                {
                    "id": uuid4(),
                    "ws": project.workspace_id,
                    "thread": thread_id,
                    "turn": turn[0].turn_id,
                    "key": turn[0].message_artifact_key,
                    "sha": turn[0].message_sha256,
                },
            )
            app = _app(
                conn,
                settings=_settings(),
                storage=_UnavailableStorage(tmp_path / "unavailable"),
            )
            path = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/messages"
            async with _client(app) as client:
                response = await client.get(
                    path,
                    params={"include": "bodies"},
                    headers={"X-Workspace-Id": project.workspace_id},
                )
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "ARTIFACT_STORAGE_UNAVAILABLE"

    run_async(scenario())


# --- retention and the vocabulary guards ---------------------------------------------------------


def test_retention_prunes_terminal_turns_only(tmp_path: Path) -> None:
    """§3.3(7)'s explicit policy: whole terminal turns age out; a live one never does."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-retain", name="D3 retention")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="rn"
            )
            storage = FsStorage(tmp_path / "artifacts")
            finished_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="one",
                key="k-retain-1",
                storage=storage,
                dispatch=False,
            )
            live_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="two",
                key="k-retain-2",
                storage=storage,
                dispatch=False,
            )
            done = await _emitter(conn, project=project, thread_id=thread_id, turn_id=finished_turn)
            await done.turn_started()
            await done.turn_finished(status="completed")
            live = await _emitter(conn, project=project, thread_id=thread_id, turn_id=live_turn)
            await live.turn_started()
            await live.text_delta(round_ordinal=1, call_index=0, delta="still going")

            # A frame is immutable: the retention policy is the *only* thing allowed to remove one,
            # and nothing at all may rewrite one. (Which is also why this test ages the window
            # forward rather than back-dating the rows.)
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(text("UPDATE agent_turn_event_stream SET occurred_at = now()"))

        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-d3-retain", name="D3 retention")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="rn"
            )
            storage = FsStorage(tmp_path / "artifacts")
            finished_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="one",
                key="k-retain-1",
                storage=storage,
                dispatch=False,
            )
            live_turn = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="two",
                key="k-retain-2",
                storage=storage,
                dispatch=False,
            )
            done = await _emitter(conn, project=project, thread_id=thread_id, turn_id=finished_turn)
            await done.turn_started()
            await done.turn_finished(status="completed")
            live = await _emitter(conn, project=project, thread_id=thread_id, turn_id=live_turn)
            await live.turn_started()
            await live.text_delta(round_ordinal=1, call_index=0, delta="still going")

            later = datetime.now(UTC) + timedelta(days=7)
            deleted = await prune_turn_events(conn, retention_s=3600.0, now=later)
            assert deleted > 0
            assert (
                await _frames(conn, workspace_id=project.workspace_id, turn_id=finished_turn) == []
            )
            # The live attempt keeps every frame, at any age: pruning it would strand a consumer
            # mid-generation and lose the deltas reconciliation is about to check.
            surviving = await _frames(conn, workspace_id=project.workspace_id, turn_id=live_turn)
            assert [frame.event_type for frame in surviving] == [
                TurnEventType.TURN_ACCEPTED.value,
                TurnEventType.TURN_STARTED.value,
                TurnEventType.TEXT_START.value,
                TurnEventType.TEXT_DELTA.value,
            ]

            cf = conn_session_factory(conn)
            assert await sweep_turn_stream_retention(cf, retention_s=3600.0) == 0

    run_async(scenario())


def test_the_stored_event_vocabulary_matches_the_database_check() -> None:
    """The §3.2 vocabulary is closed in two places; a drift between them fails here, loudly."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            definition = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'agent_turn_event_stream_type'"
                    )
                )
            ).scalar_one()
            for event_type in TURN_EVENT_TYPES:
                assert f"'{event_type}'" in definition, event_type
            # ``stream.hello`` is generated at connect and must never be storable.
            assert "stream.hello" not in definition

    run_async(scenario())


def test_the_projection_dedup_prefix_matches_its_authoring_module() -> None:
    """The projections package restates a constant it may not import; this is the drift guard."""

    assert AGENT_TURN_TASK_DEDUP_PREFIX == AGENT_TURN_DEDUP_PREFIX


def test_stop_recovery_without_stream_persists_only_latest_answer_and_survives_pruning(
    tmp_path: Path,
) -> None:
    from clue_api.agent_turn_wiring import DbAgentHistoryStore

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-stop-recovery", name="Stop recovery")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="recover",
            )
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="recover",
                key="recovery",
                storage=storage,
            )
            await _agent_turn_row(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="superseded answer")
            await emitter.text_delta(round_ordinal=2, call_index=0, delta="Exact partial `")
            await emitter.reasoning_delta(round_ordinal=2, delta="never history")
            app = _app(conn, settings=_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                assert (
                    await client.post(f"{base}/turns/{turn_id}/stop", headers=headers)
                ).status_code == 202
            cf = conn_session_factory(conn)
            engine = _SleepingEngine()
            engine.artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            runner = ProjectConversationTurnRunner(
                engine=engine,
                executor=None,
                recipes=None,
                starter=None,
                parameters=None,
                conn_factory=cf,
            )
            submission = SimpleNamespace(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=thread_id,
            )
            for _ in range(2):
                with pytest.raises(TurnStopped):
                    await runner._finish_stop(submission=submission, turn_id=turn_id, stream=None)
            assert not engine.cancelled  # Recovery never started the model.
            await emitter.turn_cancelled()
            assert (
                await prune_turn_events(
                    conn, retention_s=1, now=datetime.now(UTC) + timedelta(days=2)
                )
                > 0
            )
            async with _client(app) as client:
                history = await client.get(f"{base}/messages?include=bodies", headers=headers)
                turns = await client.get(f"{base}/turns", headers=headers)
            assert [x["body"] for x in history.json()["data"] if x["role"] == "assistant"] == [
                "Exact partial `"
            ]
            assert turns.json()["data"][0]["state"] == "cancelled"
            assert turns.json()["meta"]["queue_control"]["paused"] is False
            refs = await DbAgentHistoryStore(conn_factory=cf).load(
                workspace_id=project.workspace_id, thread_id=thread_id
            )
            assert next(x for x in refs if x.role == "assistant").interrupted is True

    run_async(scenario())


def test_openrouter_wire_reaches_reasoning_parts_without_duplicate_aliases(tmp_path: Path) -> None:
    from tests.gateway.test_openrouter_reasoning import _provider, _stream_response

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-reasoning-wire", name="Reasoning wire")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="wire"
            )
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="wire",
                key="wire",
                storage=FsStorage(tmp_path),
            )
            emitter = await _emitter(
                conn,
                project=project,
                thread_id=thread_id,
                turn_id=turn_id,
                policy=TurnStreamPolicy(reasoning_trace=True, batch_max_chars=1),
            )
            model = _provider(_stream_response)
            async for _ in model.astream(
                "Inspect the project",
                config={"callbacks": [TurnStreamCallbackHandler(emitter=emitter)]},
            ):
                pass
            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            deltas = [
                f for f in frames if f.event_type == "text.delta" and f.part_kind == "reasoning"
            ]
            assert (
                "".join(str(f.payload["delta"]) for f in deltas)
                == "Check `a_long_identifier` then continue."
            )
            assert not [f for f in frames if f.event_type == "text.delta" and f.part_kind == "text"]

    run_async(scenario())


@pytest.mark.parametrize("stop_first", [True, False])
def test_stop_and_finalization_preserve_the_first_durable_winner(
    tmp_path: Path,
    stop_first: bool,
) -> None:
    from clue_agents.contracts import AgentFinalizeEnvelope, FinalizeStatus
    from clue_api.agent_turn_wiring import DbAgentTurnJournal
    from clue_api.chat.turn_controls import TurnStopRequested

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-stop-finalize", name="Stop race")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="race"
            )
            storage = FsStorage(tmp_path)
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="race",
                key="race",
                storage=storage,
            )
            await _agent_turn_row(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            await emitter.turn_started()
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            body = await artifacts.persist_body(
                workspace_id=project.workspace_id, data=b"Final answer", media_type="text/plain"
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid4(),
                execution_id=await conn.scalar(
                    text("SELECT execution_id FROM agent_turn WHERE id=:turn"), {"turn": turn_id}
                ),
                status=FinalizeStatus.COMPLETED,
                user_message_artifact_ref=body,
                finalized_at=datetime.now(UTC),
            )
            ref = await artifacts.persist_body(
                workspace_id=project.workspace_id,
                data=envelope.model_dump_json().encode(),
                media_type="application/json",
            )
            journal = DbAgentTurnJournal(conn_factory=cf)
            await journal.record_finalization(
                turn_id=turn_id, workspace_id=project.workspace_id, envelope=envelope
            )
            app = _app(conn, settings=_settings(), storage=storage)
            path = f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns/{turn_id}/stop"
            headers = {"X-Workspace-Id": project.workspace_id}
            if not stop_first:
                await journal.commit_finalization_authority(
                    turn_id=turn_id,
                    workspace_id=project.workspace_id,
                    envelope=envelope,
                    envelope_ref=ref,
                )
            async with _client(app) as client:
                stopped = await client.post(path, headers=headers)
            if stop_first:
                assert stopped.status_code == 202
                with pytest.raises(TurnStopRequested):
                    await journal.commit_finalization_authority(
                        turn_id=turn_id,
                        workspace_id=project.workspace_id,
                        envelope=envelope,
                        envelope_ref=ref,
                    )
                await commit_interrupted_turn(
                    conn,
                    workspace_id=project.workspace_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    body_ref=None,
                )
            else:
                assert stopped.status_code == 409
            assert await conn.scalar(
                text("SELECT count(*) FROM agent_finalization_commit WHERE turn_id=:turn"),
                {"turn": turn_id},
            ) == int(not stop_first)
            assert await conn.scalar(
                text("SELECT count(*) FROM agent_turn_control_request WHERE turn_id=:turn"),
                {"turn": turn_id},
            ) == int(stop_first)
            if not stop_first:
                assert (
                    await conn.scalar(
                        text("SELECT queue_hold_control_id FROM agent_thread WHERE id=:thread"),
                        {"thread": thread_id},
                    )
                    is None
                )

    run_async(scenario())
