"""The operator scripts run the same functions as the /ops/v1 routes (spec 2026-10-25 §7).

Each script owns its transaction, so these tests seed COMMITTED rows in a fresh workspace on the
throwaway test database, run the script's ``main`` in-process, and read the result back.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from scripts import provision_additional_workspace, repair_workspace
from tests.api.test_workspace_ops_repair_db import _illumio
from tests.auth.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _seed_illumio() -> tuple[str, Any]:
    async def scenario() -> tuple[str, Any]:
        async with db_lifespan() as engine, engine.begin() as conn:
            ws, operator, _ = await _illumio(conn, failed_assets=2)
            return ws, operator

    return run_async(scenario())


def _counts(ws: str) -> tuple[int, int, int]:
    async def scenario() -> tuple[int, int, int]:
        async with db_lifespan() as engine, engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT (SELECT count(*) FROM onboarding_run WHERE workspace_id = :w),"
                        " (SELECT count(*) FROM design_ingestion_job WHERE workspace_id = :w),"
                        " (SELECT count(*) FROM workspace_operation WHERE workspace_id = :w)"
                    ),
                    {"w": ws},
                )
            ).one()
            return int(row[0]), int(row[1]), int(row[2])

    return run_async(scenario())


def test_repair_script_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    ws, operator = _seed_illumio()
    before = _counts(ws)
    code = repair_workspace.main(["--workspace", ws, "--operator-email", operator.email])
    assert code == 0
    out = capsys.readouterr().out
    assert "re-run   synthesis" in out and "describe 2 assets as one batch" in out
    assert "DRY RUN" in out
    assert _counts(ws) == before


def test_repair_script_apply_matches_the_route_and_a_second_apply_refuses(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ws, operator = _seed_illumio()
    runs, jobs, audits = _counts(ws)
    args = ["--workspace", ws, "--operator-email", operator.email, "--reason", "outage", "--apply"]
    assert repair_workspace.main(args) == 0
    assert "APPLIED" in capsys.readouterr().out
    assert _counts(ws) == (runs + 1, jobs + 1, audits + 1)
    assert repair_workspace.main(args) == 1
    assert "REFUSED nothing_to_repair" in capsys.readouterr().out


def test_repair_script_runs_without_a_design_api(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CLUE_DESIGN_API_BASE_URL", raising=False)
    ws, operator = _seed_illumio()
    args = ["--workspace", ws, "--operator-email", operator.email, "--reason", "vm", "--apply"]
    assert repair_workspace.main(args) == 0

    async def kinds() -> list[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            return list(
                (
                    await conn.execute(
                        text(
                            "SELECT kind::text FROM design_ingestion_job WHERE workspace_id = :w"
                            " ORDER BY created_at"
                        ),
                        {"w": ws},
                    )
                ).scalars()
            )

    assert run_async(kinds())[-1] == "kit_repair"


def test_provision_script_dry_run_then_apply_writes_the_audit_row(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, operator = _seed_illumio()
    name = f"Acme {uuid4().hex[:6]}"
    base = [
        "--email",
        operator.email,
        "--website",
        "https://acme.example",
        "--company-name",
        name,
        "--operator-email",
        operator.email,
        "--app-origin",
        "https://app.cluehq.ai",
    ]
    assert provision_additional_workspace.main(base) == 0
    assert "DRY RUN" in capsys.readouterr().out

    async def find() -> list[Any]:
        async with db_lifespan() as engine, engine.connect() as conn:
            return list(
                (
                    await conn.execute(
                        text(
                            "SELECT w.workspace_id, o.operation FROM workspace w LEFT JOIN"
                            " workspace_operation o USING (workspace_id) WHERE w.name = :n"
                        ),
                        {"n": name},
                    )
                ).all()
            )

    assert run_async(find()) == []
    assert provision_additional_workspace.main([*base, "--apply"]) == 0
    assert "COMMITTED" in capsys.readouterr().out
    [(_, operation)] = run_async(find())
    assert operation == "add_workspace"
    assert provision_additional_workspace.main([*base, "--apply"]) == 1
    assert "REFUSED workspace_exists" in capsys.readouterr().out
