"""F3 Phase 1 (spec WS-1, plan Task 1): the per-chat snapshot version record, the project library
epoch (AW-20), and the settings the machine-independent workspace reads (WS-21, AW-11, AW-17)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import Settings
from clue_db import db_lifespan

from .conftest import run_async


async def _with_rollback(body) -> None:  # type: ignore[no-untyped-def]
    async with db_lifespan() as engine, engine.connect() as conn:
        tx = await conn.begin()
        try:
            await body(conn)
        finally:
            await tx.rollback()


async def _columns(conn: AsyncConnection, table: str) -> set[str]:
    rows = await conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return {row[0] for row in rows}


async def _constraints(conn: AsyncConnection, table: str) -> set[str]:
    rows = await conn.execute(
        text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"),
        {"t": table},
    )
    return {row[0] for row in rows}


@pytest.mark.usefixtures("require_db")
def test_agent_workspace_snapshot_table_shape() -> None:
    async def body(conn: AsyncConnection) -> None:
        assert await _columns(conn, "agent_workspace_snapshot") == {
            "workspace_id",
            "thread_id",
            "project_id",
            "version",
            "manifest_artifact_key",
            "manifest_sha256",
            "last_activity_at",
            "updated_at",
        }
        assert await _constraints(conn, "agent_workspace_snapshot") >= {
            "agent_workspace_snapshot_pkey",
            "agent_workspace_snapshot_version_positive",
            "agent_workspace_snapshot_manifest_sha_shape",
        }

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
@pytest.mark.parametrize(("version", "sha"), [(0, "a" * 64), (1, "not-a-sha")])
def test_agent_workspace_snapshot_checks(version: int, sha: str) -> None:
    async def body(conn: AsyncConnection) -> None:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO agent_workspace_snapshot (workspace_id, thread_id, project_id, "
                    "version, manifest_artifact_key, manifest_sha256) "
                    "VALUES ('ws-x', 'thr-x', 'prj-x', :v, 'ws-x/k', :sha)"
                ),
                {"v": version, "sha": sha},
            )

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
def test_project_library_epoch_table_shape() -> None:
    async def body(conn: AsyncConnection) -> None:
        assert await _columns(conn, "project_library_epoch") == {
            "workspace_id",
            "project_id",
            "epoch",
            "updated_at",
        }
        assert await _constraints(conn, "project_library_epoch") >= {
            "project_library_epoch_pkey",
            "project_library_epoch_positive",
        }

    run_async(_with_rollback(body))


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.agent_workspace_snapshots_enabled is True
    assert settings.agent_workspace_cache_idle_s == 1800.0
    assert settings.agent_workspace_cache_max_bytes == 10737418240
    assert settings.agent_workspace_transfer_concurrency == 16
    assert settings.agent_workspace_cache_sweep_interval_s == 300.0
