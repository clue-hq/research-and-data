"""C6.8 API-root preparation for one governed account-research deepagent turn."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID, uuid5

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentProfileRegistry,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AgentWorkspaceFactory,
    ArtifactRef,
    CompiledContextCard,
    ContextAssemblyPolicy,
    ContextLayer,
    DeterministicAgentContextAssembler,
    DomainObjectRef,
    LayerBudget,
    ResolvedAgentProfile,
)
from clue_api.account_research_wiring import (
    AccountResearchAgentRuntime,
    build_account_research_execution,
)
from clue_api.agent_execution_wiring import (
    DbAgentPlanJournal,
    postgres_agent_checkpointer,
)
from clue_api.agent_runtime_wiring import CompletionGuard
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_config import Settings
from clue_core import (
    AccountEntity,
    AssemblyRequest,
    EntityId,
    ExecutionId,
    MemoryBundle,
    ProjectRunId,
    RunId,
    operation_id_from_key,
)
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
from clue_fleet import LeaseGeneration, WorkId, acquire_work_lease, release_work_lease
from clue_research.durable import (
    AccountRunRow,
    ProjectRunRow,
    ResearchPlan,
    get_account_run,
    get_project_run,
)
from clue_research.identity import get_account
from clue_spine import Brand, Product, Project, get_brand, get_product, get_project
from clue_toolbelt import ToolInvoker, ToolRegistry

__all__ = [
    "DbCompiledContextCardReader",
    "PreparedAccountResearchTurnRunner",
    "account_research_context_policy",
    "build_account_research_context",
]

_EXECUTION_NAMESPACE_KEY = "account-research-unit@1"
_TURN_NAMESPACE = UUID("85af4b9f-7d41-51ea-a333-7181c4fdb12f")
_PREPARER_WORKER_ID = "agent-account-research-preparer"


class _NoMemoryContext:
    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        del request
        return None


def account_research_context_policy() -> ContextAssemblyPolicy:
    """The exact conservative opening-context budget for account-research@v1."""

    return ContextAssemblyPolicy(
        version="account-research-context-v1",
        token_counter_version="utf8-bytes-v1",
        budgets=tuple(
            LayerBudget(layer=layer, max_tokens=budget)
            for layer, budget in zip(
                tuple(ContextLayer),
                (24_000, 8_000, 24_000, 0, 16_000, 0, 12_000),
                strict=True,
            )
        ),
    )


class DbCompiledContextCardReader:
    """Compile minimal, typed cards from the owning stores; never query agent-owned state."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def read(
        self,
        *,
        workspace_id: str,
        object_type: str,
        object_id: str,
    ) -> CompiledContextCard | None:
        async with self._conn_factory() as conn:
            value: Brand | Product | Project | AccountEntity | None
            if object_type == "brand":
                value = await get_brand(conn, workspace_id=workspace_id, brand_id=object_id)
            elif object_type == "product":
                value = await get_product(conn, object_id)
            elif object_type == "project":
                value = await get_project(conn, object_id)
            elif object_type == "account":
                try:
                    entity_id = EntityId(UUID(object_id))
                except ValueError:
                    return None
                value = await get_account(conn, entity_id)
            else:
                return None
        if value is None or value.workspace_id != workspace_id:
            return None
        return CompiledContextCard(
            ref=DomainObjectRef(
                workspace_id=workspace_id,
                object_type=object_type,
                object_id=object_id,
                version=None,
            ),
            body=value.model_dump_json(exclude_none=False),
        )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _effective_budget_limit(
    settings: Settings,
    *,
    budget_cap_cents: Decimal | None,
    plan: ResearchPlan,
) -> int:
    candidates = [
        value
        for value in (
            budget_cap_cents,
            *(aspect.budget_envelope_cents for aspect in plan.aspects),
        )
        if value is not None
    ]
    if not candidates:
        return settings.agent_account_plan_budget_limit_millicents
    durable_limit = int(min(candidates) * Decimal(1000))
    return min(settings.agent_account_plan_budget_limit_millicents, durable_limit)


