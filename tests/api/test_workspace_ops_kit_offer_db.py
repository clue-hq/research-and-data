"""The platform offers a design ingestion job in-process (spec 2026-10-25 §4, D7).

The job row and its ``design_job`` fleet task land in one transaction — the same pair the design
API's own offer writes — so a workspace repair needs no design API to be reachable.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.workspace_ops.kit_offer import offer_design_job
from tests.auth.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_offer_design_job_writes_job_row_and_design_task_together() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = f"ws_ops_offer_{uuid4().hex[:8]}"
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
            )
            job_id = await offer_design_job(
                conn, workspace_id=ws, kind="kit_repair", request={"targets": {}}
            )
            job = (
                await conn.execute(
                    text("SELECT kind::text, status::text, work_id FROM design_ingestion_job"
                         " WHERE job_id = :j AND workspace_id = :w"),
                    {"j": job_id, "w": ws},
                )
            ).one()
            assert (job.kind, job.status) == ("kit_repair", "queued")
            assert isinstance(job.work_id, UUID)
            task = (
                await conn.execute(
                    text("SELECT kind::text, dedup_key, payload_json AS payload FROM fleet_task"
                         " WHERE dedup_key = :d"),
                    {"d": str(job.work_id)},
                )
            ).one()
            assert task.kind == "design_job"
            assert task.payload["ingestion_kind"] == "kit_repair"
            assert task.payload["job_id"] == job_id
            assert task.payload["workspace_id"] == ws

    run_async(scenario())
