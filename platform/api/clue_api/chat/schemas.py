"""Wire shapes for the chat surface (FI Lane D D0).

These mirror the frontend's authored thread contract
(``apps/frontend/docs/api-contracts/projects.md``) exactly where the backend can honour it — the
``{data: …}`` envelope, the sidebar conversation shape (``id``/``title``/``href``/``status``), the
``{error: {code, message, requestId}}`` envelope FI-1 fixed — and diverges only where the authored
proposal cannot be served truthfully. Every divergence is recorded in the D0 report for founder
review; this file does not edit that document.

The two substantive shape decisions:

* **``status`` is derived, never stored.** The authored contract's conversation status vocabulary
  is ``idle | running | review | approval | needs-input``, which is a statement about the *latest
  turn*, not about the thread row. D0 has no turn execution yet, so this surface serves ``idle``
  for an active thread and ``archived`` for an archived one, and the real derivation (latest turn
  status + open gates) lands with D2/D4. It is computed in one function here so there is one place
  to change when it does.
* **Message summaries are body-free.** The transcript's bodies are content-addressed artifacts
  behind a separate permissioned read; a message summary carries the address and the typed
  ``refs[]``, not the text.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from clue_api.agent_gate import money_text
from clue_api.chat.message_bodies import HydratedBody
from clue_api.chat.turn_parts import TaskCounts, TaskState, task_part_from_run
from clue_api.turn_action import TurnActionUnresolvable, parse_turn_action_ref
from clue_projections import (
    GateView,
    ThreadMessagePage,
    ThreadMessageSummary,
    ThreadResearchTaskView,
    ThreadView,
)

if TYPE_CHECKING:
    from clue_api.arv2.discovery_store import DiscoveryRunRow

__all__ = [
    "AgentProfileOptionWire",
    "ArchiveThreadResponse",
    "ComposerContextEntityWire",
    "CrmWriteAnswer",
    "ContextRefRequest",
    "CreateBlankProjectRequest",
    "CreateThreadRequest",
    "HomeProjectRequest",
    "HomeComposerCapabilitiesWire",
    "HomeResponse",
    "HomeWire",
    "GateAnswerWire",
    "GateLaunchWire",
    "GateListResponse",
    "GateResponseRequest",
    "GateWire",
    "MessageListResponse",
    "PageMeta",
    "PrepareComposerContextRequest",
    "PreparedComposerContextResponse",
    "PreparedComposerContextWire",
    "ResearchTaskFieldProgressWire",
    "ResearchTaskListResponse",
    "ResearchTaskWire",
    "research_task_wire",
    "ProjectActivityWire",
    "ProjectBootstrapResponse",
    "ProjectBootstrapWire",
    "ProjectDirectoryItemResponse",
    "ProjectDirectoryItemWire",
    "ProjectDirectoryResponse",
    "ProjectShellResponse",
    "ProjectShellWire",
    "SetProjectArchivedRequest",
    "SidebarProjectsResponse",
    "SubmitTurnRequest",
    "UpdateProjectRequest",
    "gate_response_message",
    "gate_wire",
    "ThreadDiscoveryWire",
    "ThreadListResponse",
    "ThreadMessageWire",
    "ThreadResponse",
    "ThreadWire",
    "TurnAcceptedResponse",
    "TurnAcceptedWire",
    "UpdateThreadRequest",
    "message_list_response",
    "message_wire",
    "thread_discovery_wire",
    "thread_href",
    "thread_status",
    "thread_wire",
    "thread_wire_from_references",
]


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Request(BaseModel):
    """Request bodies forbid unknown keys: a typo'd field is a loud 422, never a silent no-op."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- requests ----------------------------------------------------------------------------------


