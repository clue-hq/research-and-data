"""The directory and project-mutation routes, end to end through the journaled toolbelt."""

import pytest
from sqlalchemy import text

from clue_spine import create_project
from tests.api.test_chat_thread_surface_db import (
    _app,
    _client,
    _settings,
    require_chat_db,  # noqa: F401
    seed_project,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_chat_db")


def H(ws: str, key: str | None = None) -> dict[str, str]:
    return {"X-Workspace-Id": ws, **({"Idempotency-Key": key} if key else {})}


def test_blank_create_patch_archive_and_directory_round_trip():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            seed = await seed_project(conn, "ws-directory-routes", name="Seeded")
            ws = seed.workspace_id
            await conn.execute(
                text("UPDATE project SET status='active' WHERE project_id=:id"),
                {"id": seed.project_id},
            )
            await create_project(
                conn,
                workspace_id=ws,
                brand_id=seed.brand_id,
                name="Onboarding · B",
                status="archived",
                kind="system",
            )
            async with _client(_app(conn, settings=_settings())) as client:
                created = await client.post(
                    "/api/v1/projects/blank",
                    json={
                        "brand_id": seed.brand_id,
                        "title": " Q4 push ",
                        "description": "Twenty meetings",
                    },
                    headers=H(ws, "blank-1"),
                )
                assert created.status_code == 201, created.text
                item = created.json()["data"]
                assert item["title"] == "Q4 push" and item["description"] == "Twenty meetings"
                assert item["status"] == "active" and item["pinned"] is False
                assert item["href"] == f"/projects/{item['id']}"
                assert item["activity"] == {"chats": 0, "running": 0, "needs_input": 0}
                replay = await client.post(
                    "/api/v1/projects/blank",
                    json={
                        "brand_id": seed.brand_id,
                        "title": " Q4 push ",
                        "description": "Twenty meetings",
                    },
                    headers=H(ws, "blank-1"),
                )
                assert replay.status_code == 201 and replay.json()["data"]["id"] == item["id"]
                no_key = await client.post(
                    "/api/v1/projects/blank",
                    json={"brand_id": seed.brand_id, "title": "x"},
                    headers=H(ws),
                )
                assert no_key.status_code == 400
                assert no_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

                pinned = await client.patch(
                    f"/api/v1/projects/{item['id']}", json={"pinned": True}, headers=H(ws)
                )
                assert pinned.status_code == 200 and pinned.json()["data"]["pinned"] is True
                details = await client.patch(
                    f"/api/v1/projects/{item['id']}",
                    json={"title": "Q4 enterprise push", "description": "Objective"},
                    headers=H(ws),
                )
                assert details.json()["data"]["title"] == "Q4 enterprise push"
                empty = await client.patch(f"/api/v1/projects/{item['id']}", json={}, headers=H(ws))
                assert empty.status_code == 422

                directory = await client.get("/api/v1/projects", headers=H(ws))
                assert directory.status_code == 200, directory.text
                titles = [p["title"] for p in directory.json()["data"]]
                assert titles == ["Q4 enterprise push", "Seeded"]  # pinned first; no system project
                assert directory.json()["meta"] == {"next_cursor": None}

                archived = await client.post(
                    f"/api/v1/projects/{item['id']}/archive",
                    json={"archived": True},
                    headers=H(ws),
                )
                assert archived.status_code == 200
                assert archived.json()["data"]["status"] == "archived"
                assert archived.json()["data"]["archived_at"] is not None
                refused = await client.patch(
                    f"/api/v1/projects/{item['id']}", json={"title": "nope"}, headers=H(ws)
                )
                assert refused.status_code == 409
                assert refused.json()["error"]["code"] == "PROJECT_ARCHIVED"
                new_thread = await client.post(
                    f"/api/v1/projects/{item['id']}/threads", json={}, headers=H(ws, "t-1")
                )
                assert new_thread.status_code == 409
                assert new_thread.json()["error"]["code"] == "PROJECT_ARCHIVED"

                archived_list = await client.get(
                    "/api/v1/projects", params={"status": "archived"}, headers=H(ws)
                )
                assert [p["title"] for p in archived_list.json()["data"]] == ["Q4 enterprise push"]
                active_list = await client.get("/api/v1/projects", headers=H(ws))
                assert [p["title"] for p in active_list.json()["data"]] == ["Seeded"]

                restored = await client.post(
                    f"/api/v1/projects/{item['id']}/archive",
                    json={"archived": False},
                    headers=H(ws),
                )
                assert restored.json()["data"]["status"] == "active"

                shell = await client.get(f"/api/v1/projects/{item['id']}", headers=H(ws))
                assert shell.status_code == 200
                assert shell.json()["data"]["description"] == "Objective"
                assert shell.json()["data"]["pinned"] is True
                bad_cursor = await client.get(
                    "/api/v1/projects", params={"cursor": "zzz"}, headers=H(ws)
                )
                assert bad_cursor.status_code == 422
                assert bad_cursor.json()["error"]["code"] == "INVALID_CURSOR"

    run_async(scenario())


def test_system_projects_are_invisible_and_foreign_projects_are_404():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            seed = await seed_project(conn, "ws-directory-hidden", name="Seeded")
            ws = seed.workspace_id
            # A real second tenant (workspace + principal rows), so the cross-workspace refusal
            # below is the surface's lens and not a missing-fixture crash.
            other = await seed_project(conn, "ws-directory-neighbour", name="Neighbour")
            system = await create_project(
                conn,
                workspace_id=ws,
                brand_id=seed.brand_id,
                name="Onboarding · B",
                status="archived",
                kind="system",
            )
            async with _client(_app(conn, settings=_settings())) as client:
                for path in (f"/api/v1/projects/{system.project_id}", "/api/v1/projects/prj_nope"):
                    response = await client.get(path, headers=H(ws))
                    assert response.status_code == 404, path
                pin = await client.patch(
                    f"/api/v1/projects/{system.project_id}", json={"pinned": True}, headers=H(ws)
                )
                assert pin.status_code == 404
                foreign = await client.patch(
                    f"/api/v1/projects/{seed.project_id}",
                    json={"pinned": True},
                    headers=H(other.workspace_id),
                )
                assert foreign.status_code == 404

    run_async(scenario())
