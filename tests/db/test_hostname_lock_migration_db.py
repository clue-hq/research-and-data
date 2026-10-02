"""The handle → label backfill (ruling 2026-09-28): an F5 handle becomes the system label.

Two proofs. The first runs on any migrated DB: at head the F5 ``design_workspace_handle`` table is
gone and ``workspace_hostname`` carries the ``locked_at`` column. The second walks the backfill
revision down and up with real rows, so it COMMITS schema changes and only runs when
``CLUE_DATABASE_URL`` names a scratch database (its name contains ``smoke``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from clue_config import Settings
from clue_db import create_engine, database_url
from tests.clue_spine.conftest import _alembic_config, rollback_conn, run_async
from tests.clue_spine.conftest import migrated_db as migrated_db  # noqa: F401
from tests.clue_spine.conftest import require_spine_db as require_spine_db  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_spine_db")
JOIN_REV = "c16e1ae684b3"
LOCK_REV = "770bf20802e1"
T_LOCK = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def test_handle_table_is_gone_and_registry_has_the_lock_column() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            exists = (
                await conn.execute(text("SELECT to_regclass('design_workspace_handle')"))
            ).scalar()
            assert exists is None
            cols = (
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'workspace_hostname'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "locked_at" in cols

    run_async(scenario())


async def _sql(statement: str, params: dict[str, Any] | None = None) -> list[Any]:
    """Run one statement in its own committed transaction (the migrations must see the rows)."""
    engine = create_engine()
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(statement), params or {})
            return list(result.mappings().all()) if result.returns_rows else []
    finally:
        await engine.dispose()


def test_backfill_turns_handles_into_labels_and_round_trips() -> None:
    if "smoke" not in database_url():
        pytest.skip("commits schema changes: set CLUE_DATABASE_URL to a scratch *smoke* database")
    cfg = _alembic_config()
    suffix = Settings().pages_system_suffix
    tag = uuid4().hex[:6]
    # locked: a handle that published → its label keeps the lock.
    # fresh: a handle that never published → an unlocked label.
    # keeper: already has an S1 system row → that row wins, its handle is dropped unread.
    ids = {k: f"ws_{k}{tag}" for k in ("locked", "fresh", "keeper")}
    handles = {k: f"{k}-{tag}" for k in ids}
    keeper_host = f"keeper-s1-{tag}.{suffix}"

    command.downgrade(cfg, JOIN_REV)
    try:
        for key, workspace_id in ids.items():
            run_async(
                _sql(
                    "INSERT INTO workspace (workspace_id, name) VALUES (:w, :n)",
                    {"w": workspace_id, "n": key},
                )
            )
            run_async(
                _sql(
                    "INSERT INTO design_workspace_handle (workspace_id, handle, locked_at) "
                    "VALUES (:w, :h, :l)",
                    {
                        "w": workspace_id,
                        "h": handles[key],
                        "l": T_LOCK if key == "locked" else None,
                    },
                )
            )
        run_async(
            _sql(
                "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                "activated_at) VALUES (:h, :w, 'system', 'active', now())",
                {"h": keeper_host, "w": ids["keeper"]},
            )
        )

        command.upgrade(cfg, LOCK_REV)
        rows = run_async(
            _sql(
                "SELECT workspace_id, hostname, locked_at FROM workspace_hostname "
                "WHERE kind = 'system' AND workspace_id = ANY(:ws)",
                {"ws": list(ids.values())},
            )
        )
        by_ws = {r["workspace_id"]: r for r in rows}
        assert by_ws[ids["locked"]]["hostname"] == f"{handles['locked']}.{suffix}"
        assert by_ws[ids["locked"]]["locked_at"] == T_LOCK
        assert by_ws[ids["fresh"]]["hostname"] == f"{handles['fresh']}.{suffix}"
        assert by_ws[ids["fresh"]]["locked_at"] is None
        assert by_ws[ids["keeper"]]["hostname"] == keeper_host
        assert run_async(_sql("SELECT to_regclass('design_workspace_handle') AS t"))[0]["t"] is None

        command.downgrade(cfg, "-1")
        back = run_async(
            _sql(
                "SELECT workspace_id, handle, locked_at FROM design_workspace_handle "
                "WHERE workspace_id = ANY(:ws)",
                {"ws": list(ids.values())},
            )
        )
        back_by_ws = {r["workspace_id"]: r for r in back}
        assert back_by_ws[ids["locked"]]["handle"] == handles["locked"]
        assert back_by_ws[ids["locked"]]["locked_at"] == T_LOCK
        assert back_by_ws[ids["fresh"]]["handle"] == handles["fresh"]
        assert back_by_ws[ids["fresh"]]["locked_at"] is None
        # The keeper's handle was dropped unread on the way up; its S1 label comes back instead.
        assert back_by_ws[ids["keeper"]]["handle"] == keeper_host.removesuffix("." + suffix)
    finally:
        command.upgrade(cfg, "head")
        run_async(
            _sql(
                "DELETE FROM workspace_hostname WHERE workspace_id = ANY(:ws)",
                {"ws": list(ids.values())},
            )
        )
        run_async(
            _sql("DELETE FROM workspace WHERE workspace_id = ANY(:ws)", {"ws": list(ids.values())})
        )
