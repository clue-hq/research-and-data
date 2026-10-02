"""Conversation naming — the conditional thread title fills only a null title."""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_api.thread_store import (
    create_thread,
    get_thread,
    set_thread_title,
    set_thread_title_if_unset,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


def test_conditional_title_fills_only_a_null_title(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = f"ws-naming-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="Named project")
            principal = await seed_principal(
                conn, workspace_id=workspace_id, user_id="usr-naming", membership_id="mem-naming"
            )
            untitled = await create_thread(
                conn,
                thread_id=f"thr-naming-{uuid4().hex[:8]}",
                workspace_id=workspace_id,
                project_id=project.project_id,
                created_by_user_id=principal.user_id,
                created_via_membership_id=principal.membership_id,
            )
            assert untitled.title is None

            first = await set_thread_title_if_unset(
                conn, workspace_id=workspace_id, thread_id=untitled.id, title="Find GI accounts"
            )
            assert first is not None and first.title == "Find GI accounts"
            assert first.updated_at >= untitled.updated_at

            second = await set_thread_title_if_unset(
                conn, workspace_id=workspace_id, thread_id=untitled.id, title="Other"
            )
            assert second is None
            assert (
                await get_thread(conn, workspace_id=workspace_id, thread_id=untitled.id)
            ).title == "Find GI accounts"

            manual = await create_thread(
                conn,
                thread_id=f"thr-manual-{uuid4().hex[:8]}",
                workspace_id=workspace_id,
                project_id=project.project_id,
                created_by_user_id=principal.user_id,
                created_via_membership_id=principal.membership_id,
            )
            await set_thread_title(
                conn, workspace_id=workspace_id, thread_id=manual.id, title="Mine"
            )
            assert (
                await set_thread_title_if_unset(
                    conn, workspace_id=workspace_id, thread_id=manual.id, title="Bot"
                )
            ) is None

            assert (
                await set_thread_title_if_unset(
                    conn, workspace_id="ws-other", thread_id=untitled.id, title="X"
                )
            ) is None

    run_async(scenario())
