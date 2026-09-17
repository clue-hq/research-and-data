"""Lane 3 slice 1, Task 1: ``agent_model_call`` carries the gateway-measured cost beside the
still-zero ``cost_millicredits`` (which remains the uncomposed credits milestone's policy)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.db.conftest import run_async

# ``migrated_db``/``require_profiling_db``/``rollback_conn`` live in
# ``tests/profiling/conftest.py``, which pytest does not apply to this package; importing them here
# registers them for this module (the same pattern
# ``tests/db/test_work_email_verdict_migration.py`` uses for its own gate).
from tests.profiling.conftest import (  # noqa: F401
    migrated_db,
    require_profiling_db,
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_agent_model_call_has_nullable_cost_usd_and_cost_source() -> None:
    async def scenario() -> list[tuple[str, str, str]]:
        async with rollback_conn(seed_pack=False) as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'agent_model_call' "
                    "AND column_name IN ('cost_usd', 'cost_source') ORDER BY column_name"
                )
            )
            return [(r[0], r[1], r[2]) for r in rows]

    assert run_async(scenario()) == [
        ("cost_source", "text", "YES"),
        ("cost_usd", "numeric", "YES"),
    ]


def test_cost_source_check_rejects_a_word_outside_the_gateway_vocabulary() -> None:
    async def scenario() -> str:
        async with rollback_conn(seed_pack=False) as conn:
            check = await conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'agent_model_call_cost_source'"
                )
            )
            return str(check.scalar_one())

    definition = run_async(scenario())
    for word in ("metered", "estimate", "unpriced"):
        assert word in definition
    assert "free" not in definition  # the provider ledger's label, never a model call's