class CreateThreadRequest(_Request):
    """``POST /api/v1/projects/:projectId/threads`` — ``{"title": "New chat"}``.

    ``title`` is optional: the authored contract always sends one, but a thread opened by a
    composer submission has no name until the conversation earns it, and an empty string is not a
    name (the durable CHECK refuses blank titles).
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)


class UpdateProjectRequest(_Request):
    """At least one field; ``title`` alone is the sidebar rename, ``pinned`` alone is the pin
    toggle."""

    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    pinned: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> UpdateProjectRequest:
        if self.title is None and self.description is None and self.pinned is None:
            raise ValueError("at least one of title, description, pinned is required")
        return self


class CreateBlankProjectRequest(_Request):
    brand_id: str = Field(min_length=1, max_length=255)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(max_length=2000)] = ""


class SetProjectArchivedRequest(_Request):
    archived: bool


class RenameProjectWire(_Wire):
    id: str
    title: str


class RenameProjectResponse(_Wire):
    data: RenameProjectWire


class UpdateThreadRequest(_Request):
    """``PATCH /api/v1/projects/:projectId/threads/:threadId`` — rename and/or pin.

    Mirrors the authored project-level ``PATCH`` semantics ("both fields are optional, but at least
    one must be present"), applied to a *thread* — see the report's contract-deviation list.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> UpdateThreadRequest:
        if self.title is None and self.pinned is None:
            raise ValueError("supply at least one of title or pinned")
        return self


class CrmWriteAnswer(_Request):
    """The person's choices on a CRM write permission card (CRM integration Phase 2, card §3 A).

    ``selected_write_ids`` are the ticked changes of the card; ``always_allow`` the standing
    permissions (scope keys the card offered) to grant from now on. Both are choices only: the
    server proves every id belongs to the proposal and every scope was offered by the card.
    """

    selected_write_ids: list[UUID] = Field(default_factory=list, max_length=1_000)
    always_allow: list[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=100
    )


class GateResponseRequest(_Request):
    """A structured answer to one durable ``agent_gate`` (charter §3.5, §3-P5(c)).

    The two ``expected_*`` fields are the client's statement of *what it was looking at* when the
    user clicked, and the server refuses the answer unless they match the immutable gate. That is
    what makes "approve" mean the thing on the screen: a directive redrafted since the card was
    rendered, or a maximum spend recomputed since, cannot be silently approved.

    Note what is absent and always will be: any way to name the actor, the action, the addressee, or
    the amount to *use*. The client says which amount it believes it saw; the server spends the
    amount it stored.
    """

    gate_id: str = Field(min_length=1, max_length=64)
    decision: Literal["approved", "rejected", "revised"]
    expected_subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_estimated_cost_cents: Decimal | None = Field(default=None, ge=0)
    revision_request: str | None = Field(default=None, min_length=1, max_length=4_000)
    # Present only for a product-selection gate.  It is a human choice, never an authority
    # coordinate: the server proves it is a member of the gate's immutable candidate snapshot and
    # then invokes the human-only confirmation tool with ambient workspace/project authority.
    selected_product_id: str | None = Field(default=None, min_length=1, max_length=200)
    # Present only for a product-**set** selection gate (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.3,
    # ruling P1: a project targets a set). Same posture as the single choice above — the server
    # proves every id is a member of the gate's immutable candidate snapshot and confirms the set
    # itself with ambient workspace/project authority.
    selected_product_ids: (
        list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] | None
    ) = Field(default=None, min_length=1, max_length=200)
    # Present only for a CRM write permission card: the ticked changes and the "Always allow"
    # choices. The server proves each against the proposal and the card it showed.
    crm_write: CrmWriteAnswer | None = None

    @model_validator(mode="after")
    def one_bounded_auxiliary_answer(self) -> GateResponseRequest:
        supplied = [
            name
            for name, value in (
                ("revision_request", self.revision_request),
                ("selected_product_id", self.selected_product_id),
                ("selected_product_ids", self.selected_product_ids),
                ("crm_write", self.crm_write),
            )
            if value is not None
        ]
        if len(supplied) > 1:
            raise ValueError(
                "revision_request, selected_product_id, selected_product_ids and crm_write are "
                "mutually exclusive"
            )
        return self


class ContextRefRequest(_Request):
    """An ordered, workspace-scoped domain-object reference.

    ``design_document`` (P3.1) pins the open leg's document, or — with no nodes beside it — is a
    plain mention of a microsite or ad from the Gallery. ``design_node`` is the ordered,
    per-message selection inside that exact document scene. ``design_asset`` identifies one ready
    image in the design asset library for reference conditioning. ``project_document`` is a
    Gallery file (a row of ``brand_knowledge_document`` with a project), always version-pinned.

    ``note`` is the marketer's own words about *this* ref — the annotation written onto one
    element in the web editor ("1. Make this shorter"). It rides the ref rather than the message
    so the instruction stays bound to the thing it is about; optional, because most refs are a
    plain selection.
    """

    object_type: Literal[
        "account", "contact", "design_document", "design_node", "design_asset", "project_document"
    ]
    object_id: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=2_000)


MAX_CONTEXT_REFS_PER_TURN = 100


class PrepareComposerContextRequest(_Request):
    """Resolve an exact unsent Account/Contact set for one project composer."""

    thread_id: str | None = Field(default=None, min_length=1, max_length=200)
    context_refs: tuple[ContextRefRequest, ...] = Field(
        min_length=1,
        max_length=MAX_CONTEXT_REFS_PER_TURN,
    )


class AttachmentRefRequest(_Request):
    """A durable upload receipt; browser-local URLs and paths have no field in this shape."""

    upload_id: UUID
    artifact_key: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1, max_length=255)
    byte_count: int = Field(ge=0)
    filename: str = Field(min_length=1, max_length=255)


