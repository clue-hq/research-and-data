"""C5 execution test scope: reuse the repository's migrated Postgres harness."""

from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db
