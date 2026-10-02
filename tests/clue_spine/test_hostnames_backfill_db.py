"""Custom-domain publishing S1 Task 5: the idempotent system-hostname backfill."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_spine.hostnames import backfill_system_hostnames, system_hostname

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


def test_backfill_writes_missing_rows_once() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            bare = ["ws_" + uuid4().hex for _ in range(2)]
            for w in bare:
                await conn.execute(
                    text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :n)"),
                    {"w": w, "n": "Backfill " + w[-4:]},
                )
            preview = await backfill_system_hostnames(conn, suffix="pages.test", dry_run=True)
            assert preview["written"] == 0 and preview["missing"] >= 2
            assert await system_hostname(conn, bare[0]) is None
            first = await backfill_system_hostnames(conn, suffix="pages.test")
            assert first["written"] >= 2
            assert (await system_hostname(conn, bare[0]) or "").endswith(".pages.test")
            second = await backfill_system_hostnames(conn, suffix="pages.test")
            assert second["written"] == 0

    run_async(scenario())
