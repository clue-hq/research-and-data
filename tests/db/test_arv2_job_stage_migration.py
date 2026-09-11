"""``arv2_research_job.stage`` (research progress card, spec 2026-09-12): up, constrained, down."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_stage_column_exists_and_is_constrained() -> None:
    async def scenario() -> tuple[str | None, str | None]:
        async with db_lifespan() as engine, engine.connect() as conn:
            column = (
                await conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'arv2_research_job' AND column_name = 'stage'"
                    )
                )
            ).scalar_one_or_none()
            check = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'arv2_research_job_stage'"
                    )
                )
            ).scalar_one_or_none()
        return column, check

    column, check = run_async(scenario())
    assert column == "YES"
    assert check is not None
    for stage in ("deep_research", "synthesis", "committee", "member_research"):
        assert f"'{stage}'" in check
