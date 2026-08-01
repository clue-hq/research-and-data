"""C6.5 production composition for the Head-of-ABM Stage-0 vertical."""

from __future__ import annotations

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
from clue_agents.workspace import AgentWorkspaceLease
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
    crash_hook: AgentExecutionCrashHook = _no_crash,
    conn_factory: ConnFactory = transaction,
) -> C5AgentExecutionAdapter:
    """Build the only C6.5 agent-to-C5 path, including C4-equivalent exact pins."""

    resolved = profiles.resolve(AgentRole.HEAD_OF_ABM)
    if request.constitution.role is not AgentRole.HEAD_OF_ABM:
        raise ValueError("Stage-0 vertical requires a Head-of-ABM constitution")
    if request.constitution.profile_ref != resolved.profile_ref:
        raise ValueError("Stage-0 turn does not pin the promoted Head-of-ABM profile")
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
        ),
        # PC-C8 §6a: the captured turn is derived here, from the request's own artifact and its
        # capture record, so no caller has to hand the engine a turn-shaped argument it could get
        # wrong — and so the model can never author one.
        captured_turn=RequestCapturedTurn(
            binder=CapturedTurnBinder(artifacts=artifacts, conn_factory=conn_factory),
            request=request,
        ),
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
        max_runtime_s: float = 300.0,
        max_rounds: int = 24,
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
        self._crash_hook = crash_hook
        self._conn_factory = conn_factory

    async def run(
        self,
        *,
        request: AgentTurnRequest,
        context: AssembledAgentContext,
        lease: AgentWorkspaceLease,
        execution: C5AgentExecutionAdapter,
        completion_guard: CompletionGuard | None = None,
    ) -> AgentTurnOutcome:
        """Run one Stage-0 turn.

        ``completion_guard`` is the surface's veto over a non-failing terminal proposal — the seam
        the Stage-0 routing-receipt honesty check rides. It is optional because the guard needs the
        captured onboarding input of *this* turn, which only the calling surface knows.
        """

        resolved = self._profiles.resolve(AgentRole.HEAD_OF_ABM)
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
        if not lease.resources_frozen:
            self._materializer.materialize(
                lease=lease,
                snapshot=resolved.resource_snapshot,
                seed_files=tuple(
                    WorkspaceSeedFile(
                        path=item.path,
                        content=item.data,
                        sha256=item.sha256,
                        media_type=item.media_type,
                    )
                    for item in context.materializations
                ),
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
        governed_tools = GovernedAgentToolFactory(
            request=request,
            resolved_profile=resolved,
            registry=self._tools,
            execution=execution,
            lease=lease,
            artifacts=self._artifacts,
            completion_guard=completion_guard,
        ).build()
        runtime = DeepAgentTurnRuntime(
            models=self._models,
            execution=execution,
            max_runtime_s=self._max_runtime_s,
            max_rounds=self._max_rounds,
        )
        return await DurableDeepAgentTurnRunner(
            runtime=runtime,
            turns=self._turns,
            artifacts=self._artifacts,
        ).run(
            request=request,
            resolved_profile=resolved,
            context=context,
            lease=lease,
            tools=governed_tools,
        )
