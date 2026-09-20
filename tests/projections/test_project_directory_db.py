"""The directory read: marketing projects only, pinned-first by composite activity, keyset paged."""

import pytest
from sqlalchemy import text

from clue_api.thread_store import create_thread
from clue_projections import (
    InvalidCursorError,
    project_directory_item,
    project_directory_page,
    project_sidebar_page,
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

            # An ARCHIVED conversation is not activity. Touching it here gives it the latest
            # ``updated_at`` in the whole workspace, yet the project's composite must fall back
            # to the project's own stamp — the same lens ``chat_count``/``thread_ids`` apply.
            await conn.execute(text("SELECT pg_sleep(0.01)"))
            await conn.execute(
                text(
                    "UPDATE agent_thread SET status = 'archived', "
                    "updated_at = clock_timestamp() WHERE id = :id"
                ),
                {"id": "thr_dir_alpha"},
            )
            after = await project_directory_item(
                workspace_id=WS, project_id=rows["Alpha"].project_id, conn_factory=cf
            )
            assert after is not None
            assert after.chat_count == 0 and after.thread_ids == ()
            assert after.updated_at == rows["Alpha"].updated_at  # the project's own stamp
            assert after.updated_at < alpha.updated_at  # the archived touch moved nothing

    run_async(scenario())


def test_sidebar_orders_pinned_first_by_activity_and_hides_system_projects():
    """The rail and the directory sort by the SAME composite key, so they never disagree.

    The system anchor seeded here is *active*, so only the ``kind = 'marketing'`` lens can keep
    it out of the rail — an archived-only filter would serve it.
    """

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:
            brand, rows = await _seed(conn)
            cf = conn_session_factory(conn)
            await create_project(
                conn,
                workspace_id=WS,
                brand_id=brand.brand_id,
                name="Onboarding · live",
                status="active",
                kind="system",
            )
            await set_project_pinned(
                conn, workspace_id=WS, project_id=rows["Beta"].project_id, pinned=True
            )
            await conn.execute(text("SELECT pg_sleep(0.01)"))
            await create_thread(
                conn,
                thread_id="thr_side_alpha",
                workspace_id=WS,
                project_id=rows["Alpha"].project_id,
                created_by_user_id="usr_directory",
            )
            # ``now()`` is frozen inside this one rolled-back transaction, so the thread would be
            # born with the exact stamp every project carries. ``clock_timestamp()`` after the
            # sleep reproduces the elapsed time each of these writes has in production.
            await conn.execute(
                text("UPDATE agent_thread SET updated_at = clock_timestamp() WHERE id = :id"),
                {"id": "thr_side_alpha"},
            )

            page = await project_sidebar_page(workspace_id=WS, conn_factory=cf)
            assert [p.title for p in page.items] == ["Beta", "Alpha", "Gamma"]
            assert page.items[0].pinned is True
            assert page.items[1].updated_at > page.items[2].updated_at
            assert [t.thread_id for t in page.items[1].threads] == ["thr_side_alpha"]

            first = await project_sidebar_page(workspace_id=WS, limit=1, conn_factory=cf)
            assert [p.title for p in first.items] == ["Beta"]
            rest = await project_sidebar_page(
                workspace_id=WS, limit=5, cursor=first.next_cursor, conn_factory=cf
            )
            assert [p.title for p in rest.items] == ["Alpha", "Gamma"]
            assert rest.next_cursor is None

    run_async(scenario())
