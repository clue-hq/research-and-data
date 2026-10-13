"""The fleet maintenance clock and the artifact privacy-purge index (2026-10-09).

``maintenance_run`` holds when a fleet-wide maintenance job last ran (one row per job), so a
48-hour storage sweep survives deploys and runs on one process. ``artifact_privacy_purged`` lets
the sweep find recently privacy-purged rows without reading the whole artifact table (review N-2).
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
_PREVIOUS_REVISION = "702784fe02b7"


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _state() -> tuple[object, object]:
    async with db_lifespan() as engine, engine.connect() as conn:
        table = (await conn.execute(text("SELECT to_regclass('maintenance_run')"))).scalar_one()
        index = (
            await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname='artifact_privacy_purged'")
            )
        ).scalar_one_or_none()
        return table, index


@pytest.mark.usefixtures("require_db")
def test_the_clock_and_the_index_exist_and_round_trip() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    table, index = run_async(_state())
    assert table is not None
    assert index == (
        "CREATE INDEX artifact_privacy_purged ON public.artifact USING btree (purged_at) "
        "WHERE privacy_erased"
    )
    command.downgrade(cfg, _PREVIOUS_REVISION)
    assert run_async(_state()) == (None, None)
    command.upgrade(cfg, "head")
    assert run_async(_state())[0] is not None
