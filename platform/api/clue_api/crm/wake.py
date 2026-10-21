"""Wake the chats that wait on the CRM: on its connection (R-3.10) and on their writes.

When a connection becomes active, each fulfilled connect request gets one derived turn in its
chat (``derivation = 'crm_connected'``), so the Head of ABM continues without anyone typing — the
same mechanism as a finished discovery (``clue_api.discovery_wake``). The turn is attributed to
whoever submitted the turn that showed the card, and is hidden from the transcript as a user
bubble like every derived turn.

A proposal of CRM writes wakes the chat that proposed it the same way (``derivation =
'crm_writes_finished'``): once when its writes are finished, and once each time they pause (an
expired connection, Salesforce's API allowance) with progress since the last pause.

It writes only through the ``conn`` it is given and never commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import (
    DERIVATION_CRM_CONNECTED,
    DERIVATION_CRM_WRITES_FINISHED,
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
from clue_api.crm.writes import WriteCounts, WriteProposal, proposal_counts
from clue_spine import get_project

__all__ = [
    "crm_connected_message",
    "crm_writes_finished_message",
    "crm_writes_paused_message",
    "queue_crm_connected_turns",
    "queue_crm_writes_finished_turn",
    "queue_crm_writes_paused_turn",
]

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


# --- writes ------------------------------------------------------------------------------------


def _tally(counts: WriteCounts) -> str:
    return f"{counts.done} done, {counts.failed} failed, {counts.skipped} skipped"


def _log_hint(proposal_id: UUID) -> str:
    return f"read the details with crm_write_log(proposal_id={proposal_id})"


def crm_writes_finished_message(proposal_id: UUID, counts: WriteCounts) -> str:
    message = f"The CRM changes are finished: {_tally(counts)} — {_log_hint(proposal_id)}."
    if counts.not_chosen:
        message += f" {counts.not_chosen} not chosen on the card were not sent."
    return message


def crm_writes_paused_message(
    proposal_id: UUID, counts: WriteCounts, *, reason: str, resumes: str
) -> str:
    return (
        f"The CRM changes are paused: {reason.rstrip('.')}. So far {_tally(counts)}, "
        f"{counts.waiting} waiting. They continue by themselves {resumes}. "
        f"{_log_hint(proposal_id).capitalize()}."
    )


async def queue_crm_writes_finished_turn(
    conn: AsyncConnection, artifacts: DurableAgentArtifactStore, *, proposal: WriteProposal
) -> UUID | None:
    """Wake the proposing chat once when the proposal's writes are finished.

    The turn id is derived from the proposal (``crm-writes-finished:<proposal_id>``), so a
    replayed ending lands on the same turn. ``None`` when it was queued already or there is
    nobody to wake.
    """
    counts = await proposal_counts(conn, proposal_id=proposal.proposal_id)
    return await _queue_write_wake(
        conn,
        artifacts,
        proposal=proposal,
        key=f"crm-writes-finished:{proposal.proposal_id}",
        message=crm_writes_finished_message(proposal.proposal_id, counts),
    )


async def queue_crm_writes_paused_turn(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore,
    *,
    proposal: WriteProposal,
    reason: str,
    resumes: str,
) -> UUID | None:
    """Wake the proposing chat when the proposal's writes pause.

    Keyed by the number of changes already decided, so pausing again without progress (a
    resumed run that meets the same expired connection) does not wake the chat twice.
    """
    counts = await proposal_counts(conn, proposal_id=proposal.proposal_id)
    decided = counts.done + counts.failed + counts.skipped
    return await _queue_write_wake(
        conn,
        artifacts,
        proposal=proposal,
        key=f"crm-writes-paused:{proposal.proposal_id}:{decided}",
        message=crm_writes_paused_message(
            proposal.proposal_id, counts, reason=reason, resumes=resumes
        ),
    )


async def _queue_write_wake(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore,
    *,
    proposal: WriteProposal,
    key: str,
    message: str,
) -> UUID | None:
    asking = await get_submission(
        conn, workspace_id=proposal.workspace_id, turn_id=proposal.turn_id
    )
    project = await get_project(conn, proposal.project_id)
    if asking is None or project is None:
        return None
    turn_id = turn_id_for_submission(
        workspace_id=proposal.workspace_id, thread_id=proposal.thread_id, idempotency_key=key
    )
    if await get_submission(conn, workspace_id=proposal.workspace_id, turn_id=turn_id):
        return None
    captured = await persist_user_turn(
        conn,
        artifacts=artifacts,
        workspace_id=proposal.workspace_id,
        brand_id=project.brand_id,
        project_id=proposal.project_id,
        turn_id=turn_id,
        message=message,
        client_entity_id=await project_client_entity_id(
            conn, workspace_id=proposal.workspace_id, project_id=proposal.project_id
        ),
        binding_kind=CONVERSATION_CONTEXT_BINDING_KIND,
    )
    _, created = await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=proposal.workspace_id,
        project_id=proposal.project_id,
        thread_id=proposal.thread_id,
        submitted_by_user_id=asking.submitted_by_user_id,
        submitted_via_membership_id=asking.submitted_via_membership_id,
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=key,
        derivation=DERIVATION_CRM_WRITES_FINISHED,
        derived_from_turn_id=proposal.turn_id,
    )
    if not created:
        return None
    await dispatch_next_thread_turn(
        conn, workspace_id=proposal.workspace_id, thread_id=proposal.thread_id
    )
    return turn_id
