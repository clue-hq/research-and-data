"""The onboarding synthesis turn (ARV2-ONBOARDING-PLAN.md §5; O4).

This module lives outside ``clue_api.arv2`` because it composes the agent/execution substrate:
one governed deepagent turn per onboarding run, executed inside the promoted
``onboarding-synthesis-unit@1`` recipe, under a per-brand system project row.

The shape is the account-research unit runner (``account_research_wiring`` +
``account_research_turn_wiring``) with the account scope replaced by the **brand** scope: the
brand's current knowledge documents are materialized read-only under ``inputs/brand/knowledge/``,
and the turn's ``outputs/`` become new ``brand_knowledge_document`` rows stamped with
``produced_by_turn_id``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentPlanPolicy,
    AgentResourceMaterializer,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    AgentWorkspaceLease,
    ArtifactRef,
    ContextAssemblyPolicy,
    ContextLayer,
    DeepAgentTurnRuntime,
    DeterministicAgentContextAssembler,
    LayerBudget,
    ResolvedAgentProfile,
    WorkspaceSeedFile,
)
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_execution_wiring import (
    C5AgentExecutionAdapter,
    CheckpointerFactory,
    DbAgentPlanJournal,
    postgres_agent_checkpointer,
)
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    build_agent_context_assembler,
)
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    DurableDeepAgentTurnRunner,
    GovernedAgentToolFactory,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_api.stage0_recipe import RecipeStep, StepPinProvider
from clue_config import Secrets, Settings
from clue_core import (
    AssemblyRequest,
    ExecutionId,
    MemoryBundle,
    operation_id_from_key,
)
from clue_db import ConnFactory, transaction
from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    DbExecutionStarter,
    DbRecipeReader,
    ExecutionConflict,
    ExecutionParameterStore,
    ExecutionStatus,
    PinRequest,
    RecipeExecutor,
    RecipeScopeType,
)
from clue_fleet import LeaseGeneration, WorkId, acquire_work_lease, release_work_lease
from clue_obs import get_logger
from clue_spine import get_brand
from clue_storage import StorageBackend, read_verified_artifact
from clue_toolbelt import ToolContext, ToolInvoker, ToolRegistry

__all__ = [
    "BUDGET_LIMIT_MILLICENTS",
    "EXECUTION_NAMESPACE_KEY",
    "INPUT_PREFIX",
    "SYNTHESIS_CARD_MEDIA_TYPE",
    "TURN_NAMESPACE",
    "OnboardingSynthesisLauncher",
    "OnboardingSynthesisResult",
    "OnboardingSynthesisStepPinProvider",
    "build_onboarding_synthesis_context",
    "build_onboarding_synthesis_launcher",
    "ensure_onboarding_project",
    "onboarding_project_id",
    "onboarding_synthesis_context_policy",
]

log = get_logger("clue_api.onboarding_synthesis_wiring")

#: The deterministic execution namespace: one execution per onboarding run, per recipe identity.
EXECUTION_NAMESPACE_KEY = "onboarding-synthesis-unit@1"
#: The uuid5 namespace for this surface's turn ids — one turn per onboarding run.
TURN_NAMESPACE = UUID("6c2f9d0e-4b3a-5f1e-9a77-0e2b4c8d1f55")
#: The $5 record-only ceiling the C5 plan policy enforces for one synthesis turn.
BUDGET_LIMIT_MILLICENTS = 500_000
SYNTHESIS_CARD_MEDIA_TYPE = "application/vnd.clue.onboarding-synthesis-card+json"
#: Every brand knowledge document is materialized read-only below this workspace prefix.
INPUT_PREFIX = "inputs/brand/knowledge/"

_RECIPE_KEY = "onboarding-synthesis-unit"
_RECIPE_VERSION = 1
_GATE_NODE_KEY = "onboarding_synthesis_interactions"
_PREPARER_WORKER_ID = "agent-onboarding-synthesis-preparer"
_EVIDENCE_TOOL_NAME = "exa_search_evidence"
_EVIDENCE_TOOL_VERSION = "1"
_PERSONA_SKILL_KEY = "audience-persona"

#: A document is servable input when its bytes exist and it has not been superseded.
_SERVABLE_STATUSES = ("ready", "proposed", "confirmed")
#: Synthesis needs both halves of the brand's story: who the company is, and what it sells.
_REQUIRED_INPUT_KINDS = frozenset({"company-overview", "product-catalog"})

#: The two document kinds this turn may produce, and the durable status each is born with. An ICP
#: is a *proposal* a human confirms; a persona is a derived reading of a confirmed-or-proposed ICP
#: and is simply ready.
_OUTPUT_KINDS: dict[str, tuple[str, str]] = {
    "icp-definition": ("icp", "proposed"),
    "audience-persona": ("persona", "ready"),
}

#: The persona role vocabulary the card names for the model. Kept here, not in ``clue_core.enums``:
#: these are the strings the skills write into persona front matter, and nothing in O4 validates a
#: claim-side ``Persona`` against them.
_PERSONA_VOCABULARY = (
    "economic_buyer",
    "champion",
    "user",
    "technical_evaluator",
    "blocker",
)

_USER_MESSAGE = "Write the ICP documents, then one persona document per ICP, then finalize_turn."


async def _no_crash(
    point: str,
    *,
    execution_id: ExecutionId,
    node_key: str | None,
) -> None:
    del point, execution_id, node_key


def onboarding_project_id(*, workspace_id: str, brand_id: str) -> str:
    """The deterministic per-brand system project id this surface's turns belong to."""

    digest = uuid5(NAMESPACE_URL, f"onboarding-project:{workspace_id}:{brand_id}").hex[:24]
    return f"prj_onb_{digest}"


