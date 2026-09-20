"""Typed turn parts — projections of durable receipts, never stores.

FI Lane D slice **D3**, charter §3.1 (the Clue-part ↔ renderer map) and §3.4 (the payload floors).
Doc A §3a is the rule this module exists to obey: *the context window is a cache, never a store;
tool results return receipts, not goods.* A streamed part is therefore a **projection** — every
field is read from something durable (a plan operation, a tool receipt, a run row, a finalization
ref), and a part id is derived from that durable identity, so "which receipt is this card?" is
always answerable and never invented.

Everything here is pure and frozen: models plus derivation functions. The emitter
(:mod:`clue_api.chat.turn_stream`) decides *when* to send a snapshot; this module decides what a
snapshot legally contains. Keeping them apart is what lets the payload floors be unit-tested
without a database, a model, or a socket.

Two rules the models enforce structurally rather than by review:

* **Replacement, not append.** Every snapshot is the *full current state* of its part (§3.2), and
  carries a ``revision`` that increases per emission. A consumer replaces by ``(message_id,
  part_id)``; it never has to merge two half-cards.
* **No display copy.** No labels like "Thought for 5 seconds", no icons, no animation timings, no
  pre-rendered prose in a tool output (§3.1/§3.4). The backend sends semantic state; the frontend
  adapter chooses words.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue

__all__ = [
    "ActivityStep",
    "ActivityStepStatus",
    "AgentActivityPart",
    "ClarificationPart",
    "ClarificationQuestion",
    "GatePart",
    "PartKind",
    "PlanPart",
    "PlanStep",
    "ReasoningPart",
    "ReasoningState",
    "SourceItem",
    "SourcesPart",
    "TaskCounts",
    "TaskPart",
    "TaskState",
    "ToolPart",
    "ToolPartState",
    "TurnPart",
    "activity_part_id",
    "assistant_message_id",
    "clarification_part_id",
    "gate_part_id",
    "plan_part_id",
    "reasoning_part_id",
    "sources_part_id",
    "task_part_id",
    "text_part_id",
    "tool_part_id",
]


class PartKind(StrEnum):
    """The §3.1 domain-part vocabulary, mirrored by a SQL CHECK (migration ``98a5ddafa21b``)."""

    TEXT = "text"
    REASONING = "reasoning"
    AGENT_ACTIVITY = "agent_activity"
    TOOL = "tool"
    TASK = "task"
    PLAN = "plan"
    GATE = "gate"
    SOURCES = "sources"
    ACTION = "action"
    CLARIFICATION = "clarification"


class ToolPartState(StrEnum):
    """The AI Elements tool lifecycle, spelled exactly as §3.4 requires."""

    INPUT_STREAMING = "input-streaming"
    INPUT_AVAILABLE = "input-available"
    APPROVAL_REQUESTED = "approval-requested"
    APPROVAL_RESPONDED = "approval-responded"
    OUTPUT_AVAILABLE = "output-available"
    OUTPUT_DENIED = "output-denied"
    OUTPUT_ERROR = "output-error"


class TaskState(StrEnum):
    """§3.4's task vocabulary: one run stays one visible task at 1 account or 500."""

    QUEUED = "queued"
    SCOPING = "scoping"
    LIGHT_RESEARCH = "light_research"
    CHECKPOINT = "checkpoint"
    DEEP_RESEARCH = "deep_research"
    SYNTHESIZING = "synthesizing"
    NEEDS_INPUT = "needs_input"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"


class ActivityStepStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"
    ERROR = "error"


