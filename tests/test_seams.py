"""Cross-package M0 seam contracts (Wave 1 integration).

`db/` (M0.3) and `config/` (M0.4) are built independently and cannot import each other
(import-linter forbids it), so each declares the database-DSN env-var name itself. This is the
machine-checked guard that the two never drift — a typo in either would silently break the DB seam
(the pool looks up one var while config reads another) with no other failing test to catch it.
"""

from __future__ import annotations

from clue_config import DB_DSN_ENV_VAR
from clue_db import DATABASE_URL_ENV


def test_database_dsn_env_var_seam_is_consistent() -> None:
    assert DATABASE_URL_ENV == DB_DSN_ENV_VAR == "CLUE_DATABASE_URL"