async def ensure_onboarding_project(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    brand_name: str,
) -> str:
    """Create (idempotently) the per-brand system project an onboarding turn is scoped to.

    ``agent_turn.project_id`` and ``execution.project_id`` are real foreign keys, so a governed
    turn always belongs to a project. Onboarding is not a marketing motion, so the row is born
    ``archived`` and carries no product: it is a scope anchor, never something a marketer opens.
    """

    project_id = onboarding_project_id(workspace_id=workspace_id, brand_id=brand_id)
    await conn.execute(
        text(
            "INSERT INTO project (project_id, workspace_id, brand_id, name, status) "
            "VALUES (:project_id, :workspace_id, :brand_id, :name, 'archived') "
            "ON CONFLICT (project_id) DO NOTHING"
        ),
        {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "name": f"Onboarding · {brand_name}",
        },
    )
    return project_id


@dataclass(frozen=True, slots=True)
class OnboardingSynthesisResult:
    """The step outcome the onboarding driver records — structurally O3's ``SynthesisOutcome``."""

    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal
    documents: tuple[UUID, ...]


class OnboardingSynthesisStepPinProvider(StepPinProvider):
    """Freeze the mutable skill catalog this surface's one spendable tool depends on.

    ``exa_search_evidence@1`` declares ``pin_requirements=("skill",)``: it may be spent only inside
    a slot that pinned the ``audience-persona`` skill telling the model what evidence is *for*.
    The recipe pins that skill statically for the gate; this provider re-observes it per dynamic
    child so the exact digest the child ran against is durable.
    """

    def __init__(self, *, compatibility: CompatibilityLoader) -> None:
        self._compatibility = compatibility

    async def _current(self, *, kind: str, key: str, ctx: ToolContext) -> PinRequest:
        observation = await self._compatibility.observe_current(
            kind=kind,
            key=key,
            context=CompatibilityContext(workspace_id=ctx.workspace_id),
        )
        if observation is None:
            raise ExecutionConflict(
                f"cannot pin missing onboarding-synthesis resource {kind}:{key}"
            )
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
        if step.tool_name != _EVIDENCE_TOOL_NAME or step.tool_version != _EVIDENCE_TOOL_VERSION:
            raise ExecutionConflict(
                "the onboarding-synthesis recipe admits only exa_search_evidence@1"
            )
        return (
            await self._current(kind="skill", key=_PERSONA_SKILL_KEY, ctx=ctx),
            *step.pin_requests,
        )


class _NoMemoryContext:
    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        del request
        return None


def onboarding_synthesis_context_policy() -> ContextAssemblyPolicy:
    """The opening-context budget for onboarding-synthesis@v1.

    L3 (project) is generous because the brand card, the budget envelope and the synthesis card
    all land there; L4 (memory) and L6 (conversation) are zero because this surface has neither.
    The brand's knowledge documents are **not** context candidates — they are workspace input
    files, materialized under ``inputs/`` and read with the framework's ``read_file``.
    """

    return ContextAssemblyPolicy(
        version="onboarding-synthesis-context-v1",
        token_counter_version="utf8-bytes-v1",
        budgets=tuple(
            LayerBudget(layer=layer, max_tokens=budget)
            for layer, budget in zip(
                tuple(ContextLayer),
                (24_000, 8_000, 64_000, 0, 8_000, 0, 12_000),
                strict=True,
            )
        ),
    )


