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
from clue_api.product_selection_gate_tools import build_product_selection_gate_tools
from clue_api.stage0_icp_gate_tools import build_stage0_icp_gate_tools
from clue_db import ConnFactory, transaction
from clue_toolbelt import ToolRegistry

__all__ = ["register_agent_gate_tools"]


def register_agent_gate_tools(
    registry: ToolRegistry,
    *,
    conn_factory: ConnFactory = transaction,
    budget_controls_enabled: bool = True,
) -> None:
    """Register ``open_directive_confirmation_gate@1`` as the default for its name.

    ``budget_controls_enabled`` is ``Settings.budget_controls_enabled`` (FI pilot budget-controls).
    It changes only the *value* the tool result carries for ``max_spend_cents`` — never the
    descriptor — so the registered contract, and every profile pin over it, is identical in both
    modes."""

    for tool in build_agent_gate_tools(
        conn_factory=conn_factory,
        budget_controls_enabled=budget_controls_enabled,
    ):
        registry.register(tool, make_default=True)
    # ARV2 onboarding O6 (T6): ``open_icp_confirmation_gate@1`` is no longer the default alias for
    # its name. ``head-of-abm@v44`` pins ``@2`` — the gate over the ICP knowledge document — and a
    # default that disagreed with the active profile's pin would hand an unversioned caller the
    # gate nobody holds. ``@1`` stays registered, frozen, and resolvable by exact address for
    # replay. The ``@2`` registration claims the alias, in ``toolbelt_wiring`` (it needs storage).
    for tool in build_stage0_icp_gate_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=False)
    for tool in build_product_selection_gate_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=True)
