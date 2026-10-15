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
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, TypeVar
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentModelProvider,
    AgentProfileRegistry,
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    ContextAssemblyPolicy,
    ContextLayer,
    DomainObjectRef,
    LayerBudget,
    MountRequest,
    ProjectContextArtifact,
)
from clue_agents.bridge import process_bridge
from clue_api.account_deep_steering_context import prepare_account_deep_steering_context
from clue_api.agent_execution_wiring import FreshWakeChildRunner
from clue_api.agent_gate import gate_answer_for_turn
from clue_api.agent_platform_wiring import AgentPlatformComponents
from clue_api.agent_registry_wiring import PROJECT_CONVERSATION_SURFACE
from clue_api.agent_turn_scope_pin import (
    AgentTurnScopePinRow,
    get_agent_turn_scope_pin,
    load_or_create_agent_turn_scope_pin,
)
from clue_api.agent_turn_submission import (
    AGENT_TURN_DEDUP_PREFIX,
    AgentTurnSubmissionRow,
    dispatch_next_thread_turn,
    get_submission,
    lock_thread_queue,
    message_artifact_ref,
    submission_attachment_refs,
    submission_context_refs,
)
from clue_api.arv2.discovery_store import release_discovery_for_turn
from clue_api.arv2.icp_confirmation import ProjectIcpPin, current_project_icp_pin
from clue_api.brand_knowledge_context import (
    BRAND_KNOWLEDGE_INDEX_CARD_MEDIA_TYPE,
    ConfirmedIcpRef,
    PinnedDocument,
    compile_brand_knowledge_index_card,
    confirmed_icp_for_project,
    load_or_create_knowledge_pin,
    read_pinned_documents,
)
from clue_api.brand_library import ensure_brand_library
from clue_api.chat.composer_context import PROJECT_CONVERSATION_AGENT_PROFILE_ID
from clue_api.chat.interrupted_turn import commit_interrupted_turn, recover_interrupted_answer
from clue_api.chat.turn_controls import stop_requested
from clue_api.chat.turn_events import prune_turn_events
from clue_api.chat.turn_stream import TurnStreamEmitter, TurnStreamPolicy
from clue_api.context_observability import record_context_card
from clue_api.conversation_capture import (
    CONVERSATION_CONTEXT_BINDING_KIND,
    project_client_entity_id,
)
from clue_api.conversation_naming import ConversationNamer
from clue_api.conversation_turns import (
    CONVERSATION_RECIPE_KEY,
    CONVERSATION_RECIPE_VERSION,
    ConversationTurnEngine,
    ConversationTurnResult,
    build_conversation_turn_engine,
)
from clue_api.design_leg_wiring import (
    DesignLegExitJudge,
    DesignLegFinisher,
    DesignLegLaneDriver,
    DesignLegTurnRunner,
)
from clue_api.frontend_read import latest_project_run_context
from clue_api.langfuse_callbacks import build_langfuse_callbacks
from clue_api.product_management import recent_change_lines
from clue_api.project_attachments import sync_project_attachments
from clue_api.project_context_files import (
    PROJECT_LIBRARY_INDEX_CARD_MEDIA_TYPE,
    CompiledProjectFile,
    load_or_create_project_files_pin,
    read_pinned_project_files,
)
from clue_api.project_library import (
    LIBRARY_INDEX_PATH,
    ProjectLibrarySnapshot,
    compile_project_library,
    ensure_project_library,
    installed_project_library_digest,
    materialize_pinned_project_library,
    pinned_library_digest,
)
from clue_api.project_root_writer import (
    ProjectRootWriter,
    bridge_bound_artifact_reader,
    bridge_transaction,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import ContextAssembly, EntityId, ExecutionId, MemoryType, operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_design import legs as design_leg_dal
from clue_design.exit_judgment import (
    ExitJudgment,
    parse_exit_judgment,
    render_exit_judgment_prompt,
)
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
from clue_obs.langfuse import observation, propagate_trace
from clue_projections import (
    PROJECT_CONVERSATION_CARD_MEDIA_TYPE,
    compile_project_conversation_card,
)
from clue_research.stage0 import current_kb_version
from clue_spine import ProjectProductSet, current_project_product_set, get_project
from clue_storage import ArtifactNotFound, StorageBackend
from clue_toolbelt import ToolInvoker, ToolRegistry

log = get_logger("clue_api.agent_turn_fleet")

__all__ = [
    "PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS",
    "PROJECT_CONVERSATION_CARD_MEDIA_TYPE",
    "AgentTurnWorkHandler",
    "ProjectConversationTurnRunner",
    "RequiredTurnArtifactMissing",
    "TurnStopped",
    "UnknownTurnSubmission",
    "build_agent_turn_work_handler",
    "project_conversation_card_payload",
    "project_conversation_context_policy",
    "sweep_thread_dispatch",
]

#: The conversation's own budget envelope. A conversation turn is model time, not research spend:
#: every externally-spending path this surface can reach is either withheld (the launch tools) or
#: governed by its own pre-spend gate and per-run cap. Sized like the trial's, and a module
#: constant rather than a setting because there is nothing here an operator should tune per
#: deployment without also revisiting the profile's round/timeout limits.
PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS = 1_000_000

_EXECUTION_NAMESPACE_KEY = "project-conversation@1"
_DRIVER_WORKER_ID = "agent-turn-recipe-driver"
REQUIRED_CONTEXT_ARTIFACT_MISSING = "required_context_artifact_missing"

#: What one watched turn body returns — ``ConversationTurnResult`` on the head-of-abm path,
#: ``DesignLegTurnResult`` on the design path (P3.4's routing rule selects the body).
_ResultT = TypeVar("_ResultT")


class UnknownTurnSubmission(LookupError):
    """The task named a turn with no durable submission — nothing here may be invented."""


class TurnStopped(RuntimeError):
    """This generation attempt was cancelled by a durable stop request (charter §3.5).

    Not a failure: the platform did exactly what its user asked. It is raised so the surrounding
    handler stops treating the turn as in-flight, and it is finalized as a *done* task with a
    ``cancelled`` outcome — a ``FAILED`` task would misreport a deliberate stop as an error and
    invite an operator requeue of a turn nobody wants run.
    """


class RequiredTurnArtifactMissing(RuntimeError):
    """The exact current/history bytes required for this turn no longer exist.

    This is terminal and non-retryable for the captured turn: a digest can verify recovered bytes
    but cannot recreate them. The exception deliberately carries no artifact key into the task's
    public result; the durable journal and SSE use one stable failure code instead.
    """


class ProjectConversationScopeError(ValueError):
    """The submission's project/thread scope does not agree with durable state."""


def project_conversation_context_policy() -> ContextAssemblyPolicy:
    """The seven-layer budget for a production conversation.

    Identical to the trial's shape and for the same reason: L6 (thread history) is the layer a real
    conversation grows into, so it gets the large share, and L3's card is bounded by construction.

    L1 is 40,000 bytes under the ``utf8-bytes-v1`` counter. It holds exactly one candidate — the
    resolved system prompt, which is the profile's prompt body plus the generated capability map
    (:class:`clue_agents.context.IdentityLayerSource`) — so the number is a direct statement of how
    large a disclosed profile is expected to grow. The v1 number of 24,000 was set when the Head of
    ABM disclosed a handful of skills; the fifteen-chapter operating manual took the resolved
    prompt to ~23.7 KB and the turn died at assembly with 273 bytes to spare, because the budget
    was then a gate. It is not one any more (v3, founder ruling 2026-09-14): every layer is
    assembled whole and an overrun is logged, so these seven numbers say what we *expect* a layer
    to cost and nothing more. ``tests/agents/test_manual_drift.py`` reports the prompt's size
    against this one so growth is seen offline rather than guessed at.
    """

    return ContextAssemblyPolicy(
        version="project-conversation-context-v3",
        token_counter_version="utf8-bytes-v1",
        budgets=tuple(
            LayerBudget(layer=layer, max_tokens=budget)
            for layer, budget in zip(
                tuple(ContextLayer),
                (40_000, 12_000, 48_000, 16_000, 8_000, 96_000, 32_000),
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
    client_knowledge_available: bool = False,
    stage0_project_state_available: bool = False,
) -> dict[str, JsonValue]:
    """The always-present v2 conversation envelope this surface puts in L3.

    The account-wide Client-KB and active-project Stage-0 state are independently owned artifacts,
    never nested here. Availability describes what the worker actually composed for this turn;
    S1 therefore defaults both to unavailable until S3 attaches those production artifacts.
    """

    card = compile_project_conversation_card(
        workspace_id=workspace_id,
        project_id=project_id,
        project_name=project_name,
        project_status=project_status,
        brand_id=brand_id,
        confirmed_product_id=product_id,
        thread_id=thread_id,
        client_knowledge_available=client_knowledge_available,
        stage0_project_state_available=stage0_project_state_available,
    )
    return card.model_dump(mode="json", exclude_none=False)


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
    product_kb_version: int | None

    @classmethod
    def from_pin(cls, pin: AgentTurnScopePinRow) -> _ProjectScope:
        return cls(
            project_id=pin.project_id,
            name=pin.project_name,
            status=pin.project_status,
            brand_id=pin.brand_id,
            product_id=pin.product_id,
            client_entity_id=pin.client_entity_id,
            client_kb_version=pin.client_kb_version,
            product_kb_version=pin.product_kb_version,
        )


@dataclass(frozen=True, slots=True)
class _ContextCardObservation:
    card_kind: str
    schema_version: str
    content_sha256: str
    omitted_count: int


@dataclass(frozen=True, slots=True)
class _ProjectContextBundle:
    """The conditional half of one atomically constituted production L3 bundle.

    Since ARV2 onboarding O6 (ruling D5) the conditional half is the brand-knowledge index over
    this turn's pinned documents and the project-files index over its pinned project files, plus
    whatever account-deep steering the focus refs earn. A turn composed without a blob backend
    (diagnostic fixtures) is the one valid empty bundle; the v2 conversation envelope is still
    compiled only *after* this bundle succeeds, so it can never advertise an artifact that failed
    to compile or persist.
    """

    artifacts: tuple[ProjectContextArtifact, ...] = ()
    observations: tuple[_ContextCardObservation, ...] = ()

    def artifact(self, name: str) -> ProjectContextArtifact | None:
        return next((item for item in self.artifacts if item.name == name), None)


def _bounded_omission_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


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
        design_legs: DesignLegTurnRunner | None = None,
        storage: StorageBackend | None = None,
        conn_factory: ConnFactory = transaction,
        project_writer_conn_factory: ConnFactory = bridge_transaction,
        streaming: bool = True,
        stream_policy: TurnStreamPolicy | None = None,
        stop_poll_interval_s: float = 0.25,
    ) -> None:
        self._engine = engine
        self._executor = executor
        self._recipes = recipes
        self._starter = starter
        self._parameters = parameters
        self._design_legs = design_legs
        # ARV2 onboarding O6: the blob backend the pinned knowledge documents are read from. A
        # runner composed without one (diagnostic fixtures) composes no knowledge at all and says
        # so once per turn — it never falls back to "current" documents nobody pinned.
        self._storage = storage
        self._conn_factory = conn_factory
        # The project mount's writer opens its *own* transaction, on the bridge loop, because the
        # deepagents backend calls it synchronously from a worker thread and a connection belongs
        # to the loop that made it. It is therefore a second factory, never ``conn_factory``: that
        # one's engine is this process's, and crossing the two loops is the exact hazard the
        # bridge exists to avoid. A test replaces it with a factory yielding its own connection.
        self._project_writer_conn_factory = project_writer_conn_factory
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
            user_message_ref = await message_artifact_ref(conn, submission)
            submission_focus_refs = await submission_context_refs(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
            )
            # The files the human attached to this exact message, in the order they attached
            # them. Read here beside the focus refs because both are the same durable fact about
            # one submission: what the person sent with their words.
            submission_attachments = await submission_attachment_refs(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
            )
            # Existing pins are read before replay so a committed retry can prove which scope the
            # original attempt used without consulting mutable project/recon state. A legacy
            # committed turn can predate S3.1 and legitimately have no receipt; never invent one
            # from today's state and mislabel it as the original.
            scope_pin = await get_agent_turn_scope_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=turn_id,
            )
            # P3.4 (PD-part3 §1-D1) — THE routing rule, one indexed read: an open design leg on
            # the thread receives this message; otherwise head-of-abm does. No other routing
            # input exists, and no LLM is in the loop.
            open_leg = await design_leg_dal.get_open_leg_for_thread(
                conn,
                workspace_id=workspace_id,
                thread_id=submission.thread_id,
            )
            # The finding-C amendment's worker half (PD-part3 §1-D1 amendment): a gate answer
            # belongs to head-of-abm regardless of leg state. The route already refuses a fresh
            # answer while a leg is open, but it cannot see the future — an answer accepted
            # first and QUEUED BEHIND a turn that then opened a leg would otherwise reach the
            # design agent as canonical gate-answer JSON. The answer row is the durable proof.
            if open_leg is not None and open_leg.get("opened_by_turn_id") == str(turn_id):
                # The head-of-abm turn that OPENED this leg is never a leg turn. Only its retry
                # (a crash or lost lease after the leg was born) can arrive here, and it must
                # replay as the committed head-of-abm turn it is; routed to the leg it collided
                # with its own durable rows and failed (incident 2026-09-29).
                open_leg = None
            elif open_leg is not None and (
                await gate_answer_for_turn(conn, workspace_id=workspace_id, turn_id=turn_id)
                is not None
            ):
                open_leg = None
            elif open_leg is None:
                # P3.7 crash-window re-entry: a design turn that CLOSED its leg via the §2.2
                # exit bridge and died before finalizing finds no open leg on retry — but it
                # is still a design turn, and re-running it as head-of-abm would collide with
                # its own durable rows. The exit journal names its closer; deliver it back.
                open_leg = await design_leg_dal.get_leg_closed_by_turn(
                    conn,
                    workspace_id=workspace_id,
                    turn_id=turn_id,
                )
        async with self._conn_factory() as conn:
            pending_stop = await stop_requested(conn, workspace_id=workspace_id, turn_id=turn_id)
        if pending_stop:
            # Recovery must reconcile Stop before opening a new attempt or calling any model.
            await self._finish_stop(submission=submission, turn_id=turn_id, stream=None)
        # FI Lane D D3: open this attempt's stream *before* anything runs. The outbox itself decides
        # the attempt ordinal, so a re-claimed task after a crash opens a distinct attempt and
        # resets whatever the dead one left open — never splicing two generations (§3.3(6)).
        stream = (
            None
            if not self._streaming
            else await TurnStreamEmitter.open(
                workspace_id=workspace_id,
                project_id=submission.project_id,
                thread_id=submission.thread_id,
                turn_id=turn_id,
                conn_factory=self._conn_factory,
                policy=self._stream_policy,
            )
        )
        if open_leg is not None:
            # The design deepagent owns the thread while its leg is open. None of the
            # head-of-abm machinery below — profile resolution, the C5 recipe, the
            # conversation engine — runs for this turn.
            if self._design_legs is None:
                raise RuntimeError(
                    "this thread has an open design leg but the worker composed no design "
                    "leg runner; set CLUE_DESIGN_RUNTIME_ENABLED on the fleet deployment"
                )
            # A design turn is still a production turn: it pins (or replays) the same immutable
            # S3.1 scope receipt as the head-of-abm path, so its card describes the scope the
            # turn actually ran under — replay-stable across retries.
            if scope_pin is None:
                async with self._conn_factory() as conn:
                    scope_pin, _ = await load_or_create_agent_turn_scope_pin(
                        conn,
                        submission=submission,
                    )
            scope = _ProjectScope.from_pin(scope_pin)
            design_legs_runner = self._design_legs
            leg_result = await self._execute_watched(
                run=lambda: design_legs_runner.run_leg_turn(
                    submission=submission,
                    leg=open_leg,
                    user_message_ref=user_message_ref,
                    focus_refs=submission_focus_refs,
                    card_payload=project_conversation_card_payload(
                        workspace_id=workspace_id,
                        project_id=scope.project_id,
                        project_name=scope.name,
                        project_status=scope.status,
                        brand_id=scope.brand_id,
                        product_id=scope.product_id,
                        thread_id=submission.thread_id,
                    ),
                    stream=stream,
                    scope_pin=scope_pin,
                ),
                submission=submission,
                turn_id=turn_id,
                stream=stream,
            )
            return ConversationTurnResult(
                outcome=leg_result.outcome,
                assistant_message=leg_result.assistant_message,
                replayed=leg_result.replayed,
            )

        execution_id = ExecutionId(operation_id_from_key(str(turn_id), _EXECUTION_NAMESPACE_KEY))
        committed = await self._engine.replay_committed(
            turn_id=turn_id,
            workspace_id=workspace_id,
            project_id=submission.project_id,
            thread_id=submission.thread_id,
            actor_id=submission.submitted_by_user_id,
            user_message_artifact_ref=user_message_ref,
            stream=stream,
        )
        if committed is not None:
            if committed.outcome.status is AgentExecutionStatus.COMPLETED:
                await self._complete_recipe(
                    execution_id, turn_id=turn_id, actor_id=submission.submitted_by_user_id
                )
            log.info(
                "agent_turn.context_replayed",
                turn_id=str(turn_id),
                workspace_id=workspace_id,
                project_id=submission.project_id,
                scope_pin_available=scope_pin is not None,
                client_entity_id=(
                    None
                    if scope_pin is None or scope_pin.client_entity_id is None
                    else str(scope_pin.client_entity_id)
                ),
                client_kb_version=(None if scope_pin is None else scope_pin.client_kb_version),
                product_kb_version=(None if scope_pin is None else scope_pin.product_kb_version),
                knowledge_scope_policy_version=(
                    None if scope_pin is None else scope_pin.knowledge_scope_policy_version
                ),
            )
            return committed

        if scope_pin is None:
            async with self._conn_factory() as conn:
                scope_pin, created = await load_or_create_agent_turn_scope_pin(
                    conn,
                    submission=submission,
                )
            log.info(
                "agent_turn.scope_pinned",
                turn_id=str(turn_id),
                workspace_id=workspace_id,
                project_id=scope_pin.project_id,
                client_entity_id=(
                    None if scope_pin.client_entity_id is None else str(scope_pin.client_entity_id)
                ),
                client_kb_version=scope_pin.client_kb_version,
                product_kb_version=scope_pin.product_kb_version,
                knowledge_scope_policy_version=scope_pin.knowledge_scope_policy_version,
                created=created,
            )
        scope = _ProjectScope.from_pin(scope_pin)
        # ARV2 onboarding O6 (ruling D6): pin this turn's brand-knowledge document set before
        # anything is composed from it. Onboarding keeps publishing versions in the background, so
        # a turn that re-resolved "current" per attempt could seed one set, crash, and seed a
        # different set on the retry — the file the model was told to re-read would have moved.
        # Every later attempt reads the winner's row.
        documents: tuple[PinnedDocument, ...] = ()
        confirmed_icp: ConfirmedIcpRef | None = None
        product_set: ProjectProductSet | None = None
        product_changes: tuple[str, ...] = ()
        icp_pin: ProjectIcpPin | None = None
        knowledge_pin_created = False
        # What this turn's workspace mounts beside its thread root. A turn that composes no
        # knowledge has no library version to name, so it mounts nothing.
        mounts = MountRequest()
        if self._storage is None:
            log.info(
                "agent_turn.knowledge_not_composed",
                turn_id=str(turn_id),
                workspace_id=workspace_id,
                project_id=scope.project_id,
                brand_id=scope.brand_id,
            )
        else:
            async with self._conn_factory() as conn:
                knowledge_pin, knowledge_pin_created = await load_or_create_knowledge_pin(
                    conn,
                    workspace_id=workspace_id,
                    turn_id=turn_id,
                    brand_id=scope.brand_id,
                    project_id=scope.project_id,
                )
                documents = await read_pinned_documents(conn, self._storage, pin=knowledge_pin)
                product_set = await current_project_product_set(
                    conn,
                    workspace_id=workspace_id,
                    project_id=scope.project_id,
                )
                # Spec 2026-10-15 §8: the agent hears about merged, renamed and removed products.
                product_changes = await recent_change_lines(
                    conn, workspace_id=workspace_id, brand_id=scope.brand_id
                )
                # Founder rulings 2026-09-10: what this project's ICP *is* comes from its durable
                # pin, not from whatever the brand's documents currently claim.
                icp_pin = await current_project_icp_pin(
                    conn,
                    workspace_id=workspace_id,
                    project_id=scope.project_id,
                )
            confirmed_icp = confirmed_icp_for_project(
                documents,
                pinned_document_id=None if icp_pin is None else icp_pin.document_id,
            )
            # The same pinned bytes, written once per knowledge version beside the threads and
            # mounted read-only at ``brand/`` for every thread of every project of this brand.
            # It is materialized here, not seeded per turn: a present tree is never rewritten.
            brand_version = await ensure_brand_library(
                self._engine.components.workspaces,
                pin=knowledge_pin,
                documents=documents,
            )
            mounts = MountRequest(brand=(scope.brand_id, brand_version))
        # The project's own state (spec §4.1): status.md, decisions.md, the artifact index and
        # every document this project authored, compiled once beside the threads and mounted
        # read-only at ``project/``. The project moves while a turn runs — a discovery run
        # finishes, a decision is recorded, another thread's write refreshes the tree — so the
        # generation this turn composes against is recorded in its insert-once pin, and a later
        # attempt reads the pinned set rather than whatever is installed by then.
        project_library_index: bytes | None = None
        #: Set when this turn built a tree of its own; removed in the ``finally`` below.
        pinned_tree_name: str | None = None
        if self._storage is not None:
            # Bound once here so the compiler below closes over a backend, not over an attribute
            # whose declared type still admits ``None``.
            storage = self._storage
            compiled: ProjectLibrarySnapshot | None = None
            async with self._conn_factory() as conn:

                async def compile_library() -> Sequence[CompiledProjectFile]:
                    # Called at most once per turn, and only on the attempt that wins the pin.
                    # The whole generation is compiled here — the pin records the library's own
                    # files, ``index.json`` included — and the same snapshot installs the tree
                    # below, so one turn pays for one compile.
                    nonlocal compiled
                    compiled = await compile_project_library(
                        conn,
                        storage,
                        self._engine.artifacts,
                        workspace_id=workspace_id,
                        project_id=scope.project_id,
                    )
                    return compiled.files

                project_pin, project_pin_created = await load_or_create_project_files_pin(
                    conn,
                    self._engine.artifacts,
                    workspace_id=workspace_id,
                    turn_id=turn_id,
                    project_id=scope.project_id,
                    compile=compile_library,
                )
                project_files = await read_pinned_project_files(
                    conn, self._storage, pin=project_pin
                )
                if project_pin_created and compiled is not None:
                    # This attempt compiled the generation it pinned: install that exact snapshot,
                    # skipping a second identical compile inside ``ensure``.
                    library = await ensure_project_library(
                        conn,
                        storage,
                        self._engine.artifacts,
                        self._engine.components.workspaces,
                        workspace_id=workspace_id,
                        project_id=scope.project_id,
                        snapshot=compiled,
                    )
                    library_digest: str | None = library.digest
                else:
                    library_digest = None
            project_library_index = next(
                (file.body for file in project_files if file.ref.path == LIBRARY_INDEX_PATH),
                None,
            )
            if not project_pin_created:
                # A later attempt of this turn. The live library is shared and is refreshed
                # whenever the project moves, so it may no longer be the tree this turn pinned;
                # when it is not, the pinned generation is rebuilt as a tree of this turn's own
                # and mounted instead, so the model re-reads the files its receipt names.
                library_digest = pinned_library_digest(project_files)
                installed = await installed_project_library_digest(
                    self._engine.components.workspaces,
                    workspace_id=workspace_id,
                    project_id=scope.project_id,
                )
                if library_digest is not None and library_digest != installed:
                    pinned_tree_name = f"pinned-{turn_id.hex[:12]}"
                    await materialize_pinned_project_library(
                        self._engine.components.workspaces,
                        workspace_id=workspace_id,
                        project_id=scope.project_id,
                        name=pinned_tree_name,
                        files=project_files,
                        digest=library_digest,
                    )
                elif library_digest is None:
                    # A pin with no manifest — written before the library existed. There is
                    # nothing to replay from, so the live tree is the honest answer.
                    library_digest = installed
            # The mount is opened *versioned*: the model reads the project's tree as plain files
            # and a write under it is taken by this writer as a new version of the document that
            # path names. Exactly one writer is built per turn attempt and passed as one instance
            # — ``MountRequest`` compares by value, and a second, equal-but-distinct writer would
            # make two otherwise identical requests unequal.
            #
            # A replay attempt keeps its pinned tree *and* the writer (ruling P3-3): the pinned
            # generation is what the model re-reads, and the first accepted write reopens the
            # mount on the project's shared library, which is where the version it just minted
            # actually lives.
            project_writer = ProjectRootWriter(
                bridge=process_bridge(),
                storage=storage,
                # NOT ``self._engine.artifacts`` (ruling P3-14): that reader's connections are
                # this worker's, and ``refresh()`` reads the artifact index from the bridge loop.
                # One reader per loop, each built from that loop's own factory.
                artifacts=bridge_bound_artifact_reader(storage, self._project_writer_conn_factory),
                workspaces=self._engine.components.workspaces,
                workspace_id=workspace_id,
                brand_id=scope.brand_id,
                project_id=scope.project_id,
                turn_id=turn_id,
                user_id=submission.submitted_by_user_id,
                conn_factory=self._project_writer_conn_factory,
            )
            mounts = replace(mounts, project_library=True, project_writer=project_writer)
            if pinned_tree_name is not None:
                mounts = replace(mounts, project_library_name=pinned_tree_name)
            log.info(
                "agent_turn.project_library_ready",
                turn_id=str(turn_id),
                project_id=scope.project_id,
                library_sha256=library_digest,
                file_count=len(project_files),
                pin_created=project_pin_created,
                replayed_from_pin=pinned_tree_name is not None,
            )
        # Spec 2026-09-19 §3.2: every file attached in this project, byte for byte, beside the
        # threads. Synced here — on the worker that owns the workspace root — never by the API.
        # Unconditional: an attachment is the human's own file and does not depend on whether
        # this runner composes the project's knowledge library.
        async with self._conn_factory() as conn:
            await sync_project_attachments(
                self._engine.components.workspaces,
                self._engine.components.artifacts,
                conn,
                workspace_id=workspace_id,
                project_id=scope.project_id,
            )
        mounts = replace(mounts, attachments=True)
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
            thread_id=submission.thread_id,
            execution_id=execution_id,
            policy=resolved.profile.workspace,
            mounts=mounts,
        )
        try:
            focus_ref = DomainObjectRef(
                workspace_id=workspace_id,
                object_type="project",
                object_id=scope.project_id,
                version=None,
            )
            context_bundle = await self._compose_project_context(
                submission=submission,
                scope=scope,
                documents=documents,
                confirmed_icp=confirmed_icp,
                product_set=product_set,
                product_changes=product_changes,
                project_library_index=project_library_index,
                focus_refs=submission_focus_refs,
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
                    # Ruling D5: neither card is compiled onto this surface any more. The envelope
                    # says so honestly rather than advertising an artifact L3 does not carry.
                    client_knowledge_available=False,
                    stage0_project_state_available=False,
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
                    project_context_artifacts=context_bundle.artifacts,
                ),
                user_message_artifact_ref=user_message_ref,
                focus_refs=submission_focus_refs,
                attachment_refs=tuple(item.ref for item in submission_attachments),
                requested_at=submission.requested_at,
            )
            brand_knowledge_index = context_bundle.artifact("brand_knowledge_index")
            log.info(
                "agent_turn.context_composed",
                turn_id=str(turn_id),
                workspace_id=workspace_id,
                project_id=scope.project_id,
                brand_id=scope.brand_id,
                product_id=scope.product_id,
                client_entity_id=(
                    None if scope.client_entity_id is None else str(scope.client_entity_id)
                ),
                client_kb_version=scope.client_kb_version,
                product_kb_version=scope.product_kb_version,
                project_card_sha256=card_ref.sha256,
                brand_knowledge_documents=len(documents),
                brand_knowledge_index_sha256=(
                    None
                    if brand_knowledge_index is None
                    else brand_knowledge_index.artifact_ref.sha256
                ),
                knowledge_pin_created=knowledge_pin_created,
                client_knowledge_available=False,
                stage0_project_state_available=False,
            )
            observations = {item.card_kind: item for item in context_bundle.observations}
            self._observe_context_card(
                submission=submission,
                scope=scope,
                observation=_ContextCardObservation(
                    card_kind="project_conversation",
                    schema_version="2",
                    content_sha256=card_ref.sha256,
                    omitted_count=0,
                ),
            )
            self._observe_context_card(
                submission=submission,
                scope=scope,
                observation=observations.get("brand_knowledge_index"),
                card_kind="brand_knowledge_index",
                schema_version="1",
            )
            self._observe_context_card(
                submission=submission,
                scope=scope,
                observation=observations.get("project_library_index"),
                card_kind="project_library_index",
                schema_version="1",
            )
            result = await self._execute_watched(
                run=lambda: self._engine.execute(
                    request=request,
                    lease=lease,
                    budget_limit_millicents=PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS,
                    submitted_by_user_id=submission.submitted_by_user_id,
                    submitted_via_membership_id=submission.submitted_via_membership_id,
                    stream=stream,
                    # The exact mount table this turn's lease was acquired with, so the code
                    # sandbox binds the directories the model's own file tools see — including
                    # a replayed turn's pinned project tree — rather than re-deriving them.
                    mounts=mounts,
                ),
                submission=submission,
                turn_id=request.turn_id,
                stream=stream,
            )
            if result.outcome.status is AgentExecutionStatus.COMPLETED:
                await self._complete_recipe(
                    execution_id,
                    turn_id=request.turn_id,
                    actor_id=submission.submitted_by_user_id,
                )
            return result
        finally:
            lease.release()
            if pinned_tree_name is not None:
                # What this turn wrote, this turn removes: the replay tree exists only for the
                # length of the attempt that needed it, and the project's shared library — which
                # ``remove_project_tree`` refuses to touch — is untouched either way.
                self._engine.components.workspaces.remove_project_tree(
                    workspace_id, scope.project_id, pinned_tree_name
                )

    async def _compose_project_context(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        scope: _ProjectScope,
        documents: tuple[PinnedDocument, ...] = (),
        confirmed_icp: ConfirmedIcpRef | None = None,
        product_set: ProjectProductSet | None = None,
        product_changes: tuple[str, ...] = (),
        project_library_index: bytes | None = None,
        focus_refs: tuple[DomainObjectRef, ...] = (),
    ) -> _ProjectContextBundle:
        """Compile and persist the bounded index of this turn's pinned brand knowledge.

        Ruling D5: the Head of ABM does not open on four compiled cards any more — it opens on an
        *index* of the brand's own knowledge documents and reads the files it needs by path from
        ``brand/knowledge/``. ``documents`` are the exact bytes the turn's knowledge pin
        froze, so this method compiles nothing from mutable "current" state; a brand with no
        servable document yet composes honestly nothing.

        The project's own state is indexed the same way, from the same kind of pin — but its card
        is not compiled here at all: it is the *library's own manifest*, as this turn's pin froze
        it (``project_library_index``). The tree ships its manifest, the pin records it, and the
        opening context serves those exact bytes, so the card, the receipt and the files the model
        opens at ``project/`` cannot describe three different generations.
        """

        artifacts: list[ProjectContextArtifact] = []
        observations: list[_ContextCardObservation] = []
        if documents:
            card = compile_brand_knowledge_index_card(
                brand_id=scope.brand_id,
                documents=documents,
                confirmed_icp=confirmed_icp,
                product_set=product_set,
                recent_product_changes=product_changes,
            )
            index_ref = await self._artifact(
                submission,
                scope,
                BRAND_KNOWLEDGE_INDEX_CARD_MEDIA_TYPE,
                card.model_dump(mode="json", exclude_none=False),
                bind_project=False,
            )
            if index_ref.sha256 != card.content_sha256().removeprefix("sha256:"):
                raise RuntimeError(
                    "persisted brand-knowledge index differs from its compiled content hash"
                )
            artifacts.append(
                ProjectContextArtifact(
                    name="brand_knowledge_index",
                    artifact_ref=index_ref,
                    domain_ref=DomainObjectRef(
                        workspace_id=submission.workspace_id,
                        object_type="brand_knowledge_index",
                        object_id=scope.brand_id,
                        version=None,
                    ),
                )
            )
            observations.append(
                _ContextCardObservation(
                    card_kind=card.card_kind,
                    schema_version=card.schema_version,
                    content_sha256=index_ref.sha256,
                    omitted_count=card.omitted_count,
                )
            )

        if project_library_index is not None:
            project_ref = await self._artifact(
                submission,
                scope,
                PROJECT_LIBRARY_INDEX_CARD_MEDIA_TYPE,
                json.loads(project_library_index),
            )
            if project_ref.sha256 != hashlib.sha256(project_library_index).hexdigest():
                raise RuntimeError(
                    "persisted project-library index differs from the pinned manifest"
                )
            artifacts.append(
                ProjectContextArtifact(
                    name="project_library_index",
                    artifact_ref=project_ref,
                    domain_ref=DomainObjectRef(
                        workspace_id=submission.workspace_id,
                        object_type="project_library_index",
                        object_id=scope.project_id,
                        version=None,
                    ),
                )
            )
            observations.append(
                _ContextCardObservation(
                    card_kind="project_library_index",
                    schema_version="1",
                    content_sha256=project_ref.sha256,
                    omitted_count=0,
                )
            )

        if any(ref.object_type == "account" for ref in focus_refs):
            async with self._conn_factory() as conn:
                run_context = await latest_project_run_context(
                    conn,
                    workspace_id=submission.workspace_id,
                    project_id=scope.project_id,
                )
            if run_context is not None:
                artifacts.extend(
                    await prepare_account_deep_steering_context(
                        artifacts=self._engine.components.artifacts,
                        workspace_id=submission.workspace_id,
                        project_run_id=run_context.project_run_id,
                        conn_factory=self._conn_factory,
                    )
                )

        return _ProjectContextBundle(
            artifacts=tuple(artifacts),
            observations=tuple(observations),
        )

    @staticmethod
    def _observe_context_card(
        *,
        submission: AgentTurnSubmissionRow,
        scope: _ProjectScope,
        observation: _ContextCardObservation | None,
        card_kind: str | None = None,
        schema_version: str | None = None,
    ) -> None:
        kind = observation.card_kind if observation is not None else card_kind
        version = observation.schema_version if observation is not None else schema_version
        assert kind is not None and version is not None
        available = observation is not None
        omitted_count = 0 if observation is None else observation.omitted_count
        content_sha256 = None if observation is None else observation.content_sha256
        log.info(
            "agent_turn.context_card",
            turn_id=str(submission.turn_id),
            workspace_id=submission.workspace_id,
            project_id=scope.project_id,
            card_kind=kind,
            schema_version=version,
            content_sha256=content_sha256,
            available=available,
            omitted_count=omitted_count,
            client_kb_version=scope.client_kb_version,
            product_kb_version=scope.product_kb_version,
        )
        record_context_card(
            card_kind=kind,
            schema_version=version,
            available=available,
            omitted_count=omitted_count,
        )

    async def _execute_watched(
        self,
        *,
        run: Callable[[], Awaitable[_ResultT]],
        submission: AgentTurnSubmissionRow,
        turn_id: UUID,
        stream: TurnStreamEmitter | None,
    ) -> _ResultT:
        """Run the turn body, racing it against a durable **stop** request (charter §3.5).

        ``run`` is whichever turn body the routing rule selected — the head-of-abm conversation
        engine, or a design-leg turn (P3.4). The stop semantics, the exact-artifact boundary and
        the cancellation journaling are identical for both, which is why this wrapper takes a
        callable rather than knowing either body.

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

        async def _execute_with_artifact_boundary() -> _ResultT:
            try:
                return await run()
            except ArtifactNotFound as error:
                # Context and finalization artifacts are exact authority. Never invoke/continue
                # the model with a guessed replacement, and never leave an attached browser on a
                # non-terminal ``turn.started`` frame. The surrounding work handler will mark the
                # fleet task failed and dispatch the next queued submission.
                await self._engine.components.turns.mark_unfinalized(
                    turn_id=turn_id,
                    workspace_id=submission.workspace_id,
                    reason_code=REQUIRED_CONTEXT_ARTIFACT_MISSING,
                    abandoned=False,
                )
                if stream is not None:
                    await stream.turn_finished(
                        status="failed",
                        failure_code=REQUIRED_CONTEXT_ARTIFACT_MISSING,
                    )
                log.warning(
                    "agent_turn.required_artifact_missing",
                    turn_id=str(turn_id),
                    workspace_id=submission.workspace_id,
                )
                raise RequiredTurnArtifactMissing(
                    "required turn context is no longer available; start a new thread"
                ) from error

        turn = asyncio.create_task(_execute_with_artifact_boundary())
        watcher = asyncio.create_task(
            self._await_stop(
                workspace_id=submission.workspace_id,
                turn_id=turn_id,
                generation_attempt_id=None if stream is None else stream.generation_attempt_id,
            )
        )
        try:
            done, _pending = await asyncio.wait(
                {turn, watcher}, return_when=asyncio.FIRST_COMPLETED
            )
            async with self._conn_factory() as conn:
                stopped = await stop_requested(
                    conn, workspace_id=submission.workspace_id, turn_id=turn_id
                )
            if turn in done and not stopped:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
                return turn.result()
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            if self._design_legs is not None:
                await self._design_legs.request_stop_for_turn(
                    workspace_id=submission.workspace_id, turn_id=turn_id
                )
            turn.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await turn
            await self._finish_stop(submission=submission, turn_id=turn_id, stream=stream)
            raise AssertionError("stop reconciliation must terminate this turn")
        finally:
            for task in (watcher, turn):
                if not task.done():
                    task.cancel()
            for task in (watcher, turn):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _finish_stop(
        self, *, submission: AgentTurnSubmissionRow, turn_id: UUID, stream: TurnStreamEmitter | None
    ) -> None:
        if self._design_legs is not None:
            await self._design_legs.request_stop_for_turn(
                workspace_id=submission.workspace_id, turn_id=turn_id
            )
            await self._design_legs.await_stopped_turn(
                workspace_id=submission.workspace_id, turn_id=turn_id
            )
        async with self._conn_factory() as conn:
            acknowledged = bool(
                await conn.scalar(
                    text(
                        "SELECT 1 FROM agent_turn_stop_ack a JOIN "
                        "agent_turn_control_request c USING (control_id) "
                        "WHERE c.workspace_id=:workspace AND c.turn_id=:turn AND c.kind='stop'"
                    ),
                    {"workspace": submission.workspace_id, "turn": turn_id},
                )
            )
            prefix = (
                stream.interrupted_answer()
                if stream is not None
                else await recover_interrupted_answer(
                    conn, workspace_id=submission.workspace_id, turn_id=turn_id
                )
            )
        if not acknowledged:
            body_ref = None
            if prefix:
                body_ref = await self._engine.artifacts.persist_body(
                    workspace_id=submission.workspace_id,
                    data=prefix.encode("utf-8"),
                    media_type="text/plain",
                    project_bindings=((submission.project_id, "project_conversation_context"),),
                )
            async with self._conn_factory() as conn:
                await commit_interrupted_turn(
                    conn,
                    workspace_id=submission.workspace_id,
                    thread_id=submission.thread_id,
                    turn_id=turn_id,
                    body_ref=body_ref,
                )
        if stream is not None:
            await stream.turn_cancelled()
        raise TurnStopped("this generation attempt was stopped by its submitter")

    async def _await_stop(
        self,
        *,
        workspace_id: str,
        turn_id: UUID,
        generation_attempt_id: UUID | None,
    ) -> None:
        """Poll the durable control table until this attempt is asked to stop."""

        while True:
            await asyncio.sleep(max(0.05, self._stop_poll_interval_s))
            async with self._conn_factory() as conn:
                if await stop_requested(
                    conn,
                    workspace_id=workspace_id,
                    turn_id=turn_id,
                    generation_attempt_id=generation_attempt_id,
                ):
                    return

    async def _complete_recipe(
        self, execution_id: ExecutionId, *, turn_id: UUID, actor_id: str | None
    ) -> None:
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
        # The drive runs under the same authority the turn's own tool calls were journaled with
        # (``turn-action:<turn_id>``), so a node the drive touches is never a replay under a
        # different authority.
        status = await self._drive(
            execution_id, actor_id=actor_id, action_ref=derive_turn_action_ref(turn_id)
        )
        if status is not ExecutionStatus.COMPLETED:
            raise RuntimeError("a completed conversation turn did not complete its C5 recipe")

    async def _drive(
        self,
        execution_id: ExecutionId,
        *,
        actor_id: str | None = None,
        action_ref: str | None = None,
    ) -> ExecutionStatus:
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
                actor_id=actor_id,
                action_ref=action_ref,
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
        bind_project: bool = True,
        subject_bindings: tuple[tuple[UUID, str], ...] | None = None,
    ) -> ArtifactRef:
        return await self._engine.artifacts.persist_body(
            workspace_id=submission.workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            subject_bindings=(
                self._client_subject_bindings(scope)
                if subject_bindings is None
                else subject_bindings
            ),
            project_bindings=(
                ((scope.project_id, "project_conversation_context"),) if bind_project else ()
            ),
        )

    @staticmethod
    def _client_subject_bindings(scope: _ProjectScope) -> tuple[tuple[UUID, str], ...]:
        return (
            ()
            if scope.client_entity_id is None
            else ((UUID(str(scope.client_entity_id)), CONVERSATION_CONTEXT_BINDING_KIND),)
        )

    async def _resolve_current_scope(
        self,
        conn: AsyncConnection,
        submission: AgentTurnSubmissionRow,
    ) -> _ProjectScope:
        """Resolve mutable current scope for diagnostic/compiler fixtures only.

        Production :meth:`run` never calls this helper. It uses
        :func:`load_or_create_agent_turn_scope_pin`, whose immutable row is the retry authority.
        """

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
                product_id=None,
            )
        )
        product_kb_version = (
            None
            if entity_id is None or project.product_id is None or kb_version is None
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
            product_kb_version=product_kb_version,
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
        async with self._conn_factory() as conn:
            await lock_thread_queue(conn, workspace_id=workspace_id, thread_id=thread_id)
            held_by = await conn.scalar(
                text(
                    "SELECT c.turn_id FROM agent_thread t JOIN agent_turn_control_request c "
                    "ON c.control_id=t.queue_hold_control_id WHERE "
                    "t.workspace_id=:workspace AND t.id=:thread"
                ),
                {"workspace": workspace_id, "thread": thread_id},
            )
        if held_by is not None and held_by != turn_id:
            # Covers tasks offered just before Stop acquired the dispatch lock.
            return WorkResult(
                outcome="queue_held",
                references=references,
                requeue=True,
                requeue_after=timedelta(seconds=1),
            )
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
            async with self._conn_factory() as conn:
                pending_stop = await stop_requested(
                    conn, workspace_id=workspace_id, turn_id=turn_id
                )
            if pending_stop:
                log.exception("agent_turn.stop_reconciliation_failed", turn_id=str(turn_id))
                return WorkResult(
                    outcome="stop_pending",
                    references=references,
                    requeue=True,
                    requeue_after=timedelta(seconds=1),
                )
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
            # Spec 2026-09-30 §4: if this was a discovery run's wake turn, the run holding this
            # thread (and its project) is released now — in the dispatch's own transaction, so the
            # dispatch below already sees the thread free and offers the first held message.
            await release_discovery_for_turn(conn, workspace_id=workspace_id, turn_id=turn_id)
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


def _completion_text(completion: object) -> str | dict[str, object]:
    """A LangChain completion's text, whatever content shape the provider produced.

    The gateway's models run the Responses API (``output_version="responses/v1"``), whose
    ``AIMessage.content`` is a LIST of typed blocks — never a plain string — so the naive
    ``str(content)`` was a Python repr that could never parse and silently disabled the
    exit bridge (adversarial-review fix; the block-walk mirrors the shipped
    ``entity_research_runtime`` precedent). Strings and dicts pass through; anything else
    unrecognized returns ``""``, which parses to ``None`` → the fail-safe CONTINUE.
    """

    content = getattr(completion, "content", completion)
    if isinstance(content, (str, dict)):
        return content
    if isinstance(content, Sequence):
        return "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, Mapping) and block.get("type") in ("text", "output_text")
        )
    return ""


def _judgment_payload(judgment: ExitJudgment) -> dict[str, object]:
    """The verdict as a JSON-safe mapping for the evaluator observation's output."""

    return judgment.model_dump(mode="json")


