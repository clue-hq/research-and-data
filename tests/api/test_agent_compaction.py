"""Every governed agent's compaction is sized from settings and the model window."""

from __future__ import annotations

import pytest

import clue_agents.compaction_config as agent_compaction
import clue_api.agent_compaction
from clue_config import load_settings
from clue_gateway import model_windows


def test_compaction_for_reads_settings_and_the_registered_window_without_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The platform's models come from the registry setting; only an unregistered one reaches
    OpenRouter's catalogue (2026-10-05: a slow catalogue fetch froze a fleet worker for 105 s)."""
    model_windows._reset_cache()
    fetched: list[int] = []

    def catalogue() -> dict[str, int]:
        fetched.append(1)
        return {}

    monkeypatch.setattr(model_windows, "_fetch_catalogue", catalogue)
    monkeypatch.setattr(
        agent_compaction,
        "load_settings",
        lambda: load_settings(_env_file=None, agent_compact_trigger_fraction=0.8),
    )
    settings = agent_compaction.compaction_for("x-ai/grok-4.6")
    assert settings.context_window == 500_000
    assert settings.trigger_fraction == 0.8
    assert fetched == [], "a registered model never reaches the catalogue"

    assert agent_compaction.compaction_for("x-ai/unknown").context_window is None
    assert fetched == [1]
    model_windows._reset_cache()


def test_the_platform_import_path_is_the_same_function() -> None:
    assert clue_api.agent_compaction.compaction_for is agent_compaction.compaction_for


@pytest.mark.parametrize(
    "given,expected",
    [
        ("openai:x-ai/grok-4.7", "x-ai/grok-4.7"),
        ("x-ai/grok-4.7", "x-ai/grok-4.7"),
        ("deepseek/deepseek-v4.1-flash:batch", "deepseek/deepseek-v4.1-flash:batch"),
        ("openai:deepseek/deepseek-v4.1-flash:batch", "deepseek/deepseek-v4.1-flash:batch"),
    ],
)
def test_the_window_lookup_ignores_a_langchain_provider_prefix(given: str, expected: str) -> None:
    assert agent_compaction.window_model_id(given) == expected


def test_the_design_agents_prefixed_model_gets_its_registered_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression 2026-10-05: ``openai:x-ai/grok-4.7`` resolved to no window at all."""
    model_windows._reset_cache()
    monkeypatch.setattr(model_windows, "_fetch_catalogue", lambda: {})
    monkeypatch.setattr(agent_compaction, "load_settings", lambda: load_settings(_env_file=None))
    assert agent_compaction.compaction_for("openai:x-ai/grok-4.7").context_window == 500_000
    model_windows._reset_cache()