def build_onboarding_synthesis_context(
    *,
    resolved_profile: ResolvedAgentProfile,
    artifacts: DurableAgentArtifactStore,
    cards: DbCompiledContextCardReader,
    conn_factory: ConnFactory = transaction,
) -> DeterministicAgentContextAssembler:
    """Build the L1-L7 assembler for one synthesis turn; no memory, no conversation history."""

    return build_agent_context_assembler(
        resolved_profile=resolved_profile,
        artifacts=artifacts,
        cards=cards,
        memory=_NoMemoryContext(),
        memory_recipe=EXECUTION_NAMESPACE_KEY,
        requested_memory_types=(),
        policy=onboarding_synthesis_context_policy(),
        conn_factory=conn_factory,
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


async def _current_input_documents(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
) -> tuple[dict[str, Any], ...]:
    """The brand's current servable knowledge documents — the max version of each path."""

    rows = (
        await conn.execute(
            text(
                "SELECT DISTINCT ON (path) path, kind, version, artifact_key, artifact_sha256 "
                "FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                "  AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "ORDER BY path, version DESC"
            ),
            {
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "statuses": list(_SERVABLE_STATUSES),
            },
        )
    ).mappings()
    return tuple(dict(row) for row in rows.all())


class OnboardingSynthesisLauncher:
    """Prepare every trusted input, then run one governed synthesis turn and register its output."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage: StorageBackend,
        components: AgentPlatformComponents,
        tools: ToolRegistry,
        tool_invoker: ToolInvoker,
        executor: RecipeExecutor,
        compatibility: CompatibilityLoader,
        plans: DbAgentPlanJournal,
        recipes: DbRecipeReader,
        starter: DbExecutionStarter,
        parameters: ExecutionParameterStore,
        materializer: AgentResourceMaterializer | None = None,
        checkpointer_factory: CheckpointerFactory = postgres_agent_checkpointer,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._components = components
        self._tools = tools
        self._tool_invoker = tool_invoker
        self._executor = executor
        self._compatibility = compatibility
        self._plans = plans
        self._recipes = recipes
        self._starter = starter
        self._parameters = parameters
        self._materializer = materializer or AgentResourceMaterializer()
        self._checkpointer_factory = checkpointer_factory
        self._conn_factory = conn_factory

    async def launch(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        run_id: UUID,
        step_id: UUID,
    ) -> OnboardingSynthesisResult:
        """Run the turn.

        The driver's failure law: every failure is a step outcome, never a raise.
        """

        try:
            return await self._launch(
                workspace_id=workspace_id,
                brand_id=brand_id,
                run_id=run_id,
                step_id=step_id,
            )
        except Exception as error:  # noqa: BLE001 -- a contained step outcome, never a raise
            log.exception(
                "onboarding_synthesis.contained_failure",
                run_id=str(run_id),
                step_id=str(step_id),
                workspace_id=workspace_id,
            )
            return OnboardingSynthesisResult(
                "failed",
                type(error).__name__,
                str(error)[:500],
                Decimal(0),
                (),
            )

    async def _launch(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        run_id: UUID,
        step_id: UUID,
    ) -> OnboardingSynthesisResult:
        # Resolved WITHOUT a surface, deliberately. A surface is a *narrowing*, and the registry
        # refuses one that withholds nothing ("it is not a restriction"). This role's whole
        # reviewed authority is already ``exa_search_evidence@1`` — the unit surface and the full
        # surface are the same set — so `ONBOARDING_SYNTHESIS_UNIT_SURFACE` names the place this
        # role runs (the recipe slot, which is the real second ceiling) rather than a tool ceiling
        # the profile does not need.
        resolved = self._components.profiles.resolve(AgentRole.ONBOARDING_SYNTHESIS)

        # 1. inputs -----------------------------------------------------------------------------
        async with self._conn_factory() as conn:
            brand = await get_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
            if brand is None:
                raise ValueError("the onboarding brand does not belong to this workspace")
            rows = await _current_input_documents(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
            )
            # The onboarding run is O3's row. This surface only *reads* it, and only for two
            # honest values: the domain the card names, and the run's own request time (so a
            # replayed launch stamps the same instant its first attempt did). A launch driven
            # before the row exists — the isolated turn-runner test — simply has neither.
            run_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT company_domain, requested_at FROM onboarding_run "
                            "WHERE run_id = :run_id"
                        ),
                        {"run_id": run_id},
                    )
                )
                .mappings()
                .first()
            )
            company_domain = None if run_row is None else run_row["company_domain"]
            requested_at = datetime.now(UTC) if run_row is None else run_row["requested_at"]
            if not {str(row["kind"]) for row in rows} >= _REQUIRED_INPUT_KINDS:
                log.warning(
                    "onboarding_synthesis.no_inputs",
                    run_id=str(run_id),
                    step_id=str(step_id),
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                )
                return OnboardingSynthesisResult("empty", None, "no inputs", Decimal(0), ())
            input_seeds: list[WorkspaceSeedFile] = []
            for row in rows:
                _, body = await read_verified_artifact(
                    conn,
                    self._storage,
                    storage_key=str(row["artifact_key"]),
                    workspace_id=workspace_id,
                )
                input_seeds.append(
                    WorkspaceSeedFile(
                        path=INPUT_PREFIX + str(row["path"]),
                        content=body,
                        sha256=str(row["artifact_sha256"]),
                        media_type="text/markdown",
                    )
                )
            # 2. the per-brand system project the turn and its execution belong to.
            project_id = await ensure_onboarding_project(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                brand_name=brand.name,
            )

        # 3. the durable C5 execution -----------------------------------------------------------
        execution_id = ExecutionId(operation_id_from_key(str(run_id), EXECUTION_NAMESPACE_KEY))
        revision = await self._recipes.get_by_identity(
            scope_type=RecipeScopeType.SYSTEM,
            workspace_id=None,
            recipe_key=_RECIPE_KEY,
            version=_RECIPE_VERSION,
        )
        if revision is None:
            raise RuntimeError("promoted onboarding-synthesis-unit@1 is not installed")
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
            project_id=project_id,
        )
        await self._drive_execution(execution_id)

        # 4. the isolated one-execution workspace ------------------------------------------------
        lease = self._components.workspaces.acquire(
            workspace_id=workspace_id,
            project_id=project_id,
            execution_id=execution_id,
            policy=resolved.profile.workspace,
        )

        # 5. the four trusted artifacts ----------------------------------------------------------
        card_ref = await self._artifact(
            workspace_id,
            SYNTHESIS_CARD_MEDIA_TYPE,
            {
                "schema_version": "1",
                "brand_id": brand_id,
                "company_domain": company_domain,
                "inputs": [
                    {
                        "path": str(row["path"]),
                        "kind": str(row["kind"]),
                        "version": int(row["version"]),
                    }
                    for row in rows
                ],
                "persona_vocabulary": list(_PERSONA_VOCABULARY),
            },
            project_id,
        )
        budget_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-budget-envelope+json",
            {"schema_version": "1", "limit_millicents": BUDGET_LIMIT_MILLICENTS},
            project_id,
        )
        manifest_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-resource-manifest+json",
            resolved.resource_manifest.model_dump(mode="json"),
            project_id,
        )
        user_message_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-turn-input+json",
            {
                "schema_version": "1",
                "objective": _USER_MESSAGE,
                "onboarding_run_id": str(run_id),
                "onboarding_step_id": str(step_id),
                "input_paths": [INPUT_PREFIX + str(row["path"]) for row in rows],
            },
            project_id,
        )

        # 6. the turn request --------------------------------------------------------------------
        turn_id = uuid5(TURN_NAMESPACE, f"{run_id}")
        request = AgentTurnRequest(
            turn_id=turn_id,
            thread_id=f"onboarding-synthesis-{run_id}",
            constitution=AgentConstitution(
                workspace_id=workspace_id,
                project_id=project_id,
                execution_id=execution_id,
                actor_id="system",
                role=AgentRole.ONBOARDING_SYNTHESIS,
                brand_id=brand_id,
                workspace_root_id=lease.identity.workspace_root_id,
                project_card_ref=card_ref,
                budget_envelope_ref=budget_ref,
                profile_ref=resolved.profile_ref,
                resource_manifest_ref=manifest_ref,
                resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
            ),
            user_message_artifact_ref=user_message_ref,
            requested_at=requested_at,
        )
        await self._components.turns.create(request=request, profile=resolved.profile)

        # 7. replay short-circuit ----------------------------------------------------------------
        outcome = await self._components.turns.load_committed_outcome(
            turn_id=turn_id,
            workspace_id=workspace_id,
        )
        if outcome is None:
            outcome = await self._run_turn(
                request=request,
                resolved=resolved,
                lease=lease,
                input_seeds=tuple(input_seeds),
            )

        # 8. close the durable recipe ------------------------------------------------------------
        await self._complete_recipe_if_needed(outcome)

        cost_usd = await self._cost_usd(execution_id=execution_id, workspace_id=workspace_id)
        if outcome.status is not AgentExecutionStatus.COMPLETED or outcome.finalization_ref is None:
            return OnboardingSynthesisResult(
                "failed",
                outcome.failure_code or "turn_not_completed",
                f"the synthesis turn ended {outcome.status.value}",
                cost_usd,
                (),
            )

        # 9. outputs -> documents ----------------------------------------------------------------
        documents = await self._register_documents(
            workspace_id=workspace_id,
            brand_id=brand_id,
            turn_id=turn_id,
            finalization_ref=outcome.finalization_ref,
        )
        if not documents:
            return OnboardingSynthesisResult(
                "empty",
                None,
                "the agent wrote no documents",
                cost_usd,
                (),
            )
        return OnboardingSynthesisResult("completed", None, None, cost_usd, documents)

    # --- the turn ------------------------------------------------------------------------------

    async def _run_turn(
        self,
        *,
        request: AgentTurnRequest,
        resolved: ResolvedAgentProfile,
        lease: AgentWorkspaceLease,
        input_seeds: tuple[WorkspaceSeedFile, ...],
    ) -> AgentTurnOutcome:
        contexts = build_onboarding_synthesis_context(
            resolved_profile=resolved,
            artifacts=self._components.artifacts,
            cards=DbCompiledContextCardReader(conn_factory=self._conn_factory),
            conn_factory=self._conn_factory,
        )
        context = await contexts.assemble(
            request=request,
            profile=resolved.profile,
            history=(),
        )
        context_seeds = tuple(
            WorkspaceSeedFile(
                path=item.path,
                content=item.data,
                sha256=item.sha256,
                media_type=item.media_type,
            )
            for item in context.materializations
        )
        seed_paths = {*(item.path for item in context_seeds), *(item.path for item in input_seeds)}
        if len(seed_paths) != len(context_seeds) + len(input_seeds):
            raise ValueError("a knowledge-document input collided with a canonical context path")
        seed_files = (*context_seeds, *input_seeds)
        if lease.resources_frozen:
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

        execution = C5AgentExecutionAdapter(
            turn_id=request.turn_id,
            constitution=request.constitution,
            resolved_profile=resolved,
            policy=AgentPlanPolicy.from_profile(
                resolved.profile,
                budget_limit_millicents=BUDGET_LIMIT_MILLICENTS,
                max_fanout=1,
                max_parallelism=1,
                max_rounds=resolved.profile.max_model_rounds,
            ),
            slot_key=_GATE_NODE_KEY,
            tools=self._tools,
            tool_invoker=self._tool_invoker,
            executor=self._executor,
            artifacts=self._components.artifacts,
            journal=self._plans,
            checkpointer_factory=self._checkpointer_factory,
            pin_provider=OnboardingSynthesisStepPinProvider(compatibility=self._compatibility),
            conn_factory=self._conn_factory,
        )
        execution.bind_finalization_authority(
            AgentFinalizationAuthority(
                lease=lease,
                artifacts=self._components.artifacts,
                turns=self._components.turns,
                crash_hook=_no_crash,
                conn_factory=self._conn_factory,
            )
        )
        governed_tools = GovernedAgentToolFactory(
            request=request,
            resolved_profile=resolved,
            registry=self._tools,
            execution=execution,
            lease=lease,
            artifacts=self._components.artifacts,
        ).build()
        return await DurableDeepAgentTurnRunner(
            runtime=DeepAgentTurnRuntime(
                models=self._components.models,
                execution=execution,
                max_runtime_s=resolved.profile.turn_timeout_s,
                max_rounds=resolved.profile.max_model_rounds,
            ),
            turns=self._components.turns,
            artifacts=self._components.artifacts,
        ).run(
            request=request,
            resolved_profile=resolved,
            context=context,
            lease=lease,
            tools=governed_tools,
        )

    # --- durable recipe ------------------------------------------------------------------------

    async def _complete_recipe_if_needed(self, outcome: AgentTurnOutcome) -> None:
        if outcome.status is not AgentExecutionStatus.COMPLETED:
            return
        try:
            await self._executor.decide_gate(
                execution_id=outcome.execution_id,
                node_key=_GATE_NODE_KEY,
                actor="agent",
                decision="complete",
            )
        except ExecutionConflict:
            # A replayed launch finds the gate already decided. The status assertion below is
            # still the real invariant, so swallowing the second decision hides nothing.
            log.info(
                "onboarding_synthesis.gate_already_decided",
                execution_id=str(outcome.execution_id),
            )
        status = await self._drive_execution(outcome.execution_id)
        if status is not ExecutionStatus.COMPLETED:
            raise RuntimeError("completed synthesis turn did not complete its durable C5 recipe")

    async def _drive_execution(self, execution_id: ExecutionId) -> ExecutionStatus:
        async with self._conn_factory() as conn:
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id=_PREPARER_WORKER_ID,
            )
        if lease is None:
            raise RuntimeError("onboarding-synthesis execution is owned by another live worker")
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

    # --- outputs -------------------------------------------------------------------------------

    async def _register_documents(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        turn_id: UUID,
        finalization_ref: ArtifactRef,
    ) -> tuple[UUID, ...]:
        """Turn each finalized output into a versioned ``brand_knowledge_document``.

        An output whose front matter is unreadable, whose ``kind`` is not one this surface may
        produce, or which carries no ``icp_key`` is skipped and logged. It is never a failure: the
        turn's other documents are real, and an unidentifiable file is honestly not a document.

        A re-synthesis at the same path is a new version that **names** the document it replaces
        (``supersedes_document_id``) and then retires it, so the chain is walkable in both
        directions rather than only inferrable from the version ordering.
        """

        envelope = AgentFinalizeEnvelope.model_validate_json(
            await self._components.artifacts.read(finalization_ref)
        )
        registered: list[UUID] = []
        for ref in envelope.output_refs:
            body = await self._components.artifacts.read(ref)
            try:
                front, _ = parse_front_matter(body.decode())
            except (UnicodeDecodeError, ValueError) as error:
                log.warning(
                    "onboarding_synthesis.unreadable_output",
                    turn_id=str(turn_id),
                    artifact_key=ref.artifact_key,
                    reason=str(error)[:200],
                )
                continue
            kind, icp_key = document_identity(front)
            naming = _OUTPUT_KINDS.get(kind)
            if naming is None or icp_key is None:
                log.warning(
                    "onboarding_synthesis.unidentifiable_output",
                    turn_id=str(turn_id),
                    artifact_key=ref.artifact_key,
                    kind=kind,
                    icp_key=icp_key,
                )
                continue
            prefix, status = naming
            path = f"audience/{prefix}-{icp_key}.md"
            document_id = uuid5(
                NAMESPACE_URL,
                f"onboarding-synthesis-doc:{turn_id}:{path}",
            )
            async with self._conn_factory() as conn:
                # One read answers both halves of the version chain: the next version number (over
                # every row at this path, whatever its status) and the document this one replaces
                # — the highest-version *servable* row, which the UPDATE below then supersedes.
                # They must agree, or a reader following ``supersedes_document_id`` backwards
                # would walk off a row that was never actually retired.
                lineage = (
                    (
                        await conn.execute(
                            text(
                                "SELECT"
                                "  (SELECT COALESCE(MAX(version), 0) + 1"
                                "     FROM brand_knowledge_document"
                                "    WHERE workspace_id = :workspace_id"
                                "      AND brand_id = :brand_id AND path = :path"
                                "  ) AS next_version,"
                                "  (SELECT document_id"
                                "     FROM brand_knowledge_document"
                                "    WHERE workspace_id = :workspace_id"
                                "      AND brand_id = :brand_id AND path = :path"
                                "      AND status = ANY(:statuses)"
                                "    ORDER BY version DESC LIMIT 1"
                                "  ) AS supersedes_document_id"
                            ),
                            {
                                "workspace_id": workspace_id,
                                "brand_id": brand_id,
                                "path": path,
                                "statuses": list(_SERVABLE_STATUSES),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                version = int(lineage["next_version"])
                supersedes = lineage["supersedes_document_id"]
                await conn.execute(
                    text(
                        "INSERT INTO brand_knowledge_document ("
                        "  document_id, workspace_id, brand_id, folder, path, kind, version, "
                        "  status, artifact_key, artifact_sha256, produced_by_turn_id, "
                        "  supersedes_document_id"
                        ") VALUES ("
                        "  :document_id, :workspace_id, :brand_id, 'audience', :path, :kind, "
                        "  :version, :status, :artifact_key, :artifact_sha256, :turn_id, "
                        "  :supersedes"
                        ") ON CONFLICT (document_id) DO NOTHING"
                    ),
                    {
                        "document_id": document_id,
                        "workspace_id": workspace_id,
                        "brand_id": brand_id,
                        "path": path,
                        "kind": kind,
                        "version": version,
                        "status": status,
                        "artifact_key": ref.artifact_key,
                        "artifact_sha256": ref.sha256,
                        "turn_id": turn_id,
                        # A replayed launch re-reads a chain it already wrote, so the row it would
                        # name is its own; the ON CONFLICT above makes that a no-op either way.
                        "supersedes": None if supersedes == document_id else supersedes,
                    },
                )
                await conn.execute(
                    text(
                        "UPDATE brand_knowledge_document SET status = 'superseded', "
                        "  updated_at = now() "
                        "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                        "  AND path = :path AND document_id <> :document_id "
                        "  AND status = ANY(:statuses)"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "brand_id": brand_id,
                        "path": path,
                        "document_id": document_id,
                        "statuses": list(_SERVABLE_STATUSES),
                    },
                )
            registered.append(document_id)
        return tuple(registered)

    # --- cost ----------------------------------------------------------------------------------

    async def _cost_usd(self, *, execution_id: ExecutionId, workspace_id: str) -> Decimal:
        """Sum the evidence tool's own reported spend across this execution's durable receipts."""

        total = Decimal(0)
        receipts = await self._plans.load_receipts(
            execution_id=execution_id,
            workspace_id=workspace_id,
        )
        for receipt in receipts:
            if receipt.kind != "tool" or not receipt.address.startswith(f"{_EVIDENCE_TOOL_NAME}@"):
                continue
            for ref in receipt.artifact_refs:
                try:
                    payload = json.loads(await self._components.artifacts.read(ref))
                    references = payload.get("references") or {}
                    total += Decimal(str(references.get("cost_usd", "0")))
                except (InvalidOperation, ValueError, AttributeError, TypeError):
                    log.warning(
                        "onboarding_synthesis.unreadable_tool_cost",
                        execution_id=str(execution_id),
                        artifact_key=ref.artifact_key,
                    )
        return total

    # --- helpers -------------------------------------------------------------------------------

    async def _artifact(
        self,
        workspace_id: str,
        media_type: str,
        payload: object,
        project_id: str,
    ) -> ArtifactRef:
        return await self._components.artifacts.persist_body(
            workspace_id=workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            project_bindings=((project_id, "onboarding_synthesis_context"),),
        )

    @classmethod
    async def for_tests(
        cls,
        *,
        conn: AsyncConnection,
        storage: StorageBackend,
        models: Any,
        workspace_root: Path,
    ) -> OnboardingSynthesisLauncher:
        """Compose the real launcher over one test connection, with a scripted model provider.

        Everything here is production wiring: the real toolbelt, profile registry, recipe seeder
        and lifecycle, execution starter, recipe executor, tool invoker, artifact store and
        workspace factory. Exactly three things are substituted, and each for a stated reason —
        the model provider (scripted, so no turn spends real money), the checkpointer (in-memory,
        because the test's rolled-back connection cannot host LangGraph's own tables), and the
        workspace root (a temporary directory rather than ``CLUE_AGENT_WORKSPACE_ROOT``).

        ``build_toolbelt`` is called **without** ``secrets``, so ``exa_search_evidence@1`` is
        composed fail-closed and refuses ``exa_not_configured`` if anything ever calls it.
        """

        from clue_agents import AgentWorkspaceFactory, WorkspaceRootPolicy
        from clue_api.agent_platform_wiring import DbAgentOwnershipRouter
        from clue_api.agent_registry_wiring import build_agent_profile_registry
        from clue_api.agent_turn_wiring import (
            AgentPrivacyService,
            DbAgentHistoryStore,
            DbAgentReplayReader,
            DbAgentTurnJournal,
        )
        from clue_api.execution_wiring import (
            ExecutionRunEventWriter,
            StorageExecutionParameterStore,
            StorageParameterArtifactStore,
            build_tool_invoker,
        )
        from clue_api.recipe_wiring import (
            build_recipe_lifecycle,
            build_recipe_pin_registry,
            load_system_recipe_definitions,
            seed_system_recipes,
        )
        from clue_api.toolbelt_wiring import build_toolbelt
        from clue_config import load_settings
        from clue_execution import DbExecutionJournal, DbRecipeRepository
        from clue_toolbelt import DbIdempotencyStore

        @asynccontextmanager
        async def conn_factory() -> AsyncIterator[AsyncConnection]:
            yield conn

        def checkpointer_factory(
            execution_id: ExecutionId,
        ) -> Any:
            del execution_id

            @asynccontextmanager
            async def opened() -> AsyncIterator[BaseCheckpointSaver[str]]:
                yield InMemorySaver()

            return opened()

        settings = load_settings(_env_file=None)
        tools = build_toolbelt(storage=None, gateway=None)
        artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)

        root = Path(workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        source_root = root / "source"
        home_root = root / "home"
        source_root.mkdir(mode=0o700, exist_ok=True)
        home_root.mkdir(mode=0o700, exist_ok=True)
        workspaces = AgentWorkspaceFactory(
            prepared_root=WorkspaceRootPolicy(
                configured_root=root / "runtime",
                source_root=source_root,
                home_root=home_root,
            ).prepare(),
            artifact_sink=artifacts,
        )

        pin_registry = build_recipe_pin_registry(tool_registry=tools, conn_factory=conn_factory)
        compatibility = CompatibilityLoader(pin_registry)
        await seed_system_recipes(
            repository=DbRecipeRepository(conn_factory=conn_factory),
            lifecycle=build_recipe_lifecycle(
                tool_registry=tools,
                conn_factory=conn_factory,
                pin_registry=pin_registry,
            ),
            definitions=[
                definition
                for definition in load_system_recipe_definitions()
                if definition.recipe_key == _RECIPE_KEY
            ],
        )
        journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
        parameters = StorageExecutionParameterStore(
            StorageParameterArtifactStore(storage=storage, conn_factory=conn_factory)
        )
        tool_invoker = build_tool_invoker(
            registry=tools,
            idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
            storage=storage,
            settings=settings,
            conn_factory=conn_factory,
        )
        recipes = DbRecipeReader(conn_factory=conn_factory)
        components = AgentPlatformComponents(
            profiles=build_agent_profile_registry(tools),
            models=models,
            workspaces=workspaces,
            artifacts=artifacts,
            turns=DbAgentTurnJournal(conn_factory=conn_factory),
            history=DbAgentHistoryStore(conn_factory=conn_factory),
            replay=DbAgentReplayReader(storage=storage, conn_factory=conn_factory),
            privacy=AgentPrivacyService(
                storage=storage,
                workspaces=workspaces,
                conn_factory=conn_factory,
            ),
            ownership=DbAgentOwnershipRouter(settings=settings, conn_factory=conn_factory),
        )
        return cls(
            settings=settings,
            storage=storage,
            components=components,
            tools=tools,
            tool_invoker=tool_invoker,
            executor=RecipeExecutor(
                conn_factory=conn_factory,
                recipes=recipes,
                compatibility=compatibility,
                journal=journal,
                parameters=parameters,
                tool_invoker=tool_invoker,
                max_concurrency=1,
            ),
            compatibility=compatibility,
            plans=DbAgentPlanJournal(conn_factory=conn_factory),
            recipes=recipes,
            starter=DbExecutionStarter(
                conn_factory=conn_factory,
                recipes=recipes,
                compatibility=compatibility,
                journal=journal,
            ),
            parameters=parameters,
            checkpointer_factory=checkpointer_factory,
            conn_factory=conn_factory,
        )


def build_onboarding_synthesis_launcher(
    *,
    settings: Settings,
    secrets: Secrets,
    storage: StorageBackend,
    components: AgentPlatformComponents,
    tools: ToolRegistry,
    tool_invoker: ToolInvoker,
    executor: RecipeExecutor,
    compatibility: CompatibilityLoader,
    plans: DbAgentPlanJournal,
    recipes: DbRecipeReader,
    starter: DbExecutionStarter,
    parameters: ExecutionParameterStore,
    conn_factory: ConnFactory = transaction,
) -> OnboardingSynthesisLauncher:
    """The production seam the onboarding driver (O3) composes at the API/fleet root."""

    del secrets  # the turn spends only through governed tools, which own their own credentials
    return OnboardingSynthesisLauncher(
        settings=settings,
        storage=storage,
        components=components,
        tools=tools,
        tool_invoker=tool_invoker,
        executor=executor,
        compatibility=compatibility,
        plans=plans,
        recipes=recipes,
        starter=starter,
        parameters=parameters,
        conn_factory=conn_factory,
    )