class ReasoningState(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    ERROR = "error"


class _Part(BaseModel):
    """Frozen, closed-shape, and always a complete snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    part_id: str
    kind: PartKind
    revision: int = Field(default=1, ge=1)

    def wire(self) -> dict[str, JsonValue]:
        """The ``part`` member of a §3.2 envelope."""

        return self.model_dump(mode="json", exclude_none=True)


class ToolPart(_Part):
    """One governed tool call, projected from its durable plan operation and receipt.

    ``output`` is structured JSON/refs — the receipt — never pre-rendered prose (§3.4). The
    adapter chooses disclosure copy; the backend states what happened.
    """

    kind: PartKind = PartKind.TOOL
    state: ToolPartState
    tool_name: str
    tool_version: str | None = None
    tool_call_id: str
    #: The durable receipt this card *is*: the ``agent_plan_operation`` node key, and its
    #: ``operation_id`` once the operation exists.
    node_key: str
    operation_id: UUID | None = None
    input: dict[str, JsonValue] | None = None
    output: dict[str, JsonValue] | None = None
    error_code: str | None = None
    error_reasons: tuple[str, ...] = ()


class ReasoningPart(_Part):
    """A safe status surface for one model round — never raw provider reasoning (§3.3's rule).

    In the shipped (``summary``) mode it carries no text at all. What the model privately "thought"
    is not a platform output; what the platform can honestly say is that a round is running or has
    ended, and how many governed calls it asked for. Both text fields default to ``None`` and
    ``wire()`` excludes ``None``, so a ``summary``-mode snapshot is byte-for-byte the payload this
    part has always had.

    ``text`` exists for the **dev-only** raw-reasoning lens (``CLUE_CHAT_REASONING_TRACE_MODE=raw``,
    refused at startup outside a dev deployment). When it is set, ``text_ephemeral`` is set with it
    and says the load-bearing thing about it: unlike assistant prose, this text has **no durable
    counterpart**. There is no reasoning message in the transcript, no byte-equality reconciliation
    against one, and nothing to re-fetch after a ``stream.reset`` — it exists for as long as the
    outbox holds it and then it is gone. A consumer must render it as a live diagnostic and must
    never treat it as part of the turn's record.
    """

    kind: PartKind = PartKind.REASONING
    state: ReasoningState
    round_ordinal: int = Field(ge=1)
    requested_tool_calls: int = Field(default=0, ge=0)
    started_at: str
    completed_at: str | None = None
    text: str | None = None
    text_ephemeral: bool | None = None


class ActivityStep(BaseModel):
    """One observed step of the agent's activity — stable id, semantic kind, status (§3.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: str
    status: ActivityStepStatus
    label: str
    description: str | None = None
    object_refs: tuple[dict[str, JsonValue], ...] = ()
    started_at: str | None = None
    completed_at: str | None = None


class AgentActivityPart(_Part):
    """The ordered, observed activity of one generation attempt (§3.4's ``agent_activity`` floor).

    Worker-fleet transcripts and private model reasoning never ride this part: every step is
    something the platform durably recorded — a model round beginning, a governed tool succeeding
    or being refused.
    """

    kind: PartKind = PartKind.AGENT_ACTIVITY
    title: str
    steps: tuple[ActivityStep, ...] = ()


class TaskCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(default=0, ge=0)
    queued: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    #: Finished and routed to a human — counted apart from ``partial`` (a shortfall) because it is
    #: the one terminal outcome that names a queue somebody can work.
    needs_review: int = Field(default=0, ge=0)
    blocked: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class TaskPart(_Part):
    """One detached research run as one visible task, projected from the run's durable rows."""

    kind: PartKind = PartKind.TASK
    state: TaskState
    title: str
    run_ref: dict[str, JsonValue]
    counts: TaskCounts = TaskCounts()
    exception_refs: tuple[dict[str, JsonValue], ...] = ()


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    status: ActivityStepStatus = ActivityStepStatus.PENDING


class PlanPart(_Part):
    """A plan/directive snapshot plus the durable ref and revision it projects (§3.4).

    It never dereferences a project-wide singleton: the ref names the exact durable object and the
    revision names the exact version this message showed.
    """

    kind: PartKind = PartKind.PLAN
    plan_ref: dict[str, JsonValue]
    revision_label: str | None = None
    title: str
    summary: str | None = None
    steps: tuple[PlanStep, ...] = ()
    status: str = "proposed"
    subject_refs: tuple[dict[str, JsonValue], ...] = ()


class GatePart(_Part):
    """The durable confirmation snapshot a ``Confirmation`` card renders (§3.4).

    D3 owns the *projection seam* only: it carries whatever the durable gate object says, and D4 —
    which builds ``agent_gate`` — is what fills the payload. A closed gate stays in history with
    its answer, which is why ``decision``/``answered_by``/``answered_at`` are part of the snapshot
    rather than a reason to delete the card.
    """

    kind: PartKind = PartKind.GATE
    gate_ref: dict[str, JsonValue]
    gate_kind: str
    state: str
    title: str | None = None
    summary: str | None = None
    subject_refs: tuple[dict[str, JsonValue], ...] = ()
    expected_subject_sha256: str | None = None
    amount_cents: int | None = None
    currency: str | None = None
    addressee_user_id: str | None = None
    permitted_decisions: tuple[str, ...] = ()
    decision: str | None = None
    answered_by_user_id: str | None = None
    answered_at: str | None = None


class ClarificationQuestion(BaseModel):
    """One question the design runtime asked before designing (its ``request_clarification``
    payload, field for field). ``default`` is what the runtime uses when the answer is skipped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    question: str
    why_it_matters: str = ""
    options: tuple[str, ...] = ()
    default: str
    allow_freeform: bool = True


class ClarificationPart(_Part):
    """Spec 2026-09-20 (clarification cards) §2.1: a document's opening-move questions.

    Emitted by the leg runner once per addressed document whose terminal run ended
    ``clarification_requested``. The card the client renders above the composer; on a turn that
    is no longer the latest it renders read-only. The durable record is the summary sentence on
    the turn's assistant message — this part is the live/replayed projection, like a gate's.
    """

    kind: PartKind = PartKind.CLARIFICATION
    document_id: str
    document_title: str
    doc_kind: str
    account_name: str | None = None
    run_id: str
    questions: tuple[ClarificationQuestion, ...]


class SourceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    title: str | None = None
    url: str | None = None
    source_kind: str | None = None
    evidence_ref: dict[str, JsonValue] | None = None


class SourcesPart(_Part):
    """Real message-scoped source items — never display-only "Used N sources" copy (§3.4)."""

    kind: PartKind = PartKind.SOURCES
    items: tuple[SourceItem, ...]


#: The union every emitter method accepts.
TurnPart = (
    ToolPart
    | ReasoningPart
    | AgentActivityPart
    | TaskPart
    | PlanPart
    | GatePart
    | SourcesPart
    | ClarificationPart
)


# --- part identity ------------------------------------------------------------------------------
#
# Every id derives from the durable thing the part projects, so a client's "which receipt is this?"
# is a lookup rather than a guess, and two attempts of one turn can never collide.


def assistant_message_id(turn_id: UUID) -> UUID:
    """The derived id of the turn's assistant message — the same derivation the engine appends
    ``agent_thread_message`` under, so a streamed part and the durable message agree."""

    return uuid5(turn_id, "assistant")


def text_part_id(*, generation_attempt_id: UUID, round_ordinal: int, call_index: int = 0) -> str:
    """The assistant-text part of one *finalize call* of one attempt.

    Scoped to the attempt because §3.3(6) forbids splicing two generations into one part, and to
    the round because a rejected ``finalize_turn`` is repaired by a *second* call whose text is a
    different continuation — the first one's part is reset, not extended.
    """

    return f"text:{generation_attempt_id}:{round_ordinal}:{call_index}"


def reasoning_part_id(*, generation_attempt_id: UUID, round_ordinal: int) -> str:
    return f"reasoning:{generation_attempt_id}:{round_ordinal}"


def activity_part_id(*, generation_attempt_id: UUID) -> str:
    return f"activity:{generation_attempt_id}"


def tool_part_id(*, node_key: str) -> str:
    """A governed tool call's part id, from the durable ``agent_plan_operation.node_key``.

    ``node_key`` — not the operation id — because the card must exist from the moment the plan is
    proposed, including for a plan that is *rejected* and therefore never produces an operation.
    """

    return f"tool:{node_key}"


def task_part_id(*, run_id: UUID) -> str:
    return f"task:{run_id}"


def plan_part_id(*, object_type: str, object_id: str) -> str:
    return f"plan:{object_type}:{object_id}"


def gate_part_id(*, object_type: str, object_id: str) -> str:
    return f"gate:{object_type}:{object_id}"


def sources_part_id(*, message_id: UUID) -> str:
    return f"sources:{message_id}"


def clarification_part_id(document_id: str) -> str:
    return f"clarification:{document_id}"


# --- projections from durable objects -------------------------------------------------------


def object_ref_wire(ref: object) -> dict[str, JsonValue]:
    """Normalize a :class:`~clue_agents.DomainObjectRef` (or an artifact ref) onto the wire.

    Duck-typed on purpose: this module must not import the agent contracts (it is consumed by the
    HTTP read surface, which stays free of the agent plane), and every ref shape the platform uses
    exposes the same three or four attributes.
    """

    payload: dict[str, JsonValue] = {}
    for name in ("workspace_id", "object_type", "object_id", "version", "artifact_key", "sha256"):
        value = getattr(ref, name, None)
        if value is not None:
            payload[name] = str(value) if not isinstance(value, int) else value
    return payload


def task_part_from_run(
    *,
    run_id: UUID,
    run_kind: str,
    state: str,
    counts: TaskCounts,
    revision: int = 1,
    workspace_id: str | None = None,
) -> TaskPart:
    """Project one ``entity_research_run`` (+ its job states) into one task card.

    The mapping is deliberately conservative: a run state the platform has not taught this surface
    about becomes ``queued`` rather than a guessed phase, because a wrong phase is a lie the UI
    animates.

    ``terminal`` is the one state that cannot be mapped from the run row alone — the run table
    records only *that* it ended — so it is resolved from the counts, which is where per-subject
    outcomes actually live. A run that ended with some subjects exhausted, routed to review or
    budget-stopped is ``partial``, never ``completed``: §3.4's whole reason for having a ``partial``
    state is that "finished" and "finished with everything asked of it" are different facts.
    """

    return TaskPart(
        part_id=task_part_id(run_id=run_id),
        revision=revision,
        state=_terminal_task_state(counts)
        if state == "terminal"
        else _TASK_STATES.get(state, TaskState.QUEUED),
        title=run_kind.replace("_", " "),
        run_ref={
            "object_type": "entity_research_run",
            "object_id": str(run_id),
            **({"workspace_id": workspace_id} if workspace_id is not None else {}),
        },
        counts=counts,
    )


#: ``entity_research_run.state`` → the §3.4 task vocabulary. The run table's closed vocabulary is
#: ``queued``/``running``/``waiting_external``/``terminal`` (migration ``022b1154b3aa``);
#: ``terminal`` is absent here because it is derived from the counts by
#: :func:`_terminal_task_state`. ``waiting_external`` is deep research *in flight* behind a provider
#: call — not a question for the human, which is what ``needs_input`` would claim.
_TASK_STATES: dict[str, TaskState] = {
    "queued": TaskState.QUEUED,
    "running": TaskState.DEEP_RESEARCH,
    "waiting_external": TaskState.DEEP_RESEARCH,
}


def _terminal_task_state(counts: TaskCounts) -> TaskState:
    """What an ended run actually achieved, read off its subjects' finalization outcomes.

    ``needs_review`` is counted apart from ``partial`` but reads the same here: a subject routed to
    review is a subject the run did not finish everything on, so the *state* is unchanged by the
    split — only the counts got more honest.
    """

    unfinished = counts.partial + counts.needs_review
    if counts.completed == 0 and unfinished == 0 and counts.failed > 0:
        return TaskState.FAILED
    if unfinished > 0 or counts.failed > 0:
        return TaskState.PARTIAL
    return TaskState.COMPLETED
