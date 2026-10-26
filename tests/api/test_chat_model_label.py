"""The chat composer's model label follows the configured Head of ABM model (founder 2026-10-26)."""

from __future__ import annotations

import pytest

from clue_api.chat.composer_context import (
    PROJECT_CONVERSATION_MODEL_ID,
    model_display_name,
    project_conversation_model_id,
)


@pytest.mark.parametrize(
    ("model_id", "label"),
    [
        ("x-ai/grok-4.6", "Grok 4.6"),
        ("openai/gpt-6.1-sol", "Gpt 6.1 Sol"),
        ("anthropic/claude-opus-5.5", "Claude Opus 5.5"),
        ("grok-4.7", "Grok 4.7"),
        ("openai/gpt-6.1-sol:online", "Gpt 6.1 Sol"),
    ],
)
def test_a_model_id_reads_as_a_plain_name(model_id: str, label: str) -> None:
    assert model_display_name(model_id) == label


def test_the_conversation_model_follows_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEAD_OF_ABM_AGENT_MODEL", "  openai/gpt-6.1-sol ")
    assert project_conversation_model_id() == "openai/gpt-6.1-sol"
    monkeypatch.setenv("HEAD_OF_ABM_AGENT_MODEL", "")
    assert project_conversation_model_id() == PROJECT_CONVERSATION_MODEL_ID
    monkeypatch.delenv("HEAD_OF_ABM_AGENT_MODEL")
    assert project_conversation_model_id() == PROJECT_CONVERSATION_MODEL_ID
