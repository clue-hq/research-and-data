"""FI Lane D "dev-lens" mini-slice: the raw reasoning toggle and the turn-context inspector.

Both halves exist to make prompt/skill tuning possible, and both are **dev-only by construction**.
This suite's first job is therefore not to prove the features work — it is to prove they cannot
exist in production, and that the ratified §3.3 contract they relax is *sharpened* rather than
weakened:

* the production negative ("what streams as reasoning is a safe activity summary, never provider
  reasoning content") is asserted here in its strongest form — a provider that streams reasoning on
  every chunk, and an outbox that contains none of it — and the D3 suite's own version of that
  assertion (``test_no_provider_content_or_surrounding_json_reaches_the_wire``) still passes
  verbatim, unchanged;
* raw reasoning reaches the wire **iff** the lens is on;
* a production process holding either flag does not construct at all.

Everything else here is the positive contract: the emission shape (``text.delta`` targeting the
reasoning part id — no new event type, no new part kind, no migration), the four inspector routes'
shapes and their byte budget, and the cross-tenant / cross-thread refusals.

DB-backed and rollback-only per ``tests/api`` conventions.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import pytest
from httpx import ASGITransport
from langchain_core.messages import AIMessageChunk
from pydantic import ValidationError
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.chat.turn_events import TurnEventType, list_turn_events
from clue_api.chat.turn_parts import PartKind
from clue_api.chat.turn_stream import (
    TurnStreamCallbackHandler,
    TurnStreamEmitter,
    TurnStreamPolicy,
    reasoning_deltas_from_chunk,
)
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_api.thread_wiring import register_thread_tools
from clue_config import GatewayConfig, ReasoningRequest, Settings, load_settings
from clue_gateway.agent_model import _reasoning_request
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

USER_ID = "usr_devlens"
_AUTHENTICATED_AT = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
NOW_UTC = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)

#: The bait every leak assertion below hunts for: a provider "thinking out loud".
PRIVATE_THOUGHT = "The user is probably fishing; I should hedge."


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


# --- harness -------------------------------------------------------------------------------------


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


def _principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=f"wsm_devlens_{workspace_id}",
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=_AUTHENTICATED_AT,
    )


def _app(conn: Any, *, settings: Settings, storage: Any) -> Any:
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
        chat_principal_resolver=lambda workspace_id: _principal(workspace_id),
        ingestion_storage=storage,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _emitter(
    conn: Any,
    *,
    project: Any,
    thread_id: str,
    turn_id: UUID,
    reasoning_trace: bool,
) -> TurnStreamEmitter:
    return await TurnStreamEmitter.open(
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        conn_factory=conn_session_factory(conn),
        policy=TurnStreamPolicy(reasoning_trace=reasoning_trace),
    )


async def _frames(conn: Any, *, workspace_id: str, turn_id: UUID) -> tuple[Any, ...]:
    return await list_turn_events(conn, workspace_id=workspace_id, turn_id=turn_id)


def _reasoning_chunk(text_fragment: str) -> AIMessageChunk:
    """A chunk shaped exactly as ``langchain_openai`` emits a Responses reasoning-summary delta."""

    return AIMessageChunk(
        content=[
            {
                "type": "reasoning",
                "summary": [{"index": 0, "type": "summary_text", "text": text_fragment}],
                "index": 0,
            }
        ]
    )


async def _seed_project(conn: Any, workspace_id: str, *, label: str) -> Any:
    project = await _seed_project_row(conn, workspace_id, name=f"dev lens {label}")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"wsm_devlens_{workspace_id}",
    )
    return project


async def _thread(conn: Any, *, workspace_id: str, project_id: str, label: str) -> str:
    thread_id = f"thr_devlens_{label}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": thread_id, "workspace": workspace_id, "project": project_id, "user": USER_ID},
    )
    return thread_id


# --- half 1, the production negative (SHARPENED, never weakened) ---------------------------------


def test_summary_mode_puts_no_provider_reasoning_on_the_wire() -> None:
    """The ratified §3.3 contract, asserted against a provider that leaks on every chunk.

    The emitter's policy is the shipped default — the only state a production process can hold —
    and the model streams a reasoning summary alongside its finalize argument. Not one byte of it
    may exist anywhere in the outbox, and the ``reasoning`` part must stay the text-free status card
    it has always been.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed_project(conn, "ws-lens-summary", label="summary")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="sum",
            )
            turn_id = uuid5(NAMESPACE_URL, "dev-lens:summary:turn")
            emitter = await _emitter(
                conn,
                project=project,
                thread_id=thread_id,
                turn_id=turn_id,
                reasoning_trace=False,
            )
            assert emitter.reasoning_trace_enabled is False

            await emitter.round_started(round_ordinal=1)
            # Both paths a leak could take: the callback handler's chunk inspection, and a direct
            # call on the emitter (a future caller that forgot the lens).
            handler = TurnStreamCallbackHandler(emitter=emitter)
            handler._rounds[turn_id] = 1  # noqa: SLF001 -- the handler's per-run round map
            await handler.on_llm_new_token(
                "",
                chunk=type("C", (), {"message": _reasoning_chunk(PRIVATE_THOUGHT)})(),
                run_id=turn_id,
            )
            await emitter.reasoning_delta(round_ordinal=1, delta=PRIVATE_THOUGHT)
            await emitter.round_finished(round_ordinal=1, requested_tool_calls=1)
            assert emitter.emission_failures == []

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            whole = json.dumps([frame.envelope() for frame in frames])
            assert PRIVATE_THOUGHT not in whole
            # Not one text.delta exists at all: nothing was streamed, so nothing was dropped later.
            assert [f for f in frames if f.event_type == TurnEventType.TEXT_DELTA.value] == []
            reasoning = [f for f in frames if f.part_kind == PartKind.REASONING.value]
            assert reasoning, "the safe status card must still be emitted"
            for frame in reasoning:
                part = frame.payload["part"]
                assert isinstance(part, dict)
                assert "text" not in part
                assert "text_ephemeral" not in part

    run_async(scenario())


