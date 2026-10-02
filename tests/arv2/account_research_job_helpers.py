"""Seed R2 ``arv2_research_run``/``arv2_research_job`` rows the way production writes them.

One helper, shared by every suite that needs an account to *have been researched*, because the
alternative is three copies of the run-row pin list drifting apart. Every transition goes through
``account_research_store`` — ``create_run`` → ``create_job`` → ``begin_job`` → ``finish_job`` /
``suspend_job`` — so a seeded job satisfies the same CHECKs a real one does (a terminal status
carries a ``finished_at``, a ``needs_review`` one carries a failure code) instead of being hand-
written into a shape the driver could never produce.

``created_at`` is the one column written directly: ``create_job`` takes the transaction's
``now()``, so two jobs seeded in one rollback connection share a timestamp and "which is newer"
would fall through to uuid ordering. A test that means "an hour later" says so.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2 import account_research_store as store
from clue_core import EntityId, new_project_run_id
from clue_research.durable.project_run import ensure_project_run
from clue_spine import Project

__all__ = ["seed_arv2_job"]

#: A syntactically valid sha for the run row's three ``^[0-9a-f]{64}$`` CHECKs. The tables have no
#: FK to the artifact store, so a seeded run pins a key that need not resolve — what is under test
#: is the job's status, never the replayability of its pins.
_SHA = "a" * 64


async def seed_arv2_job(
    conn: AsyncConnection,
    *,
    project: Project,
    account_id: EntityId,
    status: store.JobStatus = "not_started",
    workspace_id: str | None = None,
    created_at: datetime | None = None,
    icp_key: str = "alpha",
    icp_version: int = 1,
) -> uuid.UUID:
    """One ARV2 run with one job for ``account_id``, driven to ``status``. Returns the job id.

    One job per run, which is not the production shape (a run fans out over the selected accounts)
    but is the shape these reads care about: the status is per *account*, and giving each seeded
    account its own run keeps "a second, newer job" a single call rather than a run rewrite.
    """
    ws = workspace_id if workspace_id is not None else project.workspace_id
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=ws,
        icp_key=icp_key,
        icp_version=icp_version,
    )
    run_id = uuid.uuid4()
    await store.create_run(
        conn,
        store.RunRow(
            run_id=run_id,
            workspace_id=ws,
            project_id=project.project_id,
            brand_id=project.brand_id,
            project_run_id=uuid.UUID(str(project_run_id)),
            icp_artifact_key=f"{ws}/{_SHA}",
            icp_artifact_sha256=_SHA,
            icp_key=icp_key,
            icp_version=icp_version,
            product_selection_version=1,
            effort="full",
            committee_cap=3,
            directive_text="",
            profile_ref="arv2-account/v1",
            profile_sha256=_SHA,
            requested_by_user_id="u_owner",
            request_sha256=_SHA,
        ),
    )
    job_id = uuid.uuid4()
    await store.create_job(
        conn,
        job_id=job_id,
        run_id=run_id,
        workspace_id=ws,
        account_entity_id=uuid.UUID(str(account_id)),
    )
    if status != "not_started":
        # Every non-queued status is reached from ``in_progress``, exactly as the driver reaches it.
        await store.begin_job(conn, job_id=job_id)
    if status in ("completed", "needs_review"):
        await store.finish_job(
            conn,
            job_id=job_id,
            status=status,
            finalization={"outcome": status},
            failure_code="unresolved_fields" if status == "needs_review" else None,
            model_rounds=1,
            tool_calls=1,
            cost_usd=Decimal("0"),
            credits=Decimal("0"),
            media_seconds=0,
        )
    elif status == "suspended":
        await store.suspend_job(conn, job_id=job_id)
    await store.refresh_run_status(conn, run_id=run_id)
    if created_at is not None:
        await conn.execute(
            text("UPDATE arv2_research_job SET created_at = :at WHERE job_id = :id"),
            {"at": created_at, "id": job_id},
        )
    return job_id
