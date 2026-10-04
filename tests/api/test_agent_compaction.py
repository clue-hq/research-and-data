"""Every governed agent's compaction is sized from settings and the model window."""

from __future__ import annotations

import pytest

import clue_agents.compaction_config as agent_compaction
import clue_api.agent_compaction
from clue_config import load_settings


def test_compaction_for_reads_settings_and_the_models_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_compaction,
        "load_settings",
        lambda: load_settings(_env_file=None, agent_compact_trigger_fraction=0.8),
    )
    monkeypatch.setattr(
        agent_compaction,
        "resolve_context_window",
        lambda model_id, *, override: {"x-ai/grok-4.6": 500_000}.get(model_id),
    )
    settings = agent_compaction.compaction_for("x-ai/grok-4.6")
    assert settings.context_window == 500_000
    assert settings.trigger_fraction == 0.8
    assert agent_compaction.compaction_for("x-ai/unknown").context_window is None


def test_the_platform_import_path_is_the_same_function() -> None:
    assert clue_api.agent_compaction.compaction_for is agent_compaction.compaction_for
