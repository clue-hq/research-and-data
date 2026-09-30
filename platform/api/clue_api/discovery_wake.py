"""The Head of ABM's turn at the end of a discovery run (spec 2026-09-30 §4 "The wake").

When a discovery run ends, the thread that launched it gets one derived turn whose message is the
run's summary: no user bubble (any non-NULL ``derivation`` hides it), but a durable user row so the
Head of ABM reads the summary as the turn's message. The run stays held — its project lock and its
thread — until that turn finishes; the ``AGENT_TURN`` handler then releases it and the thread moves
on to whatever the user sent meanwhile.

This lives outside ``clue_api.arv2`` on purpose: the lane may not import the turn-submission
module, so the discovery driver is handed this object through its ``DiscoveryWake`` seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import (
    DERIVATION_DISCOVERY_FINISHED,
    dispatch_next_thread_turn,
    get_submission,
    insert_submission,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.discovery_store import DiscoveryRunRow, record_wake_turn
from clue_api.conversation_capture import (
    CONVERSATION_CONTEXT_BINDING_KIND,
    persist_user_turn,
    project_client_entity_id,
)

__all__ = ["DbDiscoveryWake"]


class DbDiscoveryWake:
    """Queue the wake turn in the launching thread, inside the transaction that ends the run.

    It writes only through the ``conn`` it is given and never commits: the driver calls it in a
    savepoint of its own ending transaction, so a failure here rolls back to that savepoint and the
    driver releases the run instead. (The message bytes themselves go through the artifact store,
    which captures before use exactly as the turn route does.)
    """

    def __init__(self, artifacts: DurableAgentArtifactStore) -> None:
        self._artifacts = artifacts

    async def queue(
        self,
        conn: AsyncConnection,
        run: DiscoveryRunRow,
        summary: Mapping[str, Any],
        message: str,
    ) -> UUID | None:
        """Queue the wake and return its turn id, or ``None`` when there is nobody to wake.

        The turn id is derived from the run, so a replayed ending lands on the same turn. The
        submission is attributed to whoever submitted the launching turn — the person who asked
        for the discovery is the one the answer is for.
        """

        del summary  # the message is the summary, already rendered by the driver
        if run.launched_thread_id is None or run.launching_turn_id is None:
            return None
        launching = await get_submission(
            conn, workspace_id=run.workspace_id, turn_id=run.launching_turn_id
        )
        if launching is None:
            return None
        key = f"discovery-finished:{run.run_id}"
        turn_id = turn_id_for_submission(
            workspace_id=run.workspace_id,
            thread_id=run.launched_thread_id,
            idempotency_key=key,
        )
        captured = await persist_user_turn(
            conn,
            artifacts=self._artifacts,
            workspace_id=run.workspace_id,
            brand_id=run.brand_id,
            project_id=run.project_id,
            turn_id=turn_id,
            message=message,
            client_entity_id=await project_client_entity_id(
                conn, workspace_id=run.workspace_id, project_id=run.project_id
            ),
            binding_kind=CONVERSATION_CONTEXT_BINDING_KIND,
        )
        await insert_submission(
            conn,
            turn_id=turn_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            thread_id=run.launched_thread_id,
            submitted_by_user_id=launching.submitted_by_user_id,
            submitted_via_membership_id=launching.submitted_via_membership_id,
            onboarding_input_id=captured.onboarding_input_id,
            message_artifact_key=captured.artifact_ref.artifact_key,
            message_sha256=captured.artifact_ref.sha256,
            idempotency_key=key,
            derivation=DERIVATION_DISCOVERY_FINISHED,
            derived_from_turn_id=run.launching_turn_id,
        )
        # Recorded before the dispatch, not only by the driver afterwards: dispatch holds a thread
        # whose unreleased run has no wake yet, so without this it would offer nothing and the
        # wake would wait for the next unrelated dispatch.
        await record_wake_turn(conn, run_id=run.run_id, wake_turn_id=turn_id)
        # A no-op while the launching turn's own task is still in flight; the worker offers the
        # wake when that task finishes.
        await dispatch_next_thread_turn(
            conn, workspace_id=run.workspace_id, thread_id=run.launched_thread_id
        )
        return turn_id
