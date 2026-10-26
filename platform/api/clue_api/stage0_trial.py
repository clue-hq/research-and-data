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

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    ArtifactRef,
    ContextAssemblyPolicy,
    ContextLayer,
    DomainObjectRef,
    FinalizeStatus,
    LayerBudget,
)
from clue_api.agent_platform_wiring import (
    AgentPlatformComponents,
    build_agent_platform_components,
)
from clue_api.agent_registry_wiring import STAGE0_CONVERSATION_TRIAL_SURFACE
from clue_api.agent_runtime_wiring import ModelFinalizeRequest
from clue_api.composition import load_research_packs
from clue_api.conversation_capture import (
    CONVERSATION_CONTEXT_BINDING_KIND,
    CONVERSATION_USER_MESSAGE_BINDING_KIND,
    persist_user_turn,
)
from clue_api.conversation_turns import (
    CONVERSATION_RECIPE_KEY,
    CONVERSATION_RECIPE_VERSION,
    ConversationTurnEngine,
    build_conversation_turn_engine,
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
from clue_api.run_composition import build_platform_gateway
from clue_api.stage0_card_dsar import stage0_card_subject_bindings
from clue_api.statement_evidence import (
    ArtifactStatementEvidenceReader,
    resolve_statement_quotes,
)
from clue_api.storage_wiring import build_storage_backend
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import (
    DEFAULT_STAGE0_POLICY,
    Secrets,
    Settings,
    default_gateway_config,
    load_settings,
)
from clue_core import (
    ContextAssembly,
    EntityId,
    ExecutionId,
    LLMGateway,
    MemoryType,
    MemoryWriteSeam,
    OnboardingInputId,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessSnapshotRef,
    VolunteeredStatementId,
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
from clue_projections import (
    STAGE0_PROJECT_CARD_MEDIA_TYPE,
    ExcludedEvidence,
    compile_stage0_project_card,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.stage0 import (
    CLIENT_BASELINE_FIELDS,
    CLIENT_ICP_SYNTHESIS_FIELDS,
    ClientInput,
    ClientKnowledgeBaseRef,
    ICPConfirmation,
    ICPProposal,
    ICPSynthesisStatus,
    ProjectStatement,
    VolunteeredMaterial,
    client_kb_readiness_metrics,
    confirm_icp,
    count_statements_for_input,
    ensure_readiness_spec,
    evaluate_readiness,
    read_client_kb_claims,
    read_statements,
    reverse_profile,
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
from clue_toolbelt import DbIdempotencyStore

_SESSION_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# A pure surface command: one line, a leading slash-command token, and at most three arguments
# (``/confirm-icp 2``). Deliberately syntactic — the guard below must not judge *content*, and a
# message that is really prose gets routed like any other turn.
_PURE_COMMAND = re.compile(r"^/\S+(?:[ \t]+\S+){0,3}$")
_TURN_NAMESPACE_LABEL = "stage0-trial-turn@1"
_EXECUTION_NAMESPACE_LABEL = "stage0-trial-execution@1"
_WORKER_ID = "stage0-trial-cli"
#: Aliases of the one shared vocabulary (:mod:`clue_api.conversation_capture`) — both conversation
#: surfaces bind the same two kinds, and two spellings of one binding kind would split DSAR reach.
STAGE0_USER_MESSAGE_BINDING_KIND = CONVERSATION_USER_MESSAGE_BINDING_KIND
STAGE0_CONTEXT_BINDING_KIND = CONVERSATION_CONTEXT_BINDING_KIND

#: The exact promoted Recipe-#0 revision this trial runs — the same pin the production project
#: conversation runs (:data:`~clue_api.conversation_turns.CONVERSATION_RECIPE_VERSION`), because the
#: C5 interaction slot's tool allowlist lives in that revision: a tool granted on the profile but
#: absent from the pinned revision is rejected at plan validation (`c5_tool_not_allowed`), so two
#: pins would mean two different callable tool sets for one role.
STAGE0_RECIPE_VERSION = CONVERSATION_RECIPE_VERSION


class Stage0ProductNotConfirmed(ValueError):
    """A human-gated Stage-0 step was attempted before the project's product was confirmed.

    Both ICP synthesis and ICP confirmation require the same gate: an ICP is only meaningful for a
    confirmed product, and the trial must not present proposals compiled against a product the
    human never chose."""

    def __init__(self, action: str) -> None:
        super().__init__(f"run /confirm-product first: {action} requires a confirmed product")
        self.action = action


NO_ROUTING_RECEIPT = (
    "This turn has no durable routing receipt, so it cannot be finalized as completed or "
    "awaiting_input: the human's message was captured as an onboarding input, but nothing was "
    "routed out of it, and reporting otherwise would claim work the database does not contain. "
    "Call record_interview_answer and route every part of the message you used — claim, memory, "
    "project_state, or a field/source proposal. The platform supplies this turn's captured "
    "message and its ids; you supply the routing. If nothing in the message is material, say so "
    "honestly by routing it with route='unmapped' (that route needs only a route_key and the "
    "exact quote offsets), then finalize again. Never tell the human that something was captured, "
    "recorded, saved, or stored except by reporting a routing receipt you actually received."
)


def is_pure_command(message: str) -> bool:
    """Structurally decide whether a user turn is only a surface command.

    "Substantive" is defined syntactically on purpose. The guard must not form an opinion about
    what the human *meant* — a false positive here only means the agent is not forced to route,
    and a false negative costs one honest ``unmapped`` route. Anything that is not a single-line
    slash command with at most three arguments is treated as substantive.
    """

    return _PURE_COMMAND.fullmatch(message.strip()) is not None


class Stage0RoutingReceiptGuard:
    """Refuse a Stage-0 finalize that reports work this turn has no durable receipt for.

    The live defect this closes: the agent told the human "this is now captured as project state"
    on seven consecutive turns while ``volunteered_statement`` stayed empty. Language policing
    cannot fix that — the check is structural instead. A ``completed``/``awaiting_input`` finalize
    of a substantive turn requires at least one routing receipt for *this* turn's captured
    onboarding input; ``failed``/``blocked`` are never gated, because an honest failure must not be
    forced through a write it could not make.

    Refusal raises ``ValueError``, which the runtime's bounded finalize repair hands back to the
    model as visible tool feedback: it gets a corrective attempt (route, then finalize) out of the
    turn's shared repair budget — shared with the finalize *shape* contract, which a converging
    model may also trip once — and an unrepaired refusal still ends the turn ``missing_finalize``.
    """

    def __init__(
        self,
        *,
        workspace_id: str,
        onboarding_input_id: OnboardingInputId,
        user_message: str,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._workspace_id = workspace_id
        self._onboarding_input_id = onboarding_input_id
        self._user_message = user_message
        self._conn_factory = conn_factory

    async def __call__(self, proposal: ModelFinalizeRequest) -> None:
        if proposal.status not in {FinalizeStatus.COMPLETED, FinalizeStatus.AWAITING_INPUT}:
            return
        if is_pure_command(self._user_message):
            return
        async with self._conn_factory() as conn:
            counts = await count_statements_for_input(
                conn,
                workspace_id=self._workspace_id,
                onboarding_input_id=self._onboarding_input_id,
            )
        if counts.total == 0:
            raise ValueError(NO_ROUTING_RECEIPT)


@dataclass(frozen=True, slots=True)
class _StoredProposals:
    """The saved ICP proposal file read against the *current* trial state.

    ``proposals`` is the offerable set and is empty whenever ``lineage_mismatch`` is set: a
    superseded file is a reference, never a confirmable candidate. ``lineage_mismatch`` names which
    lineage keys disagree — reference-only, never the superseded proposal content.
    """

    proposals: tuple[ICPProposal, ...]
    lineage_mismatch: str | None


@dataclass(frozen=True, slots=True)
class _ResolvedStatements:
    """Live project statements plus the ids whose evidence artifact no longer exists."""

    statements: tuple[ProjectStatement, ...]
    excluded_statement_ids: tuple[VolunteeredStatementId, ...]


class Stage0IcpSynthesis(BaseModel):
    """What the trial hands its callers after one ICP synthesis.

    ``proposals`` is already the *offerable* set: empty whenever ``status`` is not
    :attr:`~clue_research.stage0.ICPSynthesisStatus.GROUNDED`, so no surface can accidentally
    present the ungrounded floor as a numbered candidate. ``excluded_statement_ids`` names the
    statements left out because their captured evidence is gone (reference-only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ICPSynthesisStatus
    reason_codes: tuple[str, ...] = ()
    proposals: tuple[ICPProposal, ...] = ()
    excluded_statement_ids: tuple[VolunteeredStatementId, ...] = ()


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


def stage0_trial_context_policy() -> ContextAssemblyPolicy:
    """Conservative seven-layer budget with room for a long kickoff interview.

    L1 tracks the production conversation's 40,000 for the same reason: this trial resolves the
    same ``HEAD_OF_ABM`` profile, so it carries the same system prompt — prompt body plus generated
    capability map — and the fifteen-chapter operating manual put that prompt within 300 bytes of
    the old 24,000, which was then a ceiling that failed the turn. Since v3 (founder ruling
    2026-09-14) no layer budget withholds context or fails an assembly; these numbers are what the
    trial expects each layer to cost, and an overrun is logged rather than enforced. The trial and
    production still carry the *same* numbers so a trial keeps telling the truth about the profile
    production runs.
    """

    return ContextAssemblyPolicy(
        version="stage0-trial-context-v3",
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
        if definition.recipe_key == CONVERSATION_RECIPE_KEY
    )
    if not any(definition.version == STAGE0_RECIPE_VERSION for definition in definitions):
        raise RuntimeError(f"recipe0-stage0@{STAGE0_RECIPE_VERSION} definition is not installed")
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
        components: AgentPlatformComponents,
        engine: ConversationTurnEngine,
        executor: RecipeExecutor,
        recipes: DbRecipeReader,
        starter: DbExecutionStarter,
        parameters: ExecutionParameterStore,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self.state = state
        self.paths = paths
        self._settings = settings
        self._storage = storage
        self._gateway = gateway
        self._components = components
        # D2: the profile, context assembler, deepagent runtime and turn-execution path all live
        # on the shared engine now — the trial and the production project conversation run the
        # same twelve steps, and this harness is no longer a second copy of them.
        self._engine = engine
        self._executor = executor
        self._recipes = recipes
        self._starter = starter
        self._parameters = parameters
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
        # PC-C8 §8: the trial runs the promoted Head-of-ABM profile on its own *capability
        # surface*. `start_recon`, `synthesize_icps` and `submit_onboarding_input` are not
        # installed here (`C6_SURFACE_POLICIES`), so the middleware allowed-set, the resource
        # manifest, and the generated capability map all describe the same narrower surface —
        # the restriction is a tool that is absent, not prose asking the model to abstain.
        #
        # D2: composing that surface is now one shared call. This harness still runs it per
        # request — it is a per-session CLI whose whole point is a fresh, inspectable stack, and
        # its toolbelt is deliberately different (no scrape binder, Stage-0 recipes only) — while
        # the production worker calls the identical builder once at startup.
        engine = build_conversation_turn_engine(
            surface=STAGE0_CONVERSATION_TRIAL_SURFACE,
            components=components,
            tools=tools,
            tool_invoker=tool_invoker,
            executor=executor,
            compatibility=compatibility,
            memory=memory_assembly_factory(resolved_settings, conn_factory),
            requested_memory_types=(
                MemoryType.PREFERENCE,
                MemoryType.BEHAVIORAL_LEARNING,
            ),
            context_policy=stage0_trial_context_policy(),
            conn_factory=conn_factory,
        )
        return cls(
            state=state,
            paths=paths,
            settings=resolved_settings,
            storage=storage,
            gateway=gateway,
            components=components,
            engine=engine,
            executor=executor,
            recipes=recipes,
            starter=starter,
            parameters=parameters,
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
        # Capture before spend, through the one shared owner of that path (D2).
        async with self._conn_factory() as conn:
            captured = await persist_user_turn(
                conn,
                artifacts=self._components.artifacts,
                workspace_id=self.state.workspace_id,
                brand_id=self.state.brand_id,
                product_id=self.state.product_id,
                project_id=self.state.project_id,
                client_entity_id=EntityId(self.state.client_entity_id),
                turn_id=turn_id,
                message=message,
            )
        user_ref = captured.artifact_ref
        requested_at = datetime.now(UTC)
        resolved = self._engine.resolved
        card_ref = await self._project_card_ref()
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
            version=STAGE0_RECIPE_VERSION,
        )
        if revision is None:
            raise RuntimeError(f"promoted recipe0-stage0@{STAGE0_RECIPE_VERSION} is not installed")
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
        lease = await self._components.workspaces.acquire_restored(
            workspace_id=self.state.workspace_id,
            project_id=self.state.project_id,
            thread_id=self.state.thread_id,
            execution_id=execution_id,
            policy=resolved.profile.workspace,
        )
        try:
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
                    client_entity_id=str(self.state.client_entity_id),
                    workspace_root_id=lease.identity.workspace_root_id,
                    project_card_ref=card_ref,
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
            # Reserve the sequence before model spend. A crash leaves an explicit unfinalized
            # turn and cannot let a later, different message reuse its immutable turn/execution
            # identity. (It now happens just *before* the shared execution path rather than
            # inside it — strictly earlier than before, so the guarantee is unchanged.)
            self.state = self.state.model_copy(update={"next_turn": sequence + 1})
            self.paths.save_state(self.state)
            result = await self._engine.execute(
                request=request,
                lease=lease,
                budget_limit_millicents=budget_limit,
                completion_guard=Stage0RoutingReceiptGuard(
                    workspace_id=self.state.workspace_id,
                    onboarding_input_id=captured.onboarding_input_id,
                    user_message=message,
                    conn_factory=self._conn_factory,
                ),
            )
            outcome = result.outcome
            assistant_message = result.assistant_message
            if (
                outcome.finalization_ref is not None
                and outcome.status is AgentExecutionStatus.COMPLETED
            ):
                # ``actor='human'`` matches the gate's declared authority in ``recipe0-stage0``
                # — the human who submitted the turn is the one whose interaction just ended.
                # This read ``'agent'`` until FI Lane D D4: a latent mismatch against a
                # HUMAN-authority gate that the production runner (``agent_turn_fleet_wiring``)
                # never inherited, kept alive only because ``decide_gate`` is the trial's last
                # step and its ``ExecutionConflict`` was never reached in a passing run.
                # Reconciled here so one gate has one authority.
                await self._executor.decide_gate(
                    execution_id=execution_id,
                    node_key="stage0_interactions",
                    actor="human",
                    decision="complete",
                )
                completed = await self._drive(execution_id)
                if completed is not ExecutionStatus.COMPLETED:
                    raise RuntimeError("completed Stage-0 turn did not complete Recipe 0")
            await self._refresh_client_kb_from_conversation()
            # Readiness is deterministic evidence, not a thing the agent may claim: recompute
            # it from durable state after any turn that actually routed material information,
            # so the readiness ledger reflects the conversation instead of staying empty for
            # the whole trial.
            await self._recompute_readiness(
                turn_id=turn_id,
                onboarding_input_id=captured.onboarding_input_id,
            )
            self.paths.save_state(self.state)
            await self.export_report()
            return outcome, assistant_message
        finally:
            await self._components.workspaces.release_saved(lease)

    async def _recompute_readiness(
        self,
        *,
        turn_id: UUID,
        onboarding_input_id: OnboardingInputId,
    ) -> ReadinessSnapshotRef | None:
        """Re-run the C4 readiness evaluator over durable truth after a material routed turn.

        Reuses :func:`~clue_research.stage0.evaluate_readiness` — the one Stage-0 readiness
        implementation — with metrics compiled from the version-pinned Client KB and this
        project's live statements. A turn whose only receipts are ``unmapped`` routed nothing
        material, so there is no new evidence to evaluate and no decision is written.

        The decision id is derived from the turn *and* the immutable context the evaluator pins,
        so replaying the same turn against the same truth is idempotent while a turn re-run after
        the product or Client-KB version moved records a new, honest decision instead of tripping
        the evaluator's replay check.
        """

        async with self._conn_factory() as conn:
            counts = await count_statements_for_input(
                conn,
                workspace_id=self.state.workspace_id,
                onboarding_input_id=onboarding_input_id,
            )
            if counts.non_unmapped == 0:
                return None
            project = await get_project(conn, self.state.project_id)
            if project is None or project.workspace_id != self.state.workspace_id:
                raise RuntimeError("Stage-0 trial project is missing")
            claims = await read_client_kb_claims(
                conn,
                EntityId(self.state.client_entity_id),
                workspace_id=self.state.workspace_id,
                version=self.state.client_kb_version,
                product_id=None,
            )
            statements = await read_statements(
                conn,
                workspace_id=self.state.workspace_id,
                project_id=self.state.project_id,
            )
            # One shared metric compiler, with this ICP gate's explicit nine-field denominator;
            # the Clue-Trial discovery gate uses the broader company-knowledge denominator.
            # Per-turn interview counters remain additional surface-owned evidence.
            metrics: dict[str, Any] = {
                **client_kb_readiness_metrics(
                    claims,
                    baseline_field_keys=CLIENT_ICP_SYNTHESIS_FIELDS,
                ),
                "project_state_statements": len(statements),
                "routed_statements_this_turn": counts.total,
                "material_statements_this_turn": counts.non_unmapped,
            }
            decision_id = ReadinessDecisionId(
                uuid5(
                    turn_id,
                    "stage0-trial-readiness:"
                    f"{ReadinessGate.ICP_SYNTHESIS.value}:{self.state.brand_id}:"
                    f"{project.product_id}:{self.state.project_id}:"
                    f"{self.state.client_entity_id}:{self.state.client_kb_version}",
                )
            )
            return await evaluate_readiness(
                conn,
                workspace_id=self.state.workspace_id,
                brand_id=self.state.brand_id,
                # The decision records the *confirmed* product (None until the human confirms),
                # never the unconfirmed candidate the KB read is scoped to.
                product_id=project.product_id,
                project_id=self.state.project_id,
                client_entity_id=EntityId(self.state.client_entity_id),
                client_kb_version=self.state.client_kb_version,
                gate=ReadinessGate.ICP_SYNTHESIS,
                spec=DEFAULT_STAGE0_POLICY.readiness,
                metrics=metrics,
                # Deterministic engine work, not an agent claim (the DB pins the actor vocabulary).
                created_by_actor="system",
                readiness_decision_id=decision_id,
            )

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
                product_id=None,
            )
            raw = await claims_for(
                conn,
                EntityId(self.state.client_entity_id),
                scope=WorkspaceScope.for_workspace(self.state.workspace_id),
            )
            live: dict[str, Any] = {}
            for claim in raw:
                if (
                    claim.field_key in CLIENT_BASELINE_FIELDS
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

    async def synthesize_icp_proposals(self) -> Stage0IcpSynthesis:
        """Synthesize from the version-pinned Client KB **and** the project's own statements.

        Human-gated exactly like confirmation: an unconfirmed product refuses. A result with no
        grounding evidence is persisted as a not-ready outcome with **no numbered proposals**, so
        the ungrounded config floor can never be confirmed as if it were a real candidate.
        """

        async with self._conn_factory() as conn:
            project = await get_project(conn, self.state.project_id)
            if project is None or project.product_id != self.state.product_id:
                raise Stage0ProductNotConfirmed("ICP synthesis")
            resolved = await self._project_statements(conn)
            result = await synthesize_icps(
                conn,
                ClientKnowledgeBaseRef(
                    client_entity_id=EntityId(self.state.client_entity_id),
                    client_kb_version=self.state.client_kb_version,
                    # The trial state's Client-KB version is the account-wide company lineage.
                    # Product identity remains an independent, already-confirmed project pin.
                    product_id=None,
                ),
                workspace_id=self.state.workspace_id,
                project_statements=resolved.statements,
                gateway=self._gateway,
                synthesis_model=self._settings.synthesis_model,
            )
        grounded = result.status is ICPSynthesisStatus.GROUNDED
        payload = {
            "schema_version": "1",
            "workspace_id": self.state.workspace_id,
            "client_entity_id": str(self.state.client_entity_id),
            "client_kb_version": self.state.client_kb_version,
            "product_id": self.state.product_id,
            "generated_at": datetime.now(UTC),
            "status": result.status.value,
            "reason_codes": list(result.reason_codes),
            "project_statement_ids": [str(item.statement_id) for item in resolved.statements],
            # Statements whose captured evidence artifact is gone (DSAR erasure / tombstone /
            # purge). Reference-only: the ids record what was left out, never the lost words.
            "excluded_statement_ids": [str(item) for item in resolved.excluded_statement_ids],
            # An ungrounded floor is recorded for inspection but is deliberately NOT offered as a
            # confirmable proposal — /confirm-icp has nothing to confirm until evidence exists.
            "proposals": (
                [item.model_dump(mode="json") for item in result.proposals] if grounded else []
            ),
            "not_ready_floor": (
                None if grounded else [item.model_dump(mode="json") for item in result.proposals]
            ),
        }
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.icp_proposals.write_text(_pretty_json(payload) + "\n", encoding="utf-8")
        await self.export_report()
        return Stage0IcpSynthesis(
            status=result.status,
            reason_codes=result.reason_codes,
            proposals=result.proposals if grounded else (),
            excluded_statement_ids=resolved.excluded_statement_ids,
        )

    async def _project_statements(self, conn: AsyncConnection) -> _ResolvedStatements:
        """Resolve this project's live ``project_state`` statements into synthesis evidence.

        The slicing, hash verification, workspace scoping and erased-evidence semantics all live in
        :func:`~clue_api.statement_evidence.resolve_statement_quotes` — the same seam the PC-C8
        Stage-0 project card reads through. That shared owner is the point: if synthesis resolved
        quotes here and the card resolved them elsewhere, the model's context and the synthesis
        prompt could disagree about what a statement says. This method only shapes the shared
        result into the synthesis input contract.
        """

        rows = await read_statements(
            conn,
            workspace_id=self.state.workspace_id,
            project_id=self.state.project_id,
        )
        resolutions = await resolve_statement_quotes(
            conn,
            self._components.artifacts,
            workspace_id=self.state.workspace_id,
            statements=rows,
        )
        route_keys = {str(row.id): row.route_key for row in rows}
        statements: list[ProjectStatement] = []
        excluded: list[VolunteeredStatementId] = []
        for item in resolutions:
            if isinstance(item, ExcludedEvidence):
                excluded.append(item.statement_id)
                continue
            statements.append(
                ProjectStatement(
                    statement_id=item.statement_id,
                    route_key=route_keys[str(item.statement_id)],
                    quote=item.quote,
                )
            )
        return _ResolvedStatements(
            statements=tuple(statements),
            excluded_statement_ids=tuple(excluded),
        )

    async def confirm_icp_proposal(self, number: int) -> ICPConfirmation:
        """Apply the human-only confirmation to one numbered proposal."""

        proposals = self._load_icp_proposals()
        if not proposals:
            raise ValueError(
                "no grounded ICP proposal is available — run /synthesize-icp after the "
                "conversation has produced durable evidence"
            )
        if number < 1 or number > len(proposals):
            raise ValueError(f"proposal number must be between 1 and {len(proposals)}")
        async with self._conn_factory() as conn:
            project = await get_project(conn, self.state.project_id)
            if project is None or project.product_id != self.state.product_id:
                raise Stage0ProductNotConfirmed("ICP confirmation")
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

    async def snapshot(self) -> dict[str, object]:
        """Compile the full current truth the **human** inspects (`/status`, `report.json`).

        Deliberately unbounded and full-fidelity: this is an inspection surface, and completeness
        is its job. It no longer feeds model context — PC-C8 gave L3 one bounded owner
        (:meth:`_project_card_ref`), and the two roles pulled in opposite directions.

        It also no longer names the current turn. Turn identity has exactly one owner now (the L7
        envelope, from the engine-side binding); carrying it here as well is what let the model
        read an id out of L3 and hand it back as if it had chosen it.
        """

        async with self._conn_factory() as conn:
            project = await get_project(conn, self.state.project_id)
            if project is None or project.workspace_id != self.state.workspace_id:
                raise RuntimeError("Stage-0 trial project is missing")
            claims = await read_client_kb_claims(
                conn,
                EntityId(self.state.client_entity_id),
                workspace_id=self.state.workspace_id,
                version=self.state.client_kb_version,
                product_id=None,
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
        stored = self._read_icp_proposals()
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
            # Reference-only. A proposal file from a superseded lineage offers nothing confirmable
            # and says so, rather than raising and taking every turn, status read, and report
            # export down with it — /confirm-icp is where lineage drift is still fatal.
            "icp_proposals": [item.model_dump(mode="json") for item in stored.proposals],
            "icp_proposals_stale": stored.lineage_mismatch is not None,
            "icp_proposals_stale_reason": stored.lineage_mismatch,
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

    def _read_icp_proposals(self) -> _StoredProposals:
        """Read the saved proposal file *tolerantly*, reporting drift instead of raising.

        Reading superseded proposals and confirming one are different concerns, and conflating
        them bricked whole sessions: this used to raise on any lineage drift, while ``snapshot()``
        — which runs at the start and end of *every* turn, and behind ``/status`` and every report
        export — called it unconditionally. The first claim-bearing turn after ``/synthesize-icp``
        publishes the next immutable Client-KB version, so from that turn on every read raised
        until the human happened to re-synthesize.

        Drift is therefore surfaced, not thrown: no proposals are offered (nothing stale can be
        confirmed by accident) and the mismatch is named. The name is *reference-only* — which
        lineage keys disagree, never the superseded content. Authority stays with
        :meth:`_load_icp_proposals`, which is what confirmation calls.
        """

        if not self.paths.icp_proposals.exists():
            return _StoredProposals(proposals=(), lineage_mismatch=None)
        try:
            payload = json.loads(self.paths.icp_proposals.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _StoredProposals(
                proposals=(),
                lineage_mismatch="the saved ICP proposal file is not readable JSON",
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("proposals"), list):
            return _StoredProposals(
                proposals=(),
                lineage_mismatch="the saved ICP proposal file is not a proposal record",
            )
        drifted = sorted(
            key
            for key, current in (
                ("workspace_id", self.state.workspace_id),
                ("client_entity_id", str(self.state.client_entity_id)),
                ("client_kb_version", self.state.client_kb_version),
                ("product_id", self.state.product_id),
            )
            if payload.get(key) != current
        )
        if drifted:
            return _StoredProposals(
                proposals=(),
                lineage_mismatch=(
                    "the saved ICP proposals were synthesized against a different "
                    f"{', '.join(drifted)}; run /synthesize-icp again"
                ),
            )
        try:
            proposals = tuple(ICPProposal.model_validate(item) for item in payload["proposals"])
        except ValidationError:
            return _StoredProposals(
                proposals=(),
                lineage_mismatch="the saved ICP proposals are not valid proposal records",
            )
        return _StoredProposals(proposals=proposals, lineage_mismatch=None)

    def _load_icp_proposals(self) -> tuple[ICPProposal, ...]:
        """The strict read: confirming a proposal is where lineage is authority, so drift raises.

        A confirmation stamps ``self.state.client_kb_version`` onto the confirmed ICP, so a
        proposal synthesized against an older version would be recorded under a lineage it was
        never derived from. Empty is a correct outcome here; misattributed is not.
        """

        stored = self._read_icp_proposals()
        if stored.lineage_mismatch is not None:
            raise ValueError(
                "ICP proposal file does not match the current Stage-0 trial lineage: "
                f"{stored.lineage_mismatch}"
            )
        return stored.proposals

    async def _project_card_ref(self) -> ArtifactRef:
        """Compile and persist this turn's L3 project card (PC-C8 §3).

        The card replaces the stage/readiness snapshot pair: one bounded, typed projection of
        durable project state instead of two `to_jsonb` dumps that re-serialized the same readiness
        ledger and grew with every turn. Persisting is content-addressed, so an unchanged project
        re-persists the same key — the crash-replay reuse AC-9 asks for falls out of that rather
        than out of a cache.

        ``readiness_spec_version`` is passed **explicitly**: the compiler's default is the
        workspace's newest spec revision, but the card must show what *this engine* evaluates
        against, which is the revision ``DEFAULT_STAGE0_POLICY.readiness`` hashes to. A newer
        revision written by anything else would otherwise silently mark every live gate
        ``not_evaluated_for_current_lineage``.
        """

        async with self._conn_factory() as conn:
            spec_version = await ensure_readiness_spec(
                conn,
                workspace_id=self.state.workspace_id,
                spec=DEFAULT_STAGE0_POLICY.readiness,
            )
        stored = self._read_icp_proposals()
        card = await compile_stage0_project_card(
            project_id=self.state.project_id,
            workspace_id=self.state.workspace_id,
            client_entity_id=EntityId(self.state.client_entity_id),
            client_kb_version=self.state.client_kb_version,
            evidence=ArtifactStatementEvidenceReader(
                artifacts=self._components.artifacts,
                conn_factory=self._conn_factory,
            ),
            product_id=self.state.product_id,
            # Proposal *bodies* stay on the human surface (spec §5.1); the card says only whether
            # something confirmable is waiting, and whether it has drifted out of lineage.
            proposals_pending=bool(stored.proposals),
            proposals_stale=stored.lineage_mismatch is not None,
            readiness_spec_version=spec_version,
            conn_factory=self._conn_factory,
        )
        return await self._components.artifacts.persist_body(
            workspace_id=self.state.workspace_id,
            data=card.canonical_bytes(),
            media_type=STAGE0_PROJECT_CARD_MEDIA_TYPE,
            # PC-C8 §9: the body embeds `quoted_text` — a derived copy of interview personal data
            # this slice creates — so it is bound to *every statement it quotes*, not only to the
            # client. Per-source bindings are what make "which card artifacts quote statement X" a
            # direct query, and therefore what makes erasure of one statement's words reach the
            # cards that copied them.
            subject_bindings=stage0_card_subject_bindings(
                card=card,
                base=((self.state.client_entity_id, STAGE0_CONTEXT_BINDING_KIND),),
            ),
        )

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
    "NO_ROUTING_RECEIPT",
    "STAGE0_CONTEXT_BINDING_KIND",
    "STAGE0_RECIPE_VERSION",
    "STAGE0_USER_MESSAGE_BINDING_KIND",
    "Stage0IcpSynthesis",
    "Stage0ProductNotConfirmed",
    "Stage0RoutingReceiptGuard",
    "Stage0Trial",
    "Stage0TrialPaths",
    "Stage0TrialState",
    "create_stage0_trial_session",
    "is_pure_command",
    "stage0_trial_context_policy",
    "stage0_trial_recipe_definitions",
    "stage0_trial_settings",
]
