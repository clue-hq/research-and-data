"""Row transitions of the onboarding substrate, against the O1 CHECKs (spec §3)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_store import (
    create_customers_run,
    create_run,
    fail_document,
    fail_run,
    finish_run,
    finish_step,
    list_documents,
    mark_run_running,
    open_document,
    publish_document,
    read_current_run,
    start_step,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

USER = "usr_o3_store"
SHA = "a" * 64


async def _seed(conn: AsyncConnection, ws: str) -> tuple[str, UUID]:
    project = await seed_project(conn, ws, name="O3 store")
    await seed_principal(conn, workspace_id=ws, user_id=USER)
    run_id = uuid4()
    await create_run(
        conn,
        run_id=run_id,
        workspace_id=ws,
        brand_id=project.brand_id,
        company_domain="insighthealth.ai",
        requested_by_user_id=USER,
    )
    return project.brand_id, run_id


def test_a_run_walks_queued_running_completed_and_sums_step_costs() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-ok"
            brand_id, run_id = await _seed(conn, ws)
            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None and status.status == "queued" and status.steps == ()
            await mark_run_running(conn, run_id=run_id)

            step = uuid4()
            await start_step(
                conn, step_id=step, run_id=run_id, workspace_id=ws, kind="overview", phase="fast"
            )
            doc = uuid4()
            version = await open_document(
                conn,
                document_id=doc,
                workspace_id=ws,
                brand_id=brand_id,
                folder="company",
                path="company/overview.md",
                kind="company-overview",
                step_id=step,
            )
            assert version == 1
            await publish_document(
                conn, document_id=doc, artifact_key=f"{ws}/{SHA}", artifact_sha256=SHA
            )
            await finish_step(
                conn,
                step_id=step,
                status="completed",
                provider_run_id="agent_run_x",
                raw_artifact_key="raw/1",
                cost_usd=Decimal("0.5"),
                searches=60,
            )
            assert await finish_run(conn, run_id=run_id) == "completed"

            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None and status.status == "completed"
            assert status.cost_usd == Decimal("0.5")
            (only,) = status.steps
            assert (only.kind, only.status, only.failure_code) == ("overview", "completed", None)
            assert only.finished_at is not None

            (row,) = await list_documents(conn, workspace_id=ws, brand_id=brand_id)
            assert (row.path, row.version, row.status, row.artifact_sha256) == (
                "company/overview.md",
                1,
                "ready",
                SHA,
            )

    run_async(scenario())


def test_empty_and_failed_steps_make_the_run_completed_with_gaps() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-gaps"
            brand_id, run_id = await _seed(conn, ws)
            await mark_run_running(conn, run_id=run_id)
            s1, s2, s3 = uuid4(), uuid4(), uuid4()
            await start_step(
                conn, step_id=s1, run_id=run_id, workspace_id=ws, kind="overview", phase="fast"
            )
            await start_step(
                conn, step_id=s2, run_id=run_id, workspace_id=ws, kind="reviews", phase="fast"
            )
            await start_step(
                conn,
                step_id=s3,
                run_id=run_id,
                workspace_id=ws,
                kind="product_research",
                phase="background",
                subject_ref="prd_a",
            )
            d2 = uuid4()
            await open_document(
                conn,
                document_id=d2,
                workspace_id=ws,
                brand_id=brand_id,
                folder="proof",
                path="proof/customer-reviews.md",
                kind="customer-reviews",
                step_id=s2,
            )
            await finish_step(conn, step_id=s1, status="completed", cost_usd=Decimal("0.5"))
            # empty: the CHECK forbids a failure_code; the reason rides failure_message only
            await finish_step(
                conn,
                step_id=s2,
                status="empty",
                cost_usd=Decimal("0.25"),
                failure_code="ignored",
                failure_message="no reviews found",
            )
            await fail_document(conn, document_id=d2, status="empty")
            # The reported cost is the live burn: the finished steps' own costs, summed, while
            # the run is still open and its own cost column is untouched.
            live = await read_current_run(conn, workspace_id=ws)
            assert live is not None and live.cost_usd == Decimal("0.75")
            await finish_step(
                conn,
                step_id=s3,
                status="failed",
                failure_code="timeout",
                failure_message="run not terminal after 900s",
            )
            assert await finish_run(conn, run_id=run_id) == "completed_with_gaps"
            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None and status.cost_usd == Decimal("0.75")
            by_kind = {s.kind: s for s in status.steps}
            assert by_kind["reviews"].failure_code is None
            assert by_kind["product_research"].failure_code == "timeout"
            assert by_kind["product_research"].subject_ref == "prd_a"

    run_async(scenario())


def test_a_failed_step_with_no_code_lands_under_the_biconditional() -> None:
    """``onboarding_step_failure_pair`` is biconditional: ``failed`` MUST name a code.

    A caller that fails a step without one is not a database error — the store supplies
    ``unspecified`` so the containment path can never be the thing that breaks.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-nocode"
            _, run_id = await _seed(conn, ws)
            await mark_run_running(conn, run_id=run_id)
            step = uuid4()
            await start_step(
                conn, step_id=step, run_id=run_id, workspace_id=ws, kind="synthesis", phase="fast"
            )
            await finish_step(conn, step_id=step, status="failed")
            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None
            (only,) = status.steps
            assert (only.status, only.failure_code) == ("failed", "unspecified")

    run_async(scenario())


