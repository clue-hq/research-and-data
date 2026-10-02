"""B4 slice-3 — the read-side HTTP surface: projections, the tool route, manifest ops, SSE.

Drives the ASGI app in-process via ``httpx.ASGITransport`` on the same event loop as the rollback
connection (the ``handoff_app`` test idiom). Covers the slice exit gates at the HTTP layer:

* **THE SSE replay test (the de-risk):** emit events → connect with ``Last-Event-ID`` mid-stream →
  zero gap (every later seq served, in order), duplicates tolerated by seq; a cursor older than the
  replay horizon → ``stream.reset``; ``stream.hello`` always opens the stream.
* **single-use stream tokens:** the mint route; a second use of the same token is refused (401).
* the projection routes (overview / progress / manifest / readiness) over a live DB-seeded run,
  including ``narrative_emit_skipped`` in the served overview; 404 + tenancy; 401 with no tenant.
* the **tool route**: 422 with machine-readable precondition ``reason_codes``; ``Idempotency-Key``
  replay (second call served from the A9 store, ``replayed: true``); 409 on a same-key body change;
  404 unknown tool; actor header validation.
* **manifest ops**: pause → the run machine really pauses (and resume flips it back); an op with no
  real semantics → 422 with the reason + accepted-op list.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api import (
    build_agent_profile_registry,
    build_tool_invoker,
    build_toolbelt,
    consume_stream_token,
    create_projections_app,
    mint_stream_token,
)
from clue_auth import (
    DatabaseAuthorizer,
    DatabaseIdentityResolver,
    DatabaseMembershipLoader,
    LocalFixtureAuthenticator,
    PrincipalService,
    create_platform_user,
    link_auth_identity,
)
from clue_auth.store import create_workspace_membership, revoke_workspace_membership
from clue_config import load_settings
from clue_core import (
    NARRATIVE_EMIT_SKIPPED_KEY,
    ProjectPhase,
    new_execution_id,
    new_operation_id,
    new_project_run_id,
)
from clue_execution import DbExecutionRunViewReader, emit_run_event
from clue_research.durable import PhaseCheckpointStatus
from clue_toolbelt import DbIdempotencyStore, ToolContext, ToolRegistry
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.projections._helpers import (
    build_surface,
    seed_account_run,
    seed_checkpoint,
    seed_run,
)
from tests.toolbelt.conftest import EchoTool

_WS = "ws-acme"
_OTHER = "ws-other"

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _settings():
    return load_settings(_env_file=None)


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


def _app(
    conn,
    *,
    registry: ToolRegistry | None = None,
    settings=None,
    sse_live_tail: bool = False,
    expose_agent_registry: bool = False,
    auth_service: PrincipalService | None = None,
):
    cf = conn_session_factory(conn)
    resolved_registry = (
        registry
        if registry is not None
        else (
            build_toolbelt(storage=None, gateway=None) if expose_agent_registry else ToolRegistry()
        )
    )
    resolved_settings = settings if settings is not None else _settings()
    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=resolved_registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=resolved_settings,
            conn_factory=cf,
        ),
        settings=resolved_settings,
        conn_factory=cf,
        sse_live_tail=sse_live_tail,
        manage_db_lifespan=False,
        agent_registry=(
            build_agent_profile_registry(resolved_registry) if expose_agent_registry else None
        ),
        auth_service=auth_service,
    )


def test_production_app_construction_requires_authenticated_principal_service() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            settings = load_settings(
                _env_file=None,
                auth_enabled=False,
                auth_environment="production",
                auth_mode="clerk",
                projections_auth_mode="authenticated_principal",
                metrics_exporter="otlp",
                metrics_otlp_endpoint="https://otel.example/v1/metrics",
            )
            with pytest.raises(
                RuntimeError,
                match="production projections require the authenticated principal service",
            ):
                _app(conn, settings=settings)

    run_async(_run())


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _auth_service(conn) -> PrincipalService:
    factory = conn_session_factory(conn)
    return PrincipalService(
        authenticator=LocalFixtureAuthenticator(),
        identity_resolver=DatabaseIdentityResolver(conn_factory=factory),
        authorizer=DatabaseAuthorizer(conn_factory=factory),
        memberships_for_user=DatabaseMembershipLoader(conn_factory=factory),
    )


def _frames(body: str) -> list[dict]:
    """Parse an SSE body into frames of ``{id?, event, data}``."""
    frames: list[dict] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        frame: dict = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            if key == "id":
                frame["id"] = int(value)
            elif key == "event":
                frame["event"] = value
            elif key == "data":
                frame["data"] = json.loads(value)
        frames.append(frame)
    return frames


def test_agent_registry_projection_requires_auth_and_exposes_no_resource_bodies() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            app = _app(conn, expose_agent_registry=True)
            async with _client(app) as client:
                unauthenticated = await client.get("/agent/registry")
                response = await client.get(
                    "/agent/registry",
                    headers={"X-Workspace-Id": _WS},
                )
            assert unauthenticated.status_code == 401
            assert response.status_code == 200
            registry = response.json()["registry"]
            assert registry["roles"]
            encoded = json.dumps(registry)
            assert "prompt_body" not in encoded
            assert "skill_body" not in encoded

    run_async(_run())


async def _mint(client: httpx.AsyncClient, run_id, *, ws: str = _WS) -> str:
    r = await client.post(f"/project_runs/{run_id}/stream_token", headers={"X-Workspace-Id": ws})
    assert r.status_code == 200
    return r.json()["stream_token"]


# --- projections over HTTP -------------------------------------------------------------------


def test_overview_route_serves_live_run_with_gap_marker() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.HANDOFF)
            await seed_account_run(conn, project_run_id=run_id)
            await seed_checkpoint(
                conn,
                project_run_id=run_id,
                phase=ProjectPhase.HANDOFF,
                status=PhaseCheckpointStatus.COMMITTED,
                payload={NARRATIVE_EMIT_SKIPPED_KEY: True, "reason": "no reader"},
            )
            async with _client(_app(conn)) as client:
                ok = await client.get(
                    f"/project_runs/{run_id}/overview", headers={"X-Workspace-Id": _WS}
                )
                cross = await client.get(
                    f"/project_runs/{run_id}/overview", headers={"X-Workspace-Id": _OTHER}
                )
                unauth = await client.get(f"/project_runs/{run_id}/overview")
            assert ok.status_code == 200
            body = ok.json()
            assert body["schema_version"] == "2"
            overview = body["overview"]
            assert overview["narrative_emit_skipped"] is True
            assert overview["handoff_reached"] is True
            assert overview["accounts_total"] == 1
            # Tenancy: cross-tenant is a 404 (indistinguishable from absent); no tenant is 401.
            assert cross.status_code == 404
            assert unauth.status_code == 401

    run_async(_run())


def test_manifest_and_readiness_and_progress_routes() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS, phase=ProjectPhase.DEEP)
            entity = await seed_account_run(conn, project_run_id=run_id, tier="high")
            async with _client(_app(conn)) as client:
                manifest = await client.get(
                    f"/project_runs/{run_id}/manifest", headers={"X-Workspace-Id": _WS}
                )
                readiness = await client.get(
                    f"/project_runs/{run_id}/readiness", headers={"X-Workspace-Id": _WS}
                )
                progress = await client.get(
                    f"/project_runs/{run_id}/accounts/{entity}/progress",
                    headers={"X-Workspace-Id": _WS},
                )
                missing = await client.get(
                    f"/project_runs/{new_project_run_id()}/manifest",
                    headers={"X-Workspace-Id": _WS},
                )
            assert manifest.status_code == 200
            assert manifest.json()["manifest"]["run_status"] == "active"  # review F9a
            nodes = manifest.json()["manifest"]["nodes"]
            keys = {n["node_key"] for n in nodes}
            assert f"account:{entity}" in keys
            assert {f"phase:{p.value}" for p in ProjectPhase} <= keys
            assert readiness.status_code == 200
            assert len(readiness.json()["readiness"]["accounts"]) == 1
            assert progress.status_code == 200
            assert progress.json()["progress"]["account_entity_id"] == str(entity)
            assert missing.status_code == 404

    run_async(_run())


# --- SSE: hello / replay / reset / single-use tokens -----------------------------------------


def test_sse_replay_from_last_event_id_has_zero_gap() -> None:
    """THE de-risk: connect mid-stream with ``Last-Event-ID`` → every later event is served in seq
    order with no gap; the ids are exactly the outbox seqs (duplicates tolerated by seq)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            seqs = []
            for i in range(5):
                ev = await emit_run_event(
                    conn,
                    workspace_id=_WS,
                    run_id=run_id,
                    topic="run.step.progress",
                    payload={"i": i},
                )
                seqs.append(ev.seq)
            async with _client(_app(conn)) as client:
                # First connect: everything from the beginning after stream.hello.
                token = await _mint(client, run_id)
                first = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS},
                )
                assert first.status_code == 200
                assert first.headers["content-type"].startswith("text/event-stream")
                frames = _frames(first.text)
                assert frames[0]["event"] == "stream.hello"
                data_frames = [f for f in frames if "id" in f]
                assert [f["id"] for f in data_frames] == seqs  # zero gap, in order
                assert all(f["event"] == "run.step.progress" for f in data_frames)

                # Disconnect-and-reconnect mid-stream: Last-Event-ID = the 2nd event's seq →
                # exactly the strictly-later events, zero gap, no reset.
                token2 = await _mint(client, run_id)
                second = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token2},
                    headers={"X-Workspace-Id": _WS, "Last-Event-ID": str(seqs[1])},
                )
                frames2 = _frames(second.text)
                assert frames2[0]["event"] == "stream.hello"
                assert [f["event"] for f in frames2].count("stream.reset") == 0
                assert [f["id"] for f in frames2 if "id" in f] == seqs[2:]

                # Overlapping replay (a duplicate of an already-seen event) is tolerated by seq:
                # re-connecting with an EARLIER cursor re-serves seqs the client saw — same ids.
                token3 = await _mint(client, run_id)
                third = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token3},
                    headers={"X-Workspace-Id": _WS, "Last-Event-ID": str(seqs[0])},
                )
                assert [f["id"] for f in _frames(third.text) if "id" in f] == seqs[1:]

    run_async(_run())


