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
                        "('arv2_discovery_run','arv2_discovery_candidate','arv2_discovery_search')"
                    )
                )
            }
        return labels, tables

    labels, tables = run_async(scenario())
    assert "arv2_discovery" in labels
    assert FleetTaskKind.ARV2_DISCOVERY.value == "arv2_discovery"
    assert labels == [k.value for k in FleetTaskKind]
    assert tables == {"arv2_discovery_run", "arv2_discovery_candidate", "arv2_discovery_search"}


@pytest.mark.usefixtures("require_db")
def test_a_run_owns_its_searches_one_webset_each_and_no_longer_carries_one_webset() -> None:
    """``97427f8eb3d6`` (rulings 2026-09-28): a run makes up to three searches, each a webset of its
    own, recorded before it is bought; the one-webset columns and the fixed provider ask are gone,
    and the disposition that remembers an earlier run's company is ``found_before``."""

    async def scenario() -> tuple[set[str], set[str], set[str], str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            run_columns = {
                str(r.column_name)
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'arv2_discovery_run'"
                    )
                )
            }
            search_columns = {
                str(r.column_name)
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'arv2_discovery_search'"
                    )
                )
            }
            constraints = {
                str(r.conname)
                for r in await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'arv2_discovery_search'::regclass"
                    )
                )
            }
            disposition = str(
                (
                    await conn.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname = 'arv2_discovery_candidate_disposition'"
                        )
                    )
                ).scalar_one()
            )
        return run_columns, search_columns, constraints, disposition

    run_columns, search_columns, constraints, disposition = run_async(scenario())
    assert not run_columns & {
        "webset_id",
        "strict_search_id",
        "relaxed_search_id",
        "strict_count",
        "relaxed_requested",
    }
    assert {"asked", "found_strict", "found_relaxed", "recall_estimate"} <= run_columns
    assert search_columns >= {
        "run_id",
        "ordinal",
        "kind",
        "external_id",
        "webset_id",
        "asked",
        "criteria",
        "exclude_webset_ids",
        "found",
        "finished_at",
    }
    assert constraints >= {
        "arv2_discovery_search_pkey",
        "arv2_discovery_search_kind",
        "arv2_discovery_search_external_id",
    }
    assert "found_before" in disposition and "not_chosen_before" not in disposition


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
