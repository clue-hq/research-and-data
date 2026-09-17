"""The governed tool that presents a directive-confirmation gate (FI Lane D D4, §3-P5(a)/(b)).

One tool, ``open_directive_confirmation_gate@1``, agent-callable. It is the only way a gate comes
into existence, and it exists as a *tool* rather than a route because the agent is the one that
decides it has finished drafting and is ready to ask — Doc A's rule that the platform's writes go
through the toolbelt applies to asking for authority exactly as it does to spending it.

Three properties it guarantees, all of them by deriving rather than accepting:

* **The addressee is not the agent's choice.** The gate is anchored to the turn the agent is
  currently answering (served through the PC-C8 ``TRUSTED_TURN_FIELD`` seam as ``source_turn_ref``,
  stripped from the model-visible schema), and its addressee is the human who *submitted* that turn,
  read from the durable submission row. A model that could name an addressee could address a gate to
  an account it controls.
* **The amount is not the agent's claim.** ``max_spend_cents`` is computed here by
  :func:`~clue_api.account_research_estimate.compute_account_research_estimate` — the identical Σ
  the launcher runs — and written immutably. Ratified §6-D5: no estimate tool, one number, verified
  again at launch.
* **The subject cannot drift.** The gate stores the directive's current ``canonical_json_sha256``;
  an answer that names a different digest is refused by the turn route, so approving a directive
  that has since been redrafted is unrepresentable rather than merely unlikely.

Presenting a gate spends nothing and confirms nothing. The agent's next act is to end its turn
``awaiting_input`` with the returned ``gate_ref`` in ``open_gate_refs``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, ClassVar
from uuid import UUID

from pydantic import Field, JsonValue, StringConstraints
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_discovery_readiness import (
    AccountResearchDiscoveryNotReady,
    require_sealed_account_discovery,
)
from clue_api.account_research_estimate import compute_account_research_estimate
from clue_api.agent_gate import (
    DEFAULT_GATE_CURRENCY,
    KIND_DIRECTIVE_CONFIRMATION,
    AgentGateSubjectBinding,
    directive_confirmation_gate_id,
    insert_gate,
    money_text,
)
from clue_api.turn_action import (
    TurnActionUnresolvable,
    TurnIdentity,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_core import EntityId, ProjectRunId, ResearchDirectiveId, ResearchDirectiveStatus
from clue_db import ConnFactory, transaction
from clue_research.directives import ResearchDirectiveError, get_research_directive
from clue_research.durable import get_project_run
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "AMOUNT_WITHHELD",
    "GATE_REF_PREFIX",
    "OpenDirectiveConfirmationGateInput",
    "OpenDirectiveConfirmationGateOutput",
    "OpenDirectiveConfirmationGateTool",
    "build_agent_gate_tools",
    "gate_ref",
]

#: The opaque reference the agent carries in ``open_gate_refs``; the ref's object type is
#: :data:`~clue_api.agent_gate.GATE_OBJECT_TYPE`. Spelled here once so a gate has one name.
GATE_REF_PREFIX = "agent-gate:"

#: Bounded so the snapshot stays a readable card rather than a second copy of the directive.
_MAX_SNAPSHOT_FIELDS = 40
_MAX_SNAPSHOT_QUESTIONS = 20

#: What ``max_spend_cents`` spells on a model-visible surface when the FI pilot budget-controls
#: switch is off. The empty string is not a number ``money_text`` can ever produce, so "withheld"
#: and "zero" stay distinguishable, and the frozen output schema is untouched.
AMOUNT_WITHHELD = ""


def gate_ref(gate_id: UUID) -> str:
    return f"{GATE_REF_PREFIX}{gate_id}"


class OpenDirectiveConfirmationGateInput(ToolInput):
    """What the agent proposes; every authority value is added by the engine, not by this model."""

    project_run_id: str = Field(min_length=1, max_length=64)
    research_directive_id: str = Field(min_length=1, max_length=64)
    account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


# The reference-only result schema. **Frozen** — ``head-of-abm/v23`` pins its
# ``output_schema_sha256``, so the FI pilot budget-controls switch may not add, remove, or retype a
# field here — nor even give this class a docstring, which pydantic publishes as the schema's
# ``description`` and which therefore moves the digest (spec AC5, learned the hard way).
# Presentation is suppressed by the *value*, not the shape: with controls off ``max_spend_cents``
# carries ``AMOUNT_WITHHELD`` — the empty string, which no amount ever spells — so the model is told
# a gate exists without being told a number it must not repeat. ``currency`` stays: a denomination
# without a quantity discloses nothing.
class OpenDirectiveConfirmationGateOutput(ToolOutput):
    gate_id: str
    gate_ref: str
    gate_kind: str
    subject_ref: str
    subject_revision: int
    expected_subject_sha256: str
    max_spend_cents: str
    currency: str
    account_count: int
    addressee_user_id: str
    created: bool


class _GateRefused(ValueError):
    """One typed refusal, raised by the shared resolution and rendered by both entry points."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class _ResolvedGateSubject:
    turn: TurnIdentity
    account_ids: tuple[EntityId, ...]
    subject_ref: str
    subject_revision: int
    expected_subject_sha256: str
    max_spend_cents: Decimal
    snapshot: dict[str, JsonValue]


