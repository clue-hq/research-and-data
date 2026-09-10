"""The R2 migration: fleet kind, run/job/annotation tables, the ledger extras column."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from clue_fleet import FleetTaskKind

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_fleet_kind_and_r2_tables_exist() -> None:
    async def scenario() -> tuple[list[str], set[str], bool]:
        async with db_lifespan() as engine, engine.connect() as conn:
            labels = [
                str(r.enumlabel)
                for r in await conn.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = 'fleet_task_kind' ORDER BY e.enumsortorder"
                    )
                )
            ]
            tables = {
                str(r.table_name)
                for r in await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                        "('arv2_research_run','arv2_research_job','arv2_claim_annotation')"
                    )
                )
            }
            extras = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns WHERE table_name = "
                        "'provider_call_ledger' AND column_name = 'extras_json'"
                    )
                )
            ).first() is not None
        return labels, tables, extras

    labels, tables, extras = run_async(scenario())
    # Presence, not last-ness: R4 appended ``arv2_discovery`` after this one. The ordered
    # comparison below is what actually proves labels are appended and never inserted.
    assert "arv2_account_research" in labels
    assert labels == [k.value for k in FleetTaskKind]
    assert tables == {"arv2_research_run", "arv2_research_job", "arv2_claim_annotation"}
    assert extras


@pytest.mark.usefixtures("require_db")
def test_job_status_and_finished_at_move_together() -> None:
    """A terminal job without a ``finished_at`` is not a row this substrate will hold."""

    async def scenario() -> str:
        async with db_lifespan() as engine, engine.connect() as conn:
            try:
                await conn.execute(
                    text(
                        "INSERT INTO arv2_research_job (job_id, run_id, workspace_id, "
                        "account_entity_id, status) VALUES (gen_random_uuid(), gen_random_uuid(), "
                        "'ws', gen_random_uuid(), 'completed')"
                    )
                )
            except Exception as error:  # noqa: BLE001 — the CHECK must refuse
                return str(error)
        return "accepted"

    # Named, so the row cannot be refused for some incidental reason (a missing FK parent, a
    # table that was never created) and leave the CHECK itself unexercised.
    assert "arv2_research_job_finished" in run_async(scenario())