class SubmitTurnRequest(_Request):
    """``POST /api/v1/projects/:projectId/threads/:threadId/turns``.

    Exactly one of two bodies (charter §3.5): an ordinary ``{"message": "..."}``, or the structured
    ``{"gate_response": {...}}`` D4 added. Mutually exclusive rather than merged, because they are
    different acts: one is something the user said, the other is a decision about a specific durable
    object, and a body that could be read as either would make "did the user approve?" a parsing
    question.

    Both are captured the same way, though — a gate response is serialized to canonical bytes
    (:func:`gate_response_message`) and captured as *the turn's message*, so capture-before-effect
    holds identically and the transcript shows what was decided rather than a gap where a click was.

    What this body will never carry, on any slice: ``actor_id`` or ``action_ref`` (§3.5). Authority
    is ambient and server-derived — a client that could name its own actor could approve its own
    spend.
    """

    message: str | None = Field(default=None, max_length=32_000)
    gate_response: GateResponseRequest | None = None
    context_refs: tuple[ContextRefRequest, ...] = Field(
        default=(), max_length=MAX_CONTEXT_REFS_PER_TURN
    )
    attachment_refs: tuple[AttachmentRefRequest, ...] = ()
    agent_profile_id: str | None = Field(default=None, min_length=1, max_length=200)
    # P3.1 (PD-part3 delta 5): the design turn contract's one-clarification-round echo —
    # the PREVIOUS design turn's outcome on this thread's open leg, echoed back by the
    # client. 'clarification_requested' is the only value with routing meaning (the
    # design runtime withholds request_clarification for that turn). Ignored on
    # non-design turns; senders arrive with Part IV's surface.
    previous_turn_outcome: Literal["clarification_requested"] | None = None

    @model_validator(mode="after")
    def exactly_one_body(self) -> SubmitTurnRequest:
        """One act per turn, and whitespace is not a message.

        The length bound alone would let ``"   "`` through to the capture path, which refuses it —
        a 500 for what is plainly a bad request. Refusing here makes it the 422 it is.
        """

        if (self.message is None) == (self.gate_response is None):
            raise ValueError("supply exactly one of message or gate_response")
        if self.message is not None and not self.message.strip() and not self.context_refs:
            raise ValueError(
                "message must contain something other than whitespace unless context references "
                "are supplied"
            )
        if self.gate_response is not None and (
            self.context_refs or self.attachment_refs or self.agent_profile_id is not None
        ):
            raise ValueError(
                "context_refs, attachment_refs, and agent_profile_id require an ordinary message"
            )
        return self


class HomeProjectRequest(_Request):
    """The one atomic Home act: create a project and accept its first human turn."""

    brand_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=32_000)
    context_refs: tuple[ContextRefRequest, ...] = Field(
        default=(), max_length=MAX_CONTEXT_REFS_PER_TURN
    )
    attachment_refs: tuple[AttachmentRefRequest, ...] = ()
    agent_profile_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def non_blank_message(self) -> HomeProjectRequest:
        if not self.message.strip():
            raise ValueError("message must contain something other than whitespace")
        return self


def gate_response_message(
    response: GateResponseRequest, *, crm_write_summary: str | None = None
) -> str:
    """The canonical bytes a gate response is captured as.

    Deterministic (sorted keys, compact separators, one spelling of the amount) because these bytes
    *are* the turn's captured message: they back the artifact digest, the ``onboarding_input``
    record, and therefore the ``turn-action:`` receipt the confirmation is attributed to. A retried
    click must produce byte-identical capture or the idempotent replay would look like a different
    message under a used key.
    """

    payload: dict[str, Any] = {
        "kind": "gate_response",
        "gate_id": response.gate_id,
        "decision": response.decision,
        "expected_subject_sha256": response.expected_subject_sha256,
        "expected_estimated_cost_cents": (
            None
            if response.expected_estimated_cost_cents is None
            else money_text(response.expected_estimated_cost_cents)
        ),
    }
    if response.revision_request is not None:
        payload["revision_request"] = response.revision_request
    # Preserve byte-for-byte compatibility for historical directive answers: an absent optional
    # product choice adds no new null member to their canonical transcript record.
    if response.selected_product_id is not None:
        payload["selected_product_id"] = response.selected_product_id
    # Same rule for the set-valued answer: the member order is the order the human chose in, so it
    # is captured as sent rather than sorted.
    if response.selected_product_ids is not None:
        payload["selected_product_ids"] = list(response.selected_product_ids)
    # A CRM write card answer: the choices, de-duplicated in the order made, and one sentence the
    # agent reads ("Allowed 60 of 61 changes; always allow adding contacts to Clue lists."). The
    # sentence is derived from the immutable card, so a retried click captures the same bytes.
    if crm_write_summary is not None:
        chosen = response.crm_write or CrmWriteAnswer()
        payload["crm_write"] = {
            "selected_write_ids": list(dict.fromkeys(str(i) for i in chosen.selected_write_ids)),
            "always_allow": list(dict.fromkeys(chosen.always_allow)),
            "summary": crm_write_summary,
        }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


# --- responses ---------------------------------------------------------------------------------


def thread_href(*, project_id: str, thread_id: str) -> str:
    """The frontend route this thread lives at — the authored contract's ``href`` field.

    Phase R (founder rulings R1/R2, 2026-08-17): the canonical shape is the
    explicit chats path; the legacy ``?thread=`` query form survives only as a
    frontend redirect absorber and must not be emitted.
    """

    return f"/projects/{project_id}/chats/{thread_id}"


#: The derived conversation-status vocabulary, single-sourced: :func:`thread_status` is the one
#: producer, and every wire field that carries it annotates with this alias.
ConversationStatus = Literal["idle", "running", "approval", "needs-input", "archived"]


