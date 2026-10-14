"""C6.6 fresh-wake specialist composition and durable reference-only return."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid5

from langchain.agents.middleware.types import AgentMiddleware
from sqlalchemy import text

from clue_agents import (
    AgentConstitution,
    AgentContextAssembler,
    AgentExecutionAdapter,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentModelProvider,
    AgentProfileRegistry,
    AgentResourceMaterializer,
    AgentTurnOutcome,
    AgentTurnRequest,
    AgentWorkspaceLease,
    ContextLayer,
    DeepAgentTurnRuntime,
    DelegationRequest,
    DelegationResult,
    ResolvedAgentProfile,
    SpecialistTaskEnvelope,
    WorkspaceSeedFile,
)
from clue_api.agent_compaction import compaction_for
from clue_api.agent_execution_wiring import (
    AgentExecutionCrashHook,
    C5AgentExecutionAdapter,
)
from clue_api.agent_runtime_wiring import (
    AgentFinalizationAuthority,
    DurableDeepAgentTurnRunner,
    GovernedAgentToolFactory,
)
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_core import ExecutionId
from clue_db import ConnFactory, transaction
from clue_toolbelt import ToolRegistry

__all__ = [
    "DbSpecialistExecutionJournal",
    "FreshWakeSpecialistRunner",
    "SpecialistExecutionFactory",
    "SpecialistExecutionAdapter",
    "SpecialistSpendReader",
    "SpecialistWorkspaceProvider",
]

_CHILD_TURN_NAMESPACE = UUID("cd11ff72-aec1-5c46-a261-07d6c7b7f2fe")


async def _no_crash(
    point: str,
    *,
    execution_id: ExecutionId,
    node_key: str | None,
) -> None:
    del point, execution_id, node_key


class SpecialistWorkspaceProvider(Protocol):
    """Acquire the isolated one-execution child workspace.

    Implementations may create it or reopen the same validated root during crash recovery. They
    must never silently replace a prior child root with an empty workspace.
    """

    def acquire(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        execution_id: ExecutionId,
        resolved_profile: ResolvedAgentProfile,
    ) -> AgentWorkspaceLease: ...


class SpecialistExecutionAdapter(AgentExecutionAdapter, Protocol):
    """Execution port plus the one-time finalization authority binding."""

    def bind_finalization_authority(self, authority: object) -> None: ...


class SpecialistExecutionFactory(Protocol):
    """Build the child role's only governed C5 execution adapter."""

    def __call__(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        budget_limit_millicents: int,
    ) -> SpecialistExecutionAdapter: ...


class RecordOnlySpecialistExecutionFactory(SpecialistExecutionFactory, Protocol):
    """Opt-in trusted adapter; legacy factories cannot silently relax monetary policy."""

    def record_only(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        budget_limit_millicents: int,
    ) -> SpecialistExecutionAdapter: ...


@dataclass(frozen=True)
class SpecialistRuntimeBindings:
    """Trusted per-child extensions; never supplied by the model's delegation arguments."""

    backend: object | None = None
    middleware: tuple[AgentMiddleware[Any, Any, Any], ...] = ()
    before_work: Callable[[], Awaitable[None]] | None = None
    # Trusted run allowance, never a model-supplied delegation option. None retains the profile.
    max_model_rounds: int | None = None
    disable_runtime_timeout: bool = False


SpecialistBindingFactory = Callable[
    [AgentTurnRequest, ResolvedAgentProfile, AgentWorkspaceLease],
    Awaitable[SpecialistRuntimeBindings],
]


class SpecialistSpendReader(Protocol):
    """Return actual child spend in the delegation ledger's millicent unit."""

    async def spend_millicents(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
    ) -> int: ...


