"""Worker-side execution of one production project-conversation turn (FI Lane D D2).

The other half of :mod:`clue_api.agent_turn_submission`: the HTTP route captures a human turn and
enqueues an ``AGENT_TURN`` fleet task; this module is what claims it. Ratified §6-D1 — the turn
runs **here**, in the detached worker that already composes the gateway, the toolbelt and the
launch services, never in the HTTP process (Doc A: "the thread session never executes long-running
work… sessions attach/detach").

Three things live here, in order of who calls whom:

* :func:`build_agent_turn_work_handler` — the composition, called **once at worker startup**. The
  conversation engine, the recipe seam and the profile are built there and reused by every turn,
  which is the defect §1.2 records against the trial (per-request recomposition) closed for
  production.
* :class:`ProjectConversationTurnRunner` — per turn: read the durable submission (the authority for
  *who* is acting), start and drive this turn's C5 recipe execution to its interaction gate, build
  the constitution, and hand the request to the shared engine.
* :class:`AgentTurnWorkHandler` — the ``WorkHandler`` the fleet drains, and the owner of the
  hand-off to the thread's *next* turn.

Two authority rules this module exists to keep:

1. ``constitution.actor_id`` is the submitting human's Clue-owned ``platform_user.user_id``, read
   from ``agent_turn_submission``. Not from the task payload (a message is not evidence), not a
   literal like the trial's ``"stage0-trial-user"``, and never synthesised. The same pair is
   stamped onto the ``agent_turn`` row, which is what makes D1's ``turn-action:<turn_id>`` receipt
   resolve for a production turn at all.
2. The worker is a *service* principal executing somebody's turn — it holds no authority of its
   own, so everything it does is scoped by the durable row it read.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    ContextAssemblyPolicy,
    ContextLayer,
    DomainObjectRef,
    LayerBudget,
)
from clue_api.agent_execution_wiring import FreshWakeChildRunner
from clue_api.agent_platform_wiring import AgentPlatformComponents
from clue_api.agent_registry_wiring import PROJECT_CONVERSATION_SURFACE
from clue_api.agent_turn_submission import (
    AGENT_TURN_DEDUP_PREFIX,
    AgentTurnSubmissionRow,
    dispatch_next_thread_turn,
    get_submission,
    message_artifact_ref,
    submission_context_refs,
)
from clue_api.chat.composer_context import PROJECT_CONVERSATION_AGENT_PROFILE_ID
from clue_api.chat.turn_controls import stop_requested
from clue_api.chat.turn_events import prune_turn_events
from clue_api.chat.turn_stream import TurnStreamEmitter, TurnStreamPolicy
from clue_api.conversation_capture import (
    CONVERSATION_CONTEXT_BINDING_KIND,
    project_client_entity_id,
)
from clue_api.conversation_turns import (
    CONVERSATION_RECIPE_KEY,
    CONVERSATION_RECIPE_VERSION,
    ConversationTurnEngine,
    ConversationTurnResult,
    build_conversation_turn_engine,
)
from clue_core import ContextAssembly, EntityId, ExecutionId, MemoryType, operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_execution import (
    CompatibilityLoader,
    DbExecutionStarter,
    DbRecipeReader,
    ExecutionParameterStore,
    ExecutionStatus,
    RecipeExecutor,
    RecipeScopeType,
)
from clue_fleet import (
    FleetTaskKind,
    FleetTaskStatus,
    LeaseGeneration,
    WorkContext,
    WorkId,
    WorkQueue,
    WorkResult,
    acquire_work_lease,
    release_work_lease,
)
from clue_obs import get_logger
from clue_research.stage0 import current_kb_version
from clue_spine import get_project
from clue_toolbelt import ToolInvoker, ToolRegistry

log = get_logger("clue_api.agent_turn_fleet")

__all__ = [
    "PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS",
    "PROJECT_CONVERSATION_CARD_MEDIA_TYPE",
    "AgentTurnWorkHandler",
    "ProjectConversationTurnRunner",
    "TurnStopped",
    "UnknownTurnSubmission",
    "build_agent_turn_work_handler",
    "project_conversation_card_payload",
    "project_conversation_context_policy",
    "sweep_thread_dispatch",
]

#: This surface's L3 card — one card per surface (PC-C8 §10). Deliberately not the Stage-0 project
#: card: that one is compiled around a client entity and an interview, and a production project
#: conversation must be describable before either exists.
PROJECT_CONVERSATION_CARD_MEDIA_TYPE = "application/vnd.clue.project-conversation-card+json"

#: The conversation's own budget envelope. A conversation turn is model time, not research spend:
#: every externally-spending path this surface can reach is either withheld (the launch tools) or
#: governed by its own pre-spend gate and per-run cap. Sized like the trial's, and a module
#: constant rather than a setting because there is nothing here an operator should tune per
#: deployment without also revisiting the profile's round/timeout limits.
PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS = 1_000_000

_EXECUTION_NAMESPACE_KEY = "project-conversation@1"
_DRIVER_WORKER_ID = "agent-turn-recipe-driver"


class UnknownTurnSubmission(LookupError):
    """The task named a turn with no durable submission — nothing here may be invented."""


class TurnStopped(RuntimeError):
    """This generation attempt was cancelled by a durable stop request (charter §3.5).

    Not a failure: the platform did exactly what its user asked. It is raised so the surrounding
    handler stops treating the turn as in-flight, and it is finalized as a *done* task with a
    ``cancelled`` outcome — a ``FAILED`` task would misreport a deliberate stop as an error and
    invite an operator requeue of a turn nobody wants run.
    """


class ProjectConversationScopeError(ValueError):
    """The submission's project/thread scope does not agree with durable state."""


