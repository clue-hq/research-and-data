"""The project context files against the real rows they are compiled from.

``inputs/project/status.md`` is not a story the model tells about the project — it is the project's
own ARV2 rows, read at the moment the turn opens. These tests seed those rows by hand and assert
the compiled facts, because the thing that would silently rot is a count: a discovery run's
verified/shown/approved tallies and an account's person-job count are derived, and a derivation
that drifts from the schema reads as a confident wrong number rather than as an error.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.project_status import load_project_status_facts
from clue_core import EntityId, new_project_run_id
from clue_research.durable import ensure_project_run
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from clue_spine import Project
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

_SHA = "a" * 64
_USER = "usr-context-files"


@pytest.fixture
def require_profiling_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _seed_workspace_project(conn: AsyncConnection) -> Project:
    """A workspace, a brand and a project, plus the ``project_run`` the ARV2 runs hang off."""

    workspace_id = f"pcf-{uuid4().hex[:6]}"
    return await seed_project(conn, workspace_id, name="Project context files")


async def _seed_project_run(conn: AsyncConnection, project: Project) -> UUID:
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="gi-groups",
        icp_version=1,
    )
    return project_run_id


async def _seed_account(conn: AsyncConnection, project: Project, name: str) -> EntityId:
    account_id = await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=f"{name.split()[0].lower()}.example",
        workspace_id=project.workspace_id,
    )
    await ensure_project_account(
        conn,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        account_entity_id=account_id,
        added_via="manual",
    )
    return account_id


async def _seed_discovery_run(
    conn: AsyncConnection,
    project: Project,
    project_run_id: UUID,
    *,
    asked: int,
    found_strict: int,
    found_relaxed: int,
) -> UUID:
    run_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_run (run_id, workspace_id, project_id, brand_id, "
            "project_run_id, icp_artifact_key, icp_artifact_sha256, icp_key, icp_version, "
            "requested_by_user_id, request_sha256, target_count, strict_count, relaxed_enabled, "
            "criteria_gate_keys, status, asked, found_strict, found_relaxed) "
            "VALUES (:run, :ws, :project, :brand, :project_run, :key, :sha, 'gi-groups', 1, "
            ":user, :request_sha, 20, 35, true, CAST(:gates AS jsonb), 'completed', :asked, "
            ":found_strict, :found_relaxed)"
        ),
        {
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "brand": project.brand_id,
            "project_run": project_run_id,
            "key": f"{project.workspace_id}/icp",
            "sha": _SHA,
            "user": _USER,
            "request_sha": uuid4().hex + uuid4().hex,
            "gates": json.dumps(["geography"]),
            "asked": asked,
            "found_strict": found_strict,
            "found_relaxed": found_relaxed,
        },
    )
    return run_id


async def _seed_candidate(
    conn: AsyncConnection,
    project: Project,
    run_id: UUID,
    domain: str,
    *,
    disposition: str,
    decision: str | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO arv2_discovery_candidate (candidate_id, run_id, workspace_id, "
            "project_id, pass, domain, name, provider_snapshot_json, disposition, decision) "
            "VALUES (:candidate, :run, :ws, :project, 'strict', :domain, :name, "
            "CAST(:snapshot AS jsonb), :disposition, :decision)"
        ),
        {
            "candidate": uuid4(),
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "domain": domain,
            "name": domain,
            "snapshot": json.dumps({"domain": domain}),
            "disposition": disposition,
            "decision": decision,
        },
    )


async def _seed_research_run(conn: AsyncConnection, project: Project, project_run_id: UUID) -> UUID:
    run_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO arv2_research_run (run_id, workspace_id, project_id, brand_id, "
            "project_run_id, icp_artifact_key, icp_artifact_sha256, icp_key, icp_version, "
            "product_selection_version, effort, committee_cap, profile_ref, profile_sha256, "
            "requested_by_user_id, request_sha256, status) "
            "VALUES (:run, :ws, :project, :brand, :project_run, :key, :sha, 'gi-groups', 1, "
            "1, 'full', 5, 'account-research@v1', :sha, :user, :request_sha, 'in_progress')"
        ),
        {
            "run": run_id,
            "ws": project.workspace_id,
            "project": project.project_id,
            "brand": project.brand_id,
            "project_run": project_run_id,
            "key": f"{project.workspace_id}/icp",
            "sha": _SHA,
            "user": _USER,
            "request_sha": uuid4().hex + uuid4().hex,
        },
    )
    return run_id


async def _seed_job(
    conn: AsyncConnection,
    project: Project,
    run_id: UUID,
    account_id: EntityId,
    *,
    subject_type: str,
    status: str,
    stage: str | None = None,
) -> None:
    # ``arv2_research_job_finished`` makes the terminal statuses and ``finished_at`` biconditional,
    # and ``arv2_research_job_subject`` does the same for a person job and its contact.
    await conn.execute(
        text(
            "INSERT INTO arv2_research_job (job_id, run_id, workspace_id, account_entity_id, "
            "status, subject_type, subject_entity_id, stage, finished_at) "
            "VALUES (:job, :run, :ws, :account, :status, :subject_type, :subject_entity, :stage, "
            "CASE WHEN :status IN ('completed', 'needs_review') THEN now() END)"
        ),
        {
            "job": uuid4(),
            "run": run_id,
            "ws": project.workspace_id,
            "account": account_id,
            "status": status,
            "subject_type": subject_type,
            "subject_entity": uuid4() if subject_type == "person" else None,
            "stage": stage,
        },
    )


def test_status_facts_read_the_pin_the_product_set_and_the_arv2_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await _seed_workspace_project(conn)
            ws, project_id = project.workspace_id, project.project_id

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.icp is None and facts.product_set is None and facts.discovery is None
            assert facts.research == () and facts.account_count == 0

            # One account in the project, one discovery run with two candidates (one approved),
            # one research run with one account job (stage synthesis) and two person jobs.
            account_id = await _seed_account(conn, project, "Goodman Campbell")
            project_run_id = await _seed_project_run(conn, project)
            discovery_run = await _seed_discovery_run(
                conn, project, project_run_id, asked=20, found_strict=10, found_relaxed=3
            )
            await _seed_candidate(
                conn,
                project,
                discovery_run,
                "goodman.org",
                disposition="pass",
                decision="approved",
            )
            await _seed_candidate(conn, project, discovery_run, "acme.org", disposition="pending")
            research_run = await _seed_research_run(conn, project, project_run_id)
            await _seed_job(
                conn,
                project,
                research_run,
                account_id,
                subject_type="account",
                status="in_progress",
                stage="synthesis",
            )
            await _seed_job(
                conn,
                project,
                research_run,
                account_id,
                subject_type="person",
                status="not_started",
            )
            await _seed_job(
                conn,
                project,
                research_run,
                account_id,
                subject_type="person",
                status="completed",
            )

            facts = await load_project_status_facts(conn, workspace_id=ws, project_id=project_id)
            assert facts.account_count == 1
            assert facts.discovery is not None
            assert (
                facts.discovery.found,
                facts.discovery.verified,
                facts.discovery.shown,
                facts.discovery.approved,
            ) == (13, 1, 1, 1)
            assert facts.discovery.asked == 20
            assert len(facts.research) == 1
            (job,) = facts.research[0].jobs
            assert (job.account_name, job.status, job.stage, job.person_jobs) == (
                "Goodman Campbell",
                "in_progress",
                "synthesis",
                2,
            )

    run_async(scenario())
