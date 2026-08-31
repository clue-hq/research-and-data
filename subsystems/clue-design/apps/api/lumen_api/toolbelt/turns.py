"""Governed turn-enqueue tools (Part II slice D6 Round B).

The two design turn routes (``POST /agent/turns``, ``POST /documents/{id}/web/turns``) OFFER a
turn: they write the ``design_agent_run`` row and its ``design_job`` fleet task in ONE
transaction (``HybridRepository.create_run_and_offer``, R-D5-B5) and return. That single atomic
enqueue is the durable mutation, and it is what these tools govern.

**Everything before the row stays in the route.** Both routes deliberately validate and resolve
*before* the run row exists — reference attachments (the resolver's 422s would otherwise be
swallowed by the worker's catch-all into a generic ``agent_runtime.failed``), the document kind
and draft gates, the base-version check, the target account (an unknown id must 404 cleanly).
D6 does not move any of that: a tool precondition cannot produce ``reference.asset_not_found``,
and moving the resolution inside the tool would put an expensive rasterization behind the
journal for no governance gain. The gates that guard *the mutation itself* — the document
exists, is the right kind, is still a draft, and the run id is free — are mirrored here as
preconditions, so a non-HTTP caller cannot enqueue a turn the routes would have refused.

Replay honesty (R-D6-B3): ``OPERATION_IDEMPOTENT``, ``operation_id_required``. The run id is
minted fresh per request, so the *row* is a new identity every time — but the OFFER side is
domain-idempotent underneath: ``enqueue_task`` dedups on ``dedup_key = str(work_id)``, and the
work id is derived from the run id, so the run row and its task cannot diverge and a re-offer of
the same work id is absorbed by the queue rather than duplicated.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool
from .documents import document_failures

__all__ = [
    "StartAgentTurnInput",
    "StartAgentTurnTool",
    "StartWebTurnInput",
    "StartWebTurnTool",
    "TurnRunRef",
]

JsonObject = dict[str, Any]


class TurnRunRef(ToolOutput):
    """The offered run, by reference. Never the envelope — the caller already holds it."""

    run_id: str
    work_id: str
    document_id: str | None
    kind: str
    status: str


def _run_taken(repository: Any, run_id: str) -> tuple[PreconditionFailure, ...]:
    if repository.get_run(run_id) is None:
        return ()
    return (
        PreconditionFailure(
            reason_code="design_run_exists",
            message=f"design run {run_id!r} already exists in this workspace",
        ),
    )


class StartAgentTurnInput(ToolInput):
    #: Minted by the route (``run_<uuid4hex>``) — the tool never invents a run identity.
    run_id: str
    #: The fleet work id, derived from ``run_id``; it is also the queue's ``dedup_key``.
    work_id: str
    #: An agent turn legitimately names a document the store has never seen (the editor can
    #: drive a turn against an unsaved scene), so this is NOT gated on existence — the DAL
    #: stores an unknown id as NULL rather than rejecting it.
    document_id: str | None = None
    #: The FROZEN ``DesignTurnEnvelope`` payload: the request, the resolved reference assets and
    #: the workspace. Stored on both the run row and the fleet task, from this one object.
    envelope: JsonObject
    priority: int = 0


class StartAgentTurnTool(DesignTool):
    """Offer one scene-mode agent turn to the fleet."""

    name = "design_start_agent_turn"
    version = "1"
    model_description = (
        "Offer a scene-mode design agent turn to the worker fleet: writes the run row and its "
        "fleet task in one transaction and returns the run reference. The turn executes "
        "asynchronously."
    )
    input_model: ClassVar[type[ToolInput]] = StartAgentTurnInput
    output_model: ClassVar[type[ToolOutput]] = TurnRunRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + run_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the run id is minted per request, so each execution is a new run row; the OFFER "
            "side is domain-idempotent underneath (the fleet queue dedups on "
            "dedup_key = work_id, derived from the run id), so a run and its task can never "
            "diverge and a re-offer of the same work id is absorbed, not duplicated"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("run_id", "work_id", "document_id")
    )
    _kind: ClassVar[str] = "agent_turn"

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, StartAgentTurnInput)
        return _run_taken(self.host.repository(ctx.workspace_id), inputs.run_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, StartAgentTurnInput)
        run = self.host.repository(ctx.workspace_id).create_run_and_offer(
            inputs.run_id,
            inputs.document_id,
            kind=self._kind,
            envelope=inputs.envelope,
            work_id=UUID(inputs.work_id),
            priority=inputs.priority,
        )
        return TurnRunRef(
            run_id=run["run_id"],
            work_id=inputs.work_id,
            document_id=inputs.document_id,
            kind=self._kind,
            status=run["status"],
        )


class StartWebTurnInput(StartAgentTurnInput):
    """The scene turn's input with ``document_id`` promoted to REQUIRED.

    It subclasses deliberately: :class:`StartWebTurnTool` inherits ``run``, whose ``isinstance``
    narrowing would otherwise refuse its own input model.
    """

    #: Required on this path: a website turn is defined against one stored document, which the
    #: route has already resolved, kind-checked and base-version-checked.
    document_id: str


class StartWebTurnTool(StartAgentTurnTool):
    """Offer one website-mode agent turn to the fleet."""

    name = "design_start_web_turn"
    version = "1"
    model_description = (
        "Offer a website-mode design agent turn to the worker fleet: writes the run row and its "
        "fleet task in one transaction and returns the run reference. The turn's persist is "
        "governed separately by design_apply_web_operations."
    )
    input_model: ClassVar[type[ToolInput]] = StartWebTurnInput
    _kind: ClassVar[str] = "web_turn"

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, StartWebTurnInput)
        repository = self.host.repository(ctx.workspace_id)
        if failures := document_failures(
            repository,
            inputs.document_id,
            kind="web",
            draft=True,
            action="start an AI turn",
        ):
            return failures
        return _run_taken(repository, inputs.run_id)
