"""Local, inspectable Stage-0 conversation harness over the production deepagent runtime.

This module is deliberately a composition root, not a second Stage-0 implementation. It joins the
existing C4 tools, C5 Recipe 0 executor, C6 Head-of-ABM runtime, scoped-memory seams, object spine,
claim store, and durable artifacts into the smallest useful no-frontend trial surface.

The harness is conversation-only by design: official-site scraping and research providers are not
bound. A trial therefore starts exclusively from the identity seed supplied by the user and from
what the user says in the conversation. Exa and website acquisition are separate later tests.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    ArtifactRef,
    ContextAssemblyPolicy,
    ContextLayer,
    DelegationRequest,
    DelegationResult,
    DomainObjectRef,
    LayerBudget,
)
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_execution_wiring import (
    DbAgentPlanJournal,
    postgres_agent_checkpointer,
)
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    build_agent_context_assembler,
    build_agent_platform_components,
)
from clue_api.composition import load_research_packs
from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_api.head_of_abm_wiring import (
    HeadOfAbmStage0Runtime,
    build_head_of_abm_stage0_execution,
)
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    load_system_recipe_definitions,
    seed_system_recipes,
)
from clue_api.run_composition import build_platform_gateway
from clue_api.storage_wiring import build_storage_backend
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Secrets, Settings, default_gateway_config, load_settings
from clue_core import (
    ContextAssembly,
    EntityId,
    ExecutionId,
    LLMGateway,
    MemoryType,
    MemoryWriteSeam,
    OnboardingInputId,
    OnboardingInputKind,
    operation_id_from_key,
)
from clue_db import ConnFactory, transaction
from clue_execution import (
    CompatibilityLoader,
    DbExecutionJournal,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    ExecutionParameterStore,
    ExecutionStatus,
    RecipeDefinition,
    RecipeExecutor,
    RecipeScopeType,
)
from clue_fleet import LeaseGeneration, WorkId, acquire_work_lease, release_work_lease
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    ClientInput,
    ClientKnowledgeBaseRef,
    ICPConfirmation,
    ICPProposal,
    VolunteeredMaterial,
    confirm_icp,
    read_client_kb_claims,
    reverse_profile,
    submit_onboarding_input,
    synthesize_icps,
)
from clue_spine import (
    confirm_project_product,
    create_brand,
    create_product,
    create_project,
    create_workspace,
    get_project,
    get_workspace,
)
from clue_storage import StorageBackend
from clue_toolbelt import DbIdempotencyStore, ToolInvoker, ToolRegistry

_SESSION_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_TURN_NAMESPACE_LABEL = "stage0-trial-turn@1"
_EXECUTION_NAMESPACE_LABEL = "stage0-trial-execution@1"
_WORKER_ID = "stage0-trial-cli"
STAGE0_USER_MESSAGE_BINDING_KIND = "conversation"
STAGE0_CONTEXT_BINDING_KIND = "context"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode()


def _pretty_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def _safe_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    normalized = normalized[:63].rstrip("-")
    if not normalized or _SESSION_SLUG.fullmatch(normalized) is None:
        raise ValueError("session name must contain letters or numbers")
    return normalized


class Stage0TrialState(BaseModel):
    """Small local handle to durable database/artifact identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1"
    session_id: UUID
    session_slug: str
    workspace_id: str
    brand_id: str
    product_id: str
    project_id: str
    client_entity_id: UUID
    client_kb_version: int = Field(ge=1)
    company_name: str
    website: str
    product_name: str
    project_name: str
    thread_id: str
    next_turn: int = Field(default=1, ge=1)
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Stage0TrialPaths:
    """User-visible local report paths. Domain truth remains in Postgres/artifact storage."""

    root: Path

    @classmethod
    def for_session(cls, root: Path, slug: str) -> Stage0TrialPaths:
        if _SESSION_SLUG.fullmatch(slug) is None:
            raise ValueError("invalid Stage-0 trial session slug")
        return cls(root=root / slug)

    @property
    def state(self) -> Path:
        return self.root / "session.json"

    @property
    def report_json(self) -> Path:
        return self.root / "report.json"

    @property
    def report_markdown(self) -> Path:
        return self.root / "report.md"

    @property
    def transcript(self) -> Path:
        return self.root / "transcript.md"

    @property
    def icp_proposals(self) -> Path:
        return self.root / "icp-proposals.json"

    def save_state(self, state: Stage0TrialState) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ".session.json.tmp"
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.state)

    def load_state(self) -> Stage0TrialState:
        return Stage0TrialState.model_validate_json(self.state.read_text(encoding="utf-8"))