#: A hard deadline for each model the exit judge tries. Its answer is one small JSON object,
#: normally back in ~10 s; on 2026-10-04 a stalled provider held a judge call for 13 minutes
#: (keep-alives defeat the per-read timeout). Past this, the fallback chain takes over, and if
#: every model stalls the judge's own fail-safe answers CONTINUE.
_EXIT_JUDGE_CALL_DEADLINE_S = 45.0


def build_design_leg_exit_judge(
    *,
    models: AgentModelProvider,
    profiles: AgentProfileRegistry,
) -> DesignLegExitJudge:
    """The live §2.2 exit judge: the design role's own catalog model over the P3.6 prompt.

    Lives HERE — the worker composition — and not in ``design_leg_wiring``, because that
    module is reachable from the HTTP turn route and the lane-D2 isolation guard forbids it
    any model-plane name. Built lazily on first use and fail-safe throughout: a build
    failure, a call failure, or unparseable output all yield ``None``, which the runner's
    ``decide_exit`` envelope turns into CONTINUE.
    """

    model_holder: list[object] = []

    async def judge(
        *,
        brief: str,
        history: tuple[tuple[str, str], ...],
        message: str,
        artifacts: tuple[str, ...] = (),
        artifact: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> ExitJudgment | None:
        try:
            if not model_holder:
                policy = profiles.resolve(AgentRole.DESIGN).profile.model
                model_holder.append(
                    models.build(
                        model_id=policy.model_id,
                        timeout_s=policy.timeout_s,
                        max_retries=policy.max_retries,
                        # The judgment is one small JSON object; the role's generation
                        # budget would be waste here.
                        # v2's answer carries a sentence or two of reasoning as well, and
                        # v3's can carry a clarifying question on top of that — a truncated
                        # verdict is an unparseable one, which costs a whole fail-safe turn.
                        max_output_tokens=min(policy.max_output_tokens, 600),
                        temperature=0.0,
                        # Lane 3 slice 5: the judge's own spend is design spend. ``role``
                        # labels every usage record and span this instance produces, so the
                        # call is attributable even though it writes no durable receipt —
                        # it runs outside any turn, so there is no turn to hang one on.
                        role=AgentRole.DESIGN.value,
                        call_deadline_s=_EXIT_JUDGE_CALL_DEADLINE_S,
                    )
                )
            prompt = render_exit_judgment_prompt(
                brief=brief,
                history=history,
                message=message,
                artifacts=artifacts,
                artifact=artifact,
                tags=tags,
            )
            # Lane 3 slice 3b: the judge is an `evaluator` in its own trace, and the direct
            # model call carries the LangChain handler so its generation nests underneath.
            # The rendered prompt stays OUT of the observation — only the turn's message and
            # how much history it weighed.
            langfuse = build_langfuse_callbacks()
            call_kwargs: dict[str, Any] = (
                {"config": {"callbacks": [langfuse.handler]}} if langfuse is not None else {}
            )
            with (
                propagate_trace(trace_name="design-leg.exit_judge", tags=("design",)),
                observation(
                    "design-leg.exit_judge",
                    as_type="evaluator",
                    input={
                        "message": message,
                        "history_turns": len(history),
                        # v3: the whole numbered list the judge was asked to address, so a
                        # trace shows which artifacts were on the table when it answered.
                        "artifacts": list(artifacts),
                        "artifact": artifact,
                        "tags": list(tags),
                    },
                ) as current,
            ):
                completion = await model_holder[0].ainvoke(prompt, **call_kwargs)  # type: ignore[attr-defined]
                judgment = parse_exit_judgment(_completion_text(completion))
                current.update(
                    output=None if judgment is None else _judgment_payload(judgment),
                    level="DEFAULT" if judgment is not None else "WARNING",
                    status_message=None if judgment is not None else "unparseable verdict",
                )
            return judgment
        except Exception:
            log.warning("design_leg.exit_judge_failed", exc_info=True)
            return None

    return judge


#: Said once, so the batch entry point cannot drift from the single-run one.
_DESIGN_LANE_UNAVAILABLE_MESSAGE = (
    "this thread's design leg needs the design lane, but the worker composed none; "
    "set CLUE_DESIGN_RUNTIME_ENABLED on the fleet deployment"
)


class _DesignLaneUnavailable:
    """The fail-loud lane for a deployment that drains chat turns but no design work.

    A thread can only hold an open leg if some deployment opened one; a worker that then claims
    its turns without the design runtime must say so rather than silently wedge the leg.
    """

    async def drive(self, *, envelope: object) -> None:
        del envelope
        raise RuntimeError(_DESIGN_LANE_UNAVAILABLE_MESSAGE)

    async def drive_batch(self, *, envelopes: object) -> None:
        del envelopes
        raise RuntimeError(_DESIGN_LANE_UNAVAILABLE_MESSAGE)


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
    storage: StorageBackend | None = None,
    child_runner: FreshWakeChildRunner | None = None,
    design_lane: DesignLegLaneDriver | None = None,
    design_exit_judge: DesignLegExitJudge | None = None,
    design_leg_finisher: DesignLegFinisher | None = None,
    design_preference_context_enabled: bool = False,
    namer: ConversationNamer | None = None,
    conn_factory: ConnFactory = transaction,
    project_writer_conn_factory: ConnFactory = bridge_transaction,
    streaming: bool = True,
    stream_policy: TurnStreamPolicy | None = None,
    stop_poll_interval_s: float = 0.25,
) -> AgentTurnWorkHandler:
    """Compose the ``AGENT_TURN`` handler **once**, at worker startup.

    Everything expensive is built here and captured in the closure of one engine: the resolved
    profile and its manifest, the context assembler, the deepagent runtime. A turn then costs a
    submission read, a recipe start, three content-addressed artifacts and the model rounds — not a
    second composition of the whole platform.

    ``design_lane`` (P3.4) is the design-leg execution seam. The leg *runner* is always composed
    — the routing rule is unconditional, so a thread with an open leg must reach a deliberate
    answer either way — but without a lane the answer is a loud refusal at drive time, the same
    stance ``clue_api.design_fleet`` takes for the fleet handler.

    ``storage`` (ARV2 onboarding O6) is the blob backend this worker reads the brand's pinned
    knowledge documents from. Without it a turn composes no knowledge and says so once.

    ``project_writer_conn_factory`` is the transaction the versioned ``project/`` mount's writes
    open. It defaults to the bridge loop's own engine because those writes happen off this
    worker's loop, and it is separate from ``conn_factory`` for exactly that reason.

    ``namer`` (conversation naming, 2026-09-18) names an untitled chat/project after the first
    completed turn; ``None`` keeps the placeholders.
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
        namer=namer,
        # Spec 2026-09-29 §3.1: the project conversation continues its saved conversation.
        continuation=components.head_of_abm_continuation_enabled,
        conn_factory=conn_factory,
    )
    design_legs_runner = DesignLegTurnRunner(
        profiles=components.profiles,
        artifacts=components.artifacts,
        turns=components.turns,
        history=components.history,
        lane=design_lane if design_lane is not None else _DesignLaneUnavailable(),
        exit_judge=design_exit_judge,
        finisher=design_leg_finisher,
        # Staged until output-history erasure closure and preference writes are validated.
        memory=memory if design_preference_context_enabled else None,
        conn_factory=conn_factory,
    )
    return AgentTurnWorkHandler(
        runner=ProjectConversationTurnRunner(
            engine=engine,
            executor=executor,
            recipes=recipes,
            starter=starter,
            parameters=parameters,
            design_legs=design_legs_runner,
            storage=storage,
            conn_factory=conn_factory,
            project_writer_conn_factory=project_writer_conn_factory,
            streaming=streaming,
            stream_policy=stream_policy,
            stop_poll_interval_s=stop_poll_interval_s,
        ),
        queue=queue,
        conn_factory=conn_factory,
    )
