"""C5.6 new-run routing between the legacy driver and durable Recipe #1."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol, cast

from pydantic import JsonValue
from sqlalchemy import text

from clue_config import Settings
from clue_core import (
    ExecutionId,
    ProjectPhase,
    ProjectRunId,
    decode_jsonb,
    operation_id_from_key,
)
from clue_db import ConnFactory, transaction
from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    DbExecutionStarter,
    DbRecipeReader,
    ExecutionParameterStore,
    ExecutionStatus,
    PinRequest,
    RecipeExecutor,
    RecipeScopeType,
    enqueue_recipe_execution,
)
from clue_fleet import WorkQueue
from clue_research.durable import ProjectRunRow, get_project_run

RECIPE1_KEY = "recipe1-classic"
RECIPE1_VERSION = 2


class ProjectExecutionRouter(Protocol):
    async def attach_confirmed_discovery(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId: ...

    async def attach_if_eligible(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId | None: ...

    async def pause_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        reason_code: str,
    ) -> bool: ...

    async def resume_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
    ) -> bool: ...


class DeferredProjectExecutionRouter:
    """Break the boot-time cycle: tools exist before the executor they route into."""

    def __init__(self) -> None:
        self._target: ProjectExecutionRouter | None = None

    def bind(self, target: ProjectExecutionRouter) -> None:
        if self._target is not None:
            raise RuntimeError("project execution router is already bound")
        self._target = target

    def _require(self) -> ProjectExecutionRouter:
        if self._target is None:
            raise RuntimeError("project execution router has not been bound")
        return self._target

    async def attach_confirmed_discovery(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId:
        return await self._require().attach_confirmed_discovery(
            project_run_id,
            actor=actor,
            parent_execution_id=parent_execution_id,
        )

    async def attach_if_eligible(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId | None:
        return await self._require().attach_if_eligible(
            project_run_id,
            actor=actor,
            parent_execution_id=parent_execution_id,
        )

    async def pause_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        reason_code: str,
    ) -> bool:
        return await self._require().pause_owned(
            project_run_id,
            actor=actor,
            reason_code=reason_code,
        )

    async def resume_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
    ) -> bool:
        return await self._require().resume_owned(project_run_id, actor=actor)


def recipe1_workspace_eligible(settings: Settings, workspace_id: str) -> bool:
    """Fail-closed deterministic new-run canary selection."""
    if not settings.recipe1_routing_enabled:
        return False
    if workspace_id in settings.recipe1_workspace_allowlist:
        return True
    if settings.recipe1_canary_percent == 0:
        return False
    bucket = int.from_bytes(hashlib.sha256(workspace_id.encode()).digest()[:8], "big") % 100
    return bucket < settings.recipe1_canary_percent


class Recipe1ProjectExecutionRouter:
    def __init__(
        self,
        *,
        settings: Settings,
        recipes: DbRecipeReader,
        starter: DbExecutionStarter,
        executor: RecipeExecutor,
        parameters: ExecutionParameterStore,
        compatibility: CompatibilityLoader,
        queue: WorkQueue,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._recipes = recipes
        self._starter = starter
        self._executor = executor
        self._parameters = parameters
        self._compatibility = compatibility
        self._queue = queue
        self._conn_factory = conn_factory

    async def _load_run(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, project_run_id)
        if run is None:
            raise ValueError("project run does not exist")
        return run

    async def _exact_pin(
        self,
        *,
        kind: str,
        key: str,
        context: CompatibilityContext,
        version: str | None = None,
    ) -> PinRequest:
        if version is not None:
            report = await self._compatibility.resolve_requirements(
                (PinRequest(kind=kind, key=key, version=version),),
                context=context,
            )
            if not report.compatible or len(report.pins) != 1:
                raise ValueError(f"required Recipe #1 pin {kind}:{key}@{version} is unavailable")
            pin = report.pins[0]
            return PinRequest(
                kind=kind,
                key=key,
                version=pin.version,
                digest=pin.digest,
            )
        observed = await self._compatibility.observe_current(
            kind=kind,
            key=key,
            context=context,
        )
        if observed is None or observed.status != "active":
            raise ValueError(f"required Recipe #1 pin {kind}:{key} is unavailable")
        return PinRequest(
            kind=kind,
            key=key,
            version=observed.version,
            digest=observed.digest,
        )

    async def _requirements(self, run: ProjectRunRow) -> tuple[PinRequest, ...]:
        context = CompatibilityContext(
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            attributes={"icp_key": run.icp_key},
        )
        identities: list[tuple[str, str]] = [
            ("project", run.project_id),
            ("project_run", str(run.id)),
            ("icp", run.icp_key),
            ("supervisor_policy", run.icp_key),
            ("field_registry", "__all_active__"),
            ("source_registry", "__all_active__"),
        ]
        lineage = (
            run.client_entity_id,
            run.client_kb_version,
            run.product_id,
            run.product_context_version_id,
            run.readiness_decision_id,
        )
        has_lineage = any(value is not None for value in lineage)
        complete_lineage = all(value is not None for value in lineage)
        if has_lineage and not complete_lineage:
            raise ValueError("Recipe #1 cannot pin a partial immutable Stage-0 lineage")
        if run.phase is ProjectPhase.DISCOVERY and not complete_lineage:
            raise ValueError(
                "a discovery-entry Recipe #1 run requires complete immutable Stage-0 lineage"
            )
        # Lineage, rather than the mutable current phase, identifies the confirmed Stage-0 entry.
        # This keeps the pin manifest stable if the start tool replays after the run has advanced.
        if complete_lineage:
            async with self._conn_factory() as conn:
                receipt_row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT freshness_snapshot FROM product_context_version "
                                "WHERE id = :id AND workspace_id = :workspace_id"
                            ),
                            {
                                "id": run.product_context_version_id,
                                "workspace_id": run.workspace_id,
                            },
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if receipt_row is None:
                raise ValueError("Recipe #1 cannot load the pinned Stage-0 context receipt")
            receipt = decode_jsonb(receipt_row["freshness_snapshot"])
            inputs = receipt.get("inputs") if isinstance(receipt, dict) else None
            if not isinstance(inputs, list):
                raise ValueError("Recipe #1 Stage-0 context receipt is malformed")
            inputs_by_kind = {
                item.get("kind"): item
                for item in inputs
                if isinstance(item, dict) and isinstance(item.get("kind"), str)
            }
            client_kb = inputs_by_kind.get("client_kb")
            product_kb = inputs_by_kind.get("product_kb")
            expected_client_key = f"{run.client_entity_id}|-"
            expected_product_key = f"{run.client_entity_id}|{run.product_id}"
            client_kb_revision = client_kb.get("revision") if isinstance(client_kb, dict) else None
            product_kb_revision = (
                product_kb.get("revision") if isinstance(product_kb, dict) else None
            )
            if (
                not isinstance(client_kb, dict)
                or client_kb.get("subject_ref") != f"client_kb:{expected_client_key}"
                or client_kb_revision != str(run.client_kb_version)
                or not isinstance(product_kb, dict)
                or product_kb.get("subject_ref") != f"product_kb:{expected_product_key}"
                or not isinstance(product_kb_revision, str)
            ):
                raise ValueError("Recipe #1 Stage-0 knowledge pins do not match the confirmed run")
            identities.extend(
                (
                    ("product_context", str(run.product_context_version_id)),
                    ("readiness_decision", str(run.readiness_decision_id)),
                )
            )
        pins = [
            await self._exact_pin(kind=kind, key=key, context=context) for kind, key in identities
        ]
        if complete_lineage:
            pins.extend(
                (
                    await self._exact_pin(
                        kind="client_kb",
                        key=expected_client_key,
                        version=str(client_kb_revision),
                        context=context,
                    ),
                    await self._exact_pin(
                        kind="product_kb",
                        key=expected_product_key,
                        version=str(product_kb_revision),
                        context=context,
                    ),
                )
            )
        supervisor = next(item for item in pins if item.kind == "supervisor_policy")
        if supervisor.version != self._settings.recipe1_supervisor_policy_version:
            raise ValueError(
                "configured Recipe #1 supervisor policy version does not match the active policy"
            )
        return tuple(pins)

    @staticmethod
    def _pre_satisfied(run: ProjectRunRow) -> dict[str, dict[str, JsonValue]]:
        lineage_values = (
            run.client_entity_id,
            run.client_kb_version,
            run.product_id,
            run.product_context_version_id,
            run.readiness_decision_id,
        )
        if not all(value is not None for value in lineage_values):
            return {}
        lineage = cast(
            dict[str, JsonValue],
            {
                "pre_satisfied": True,
                "project_run_id": str(run.id),
                "phase": ProjectPhase.DISCOVERY.value,
                "client_entity_id": str(run.client_entity_id),
                "client_kb_version": run.client_kb_version,
                "product_id": run.product_id,
                "product_context_version_id": str(run.product_context_version_id),
                "readiness_decision_id": str(run.readiness_decision_id),
            },
        )
        return {
            ProjectPhase.REVERSE_PROFILING.value: dict(lineage),
            ProjectPhase.ICP_CONFIRMED.value: dict(lineage),
        }

    async def _existing_execution_parent(
        self,
        execution_id: ExecutionId,
    ) -> tuple[bool, ExecutionId | None]:
        """Return the immutable parent already recorded for an exact execution replay."""

        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT parent_execution_id FROM execution WHERE id = :execution_id"),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return False, None
        parent = row["parent_execution_id"]
        return True, None if parent is None else ExecutionId(parent)

    async def _attach(
        self,
        run: ProjectRunRow,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId:
        revision = await self._recipes.get_by_identity(
            scope_type=RecipeScopeType.SYSTEM,
            workspace_id=None,
            recipe_key=RECIPE1_KEY,
            version=RECIPE1_VERSION,
        )
        if revision is None:
            raise RuntimeError("promoted Recipe #1 revision is not installed")
        requirements = await self._requirements(run)
        parameters: dict[str, JsonValue] = {"project_run_id": str(run.id)}
        artifact_key, manifest_hash = await self._parameters.snapshot(
            workspace_id=run.workspace_id,
            parameters=parameters,
        )
        execution_id = ExecutionId(
            operation_id_from_key(str(run.id), f"{RECIPE1_KEY}@{RECIPE1_VERSION}")
        )
        replaying, immutable_parent = await self._existing_execution_parent(execution_id)
        start = await self._starter.start(
            workspace_id=run.workspace_id,
            recipe_revision_id=revision.recipe_revision_id,
            parameters=parameters,
            parameter_artifact_key=artifact_key,
            parameter_manifest_hash=manifest_hash,
            actor=actor,
            execution_id=execution_id,
            project_id=run.project_id,
            project_run_id=run.id,
            # A later chat turn may request the same exact run attach. The Recipe #1 execution's
            # parent is initial lineage, not mutable caller state, so an exact replay must retain
            # the parent already stored on the deterministic execution id.
            parent_execution_id=immutable_parent if replaying else parent_execution_id,
            additional_requirements=requirements,
            pre_satisfied_nodes=self._pre_satisfied(run),
        )
        if not start.created:
            owner = await self._owner(run.id)
            if owner == (start.execution_id, ExecutionStatus.PAUSED):
                await self._executor.resume(execution_id=start.execution_id, actor=actor)
        await enqueue_recipe_execution(self._queue, start.execution_id)
        return start.execution_id

    async def attach_confirmed_discovery(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId:
        """Attach the ratified Stage-0 handoff regardless of the legacy new-run canary.

        The canary controls opportunistic migration of older run-start paths. A successful
        ``start_confirmed_project_run@2`` call has already crossed its stricter immutable-lineage
        boundary and promises a real Recipe #1 discovery execution, so silently returning
        ``None`` here would leave a durable run with no owner.
        """

        run = await self._load_run(project_run_id)
        lineage = (
            run.client_entity_id,
            run.client_kb_version,
            run.product_id,
            run.product_context_version_id,
            run.readiness_decision_id,
        )
        if not all(value is not None for value in lineage):
            raise ValueError(
                "confirmed discovery attach requires complete immutable Stage-0 lineage"
            )
        if tuple(ProjectPhase).index(run.phase) < tuple(ProjectPhase).index(ProjectPhase.DISCOVERY):
            raise ValueError("confirmed discovery attach requires a run at discovery or later")
        return await self._attach(
            run,
            actor=actor,
            parent_execution_id=parent_execution_id,
        )

    async def attach_if_eligible(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        parent_execution_id: ExecutionId | None = None,
    ) -> ExecutionId | None:
        run = await self._load_run(project_run_id)
        if not recipe1_workspace_eligible(self._settings, run.workspace_id):
            return None
        return await self._attach(
            run,
            actor=actor,
            parent_execution_id=parent_execution_id,
        )

    async def _owner(
        self, project_run_id: ProjectRunId
    ) -> tuple[ExecutionId, ExecutionStatus] | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT o.execution_id, c.status
                            FROM project_run_execution_owner o
                            JOIN execution_cursor c ON c.execution_id = o.execution_id
                            WHERE o.project_run_id = :run_id
                            """
                        ),
                        {"run_id": project_run_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return ExecutionId(row["execution_id"]), ExecutionStatus(str(row["status"]))

    async def pause_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
        reason_code: str,
    ) -> bool:
        owner = await self._owner(project_run_id)
        if owner is None:
            return False
        execution_id, status = owner
        if status in {ExecutionStatus.RUNNING, ExecutionStatus.QUEUED}:
            await self._executor.pause(
                execution_id=execution_id,
                actor=actor,
                reason_code=reason_code,
            )
        return True

    async def resume_owned(
        self,
        project_run_id: ProjectRunId,
        *,
        actor: str,
    ) -> bool:
        owner = await self._owner(project_run_id)
        if owner is None:
            return False
        execution_id, status = owner
        if status is ExecutionStatus.PAUSED:
            await self._executor.resume(execution_id=execution_id, actor=actor)
        elif status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED}:
            return True
        await enqueue_recipe_execution(self._queue, execution_id)
        return True


__all__: Sequence[str] = (
    "DeferredProjectExecutionRouter",
    "ProjectExecutionRouter",
    "RECIPE1_KEY",
    "RECIPE1_VERSION",
    "Recipe1ProjectExecutionRouter",
    "recipe1_workspace_eligible",
)