def thread_status(
    *,
    status: str,
    open_gate_kinds: tuple[str, ...] = (),
    running: bool = False,
) -> ConversationStatus:
    """The conversation status the sidebar renders.

    Derived, never stored — the one place the authored five-value vocabulary
    (``idle | running | review | approval | needs-input``) is produced, plus the honest sixth,
    ``archived``, which is outside it because a thread really can be closed.

    D4 supplies the gate half: an unanswered ``directive_confirmation`` is an **approval** the user
    owes, and any other unanswered gate kind is generic ``needs-input``. Both are computed from the
    absence of an answer record (ratified §6-D3), so a badge can never claim a decision is pending
    after it was made. ``open_gate_kinds`` defaults to empty so a caller that has not read the gates
    — every non-listing caller today — keeps its previous answer rather than guessing.

    ``running`` (the latest turn still executing) is D3's half of this same derivation and lands
    alongside; the two are independent inputs to one function on purpose, so the two vocabularies
    the charter complains never meet (§2) meet exactly here.

    D3 supplies ``running`` from the **submissions-union**: a thread is running when it holds a
    submission that has neither reached a terminal turn event nor a terminal fleet task. That union
    is what makes a *queued* turn visible at all — the two-phase turn identity ratified after D2
    means a turn that has not started executing exists only as a submission row, so a status
    derived from ``agent_turn`` alone would report a thread with three turns waiting as ``idle``.

    An open gate outranks ``running``: a gate is something the *user* must do, and a badge that
    says "running" while the conversation is actually blocked on them is the one wrong answer here.
    """

    if status == "archived":
        return "archived"
    if "directive_confirmation" in open_gate_kinds:
        return "approval"
    if open_gate_kinds:
        return "needs-input"
    if running:
        return "running"
    return "idle"


class ThreadSpeakerWire(_Wire):
    """Who owns the thread right now (P3.4's speaker-state projection, PD-part3 §1-D1).

    ``design`` while the thread holds an open design leg — every message goes straight to the
    design deepagent until the leg closes; ``head_of_abm`` otherwise. Part IV renders the chip;
    this is the data it reads.
    """

    role: Literal["head_of_abm", "design"]
    design_leg_id: str | None = None
    design_leg_state: Literal["open_awaiting_user", "running"] | None = None


class ThreadDiscoveryWire(_Wire):
    """The account discovery holding this thread (spec 2026-09-30 §5, §7).

    A thread whose discovery run is unreleased is busy: a message sent to it is held until the
    run's wake turn finishes. ``stoppable`` is ``True`` while the run is still searching — the
    composer's Stop then calls the discovery stop route — and ``False`` once it has ended and only
    its wake turn is pending. The brief the agent wrote is internal and never rides this wire.
    """

    run_id: str
    stoppable: bool


class ThreadWire(_Wire):
    """One thread, in the sidebar conversation shape plus the fields the shell genuinely owns."""

    id: str
    title: str | None
    href: str
    status: ConversationStatus
    pinned: bool
    project_id: str
    created_at: str
    updated_at: str
    #: ``None`` on reads that did not derive it (the tool-reference projections after a
    #: create/rename); the listing always derives it. Absent knowledge is never a guess.
    speaker: ThreadSpeakerWire | None = None
    #: The discovery holding this thread, or ``None`` when none does (and on reads that did not
    #: derive it — the tool-reference projections after a create/rename).
    discovery: ThreadDiscoveryWire | None = None


class ThreadMessageWire(_Wire):
    """One durable message, body-free, with REQ-21's typed object refs."""

    id: str
    turn_id: str
    thread_id: str
    sequence: int
    role: str
    body_artifact_key: str
    body_sha256: str
    #: Present only on the D3 hydrated cold-load read (``…/messages/bodies``); ``None`` on the
    #: body-free listing. When a hydrated page could not serve a body, ``body`` stays ``None`` and
    #: ``body_unavailable_reason`` says why (``unavailable``/``artifact_missing``/
    #: ``digest_mismatch``/``not_text``/``budget``) — an empty string would render as a message
    #: nobody wrote.
    body: str | None = None
    body_unavailable_reason: str | None = None
    created_at: str
    refs: tuple[dict[str, Any], ...]


class PageMeta(_Wire):
    next_cursor: str | None = None


class ThreadResponse(_Wire):
    """``{data: <thread>}`` — the single-thread envelope create/rename/pin return."""

    data: ThreadWire


class ArchiveThreadResponse(_Wire):
    data: ThreadWire


class ThreadListResponse(_Wire):
    data: tuple[ThreadWire, ...]
    meta: PageMeta


class MessageListResponse(_Wire):
    data: tuple[ThreadMessageWire, ...]
    meta: PageMeta


class TurnAcceptedWire(_Wire):
    """What a ``202`` says: the turn is durable and queued, not that it has run.

    ``replayed`` is ``True`` when this exact idempotency identity had already been accepted — the
    duplicate-submission case, which returns the *same* ``turn_id`` and enqueues nothing new. It is
    reported rather than hidden so a client can tell "your retry landed" from "a second turn".
    """

    turn_id: str
    thread_id: str
    requested_at: str
    replayed: bool
    #: Accept-time visibility (P3.4): which agent this message will reach — ``design`` when the
    #: thread holds an open design leg, else ``head_of_abm``. Derived in the accept transaction,
    #: so the composer can label the pending turn without a second read.
    routed_to: Literal["head_of_abm", "design"] = "head_of_abm"
    #: R-11.6: ``none`` when the submission is recorded and no turn will run for it (the answer
    #: to a CRM write card). The client then attaches no turn stream and shows nothing in flight.
    agent_reply: Literal["expected", "none"] = "expected"


class TurnAcceptedResponse(_Wire):
    data: TurnAcceptedWire


class HomeBrandWire(_Wire):
    id: str
    name: str