MemoryAssemblyFactory = Callable[[Settings, ConnFactory], ContextAssembly]
MemoryWriteFactoryBuilder = Callable[
    [Settings, LLMGateway],
    Callable[[AsyncConnection], MemoryWriteSeam],
]


class _DelegationDisabled:
    """Fail honestly if the conversational pilot tries to leave its declared scope."""

    async def run(
        self,
        *,
        request: DelegationRequest,
        child_execution_id: ExecutionId,
        resolved_profile: Any,
    ) -> DelegationResult:
        del request, child_execution_id, resolved_profile
        raise RuntimeError("specialist_delegation_disabled_for_stage0_conversation_trial")


def stage0_trial_context_policy() -> ContextAssemblyPolicy:
    """Conservative seven-layer budget with room for a long kickoff interview."""

    return ContextAssemblyPolicy(
        version="stage0-trial-context-v1",
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


def stage0_trial_settings(settings: Settings) -> Settings:
    """Supply the CLI-only isolated workspace root when its optional setting is blank."""

    if (settings.agent_workspace_root or "").strip():
        return settings
    uid = os.getuid() if hasattr(os, "getuid") else 0
    dedicated_root = Path(tempfile.gettempdir()).resolve() / f"clue-stage0-agent-{uid}"
    return settings.model_copy(update={"agent_workspace_root": str(dedicated_root)})


def stage0_trial_recipe_definitions() -> tuple[RecipeDefinition, ...]:
    """Return only the recipe family executable by the Stage-0-only toolbelt."""

    definitions = tuple(
        definition
        for definition in load_system_recipe_definitions()
        if definition.recipe_key == "recipe0-stage0"
    )
    if not any(definition.version == 3 for definition in definitions):
        raise RuntimeError("recipe0-stage0@3 definition is not installed")
    return definitions


async def create_stage0_trial_session(
    *,
    paths_root: Path,
    session_name: str,
    company_name: str,
    website: str,
    product_name: str,
    project_name: str,
    conn_factory: ConnFactory = transaction,
) -> tuple[Stage0TrialPaths, Stage0TrialState]:
    """Create an isolated identity shell and zero-spend Client-KB marker.

    The name/website are identity seeds only. ``max_source_tier=0`` and a zero budget prove this
    setup cannot acquire website or provider context.
    """

    slug = _safe_slug(session_name)
    paths = Stage0TrialPaths.for_session(paths_root, slug)
    if paths.state.exists():
        raise FileExistsError(f"Stage-0 trial session {slug!r} already exists")
    session_id = uuid4()
    workspace_id = f"s0-{slug}-{session_id.hex[:8]}"
    async with conn_factory() as conn:
        if await get_workspace(conn, workspace_id) is not None:
            raise ValueError("generated Stage-0 trial workspace already exists")
        workspace = await create_workspace(
            conn,
            workspace_id=workspace_id,
            name=f"Stage 0 trial: {company_name}",
        )
        brand = await create_brand(
            conn,
            workspace_id=workspace.workspace_id,
            name=company_name,
        )
        product = await create_product(
            conn,
            workspace_id=workspace.workspace_id,
            brand_id=brand.brand_id,
            name=product_name,
        )
        project = await create_project(
            conn,
            workspace_id=workspace.workspace_id,
            brand_id=brand.brand_id,
            product_id=None,
            name=project_name,
        )
        await load_research_packs(conn)
        client_kb = await reverse_profile(
            conn,
            ClientInput(name=company_name, website=website),
            workspace_id=workspace.workspace_id,
            budget_cap_cents=Decimal(0),
            product_id=product.product_id,
            max_source_tier=0,
        )
    state = Stage0TrialState(
        session_id=session_id,
        session_slug=slug,
        workspace_id=workspace.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client_entity_id=UUID(str(client_kb.ref.client_entity_id)),
        client_kb_version=client_kb.ref.client_kb_version,
        company_name=company_name,
        website=website,
        product_name=product_name,
        project_name=project_name,
        thread_id=f"stage0-trial-{session_id.hex}",
        created_at=datetime.now(UTC),
    )
    paths.save_state(state)
    return paths, state


class Stage0Trial:
    """One resumable conversation session over the real Stage-0 agent stack."""

    def __init__(
        self,
        *,
        state: Stage0TrialState,
        paths: Stage0TrialPaths,
        settings: Settings,
        storage: StorageBackend,
        gateway: LLMGateway,
        tools: ToolRegistry,
        tool_invoker: ToolInvoker,
        components: AgentPlatformComponents,
        compatibility: CompatibilityLoader,
        executor: RecipeExecutor,
        recipes: DbRecipeReader,
        starter: DbExecutionStarter,
        parameters: ExecutionParameterStore,
        contexts: Any,
        runtime: HeadOfAbmStage0Runtime,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self.state = state
        self.paths = paths
        self._settings = settings
        self._storage = storage
        self._gateway = gateway
        self._tools = tools
        self._tool_invoker = tool_invoker
        self._components = components
        self._compatibility = compatibility
        self._executor = executor
        self._recipes = recipes
        self._starter = starter
        self._parameters = parameters
        self._contexts = contexts
        self._runtime = runtime
        self._plans = DbAgentPlanJournal(conn_factory=conn_factory)
        self._conn_factory = conn_factory

    @classmethod
    async def build(
        cls,
        *,
        state: Stage0TrialState,
        paths: Stage0TrialPaths,
        memory_assembly_factory: MemoryAssemblyFactory,
        memory_write_factory_builder: MemoryWriteFactoryBuilder,
        settings: Settings | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> Stage0Trial:
        resolved_settings = stage0_trial_settings(settings or load_settings())
        secrets = Secrets()
        if secrets.openrouter_api_key is None:
            raise RuntimeError(
                "CLUE_OPENROUTER_API_KEY is required for a real Stage-0 deepagent trial"
            )
        storage = build_storage_backend(resolved_settings)
        gateway = build_platform_gateway(resolved_settings)
        tools = build_toolbelt(
            storage=storage,
            settings=resolved_settings,
            gateway=gateway,
            conn_factory=conn_factory,
            stage0_memory_write_factory=memory_write_factory_builder(
                resolved_settings,
                gateway,
            ),
            # Deliberate trial boundary: no official-site scrape and no research-provider context.
            stage0_scrape_binder=None,
        )
        pin_registry = build_recipe_pin_registry(
            tool_registry=tools,
            conn_factory=conn_factory,
        )
        compatibility = CompatibilityLoader(pin_registry)
        repository = DbRecipeRepository(conn_factory=conn_factory)
        lifecycle = build_recipe_lifecycle(
            tool_registry=tools,
            conn_factory=conn_factory,
            pin_registry=pin_registry,
        )
        await seed_system_recipes(
            repository=repository,
            lifecycle=lifecycle,
            definitions=stage0_trial_recipe_definitions(),
        )
        execution_journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
        parameter_artifacts = StorageParameterArtifactStore(
            storage=storage,
            conn_factory=conn_factory,
        )
        parameters = StorageExecutionParameterStore(parameter_artifacts)
        tool_invoker = build_tool_invoker(
            registry=tools,
            idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
            storage=storage,
            settings=resolved_settings,
            conn_factory=conn_factory,
        )
        recipes = DbRecipeReader(conn_factory=conn_factory)
        starter = DbExecutionStarter(
            conn_factory=conn_factory,
            recipes=recipes,
            compatibility=compatibility,
            journal=execution_journal,
        )
        executor = RecipeExecutor(
            conn_factory=conn_factory,
            recipes=recipes,
            compatibility=compatibility,
            journal=execution_journal,
            parameters=parameters,
            tool_invoker=tool_invoker,
            max_concurrency=resolved_settings.recipe_executor_max_concurrency,
        )
        components = build_agent_platform_components(
            settings=resolved_settings,
            secrets=secrets,
            gateway_config=default_gateway_config(),
            storage=storage,
            tools=tools,
            conn_factory=conn_factory,
        )
        resolved_profile = components.profiles.resolve(AgentRole.HEAD_OF_ABM)
        contexts = build_agent_context_assembler(
            resolved_profile=resolved_profile,
            artifacts=components.artifacts,
            cards=DbCompiledContextCardReader(conn_factory=conn_factory),
            memory=memory_assembly_factory(resolved_settings, conn_factory),
            memory_recipe="recipe0-stage0@3",
            requested_memory_types=(
                MemoryType.PREFERENCE,
                MemoryType.BEHAVIORAL_LEARNING,
            ),
            policy=stage0_trial_context_policy(),
            conn_factory=conn_factory,
        )
        runtime = HeadOfAbmStage0Runtime(
            profiles=components.profiles,
            models=components.models,
            turns=components.turns,
            artifacts=components.artifacts,
            tools=tools,
            child_runner=_DelegationDisabled(),
            max_runtime_s=resolved_profile.profile.turn_timeout_s,
            max_rounds=resolved_profile.profile.max_model_rounds,
            conn_factory=conn_factory,
        )
        return cls(
            state=state,
            paths=paths,
            settings=resolved_settings,
            storage=storage,
            gateway=gateway,
            tools=tools,
            tool_invoker=tool_invoker,
            components=components,
            compatibility=compatibility,
            executor=executor,
            recipes=recipes,
            starter=starter,
            parameters=parameters,
            contexts=contexts,
            runtime=runtime,
            conn_factory=conn_factory,
        )

    async def run_turn(self, message: str) -> tuple[AgentTurnOutcome, str | None]:
        """Run one user turn, persist both sides to thread history, and refresh reports."""

        if not message.strip():
            raise ValueError("Stage-0 trial message cannot be empty")
        sequence = self.state.next_turn
        turn_id = uuid5(self.state.session_id, f"{_TURN_NAMESPACE_LABEL}:{sequence}")
        execution_id = ExecutionId(
            operation_id_from_key(
                str(self.state.session_id),
                f"{_EXECUTION_NAMESPACE_LABEL}:{sequence}",
            )
        )
        user_ref = await self._components.artifacts.persist_body(
            workspace_id=self.state.workspace_id,
            data=message.encode(),
            media_type="text/plain",
            subject_bindings=(
                (self.state.client_entity_id, STAGE0_USER_MESSAGE_BINDING_KIND),
            ),
        )
        async with self._conn_factory() as conn:
            onboarding = await submit_onboarding_input(
                conn,
                workspace_id=self.state.workspace_id,
                brand_id=self.state.brand_id,
                product_id=self.state.product_id,
                project_id=self.state.project_id,
                client_entity_id=EntityId(self.state.client_entity_id),
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=user_ref.artifact_key,
                content_sha256=user_ref.sha256,
                actor="human",
                onboarding_input_id=OnboardingInputId(uuid5(turn_id, "onboarding-input")),
            )
        current = await self.snapshot(
            current_turn={
                "onboarding_input_id": str(onboarding.onboarding_input_id),
                "artifact_key": user_ref.artifact_key,
                "sha256": user_ref.sha256,
                "media_type": user_ref.media_type,
                "byte_count": user_ref.byte_count,
                "answer_is_exact_artifact_body": True,
            }
        )
        requested_at = datetime.now(UTC)
        resolved = self._components.profiles.resolve(AgentRole.HEAD_OF_ABM)
        stage_ref = await self._artifact(
            "application/vnd.clue.agent-stage-snapshot+json",
            {
                "schema_version": "1",
                "surface": "stage0_conversation_trial",
                "acquisition_mode": "manual_conversation_only",
                "external_research_enabled": False,
                "specialist_delegation_enabled": False,
                "instruction": (
                    "Use only supplied durable truth and the current user message. Do not call "
                    "start_recon or imply that website, Exa, scraping, or campaign files were "
                    "read. The current user turn is already a captured onboarding input; use its "
                    "provided onboarding_input_id and do not call submit_onboarding_input again. "
                    "Treat the user's target-ICP and campaign-strategy choices as project_state, "
                    "not as an invented claim field. Claims about the client may use only the "
                    "registered_client_claim_fields below and must include the supplied client "
                    "entity id with entity_type=account. The human triggers inspectable ICP "
                    "synthesis with /synthesize-icp; do not call synthesize_icps in this trial "
                    "because its v1 tool result exposes only a count."
                ),
                "registered_client_claim_fields": list(CLIENT_KNOWLEDGE_FIELDS),
                "current_truth": current,
            },
        )
        project = current["project"]
        if not isinstance(project, dict):
            raise RuntimeError("Stage-0 project snapshot is malformed")
        readiness_ref = await self._artifact(
            "application/vnd.clue.agent-readiness-snapshot+json",
            {
                "schema_version": "1",
                "readiness_decisions": current["readiness_decisions"],
                "confirmed_icps": current["icps"],
                "product_confirmed": project.get("product_id") == self.state.product_id,
            },
        )
        budget_limit = 1_000_000
        budget_ref = await self._artifact(
            "application/vnd.clue.agent-budget-envelope+json",
            {
                "schema_version": "1",
                "limit_millicents": budget_limit,
                "external_research_budget_cents": "0",
                "scope": "conversation and Stage-0 domain writes only",
            },
        )
        manifest_ref = await self._artifact(
            "application/vnd.clue.agent-resource-manifest+json",
            resolved.resource_manifest.model_dump(mode="json"),
        )
        revision = await self._recipes.get_by_identity(
            scope_type=RecipeScopeType.SYSTEM,
            workspace_id=None,
            recipe_key="recipe0-stage0",
            version=3,
        )
        if revision is None:
            raise RuntimeError("promoted recipe0-stage0@3 is not installed")
        parameter_key, parameter_sha = await self._parameters.snapshot(
            workspace_id=self.state.workspace_id,
            parameters={},
        )
        await self._starter.start(
            workspace_id=self.state.workspace_id,
            recipe_revision_id=revision.recipe_revision_id,
            parameters={},
            parameter_artifact_key=parameter_key,
            parameter_manifest_hash=parameter_sha,
            actor="human",
            execution_id=execution_id,
            project_id=self.state.project_id,
        )
        recipe_status = await self._drive(execution_id)
        if recipe_status is not ExecutionStatus.AWAITING_INPUT:
            raise RuntimeError(
                f"Recipe 0 did not reach its interaction gate (status={recipe_status.value})"
            )
        lease = self._components.workspaces.acquire(
            workspace_id=self.state.workspace_id,
            project_id=self.state.project_id,
            execution_id=execution_id,
            policy=resolved.profile.workspace,
        )
        focus_ref = DomainObjectRef(
            workspace_id=self.state.workspace_id,
            object_type="client_account",
            object_id=str(self.state.client_entity_id),
            version=self.state.client_kb_version,
        )
        request = AgentTurnRequest(
            turn_id=turn_id,
            thread_id=self.state.thread_id,
            constitution=AgentConstitution(
                workspace_id=self.state.workspace_id,
                project_id=self.state.project_id,
                execution_id=execution_id,
                actor_id="stage0-trial-user",
                role=AgentRole.HEAD_OF_ABM,
                brand_id=self.state.brand_id,
                product_id=self.state.product_id,
                workspace_root_id=lease.identity.workspace_root_id,
                stage_snapshot_ref=stage_ref,
                readiness_snapshot_ref=readiness_ref,
                budget_envelope_ref=budget_ref,
                profile_ref=resolved.profile_ref,
                resource_manifest_ref=manifest_ref,
                resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                focus_refs=(focus_ref,),
            ),
            user_message_artifact_ref=user_ref,
            focus_refs=(focus_ref,),
            requested_at=requested_at,
        )
        prior_history = await self._components.history.load(
            workspace_id=self.state.workspace_id,
            thread_id=self.state.thread_id,
        )
        await self._components.turns.create(request=request, profile=resolved.profile)
        await self._components.history.append(
            message_id=uuid5(turn_id, "user"),
            turn_id=turn_id,
            workspace_id=self.state.workspace_id,
            thread_id=self.state.thread_id,
            role="user",
            body_ref=user_ref,
        )
        # Reserve the sequence before model spend. A crash leaves an explicit unfinalized turn and
        # cannot let a later, different message reuse its immutable turn/execution identity.
        self.state = self.state.model_copy(update={"next_turn": sequence + 1})
        self.paths.save_state(self.state)
        committed = await self._components.turns.load_committed_outcome(
            turn_id=turn_id,
            workspace_id=self.state.workspace_id,
        )
        if committed is None:
            context = await self._contexts.assemble(
                request=request,
                profile=resolved.profile,
                history=prior_history,
            )
            execution = build_head_of_abm_stage0_execution(
                request=request,
                profiles=self._components.profiles,
                tools=self._tools,
                tool_invoker=self._tool_invoker,
                executor=self._executor,
                compatibility=self._compatibility,
                artifacts=self._components.artifacts,
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
            )
        else:
            outcome = committed
        assistant_message: str | None = None
        if outcome.finalization_ref is not None:
            envelope = AgentFinalizeEnvelope.model_validate_json(
                await self._components.artifacts.read(outcome.finalization_ref)
            )
            if envelope.user_message_artifact_ref is not None:
                assistant_message = (
                    await self._components.artifacts.read(envelope.user_message_artifact_ref)
                ).decode()
                await self._components.history.append(
                    message_id=uuid5(turn_id, "assistant"),
                    turn_id=turn_id,
                    workspace_id=self.state.workspace_id,
                    thread_id=self.state.thread_id,
                    role="assistant",
                    body_ref=envelope.user_message_artifact_ref,
                )
            if outcome.status is AgentExecutionStatus.COMPLETED:
                await self._executor.decide_gate(
                    execution_id=execution_id,
                    node_key="stage0_interactions",
                    actor="agent",
                    decision="complete",
                )
                completed = await self._drive(execution_id)
                if completed is not ExecutionStatus.COMPLETED:
                    raise RuntimeError("completed Stage-0 turn did not complete Recipe 0")
        await self._refresh_client_kb_from_conversation()
        self.paths.save_state(self.state)
        await self.export_report()
        return outcome, assistant_message

    async def _refresh_client_kb_from_conversation(self) -> None:
        """Publish new interview truth as the next immutable Client-KB version.

        Interview claims are correctly claim-native but are written under the turn operation id,
        while a Client-KB version intentionally reads only the run pinned by its marker. Re-publish
        the current live client fields as volunteered, provenance-bearing materials under one new
        zero-acquisition reverse-profile run. The original interview claims and statement lineage
        remain intact; the new KB version is the version-pinned snapshot downstream ICP synthesis
        consumes.
        """

        async with self._conn_factory() as conn:
            pinned = await read_client_kb_claims(
                conn,
                EntityId(self.state.client_entity_id),
                workspace_id=self.state.workspace_id,
                version=self.state.client_kb_version,
                product_id=self.state.product_id,
            )
            raw = await claims_for(
                conn,
                EntityId(self.state.client_entity_id),
                scope=WorkspaceScope.for_workspace(self.state.workspace_id),
            )
            live: dict[str, Any] = {}
            for claim in raw:
                if (
                    claim.field_key in CLIENT_KNOWLEDGE_FIELDS
                    and claim.product_id == self.state.product_id
                    and claim.field_key not in live
                ):
                    live[claim.field_key] = claim
            if {field_key: claim.value_json for field_key, claim in sorted(live.items())} == {
                field_key: claim.value_json for field_key, claim in sorted(pinned.items())
            }:
                return
            materials = tuple(
                VolunteeredMaterial(
                    kind="stage0_interview_claim",
                    label=f"carried from governed claim {claim.id}",
                    content=claim.evidence_span,
                    asserted_fields={field_key: claim.value_json},
                )
                for field_key, claim in sorted(live.items())
            )
            refreshed = await reverse_profile(
                conn,
                ClientInput(
                    name=self.state.company_name,
                    website=self.state.website,
                    materials=materials,
                ),
                workspace_id=self.state.workspace_id,
                budget_cap_cents=Decimal(0),
                product_id=self.state.product_id,
                max_source_tier=0,
            )
        if UUID(str(refreshed.ref.client_entity_id)) != self.state.client_entity_id:
            raise RuntimeError("Stage-0 Client-KB refresh changed the resolved client identity")
        self.state = self.state.model_copy(
            update={"client_kb_version": refreshed.ref.client_kb_version}
        )

    async def confirm_product(self) -> None:
        """Apply the human-only project/product confirmation."""

        async with self._conn_factory() as conn:
            confirmed = await confirm_project_product(
                conn,
                workspace_id=self.state.workspace_id,
                project_id=self.state.project_id,
                product_id=self.state.product_id,
            )
        if confirmed is None:
            raise ValueError("product candidate cannot be confirmed for this trial project")
        await self.export_report()

    async def synthesize_icp_proposals(self) -> tuple[ICPProposal, ...]:
        """Create inspectable proposals from the current version-pinned Client KB."""

        async with self._conn_factory() as conn:
            proposals = await synthesize_icps(
                conn,
                ClientKnowledgeBaseRef(
                    client_entity_id=EntityId(self.state.client_entity_id),
                    client_kb_version=self.state.client_kb_version,
                    product_id=self.state.product_id,
                ),
                workspace_id=self.state.workspace_id,
                gateway=self._gateway,
                synthesis_model=self._settings.synthesis_model,
            )
        payload = {
            "schema_version": "1",
            "workspace_id": self.state.workspace_id,
            "client_entity_id": str(self.state.client_entity_id),
            "client_kb_version": self.state.client_kb_version,
            "product_id": self.state.product_id,
            "generated_at": datetime.now(UTC),
            "proposals": [item.model_dump(mode="json") for item in proposals],
        }
        self.paths.icp_proposals.write_text(_pretty_json(payload) + "\n", encoding="utf-8")
        await self.export_report()
        return tuple(proposals)

    async def confirm_icp_proposal(self, number: int) -> ICPConfirmation:
        """Apply the human-only confirmation to one numbered proposal."""

        proposals = self._load_icp_proposals()
        if number < 1 or number > len(proposals):
            raise ValueError(f"proposal number must be between 1 and {len(proposals)}")
        async with self._conn_factory() as conn:
            project = await get_project(conn, self.state.project_id)
            if project is None or project.product_id != self.state.product_id:
                raise ValueError("confirm the project product before confirming an ICP")
            confirmation = await confirm_icp(
                conn,
                proposals[number - 1],
                workspace_id=self.state.workspace_id,
                client_entity_id=EntityId(self.state.client_entity_id),
                created_by="human:stage0-trial-cli",
                client_kb_version=self.state.client_kb_version,
                product_id=self.state.product_id,
            )
        await self.export_report()
        return confirmation

    async def snapshot(
        self,
        *,
        current_turn: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Compile the current truth the agent and human inspect before every turn."""

        async with self._conn_factory() as conn:
            project = await get_project(conn, self.state.project_id)
            if project is None or project.workspace_id != self.state.workspace_id:
                raise RuntimeError("Stage-0 trial project is missing")
            claims = await read_client_kb_claims(
                conn,
                EntityId(self.state.client_entity_id),
                workspace_id=self.state.workspace_id,
                version=self.state.client_kb_version,
                product_id=self.state.product_id,
            )
            memories = await self._rows(
                conn,
                """
                SELECT to_jsonb(m) AS payload
                FROM memory m
                WHERE workspace_id=:workspace
                  AND scope_id = ANY(CAST(:scopes AS text[]))
                ORDER BY created_at, memory_id
                """,
                {
                    "workspace": self.state.workspace_id,
                    "scopes": [
                        self.state.workspace_id,
                        self.state.brand_id,
                        self.state.product_id,
                        self.state.project_id,
                    ],
                },
            )
            statements = await self._rows(
                conn,
                """
                SELECT to_jsonb(s) AS payload
                FROM volunteered_statement s
                WHERE workspace_id=:workspace AND project_id=:project
                ORDER BY created_at, id
                """,
                {"workspace": self.state.workspace_id, "project": self.state.project_id},
            )
            readiness = await self._rows(
                conn,
                """
                SELECT to_jsonb(r) AS payload
                FROM readiness_decision r
                WHERE workspace_id=:workspace AND project_id=:project
                ORDER BY created_at, id
                """,
                {"workspace": self.state.workspace_id, "project": self.state.project_id},
            )
            icps = await self._rows(
                conn,
                """
                SELECT to_jsonb(i) AS payload
                FROM icp_spec i
                WHERE workspace_id=:workspace
                ORDER BY icp_key, version
                """,
                {"workspace": self.state.workspace_id},
            )
        return {
            "trial_boundary": {
                "manual_conversation_only": True,
                "website_research_performed": False,
                "exa_research_performed": False,
                "campaign_files_loaded": False,
            },
            "identity_seed": {
                "company_name": self.state.company_name,
                "website": self.state.website,
                "note": "Identity seed only; the website was not fetched.",
            },
            "workspace_id": self.state.workspace_id,
            "brand_id": self.state.brand_id,
            "product_candidate": {
                "product_id": self.state.product_id,
                "name": self.state.product_name,
            },
            "project": project.model_dump(mode="json"),
            "client_knowledge_base": {
                "client_entity_id": str(self.state.client_entity_id),
                "version": self.state.client_kb_version,
                "claims": {
                    field_key: claim.model_dump(mode="json")
                    for field_key, claim in sorted(claims.items())
                },
            },
            "memories": memories,
            "interview_statements": statements,
            "readiness_decisions": readiness,
            "icps": icps,
            "icp_proposals": [item.model_dump(mode="json") for item in self._load_icp_proposals()],
            "current_turn_input": current_turn,
        }

    async def export_report(self) -> None:
        """Write a human-readable transcript plus a complete JSON inspection bundle."""

        snapshot = await self.snapshot()
        history = await self._components.history.load(
            workspace_id=self.state.workspace_id,
            thread_id=self.state.thread_id,
        )
        messages: list[dict[str, object]] = []
        transcript_lines = [f"# Stage 0 trial: {self.state.session_slug}", ""]
        for item in history:
            body = (await self._components.artifacts.read(item.body_ref)).decode()
            messages.append(
                {
                    "sequence": item.sequence,
                    "turn_id": str(item.turn_id),
                    "role": item.role,
                    "body": body,
                    "artifact_ref": item.body_ref.model_dump(mode="json"),
                }
            )
            transcript_lines.extend((f"## {item.role.title()} {item.sequence}", "", body, ""))
        async with self._conn_factory() as conn:
            model_calls = await self._rows(
                conn,
                """
                SELECT to_jsonb(c) AS payload
                FROM agent_model_call c
                WHERE workspace_id=:workspace
                  AND turn_id IN (
                    SELECT id FROM agent_turn
                    WHERE workspace_id=:workspace AND thread_id=:thread
                  )
                ORDER BY started_at, sequence
                """,
                {"workspace": self.state.workspace_id, "thread": self.state.thread_id},
            )
            tool_results = await self._rows(
                conn,
                """
                SELECT jsonb_build_object(
                    'operation_id', r.operation_id,
                    'node_key', r.node_key,
                    'tool_address', r.tool_address,
                    'result_artifact_key', r.result_artifact_key,
                    'result_sha256', r.result_sha256,
                    'replayed', r.replayed,
                    'completed_at', r.completed_at
                ) AS payload
                FROM agent_tool_result r
                JOIN agent_plan p ON p.id=r.plan_id
                WHERE p.workspace_id=:workspace
                  AND p.turn_id IN (
                    SELECT id FROM agent_turn
                    WHERE workspace_id=:workspace AND thread_id=:thread
                  )
                ORDER BY r.completed_at, r.node_key
                """,
                {"workspace": self.state.workspace_id, "thread": self.state.thread_id},
            )
        report = {
            "schema_version": "1",
            "generated_at": datetime.now(UTC),
            "session": self.state.model_dump(mode="json"),
            "current_truth": snapshot,
            "conversation": messages,
            "model_calls": model_calls,
            "tool_results": tool_results,
        }
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.report_json.write_text(_pretty_json(report) + "\n", encoding="utf-8")
        self.paths.transcript.write_text("\n".join(transcript_lines), encoding="utf-8")
        summary = [
            f"# Stage 0 trial report: {self.state.session_slug}",
            "",
            "This trial is manual-conversation-only. It did not load campaign files, fetch the "
            "company website, call Exa, or run a scraper.",
            "",
            f"- Workspace: `{self.state.workspace_id}`",
            f"- Project: `{self.state.project_id}`",
            f"- Client entity: `{self.state.client_entity_id}`",
            f"- Client KB version: `{self.state.client_kb_version}`",
            f"- Conversation messages: {len(messages)}",
            f"- Durable client claims: {len(snapshot['client_knowledge_base']['claims'])}",  # type: ignore[index]
            f"- Scoped memories: {len(snapshot['memories'])}",  # type: ignore[arg-type]
            f"- Confirmed ICP versions: {len(snapshot['icps'])}",  # type: ignore[arg-type]
            "",
            "Inspect `transcript.md` for the conversation and `report.json` for exact claims, "
            "provenance, memory, readiness, model-call, and tool-result records.",
            "",
        ]
        self.paths.report_markdown.write_text("\n".join(summary), encoding="utf-8")

    async def close(self) -> None:
        self._components.workspaces.close()

    def _load_icp_proposals(self) -> tuple[ICPProposal, ...]:
        if not self.paths.icp_proposals.exists():
            return ()
        payload = json.loads(self.paths.icp_proposals.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("workspace_id") != self.state.workspace_id
            or payload.get("client_entity_id") != str(self.state.client_entity_id)
            or payload.get("client_kb_version") != self.state.client_kb_version
            or payload.get("product_id") != self.state.product_id
            or not isinstance(payload.get("proposals"), list)
        ):
            raise ValueError("ICP proposal file does not match the current Stage-0 trial lineage")
        return tuple(ICPProposal.model_validate(item) for item in payload["proposals"])

    async def _artifact(self, media_type: str, payload: object) -> ArtifactRef:
        return await self._components.artifacts.persist_body(
            workspace_id=self.state.workspace_id,
            data=_json_bytes(payload),
            media_type=media_type,
            subject_bindings=((self.state.client_entity_id, STAGE0_CONTEXT_BINDING_KIND),),
        )

    async def _drive(self, execution_id: ExecutionId) -> ExecutionStatus:
        async with self._conn_factory() as conn:
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id=_WORKER_ID,
            )
        if lease is None:
            raise RuntimeError("Stage-0 Recipe 0 execution is owned by another live worker")
        try:
            result = await self._executor.execute(
                execution_id,
                worker_id=_WORKER_ID,
                lease_generation=lease.generation,
            )
            return result.status
        finally:
            async with self._conn_factory() as conn:
                await release_work_lease(
                    conn,
                    work_id=WorkId(execution_id),
                    worker_id=_WORKER_ID,
                    generation=LeaseGeneration(lease.generation),
                )

    @staticmethod
    async def _rows(
        conn: AsyncConnection,
        query: str,
        parameters: dict[str, object],
    ) -> list[dict[str, object]]:
        rows = (await conn.execute(text(query), parameters)).scalars().all()
        return [dict(item) for item in rows]


__all__ = [
    "STAGE0_CONTEXT_BINDING_KIND",
    "STAGE0_USER_MESSAGE_BINDING_KIND",
    "Stage0Trial",
    "Stage0TrialPaths",
    "Stage0TrialState",
    "create_stage0_trial_session",
    "stage0_trial_context_policy",
    "stage0_trial_recipe_definitions",
    "stage0_trial_settings",
]
