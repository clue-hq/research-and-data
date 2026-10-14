"""The resume script lists stuck jobs, plans by default, and writes only with --apply (§3.6)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from scripts.resume_arv2_research_job import run
from sqlalchemy import text

from clue_api.arv2.account_research_store import read_job
from clue_api.arv2.job_resume import TopUp
from clue_storage.fs import FsStorage
from tests.arv2.test_job_resume_db import _fail
from tests.arv2.test_quality_claims_db import setup
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_list_plan_and_apply(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)

            @asynccontextmanager
            async def connect():
                async with conn.begin_nested():
                    yield conn

            common = {
                "connect": connect,
                "reason": "deadlock fixed",
                "top_up": TopUp(),
                "restart_fresh": False,
                "actor": "operator:test",
            }
            listing = await run(workspace_id=op.workspace_id, job_id=None, apply=False, **common)
            assert any(str(op.job_id) in line and "resumable" in line for line in listing)

            planned = await run(workspace_id=None, job_id=op.job_id, apply=False, **common)
            assert planned[-1].startswith("dry run")
            assert (await read_job(conn, job_id=op.job_id)).status == "needs_review"

            applied = await run(workspace_id=None, job_id=op.job_id, apply=True, **common)
            assert any(line.startswith("resumed") for line in applied)
            assert (await read_job(conn, job_id=op.job_id)).status == "suspended"

            refused = await run(workspace_id=None, job_id=op.job_id, apply=True, **common)
            assert refused == ["refused: job_already_queued: The job is already queued or running."]
            audits = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_research_job_resume WHERE job_id=:job"),
                    {"job": op.job_id},
                )
            ).scalar_one()
            assert audits == 1

    run_async(case())
