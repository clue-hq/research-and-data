"""Wake every chat that was waiting on the CRM connection (R-3.10).

When a connection becomes active, each fulfilled connect request gets one derived turn in its
chat (``derivation = 'crm_connected'``), so the Head of ABM continues without anyone typing — the
same mechanism as a finished discovery (``clue_api.discovery_wake``). The turn is attributed to
whoever submitted the turn that showed the card, and is hidden from the transcript as a user
bubble like every derived turn.

It writes only through the ``conn`` it is given and never commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import (
    DERIVATION_CRM_CONNECTED,
    dispatch_next_thread_turn,
    get_submission,
    insert_submission,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.conversation_capture import (
    CONVERSATION_CONTEXT_BINDING_KIND,
    persist_user_turn,
    project_client_entity_id,
)
from clue_api.crm.composio_gateway import CrmProvider
from clue_api.crm.connections import ConnectRequest
from clue_spine import get_project

__all__ = ["crm_connected_message", "queue_crm_connected_turns"]

_NAMES: dict[str, str] = {"hubspot": "HubSpot", "salesforce": "Salesforce"}


def crm_connected_message(provider: CrmProvider) -> str:
    return f"The workspace's {_NAMES[provider]} is now connected. Continue where we left off."


async def queue_crm_connected_turns(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore,
    *,
    requests: Sequence[ConnectRequest],
    provider: CrmProvider,
) -> list[UUID]:
    """Queue one wake turn per request and return their turn ids.

    The turn id is derived from the request, so a replayed callback lands on the same turn. A
    request whose card-showing turn or project is gone is skipped (there is nobody to wake).
    """
    message = crm_connected_message(provider)
    woken: list[UUID] = []
    for request in requests:
        asking = await get_submission(
            conn, workspace_id=request.workspace_id, turn_id=request.turn_id
        )
        project = await get_project(conn, request.project_id)
        if asking is None or project is None:
            continue
        key = f"crm-connected:{request.request_id}"
        turn_id = turn_id_for_submission(
            workspace_id=request.workspace_id, thread_id=request.thread_id, idempotency_key=key
        )
        captured = await persist_user_turn(
            conn,
            artifacts=artifacts,
            workspace_id=request.workspace_id,
            brand_id=project.brand_id,
            project_id=request.project_id,
            turn_id=turn_id,
            message=message,
            client_entity_id=await project_client_entity_id(
                conn, workspace_id=request.workspace_id, project_id=request.project_id
            ),
            binding_kind=CONVERSATION_CONTEXT_BINDING_KIND,
        )
        _, created = await insert_submission(
            conn,
            turn_id=turn_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            thread_id=request.thread_id,
            submitted_by_user_id=asking.submitted_by_user_id,
            submitted_via_membership_id=asking.submitted_via_membership_id,
            onboarding_input_id=captured.onboarding_input_id,
            message_artifact_key=captured.artifact_ref.artifact_key,
            message_sha256=captured.artifact_ref.sha256,
            idempotency_key=key,
            derivation=DERIVATION_CRM_CONNECTED,
            derived_from_turn_id=request.turn_id,
        )
        if created:
            await dispatch_next_thread_turn(
                conn, workspace_id=request.workspace_id, thread_id=request.thread_id
            )
            woken.append(turn_id)
    return woken
