"""Lane 3 slice 1, Task 5: ``GET /cost/report`` through the real projections app, bound to the
test's rolled-back connection (the ``test_projections_app`` idiom)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _app(conn: AsyncConnection):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


async def _seed_one_exa_row(conn: AsyncConnection) -> str:
    ws = f"ws_cost_ep_{uuid4().hex[:10]}"
    project = await seed_project(conn, ws, name="endpoint")
    await conn.execute(
        text(
            "INSERT INTO provider_call_ledger (call_id, workspace_id, project_id, project_run_id, "
            " entity_research_job_id, provider, operation, label, phase, attempts, estimate_usd, "
            " cost_usd, outcome, extras_json, recorded_at) "
            "VALUES (:call, :ws, :p, :run, :job, 'exa', 'search', 'search-x', 'result', 1, 0.01, "
            " 0.007, 'ok', CAST('{\"cost_source\": \"metered\"}' AS jsonb), :at)"
        ),
        {
            "call": uuid4(),
            "ws": ws,
            "p": project.project_id,
            "run": str(uuid4()),
            "job": uuid4(),
            "at": datetime(2026, 9, 14, tzinfo=UTC),
        },
    )
    return ws


async def _get(conn: AsyncConnection, *, workspace_id: str | None, **params: Any) -> httpx.Response:
    headers = {} if workspace_id is None else {"X-Workspace-Id": workspace_id}
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(conn)), base_url="http://t"
    ) as client:
        return await client.get("/cost/report", params=params, headers=headers)


def test_report_is_served_workspace_scoped() -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _seed_one_exa_row(conn)
            mine = await _get(conn, workspace_id=ws)
            theirs = await _get(conn, workspace_id="ws_nobody")
            return mine.json(), theirs.json()

    mine, theirs = run_async(scenario())
    assert mine["schema_version"] == "2"
    assert Decimal(mine["report"]["provider_usd"]) == Decimal("0.007")
    assert mine["report"]["providers"][0]["provider"] == "exa"
    assert Decimal(theirs["report"]["total_usd"]) == Decimal("0")
    assert theirs["report"]["not_covered"]  # the honesty list rides every response


def test_missing_workspace_header_is_401_and_bad_window_is_422() -> None:
    async def scenario() -> tuple[int, int]:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _seed_one_exa_row(conn)
            no_header = await _get(conn, workspace_id=None)
            bad_window = await _get(
                conn, workspace_id=ws, since="2026-09-14T12:00:00Z", until="2026-09-14T11:00:00Z"
            )
            return no_header.status_code, bad_window.status_code

    assert run_async(scenario()) == (401, 422)
