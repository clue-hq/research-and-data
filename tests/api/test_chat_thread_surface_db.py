"""FI Lane D D0 — the `/api/v1` chat surface end to end (DB-gated).

Drives the real ASGI app in-process over the test's rolled-back connection (the
``test_projections_app`` idiom), with the four governed thread tools registered in a real
``ToolRegistry`` behind a real ``ToolInvoker`` — so what these tests exercise is the whole path the
frontend will use: HTTP → principal → permission → toolbelt → durable row.

The D0 acceptance criteria this file owns:

* thread CRUD round-trips over HTTP with the injected test principal;
* **no provider identifier reaches any row** — the only identities written are the Clue-owned
  internal ids the principal carried;
* a cross-workspace mutation is a typed refusal in the FI-1 error envelope, never a 500 and never
  a leak;
* the surface is absent entirely when its flag is off;
* enabling it in production without an injected Lane-B principal resolver fails at *startup*.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_api import build_tool_invoker, create_projections_app
from clue_api.chat import (
    CHAT_PERMISSIONS,
    PERMISSION_THREAD_WRITE,
    ProductionPrincipalRequired,
    RequestPrincipal,
    install_chat_surface,
)
from clue_config import Settings, load_settings
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

#: The internal ids the injected principal carries. Deliberately Clue-shaped
#: (``platform_user.user_id`` / ``workspace_membership.membership_id``) and deliberately not
#: anything a provider could have issued — the point of the "no provider id" assertion below.
USER_ID = "usr_d0_test"
MEMBERSHIP_ID = "wsm_d0_test"

#: What a Clerk-shaped identifier looks like. No column may ever contain one.
PROVIDER_SUBJECT = "user_2abcCLERKsubject"


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


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


async def seed_project(conn, workspace_id: str, *, name: str):
    """Seed the project **and** the principal's Lane B rows.

    Lane D's B1-join migration made ``agent_thread.created_by_user_id`` a real foreign key onto
    ``platform_user``, so the identity this suite's principal carries must exist before any thread
    it creates can be written.
    """

    project = await _seed_project_row(conn, workspace_id, name=name)
    await seed_principal(conn, workspace_id=workspace_id, user_id=USER_ID)
    return project


def _principal(workspace_id: str, *, permissions: frozenset[str] | None = None) -> RequestPrincipal:
    return RequestPrincipal(
        principal_kind="human",
        user_id=USER_ID,
        membership_id=MEMBERSHIP_ID,
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS if permissions is None else permissions,
    )


def _app(conn, *, settings: Settings, permissions: frozenset[str] | None = None):
    """The real projections app with the chat surface mounted and a real thread toolbelt."""

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
        chat_principal_resolver=lambda workspace_id: _principal(
            workspace_id, permissions=permissions
        ),
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def test_thread_crud_round_trips_over_http_with_the_injected_principal(
    require_chat_db: None,
) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-http", name="D0 http")
            headers = {"X-Workspace-Id": project.workspace_id}
            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                created = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads",
                    json={"title": "Landing page concepts"},
                    headers=headers,
                )
                assert created.status_code == 201, created.text
                thread = created.json()["data"]
                assert thread["title"] == "Landing page concepts"
                assert thread["status"] == "idle"
                assert thread["pinned"] is False
                assert thread["id"].startswith("thr_")
                assert thread["href"] == (f"/projects/{project.project_id}?thread={thread['id']}")
                assert created.headers["X-Request-Id"]

                listed = await client.get(
                    f"/api/v1/projects/{project.project_id}/threads", headers=headers
                )
                assert listed.status_code == 200
                assert [item["id"] for item in listed.json()["data"]] == [thread["id"]]
                assert listed.json()["meta"]["next_cursor"] is None

                renamed = await client.patch(
                    f"/api/v1/projects/{project.project_id}/threads/{thread['id']}",
                    json={"title": "Enterprise account research", "pinned": True},
                    headers=headers,
                )
                assert renamed.status_code == 200, renamed.text
                assert renamed.json()["data"]["title"] == "Enterprise account research"
                assert renamed.json()["data"]["pinned"] is True

                archived = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads/{thread['id']}/archive",
                    headers=headers,
                )
                assert archived.status_code == 200, archived.text
                assert archived.json()["data"]["status"] == "archived"

                # Archived threads leave the default active view but are never deleted.
                active = await client.get(
                    f"/api/v1/projects/{project.project_id}/threads",
                    params={"status": "active"},
                    headers=headers,
                )
                assert active.json()["data"] == []
                everything = await client.get(
                    f"/api/v1/projects/{project.project_id}/threads", headers=headers
                )
                assert [item["id"] for item in everything.json()["data"]] == [thread["id"]]

                # An archived thread refuses a rename with its stable reason code, not a 500.
                refused = await client.patch(
                    f"/api/v1/projects/{project.project_id}/threads/{thread['id']}",
                    json={"title": "too late"},
                    headers=headers,
                )
                assert refused.status_code == 409
                assert refused.json()["error"]["code"] == "THREAD_ARCHIVED"
                assert refused.json()["error"]["requestId"]

            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT created_by_user_id, created_via_membership_id, status, "
                            "pinned, title, workspace_id, project_id FROM agent_thread "
                            "WHERE id = :id"
                        ),
                        {"id": thread["id"]},
                    )
                )
                .mappings()
                .one()
            )
            # The creator is the principal's *internal* id, taken from ambient authority — the
            # request body never carried one. Membership stays NULL until Lane B B4 threads it
            # through the ToolContext seam; a fabricated value would be worse than an absent one.
            assert row["created_by_user_id"] == USER_ID
            assert row["created_via_membership_id"] is None
            assert row["status"] == "archived"
            assert row["title"] == "Enterprise account research"

    run_async(scenario())


def test_no_provider_identifier_can_reach_a_thread_row(require_chat_db: None) -> None:
    """A client that shouts a Clerk subject at the surface still writes only internal ids.

    Lane B ruling 3: no provider value is a key, a foreign key, or a stored identity. The surface
    reads no identity header at all, so the only way this could fail is a route accepting one — and
    the request body forbids unknown fields outright.
    """

    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-noprovider", name="D0 no provider")
            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                smuggled = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads",
                    json={"title": "smuggle", "created_by_user_id": PROVIDER_SUBJECT},
                    headers={"X-Workspace-Id": project.workspace_id},
                )
                # An unknown body field is a loud refusal, not a silently ignored key.
                assert smuggled.status_code == 422
                assert smuggled.json()["error"]["code"] == "VALIDATION_ERROR"

                created = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads",
                    json={"title": "honest"},
                    headers={
                        "X-Workspace-Id": project.workspace_id,
                        # Headers a provider adapter might set. Domain code reads none of them.
                        "X-User-Id": PROVIDER_SUBJECT,
                        "Authorization": f"Bearer {PROVIDER_SUBJECT}",
                    },
                )
                assert created.status_code == 201

            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, created_by_user_id, created_via_membership_id, title "
                            "FROM agent_thread WHERE workspace_id = :workspace"
                        ),
                        {"workspace": project.workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [row["title"] for row in rows] == ["honest"]
            for row in rows:
                assert row["created_by_user_id"] == USER_ID
                assert PROVIDER_SUBJECT not in str(dict(row))

    run_async(scenario())


def test_a_thread_in_another_workspace_is_indistinguishable_from_one_that_never_existed(
    require_chat_db: None,
) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            mine = await seed_project(conn, "ws-d0-mine", name="D0 mine")
            theirs = await seed_project(conn, "ws-d0-theirs", name="D0 theirs")
            app = _app(conn, settings=_settings())
            async with _client(app) as client:
                created = await client.post(
                    f"/api/v1/projects/{theirs.project_id}/threads",
                    json={"title": "theirs"},
                    headers={"X-Workspace-Id": theirs.workspace_id},
                )
                assert created.status_code == 201
                foreign_id = created.json()["data"]["id"]

                for response in (
                    await client.patch(
                        f"/api/v1/projects/{mine.project_id}/threads/{foreign_id}",
                        json={"title": "mine now"},
                        headers={"X-Workspace-Id": mine.workspace_id},
                    ),
                    await client.post(
                        f"/api/v1/projects/{mine.project_id}/threads/{foreign_id}/archive",
                        headers={"X-Workspace-Id": mine.workspace_id},
                    ),
                ):
                    assert response.status_code == 404
                    assert response.json()["error"]["code"] == "THREAD_NOT_FOUND"

                # Same shape as a genuinely absent thread — the two are not distinguishable.
                absent = await client.patch(
                    f"/api/v1/projects/{mine.project_id}/threads/thr_nothing",
                    json={"title": "x"},
                    headers={"X-Workspace-Id": mine.workspace_id},
                )
                assert absent.status_code == 404
                assert absent.json()["error"]["code"] == "THREAD_NOT_FOUND"

                # A project in another workspace cannot be written into either.
                cross_project = await client.post(
                    f"/api/v1/projects/{theirs.project_id}/threads",
                    json={"title": "wrong tenant"},
                    headers={"X-Workspace-Id": mine.workspace_id},
                )
                assert cross_project.status_code == 404
                assert cross_project.json()["error"]["code"] == "PROJECT_NOT_FOUND"

            surviving = (
                await conn.execute(
                    text("SELECT title FROM agent_thread WHERE id = :id"), {"id": foreign_id}
                )
            ).scalar_one()
            assert surviving == "theirs"

    run_async(scenario())


def test_a_membership_without_thread_write_cannot_mutate(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-readonly", name="D0 read only")
            app = _app(
                conn,
                settings=_settings(),
                permissions=CHAT_PERMISSIONS - {PERMISSION_THREAD_WRITE},
            )
            async with _client(app) as client:
                refused = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads",
                    json={"title": "nope"},
                    headers={"X-Workspace-Id": project.workspace_id},
                )
                assert refused.status_code == 403
                assert refused.json()["error"]["code"] == "PERMISSION_DENIED"

                # Reads still work: the refusal is per permission, not per surface.
                listed = await client.get(
                    f"/api/v1/projects/{project.project_id}/threads",
                    headers={"X-Workspace-Id": project.workspace_id},
                )
                assert listed.status_code == 200

            assert (
                await conn.execute(text("SELECT count(*) FROM agent_thread WHERE title = 'nope'"))
            ).scalar_one() == 0

    run_async(scenario())


def test_a_repeated_idempotency_key_creates_one_thread_not_two(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-idem", name="D0 idempotency")
            app = _app(conn, settings=_settings())
            headers = {"X-Workspace-Id": project.workspace_id, "Idempotency-Key": "compose-1"}
            async with _client(app) as client:
                first = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads",
                    json={"title": "New chat"},
                    headers=headers,
                )
                second = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads",
                    json={"title": "New chat"},
                    headers=headers,
                )
            assert first.status_code == 201
            assert second.status_code == 201
            assert first.json()["data"]["id"] == second.json()["data"]["id"]
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_thread WHERE workspace_id = :workspace"),
                    {"workspace": project.workspace_id},
                )
            ).scalar_one() == 1

    run_async(scenario())


def test_the_surface_is_absent_when_the_flag_is_off(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-off", name="D0 flag off")
            app = _app(conn, settings=load_settings(_env_file=None))
            async with _client(app) as client:
                response = await client.post(
                    f"/api/v1/projects/{project.project_id}/threads",
                    json={"title": "nope"},
                    headers={"X-Workspace-Id": project.workspace_id},
                )
            assert response.status_code == 404

    run_async(scenario())


def test_enabling_chat_in_production_without_a_real_principal_fails_at_startup() -> None:
    """Contract §5.6: a process that would serve chat traffic under a development identity must
    fail to start, not at first request."""

    from fastapi import FastAPI

    settings = load_settings(_env_file=None, chat_enabled=True, projections_auth_mode="service")
    with pytest.raises(ProductionPrincipalRequired):
        install_chat_surface(
            FastAPI(),
            settings=settings,
            conn_factory=None,  # type: ignore[arg-type]
            tool_invoker=None,  # type: ignore[arg-type]
        )

    # …and an injected Lane-B resolver is exactly what makes it legal.
    app = FastAPI()
    install_chat_surface(
        app,
        settings=settings,
        conn_factory=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        principal_resolver=lambda workspace_id: _principal(workspace_id),
    )
    assert "/api/v1/projects/{project_id}/threads" in app.openapi()["paths"]
