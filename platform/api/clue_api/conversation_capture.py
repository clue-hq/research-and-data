"""Capture one human conversation message durably, before anything spends (FI Lane D D2).

The capture half of a conversation turn, split out from :mod:`clue_api.conversation_turns` for one
structural reason: **the HTTP process must be able to do this and nothing else**. The turn route
runs inside the projections app, which composes no model gateway (§3-P3, ratified §6-D1), so the
capture path may not sit in a module whose import graph reaches the deepagent runtime. Keeping it
here is what lets the isolation guard be a real, checkable contract rather than a convention.

Both conversation surfaces call :func:`persist_user_turn`: the dev-only stage-0 trial before it
wakes the model in-process, and the production turn route before it enqueues the fleet task. One
implementation, because the ordering it encodes — bytes first, capture record second, spend last —
is the platform's capture-before-use contract and is what D1's ``turn-action:<turn_id>`` receipt
re-derives to prove a human acted.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import ArtifactRef
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import EntityId, OnboardingInputId, OnboardingInputKind
from clue_research.stage0 import submit_onboarding_input

__all__ = [
    "CONVERSATION_CONTEXT_BINDING_KIND",
    "CONVERSATION_USER_MESSAGE_BINDING_KIND",
    "CapturedUserTurn",
    "persist_user_turn",
    "project_client_entity_id",
]

#: The DSAR binding kinds a conversation writes: the human's own words, and everything the platform
#: compiles *about* the conversation for the model to read.
CONVERSATION_USER_MESSAGE_BINDING_KIND = "conversation"
CONVERSATION_CONTEXT_BINDING_KIND = "context"


@dataclass(frozen=True, slots=True)
class CapturedUserTurn:
    """What the platform durably holds about one human message, before any model has seen it."""

    turn_id: UUID
    artifact_ref: ArtifactRef
    onboarding_input_id: OnboardingInputId


async def persist_user_turn(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    turn_id: UUID,
    message: str,
    product_id: str | None = None,
    client_entity_id: EntityId | None = None,
    binding_kind: str = CONVERSATION_USER_MESSAGE_BINDING_KIND,
) -> CapturedUserTurn:
    """Capture one human message durably: artifact + DSAR binding + ``onboarding_input``.

    The single owner of this path. Both the trial and the production turn route call it, and both
    call it *before* spend — the trial before it wakes the model, the route before it enqueues the
    fleet task. That ordering is the platform's capture-before-use contract: the
    ``onboarding_input`` row's artifact foreign key proves the bytes existed first, and
    :func:`clue_api.turn_action.resolve_turn_action` re-derives exactly this join to prove a human
    receipt later.

    The ``onboarding_input`` id is derived from the turn id, so re-capturing the same turn is a
    replay (``ON CONFLICT DO NOTHING``) rather than a second capture record.

    ``client_entity_id`` is the DSAR subject: when the workspace has a reverse-profiled client it
    is bound so an erasure of that subject reaches these words. When it is absent (a project whose
    Stage-0 recon has not run) the artifact is still workspace-scoped and reachable through the
    turn's own artifact refs — binding it to a *guessed* subject would be worse than binding it to
    none.
    """

    if not message.strip():
        raise ValueError("a conversation turn message cannot be empty")
    subject_bindings = (
        ((UUID(str(client_entity_id)), binding_kind),) if client_entity_id is not None else ()
    )
    ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=message.encode(),
        media_type="text/plain",
        subject_bindings=subject_bindings,
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        product_id=product_id,
        project_id=project_id,
        client_entity_id=client_entity_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=ref.artifact_key,
        content_sha256=ref.sha256,
        actor="human",
        onboarding_input_id=OnboardingInputId(uuid5(turn_id, "onboarding-input")),
    )
    return CapturedUserTurn(
        turn_id=turn_id,
        artifact_ref=ref,
        onboarding_input_id=captured.onboarding_input_id,
    )


_PROJECT_CLIENT_ENTITY_SQL = text(
    """
    SELECT client_entity_id
    FROM onboarding_input
    WHERE workspace_id = :workspace_id
      AND project_id = :project_id
      AND client_entity_id IS NOT NULL
    ORDER BY created_at DESC, id DESC
    LIMIT 1
    """
)


async def project_client_entity_id(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> EntityId | None:
    """The client entity this project's captures are bound to, if it has one yet.

    *Discovered, never assumed.* A project whose Stage-0 recon has run has captured a client entity
    on its own onboarding inputs; a project that has not simply has no client knowledge base yet,
    and ``None`` is the honest answer. Guessing would bind a human's words — and every Stage-0 tool
    call the turn could make — to the wrong subject, which is worse than binding them to none.

    One reader, called from both sides of the seam (the route, for the DSAR subject binding; the
    worker, for the constitution and the L3 card), so the two can never disagree about who the
    client is.
    """

    value = (
        await conn.execute(
            _PROJECT_CLIENT_ENTITY_SQL,
            {"workspace_id": workspace_id, "project_id": project_id},
        )
    ).scalar_one_or_none()
    return None if value is None else EntityId(UUID(str(value)))
