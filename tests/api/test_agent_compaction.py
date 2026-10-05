"""The composition root sizes every agent's compaction from settings and the model window."""

from __future__ import annotations

import pytest

import clue_api.agent_compaction as agent_compaction
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
