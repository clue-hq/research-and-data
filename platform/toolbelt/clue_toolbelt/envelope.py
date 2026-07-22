"""The typed tool envelope (Plane 2 / REQ-02 / Doc A — the single write path).

A *tool* is the platform's typed unit of research capability: a named, versioned envelope over an
existing backend capability with a pydantic input model, real machine-readable **preconditions**, a
cost **estimate**, and an async **invoke** that returns *references* (ids/keys) — never blobs (Doc R
"workers return references, not blobs"). Concrete tools are constructed and registered at the
``clue_api`` composition root (the only package that may import research/fleet/…); this envelope
lives in the dependency-inverted ``clue_toolbelt`` package (D5 — imports only
core/config/db/obs), so the toolbelt shape is stable while the capabilities behind it evolve.

Design points bound by the PB-B4 spec:

* **Preconditions are loud (pre-mortem #2).** ``preconditions(inputs, ctx)`` returns a sequence of
  :class:`PreconditionFailure` (empty ⇒ ready). The runner raises
  :class:`~clue_toolbelt.errors.PreconditionFailed` when non-empty — a tool never returns a
  silent-empty success on an unmet prerequisite.
* **Invoke returns references.** :meth:`Tool.invoke` returns a :class:`ToolResult` whose
  ``references`` is a JSON-serialisable mapping of ids/keys/versions (and small scalar flags such as
  the HANDOFF ``narrative_emit_skipped`` marker) — the durable handles a caller resolves later, not
  the payloads themselves.
* **Quality-mode slot (D9 / A8).** Every invocation carries an optional ``quality_mode: str | None``
  on the :class:`ToolContext` — **recorded and journaled, not yet resolved to knobs** (REQ-14 lands
  later). The slot exists so tool schemas do not churn when quality tiers arrive.
* **Actor (REQ-20).** ``ctx.actor`` is ``"human"`` or ``"agent"`` — stamped on the invocation span
  so every write is attributable and human/agent parity is observable.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from clue_db import ConnFactory

__all__ = [
    "Actor",
    "ToolContext",
    "PreconditionFailure",
    "ToolEstimate",
    "ToolResult",
    "ToolInput",
    "Tool",
]

# REQ-20 human↔agent parity: every invocation is one or the other, stamped on the span.
Actor = Literal["human", "agent"]


class ToolInput(BaseModel):
    """Base for a tool's typed input model. ``extra='forbid'`` so an unknown field is a loud
    ``ValidationError`` (a typo'd key never silently no-ops), ``frozen`` so an input body is an
    immutable, canonicalisable record (its hash is the D6 idempotency body key)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True, slots=True)
class ToolContext:
    """The ambient invocation context — *not* tool inputs, but who/where/how the call runs.

    * ``workspace_id`` — the tenant scope every precondition read and every write is bound to (a
      tool never crosses workspaces; the DB reads filter on it).
    * ``actor`` — ``"human"`` or ``"agent"`` (REQ-20), stamped on the invocation span.
    * ``conn_factory`` — the injected :data:`~clue_db.ConnFactory` a precondition reads the DB
      through (defaults to :func:`clue_db.transaction`); the toolbelt opens a connection no other
      way.
    * ``quality_mode`` — the A8 slot (D9): recorded/journaled, not resolved. ``None`` ⇒ unset.
    """

    workspace_id: str
    actor: Actor
    conn_factory: ConnFactory
    quality_mode: str | None = None


@dataclass(frozen=True, slots=True)
class PreconditionFailure:
    """A single unmet precondition: a ``reason_code`` (stable, machine-readable — the assertion
    surface for the out-of-order matrix + the HTTP error body) and a human ``message`` naming the
    fix. A tool documents its reason codes on its class; the runner collects any failures into a
    :class:`~clue_toolbelt.errors.PreconditionFailed`."""

    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class ToolEstimate:
    """The predicted cost of *running this tool once* (the pre-spend prior the UI shows before an
    invocation — Doc C §5). ``cost_cents`` is a :class:`~decimal.Decimal` (money is never a float);
    ``detail`` is an optional JSON-able breakdown. A pure-read/control tool returns
    :meth:`free` (zero, documented). This is distinct from the *result* of a cost-estimating tool
    such as ``estimate_project`` (which returns a whole-campaign estimate in its references)."""

    cost_cents: Decimal = Decimal(0)
    detail: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def free(cls) -> ToolEstimate:
        """The zero-cost estimate — for pure-read and run-control tools (no external spend)."""
        return cls(cost_cents=Decimal(0))


class ToolResult(BaseModel):
    """The reference-carrying result of an invocation (never blobs).

    ``references`` is a JSON-serialisable mapping of the ids/keys/versions (and small scalar flags,
    e.g. the HANDOFF ``narrative_emit_skipped`` marker) the caller resolves later. The whole result
    round-trips through JSON so the D6 idempotency store can replay a stored response byte-for-byte;
    ``replayed`` is set ``True`` by the runner when a result is served from that store (so a caller
    can tell a fresh execution from an idempotent replay)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    version: str
    references: dict[str, Any] = {}
    replayed: bool = False


class Tool(abc.ABC):
    """The typed tool envelope. A concrete tool subclasses this at the ``clue_api`` root, sets
    ``name``/``version``/``input_model``, and implements :meth:`preconditions`, :meth:`estimate`,
    :meth:`invoke`. All three are the tool's *only* contract with the runner — there is no other way
    to reach the backend capability, so an invocation cannot skip the log_span/idempotency wrapper
    (D5: an unlogged write is structurally impossible)."""

    #: The stable registry name (``reverse_profile``, ``run_deep_account``, …).
    name: ClassVar[str]
    #: The tool's schema/behaviour version — bumped when the input model or semantics change.
    version: ClassVar[str] = "1"
    #: The pydantic input model the runner validates the request body against.
    input_model: ClassVar[type[ToolInput]]

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        """Return the unmet preconditions for this ``(inputs, ctx)`` — an empty sequence ⇒ ready to
        invoke. Reads the DB through ``ctx.conn_factory``; MUST NOT write or spend. The default is
        "no preconditions" (a genuinely prerequisite-free tool such as ``reverse_profile`` /
        ``start_project_run``); every other tool overrides with real, documented reason codes."""
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        """The pre-spend cost prior for running this tool once (Doc C §5). Default: free (pure-read
        / control tools). A spend tool overrides with the existing estimate machinery or a static
        prior."""
        return ToolEstimate.free()

    @abc.abstractmethod
    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        """Execute the capability and return a :class:`ToolResult` of **references** (ids/keys/
        versions), never blobs. Called only by the runner, only after preconditions pass, only
        inside the invocation span — so a tool body never has to log or check idempotency itself."""
        raise NotImplementedError
