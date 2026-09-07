"""POST /onboarding enqueues one fleet task and returns 202; GET /onboarding/current reads it."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.onboarding_routes import create_onboarding_router
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.auth.conftest import rollback_conn, run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _RecordingEnqueuer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue(self, **kw: Any) -> bool:
        self.calls.append(kw)
        return len(self.calls) == 1


class _BrokenEnqueuer:
    """A queue that is down. Whatever the reason, the run was not offered."""

    async def enqueue(self, **kw: Any) -> bool:
        raise RuntimeError("fleet queue unreachable")


def test_start_creates_a_queued_run_and_enqueues_once_then_current_reads_it() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route"
            project = await seed_project(conn, ws, name="O3 route")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_route")
            enqueuer = _RecordingEnqueuer()
            app = FastAPI()
            app.include_router(
                create_onboarding_router(conn_factory=conn_session_factory(conn), enqueuer=enqueuer)
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                nothing = await client.get("/onboarding/current", headers={"X-Workspace-Id": ws})
                assert nothing.status_code == 200 and nothing.json()["status"] == "none"
                started = await client.post(
                    "/onboarding",
                    headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_route"},
                    json={
                        "company_domain": "insighthealth.ai",
                        "company_name": "Insight Health",
                    },
                )
                assert started.status_code == 202, started.text
                body = started.json()
                run_id = UUID(body["run_id"])
                assert body["status"] == "queued"
                assert enqueuer.calls[0]["brand_id"] == project.brand_id
                assert enqueuer.calls[0]["run_id"] == run_id
                current = await client.get("/onboarding/current", headers={"X-Workspace-Id": ws})
                assert current.json()["runId"] == str(run_id)
                assert current.json()["status"] == "queued"
                assert current.json()["steps"] == []
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT status, brand_id, requested_by_user_id "
                                "FROM onboarding_run WHERE run_id = :r"
                            ),
                            {"r": run_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert (
                    row["status"],
                    row["brand_id"],
                    row["requested_by_user_id"],
                ) == ("queued", project.brand_id, "usr_o3_route")

                again = await client.post(
                    "/onboarding",
                    headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_route"},
                    json={"company_domain": "insighthealth.ai"},
                )
                # A queued/running run already exists for the workspace.
                assert again.status_code == 409
                assert again.json()["detail"]["error"] == "onboarding_in_progress"
                # And the refusal never reached the fleet: still exactly one offer.
                assert len(enqueuer.calls) == 1

    run_async(scenario())


def test_a_blank_domain_or_foreign_brand_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route-bad"
            await seed_project(conn, ws, name="O3 route bad")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_bad")
            app = FastAPI()
            app.include_router(
                create_onboarding_router(
                    conn_factory=conn_session_factory(conn), enqueuer=_RecordingEnqueuer()
                )
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                blank = await client.post(
                    "/onboarding",
                    headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_bad"},
                    json={"company_domain": "  "},
                )
                assert blank.status_code == 422
                foreign = await client.post(
                    "/onboarding",
                    headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_bad"},
                    json={"company_domain": "x.io", "brand_id": "brd_not_mine"},
                )
                assert foreign.status_code == 409
                assert foreign.json()["detail"]["error"] == "brand_unavailable"

    run_async(scenario())


def test_an_unnamed_company_is_enqueued_under_its_own_domain() -> None:
    """The fleet always receives a company_name — a blank one falls back to the domain."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route-unnamed"
            await seed_project(conn, ws, name="O3 route unnamed")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_unnamed")
            enqueuer = _RecordingEnqueuer()
            app = FastAPI()
            app.include_router(
                create_onboarding_router(conn_factory=conn_session_factory(conn), enqueuer=enqueuer)
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                started = await client.post(
                    "/onboarding",
                    headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_unnamed"},
                    # A pasted URL, and a name that is only whitespace.
                    json={"company_domain": "HTTPS://Insight.Health/", "company_name": "   "},
                )
                assert started.status_code == 202, started.text
                call = enqueuer.calls[0]
                assert call["company_domain"] == "insight.health"
                assert call["company_name"] == "insight.health"
                assert call["workspace_id"] == ws

    run_async(scenario())


def test_a_run_that_could_not_be_offered_to_the_fleet_is_failed_not_stranded() -> None:
    """A recorded-but-never-offered run is a row nothing will ever drive — so it must not survive
    as ``queued``, where it would also block every later start for the workspace."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route-noqueue"
            await seed_project(conn, ws, name="O3 route no queue")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_noqueue")
            app = FastAPI()
            app.include_router(
                create_onboarding_router(
                    conn_factory=conn_session_factory(conn), enqueuer=_BrokenEnqueuer()
                )
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                refused = await client.post(
                    "/onboarding",
                    headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_noqueue"},
                    json={"company_domain": "insighthealth.ai"},
                )
                assert refused.status_code == 503, refused.text
                assert refused.json()["detail"]["error"] == "enqueue_failed"
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT status, finished_at FROM onboarding_run "
                                "WHERE workspace_id = :ws"
                            ),
                            {"ws": ws},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert row["status"] == "failed"
                assert row["finished_at"] is not None
                # And the failed run does not block the workspace's next attempt.
                current = await client.get("/onboarding/current", headers={"X-Workspace-Id": ws})
                assert current.json()["status"] == "failed"

    run_async(scenario())