def test_sse_reconnect_replays_journaled_node_events_without_a_gap() -> None:
    """A recipe-owned execution projects node events into the existing project-run SSE outbox."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            project_id = (
                await conn.execute(
                    text("SELECT project_id FROM project_run WHERE id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()
            execution_id = new_execution_id()
            await conn.execute(
                text(
                    """
                    INSERT INTO execution
                        (id, workspace_id, project_id, project_run_id, started_by,
                         parameter_manifest_hash, pin_manifest_hash)
                    VALUES (:id, :workspace_id, :project_id, :run_id, 'agent', :hash, :hash)
                    """
                ),
                {
                    "id": execution_id,
                    "workspace_id": _WS,
                    "project_id": project_id,
                    "run_id": run_id,
                    "hash": "a" * 64,
                },
            )
            registry = ToolRegistry()
            tool = EchoTool()
            registry.register(tool, make_default=True)
            cf = conn_session_factory(conn)
            settings = _settings()
            invoker = build_tool_invoker(
                registry=registry,
                idempotency_store=DbIdempotencyStore(conn_factory=cf),
                storage=_MemoryStorage(),
                settings=settings,
                conn_factory=cf,
            )
            await invoker.invoke(
                tool.name,
                {"value": 8},
                ToolContext(
                    workspace_id=_WS,
                    actor="agent",
                    conn_factory=cf,
                    operation_id=new_operation_id(),
                    execution_id=execution_id,
                    execution_node_key="echo-node",
                ),
            )
            execution_view = await DbExecutionRunViewReader(conn_factory=cf).read_execution(
                workspace_id=_WS,
                execution_id=execution_id,
            )
            assert execution_view is not None
            assert execution_view.summary.project_run_id == run_id
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT seq, topic FROM run_event "
                            "WHERE run_id = :run_id AND execution_id = :execution_id ORDER BY seq"
                        ),
                        {"run_id": run_id, "execution_id": execution_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [row["topic"] for row in stored] == [
                "node.scheduled",
                "node.started",
                "node.completed",
            ]

            app = create_projections_app(
                surface=build_surface(conn),
                tool_invoker=invoker,
                settings=settings,
                conn_factory=cf,
                sse_live_tail=False,
                manage_db_lifespan=False,
            )
            async with _client(app) as client:
                token = await _mint(client, run_id)
                response = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token},
                    headers={
                        "X-Workspace-Id": _WS,
                        "Last-Event-ID": str(stored[0]["seq"]),
                    },
                )
            frames = _frames(response.text)
            journal_frames = [frame for frame in frames if frame["event"].startswith("node.")]
            assert [frame["id"] for frame in journal_frames] == [row["seq"] for row in stored[1:]]
            assert [frame["event"] for frame in journal_frames] == [
                "node.started",
                "node.completed",
            ]

    run_async(_run())


def test_sse_cursor_older_than_horizon_gets_stream_reset() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            old = await emit_run_event(
                conn, workspace_id=_WS, run_id=run_id, topic="run.phase.started", payload={}
            )
            new = await emit_run_event(
                conn, workspace_id=_WS, run_id=run_id, topic="run.phase.completed", payload={}
            )
            # Age the cursor's event past the replay horizon.
            await conn.execute(
                text(
                    "UPDATE run_event SET created_at = now() - make_interval(secs => :s) "
                    "WHERE seq = :seq"
                ),
                {"s": _settings().sse_replay_horizon_s + 3600, "seq": old.seq},
            )
            async with _client(_app(conn)) as client:
                token = await _mint(client, run_id)
                r = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS, "Last-Event-ID": str(old.seq)},
                )
            frames = _frames(r.text)
            events = [f["event"] for f in frames]
            assert events[0] == "stream.hello"
            assert "stream.reset" in events  # the horizon contract
            # After a reset the backlog restarts from seq 0 (review F1) — the COMPLETE
            # still-available history, not just what was newer than the aged cursor.
            assert [f["id"] for f in frames if "id" in f] == [old.seq, new.seq]

    run_async(_run())


def test_stream_token_is_single_use() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            async with _client(_app(conn)) as client:
                token = await _mint(client, run_id)
                first = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS},
                )
                assert first.status_code == 200
                # Second use of the SAME token: refused (single-use).
                second = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS},
                )
                assert second.status_code == 401
                # A cross-tenant consume of a fresh token is refused too (no leak).
                token2 = await _mint(client, run_id)
                cross = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token2},
                    headers={"X-Workspace-Id": _OTHER},
                )
                assert cross.status_code == 401
                # A garbage token: 401, not a traceback.
                garbage = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": "not-a-token"},
                    headers={"X-Workspace-Id": _WS},
                )
                assert garbage.status_code == 401

    run_async(_run())


# --- the tool route + manifest ops -----------------------------------------------------------


def _toolbelt(conn) -> ToolRegistry:
    from clue_api.toolbelt_wiring import build_toolbelt

    return build_toolbelt(storage=None, gateway=None, conn_factory=conn_session_factory(conn))


def test_tool_route_precondition_422_replay_and_conflict() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await seed_workspace(conn, _WS)
            app = _app(conn, registry=_toolbelt(conn))
            async with _client(app) as client:
                headers = {"X-Workspace-Id": _WS}
                # Unmet precondition → 422 with the machine-readable reason codes.
                refused = await client.post(
                    "/tools/pause_run",
                    json={"project_run_id": str(uuid4())},
                    headers=headers,
                )
                assert refused.status_code == 422
                detail = refused.json()["detail"]
                assert detail["error"] == "precondition_failed"
                assert detail["reason_codes"] == ["run_not_found"]
                assert detail["failures"][0]["reason_code"] == "run_not_found"

                # Unknown tool → 404.
                unknown = await client.post("/tools/nope", json={}, headers=headers)
                assert unknown.status_code == 404

                # Bad actor header → 422.
                bad_actor = await client.post(
                    "/tools/estimate_project",
                    json={},
                    headers={**headers, "X-Actor": "robot"},
                )
                assert bad_actor.status_code == 422

                # Idempotency-Key replay: first executes, second replays the stored response.
                key = f"key-{uuid4()}"
                body = {"projected_account_count": 10}
                first = await client.post(
                    "/tools/estimate_project",
                    json=body,
                    headers={**headers, "Idempotency-Key": key},
                )
                assert first.status_code == 200
                assert first.json()["result"]["replayed"] is False
                replay = await client.post(
                    "/tools/estimate_project",
                    json=body,
                    headers={**headers, "Idempotency-Key": key},
                )
                assert replay.status_code == 200
                assert replay.json()["result"]["replayed"] is True
                assert replay.json()["result"]["references"] == first.json()["result"]["references"]

                # Same key + a DIFFERENT body → 409 IdempotencyConflict.
                conflict = await client.post(
                    "/tools/estimate_project",
                    json={"projected_account_count": 99},
                    headers={**headers, "Idempotency-Key": key},
                )
                assert conflict.status_code == 409
                assert conflict.json()["detail"]["error"] == "idempotency_conflict"

    run_async(_run())


def test_authenticated_tool_route_ignores_actor_header_and_journals_internal_principal() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await seed_workspace(conn, _WS)
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="tool-user",
            )
            membership = await create_workspace_membership(
                conn,
                workspace_id=_WS,
                user_id=user.user_id,
                role_key="operator",
            )
            registry = ToolRegistry()
            registry.register(EchoTool(), make_default=True)
            app = _app(conn, registry=registry, auth_service=_auth_service(conn))
            async with _client(app) as client:
                response = await client.post(
                    "/tools/echo",
                    json={"value": 8},
                    headers={
                        "X-Clue-Local-Auth-Subject": "tool-user",
                        "X-Clue-Workspace-Id": _WS,
                        "X-Actor": "agent",
                    },
                )
            assert response.status_code == 200
            authority = (
                await conn.execute(
                    text(
                        "SELECT invocation_actor, principal_kind, actor_id, membership_id "
                        "FROM execution_node_authority ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).one()
            assert authority == ("human", "human", user.user_id, membership.membership_id)

    run_async(_run())


def test_authenticated_selector_cannot_cross_workspace_or_write() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await seed_workspace(conn, _WS)
            await seed_workspace(conn, _OTHER)
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="workspace-bound-user",
            )
            await create_workspace_membership(
                conn,
                workspace_id=_WS,
                user_id=user.user_id,
                role_key="operator",
            )
            registry = ToolRegistry()
            registry.register(EchoTool(), make_default=True)
            app = _app(conn, registry=registry, auth_service=_auth_service(conn))
            before = int(
                (
                    await conn.execute(text("SELECT count(*) FROM execution_node_authority"))
                ).scalar_one()
            )
            async with _client(app) as client:
                tool_response = await client.post(
                    "/tools/echo",
                    json={"value": 8},
                    headers={
                        "X-Clue-Local-Auth-Subject": "workspace-bound-user",
                        "X-Clue-Workspace-Id": _OTHER,
                        "X-Workspace-Id": _WS,
                        "Idempotency-Key": "cross-workspace-attempt",
                    },
                )
                launch_response = await client.post(
                    "/tools/launch_account_research",
                    json={},
                    headers={
                        "X-Clue-Local-Auth-Subject": "workspace-bound-user",
                        "X-Clue-Workspace-Id": _OTHER,
                    },
                )
                stream_response = await client.post(
                    f"/project_runs/{new_project_run_id()}/stream_token",
                    headers={
                        "X-Clue-Local-Auth-Subject": "workspace-bound-user",
                        "X-Clue-Workspace-Id": _OTHER,
                    },
                )
            after = int(
                (
                    await conn.execute(text("SELECT count(*) FROM execution_node_authority"))
                ).scalar_one()
            )
            for response in (tool_response, launch_response, stream_response):
                assert response.status_code == 403
                assert response.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"
            assert after == before

    run_async(_run())


def test_membership_revocation_blocks_the_next_request_without_a_new_write() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await seed_workspace(conn, _WS)
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="revoked-user",
            )
            membership = await create_workspace_membership(
                conn,
                workspace_id=_WS,
                user_id=user.user_id,
                role_key="operator",
            )
            registry = ToolRegistry()
            registry.register(EchoTool(), make_default=True)
            app = _app(conn, registry=registry, auth_service=_auth_service(conn))
            async with _client(app) as client:
                accepted = await client.post(
                    "/tools/echo",
                    json={"value": 1},
                    headers={
                        "X-Clue-Local-Auth-Subject": "revoked-user",
                        "X-Clue-Workspace-Id": _WS,
                        "Idempotency-Key": "before-revocation",
                    },
                )
                assert accepted.status_code == 200
                before = int(
                    (
                        await conn.execute(text("SELECT count(*) FROM execution_node_authority"))
                    ).scalar_one()
                )
                await revoke_workspace_membership(conn, membership.membership_id)
                refused = await client.post(
                    "/tools/echo",
                    json={"value": 2},
                    headers={
                        "X-Clue-Local-Auth-Subject": "revoked-user",
                        "X-Clue-Workspace-Id": _WS,
                        "Idempotency-Key": "after-revocation",
                    },
                )
            after = int(
                (
                    await conn.execute(text("SELECT count(*) FROM execution_node_authority"))
                ).scalar_one()
            )
            assert refused.status_code == 403
            assert refused.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"
            assert after == before

    run_async(_run())


def test_provider_swap_keeps_the_same_durable_actor_and_membership() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await seed_workspace(conn, _WS)
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="provider-subject-one",
            )
            await link_auth_identity(
                conn,
                user_id=user.user_id,
                provider_key="local_fixture",
                provider_subject="provider-subject-two",
            )
            membership = await create_workspace_membership(
                conn,
                workspace_id=_WS,
                user_id=user.user_id,
                role_key="operator",
            )
            registry = ToolRegistry()
            registry.register(EchoTool(), make_default=True)
            app = _app(conn, registry=registry, auth_service=_auth_service(conn))
            async with _client(app) as client:
                for index, subject in enumerate(
                    ("provider-subject-one", "provider-subject-two"), start=1
                ):
                    response = await client.post(
                        "/tools/echo",
                        json={"value": index},
                        headers={
                            "X-Clue-Local-Auth-Subject": subject,
                            "X-Clue-Workspace-Id": _WS,
                            "Idempotency-Key": f"provider-swap-{index}",
                        },
                    )
                    assert response.status_code == 200
            authority = (
                (
                    await conn.execute(
                        text(
                            "SELECT actor_id, membership_id FROM execution_node_authority "
                            "ORDER BY created_at DESC LIMIT 2"
                        )
                    )
                )
                .tuples()
                .all()
            )
            assert authority == [
                (user.user_id, membership.membership_id),
                (user.user_id, membership.membership_id),
            ]

    run_async(_run())


def test_manifest_ops_pause_resume_and_unsupported_422() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            app = _app(conn, registry=_toolbelt(conn))
            async with _client(app) as client:
                headers = {"X-Workspace-Id": _WS}
                # pause maps to the run machine — the run really pauses.
                paused = await client.request(
                    "PATCH",
                    f"/project_runs/{run_id}/manifest",
                    json={"op": "pause"},
                    headers=headers,
                )
                assert paused.status_code == 200
                assert paused.json()["result"]["references"]["status"] == "paused"
                # resume flips it back (no queue wired → enqueued False, status active).
                resumed = await client.request(
                    "PATCH",
                    f"/project_runs/{run_id}/manifest",
                    json={"op": "resume"},
                    headers=headers,
                )
                assert resumed.status_code == 200
                assert resumed.json()["result"]["references"]["status"] == "active"
                # adjust requires the cap → 422 without it; applies with it.
                no_cap = await client.request(
                    "PATCH",
                    f"/project_runs/{run_id}/manifest",
                    json={"op": "adjust"},
                    headers=headers,
                )
                assert no_cap.status_code == 422
                # The op IS supported; the request is missing its parameter (review F9b).
                assert no_cap.json()["detail"]["error"] == "invalid_params"
                adjusted = await client.request(
                    "PATCH",
                    f"/project_runs/{run_id}/manifest",
                    json={"op": "adjust", "budget_cap_cents": 5000},
                    headers=headers,
                )
                assert adjusted.status_code == 200
                assert adjusted.json()["result"]["references"]["budget_cap_cents"] == "5000"
                # An op with no real semantics today → 422 with the reason + accepted list.
                invalid = await client.request(
                    "PATCH",
                    f"/project_runs/{run_id}/manifest",
                    json={"op": "retry_node"},
                    headers=headers,
                )
                assert invalid.status_code == 422
                detail = invalid.json()["detail"]
                assert detail["error"] == "unsupported_manifest_op"
                assert detail["reason"] == "unsupported_op"
                assert detail["accepted_ops"] == ["adjust", "pause", "resume"]

    run_async(_run())


# --- slice-3 review fixes (F1/F2/F3/F7/F8) ---------------------------------------------------


def test_sse_unknown_cursor_resets_and_serves_full_backlog() -> None:
    """Review F1: a corrupted/future/cross-environment ``Last-Event-ID`` must not become the tail
    floor — the plan resets, the effective cursor drops to 0, and the COMPLETE backlog is served
    (pre-fix: reset frame + permanently dead stream that matched nothing forever)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            seqs = []
            for i in range(3):
                ev = await emit_run_event(
                    conn,
                    workspace_id=_WS,
                    run_id=run_id,
                    topic="run.step.progress",
                    payload={"i": i},
                )
                seqs.append(ev.seq)
            async with _client(_app(conn)) as client:
                token = await _mint(client, run_id)
                r = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS, "Last-Event-ID": "10000000"},
                )
            frames = _frames(r.text)
            events = [f["event"] for f in frames]
            assert events[0] == "stream.hello"
            assert "stream.reset" in events
            # The full backlog is served — the bogus cursor never filters delivery.
            assert [f["id"] for f in frames if "id" in f] == seqs

    run_async(_run())


