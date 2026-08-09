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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_api.agent_gate import money_text
from clue_api.chat.message_bodies import HydratedBody
from clue_projections import GateView, ThreadMessagePage, ThreadMessageSummary, ThreadView

__all__ = [
    "AgentProfileOptionWire",
    "ArchiveThreadResponse",
    "ComposerContextEntityWire",
    "ContextRefRequest",
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
    "ProjectBootstrapResponse",
    "ProjectBootstrapWire",
    "ProjectShellResponse",
    "ProjectShellWire",
    "SidebarProjectsResponse",
    "SubmitTurnRequest",
    "gate_response_message",
    "gate_wire",
    "ThreadListResponse",
    "ThreadMessageWire",
    "ThreadResponse",
    "ThreadWire",
    "TurnAcceptedResponse",
    "TurnAcceptedWire",
    "UpdateThreadRequest",
    "message_list_response",
    "message_wire",
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
    expected_estimated_cost_cents: Decimal = Field(ge=0)


class ContextRefRequest(_Request):
    """An ordered, workspace-scoped account/contact reference."""

    object_type: Literal["account", "contact"]
    object_id: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, gt=0)


class AttachmentRefRequest(_Request):
    """A durable upload receipt; browser-local URLs and paths have no field in this shape."""

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

    message: str | None = Field(default=None, min_length=1, max_length=32_000)
    gate_response: GateResponseRequest | None = None
    context_refs: tuple[ContextRefRequest, ...] = ()
    attachment_refs: tuple[AttachmentRefRequest, ...] = ()
    agent_profile_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def exactly_one_body(self) -> SubmitTurnRequest:
        """One act per turn, and whitespace is not a message.

        The length bound alone would let ``"   "`` through to the capture path, which refuses it —
        a 500 for what is plainly a bad request. Refusing here makes it the 422 it is.
        """

        if (self.message is None) == (self.gate_response is None):
            raise ValueError("supply exactly one of message or gate_response")
        if self.message is not None and not self.message.strip():
            raise ValueError("message must contain something other than whitespace")
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
    context_refs: tuple[ContextRefRequest, ...] = ()
    attachment_refs: tuple[AttachmentRefRequest, ...] = ()
    agent_profile_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def non_blank_message(self) -> HomeProjectRequest:
        if not self.message.strip():
            raise ValueError("message must contain something other than whitespace")
        return self


def gate_response_message(response: GateResponseRequest) -> str:
    """The canonical bytes a gate response is captured as.

    Deterministic (sorted keys, compact separators, one spelling of the amount) because these bytes
    *are* the turn's captured message: they back the artifact digest, the ``onboarding_input``
    record, and therefore the ``turn-action:`` receipt the confirmation is attributed to. A retried
    click must produce byte-identical capture or the idempotent replay would look like a different
    message under a used key.
    """

    return json.dumps(
        {
            "kind": "gate_response",
            "gate_id": response.gate_id,
            "decision": response.decision,
            "expected_subject_sha256": response.expected_subject_sha256,
            "expected_estimated_cost_cents": money_text(response.expected_estimated_cost_cents),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


# --- responses ---------------------------------------------------------------------------------


def thread_href(*, project_id: str, thread_id: str) -> str:
    """The frontend route this thread lives at — the authored contract's ``href`` field."""

    return f"/projects/{project_id}?thread={thread_id}"


def thread_status(
    *,
    status: str,
    open_gate_kinds: tuple[str, ...] = (),
    running: bool = False,
) -> str:
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


class ThreadWire(_Wire):
    """One thread, in the sidebar conversation shape plus the fields the shell genuinely owns."""

    id: str
    title: str | None
    href: str
    status: str
    pinned: bool
    project_id: str
    created_at: str
    updated_at: str


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
    #: ``body_unavailable_reason`` says why (``unavailable``/``digest_mismatch``/``not_text``/
    #: ``budget``) — an empty string would render as a message nobody wrote.
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
    id: str
    title: str
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
    brand_id: str
    product_id: str | None
    status: Literal["draft", "active", "paused", "archived"]
    created_at: str
    context_entities: tuple[ComposerContextEntityWire, ...] = ()
    agent_profiles: tuple[AgentProfileOptionWire, ...] = ()
    default_agent_profile_id: str | None = None
    composer_capabilities: HomeComposerCapabilitiesWire = Field(
        default_factory=HomeComposerCapabilitiesWire
    )
    artifacts: tuple[dict[str, Any], ...] = ()


class ProjectShellResponse(_Wire):
    data: ProjectShellWire


class SidebarConversationWire(_Wire):
    id: str
    title: str | None
    href: str
    status: Literal["idle", "running", "approval", "needs-input", "archived"]
    pinned: bool
    updated_at: str


class SidebarProjectWire(_Wire):
    id: str
    title: str
    href: str
    conversations: tuple[SidebarConversationWire, ...]


class SidebarPageMeta(_Wire):
    next_cursor: str | None = None


class SidebarProjectsResponse(_Wire):
    data: tuple[SidebarProjectWire, ...]
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
    max_spend_cents: str
    currency: str
    addressee_user_id: str
    created_at: str
    answer: GateAnswerWire | None
    launches: tuple[GateLaunchWire, ...]


class GateListResponse(_Wire):
    data: tuple[GateWire, ...]


def gate_wire(view: GateView) -> GateWire:
    """One thread gate on the wire."""

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
        max_spend_cents=money_text(view.max_spend_cents),
        currency=view.currency,
        addressee_user_id=view.addressee_user_id,
        created_at=view.created_at.isoformat(),
        answer=(
            None
            if view.answer is None
            else GateAnswerWire(
                turn_id=view.answer.turn_id,
                action_ref=view.answer.action_ref,
                decision=view.answer.decision,
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
    )


def thread_wire(
    view: ThreadView,
    *,
    open_gate_kinds: tuple[str, ...] = (),
    running: bool = False,
) -> ThreadWire:
    """One thread on the wire.

    Both derivation inputs default to "nothing known" so a caller that has read neither the gates
    nor the submissions-union gets the honest ``idle``/``archived`` answer rather than a guess:
    ``open_gate_kinds`` from :func:`~clue_projections.open_gate_kinds_for_threads` (D4) and
    ``running`` from :func:`~clue_projections.threads_running` (D3).
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
    )


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
) -> ThreadMessageWire:
    """One message on the wire; ``body`` is present only on the D3 hydrated cold-load read.

    Body-free stays the default (D0's decision): a listing carries the content *address*, and the
    words are fetched deliberately. ``body_unavailable_reason`` exists so a hydrated page can be
    honest about a body it could not serve — erased, too large, not text — instead of returning an
    empty string that renders as a message the user never sent.
    """

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
        refs=tuple(ref.model_dump(mode="json") for ref in item.refs),
    )


def message_list_response(
    page: ThreadMessagePage,
    *,
    thread_id: str,
    bodies: Mapping[str, HydratedBody] | None = None,
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
            )
            for item in page.items
            for hydrated in ((None if bodies is None else bodies.get(item.body_artifact_key)),)
        ),
        meta=PageMeta(next_cursor=page.next_cursor),
    )
