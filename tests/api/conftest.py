"""DB harness for the api composition-root tests.

Reuses the M8 profiling fixtures + doubles (DRY): the session-scoped ``migrated_db`` /
``require_profiling_db`` skip-gate and the autouse resolver-binding reset are re-exported here so
``tests/api`` (a separate conftest scope) inherits them, and the test modules import the plain
helpers/doubles (``rollback_conn`` / ``seed_packs`` / ``insert_test_*`` / ``Fake*``) directly. DB
tests ``pytest.skip`` without a reachable ``CLUE_DATABASE_URL`` so ``make check`` stays green.

It also makes the api suite hermetic to ambient **activation flags**: these tests assert
default-off wiring (which routes/tools a composition root exposes), so an operator's live
trial/canary configuration (``CLUE_TRIAL_ENABLED``, ``CLUE_C7_*``, ``CLUE_AGENT_*_ROUTING_ENABLED``
…) must not change what they observe. See ``_hermetic_feature_flags`` below.
"""

from __future__ import annotations

import pytest

from clue_config import Settings

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

# Every boolean ``Settings`` field is an activation switch, and each is read from ``CLUE_<FIELD>``.
# Enumerated from the model rather than hand-listed so a flag added later is neutralised
# automatically. Deliberately narrow: booleans only — credentials, ``CLUE_DATABASE_URL``,
# Redis/storage URLs and model ids are left exactly as the ambient environment supplies them (the
# DB skip-gate and the operator's model selection must keep working).
FLAG_ENV_VARS: tuple[str, ...] = tuple(
    sorted(
        f"{Settings.model_config['env_prefix']}{name.upper()}"
        for name, field in Settings.model_fields.items()
        if field.annotation is bool
    )
)


@pytest.fixture(autouse=True)
def _hermetic_feature_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ambient activation flags so the api suite observes documented defaults.

    Two leak channels, both closed here:

    * the **process environment** — an operator shell with the trial/canary flags exported;
    * the **``.env`` file** — ``Settings`` declares ``env_file=".env"``, and the composition roots
      call the production ``load_settings()`` (no ``_env_file=None``), so a repo-root ``.env``
      reaches them even from an otherwise clean shell. ``tests/api/test_toolbelt_wiring.py::
      test_out_of_order_matrix`` fails on this channel alone. Detaching ``env_file`` for the
      duration of a test makes a local run see exactly what CI (which has no ``.env``) sees.
      Scoped to ``Settings``: ``Secrets`` keeps its own ``.env`` loading, so credentials and
      ``CLUE_DATABASE_URL`` — hence the DB skip-gate — are untouched.

    Function-scoped and autouse, so it runs before the test body: a test that *wants* a flag on
    still sets it (via its own ``monkeypatch.setenv`` or, more commonly here, by passing the value
    straight to ``load_settings``) after this cleanup, and ``monkeypatch`` restores the operator's
    environment afterwards.
    """
    for var in FLAG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