def test_stream_token_is_run_bound() -> None:
    """Review F2: a token minted for run A must not open run B's stream (same workspace)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_a = await seed_run(conn, workspace_id=_WS)
            run_b = await seed_run(conn, workspace_id=_WS)
            async with _client(_app(conn)) as client:
                token = await _mint(client, run_a)
                other = await client.get(
                    f"/project_runs/{run_b}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS},
                )
                assert other.status_code == 401
                # The token is NOT consumed by the refused attempt's UPDATE (no matching row), so
                # it still opens the stream it was minted for.
                own = await client.get(
                    f"/project_runs/{run_a}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS},
                )
                assert own.status_code == 200

    run_async(_run())


def test_schema_version_header_served_on_json_and_sse() -> None:
    """Review F3: the declared ``X-Projections-Schema-Version`` header is actually set — on JSON
    routes and on the SSE response (headers precede the streamed body)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            async with _client(_app(conn)) as client:
                overview = await client.get(
                    f"/project_runs/{run_id}/overview", headers={"X-Workspace-Id": _WS}
                )
                token = await _mint(client, run_id)
                sse = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token},
                    headers={"X-Workspace-Id": _WS},
                )
            assert overview.headers["X-Projections-Schema-Version"] == "2"
            assert sse.headers["X-Projections-Schema-Version"] == "2"

    run_async(_run())


