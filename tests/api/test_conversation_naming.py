"""Conversation naming — the pure parts: settings, the name normaliser, the prompt."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from clue_api.conversation_naming import (
    NAMING_INPUT_CHARS,
    NAMING_RESPONSE_FORMAT,
    NAMING_SYSTEM_PROMPT,
    NamingOutcome,
    NamingRequest,
    TurnNamingLauncher,
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


def _naming_request() -> NamingRequest:
    return NamingRequest(
        workspace_id="ws",
        project_id="prj",
        thread_id="thr",
        turn_id=uuid4(),
        user_message="u",
        assistant_message="a",
    )


class _SlowNamer:
    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s
        self.calls: list[NamingRequest] = []

    async def name(self, request: NamingRequest) -> NamingOutcome:
        self.calls.append(request)
        await asyncio.sleep(self.delay_s)
        return NamingOutcome(chat_title="Fast title", project_name=None, skipped_reason=None)


def test_launcher_without_a_namer_starts_nothing() -> None:
    async def scenario() -> None:
        launcher = TurnNamingLauncher(namer=None)
        assert launcher.start(_naming_request()) is None
        assert await launcher.wait_grace(None) is True
        assert launcher.pending == 0

    asyncio.run(scenario())


def test_fast_namer_finishes_inside_the_grace() -> None:
    async def scenario() -> None:
        namer = _SlowNamer(0.01)
        launcher = TurnNamingLauncher(namer=namer, grace_s=0.5)
        task = launcher.start(_naming_request())
        assert task is not None
        assert await launcher.wait_grace(task) is True
        assert task.result().chat_title == "Fast title"
        assert launcher.pending == 0

    asyncio.run(scenario())


def test_slow_namer_is_left_running_detached_and_still_completes() -> None:
    async def scenario() -> None:
        namer = _SlowNamer(0.2)
        launcher = TurnNamingLauncher(namer=namer, grace_s=0.02)
        task = launcher.start(_naming_request())
        assert task is not None
        assert await launcher.wait_grace(task) is False
        assert not task.done()
        assert launcher.pending == 1
        await task
        assert task.result().chat_title == "Fast title"
        assert launcher.pending == 0

    asyncio.run(scenario())


def test_launcher_swallows_a_namer_that_raises() -> None:
    class _Broken:
        async def name(self, request: NamingRequest) -> NamingOutcome:
            raise RuntimeError("boom")

    async def scenario() -> None:
        launcher = TurnNamingLauncher(namer=_Broken(), grace_s=0.5)
        task = launcher.start(_naming_request())
        assert task is not None
        assert await launcher.wait_grace(task) is True
        assert task.result().skipped_reason == "unexpected_error"

    asyncio.run(scenario())
