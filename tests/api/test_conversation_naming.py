"""Conversation naming — the pure parts: settings, the name normaliser, the prompt."""

from __future__ import annotations

from pathlib import Path

import pytest

from clue_config import Settings


def test_naming_settings_default_on_luna_sixty_seconds() -> None:
    settings = Settings(_env_file=None)
    assert settings.conversation_naming_enabled is True
    assert settings.conversation_naming_model == "openai/gpt-5.6-luna"
    assert settings.conversation_naming_timeout_s == 60.0


def test_naming_settings_read_their_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_CONVERSATION_NAMING_ENABLED", "false")
    monkeypatch.setenv("CLUE_CONVERSATION_NAMING_MODEL", "openai/gpt-5-mini")
    monkeypatch.setenv("CLUE_CONVERSATION_NAMING_TIMEOUT_S", "12.5")
    settings = Settings(_env_file=None)
    assert settings.conversation_naming_enabled is False
    assert settings.conversation_naming_model == "openai/gpt-5-mini"
    assert settings.conversation_naming_timeout_s == 12.5


def test_env_example_and_lane_env_carry_the_three_knobs() -> None:
    for path in (".env.example", ".env"):
        body = Path(path).read_text(encoding="utf-8")
        assert "CLUE_CONVERSATION_NAMING_ENABLED=true" in body, path
        assert "CLUE_CONVERSATION_NAMING_MODEL=openai/gpt-5.6-luna" in body, path
        assert "CLUE_CONVERSATION_NAMING_TIMEOUT_S=60.0" in body, path
