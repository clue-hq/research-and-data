"""Design-substrate test harness (Part II D1) — a migrated DB + rollback-isolated work.

Mirrors the identity/claim-store harness: DB-requiring tests skip gracefully when
``CLUE_DATABASE_URL`` is unset or the database is unreachable (``make check`` stays green
without a database); when reachable, the schema is migrated to head once per session. Tests
run their writes inside transactions that either roll back on the asserted failure or are
rolled back explicitly, so they neither see nor leave rows behind. Reuses the M0.3 helpers
(DRY — not re-implemented).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

# Reuse the M0.3 helpers: the single-loop coroutine runner and the reachable-DB gate (DRY).
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
def require_design_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable database is available."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the design substrate tests"
        )
