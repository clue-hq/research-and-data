"""The R2 run/job/annotation store: one function per transition, against the real tables."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2 import account_research_store as store
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_core import (
    EntityType,
    ExtractionMethod,
    ResearchMode,
    new_project_run_id,
    new_run_id,
)
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity
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

SHA = "a" * 64


async def _seed(conn: AsyncConnection) -> tuple[store.RunRow, tuple[UUID, UUID]]:
    """A workspace, its project + project run, two accounts, and the run row that pins them."""
    project = await seed_project(conn, "ws_r2_store")
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="icp-clue-abm-buyers",
        icp_version=1,
    )
    accounts = []
    for name, domain in (("Zafran", "zafran.io"), ("Probook", "probook.ai")):
        accounts.append(
            await insert_account_entity(
                conn,
                canonical_name=name,
                primary_domain=domain,
                workspace_id=project.workspace_id,
            )
        )
    row = store.RunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        project_run_id=UUID(str(project_run_id)),
        icp_artifact_key="ws_r2_store/icp",
        icp_artifact_sha256=SHA,
        icp_key="icp-clue-abm-buyers",
        icp_version=1,
        product_selection_version=1,
        effort="full",
        committee_cap=3,
        directive_text="focus on hiring signals",
        profile_ref="arv2-account/v1",
        profile_sha256="b" * 64,
        requested_by_user_id="user_founder",
        request_sha256="c" * 64,
    )
    return row, (accounts[0], accounts[1])


def test_a_run_and_its_jobs_walk_the_seam_1_states() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (first_account, second_account) = await _seed(conn)
            assert await store.create_run(conn, run) is True
            assert await store.create_run(conn, run) is False

            stored = await store.read_run(conn, run_id=run.run_id)
            assert stored is not None
            assert stored.status == "not_started" and stored.finished_at is None
            assert stored.directive_text == run.directive_text
            assert stored.icp_artifact_sha256 == SHA
            assert stored.committee_cap == 3 and stored.effort == "full"
            assert stored.product_selection_version == 1
            assert stored.brand_id == run.brand_id
            assert stored.created_at is not None

            first, second = uuid4(), uuid4()
            for job_id, account in ((first, first_account), (second, second_account)):
                assert (
                    await store.create_job(
                        conn,
                        job_id=job_id,
                        run_id=run.run_id,
                        workspace_id=run.workspace_id,
                        account_entity_id=account,
                    )
                    is True
                )
            assert (
                await store.create_job(
                    conn,
                    job_id=first,
                    run_id=run.run_id,
                    workspace_id=run.workspace_id,
                    account_entity_id=first_account,
                )
                is False
            )
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "not_started"

            begun = await store.begin_job(conn, job_id=first)
            assert begun is not None
            assert begun.status == "in_progress" and begun.attempt == 1
            assert begun.started_at is not None and begun.finished_at is None
            assert begun.account_entity_id == first_account
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "in_progress"

            await store.finish_job(
                conn,
                job_id=first,
                status="completed",
                finalization={"outcome": "completed", "claims": 12},
                model_rounds=9,
                tool_calls=31,
                cost_usd=Decimal("1.250000"),
                credits=Decimal("4.500"),
                media_seconds=61,
            )
            done = await store.read_job(conn, job_id=first)
            assert done is not None
            assert done.status == "completed" and done.finished_at is not None
            assert done.finalization == {"outcome": "completed", "claims": 12}
            assert done.failure_code is None and done.failure_message is None
            assert done.model_rounds == 9 and done.tool_calls == 31
            assert done.cost_usd == Decimal("1.250000")
            assert done.credits == Decimal("4.500")
            assert done.media_seconds == 61
            # One completed, one still queued: the run is under way, not finished.
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "in_progress"
            assert (await store.read_run(conn, run_id=run.run_id)).finished_at is None  # type: ignore[union-attr]

            # A terminal job neither re-begins nor suspends.
            assert await store.begin_job(conn, job_id=first) is None
            await store.suspend_job(conn, job_id=first)
            assert (await store.read_job(conn, job_id=first)).status == "completed"  # type: ignore[union-attr]

            assert await store.begin_job(conn, job_id=second) is not None
            await store.suspend_job(conn, job_id=second)
            suspended = await store.read_job(conn, job_id=second)
            assert suspended is not None and suspended.status == "suspended"
            assert await store.refresh_run_status(conn, run_id=run.run_id) == "suspended"

            resumed = await store.begin_job(conn, job_id=second)
            assert resumed is not None and resumed.attempt == 2
            await store.finish_job(
                conn,
                job_id=second,
                status="needs_review",
                finalization={"outcome": "needs_review"},
                failure_code="link_audit_failed",
                failure_message="two claims cite pages that do not carry them",
                model_rounds=4,
                tool_calls=12,
                cost_usd=Decimal("0.500000"),
                credits=Decimal("0"),
                media_seconds=0,
            )
            flagged = await store.read_job(conn, job_id=second)
            assert flagged is not None
            assert flagged.status == "needs_review"
            assert flagged.failure_code == "link_audit_failed"
            assert flagged.finished_at is not None

            assert await store.refresh_run_status(conn, run_id=run.run_id) == "needs_review"
            closed = await store.read_run(conn, run_id=run.run_id)
            assert closed is not None and closed.finished_at is not None

            jobs = await store.list_jobs(conn, run_id=run.run_id)
            assert {job.job_id for job in jobs} == {first, second}
            assert len(jobs) == 2

    run_async(scenario())


def test_a_run_whose_jobs_all_completed_is_completed() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _) = await _seed(conn)
            await store.create_run(conn, run)
            job_id = uuid4()
            await store.create_job(
                conn,
                job_id=job_id,
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                account_entity_id=account,
            )
            await store.begin_job(conn, job_id=job_id)
            await store.finish_job(
                conn,
                job_id=job_id,
                status="completed",
                finalization={"outcome": "completed"},
                model_rounds=1,
                tool_calls=1,
                cost_usd=Decimal("0"),
                credits=Decimal("0"),
                media_seconds=0,
            )
            status = await store.refresh_run_status(conn, run_id=run.run_id)
            closed = await store.read_run(conn, run_id=run.run_id)
            return status, closed

    status, closed = run_async(scenario())
    assert status == "completed"
    assert closed is not None and closed.finished_at is not None


def test_annotations_land_one_row_per_claim_and_verdict() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with rollback_conn() as conn:
            run, (account, _) = await _seed(conn)
            await store.create_run(conn, run)
            job_id = uuid4()
            await store.create_job(
                conn,
                job_id=job_id,
                run_id=run.run_id,
                workspace_id=run.workspace_id,
                account_entity_id=account,
            )
            writer = LenientClaimWriter(lenient=True)
            claims = []
            for field_key, value in (
                ("core.account_name", "Zafran Security"),
                ("core.primary_domain", "zafran.io"),
            ):
                receipt = await writer.write(
                    conn,
                    ClaimDraft(
                        entity_id=account,
                        entity_type=EntityType.ACCOUNT,
                        field_key=field_key,
                        value_json=value,
                        extraction_method=ExtractionMethod.API,
                        run_id=new_run_id(),
                        research_mode=ResearchMode.ACCOUNT_PROFILING,
                        workspace_id=run.workspace_id,
                        source_url="https://zafran.io/",
                    ),
                )
                claims.append(UUID(str(receipt.claim_id)))
            written = await store.record_annotations(
                conn,
                job_id=job_id,
                claim_ids_by_verdict={
                    "EXACT": [claims[0]],
                    "NOT_FOUND": [claims[1]],
                    "PARTIAL": [],
                },
            )
            empty = await store.record_annotations(
                conn, job_id=job_id, claim_ids_by_verdict={"PARTIAL": []}
            )
            rows = (
                await conn.execute(
                    text(
                        "SELECT claim_id, kind, verdict FROM arv2_claim_annotation "
                        "WHERE job_id = :job"
                    ),
                    {"job": job_id},
                )
            ).all()
            return (
                written,
                empty,
                sorted((str(r.claim_id), r.kind, r.verdict) for r in rows),
                claims,
            )

    written, empty, rows, claims = run_async(scenario())
    assert written == 2
    assert empty == 0
    assert rows == sorted(
        [(str(claims[0]), "link_audit", "EXACT"), (str(claims[1]), "link_audit", "NOT_FOUND")]
    )
