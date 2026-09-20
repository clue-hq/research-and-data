"""The four project-row tools: preconditions, replay identity, and the running-work refusal."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.project_tools import (
    CreateProjectTool,
    SetProjectArchivedTool,
    SetProjectPinnedTool,
    UpdateProjectDetailsTool,
)
from clue_api.thread_store import create_thread
from clue_core import operation_id_from_key
from clue_spine import UNTITLED_PROJECT_NAME, create_project, get_project_for_workspace
from clue_toolbelt import ToolContext
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("migrated_db")


def _ctx(workspace_id: str, cf) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="human",
        conn_factory=cf,
        operation_id=operation_id_from_key(workspace_id, f"project-tools:{uuid4().hex}"),
        principal_kind="human",
        actor_id="usr_tools",
        # An authenticated human context must carry its membership (envelope.py `__post_init__`).
        # These tools never read it — nothing here writes an ownership column — so a literal is
        # enough; the HTTP route tests carry the real seeded one.
        membership_id="mbr_tools",
    )


def _codes(failures):
    return [f.reason_code for f in failures]


def test_create_is_replay_safe_and_refuses_the_placeholder_title():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            seed = await seed_project(conn, "ws-tools-create", name="Seed")
            cf = conn_session_factory(conn)
            tool = CreateProjectTool(conn_factory=cf)
            ctx = _ctx(seed.workspace_id, cf)
            good = tool.input_model(
                project_id="prj_blank_1",
                brand_id=seed.brand_id,
                title="  Q4 push  ",
                description="obj",
            )
            assert await tool.preconditions(good, ctx) == ()
            first = await tool.invoke(good, ctx)
            again = await tool.invoke(good, ctx)
            assert first.references == again.references == {"id": "prj_blank_1", "title": "Q4 push"}
            row = await get_project_for_workspace(
                conn, workspace_id=seed.workspace_id, project_id="prj_blank_1"
            )
            assert row is not None and row.status == "active" and row.description == "obj"

            bad_brand = tool.input_model(
                project_id="prj_blank_2", brand_id="brand_x", title="T", description=""
            )
            assert _codes(await tool.preconditions(bad_brand, ctx)) == ["brand_not_found"]
            reserved = tool.input_model(
                project_id="prj_blank_3",
                brand_id=seed.brand_id,
                title=UNTITLED_PROJECT_NAME,
                description="",
            )
            assert _codes(await tool.preconditions(reserved, ctx)) == ["project_title_reserved"]

    run_async(scenario())


def test_details_pin_and_archive_refuse_system_archived_draft_and_running(monkeypatch):
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            seed = await seed_project(conn, "ws-tools-mut", name="Seed")
            await conn.execute(
                text("UPDATE project SET status='active' WHERE project_id=:id"),
                {"id": seed.project_id},
            )
            cf = conn_session_factory(conn)
            ws, pid = seed.workspace_id, seed.project_id
            ctx = _ctx(ws, cf)
            system = await create_project(
                conn,
                workspace_id=ws,
                brand_id=seed.brand_id,
                name="Onboarding · S",
                status="archived",
                kind="system",
            )
            details, pin, archive = (
                UpdateProjectDetailsTool(conn_factory=cf),
                SetProjectPinnedTool(conn_factory=cf),
                SetProjectArchivedTool(conn_factory=cf),
            )
            assert _codes(
                await details.preconditions(
                    details.input_model(project_id="prj_missing", title="T", description=""), ctx
                )
            ) == ["project_not_found"]
            assert _codes(
                await pin.preconditions(
                    pin.input_model(project_id=system.project_id, pinned=True), ctx
                )
            ) == ["project_system"]

            # A queued/executing turn makes the project "running": archive refuses with the
            # dummy's own sentence. `threads_running` is the submissions-union read the sidebar
            # uses; it is stubbed here so this test does not have to seed a whole submission row
            # (the route test in Task 5 exercises the real read through the Home bootstrap).
            await create_thread(conn, thread_id="thr_tools_run", workspace_id=ws, project_id=pid)
            import clue_api.project_tools as project_tools_module

            async def _running(*, workspace_id, thread_ids, conn_factory):
                return frozenset(thread_ids)

            monkeypatch.setattr(project_tools_module, "threads_running", _running)
            failures = await archive.preconditions(
                archive.input_model(project_id=pid, archived=True), ctx
            )
            assert _codes(failures) == ["project_running"]
            assert (
                failures[0].message
                == "This project has running work. Wait for it to finish before archiving."
            )

            async def _idle(*, workspace_id, thread_ids, conn_factory):
                return frozenset()

            monkeypatch.setattr(project_tools_module, "threads_running", _idle)
            assert (
                await archive.preconditions(archive.input_model(project_id=pid, archived=True), ctx)
                == ()
            )
            result = await archive.invoke(archive.input_model(project_id=pid, archived=True), ctx)
            assert result.references == {"id": pid, "status": "archived"}
            assert _codes(
                await details.preconditions(
                    details.input_model(project_id=pid, title="T", description=""), ctx
                )
            ) == ["project_archived"]
            # Pin is allowed while archived (the dummy's rule).
            assert await pin.preconditions(pin.input_model(project_id=pid, pinned=True), ctx) == ()

            await conn.execute(
                text("UPDATE project SET status='draft', archived_at=NULL WHERE project_id=:id"),
                {"id": pid},
            )
            assert _codes(
                await archive.preconditions(archive.input_model(project_id=pid, archived=True), ctx)
            ) == ["project_draft"]

    run_async(scenario())
