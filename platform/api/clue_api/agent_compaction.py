"""Compaction thresholds for a governed agent's model (founder ruling 2026-09-29).

The composition-root half of :mod:`clue_agents.compaction`: it reads the deployment's settings and
the model's context window, so the agent runtime stays free of config and gateway imports. Every
``DeepAgentTurnRuntime`` is given :func:`compaction_for`, which the runtime calls per run with the
model it is about to build.
"""

from __future__ import annotations

from clue_agents.compaction import CompactionSettings
from clue_config import load_settings
from clue_gateway.model_windows import resolve_context_window


def compaction_for(model_id: str) -> CompactionSettings:
    settings = load_settings()
    return CompactionSettings(
        trigger_fraction=settings.agent_compact_trigger_fraction,
        keep_fraction=settings.agent_compact_keep_fraction,
        trigger_tokens=settings.agent_compact_trigger_tokens,
        keep_messages=settings.agent_compact_keep_messages,
        context_window=resolve_context_window(
            model_id, override=settings.agent_context_window_tokens
        ),
    )