def test_raw_mode_streams_the_reasoning_trace_onto_the_reasoning_part() -> None:
    """The other half of "iff": with the dev lens on, the trace reaches the wire — and only there.

    The emission shape is the decided one: ``text.delta`` frames carrying the *reasoning* part's id
    and ``part_kind='reasoning'``, so no DB CHECK, no event vocabulary and no part vocabulary
    changes. The closing ``part.completed`` snapshot carries the whole accumulated trace plus the
    ephemerality marker, because nothing durable will ever confirm this text.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed_project(conn, "ws-lens-raw", label="raw")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="raw"
            )
            turn_id = uuid5(NAMESPACE_URL, "dev-lens:raw:turn")
            emitter = await _emitter(
                conn, project=project, thread_id=thread_id, turn_id=turn_id, reasoning_trace=True
            )
            await emitter.round_started(round_ordinal=1)
            handler = TurnStreamCallbackHandler(emitter=emitter)
            handler._rounds[turn_id] = 1  # noqa: SLF001
            for fragment in ("The user ", "is probably ", "fishing."):
                await handler.on_llm_new_token(
                    "",
                    chunk=type("C", (), {"message": _reasoning_chunk(fragment)})(),
                    run_id=turn_id,
                )
            await emitter.round_finished(round_ordinal=1, requested_tool_calls=1)
            assert emitter.emission_failures == []

            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            deltas = [f for f in frames if f.event_type == TurnEventType.TEXT_DELTA.value]
            assert deltas, "the lens must actually stream"
            assert {f.part_kind for f in deltas} == {PartKind.REASONING.value}
            assert {f.part_id for f in deltas} == {f"reasoning:{emitter.generation_attempt_id}:1"}
            assert [f.delta_index for f in deltas] == list(range(len(deltas)))
            assert (
                "".join(str(f.payload["delta"]) for f in deltas) == "The user is probably fishing."
            )
            # A reasoning delta belongs to no message: it must not carry one, because a consumer
            # accumulating message text would otherwise splice it into the assistant's answer.
            assert all(f.message_id is None for f in deltas)

            completed = [
                f
                for f in frames
                if f.part_kind == PartKind.REASONING.value
                and f.event_type == TurnEventType.PART_COMPLETED.value
            ]
            assert len(completed) == 1
            part = completed[0].payload["part"]
            assert isinstance(part, dict)
            assert part["text"] == "The user is probably fishing."
            assert part["text_ephemeral"] is True

    run_async(scenario())


def test_a_reasoning_trace_never_enters_the_assistant_message_reconciliation() -> None:
    """§3.3(5) is untouched by the lens.

    Reconciliation joins the deltas of the *text* part and compares them to the durable assistant
    message. A reasoning trace streamed in the same attempt lives on a different part id, so it can
    neither be spliced into the prose nor cause the byte-equality check to fail — which is the whole
    reason the decided shape targets the reasoning part rather than opening a second text part.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed_project(conn, "ws-lens-recon", label="recon")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="rc"
            )
            turn_id = uuid5(NAMESPACE_URL, "dev-lens:recon:turn")
            emitter = await _emitter(
                conn, project=project, thread_id=thread_id, turn_id=turn_id, reasoning_trace=True
            )
            await emitter.round_started(round_ordinal=1)
            await emitter.reasoning_delta(round_ordinal=1, delta=PRIVATE_THOUGHT)
            await emitter.text_delta(round_ordinal=1, call_index=0, delta="Hello, world")
            await emitter.round_finished(round_ordinal=1, requested_tool_calls=1)

            assert await emitter.reconcile_text(assistant_message="Hello, world") is True
            frames = await _frames(conn, workspace_id=project.workspace_id, turn_id=turn_id)
            end = [f for f in frames if f.event_type == TurnEventType.TEXT_END.value]
            assert len(end) == 1
            assert end[0].payload["byte_count"] == len(b"Hello, world")
            # And the two streams stayed on their own parts.
            deltas = [f for f in frames if f.event_type == TurnEventType.TEXT_DELTA.value]
            assert len({f.part_kind for f in deltas}) == 2

    run_async(scenario())


