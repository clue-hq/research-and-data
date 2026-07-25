"""DB harness for the B4 read-side projection tests (PB-B4 slice 3).

Mirrors ``tests/api/conftest.py``: re-exports the session-scoped ``migrated_db`` /
``require_profiling_db`` skip-gate + the autouse resolver-binding reset so this conftest scope
inherits them; the test modules import the plain helpers (``rollback_conn`` /
``conn_session_factory``) directly. DB tests ``pytest.skip`` without a reachable
``CLUE_DATABASE_URL`` so ``make check`` stays green.
"""

from __future__ import annotations

from tests.db.conftest import run_async as run_async
from tests.profiling.conftest import (
    _clear_resolver_bindings as _clear_resolver_bindings,
)
from tests.profiling.conftest import (
    migrated_db as migrated_db,
)
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)
