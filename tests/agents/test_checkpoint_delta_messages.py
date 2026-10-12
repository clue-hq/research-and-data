"""Agent checkpoints store the message history as deltas, not a full copy per step.

deepagents declares ``messages`` as a ``DeltaChannel`` (a full snapshot every 50 updates, the
writes in between), which keeps checkpoint growth linear. In production every checkpoint saved the
whole list (run 5, 2026-10-12: the account agent's 91 blobs grew from 10 KB to 1.16 MB; no
production checkpoint of runs 3, 4 or 5 ever counted ``messages`` as a delta channel).

Cause: LangChain merges state schemas in a dict keyed by type, so a schema keeps its *first*
position. ``ToolRepairRoundsMiddleware`` and ``TurnBudgetMiddleware`` declared
``state_schema = ClueDeepAgentState``, which put our state early; our summariser's
``SummarizationState`` came later and its plain ``messages`` reducer won. A test model hides it:
deepagents' default summariser (same state type) sits earlier in the stack, and only the governed
harness profile removes it.
"""

from __future__ import annotations

from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.channels.delta import DeltaChannel

from clue_agents.compaction import (
    CompactionSettings,
    build_compaction_middleware,
    register_governed_harness_profile,
)
from clue_agents.model_session import ModelSessionAffinity
from clue_agents.runtime import TurnBudgetMiddleware
from clue_agents.state import ClueDeepAgentState
from clue_agents.tool_recovery import ToolRepairRoundsMiddleware
from clue_config.gateway import GatewayConfig
from clue_gateway.agent_model import GovernedAgentChatModel


def _governed() -> GovernedAgentChatModel:
    return GovernedAgentChatModel(
        models=(FakeMessagesListChatModel(responses=[AIMessage("ok")]),),
        model_ids=("openai/gpt-6.1-sol",),
        requested_model="openai/gpt-6.1-sol",
        gateway_config=GatewayConfig(),
    )


def test_the_production_composition_keeps_messages_a_delta_channel():
    register_governed_harness_profile()
    model = _governed()
    summariser, compact_tool = build_compaction_middleware(
        model, None, CompactionSettings(0.9, 0.1, 240_000, 40, None)
    )
    graph = create_deep_agent(
        model=model,
        middleware=(
            ModelSessionAffinity("session"),
            ToolRepairRoundsMiddleware(),
            TurnBudgetMiddleware(max_rounds=10, wrap_up_status="awaiting_input", max_runtime_s=0),
            summariser,
            compact_tool,
        ),
        state_schema=ClueDeepAgentState,
    )
    channel = graph.channels["messages"]
    assert isinstance(channel, DeltaChannel)
    assert channel.snapshot_frequency == 50
