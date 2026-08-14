"""R3 acceptance: real tenant-scoped project and batch sidebar reads."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from clue_api.thread_store import create_thread, set_thread_pinned
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
                "brand_id",
                "product_id",
                "status",
                "created_at",
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
                    "id": "head-of-abm@v24",
                    "label": "GPT-5.6 Terra",
                    "short_label": "GPT-5.6 Terra",
                    "description": "Clue's governed GPT-5.6 Terra conversation profile",
                    "model_id": "openai/gpt-5.6-terra",
                }
            ]
            assert data["default_agent_profile_id"] == "head-of-abm@v24"
            assert data["composer_capabilities"] == {
                "context_refs": True,
                "attachments": False,
                "agent_profile_selection": True,
            }
            for refusal in (foreign_response, missing_response):
                assert (refusal.status_code, refusal.json()["error"]["code"]) == (
                    404,
                    "PROJECT_NOT_FOUND",
                )

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
