"""Disposable-database reversibility gate for the M8D R2 migration."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from tests.db.conftest import run_async

from clue_db import DATABASE_URL_ENV

_REPO = Path(__file__).resolve().parents[2]
_PREVIOUS_HEAD = "d338ba5a8f7e"


async def _database(base_url: str, name: str, *, create: bool) -> None:
    if re.fullmatch(r"roseau_r2_[0-9a-f]{12}", name) is None:
        raise ValueError("refusing to mutate an unscoped R2 database")
    engine = create_async_engine(
        make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            if create:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
            else:
                await conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:name AND pid <> pg_backend_pid()"
                    ),
                    {"name": name},
                )
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        await engine.dispose()


def _migrate(command: str, revision: str, *, env: dict[str, str]) -> None:
    result = subprocess.run(  # noqa: S603 - fixed repository-owned Alembic executable
        [str(_REPO / ".venv" / "bin" / "alembic"), command, revision],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stderr


async def _assert_r2_schema(database_url: str, *, present: bool) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            table = (
                await conn.execute(
                    text("SELECT to_regclass('public.entity_research_job') IS NOT NULL")
                )
            ).scalar_one()
            enum_value = (
                await conn.execute(
                    text(
                        """
                        SELECT EXISTS (
                          SELECT 1 FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
                          WHERE t.typname = 'fleet_task_kind'
                            AND e.enumlabel = 'entity_research_job'
                        )
                        """
                    )
                )
            ).scalar_one()
            assert bool(table) is present
            assert bool(enum_value) is present
            authority_constraints = (
                await conn.execute(
                    text(
                        """
                        SELECT count(*) FROM pg_constraint
                        WHERE conname IN (
                          'entity_research_run_lifecycle_scope',
                          'entity_research_job_authorization_scope'
                        )
                        """
                    )
                )
            ).scalar_one()
            assert int(authority_constraints) == (2 if present else 0)
    finally:
        await engine.dispose()


def test_r2_upgrade_downgrade_upgrade_on_fresh_isolated_database(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("requires a reachable Postgres server")
    base_url = os.environ[DATABASE_URL_ENV]
    name = f"roseau_r2_{uuid4().hex[:12]}"
    database_url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    env = {**os.environ, DATABASE_URL_ENV: database_url}
    run_async(_database(base_url, name, create=True))
    try:
        _migrate("upgrade", "head", env=env)
        run_async(_assert_r2_schema(database_url, present=True))
        _migrate("downgrade", _PREVIOUS_HEAD, env=env)
        run_async(_assert_r2_schema(database_url, present=False))
        _migrate("upgrade", "head", env=env)
        run_async(_assert_r2_schema(database_url, present=True))
    finally:
        run_async(_database(base_url, name, create=False))
