"""Lane 3 slice 3a, Task 4: ``agent_model_call`` carries the Langfuse trace and observation ids
(nullable: NULL for Langfuse-off turns and every pre-migration row)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.db.conftest import run_async
from tests.profiling.conftest import (  # noqa: F401
    migrated_db,
    require_profiling_db,
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_agent_model_call_has_nullable_langfuse_ids() -> None:
    async def scenario() -> list[tuple[str, str, str]]:
        async with rollback_conn(seed_pack=False) as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'agent_model_call' "
                    "AND column_name IN ('langfuse_trace_id', 'langfuse_observation_id') "
                    "ORDER BY column_name"
                )
            )
            return [(r[0], r[1], r[2]) for r in rows]

    assert run_async(scenario()) == [
        ("langfuse_observation_id", "text", "YES"),
        ("langfuse_trace_id", "text", "YES"),
    ]
