"""Project metadata columns and their spine writers (spec 2026-09-19 §2.2)."""

import pytest
from sqlalchemy import text

from clue_spine import (
    create_project,
    get_project_for_workspace,
    set_project_archived,
    set_project_name,
    set_project_pinned,
    touch_project,
    update_project_details,
)
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("migrated_db")


def test_project_rows_carry_directory_metadata_and_writers_bump_updated_at():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-spine-directory", name="Seeded")
            # A seeded project is born `draft`; the directory's rows are the live ones.
            await conn.execute(
                text("UPDATE project SET status = 'active' WHERE project_id = :id"),
                {"id": project.project_id},
            )
            assert project.description == ""
            assert project.pinned is False
            assert project.kind == "marketing"
            assert project.archived_at is None
            assert project.updated_at == project.created_at
            ws, pid = project.workspace_id, project.project_id

            pinned = await set_project_pinned(conn, workspace_id=ws, project_id=pid, pinned=True)
            assert pinned is not None and pinned.pinned is True
            assert pinned.updated_at == project.updated_at  # pin never bumps

            await conn.execute(text("SELECT pg_sleep(0.01)"))
            detailed = await update_project_details(
                conn, workspace_id=ws, project_id=pid, name="Renamed", description="Objective"
            )
            assert detailed is not None
            assert (detailed.name, detailed.description) == ("Renamed", "Objective")
            assert detailed.updated_at > project.updated_at

            renamed = await set_project_name(conn, workspace_id=ws, project_id=pid, name="Again")
            assert renamed is not None and renamed.updated_at >= detailed.updated_at

            before = renamed.updated_at
            await conn.execute(text("SELECT pg_sleep(0.01)"))
            await touch_project(conn, workspace_id=ws, project_id=pid)
            touched = await get_project_for_workspace(conn, workspace_id=ws, project_id=pid)
            assert touched is not None and touched.updated_at > before

            archived = await set_project_archived(
                conn, workspace_id=ws, project_id=pid, archived=True
            )
            assert archived is not None
            assert archived.status == "archived" and archived.archived_at is not None
            restored = await set_project_archived(
                conn, workspace_id=ws, project_id=pid, archived=False
            )
            assert restored is not None
            assert restored.status == "active" and restored.archived_at is None

            # Foreign workspace: every writer is a scoped miss.
            assert (
                await set_project_pinned(conn, workspace_id="ws-other", project_id=pid, pinned=True)
                is None
            )

    run_async(scenario())


def test_a_draft_project_cannot_be_archived_and_a_system_project_is_born_marked():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-spine-draft", name="Draft")
            await conn.execute(
                text("UPDATE project SET status = 'draft' WHERE project_id = :id"),
                {"id": project.project_id},
            )
            assert (
                await set_project_archived(
                    conn,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    archived=True,
                )
                is None
            )

            system = await create_project(
                conn,
                workspace_id=project.workspace_id,
                brand_id=project.brand_id,
                name="Onboarding · Brand",
                status="archived",
                kind="system",
            )
            assert system.kind == "system" and system.archived_at is not None

    run_async(scenario())