def test_finish_run_cannot_overwrite_a_run_that_already_failed() -> None:
    """``fail_run`` is the containment terminal, so nothing may walk a run back off it.

    A driver whose containment path ran and whose normal close-out then also ran must not report
    ``completed``: ``finish_run`` returns the status the row actually holds, not the one it tried
    to write, and the original ``finished_at`` stands.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-terminal"
            _, run_id = await _seed(conn, ws)
            await mark_run_running(conn, run_id=run_id)
            step = uuid4()
            await start_step(
                conn, step_id=step, run_id=run_id, workspace_id=ws, kind="overview", phase="fast"
            )
            await finish_step(conn, step_id=step, status="completed", cost_usd=Decimal("0.5"))
            await fail_run(conn, run_id=run_id)
            failed_at = (
                await conn.execute(
                    text("SELECT finished_at FROM onboarding_run WHERE run_id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()

            assert await finish_run(conn, run_id=run_id) == "failed"
            after = (
                (
                    await conn.execute(
                        text("SELECT status, finished_at FROM onboarding_run WHERE run_id = :id"),
                        {"id": run_id},
                    )
                )
                .mappings()
                .one()
            )
            assert after["status"] == "failed" and after["finished_at"] == failed_at
            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None and status.status == "failed"

    run_async(scenario())


def test_publishing_a_second_version_supersedes_the_first() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-v2"
            brand_id, run_id = await _seed(conn, ws)
            await mark_run_running(conn, run_id=run_id)
            first_step, second_step = uuid4(), uuid4()
            await start_step(
                conn,
                step_id=first_step,
                run_id=run_id,
                workspace_id=ws,
                kind="overview",
                phase="fast",
            )
            d1 = uuid4()
            assert (
                await open_document(
                    conn,
                    document_id=d1,
                    workspace_id=ws,
                    brand_id=brand_id,
                    folder="company",
                    path="company/overview.md",
                    kind="company-overview",
                    step_id=first_step,
                )
                == 1
            )
            await publish_document(
                conn, document_id=d1, artifact_key=f"{ws}/{SHA}", artifact_sha256=SHA
            )
            await finish_step(conn, step_id=first_step, status="completed")

            await start_step(
                conn,
                step_id=second_step,
                run_id=run_id,
                workspace_id=ws,
                kind="lineup",
                phase="fast",
            )
            d2 = uuid4()
            assert (
                await open_document(
                    conn,
                    document_id=d2,
                    workspace_id=ws,
                    brand_id=brand_id,
                    folder="company",
                    path="company/overview.md",
                    kind="company-overview",
                    step_id=second_step,
                )
                == 2
            )
            await publish_document(
                conn,
                document_id=d2,
                artifact_key=f"{ws}/{'b' * 64}",
                artifact_sha256="b" * 64,
            )
            rows = {
                r.version: r
                for r in await list_documents(
                    conn, workspace_id=ws, brand_id=brand_id, all_versions=True
                )
            }
            assert rows[1].status == "superseded" and rows[2].status == "ready"
            (current,) = await list_documents(conn, workspace_id=ws, brand_id=brand_id)
            assert current.version == 2

    run_async(scenario())


def test_a_step_identity_cannot_repeat_within_a_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-store-dup"
            _, run_id = await _seed(conn, ws)
            await start_step(
                conn, step_id=uuid4(), run_id=run_id, workspace_id=ws, kind="overview", phase="fast"
            )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await start_step(
                        conn,
                        step_id=uuid4(),
                        run_id=run_id,
                        workspace_id=ws,
                        kind="overview",
                        phase="fast",
                    )

    run_async(scenario())


def test_a_customers_run_is_created_with_its_kind() -> None:
    """Spec 2026-10-16 §4.4: a brand onboarded earlier gets a customers-only run."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-customers-run"
            brand_id, _full = await _seed(conn, ws)
            run_id = uuid4()
            await create_customers_run(
                conn,
                run_id=run_id,
                workspace_id=ws,
                brand_id=brand_id,
                company_domain="conduit.ai",
                requested_by_user_id=USER,
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT kind, status, persona_icp_document_id, company_domain "
                        "FROM onboarding_run WHERE run_id = :run_id"
                    ),
                    {"run_id": run_id},
                )
            ).one()
            assert tuple(row) == ("customers", "queued", None, "conduit.ai")

    run_async(scenario())
