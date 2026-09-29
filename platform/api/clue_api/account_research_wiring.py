"""C6.7 governed per-account research agent inside the existing deep-fleet slot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from clue_agents import (
    AgentExecutionStatus,
    AgentModelProvider,
    AgentPlanPolicy,
    AgentProfileRegistry,
    AgentResourceMaterializer,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    FinalizeStatus,
    WorkspaceSeedFile,
)
from clue_agents.workspace import AgentWorkspaceLease
from clue_api.agent_compaction import compaction_for
from clue_api.agent_execution_wiring import (
    AgentExecutionCrashHook,
    C5AgentExecutionAdapter,
    CheckpointerFactory,
    DbAgentPlanJournal,
)
from clue_api.agent_registry_wiring import ACCOUNT_RESEARCH_UNIT_SURFACE
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    CompletionGuard,
    DurableDeepAgentTurnRunner,
    GovernedAgentToolFactory,
    ModelFinalizeRequest,
)
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.stage0_recipe import RecipeStep, StepPinProvider
from clue_config import RecursionPolicy
from clue_core import (
    ClaimId,
    EntityId,
    ExecutionId,
    ICPSpec,
    ProjectRunId,
    ResearchDirectivePin,
    ResearchTerminalStatus,
    Resolver,
    RunId,
    UtcDatetime,
    WorkerStatus,
    account_axis_field_keys,
)
from clue_db import ConnFactory, transaction
from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    ExecutionConflict,
    PinRequest,
    RecipeExecutor,
)
from clue_research.coverage import list_attempts, list_decisions
from clue_research.durable import DbAccountRunStore, ResearchPlan, get_account_run
from clue_research.profiling import AccountProfileResult
from clue_research.profiling.aspect_worker import AspectCoverage
from clue_research.sources import bind_resolver_overrides
from clue_toolbelt import ToolContext, ToolInvoker, ToolRegistry

__all__ = [
    "AccountResolverBindingAvailability",
    "AccountResolverBindings",
    "AccountResolverBindingsUnavailable",
    "AccountResearchAgentRuntime",
    "AccountResolverBindingProvider",
    "AccountResearchStepPinProvider",
    "AccountResearchTurnRunner",
    "GovernedAccountProfiler",
    "build_account_research_execution",
]


async def _no_crash(
    point: str,
    *,
    execution_id: ExecutionId,
    node_key: str | None,
) -> None:
    del point, execution_id, node_key


class AccountResearchStepPinProvider(StepPinProvider):
    """Freeze the complete account-unit identity and mutable catalogs per operation."""

    def __init__(self, *, compatibility: CompatibilityLoader) -> None:
        self._compatibility = compatibility

    async def _current(self, *, kind: str, key: str, ctx: ToolContext) -> PinRequest:
        observation = await self._compatibility.observe_current(
            kind=kind,
            key=key,
            context=CompatibilityContext(workspace_id=ctx.workspace_id),
        )
        if observation is None:
            raise ExecutionConflict(f"cannot pin missing account-research resource {kind}:{key}")
        return PinRequest(
            kind=kind,
            key=key,
            version=observation.version,
            digest=observation.digest,
        )

    async def pins_for(
        self,
        step: RecipeStep,
        *,
        ctx: ToolContext,
    ) -> tuple[PinRequest, ...]:
        if step.tool_name != "research_account_gaps" or step.tool_version != "2":
            raise ExecutionConflict("account-research recipe admits only research_account_gaps@2")
        project_run_id = step.input_refs.get("project_run_id")
        account_entity_id = step.input_refs.get("account_entity_id")
        if not isinstance(project_run_id, str) or not isinstance(account_entity_id, str):
            raise ExecutionConflict("account research requires project-run and account identities")
        return (
            await self._current(kind="project_run", key=project_run_id, ctx=ctx),
            await self._current(kind="account", key=account_entity_id, ctx=ctx),
            await self._current(kind="field_registry", key="__all_active__", ctx=ctx),
            await self._current(kind="source_registry", key="__all_active__", ctx=ctx),
            # ``coverage_policy:default@1`` is already a static requirement of the
            # ``account_research_interactions`` recipe node. Adding a digest-pinned dynamic copy
            # creates a conflicting requirement (version-only versus version+digest) at execution
            # start. Only request genuinely run-/subject-/catalog-dynamic resources here.
            *step.pin_requests,
        )


def build_account_research_execution(
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
    crash_hook: AgentExecutionCrashHook = _no_crash,
    conn_factory: ConnFactory = transaction,
) -> C5AgentExecutionAdapter:
    """Build the one-tool C5 adapter for an already-started account-unit execution."""

    resolved = profiles.resolve(
        AgentRole.ACCOUNT_RESEARCH,
        surface=ACCOUNT_RESEARCH_UNIT_SURFACE,
    )
    if request.constitution.role is not AgentRole.ACCOUNT_RESEARCH:
        raise ValueError("account research execution requires account_research authority")
    if request.constitution.profile_ref != resolved.profile_ref:
        raise ValueError("account research turn does not pin the promoted profile")
    return C5AgentExecutionAdapter(
        turn_id=request.turn_id,
        constitution=request.constitution,
        resolved_profile=resolved,
        policy=AgentPlanPolicy.from_profile(
            resolved.profile,
            budget_limit_millicents=budget_limit_millicents,
            max_fanout=1,
            max_parallelism=1,
            max_rounds=resolved.profile.max_model_rounds,
        ),
        slot_key="account_research_interactions",
        tools=tools,
        tool_invoker=tool_invoker,
        executor=executor,
        artifacts=artifacts,
        journal=plans,
        checkpointer_factory=checkpointer_factory,
        pin_provider=AccountResearchStepPinProvider(compatibility=compatibility),
        crash_hook=crash_hook,
        conn_factory=conn_factory,
    )


class AccountResearchAgentRuntime:
    """Run one fully prepared, isolated account turn through the real deepagent loop."""

    def __init__(
        self,
        *,
        profiles: AgentProfileRegistry,
        models: AgentModelProvider,
        turns: DbAgentTurnJournal,
        artifacts: DurableAgentArtifactStore,
        tools: ToolRegistry,
        materializer: AgentResourceMaterializer | None = None,
        crash_hook: AgentExecutionCrashHook = _no_crash,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._profiles = profiles
        self._models = models
        self._turns = turns
        self._artifacts = artifacts
        self._tools = tools
        self._materializer = materializer or AgentResourceMaterializer()
        self._crash_hook = crash_hook
        self._conn_factory = conn_factory

    async def run(
        self,
        *,
        request: AgentTurnRequest,
        context: AssembledAgentContext,
        lease: AgentWorkspaceLease,
        execution: C5AgentExecutionAdapter,
        completion_guard: CompletionGuard,
    ) -> AgentTurnOutcome:
        resolved = self._profiles.resolve(
            AgentRole.ACCOUNT_RESEARCH,
            surface=ACCOUNT_RESEARCH_UNIT_SURFACE,
        )
        constitution = request.constitution
        if constitution.role is not AgentRole.ACCOUNT_RESEARCH:
            raise ValueError("account turn requires account_research authority")
        if constitution.profile_ref != resolved.profile_ref:
            raise ValueError("account turn profile differs from the promoted profile")
        if constitution.resource_manifest_sha256 != resolved.resource_manifest.aggregate_sha256:
            raise ValueError("account turn resource manifest differs from the promoted profile")
        if (
            lease.identity.workspace_id != constitution.workspace_id
            or lease.identity.project_id != constitution.project_id
            or lease.identity.execution_id != constitution.execution_id
            or lease.identity.workspace_root_id != constitution.workspace_root_id
        ):
            raise ValueError("account turn crosses the isolated workspace lease")
        if context.manifest.execution_id != constitution.execution_id:
            raise ValueError("assembled account context belongs to another execution")
        seed_files = tuple(
            WorkspaceSeedFile(
                path=item.path,
                content=item.data,
                sha256=item.sha256,
                media_type=item.media_type,
            )
            for item in context.materializations
        )
        if not lease.resources_frozen:
            self._materializer.materialize(
                lease=lease,
                snapshot=resolved.resource_snapshot,
                seed_files=seed_files,
            )
        else:
            self._materializer.verify_materialized(
                lease=lease,
                snapshot=resolved.resource_snapshot,
                seed_files=seed_files,
            )
        await self._turns.create(request=request, profile=resolved.profile)
        execution.bind_finalization_authority(
            AgentFinalizationAuthority(
                lease=lease,
                artifacts=self._artifacts,
                turns=self._turns,
                crash_hook=self._crash_hook,
                conn_factory=self._conn_factory,
            )
        )
        governed_tools = GovernedAgentToolFactory(
            request=request,
            resolved_profile=resolved,
            registry=self._tools,
            execution=execution,
            lease=lease,
            artifacts=self._artifacts,
            completion_guard=completion_guard,
        ).build()
        return await DurableDeepAgentTurnRunner(
            runtime=DeepAgentTurnRuntime(
                compaction_for=compaction_for,
                models=self._models,
                execution=execution,
                max_runtime_s=resolved.profile.turn_timeout_s,
                max_rounds=resolved.profile.max_model_rounds,
            ),
            turns=self._turns,
            artifacts=self._artifacts,
        ).run(
            request=request,
            resolved_profile=resolved,
            context=context,
            lease=lease,
            tools=governed_tools,
        )


class AccountResearchTurnRunner(Protocol):
    """Prepare/start the durable C5 execution, isolated workspace, and seven-layer context."""

    async def run(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        account_run_id: RunId,
        tier: str,
        plan: ResearchPlan,
        budget_cap_cents: Decimal | None,
        completion_guard: CompletionGuard,
    ) -> AgentTurnOutcome: ...


class AccountResolverBindingProvider(Protocol):
    """Ready, account-scoped resolver bindings made visible only during one agent turn."""

    async def resolver_bindings(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_entity_id: EntityId,
        research_directive: ResearchDirectivePin | None,
    ) -> AccountResolverBindings: ...


class AccountResolverBindingAvailability(StrEnum):
    READY = "ready"
    NOT_APPLICABLE = "not_applicable"
    WAITING_EXTERNAL = "waiting_external"
    REQUIRED_MISSING = "required_missing"
    FAILED_EXTERNAL = "failed_external"


@dataclass(frozen=True)
class AccountResolverBindings:
    """Provider-neutral task-local bindings plus an explicit preparation disposition."""

    availability: AccountResolverBindingAvailability
    bindings: Mapping[str, Resolver]
    reason_code: str | None = None
    operation_ref: str | None = None
    retry_after: UtcDatetime | None = None
    snapshot_refs: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.availability is AccountResolverBindingAvailability.READY and not self.bindings:
            raise ValueError("ready resolver bindings cannot be empty")
        if (
            self.availability
            in {
                AccountResolverBindingAvailability.WAITING_EXTERNAL,
                AccountResolverBindingAvailability.REQUIRED_MISSING,
                AccountResolverBindingAvailability.FAILED_EXTERNAL,
            }
            and not self.reason_code
        ):
            raise ValueError("unavailable resolver bindings require a reason code")
        if self.availability is AccountResolverBindingAvailability.WAITING_EXTERNAL:
            if self.operation_ref is None or self.retry_after is None:
                raise ValueError("waiting resolver bindings require operation_ref and retry_after")
        elif self.retry_after is not None:
            raise ValueError("only waiting resolver bindings may carry retry_after")


class AccountResolverBindingsUnavailable(RuntimeError):
    def __init__(self, resolution: AccountResolverBindings) -> None:
        self.resolution = resolution
        super().__init__(resolution.reason_code or resolution.availability.value)


class GovernedAccountProfiler:
    """ProfileAccountFn replacement: durable plan -> one account agent -> ledger projection."""

    def __init__(
        self,
        *,
        turns: AccountResearchTurnRunner,
        resolver_provider: AccountResolverBindingProvider | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._turns = turns
        self._resolver_provider = resolver_provider
        self._conn_factory = conn_factory

    async def __call__(
        self,
        *,
        account_entity_id: EntityId,
        spec: ICPSpec,
        tier: str,
        run_id: RunId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        budget_cap_cents: Decimal | None = None,
        recursion_policy: RecursionPolicy | None = None,
        research_directive: ResearchDirectivePin | None = None,
        resolver_bindings: Mapping[str, Resolver] | None = None,
        **_mechanical_collaborators: object,
    ) -> AccountProfileResult:
        store = DbAccountRunStore(
            recursion_policy=recursion_policy,
            conn_factory=self._conn_factory,
        )
        account_fields = (
            None if spec.field_keys is None else account_axis_field_keys(spec.field_keys)
        )
        plan = await store.begin(
            account_run_id=run_id,
            project_run_id=project_run_id,
            entity_id=account_entity_id,
            tier=tier,
            workspace_id=workspace_id,
            field_keys=account_fields,
            research_directive=research_directive,
        )
        planned_fields = tuple(field for aspect in plan.aspects for field in aspect.field_keys)
        if not planned_fields:
            return AccountProfileResult(
                account_entity_id=account_entity_id,
                tier=tier,
                run_id=run_id,
                status=WorkerStatus.OK,
                coverage_terminal=True,
                cost_already_recorded=True,
            )

        async def require_terminal(proposal: ModelFinalizeRequest) -> None:
            # Account research is gated on `completed` only: an `awaiting_input` account turn is
            # honestly reporting that it *cannot* finish coverage yet, which is exactly what the
            # engine-terminal check would otherwise refuse.
            if proposal.status is not FinalizeStatus.COMPLETED:
                return
            if not await self._all_terminal(
                workspace_id=workspace_id,
                run_id=run_id,
                account_entity_id=account_entity_id,
                planned_fields=planned_fields,
            ):
                raise ValueError(
                    "completed account finalization requires engine-terminal coverage "
                    "for every initially planned field"
                )

        bindings: Mapping[str, Resolver] = resolver_bindings or {}
        if not bindings and self._resolver_provider is not None:
            resolution = await self._resolver_provider.resolver_bindings(
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                research_directive=research_directive,
            )
            if resolution.availability in {
                AccountResolverBindingAvailability.WAITING_EXTERNAL,
                AccountResolverBindingAvailability.REQUIRED_MISSING,
                AccountResolverBindingAvailability.FAILED_EXTERNAL,
            }:
                raise AccountResolverBindingsUnavailable(resolution)
            bindings = resolution.bindings
        if bindings:
            with bind_resolver_overrides(bindings):
                outcome = await self._turns.run(
                    workspace_id=workspace_id,
                    project_run_id=project_run_id,
                    account_entity_id=account_entity_id,
                    account_run_id=run_id,
                    tier=tier,
                    plan=plan,
                    budget_cap_cents=budget_cap_cents,
                    completion_guard=require_terminal,
                )
        else:
            outcome = await self._turns.run(
                workspace_id=workspace_id,
                project_run_id=project_run_id,
                account_entity_id=account_entity_id,
                account_run_id=run_id,
                tier=tier,
                plan=plan,
                budget_cap_cents=budget_cap_cents,
                completion_guard=require_terminal,
            )
        return await self._project_result(
            workspace_id=workspace_id,
            account_entity_id=account_entity_id,
            run_id=run_id,
            tier=tier,
            plan=plan,
            turn_status=outcome.status,
        )

    async def _all_terminal(
        self,
        *,
        workspace_id: str,
        run_id: RunId,
        account_entity_id: EntityId,
        planned_fields: tuple[str, ...],
    ) -> bool:
        async with self._conn_factory() as conn:
            decisions = await list_decisions(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                entity_id=account_entity_id,
            )
        terminal = {item.field_key for item in decisions if item.terminal_status is not None}
        return set(planned_fields) <= terminal

    async def _project_result(
        self,
        *,
        workspace_id: str,
        account_entity_id: EntityId,
        run_id: RunId,
        tier: str,
        plan: ResearchPlan,
        turn_status: AgentExecutionStatus,
    ) -> AccountProfileResult:
        async with self._conn_factory() as conn:
            attempts = await list_attempts(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                entity_id=account_entity_id,
            )
            decisions = await list_decisions(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                entity_id=account_entity_id,
            )
            row = await get_account_run(conn, run_id)
        latest = {item.field_key: item for item in decisions}
        planned = tuple(field for aspect in plan.aspects for field in aspect.field_keys)
        terminal = {
            key: decision
            for key, decision in latest.items()
            if decision.terminal_status is not None
        }
        coverage_terminal = set(planned) <= set(terminal)
        aspects = tuple(
            AspectCoverage(
                aspect=aspect.aspect,
                fields_targeted=len(aspect.field_keys),
                fields_filled=sum(
                    terminal.get(key) is not None
                    and terminal[key].terminal_status is ResearchTerminalStatus.FILLED
                    for key in aspect.field_keys
                ),
                fields_empty=sum(
                    terminal.get(key) is not None
                    and terminal[key].terminal_status is not ResearchTerminalStatus.FILLED
                    for key in aspect.field_keys
                ),
                dispositions={
                    key: _terminal_disposition(terminal.get(key)) for key in aspect.field_keys
                },
            )
            for aspect in plan.aspects
        )
        claim_refs = tuple(
            dict.fromkeys(ClaimId(ref) for attempt in attempts for ref in attempt.claim_refs)
        )
        status = (
            WorkerStatus.OK
            if coverage_terminal
            else WorkerStatus.FAILED
            if turn_status is AgentExecutionStatus.FAILED
            else WorkerStatus.PARTIAL
        )
        return AccountProfileResult(
            account_entity_id=account_entity_id,
            tier=tier,
            run_id=run_id,
            status=status,
            aspects=aspects,
            claim_refs=claim_refs,
            cost_cents=row.cost_cents if row is not None else Decimal(0),
            gap_field_count=len(planned),
            cost_already_recorded=True,
            coverage_terminal=coverage_terminal,
        )


def _terminal_disposition(decision: object | None) -> str:
    status = getattr(decision, "terminal_status", None)
    return status.value if isinstance(status, ResearchTerminalStatus) else "unresolved"
