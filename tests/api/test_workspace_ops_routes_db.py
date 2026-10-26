"""The open ``/ops/v1`` operator routes (spec 2026-10-25 §8 D1: no sign-in, for now).

Every request here carries NO auth header. The routes call the same functions the scripts do.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.workspace_ops.preflight import PreflightReport, ProbeResult
from clue_api.workspace_ops.routes import install_ops_routes
from clue_config import Settings
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_workspace_ops_repair_db import _illumio
from tests.auth.conftest import rollback_conn, run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _Enqueuer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue(self, **kw: Any) -> bool:
        self.calls.append(kw)
        return True


async def _ok(workspace_id: str) -> PreflightReport:
    return PreflightReport(results=(ProbeResult("exa", "ok", True, "fine"),))


def _app(conn: AsyncConnection, *, enabled: bool = True) -> FastAPI:
    app = FastAPI()
    install_ops_routes(
        app,
        settings=Settings(_env_file=None, ops_routes_enabled=enabled),
        conn_factory=conn_session_factory(conn),
        enqueuer=_Enqueuer(),
        brand_kit_ingestion=None,
        preflight=_ok,
    )
    return app


async def _call(app: FastAPI, method: str, path: str, json: Any = None) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.request(method, path, json=json)


async def _operator(conn: AsyncConnection) -> tuple[str, str]:
    ws = f"ws-ops-routes-{uuid4().hex[:6]}"
    await seed_project(conn, ws, name="Operator home")
    user = f"usr_ops_routes_{uuid4().hex[:6]}"
    await seed_principal(conn, workspace_id=ws, user_id=user)
    email = f"shank.{uuid4().hex[:6]}@cluehq.ai"
    await conn.execute(
        text("UPDATE platform_user SET email = :e WHERE user_id = :u"), {"e": email, "u": user}
    )
    return ws, email


def test_add_workspace_dry_run_writes_nothing_then_apply_then_duplicate_409() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            _, email = await _operator(conn)
            app = _app(conn)
            body = {
                "email": email,
                "website": "https://illumio.com",
                "company_name": "Illumio",
                "operator_email": email,
            }

            dry = await _call(app, "POST", "/ops/v1/workspaces", body)
            assert dry.status_code == 200, dry.text
            assert dry.json()["applied"] is False
            assert "/onboarding/setting-up?workspace=" in dry.json()["onboarding_link"]
            count = "SELECT count(*) FROM workspace WHERE name = 'Illumio'"
            assert (await conn.execute(text(count))).scalar_one() == 0

            applied = await _call(app, "POST", "/ops/v1/workspaces", {**body, "apply": True})
            assert applied.status_code == 200, applied.text
            ws = applied.json()["workspace_id"]
            assert (await conn.execute(text(count))).scalar_one() == 1
            audit = (
                await conn.execute(
                    text(
                        "SELECT operation, actor FROM workspace_operation WHERE workspace_id = :w"
                    ),
                    {"w": ws},
                )
            ).one()
            assert (audit.operation, audit.actor) == ("add_workspace", f"operator:{email}")

            again = await _call(app, "POST", "/ops/v1/workspaces", {**body, "apply": True})
            assert again.status_code == 409, again.text
            assert again.json()["detail"]["code"] == "workspace_exists"

    run_async(scenario())


def test_unknown_workspace_404_and_unknown_operator_422() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, _ = await _operator(conn)
            app = _app(conn)
            missing = await _call(app, "GET", "/ops/v1/workspaces/ws-nope/repair-plan")
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "workspace_not_found"
            unknown = await _call(
                app,
                "POST",
                f"/ops/v1/workspaces/{ws}/repair",
                {"plan_digest": "x", "reason": "r", "operator_email": "nobody@example.invalid"},
            )
            assert unknown.status_code == 422
            assert unknown.json()["detail"]["code"] == "operator_unknown"

    run_async(scenario())


def test_preflight_and_start_onboarding_dry_run_then_apply() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, email = await _operator(conn)
            app = _app(conn)
            preflight = await _call(app, "GET", f"/ops/v1/workspaces/{ws}/preflight")
            assert preflight.status_code == 200
            assert preflight.json()["blocking"] is False

            body = {"domain": "illumio.com", "operator_email": email}
            dry = await _call(app, "POST", f"/ops/v1/workspaces/{ws}/onboarding", body)
            assert dry.status_code == 200 and dry.json()["would_start"] is True
            runs = "SELECT count(*) FROM onboarding_run WHERE workspace_id = :w"
            assert (await conn.execute(text(runs), {"w": ws})).scalar_one() == 0

            started = await _call(
                app, "POST", f"/ops/v1/workspaces/{ws}/onboarding", {**body, "apply": True}
            )
            assert started.status_code == 200, started.text
            assert (await conn.execute(text(runs), {"w": ws})).scalar_one() == 1
            audit = (
                await conn.execute(
                    text(
                        "SELECT operation, onboarding_run_id::text FROM workspace_operation"
                        " WHERE workspace_id = :w"
                    ),
                    {"w": ws},
                )
            ).one()
            assert audit == ("start_onboarding", started.json()["run_id"])

    run_async(scenario())


def test_repair_plan_then_apply_through_http() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, operator, _ = await _illumio(conn)
            app = _app(conn)
            plan = await _call(app, "GET", f"/ops/v1/workspaces/{ws}/repair-plan")
            assert plan.status_code == 200
            assert plan.json()["nothing_to_repair"] is False
            applied = await _call(
                app,
                "POST",
                f"/ops/v1/workspaces/{ws}/repair",
                {
                    "plan_digest": plan.json()["plan_digest"],
                    "reason": "outage",
                    "operator_email": operator.email,
                },
            )
            assert applied.status_code == 200, applied.text
            assert applied.json()["onboarding_run_id"] and applied.json()["design_job_ids"]
            again = await _call(
                app,
                "POST",
                f"/ops/v1/workspaces/{ws}/repair",
                {
                    "plan_digest": plan.json()["plan_digest"],
                    "reason": "outage",
                    "operator_email": operator.email,
                },
            )
            assert again.status_code == 409
            assert again.json()["detail"]["code"] == "nothing_to_repair"

    run_async(scenario())


def test_routes_are_absent_when_the_flag_is_off() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            app = _app(conn, enabled=False)
            response = await _call(app, "GET", "/ops/v1/workspaces/x/repair-plan")
            assert response.status_code == 404

    run_async(scenario())


@pytest.mark.parametrize("enabled", [True, False])
def test_the_production_application_mounts_ops_routes_per_the_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, enabled: bool
) -> None:
    from clue_api import projections_main, run_composition
    from clue_config import Secrets
    from tests.api.test_brand_kit_onboarding_ingestion_db import _NoKeySecrets

    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    app = projections_main.build_application(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            storage_fs_root=str(tmp_path / "artifacts"),
            ops_routes_enabled=enabled,
        ),
        secrets=Secrets(_env_file=None),
    )
    # Included routers are not flat ``app.routes`` entries in this FastAPI; the schema lists all.
    paths = set(app.openapi()["paths"])
    expected = {
        "/ops/v1/workspaces",
        "/ops/v1/workspaces/{workspace_id}/preflight",
        "/ops/v1/workspaces/{workspace_id}/onboarding",
        "/ops/v1/workspaces/{workspace_id}/repair-plan",
        "/ops/v1/workspaces/{workspace_id}/repair",
    }
    assert (expected <= paths) is enabled
    assert not (expected & paths) or enabled
