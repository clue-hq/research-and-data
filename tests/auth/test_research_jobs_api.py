"""Workspace admins list stuck research jobs and resume one (spec 2026-10-14 §3.7)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_launch import launch_arv2_account_research
from clue_auth.store import create_platform_user, create_workspace_membership, link_auth_identity
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_launch_db import _request

from .conftest import rollback_conn, run_async
from .test_settings_integration import build_app, headers, seed

pytestmark = pytest.mark.usefixtures("require_auth_db")

STUCK = "/frontend/v1/research/jobs/stuck"


async def _failed_job(conn, storage, workspace_id: str, user_id: str):
    fixture = await seed_icp_fixture(conn, storage, workspace_id=workspace_id, user_id=user_id)
    launch = await launch_arv2_account_research(
        conn,
        _request(fixture, requested_by_user_id=user_id, account_entity_ids=(fixture.accounts[0],)),
        settings=settings_for(arv2_account_research_enabled=True),
        storage=storage,
        profile_sha256=arv2_account_profile_sha256(version="v4"),
    )
    job = launch.job_ids[0]
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET status='needs_review', attempt=1, started_at=now(), "
            "finished_at=now(), failure_code='d_b_a_p_i_error', failure_message='stopped' "
            "WHERE job_id=:job"
        ),
        {"job": job},
    )
    return job


def _client(conn, workspace_id: str, subject: str = "owner") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(conn, [])),
        base_url="http://test",
        headers=headers(workspace_id, subject),
    )


def test_an_owner_lists_and_resumes_a_failed_job(tmp_path):
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await load_core_pack(conn)
            ws = owner.workspace.workspace_id
            job = await _failed_job(conn, FsStorage(tmp_path), ws, "usr_jobs_api")
            async with _client(conn, ws) as client:
                listed = await client.get(STUCK)
                assert listed.status_code == 200, listed.text
                row = next(j for j in listed.json()["jobs"] if j["job_id"] == str(job))
                assert (row["state"], row["resumable"]) == ("failed", True)
                resumed = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume",
                    json={"reason": "deadlock fixed", "top_up": {}},
                )
                assert resumed.status_code == 200, resumed.text
                assert resumed.json()["status"] == "suspended"
                assert resumed.json()["restarted"] is False
                again = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume", json={"reason": "again"}
                )
                assert again.status_code == 409
                assert again.json()["error"]["code"] == "job_already_queued"
                blank = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume", json={"reason": " "}
                )
                assert blank.status_code == 409
            actor = (
                await conn.execute(
                    text("SELECT actor FROM arv2_research_job_resume WHERE job_id=:job"),
                    {"job": job},
                )
            ).scalar_one()
            assert actor == f"human:{owner.user.user_id}"

    run_async(scenario())


@pytest.mark.parametrize("role", ["owner", "admin", "operator", "viewer"])
def test_only_owners_and_admins_may_list_or_resume(tmp_path, role):
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await load_core_pack(conn)
            ws = owner.workspace.workspace_id
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn, user_id=user.user_id, provider_key="clerk", provider_subject="member"
            )
            await create_workspace_membership(
                conn, workspace_id=ws, user_id=user.user_id, role_key=role
            )
            job = await _failed_job(conn, FsStorage(tmp_path), ws, "usr_jobs_roles")
            expected = 200 if role in ("owner", "admin") else 403
            async with _client(conn, ws, "member") as client:
                assert (await client.get(STUCK)).status_code == expected
                resumed = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume", json={"reason": "fixed"}
                )
                assert resumed.status_code == expected, resumed.text

    run_async(scenario())


def test_another_workspaces_job_is_not_found(tmp_path):
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await load_core_pack(conn)
            elsewhere = await _failed_job(conn, FsStorage(tmp_path), "ws_jobs_other", "usr_other")
            async with _client(conn, owner.workspace.workspace_id) as client:
                listed = (await client.get(STUCK)).json()["jobs"]
                assert all(j["job_id"] != str(elsewhere) for j in listed)
                resumed = await client.post(
                    f"/frontend/v1/research/jobs/{elsewhere}/resume", json={"reason": "fixed"}
                )
                assert resumed.status_code == 404
                assert resumed.json()["error"]["code"] == "job_not_found"

    run_async(scenario())