def _failure(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


def _parse(
    inputs: OpenDirectiveConfirmationGateInput,
) -> tuple[ProjectRunId, ResearchDirectiveId, tuple[EntityId, ...]]:
    try:
        project_run_id = ProjectRunId(UUID(inputs.project_run_id))
        directive_id = ResearchDirectiveId(UUID(inputs.research_directive_id))
        account_ids = tuple(EntityId(UUID(value)) for value in inputs.account_entity_ids)
    except ValueError as exc:
        raise _GateRefused(
            "gate subject identifiers must be canonical identifiers",
            reason_code="gate_subject_malformed",
        ) from exc
    if len(set(account_ids)) != len(account_ids):
        raise _GateRefused(
            "a gate's account set must be unique",
            reason_code="gate_subject_malformed",
        )
    return project_run_id, directive_id, account_ids


class OpenDirectiveConfirmationGateTool(Tool):
    name = "open_directive_confirmation_gate"
    version = "1"
    model_description = (
        "Present the human with the confirmation gate for one drafted account-research directive "
        "and one exact account set: it records what you are asking them to approve and the "
        "server-computed maximum spend for that set. It spends nothing, confirms nothing, and "
        "launches nothing — end the turn awaiting input with the returned gate_ref, and only the "
        "human's own confirming turn can answer it."
    )
    input_model: ClassVar[type[ToolInput]] = OpenDirectiveConfirmationGateInput
    output_model: ClassVar[type[ToolOutput]] = OpenDirectiveConfirmationGateOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="the presented gate for one turn + one exact directive revision",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_run_id", "research_directive_id", "account_entity_ids")
    )
    pin_requirements = ("project_run", "research_directive")

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        budget_controls_enabled: bool = True,
    ) -> None:
        self._conn_factory = conn_factory
        self._budget_controls_enabled = budget_controls_enabled

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OpenDirectiveConfirmationGateInput)
        try:
            async with self._conn_factory() as conn:
                await self._resolve(conn, inputs, ctx)
        except _GateRefused as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        """Presenting a gate is free. The *amount on it* is what the human is asked about."""

        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OpenDirectiveConfirmationGateInput)
        async with self._conn_factory() as conn:
            resolved = await self._resolve(conn, inputs, ctx)
            gate_id = directive_confirmation_gate_id(
                workspace_id=ctx.workspace_id,
                turn_id=resolved.turn.turn_id,
                subject_ref=resolved.subject_ref,
                expected_subject_sha256=resolved.expected_subject_sha256,
            )
            row, created = await insert_gate(
                conn,
                gate_id=gate_id,
                workspace_id=ctx.workspace_id,
                project_id=resolved.turn.project_id,
                thread_id=resolved.turn.thread_id,
                turn_id=resolved.turn.turn_id,
                kind=KIND_DIRECTIVE_CONFIRMATION,
                subject_ref=resolved.subject_ref,
                subject_revision=resolved.subject_revision,
                expected_subject_sha256=resolved.expected_subject_sha256,
                subject_snapshot=resolved.snapshot,
                max_spend_cents=resolved.max_spend_cents,
                currency=DEFAULT_GATE_CURRENCY,
                # Derived from the durable submission, never proposed: the person who spoke is the
                # person entitled to answer.
                addressee_user_id=resolved.turn.submitted_by_user_id or "",
                subject_bindings=tuple(
                    AgentGateSubjectBinding(
                        subject_entity_id=UUID(str(account_id)),
                        binding_kind="research_directive_account",
                    )
                    for account_id in resolved.account_ids
                ),
            )
        presented_max_spend: str | None = AMOUNT_WITHHELD
        if self._budget_controls_enabled:
            if row.max_spend_cents is None:
                raise RuntimeError("directive confirmation gate is missing its computed spend cap")
            presented_max_spend = money_text(row.max_spend_cents)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "gate_id": str(row.gate_id),
                "gate_ref": gate_ref(row.gate_id),
                "gate_kind": row.kind,
                "subject_ref": row.subject_ref,
                "subject_revision": int(row.subject_revision or 0),
                "expected_subject_sha256": row.expected_subject_sha256,
                # FI pilot budget-controls: the amount is computed and stored on the immutable row
                # above in BOTH modes (audit + approval integrity); only its *presentation* is
                # gated. The model never needs the number — it hands the human a gate_ref and ends
                # the turn — so withholding it here costs the flow nothing.
                "max_spend_cents": presented_max_spend,
                "currency": row.currency,
                "account_count": len(resolved.account_ids),
                "addressee_user_id": row.addressee_user_id,
                "created": created,
            },
        )

    async def _resolve(
        self,
        conn: AsyncConnection,
        inputs: OpenDirectiveConfirmationGateInput,
        ctx: ToolContext,
    ) -> _ResolvedGateSubject:
        """Every check the gate depends on, run identically by preconditions and by invoke.

        One method rather than two so the tool cannot pass its own preconditions and then fail
        differently — the out-of-order matrix asserts that a refused precondition means no write,
        and that only holds if the two agree about what "refused" means.
        """

        project_run_id, directive_id, account_ids = _parse(inputs)
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _GateRefused(str(exc), reason_code="gate_turn_ref_malformed") from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None:
            raise _GateRefused(
                "no such turn in this workspace",
                reason_code="gate_turn_not_found",
            )
        if turn.submitted_by_user_id is None:
            raise _GateRefused(
                "this turn records no human submitter, so no gate can be addressed to anyone",
                reason_code="gate_addressee_missing",
            )
        project_run = await get_project_run(conn, project_run_id)
        if (
            project_run is None
            or project_run.workspace_id != ctx.workspace_id
            or project_run.project_id != turn.project_id
        ):
            raise _GateRefused(
                "no such project run in this conversation's project",
                reason_code="gate_project_run_not_found",
            )
        try:
            await require_sealed_account_discovery(
                conn,
                workspace_id=ctx.workspace_id,
                project_run_id=project_run_id,
                icp_key=project_run.icp_key,
                icp_version=project_run.icp_version,
            )
        except AccountResearchDiscoveryNotReady as exc:
            raise _GateRefused(str(exc), reason_code=exc.reason_code) from exc
        directive = await get_research_directive(conn, directive_id, workspace_id=ctx.workspace_id)
        if directive is None or directive.project_id != turn.project_id:
            raise _GateRefused(
                "no such workspace directive in this conversation's project",
                reason_code="research_directive_not_found",
            )
        if directive.status is not ResearchDirectiveStatus.DRAFT:
            raise _GateRefused(
                "only a current draft can be presented for confirmation",
                reason_code="research_directive_not_draft",
            )
        try:
            estimate = await compute_account_research_estimate(
                conn,
                workspace_id=ctx.workspace_id,
                project_run_id=project_run_id,
                directive_id=directive_id,
                account_ids=account_ids,
                # The gate's whole purpose is to price a *draft*; the launcher prices the confirmed
                # directive with the identical computation.
                allow_draft=True,
            )
        except ResearchDirectiveError as exc:
            raise _GateRefused(str(exc), reason_code="research_directive_invalid") from exc
        first = estimate.effective_by_account[account_ids[0]]
        snapshot: dict[str, JsonValue] = {
            "directive_ref": directive.directive_ref,
            "directive_version": directive.version,
            # The bare identifier as well as the versioned ref: the turn route confirms this exact
            # directive when the gate is approved, and re-parsing it out of a display string would
            # make the confirmation depend on a ref format nobody promised to keep.
            "research_directive_id": str(directive.directive_id),
            "project_run_id": str(project_run_id),
            "account_entity_ids": [str(value) for value in account_ids],
            "account_count": len(account_ids),
            "tier": first.effort_policy.tier,
            "field_keys": [str(value) for value in first.field_keys[:_MAX_SNAPSHOT_FIELDS]],
            "questions": [str(item.text) for item in first.questions[:_MAX_SNAPSHOT_QUESTIONS]],
        }
        return _ResolvedGateSubject(
            turn=turn,
            account_ids=account_ids,
            subject_ref=directive.directive_ref,
            subject_revision=directive.version,
            expected_subject_sha256=directive.canonical_json_sha256,
            max_spend_cents=estimate.total_cents,
            snapshot=snapshot,
        )


def build_agent_gate_tools(
    *,
    conn_factory: ConnFactory = transaction,
    budget_controls_enabled: bool = True,
) -> tuple[Tool, ...]:
    return (
        OpenDirectiveConfirmationGateTool(
            conn_factory=conn_factory,
            budget_controls_enabled=budget_controls_enabled,
        ),
    )
