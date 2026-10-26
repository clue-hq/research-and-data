"""A brand-kit job that finished with gaps says so (spec 2026-10-25 §5.1).

``complete`` derives the terminal status from the job's own evidence: a non-empty ``gaps`` list
makes it ``succeeded_with_gaps``; anything else stays ``succeeded``. One place decides, so no
producer can forget.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import ingestion as design_ingestion
from clue_design.enums import DesignIngestionKind
from tests.design.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_design_db")


async def _job(conn: AsyncConnection) -> tuple[str, str]:
    ws = f"ws_test_gaps_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    job = await design_ingestion.create_job(
        conn, workspace_id=ws, kind=DesignIngestionKind.WEBSITE, request={"url": "https://a.co"}
    )
    return ws, str(job["job_id"])


async def _complete(evidence: str | None) -> str:
    async with db_lifespan() as engine, engine.connect() as conn:
        trans = await conn.begin()
        try:
            ws, job_id = await _job(conn)
            done = await design_ingestion.complete(
                conn,
                workspace_id=ws,
                job_id=job_id,
                brand_kit_id=None,
                version=None,
                evidence_json=evidence,
            )
            return str(done["status"])
        finally:
            await trans.rollback()


def test_complete_with_gaps_in_evidence_is_succeeded_with_gaps() -> None:
    evidence = json.dumps({"gaps": [{"area": "descriptions", "failed": 3, "reason": "x"}]})
    assert run_async(_complete(evidence)) == "succeeded_with_gaps"


@pytest.mark.parametrize("evidence", [json.dumps({"gaps": []}), json.dumps({"kept": 1}), None])
def test_complete_without_gaps_is_succeeded(evidence: str | None) -> None:
    assert run_async(_complete(evidence)) == "succeeded"