class ComposerContextEntityWire(_Wire):
    object_type: Literal["account", "contact"]
    object_id: str
    label: str
    secondary_label: str
    image_url: str | None = None
    version: int | None = None
    # A contact's account (id + name), so the picker can nest it and search can name it.
    account_id: str | None = None
    account_name: str | None = None


class MentionDirectoryWire(_Wire):
    """Every account and committee contact the @ tagger may offer (2026-10-05)."""

    entities: tuple[ComposerContextEntityWire, ...]
    #: ``False`` when the workspace exceeded the size threshold and the list was cut; the
    #: composer then also asks ``/mention-directory/search`` as the user types.
    complete: bool


class MentionDirectoryResponse(_Wire):
    data: MentionDirectoryWire


class MentionSearchWire(_Wire):
    entities: tuple[ComposerContextEntityWire, ...]


class MentionSearchResponse(_Wire):
    data: MentionSearchWire


class PreparedComposerContextWire(_Wire):
    project_id: str
    thread_id: str | None
    context_entities: tuple[ComposerContextEntityWire, ...]


class PreparedComposerContextResponse(_Wire):
    data: PreparedComposerContextWire


class AgentProfileOptionWire(_Wire):
    id: str
    label: str
    short_label: str
    description: str
    model_id: str


class HomeComposerCapabilitiesWire(_Wire):
    context_refs: bool = False
    attachments: bool = False
    agent_profile_selection: bool = False


class HomeWire(_Wire):
    brands: tuple[HomeBrandWire, ...]
    default_brand_id: str | None
    context_entities: tuple[ComposerContextEntityWire, ...] = ()
    agent_profiles: tuple[AgentProfileOptionWire, ...] = ()
    default_agent_profile_id: str | None = None
    composer_capabilities: HomeComposerCapabilitiesWire = Field(
        default_factory=HomeComposerCapabilitiesWire
    )
    suggestions: tuple[str, ...] = ()


class HomeResponse(_Wire):
    data: HomeWire


class ProjectBootstrapProjectWire(_Wire):
    id: str
    title: str
    brand_id: str
    href: str
    created_at: str


class ProjectBootstrapThreadWire(_Wire):
    """The thread the Home composer just opened.

    ``title`` is ``None`` until the conversation namer titles it after the first completed turn
    (spec 2026-09-18-conversation-naming-design §4.7); the client shows its New chat label.
    """

    id: str
    title: str | None
    href: str
    status: Literal["running"] = "running"
    pinned: bool = False
    project_id: str
    created_at: str
    updated_at: str


class ProjectBootstrapWire(_Wire):
    project: ProjectBootstrapProjectWire
    thread: ProjectBootstrapThreadWire
    turn: TurnAcceptedWire
    href: str


class ProjectBootstrapResponse(_Wire):
    data: ProjectBootstrapWire


class ProjectShellWire(_Wire):
    id: str
    title: str
    description: str = ""
    brand_id: str
    product_id: str | None
    status: Literal["draft", "active", "paused", "archived"]
    pinned: bool = False
    created_at: str
    updated_at: str | None = None
    archived_at: str | None = None
    context_entities: tuple[ComposerContextEntityWire, ...] = ()
    agent_profiles: tuple[AgentProfileOptionWire, ...] = ()
    default_agent_profile_id: str | None = None
    composer_capabilities: HomeComposerCapabilitiesWire = Field(
        default_factory=HomeComposerCapabilitiesWire
    )
    artifacts: tuple[dict[str, Any], ...] = ()


class ProjectShellResponse(_Wire):
    data: ProjectShellWire


class DesignArtifactWire(_Wire):
    """W1.3 artifact→design-document read seam (v1: ``document_id == id``).

    Design documents are not yet registered as platform artifacts (the Gallery
    integration is future work), so the v1 seam resolves the artifact id AS the
    design-document id behind this typed shape — the URL contract survives the
    later linkage unchanged. Cross-PROJECT containment is not yet provable
    (the document row carries a workspace, not a project); workspace scoping is
    enforced, and the project/document linkage (leg-derived or an artifact
    registry) is the recorded follow-up.
    """

    id: str
    project_id: str
    document_id: str
    kind: Literal["web", "ad", "site"]
    title: str
    status: str
    current_version_id: str


class DesignArtifactResponse(_Wire):
    data: DesignArtifactWire


class DesignArtifactAccountWire(_Wire):
    """The account a listed artifact was made for — the artifacts page's own shape.

    Spec 2026-09-19 §3.8: the document records the account, so the gallery feed carries it
    rather than leaving the client to guess. The gallery card's designed component has no
    account slot yet, so the field rides the wire and stays invisible until one is designed
    (the dummy-frontend rule: no invented chrome). Absent when the document names no
    account — a card then states nothing.
    """

    id: str
    name: str
    domain: str | None = None
    account_entity_id: str | None = None
    #: Brandfetch's Logo API mark for the account's domain (founder, 2026-09-20 — the
    #: accounts screens' own rule), or ``None`` without a domain or a configured client id.
    logo_path: str | None = None


