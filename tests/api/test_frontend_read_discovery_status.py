"""``GET /frontend/v1/projects/{id}/discovery/current`` — the project's latest discovery run."""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_api.arv2.discovery_store import (
    CandidateRow,
    DiscoveryRunRow,
    begin_discovery_run,
    create_discovery_run,
    record_discovery_progress,
    record_verdicts,
    upsert_candidate,
)
from clue_api.frontend_read.app import FRONTEND_READ_PREFIX
from clue_core import ProjectPhase, ProjectRunId
from clue_research.durable.project_run import ensure_project_run
from tests._workspace import seed_project
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

from .test_frontend_read_accounts_list import _app, _client

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WS = "ws_discovery_status"


async def _run_for(conn, project) -> DiscoveryRunRow:  # noqa: ANN001
    project_run_id = uuid4()
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(project_run_id),
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="clue-abm-buyers",
        icp_version=1,
        phase=ProjectPhase.DEEP,
    )
    row = DiscoveryRunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        project_run_id=project_run_id,
        icp_artifact_key="ws/abc",
        icp_artifact_sha256="b" * 64,
        icp_key="clue-abm-buyers",
        icp_version=1,
        requested_by_user_id="user-1",
        request_sha256=uuid4().hex * 2,
        target_count=20,
        relaxed_enabled=True,
        criteria_gate_keys=("geography", "stage"),
    )
    assert await create_discovery_run(conn, row) is True
    return row


def test_none_then_the_latest_run_with_its_counts() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WS)
            path = f"{FRONTEND_READ_PREFIX}/projects/{project.project_id}/discovery/current"
            headers = {"X-Workspace-Id": WS}
            async with _client(_app(conn)) as client:
                empty = await client.get(path, headers=headers)
            assert empty.status_code == 200 and empty.json()["data"] is None

            row = await _run_for(conn, project)
            assert await begin_discovery_run(conn, run_id=row.run_id) is not None
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=5, found_relaxed=0, analyzed=90
            )
            # ``verified`` means the verifier JUDGED this company, which is a verdict row — not
            # merely "no longer pending". `d.com` is the proof: the driver stamps
            # `duplicate_of_existing` BEFORE any gate is asked, so it leaves the pass with no
            # verdicts and must not be counted as checked.
            for domain, disposition in (
                ("a.com", "pass"),
                ("b.com", "unclear"),
                ("c.com", "pending"),
                ("d.com", "duplicate_of_existing"),
            ):
                candidate_id = await upsert_candidate(
                    conn,
                    CandidateRow(
                        candidate_id=uuid4(),
                        run_id=row.run_id,
                        workspace_id=WS,
                        project_id=project.project_id,
                        pass_="strict",
                        domain=domain,
                        websets_url=f"https://{domain}",
                        name=domain,
                        provider_snapshot={},
                    ),
                )
                if disposition != "pending":
                    await record_verdicts(
                        conn,
                        candidate_id=candidate_id,
                        verdicts=(
                            []
                            if disposition == "duplicate_of_existing"
                            else [{"gate_key": "geography", "verdict": "pass"}]
                        ),
                        fit=0.5,
                        disposition=disposition,
                        account_entity_id=None,
                    )
            async with _client(_app(conn)) as client:
                live = await client.get(path, headers=headers)
                other = await client.get(path, headers={"X-Workspace-Id": "ws_someone_else"})
            body = live.json()["data"]
            assert body["run_id"] == str(row.run_id)
            assert body["status"] == "in_progress"
            counts = (body["asked"], body["found"], body["verified"], body["shown"])
            # Four candidates; two carry a verdict. The pre-spend duplicate does not.
            assert counts == (None, 5, 2, 2)
            assert body["started_at"] is not None and body["finished_at"] is None
            # Another workspace never sees this project's run.
            assert other.status_code in (200, 404)
            if other.status_code == 200:
                assert other.json()["data"] is None

    run_async(scenario())