def project_conversation_context_policy() -> ContextAssemblyPolicy:
    """The seven-layer budget for a production conversation.

    Identical to the trial's shape and for the same reason: L6 (thread history) is the layer a real
    conversation grows into, so it gets the large share, and L3's card is bounded by construction.
    """

    return ContextAssemblyPolicy(
        version="project-conversation-context-v1",
        token_counter_version="utf8-bytes-v1",
        budgets=tuple(
            LayerBudget(layer=layer, max_tokens=budget)
            for layer, budget in zip(
                tuple(ContextLayer),
                (24_000, 12_000, 48_000, 16_000, 8_000, 96_000, 32_000),
                strict=True,
            )
        ),
    )


def project_conversation_card_payload(
    *,
    workspace_id: str,
    project_id: str,
    project_name: str,
    project_status: str,
    brand_id: str,
    product_id: str | None,
    thread_id: str,
    client_entity_id: str | None,
    client_kb_version: int | None,
) -> dict[str, JsonValue]:
    """The whole L3 card this surface puts in front of the model.

    Pure and separately callable so its shape is testable without standing up a project. It names
    what the model is scoped to and *admits what is absent*: a project whose Stage-0 recon has not
    run has no client knowledge base, and saying so is better than a card that quietly omits it and
    leaves the model to assume one exists.
    """

    return {
        "schema_version": "1",
        "card_kind": "project_conversation",
        "surface": PROJECT_CONVERSATION_SURFACE,
        "project": {
            "project_id": project_id,
            "name": project_name,
            "status": project_status,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "product_id": product_id,
        },
        "thread": {"thread_id": thread_id},
        "client_knowledge_base": (
            None
            if client_entity_id is None
            else {
                "client_entity_id": client_entity_id,
                "client_kb_version": client_kb_version,
            }
        ),
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


@dataclass(frozen=True, slots=True)
class _ProjectScope:
    project_id: str
    name: str
    status: str
    brand_id: str
    product_id: str | None
    client_entity_id: EntityId | None
    client_kb_version: int | None


class ProjectConversationTurnRunner:
    """Prepare one production conversation turn's trusted inputs and run it."""

    def __init__(
        self,
        *,
        engine: ConversationTurnEngine,
        executor: RecipeExecutor,
        recipes: DbRecipeReader,
        starter: DbExecutionStarter,
        parameters: ExecutionParameterStore,
        conn_factory: ConnFactory = transaction,
        streaming: bool = True,
        stream_policy: TurnStreamPolicy | None = None,
        stop_poll_interval_s: float = 0.25,
    ) -> None:
        self._engine = engine
        self._executor = executor
        self._recipes = recipes
        self._starter = starter
        self._parameters = parameters
        self._conn_factory = conn_factory
        # D3 streaming is on for the production conversation and switchable off in one place, so a
        # deployment that must fall back to non-streaming turns changes a flag, not a code path.
        self._streaming = streaming
        self._stream_policy = stream_policy
        self._stop_poll_interval_s = stop_poll_interval_s

    async def run(self, *, turn_id: UUID, workspace_id: str) -> ConversationTurnResult:
        async with self._conn_factory() as conn:
            submission = await get_submission(conn, workspace_id=workspace_id, turn_id=turn_id)
            if submission is None:
                raise UnknownTurnSubmission(
                    "no durable submission exists for this turn in this workspace"
                )
            scope = await self._load_scope(conn, submission)
            user_message_ref = await message_artifact_ref(conn, submission)
            submission_focus_refs = await submission_context_refs(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
            )
        # FI Lane D D3: open this attempt's stream *before* anything runs. The outbox itself decides
        # the attempt ordinal, so a re-claimed task after a crash opens a distinct attempt and
        # resets whatever the dead one left open — never splicing two generations (§3.3(6)).
        stream = (
            None
            if not self._streaming
            else await TurnStreamEmitter.open(
                workspace_id=workspace_id,
                project_id=scope.project_id,
                thread_id=submission.thread_id,
                turn_id=turn_id,
                conn_factory=self._conn_factory,
                policy=self._stream_policy,
            )
        )

        execution_id = ExecutionId(operation_id_from_key(str(turn_id), _EXECUTION_NAMESPACE_KEY))
        revision = await self._recipes.get_by_identity(
            scope_type=RecipeScopeType.SYSTEM,
            workspace_id=None,
            recipe_key=CONVERSATION_RECIPE_KEY,
            version=CONVERSATION_RECIPE_VERSION,
        )
        if revision is None:
            raise RuntimeError(
                f"promoted {CONVERSATION_RECIPE_KEY}@{CONVERSATION_RECIPE_VERSION} is not installed"
            )
        parameter_key, parameter_sha = await self._parameters.snapshot(
            workspace_id=workspace_id,
            parameters={},
        )
        # ``actor='human'`` because a human did start this: the execution exists because somebody
        # submitted a turn, and the recipe's interaction gate declares human authority.
        await self._starter.start(
            workspace_id=workspace_id,
            recipe_revision_id=revision.recipe_revision_id,
            parameters={},
            parameter_artifact_key=parameter_key,
            parameter_manifest_hash=parameter_sha,
            actor="human",
            execution_id=execution_id,
            project_id=scope.project_id,
        )
        status = await self._drive(execution_id)
        if status is not ExecutionStatus.AWAITING_INPUT:
            raise RuntimeError(
                "the conversation recipe did not reach its interaction gate "
                f"(status={status.value})"
            )
        resolved = self._engine.resolved
        resolved_profile_id = f"{resolved.profile_ref.name}@{resolved.profile_ref.version}"
        if resolved_profile_id != PROJECT_CONVERSATION_AGENT_PROFILE_ID:
            raise RuntimeError(
                "the advertised project-conversation profile differs from the promoted profile"
            )
        if (
            submission.agent_profile_id is not None
            and submission.agent_profile_id != resolved_profile_id
        ):
            raise RuntimeError("the submitted agent profile is not promoted for this surface")
        lease = self._engine.components.workspaces.acquire(
            workspace_id=workspace_id,
            project_id=scope.project_id,
            execution_id=execution_id,
            policy=resolved.profile.workspace,
        )
        focus_ref = DomainObjectRef(
            workspace_id=workspace_id,
            object_type="project",
            object_id=scope.project_id,
            version=None,
        )
        card_ref = await self._artifact(
            submission,
            scope,
            PROJECT_CONVERSATION_CARD_MEDIA_TYPE,
            project_conversation_card_payload(
                workspace_id=workspace_id,
                project_id=scope.project_id,
                project_name=scope.name,
                project_status=scope.status,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                thread_id=submission.thread_id,
                client_entity_id=(
                    None if scope.client_entity_id is None else str(scope.client_entity_id)
                ),
                client_kb_version=scope.client_kb_version,
            ),
        )
        budget_ref = await self._artifact(
            submission,
            scope,
            "application/vnd.clue.agent-budget-envelope+json",
            {
                "schema_version": "1",
                "limit_millicents": PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS,
                "external_research_budget_cents": "0",
                "scope": "conversation and Stage-0 domain writes only",
            },
        )
        manifest_ref = await self._artifact(
            submission,
            scope,
            "application/vnd.clue.agent-resource-manifest+json",
            resolved.resource_manifest.model_dump(mode="json"),
        )
        request = AgentTurnRequest(
            turn_id=turn_id,
            thread_id=submission.thread_id,
            constitution=AgentConstitution(
                workspace_id=workspace_id,
                project_id=scope.project_id,
                execution_id=execution_id,
                # The one identity rule of this module: the acting human, from the durable row.
                actor_id=submission.submitted_by_user_id,
                role=AgentRole.HEAD_OF_ABM,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                client_entity_id=(
                    None if scope.client_entity_id is None else str(scope.client_entity_id)
                ),
                workspace_root_id=lease.identity.workspace_root_id,
                project_card_ref=card_ref,
                budget_envelope_ref=budget_ref,
                profile_ref=resolved.profile_ref,
                resource_manifest_ref=manifest_ref,
                resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                focus_refs=(focus_ref,),
            ),
            user_message_artifact_ref=user_message_ref,
            focus_refs=submission_focus_refs,
            requested_at=submission.requested_at,
        )
        result = await self._execute_watched(
            request=request,
            lease=lease,
            submission=submission,
            stream=stream,
        )
        if result.outcome.status is AgentExecutionStatus.COMPLETED:
            await self._complete_recipe(execution_id)
        return result

    async def _execute_watched(
        self,
        *,
        request: AgentTurnRequest,
        lease: object,
        submission: AgentTurnSubmissionRow,
        stream: TurnStreamEmitter | None,
    ) -> ConversationTurnResult:
        """Run the turn, racing it against a durable **stop** request (charter §3.5).

        Stop cannot be an interrupt from the web process — by ratified §6-D1 that process does not
        even compose the model plane — so it is a durable row plus a bounded observation here. The
        cancellation window is therefore one poll interval plus whatever the in-flight ``await``
        takes to unwind, and it is deliberately narrow in scope:

        * only **this** generation attempt is cancelled;
        * governed tool effects that already committed stay committed — they are receipts of things
          that really happened, and "undo" is not a property this platform claims;
        * a detached research run keeps running (suspending one is the supervisor tool's job);
        * the partial text stays in the outbox for audit, and no ``text.end`` is ever emitted for
          it, so a stopped attempt can never be mistaken for a finished answer (§3.3(8)).
        """

        async def _execute() -> ConversationTurnResult:
            return await self._engine.execute(
                request=request,
                lease=lease,  # type: ignore[arg-type]
                budget_limit_millicents=PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS,
                submitted_by_user_id=submission.submitted_by_user_id,
                submitted_via_membership_id=submission.submitted_via_membership_id,
                stream=stream,
            )

        if stream is None or self._stop_poll_interval_s <= 0:
            return await _execute()

        turn = asyncio.create_task(_execute())
        watcher = asyncio.create_task(
            self._await_stop(
                workspace_id=submission.workspace_id,
                turn_id=request.turn_id,
                generation_attempt_id=stream.generation_attempt_id,
            )
        )
        done, _pending = await asyncio.wait({turn, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if turn in done:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            return turn.result()
        turn.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await turn
        # The cancelled task passed through the generic runtime unwinder, which cannot know
        # whether cancellation meant a user Stop or a process/lease failure. This runner owns that
        # distinction, so its later terminal journal event deliberately supersedes the generic
        # abandoned marker with the durable truth.
        await self._engine.components.turns.mark_cancelled(
            turn_id=request.turn_id,
            workspace_id=submission.workspace_id,
        )
        await stream.turn_cancelled()
        log.info(
            "agent_turn.stopped",
            turn_id=str(request.turn_id),
            workspace_id=submission.workspace_id,
            generation_attempt_id=str(stream.generation_attempt_id),
        )
        raise TurnStopped("this generation attempt was stopped by its submitter")

    async def _await_stop(
        self,
        *,
        workspace_id: str,
        turn_id: UUID,
        generation_attempt_id: UUID,
    ) -> None:
        """Poll the durable control table until this attempt is asked to stop."""

        while True:
            await asyncio.sleep(self._stop_poll_interval_s)
            async with self._conn_factory() as conn:
                if await stop_requested(
                    conn,
                    workspace_id=workspace_id,
                    turn_id=turn_id,
                    generation_attempt_id=generation_attempt_id,
                ):
                    return

    async def _complete_recipe(self, execution_id: ExecutionId) -> None:
        """Close this turn's interaction gate so its execution reaches a terminal state.

        ``actor='human'`` matches the gate's declared authority in ``recipe0-stage0`` — the human
        who submitted the turn is the one whose interaction just ended. (The trial passes
        ``'agent'`` here against the same human-authority gate; that mismatch is the trial's, and
        D2 does not inherit it.)
        """

        await self._executor.decide_gate(
            execution_id=execution_id,
            node_key="stage0_interactions",
            actor="human",
            decision="complete",
        )
        status = await self._drive(execution_id)
        if status is not ExecutionStatus.COMPLETED:
            raise RuntimeError("a completed conversation turn did not complete its C5 recipe")

    async def _drive(self, execution_id: ExecutionId) -> ExecutionStatus:
        async with self._conn_factory() as conn:
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id=_DRIVER_WORKER_ID,
            )
        if lease is None:
            raise RuntimeError("this conversation execution is owned by another live worker")
        try:
            result = await self._executor.execute(
                execution_id,
                worker_id=_DRIVER_WORKER_ID,
                lease_generation=lease.generation,
            )
            return result.status
        finally:
            async with self._conn_factory() as conn:
                await release_work_lease(
                    conn,
                    work_id=WorkId(execution_id),
                    worker_id=_DRIVER_WORKER_ID,
                    generation=LeaseGeneration(lease.generation),
                )

    async def _artifact(
        self,
        submission: AgentTurnSubmissionRow,
        scope: _ProjectScope,
        media_type: str,
        payload: object,
    ) -> ArtifactRef:
        return await self._engine.artifacts.persist_body(
            workspace_id=submission.workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            subject_bindings=(
                ()
                if scope.client_entity_id is None
                else ((UUID(str(scope.client_entity_id)), CONVERSATION_CONTEXT_BINDING_KIND),)
            ),
            project_bindings=((scope.project_id, "project_conversation_context"),),
        )

    async def _load_scope(
        self,
        conn: AsyncConnection,
        submission: AgentTurnSubmissionRow,
    ) -> _ProjectScope:
        project = await get_project(conn, submission.project_id)
        if project is None or project.workspace_id != submission.workspace_id:
            raise ProjectConversationScopeError("the submission names no project in its workspace")
        entity_id = await project_client_entity_id(
            conn,
            workspace_id=submission.workspace_id,
            project_id=submission.project_id,
        )
        kb_version = (
            None
            if entity_id is None
            else await current_kb_version(
                conn,
                entity_id,
                workspace_id=submission.workspace_id,
                product_id=project.product_id,
            )
        )
        return _ProjectScope(
            project_id=project.project_id,
            name=project.name,
            status=project.status,
            brand_id=project.brand_id,
            product_id=project.product_id,
            client_entity_id=entity_id,
            client_kb_version=kb_version,
        )


class AgentTurnWorkHandler:
    """The ``AGENT_TURN`` fleet handler: run one turn, then hand the thread to its next one.

    It finalizes its **own** task (``task_finalized=True``) rather than letting the worker shell do
    it, for one structural reason: the next turn of this thread may only be offered once *this*
    task is terminal, because "is a task in flight for this thread" is exactly what
    :func:`~clue_api.agent_turn_submission.dispatch_next_thread_turn` reads. Finishing first and
    dispatching second is what keeps the chain going without ever having two live tasks on one
    thread.

    A failure is recorded as ``FAILED`` and the thread still moves on. That is deliberate: the
    fleet's doctrine is that a failed task is retried only by an explicit requeue, never silently,
    and a turn that cannot succeed must not block every later turn of the conversation behind it.
    A *crash* is the other case entirely — the task stays ``claimed``, the staleness window hands
    it to another worker as a distinct attempt, and the committed-outcome short-circuit guarantees
    that attempt converges on the one outcome rather than executing the turn twice.
    """

    def __init__(
        self,
        *,
        runner: ProjectConversationTurnRunner,
        queue: WorkQueue,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._runner = runner
        self._queue = queue
        self._conn_factory = conn_factory

    @property
    def kind(self) -> FleetTaskKind:
        return FleetTaskKind.AGENT_TURN

    async def handle(self, context: WorkContext) -> WorkResult:
        turn_id = UUID(str(context.payload["turn_id"]))
        workspace_id = str(context.payload["workspace_id"])
        thread_id = str(context.payload["thread_id"])
        references: dict[str, JsonValue] = {"turn_id": str(turn_id)}
        try:
            result = await self._runner.run(turn_id=turn_id, workspace_id=workspace_id)
        except TurnStopped:
            # A stop is an executed instruction, not an error: the task is DONE, the turn carries
            # its own ``turn.cancelled`` event, and the thread moves on to its next turn.
            log.info("agent_turn.cancelled", turn_id=str(turn_id), workspace_id=workspace_id)
            outcome = "cancelled"
            status = FleetTaskStatus.DONE
            references["status"] = "cancelled"
        except Exception as error:  # noqa: BLE001 — recorded as a failed task, never swallowed
            log.exception(
                "agent_turn.failed",
                turn_id=str(turn_id),
                workspace_id=workspace_id,
                thread_id=thread_id,
            )
            outcome = "error"
            status = FleetTaskStatus.FAILED
            references["error"] = type(error).__name__
        else:
            outcome = result.outcome.status.value
            status = FleetTaskStatus.DONE
            references["status"] = result.outcome.status.value
            references["replayed"] = result.replayed
        finalized = await self._queue.finish(
            task_id=context.task_id,
            worker_id=context.worker_id,
            status=status,
            result_ref={"outcome": outcome, **references},
        )
        if not finalized:
            # Fenced out (a stale reclaim took the task while this attempt ran). The new owner's
            # outcome stands and the new owner will dispatch; this attempt must not.
            log.warning(
                "agent_turn.fenced_out",
                turn_id=str(turn_id),
                workspace_id=workspace_id,
            )
            return WorkResult(outcome="fenced_out", references=references, task_finalized=True)
        async with self._conn_factory() as conn:
            await dispatch_next_thread_turn(
                conn,
                workspace_id=workspace_id,
                thread_id=thread_id,
            )
        return WorkResult(outcome=outcome, references=references, task_finalized=True)


_SWEEP_THREADS_SQL = text(
    """
    SELECT DISTINCT s.workspace_id, s.thread_id
    FROM agent_turn_submission s
    WHERE NOT EXISTS (
        SELECT 1 FROM fleet_task f
        WHERE f.kind = CAST('agent_turn' AS fleet_task_kind)
          AND f.dedup_key = :prefix || s.turn_id::text
    )
    ORDER BY s.workspace_id, s.thread_id
    LIMIT :thread_limit
    """
)


async def sweep_thread_dispatch(
    conn_factory: ConnFactory = transaction,
    *,
    thread_limit: int = 200,
) -> int:
    """Offer the next turn of every thread holding an **undispatched** submission. Returns how many.

    The self-heal for the narrow gap the D2 review recorded: the handler finalizes its own task and
    *then* dispatches the thread's next turn, so a process death between those two steps leaves a
    queued submission with no task, waiting until that thread's next POST. Dispatch-on-attach (the
    stream surface) covers a user who is looking at the conversation; this covers the one who is
    not.

    Safe to call at any cadence and from any process: :func:`dispatch_next_thread_turn` takes the
    per-thread advisory lock and refuses when a task is already in flight, so a sweep racing a POST
    or a worker cannot produce a second live turn on one thread.
    """

    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _SWEEP_THREADS_SQL,
                    {"prefix": AGENT_TURN_DEDUP_PREFIX, "thread_limit": thread_limit},
                )
            )
            .mappings()
            .all()
        )
    dispatched = 0
    for row in rows:
        async with conn_factory() as conn:
            offered = await dispatch_next_thread_turn(
                conn,
                workspace_id=str(row["workspace_id"]),
                thread_id=str(row["thread_id"]),
            )
        if offered is not None:
            dispatched += 1
            log.info(
                "agent_turn.dispatch_swept",
                workspace_id=str(row["workspace_id"]),
                thread_id=str(row["thread_id"]),
                turn_id=str(offered),
            )
    return dispatched


