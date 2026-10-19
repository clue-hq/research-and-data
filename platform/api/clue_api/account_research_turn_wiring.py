"""C6.8 API-root preparation for one governed account-research deepagent turn."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import text

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
    ProjectContextArtifact,
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
from clue_api.agent_registry_wiring import ACCOUNT_RESEARCH_UNIT_SURFACE
from clue_api.agent_runtime_wiring import CompletionGuard
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.arv2.display.gather import SubjectNotFound, resolve_subject
from clue_config import Settings
from clue_core import (
    AccountEntity,
    AssemblyRequest,
    ContextAssembly,
    EntityId,
    ExecutionId,
    MemoryBundle,
    MemorySelectionPin,
    MemorySelectionStale,
    MemorySelectionUnavailable,
    MemoryType,
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
from clue_research.directives import effective_account_research_directive
from clue_research.durable import (
    AccountRunRow,
    ProjectRunRow,
    ResearchPlan,
    get_account_run,
    get_project_run,
)
from clue_research.identity import get_account, get_contact
from clue_spine import Brand, Product, Project, get_brand, get_product, get_project
from clue_storage import StorageBackend, read_verified_artifact
from clue_toolbelt import ToolInvoker, ToolRegistry

__all__ = [
    "ACCOUNT_RESEARCH_CARD_MEDIA_TYPE",
    "DbCompiledContextCardReader",
    "PreparedAccountResearchTurnRunner",
    "account_research_card_payload",
    "account_research_context_policy",
    "build_account_research_context",
]

#: This surface's L3 card: the account-research analogue of the Stage-0 project card, carrying the
#: plan and the admission verdict that used to be two separate constitution refs (PC-C8 §10).
ACCOUNT_RESEARCH_CARD_MEDIA_TYPE = "application/vnd.clue.account-research-card+json"

_EXECUTION_NAMESPACE_KEY = "account-research-unit@1"
_TURN_NAMESPACE = UUID("85af4b9f-7d41-51ea-a333-7181c4fdb12f")
_PREPARER_WORKER_ID = "agent-account-research-preparer"


def account_research_card_payload(
    *,
    workspace_id: str,
    project: Project,
    project_run_id: ProjectRunId,
    account_run_id: RunId,
    account_entity_id: EntityId,
    account_run_status: str,
    tier: str,
    plan: ResearchPlan,
) -> dict[str, JsonValue]:
    """The whole L3 card this surface puts in front of the model (PC-C8 §10).

    One card per surface. The two snapshots it replaced were already small and bounded (a plan and
    an admission verdict, neither growing with conversation length), so the fix here is the *shape*
    rule rather than a size fix — same fields, one payload, its own media type. It is deliberately
    not a ``Stage0ProjectCard``: nothing on this surface has a Stage-0 interview to project.

    The ``project`` block is not decoration. Dropping ``ProjectLayerSource``'s compiled project-row
    read was justified by "the card subsumes it" — true of the Stage-0 card, which describes the
    project in detail, and **false here** unless this card names the project the run belongs to.
    The constitution still sets ``project_id``, so without it the model is scoped to a project it
    cannot name.

    Pure and separately callable so the payload's shape is testable without standing up a project
    run, an account run, and a research plan.
    """

    return {
        "schema_version": "1",
        "card_kind": "account_research",
        "surface": "account_research",
        "project": {
            "project_id": project.project_id,
            "name": project.name,
            "status": project.status,
            "workspace_id": workspace_id,
            "brand_id": project.brand_id,
            "product_id": project.product_id,
        },
        "project_run_id": str(project_run_id),
        "account_run_id": str(account_run_id),
        "account_entity_id": str(account_entity_id),
        "tier": tier,
        "plan": plan.model_dump(mode="json"),
        "admission": {
            "admitted": True,
            "authority": "deep_phase_account_admission",
            "account_run_status": account_run_status,
        },
    }


class _NoMemoryContext:
    """The memory seam with memory switched off: no bodies, no pins, no journal."""

    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        del request
        return None

    async def select(
        self, request: AssemblyRequest
    ) -> MemorySelectionPin | MemorySelectionUnavailable:
        del request
        return MemorySelectionUnavailable(reason="memory_disabled")

    async def resolve(
        self, request: AssemblyRequest, pin: MemorySelectionPin
    ) -> MemoryBundle | MemorySelectionStale | MemorySelectionUnavailable:
        del request, pin
        return MemorySelectionUnavailable(reason="memory_disabled")


def account_research_context_policy() -> ContextAssemblyPolicy:
    """The exact conservative opening-context budget for account-research@v1.

    Budgets are reported, never enforced (founder ruling 2026-09-14), which is why this is v3:
    ``max_tokens`` is what this surface expects a layer to cost, and an overrun is logged rather
    than trimmed or failed. The numbers are unchanged from v2 — only what they mean is.
    """

    return ContextAssemblyPolicy(
        version="account-research-context-v3",
        token_counter_version="utf8-bytes-v1",
        budgets=tuple(
            LayerBudget(layer=layer, max_tokens=budget)
            for layer, budget in zip(
                tuple(ContextLayer),
                (24_000, 8_000, 128_000, 16_000, 16_000, 0, 12_000),
                strict=True,
            )
        ),
    )


class DbCompiledContextCardReader:
    """Compile minimal, typed cards from the owning stores; never query agent-owned state."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        storage: StorageBackend | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        # Only the ``brand_knowledge_document`` and ``project_document`` types use blob bytes (the
        # latter only for the title); every other type compiles from durable rows alone, so a
        # reader built without storage still serves them all.
        self._storage = storage

    async def read(
        self,
        *,
        workspace_id: str,
        object_type: str,
        object_id: str,
    ) -> CompiledContextCard | None:
        async with self._conn_factory() as conn:
            value: Brand | Product | Project | AccountEntity | None
            body: str | None = None
            version: int | None = None
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
                version = None if value is None else value.canonical_version
            elif object_type == "design_document":
                # P3.1 (master plan §2.4): the design leg's target-document focus ref.
                # clue_api is the composition root and may import clue_design directly;
                # the card is a minimal typed summary, never the scene body.
                from clue_api.design_leg_wiring import head_of_abm_doc_kind
                from clue_design.documents import get_document as get_design_document
                from clue_design.errors import DesignNotFoundError

                try:
                    document = await get_design_document(
                        conn, workspace_id=workspace_id, document_id=object_id
                    )
                except DesignNotFoundError:
                    return None
                value = None
                body = json.dumps(
                    {
                        "id": document["id"],
                        "title": document.get("title"),
                        "doc_kind": head_of_abm_doc_kind(str(document.get("doc_kind") or "")),
                        "status": document.get("status"),
                        "current_version": document.get("current_version"),
                        "brand_kit_id": document.get("effective_brand_kit_id"),
                        "brand_kit_version": document.get("effective_brand_kit_version"),
                    },
                    sort_keys=True,
                )
                # A fresh document's CAS counter is 0, and DomainObjectRef versions are
                # >= 1 — an unwritten document is honestly unversioned.
                version = document.get("current_version") or None
            elif object_type == "brand_knowledge_document":
                # O4: an onboarding knowledge document rides the focus layer as its own markdown.
                # The body is the verified artifact, never a re-rendered summary.
                if self._storage is None:
                    return None
                try:
                    document_id = UUID(object_id)
                except ValueError:
                    return None
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT version, artifact_key FROM brand_knowledge_document "
                                "WHERE document_id = :document_id AND workspace_id = :workspace_id"
                            ),
                            {"document_id": document_id, "workspace_id": workspace_id},
                        )
                    )
                    .mappings()
                    .first()
                )
                # A document still running has no bytes yet — an honest miss, never a blank body.
                if row is None or row["artifact_key"] is None:
                    return None
                _, data = await read_verified_artifact(
                    conn,
                    self._storage,
                    storage_key=str(row["artifact_key"]),
                    workspace_id=workspace_id,
                )
                value = None
                body = data.decode()
                version = int(row["version"])
            elif object_type == "project_document":
                # A Gallery file the user tagged. The card is a typed summary that says WHERE
                # the file is in the agent's workspace — the body already sits under the
                # read-only ``project`` mount — never the body itself (that is the
                # ``brand_knowledge_document`` branch's job for onboarding knowledge).
                from clue_api.arv2.project_documents import (
                    document_title,
                    read_project_document,
                    workspace_path_of,
                )

                try:
                    document_id = UUID(object_id)
                except ValueError:
                    return None
                row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT document_id, project_id, path, kind, version, status, "
                                "updated_at, artifact_key FROM brand_knowledge_document "
                                "WHERE document_id = :document_id "
                                "  AND workspace_id = :workspace_id "
                                "  AND project_id IS NOT NULL"
                            ),
                            {"document_id": document_id, "workspace_id": workspace_id},
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None or row["artifact_key"] is None:
                    return None
                front: dict[str, Any] = {}
                text_body = ""
                if self._storage is not None:
                    # ``servable_only=False``: a replayed turn whose tagged version has since
                    # been superseded still names the document the user tagged.
                    read = await read_project_document(
                        conn,
                        self._storage,
                        workspace_id=workspace_id,
                        project_id=str(row["project_id"]),
                        document_id=document_id,
                        servable_only=False,
                    )
                    if read is not None:
                        _, front, text_body = read
                value = None
                body = json.dumps(
                    {
                        "document_id": str(row["document_id"]),
                        "path": workspace_path_of(str(row["path"])),
                        "title": document_title(front, text_body, path=str(row["path"])),
                        "kind": row["kind"],
                        "version": int(row["version"]),
                        "status": row["status"],
                        "updated_at": row["updated_at"].isoformat(),
                    },
                    sort_keys=True,
                )
                version = int(row["version"])
            elif object_type == "contact":
                try:
                    entity_id = EntityId(UUID(object_id))
                except ValueError:
                    return None
                contact = await get_contact(conn, entity_id)
                if contact is None or contact.workspace_id != workspace_id:
                    return None
                try:
                    subject = await resolve_subject(
                        conn,
                        workspace_id=workspace_id,
                        kind="contact",
                        subject_id=str(contact.id),
                    )
                except SubjectNotFound:
                    return None
                value = None
                # The same minimal typed summary the design-document branch above compiles: who
                # this person is and which account they hang under. The card is opening context,
                # not the research — the agent reads a contact's claims through the toolbelt, and
                # inlining a whole profile here would put an unbounded, ungoverned copy of one
                # person's personal data into every turn that mentions them.
                body = json.dumps(
                    {
                        "name": subject.name,
                        "title": subject.title,
                        "persona": subject.persona,
                        "account_name": subject.account_name,
                        "account_domain": subject.account_domain,
                    },
                    sort_keys=True,
                )
                version = contact.canonical_version
            else:
                return None
        if body is None:
            if value is None or value.workspace_id != workspace_id:
                return None
            body = value.model_dump_json(exclude_none=False)
        return CompiledContextCard(
            ref=DomainObjectRef(
                workspace_id=workspace_id,
                object_type=object_type,
                object_id=object_id,
                version=version,
            ),
            body=body,
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
        resolved = self._profiles.resolve(
            AgentRole.ACCOUNT_RESEARCH,
            surface=ACCOUNT_RESEARCH_UNIT_SURFACE,
        )
        project_run, account_run, account, project = await self._load_scope(
            workspace_id=workspace_id,
            project_run_id=project_run_id,
            account_run_id=account_run_id,
            account_entity_id=account_entity_id,
            tier=tier,
        )
        if account_run.research_directive != plan.research_directive:
            raise ValueError("account run and durable research plan directive pins differ")
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
            thread_id=f"account-research-{account_run_id}",
            execution_id=execution_id,
            policy=resolved.profile.workspace,
        )
        try:
            focus_ref = DomainObjectRef(
                workspace_id=workspace_id,
                object_type="account",
                object_id=str(account_entity_id),
                version=None,
            )
            project_context_artifacts: tuple[ProjectContextArtifact, ...] = ()
            if plan.research_directive is not None:
                async with self._conn_factory() as conn:
                    effective_directive = await effective_account_research_directive(
                        conn,
                        workspace_id=workspace_id,
                        directive_id=plan.research_directive.directive_id,
                        account_id=account_entity_id,
                        expected_pin=plan.research_directive,
                    )
                directive_artifact_ref = await self._artifact(
                    workspace_id,
                    "application/vnd.clue.account-research-directive+json",
                    effective_directive.model_dump(mode="json"),
                    account_entity_id,
                    project.project_id,
                )
                project_context_artifacts = (
                    ProjectContextArtifact(
                        name="research-directive",
                        artifact_ref=directive_artifact_ref,
                        domain_ref=DomainObjectRef(
                            workspace_id=workspace_id,
                            object_type="research_directive",
                            object_id=str(plan.research_directive.directive_id),
                            version=plan.research_directive.version,
                        ),
                    ),
                )
            card_ref = await self._artifact(
                workspace_id,
                ACCOUNT_RESEARCH_CARD_MEDIA_TYPE,
                account_research_card_payload(
                    workspace_id=workspace_id,
                    project=project,
                    project_run_id=project_run_id,
                    account_run_id=account_run_id,
                    account_entity_id=account_entity_id,
                    account_run_status=account_run.status.value,
                    tier=tier,
                    plan=plan,
                ),
                account_entity_id,
                project.project_id,
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
                project.project_id,
            )
            manifest_ref = await self._artifact(
                workspace_id,
                "application/vnd.clue.agent-resource-manifest+json",
                resolved.resource_manifest.model_dump(mode="json"),
                account_entity_id,
                project.project_id,
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
                    "strategy_contract": {
                        "authority": "coverage_engine",
                        "instruction": (
                            "Omit strategy_hint unless a prior governed result names the exact "
                            "next permitted engine strategy. Never use source-family names or "
                            "skip the engine-owned waterfall."
                        ),
                    },
                    "research_directive_ref": (
                        plan.research_directive.directive_ref
                        if plan.research_directive is not None
                        else None
                    ),
                    "research_directive_sha256": (
                        plan.research_directive.canonical_json_sha256
                        if plan.research_directive is not None
                        else None
                    ),
                },
                account_entity_id,
                project.project_id,
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
                    project_card_ref=card_ref,
                    budget_envelope_ref=budget_ref,
                    profile_ref=resolved.profile_ref,
                    resource_manifest_ref=manifest_ref,
                    resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                    focus_refs=(focus_ref,),
                    project_context_artifacts=project_context_artifacts,
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
        finally:
            lease.release()

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
        project_id: str,
    ) -> ArtifactRef:
        return await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            subject_bindings=((UUID(str(account_entity_id)), "context"),),
            project_bindings=((project_id, "account_research_context"),),
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
    memory: ContextAssembly | None = None,
    conn_factory: ConnFactory = transaction,
) -> DeterministicAgentContextAssembler:
    """Build L1-L7 context; production includes project/account advisory preferences."""

    from clue_api.agent_platform_wiring import build_agent_context_assembler

    return build_agent_context_assembler(
        resolved_profile=resolved_profile,
        artifacts=artifacts,
        cards=cards,
        memory=memory if memory is not None else _NoMemoryContext(),
        memory_recipe="account-research-unit@1",
        requested_memory_types=((MemoryType.PREFERENCE,) if memory is not None else ()),
        policy=account_research_context_policy(),
        conn_factory=conn_factory,
    )
