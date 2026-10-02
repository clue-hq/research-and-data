"""POST /onboarding enqueues one fleet task and returns 202; GET /onboarding/current reads it."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import text

from clue_api.arv2.onboarding_store import create_persona_run
from clue_api.onboarding_routes import create_onboarding_router
from clue_design import ingestion as design_ingestion
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
                # A workspace with no design ingestion job says so — never a fabricated
                # "queued" the setting-up checklist would spin on forever.
                assert nothing.json()["brandKitIngestion"] is None
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


def test_an_open_personas_run_does_not_block_the_whole_brand_walk() -> None:
    """The one-run-at-a-time rule is about the *walk*, not about every row in the table.

    A personas run is a narrow, project-scoped turn for one ICP document. It races nothing the
    onboarding walk writes, so letting it hold the workspace's only start slot would mean a human
    who asked for personas could not re-onboard their brand until that turn finished.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route-personas"
            project = await seed_project(conn, ws, name="O3 route personas")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o3_personas")
            document_id = (
                await conn.execute(
                    text(
                        "INSERT INTO brand_knowledge_document (document_id, workspace_id, "
                        " brand_id, project_id, folder, path, kind, version, status) "
                        "VALUES (gen_random_uuid(), :ws, :brand, :project, 'audience', "
                        " 'audience/icp-gi.md', 'icp-definition', 1, 'running') "
                        "RETURNING document_id"
                    ),
                    {"ws": ws, "brand": project.brand_id, "project": project.project_id},
                )
            ).scalar_one()
            await create_persona_run(
                conn,
                run_id=uuid4(),
                workspace_id=ws,
                brand_id=project.brand_id,
                project_id=project.project_id,
                persona_icp_document_id=document_id,
                company_domain="insighthealth.ai",
                requested_by_user_id="usr_o3_personas",
            )
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
                    headers={"X-Workspace-Id": ws, "X-Test-User-Id": "usr_o3_personas"},
                    json={"company_domain": "insighthealth.ai"},
                )
            assert started.status_code == 202, started.text
            assert len(enqueuer.calls) == 1

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


def test_current_echoes_the_workspaces_newest_brand_kit_ingestion_job() -> None:
    """The checklist's brand-kit row moves because this read serves the real job.

    ``POST /onboarding`` fires the ingestion; without this field the row could only ever read
    "queued", on a screen watched for minutes. Job truth only — the row mapping is the client's.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-route-kit"
            await seed_project(conn, ws, name="O3 route kit")
            app = FastAPI()
            app.include_router(
                create_onboarding_router(
                    conn_factory=conn_session_factory(conn), enqueuer=_RecordingEnqueuer()
                )
            )
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                before = await client.get("/onboarding/current", headers={"X-Workspace-Id": ws})
                assert before.json()["brandKitIngestion"] is None

                job = await design_ingestion.create_job(
                    conn,
                    workspace_id=ws,
                    kind="website",
                    request={"url": "https://insighthealth.ai"},
                )
                after = await client.get("/onboarding/current", headers={"X-Workspace-Id": ws})
                assert after.json()["brandKitIngestion"] == {
                    "jobId": str(job["job_id"]),
                    # The ``design_ingestion_status`` enum as stored, not a derived row state.
                    "status": "queued",
                }

                # Newest-first ordering is the DAL's own contract (``list_recent``), pinned by
                # the design ingestion tests; two rows minted inside one transaction share a
                # ``created_at``, so asserting it here would pin the uuid tiebreak instead.

    run_async(scenario())
