"""Cross-package integration harness — a migrated DB gate for tests that span subsystems.

Every other DB suite lives under the package it exercises (``tests/identity``, ``tests/stage0``,
``tests/discovery_scoring``, …) and owns a conftest with the same migrated-DB gate. This directory
is for the tests that belong to **no single package** because their whole point is that two entry
paths meet on one row — FI-2 slice 0's canonical two-project fixture is the first.

Only the session-scoped migration + the skip gate live here. The seeded, rollback-isolated
connection is reused from ``tests.stage0.conftest`` (it already seeds the core pack, the import
pack, the starter packs and the source manifests — everything both the discovery phase and the
import pipeline read), so nothing about the fixture state is re-implemented here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> bool:
    """Migrate to head once per session when a DB is reachable; return whether it is."""
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_integration_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable DB is available (so ``make check`` stays green w/o one)."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the integration fixtures"
        )
