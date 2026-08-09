"""R2 acceptance: Home creates one real project, thread and queued Deep-Agent turn."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api import build_tool_invoker, create_projections_app
from clue_api.chat import RequestPrincipal
from clue_api.chat.router import _first_thread_title
from clue_api.thread_wiring import register_thread_tools
from clue_auth import permissions_for_role
from clue_config import Settings, load_settings
from clue_spine import create_brand
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import fixture_membership_id, seed_principal
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the DB gate to this module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_home_bootstrap"
_AUTHENTICATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


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


def _settings() -> Settings:
    return load_settings(_env_file=None, chat_enabled=True)


def _principal(workspace_id: str, *, role: str = "owner") -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=USER_ID),
        workspace_id=workspace_id,
        role_key=role,
        permissions=permissions_for_role(role),  # type: ignore[arg-type]
        authenticated_at=_AUTHENTICATED_AT,
    )


def _transactional_conn_factory(conn):
    @asynccontextmanager
    async def factory():
        transaction = await conn.begin_nested()
        try:
            yield conn
        except BaseException:
            await transaction.rollback()
            raise
        else:
            await transaction.commit()

    return factory


def _app(conn, *, role: str = "owner", transactional: bool = False):
    cf = _transactional_conn_factory(conn) if transactional else conn_session_factory(conn)
    storage = _MemoryStorage()
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
    app = create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=storage,
            settings=_settings(),
            conn_factory=cf,
        ),
        settings=_settings(),
        conn_factory=cf,
        ingestion_storage=storage,
        manage_db_lifespan=False,
        chat_principal_resolver=lambda workspace_id: _principal(workspace_id, role=role),
    )
    return app, storage


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _seed(conn, workspace_id: str):
    await seed_workspace(conn, workspace_id)
    await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
    return await create_brand(conn, workspace_id=workspace_id, name="Clue Demo Brand")


async def _workspace_row_count(conn, table: str, workspace_id: str) -> int:
    if table == "fleet_task":
        statement = text(
            "SELECT count(*) FROM fleet_task "
            "WHERE payload_json ->> 'workspace_id' = :workspace_id"
        )
    else:
        statement = text(f"SELECT count(*) FROM {table} WHERE workspace_id = :workspace_id")
    return int(
        (await conn.execute(statement, {"workspace_id": workspace_id})).scalar_one()
    )


def _body(brand_id: str, message: str = "Start an ABM project for Northstar Labs") -> dict:
    return {
        "brand_id": brand_id,
        "message": message,
        "context_refs": [],
        "attachment_refs": [],
        "agent_profile_id": None,
    }


def test_first_thread_title_follows_the_frozen_unicode_rule() -> None:
    assert _first_thread_title("  Plan\tNorthstar\nLabs  ") == "Plan Northstar Labs"
    assert _first_thread_title("x" * 81) == f"{'x' * 79}…"
    title = _first_thread_title(f"{'word ' * 18}tail")
    assert len(title) <= 80
    assert title.endswith("…")
    assert not title.endswith(" …")


def test_home_read_is_real_scoped_and_capability_honest(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-home-read")
            app, _storage = _app(conn)
            async with _client(app) as client:
                response = await client.get(
                    "/api/v1/home",
                    headers={"X-Workspace-Id": "ws-home-read"},
                )
            assert response.status_code == 200, response.text
            assert response.json() == {
                "data": {
                    "brands": [{"id": brand.brand_id, "name": "Clue Demo Brand"}],
                    "default_brand_id": brand.brand_id,
                    "context_entities": [],
                    "agent_profiles": [],
                    "default_agent_profile_id": None,
                    "composer_capabilities": {
                        "context_refs": False,
                        "attachments": False,
                        "agent_profile_selection": False,
                    },
                    "suggestions": [
                        "Find target accounts for our new campaign",
                        "Research the buying committee for a target account",
                        "Plan a personalized ABM campaign",
                    ],
                }
            }

    run_async(scenario())


def test_home_bootstrap_is_atomic_and_exact_replay_is_one_project_turn(
    require_chat_db: None,
) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-home-create")
            app, storage = _app(conn)
            headers = {
                "X-Workspace-Id": "ws-home-create",
                "Idempotency-Key": "home-create-1",
            }
            async with _client(app) as client:
                created = await client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json=_body(brand.brand_id),
                )
                replay = await client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json=_body(brand.brand_id),
                )
            assert created.status_code == 201, created.text
            assert replay.status_code == 200, replay.text
            first = created.json()["data"]
            second = replay.json()["data"]
            assert first["project"]["title"] == "Untitled project"
            assert first["project"]["brand_id"] == brand.brand_id
            assert first["thread"]["title"] == "Start an ABM project for Northstar Labs"
            assert first["thread"]["status"] == "running"
            assert first["turn"]["replayed"] is False
            assert second["turn"]["replayed"] is True
            assert second["project"]["id"] == first["project"]["id"]
            assert second["thread"]["id"] == first["thread"]["id"]
            assert second["turn"]["turn_id"] == first["turn"]["turn_id"]
            assert first["href"] == (
                f"/projects/{first['project']['id']}?thread={first['thread']['id']}"
            )

            counts = {}
            for table in (
                "project",
                "agent_thread",
                "onboarding_input",
                "agent_turn_submission",
                "agent_turn_event_stream",
                "fleet_task",
            ):
                counts[table] = await _workspace_row_count(
                    conn,
                    table,
                    "ws-home-create",
                )
            assert counts == {
                "project": 1,
                "agent_thread": 1,
                "onboarding_input": 1,
                "agent_turn_submission": 1,
                "agent_turn_event_stream": 1,
                "fleet_task": 1,
            }
            assert list(storage.blobs.values()) == [
                b"Start an ABM project for Northstar Labs"
            ]

    run_async(scenario())


def test_home_bootstrap_refuses_conflicts_foreign_brand_and_unavailable_capabilities(
    require_chat_db: None,
) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-home-refuse")
            foreign = await _seed(conn, "ws-home-foreign")
            app, _storage = _app(conn)
            headers = {
                "X-Workspace-Id": "ws-home-refuse",
                "Idempotency-Key": "same-home-key",
            }
            async with _client(app) as client:
                missing_key = await client.post(
                    "/api/v1/projects",
                    headers={"X-Workspace-Id": "ws-home-refuse"},
                    json=_body(brand.brand_id),
                )
                unavailable = await client.post(
                    "/api/v1/projects",
                    headers={**headers, "Idempotency-Key": "unsupported"},
                    json={**_body(brand.brand_id), "context_refs": [
                        {"object_type": "account", "object_id": "acct_1", "version": None}
                    ]},
                )
                foreign_brand = await client.post(
                    "/api/v1/projects",
                    headers={**headers, "Idempotency-Key": "foreign"},
                    json=_body(foreign.brand_id),
                )
                created = await client.post(
                    "/api/v1/projects", headers=headers, json=_body(brand.brand_id)
                )
                conflict = await client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json=_body(brand.brand_id, "A different first message"),
                )
            assert (missing_key.status_code, missing_key.json()["error"]["code"]) == (
                400,
                "IDEMPOTENCY_KEY_REQUIRED",
            )
            assert (unavailable.status_code, unavailable.json()["error"]["code"]) == (
                409,
                "CAPABILITY_UNAVAILABLE",
            )
            assert (foreign_brand.status_code, foreign_brand.json()["error"]["code"]) == (
                404,
                "BRAND_NOT_FOUND",
            )
            assert created.status_code == 201
            assert (conflict.status_code, conflict.json()["error"]["code"]) == (
                409,
                "IDEMPOTENCY_CONFLICT",
            )
            count = await _workspace_row_count(conn, "project", "ws-home-refuse")
            assert count == 1

    run_async(scenario())


def test_viewer_cannot_bootstrap_a_project(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-home-viewer")
            app, _storage = _app(conn, role="viewer")
            async with _client(app) as client:
                response = await client.post(
                    "/api/v1/projects",
                    headers={
                        "X-Workspace-Id": "ws-home-viewer",
                        "Idempotency-Key": "viewer-create",
                    },
                    json=_body(brand.brand_id),
                )
            assert (response.status_code, response.json()["error"]["code"]) == (
                403,
                "PERMISSION_DENIED",
            )
            count = await _workspace_row_count(conn, "project", "ws-home-viewer")
            assert count == 0

    run_async(scenario())


def test_bootstrap_failure_before_commit_leaves_no_partial_domain_rows(
    require_chat_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del require_chat_db

    async def fail_dispatch(*_args, **_kwargs):
        raise RuntimeError("simulated queue refusal")

    monkeypatch.setattr(
        "clue_api.chat.router.dispatch_next_thread_turn",
        fail_dispatch,
    )

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-home-rollback")
            app, _storage = _app(conn, transactional=True)
            async with _client(app) as client:
                response = await client.post(
                    "/api/v1/projects",
                    headers={
                        "X-Workspace-Id": "ws-home-rollback",
                        "Idempotency-Key": "must-roll-back",
                    },
                    json=_body(brand.brand_id),
                )
            assert (response.status_code, response.json()["error"]["code"]) == (
                500,
                "INTERNAL_ERROR",
            )
            for table in (
                "project",
                "agent_thread",
                "onboarding_input",
                "agent_turn_submission",
                "agent_turn_event_stream",
                "fleet_task",
            ):
                count = await _workspace_row_count(
                    conn,
                    table,
                    "ws-home-rollback",
                )
                assert count == 0, table

    run_async(scenario())
