"""Plane 2 — the typed tool envelope + registry + invocation runner (build step 2 / REQ-02).

``clue_toolbelt`` is the **single typed write path** of the platform (Doc A: no fake agency — a
research capability becomes a *tool*, and the toolbelt is the only surface a human or an agent
invokes them through). It is dependency-inverted like the resolver seam (D5): it imports **only**
the shared base — ``clue_core`` / ``clue_config`` / ``clue_db`` / ``clue_obs`` — never
research/memory/content/fleet/gateway/api. The concrete tools (which *do* touch the capabilities)
are constructed and registered at the ``clue_api`` composition root (``clue_api.toolbelt_wiring``),
the only package allowed to import everything.

What ships here:

* :mod:`clue_toolbelt.envelope` — :class:`Tool` (the abstract typed envelope: name/version/input
  model, :meth:`~Tool.preconditions`, :meth:`~Tool.estimate`, :meth:`~Tool.invoke`), the
  :class:`ToolContext` (workspace + actor + conn factory + the A8 ``quality_mode`` slot),
  :class:`PreconditionFailure`, :class:`ToolEstimate`, :class:`ToolResult` (references not blobs).
* :mod:`clue_toolbelt.registry` — :class:`ToolRegistry` (register/get/list; duplicate = loud).
* :mod:`clue_toolbelt.runner` — :func:`invoke_tool`, the one wrapper that validates, checks
  idempotency (D6) + preconditions, and runs the body inside a mandatory ``log_span`` (an unlogged
  invocation is structurally impossible).
* :mod:`clue_toolbelt.idempotency` — the A9 store seam + its ``tool_invocation`` Db impl.
* :mod:`clue_toolbelt.errors` — ``UnknownTool`` / ``PreconditionFailed`` / ``IdempotencyConflict``.
"""

from __future__ import annotations

from clue_toolbelt.envelope import (
    Actor,
    PreconditionFailure,
    Tool,
    ToolContext,
    ToolEstimate,
    ToolInput,
    ToolResult,
)
from clue_toolbelt.errors import (
    IdempotencyConflict,
    PreconditionFailed,
    ToolbeltError,
    UnknownTool,
)
from clue_toolbelt.idempotency import (
    DbIdempotencyStore,
    IdempotencyStore,
    StoredInvocation,
    body_sha256,
)
from clue_toolbelt.registry import ToolRegistry
from clue_toolbelt.runner import invoke_tool

__all__ = [
    # envelope
    "Actor",
    "Tool",
    "ToolInput",
    "ToolContext",
    "ToolEstimate",
    "ToolResult",
    "PreconditionFailure",
    # registry
    "ToolRegistry",
    # runner
    "invoke_tool",
    # idempotency (A9)
    "IdempotencyStore",
    "DbIdempotencyStore",
    "StoredInvocation",
    "body_sha256",
    # errors
    "ToolbeltError",
    "UnknownTool",
    "PreconditionFailed",
    "IdempotencyConflict",
]
