"""The design-leg turn engine (Part III P3.4 — PD-part3 §1-D1/D3, §2.4).

The worker-side half of ruling D1's routing rule. When the ``AGENT_TURN`` worker claims a turn
whose thread holds an **open** ``design_leg``, the message does not wake head-of-abm — it becomes
a **design turn on that leg**, and this module is what runs it:

* **Attribution on the shared thread (D3).** The turn lands as a real ``agent_turn`` row —
  role=``design``, its execution parented under the delegating platform execution
  (``design_leg.parent_execution_id``) — with the submitting human copied from the durable
  submission, exactly as every other turn. The §2.5 one-thread/attribution contract holds
  without the design runtime learning anything about platform journals.
* **Execution on the design lane (D3).** The turn's body is a ``DesignTurnEnvelope`` driven
  through the :class:`DesignLegLaneDriver` seam. Production drives the design fleet handler
  *inline under a real work lease* (see ``clue_api.design_fleet.build_design_leg_lane_driver``)
  rather than enqueueing a second fleet task: the platform fleet drains one task at a time per
  worker, so an ``AGENT_TURN`` handler that queued a ``design_job`` and waited for it would
  deadlock a single-worker deployment against itself. Same handler, same claim CAS, same
  generation fences — only the queue hop is skipped. The run row is stamped with
  ``leg_id`` + ``execution_id`` (the P3.1 linkage), and its id is **derived from the turn id**,
  so a re-claimed task converges on the same run instead of dispatching a second one.
* **An honest terminal shape (D1).** A design turn that produced a proposal ends
  ``AWAITING_INPUT`` with a committed :class:`~clue_agents.AgentFinalizeEnvelope` whose
  ``open_gate_refs`` name the leg — the leg *is* the open interaction — which also buys the
  committed-outcome replay short-circuit for free. A failed design run fails the turn with no
  manufactured finalization, and the leg stays open: the user answers, the leg goes on.
* **Leg-scoped history (§2.4).** :func:`load_design_leg_history` returns exactly this leg's
  user↔design exchanges (joined through the turns' execution parentage, which survives even a
  turn whose design run never got created); :func:`load_head_of_abm_history` is the other half —
  the conversation surface's load that **excludes** every design-role turn, so head-of-abm never
  ingests the leg transcript. Leg summaries enter head-of-abm's view at leg close (P3.5).

What deliberately does **not** happen here: no platform model wake (the trio runs inside the
design runtime, P3.2's gateway move already governs its spend per role), no platform workspace
lease (the design runtime's virtual workspace is keyed to its run — ``workspace_root_id`` records
the leg address honestly), and no leg close (``finish_design_leg`` is P3.5's engine-validated
exit; a turn ending keeps the leg ``open_awaiting_user``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import text

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentHistoryStore,
    AgentProfileRegistry,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    ArtifactRef,
    DomainObjectRef,
    FinalizeStatus,
    HistoryMessageRef,
    ProjectContextArtifact,
)
from clue_api.agent_turn_submission import AgentTurnSubmissionRow
from clue_api.agent_turn_wiring import (
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.chat.turn_stream import TurnStreamEmitter
from clue_core import ExecutionId
from clue_db import ConnFactory, transaction
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import get_document
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.errors import DesignNotFoundError
from clue_obs import get_logger
from clue_spine import get_project

log = get_logger("clue_api.design_leg")

__all__ = [
    "DESIGN_LEG_BUDGET_LIMIT_MILLICENTS",
    "DESIGN_LEG_TURN_FAILED",
    "DesignLegLaneDriver",
    "DesignLegTurnResult",
    "DesignLegTurnRunner",
    "design_leg_execution_id",
    "design_leg_run_id",
    "design_legs_for_threads",
    "load_design_leg_history",
    "load_head_of_abm_history",
]

#: The leg turn's platform-side spend envelope. Model spend happens inside the design runtime and
#: is measured at the gateway per role (P3.2's single-authority attribution); this envelope is the
#: constitutional bound the ``agent_turn`` row records, sized like the conversation's.
DESIGN_LEG_BUDGET_LIMIT_MILLICENTS = 1_000_000

#: The one stable failure code a failed design run surfaces on the platform turn.
DESIGN_LEG_TURN_FAILED = "design_leg_turn_failed"

_EXECUTION_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-execution")
_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-run")
_FINALIZATION_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-finalization")

_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed"})


def design_leg_execution_id(turn_id: UUID) -> ExecutionId:
    """The design turn's execution identity — one per turn, derived, crash-stable."""

    return ExecutionId(uuid5(_EXECUTION_NAMESPACE, str(turn_id)))


