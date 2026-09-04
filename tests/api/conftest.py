"""DB harness for the api composition-root tests.

Reuses the M8 profiling fixtures + doubles (DRY): the session-scoped ``migrated_db`` /
``require_profiling_db`` skip-gate and the autouse resolver-binding reset are re-exported here so
``tests/api`` (a separate conftest scope) inherits them, and the test modules import the plain
helpers/doubles (``rollback_conn`` / ``seed_packs`` / ``insert_test_*`` / ``Fake*``) directly. DB
tests ``pytest.skip`` without a reachable ``CLUE_DATABASE_URL`` so ``make check`` stays green.

It also makes the api suite hermetic to ambient **activation flags**: these tests assert
default-off wiring (which routes/tools a composition root exposes), so an operator's live
trial/canary configuration (``CLUE_TRIAL_ENABLED``, ``CLUE_C7_*``, ``CLUE_AGENT_*_ROUTING_ENABLED``
…) must not change what they observe. The autouse ``_hermetic_feature_flags`` covers every test
body; a **higher-scoped fixture is instantiated before it**, so a module-/session-scoped fixture
that builds a composition root must enter ``hermetic_flag_env()`` itself (see
``tests/api/test_agent_registry_wiring.py::registry``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

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
# automatically. Deliberately narrow otherwise: credentials, ``CLUE_DATABASE_URL``, Redis/storage
# URLs and model ids are left exactly as the ambient environment supplies them (the DB skip-gate
# and the operator's model selection must keep working).
#
# ``CLUE_PRODUCT_PATH`` is added explicitly: it is a ``Literal``, not a bool, but it is an
# activation switch of exactly the kind this fixture exists to neutralise — the
# ``integration_pilot`` overlay turns a dozen of the enumerated flags *on* as defaults, so leaving
# it exported flips the very wiring these tests assert is off (and the overlay wins wherever the
# stripped ``=false`` lines used to hold it back).
FLAG_ENV_VARS: tuple[str, ...] = tuple(
    sorted(
        {
            f"{Settings.model_config['env_prefix']}{name.upper()}"
            for name, field in Settings.model_fields.items()
            if field.annotation is bool
        }
        | {f"{Settings.model_config['env_prefix']}PRODUCT_PATH"}
    )
)


@contextmanager
def hermetic_flag_env() -> Iterator[None]:
    """Neutralise both activation-flag channels for the duration of the block.

    * the **process environment** — an operator shell with the trial/canary flags exported;
    * the **``.env`` file** — ``Settings`` declares ``env_file=".env"``, and the composition roots
      call the production ``load_settings()`` (no ``_env_file=None``), so a repo-root ``.env``
      reaches them even from an otherwise clean shell. ``tests/api/test_toolbelt_wiring.py::
      test_out_of_order_matrix`` fails on this channel alone. Detaching ``env_file`` makes a local
      run see exactly what CI (which has no ``.env``) sees. Scoped to ``Settings``: ``Secrets``
      keeps its own ``.env`` loading, so credentials and ``CLUE_DATABASE_URL`` — hence the DB
      skip-gate — are untouched.

    The one policy definition for the package: the autouse fixture below wraps every test in it,
    and a higher-scoped fixture (which pytest builds *before* any function-scoped fixture) enters
    it directly rather than re-implementing the neutralisation.
    """
    with pytest.MonkeyPatch.context() as mp:
        for var in FLAG_ENV_VARS:
            mp.delenv(var, raising=False)
        mp.setitem(Settings.model_config, "env_file", None)
        yield


@pytest.fixture(autouse=True)
def _hermetic_feature_flags() -> Iterator[None]:
    """Strip ambient activation flags so each api test observes documented defaults.

    Function-scoped and autouse, so it runs before the test body and before any other
    function-scoped fixture: a test that *wants* a flag on still sets it (via its own
    ``monkeypatch.setenv`` or, more commonly here, by passing the value straight to
    ``load_settings``) after this cleanup, and the operator's environment is restored afterwards.
    """
    with hermetic_flag_env():
        yield