# --- half 1, the pure extractor ------------------------------------------------------------------


def test_reasoning_deltas_are_read_from_every_shape_the_gateway_can_produce() -> None:
    """Three normalized LangChain shapes, one extractor, and nothing else touched.

    The last two assertions are the load-bearing ones: ordinary assistant content and tool-call
    arguments are *not* reasoning and must never come back from here, or this function would become
    a second, ungoverned path for the finalize argument to reach the wire.
    """

    summary = AIMessageChunk(
        content=[
            {
                "type": "reasoning",
                "summary": [{"index": 0, "type": "summary_text", "text": "step one"}],
            }
        ]
    )
    assert reasoning_deltas_from_chunk(summary) == ("step one",)

    thinking = AIMessageChunk(
        content=[
            {
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": "thinking hard"}],
            }
        ]
    )
    assert reasoning_deltas_from_chunk(thinking) == ("thinking hard",)

    passthrough = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "hmm"})
    assert reasoning_deltas_from_chunk(passthrough) == ("hmm",)

    # An opening reasoning item with no text yet produces nothing (no empty deltas on the wire).
    assert reasoning_deltas_from_chunk(AIMessageChunk(content=[{"type": "reasoning"}])) == ()
    # Ordinary prose is not reasoning.
    assert reasoning_deltas_from_chunk(AIMessageChunk(content="Let me think…")) == ()
    assert (
        reasoning_deltas_from_chunk(AIMessageChunk(content=[{"type": "text", "text": "answer"}]))
        == ()
    )
    # Nor is a tool-call argument.
    chunked = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "name": "finalize_turn",
                "args": '{"user_message": "secret"}',
                "id": "c1",
                "index": 0,
                "type": "tool_call_chunk",
            }
        ],
    )
    assert reasoning_deltas_from_chunk(chunked) == ()


# --- half 1, the gateway seam --------------------------------------------------------------------


def test_the_gateway_asks_for_reasoning_only_when_the_lens_configures_it() -> None:
    """The request is a *config* value, and the per-model baseline survives without it."""

    baseline = GatewayConfig()
    assert _reasoning_request(baseline, model_id="openai/gpt-5.6-terra") == {"effort": "high"}
    assert _reasoning_request(baseline, model_id="openai/gpt-5.6-sol") == {"effort": "none"}
    assert _reasoning_request(baseline, model_id="anthropic/claude-sonnet-4") is None

    lens = GatewayConfig(
        agent_reasoning=ReasoningRequest(effort="medium", summary="auto", max_tokens=4096)
    )
    # The override replaces the governed ``effort: none`` baseline — a model told to spend no
    # reasoning effort has no reasoning to expose, so leaving the baseline would make the lens a
    # no-op on exactly the model the platform pins.
    assert _reasoning_request(lens, model_id="openai/gpt-5.6-terra") == {
        "effort": "medium",
        "summary": "auto",
        "max_tokens": 4096,
    }
    assert _reasoning_request(lens, model_id="anthropic/claude-sonnet-4") == {
        "effort": "medium",
        "summary": "auto",
        "max_tokens": 4096,
    }
    # An empty request is not a request: it must not become an empty provider block.
    assert (
        _reasoning_request(GatewayConfig(agent_reasoning=ReasoningRequest()), model_id="x") is None
    )


# --- both halves: production-unreachability ------------------------------------------------------


