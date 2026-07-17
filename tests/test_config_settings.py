"""M0.4 — deploy-time settings (non-secret env) tests."""

from __future__ import annotations

import pytest

from clue_config import (
    DEFAULT_SYNTHESIS_MODEL,
    get_config,
    load_settings,
)
from clue_config.gateway import default_gateway_config


def test_synthesis_model_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_SYNTHESIS_MODEL", raising=False)
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.synthesis_model == DEFAULT_SYNTHESIS_MODEL
    assert settings.synthesis_model == "anthropic/claude-opus-4-8"


def test_synthesis_model_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SYNTHESIS_MODEL", "openai/gpt-4o")
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.synthesis_model == "openai/gpt-4o"


def test_gateway_config_picks_up_env_synthesis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SYNTHESIS_MODEL", "openai/gpt-4o-mini")
    assert default_gateway_config().synthesis_model == "openai/gpt-4o-mini"


def test_get_config_gateway_uses_env_synthesis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SYNTHESIS_MODEL", "anthropic/claude-3.5-sonnet")
    assert get_config("acme").gateway.synthesis_model == "anthropic/claude-3.5-sonnet"
