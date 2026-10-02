"""The two ``shared_from`` columns on ``display_section_recipe`` (spec 2026-09-12 §3, Task 7).

A shared section owns no block: it names the recipe whose stored body it renders. The pair is
all-or-nothing at the database, so a half-named owner cannot exist even if a workspace row is
inserted by hand.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_the_recipe_table_carries_the_shared_from_pair_and_its_check() -> None:
    async def scenario() -> tuple[dict[str, str], dict[str, str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            columns = {
                str(row.column_name): str(row.data_type)
                for row in await conn.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name = 'display_section_recipe'"
                    )
                )
            }
            constraints = {
                str(row.conname): str(row.definition)
                for row in await conn.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) AS definition "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'display_section_recipe'::regclass"
                    )
                )
            }
            return columns, constraints

    columns, constraints = run_async(scenario())
    assert columns["shared_from_page"] == "text"
    assert columns["shared_from_section_key"] == "text"
    check = constraints["display_section_recipe_shared_from_pair"]
    assert "shared_from_page" in check and "shared_from_section_key" in check