async def sweep_turn_stream_retention(
    conn_factory: ConnFactory = transaction,
    *,
    retention_s: float,
) -> int:
    """Prune the turn outbox past its replay window (§3.3(7)). Returns the frames deleted.

    Only whole *terminal* turns are pruned, so a live attempt is never truncated under an attached
    consumer, and nothing durable is lost: a consumer whose cursor aged out is told to re-fetch the
    canonical message, which is where the truth lived all along.
    """

    async with conn_factory() as conn:
        return await prune_turn_events(conn, retention_s=retention_s)


def build_agent_turn_work_handler(
    *,
    components: AgentPlatformComponents,
    tools: ToolRegistry,
    tool_invoker: ToolInvoker,
    executor: RecipeExecutor,
    compatibility: CompatibilityLoader,
    recipes: DbRecipeReader,
    starter: DbExecutionStarter,
    parameters: ExecutionParameterStore,
    memory: ContextAssembly,
    queue: WorkQueue,
    child_runner: FreshWakeChildRunner | None = None,
    conn_factory: ConnFactory = transaction,
    streaming: bool = True,
    stream_policy: TurnStreamPolicy | None = None,
    stop_poll_interval_s: float = 0.25,
) -> AgentTurnWorkHandler:
    """Compose the ``AGENT_TURN`` handler **once**, at worker startup.

    Everything expensive is built here and captured in the closure of one engine: the resolved
    profile and its manifest, the context assembler, the deepagent runtime. A turn then costs a
    submission read, a recipe start, three content-addressed artifacts and the model rounds — not a
    second composition of the whole platform.
    """

    engine = build_conversation_turn_engine(
        surface=PROJECT_CONVERSATION_SURFACE,
        components=components,
        tools=tools,
        tool_invoker=tool_invoker,
        executor=executor,
        compatibility=compatibility,
        memory=memory,
        requested_memory_types=(MemoryType.PREFERENCE, MemoryType.BEHAVIORAL_LEARNING),
        context_policy=project_conversation_context_policy(),
        child_runner=child_runner,
        conn_factory=conn_factory,
    )
    return AgentTurnWorkHandler(
        runner=ProjectConversationTurnRunner(
            engine=engine,
            executor=executor,
            recipes=recipes,
            starter=starter,
            parameters=parameters,
            conn_factory=conn_factory,
            streaming=streaming,
            stream_policy=stream_policy,
            stop_poll_interval_s=stop_poll_interval_s,
        ),
        queue=queue,
        conn_factory=conn_factory,
    )
