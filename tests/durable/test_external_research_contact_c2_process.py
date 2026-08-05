"""M8C C2 disposable-DB concurrency, crash/restart and fresh-process acceptance."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from clue_db import DATABASE_URL_ENV
from tests.db.conftest import run_async

_REPO = Path(__file__).resolve().parents[2]
_HARNESS = "tests.durable.external_research_contact_c2_process_harness"
_PREVIOUS_HEAD = "d0f7a2858e40"


async def _create_database(base_url: str, database_name: str) -> None:
    if re.fullmatch(r"roseau_c2_[0-9a-f]{12}", database_name) is None:
        raise ValueError("refusing to create an unscoped C2 database")
    admin_url = make_url(base_url).set(database="postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


async def _drop_database(base_url: str, database_name: str) -> None:
    if re.fullmatch(r"roseau_c2_[0-9a-f]{12}", database_name) is None:
        raise ValueError("refusing to drop an unscoped C2 database")
    admin_url = make_url(base_url).set(database="postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        await engine.dispose()


def _run(
    mode: str,
    *,
    env: dict[str, str],
    state: Path,
    storage_root: Path,
    timeout: int = 240,
) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - fixed interpreter/module and closed mode
        [
            sys.executable,
            "-m",
            _HARNESS,
            mode,
            "--state",
            str(state),
            "--storage-root",
            str(storage_root),
        ],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, object], json.loads(result.stdout.strip().splitlines()[-1]))


def _migrate(args: tuple[str, str], *, env: dict[str, str]) -> None:
    result = subprocess.run(  # noqa: S603 - repository-owned Alembic entry point
        [str(_REPO / ".venv" / "bin" / "alembic"), *args],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stderr


def test_c2_concurrency_crash_and_fresh_process_replay(
    tmp_path: Path,
    migrated_db: bool,
) -> None:
    if not migrated_db:
        pytest.skip("requires a reachable Postgres server for the disposable C2 database")
    base_url = os.environ[DATABASE_URL_ENV]
    database_name = f"roseau_c2_{uuid4().hex[:12]}"
    database_url = (
        make_url(base_url).set(database=database_name).render_as_string(hide_password=False)
    )
    env = {**os.environ, DATABASE_URL_ENV: database_url}
    state = tmp_path / "state.json"
    storage_root = tmp_path / "artifacts"
    run_async(_create_database(base_url, database_name))
    try:
        _migrate(("upgrade", "head"), env=env)
        _migrate(("downgrade", _PREVIOUS_HEAD), env=env)
        _migrate(("upgrade", "head"), env=env)
        seeded = _run("seed", env=env, state=state, storage_root=storage_root)
        assert seeded == {"provider_calls": 0, "seeded": True}

        argv = [
            sys.executable,
            "-m",
            _HARNESS,
            "reserve",
            "--state",
            str(state),
            "--storage-root",
            str(storage_root),
        ]
        processes = [
            subprocess.Popen(  # noqa: S603 - fixed interpreter/module and closed mode
                argv,
                cwd=_REPO,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        reservations: list[dict[str, object]] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=120)
            assert process.returncode == 0, stderr
            reservations.append(json.loads(stdout.strip().splitlines()[-1]))
        assert len({row["operation_id"] for row in reservations}) == 1
        assert sorted(bool(row["created"]) for row in reservations) == [False, True]
        assert {row["subject_kind"] for row in reservations} == {"contact"}
        assert sum(int(row["provider_calls"]) for row in reservations) == 0

        settled = _run("settle", env=env, state=state, storage_root=storage_root)
        replayed = _run("replay", env=env, state=state, storage_root=storage_root)
        assert replayed["operation_id"] == settled["operation_id"]
        assert replayed["snapshot_id"] == settled["snapshot_id"]
        assert replayed["attempts"] == 1
        assert replayed["receipts"] == 1
        assert replayed["uses"] == 1
        assert replayed["spent_cents"] == "3"
        assert replayed["provider_calls"] == 0

        crashed = _run("dispatch-crash", env=env, state=state, storage_root=storage_root)
        assert crashed["decision"] == "acquired"
        assert crashed["attempt_ordinal"] == 0
        joined = _run("join", env=env, state=state, storage_root=storage_root)
        assert joined["decision"] == "join_active"
        assert joined["attempts"] == 1
        assert joined["receipts"] == 0
        assert joined["snapshots"] == 0
        assert joined["provider_calls"] == 0
        quarantined = _run("expire", env=env, state=state, storage_root=storage_root)
        assert quarantined["decision"] == "quarantined_stale_dispatch"
        assert quarantined["attempts"] == 1
        assert quarantined["receipts"] == 0
        assert quarantined["snapshots"] == 0
        assert quarantined["spent_cents"] == replayed["spent_cents"]
        assert quarantined["provider_calls"] == 0
    finally:
        run_async(_drop_database(base_url, database_name))
