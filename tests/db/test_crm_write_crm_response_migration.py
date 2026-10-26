"""L8: a CRM write keeps the CRM's whole answer beside its message (migration ``01b066d230e7``).

``crm_write.crm_response`` is a nullable ``jsonb`` column. The round trip downgrades to the
previous revision and upgrades again, so the DB is always left at head.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PREVIOUS_REVISION = "f09f9e286be6"


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _column() -> tuple[str, str] | None:
    async with db_lifespan() as engine, engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'crm_write' AND column_name = 'crm_response'"
                )
            )
        ).one_or_none()
    return None if row is None else (row.data_type, row.is_nullable)


@pytest.mark.usefixtures("require_db")
def test_crm_response_round_trips() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    try:
        assert run_async(_column()) == ("jsonb", "YES")
        command.downgrade(cfg, _PREVIOUS_REVISION)
        assert run_async(_column()) is None
    finally:
        command.upgrade(cfg, "head")
    assert run_async(_column()) == ("jsonb", "YES")
