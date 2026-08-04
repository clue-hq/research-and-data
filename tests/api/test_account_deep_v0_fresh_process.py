"""M8B V0 acceptance: durable state remains complete and replayable in a new process."""

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
_HARNESS = "tests.api.account_deep_v0_process_harness"


async def _create_database(base_url: str, database_name: str) -> None:
    if re.fullmatch(r"roseau_v0_[0-9a-f]{12}", database_name) is None:
        raise ValueError("refusing to create an unscoped V0 database")
    admin_url = make_url(base_url).set(database="postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


async def _drop_database(base_url: str, database_name: str) -> None:
    if re.fullmatch(r"roseau_v0_[0-9a-f]{12}", database_name) is None:
        raise ValueError("refusing to drop an unscoped V0 database")
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


def _run(argv: list[str], *, env: dict[str, str], timeout: int = 240) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - fixed interpreter/module and bounded test argv
        argv,
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, object], json.loads(result.stdout.strip().splitlines()[-1]))


def _as_int(value: object) -> int:
    assert isinstance(value, int)
    return value


def test_v0_fresh_process_replay_inspects_complete_durable_state(
    tmp_path: Path,
    migrated_db: bool,
) -> None:
    if not migrated_db:
        pytest.skip("requires a reachable Postgres server for the disposable V0 database")
    base_url = os.environ[DATABASE_URL_ENV]
    database_name = f"roseau_v0_{uuid4().hex[:12]}"
    database_url = (
        make_url(base_url).set(database=database_name).render_as_string(hide_password=False)
    )
    storage_root = tmp_path / "artifacts"
    state_path = tmp_path / "state.json"
    workspace_id = f"ws-v0-process-{uuid4().hex}"
    env = {**os.environ, DATABASE_URL_ENV: database_url}
    run_async(_create_database(base_url, database_name))
    try:
        for migration_command in (
            ("upgrade", "head"),
            ("downgrade", "base"),
            ("upgrade", "head"),
        ):
            migrated = subprocess.run(  # noqa: S603 - repository-owned Alembic entry point
                [str(_REPO / ".venv" / "bin" / "alembic"), *migration_command],
                cwd=_REPO,
                env=env,
                capture_output=True,
                text=True,
                timeout=240,
            )
            assert migrated.returncode == 0, migrated.stderr
        seeded = _run(
            [
                sys.executable,
                "-m",
                _HARNESS,
                "seed",
                "--storage-root",
                str(storage_root),
                "--state",
                str(state_path),
                "--workspace-id",
                workspace_id,
            ],
            env=env,
        )
        concurrent: list[subprocess.Popen[str]] = []
        launch_argv = [
            sys.executable,
            "-m",
            _HARNESS,
            "launch",
            "--state",
            str(state_path),
        ]
        for _ in range(2):
            concurrent.append(
                subprocess.Popen(  # noqa: S603 - fixed interpreter/module and bounded test argv
                    launch_argv,
                    cwd=_REPO,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        launch_results: list[dict[str, object]] = []
        for process in concurrent:
            stdout, stderr = process.communicate(timeout=120)
            assert process.returncode == 0, stderr
            launch_results.append(json.loads(stdout.strip().splitlines()[-1]))
        replayed = _run(
            [
                sys.executable,
                "-m",
                _HARNESS,
                "replay",
                "--storage-root",
                str(storage_root),
                "--state",
                str(state_path),
            ],
            env=env,
        )
        assert seeded["provider_calls_this_process"] == 4
        assert replayed["provider_calls_this_process"] == 0
        stable_keys = {
            "workspace_id",
            "project_run_id",
            "account_id",
            "operation_id",
            "operation_state",
            "receipt_ref",
            "provider_units_charged",
            "cost_cents_charged",
            "snapshot_refs",
            "attempt_count",
            "claim_count",
            "claim_field_keys",
            "gate_count",
            "eligibility_count",
            "verified_artifact_count",
            "account_run_status",
            "account_run_sub_phase",
            "account_run_refs",
            "launch_id",
            "launch_request_sha256",
        }
        assert {key: seeded[key] for key in stable_keys} == {
            key: replayed[key] for key in stable_keys
        }
        assert replayed["operation_state"] == "ready"
        assert replayed["receipt_ref"]
        assert replayed["provider_units_charged"] == "28"
        assert replayed["cost_cents_charged"] == "14.0"
        assert replayed["attempt_count"] == 4
        assert _as_int(replayed["claim_count"]) == 9
        assert replayed["claim_field_keys"] == [
            "account.scoring.tier",
            "contact.current_location",
            "contact.current_title",
            "contact.job_function",
            "contact.job_level",
            "contact.organization_relationship",
            "contact.persona",
            "contact.role_on_committee",
            "contact.team_membership",
        ]
        assert _as_int(replayed["gate_count"]) >= 2
        assert _as_int(replayed["eligibility_count"]) >= 1
        assert _as_int(replayed["verified_artifact_count"]) >= 8
        assert replayed["account_run_status"] == "running"
        assert replayed["account_run_sub_phase"] == "committee_discovered"
        assert replayed["account_run_refs"]
        assert all(item["replayed"] is True for item in launch_results)
        assert {item["launch_id"] for item in launch_results} == {replayed["launch_id"]}
        assert {item["request_sha256"] for item in launch_results} == {
            replayed["launch_request_sha256"]
        }
    finally:
        run_async(_drop_database(base_url, database_name))