@pytest.mark.parametrize(
    "flag",
    [
        {"chat_reasoning_trace_mode": "raw"},
        {"chat_dev_inspector_enabled": True},
    ],
)
def test_a_production_process_refuses_to_start_with_either_dev_lens_flag(
    flag: dict[str, object],
) -> None:
    """The whole "dev-only by construction" claim, as a startup refusal.

    Not a request-time check: a production process holding either value does not construct, so
    there is no running deployment in which a later code path could be reached with the flag on.
    Same predicate, same validator, same failure mode as the local-fixture-auth and local-header
    refusals that already guard this settings object.
    """

    production = {
        "auth_enabled": True,
        "auth_environment": "production",
        "auth_mode": "clerk",
        "projections_auth_mode": "authenticated_principal",
    }
    with pytest.raises(ValidationError):
        load_settings(_env_file=None, **production, **flag)
    # …and the same flag is accepted in a dev deployment, so the refusal is about production and
    # not about the flag being unusable.
    assert load_settings(_env_file=None, auth_environment="local", **flag) is not None
    assert load_settings(_env_file=None, **flag) is not None


def test_the_inspector_routes_do_not_exist_unless_the_dev_flag_is_on(tmp_path: Path) -> None:
    """Half 2's structural half: with the flag off the routes are simply not registered.

    Combined with the startup refusal above, the inspector is unreachable in production in the
    strongest available sense — the paths 404 in a process that would not have started.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed_project(conn, "ws-lens-off", label="off")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="off"
            )
            app = _app(conn, settings=_settings(), storage=FsStorage(tmp_path / "off"))
            async with _client(app) as client:
                for path in (
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}/inspector",
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}"
                    f"/turns/{uuid5(NAMESPACE_URL, 'x')}/inspector/context",
                ):
                    response = await client.get(
                        path, headers={"X-Workspace-Id": project.workspace_id}
                    )
                    assert response.status_code == 404, path

    run_async(scenario())


def test_the_body_free_context_ref_route_is_registered_without_the_dev_lens(tmp_path: Path) -> None:
    """S6-C is a production read, not a back door into the body-hydrating dev inspector."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "operator-refs")
            project = await _seed_project(conn, "ws-s6-context-refs", label="refs")
            thread_id = await _thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                label="refs",
            )
            seeded = await _seed_turn_receipts(
                conn,
                project=project,
                thread_id=thread_id,
                label="operator-refs",
                storage=storage,
            )
            app = _app(conn, settings=_settings(), storage=storage)
            path = (
                f"/api/v1/projects/{project.project_id}/threads/{thread_id}"
                f"/turns/{seeded.turn_id}/context-refs"
            )
            async with _client(app) as client:
                response = await client.get(
                    path,
                    headers={"X-Workspace-Id": project.workspace_id},
                )
                inspector = await client.get(
                    path.removesuffix("context-refs") + "inspector/context",
                    headers={"X-Workspace-Id": project.workspace_id},
                )
            assert response.status_code == 200
            assert inspector.status_code == 404
            data = response.json()["data"]
            assert data["state"] == "available"
            assert data["context_bundle_id"]
            assert data["aggregate_sha256"] == "a" * 64
            included = data["layers"][0]["refs"][0]
            assert included["artifact_key"] == seeded.context_artifact_key
            # The schema itself has no hydration field: the sensitive bytes exist in storage but
            # cannot appear through this route, even when a storage backend is composed.
            forbidden = {
                "body",
                "text",
                "claim_value",
                "evidence_span",
                "source_url",
                "email",
                "token",
                "credential",
            }
            encoded = json.dumps(data).casefold()
            assert all(f'"{field}"' not in encoded for field in forbidden)
            assert "you are the head of abm." not in encoded

    run_async(scenario())


def test_the_body_free_context_ref_route_reports_pending_and_refuses_foreign_scope(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "operator-scope")
            owner = await _seed_project(conn, "ws-s6-owner", label="owner")
            foreign = await _seed_project(conn, "ws-s6-foreign", label="foreign")
            owner_thread = await _thread(
                conn,
                workspace_id=owner.workspace_id,
                project_id=owner.project_id,
                label="owner",
            )
            foreign_thread = await _thread(
                conn,
                workspace_id=foreign.workspace_id,
                project_id=foreign.project_id,
                label="foreign",
            )
            seeded = await _seed_turn_receipts(
                conn,
                project=owner,
                thread_id=owner_thread,
                label="pending",
                storage=storage,
                with_context=False,
            )
            app = _app(conn, settings=_settings(), storage=storage)
            owner_path = (
                f"/api/v1/projects/{owner.project_id}/threads/{owner_thread}"
                f"/turns/{seeded.turn_id}/context-refs"
            )
            foreign_path = (
                f"/api/v1/projects/{foreign.project_id}/threads/{foreign_thread}"
                f"/turns/{seeded.turn_id}/context-refs"
            )
            async with _client(app) as client:
                pending = await client.get(
                    owner_path,
                    headers={"X-Workspace-Id": owner.workspace_id},
                )
                refused = await client.get(
                    foreign_path,
                    headers={"X-Workspace-Id": foreign.workspace_id},
                )
            assert pending.status_code == 200
            assert pending.json()["data"] == {
                "turn_id": str(seeded.turn_id),
                "state": "pending",
                "context_bundle_id": None,
                "schema_version": None,
                "policy_version": None,
                "token_counter_version": None,
                "aggregate_sha256": None,
                "assembled_at": None,
                "layers": [],
            }
            assert refused.status_code == 404
            assert refused.json()["error"]["code"] == "TURN_NOT_FOUND"

    run_async(scenario())