class DesignArtifactListItemWire(DesignArtifactWire):
    """One gallery row: the W1.3 item shape plus what a *listed* artifact needs.

    The list is **leg-derived** (v1 ruling 1): a document belongs to the project whose
    threads hold the design legs that name it, so every listed document carries the
    thread it came from. ``origin_thread_id`` is the thread of the document's latest
    leg — a document worked on from two threads reports the most recent one, not all
    of them; the gallery uses it to link a card back to its conversation.

    Since spec 2026-09-19 §3.2 a leg names a SET of documents, so one leg contributes one
    item per artboard it opened, each reporting that leg's thread.
    """

    created_at: str
    updated_at: str
    origin_thread_id: str
    # G-H: the card's own facts, carried from the document rather than guessed
    # by the client. Both are absent when the document does not record them —
    # a card then states nothing instead of inventing a channel or a size.
    artifact_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    account: DesignArtifactAccountWire | None = None


class DesignArtifactListResponse(_Wire):
    data: tuple[DesignArtifactListItemWire, ...]


class SidebarConversationWire(_Wire):
    id: str
    title: str | None
    href: str
    status: ConversationStatus
    pinned: bool
    updated_at: str


class SidebarProjectWire(_Wire):
    id: str
    title: str
    href: str
    pinned: bool
    updated_at: str
    conversations: tuple[SidebarConversationWire, ...]


class SidebarPageMeta(_Wire):
    next_cursor: str | None = None


class SidebarProjectsResponse(_Wire):
    data: tuple[SidebarProjectWire, ...]
    meta: SidebarPageMeta


# --- the projects directory (spec 2026-09-19 §2.3) -----------------------------------------------


class ProjectActivityWire(_Wire):
    """What the directory card says about a project's conversations — counted, never guessed."""

    chats: int
    running: int
    needs_input: int


class ProjectDirectoryItemWire(_Wire):
    id: str
    title: str
    description: str
    href: str
    status: Literal["active", "archived"]
    pinned: bool
    brand_id: str
    product_id: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    activity: ProjectActivityWire


class ProjectDirectoryItemResponse(_Wire):
    data: ProjectDirectoryItemWire


class ProjectDirectoryResponse(_Wire):
    data: tuple[ProjectDirectoryItemWire, ...]
    meta: SidebarPageMeta


# --- the durable gate read (FI Lane D D5-close) --------------------------------------------------
#
# One wire member per :class:`~clue_projections.gates.GateView` member, same spelling, same
# nesting. The read is a *faithful* projection of a join that already exists — deliberately not a
# second, prettier contract — because the approval card's whole job is to echo back exactly what
# the immutable row says, and any reshaping here would be a place for the two to drift.


class GateAnswerWire(_Wire):
    """How a gate was answered, if it was. Absent (``null``) is what "open" means (§6-D3)."""

    turn_id: str
    action_ref: str
    decision: str
    expected_subject_sha256: str
    decision_payload: dict[str, Any]
    selected_option_ref: str | None
    answered_by_user_id: str
    answered_at: str


class GateLaunchWire(_Wire):
    """The research run an approved gate's confirming turn actually authorized."""

    research_run_id: str
    run_kind: str
    run_state: str
    source_action_ref: str
    approval_refs: tuple[str, ...]


class GateWire(_Wire):
    """One gate, its answer, and anything the answer launched.

    ``max_spend_cents`` crosses as its canonical **text** spelling rather than a JSON number: the
    column is ``numeric(20,4)``, an answer is refused unless its amount matches the stored one
    numerically, and a float round-trip is the one way a client could send back an amount it never
    saw. :func:`~clue_api.agent_gate.money_text` is the same function the digest and the captured
    request bytes use, so one amount has exactly one spelling everywhere.

    It is ``None`` — absent from the JSON — when FI pilot budget-controls are off: the amount stays
    on the immutable row, but no human surface may see it, and the answer route correspondingly
    stops requiring the echo (the ``expected_subject_sha256`` digest check, which is the
    load-bearing stale-approval guard, is untouched in both modes). ``None`` rather than ``"0"`` or
    ``""`` deliberately: a withheld amount must not be readable as a real one.
    """

    gate_id: str
    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: str
    kind: str
    subject_ref: str
    subject_revision: int | None
    expected_subject_sha256: str
    subject_snapshot: dict[str, Any]
    permitted_decisions: tuple[str, ...]
    max_spend_cents: str | None
    currency: str | None
    addressee_user_id: str
    created_at: str
    snapshot_erased_at: str | None
    snapshot_erasure_reason: str | None
    answer: GateAnswerWire | None
    launches: tuple[GateLaunchWire, ...]
    #: Unanswered and no longer answerable: a CRM write card a newer card replaced, or one a
    #: reconnect closed. Such a gate is not open and asks nothing of anyone.
    withdrawn: bool = False


class GateListResponse(_Wire):
    data: tuple[GateWire, ...]