def test_stream_token_mint_refuses_absent_or_cross_tenant_run() -> None:
    """Review F7: minting on a nonexistent or cross-tenant run is a 404 (indistinguishable from
    absent — the same posture as the projection routes), not an open-ended token."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            async with _client(_app(conn)) as client:
                cross = await client.post(
                    f"/project_runs/{run_id}/stream_token", headers={"X-Workspace-Id": _OTHER}
                )
                absent = await client.post(
                    f"/project_runs/{new_project_run_id()}/stream_token",
                    headers={"X-Workspace-Id": _WS},
                )
            assert cross.status_code == 404
            assert absent.status_code == 404

    run_async(_run())


def test_garbage_last_event_id_header_falls_back_to_query_cursor() -> None:
    """Review F8: an unparseable ``Last-Event-ID`` header falls back to the query cursor instead
    of discarding it (pre-fix: garbage header silently restarted the stream from zero)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            seqs = []
            for i in range(3):
                ev = await emit_run_event(
                    conn,
                    workspace_id=_WS,
                    run_id=run_id,
                    topic="run.step.progress",
                    payload={"i": i},
                )
                seqs.append(ev.seq)
            async with _client(_app(conn)) as client:
                token = await _mint(client, run_id)
                r = await client.get(
                    f"/project_runs/{run_id}/events",
                    params={"stream_token": token, "last_event_id": seqs[0]},
                    headers={"X-Workspace-Id": _WS, "Last-Event-ID": "not-a-number"},
                )
            frames = _frames(r.text)
            assert [f["event"] for f in frames].count("stream.reset") == 0
            assert [f["id"] for f in frames if "id" in f] == seqs[1:]

    run_async(_run())


