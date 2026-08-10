"""Composition-root registration for the D4 gate tools (FI Lane D slice D4).

Its own module, per the ``*_wiring.py`` chokepoint protocol (`docs/specs/FI-lane-demarcation.md`
§3): a lane adds **one registration call** at the shared composition root and owns everything
behind it here, so parallel lanes never restructure ``toolbelt_wiring.build_toolbelt`` around each
other.

The gate tool takes no service — it reads durable directive/claim state and writes one immutable
row — so unlike the launch tools it is unconditionally available in every process that composes a
toolbelt. That is deliberate: presenting a gate spends nothing, and a deployment where the agent
could launch research but not *ask* first would be exactly backwards.
"""

from __future__ import annotations

from clue_api.agent_gate_tools import build_agent_gate_tools
from clue_db import ConnFactory, transaction
from clue_toolbelt import ToolRegistry

__all__ = ["register_agent_gate_tools"]


def register_agent_gate_tools(
    registry: ToolRegistry, *, conn_factory: ConnFactory = transaction
) -> None:
    """Register ``open_directive_confirmation_gate@1`` as the default for its name."""

    for tool in build_agent_gate_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=True)
