"""Conversation naming — the conditional project rename fills only the placeholder."""

from __future__ import annotations

from clue_spine import (
    UNTITLED_PROJECT_NAME,
    get_project,
    set_project_name,
    set_project_name_if_untitled,
)
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


def test_untitled_sentinel_is_the_router_literal() -> None:
    assert UNTITLED_PROJECT_NAME == "Untitled project"


def test_conditional_rename_fills_only_the_placeholder(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        import pytest

        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            untitled = await seed_project(conn, "ws-naming-spine", name=UNTITLED_PROJECT_NAME)
            renamed = await set_project_name_if_untitled(
                conn,
                workspace_id="ws-naming-spine",
                project_id=untitled.project_id,
                name="GI practice outreach",
            )
            assert renamed is not None and renamed.name == "GI practice outreach"

            # A second generated name never overwrites the first.
            again = await set_project_name_if_untitled(
                conn,
                workspace_id="ws-naming-spine",
                project_id=untitled.project_id,
                name="Something else",
            )
            assert again is None
            assert (await get_project(conn, untitled.project_id)).name == "GI practice outreach"

            # A human rename wins: the manual writer is unconditional, the generated one is not.
            manual = await seed_project(conn, "ws-naming-spine", name=UNTITLED_PROJECT_NAME)
            await set_project_name(
                conn, workspace_id="ws-naming-spine", project_id=manual.project_id, name="Mine"
            )
            assert (
                await set_project_name_if_untitled(
                    conn, workspace_id="ws-naming-spine", project_id=manual.project_id, name="Bot"
                )
            ) is None
            assert (await get_project(conn, manual.project_id)).name == "Mine"

            # Cross-workspace: a miss, never a write.
            assert (
                await set_project_name_if_untitled(
                    conn, workspace_id="ws-other", project_id=untitled.project_id, name="X"
                )
            ) is None

    run_async(scenario())
