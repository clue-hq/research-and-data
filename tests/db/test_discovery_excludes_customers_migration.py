"""The ``customers`` onboarding step/run kind and the ``excluded_by_brief`` discovery disposition.

Spec 2026-10-16-discovery-excludes-seller-customers-design: onboarding researches the seller's
existing customers in its own step (and a customers-only run for brands onboarded earlier), and a
discovery candidate the brief excluded is recorded with the brief entry it matched. All three
vocabularies are CHECKs, so admitting the new values is a migration.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan

from .conftest import run_async


async def _check(conn: AsyncConnection, table: str, name: str) -> str:
    definition = await conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = CAST(:table AS regclass) AND conname = :name"
        ),
        {"table": table, "name": name},
    )
    return str(definition.scalar_one())


async def _definitions() -> dict[str, str]:
    async with db_lifespan() as engine, engine.connect() as conn:
        return {
            "step": await _check(conn, "onboarding_step", "onboarding_step_kind"),
            "run": await _check(conn, "onboarding_run", "onboarding_run_kind"),
            "disposition": await _check(
                conn, "arv2_discovery_candidate", "arv2_discovery_candidate_disposition"
            ),
            "entry": await _check(
                conn, "arv2_discovery_candidate", "arv2_discovery_candidate_excluded_entry"
            ),
            "gate": await _check(
                conn, "arv2_discovery_candidate", "arv2_discovery_candidate_excluded_gate"
            ),
        }


@pytest.mark.usefixtures("require_db")
def test_onboarding_admits_the_customers_step_and_run_kinds_without_dropping_one() -> None:
    found = run_async(_definitions())
    assert "'customers'" in found["step"]
    for kind in ("overview", "lineup", "catalog_sync", "reviews", "synthesis", "persona"):
        assert f"'{kind}'" in found["step"]
    assert "'customers'" in found["run"]
    assert "'full'" in found["run"] and "'personas'" in found["run"]


@pytest.mark.usefixtures("require_db")
def test_a_brief_exclusion_must_name_its_entry_and_a_gate_exclusion_its_gate() -> None:
    found = run_async(_definitions())
    assert "'excluded_by_brief'" in found["disposition"]
    assert "'excluded'" in found["disposition"] and "'found_before'" in found["disposition"]
    assert "excluded_by_brief" in found["entry"]
    assert "excluded_by_entry IS NOT NULL" in found["entry"]
    assert "excluded_by_gate IS NOT NULL" in found["gate"]
