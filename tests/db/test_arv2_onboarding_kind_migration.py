"""The onboarding_run fleet kind and the artifact-keyed catalog lineage (O3 Task 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan
from clue_fleet import FleetTaskKind

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_the_fleet_kind_enum_has_onboarding_run_and_matches_the_db() -> None:
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
    # Not last any more — R2 appended ``arv2_account_research`` after it. What this test still
    # owns is that O3's label is present and the enum matches the DB in order.
    assert "onboarding_run" in labels
    assert labels == [k.value for k in FleetTaskKind]


@pytest.mark.usefixtures("require_db")
def test_the_onboarding_product_lineage_table_carries_its_contract() -> None:
    async def scenario() -> dict[str, str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conrelid = 'onboarding_product_lineage'::regclass"
                )
            )
            return {str(r.conname): str(r.definition) for r in rows}

    constraints = run_async(scenario())
    document_fk = constraints["onboarding_product_lineage_document_fk"]
    assert "brand_knowledge_document" in document_fk
    # A lineage row must never make its source document structurally undeletable — the S5
    # ``product_catalog_lineage`` precedent, where the cascade is what preserves DSAR reach.
    assert "ON DELETE CASCADE" in document_fk
    assert "(document_id, entry_ordinal)" in constraints["onboarding_product_lineage_entry_unique"]
    for state in ("created", "alias_reused", "lineage_reused", "unresolved_ambiguous"):
        assert state in constraints["onboarding_product_lineage_state"]
    assert "product" in constraints["onboarding_product_lineage_product_fk"]


@pytest.mark.usefixtures("require_db")
def test_the_lineage_append_only_trigger_refuses_edits_but_not_deletion() -> None:
    """Append-only means no in-place edits; it never meant the row cannot be deleted.

    The trigger must fire on UPDATE only, so the ``ON DELETE CASCADE`` on the document FK can
    actually run when a knowledge document is erased.
    """

    async def scenario() -> str:
        async with db_lifespan() as engine, engine.connect() as conn:
            definition = await conn.execute(
                text(
                    "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid = 'onboarding_product_lineage'::regclass "
                    "AND tgname = 'onboarding_product_lineage_append_only'"
                )
            )
            return str(definition.scalar_one())

    trigger = run_async(scenario())
    assert "BEFORE UPDATE ON" in trigger
    assert "DELETE" not in trigger