def gate_wire(view: GateView, *, budget_controls_enabled: bool = True) -> GateWire:
    """One thread gate on the wire.

    ``budget_controls_enabled`` is ``Settings.budget_controls_enabled``; False withholds the amount
    (FI pilot budget-controls). Everything that makes the gate *answerable* — the id, the subject
    ref, its digest, the addressee — crosses in both modes."""

    return GateWire(
        gate_id=view.gate_id,
        workspace_id=view.workspace_id,
        project_id=view.project_id,
        thread_id=view.thread_id,
        turn_id=view.turn_id,
        kind=view.kind,
        subject_ref=view.subject_ref,
        subject_revision=view.subject_revision,
        expected_subject_sha256=view.expected_subject_sha256,
        subject_snapshot=dict(view.subject_snapshot),
        permitted_decisions=view.permitted_decisions,
        max_spend_cents=(
            money_text(view.max_spend_cents)
            if budget_controls_enabled and view.max_spend_cents is not None
            else None
        ),
        currency=view.currency,
        addressee_user_id=view.addressee_user_id,
        created_at=view.created_at.isoformat(),
        snapshot_erased_at=(
            None if view.snapshot_erased_at is None else view.snapshot_erased_at.isoformat()
        ),
        snapshot_erasure_reason=view.snapshot_erasure_reason,
        answer=(
            None
            if view.answer is None
            else GateAnswerWire(
                turn_id=view.answer.turn_id,
                action_ref=view.answer.action_ref,
                decision=view.answer.decision,
                expected_subject_sha256=view.answer.expected_subject_sha256,
                decision_payload=dict(view.answer.decision_payload),
                selected_option_ref=view.answer.selected_option_ref,
                answered_by_user_id=view.answer.answered_by_user_id,
                answered_at=view.answer.answered_at.isoformat(),
            )
        ),
        launches=tuple(
            GateLaunchWire(
                research_run_id=launch.research_run_id,
                run_kind=launch.run_kind,
                run_state=launch.run_state,
                source_action_ref=launch.source_action_ref,
                approval_refs=launch.approval_refs,
            )
            for launch in view.launches
        ),
        withdrawn=view.withdrawn,
    )


class ResearchTaskFieldProgressWire(_Wire):
    """Fields landed vs. fields honestly given up on, across a run's settled subjects."""

    completed: int = Field(ge=0)
    unresolved: int = Field(ge=0)


class ResearchTaskWire(_Wire):
    """One pollable research task — the stream's ``task`` part, plus what a poller needs.

    Deliberately *not* a new shape. ``part_id``/``kind``/``state``/``title``/``run_ref``/``counts``
    are produced by :func:`~clue_api.chat.turn_parts.task_part_from_run`, the same function the
    turn-close emitter uses, so a polled task and a streamed one merge as the same card in the
    transcript reducer rather than as two cards that happen to look alike.

    Three members the stream frame has no use for: ``revision``, the job-event high-water mark the
    reducer merges on; ``field_progress``, which is ``None`` until a job has published coverage
    and for a contact run (Slice F's surface) — never a fabricated zero; and ``source_turn_id``,
    the turn whose durable ``turn-action:`` receipt launched the run — a streamed part rides its
    own turn's frames, but a polled one must say which message re-materializes its card after a
    reload (C3's cold-load fix). ``None`` only for a launch receipt that is not a turn action.
    """

    part_id: str
    kind: Literal["task"] = "task"
    revision: int = Field(ge=1)
    state: TaskState
    title: str
    run_ref: dict[str, Any]
    counts: TaskCounts
    exception_refs: tuple[dict[str, Any], ...] = ()
    field_progress: ResearchTaskFieldProgressWire | None = None
    source_turn_id: str | None = None


class ResearchTaskListResponse(_Wire):
    """``{"tasks": [...]}`` — an empty list for a thread that launched nothing, never a 404."""

    tasks: tuple[ResearchTaskWire, ...]


def research_task_wire(view: ThreadResearchTaskView, *, workspace_id: str) -> ResearchTaskWire:
    """One polled task on the wire, built from the canonical task-part projection.

    The canonical typed part is projected once and copied member-for-member onto the polled shape:
    if ``TaskPart`` gains a member, this conversion is where the omission shows up, instead of the
    polled card quietly drifting from the streamed one.
    """

    part = task_part_from_run(
        run_id=UUID(view.task.research_run_id),
        run_kind=view.task.run_kind,
        state=view.task.run_state,
        counts=TaskCounts(**view.task.counts.model_dump()),
        workspace_id=workspace_id,
    )
    return ResearchTaskWire(
        part_id=part.part_id,
        kind="task",
        # The projected part's own revision is the ``1`` default; the durable ledger's high-water
        # mark replaces it here, which is the whole point of the poll.
        revision=view.revision,
        state=part.state,
        title=part.title,
        run_ref=part.run_ref,
        counts=part.counts,
        exception_refs=part.exception_refs,
        field_progress=(
            None
            if view.field_progress is None
            else ResearchTaskFieldProgressWire(
                completed=view.field_progress.completed,
                unresolved=view.field_progress.unresolved,
            )
        ),
        source_turn_id=_source_turn_id(view.task.source_action_ref),
    )


def _source_turn_id(source_action_ref: str) -> str | None:
    """The turn a launch receipt names, or ``None`` for a receipt that is not a turn action.

    The canonical parser is the authority (:func:`clue_api.turn_action.parse_turn_action_ref`);
    a ref it refuses yields an honest ``None`` rather than a hand-parsed guess.
    """

    try:
        return str(parse_turn_action_ref(source_action_ref))
    except TurnActionUnresolvable:
        return None


