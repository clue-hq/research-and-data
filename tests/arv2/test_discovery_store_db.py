"""The R4 discovery store: one function per transition, against the real tables."""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.discovery_store import (
    CandidateRow,
    DiscoveryRunRow,
    begin_discovery_run,
    create_discovery_run,
    find_discovery_run,
    finish_discovery_run,
    list_candidates,
    mark_candidates_approved,
    read_discovery_run,
    record_discovery_progress,
    record_relaxed_search,
    record_verdicts,
    record_webset,
    request_relaxed,
    suspend_discovery_run,
    unapproved_domains,
    upsert_candidate,
)
from clue_core import ProjectPhase, ProjectRunId
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity
from clue_spine import Project
from tests._workspace import seed_project

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_r4_store"
PROJECT_RUN_ID = uuid4()


async def _seed(conn: AsyncConnection) -> Project:
    """A workspace, its brand + project, and the project run every discovery run hangs off."""
    project = await seed_project(conn, WORKSPACE)
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(PROJECT_RUN_ID),
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="clue-abm-buyers",
        icp_version=1,
        phase=ProjectPhase.DEEP,
    )
    return project


def _run(project: Project, *, request_sha256: str = "a" * 64, target: int = 20) -> DiscoveryRunRow:
    return DiscoveryRunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        project_run_id=PROJECT_RUN_ID,
        icp_artifact_key="ws/abc",
        icp_artifact_sha256="b" * 64,
        icp_key="clue-abm-buyers",
        icp_version=1,
        requested_by_user_id="user-1",
        request_sha256=request_sha256,
        target_count=target,
        strict_count=35,
        relaxed_enabled=True,
        criteria_gate_keys=("geography", "stage"),
    )


def test_run_create_is_idempotent_and_replay_finds_it_by_request_sha() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            assert await create_discovery_run(conn, row) is True
            assert await create_discovery_run(conn, row) is False
            found = await find_discovery_run(
                conn, workspace_id=row.workspace_id, request_sha256=row.request_sha256
            )
            assert found is not None
            assert found.run_id == row.run_id
            assert found.status == "not_started"
            assert found.criteria_gate_keys == ("geography", "stage")
            assert found.relaxed_enabled is True
            # A launched run has bought nothing yet: no webset, and neither of its searches.
            assert (found.webset_id, found.strict_search_id, found.relaxed_search_id) == (
                None,
                None,
                None,
            )

    run_async(scenario())


def test_begin_claims_only_not_started_or_suspended_and_finish_records_counts() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            await create_discovery_run(conn, row)
            begun = await begin_discovery_run(conn, run_id=row.run_id)
            assert begun is not None
            assert begun.status == "in_progress"
            assert begun.started_at is not None
            assert await begin_discovery_run(conn, run_id=row.run_id) is None
            await record_webset(
                conn,
                run_id=row.run_id,
                webset_id="ws_123",
                asked=35,
                recall_estimate=210,
                strict_search_id="srch_strict",
            )
            mid = await read_discovery_run(conn, run_id=row.run_id)
            assert mid is not None
            # The strict search is durable from the create, and no widening has been bought yet.
            assert mid.strict_search_id == "srch_strict"
            assert mid.relaxed_search_id is None
            await record_relaxed_search(conn, run_id=row.run_id, relaxed_search_id="srch_relaxed")
            await finish_discovery_run(
                conn,
                run_id=row.run_id,
                status="completed",
                found_strict=15,
                found_relaxed=0,
                analyzed=333,
                receipt={"asked": 35},
            )
            done = await read_discovery_run(conn, run_id=row.run_id)
            assert done is not None
            assert done.status == "completed"
            assert done.found_strict == 15
            assert done.receipt == {"asked": 35}
            assert done.webset_id == "ws_123"
            assert done.asked == 35
            assert done.recall_estimate == 210
            # Both searches survive the finish, so a reopened relaxed request never buys a second.
            assert done.strict_search_id == "srch_strict"
            assert done.relaxed_search_id == "srch_relaxed"
            assert done.finished_at is not None
            assert await request_relaxed(conn, run_id=row.run_id) is True
            reopened = await read_discovery_run(conn, run_id=row.run_id)
            assert reopened is not None
            assert reopened.status == "not_started"
            assert reopened.relaxed_requested is True

    run_async(scenario())


