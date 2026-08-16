"""C5.6 Recipe #1 cutover, waits, routing, and historical-view contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.execution_tools import ExecutionControlServices, register_execution_control_tools
from clue_api.execution_wiring import (
    ExecutionRunEventWriter,
    StorageExecutionParameterStore,
    StorageParameterArtifactStore,
    build_tool_invoker,
)
from clue_api.project_execution_router import (
    Recipe1ProjectExecutionRouter,
    recipe1_workspace_eligible,
)
from clue_api.recipe_wiring import (
    build_recipe_lifecycle,
    build_recipe_pin_registry,
    load_system_recipe_definitions,
    seed_system_recipes,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_core import (
    DiscoveryBatchId,
    DiscoveryExternalWait,
    DiscoveryOperationId,
    DiscoverySealBlocker,
    DiscoveryWakeReason,
    EntityId,
    ExecutionId,
    ICPCreatedFrom,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    ProductContextVersionId,
    ProjectPhase,
    ReadinessDecisionId,
)
from clue_db import ConnFactory
from clue_execution import (
    PROJECT_PHASE_EXTERNAL_WAIT_REASON,
    CompatibilityLoader,
    DbExecutionJournal,
    DbExecutionRunViewReader,
    DbExecutionStarter,
    DbRecipeReader,
    DbRecipeRepository,
    ExecutionStatus,
    RecipeExecutor,
    get_cursor,
)
from clue_fleet import WorkId, WorkQueue, acquire_work_lease
from clue_projections import run_manifest
from clue_research.durable import (
    PHASE_SEQUENCE,
    DbIdempotencyStore,
    DbProjectRunStore,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunStatus,
)
from clue_research.icp import create_icp_spec
from clue_toolbelt import DbIdempotencyStore as ToolIdempotencyStore
from tests._workspace import seed_project, seed_workspace
from tests.db.conftest import run_async
from tests.execution.outcome_fingerprint import build_outcome_fingerprint
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, Any]]:
        return
        yield


class _Phase:
    def __init__(self, phase: ProjectPhase, *, pause: bool = False) -> None:
        self.phase = phase
        self.pause = pause
        self.calls = 0

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        self.calls += 1
        decision = ctx.params.get("checkpoint_decision")
        approved = self.pause and isinstance(decision, dict) and decision.get("action") == "approve"
        return PhaseResult(
            status=(PhaseStatus.PAUSED if self.pause and not approved else PhaseStatus.COMPLETED),
            payload=(
                {
                    "gate": self.phase.value,
                    "checkpoint_status": "resumed",
                    "decision_action": "approve",
                }
                if approved
                else ({"gate": self.phase.value} if self.pause else {})
            ),
        )


class _ExternalWaitPhase:
    phase = ProjectPhase.DISCOVERY

    def __init__(self) -> None:
        self.calls = 0
        self.batch_id = DiscoveryBatchId(uuid4())
        self.operation_id = DiscoveryOperationId(uuid4())

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        del ctx
        self.calls += 1
        if self.calls == 1:
            wait = DiscoveryExternalWait(
                discovery_batch_id=self.batch_id,
                pending_operation_ids=(self.operation_id,),
                next_poll_at=datetime.now(UTC) + timedelta(minutes=5),
                wake_reason=DiscoveryWakeReason.SCHEDULED_POLL,
                blockers=(DiscoverySealBlocker.OPERATION_TERMINALITY,),
            )
            return PhaseResult(
                status=PhaseStatus.WAITING_EXTERNAL,
                payload=wait.model_dump(mode="json"),
            )
        return PhaseResult(status=PhaseStatus.COMPLETED, payload={})


class _Queue:
    async def enqueue(self, **_kwargs: object) -> bool:
        return True


def _factory(conn: AsyncConnection) -> ConnFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        nested = await conn.begin_nested()
        try:
            yield conn
        except BaseException:
            await nested.rollback()
            raise
        else:
            await nested.commit()

    return factory


def test_recipe1_routing_is_fail_closed_and_deterministic() -> None:
    off = Settings(
        _env_file=None,
        recipe1_routing_enabled=False,
        recipe1_workspace_allowlist=("ws",),
        recipe1_canary_percent=100,
    )
    assert not recipe1_workspace_eligible(off, "ws")
    allow = Settings(
        _env_file=None,
        recipe1_routing_enabled=True,
        recipe1_workspace_allowlist=("ws",),
    )
    assert recipe1_workspace_eligible(allow, "ws")
    assert not recipe1_workspace_eligible(allow, "other")
    percentage = Settings(
        _env_file=None,
        recipe1_routing_enabled=True,
        recipe1_canary_percent=37,
    )
    assert recipe1_workspace_eligible(percentage, "stable") == recipe1_workspace_eligible(
        percentage, "stable"
    )


def test_recipe1_phase_spine_waits_and_resumes_without_reexecuting_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-recipe1-cutover")
            project = await seed_project(conn, workspace_id)
            second_workspace_id = await seed_workspace(conn, "ws-recipe1-repeat")
            second_project = await seed_project(conn, second_workspace_id)
            legacy_workspace_id = await seed_workspace(conn, "ws-recipe1-legacy")
            legacy_project = await seed_project(conn, legacy_workspace_id)
            await create_icp_spec(
                conn,
                workspace_id=workspace_id,
                icp_key="golden",
                created_from=ICPCreatedFrom.SYNTHESIS,
                activate=True,
            )
            await create_icp_spec(
                conn,
                workspace_id=second_workspace_id,
                icp_key="golden",
                created_from=ICPCreatedFrom.SYNTHESIS,
                activate=True,
            )
            await create_icp_spec(
                conn,
                workspace_id=legacy_workspace_id,
                icp_key="golden",
                created_from=ICPCreatedFrom.SYNTHESIS,
                activate=True,
            )
            factory = _factory(conn)
            phases = PhaseHandlerRegistry()
            handlers = {
                phase: (
                    _ExternalWaitPhase()
                    if phase is ProjectPhase.DISCOVERY
                    else _Phase(phase, pause=phase is ProjectPhase.TIER_CHECKPOINT)
                )
                for phase in PHASE_SEQUENCE
            }
            for handler in handlers.values():
                phases.register(handler)
            machine = ProjectRun(
                store=DbProjectRunStore(conn_factory=factory),
                registry=phases,
                ledger=DbIdempotencyStore(conn_factory=factory),
            )
            run_id = await machine.start(
                project_id=project.project_id,
                workspace_id=workspace_id,
                icp_key="golden",
                icp_version=1,
            )

            settings = Settings(
                _env_file=None,
                recipe1_routing_enabled=True,
                recipe1_workspace_allowlist=(workspace_id, second_workspace_id),
            )
            registry = build_toolbelt(
                storage=None,
                settings=settings,
                run_machine=machine,
                conn_factory=factory,
            )
            pin_registry = build_recipe_pin_registry(
                tool_registry=registry,
                conn_factory=factory,
            )
            compatibility = CompatibilityLoader(pin_registry)
            repository = DbRecipeRepository(conn_factory=factory)
            storage = _MemoryStorage()
            parameters = StorageExecutionParameterStore(
                StorageParameterArtifactStore(storage=storage, conn_factory=factory)
            )
            journal = DbExecutionJournal(transport=ExecutionRunEventWriter())
            reader = DbRecipeReader(conn_factory=factory)
            starter = DbExecutionStarter(
                conn_factory=factory,
                recipes=reader,
                compatibility=compatibility,
                journal=journal,
            )
            invoker = build_tool_invoker(
                registry=registry,
                idempotency_store=ToolIdempotencyStore(conn_factory=factory),
                storage=storage,
                settings=settings,
                conn_factory=factory,
            )
            executor = RecipeExecutor(
                conn_factory=factory,
                recipes=reader,
                compatibility=compatibility,
                journal=journal,
                parameters=parameters,
                tool_invoker=invoker,
            )
            queue = cast(WorkQueue, _Queue())
            register_execution_control_tools(
                ExecutionControlServices(
                    starter=starter,
                    executor=executor,
                    parameters=parameters,
                    recipes=repository,
                    run_machine=machine,
                    queue=queue,
                    conn_factory=factory,
                    registry=registry,
                )
            )
            await seed_system_recipes(
                repository=repository,
                lifecycle=build_recipe_lifecycle(
                    tool_registry=registry,
                    conn_factory=factory,
                    pin_registry=pin_registry,
                ),
                definitions=tuple(
                    definition
                    for definition in load_system_recipe_definitions()
                    if definition.recipe_key == "recipe1-classic"
                ),
            )
            router = Recipe1ProjectExecutionRouter(
                settings=settings,
                recipes=reader,
                starter=starter,
                executor=executor,
                parameters=parameters,
                compatibility=compatibility,
                queue=queue,
                conn_factory=factory,
            )
            forced_router = Recipe1ProjectExecutionRouter(
                settings=Settings(_env_file=None, recipe1_routing_enabled=False),
                recipes=reader,
                starter=starter,
                executor=executor,
                parameters=parameters,
                compatibility=compatibility,
                queue=queue,
                conn_factory=factory,
            )
            invalid_confirmed_run = await machine.start(
                project_id=project.project_id,
                workspace_id=workspace_id,
                icp_key="golden",
                icp_version=1,
            )
            await conn.execute(
                text("UPDATE project_run SET phase = 'discovery' WHERE id = :run_id"),
                {"run_id": invalid_confirmed_run},
            )
            with pytest.raises(ValueError, match="complete immutable Stage-0 lineage"):
                await forced_router.attach_confirmed_discovery(
                    invalid_confirmed_run,
                    actor="human",
                )

            # The confirmed handoff bypasses only the legacy workspace canary. Probe that
            # selection rule with a complete immutable row; the common concrete attach path is
            # exercised immediately below through the enabled router.
            confirmed_probe = (await forced_router._load_run(run_id)).model_copy(
                update={
                    "phase": ProjectPhase.DISCOVERY,
                    "client_entity_id": EntityId(uuid4()),
                    "client_kb_version": 1,
                    "product_id": "product-confirmed",
                    "product_context_version_id": ProductContextVersionId(uuid4()),
                    "readiness_decision_id": ReadinessDecisionId(uuid4()),
                }
            )
            expected_probe_execution = ExecutionId(uuid4())
            attach_probe = AsyncMock(return_value=expected_probe_execution)
            monkeypatch.setattr(
                forced_router,
                "_load_run",
                AsyncMock(return_value=confirmed_probe),
            )
            monkeypatch.setattr(forced_router, "_attach", attach_probe)
            assert await forced_router.attach_if_eligible(run_id, actor="human") is None
            assert (
                await forced_router.attach_confirmed_discovery(run_id, actor="human")
                == expected_probe_execution
            )
            attach_probe.assert_awaited_once_with(
                confirmed_probe,
                actor="human",
                parent_execution_id=None,
            )

            original_parent_execution_id = ExecutionId(uuid4())
            retry_parent_execution_id = ExecutionId(uuid4())
            for parent_id in (original_parent_execution_id, retry_parent_execution_id):
                await conn.execute(
                    text(
                        "INSERT INTO execution "
                        "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                        "pin_manifest_hash) VALUES "
                        "(:id, :workspace_id, :project_id, 'agent', :hash, :hash)"
                    ),
                    {
                        "id": parent_id,
                        "workspace_id": workspace_id,
                        "project_id": project.project_id,
                        "hash": "0" * 64,
                    },
                )
            execution_id = await router.attach_if_eligible(
                run_id,
                actor="human",
                parent_execution_id=original_parent_execution_id,
            )
            assert execution_id is not None
            replayed_execution_id = await router.attach_if_eligible(
                run_id,
                actor="human",
                parent_execution_id=retry_parent_execution_id,
            )
            assert replayed_execution_id == execution_id
            assert (
                await conn.execute(
                    text("SELECT parent_execution_id FROM execution WHERE id = :execution_id"),
                    {"execution_id": execution_id},
                )
            ).scalar_one() == original_parent_execution_id
            lease = await acquire_work_lease(
                conn,
                work_id=WorkId(execution_id),
                worker_id="worker",
                ttl=timedelta(seconds=60),
            )
            assert lease is not None

            first = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=lease.generation,
            )
            assert first.status is ExecutionStatus.PAUSED
            waiting = await machine.status(run_id)
            assert waiting.phase is ProjectPhase.DISCOVERY
            assert waiting.status is ProjectRunStatus.ACTIVE
            assert handlers[ProjectPhase.DISCOVERY].calls == 1
            assert handlers[ProjectPhase.TIER_CHECKPOINT].calls == 0
            assert await executor.resume_if_paused_for(
                execution_id=execution_id,
                actor="system",
                reason_code=PROJECT_PHASE_EXTERNAL_WAIT_REASON,
            )
            second = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=lease.generation,
            )
            assert second.status is ExecutionStatus.PAUSED
            paused = await machine.status(run_id)
            assert paused.phase is ProjectPhase.TIER_CHECKPOINT
            assert paused.status is ProjectRunStatus.PAUSED
            assert handlers[ProjectPhase.DISCOVERY].calls == 2
            assert handlers[ProjectPhase.TIER_CHECKPOINT].calls == 1

            await machine.submit_checkpoint(run_id, decision={"action": "approve"})
            assert await router.resume_owned(run_id, actor="human")
            third = await executor.execute(
                execution_id,
                worker_id="worker",
                lease_generation=lease.generation,
            )
            assert third.status is ExecutionStatus.COMPLETED
            completed = await machine.status(run_id)
            assert completed.status is ProjectRunStatus.COMPLETED
            assert handlers[ProjectPhase.TIER_CHECKPOINT].calls == 2
            assert third.completed_node_keys == tuple(
                sorted(phase.value for phase in PHASE_SEQUENCE)
            )

            view_reader = DbExecutionRunViewReader(
                conn_factory=factory,
                compatibility=compatibility,
            )
            view = await view_reader.read_project_run(
                workspace_id=workspace_id,
                project_run_id=run_id,
            )
            assert view is not None
            assert len(view.nodes) == len(PHASE_SEQUENCE)
            assert len(view.edges) == len(PHASE_SEQUENCE) - 1
            assert all(
                edge.from_node_id in {node.node_id for node in view.nodes}
                and edge.to_node_id in {node.node_id for node in view.nodes}
                for edge in view.edges
            )
            tier_events = [
                event.event_type.value
                for event in view.events
                if event.node_id
                == next(node.node_id for node in view.nodes if node.node_key == "tier_checkpoint")
            ]
            assert tier_events.count("node.abandoned") == 1
            assert tier_events.count("node.completed") == 1
            discovery_events = [
                event.event_type.value
                for event in view.events
                if event.node_id
                == next(node.node_id for node in view.nodes if node.node_key == "discovery")
            ]
            assert discovery_events.count("node.abandoned") == 1
            assert discovery_events.count("node.completed") == 1

            owner_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM project_run_execution_owner "
                            "WHERE project_run_id = :run_id"
                        ),
                        {"run_id": run_id},
                    )
                ).scalar_one()
            )
            assert owner_count == 1
            manifest = await run_manifest(
                conn_factory=factory,
                project_run_id=run_id,
                workspace_id=workspace_id,
            )
            assert manifest is not None
            assert manifest.execution_id == execution_id
            assert manifest.recipe_revision_id is not None
            assert {node.node_key for node in manifest.nodes} >= {
                f"phase:{phase.value}" for phase in PHASE_SEQUENCE
            }
            manifest_keys = {node.node_key for node in manifest.nodes}
            assert all(
                dependency in manifest_keys
                for node in manifest.nodes
                for dependency in node.depends_on
            )
            assert {
                "project",
                "project_run",
                "icp",
                "field_registry",
                "source_registry",
                "supervisor_policy",
            } <= {pin.kind for pin in manifest.pins}
            recipe_library = await view_reader.list_recipe_library(
                workspace_id=workspace_id,
                project_id=project.project_id,
            )
            recipe1_view = next(
                item
                for item in recipe_library
                if item.recipe_key == "recipe1-classic" and item.version == 2
            )
            assert recipe1_view.lifecycle_status == "promoted"
            assert recipe1_view.migration_state == "executable"
            assert recipe1_view.compatibility_status == "compatible"
            supervision = await view_reader.read_supervision(
                workspace_id=workspace_id,
                execution_id=execution_id,
            )
            assert supervision is not None
            assert supervision.observations == ()
            assert supervision.diagnoses == ()
            assert supervision.controls == ()
            assert supervision.effective_controls == ()

            second_recipe_run = await machine.start(
                project_id=second_project.project_id,
                workspace_id=second_workspace_id,
                icp_key="golden",
                icp_version=1,
            )
            second_execution = await router.attach_if_eligible(second_recipe_run, actor="human")
            assert second_execution is not None
            await machine.pause(second_recipe_run)
            assert await router.pause_owned(
                second_recipe_run,
                actor="human",
                reason_code="test_user_pause",
            )
            paused_cursor = await get_cursor(conn, second_execution)
            assert paused_cursor.status is ExecutionStatus.PAUSED
            await machine.resume(second_recipe_run)
            assert await router.resume_owned(second_recipe_run, actor="human")
            resumed_cursor = await get_cursor(conn, second_execution)
            assert resumed_cursor.status is ExecutionStatus.RUNNING
            second_lease = await acquire_work_lease(
                conn,
                work_id=WorkId(second_execution),
                worker_id="worker-two",
                ttl=timedelta(seconds=60),
            )
            assert second_lease is not None
            await executor.execute(
                second_execution,
                worker_id="worker-two",
                lease_generation=second_lease.generation,
            )
            await machine.submit_checkpoint(
                second_recipe_run,
                decision={"action": "approve"},
            )
            await router.resume_owned(second_recipe_run, actor="human")
            second_result = await executor.execute(
                second_execution,
                worker_id="worker-two",
                lease_generation=second_lease.generation,
            )
            assert second_result.status is ExecutionStatus.COMPLETED

            legacy_registry = PhaseHandlerRegistry()
            for phase in PHASE_SEQUENCE:
                legacy_registry.register(_Phase(phase, pause=phase is ProjectPhase.TIER_CHECKPOINT))
            legacy_machine = ProjectRun(
                store=DbProjectRunStore(conn_factory=factory),
                registry=legacy_registry,
                ledger=DbIdempotencyStore(conn_factory=factory),
            )
            legacy_run = await legacy_machine.start(
                project_id=legacy_project.project_id,
                workspace_id=legacy_workspace_id,
                icp_key="golden",
                icp_version=1,
            )
            await legacy_machine.run_to_completion(legacy_run)
            await legacy_machine.submit_checkpoint(
                legacy_run,
                decision={"action": "approve"},
            )
            legacy_result = await legacy_machine.run_to_completion(legacy_run)
            assert legacy_result.status is ProjectRunStatus.COMPLETED

            first_fingerprint = await build_outcome_fingerprint(
                conn,
                workspace_id=workspace_id,
                project_run_id=run_id,
            )
            second_fingerprint = await build_outcome_fingerprint(
                conn,
                workspace_id=second_workspace_id,
                project_run_id=second_recipe_run,
            )
            legacy_fingerprint = await build_outcome_fingerprint(
                conn,
                workspace_id=legacy_workspace_id,
                project_run_id=legacy_run,
            )
            assert first_fingerprint == second_fingerprint == legacy_fingerprint

    run_async(scenario())
