"""Detached ARV2 research composed through the shared governed Deep Agent runtime.

The fleet owns the researcher slot. Current researchers own dossier and narrative writing;
specialist registration and delegation are retained only for historical pinned profiles.
Source data stays behind revocable DB/object-storage views; task cards carry references only.
This composition does not enable a launch profile or change an interactive agent's authority.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import replace
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langchain_core.messages import SystemMessage
from pydantic import JsonValue
from sqlalchemy import text

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentModelProvider,
    AgentPlanPolicy,
    AgentProfileRegistry,
    AgentResourceMaterializer,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AgentWorkspaceFactory,
    AgentWorkspaceLease,
    ArtifactRef,
    AssembledAgentContext,
    ContextAssemblyPolicy,
    ContextLayer,
    DeepAgentTurnRuntime,
    DelegationRequest,
    DelegationResult,
    FinalizeStatus,
    LayerBudget,
    ResolvedAgentProfile,
    ToolPin,
    WorkspaceSeedFile,
)
from clue_agents.catalog import FolderProfileCatalog, FolderPromptCatalog, FolderSkillCatalog
from clue_agents.compaction import CompactionSettings
from clue_agents.ports import SpillSink
from clue_agents.tool_result_clearing import BatchedToolResultClearing
from clue_api.agent_compaction import compaction_for
from clue_api.agent_execution_wiring import (
    C5AgentExecutionAdapter,
    CheckpointerFactory,
    DbAgentDelegationRuntime,
    DbAgentPlanJournal,
    postgres_agent_checkpointer,
)
from clue_api.agent_platform_wiring import build_agent_context_assembler
from clue_api.agent_registry_wiring import ToolRegistryAgentCatalog
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    DurableDeepAgentTurnRunner,
    GovernedAgentToolFactory,
)
from clue_api.agent_turn_wiring import DbAgentTurnJournal
from clue_api.arv2.account_research_catalog import (
    CONTACT_ENRICHMENT_POLICY,
    RESEARCH_PROVIDER_POLICY,
)
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.account_research_tools import ToolRuntime
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_committee_tool import (
    NominateBriefedCommitteeTool,
    NominateBriefedWebCommitteeTool,
    NominateCommitteeTool,
    NominateSourceCommitteeTool,
    NominateSourceWebCommitteeTool,
    NominateWebCommitteeTool,
)
from clue_api.arv2.quality_completion import (
    COMPLETION_INSTRUCTIONS,
    build_completion_report,
    completion_notes,
)
from clue_api.arv2.quality_context import read_context
from clue_api.arv2.quality_execution import (
    Allowance,
    SharedResearchAllowance,
    begin_runtime,
    bind_execution,
    finish_runtime,
    reserve,
    runtime_remaining,
)
from clue_api.arv2.quality_findings import (
    RecordContentResearchFindingTool,
    RecordPathResearchFindingTool,
    RecordResearchFindingTool,
)
from clue_api.arv2.quality_json_dossier import (
    BeginDossierRevisionTool,
    DiscardDossierRevisionTool,
    FinishDossierTool,
    SaveDossierSectionTool,
    UpdateDossierFindingsTool,
    ValidateDossierTool,
    uses_json_dossier,
    validate_dossier_handoff,
)
from clue_api.arv2.quality_mapping import QualityProviderWriter
from clue_api.arv2.quality_media_tool import SubmitTranscriptClaimTool
from clue_api.arv2.quality_narrative import SubmitValueNarrativeTool
from clue_api.arv2.quality_owned_narrative import (
    ReadNarrativeInputsTool,
    WriteResearchNarrativeTool,
)
from clue_api.arv2.quality_page_tools import (
    PublishAdvisoryResearchPageTool,
    PublishResearchPageTool,
    ReadPageInputsTool,
)
from clue_api.arv2.quality_provider_tools import AcquireResearchTool
from clue_api.arv2.quality_recipe import RECIPE_26, at_least
from clue_api.arv2.quality_results import QualityJobRunner, ResearchUnitReport, validate_report
from clue_api.arv2.quality_tools import (
    CorrectResearchClaimTool,
    PathProcessingDispositionTool,
    ProcessingDispositionTool,
    SearchEvidenceTool,
    SearchPathEvidenceTool,
    SubmitResearchClaimTool,
)
from clue_api.arv2.quality_views import research_backend
from clue_api.arv2.research_operations import OperationScope
from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    build_tool_invoker,
)
from clue_api.quality_research_artifacts import ResearchArtifacts, ResearchParameterArtifacts
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    seed_system_recipes,
)
from clue_api.specialist_wiring import (
    DbSpecialistExecutionJournal,
    FreshWakeSpecialistRunner,
    SpecialistRuntimeBindings,
)
from clue_config import Settings
from clue_core import (
    AssemblyRequest,
    ExecutionId,
    MemoryBundle,
    MemorySelectionPin,
    MemorySelectionUnavailable,
)
from clue_db import ConnFactory
from clue_execution import (
    CompatibilityLoader,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    ExecutionConflict,
    ExecutionStatus,
    RecipeDefinition,
    RecipeExecutor,
    RecipeScopeType,
)
from clue_fleet import LeaseGeneration, WorkId, acquire_work_lease, release_work_lease
from clue_obs import get_logger
from clue_storage import StorageBackend
from clue_toolbelt import DbIdempotencyStore, ToolRegistry

log = get_logger("arv2.quality.runtime")
CATALOG_ROOT = Path(__file__).parents[2] / "agents" / "catalog" / "research-quality"
ROLES = frozenset(
    {AgentRole.ACCOUNT_RESEARCH, AgentRole.RESEARCH_CLAIMS, AgentRole.RESEARCH_NARRATIVE}
)
SLOT = "research_interactions"
RECIPE = "arv2-quality-unit"
_WORKER = "arv2-quality-inline"


async def _no_crash(point: str, *, execution_id: ExecutionId, node_key: str | None) -> None:
    pass


class _PinnedContextOnly:
    """All factual context comes from the exact research pin, never mutable compiled cards."""

    async def read(self, *, workspace_id: str, object_type: str, object_id: str) -> None:
        return None

    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        return None

    async def select(self, request: AssemblyRequest) -> MemorySelectionUnavailable:
        return MemorySelectionUnavailable(reason="memory_disabled")

    async def resolve(
        self, request: AssemblyRequest, pin: MemorySelectionPin
    ) -> MemorySelectionUnavailable:
        return MemorySelectionUnavailable(reason="memory_disabled")


def quality_tools(
    scope: JobScope,
    storage: StorageBackend,
    *,
    purge: bool,
    acquisition_runtime: ToolRuntime | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    for cls in (
        SubmitResearchClaimTool,
        SubmitTranscriptClaimTool,
        CorrectResearchClaimTool,
        SearchEvidenceTool,
        ProcessingDispositionTool,
        NominateCommitteeTool,
        NominateWebCommitteeTool,
        SubmitValueNarrativeTool,
        ReadPageInputsTool,
        ReadNarrativeInputsTool,
        WriteResearchNarrativeTool,
        PublishResearchPageTool,
        RecordResearchFindingTool,
        RecordPathResearchFindingTool,
        RecordContentResearchFindingTool,
        SearchPathEvidenceTool,
        PathProcessingDispositionTool,
        NominateSourceCommitteeTool,
        NominateSourceWebCommitteeTool,
        NominateBriefedCommitteeTool,
        NominateBriefedWebCommitteeTool,
        PublishAdvisoryResearchPageTool,
        DiscardDossierRevisionTool,
        BeginDossierRevisionTool,
        SaveDossierSectionTool,
        UpdateDossierFindingsTool,
        ValidateDossierTool,
        FinishDossierTool,
    ):
        tool = cls(scope, storage, purge_unevidenced=purge)
        registry.register(tool, make_default=tool.version == "1")
    registry.register(AcquireResearchTool(acquisition_runtime), make_default=True)
    return registry


def quality_profiles(
    tools: ToolRegistry, root: Path = CATALOG_ROOT, *, version: int = 5, person: bool = False
) -> AgentProfileRegistry:
    # Revision 20 researchers own both claims and narratives. Do not make dormant
    # specialist profiles available to these runs; preserve older pinned runtimes.
    active_roles = frozenset({AgentRole.ACCOUNT_RESEARCH}) if version >= 20 else ROLES
    authority = {
        descriptor.address: (
            frozenset({AgentRole.ACCOUNT_RESEARCH})
            if descriptor.name
            in {
                "acquire_research_evidence",
                "nominate_committee_candidate",
                "nominate_web_committee_candidate",
                "discard_dossier_revision",
                "begin_dossier_revision",
                "save_dossier_section",
                "update_dossier_findings",
                "validate_dossier",
                "finish_dossier",
                "read_narrative_inputs",
                "write_research_narrative",
            }
            else frozenset({AgentRole.RESEARCH_NARRATIVE})
            if descriptor.name in {"submit_value_narrative", "publish_research_page"}
            else ROLES
            if descriptor.name
            in {
                "submit_research_claim",
                "record_research_finding",
                "search_evidence",
                "read_research_page_inputs",
            }
            else frozenset({AgentRole.ACCOUNT_RESEARCH, AgentRole.RESEARCH_CLAIMS})
        )
        for descriptor in tools.all_descriptors()
    }
    catalog = ToolRegistryAgentCatalog(tools, authority=authority)
    inventory = tuple(
        catalog.resolve(
            ToolPin(
                name=d.name,
                version=d.version,
                input_schema_sha256=d.input_schema_sha256,
                output_schema_sha256=d.output_schema_sha256,
            )
        )
        for d in tools.all_descriptors()
    )
    return AgentProfileRegistry(
        prompts=FolderPromptCatalog(root / "prompts"),
        skills=FolderSkillCatalog(root / "skills"),
        profiles=FolderProfileCatalog(root / "profiles"),
        tools=catalog,
        tool_inventory=inventory,
        engine_tool_ceiling=frozenset(authority),
        required_roles=active_roles,
        selected_profile_versions={
            role: ("v25-person" if person else "v25")
            if version >= 25 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v24-person" if person else "v24")
            if version >= 24 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v23-person" if person else "v23")
            if version >= 23 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v22-person" if person else "v22")
            if version >= 22 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v21-person" if person else "v21")
            if version >= 21 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v20-person" if person else "v20")
            if version >= 20 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v19-person" if person and role == AgentRole.ACCOUNT_RESEARCH else "v19")
            if version >= 19
            else ("v17-person" if person else "v17")
            if version >= 17 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v16-person" if person else "v16")
            if version >= 16 and role == AgentRole.ACCOUNT_RESEARCH
            else ("v15-person" if person and role == AgentRole.ACCOUNT_RESEARCH else "v15")
            if version >= 15
            else ("v14-person" if person and role == AgentRole.ACCOUNT_RESEARCH else "v14")
            if version >= 14
            else "v13"
            if version >= 13 and not person and role == AgentRole.ACCOUNT_RESEARCH
            else "v12"
            if version >= 12 and not person and role == AgentRole.ACCOUNT_RESEARCH
            else "v11-person"
            if version >= 11 and person and role == AgentRole.ACCOUNT_RESEARCH
            else "v10"
            if version >= 11 and not person and role == AgentRole.ACCOUNT_RESEARCH
            else "v9-person"
            if version >= 9 and person and role == AgentRole.ACCOUNT_RESEARCH
            else "v6"
            if version >= 7 and (person or role != AgentRole.ACCOUNT_RESEARCH)
            else f"v{version}"
            for role in active_roles
        },
    )


def research_compaction_for(
    scope: JobScope, settings: Settings
) -> Callable[[str], CompactionSettings]:
    """Recipe 26+: research compacts at a fixed token count as a backstop to result clearing.

    The shared rule (90% of the model's window: 450k for Grok 4.6) never fired on research,
    whose conversations peaked around 205k tokens (2026-10-06).
    """
    if not at_least(scope, RECIPE_26):
        return compaction_for
    research = CompactionSettings(
        trigger_fraction=0.90,
        keep_fraction=0.10,
        trigger_tokens=settings.arv2_research_compact_trigger_tokens,
        keep_messages=settings.arv2_research_compact_keep_messages,
        context_window=None,
    )
    return lambda model_id: research


def drop_identity_echo(context: AssembledAgentContext, identity: str) -> AssembledAgentContext:
    """Recipe 26+: the runtime already sends the identity as the system message.

    The L1 identity layer also opened the conversation with the same text as a
    ``SystemMessage``, so every call carried the prompt and resource map twice (a third copy
    after a reconciliation continuation). The manifest still records the layer; only the
    duplicate message is not sent.
    """
    kept = tuple(
        m for m in context.messages if not (isinstance(m, SystemMessage) and m.content == identity)
    )
    if kept == context.messages:
        return context
    return context.model_copy(update={"messages": kept})


class _Contexts:
    def __init__(self, runtime: ResearchUnitRuntime):
        self.runtime = runtime

    async def assemble(
        self, *, request: AgentTurnRequest, profile: Any, history: Sequence[Any]
    ) -> AssembledAgentContext:
        runtime = self.runtime
        resolved = runtime.profiles.resolve(profile.role)
        # Model selection is runtime configuration, not a new prompt/skill revision.
        # Keep the identity layer consistent with the exact configured turn profile.
        configured = resolved.profile.model_copy(update={"model": profile.model})
        if configured != profile:
            raise ValueError("Research context profile differs beyond model configuration")
        resolved = replace(resolved, profile=configured)
        assembled = await build_agent_context_assembler(
            resolved_profile=resolved,
            artifacts=runtime.artifacts,
            cards=_PinnedContextOnly(),
            memory=_PinnedContextOnly(),
            memory_recipe=RECIPE,
            requested_memory_types=(),
            policy=ContextAssemblyPolicy(
                version="research-quality-v1",
                token_counter_version="utf8-bytes-v1",
                budgets=tuple(
                    LayerBudget(layer=layer, max_tokens=budget)
                    for layer, budget in zip(
                        tuple(ContextLayer), (24000, 0, 12000, 0, 2000, 0, 16000), strict=True
                    )
                ),
            ),
            conn_factory=runtime.connections,
        ).assemble(request=request, profile=profile, history=history)
        if at_least(runtime.scope, RECIPE_26):
            assembled = drop_identity_echo(assembled, resolved.system_prompt)
        return assembled


class _ChildExecutions(DbSpecialistExecutionJournal):
    def __init__(self, runtime: ResearchUnitRuntime):
        self.runtime = runtime

    async def begin(
        self, *, request: DelegationRequest, child_execution_id: ExecutionId, project_id: str
    ) -> None:
        runtime = self.runtime
        if project_id != runtime.scope.project_id:
            raise ValueError("specialist belongs to another project")
        async with runtime.connections() as conn:
            await resolve_authority(conn, runtime.scope, request.parent_execution_id)
            await reserve(
                conn,
                runtime.operation_scope,
                execution_id=request.parent_execution_id,
                kind="delegation",
                activity_id=request.delegation_id,
            )
        await runtime.prepare(
            child_execution_id,
            parent=request.parent_execution_id,
            task_ref=request.task_artifact_ref,
        )


class _ChildFactory:
    def __init__(self, runtime: ResearchUnitRuntime):
        self.runtime = runtime

    def __call__(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        budget_limit_millicents: int,
    ) -> C5AgentExecutionAdapter:
        return self.runtime.adapter(request, resolved_profile)

    def record_only(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        budget_limit_millicents: int,
    ) -> C5AgentExecutionAdapter:
        return self.runtime.adapter(request, resolved_profile)


class _Workspaces:
    def __init__(self, workspaces: AgentWorkspaceFactory, artifacts: ResearchArtifacts):
        self.workspaces = workspaces
        self.artifacts = artifacts

    def acquire(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        execution_id: ExecutionId,
        resolved_profile: ResolvedAgentProfile,
    ) -> AgentWorkspaceLease:
        return self.workspaces.acquire(
            workspace_id=workspace_id,
            project_id=project_id,
            thread_id=thread_id,
            execution_id=execution_id,
            policy=resolved_profile.profile.workspace,
            artifact_sink=self.artifacts,
        )


class _InlineChild:
    def __init__(self, runtime: ResearchUnitRuntime, runner: FreshWakeSpecialistRunner):
        self.runtime = runtime
        self.runner = runner
        self.lock = asyncio.Lock()

    async def run(
        self,
        *,
        request: DelegationRequest,
        child_execution_id: ExecutionId,
        resolved_profile: ResolvedAgentProfile,
    ) -> DelegationResult:
        async with self.lock:
            result = await self.runner.run(
                request=request,
                child_execution_id=child_execution_id,
                resolved_profile=resolved_profile,
            )
            if result.status == "completed":
                await self.runtime.complete(child_execution_id)
            return result


class ResearchUnitRuntime:
    """One job's detached C5 composition. Construct after its immutable context is persisted."""

    def __init__(
        self,
        *,
        scope: JobScope,
        context_id: UUID,
        settings: Settings,
        storage: StorageBackend,
        connections: ConnFactory,
        models: AgentModelProvider,
        workspaces: AgentWorkspaceFactory,
        tools: ToolRegistry,
        limits: Allowance,
        unit_key: str | None = None,
        checkpointer_factory: CheckpointerFactory = postgres_agent_checkpointer,
        reconciliation: dict[str, Any] | None = None,
    ):
        self.scope, self.context_id = scope, context_id
        self.reconciliation = reconciliation
        self._spill_sinks: dict[ExecutionId, SpillSink] = {}
        self.runtime_owner: UUID | None = None
        self.execution_id = ExecutionId(
            uuid5(
                NAMESPACE_URL,
                f"research-quality:{scope.job_id}:{unit_key}"
                if unit_key
                else f"research-quality:{scope.job_id}",
            )
        )
        self.settings, self.storage, self.connections = settings, storage, connections
        self.models, self.workspaces, self.tools, self.limits = models, workspaces, tools, limits
        self.operation_scope = OperationScope(
            scope.workspace_id, scope.run_id, scope.job_id, scope.account_id
        )
        acquisition = cast(AcquireResearchTool, tools.get("acquire_research_evidence", "1"))
        if acquisition.runtime is not None:
            if acquisition.runtime.scope != scope:
                raise ValueError("acquisition belongs to another research job")
            acquisition.runtime._writer = QualityProviderWriter(
                scope,
                storage,
                self.execution_id,
                acquisition.runtime.catalog,
                purge=settings.unevidenced_row_purge_enabled,
            )
        self.artifacts = ResearchArtifacts(storage=storage, conn_factory=connections)
        self.artifacts.scope = scope
        self.artifacts.context_id = context_id
        self.turns = DbAgentTurnJournal(conn_factory=connections)
        self.resource_version = int((scope.input_refs or {}).get("quality_recipe_version", 5))
        self.profiles = quality_profiles(
            tools, version=self.resource_version, person=scope.subject_kind == "person"
        )
        self.checkpointer_factory = checkpointer_factory
        self.plans = DbAgentPlanJournal(conn_factory=connections)
        self.contexts = _Contexts(self)
        pins = build_recipe_pin_registry(tool_registry=tools, conn_factory=connections)
        self.compatibility = CompatibilityLoader(pins)
        self.lifecycle = build_recipe_lifecycle(
            tool_registry=tools, conn_factory=connections, pin_registry=pins
        )
        self.recipes = DbRecipeReader(conn_factory=connections)
        self.parameters = StorageExecutionParameterStore(ResearchParameterArtifacts(self.artifacts))
        self.invoker = build_tool_invoker(
            registry=tools,
            idempotency_store=DbIdempotencyStore(conn_factory=connections),
            storage=storage,
            settings=settings,
            conn_factory=connections,
            parameter_artifacts=ResearchParameterArtifacts(self.artifacts),
        )
        journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
        self.starter = DbExecutionStarter(
            conn_factory=connections,
            recipes=self.recipes,
            compatibility=self.compatibility,
            journal=journal,
        )
        self.executor = RecipeExecutor(
            conn_factory=connections,
            recipes=self.recipes,
            compatibility=self.compatibility,
            journal=journal,
            parameters=self.parameters,
            tool_invoker=self.invoker,
            max_concurrency=1,
        )

    async def install(self) -> None:
        definition = RecipeDefinition.model_validate_json(
            (CATALOG_ROOT / f"recipe-v{self.resource_version}.json").read_bytes()
        )
        await seed_system_recipes(
            repository=DbRecipeRepository(conn_factory=self.connections),
            lifecycle=self.lifecycle,
            definitions=(definition,),
        )

    async def prepare(
        self,
        execution_id: ExecutionId,
        *,
        parent: ExecutionId | None = None,
        task_ref: ArtifactRef | None = None,
    ) -> None:
        recipe = await self.recipes.get_by_identity(
            scope_type=RecipeScopeType.SYSTEM,
            workspace_id=None,
            recipe_key=RECIPE,
            version=self.resource_version,
        )
        if recipe is None:
            raise RuntimeError("research quality recipe is not installed")
        parameters: dict[str, JsonValue] = {
            "job_id": str(self.scope.job_id),
            "context_id": str(self.context_id),
            "task_sha256": task_ref.sha256 if task_ref else None,
        }
        key, sha = await self.parameters.snapshot(
            workspace_id=self.scope.workspace_id, parameters=parameters
        )
        await self.starter.start(
            workspace_id=self.scope.workspace_id,
            project_id=self.scope.project_id,
            execution_id=execution_id,
            parent_execution_id=parent,
            recipe_revision_id=recipe.recipe_revision_id,
            parameters=parameters,
            parameter_artifact_key=key,
            parameter_manifest_hash=sha,
            actor="agent",
        )
        await self.drive(execution_id)

    async def drive(self, execution_id: ExecutionId) -> ExecutionStatus:
        async with self.connections() as conn:
            lease = await acquire_work_lease(conn, work_id=WorkId(execution_id), worker_id=_WORKER)
        if lease is None:
            raise RuntimeError("research execution is owned by another worker")
        try:
            result = await self.executor.execute(
                execution_id, worker_id=_WORKER, lease_generation=lease.generation
            )
            return result.status
        finally:
            async with self.connections() as conn:
                await release_work_lease(
                    conn,
                    work_id=WorkId(execution_id),
                    worker_id=_WORKER,
                    generation=LeaseGeneration(lease.generation),
                )

    async def complete(self, execution_id: ExecutionId) -> None:
        # A replay may have already closed the gate; the terminal status is still verified.
        with suppress(ExecutionConflict):
            await self.executor.decide_gate(
                execution_id=execution_id, node_key=SLOT, actor="agent", decision="complete"
            )
        if await self.drive(execution_id) is not ExecutionStatus.COMPLETED:
            raise RuntimeError("research finalization did not complete its recipe")

    def adapter(
        self,
        request: AgentTurnRequest,
        resolved: ResolvedAgentProfile,
        delegation: DbAgentDelegationRuntime | None = None,
        spill_sink: SpillSink | None = None,
    ) -> C5AgentExecutionAdapter:
        # Older pinned profiles have no reads/ authority; retain their existing behavior
        # rather than turning a previously valid 12–16 KiB result into a workspace refusal.
        active_spill_sink = (
            spill_sink or self._spill_sinks.get(request.constitution.execution_id)
            if "reads" in resolved.profile.workspace.readable_prefixes
            else None
        )
        return C5AgentExecutionAdapter(
            turn_id=request.turn_id,
            constitution=request.constitution,
            resolved_profile=resolved,
            policy=AgentPlanPolicy.from_profile(
                resolved.profile,
                budget_limit_millicents=0,
                budget_mode="record_only",
                max_fanout=1,
                max_parallelism=1,
                max_rounds=self.limits.model_calls,
            ),
            slot_key=SLOT,
            tools=self.tools,
            tool_invoker=self.invoker,
            executor=self.executor,
            artifacts=self.artifacts,
            journal=self.plans,
            checkpointer_factory=self.checkpointer_factory,
            delegation=delegation,
            conn_factory=self.connections,
            spill_sink=active_spill_sink,
        )

    async def bindings(
        self, request: AgentTurnRequest, resolved: ResolvedAgentProfile, lease: AgentWorkspaceLease
    ) -> SpecialistRuntimeBindings:
        execution = request.constitution.execution_id
        # Fresh-wake bindings precede construction of the child's adapter. Each execution
        # must spill into its own readable workspace, including after recovery/reacquisition.
        self._spill_sinks[execution] = lease.backend
        async with self.connections() as conn:
            parent = (
                await conn.execute(
                    text("SELECT parent_execution_id FROM execution WHERE id=:id"),
                    {"id": execution},
                )
            ).scalar_one()
            await bind_execution(
                conn,
                self.operation_scope,
                execution_id=execution,
                context_id=self.context_id,
                role=request.constitution.role.value,
                limits=self.limits,
                parent_execution_id=parent,
            )
            await resolve_authority(conn, self.scope, execution)

        async def before_work() -> None:
            async with self.connections() as conn:
                await resolve_authority(conn, self.scope, execution)
                if self.runtime_owner is not None:
                    await runtime_remaining(conn, self.operation_scope, owner=self.runtime_owner)

        from clue_api.arv2.quality_dossier import AccountDossierPersistence, uses_account_dossier

        dossier_middleware = (
            (
                AccountDossierPersistence(
                    self.connections, self.storage, self.scope, execution, lease.backend
                ),
            )
            if uses_account_dossier(self.scope)
            and not uses_json_dossier(self.scope)
            and request.constitution.role == AgentRole.ACCOUNT_RESEARCH
            else ()
        )
        return SpecialistRuntimeBindings(
            backend=research_backend(
                lease.backend,
                self.connections,
                self.storage,
                self.scope,
                execution,
                capabilities=cast(
                    AcquireResearchTool, self.tools.get("acquire_research_evidence", "1")
                ).capabilities(),
            ),
            middleware=(
                *(
                    (
                        BatchedToolResultClearing(
                            trigger_tokens=self.settings.arv2_research_clear_trigger_tokens,
                            target_tokens=self.settings.arv2_research_clear_target_tokens,
                        ),
                    )
                    if at_least(self.scope, RECIPE_26)
                    else ()
                ),
                *dossier_middleware,
                SharedResearchAllowance(
                    self.connections,
                    self.operation_scope,
                    execution,
                    domain_tools=frozenset(d.name for d in self.tools.all_descriptors()),
                ),
            ),
            before_work=before_work,
            max_model_rounds=self.limits.model_calls,
            disable_runtime_timeout=self.settings.arv2_account_max_runtime_s == 0,
        )

    async def spend_millicents(self, *, execution_id: ExecutionId, workspace_id: str) -> int:
        # This is the delegation ledger's known charged component. The root spend report also
        # records every unpriced model row; this scalar is never used as a completeness claim.
        async with self.connections() as conn:
            cost = (
                await conn.execute(
                    text(
                        "SELECT COALESCE(sum(cost_usd),0) FROM agent_model_call "
                        "WHERE execution_id=:id AND workspace_id=:ws"
                    ),
                    {"id": execution_id, "ws": workspace_id},
                )
            ).scalar_one()
        return int((Decimal(cost) * 100000).to_integral_value(rounding=ROUND_CEILING))

    async def artifact(self, value: object, kind: str) -> ArtifactRef:
        return await self.artifacts.persist_body(
            workspace_id=self.scope.workspace_id,
            data=json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(),
            media_type=f"application/vnd.clue.{kind}+json",
            subject_bindings=((self.scope.person_subject_id or self.scope.account_id, "context"),),
            project_bindings=((self.scope.project_id, "research_quality"),),
        )

    async def run(self, *, objective: str, model_id: str | None = None) -> AgentTurnOutcome:
        await self.install()
        execution = self.execution_id
        await self.prepare(execution)
        resolved = self.profiles.resolve(AgentRole.ACCOUNT_RESEARCH)
        if model_id:
            resolved = replace(
                resolved,
                profile=resolved.profile.model_copy(
                    update={
                        "model": resolved.profile.model.model_copy(update={"model_id": model_id})
                    }
                ),
            )
        continuation_config = None
        if self.reconciliation is not None:
            # The source identity is derived from the authorized parent job, never model input.
            source_execution = ExecutionId(
                uuid5(NAMESPACE_URL, f"research-quality:{self.scope.job_id}")
            )
            async with self.connections() as conn:
                await resolve_authority(conn, self.scope, source_execution)
                from clue_api.arv2.quality_reconciliation import account_research_model

                recorded_model = await account_research_model(conn, self.scope)
            resolved = replace(
                resolved,
                profile=resolved.profile.model_copy(
                    update={
                        "model": resolved.profile.model.model_copy(
                            update={"model_id": recorded_model}
                        )
                    }
                ),
            )
            continuation_config = {
                "configurable": {
                    "thread_id": str(source_execution),
                    "checkpoint_ns": "",
                }
            }
        thread = f"research-quality-{execution}"
        lease = self.workspaces.acquire(
            workspace_id=self.scope.workspace_id,
            project_id=self.scope.project_id,
            thread_id=thread,
            execution_id=execution,
            policy=resolved.profile.workspace,
            artifact_sink=self.artifacts,
        )
        try:
            async with self.connections() as conn:
                context = await read_context(
                    conn,
                    self.storage,
                    workspace_id=self.scope.workspace_id,
                    project_id=self.scope.project_id,
                    context_id=self.context_id,
                )
                started = (
                    await conn.execute(
                        text("SELECT started_at FROM execution WHERE id=:id"), {"id": execution}
                    )
                ).scalar_one()
            card = await self.artifact(
                {
                    "context_id": str(self.context_id),
                    "context_path": "/research/context.json",
                    "evidence_path": "/evidence/index.json",
                    "subject_kind": self.scope.subject_kind,
                    "subject_id": str(self.scope.person_subject_id or self.scope.account_id),
                    "account_id": str(self.scope.account_id),
                    "account_name": self.scope.account_name,
                    "account_domain": self.scope.account_domain,
                    "context_gaps": context.gaps,
                    "contact_enrichment_policy": CONTACT_ENRICHMENT_POLICY,
                    "research_provider_policy": RESEARCH_PROVIDER_POLICY,
                },
                "research-quality-card",
            )
            budget = await self.artifact(
                {"mode": "record_only", "limit_millicents": 0}, "agent-budget-envelope"
            )
            manifest = await self.artifact(
                resolved.resource_manifest.model_dump(mode="json"), "agent-resource-manifest"
            )
            task = await self.artifact(
                {
                    "objective": objective,
                    **(
                        {"completion_contract": COMPLETION_INSTRUCTIONS}
                        if uses_json_dossier(self.scope)
                        else {}
                    ),
                    "context_id": str(self.context_id),
                    "job_id": str(self.scope.job_id),
                },
                "agent-turn-input",
            )
            request = AgentTurnRequest(
                turn_id=uuid5(NAMESPACE_URL, f"research-quality-turn:{execution}"),
                thread_id=thread,
                constitution=AgentConstitution(
                    workspace_id=self.scope.workspace_id,
                    project_id=self.scope.project_id,
                    execution_id=execution,
                    actor_id="system",
                    role=AgentRole.ACCOUNT_RESEARCH,
                    brand_id=context.brand_id,
                    workspace_root_id=lease.identity.workspace_root_id,
                    project_card_ref=card,
                    budget_envelope_ref=budget,
                    profile_ref=resolved.profile_ref,
                    resource_manifest_ref=manifest,
                    resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                ),
                user_message_artifact_ref=task,
                requested_at=started,
            )
            await self.turns.create(request=request, profile=resolved.profile)
            bindings = await self.bindings(request, resolved, lease)
            prior = await self.turns.load_committed_outcome(
                turn_id=request.turn_id, workspace_id=self.scope.workspace_id
            )
            if prior is not None:
                if prior.status is AgentExecutionStatus.COMPLETED:
                    await self.complete(execution)
                return prior
            if self.reconciliation is not None:
                from clue_api.arv2.quality_reconciliation import ReconciliationReply

                # Preserve the original workspace notes and native compaction archive.
                # Current evidence remains a live, authorized research_backend view.
                source_lease = self.workspaces.acquire(
                    workspace_id=self.scope.workspace_id,
                    project_id=self.scope.project_id,
                    thread_id=f"research-quality-{source_execution}",
                    execution_id=source_execution,
                    policy=resolved.profile.workspace,
                    artifact_sink=self.artifacts,
                )
                try:
                    existing = {e.path for e in await lease.backend.list_entries()}
                    for prefix in ("work", "scratch", "reads"):
                        if prefix not in resolved.profile.workspace.readable_prefixes:
                            continue
                        for entry in await source_lease.backend.list_entries(prefix):
                            if entry.path not in existing:
                                content = await source_lease.backend.read_text(entry.path)
                                if prefix == "reads":
                                    await asyncio.to_thread(
                                        lease.backend.write_spill,
                                        Path(entry.path).stem,
                                        content.encode(),
                                    )
                                else:
                                    await lease.backend.write_text(entry.path, content)
                finally:
                    source_lease.release()
                for path, value in (
                    (
                        "work/reconciliation/input.json",
                        {k: v for k, v in self.reconciliation.items() if not k.startswith("_")},
                    ),
                    ("work/reconciliation/schema.json", ReconciliationReply.model_json_schema()),
                ):
                    content = json.dumps(value, ensure_ascii=False)
                    entries = {e.path for e in await lease.backend.list_entries("work")}
                    if path not in entries:
                        await lease.backend.write_text(path, content)
                instructions_path = "work/reconciliation/instructions.md"
                if instructions_path not in {
                    e.path for e in await lease.backend.list_entries("work")
                }:
                    await lease.backend.write_text(
                        instructions_path, self.reconciliation["_editorial_system"]
                    )
            owner = uuid4()
            async with self.connections() as conn:
                remaining_runtime = await begin_runtime(conn, self.operation_scope, owner=owner)
            self.runtime_owner = owner
            assembled = await self.contexts.assemble(
                request=request, profile=resolved.profile, history=()
            )
            materializer = AgentResourceMaterializer()
            seeds = tuple(
                WorkspaceSeedFile(
                    path=i.path, content=i.data, sha256=i.sha256, media_type=i.media_type
                )
                for i in assembled.materializations
            )
            if lease.resources_frozen:
                materializer.verify_materialized(
                    lease=lease, snapshot=resolved.resource_snapshot, seed_files=seeds
                )
            else:
                materializer.materialize(
                    lease=lease, snapshot=resolved.resource_snapshot, seed_files=seeds
                )
            delegation = None
            if resolved.profile.delegation_roles:
                child = FreshWakeSpecialistRunner(
                    parent_request=request,
                    profiles=self.profiles,
                    models=self.models,
                    turns=self.turns,
                    artifacts=self.artifacts,
                    tools=self.tools,
                    contexts=self.contexts,
                    workspaces=_Workspaces(self.workspaces, self.artifacts),
                    execution_factory=_ChildFactory(self),
                    spend=self,
                    executions=_ChildExecutions(self),
                    bindings=self.bindings,
                    conn_factory=self.connections,
                )
                delegation = DbAgentDelegationRuntime(
                    registry=self.profiles,
                    child_runner=_InlineChild(self, child),
                    conn_factory=self.connections,
                )
            adapter = self.adapter(request, resolved, delegation, spill_sink=lease.backend)
            adapter.bind_finalization_authority(
                AgentFinalizationAuthority(
                    lease=lease,
                    artifacts=self.artifacts,
                    turns=self.turns,
                    crash_hook=_no_crash,
                    conn_factory=self.connections,
                )
            )

            async def completion_guard(model_input: Any) -> None:
                if model_input.status is FinalizeStatus.COMPLETED:
                    if self.reconciliation is not None:
                        from clue_api.arv2.quality_reconciliation import parse_updates

                        try:
                            reply = json.loads(
                                await lease.backend.read_text("outputs/reconciliation.json")
                            )
                            parse_updates(reply, self.reconciliation["_validation_packet"])
                        except (ValueError, OSError) as exc:
                            raise ValueError(
                                "Invalid /outputs/reconciliation.json: "
                                + str(exc)
                                + ". Read /work/reconciliation/schema.json. Correct those fields "
                                "or citations and retry finalize_turn. No sections were changed. "
                                "Updates accept page and section only. "
                                "Headings belong in section.items[].h2."
                            ) from exc
                        return
                    if uses_json_dossier(self.scope):
                        # The researcher supplies judgment; storage supplies bookkeeping.
                        entries = await lease.backend.list_entries("outputs")
                        raw = (
                            await lease.backend.read_text("outputs/research.json")
                            if any(e.path == "outputs/research.json" for e in entries)
                            else None
                        )
                        notes = completion_notes(raw, model_input.user_message)
                        async with self.connections() as conn:
                            report = await build_completion_report(
                                conn, self.storage, self.scope, self.context_id, notes
                            )
                        if raw is None:
                            await lease.backend.write_text(
                                "outputs/research.json", report.model_dump_json()
                            )
                        else:
                            await lease.backend.edit_text(
                                "outputs/research.json", old=raw, new=report.model_dump_json()
                            )
                        return
                    report = ResearchUnitReport.model_validate_json(
                        await lease.backend.read_text("outputs/research.json")
                    )
                    async with self.connections() as conn:
                        await validate_report(conn, self.scope, self.context_id, report)
                        await validate_dossier_handoff(
                            conn, self.storage, self.scope, self.context_id, report.claim_ids
                        )

            governed = GovernedAgentToolFactory(
                request=request,
                resolved_profile=resolved,
                registry=self.tools,
                execution=adapter,
                lease=lease,
                artifacts=self.artifacts,
                before_work=bindings.before_work,
                required_output_path="outputs/reconciliation.json"
                if self.reconciliation is not None
                else None
                if uses_json_dossier(self.scope)
                else "outputs/research.json",
                completion_guard=completion_guard,
            ).build()
            if self.reconciliation is not None:
                # The resumed researcher may inspect its workspace and submit a validated
                # artifact. It cannot acquire evidence, launch jobs, import claims or publish
                # pages outside the reconciliation transaction.
                governed = tuple(tool for tool in governed if tool.name == "finalize_turn")
            elif uses_json_dossier(self.scope):
                for tool in governed:
                    if tool.name == "finalize_turn":
                        tool.description += "\n\n" + COMPLETION_INSTRUCTIONS
            outcome = await DurableDeepAgentTurnRunner(
                runtime=DeepAgentTurnRuntime(
                    compaction_for=research_compaction_for(self.scope, self.settings),
                    models=self.models,
                    execution=adapter,
                    max_runtime_s=(
                        min(
                            remaining_runtime,
                            resolved.profile.turn_timeout_s,
                            float(self.settings.arv2_account_max_runtime_s),
                        )
                        if self.settings.arv2_account_max_runtime_s
                        else None
                    ),
                    max_rounds=self.limits.model_calls,
                    middleware=bindings.middleware,
                    long_turn_alert_s=self.settings.agent_long_turn_alert_s or None,
                    continuation_config=continuation_config,
                ),
                turns=self.turns,
                artifacts=self.artifacts,
                before_work=bindings.before_work,
                conn_factory=self.connections,
            ).run(
                request=request,
                resolved_profile=resolved,
                context=assembled,
                lease=lease,
                tools=governed,
                backend=bindings.backend,
            )
            if outcome.status is AgentExecutionStatus.COMPLETED:
                await self.complete(execution)
            log.info(
                "arv2.quality.unit_finished",
                job_id=str(self.scope.job_id),
                execution_id=str(execution),
                context_id=str(self.context_id),
                status=outcome.status.value,
            )
            return outcome
        finally:
            if self.runtime_owner is not None:

                async def settle_runtime() -> None:
                    async with self.connections() as conn:
                        await finish_runtime(
                            conn, self.operation_scope, owner=cast(UUID, self.runtime_owner)
                        )

                await asyncio.shield(settle_runtime())
                self.runtime_owner = None
            lease.release()

    async def reconciliation_output(self, outcome: AgentTurnOutcome) -> dict[str, Any]:
        if outcome.status is not AgentExecutionStatus.COMPLETED or outcome.finalization_ref is None:
            raise ValueError(
                f"Account reconciliation continuation did not complete: {outcome.failure_code}"
            )
        envelope = AgentFinalizeEnvelope.model_validate_json(
            await self.artifacts.read(outcome.finalization_ref)
        )
        replies = []
        assert self.reconciliation is not None
        from clue_api.arv2.quality_reconciliation import parse_updates

        for ref in envelope.output_refs:
            try:
                body = json.loads(await self.artifacts.read(ref))
            except (ValueError, UnicodeError):
                continue
            if isinstance(body, dict) and "updates" in body:
                parse_updates(body, self.reconciliation["_validation_packet"])
                replies.append(body)
        if len(replies) != 1:
            raise ValueError("Reconciliation requires exactly one validated output artifact")
        return replies[0]

    async def report(self, outcome: AgentTurnOutcome) -> ResearchUnitReport | None:
        if outcome.finalization_ref is None:
            return None
        envelope = AgentFinalizeEnvelope.model_validate_json(
            await self.artifacts.read(outcome.finalization_ref)
        )
        reports = []
        for ref in envelope.output_refs:
            try:
                raw = json.loads(await self.artifacts.read(ref))
            except (ValueError, UnicodeError):
                continue
            if isinstance(raw, dict) and raw.get("schema_version") == "research-unit-v1":
                reports.append(ResearchUnitReport.model_validate(raw))
        if len(reports) != 1:
            if outcome.status is AgentExecutionStatus.COMPLETED:
                raise ValueError("completed research requires exactly one typed unit report")
            return None
        async with self.connections() as conn:
            await validate_report(conn, self.scope, self.context_id, reports[0])
            if outcome.status is AgentExecutionStatus.COMPLETED:
                await validate_dossier_handoff(
                    conn, self.storage, self.scope, self.context_id, reports[0].claim_ids
                )
        return reports[0]


def build_quality_job_runner(
    *,
    settings: Settings,
    storage: StorageBackend,
    connections: ConnFactory,
    models: AgentModelProvider,
    workspaces: AgentWorkspaceFactory | None = None,
) -> QualityJobRunner:
    """Lazy fleet composition: legacy workers need no quality workspace until a pinned job."""
    from clue_api.agent_workspace_wiring import build_agent_workspace_factory
    from clue_api.arv2.quality_results import QualityJobOutcome

    async def run(
        *,
        scope: JobScope,
        context_id: UUID,
        runtime: ToolRuntime,
        objective: str,
        model_id: str,
        unit_key: str | None = None,
        reconciliation: dict[str, Any] | None = None,
    ) -> QualityJobOutcome:
        active_workspaces = workspaces or build_agent_workspace_factory(
            storage=storage, settings=settings
        )
        try:
            owner = ResearchUnitRuntime(
                scope=scope,
                context_id=context_id,
                settings=settings,
                storage=storage,
                connections=connections,
                models=models,
                workspaces=active_workspaces,
                tools=quality_tools(
                    scope,
                    storage,
                    purge=settings.unevidenced_row_purge_enabled,
                    acquisition_runtime=runtime,
                ),
                limits=Allowance(
                    settings.arv2_account_max_model_rounds,
                    settings.arv2_account_max_model_rounds
                    * settings.arv2_account_max_tool_calls_per_round,
                    settings.arv2_account_max_model_rounds,
                    settings.arv2_account_max_runtime_s * 1000,
                ),
                unit_key=unit_key,
                reconciliation=reconciliation,
            )
            result = await owner.run(objective=objective, model_id=model_id)
            reply = (
                await owner.reconciliation_output(result) if reconciliation is not None else None
            )
            report = None if reconciliation is not None else await owner.report(result)
            return QualityJobOutcome(
                execution_id=result.execution_id,
                status=result.status.value,
                finalization_key=result.finalization_ref.artifact_key
                if result.finalization_ref
                else None,
                report=report,
                failure_code=result.failure_code,
                reconciliation_reply=reply,
            )
        finally:
            if workspaces is None:
                active_workspaces.close()

    return run
