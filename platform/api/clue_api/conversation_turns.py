"""One platform-deepagent **conversation turn** — the composition and the execution path.

FI Lane D slice **D2**. Two surfaces run the same Head-of-ABM conversation over the same durable
substrate: the dev-only stage-0 trial harness (`clue_api.stage0_trial`, ratified §6-D6) and the
production project conversation the fleet worker executes
(`clue_api.agent_turn_fleet_wiring`). Before this module they would have been two copies of the
same twelve steps; the charter names that duplication as the trial's defect (§1.2) and D2's job is
to leave exactly one implementation:

* :mod:`clue_api.conversation_capture` — the capture-before-spend half, which lives in its own
  module precisely so the HTTP process can import it without importing anything model-shaped.
* :class:`ConversationTurnEngine` — the execution half, and the thing that is **composed once**.
  The trial rebuilds it per request because it is a per-session CLI harness; the fleet worker
  builds it at startup and reuses it for every turn, which is the whole point of §3-P3.

What is deliberately *not* here: how a turn's identity, project card, budget envelope and
constitution are assembled. Those differ per surface (the trial has a Stage-0 project card and a
local session file; production reads durable project state), so each surface builds its own
:class:`~clue_agents.AgentTurnRequest` and hands it to the same engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid5

from clue_agents import (
    AgentFinalizeEnvelope,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AgentWorkspaceLease,
    ContextAssemblyPolicy,
    DelegationRequest,
    DelegationResult,
    DeterministicAgentContextAssembler,
    ResolvedAgentProfile,
)
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_execution_wiring import (
    DbAgentPlanJournal,
    FreshWakeChildRunner,
    postgres_agent_checkpointer,
)
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    build_agent_context_assembler,
)
from clue_api.agent_runtime_wiring import CompletionGuard
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.turn_stream import TurnStreamEmitter
from clue_api.head_of_abm_wiring import (
    HeadOfAbmStage0Runtime,
    build_head_of_abm_stage0_execution,
)
from clue_api.turn_binding import CapturedTurnBinder
from clue_core import ContextAssembly, ExecutionId, MemoryType
from clue_db import ConnFactory, transaction
from clue_execution import CompatibilityLoader, RecipeExecutor
from clue_toolbelt import ToolInvoker, ToolRegistry

__all__ = [
    "CONVERSATION_RECIPE_KEY",
    "CONVERSATION_RECIPE_VERSION",
    "ConversationTurnEngine",
    "ConversationTurnResult",
    "DelegationWithheld",
    "build_conversation_turn_engine",
]

#: The promoted Recipe-#0 revision every Head-of-ABM conversation runs, on both surfaces. It is one
#: constant because it is one fact: the C5 interaction slot's tool allowlist lives in that revision,
#: so a tool granted on a profile but absent from the pinned revision is rejected at plan validation
#: (``c5_tool_not_allowed``). Two surfaces pinning two revisions would mean two different sets of
#: callable tools for the same role, discovered only at the first refused plan.
#:
#: **v6** (FI Lane D D4) widens that slot to the Option-B kickoff chain —
#: ``draft_account_research_directive@2``, ``open_directive_confirmation_gate@1``,
#: ``launch_account_research@1`` — because a surface grant alone is not enough: the C5 slot is a
#: second, independent ceiling, and until this revision the widened conversation surface would have
#: shown the model three tools that plan validation then refused. The trial surface still withholds
#: all three, so raising the shared ceiling grants the trial nothing.
CONVERSATION_RECIPE_KEY = "recipe0-stage0"
CONVERSATION_RECIPE_VERSION = 7

#: Finalization ``domain_refs`` object types that render as a §3.4 ``plan`` part. Deliberately a
#: closed set: an unknown object type is *not* projected, because a card whose contents the surface
#: cannot describe is worse than no card. D4's directive/gate objects extend this.
_PLAN_OBJECT_TYPES: frozenset[str] = frozenset({"research_directive", "agent_plan", "plan"})


class DelegationWithheld:
    """The unreachable backstop for a conversation surface that withholds every delegable role.

    Both conversation surfaces withhold ``RESEARCH`` / ``CONTENT_DRAFTER`` / ``REVIEWER``
    (``C6_SURFACE_POLICIES``), so ``delegation_roles`` is empty, ``delegate_specialist`` is not in
    the middleware's allowed set, and no delegation can be constructed to hand a child runner. This
    stays only because :class:`~clue_api.head_of_abm_wiring.HeadOfAbmStage0Runtime` requires a child
    runner and "there is no runner" is not expressible — it is a backstop, not the fence.
    Restriction by crash is what ruling §2.4 rejects; the withheld roles are the actual mechanism.
    """

    async def run(
        self,
        *,
        request: DelegationRequest,
        child_execution_id: ExecutionId,
        resolved_profile: Any,
    ) -> DelegationResult:
        del request, child_execution_id, resolved_profile
        raise RuntimeError("specialist_delegation_withheld_on_conversation_surface")


@dataclass(frozen=True, slots=True)
class ConversationTurnResult:
    """One executed (or replayed) turn."""

    outcome: AgentTurnOutcome
    assistant_message: str | None
    #: ``True`` when the turn already had a committed finalization and was **not** re-executed.
    replayed: bool


class ConversationTurnEngine:
    """The composed-once Head-of-ABM conversation runtime, and the one turn execution path.

    Everything expensive — the resolved profile and its resource manifest, the captured-turn
    binder, the seven-layer context assembler, the deepagent runtime — is built by
    :func:`build_conversation_turn_engine` and then reused. The fleet worker builds exactly one of
    these at startup; nothing about it is per-turn or per-workspace, because the per-turn scope
    travels in the :class:`~clue_agents.AgentTurnRequest`.
    """

    def __init__(
        self,
        *,
        surface: str,
        resolved: ResolvedAgentProfile,
        components: AgentPlatformComponents,
        tools: ToolRegistry,
        tool_invoker: ToolInvoker,
        executor: RecipeExecutor,
        compatibility: CompatibilityLoader,
        contexts: DeterministicAgentContextAssembler,
        runtime: HeadOfAbmStage0Runtime,
        captured_turns: CapturedTurnBinder,
        plans: DbAgentPlanJournal,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self.surface = surface
        self.resolved = resolved
        self.components = components
        self._tools = tools
        self._tool_invoker = tool_invoker
        self._executor = executor
        self._compatibility = compatibility
        self._contexts = contexts
        self._runtime = runtime
        self._captured_turns = captured_turns
        self._plans = plans
        self._conn_factory = conn_factory

    @property
    def artifacts(self) -> DurableAgentArtifactStore:
        return self.components.artifacts

    async def execute(
        self,
        *,
        request: AgentTurnRequest,
        lease: AgentWorkspaceLease,
        budget_limit_millicents: int,
        completion_guard: CompletionGuard | None = None,
        submitted_by_user_id: str | None = None,
        submitted_via_membership_id: str | None = None,
        stream: TurnStreamEmitter | None = None,
    ) -> ConversationTurnResult:
        """Run one turn, honouring the committed-outcome replay short-circuit.

        The short-circuit is the crash-safety contract: a turn that already holds an authoritative
        :class:`agent_finalization_commit` is **never executed a second time**, whatever re-enters
        here — a retried fleet task, a restarted process, a duplicate submission. The load is a
        pure read of the immutable commit joined to its live envelope artifact (an unfinalized
        failed turn deliberately returns ``None``, so an honest retry can resume its durable model
        checkpoint instead of manufacturing success).

        History is appended around that short-circuit rather than inside it, so a replayed turn
        re-projects the same two thread messages by their derived ids (``uuid5(turn_id, role)``)
        instead of duplicating them.

        ``stream`` (FI Lane D D3, charter §3-P4) is the live projection of this turn onto the
        durable event outbox. It is optional and never authoritative: every emission is best-effort
        by construction, and a turn's committed outcome is identical whether anybody was watching.
        """

        constitution = request.constitution
        workspace_id = constitution.workspace_id
        prior_history = await self.components.history.load(
            workspace_id=workspace_id,
            thread_id=request.thread_id,
        )
        await self.components.turns.create(
            request=request,
            profile=self.resolved.profile,
            submitted_by_user_id=submitted_by_user_id,
            submitted_via_membership_id=submitted_via_membership_id,
        )
        await self.components.history.append(
            message_id=uuid5(request.turn_id, "user"),
            turn_id=request.turn_id,
            workspace_id=workspace_id,
            thread_id=request.thread_id,
            role="user",
            body_ref=request.user_message_artifact_ref,
        )
        committed = await self.components.turns.load_committed_outcome(
            turn_id=request.turn_id,
            workspace_id=workspace_id,
        )
        if stream is not None:
            await stream.turn_started()
        if committed is None:
            context = await self._contexts.assemble(
                request=request,
                profile=self.resolved.profile,
                history=prior_history,
            )
            execution = build_head_of_abm_stage0_execution(
                request=request,
                profiles=self.components.profiles,
                tools=self._tools,
                tool_invoker=self._tool_invoker,
                executor=self._executor,
                compatibility=self._compatibility,
                artifacts=self.components.artifacts,
                plans=self._plans,
                checkpointer_factory=postgres_agent_checkpointer,
                budget_limit_millicents=budget_limit_millicents,
                captured_turns=self._captured_turns,
                surface=self.surface,
                conn_factory=self._conn_factory,
            )
            outcome = await self._runtime.run(
                request=request,
                context=context,
                lease=lease,
                execution=execution,
                completion_guard=completion_guard,
                stream=stream,
            )
        else:
            outcome = committed
        assistant_message: str | None = None
        envelope: AgentFinalizeEnvelope | None = None
        if outcome.finalization_ref is not None:
            envelope = AgentFinalizeEnvelope.model_validate_json(
                await self.components.artifacts.read(outcome.finalization_ref)
            )
            if envelope.user_message_artifact_ref is not None:
                assistant_message = (
                    await self.components.artifacts.read(envelope.user_message_artifact_ref)
                ).decode()
                await self.components.history.append(
                    message_id=uuid5(request.turn_id, "assistant"),
                    turn_id=request.turn_id,
                    workspace_id=workspace_id,
                    thread_id=request.thread_id,
                    role="assistant",
                    body_ref=envelope.user_message_artifact_ref,
                )
        if stream is not None:
            await self._project_turn_close(
                stream=stream,
                outcome=outcome,
                envelope=envelope,
                assistant_message=assistant_message,
                replayed=committed is not None,
            )
        return ConversationTurnResult(
            outcome=outcome,
            assistant_message=assistant_message,
            replayed=committed is not None,
        )

    async def _project_turn_close(
        self,
        *,
        stream: TurnStreamEmitter,
        outcome: AgentTurnOutcome,
        envelope: AgentFinalizeEnvelope | None,
        assistant_message: str | None,
        replayed: bool,
    ) -> None:
        """Project the finalization's durable refs, reconcile the text, then close the turn.

        Order is the contract a consumer relies on: the cards a message carries arrive before the
        message is declared finished, and the text is either proved byte-identical (``text.end``) or
        loudly disowned (``stream.reset``) before the terminal event lands.

        A **replayed** turn streams nothing and says so: no delta of this attempt exists, so the
        honest instruction is "re-fetch the canonical message", not a fabricated replay of text the
        model produced in an earlier process.

        The **task** projection runs whatever the turn's status: a launch is committed by its own
        transaction, so a turn that launched research and then failed to finalize still launched it,
        and hiding the card would hide spend the human authorized.

        What is deliberately **not** projected here is a ``sources`` part. §3.4's floor demands real
        message-scoped source items, and this surface has none to give: the project conversation
        withholds every fetching tool by policy ("you do not … fetch external sources",
        ``C6_SURFACE_POLICIES``), so no durable source receipt is produced in a turn. The only
        remaining candidate — the finalization's ``domain_refs`` — is *model-declared*, carries no
        URL, title or evidence ref, and projecting it would manufacture provenance out of a
        model's assertion. An honest gap beats an invented citation; when a tool on this surface
        starts producing durable source receipts, that receipt is what feeds
        ``TurnStreamEmitter.emit_sources_part``.
        """

        if envelope is not None:
            await stream.emit_gate_parts(refs=envelope.open_gate_refs)
            for ref in envelope.domain_refs:
                if ref.object_type in _PLAN_OBJECT_TYPES:
                    await stream.emit_plan_part(
                        ref=ref,
                        title=ref.object_type.replace("_", " "),
                        revision_label=None if ref.version is None else str(ref.version),
                    )
        await stream.emit_launched_task_parts()
        if replayed:
            await stream.rehydrate(reason="turn_replayed")
        else:
            await stream.reconcile_text(assistant_message=assistant_message)
        await stream.turn_finished(
            status=outcome.status.value,
            failure_code=outcome.failure_code,
            replayed=replayed,
        )


def build_conversation_turn_engine(
    *,
    surface: str,
    components: AgentPlatformComponents,
    tools: ToolRegistry,
    tool_invoker: ToolInvoker,
    executor: RecipeExecutor,
    compatibility: CompatibilityLoader,
    memory: ContextAssembly,
    requested_memory_types: tuple[MemoryType, ...],
    context_policy: ContextAssemblyPolicy,
    child_runner: FreshWakeChildRunner | None = None,
    conn_factory: ConnFactory = transaction,
) -> ConversationTurnEngine:
    """Compose one conversation engine for one declared capability surface.

    ``surface`` is load-bearing three times over — the resolved profile, the context assembler's
    L1/L2 authority description, and the runtime's own assertion all read it — which is exactly why
    it is a parameter rather than a constant: the production project conversation and the dev trial
    are the *same* role on *different* surfaces, and a surface mismatch between the three is the
    failure this single builder makes unrepresentable.
    """

    resolved = components.profiles.resolve(AgentRole.HEAD_OF_ABM, surface=surface)
    # PC-C8 §6: one binder shared by L7 (which *names* the captured turn) and the execution seam
    # (which *injects* its bytes and ids). Both derive the same binding from durable state, so
    # sharing costs nothing and saves the second read of every turn.
    captured_turns = CapturedTurnBinder(
        artifacts=components.artifacts,
        conn_factory=conn_factory,
    )
    contexts = build_agent_context_assembler(
        resolved_profile=resolved,
        artifacts=components.artifacts,
        cards=DbCompiledContextCardReader(conn_factory=conn_factory),
        memory=memory,
        memory_recipe=f"{CONVERSATION_RECIPE_KEY}@{CONVERSATION_RECIPE_VERSION}",
        requested_memory_types=requested_memory_types,
        policy=context_policy,
        captured_turns=captured_turns,
        conn_factory=conn_factory,
    )
    runtime = HeadOfAbmStage0Runtime(
        profiles=components.profiles,
        models=components.models,
        turns=components.turns,
        artifacts=components.artifacts,
        tools=tools,
        child_runner=child_runner if child_runner is not None else DelegationWithheld(),
        max_runtime_s=resolved.profile.turn_timeout_s,
        max_rounds=resolved.profile.max_model_rounds,
        surface=surface,
        conn_factory=conn_factory,
    )
    return ConversationTurnEngine(
        surface=surface,
        resolved=resolved,
        components=components,
        tools=tools,
        tool_invoker=tool_invoker,
        executor=executor,
        compatibility=compatibility,
        contexts=contexts,
        runtime=runtime,
        captured_turns=captured_turns,
        plans=DbAgentPlanJournal(conn_factory=conn_factory),
        conn_factory=conn_factory,
    )
