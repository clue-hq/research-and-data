"""Composition-root registration for the REQ-21 thread tools (FI Lane D slice D0).

Its own module, per the ``*_wiring.py`` chokepoint protocol (`docs/specs/FI-lane-demarcation.md`
§3): a lane adds **one registration call** at the shared composition root and owns everything
behind it here, so parallel lanes never restructure ``toolbelt_wiring.build_toolbelt`` around each
other.
"""

from __future__ import annotations

from clue_api.thread_tools import build_thread_tools
from clue_db import ConnFactory, transaction
from clue_toolbelt import ToolRegistry

__all__ = ["register_thread_tools"]


def register_thread_tools(
    registry: ToolRegistry, *, conn_factory: ConnFactory = transaction
) -> None:
    """Register ``create_thread`` / ``rename_thread`` / ``set_thread_pinned`` / ``archive_thread``.

    Each becomes the default for its name — there is exactly one version of each today, and
    :class:`~clue_toolbelt.ToolRegistry` refuses a duplicate loudly, so a double registration fails
    at construction rather than in production.
    """

    for tool in build_thread_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=True)
