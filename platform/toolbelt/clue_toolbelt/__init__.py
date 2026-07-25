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
* :mod:`clue_toolbelt.runner` — :func:`invoke_tool`, the inner wrapper that validates, checks
  idempotency (D6) + preconditions, and runs the body inside a mandatory ``log_span``.
* :mod:`clue_toolbelt.invoker` — :class:`ToolInvoker`, the required production boundary that
  snapshots validated parameters and journals every invocation around the inner runner.
* :mod:`clue_toolbelt.idempotency` — the A9 store seam + its ``tool_invocation`` Db impl.
* :mod:`clue_toolbelt.errors` — ``UnknownTool`` / ``PreconditionFailed`` / ``IdempotencyConflict``.
"""

from __future__ import annotations

from clue_toolbelt.envelope import (
    Actor,
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolDescriptor,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
    UntypedToolOutput,
)
from clue_toolbelt.errors import (
    IdempotencyConflict,
    PreconditionFailed,
    ToolAwaitingInput,
    ToolbeltError,
    ToolContractViolation,
    UnknownTool,
)
from clue_toolbelt.idempotency import (
    DbIdempotencyStore,
    IdempotencyStore,
    StoredInvocation,
    body_sha256,
)
from clue_toolbelt.invoker import (
    InvocationCrashHook,
    InvocationJournal,
    JournalDisposition,
    JournalStart,
    ParameterSnapshot,
    ParameterSnapshotter,
    ToolInvoker,
)
from clue_toolbelt.registry import ToolRegistry
from clue_toolbelt.runner import invoke_tool

__all__ = [
    # envelope
    "Actor",
    "ExternalReplayBoundary",
    "JournalParameterPolicy",
    "ReplayPolicy",
    "ReplaySafety",
    "Tool",
    "ToolInput",
    "ToolOutput",
    "UntypedToolOutput",
    "ToolContext",
    "ToolDescriptor",
    "ToolEffectClass",
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
    # durable production invocation
    "InvocationJournal",
    "InvocationCrashHook",
    "JournalDisposition",
    "JournalStart",
    "ParameterSnapshot",
    "ParameterSnapshotter",
    "ToolInvoker",
    # errors
    "ToolbeltError",
    "ToolContractViolation",
    "ToolAwaitingInput",
    "UnknownTool",
    "PreconditionFailed",
    "IdempotencyConflict",
]
