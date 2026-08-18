"""The integration-pilot product path refuses to start without its provider credentials."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from clue_api.product_path_preflight import (
    ProductPathCompositionError,
    assert_product_path_composition,
)
from clue_config import Secrets, Settings


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


def test_pilot_names_every_missing_credential() -> None:
    with pytest.raises(ProductPathCompositionError) as err:
        assert_product_path_composition(_pilot(), Secrets(_env_file=None))  # type: ignore[call-arg]
    msg = str(err.value)
    assert "CLUE_EXA_API_KEY" in msg
    assert "CLUE_SUMBLE_API_KEY" in msg
    assert "CLUE_OPENROUTER_API_KEY" in msg