def thread_speaker_wire(design_leg: dict[str, Any] | None) -> ThreadSpeakerWire:
    """The speaker from one thread's open-leg row (or its absence)."""

    if design_leg is None:
        return ThreadSpeakerWire(role="head_of_abm")
    state = str(design_leg["state"])
    if state not in ("open_awaiting_user", "running"):  # pragma: no cover - closed is filtered
        return ThreadSpeakerWire(role="head_of_abm")
    return ThreadSpeakerWire(
        role="design",
        design_leg_id=str(design_leg["id"]),
        design_leg_state=state,  # type: ignore[arg-type]
    )


def thread_wire(
    view: ThreadView,
    *,
    open_gate_kinds: tuple[str, ...] = (),
    running: bool = False,
    speaker: ThreadSpeakerWire | None = None,
    discovery: ThreadDiscoveryWire | None = None,
) -> ThreadWire:
    """One thread on the wire.

    The derivation inputs default to "nothing known" so a caller that has read neither the gates
    nor the submissions-union gets the honest ``idle``/``archived`` answer rather than a guess:
    ``open_gate_kinds`` from :func:`~clue_projections.open_gate_kinds_for_threads` (D4),
    ``running`` from :func:`~clue_projections.threads_running` (D3), and ``speaker`` (P3.4) from
    :func:`~clue_api.design_leg_wiring.design_legs_for_threads` through
    :func:`thread_speaker_wire` — ``None`` means "not derived", never "head-of-abm". ``discovery``
    comes from :func:`~clue_api.arv2.discovery_store.active_discoveries_for_threads` through
    :func:`thread_discovery_wire`.
    """

    return ThreadWire(
        id=view.thread_id,
        title=view.title,
        href=thread_href(project_id=view.project_id, thread_id=view.thread_id),
        status=thread_status(
            status=view.status,
            open_gate_kinds=open_gate_kinds,
            running=running,
        ),
        pinned=view.pinned,
        project_id=view.project_id,
        created_at=view.created_at.isoformat(),
        updated_at=view.updated_at.isoformat(),
        speaker=speaker,
        discovery=discovery,
    )


def thread_discovery_wire(run: DiscoveryRunRow | None) -> ThreadDiscoveryWire | None:
    """The discovery a thread is held by, from its unreleased run — or ``None`` without one.

    Stop means something only while the run is searching: once it has an end reason the run is
    over and the thread waits only for the wake turn, which the turn's own Stop handles.
    """

    if run is None:
        return None
    return ThreadDiscoveryWire(run_id=str(run.run_id), stoppable=run.end_reason is None)


def thread_wire_from_references(references: dict[str, Any]) -> ThreadWire:
    """Build the wire shape from a thread tool's reference-only result.

    The tools return references rather than view models (Doc A), so the HTTP layer projects them
    here instead of issuing a second read — the tool already told us the committed state.
    """

    project_id = str(references["project_id"])
    thread_id = str(references["thread_id"])
    title = references["title"]
    return ThreadWire(
        id=thread_id,
        title=None if title is None else str(title),
        href=thread_href(project_id=project_id, thread_id=thread_id),
        status=thread_status(status=str(references["status"])),
        pinned=bool(references["pinned"]),
        project_id=project_id,
        created_at=str(references["created_at"]),
        updated_at=str(references["updated_at"]),
    )


def message_wire(
    item: ThreadMessageSummary,
    *,
    thread_id: str,
    body: str | None = None,
    body_unavailable_reason: str | None = None,
    ref_presentations: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> ThreadMessageWire:
    """One message on the wire; ``body`` is present only on the D3 hydrated cold-load read.

    Body-free stays the default (D0's decision): a listing carries the content *address*, and the
    words are fetched deliberately. ``body_unavailable_reason`` exists so a hydrated page can be
    honest about a body it could not serve — erased, too large, not text — instead of returning an
    empty string that renders as a message the user never sent.
    """

    refs: list[dict[str, Any]] = []
    for ref in item.refs:
        wire = ref.model_dump(mode="json")
        if ref_presentations is not None:
            wire.update(ref_presentations.get((ref.object_type, ref.object_id), {}))
        refs.append(wire)

    return ThreadMessageWire(
        id=str(item.message_id),
        turn_id=str(item.turn_id),
        thread_id=thread_id,
        sequence=item.sequence,
        role=item.role,
        body_artifact_key=item.body_artifact_key,
        body_sha256=item.body_sha256,
        body=body,
        body_unavailable_reason=body_unavailable_reason,
        created_at=item.created_at.isoformat(),
        refs=tuple(refs),
    )


def message_list_response(
    page: ThreadMessagePage,
    *,
    thread_id: str,
    bodies: Mapping[str, HydratedBody] | None = None,
    ref_presentations: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> MessageListResponse:
    """One page on the wire. ``bodies`` is supplied only by the ``?include=bodies`` opt-in.

    A message whose body was requested but could not be served keeps ``body=None`` and carries the
    reason, so "we did not ask for it" and "we asked and it is gone" stay distinguishable.
    """

    return MessageListResponse(
        data=tuple(
            message_wire(
                item,
                thread_id=thread_id,
                body=(None if hydrated is None else hydrated.body),
                body_unavailable_reason=(
                    None if hydrated is None or hydrated.body is not None else hydrated.reason
                ),
                ref_presentations=ref_presentations,
            )
            for item in page.items
            for hydrated in ((None if bodies is None else bodies.get(item.body_artifact_key)),)
        ),
        meta=PageMeta(next_cursor=page.next_cursor),
    )
