"""The closed typed object-ref vocabulary a thread message projects (REQ-21 / FI Lane D D0).

REQ-21's shell says a chat message carries typed ``refs[]`` so the surface can *open the thing the
message is about* — a tab, a gate card, a produced output — instead of parsing prose. This module
owns that vocabulary and nothing else, so there is exactly one place to read (and one place to
extend, under review) what a message may point at.

**Refs are a projection, never a store (Doc A §3a).** Every ref returned here is read back out of a
durable, append-only agent-plane receipt that already existed:

* :data:`MessageRefFlavor.ATTACHMENT` — an ``agent_artifact_ref`` with ``ref_role='attachment'``,
  the files the human sent with the turn.
* :data:`MessageRefFlavor.CONTEXT` — an ordered
  ``agent_turn_submission_context_ref`` row, the account/contact objects the human selected.
* :data:`MessageRefFlavor.OUTPUT` / :data:`MessageRefFlavor.OPEN_GATE` — an
  ``agent_finalization_domain_ref`` row (its ``ref_role`` CHECK is exactly ``output | open_gate``):
  the domain objects the turn produced, and the gate it is waiting on.
* :data:`MessageRefFlavor.NEXT_ACTION` / :data:`MessageRefFlavor.ASSUMPTION` /
  :data:`MessageRefFlavor.WORKSPACE_OUTPUT` — ``agent_artifact_ref`` rows carrying those exact
  ``ref_role`` values.

**Nothing here widens a closed vocabulary.** Each flavor is one existing ``ref_role`` value from
``agent_artifact_ref``/``agent_finalization_domain_ref``, so the durable CHECK constraints are the
authority and this enum is their projection. The *kind* of thing referenced stays in ``object_type``
(``artifact``, or whatever domain type the finalization recorded) — flavor answers "what is this
ref doing on this message", ``object_type`` answers "what is it".

**How a turn-scoped ref becomes a message-scoped ref.** The durable rows key on the turn, not on a
message — the agent plane has no part-level identity (charter §1.1). The attribution rule is
therefore fixed and mechanical, not inferred: a turn's *user* message carries the turn's
attachments; the turn's *assistant* message carries everything the turn produced or is waiting on.
``system``/``tool`` messages carry no refs today. That rule is stated here because it is a contract
D3's part projections must not silently re-invent.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ARTIFACT_OBJECT_TYPE",
    "ASSISTANT_MESSAGE_FLAVORS",
    "USER_MESSAGE_FLAVORS",
    "MessageObjectRef",
    "MessageRefFlavor",
    "flavors_for_message_role",
]

#: The ``object_type`` a content-addressed artifact ref projects under.
ARTIFACT_OBJECT_TYPE = "artifact"


class MessageRefFlavor(StrEnum):
    """What a ref is doing on the message — a closed set, mirroring the durable ``ref_role``s."""

    #: A file the human attached to the turn (``agent_artifact_ref.ref_role='attachment'``).
    ATTACHMENT = "attachment"
    #: An account/contact object the human explicitly selected for this turn.
    CONTEXT = "context"
    #: A domain object the turn produced (``agent_finalization_domain_ref.ref_role='output'``).
    OUTPUT = "output"
    #: The gate the turn is waiting on (``agent_finalization_domain_ref.ref_role='open_gate'``).
    #: D4 gives this a payload; at D0 it is the pointer the approval card will resolve.
    OPEN_GATE = "open_gate"
    #: A next step the turn recorded (``agent_artifact_ref.ref_role='next_action'``).
    NEXT_ACTION = "next_action"
    #: An assumption the turn recorded (``agent_artifact_ref.ref_role='assumption'``).
    ASSUMPTION = "assumption"
    #: A file the turn left in its agent workspace
    #: (``agent_artifact_ref.ref_role='workspace_output'``).
    WORKSPACE_OUTPUT = "workspace_output"


#: The flavors a ``user`` message may carry. A user turn contributes exactly what the human sent.
USER_MESSAGE_FLAVORS: frozenset[MessageRefFlavor] = frozenset(
    {MessageRefFlavor.ATTACHMENT, MessageRefFlavor.CONTEXT}
)

#: The flavors an ``assistant`` message may carry — everything the turn produced or is blocked on.
ASSISTANT_MESSAGE_FLAVORS: frozenset[MessageRefFlavor] = frozenset(
    {
        MessageRefFlavor.OUTPUT,
        MessageRefFlavor.OPEN_GATE,
        MessageRefFlavor.NEXT_ACTION,
        MessageRefFlavor.ASSUMPTION,
        MessageRefFlavor.WORKSPACE_OUTPUT,
    }
)

_BY_ROLE: dict[str, frozenset[MessageRefFlavor]] = {
    "user": USER_MESSAGE_FLAVORS,
    "assistant": ASSISTANT_MESSAGE_FLAVORS,
}


def flavors_for_message_role(role: str) -> frozenset[MessageRefFlavor]:
    """The flavors a message of this role may carry — empty for ``system``/``tool``."""

    return _BY_ROLE.get(role, frozenset())


class MessageObjectRef(BaseModel):
    """One typed, workspace-scoped pointer from a message to durable state.

    The field set mirrors ``clue_agents.contracts.DomainObjectRef`` (``workspace_id`` /
    ``object_type`` / ``object_id`` / ``version``) plus the ``flavor`` REQ-21 asks for. It is
    re-declared here rather than imported because the machine-enforced import contract forbids
    ``clue_projections`` from importing ``clue_agents`` at all (pyproject rule P1) — this is the
    wire projection of that contract, not the contract itself.

    An artifact-backed ref (attachment / next action / assumption / workspace output) projects as
    ``object_type='artifact'`` with the content-addressed ``storage_key`` as ``object_id``; a
    finalization domain ref carries the domain type and id the turn actually recorded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flavor: MessageRefFlavor
    workspace_id: str
    object_type: str
    object_id: str
    version: int | None = Field(default=None, ge=1)
    #: Position within its ``(message, flavor)`` group, preserved from the durable row's ordinal so
    #: the surface renders attachments in the order they were sent.
    ordinal: int = Field(ge=0)
