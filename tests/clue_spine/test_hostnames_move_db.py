"""Moving system hostnames to the published pages' own domain (Wave 2 Contract 9)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_spine import create_workspace
from clue_spine.hostnames import (
    lock_system_hostname,
    move_system_hostnames,
    resolve_active_hostname,
    system_hostname,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


def _suffixes() -> tuple[str, str]:
    tag = uuid4().hex[:6]
    return f"old{tag}.test", f"new{tag}.test"


def test_a_move_keeps_every_label_and_lock_and_old_hosts_stop_resolving() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _suffixes()
            first = await create_workspace(
                conn, name="Move A " + uuid4().hex[:4], pages_system_suffix=old
            )
            await create_workspace(conn, name="Move B " + uuid4().hex[:4], pages_system_suffix=old)
            await lock_system_hostname(conn, workspace_id=first.workspace_id)
            before = await system_hostname(conn, first.workspace_id)
            assert before is not None
            dry = await move_system_hostnames(conn, from_suffix=old, to_suffix=new)
            assert dry["rows"] == 2 and dry["applied"] is False and dry["collisions"] == []
            assert await system_hostname(conn, first.workspace_id) == before
            done = await move_system_hostnames(conn, from_suffix=old, to_suffix=new, apply=True)
            assert done["applied"] is True
            after = await system_hostname(conn, first.workspace_id)
            assert after == before[: -len(old)] + new
            assert await resolve_active_hostname(conn, after) == first.workspace_id
            assert await resolve_active_hostname(conn, before) is None
            locked = (
                await conn.execute(
                    text("SELECT locked_at FROM workspace_hostname WHERE hostname = :h"),
                    {"h": after},
                )
            ).scalar()
            assert locked is not None

    run_async(scenario())


def test_a_move_that_would_collide_writes_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _suffixes()
            moving = await create_workspace(
                conn, name="Move Same " + uuid4().hex[:4], pages_system_suffix=old
            )
            before = await system_hostname(conn, moving.workspace_id)
            assert before is not None
            # Review finding S4-1 made a system label unique on every domain, so the one thing
            # left that can hold the new hostname is a custom row (the connect route refuses a
            # hostname under our own domains; the table does not).
            occupant = await create_workspace(
                conn, name="Move Occupant " + uuid4().hex[:4], pages_system_suffix=new
            )
            await conn.execute(
                text(
                    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                    "cname_target, ownership_txt_name, ownership_txt_value) VALUES "
                    "(:h, :w, 'custom', 'pending_dns', 'pages.test', 'n', 'v')"
                ),
                {"h": before[: -len(old)] + new, "w": occupant.workspace_id},
            )
            result = await move_system_hostnames(conn, from_suffix=old, to_suffix=new, apply=True)
            assert result["applied"] is False and len(result["collisions"]) == 1
            assert await system_hostname(conn, moving.workspace_id) == before

    run_async(scenario())
