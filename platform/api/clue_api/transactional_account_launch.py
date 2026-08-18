"""HTTP composition for the one-act directive approval + account-fleet launch.

The projections process must not compose the entity-research model/provider runtime: that work
belongs to the fleet worker.  A budget-controls-disabled directive gate still needs one small
piece of the launch plane in the HTTP transaction, however.  The human's approval turn, gate
answer, directive confirmation, fleet rows, queue offer, and tool journal must either all commit
or all roll back.

This module builds a request-scoped invoker for exactly
``launch_selected_account_research@1`` over the caller's bound connection factory.  It composes no
gateway, provider adapter, research agent, or worker handler; the launched ``ENTITY_RESEARCH_JOB``
is still executed only by the separately running fleet process.
"""

from __future__ import annotations

from collections.abc import Callable

from clue_api.account_research_fleet import AccountResearchFleetService
from clue_api.account_research_fleet_launch import AccountResearchFleetLauncher
from clue_api.entity_research_launch_tools import LaunchSelectedAccountResearchTool
from clue_api.execution_wiring import build_tool_invoker
from clue_config import Settings
from clue_db import ConnFactory
from clue_storage import StorageBackend
from clue_toolbelt import DbIdempotencyStore, ToolInvoker, ToolRegistry

TransactionalToolInvokerFactory = Callable[[ConnFactory], ToolInvoker]


def build_transactional_account_launch_invoker_factory(
    *,
    settings: Settings,
    storage: StorageBackend,
) -> TransactionalToolInvokerFactory:
    """Return the narrow launch-plane factory used by the structured gate-answer route."""

    def build(conn_factory: ConnFactory) -> ToolInvoker:
        fleets = AccountResearchFleetService(conn_factory=conn_factory)
        launcher = AccountResearchFleetLauncher(
            fleets=fleets,
            conn_factory=conn_factory,
            enforce_budget=settings.budget_controls_enabled,
        )
        registry = ToolRegistry()
        registry.register(
            LaunchSelectedAccountResearchTool(
                service=launcher,
                budget_controls_enabled=settings.budget_controls_enabled,
                conn_factory=conn_factory,
            ),
            make_default=True,
        )
        return build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
            storage=storage,
            settings=settings,
            conn_factory=conn_factory,
        )

    return build


__all__ = [
    "TransactionalToolInvokerFactory",
    "build_transactional_account_launch_invoker_factory",
]
