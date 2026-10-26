"""R-11.6: a turn submission says whether the agent replies to it (migration ``f09f9e286be6``).

The column defaults to ``expected`` (every submission before it ran a turn) and admits only
``expected`` and ``none``. The round trip downgrades to the previous revision and upgrades again,
so the DB is always left at head.
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
_PREVIOUS_REVISION = "0e92986934d3"


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _column() -> tuple[str | None, str | None]:
    async with db_lifespan() as engine, engine.connect() as conn:
        default = await conn.scalar(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'agent_turn_submission' AND column_name = 'agent_reply'"
            )
        )
        check = await conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'agent_turn_submission_agent_reply'"
            )
        )
    return default, check


@pytest.mark.usefixtures("require_db")
def test_agent_reply_round_trips() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    try:
        default, check = run_async(_column())
        assert default is not None and "expected" in default
        assert check is not None and "'expected'" in check and "'none'" in check

        command.downgrade(cfg, _PREVIOUS_REVISION)
        assert run_async(_column()) == (None, None)
    finally:
        command.upgrade(cfg, "head")
    assert run_async(_column())[1] is not None
