"""Default-off production wiring for Sumble S2 committee preparation."""

from __future__ import annotations

import pytest

from clue_api.sumble_committee_preparation import build_production_sumble_committee_preparer
from clue_config import Secrets, Settings
from tests.api.test_storage_wiring import FakeStorage


def test_sumble_committee_production_wiring_is_independently_default_off() -> None:
    result = build_production_sumble_committee_preparer(
        Settings(_env_file=None),
        secrets=Secrets(_env_file=None),
        inputs=object(),  # type: ignore[arg-type]
        storage=FakeStorage(),
        pre_spend_gate=object(),  # type: ignore[arg-type]
    )
    assert result is None


def test_enabling_sumble_committee_without_credential_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="CLUE_SUMBLE_API_KEY"):
        build_production_sumble_committee_preparer(
            Settings(_env_file=None, sumble_committee_acquisition_enabled=True),
            secrets=Secrets(_env_file=None, sumble_api_key=None),
            inputs=object(),  # type: ignore[arg-type]
            storage=FakeStorage(),
            pre_spend_gate=object(),  # type: ignore[arg-type]
        )