# --- half 2: the inspector over real receipts ----------------------------------------------------


class _Turn:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _seed_turn_receipts(
    conn: Any,
    *,
    project: Any,
    thread_id: str,
    label: str,
    storage: Any,
    context_body: bytes = b"You are the Head of ABM.",
    with_context: bool = True,
) -> _Turn:
    """One assistant turn with the full C6 receipt set the four tabs read.

    Written with raw SQL rather than through the production writers on purpose: the inspector's
    contract is *what the rows say*, and a fixture that went through the writers would be testing
    the writers. Every CHECK the tables carry is respected, which is itself part of the proof that
    the shapes served here are the shapes that can exist.
    """

    workspace_id = project.workspace_id
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    context_ref = await artifacts.persist_body(
        workspace_id=workspace_id, data=context_body, media_type="text/plain"
    )
    proposal_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"steps": [{"node_key": "n1"}, {"node_key": "dropped"}]}).encode(),
        media_type="application/json",
    )
    validated_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"steps": [{"node_key": "n1"}]}).encode(),
        media_type="application/json",
    )
    parameter_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"title": "New chat"}).encode(),
        media_type="application/json",
    )
    result_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"references": {"thread_id": "thr_x"}}).encode(),
        media_type="application/json",
    )
    manifest_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )

    turn_id = uuid5(NAMESPACE_URL, f"dev-lens:{label}:turn")
    execution_id = uuid5(NAMESPACE_URL, f"dev-lens:{label}:execution")
    bundle_id = uuid5(NAMESPACE_URL, f"dev-lens:{label}:bundle")
    plan_id = uuid5(NAMESPACE_URL, f"dev-lens:{label}:plan")
    operation_id = uuid5(NAMESPACE_URL, f"dev-lens:{label}:operation")

    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash) "
            "ON CONFLICT (id) DO NOTHING"
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
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor, 'head_of_abm', "
            " :root, 'head-of-abm', 'v22', :sha, :manifest_key, :manifest_sha, :manifest_sha, "
            " 'test', :requested_at)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "actor": USER_ID,
            "root": f"root-{label}",
            "sha": "0" * 64,
            "manifest_key": manifest_ref.artifact_key,
            "manifest_sha": manifest_ref.sha256,
            "requested_at": NOW_UTC,
        },
    )
    for ordinal, (status, reason) in enumerate(
        (("requested", None), ("context_ready", None), ("failed", "plan_rejected")), start=1
    ):
        await conn.execute(
            text(
                "INSERT INTO agent_turn_event (event_id, turn_id, workspace_id, status, "
                " reason_code) VALUES (:event, :turn, :workspace, :status, :reason)"
            ),
            {
                "event": uuid5(NAMESPACE_URL, f"dev-lens:{label}:turn-event:{ordinal}"),
                "turn": turn_id,
                "workspace": workspace_id,
                "status": status,
                "reason": reason,
            },
        )

    # --- context bundle: two layers, one included artifact ref and one excluded domain ref -------
    # Skipped entirely for the "turn that assembled no context" case: these tables are append-only
    # (a DB trigger refuses UPDATE/DELETE), so the absence has to be seeded, never undone.
    if not with_context:
        return _Turn(
            turn_id=turn_id,
            context_artifact_key=context_ref.artifact_key,
            plan_id=plan_id,
            operation_id=operation_id,
        )
    await conn.execute(
        text(
            "INSERT INTO agent_context_bundle "
            "(id, turn_id, execution_id, workspace_id, schema_version, policy_version, "
            " token_counter_version, aggregate_sha256, assembled_at) "
            "VALUES (:id, :turn, :execution, :workspace, '1', 'policy-v1', 'tc-v1', :sha, :at)"
        ),
        {
            "id": bundle_id,
            "turn": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "sha": "a" * 64,
            "at": NOW_UTC,
        },
    )
    for ordinal, layer, included, excluded in (
        (1, "l1_identity", 1, 0),
        (6, "l6_conversation", 0, 1),
    ):
        await conn.execute(
            text(
                "INSERT INTO agent_context_layer "
                "(context_bundle_id, workspace_id, ordinal, layer, token_budget, token_count, "
                " included_count, excluded_count) "
                "VALUES (:bundle, :workspace, :ordinal, :layer, 1000, 40, :included, :excluded)"
            ),
            {
                "bundle": bundle_id,
                "workspace": workspace_id,
                "ordinal": ordinal,
                "layer": layer,
                "included": included,
                "excluded": excluded,
            },
        )
    await conn.execute(
        text(
            "INSERT INTO agent_context_ref "
            "(id, context_bundle_id, workspace_id, layer_ordinal, disposition, ordinal, ref_kind, "
            " artifact_key, artifact_sha256, content_sha256, materialized_path, token_count) "
            "VALUES (:id, :bundle, :workspace, 1, 'included', 0, 'artifact', :key, :sha, :sha, "
            " 'identity/system.md', 40)"
        ),
        {
            "id": uuid5(NAMESPACE_URL, f"dev-lens:{label}:ref:included"),
            "bundle": bundle_id,
            "workspace": workspace_id,
            "key": context_ref.artifact_key,
            "sha": context_ref.sha256,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_context_ref "
            "(id, context_bundle_id, workspace_id, layer_ordinal, disposition, ordinal, ref_kind, "
            " object_type, object_id, object_version, exclusion_reason_code) "
            "VALUES (:id, :bundle, :workspace, 6, 'excluded', 0, 'domain', "
            " 'agent_thread_message', 'msg-old', 1, 'layer_budget_exhausted')"
        ),
        {
            "id": uuid5(NAMESPACE_URL, f"dev-lens:{label}:ref:excluded"),
            "bundle": bundle_id,
            "workspace": workspace_id,
        },
    )

    # --- model rounds ----------------------------------------------------------------------------
    await conn.execute(
        text(
            "INSERT INTO agent_model_call "
            "(id, turn_id, execution_id, workspace_id, sequence, requested_model, "
            " answering_model, status, input_tokens, output_tokens, cost_millicredits, "
            " latency_ms, started_at, completed_at) "
            "VALUES (:id, :turn, :execution, :workspace, 1, 'openai/gpt-5.6-terra', "
            " 'openai/gpt-5.6-terra', 'completed', 1200, 340, 91, 1830.5, :at, :at)"
        ),
        {
            "id": uuid5(NAMESPACE_URL, f"dev-lens:{label}:model-call"),
            "turn": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "at": NOW_UTC,
        },
    )

    # --- plan, its one admitted operation, its ledger, and the operation's receipt ----------------
    await conn.execute(
        text(
            "INSERT INTO agent_plan "
            "(id, turn_id, execution_id, workspace_id, role, proposal_artifact_key, "
            " proposal_sha256, validated_artifact_key, validated_sha256, "
            " resource_manifest_sha256, max_parallelism, estimated_cost_millicents, "
            " budget_limit_millicents, validated_at) "
            "VALUES (:id, :turn, :execution, :workspace, 'head_of_abm', :proposal_key, "
            " :proposal_sha, :validated_key, :validated_sha, :manifest_sha, 4, 120, 5000, :at)"
        ),
        {
            "id": plan_id,
            "turn": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "proposal_key": proposal_ref.artifact_key,
            "proposal_sha": proposal_ref.sha256,
            "validated_key": validated_ref.artifact_key,
            "validated_sha": validated_ref.sha256,
            "manifest_sha": "0" * 64,
            "at": NOW_UTC,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_plan_event (event_id, plan_id, workspace_id, status) "
            "VALUES (:event, :plan, :workspace, 'validated')"
        ),
        {
            "event": uuid5(NAMESPACE_URL, f"dev-lens:{label}:plan-event"),
            "plan": plan_id,
            "workspace": workspace_id,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_plan_operation "
            "(plan_id, workspace_id, ordinal, node_key, operation_id, kind, address, "
            " parameter_artifact_key, parameter_sha256, estimated_cost_millicents, "
            " authority_sha256) "
            "VALUES (:plan, :workspace, 0, 'agent_create_thread_n1', :operation, 'tool', "
            " 'create_thread@1', :key, :sha, 120, :authority)"
        ),
        {
            "plan": plan_id,
            "workspace": workspace_id,
            "operation": operation_id,
            "key": parameter_ref.artifact_key,
            "sha": parameter_ref.sha256,
            "authority": "b" * 64,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_tool_result "
            "(operation_id, plan_id, node_key, workspace_id, tool_address, result_artifact_key, "
            " result_sha256, replayed, reference_count) "
            "VALUES (:operation, :plan, 'agent_create_thread_n1', :workspace, 'create_thread@1', "
            " :key, :sha, false, 1)"
        ),
        {
            "operation": operation_id,
            "plan": plan_id,
            "workspace": workspace_id,
            "key": result_ref.artifact_key,
            "sha": result_ref.sha256,
        },
    )
    return _Turn(
        turn_id=turn_id,
        context_artifact_key=context_ref.artifact_key,
        plan_id=plan_id,
        operation_id=operation_id,
    )