def design_leg_run_id(turn_id: UUID) -> str:
    """The design run this turn dispatches — derived so a retried task re-joins, never re-runs."""

    return f"run_{uuid5(_RUN_NAMESPACE, str(turn_id)).hex}"


class DesignLegLaneDriver(Protocol):
    """Drive one leg-turn envelope on the design lane to a terminal design-run row.

    Implementations own claim/fencing/execution; the runner owns everything durable around it.
    ``drive`` returns when the run row is terminal (or raises); it must never fabricate a result.
    """

    async def drive(self, *, envelope: DesignTurnEnvelope) -> None: ...


@dataclass(frozen=True, slots=True)
class DesignLegTurnResult:
    """Field-compatible with ``ConversationTurnResult`` — the work handler reads these three."""

    outcome: AgentTurnOutcome
    assistant_message: str | None
    replayed: bool


async def load_design_leg_history(
    conn_factory: ConnFactory,
    *,
    workspace_id: str,
    thread_id: str,
    leg_parent_execution_id: UUID | str,
) -> tuple[HistoryMessageRef, ...]:
    """§2.4's design-side assembly: THIS leg's user↔design exchanges, in thread order.

    The join is through turn parentage — every design turn's execution is parented under the
    leg's delegating execution — rather than through ``design_agent_run.leg_id``, so a turn
    whose run was never created (a crash before dispatch) still belongs to its leg's history.
    A reopened leg keeps its parent execution, so its history resumes where it was (§2.2).
    """

    async with conn_factory() as conn:
        result = await conn.execute(
            text(
                "SELECT m.id, m.turn_id, m.sequence, m.role, m.body_artifact_key, "
                "m.body_sha256, a.media_type, a.size_bytes "
                "FROM agent_thread_message m "
                "JOIN agent_turn t ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
                "JOIN artifact a ON a.storage_key = m.body_artifact_key "
                "WHERE m.workspace_id = :workspace AND m.thread_id = :thread "
                "AND t.role = 'design' AND t.parent_execution_id = :parent "
                "ORDER BY m.sequence"
            ),
            {
                "workspace": workspace_id,
                "thread": thread_id,
                "parent": str(leg_parent_execution_id),
            },
        )
        return tuple(
            HistoryMessageRef(
                message_id=row["id"],
                turn_id=row["turn_id"],
                sequence=int(row["sequence"]),
                role=row["role"],
                body_ref=ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=row["body_artifact_key"],
                    sha256=row["body_sha256"],
                    media_type=row["media_type"],
                    byte_count=int(row["size_bytes"]),
                ),
            )
            for row in result.mappings()
        )


