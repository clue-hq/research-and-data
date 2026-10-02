"""Deepagent state extension frozen by C6.0.

``deepagents`` gives each declarative subagent fresh messages while propagating compatible custom
state fields.  The trusted constitution and context receipt therefore travel as explicit state,
not as model-reconstructed prompt folklore.
"""

from __future__ import annotations

from typing import NotRequired
from uuid import UUID

from deepagents import DeepAgentState

from clue_agents.contracts import AgentConstitution, ContextBundleManifest

__all__ = ["ClueDeepAgentState"]


class ClueDeepAgentState(DeepAgentState):
    constitution: AgentConstitution
    context_manifest: ContextBundleManifest
    turn_id: UUID
    finalize_envelope_artifact_key: NotRequired[str]

    tool_repair_rounds: NotRequired[int]
    tool_repair_batch: NotRequired[list[str]]
    tool_repair_turn: NotRequired[str]

    turn_budget_turn: NotRequired[str]
    turn_budget_rounds: NotRequired[int]
