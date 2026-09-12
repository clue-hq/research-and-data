"""The onboarding lane is the default; the old Stage-0 recon composes only behind its own flag."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CLUE_ONBOARDING_V2_ENABLED",
        "CLUE_LEGACY_STAGE0_RECON_ENABLED",
        "CLUE_SELF_SERVE_PROVISIONING_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_the_new_lane_is_on_and_the_old_recon_is_off_by_default(clean_env: None) -> None:
    settings = Settings(_env_file=None)
    assert settings.onboarding_v2_enabled is True
    assert settings.legacy_stage0_recon_enabled is False
    # Provisioning alone no longer implies the old recon (ledger A4).
    assert (
        Settings(_env_file=None, self_serve_provisioning_enabled=True).legacy_stage0_recon_enabled
        is False
    )


def test_both_flags_are_documented_with_their_defaults() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(r"^CLUE_ONBOARDING_V2_ENABLED=true$", text, re.MULTILINE)
    assert re.search(r"^CLUE_LEGACY_STAGE0_RECON_ENABLED=false$", text, re.MULTILINE)
