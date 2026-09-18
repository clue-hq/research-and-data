"""Conversation naming — the pure parts: settings, the name normaliser, the prompt."""

from __future__ import annotations

from pathlib import Path

import pytest

from clue_api.conversation_naming import (
    NAMING_INPUT_CHARS,
    NAMING_RESPONSE_FORMAT,
    NAMING_SYSTEM_PROMPT,
    build_naming_messages,
    normalize_generated_name,
)
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Find GI target accounts", "Find GI target accounts"),
        ('  "Find  GI\ttarget accounts."  ', "Find GI target accounts"),
        ("“Outreach to GI groups!”", "Outreach to GI groups"),
        ("Plan the Q4 push…", "Plan the Q4 push"),
        ("", None),
        ("   ", None),
        ("Untitled project", None),
        ("new chat", None),
        ("one two three four five six seven eight nine", None),
        ("x" * 61, None),
        (42, None),
        (None, None),
    ],
)
def test_normalize_generated_name(raw: object, expected: str | None) -> None:
    assert normalize_generated_name(raw) == expected


def test_prompt_states_the_rules_the_spec_fixed() -> None:
    for phrase in (
        "2 to 5 words",
        "language the user wrote in",
        "Sentence case",
        "Never repeat the project name inside the chat title",
        "Never invent company, product or segment names",
        "empty string",
    ):
        assert phrase in NAMING_SYSTEM_PROMPT, phrase
    schema = NAMING_RESPONSE_FORMAT["json_schema"]["schema"]
    assert set(schema["properties"]) == {"chat_title", "project_name"}
    assert schema["additionalProperties"] is False


def test_messages_carry_only_what_is_known_and_bound_the_exchange() -> None:
    messages = build_naming_messages(
        brand_name="Acme Health",
        product_name=None,
        project_name=None,
        needs_chat_title=True,
        needs_project_name=True,
        user_message="u" * (NAMING_INPUT_CHARS + 50),
        assistant_message="a" * (NAMING_INPUT_CHARS + 50),
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == NAMING_SYSTEM_PROMPT
    body = messages[1]["content"]
    assert "Brand: Acme Health" in body
    assert "Product:" not in body
    assert "Project:" not in body
    assert "Needed: chat_title, project_name" in body
    assert body.count("u") == NAMING_INPUT_CHARS
    assert body.count("a" * 10) == NAMING_INPUT_CHARS // 10

    named = build_naming_messages(
        brand_name="Acme Health",
        product_name="Aura",
        project_name="GI practice outreach",
        needs_chat_title=True,
        needs_project_name=False,
        user_message="Who should we target first?",
        assistant_message="Start with GI groups in Texas.",
    )
    body = named[1]["content"]
    assert "Product: Aura" in body
    assert "Project: GI practice outreach" in body
    assert (
        "Needed: chat_title" in body
        and "project_name" not in body.split("Needed:")[1].split("\n")[0]
    )
