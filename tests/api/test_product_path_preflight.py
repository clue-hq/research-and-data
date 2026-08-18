"""The integration-pilot product path refuses to start without its provider credentials."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from clue_api.product_path_preflight import (
    ProductPathCompositionError,
    assert_product_path_composition,
)
from clue_config import Secrets, Settings

# The package conftest's autouse hermeticity strips *boolean* ``Settings`` flags only, and leaves
# credentials as the ambient environment supplies them. These tests read exactly the two channels it
# leaves alone — ``CLUE_PRODUCT_PATH`` (a ``Literal``, not a bool) and the three provider keys — and
# the repo's documented local workflow is ``set -a; source .env; set +a``, so those variables are
# normally exported. Without this, an operator shell carrying a real Exa key silently satisfies the
# Exa requirement (so the "names every missing credential" assertion fails), and an exported
# ``CLUE_PRODUCT_PATH=integration_pilot`` means the default-path test is not testing the default
# path at all. Strip them per-test so every assertion here is about the values the test passes in.
_AMBIENT_VARS: tuple[str, ...] = (
    "CLUE_PRODUCT_PATH",
    "CLUE_EXA_API_KEY",
    "CLUE_SUMBLE_API_KEY",
    "CLUE_OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_product_path_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _AMBIENT_VARS:
        monkeypatch.delenv(var, raising=False)


def _pilot(**kw: object) -> Settings:
    return Settings(_env_file=None, product_path="integration_pilot", **kw)  # type: ignore[call-arg]


def test_default_path_never_raises() -> None:
    assert_product_path_composition(Settings(_env_file=None), Secrets(_env_file=None))  # type: ignore[call-arg]


def test_pilot_with_all_credentials_passes() -> None:
    assert_product_path_composition(
        _pilot(),
        Secrets(  # type: ignore[call-arg]
            _env_file=None,
            exa_api_key=SecretStr("k"),
            sumble_api_key=SecretStr("k"),
            openrouter_api_key=SecretStr("k"),
        ),
    )


def test_pilot_treats_a_blank_credential_as_missing() -> None:
    """``CLUE_EXA_API_KEY=`` (the spelling ``.env.example`` ships) parses to ``SecretStr('')``.

    A blank or whitespace-only key configures nothing, so it must fail the preflight exactly like an
    absent one — otherwise an operator who copied the example file starts a pilot process whose
    provider slots are silently dead.
    """
    with pytest.raises(ProductPathCompositionError) as err:
        assert_product_path_composition(
            _pilot(),
            Secrets(  # type: ignore[call-arg]
                _env_file=None,
                exa_api_key=SecretStr(""),
                sumble_api_key=SecretStr("   "),
                openrouter_api_key=SecretStr("k"),
            ),
        )
    msg = str(err.value)
    assert "CLUE_EXA_API_KEY" in msg
    assert "CLUE_SUMBLE_API_KEY" in msg
    assert "CLUE_OPENROUTER_API_KEY" not in msg


def test_pilot_names_every_missing_credential() -> None:
    with pytest.raises(ProductPathCompositionError) as err:
        assert_product_path_composition(_pilot(), Secrets(_env_file=None))  # type: ignore[call-arg]
    msg = str(err.value)
    assert "CLUE_EXA_API_KEY" in msg
    assert "CLUE_SUMBLE_API_KEY" in msg
    assert "CLUE_OPENROUTER_API_KEY" in msg