def _inspector_settings(**kwargs: object) -> Settings:
    return _settings(chat_dev_inspector_enabled=True, **kwargs)


def test_the_inspector_serves_the_four_tabs_from_receipts_the_turn_already_wrote(
    tmp_path: Path,
) -> None:
    """Half 2's positive contract, tab by tab, over one fully-receipted turn."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "artifacts")
            project = await _seed_project(conn, "ws-lens-insp", label="insp")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="in"
            )
            seeded = await _seed_turn_receipts(
                conn, project=project, thread_id=thread_id, label="insp", storage=storage
            )
            app = _app(conn, settings=_inspector_settings(), storage=storage)
            base = f"/api/v1/projects/{project.project_id}/threads/{thread_id}"
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(app) as client:
                probe = await client.get(f"{base}/inspector", headers=headers)
                assert probe.status_code == 200
                capability = probe.json()["data"]
                assert capability["enabled"] is True
                assert capability["tabs"] == ["context", "rounds", "plan", "tools"]
                assert capability["bodies_available"] is True

                turn = f"{base}/turns/{seeded.turn_id}/inspector"

                context = (await client.get(f"{turn}/context", headers=headers)).json()["data"]
                assert context["policy_version"] == "policy-v1"
                assert context["truncated"] is False
                layers = {item["layer"]: item for item in context["layers"]}
                assert set(layers) == {"l1_identity", "l6_conversation"}
                assert layers["l1_identity"]["token_count"] == 40
                assert layers["l1_identity"]["token_budget"] == 1000
                included = layers["l1_identity"]["refs"][0]
                # The exact included bytes, hydrated from the content-addressed artifact.
                assert included["body"]["text"] == "You are the Head of ABM."
                assert included["body"]["omitted_reason"] is None
                # An excluded ref carries its reason and no body: it was never put in front of the
                # model, so serving its bytes would answer a question nobody asked.
                excluded = layers["l6_conversation"]["refs"][0]
                assert excluded["exclusion_reason_code"] == "layer_budget_exhausted"
                assert excluded["body"] is None

                rounds = (await client.get(f"{turn}/rounds", headers=headers)).json()["data"]
                assert len(rounds) == 1
                assert rounds[0]["requested_model"] == "openai/gpt-5.6-terra"
                assert rounds[0]["answering_model"] == "openai/gpt-5.6-terra"
                assert rounds[0]["input_tokens"] == 1200
                assert rounds[0]["cost_millicredits"] == 91
                assert rounds[0]["status"] == "completed"

                plan = (await client.get(f"{turn}/plan", headers=headers)).json()["data"]
                assert len(plan["plans"]) == 1
                authored = json.loads(plan["plans"][0]["proposal"]["text"])
                admitted = json.loads(plan["plans"][0]["validated"]["text"])
                # Both documents, so "which step did validation drop?" is answered from receipts.
                assert [step["node_key"] for step in authored["steps"]] == ["n1", "dropped"]
                assert [step["node_key"] for step in admitted["steps"]] == ["n1"]
                assert plan["plans"][0]["operations"][0]["validation"] == "admitted"
                assert plan["plans"][0]["events"][0]["status"] == "validated"
                # The turn ledger is where a *rejected* plan's refusal lives — there is no
                # per-operation "refused" row to invent, and the response says so by carrying this.
                assert ("failed", "plan_rejected") in [
                    (item["status"], item["reason_code"]) for item in plan["turn_events"]
                ]

                tools = (await client.get(f"{turn}/tools", headers=headers)).json()["data"]
                assert len(tools["calls"]) == 1
                call = tools["calls"][0]
                assert call["address"] == "create_thread@1"
                assert json.loads(call["arguments"]["text"]) == {"title": "New chat"}
                assert json.loads(call["result"]["text"]) == {"references": {"thread_id": "thr_x"}}
                assert call["replayed"] is False
                assert call["reference_count"] == 1

    run_async(scenario())


def test_the_inspector_truncates_loudly_rather_than_shortening_a_body(tmp_path: Path) -> None:
    """The byte budget: over-budget bodies come back as refs plus ``budget``, never as cut text.

    A half-rendered prompt would be worse than an absent one — a developer would tune against text
    the model never saw — so the only two outcomes are "the whole body" and "here is its address
    and why you do not have it".
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "budget")
            project = await _seed_project(conn, "ws-lens-budget", label="budget")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="bg"
            )
            body = b"x" * 4096
            seeded = await _seed_turn_receipts(
                conn,
                project=project,
                thread_id=thread_id,
                label="budget",
                storage=storage,
                context_body=body,
            )
            app = _app(
                conn,
                settings=_inspector_settings(chat_dev_inspector_budget_bytes=16),
                storage=storage,
            )
            headers = {"X-Workspace-Id": project.workspace_id}
            turn = (
                f"/api/v1/projects/{project.project_id}/threads/{thread_id}"
                f"/turns/{seeded.turn_id}/inspector"
            )
            async with _client(app) as client:
                context = (await client.get(f"{turn}/context", headers=headers)).json()["data"]
                assert context["truncated"] is True
                assert context["budget_bytes"] == 16
                ref = context["layers"][0]["refs"][0]
                assert ref["body"]["text"] is None
                assert ref["body"]["omitted_reason"] == "budget"
                # The address survives, so the developer can still fetch it deliberately.
                assert ref["body"]["artifact_key"] == seeded.context_artifact_key

    run_async(scenario())


