"""Where a CRM read lands: the thread's own ``reads/`` folder, looked up by the turn's execution.

A tool is handed a :class:`~clue_toolbelt.ToolContext`, which names the execution and nothing
else, so the conversation engine registers the turn's workspace here while it holds the lease and
releases it on every exit path — the same arrangement as the code sandbox's registry
(``clue_api.sandbox.workspaces.SandboxWorkspaces``). The fleet worker builds one instance and
hands the same object to the toolbelt and to the engine; two instances would mean a tool that
never finds the turn the engine bound.
"""

from __future__ import annotations

import threading

from clue_agents.ports import SpillSink
from clue_core import ExecutionId

__all__ = ["CrmReadSinks"]


class CrmReadSinks:
    """The live turns' ``reads/`` sinks, keyed by execution id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[ExecutionId, SpillSink] = {}

    def register(self, execution_id: ExecutionId, sink: SpillSink) -> None:
        """Bind this execution's workspace for the life of the turn."""
        with self._lock:
            if execution_id in self._live:
                raise ValueError("this execution already has a registered CRM read sink")
            self._live[execution_id] = sink

    def release(self, execution_id: ExecutionId) -> None:
        """End the binding. Idempotent: the turn's cleanup runs on more than one path."""
        with self._lock:
            self._live.pop(execution_id, None)

    def sink_for(self, execution_id: ExecutionId) -> SpillSink | None:
        """This execution's sink, or ``None`` when no turn registered one."""
        with self._lock:
            return self._live.get(execution_id)
