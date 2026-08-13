"""Reachable, migrated PostgreSQL gate for official-site repository tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from tests.db.conftest import _db_available

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return config


@pytest.fixture(scope="session")
def migrated_official_site_db() -> bool:
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_official_site_db(migrated_official_site_db: bool) -> None:
    if not migrated_official_site_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; set it to a disposable migrated DB"
        )