def test_the_inspector_refuses_a_turn_of_another_thread_or_another_workspace(
    tmp_path: Path,
) -> None:
    """404, never 403: a forbidden answer would confirm to somebody who cannot see it that it
    exists. Same scoping rule and same status the gates and messages reads already use."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "scope")
            owner = await _seed_project(conn, "ws-lens-owner", label="owner")
            other = await _seed_project(conn, "ws-lens-other", label="other")
            owner_thread = await _thread(
                conn, workspace_id=owner.workspace_id, project_id=owner.project_id, label="ow"
            )
            decoy_thread = await _thread(
                conn, workspace_id=owner.workspace_id, project_id=owner.project_id, label="dk"
            )
            other_thread = await _thread(
                conn, workspace_id=other.workspace_id, project_id=other.project_id, label="ot"
            )
            seeded = await _seed_turn_receipts(
                conn, project=owner, thread_id=owner_thread, label="scope", storage=storage
            )
            app = _app(conn, settings=_inspector_settings(), storage=storage)
            async with _client(app) as client:
                # Another tenant asking for the same turn id sees nothing.
                cross = await client.get(
                    f"/api/v1/projects/{other.project_id}/threads/{other_thread}"
                    f"/turns/{seeded.turn_id}/inspector/context",
                    headers={"X-Workspace-Id": other.workspace_id},
                )
                assert cross.status_code == 404
                assert cross.json()["error"]["code"] == "TURN_NOT_FOUND"
                # The right tenant, the wrong thread: also not found.
                wrong_thread = await client.get(
                    f"/api/v1/projects/{owner.project_id}/threads/{decoy_thread}"
                    f"/turns/{seeded.turn_id}/inspector/rounds",
                    headers={"X-Workspace-Id": owner.workspace_id},
                )
                assert wrong_thread.status_code == 404
                # A thread that exists in another project of the same workspace: not found.
                wrong_project = await client.get(
                    f"/api/v1/projects/{other.project_id}/threads/{owner_thread}/inspector",
                    headers={"X-Workspace-Id": owner.workspace_id},
                )
                assert wrong_project.status_code == 404
                assert wrong_project.json()["error"]["code"] == "THREAD_NOT_FOUND"

    run_async(scenario())


def test_a_turn_that_assembled_no_context_gets_an_honest_null(tmp_path: Path) -> None:
    """An absent bundle is reported as absent, not as an empty seven-layer skeleton."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "nocontext")
            project = await _seed_project(conn, "ws-lens-empty", label="empty")
            thread_id = await _thread(
                conn, workspace_id=project.workspace_id, project_id=project.project_id, label="em"
            )
            seeded = await _seed_turn_receipts(
                conn,
                project=project,
                thread_id=thread_id,
                label="empty",
                storage=storage,
                with_context=False,
            )
            app = _app(conn, settings=_inspector_settings(), storage=storage)
            async with _client(app) as client:
                response = await client.get(
                    f"/api/v1/projects/{project.project_id}/threads/{thread_id}"
                    f"/turns/{seeded.turn_id}/inspector/context",
                    headers={"X-Workspace-Id": project.workspace_id},
                )
            assert response.status_code == 200
            assert response.json()["data"] is None

    run_async(scenario())
