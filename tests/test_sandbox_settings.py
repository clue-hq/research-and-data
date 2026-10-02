"""Agent code execution and document attachments (spec 2026-09-19), Task 1: the sandbox settings
and the document-family per-file cap ship their defaults, honour their env names, and are
documented in ``.env.example`` with exactly those defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from clue_config import Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

#: Every setting this task introduces and the default it ships with.
DEFAULTS: dict[str, object] = {
    "sandbox_enabled": True,
    "sandbox_image": "clue-agent-sandbox:latest",
    "sandbox_timeout_s": 60.0,
    "sandbox_cpus": 1.0,
    "sandbox_memory_mb": 1024,
    "sandbox_max_runs_per_turn": 10,
    "sandbox_max_output_bytes": 1_048_576,
    "chat_attachment_document_max_bytes": 25 * 1024 * 1024,
}
#: The exact ``.env.example`` lines the parity rule requires for those settings.
ENV_LINES = {
    "CLUE_SANDBOX_ENABLED=true",
    "CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest",
    "CLUE_SANDBOX_TIMEOUT_S=60",
    "CLUE_SANDBOX_CPUS=1",
    "CLUE_SANDBOX_MEMORY_MB=1024",
    "CLUE_SANDBOX_MAX_RUNS_PER_TURN=10",
    "CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576",
    "CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400",
}


def test_sandbox_and_document_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for line in ENV_LINES:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    settings = Settings(_env_file=None)
    for name, value in DEFAULTS.items():
        assert getattr(settings, name) == value, name


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SANDBOX_ENABLED", "false")
    monkeypatch.setenv("CLUE_SANDBOX_MAX_RUNS_PER_TURN", "3")
    settings = Settings(_env_file=None)
    assert settings.sandbox_enabled is False
    assert settings.sandbox_max_runs_per_turn == 3


def test_every_new_key_is_documented_with_its_default() -> None:
    """The repo's parity rule: a flag the code reads appears in ``.env.example`` with its
    shipped default at the moment it is introduced."""
    body = ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = sorted(line for line in ENV_LINES if line not in body)
    assert not missing, f"absent from .env.example: {missing}"
