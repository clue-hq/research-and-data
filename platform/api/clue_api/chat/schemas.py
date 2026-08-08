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

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_projections import ThreadMessagePage, ThreadMessageSummary, ThreadView

__all__ = [
    "ArchiveThreadResponse",
    "CreateThreadRequest",
    "MessageListResponse",
    "PageMeta",
    "SubmitTurnRequest",
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


class SubmitTurnRequest(_Request):
    """``POST /api/v1/projects/:projectId/threads/:threadId/turns`` — ``{"message": "..."}``.

    Exactly one field today. Charter §3.5 gives this endpoint a second, **mutually exclusive** body
    — ``gate_response={gate_id, decision, expected_subject_sha256, expected_estimated_cost_cents}``
    — but that shape depends on the durable ``agent_gate`` substrate ratified in §6-D3, which is
    D4's to build. Accepting a placeholder for it now would mean shipping a field the server cannot
    honour, so the seam is named here and left unbuilt.

    What this body will never carry, on any slice: ``actor_id`` or ``action_ref`` (§3.5). Authority
    is ambient and server-derived — a client that could name its own actor could approve its own
    spend.
    """

    message: str = Field(min_length=1, max_length=32_000)

    @model_validator(mode="after")
    def message_is_not_blank(self) -> SubmitTurnRequest:
        """Whitespace is not a message.

        The length bound alone would let ``"   "`` through to the capture path, which refuses it —
        a 500 for what is plainly a bad request. Refusing here makes it the 422 it is.
        """

        if not self.message.strip():
            raise ValueError("message must contain something other than whitespace")
        return self


# --- responses ---------------------------------------------------------------------------------


def thread_href(*, project_id: str, thread_id: str) -> str:
    """The frontend route this thread lives at — the authored contract's ``href`` field."""

    return f"/projects/{project_id}?thread={thread_id}"


def thread_status(*, status: str) -> str:
    """The conversation status the sidebar renders.

    D0 knows only the thread's own lifecycle. ``archived`` is honest and outside the authored
    five-value vocabulary; ``idle`` is the authored value for "nothing is running". Deriving
    ``running``/``review``/``approval``/``needs-input`` needs the latest turn's status and the open
    gates, which D2 and D4 introduce — inventing them here would be a lie the UI would render.
    """

    return "archived" if status == "archived" else "idle"


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


def thread_wire(view: ThreadView) -> ThreadWire:
    return ThreadWire(
        id=view.thread_id,
        title=view.title,
        href=thread_href(project_id=view.project_id, thread_id=view.thread_id),
        status=thread_status(status=view.status),
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


def message_wire(item: ThreadMessageSummary, *, thread_id: str) -> ThreadMessageWire:
    return ThreadMessageWire(
        id=str(item.message_id),
        turn_id=str(item.turn_id),
        thread_id=thread_id,
        sequence=item.sequence,
        role=item.role,
        body_artifact_key=item.body_artifact_key,
        body_sha256=item.body_sha256,
        created_at=item.created_at.isoformat(),
        refs=tuple(ref.model_dump(mode="json") for ref in item.refs),
    )


def message_list_response(page: ThreadMessagePage, *, thread_id: str) -> MessageListResponse:
    return MessageListResponse(
        data=tuple(message_wire(item, thread_id=thread_id) for item in page.items),
        meta=PageMeta(next_cursor=page.next_cursor),
    )
