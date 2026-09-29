"""C6.5 production composition for the Head-of-ABM Stage-0 vertical."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from clue_agents import (
    AgentModelProvider,
    AgentPlanPolicy,
    AgentProfileRegistry,
    AgentResourceMaterializer,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    WorkspaceSeedFile,
)
from clue_agents.ports import SpillSink
from clue_agents.runtime import ORDINARY_FINALIZE_REPAIRS
from clue_agents.workspace import AgentWorkspaceLease
from clue_api.agent_compaction import compaction_for
from clue_api.agent_execution_wiring import (
    AgentExecutionCrashHook,
    C5AgentExecutionAdapter,
    CheckpointerFactory,
    DbAgentDelegationRuntime,
    DbAgentPlanJournal,
    FreshWakeChildRunner,
)
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    CompletionGuard,
    DurableDeepAgentTurnRunner,
    GovernedAgentToolFactory,
)
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.chat.turn_controls import stop_requested
from clue_api.chat.turn_stream import TurnStreamEmitter
from clue_api.stage0_recipe import Stage0StepPinProvider
from clue_api.turn_binding import CapturedTurnBinder, RequestCapturedTurn
from clue_core import ExecutionId
from clue_db import ConnFactory, transaction
from clue_execution import CompatibilityLoader, RecipeExecutor
from clue_toolbelt import ToolInvoker, ToolRegistry

__all__ = [
    "HeadOfAbmStage0Runtime",
    "build_head_of_abm_stage0_execution",
]


async def _no_crash(
    point: str,
    *,
    execution_id: ExecutionId,
    node_key: str | None,
) -> None:
    del point, execution_id, node_key


def build_head_of_abm_stage0_execution(
    *,
    request: AgentTurnRequest,
    profiles: AgentProfileRegistry,
    tools: ToolRegistry,
    tool_invoker: ToolInvoker,
    executor: RecipeExecutor,
    compatibility: CompatibilityLoader,
    artifacts: DurableAgentArtifactStore,
    plans: DbAgentPlanJournal,
    checkpointer_factory: CheckpointerFactory,
    budget_limit_millicents: int,
    max_fanout: int = 4,
    max_parallelism: int = 4,
    captured_turns: CapturedTurnBinder | None = None,
    surface: str | None = None,
    spill_sink: SpillSink | None = None,
    crash_hook: AgentExecutionCrashHook = _no_crash,
    conn_factory: ConnFactory = transaction,
) -> C5AgentExecutionAdapter:
    """Build the only C6.5 agent-to-C5 path, including C4-equivalent exact pins.

    ``surface`` names the declared capability surface this execution runs on (PC-C8 §8). It must
    match the surface the caller resolved the turn's constitution against, because the effective
    tool set — the authority the plan is validated against — is narrower on a restricted surface.
    """

    resolved = profiles.resolve(AgentRole.HEAD_OF_ABM, surface=surface)
    if request.constitution.role is not AgentRole.HEAD_OF_ABM:
        raise ValueError("Stage-0 vertical requires a Head-of-ABM constitution")
    if request.constitution.profile_ref != resolved.profile_ref:
        raise ValueError("Stage-0 turn does not pin the promoted Head-of-ABM profile")
    # A surface narrows the *effective tool set*, not the profile resource, so `profile_ref` alone
    # cannot tell a trial turn from a full-surface one — only the manifest digest can. Without this
    # check a caller who forgot `surface=` would build an adapter whose plan authority is wider
    # than the constitution the model was given, silently. `HeadOfAbmStage0Runtime.run` makes the
    # same assertion; this one exists because the two are independently callable.
    if request.constitution.resource_manifest_sha256 != resolved.resource_manifest.aggregate_sha256:
        raise ValueError(
            "Stage-0 turn constitution pins a different resource manifest than this surface "
            "resolves; the execution surface and the constitution's surface disagree"
        )
    return C5AgentExecutionAdapter(
        turn_id=request.turn_id,
        constitution=request.constitution,
        resolved_profile=resolved,
        policy=AgentPlanPolicy.from_profile(
            resolved.profile,
            budget_limit_millicents=budget_limit_millicents,
            max_fanout=max_fanout,
            max_parallelism=max_parallelism,
        ),
        slot_key="stage0_interactions",
        tools=tools,
        tool_invoker=tool_invoker,
        executor=executor,
        artifacts=artifacts,
        journal=plans,
        checkpointer_factory=checkpointer_factory,
        pin_provider=Stage0StepPinProvider(
            compatibility=compatibility,
            conn_factory=conn_factory,
            tools=tools,
        ),
        # PC-C8 §6a: the captured turn is derived here, from the request's own artifact and its
        # capture record, so no caller has to hand the engine a turn-shaped argument it could get
        # wrong — and so the model can never author one. A composition root that also builds the
        # context assembler passes the same binder to both, so one turn is resolved and cached
        # once; a caller that passes none gets a private binder that derives the same answer.
        captured_turn=RequestCapturedTurn(
            binder=captured_turns
            or CapturedTurnBinder(artifacts=artifacts, conn_factory=conn_factory),
            request=request,
        ),
        # A result too large for its receipt spills into this turn's own thread workspace, so
        # only a caller holding the workspace lease can supply the sink; without one an oversized
        # result keeps the old behaviour and is refused at the bound.
        spill_sink=spill_sink,
        crash_hook=crash_hook,
        conn_factory=conn_factory,
    )


class HeadOfAbmStage0Runtime:
    """Own one fully composed Stage-0 turn from frozen resources to honest finalize."""

    def __init__(
        self,
        *,
        profiles: AgentProfileRegistry,
        models: AgentModelProvider,
        turns: DbAgentTurnJournal,
        artifacts: DurableAgentArtifactStore,
        tools: ToolRegistry,
        child_runner: FreshWakeChildRunner,
        materializer: AgentResourceMaterializer | None = None,
        max_runtime_s: float | None = 300.0,
        max_rounds: int = 24,
        long_turn_alert_s: float | None = None,
        surface: str | None = None,
        crash_hook: AgentExecutionCrashHook = _no_crash,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._profiles = profiles
        self._models = models
        self._turns = turns
        self._artifacts = artifacts
        self._tools = tools
        self._child_runner = child_runner
        self._materializer = materializer or AgentResourceMaterializer()
        self._max_runtime_s = max_runtime_s
        self._max_rounds = max_rounds
        self._long_turn_alert_s = long_turn_alert_s
        self._surface = surface
        self._crash_hook = crash_hook
        self._conn_factory = conn_factory

    def _deep_runtime(
        self,
        execution: C5AgentExecutionAdapter,
        continuation_config: Mapping[str, Any] | None,
    ) -> DeepAgentTurnRuntime:
        return DeepAgentTurnRuntime(
            compaction_for=compaction_for,
            models=self._models,
            execution=execution,
            max_runtime_s=self._max_runtime_s,
            max_rounds=self._max_rounds,
            # A chat turn that hits its limit asks the human to reply "continue" (ruling
            # 2026-09-27) rather than reporting itself blocked.
            wrap_up_status="awaiting_input",
            long_turn_alert_s=self._long_turn_alert_s,
            continuation_config=continuation_config,
            # Continuing a conversation is not research: the ordinary repair allowance holds.
            max_finalize_repairs=ORDINARY_FINALIZE_REPAIRS,
        )

    async def continuation_is_settled(
        self,
        *,
        request: AgentTurnRequest,
        lease: AgentWorkspaceLease,
        execution: C5AgentExecutionAdapter,
        continuation_config: Mapping[str, Any],
    ) -> bool:
        """Whether the saved conversation ``continuation_config`` names can be continued.

        Builds the turn's own graph and reads the saved state through it; writes nothing, binds
        nothing and journals nothing, so a ``False`` leaves the turn free to open fresh.
        """
        resolved = self._profiles.resolve(AgentRole.HEAD_OF_ABM, surface=self._surface)
        governed_tools = GovernedAgentToolFactory(
            request=request,
            resolved_profile=resolved,
            registry=self._tools,
            execution=execution,
            lease=lease,
            artifacts=self._artifacts,
        ).build()
        return await self._deep_runtime(
            execution, continuation_config
        ).saved_conversation_is_settled(
            request=request,
            resolved_profile=resolved,
            backend=lease.backend,
            governed_tools=governed_tools,
        )

    async def run(
        self,
        *,
        request: AgentTurnRequest,
        context: AssembledAgentContext,
        lease: AgentWorkspaceLease,
        execution: C5AgentExecutionAdapter,
        completion_guard: CompletionGuard | None = None,
        stream: TurnStreamEmitter | None = None,
        input_seeds: tuple[WorkspaceSeedFile, ...] = (),
        continuation_config: Mapping[str, Any] | None = None,
    ) -> AgentTurnOutcome:
        """Run one Stage-0 turn.

        ``continuation_config`` (spec 2026-09-29 §3.1) names the saved conversation this turn
        continues; ``context`` must then have been assembled in continuation mode. The caller
        decides it — and checks it with :meth:`continuation_is_settled` — before assembling.

        ``completion_guard`` is the surface's veto over a non-failing terminal proposal — the seam
        the Stage-0 routing-receipt honesty check rides. It is optional because the guard needs the
        captured onboarding input of *this* turn, which only the calling surface knows.

        ``stream`` is FI Lane D D3's live projection (charter §3-P4). It is optional and defaults to
        absent for one reason: attaching it is what makes *this* turn take the model's streaming
        path, so a surface that does not want a turn stream — the dev trial, every specialist and
        fleet turn — keeps byte-for-byte the behaviour it had before D3.

        ``input_seeds`` (ARV2 onboarding O6) are read-only workspace files the *surface* pins for
        this turn, materialized alongside the assembler's own context materializations and verified
        with them, so a reclaimed turn re-proves its input bytes rather than trusting the directory.
        The production conversation turn supplies none since 2026-09-14 — it mounts the brand and
        project libraries instead of copying them into the thread — so today this is the onboarding
        synthesis surface's seeds under ``inputs/brand/knowledge/``, and the collision check below
        guards the canonical context paths against them.
        """

        resolved = self._profiles.resolve(AgentRole.HEAD_OF_ABM, surface=self._surface)
        constitution = request.constitution
        if constitution.role is not AgentRole.HEAD_OF_ABM:
            raise ValueError("Stage-0 vertical requires the Head-of-ABM role")
        if constitution.profile_ref != resolved.profile_ref:
            raise ValueError("turn profile differs from the promoted Stage-0 Head profile")
        if constitution.resource_manifest_sha256 != (resolved.resource_manifest.aggregate_sha256):
            raise ValueError("turn resource manifest differs from the promoted Stage-0 profile")
        if (
            lease.identity.workspace_id != constitution.workspace_id
            or lease.identity.project_id != constitution.project_id
            or lease.identity.execution_id != constitution.execution_id
            or lease.identity.workspace_root_id != constitution.workspace_root_id
        ):
            raise ValueError("turn constitution crosses the isolated workspace lease")
        if context.manifest.execution_id != constitution.execution_id:
            raise ValueError("assembled context belongs to another execution")
        context_seeds = tuple(
            WorkspaceSeedFile(
                path=item.path,
                content=item.data,
                sha256=item.sha256,
                media_type=item.media_type,
            )
            for item in context.materializations
        )
        # The canonical context paths are the assembler's; a surface input that lands on one of
        # them would silently replace a context file with a knowledge document. Refuse loudly.
        seed_paths = {*(item.path for item in context_seeds), *(item.path for item in input_seeds)}
        if len(seed_paths) != len(context_seeds) + len(input_seeds):
            raise ValueError("a knowledge-document input collided with a canonical context path")
        seed_files = (*context_seeds, *input_seeds)
        if lease.resources_frozen:
            # A reclaimed turn re-verifies every immutable byte before the model resumes: the
            # frozen tree is evidence, not an assumption.
            self._materializer.verify_materialized(
                lease=lease,
                snapshot=resolved.resource_snapshot,
                seed_files=seed_files,
            )
        else:
            self._materializer.materialize(
                lease=lease,
                snapshot=resolved.resource_snapshot,
                seed_files=seed_files,
            )
        await self._turns.create(request=request, profile=resolved.profile)
        execution.bind_delegation_runtime(
            DbAgentDelegationRuntime(
                registry=self._profiles,
                child_runner=self._child_runner,
                conn_factory=self._conn_factory,
                crash_hook=self._crash_hook,
            )
        )
        finalization = AgentFinalizationAuthority(
            lease=lease,
            artifacts=self._artifacts,
            turns=self._turns,
            crash_hook=self._crash_hook,
            conn_factory=self._conn_factory,
        )
        execution.bind_finalization_authority(finalization)

        async def before_work() -> None:
            async with self._conn_factory() as conn:
                stopped = await stop_requested(
                    conn, workspace_id=request.constitution.workspace_id, turn_id=request.turn_id
                )
            if stopped:
                raise asyncio.CancelledError("chat turn stopped before admitting more work")

        governed_tools = GovernedAgentToolFactory(
            request=request,
            resolved_profile=resolved,
            registry=self._tools,
            execution=execution,
            lease=lease,
            artifacts=self._artifacts,
            before_work=before_work,
            completion_guard=completion_guard,
            stream=stream,
        ).build()
        runtime = self._deep_runtime(execution, continuation_config)
        return await DurableDeepAgentTurnRunner(
            before_work=before_work,
            runtime=runtime,
            turns=self._turns,
            artifacts=self._artifacts,
        ).run(
            request=request,
            resolved_profile=resolved,
            context=context,
            lease=lease,
            tools=governed_tools,
            stream=stream,
        )