async def load_head_of_abm_history(
    conn_factory: ConnFactory,
    *,
    workspace_id: str,
    thread_id: str,
) -> tuple[HistoryMessageRef, ...]:
    """§2.4's other half: the conversation surface's thread history **without** leg transcripts.

    Filtered by turn role rather than by leg id, deliberately: head-of-abm never ingests *any*
    design exchange, whichever leg produced it. What it *does* see of a leg is exactly the
    exit summary ``finish_design_leg`` journaled at close (P3.5) — the one design-turn message
    whose id the append-only exit journal names. The journal is the authority for what crosses
    the §2.4 boundary: a summary, never a transcript.
    """

    async with conn_factory() as conn:
        result = await conn.execute(
            text(
                "SELECT m.id, m.turn_id, m.sequence, m.role, m.body_artifact_key, "
                "m.body_sha256, a.media_type, a.size_bytes "
                "FROM agent_thread_message m "
                "JOIN agent_turn t ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
                "JOIN artifact a ON a.storage_key = m.body_artifact_key "
                "WHERE m.workspace_id = :workspace AND m.thread_id = :thread "
                "AND (t.role <> 'design' OR m.id IN ("
                "    SELECT CAST(j.summary_refs->>'summary_message_id' AS uuid) "
                "    FROM design_leg_exit_journal j "
                "    WHERE j.workspace_id = m.workspace_id "
                "      AND j.summary_refs ? 'summary_message_id'"
                ")) "
                "ORDER BY m.sequence"
            ),
            {"workspace": workspace_id, "thread": thread_id},
        )
        return tuple(
            HistoryMessageRef(
                message_id=row["id"],
                turn_id=row["turn_id"],
                sequence=int(row["sequence"]),
                role=row["role"],
                body_ref=ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=row["body_artifact_key"],
                    sha256=row["body_sha256"],
                    media_type=row["media_type"],
                    byte_count=int(row["size_bytes"]),
                ),
            )
            for row in result.mappings()
        )


