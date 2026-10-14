"""Moving system hostnames to the published pages' own domain (Wave 2 Contract 9)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import create_workspace
from clue_spine.hostnames import (
    SystemHostnameMoveIncomplete,
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


# --- Review finding S4-3: the move never reports "applied" while a row stayed behind -----------
class _RenamesBetweenReadAndUpdate:
    """The finding's probe: the move reads the rows to move, then — before it updates them — one
    row's label changes (as an admin's label change would). Everything else is the real
    connection."""

    def __init__(self, conn: AsyncConnection, *, hostname: str, renamed: str) -> None:
        self._conn = conn
        self._hostname = hostname
        self._renamed = renamed
        self._fired = False

    async def execute(self, statement: Any, parameters: Any = None) -> Any:
        result = await self._conn.execute(statement, parameters)
        if not self._fired and str(statement).startswith("SELECT hostname FROM workspace_hostname"):
            self._fired = True
            await self._conn.execute(
                text("UPDATE workspace_hostname SET hostname = :new WHERE hostname = :old"),
                {"new": self._renamed, "old": self._hostname},
            )
        return result


def test_s4_3_a_row_changed_mid_move_refuses_the_whole_move() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _suffixes()
            first = await create_workspace(
                conn, name="Move Kept " + uuid4().hex[:4], pages_system_suffix=old
            )
            second = await create_workspace(
                conn, name="Move Renamed " + uuid4().hex[:4], pages_system_suffix=old
            )
            before = {
                ws.workspace_id: await system_hostname(conn, ws.workspace_id)
                for ws in (first, second)
            }
            probe = _RenamesBetweenReadAndUpdate(
                conn,
                hostname=str(before[second.workspace_id]),
                renamed=f"renamed-{uuid4().hex[:6]}.{old}",
            )
            with pytest.raises(SystemHostnameMoveIncomplete) as caught:
                async with conn.begin_nested():
                    await move_system_hostnames(
                        probe,  # type: ignore[arg-type]
                        from_suffix=old,
                        to_suffix=new,
                        apply=True,
                    )
            assert str(before[second.workspace_id]) in str(caught.value)
            # The move's transaction rolled back: nothing moved, not even the untouched row.
            for ws in (first, second):
                assert await system_hostname(conn, ws.workspace_id) == before[ws.workspace_id]

    run_async(scenario())
