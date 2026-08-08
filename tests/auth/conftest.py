"""Migrated, rollback-isolated database harness for the Lane B identity substrate."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_auth_db() -> bool:
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_auth_db(migrated_auth_db: bool) -> None:
    if not migrated_auth_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; set an isolated database to "
            "exercise the Lane B identity tests"
        )


@asynccontextmanager
async def rollback_conn() -> AsyncIterator[AsyncConnection]:
    async with db_lifespan() as engine:
        conn = await engine.connect()
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()
            await conn.close()