async def design_legs_for_threads(
    conn_factory: ConnFactory,
    *,
    workspace_id: str,
    thread_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """The speaker-state anti-join: each thread's open leg (id + state), one statement.

    The read behind the P3.4 speaker projection — the sidebar chip's "who owns this thread
    now" — shaped like ``open_gate_kinds_for_threads``: one query for the whole page, absent
    means head-of-abm speaks. The partial-unique index guarantees at most one row per thread.
    """

    if not thread_ids:
        return {}
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT thread_id, id, state FROM design_leg "
                        "WHERE workspace_id = :ws AND state <> 'closed' "
                        "AND thread_id = ANY(CAST(:threads AS text[]))"
                    ),
                    {"ws": workspace_id, "threads": list(thread_ids)},
                )
            )
            .mappings()
            .all()
        )
    return {
        str(row["thread_id"]): {"id": str(row["id"]), "state": str(row["state"])} for row in rows
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _assistant_summary(run: dict[str, Any]) -> str:
    """A truthful one-paragraph thread record of what the design turn did.

    Derived from the run's terminal result — never invented. Part IV owns the rich rendering
    (the canvas preview, the proposal card); the durable message is the honest minimum.
    """

    result = run.get("result_json") or {}
    status = str(result.get("status") or run.get("status") or "unknown")
    reason = result.get("stop_reason")
    if isinstance(reason, str) and reason.strip():
        return f"Design turn {status}: {reason.strip()}"
    return f"Design turn {status}."


class DesignLegTurnRunner:
    """Run one user message as one design turn on its open leg."""

    def __init__(
        self,
        *,
        profiles: AgentProfileRegistry,
        artifacts: DurableAgentArtifactStore,
        turns: DbAgentTurnJournal,
        history: AgentHistoryStore,
        lane: DesignLegLaneDriver,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._profiles = profiles
        self._artifacts = artifacts
        self._turns = turns
        self._history = history
        self._lane = lane
        self._conn_factory = conn_factory

    async def run_leg_turn(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        leg: dict[str, Any],
        user_message_ref: ArtifactRef,
        focus_refs: tuple[DomainObjectRef, ...],
        card_payload: dict[str, JsonValue],
        stream: TurnStreamEmitter | None,
    ) -> DesignLegTurnResult:
        workspace_id = submission.workspace_id
        leg_id = str(leg["id"])
        parent_execution_id = UUID(str(leg["parent_execution_id"]))
        turn_id = submission.turn_id
        execution_id = design_leg_execution_id(turn_id)
        resolved = self._profiles.resolve(AgentRole.DESIGN)

        async with self._conn_factory() as conn:
            project = await get_project(conn, submission.project_id)
            if project is None or project.workspace_id != workspace_id:
                raise ValueError("the design-leg submission names no project in its workspace")
            # §2.4: the leg history the envelope carries is everything BEFORE this turn.
            prior_history = await load_design_leg_history(
                self._conn_factory,
                workspace_id=workspace_id,
                thread_id=submission.thread_id,
                leg_parent_execution_id=parent_execution_id,
            )
            bundle_ref = await self._bundle_ref(conn, leg=leg, workspace_id=workspace_id)
            document_scene: dict[str, Any] = {}
            if leg.get("document_id") is not None:
                try:
                    document = await get_document(
                        conn,
                        workspace_id=workspace_id,
                        document_id=str(leg["document_id"]),
                    )
                    document_scene = document.get("scene") or {}
                except DesignNotFoundError:
                    # The pinned document vanished between delegation and this turn: dispatch
                    # with an empty scene and let the design runtime's own gates speak — a
                    # platform guess here would design against fabricated state.
                    log.warning(
                        "design_leg.pinned_document_missing",
                        leg_id=leg_id,
                        document_id=str(leg["document_id"]),
                    )
            await self._ensure_execution(
                conn,
                execution_id=execution_id,
                workspace_id=workspace_id,
                project_id=submission.project_id,
                parent_execution_id=parent_execution_id,
                user_message_ref=user_message_ref,
                manifest_sha256=resolved.resource_manifest.aggregate_sha256,
            )

        card_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.project-conversation-card+json",
            card_payload,
            project_id=submission.project_id,
        )
        budget_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-budget-envelope+json",
            {
                "schema_version": "1",
                "limit_millicents": DESIGN_LEG_BUDGET_LIMIT_MILLICENTS,
                "external_research_budget_cents": "0",
                "scope": (
                    "one design-leg turn; model spend is measured at the gateway per design "
                    "role (P3.2 single-authority attribution)"
                ),
            },
            project_id=submission.project_id,
        )
        manifest_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-resource-manifest+json",
            resolved.resource_manifest.model_dump(mode="json"),
            project_id=submission.project_id,
        )
        bundle_context = (
            ProjectContextArtifact(
                name="design-delegation-bundle",
                artifact_ref=bundle_ref,
                domain_ref=DomainObjectRef(
                    workspace_id=workspace_id,
                    object_type="design_delegation_bundle",
                    object_id=leg_id,
                    # Bundle schema v1; one immutable bundle per leg.
                    version=1,
                ),
            ),
        )
        leg_ref = DomainObjectRef(
            workspace_id=workspace_id,
            object_type="design_leg",
            object_id=leg_id,
            version=None,
        )
        request = AgentTurnRequest(
            turn_id=turn_id,
            thread_id=submission.thread_id,
            constitution=AgentConstitution(
                workspace_id=workspace_id,
                project_id=submission.project_id,
                execution_id=execution_id,
                # The one identity rule, unchanged on the design path: the acting human,
                # from the durable submission row.
                actor_id=submission.submitted_by_user_id,
                role=AgentRole.DESIGN,
                brand_id=project.brand_id,
                product_id=project.product_id,
                # No platform workspace lease: the design runtime's virtual workspace is keyed
                # to its run. The root records the leg address honestly instead.
                workspace_root_id=f"design-leg:{leg_id}",
                project_card_ref=card_ref,
                budget_envelope_ref=budget_ref,
                profile_ref=resolved.profile_ref,
                resource_manifest_ref=manifest_ref,
                resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                focus_refs=(leg_ref, *focus_refs),
                project_context_artifacts=bundle_context,
            ),
            user_message_artifact_ref=user_message_ref,
            focus_refs=focus_refs,
            requested_at=submission.requested_at,
        )
        await self._turns.create(
            request=request,
            profile=resolved.profile,
            submitted_by_user_id=submission.submitted_by_user_id,
            submitted_via_membership_id=submission.submitted_via_membership_id,
        )
        await self._history.append(
            message_id=uuid5(turn_id, "user"),
            turn_id=turn_id,
            workspace_id=workspace_id,
            thread_id=submission.thread_id,
            role="user",
            body_ref=user_message_ref,
        )
        committed = await self._turns.load_committed_outcome(
            turn_id=turn_id,
            workspace_id=workspace_id,
        )
        if stream is not None:
            await stream.turn_started()
        if committed is not None:
            assistant_message = await self._project_committed(
                committed=committed,
                submission=submission,
            )
            if stream is not None:
                await stream.rehydrate(reason="turn_replayed")
                await stream.turn_finished(
                    status=committed.status.value,
                    failure_code=committed.failure_code,
                    replayed=True,
                )
            return DesignLegTurnResult(
                outcome=committed,
                assistant_message=assistant_message,
                replayed=True,
            )

        await self._turns.mark_running(turn_id=turn_id, workspace_id=workspace_id)
        run = await self._dispatch(
            submission=submission,
            leg=leg,
            leg_id=leg_id,
            execution_id=execution_id,
            user_message_ref=user_message_ref,
            prior_history=prior_history,
            document_scene=document_scene,
            focus_refs=focus_refs,
            workspace_id=workspace_id,
        )
        await self._leg_back_to_awaiting(workspace_id=workspace_id, leg_id=leg_id)

        if run["status"] != "succeeded":
            await self._turns.mark_unfinalized(
                turn_id=turn_id,
                workspace_id=workspace_id,
                reason_code=DESIGN_LEG_TURN_FAILED,
                abandoned=False,
            )
            if stream is not None:
                await stream.turn_finished(
                    status="failed",
                    failure_code=DESIGN_LEG_TURN_FAILED,
                )
            log.warning(
                "design_leg.turn_failed",
                leg_id=leg_id,
                turn_id=str(turn_id),
                run_id=str(run.get("run_id")),
            )
            return DesignLegTurnResult(
                outcome=AgentTurnOutcome(
                    turn_id=turn_id,
                    execution_id=execution_id,
                    status=AgentExecutionStatus.FAILED,
                    failure_code=DESIGN_LEG_TURN_FAILED,
                ),
                assistant_message=None,
                replayed=False,
            )

        assistant_message = _assistant_summary(run)
        assistant_ref = await self._artifact_text(
            workspace_id,
            assistant_message,
            project_id=submission.project_id,
        )
        envelope = AgentFinalizeEnvelope(
            finalization_id=uuid5(_FINALIZATION_NAMESPACE, str(turn_id)),
            execution_id=execution_id,
            status=FinalizeStatus.AWAITING_INPUT,
            user_message_artifact_ref=assistant_ref,
            domain_refs=(
                DomainObjectRef(
                    workspace_id=workspace_id,
                    object_type="design_agent_run",
                    object_id=str(run["run_id"]),
                    version=None,
                ),
            ),
            # The leg IS the open interaction: the turn is done, the leg awaits the user.
            open_gate_refs=(leg_ref,),
            finalized_at=datetime.now(tz=UTC),
        )
        await self._turns.record_finalization(
            turn_id=turn_id,
            workspace_id=workspace_id,
            envelope=envelope,
        )
        envelope_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-finalize-envelope+json",
            json.loads(envelope.model_dump_json()),
            project_id=submission.project_id,
        )
        await self._turns.commit_finalization_authority(
            turn_id=turn_id,
            workspace_id=workspace_id,
            envelope=envelope,
            envelope_ref=envelope_ref,
        )
        await self._history.append(
            message_id=uuid5(turn_id, "assistant"),
            turn_id=turn_id,
            workspace_id=workspace_id,
            thread_id=submission.thread_id,
            role="assistant",
            body_ref=assistant_ref,
        )
        if stream is not None:
            # No platform text was streamed (design progress rides the design_run subject,
            # D3); the honest instruction is to fetch the canonical message.
            await stream.rehydrate(reason="design_turn_summary")
            await stream.turn_finished(status="awaiting_input")
        return DesignLegTurnResult(
            outcome=AgentTurnOutcome(
                turn_id=turn_id,
                execution_id=execution_id,
                status=AgentExecutionStatus.AWAITING_INPUT,
                finalization_ref=envelope_ref,
            ),
            assistant_message=assistant_message,
            replayed=False,
        )

    # -- dispatch ------------------------------------------------------------------------------

    async def _dispatch(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        leg: dict[str, Any],
        leg_id: str,
        execution_id: ExecutionId,
        user_message_ref: ArtifactRef,
        prior_history: Sequence[HistoryMessageRef],
        document_scene: dict[str, Any],
        focus_refs: tuple[DomainObjectRef, ...],
        workspace_id: str,
    ) -> dict[str, Any]:
        """Create (or re-join) the derived design run and drive it terminal."""

        run_id = design_leg_run_id(submission.turn_id)
        async with self._conn_factory() as conn:
            run = await design_runs.get_run(conn, workspace_id=workspace_id, run_id=run_id)
        if run is not None and run["status"] in _TERMINAL_RUN_STATUSES:
            return run  # a crashed attempt already finished the design work; re-join it

        envelope = await self._envelope(
            submission=submission,
            leg=leg,
            leg_id=leg_id,
            execution_id=execution_id,
            run_id=run_id,
            user_message_ref=user_message_ref,
            prior_history=prior_history,
            document_scene=document_scene,
            focus_refs=focus_refs,
            workspace_id=workspace_id,
        )
        if run is None:
            async with self._conn_factory() as conn:
                if leg["state"] == "open_awaiting_user":
                    await design_legs.mark_leg_running(
                        conn, workspace_id=workspace_id, leg_id=leg_id
                    )
                await design_runs.create_run(
                    conn,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    document_id=leg.get("document_id"),
                    payload=dict(envelope.config),
                    work_id=envelope.work_id,
                    leg_id=leg_id,
                    execution_id=UUID(str(execution_id)),
                )
        await self._lane.drive(envelope=envelope)
        async with self._conn_factory() as conn:
            run = await design_runs.get_run(conn, workspace_id=workspace_id, run_id=run_id)
        if run is None or run["status"] not in _TERMINAL_RUN_STATUSES:
            raise RuntimeError("the design lane returned without a terminal design run")
        return run

    async def _envelope(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        leg: dict[str, Any],
        leg_id: str,
        execution_id: ExecutionId,
        run_id: str,
        user_message_ref: ArtifactRef,
        prior_history: Sequence[HistoryMessageRef],
        document_scene: dict[str, Any],
        focus_refs: tuple[DomainObjectRef, ...],
        workspace_id: str,
    ) -> DesignTurnEnvelope:
        bundle = await self._bundle_body(leg=leg, workspace_id=workspace_id)
        message_text = (await self._artifacts.read(user_message_ref)).decode()
        history_texts: list[dict[str, JsonValue]] = []
        for item in prior_history:
            history_texts.append(
                {
                    "role": item.role,
                    "text": (await self._artifacts.read(item.body_ref)).decode(),
                }
            )
        return DesignTurnEnvelope(
            kind="agent_turn",
            work_id=design_runs.work_id_for_run(run_id),
            workspace_id=workspace_id,
            run_id=run_id,
            checkpoint_thread_id=run_id,
            document_id=leg.get("document_id"),
            config={
                "request": {
                    "prompt": message_text,
                    "scene": document_scene,
                    "document_id": leg.get("document_id"),
                    "previous_turn_outcome": submission.previous_turn_outcome,
                },
                "delegation_bundle": bundle,
                "history": history_texts,
                "leg": {
                    "leg_id": leg_id,
                    "thread_id": submission.thread_id,
                    "agent_turn_id": str(submission.turn_id),
                    "execution_id": str(execution_id),
                    "brand_kit_id": leg.get("brand_kit_id"),
                    "brand_kit_version": leg.get("brand_kit_version"),
                    "document_version_guard": leg.get("document_version_guard"),
                    "focus_refs": [
                        {
                            "object_type": ref.object_type,
                            "object_id": ref.object_id,
                            "version": ref.version,
                        }
                        for ref in focus_refs
                    ],
                },
            },
        )

    # -- helpers -------------------------------------------------------------------------------

    async def _bundle_ref(
        self,
        conn: Any,
        *,
        leg: dict[str, Any],
        workspace_id: str,
    ) -> ArtifactRef:
        key = leg.get("bundle_artifact_ref")
        if not key:
            raise ValueError("this design leg records no delegation bundle artifact")
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT content_sha256, media_type, size_bytes FROM artifact "
                        "WHERE storage_key = :key AND workspace_id = :ws "
                        "AND erased_at IS NULL AND purged_at IS NULL"
                    ),
                    {"key": key, "ws": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError("the design leg's delegation bundle artifact is missing")
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=str(key),
            sha256=row["content_sha256"],
            media_type=row["media_type"],
            byte_count=int(row["size_bytes"]),
        )

    async def _bundle_body(self, *, leg: dict[str, Any], workspace_id: str) -> dict[str, JsonValue]:
        async with self._conn_factory() as conn:
            ref = await self._bundle_ref(conn, leg=leg, workspace_id=workspace_id)
        body = json.loads(await self._artifacts.read(ref))
        if not isinstance(body, dict):
            raise ValueError("the delegation bundle artifact is not a JSON object")
        return body

    async def _ensure_execution(
        self,
        conn: Any,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        project_id: str,
        parent_execution_id: UUID,
        user_message_ref: ArtifactRef,
        manifest_sha256: str,
    ) -> None:
        inserted = await conn.execute(
            text(
                "INSERT INTO execution "
                "(id, workspace_id, project_id, parent_execution_id, started_by, "
                " parameter_artifact_key, parameter_manifest_hash, pin_manifest_hash) "
                "VALUES (:id, :workspace, :project, :parent, 'human', :key, :sha, :manifest) "
                "ON CONFLICT (id) DO NOTHING RETURNING id"
            ),
            {
                "id": execution_id,
                "workspace": workspace_id,
                "project": project_id,
                "parent": parent_execution_id,
                "key": user_message_ref.artifact_key,
                "sha": user_message_ref.sha256,
                "manifest": manifest_sha256,
            },
        )
        if inserted.first() is not None:
            return
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT workspace_id, project_id, parent_execution_id "
                        "FROM execution WHERE id = :id"
                    ),
                    {"id": execution_id},
                )
            )
            .mappings()
            .one()
        )
        if (
            row["workspace_id"] != workspace_id
            or row["project_id"] != project_id
            or row["parent_execution_id"] != parent_execution_id
        ):
            raise ValueError("design-leg execution id already has different immutable inputs")

    async def _leg_back_to_awaiting(self, *, workspace_id: str, leg_id: str) -> None:
        async with self._conn_factory() as conn:
            current = await design_legs.get_leg(conn, workspace_id=workspace_id, leg_id=leg_id)
            if current["state"] == "running":
                await design_legs.mark_leg_awaiting_user(
                    conn, workspace_id=workspace_id, leg_id=leg_id
                )

    async def _project_committed(
        self,
        *,
        committed: AgentTurnOutcome,
        submission: AgentTurnSubmissionRow,
    ) -> str | None:
        if committed.finalization_ref is None:
            return None
        envelope = AgentFinalizeEnvelope.model_validate_json(
            await self._artifacts.read(committed.finalization_ref)
        )
        if envelope.user_message_artifact_ref is None:
            return None
        assistant_message = (
            await self._artifacts.read(envelope.user_message_artifact_ref)
        ).decode()
        await self._history.append(
            message_id=uuid5(submission.turn_id, "assistant"),
            turn_id=submission.turn_id,
            workspace_id=submission.workspace_id,
            thread_id=submission.thread_id,
            role="assistant",
            body_ref=envelope.user_message_artifact_ref,
        )
        return assistant_message

    async def _artifact(
        self,
        workspace_id: str,
        media_type: str,
        payload: object,
        *,
        project_id: str,
    ) -> ArtifactRef:
        return await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            project_bindings=((project_id, "design_leg_context"),),
        )

    async def _artifact_text(
        self,
        workspace_id: str,
        body: str,
        *,
        project_id: str,
    ) -> ArtifactRef:
        return await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=body.encode(),
            media_type="text/plain",
            project_bindings=((project_id, "design_leg_context"),),
        )
