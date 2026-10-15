"""``arv2_research_job.restart_count`` and the ``arv2_research_job_resume`` audit table."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_restart_counter_and_audit_table_exist_with_their_checks() -> None:
    async def scenario() -> tuple[object, list[str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            column = (
                await conn.execute(
                    text(
                        "SELECT column_default FROM information_schema.columns "
                        "WHERE table_name='arv2_research_job' AND column_name='restart_count'"
                    )
                )
            ).scalar_one_or_none()
            checks = (
                (
                    await conn.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conname IN ("
                            "'arv2_research_job_restart_count','arv2_research_job_resume_reason',"
                            "'arv2_research_job_resume_actor','arv2_research_job_resume_top_up') "
                            "ORDER BY conname"
                        )
                    )
                )
                .scalars()
                .all()
            )
        return column, list(checks)

    column, checks = run_async(scenario())
    assert column == "0"
    assert checks == [
        "arv2_research_job_restart_count",
        "arv2_research_job_resume_actor",
        "arv2_research_job_resume_reason",
        "arv2_research_job_resume_top_up",
    ]