class PreparedAccountResearchTurnRunner:
    """Prepare every trusted input, then enter the C6.7 runtime with no hidden defaults."""

    def __init__(
        self,
        *,
        settings: Settings,
        runtime: AccountResearchAgentRuntime,
        profiles: AgentProfileRegistry,
        workspaces: AgentWorkspaceFactory,
        artifacts: DurableAgentArtifactStore,
        turns: DbAgentTurnJournal,
        history: DbAgentHistoryStore,
        contexts: DeterministicAgentContextAssembler,
        tools: ToolRegistry,
        tool_invoker: ToolInvoker,
        executor: RecipeExecutor,
        compatibility: CompatibilityLoader,
        plans: DbAgentPlanJournal,
        recipes: DbRecipeReader,
        starter: DbExecutionStarter,
        parameters: ExecutionParameterStore,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._runtime = runtime
        self._profiles = profiles
        self._workspaces = workspaces
        self._artifacts = artifacts
        self._turns = turns
        self._history = history
        self._contexts = contexts
        self._tools = tools
        self._tool_invoker = tool_invoker
        self._executor = executor
        self._compatibility = compatibility
        self._plans = plans
        self._recipes = recipes
        self._starter = starter
        self._parameters = parameters
        self._conn_factory = conn_factory

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
    ) -> AgentTurnOutcome:
        resolved = self._profiles.resolve(AgentRole.ACCOUNT_RESEARCH)
        project_run, account_run, account, project = await self._load_scope(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_run_id=account_run_id,
            account_entity_id=account_entity_id,
            tier=tier,
        )
        execution_id = ExecutionId(
            operation_id_from_key(str(account_run_id), _EXECUTION_NAMESPACE_KEY)
        )
        revision = await self._recipes.get_by_identity(
            scope_type=RecipeScopeType.SYSTEM,
            workspace_id=None,
            recipe_key="account-research-unit",
            version=1,
        )
        if revision is None:
            raise RuntimeError("promoted account-research-unit@1 is not installed")
        parameter_key, parameter_sha = await self._parameters.snapshot(
            workspace_id=workspace_id,
            parameters={},
        )
        await self._starter.start(
            workspace_id=workspace_id,
            recipe_revision_id=revision.recipe_revision_id,
            parameters={},
            parameter_artifact_key=parameter_key,
            parameter_manifest_hash=parameter_sha,
            actor="agent",
            execution_id=execution_id,
            project_id=project.project_id,
            project_run_id=project_run_id,
        )
        await self._drive_execution(execution_id)

        lease = self._workspaces.acquire(
            workspace_id=workspace_id,
            project_id=project.project_id,
            execution_id=execution_id,
            policy=resolved.profile.workspace,
        )
        focus_ref = DomainObjectRef(
            workspace_id=workspace_id,
            object_type="account",
            object_id=str(account_entity_id),
            version=None,
        )
        stage_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-stage-snapshot+json",
            {
                "schema_version": "1",
                "surface": "account_research",
                "project_run_id": str(project_run_id),
                "account_run_id": str(account_run_id),
                "account_entity_id": str(account_entity_id),
                "tier": tier,
                "plan": plan.model_dump(mode="json"),
            },
            account_entity_id,
        )
        readiness_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-readiness-snapshot+json",
            {
                "schema_version": "1",
                "admitted": True,
                "authority": "deep_phase_account_admission",
                "account_run_status": account_run.status.value,
            },
            account_entity_id,
        )
        budget_limit = _effective_budget_limit(
            self._settings,
            budget_cap_cents=budget_cap_cents,
            plan=plan,
        )
        budget_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-budget-envelope+json",
            {
                "schema_version": "1",
                "limit_millicents": budget_limit,
                "project_budget_cap_cents": (
                    str(project_run.budget_cap_cents)
                    if project_run.budget_cap_cents is not None
                    else None
                ),
                "account_budget_cap_cents": (
                    str(budget_cap_cents) if budget_cap_cents is not None else None
                ),
            },
            account_entity_id,
        )
        manifest_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-resource-manifest+json",
            resolved.resource_manifest.model_dump(mode="json"),
            account_entity_id,
        )
        user_message_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-turn-input+json",
            {
                "schema_version": "1",
                "objective": "Research the remaining governed evidence gaps for this account.",
                "project_run_id": str(project_run_id),
                "account_run_id": str(account_run_id),
                "account_entity_id": str(account_entity_id),
                "tier": tier,
                "planned_field_keys": sorted(
                    field for aspect in plan.aspects for field in aspect.field_keys
                ),
            },
            account_entity_id,
        )
        turn_id = uuid5(_TURN_NAMESPACE, str(account_run_id))
        request = AgentTurnRequest(
            turn_id=turn_id,
            thread_id=f"account-research-{account_run_id}",
            constitution=AgentConstitution(
                workspace_id=workspace_id,
                project_id=project.project_id,
                execution_id=execution_id,
                actor_id="platform-account-research",
                role=AgentRole.ACCOUNT_RESEARCH,
                brand_id=project.brand_id,
                product_id=project.product_id,
                workspace_root_id=lease.identity.workspace_root_id,
                stage_snapshot_ref=stage_ref,
                readiness_snapshot_ref=readiness_ref,
                budget_envelope_ref=budget_ref,
                profile_ref=resolved.profile_ref,
                resource_manifest_ref=manifest_ref,
                resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                focus_refs=(focus_ref,),
            ),
            user_message_artifact_ref=user_message_ref,
            focus_refs=(focus_ref,),
            requested_at=account_run.started_at,
        )
        await self._turns.create(request=request, profile=resolved.profile)
        committed = await self._turns.load_committed_outcome(
            turn_id=turn_id,
            workspace_id=workspace_id,
        )
        if committed is not None:
            await self._complete_recipe_if_needed(committed)
            return committed
        context = await self._contexts.assemble(
            request=request,
            profile=resolved.profile,
            history=await self._history.load(
                workspace_id=workspace_id,
                thread_id=request.thread_id,
            ),
        )
        execution = build_account_research_execution(
            request=request,
            profiles=self._profiles,
            tools=self._tools,
            tool_invoker=self._tool_invoker,
            executor=self._executor,
            compatibility=self._compatibility,
            artifacts=self._artifacts,
            plans=self._plans,
            checkpointer_factory=postgres_agent_checkpointer,
            budget_limit_millicents=budget_limit,
            conn_factory=self._conn_factory,
        )
        outcome = await self._runtime.run(
            request=request,
            context=context,
            lease=lease,
            execution=execution,
            completion_guard=completion_guard,
        )
        await self._complete_recipe_if_needed(outcome)
        return outcome

    async def _complete_recipe_if_needed(self, outcome: AgentTurnOutcome) -> None:
        if outcome.status is not AgentExecutionStatus.COMPLETED:
            return
        await self._executor.decide_gate(
            execution_id=outcome.execution_id,
            node_key="account_research_interactions",
            actor="agent",
            decision="complete",
        )
        status = await self._drive_execution(outcome.execution_id)
        if status is not ExecutionStatus.COMPLETED:
            raise RuntimeError("completed account turn did not complete its durable C5 recipe")

    async def _drive_execution(self, execution_id: ExecutionId) -> ExecutionStatus:
        async with self._conn_factory() as conn:
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id=_PREPARER_WORKER_ID,
            )
        if lease is None:
            raise RuntimeError("account-agent recipe execution is owned by another live worker")
        try:
            result = await self._executor.execute(
                execution_id,
                worker_id=_PREPARER_WORKER_ID,
                lease_generation=lease.generation,
            )
            return result.status
        finally:
            async with self._conn_factory() as conn:
                await release_work_lease(
                    conn,
                    work_id=WorkId(execution_id),
                    worker_id=_PREPARER_WORKER_ID,
                    generation=LeaseGeneration(lease.generation),
                )

    async def _artifact(
        self,
        workspace_id: str,
        media_type: str,
        payload: object,
        account_entity_id: EntityId,
    ) -> ArtifactRef:
        return await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            subject_bindings=((UUID(str(account_entity_id)), "account_context"),),
        )

    async def _load_scope(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        account_entity_id: EntityId,
        tier: str,
    ) -> tuple[ProjectRunRow, AccountRunRow, AccountEntity, Project]:
        async with self._conn_factory() as conn:
            project_run = await get_project_run(conn, project_run_id)
            account_run = await get_account_run(conn, account_run_id)
            account = await get_account(conn, account_entity_id)
            project = (
                await get_project(conn, project_run.project_id) if project_run is not None else None
            )
        if project_run is None or account_run is None or account is None or project is None:
            raise ValueError("account-agent scope is incomplete")
        if (
            project_run.workspace_id != workspace_id
            or project.workspace_id != workspace_id
            or account.workspace_id != workspace_id
            or account_run.project_run_id != project_run_id
            or account_run.entity_id != account_entity_id
            or account_run.tier != tier
            or project.project_id != project_run.project_id
            or project.brand_id != project_run.brand_id
            or project.product_id != project_run.product_id
        ):
            raise ValueError("account-agent scope identities do not agree")
        return project_run, account_run, account, project


def build_account_research_context(
    *,
    resolved_profile: ResolvedAgentProfile,
    artifacts: DurableAgentArtifactStore,
    cards: DbCompiledContextCardReader,
    conn_factory: ConnFactory = transaction,
) -> DeterministicAgentContextAssembler:
    """Build the account role's exact L1-L7 context with memory disabled by recipe contract."""

    from clue_api.agent_platform_wiring import build_agent_context_assembler

    return build_agent_context_assembler(
        resolved_profile=resolved_profile,
        artifacts=artifacts,
        cards=cards,
        memory=_NoMemoryContext(),
        memory_recipe="account-research-unit@1",
        requested_memory_types=(),
        policy=account_research_context_policy(),
        conn_factory=conn_factory,
    )