def test_stream_tokens_are_subject_bound_not_run_bound() -> None:
    """D7: a stream token authorises one **subject**, so the one auth model already covers a
    design leg's stream (which Round B mounts). Proven at the store, since the HTTP surface stays
    project-run-scoped this round: a design-subject token opens only its own subject, a
    project-run token is unchanged, and naming a subject two ways at once is refused rather than
    silently reconciled (a token bound to a subject the caller did not mean is an auth bug)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = await seed_run(conn, workspace_id=_WS)
            design_run = "run_0123456789abcdef0123456789abcdef"
            ttl = 300.0

            # A project-run token: unchanged behaviour through the pre-D7 keyword.
            project_token = await mint_stream_token(
                conn, workspace_id=_WS, run_id=run_id, ttl_s=ttl
            )
            assert await consume_stream_token(
                conn, token=project_token, workspace_id=_WS, run_id=run_id
            )

            # A design-subject token opens its subject exactly once…
            design_token = await mint_stream_token(
                conn,
                workspace_id=_WS,
                subject_kind="design_run",
                subject_id=design_run,
                ttl_s=ttl,
            )
            assert await consume_stream_token(
                conn,
                token=design_token,
                workspace_id=_WS,
                subject_kind="design_run",
                subject_id=design_run,
            )
            assert not await consume_stream_token(
                conn,
                token=design_token,
                workspace_id=_WS,
                subject_kind="design_run",
                subject_id=design_run,
            )

            # …and never another subject, another tenant, or a project run.
            wrong = await mint_stream_token(
                conn,
                workspace_id=_WS,
                subject_kind="design_run",
                subject_id=design_run,
                ttl_s=ttl,
            )
            assert not await consume_stream_token(
                conn,
                token=wrong,
                workspace_id=_WS,
                subject_kind="design_run",
                subject_id="run_ffffffffffffffffffffffffffffffff",
            )
            assert not await consume_stream_token(
                conn,
                token=wrong,
                workspace_id=_OTHER,
                subject_kind="design_run",
                subject_id=design_run,
            )
            assert not await consume_stream_token(
                conn, token=wrong, workspace_id=_WS, run_id=run_id
            )
            # None of those refusals consumed it — it still opens its own subject.
            assert await consume_stream_token(
                conn,
                token=wrong,
                workspace_id=_WS,
                subject_kind="design_run",
                subject_id=design_run,
            )

            # A workspace-wide token (all subject columns NULL) still opens any subject's stream.
            wide = await mint_stream_token(conn, workspace_id=_WS, ttl_s=ttl)
            assert await consume_stream_token(
                conn,
                token=wide,
                workspace_id=_WS,
                subject_kind="design_run",
                subject_id=design_run,
            )

            with pytest.raises(ValueError, match="not both"):
                await mint_stream_token(
                    conn,
                    workspace_id=_WS,
                    run_id=run_id,
                    subject_kind="design_run",
                    subject_id=design_run,
                    ttl_s=ttl,
                )
            with pytest.raises(ValueError, match="together"):
                await mint_stream_token(
                    conn, workspace_id=_WS, subject_kind="design_run", ttl_s=ttl
                )

    run_async(_run())


def test_healthz_answers_without_auth_or_workspace() -> None:
    """Liveness for Railway, the uptime monitors and the boot smoke test (first deployment §9.5)."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn, _client(_app(conn)) as client:
            response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    run_async(_run())
