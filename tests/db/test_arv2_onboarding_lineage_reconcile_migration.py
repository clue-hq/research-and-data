"""The lineage states the reconciler writes, and its confidence/reason columns (O3 ladder)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_the_lineage_state_check_admits_the_model_states_and_the_reconcile_columns_exist() -> None:
    async def scenario() -> tuple[dict[str, str], set[str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            cons = await conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
                    "WHERE conrelid = 'onboarding_product_lineage'::regclass"
                )
            )
            cols = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'onboarding_product_lineage'"
                )
            )
            return {str(r.conname): str(r.d) for r in cons}, {str(r.column_name) for r in cols}

    constraints, columns = run_async(scenario())
    state = constraints["onboarding_product_lineage_state"]
    for s in (
        "created",
        "alias_reused",
        "lineage_reused",
        "model_reused",
        "model_unsure",
        "unresolved_ambiguous",
    ):
        assert s in state
    assert {"reconcile_confidence", "reconcile_reason"} <= columns
    assert "'high'" in constraints["onboarding_product_lineage_reconcile_confidence"]
