"""Project labels round-trip through the authenticated, journaled write seam."""

import pytest
from sqlalchemy import text

from clue_api.chat import CHAT_PERMISSIONS
from clue_api.chat.principal import PERMISSION_PROJECT_WRITE
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


def test_project_rename_survives_fresh_reads_and_preserves_identity():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-project-rename", name="Original")
            await conn.execute(
                text("UPDATE project SET status = 'active' WHERE project_id = :id"),
                {"id": project.project_id},
            )
            headers = {"X-Workspace-Id": project.workspace_id}
            path = f"/api/v1/projects/{project.project_id}"
            async with _client(_app(conn, settings=_settings())) as client:
                response = await client.patch(
                    path,
                    json={"title": "  Campaign planning  "},
                    headers={**headers, "Idempotency-Key": "rename-project-once"},
                )
                assert response.status_code == 200, response.text
                # The PATCH now answers with the whole directory item (the projects screen reads
                # the card it just edited), so the rename is asserted on its two fields rather
                # than on the shape of the old rename-only body.
                assert response.json()["data"]["id"] == project.project_id
                assert response.json()["data"]["title"] == "Campaign planning"
                replay = await client.patch(
                    path,
                    json={"title": "  Campaign planning  "},
                    headers={**headers, "Idempotency-Key": "rename-project-once"},
                )
                assert replay.json() == response.json()

            # Fresh application/client, no shared frontend state or browser cache.
            async with _client(_app(conn, settings=_settings())) as client:
                shell = await client.get(path, headers=headers)
                assert shell.status_code == 200, shell.text
                assert shell.json()["data"]["title"] == "Campaign planning"
                sidebar = await client.get("/api/v1/projects/sidebar", headers=headers)
                assert sidebar.status_code == 200, sidebar.text
                assert (
                    next(p for p in sidebar.json()["data"] if p["id"] == project.project_id)[
                        "title"
                    ]
                    == "Campaign planning"
                )
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT name, workspace_id, brand_id, status FROM project "
                            "WHERE project_id = :id"
                        ),
                        {"id": project.project_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["name"] == "Campaign planning"
            assert row["workspace_id"] == project.workspace_id
            assert row["brand_id"] == project.brand_id
            assert row["status"] == "active"

    run_async(scenario())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": None},
        # ``pinned`` is no longer an unsupported field — the PATCH carries the pin toggle now —
        # so the unsupported-field case is a genuinely unknown key instead.
        {"title": "Valid", "colour": "red"},
    ],
)
def test_project_rename_rejects_invalid_or_unsupported_fields(body):
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-project-invalid", name="Original")
            async with _client(_app(conn, settings=_settings())) as client:
                response = await client.patch(
                    f"/api/v1/projects/{project.project_id}",
                    json=body,
                    headers={"X-Workspace-Id": project.workspace_id},
                )
                assert response.status_code == 422, response.text
            assert (
                await conn.execute(
                    text("SELECT name FROM project WHERE project_id = :id"),
                    {"id": project.project_id},
                )
            ).scalar_one() == "Original"

    run_async(scenario())


def test_project_rename_requires_membership_write_and_own_workspace():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-project-owner", name="Original")
            other = await seed_project(conn, "ws-project-other", name="Other")
            path = f"/api/v1/projects/{project.project_id}"
            async with _client(
                _app(
                    conn,
                    settings=_settings(),
                    permissions=CHAT_PERMISSIONS - {PERMISSION_PROJECT_WRITE},
                )
            ) as client:
                denied = await client.patch(
                    path, json={"title": "Denied"}, headers={"X-Workspace-Id": project.workspace_id}
                )
                assert denied.status_code == 403, denied.text
            async with _client(_app(conn, settings=_settings())) as client:
                for target in [path, "/api/v1/projects/prj_missing"]:
                    denied = await client.patch(
                        target,
                        json={"title": "Denied"},
                        headers={"X-Workspace-Id": other.workspace_id},
                    )
                    assert denied.status_code == 404, denied.text
                    assert denied.json()["error"]["code"] == "PROJECT_NOT_FOUND"
            assert (
                await conn.execute(
                    text("SELECT name FROM project WHERE project_id = :id"),
                    {"id": project.project_id},
                )
            ).scalar_one() == "Original"

    run_async(scenario())
