"""The directory read: marketing projects only, pinned-first by composite activity, keyset paged."""

import pytest
from sqlalchemy import text

from clue_api.thread_store import create_thread
from clue_projections import (
    InvalidCursorError,
    project_directory_item,
    project_directory_page,
)
from clue_spine import create_brand, create_project, set_project_pinned
from tests._identity import seed_principal
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("migrated_db")
WS = "ws-directory-read"


async def _seed(conn):
    await seed_workspace(conn, WS)
    await seed_principal(conn, workspace_id=WS, user_id="usr_directory")
    brand = await create_brand(conn, workspace_id=WS, name="Directory brand")
    rows = {}
    for name in ("Alpha", "Beta", "Gamma"):
        rows[name] = await create_project(
            conn, workspace_id=WS, brand_id=brand.brand_id, name=name, status="active"
        )
    rows["system"] = await create_project(
        conn,
        workspace_id=WS,
        brand_id=brand.brand_id,
        name="Onboarding · X",
        status="archived",
        kind="system",
    )
    rows["archived"] = await create_project(
        conn, workspace_id=WS, brand_id=brand.brand_id, name="Old", status="archived"
    )
    rows["draft"] = await create_project(
        conn, workspace_id=WS, brand_id=brand.brand_id, name="Draft", status="draft"
    )
    return brand, rows


def test_directory_excludes_system_and_draft_orders_pinned_first_by_activity_and_pages():
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            _, rows = await _seed(conn)
            cf = conn_session_factory(conn)
            # A thread on Alpha newer than every project row makes Alpha the most active.
            await conn.execute(text("SELECT pg_sleep(0.01)"))
            await create_thread(
                conn,
                thread_id="thr_dir_alpha",
                workspace_id=WS,
                project_id=rows["Alpha"].project_id,
                created_by_user_id="usr_directory",
            )
            # In production every one of these writes is its own transaction, so each row's
            # ``now()`` default is a later wall-clock instant than the last. This whole scenario
            # runs inside ONE rolled-back transaction, where ``now()`` is frozen at its start —
            # so the thread would otherwise be born with the exact stamp every project carries
            # and "most recently active" would have nothing to sort on. Stamping the thread with
            # ``clock_timestamp()`` after the sleep reproduces the real elapsed time.
            await conn.execute(
                text("UPDATE agent_thread SET updated_at = clock_timestamp() WHERE id = :id"),
                {"id": "thr_dir_alpha"},
            )
            await set_project_pinned(
                conn, workspace_id=WS, project_id=rows["Gamma"].project_id, pinned=True
            )

            page = await project_directory_page(workspace_id=WS, conn_factory=cf)
            titles = [item.title for item in page.items]
            assert titles == ["Gamma", "Alpha", "Beta"]  # pinned first, then activity
            assert page.next_cursor is None
            alpha = next(i for i in page.items if i.title == "Alpha")
            assert alpha.chat_count == 1 and alpha.thread_ids == ("thr_dir_alpha",)
            assert alpha.updated_at > rows["Alpha"].updated_at  # composite with the thread

            archived = await project_directory_page(
                workspace_id=WS, status="archived", conn_factory=cf
            )
            assert [i.title for i in archived.items] == ["Old"]  # never the system project

            first = await project_directory_page(workspace_id=WS, limit=2, conn_factory=cf)
            assert [i.title for i in first.items] == ["Gamma", "Alpha"]
            assert first.next_cursor is not None
            second = await project_directory_page(
                workspace_id=WS, limit=2, cursor=first.next_cursor, conn_factory=cf
            )
            assert [i.title for i in second.items] == ["Beta"] and second.next_cursor is None

            item = await project_directory_item(
                workspace_id=WS, project_id=rows["Gamma"].project_id, conn_factory=cf
            )
            assert item is not None and item.pinned is True
            assert (
                await project_directory_item(
                    workspace_id=WS, project_id=rows["system"].project_id, conn_factory=cf
                )
                is None
            )
            assert (
                await project_directory_item(
                    workspace_id="ws-else", project_id=rows["Gamma"].project_id, conn_factory=cf
                )
                is None
            )
            with pytest.raises(InvalidCursorError):
                await project_directory_page(
                    workspace_id=WS, cursor="not-a-cursor", conn_factory=cf
                )

    run_async(scenario())