class DbSpecialistExecutionJournal:
    """Create the child execution identity before any turn row or model wake."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def begin(
        self,
        *,
        request: DelegationRequest,
        child_execution_id: ExecutionId,
        project_id: str,
    ) -> None:
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO execution (
                        id, workspace_id, project_id, parent_execution_id, started_by,
                        parameter_artifact_key, parameter_manifest_hash, pin_manifest_hash
                    )
                    VALUES (
                        :id, :workspace, :project, :parent, 'agent',
                        :task_key, :task_sha, :manifest_sha
                    )
                    ON CONFLICT (id) DO NOTHING RETURNING id
                    """
                ),
                {
                    "id": child_execution_id,
                    "workspace": request.task_artifact_ref.workspace_id,
                    "project": project_id,
                    "parent": request.parent_execution_id,
                    "task_key": request.task_artifact_ref.artifact_key,
                    "task_sha": request.task_artifact_ref.sha256,
                    "manifest_sha": request.resource_manifest_sha256,
                },
            )
            if inserted.first() is not None:
                return
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT workspace_id, project_id, parent_execution_id,
                                   parameter_artifact_key, parameter_manifest_hash,
                                   pin_manifest_hash
                            FROM execution WHERE id=:id
                            """
                        ),
                        {"id": child_execution_id},
                    )
                )
                .mappings()
                .one()
            )
            actual = (
                row["workspace_id"],
                row["project_id"],
                row["parent_execution_id"],
                row["parameter_artifact_key"],
                row["parameter_manifest_hash"],
                row["pin_manifest_hash"],
            )
            expected = (
                request.task_artifact_ref.workspace_id,
                project_id,
                request.parent_execution_id,
                request.task_artifact_ref.artifact_key,
                request.task_artifact_ref.sha256,
                request.resource_manifest_sha256,
            )
            if actual != expected:
                raise ValueError("child execution id already has different immutable inputs")


def _budget_limit(body: bytes) -> int:
    try:
        value = json.loads(body)
        limit = value["limit_millicents"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("child budget envelope is malformed") from exc
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("child budget limit must be a non-negative integer")
    return limit


def _budget_mode(body: bytes) -> Literal["enforced", "record_only"]:
    value = json.loads(body).get("mode", "enforced")
    if value not in ("enforced", "record_only"):
        raise ValueError("child budget mode is malformed")
    return cast(Literal["enforced", "record_only"], value)


def _context_is_fresh(context: object) -> bool:
    manifest = getattr(context, "manifest", None)
    layers = getattr(manifest, "layers", ())
    conversation = next(
        (item for item in layers if item.layer is ContextLayer.L6_CONVERSATION),
        None,
    )
    return (
        conversation is not None
        and conversation.source_refs == ()
        and conversation.materialized_paths == ()
        and conversation.token_count == 0
    )


class FreshWakeSpecialistRunner:
    """Run one research/draft/review child with no inherited chat or private mind-state."""

    def __init__(
        self,
        *,
        parent_request: AgentTurnRequest,
        profiles: AgentProfileRegistry,
        models: AgentModelProvider,
        turns: DbAgentTurnJournal,
        artifacts: DurableAgentArtifactStore,
        tools: ToolRegistry,
        contexts: AgentContextAssembler,
        workspaces: SpecialistWorkspaceProvider,
        execution_factory: SpecialistExecutionFactory,
        spend: SpecialistSpendReader,
        executions: DbSpecialistExecutionJournal | None = None,
        materializer: AgentResourceMaterializer | None = None,
        crash_hook: AgentExecutionCrashHook = _no_crash,
        conn_factory: ConnFactory = transaction,
        bindings: SpecialistBindingFactory | None = None,
    ) -> None:
        self._parent_request = parent_request
        self._bindings = bindings
        self._profiles = profiles
        self._models = models
        self._turns = turns
        self._artifacts = artifacts
        self._tools = tools
        self._contexts = contexts
        self._workspaces = workspaces
        self._execution_factory = execution_factory
        self._spend = spend
        self._executions = executions or DbSpecialistExecutionJournal(conn_factory=conn_factory)
        self._materializer = materializer or AgentResourceMaterializer()
        self._crash_hook = crash_hook
        self._conn_factory = conn_factory

    async def run(
        self,
        *,
        request: DelegationRequest,
        child_execution_id: ExecutionId,
        resolved_profile: ResolvedAgentProfile,
    ) -> DelegationResult:
        parent = self._parent_request.constitution
        if request.parent_execution_id != parent.execution_id:
            raise ValueError("delegation belongs to another parent execution")
        if resolved_profile != self._profiles.resolve_delegation(
            parent=self._profiles.resolve(parent.role),
            child_role=request.subagent_role,
            current_depth=request.depth - 1,
        ):
            raise ValueError("delegation resolved profile changed before fresh wake")
        if request.resource_manifest_sha256 != (
            resolved_profile.resource_manifest.aggregate_sha256
        ):
            raise ValueError("child resource manifest differs from the resolved profile")

        task = SpecialistTaskEnvelope.model_validate_json(
            await self._artifacts.read(request.task_artifact_ref)
        )
        if task.role is not request.subagent_role:
            raise ValueError("specialist task role differs from delegation authority")
        if task.domain_refs != request.domain_refs:
            raise ValueError("specialist task domain refs differ from durable grants")
        if tuple(item.materialized_path for item in task.file_grants) != request.granted_paths:
            raise ValueError("specialist task file grants differ from durable path grants")
        workspace_id = parent.workspace_id
        if any(item.artifact_ref.workspace_id != workspace_id for item in task.file_grants):
            raise ValueError("specialist task file grant crosses the parent workspace")

        await self._executions.begin(
            request=request,
            child_execution_id=child_execution_id,
            project_id=parent.project_id,
        )
        lease = self._workspaces.acquire(
            workspace_id=workspace_id,
            project_id=parent.project_id,
            thread_id=f"delegation-{request.delegation_id}",
            execution_id=child_execution_id,
            resolved_profile=resolved_profile,
        )
        try:
            child_constitution = AgentConstitution(
                workspace_id=workspace_id,
                project_id=parent.project_id,
                execution_id=child_execution_id,
                actor_id=parent.actor_id,
                role=request.subagent_role,
                brand_id=parent.brand_id,
                product_id=parent.product_id,
                client_entity_id=parent.client_entity_id,
                workspace_root_id=lease.identity.workspace_root_id,
                # The child inherits the parent's project card verbatim — one project, one compiled
                # description of it. Only spend authority is re-scoped for the child.
                project_card_ref=parent.project_card_ref,
                budget_envelope_ref=request.child_budget_envelope_ref,
                profile_ref=resolved_profile.profile_ref,
                resource_manifest_ref=request.resource_manifest_ref,
                resource_manifest_sha256=request.resource_manifest_sha256,
                focus_refs=request.domain_refs,
            )
            child_request = AgentTurnRequest(
                turn_id=uuid5(_CHILD_TURN_NAMESPACE, str(request.delegation_id)),
                thread_id=f"delegation-{request.delegation_id}",
                constitution=child_constitution,
                user_message_artifact_ref=request.task_artifact_ref,
                focus_refs=request.domain_refs,
                requested_at=self._parent_request.requested_at,
            )
            await self._turns.create(request=child_request, profile=resolved_profile.profile)
            bindings = (
                await self._bindings(child_request, resolved_profile, lease)
                if self._bindings is not None
                else SpecialistRuntimeBindings()
            )
            if bindings.before_work is not None:
                await bindings.before_work()
            prior = await self._turns.load_committed_outcome(
                turn_id=child_request.turn_id, workspace_id=workspace_id
            )
            if prior is not None:
                return await self._result(request, child_execution_id, prior)
            context = await self._contexts.assemble(
                request=child_request,
                profile=resolved_profile.profile,
                history=(),
            )
            if not _context_is_fresh(context):
                raise ValueError(
                    "fresh-wake specialist context contains hidden conversation history"
                )

            grant_seeds: list[WorkspaceSeedFile] = []
            for grant in task.file_grants:
                body = await self._artifacts.read(grant.artifact_ref)
                grant_seeds.append(
                    WorkspaceSeedFile(
                        path=grant.materialized_path,
                        content=body,
                        sha256=grant.artifact_ref.sha256,
                        media_type=grant.artifact_ref.media_type,
                    )
                )
            seed_paths = {
                *(item.path for item in context.materializations),
                *(item.path for item in grant_seeds),
            }
            if len(seed_paths) != len(context.materializations) + len(grant_seeds):
                raise ValueError("context assembler collided with a delegated canonical file path")
            if not lease.resources_frozen:
                self._materializer.materialize(
                    lease=lease,
                    snapshot=resolved_profile.resource_snapshot,
                    seed_files=(
                        *(
                            WorkspaceSeedFile(
                                path=item.path,
                                content=item.data,
                                sha256=item.sha256,
                                media_type=item.media_type,
                            )
                            for item in context.materializations
                        ),
                        *grant_seeds,
                    ),
                )

            budget_body = await self._artifacts.read(request.child_budget_envelope_ref)
            budget_limit = _budget_limit(budget_body)
            budget_mode = _budget_mode(budget_body)
            factory = self._execution_factory
            if budget_mode == "record_only":
                if not callable(getattr(factory, "record_only", None)):
                    raise ValueError("child execution does not support record-only budgeting")
                factory = cast(RecordOnlySpecialistExecutionFactory, factory).record_only
            execution = factory(
                request=child_request,
                resolved_profile=resolved_profile,
                budget_limit_millicents=budget_limit,
            )
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
                request=child_request,
                resolved_profile=resolved_profile,
                registry=self._tools,
                execution=cast(C5AgentExecutionAdapter, execution),
                lease=lease,
                artifacts=self._artifacts,
                required_output_path=task.required_output_path,
                before_work=bindings.before_work,
            ).build()
            outcome = await DurableDeepAgentTurnRunner(
                # A child execution exists per delegation, so saved state on it is always this
                # delegation's own half-run turn (spec 2026-10-14 §3.3).
                runtime=DeepAgentTurnRuntime(
                    resume_saved_turn=True,
                    compaction_for=compaction_for,
                    models=self._models,
                    execution=execution,
                    max_runtime_s=(
                        None
                        if bindings.disable_runtime_timeout
                        else resolved_profile.profile.turn_timeout_s
                    ),
                    max_rounds=(
                        bindings.max_model_rounds
                        if bindings.max_model_rounds is not None
                        else resolved_profile.profile.max_model_rounds
                    ),
                    middleware=bindings.middleware,
                ),
                turns=self._turns,
                artifacts=self._artifacts,
                before_work=bindings.before_work,
                conn_factory=self._conn_factory,
            ).run(
                request=child_request,
                resolved_profile=resolved_profile,
                context=context,
                lease=lease,
                tools=governed_tools,
                backend=bindings.backend,
            )
            return await self._result(request, child_execution_id, outcome)
        finally:
            lease.release()

    async def _result(
        self, request: DelegationRequest, child_execution_id: ExecutionId, outcome: AgentTurnOutcome
    ) -> DelegationResult:
        workspace_id = request.task_artifact_ref.workspace_id
        budget_body = await self._artifacts.read(request.child_budget_envelope_ref)
        budget_limit, budget_mode = _budget_limit(budget_body), _budget_mode(budget_body)
        if outcome.status is AgentExecutionStatus.FAILED or outcome.finalization_ref is None:
            raise RuntimeError(outcome.failure_code or "specialist_turn_failed")
        envelope = AgentFinalizeEnvelope.model_validate_json(
            await self._artifacts.read(outcome.finalization_ref)
        )
        if envelope.execution_id != child_execution_id:
            raise ValueError("child finalization belongs to another execution")
        spend = await self._spend.spend_millicents(
            execution_id=child_execution_id,
            workspace_id=workspace_id,
        )
        if spend < 0 or (budget_mode == "enforced" and spend > budget_limit):
            raise ValueError("child reported spend outside its durable budget envelope")
        result_status: Literal["completed", "awaiting_input", "blocked"]
        if outcome.status is AgentExecutionStatus.COMPLETED:
            result_status = "completed"
        elif outcome.status is AgentExecutionStatus.AWAITING_INPUT:
            result_status = "awaiting_input"
        else:
            result_status = "blocked"
        return DelegationResult(
            delegation_id=request.delegation_id,
            parent_execution_id=request.parent_execution_id,
            child_execution_id=child_execution_id,
            status=result_status,
            output_refs=envelope.output_refs,
            domain_refs=(*envelope.domain_refs, *envelope.open_gate_refs),
            finalization_ref=outcome.finalization_ref,
            spend_millicents=spend,
            completed_at=envelope.finalized_at,
        )
