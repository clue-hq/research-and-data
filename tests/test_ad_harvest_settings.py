"""Auto ad ingestion at onboarding (2026-09-28): the three ad-harvest settings ship their
defaults, honour their env names, and are documented in ``.env.example`` with exactly those
defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from clue_config import Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

DEFAULTS: dict[str, object] = {
    "brand_ad_assets_auto_onboard": True,
    "brand_ad_assets_auto_max_creatives": 50,
    "brand_ad_assets_auto_max_pages": 8,
}
ENV_LINES = {
    "CLUE_BRAND_AD_ASSETS_AUTO_ONBOARD=true",
    "CLUE_BRAND_AD_ASSETS_AUTO_MAX_CREATIVES=50",
    "CLUE_BRAND_AD_ASSETS_AUTO_MAX_PAGES=8",
}


def test_ad_harvest_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for line in ENV_LINES:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    for name, value in DEFAULTS.items():
        assert getattr(settings, name) == value, name


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_BRAND_AD_ASSETS_AUTO_ONBOARD", "false")
    monkeypatch.setenv("CLUE_BRAND_AD_ASSETS_AUTO_MAX_CREATIVES", "20")
    monkeypatch.setenv("CLUE_BRAND_AD_ASSETS_AUTO_MAX_PAGES", "3")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.brand_ad_assets_auto_onboard is False
    assert settings.brand_ad_assets_auto_max_creatives == 20
    assert settings.brand_ad_assets_auto_max_pages == 3


def test_every_new_key_is_documented_with_its_default() -> None:
    body = ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = sorted(line for line in ENV_LINES if line not in body)
    assert not missing, missing
