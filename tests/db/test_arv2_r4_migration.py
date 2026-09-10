"""The R4 migration: the ``arv2_discovery`` fleet kind and the two discovery tables."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from clue_fleet import FleetTaskKind

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_fleet_kind_and_r4_tables_exist() -> None:
    async def scenario() -> tuple[list[str], set[str]]:
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
                        "('arv2_discovery_run','arv2_discovery_candidate')"
                    )
                )
            }
        return labels, tables

    labels, tables = run_async(scenario())
    assert "arv2_discovery" in labels
    assert FleetTaskKind.ARV2_DISCOVERY.value == "arv2_discovery"
    assert labels == [k.value for k in FleetTaskKind]
    assert tables == {"arv2_discovery_run", "arv2_discovery_candidate"}


@pytest.mark.usefixtures("require_db")
def test_candidate_domain_is_unique_per_run_and_dispositions_are_closed() -> None:
    """The two constraints the store's upsert and its closed vocabulary rely on."""

    async def scenario() -> set[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            return {
                str(r.conname)
                for r in await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'arv2_discovery_candidate'::regclass"
                    )
                )
            }

    names = run_async(scenario())
    assert "arv2_discovery_candidate_run_domain" in names
    assert "arv2_discovery_candidate_disposition" in names
