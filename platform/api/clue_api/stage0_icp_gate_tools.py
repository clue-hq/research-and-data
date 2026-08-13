"""Governed presentation of one exact draft ``icp_spec`` for human confirmation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, ClassVar, Literal

from pydantic import Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_gate import (
    KIND_ICP_CONFIRMATION,
    AgentGateRow,
    get_gate,
    insert_gate,
)
from clue_api.agent_gate_tools import gate_ref
from clue_api.stage0_icp_gate import (
    IcpGateSubject,
    IcpGateSubjectError,
    exact_icp_gate_subject,
    icp_confirmation_gate_id,
)
from clue_api.stage0_project_contracts import (
    ICP_GATE_DECISIONS,
    DraftIcpSpecRef,
    IcpGateDecision,
    TrustedStage0ProjectScopeInput,
)
from clue_api.stage0_project_scope import Stage0ProjectScope, resolve_stage0_project_scope
from clue_api.turn_action import (
    TurnActionUnresolvable,
    TurnIdentity,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
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
    "OpenIcpConfirmationGateInput",
    "OpenIcpConfirmationGateOutput",
    "OpenIcpConfirmationGateTool",
    "build_stage0_icp_gate_tools",
]


class OpenIcpConfirmationGateInput(TrustedStage0ProjectScopeInput):
    """The draft choice only; scope, subject bytes, digest and addressee are trusted."""

    icp_key: str = Field(min_length=1, max_length=200)
    icp_version: int = Field(gt=0)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class OpenIcpConfirmationGateOutput(ToolOutput):
    gate_id: str
    gate_ref: str
    gate_kind: Literal["icp_confirmation"]
    subject_ref: DraftIcpSpecRef
    subject_revision: int
    expected_subject_sha256: str
    permitted_decisions: tuple[IcpGateDecision, ...]
    addressee_user_id: str
    created: bool


class _GateRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _Resolved:
    scope: Stage0ProjectScope
    turn: TurnIdentity
    subject: IcpGateSubject
    existing_gate: AgentGateRow | None


class OpenIcpConfirmationGateTool(Tool):
    """Persist the exact human authority object for one synthesized draft ICP."""

    name = "open_icp_confirmation_gate"
    version = "1"
    model_description = (
        "Present one durable draft ICP spec to the current human for confirmation. Supply only "
        "the icp_key and icp_version returned by synthesize_icps@2; the platform derives and "
        "persists the exact snapshot, digest, permitted decisions, project scope and addressee. "
        "Then end awaiting input with the returned durable agent_gate id."
    )
    input_model: ClassVar[type[ToolInput]] = OpenIcpConfirmationGateInput
    output_model: ClassVar[type[ToolOutput]] = OpenIcpConfirmationGateOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="one presenting turn plus one exact draft icp_spec snapshot",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("icp_key", "icp_version"))
    pin_requirements = ("project", "product", "client_kb", "icp")

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OpenIcpConfirmationGateInput)
        try:
            async with self._conn_factory() as conn:
                await self._resolve(conn, inputs, ctx)
        except _GateRefused as exc:
            return (PreconditionFailure(reason_code=exc.code, message=str(exc)),)
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OpenIcpConfirmationGateInput)
        async with self._conn_factory() as conn:
            resolved = await self._resolve(conn, inputs, ctx)
            gate_id = icp_confirmation_gate_id(
                workspace_id=ctx.workspace_id,
                project_id=resolved.scope.project_id,
                subject_ref=resolved.subject.subject_ref,
                expected_subject_sha256=resolved.subject.sha256,
            )
            gate, created = await insert_gate(
                conn,
                gate_id=gate_id,
                workspace_id=resolved.scope.workspace_id,
                project_id=resolved.scope.project_id,
                thread_id=resolved.turn.thread_id,
                turn_id=resolved.turn.turn_id,
                kind=KIND_ICP_CONFIRMATION,
                subject_ref=resolved.subject.subject_ref,
                subject_revision=resolved.subject.spec.version,
                expected_subject_sha256=resolved.subject.sha256,
                subject_snapshot=resolved.subject.snapshot,
                permitted_decisions=ICP_GATE_DECISIONS,
                max_spend_cents=None,
                currency=None,
                addressee_user_id=resolved.turn.submitted_by_user_id or "",
            )
        output = OpenIcpConfirmationGateOutput(
            gate_id=str(gate.gate_id),
            gate_ref=gate_ref(gate.gate_id),
            gate_kind="icp_confirmation",
            subject_ref=resolved.subject.ref,
            subject_revision=resolved.subject.spec.version,
            expected_subject_sha256=gate.expected_subject_sha256,
            permitted_decisions=ICP_GATE_DECISIONS,
            addressee_user_id=gate.addressee_user_id,
            created=created,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())

    async def _resolve(
        self,
        conn: AsyncConnection,
        inputs: OpenIcpConfirmationGateInput,
        ctx: ToolContext,
    ) -> _Resolved:
        scope = await resolve_stage0_project_scope(
            conn,
            workspace_id=ctx.workspace_id,
            execution_id=ctx.execution_id,
        )
        if scope is None:
            raise _GateRefused(
                "stage0_scope_not_found",
                "the governed execution is not bound to a project in this workspace",
            )
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _GateRefused("gate_turn_ref_malformed", str(exc)) from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None or turn.project_id != scope.project_id:
            raise _GateRefused(
                "gate_turn_not_found",
                "the presenting turn is not part of this Stage-0 project",
            )
        if turn.submitted_by_user_id is None:
            raise _GateRefused(
                "gate_addressee_missing",
                "the presenting turn records no human addressee",
            )
        try:
            subject = await exact_icp_gate_subject(
                conn,
                scope=scope,
                icp_key=inputs.icp_key,
                icp_version=inputs.icp_version,
                require_project_synthesis=True,
            )
        except IcpGateSubjectError as exc:
            raise _GateRefused(exc.code, str(exc)) from exc
        gate_id = icp_confirmation_gate_id(
            workspace_id=ctx.workspace_id,
            project_id=scope.project_id,
            subject_ref=subject.subject_ref,
            expected_subject_sha256=subject.sha256,
        )
        existing = await get_gate(conn, workspace_id=ctx.workspace_id, gate_id=gate_id)
        if existing is not None:
            if existing.gate.thread_id != turn.thread_id:
                raise _GateRefused(
                    "icp_gate_already_presented_elsewhere",
                    "this exact ICP draft is already governed by a gate in another project thread",
                )
            if not existing.is_open:
                raise _GateRefused(
                    "icp_gate_already_answered",
                    "this exact ICP draft already has an immutable human decision",
                )
        return _Resolved(
            scope=scope,
            turn=turn,
            subject=subject,
            existing_gate=None if existing is None else existing.gate,
        )


def build_stage0_icp_gate_tools(*, conn_factory: ConnFactory = transaction) -> tuple[Tool, ...]:
    return (OpenIcpConfirmationGateTool(conn_factory=conn_factory),)
