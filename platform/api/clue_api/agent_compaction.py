"""Compaction thresholds for a governed agent's model (founder ruling 2026-09-29).

The function lives in :mod:`clue_agents.compaction_config` so the design agent sizes its
compaction the same way; this module keeps the platform's import path.
"""

from __future__ import annotations

from clue_agents.compaction_config import compaction_for

__all__ = ["compaction_for"]
