"""``open_icp_confirmation_gate@2`` — the ICP gate over a knowledge document (ARV2 onboarding O6).

The ``@1`` gate (:mod:`clue_api.stage0_icp_gate_tools`) presents one draft ``icp_spec`` row,
resolved through a governed execution's Stage-0 project scope. This version presents the artefact
the human can actually read: the brand's current ``icp-definition`` knowledge document, named by
document id and pinned by the digest of its exact bytes. It is deliberately a *version* of the same
tool rather than a new name — it asks the same question of the same person, about a subject that
has changed shape.

The model may decide the conversation is ready to ask, and it may name which ICP. It may not author
what is asked. Everything the gate carries is derived from durable rows:

* the **presenting turn** supplies the project, the thread and the addressee;
* the project supplies the **brand**, and the brand's own knowledge documents supply the subject;
* :func:`~clue_api.arv2.icp_confirmation.current_icp_document` reads the document back through its
  verified bytes, so the presented product ids, title and any existing confirmation are the
  document's own.

Nothing here reads a Client-KB version, a readiness decision or a Stage-0 pin — the presenting
turn's project is the coordinate (standing rule
``_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md``). The tool writes only the immutable
question; the chat route records the human's answer and mints the confirmed version.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from clue_agents.manual import tool_manual_link
from clue_api.agent_gate import (
    KIND_ICP_CONFIRMATION,
    get_gate,
    icp_artifact_gate_id,
    insert_gate,
)
from clue_api.agent_gate_tools import gate_ref
from clue_api.arv2.icp_confirmation import (
    IcpDocumentSubject,
    current_icp_document,
    icp_gate_snapshot,
    icp_gate_subject_ref,
)
from clue_api.stage0_project_contracts import ICP_GATE_DECISIONS, IcpGateDecision
from clue_api.turn_action import (
    TurnActionUnresolvable,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_spine import get_project
from clue_storage import StorageBackend
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
    "OpenIcpArtifactGateInput",
    "OpenIcpArtifactGateOutput",
    "OpenIcpArtifactGateTool",
    "build_icp_artifact_gate_tools",
]

#: The document statuses a human can be asked about — every servable one, since 2026-09-14. A
#: document the agent writes under ``project/`` is born ``ready``, including the ICP it drafted,
#: because the writer no longer decides that some paths are proposals and others are input: *this
#: gate* is what makes a document this project's ICP (founder ruling 2026-09-14). ``confirmed`` is
#: presentable too, because a brand's ICPs are shared and another project's confirmation is not
#: this project's answer.
_ANSWERABLE_STATUSES = ("ready", "proposed", "confirmed")


class OpenIcpArtifactGateInput(ToolInput):
    """The ICP to present, and nothing else: scope, subject bytes, digest and addressee are
    derived from the presenting turn."""

    icp_key: str = Field(min_length=1, max_length=200)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class OpenIcpArtifactGateOutput(ToolOutput):
    gate_id: str
    gate_ref: str
    gate_kind: Literal["icp_confirmation"]
    subject_ref: str
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
    gate_id: UUID
    turn_id: UUID
    thread_id: str
    project_id: str
    addressee: str
    subject: IcpDocumentSubject


class OpenIcpArtifactGateTool(Tool):
    """Persist the exact human authority object for one ICP knowledge document."""

    name = "open_icp_confirmation_gate"
    version = "2"
    model_description = (
        "Present one of this brand's ICP knowledge documents to the current human for "
        "confirmation. Supply the icp_key of the document you have read; the platform derives and "
        "persists the exact document, digest, permitted decisions, project and addressee. This "
        "call confirms nothing. Then end the turn awaiting input with the returned gate_ref. "
        + tool_manual_link("open_icp_confirmation_gate")
    )
    input_model: ClassVar[type[ToolInput]] = OpenIcpArtifactGateInput
    output_model: ClassVar[type[ToolOutput]] = OpenIcpArtifactGateOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="one presenting turn plus one exact ICP knowledge document",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("icp_key",))
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        storage: StorageBackend | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._storage = storage

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OpenIcpArtifactGateInput)
        try:
            await self._resolve(inputs, ctx)
        except _GateRefused as exc:
            return (PreconditionFailure(reason_code=exc.code, message=str(exc)),)
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OpenIcpArtifactGateInput)
        resolved = await self._resolve(inputs, ctx)
        subject = resolved.subject
        async with self._conn_factory() as conn:
            gate, created = await insert_gate(
                conn,
                gate_id=resolved.gate_id,
                workspace_id=ctx.workspace_id,
                project_id=resolved.project_id,
                thread_id=resolved.thread_id,
                turn_id=resolved.turn_id,
                kind=KIND_ICP_CONFIRMATION,
                subject_ref=icp_gate_subject_ref(subject),
                subject_revision=subject.version,
                expected_subject_sha256=subject.artifact_sha256,
                subject_snapshot=icp_gate_snapshot(subject),
                permitted_decisions=ICP_GATE_DECISIONS,
                # An ICP question spends nothing, so it carries no amount at all — and the route
                # refuses an answer that echoes one back.
                max_spend_cents=None,
                currency=None,
                addressee_user_id=resolved.addressee,
            )
        output = OpenIcpArtifactGateOutput(
            gate_id=str(gate.gate_id),
            gate_ref=gate_ref(gate.gate_id),
            gate_kind="icp_confirmation",
            subject_ref=gate.subject_ref,
            subject_revision=subject.version,
            expected_subject_sha256=gate.expected_subject_sha256,
            permitted_decisions=ICP_GATE_DECISIONS,
            addressee_user_id=gate.addressee_user_id,
            created=created,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())

    async def _resolve(self, inputs: OpenIcpArtifactGateInput, ctx: ToolContext) -> _Resolved:
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _GateRefused("gate_turn_ref_malformed", str(exc)) from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
            if turn is None:
                raise _GateRefused(
                    "gate_turn_not_found",
                    "the presenting turn is not part of this workspace",
                )
            if turn.submitted_by_user_id is None:
                raise _GateRefused(
                    "gate_addressee_missing",
                    "the presenting turn records no human addressee",
                )
            project = await get_project(conn, turn.project_id)
            if project is None or project.workspace_id != ctx.workspace_id:
                # Fail-closed and indistinguishable from an unresolvable turn: a turn whose
                # project this workspace cannot see is not a turn this workspace may present in.
                raise _GateRefused(
                    "gate_turn_not_found",
                    "the presenting turn's project is not part of this workspace",
                )
            subject = (
                None
                if self._storage is None
                else await current_icp_document(
                    conn,
                    self._storage,
                    workspace_id=ctx.workspace_id,
                    brand_id=project.brand_id,
                    icp_key=inputs.icp_key,
                    # The presenting turn supplies the project scope exactly as it supplies the
                    # brand: a project that authored its own variant of this key is asked about
                    # that variant, not about the brand's document.
                    project_id=turn.project_id,
                )
            )
            if subject is None:
                raise _GateRefused(
                    "icp_document_not_found",
                    f"this brand has no readable current ICP document for {inputs.icp_key!r}",
                )
            if subject.status not in _ANSWERABLE_STATUSES:
                raise _GateRefused(
                    "icp_document_not_servable",
                    f"the ICP document for {inputs.icp_key!r} is {subject.status}; "
                    "only a servable version can be presented",
                )
            if (
                subject.status == "confirmed"
                and subject.confirmed_for_project_id == turn.project_id
            ):
                raise _GateRefused(
                    "icp_already_confirmed_for_project",
                    "this project has already confirmed this exact ICP document",
                )
            gate_id = icp_artifact_gate_id(
                workspace_id=ctx.workspace_id,
                project_id=turn.project_id,
                subject_ref=icp_gate_subject_ref(subject),
                expected_subject_sha256=subject.artifact_sha256,
            )
            existing = await get_gate(conn, workspace_id=ctx.workspace_id, gate_id=gate_id)
            if existing is not None:
                if existing.gate.thread_id != turn.thread_id:
                    raise _GateRefused(
                        "icp_gate_already_presented_elsewhere",
                        "this exact ICP document is already governed by a gate in another thread",
                    )
                if not existing.is_open:
                    raise _GateRefused(
                        "icp_gate_already_answered",
                        "this exact ICP document already has an immutable human decision",
                    )
        return _Resolved(
            gate_id=gate_id,
            turn_id=turn.turn_id,
            thread_id=turn.thread_id,
            project_id=turn.project_id,
            addressee=turn.submitted_by_user_id,
            subject=subject,
        )


def build_icp_artifact_gate_tools(
    *,
    conn_factory: ConnFactory = transaction,
    storage: StorageBackend | None = None,
) -> tuple[Tool, ...]:
    return (OpenIcpArtifactGateTool(conn_factory=conn_factory, storage=storage),)