def test_suspend_parks_a_running_run_and_begin_reclaims_it() -> None:
    """A lost lease parks the run; the redelivered task picks it back up where it left off."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            await create_discovery_run(conn, row)
            await begin_discovery_run(conn, run_id=row.run_id)
            await suspend_discovery_run(conn, run_id=row.run_id)
            parked = await read_discovery_run(conn, run_id=row.run_id)
            assert parked is not None and parked.status == "suspended"
            reclaimed = await begin_discovery_run(conn, run_id=row.run_id)
            assert reclaimed is not None and reclaimed.status == "in_progress"

    run_async(scenario())


def test_candidates_upsert_by_domain_record_verdicts_and_remember_the_unapproved() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            first = _run(project, request_sha256="1" * 64)
            await create_discovery_run(conn, first)
            cand = CandidateRow(
                candidate_id=uuid4(),
                run_id=first.run_id,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                pass_="strict",
                domain="probook.ai",
                websets_url="https://probook.com",
                name="Probook",
                provider_snapshot={"employees": 52},
            )
            cid = await upsert_candidate(conn, cand)
            assert (
                await upsert_candidate(
                    conn, dataclasses.replace(cand, candidate_id=uuid4(), name="Probook AI")
                )
                == cid
            )
            await record_verdicts(
                conn,
                candidate_id=cid,
                verdicts=[{"gate_key": "stage", "verdict": "pass"}],
                fit=1.0,
                disposition="pass",
                account_entity_id=None,
            )
            (row,) = await list_candidates(conn, run_id=first.run_id)
            assert row.name == "Probook AI"
            assert row.fit == 1.0
            assert row.disposition == "pass"
            assert row.verdicts[0]["gate_key"] == "stage"
            assert row.pass_ == "strict"
            second = _run(project, request_sha256="2" * 64)
            await create_discovery_run(conn, second)
            assert await unapproved_domains(
                conn,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                before_run_id=second.run_id,
            ) == frozenset({"probook.ai"})
            account = await insert_account_entity(
                conn,
                canonical_name="Probook",
                primary_domain="probook.ai",
                workspace_id=first.workspace_id,
            )
            await record_verdicts(
                conn,
                candidate_id=cid,
                verdicts=row.verdicts,
                fit=1.0,
                disposition="pass",
                account_entity_id=UUID(str(account)),
            )
            assert (
                await mark_candidates_approved(
                    conn,
                    workspace_id=first.workspace_id,
                    project_id=first.project_id,
                    account_entity_ids=[UUID(str(account))],
                    decided_by_user_id="user-1",
                )
                == 1
            )
            assert (
                await unapproved_domains(
                    conn,
                    workspace_id=first.workspace_id,
                    project_id=first.project_id,
                    before_run_id=second.run_id,
                )
                == frozenset()
            )
            (approved,) = await list_candidates(conn, run_id=first.run_id)
            assert approved.decision == "approved"
            assert approved.decided_by_user_id == "user-1"
            assert approved.decided_at is not None
            assert approved.account_entity_id == UUID(str(account))

    run_async(scenario())


def test_progress_updates_counters_without_landing_the_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn)
            row = _run(project)
            assert await create_discovery_run(conn, row) is True
            assert await begin_discovery_run(conn, run_id=row.run_id) is not None
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=7, found_relaxed=0, analyzed=120
            )
            mid = await read_discovery_run(conn, run_id=row.run_id)
            assert mid is not None
            assert (mid.found_strict, mid.found_relaxed, mid.analyzed) == (7, 0, 120)
            assert mid.status == "in_progress"
            assert mid.finished_at is None and mid.receipt is None
            # A later tick only moves the numbers forward; landing still owns status + receipt.
            await record_discovery_progress(
                conn, run_id=row.run_id, found_strict=12, found_relaxed=3, analyzed=300
            )
            later = await read_discovery_run(conn, run_id=row.run_id)
            assert later is not None
            assert (later.found_strict, later.found_relaxed, later.analyzed) == (12, 3, 300)

    run_async(scenario())
