"""R3 acceptance: real tenant-scoped project and batch sidebar reads."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from clue_api.chat.composer_context import PROJECT_CONVERSATION_AGENT_PROFILE_ID
from clue_api.thread_store import create_thread, set_thread_pinned
from clue_core import AccountStatus
from clue_research.identity import insert_account_entity
from clue_spine import create_project
from tests._identity import fixture_membership_id
from tests.api.test_home_project_bootstrap_db import (
    USER_ID,
    _app,
    _body,
    _client,
    _seed,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


def test_project_shell_is_scoped_real_and_fixture_free(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-r3-project")
            foreign_brand = await _seed(conn, "ws-r3-foreign-project")
            project = await create_project(
                conn,
                workspace_id="ws-r3-project",
                brand_id=brand.brand_id,
                name="Real R3 project",
                status="active",
            )
            foreign = await create_project(
                conn,
                workspace_id="ws-r3-foreign-project",
                brand_id=foreign_brand.brand_id,
                name="Foreign project",
                status="active",
            )
            app, _storage = _app(conn)
            async with _client(app) as client:
                response = await client.get(
                    f"/api/v1/projects/{project.project_id}",
                    headers={"X-Workspace-Id": "ws-r3-project"},
                )
                foreign_response = await client.get(
                    f"/api/v1/projects/{foreign.project_id}",
                    headers={"X-Workspace-Id": "ws-r3-project"},
                )
                missing_response = await client.get(
                    "/api/v1/projects/prj_missing",
                    headers={"X-Workspace-Id": "ws-r3-project"},
                )

            assert response.status_code == 200, response.text
            data = response.json()["data"]
            assert set(data) == {
                "id",
                "title",
                "description",
                "brand_id",
                "product_id",
                "status",
                "pinned",
                "created_at",
                "updated_at",
                "archived_at",
                "context_entities",
                "agent_profiles",
                "default_agent_profile_id",
                "composer_capabilities",
                "artifacts",
            }
            assert data["id"] == project.project_id
            assert data["title"] == "Real R3 project"
            assert data["brand_id"] == brand.brand_id
            assert data["artifacts"] == []
            assert data["context_entities"] == []
            assert data["agent_profiles"] == [
                {
                    "id": PROJECT_CONVERSATION_AGENT_PROFILE_ID,
                    "label": "Grok 4.6",
                    "short_label": "Grok 4.6",
                    "description": "Clue's governed Grok 4.6 conversation profile",
                    "model_id": "x-ai/grok-4.6",
                }
            ]
            assert data["default_agent_profile_id"] == PROJECT_CONVERSATION_AGENT_PROFILE_ID
            assert data["composer_capabilities"] == {
                "context_refs": True,
                # This app composes an artifact store, so attachments are offered.
                "attachments": True,
                "agent_profile_selection": True,
            }
            for refusal in (foreign_response, missing_response):
                assert (refusal.status_code, refusal.json()["error"]["code"]) == (
                    404,
                    "PROJECT_NOT_FOUND",
                )

    run_async(scenario())


def test_composer_context_prepares_an_existing_active_thread(require_chat_db: None) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-r3-existing-context")
            project = await create_project(
                conn,
                workspace_id="ws-r3-existing-context",
                brand_id=brand.brand_id,
                name="Existing context project",
                status="active",
            )
            thread_id = "thr_r3_existing_context"
            await create_thread(
                conn,
                thread_id=thread_id,
                workspace_id="ws-r3-existing-context",
                project_id=project.project_id,
                title="Existing chat",
                created_by_user_id=USER_ID,
                created_via_membership_id=fixture_membership_id(
                    workspace_id="ws-r3-existing-context",
                    user_id=USER_ID,
                ),
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="Existing Thread Account",
                primary_domain="existing-thread.example",
                status=AccountStatus.ACTIVE,
                workspace_id="ws-r3-existing-context",
            )
            app, _storage = _app(conn)

            async with _client(app) as client:
                response = await client.post(
                    f"/api/v1/projects/{project.project_id}/composer-context/prepare",
                    headers={"X-Workspace-Id": "ws-r3-existing-context"},
                    json={
                        "thread_id": thread_id,
                        "context_refs": [
                            {
                                "object_type": "account",
                                "object_id": str(account_id),
                                "version": None,
                            }
                        ],
                    },
                )

            assert response.status_code == 200, response.text
            assert response.json()["data"] == {
                "project_id": project.project_id,
                "thread_id": thread_id,
                "context_entities": [
                    {
                        "object_type": "account",
                        "object_id": str(account_id),
                        "label": "Existing Thread Account",
                        "secondary_label": "existing-thread.example",
                        "image_url": None,
                        "version": 1,
                        "account_id": None,
                        "account_name": None,
                    }
                ],
            }

    run_async(scenario())


def test_sidebar_is_paginated_scoped_and_constant_query_count(
    require_chat_db: None,
) -> None:
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-r3-sidebar")
            foreign_brand = await _seed(conn, "ws-r3-sidebar-foreign")
            app, _storage = _app(conn)

            async with _client(app) as client:
                created = await client.post(
                    "/api/v1/projects",
                    headers={
                        "X-Workspace-Id": "ws-r3-sidebar",
                        "Idempotency-Key": "r3-running-project",
                    },
                    json=_body(brand.brand_id, "R3 running conversation"),
                )
            assert created.status_code == 201, created.text
            running_project_id = created.json()["data"]["project"]["id"]

            second = await create_project(
                conn,
                workspace_id="ws-r3-sidebar",
                brand_id=brand.brand_id,
                name="Second real project",
                status="active",
            )
            membership_id = fixture_membership_id(
                workspace_id="ws-r3-sidebar",
                user_id=USER_ID,
            )
            for index in range(12):
                await create_thread(
                    conn,
                    thread_id=f"thr_r3_{index:02d}",
                    workspace_id="ws-r3-sidebar",
                    project_id=second.project_id,
                    title=None if index == 0 else f"Thread {index}",
                    created_by_user_id=USER_ID,
                    created_via_membership_id=membership_id,
                )
                if index == 1:
                    await set_thread_pinned(
                        conn,
                        workspace_id="ws-r3-sidebar",
                        thread_id=f"thr_r3_{index:02d}",
                        pinned=True,
                    )
            foreign = await create_project(
                conn,
                workspace_id="ws-r3-sidebar-foreign",
                brand_id=foreign_brand.brand_id,
                name="Must not leak",
                status="active",
            )

            statements: list[str] = []

            def record_statement(
                _conn,
                _cursor,
                statement: str,
                _parameters,
                _context,
                _executemany,
            ) -> None:
                normalized = statement.lstrip().upper()
                if normalized.startswith(("SELECT", "WITH")):
                    statements.append(normalized)

            event.listen(conn.sync_connection, "before_cursor_execute", record_statement)
            try:
                async with _client(app) as client:
                    response = await client.get(
                        "/api/v1/projects/sidebar?limit=50",
                        headers={"X-Workspace-Id": "ws-r3-sidebar"},
                    )
            finally:
                event.remove(conn.sync_connection, "before_cursor_execute", record_statement)

            assert response.status_code == 200, response.text
            payload = response.json()
            projects = {item["id"]: item for item in payload["data"]}
            assert set(projects) == {running_project_id, second.project_id}
            assert foreign.project_id not in projects
            assert payload["meta"] == {"next_cursor": None}
            assert len(projects[second.project_id]["conversations"]) == 12
            unnamed = next(
                item
                for item in projects[second.project_id]["conversations"]
                if item["id"] == "thr_r3_00"
            )
            assert unnamed["title"] is None
            running = projects[running_project_id]["conversations"][0]
            assert running["status"] == "running"
            # One joined project/thread read plus one whole-page gate read and
            # one whole-page queued/running read. Twelve threads do not make it N+1.
            assert len(statements) == 3, statements

            async with _client(app) as client:
                first_page = await client.get(
                    "/api/v1/projects/sidebar?limit=1",
                    headers={"X-Workspace-Id": "ws-r3-sidebar"},
                )
                cursor = first_page.json()["meta"]["next_cursor"]
                second_page = await client.get(
                    "/api/v1/projects/sidebar",
                    params={"limit": 1, "cursor": cursor},
                    headers={"X-Workspace-Id": "ws-r3-sidebar"},
                )
                invalid = await client.get(
                    "/api/v1/projects/sidebar?cursor=not-a-cursor",
                    headers={"X-Workspace-Id": "ws-r3-sidebar"},
                )
            assert cursor is not None
            assert first_page.json()["data"][0]["id"] != second_page.json()["data"][0]["id"]
            assert (invalid.status_code, invalid.json()["error"]["code"]) == (
                422,
                "INVALID_CURSOR",
            )

    run_async(scenario())


def test_sidebar_serves_only_active_projects(require_chat_db: None) -> None:
    """An archived project leaves the sidebar, threads and all (O6).

    Archiving is how a marketer clears finished work out of the rail, so the
    read has to honour it at the SQL boundary rather than serving the project
    and letting the client hide it — a hidden-but-served project is still a
    project the next page cursor has to step over.
    """
    del require_chat_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            brand = await _seed(conn, "ws-o6-archive")
            membership_id = fixture_membership_id(
                workspace_id="ws-o6-archive",
                user_id=USER_ID,
            )
            live = await create_project(
                conn,
                workspace_id="ws-o6-archive",
                brand_id=brand.brand_id,
                name="Live project",
                status="active",
            )
            archived = await create_project(
                conn,
                workspace_id="ws-o6-archive",
                brand_id=brand.brand_id,
                name="Archived project",
                status="archived",
            )
            for index, project in enumerate((live, archived)):
                await create_thread(
                    conn,
                    thread_id=f"thr_o6_arch_{index}",
                    workspace_id="ws-o6-archive",
                    project_id=project.project_id,
                    title=f"Conversation {index}",
                    created_by_user_id=USER_ID,
                    created_via_membership_id=membership_id,
                )

            app, _storage = _app(conn)
            async with _client(app) as client:
                response = await client.get(
                    "/api/v1/projects/sidebar?limit=50",
                    headers={"X-Workspace-Id": "ws-o6-archive"},
                )

            assert response.status_code == 200, response.text
            projects = {item["id"]: item for item in response.json()["data"]}
            assert set(projects) == {live.project_id}
            assert archived.project_id not in projects
            assert [item["id"] for item in projects[live.project_id]["conversations"]] == [
                "thr_o6_arch_0"
            ]

    run_async(scenario())
