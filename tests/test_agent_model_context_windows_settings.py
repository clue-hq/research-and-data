"""The context windows of the platform's own models are a deployment setting (2026-10-05).

Compaction sizes itself from a model's context window. The platform's models, and their windows,
are listed in ``CLUE_AGENT_MODEL_CONTEXT_WINDOWS`` beside the models themselves, so a worker never
fetches OpenRouter's catalogue for a model it runs on every day; the catalogue is only the
fallback for a model nobody registered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from clue_config import Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = (REPO / ".env.example").read_text()
ENV = "CLUE_AGENT_MODEL_CONTEXT_WINDOWS"

DEFAULT = {
    "x-ai/grok-4.6": 500_000,
    "x-ai/grok-4.7": 500_000,
    "meta/muse-spark-1.3": 1_048_576,
}


def _documented(name: str) -> str:
    found = re.search(rf"^{name}=(.*)$", ENV_EXAMPLE, re.MULTILINE)
    assert found is not None, f"{name} is not documented in .env.example"
    return found.group(1).strip()


def test_the_default_registers_the_platform_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    assert Settings(_env_file=None).agent_model_context_windows == DEFAULT


@pytest.mark.parametrize(
    "raw",
    [
        "x-ai/grok-4.6=500000, meta/muse-spark-1.3=1048576",
        '{"x-ai/grok-4.6": 500000, "meta/muse-spark-1.3": 1048576}',
    ],
)
def test_the_environment_accepts_a_list_or_json(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(ENV, raw)
    assert Settings(_env_file=None).agent_model_context_windows == {
        "x-ai/grok-4.6": 500_000,
        "meta/muse-spark-1.3": 1_048_576,
    }


def test_a_malformed_entry_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "x-ai/grok-4.6:500000")
    with pytest.raises(ValidationError, match=ENV):
        Settings(_env_file=None)


def test_env_example_documents_the_default() -> None:
    documented = Settings.model_validate({"agent_model_context_windows": _documented(ENV)})
    assert documented.agent_model_context_windows == DEFAULT


def test_every_model_env_example_names_has_a_registered_window() -> None:
    """A model named in the agent model block or the fallback chain, with no window registered,
    would silently go back to fetching the catalogue — so the registry must cover all of them."""
    models = {
        value.removeprefix("openai:")
        for value in re.findall(r"^[A-Z0-9_]*_AGENT_MODEL(?:_[A-Z]+)?=(\S+)$", ENV_EXAMPLE, re.M)
        if "/" in value
    }
    models |= {m.strip() for m in _documented("CLUE_AGENT_FALLBACK_MODELS").split(",") if m.strip()}
    assert models, "the agent model block was not found"
    assert models <= set(DEFAULT), f"no registered window for {sorted(models - set(DEFAULT))}"
