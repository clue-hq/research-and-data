"""Real SIGKILL/restart coverage for the C5.3 domain-commit journal window."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_HARNESS = Path(__file__).with_name("graph_exit_harness.py")
_REPO_ROOT = _HARNESS.parents[2]


def _run(
    mode: str,
    *,
    storage_root: Path,
    execution_id: str | None = None,
    crash_point: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(_HARNESS), mode]
    if execution_id is not None:
        command.append(execution_id)
    return subprocess.run(
        command,
        env={
            **os.environ,
            "GRAPH_EXIT_STORAGE_ROOT": str(storage_root),
            **({"GRAPH_EXIT_CRASH_POINT": crash_point} if crash_point is not None else {}),
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(_REPO_ROOT), os.environ.get("PYTHONPATH", "")))
            ),
        },
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _last_json(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"harness emitted no JSON object:\n{output}")


async def _counts(execution_id: str) -> tuple[int, int, int, str]:
    async with db_lifespan() as engine, engine.connect() as conn:
        provider_calls = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM graph_exit_provider_call "
                        "WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": execution_id},
                )
            ).scalar_one()
        )
        effects = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM graph_exit_effect WHERE execution_id = :execution_id"
                    ),
                    {"execution_id": execution_id},
                )
            ).scalar_one()
        )
        abandoned = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM execution_event "
                        "WHERE execution_id = :execution_id "
                        "AND event_type = 'node.abandoned'"
                    ),
                    {"execution_id": execution_id},
                )
            ).scalar_one()
        )
        status = str(
            (
                await conn.execute(
                    text("SELECT status FROM execution_cursor WHERE execution_id = :execution_id"),
                    {"execution_id": execution_id},
                )
            ).scalar_one()
        )
    return provider_calls, effects, abandoned, status


@pytest.mark.parametrize(
    ("crash_point", "expected_abandoned"),
    (
        ("after_attempt_start", 1),
        ("before_tool", 1),
        ("after_domain_commit", 1),
        ("after_completion_event", 0),
        ("after_event_insert", 0),
        ("after_cursor_update", 0),
    ),
)
def test_sigkill_at_tool_boundaries_restarts_without_duplicate_effect(
    tmp_path: Path,
    crash_point: str,
    expected_abandoned: int,
) -> None:
    prepared = _run("prepare", storage_root=tmp_path)
    assert prepared.returncode == 0, prepared.stderr
    execution_id = str(_last_json(prepared.stdout)["execution_id"])

    killed = _run(
        "crash",
        storage_root=tmp_path,
        execution_id=execution_id,
        crash_point=crash_point,
    )
    assert killed.returncode < 0, (killed.stdout, killed.stderr)

    resumed = _run("resume", storage_root=tmp_path, execution_id=execution_id)
    assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
    assert _last_json(resumed.stdout)["status"] == "completed"

    provider_calls, effects, abandoned, status = run_async(_counts(execution_id))
    assert provider_calls == 1
    assert effects == 1
    assert abandoned == expected_abandoned
    assert status == "completed"
