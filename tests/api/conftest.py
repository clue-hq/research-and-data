"""DB harness for the api composition-root tests.

Reuses the M8 profiling fixtures + doubles (DRY): the session-scoped ``migrated_db`` /
``require_profiling_db`` skip-gate and the autouse resolver-binding reset are re-exported here so
``tests/api`` (a separate conftest scope) inherits them, and the test modules import the plain
helpers/doubles (``rollback_conn`` / ``seed_packs`` / ``insert_test_*`` / ``Fake*``) directly. DB
tests ``pytest.skip`` without a reachable ``CLUE_DATABASE_URL`` so ``make check`` stays green.
"""

from __future__ import annotations

# Re-export the profiling DB fixtures so api tests can request them by name (fixtures must live in a
# conftest in scope; these are the same session-migrate + skip-gate the profiling suite uses).
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
