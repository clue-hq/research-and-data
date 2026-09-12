"""``arv2_research_job.stage`` (research progress card, spec 2026-09-12): the column, its CHECK,
and the value that CHECK actually refuses."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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


@pytest.mark.usefixtures("require_db")
def test_the_check_refuses_a_stage_it_does_not_know() -> None:
    """Not the constraint's *text* but its behaviour: a row carrying an unknown stage is refused.

    A CHECK is evaluated while the tuple is formed, before the row's foreign keys are checked (they
    are after-triggers), so the invented ``run_id``/``account_entity_id`` never get a say — the
    stage is what the database objects to, and the constraint names itself in the error. The whole
    thing runs in a transaction that is never committed.
    """

    async def scenario() -> str:
        async with db_lifespan() as engine, engine.connect() as conn:
            try:
                with pytest.raises(IntegrityError) as refused:
                    await conn.execute(
                        text(
                            "INSERT INTO arv2_research_job "
                            "(job_id, run_id, workspace_id, account_entity_id, stage) "
                            "VALUES (gen_random_uuid(), gen_random_uuid(), 'ws_probe', "
                            "gen_random_uuid(), 'nonsense')"
                        )
                    )
                return str(refused.value)
            finally:
                await conn.rollback()

    message = run_async(scenario())
    assert "arv2_research_job_stage" in message
