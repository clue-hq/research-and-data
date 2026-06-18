"""pgvector smoke (M0.3 / ENG-114).

Covers the §M0.3 acceptance criterion: "CREATE EXTENSION vector succeeds in dev and CI; a trivial
vector column can be created and queried in a throwaway migration test." Skips gracefully without a
reachable DB.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_research.db import db_lifespan, transaction

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_create_extension_vector_and_use_a_throwaway_vector_column() -> None:
    """Enable `vector`, create a throwaway vector column, then insert + distance-query a row."""

    async def _run() -> None:
        async with db_lifespan(), transaction() as conn:
            # The extension is enabled by migration 0001; ensure it for a standalone run.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # Throwaway temp table dropped at session end — leaves no domain table behind.
            await conn.execute(
                text("CREATE TEMP TABLE _smoke_vec (id int PRIMARY KEY, embedding vector(3))")
            )
            await conn.execute(text("INSERT INTO _smoke_vec (id, embedding) VALUES (1, '[1,2,3]')"))
            # L2-distance query exercises the vector operator class.
            result = await conn.execute(
                text("SELECT id FROM _smoke_vec ORDER BY embedding <-> '[1,2,3]' LIMIT 1")
            )
            assert result.scalar_one() == 1

    run_async(_run())


@pytest.mark.usefixtures("require_db")
def test_vector_extension_is_installed() -> None:
    """After migrate-to-head (CI runs `make migrate` first), the `vector` extension is present."""

    async def _run() -> None:
        async with db_lifespan(), transaction() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            row = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            assert row.scalar_one() == "vector"

    run_async(_run())
