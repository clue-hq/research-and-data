"""Chat attachments (spec 2026-09-18), Task 2: the five limit settings ship their defaults,
honour their env names, and are documented in ``.env.example`` with exactly those defaults."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

#: Every chat-attachment setting and the default it ships with.
ATTACHMENT_SETTING_DEFAULTS: dict[str, int] = {
    "chat_attachment_max_files": 10,
    "chat_attachment_max_total_bytes": 150 * 1024 * 1024,
    "chat_attachment_image_max_bytes": 10 * 1024 * 1024,
    "chat_attachment_text_max_bytes": 5 * 1024 * 1024,
    "chat_attachment_history_images_max": 20,
}


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


def test_chat_attachment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ATTACHMENT_SETTING_DEFAULTS:
        monkeypatch.delenv(_env_name(name), raising=False)
    settings = Settings(_env_file=None)
    assert settings.chat_attachment_max_files == 10
    assert settings.chat_attachment_max_total_bytes == 150 * 1024 * 1024
    assert settings.chat_attachment_image_max_bytes == 10 * 1024 * 1024
    assert settings.chat_attachment_text_max_bytes == 5 * 1024 * 1024
    assert settings.chat_attachment_history_images_max == 20


def test_chat_attachment_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX", "0")
    monkeypatch.setenv("CLUE_CHAT_ATTACHMENT_MAX_FILES", "3")
    settings = Settings(_env_file=None)
    assert settings.chat_attachment_history_images_max == 0
    assert settings.chat_attachment_max_files == 3


def test_every_attachment_env_name_is_documented_with_its_default() -> None:
    """The repo's parity rule: a flag the code reads appears in ``.env.example`` with its
    shipped default at the moment it is introduced."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in ATTACHMENT_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        assert documented.group(1).strip() == str(default), field_name
