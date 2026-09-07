"""Shared fixtures for the ARV2 tests.

Global Constraint 3: every test here calls the real provider with the key read from the repo-root
``.env`` through ``clue_config.Secrets``; a missing key is a ``skip`` naming the env var, never a
mock. Raw records and the ledger go under ``.artifacts/arv2/`` (git-ignored, Constraint 4).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clue_api.arv2.calls import Ceilings, ProviderCaller
from clue_api.arv2.sinks import FileRawSink, JsonlLedger
from clue_api.arv2.transport import HttpxTransport, Transport
from clue_config import Secrets


@pytest.fixture(scope="session")
def live_secrets() -> Secrets:
    """The real provider keys, read from ``.env`` — never printed, logged or written anywhere."""
    return Secrets()


def require_secret(secrets: Secrets, field_name: str) -> str:
    """Return a live key, or skip the test naming the env var the operator has to set."""
    value = getattr(secrets, field_name, None)
    if value is None:
        pytest.skip(f"CLUE_{field_name.upper()} is unset")
    return str(value.get_secret_value())


@pytest.fixture(scope="session")
def arv2_raw_root() -> Path:
    """Where live-test raw records and the ledger land (Constraint 4). Never committed."""
    root = Path(".artifacts/arv2")
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def make_caller(arv2_raw_root: Path) -> Callable[..., ProviderCaller]:
    """Factory for a caller writing to the on-disk raw sink and JSONL ledger."""

    def _make(
        transport: Transport | None = None, *, ceilings: Ceilings | None = None
    ) -> ProviderCaller:
        return ProviderCaller(
            transport=transport or HttpxTransport(),
            raw_sink=FileRawSink(arv2_raw_root / "raw"),
            ledger=JsonlLedger(arv2_raw_root / "ledger.jsonl"),
            ceilings=ceilings,
            now=lambda: datetime.now(UTC),
        )

    return _make
