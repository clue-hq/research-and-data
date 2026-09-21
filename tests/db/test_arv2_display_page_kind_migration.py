"""The arv2_display_page fleet kind (spec 2026-09-12, plan 2026-09-21 Task 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from clue_fleet import FleetTaskKind

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_the_fleet_kind_enum_has_arv2_display_page_last_and_matches_the_db() -> None:
    async def scenario() -> list[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'fleet_task_kind' ORDER BY e.enumsortorder"
                )
            )
            return [str(r.enumlabel) for r in rows]

    labels = run_async(scenario())
    assert labels[-1] == "arv2_display_page"
    assert labels == [k.value for k in FleetTaskKind]
