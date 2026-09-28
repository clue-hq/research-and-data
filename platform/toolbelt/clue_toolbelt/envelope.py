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
  the legacy HANDOFF ``narrative_emit_skipped`` marker) — the durable handles a caller resolves
  later, not
  the payloads themselves.
* **Quality-mode slot (D9 / A8).** Every invocation carries an optional ``quality_mode: str | None``
  on the :class:`ToolContext` — **recorded and journaled, not yet resolved to knobs** (REQ-14 lands
  later). The slot exists so tool schemas do not churn when quality tiers arrive.
* **Actor (REQ-20).** ``ctx.actor`` is ``"human"`` or ``"agent"`` — stamped on the invocation span
  so every write is attributable and human/agent parity is observable.
"""

from __future__ import annotations

import abc
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from clue_core import ExecutionId, ExecutionNodeId, OperationId
from clue_db import ConnFactory

__all__ = [
    "Actor",
    "PrincipalKind",
    "ExternalReplayBoundary",
    "JournalParameterPolicy",
    "ToolContext",
    "ToolDescriptor",
    "ToolEffectClass",
    "PreconditionFailure",
    "ReplayPolicy",
    "ReplaySafety",
    "ToolEstimate",
    "ToolResult",
    "ToolInput",
    "ToolOutput",
    "UntypedToolOutput",
    "Tool",
]

# REQ-20 human↔agent parity: every invocation is one or the other, stamped on the span.
Actor = Literal["human", "agent"]
PrincipalKind = Literal["human", "service"]


class ToolInput(BaseModel):
    """Base for a tool's typed input model. ``extra='forbid'`` so an unknown field is a loud
    ``ValidationError`` (a typo'd key never silently no-ops), ``frozen`` so an input body is an
    immutable, canonicalisable record (its hash is the D6 idempotency body key)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolOutput(BaseModel):
    """Base for a tool's typed, reference-only output model."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class UntypedToolOutput(ToolOutput):
    """Legacy/ad-hoc output shape.

    It preserves compatibility for tools that have not yet declared a reference schema, but a
    descriptor carrying this model is deliberately not recipe-safe.
    """

    model_config = ConfigDict(frozen=True, extra="allow")


class ReplayPolicy(StrEnum):
    """The strongest replay statement a tool can truthfully make."""

    UNCERTIFIED = "uncertified"
    EFFECT_FREE = "effect_free"
    DOMAIN_IDEMPOTENT = "domain_idempotent"
    OPERATION_IDEMPOTENT = "operation_idempotent"
    AT_LEAST_ONCE = "at_least_once"


class ExternalReplayBoundary(StrEnum):
    """Residual behavior at an external provider boundary."""

    NONE = "none"
    AT_LEAST_ONCE = "at_least_once"
    IDEMPOTENCY_KEY = "idempotency_key"


class ToolEffectClass(StrEnum):
    """How an invocation affects durable or external state."""

    READ = "read"
    WRITE = "write"
    SPEND = "spend"
    STEERING = "steering"


@dataclass(frozen=True, slots=True)
class ReplaySafety:
    """The replay audit attached to a versioned tool descriptor."""

    policy: ReplayPolicy
    durable_identity: str
    operation_id_required: bool = False
    external_boundary: ExternalReplayBoundary = ExternalReplayBoundary.NONE
    notes: str = ""

    def __post_init__(self) -> None:
        if self.policy is not ReplayPolicy.UNCERTIFIED and not self.durable_identity.strip():
            raise ValueError("a certified replay policy requires a durable identity")
        if self.policy is ReplayPolicy.OPERATION_IDEMPOTENT and not self.operation_id_required:
            raise ValueError("operation-idempotent tools must require operation_id")
        if (
            self.policy is ReplayPolicy.AT_LEAST_ONCE
            and self.external_boundary is not ExternalReplayBoundary.AT_LEAST_ONCE
        ):
            raise ValueError("at-least-once tools must declare an at-least-once external boundary")
        if (
            self.policy is ReplayPolicy.EFFECT_FREE
            and self.external_boundary is not ExternalReplayBoundary.NONE
        ):
            raise ValueError("effect-free tools cannot declare an external replay boundary")

    @classmethod
    def uncertified(cls) -> ReplaySafety:
        return cls(policy=ReplayPolicy.UNCERTIFIED, durable_identity="")


@dataclass(frozen=True, slots=True)
class JournalParameterPolicy:
    """What may be copied into a display-safe journal projection.

    The validated body itself is always artifact-backed in C5.1. This allowlist controls only
    small top-level scalars/references that may also appear in graph/event JSON.
    """

    safe_display_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.safe_display_fields)) != len(self.safe_display_fields):
            raise ValueError("journal safe-display fields must be unique")
        if any(not item or "." in item for item in self.safe_display_fields):
            raise ValueError("journal safe-display fields must be non-empty top-level names")


def _schema_sha256(model: type[BaseModel]) -> str:
    payload = json.dumps(model.model_json_schema(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Immutable addressable contract for one exact ``name@version`` implementation."""

    name: str
    version: str
    model_description: str
    input_model: type[ToolInput]
    output_model: type[ToolOutput]
    input_schema_sha256: str
    output_schema_sha256: str
    replay: ReplaySafety
    effect_class: ToolEffectClass
    parameter_policy: JournalParameterPolicy
    pin_requirements: tuple[str, ...]
    has_steering_snapshot: bool

    def __post_init__(self) -> None:
        if not self.name.strip() or "@" in self.name:
            raise ValueError("tool name must be non-empty and must not contain '@'")
        if not self.version.strip() or "@" in self.version:
            raise ValueError("tool version must be non-empty and must not contain '@'")
        if not self.model_description.strip():
            raise ValueError("tool model description must be non-empty")
        missing = set(self.parameter_policy.safe_display_fields) - set(
            self.input_model.model_fields
        )
        if missing:
            raise ValueError(
                f"journal fields are absent from {self.name}@{self.version} input: "
                f"{sorted(missing)}"
            )
        if self.effect_class is ToolEffectClass.STEERING and not self.has_steering_snapshot:
            raise ValueError(
                f"steering tool {self.name}@{self.version} must implement audit_snapshot"
            )

    @property
    def address(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def has_typed_output(self) -> bool:
        return self.output_model is not UntypedToolOutput

    @property
    def recipe_safe(self) -> bool:
        return self.has_typed_output and self.replay.policy is not ReplayPolicy.UNCERTIFIED


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
    * ``operation_id`` — the stable logical-operation identity reused by every retry. Tool bodies
      derive durable row/run ids from it instead of minting fresh identities on each attempt.
    * ``principal_kind`` / ``actor_id`` / ``membership_id`` — authenticated internal authority.
      Human principals carry a Clue user and membership; service principals carry a distinct
      machine id and may only use the agent actor class.
    * ``action_ref`` — captured UI/turn action. Human gates derive receipts from this ambient value;
      caller-authored tool arguments never choose who approved an operation or which action carried
      the approval.
    * ``project_id`` — the project the call runs for, when its caller knows it (a turn's recipe
      execution, a design leg). Read-only scoping, never authority: a tool that serves
      project-scoped state reads it to pick the right project; ``None`` means unknown.
    """

    workspace_id: str
    actor: Actor
    conn_factory: ConnFactory
    operation_id: OperationId
    principal_kind: PrincipalKind | None = None
    actor_id: str | None = None
    membership_id: str | None = None
    action_ref: str | None = None
    quality_mode: str | None = None
    execution_id: ExecutionId | None = None
    execution_node_id: ExecutionNodeId | None = None
    execution_node_key: str | None = None
    parent_execution_id: ExecutionId | None = None
    execution_worker_id: str | None = None
    lease_generation: int | None = None
    project_id: str | None = None

    def __post_init__(self) -> None:
        if self.principal_kind is None:
            if self.membership_id is not None:
                raise ValueError("legacy tool context cannot carry an authenticated membership")
        elif self.actor_id is None:
            raise ValueError("authenticated tool context requires an actor id")
        elif self.principal_kind == "human":
            if self.actor != "human":
                raise ValueError("a human principal may only invoke with the human actor class")
            if self.membership_id is None or not self.membership_id.strip():
                raise ValueError("human tool context requires a membership id")
        elif self.actor != "agent":
            raise ValueError("a service principal may only invoke with the agent actor class")
        elif self.membership_id is not None:
            raise ValueError("service tool context cannot carry a human membership")
        if self.actor_id is not None and not self.actor_id.strip():
            raise ValueError("tool context actor id must be non-empty when supplied")
        if self.action_ref is not None and not self.action_ref.strip():
            raise ValueError("tool context action ref must be non-empty when supplied")
        if (self.execution_worker_id is None) != (self.lease_generation is None):
            raise ValueError("execution worker id and lease generation must be supplied together")
        if self.lease_generation is not None and self.lease_generation < 1:
            raise ValueError("lease generation must be positive")


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
    such as ``estimate_project`` (which returns a whole-project estimate in its references)."""

    cost_cents: Decimal = Decimal(0)
    detail: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def free(cls) -> ToolEstimate:
        """The zero-cost estimate — for pure-read and run-control tools (no external spend)."""
        return cls(cost_cents=Decimal(0))


class ToolResult(BaseModel):
    """The reference-carrying result of an invocation (never blobs).

    ``references`` is a JSON-serialisable mapping of the ids/keys/versions (and small scalar flags,
    e.g. the legacy HANDOFF ``narrative_emit_skipped`` marker) the caller resolves later. The whole
    result
    round-trips through JSON so the D6 idempotency store can replay a stored response byte-for-byte;
    ``replayed`` is set ``True`` by the runner when a result is served from that store (so a caller
    can tell a fresh execution from an idempotent replay). ``meta`` is a small JSON-able mapping the
    runner stamps with invocation-level metadata (today the pre-spend ``estimated_cost_cents`` from
    :meth:`Tool.estimate`) — distinct from ``references`` (the durable handles the tool itself
    returns)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    version: str
    references: dict[str, Any] = Field(default_factory=dict)
    replayed: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class Tool(abc.ABC):
    """The typed tool envelope. A concrete tool subclasses this at the ``clue_api`` root, sets
    ``name``/``version``/``input_model``, and implements :meth:`preconditions`, :meth:`estimate`,
    :meth:`invoke`. All three are the tool's *only* contract with the runner: :func:`invoke_tool` is
    the sanctioned path to a tool's capability, and every runner-mediated invocation runs inside the
    log_span/idempotency wrapper — a tool body never has to log or check idempotency itself (D5)."""

    #: The stable registry name (``reverse_profile``, ``run_deep_account``, …).
    name: ClassVar[str]
    #: The tool's schema/behaviour version — bumped when the input model or semantics change.
    version: ClassVar[str] = "1"
    #: Stable model-facing capability guidance. This is deliberately outside the input schema:
    #: improving when a tool should be used must not invalidate frozen recipe/profile schema pins.
    model_description: ClassVar[str | None] = None
    #: The pydantic input model the runner validates the request body against.
    input_model: ClassVar[type[ToolInput]]
    #: The exact reference-only result schema. The legacy default is not recipe-safe.
    output_model: ClassVar[type[ToolOutput]] = UntypedToolOutput
    #: Replay proof for this exact version. Uncertified tools cannot enter a standing recipe.
    replay: ClassVar[ReplaySafety] = ReplaySafety.uncertified()
    #: Read/write/spend/steering classification used by the journal and authority gates.
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    #: Safe display/reference allowlist. The full validated body remains artifact-backed.
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy()
    #: Pin kinds this tool expects the compatibility loader to resolve in C5.2.
    pin_requirements: ClassVar[tuple[str, ...]] = ()

    @property
    def descriptor(self) -> ToolDescriptor:
        """Return the immutable contract for this exact implementation."""
        return ToolDescriptor(
            name=self.name,
            version=self.version,
            model_description=(
                self.model_description
                or f"Invoke exact governed platform tool {self.name}@{self.version}."
            ),
            input_model=self.input_model,
            output_model=self.output_model,
            input_schema_sha256=_schema_sha256(self.input_model),
            output_schema_sha256=_schema_sha256(self.output_model),
            replay=self.replay,
            effect_class=self.effect_class,
            parameter_policy=self.parameter_policy,
            pin_requirements=self.pin_requirements,
            has_steering_snapshot=type(self).audit_snapshot is not Tool.audit_snapshot,
        )

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

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> Mapping[str, Any]:
        """Return display-safe effective state for a steering before/after event.

        C5.1 invokes this hook around steering effects. Non-steering tools keep the empty default;
        a steering descriptor is invalid unless its class overrides this method.
        """
        del inputs, ctx
        return {}

    @abc.abstractmethod
    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        """Execute the capability and return a :class:`ToolResult` of **references** (ids/keys/
        versions), never blobs. Called only by the runner, only after preconditions pass, only
        inside the invocation span — so a tool body never has to log or check idempotency itself."""
        raise NotImplementedError
