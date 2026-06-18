"""Migration workflow tests (M0.3 / ENG-114).

Covers the §M0.3 acceptance criteria:
- "A reversible no-op (or pgvector-enabling) migration applies and rolls back cleanly; CI runs
  up -> down -> up green."  (`test_up_down_up_is_clean`)
- "The repo contains zero domain tables after M0 (a check enumerating tables finds only the
  extension + alembic version table)."  (`test_only_alembic_version_table_and_vector_after_head`)

These drive the *same* Alembic config the `make migrate` / `make db-smoke` targets use, via
Alembic's programmatic command API, so the test and the Make targets cannot drift. Skips without a
reachable DB.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from clue_research.db import db_lifespan

from .conftest import run_async

# Repo root = tests/db/ -> tests/ -> <root>.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _alembic_config() -> Config:
    """The project's Alembic config (reads DSN from CLUE_DATABASE_URL via alembic/env.py)."""
    cfg = Config(str(_ALEMBIC_INI))
    # script_location is relative to the ini; make it absolute so the test is CWD-independent.
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.mark.usefixtures("require_db")
def test_up_down_up_is_clean() -> None:
    """upgrade head -> downgrade base -> upgrade head, the migration smoke, runs without error."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    # Leave the schema at head for any following assertions / the live `make db-smoke`.


@pytest.mark.usefixtures("require_db")
def test_only_alembic_version_table_and_vector_after_head() -> None:
    """After migrating to head, only `alembic_version` exists — no domain tables — plus `vector`."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")

    async def _run() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            tables = (
                (
                    await conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public' ORDER BY table_name"
                        )
                    )
                )
                .scalars()
                .all()
            )
            exts = (
                (await conn.execute(text("SELECT extname FROM pg_extension ORDER BY extname")))
                .scalars()
                .all()
            )

        # Exactly one table — Alembic's bookkeeping table — and no domain tables.
        assert tables == ["alembic_version"], f"unexpected tables after M0 head: {tables}"
        # The vector extension is enabled; the rest are Postgres built-ins (e.g. plpgsql).
        assert "vector" in exts

    run_async(_run())


@pytest.mark.usefixtures("require_db")
def test_downgrade_to_base_drops_the_vector_extension() -> None:
    """`downgrade base` reverses migration 0001 — the vector extension is gone afterwards."""
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    async def _run() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            present = (
                await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            ).first()
        assert present is None, "downgrade base should have dropped the vector extension"

    run_async(_run())
    # Restore head so the DB is left in a consistent, migrated state.
    command.upgrade(cfg, "head")
