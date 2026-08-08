"""API-root composition for C5.5 run aggregates and source-call telemetry."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import text

from clue_api.auth_tool_context import tool_context_for_internal_service
from clue_api.deep.handler import (
    DeepCanaryController,
    DeepCanaryGateResult,
    DeepCanaryPlan,
)
from clue_config import SupervisorPolicy
from clue_core import (
    AccountEntity,
    ContactEntity,
    ExecutionId,
    FieldDef,
    OperationId,
    PhaseContext,
    PreSpendDecision,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ProjectRunId,
    TargetLock,
)
from clue_db import ConnFactory, transaction
from clue_execution import (
    AggregateRequest,
    ControlKind,
    DbRunControlStore,
    RunAggregateReader,
    RunAggregateSnapshot,
    SupervisorEngine,
)
from clue_fleet import AccountAdmissionDecision, TierPriority
from clue_research.durable import AccountSpec
from clue_research.review import ObservabilitySurface
from clue_research.sources import SourceCallEvent, SourceCallObserver
from clue_toolbelt import ToolInvoker


class DbSourceCallObserver:
    """Append physical provider-call outcomes for exactly one recipe execution."""

    def __init__(
        self,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        project_run_id: ProjectRunId,
        project_id: str,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._execution_id = execution_id
        self._workspace_id = workspace_id
        self._project_run_id = project_run_id
        self._project_id = project_id
        self._conn_factory = conn_factory

    async def observe(self, event: SourceCallEvent) -> None:
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO source_call_observation (
                        id, execution_id, workspace_id, project_run_id, project_id,
                        account_entity_id, account_run_id, field_key, source_key, outcome,
                        error_code, claims_count, cost_cents, latency_ms
                    ) VALUES (
                        :id, :execution_id, :workspace_id, :project_run_id, :project_id,
                        :account_entity_id, :account_run_id, :field_key, :source_key, :outcome,
                        :error_code, :claims_count, :cost_cents, :latency_ms
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "execution_id": self._execution_id,
                    "workspace_id": self._workspace_id,
                    "project_run_id": self._project_run_id,
                    "project_id": self._project_id,
                    **event.model_dump(mode="python"),
                    "outcome": event.outcome.value,
                },
            )


async def source_observer_for_project_run(
    *,
    workspace_id: str,
    project_run_id: ProjectRunId,
    conn_factory: ConnFactory = transaction,
) -> SourceCallObserver | None:
    """Resolve the single Recipe #1 owner; legacy runs deliberately emit no C5.5 telemetry."""

    async with conn_factory() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT o.execution_id, r.project_id
                        FROM project_run_execution_owner o
                        JOIN project_run r ON r.id = o.project_run_id
                        JOIN execution e ON e.id = o.execution_id
                        WHERE o.project_run_id = :project_run_id
                          AND r.workspace_id = :workspace_id
                          AND e.workspace_id = :workspace_id
                        """
                    ),
                    {"project_run_id": project_run_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    return DbSourceCallObserver(
        execution_id=ExecutionId(row["execution_id"]),
        workspace_id=workspace_id,
        project_run_id=project_run_id,
        project_id=str(row["project_id"]),
        conn_factory=conn_factory,
    )


class RunControlledPreSpendGate:
    """Enforce a run-local source breaker before delegating to M9.1's existing gate."""

    def __init__(
        self,
        *,
        inner: PreSpendGate,
        controls: DbRunControlStore,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._inner = inner
        self._controls = controls
        self._conn_factory = conn_factory

    async def check(self, request: PreSpendRequest) -> PreSpendDecision:
        if request.source_key is not None:
            async with self._conn_factory() as conn:
                execution_id = (
                    await conn.execute(
                        text(
                            """
                            SELECT o.execution_id
                            FROM account_run a
                            JOIN project_run_execution_owner o
                              ON o.project_run_id = a.project_run_id
                            WHERE a.id = :account_run_id
                            """
                        ),
                        {"account_run_id": request.run_id},
                    )
                ).scalar_one_or_none()
            if execution_id is not None and not await self._controls.source_allowed(
                ExecutionId(execution_id), request.source_key
            ):
                return PreSpendDecision(
                    verdict=PreSpendVerdict.REJECT,
                    reasons=("source_breaker_active",),
                )
        return await self._inner.check(request)

    async def assemble_target_lock(
        self,
        entity: AccountEntity | ContactEntity,
        field: FieldDef,
    ) -> TargetLock:
        return await self._inner.assemble_target_lock(entity, field)

    def with_conn_factory(self, conn_factory: ConnFactory) -> RunControlledPreSpendGate:
        """Rebind both the run-control lookup and a transaction-aware inner gate."""
        rebind = getattr(self._inner, "with_conn_factory", None)
        inner = rebind(conn_factory) if callable(rebind) else self._inner
        return RunControlledPreSpendGate(
            inner=inner,
            controls=self._controls,
            conn_factory=conn_factory,
        )


class RunControlAccountAdmission:
    """Scheduler admission callback: a quarantined account is parked before ``run_one``."""

    def __init__(
        self,
        *,
        controls: DbRunControlStore,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._controls = controls
        self._conn_factory = conn_factory

    async def __call__(
        self,
        project_run_id: ProjectRunId,
        spec: AccountSpec,
        _ordinal: int,
    ) -> AccountAdmissionDecision:
        async with self._conn_factory() as conn:
            owner = (
                await conn.execute(
                    text(
                        """
                        SELECT execution_id
                        FROM project_run_execution_owner
                        WHERE project_run_id = :project_run_id
                        """
                    ),
                    {"project_run_id": project_run_id},
                )
            ).scalar_one_or_none()
        if owner is None:
            return AccountAdmissionDecision(allowed=True)
        execution_id = ExecutionId(owner)
        if await self._controls.account_allowed(execution_id, str(spec.entity_id)):
            return AccountAdmissionDecision(allowed=True)
        current = await self._controls.latest(
            execution_id, ControlKind.ACCOUNT_QUARANTINE, str(spec.entity_id)
        )
        return AccountAdmissionDecision(
            allowed=False,
            reason_code="account_quarantined",
            control_ref=f"run_control_event:{current.seq}" if current is not None else None,
        )


class ToolbeltSupervisorActions:
    """Invoke automatic controls as journaled child executions of the supervised run."""

    def __init__(
        self,
        *,
        invoker: ToolInvoker,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._invoker = invoker
        self._conn_factory = conn_factory

    async def apply(
        self,
        *,
        workspace_id: str,
        execution_id: ExecutionId,
        observation_id: str,
        diagnosis_id: str | None,
        control_kind: ControlKind,
        subject_ref: str,
        reason_code: str,
        limits: dict[str, int] | None = None,
    ) -> None:
        operation_id = OperationId(
            uuid5(
                NAMESPACE_URL,
                "clue-supervisor-control:"
                f"{execution_id}:{observation_id}:{control_kind.value}:{subject_ref}",
            )
        )
        body: dict[str, object] = {
            "execution_id": str(execution_id),
            "control_kind": control_kind.value,
            "subject_ref": subject_ref,
            "reason_code": reason_code,
            "observation_id": observation_id,
            "diagnosis_id": diagnosis_id,
        }
        if limits is not None:
            body["limits"] = limits
        await self._invoker.invoke(
            "apply_run_control",
            body,
            tool_context_for_internal_service(
                service_id="svc_run_supervisor",
                workspace_id=workspace_id,
                conn_factory=self._conn_factory,
                operation_id=operation_id,
                parent_execution_id=execution_id,
            ),
        )


class SupervisorActions(Protocol):
    async def apply(
        self,
        *,
        workspace_id: str,
        execution_id: ExecutionId,
        observation_id: str,
        diagnosis_id: str | None,
        control_kind: ControlKind,
        subject_ref: str,
        reason_code: str,
        limits: dict[str, int] | None = None,
    ) -> None: ...


class DeferredSupervisorActions:
    """Break the boot-time cycle between the run driver and its control toolbelt."""

    def __init__(self) -> None:
        self._bound: SupervisorActions | None = None

    def bind(self, actions: SupervisorActions) -> None:
        if self._bound is not None:
            raise RuntimeError("supervisor actions are already bound")
        self._bound = actions

    async def apply(
        self,
        *,
        workspace_id: str,
        execution_id: ExecutionId,
        observation_id: str,
        diagnosis_id: str | None,
        control_kind: ControlKind,
        subject_ref: str,
        reason_code: str,
        limits: dict[str, int] | None = None,
    ) -> None:
        if self._bound is None:
            raise RuntimeError("supervisor actions were not bound before run execution")
        await self._bound.apply(
            workspace_id=workspace_id,
            execution_id=execution_id,
            observation_id=observation_id,
            diagnosis_id=diagnosis_id,
            control_kind=control_kind,
            subject_ref=subject_ref,
            reason_code=reason_code,
            limits=limits,
        )


class ApiDeepCanaryController:
    """Split one existing deep handler into canary/remainder and enforce the supervisor gate."""

    def __init__(
        self,
        *,
        policy: SupervisorPolicy,
        controls: DbRunControlStore,
        supervisor: SupervisorEngine,
        actions: SupervisorActions,
        priority_for: TierPriority,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._policy = policy
        self._controls = controls
        self._supervisor = supervisor
        self._actions = actions
        self._priority_for = priority_for
        self._conn_factory = conn_factory

    async def _owner(self, ctx: PhaseContext) -> ExecutionId | None:
        project_run_id = ctx.project_run_id
        workspace_id = ctx.workspace_id
        async with self._conn_factory() as conn:
            owner = (
                await conn.execute(
                    text(
                        """
                        SELECT o.execution_id
                        FROM project_run_execution_owner o
                        JOIN execution e ON e.id = o.execution_id
                        WHERE o.project_run_id = :project_run_id
                          AND e.workspace_id = :workspace_id
                        """
                    ),
                    {"project_run_id": project_run_id, "workspace_id": workspace_id},
                )
            ).scalar_one_or_none()
        return ExecutionId(owner) if owner is not None else None

    async def plan(
        self,
        ctx: PhaseContext,
        specs: Sequence[AccountSpec],
    ) -> DeepCanaryPlan:
        owner = await self._owner(ctx)
        ordered = tuple(
            sorted(specs, key=lambda spec: (self._priority_for(spec.tier), str(spec.entity_id)))
        )
        if owner is None:
            return DeepCanaryPlan(enabled=False, canary=ordered)
        envelope = await self._controls.effective_envelope(owner)
        admitted = ordered[: envelope.max_fanout]
        excluded = ordered[envelope.max_fanout :]
        canary = admitted[: self._policy.canary_size]
        return DeepCanaryPlan(
            enabled=True,
            canary=canary,
            remainder=admitted[len(canary) :],
            envelope_excluded=excluded,
        )

    async def source_observer(self, ctx: PhaseContext) -> SourceCallObserver | None:
        return await source_observer_for_project_run(
            workspace_id=ctx.workspace_id,
            project_run_id=ctx.project_run_id,
            conn_factory=self._conn_factory,
        )

    async def evaluate(
        self,
        ctx: PhaseContext,
        canary_specs: Sequence[AccountSpec],
    ) -> DeepCanaryGateResult:
        del canary_specs
        owner = await self._owner(ctx)
        if owner is None:
            return DeepCanaryGateResult(proceed=True)
        observation = await self._supervisor.observe(
            workspace_id=ctx.workspace_id,
            execution_id=owner,
            project_run_id=ctx.project_run_id,
        )
        diagnosis = await self._supervisor.diagnose(observation)
        if observation.healthy:
            return DeepCanaryGateResult(
                proceed=True,
                observation_id=str(observation.id),
            )

        diagnosis_id = str(diagnosis.id) if diagnosis is not None else None
        permitted = {
            ControlKind(action.value) for action in self._policy.permitted_automatic_actions
        }
        bad_sources = sorted(
            {
                trigger.split(":", 1)[1]
                for trigger in observation.trigger_codes
                if trigger.startswith(
                    ("source_error_rate:", "source_empty_rate:", "source_latency:")
                )
            }
        )
        quarantined = 0
        for source_key in bad_sources[: self._policy.max_source_breakers]:
            if ControlKind.SOURCE_BREAKER in permitted:
                await self._actions.apply(
                    workspace_id=ctx.workspace_id,
                    execution_id=owner,
                    observation_id=str(observation.id),
                    diagnosis_id=diagnosis_id,
                    control_kind=ControlKind.SOURCE_BREAKER,
                    subject_ref=source_key,
                    reason_code="canary_source_health_failed",
                )
            for account_ref in observation.snapshot.source_account_refs.get(source_key, ()):
                if quarantined >= self._policy.max_quarantined_accounts:
                    break
                if ControlKind.ACCOUNT_QUARANTINE in permitted:
                    await self._actions.apply(
                        workspace_id=ctx.workspace_id,
                        execution_id=owner,
                        observation_id=str(observation.id),
                        diagnosis_id=diagnosis_id,
                        control_kind=ControlKind.ACCOUNT_QUARANTINE,
                        subject_ref=account_ref,
                        reason_code="canary_source_affected_account",
                    )
                    quarantined += 1
        if ControlKind.ESCALATION in permitted:
            await self._actions.apply(
                workspace_id=ctx.workspace_id,
                execution_id=owner,
                observation_id=str(observation.id),
                diagnosis_id=diagnosis_id,
                control_kind=ControlKind.ESCALATION,
                subject_ref="deep_gate",
                reason_code="canary_health_failed",
            )
        return DeepCanaryGateResult(
            proceed=False,
            trigger_codes=observation.trigger_codes,
            observation_id=str(observation.id),
            diagnosis_id=diagnosis_id,
        )


class ApiRunAggregateReader:
    """One canary/run snapshot composed from existing durable read surfaces and C5.5 telemetry."""

    def __init__(
        self,
        *,
        observability: ObservabilitySurface,
        stalled_after_s: float,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._surface = observability
        self._stalled_after_s = stalled_after_s
        self._conn_factory = conn_factory

    async def snapshot(self, request: AggregateRequest) -> RunAggregateSnapshot:
        progress = await self._surface.campaign_progress(
            project_run_id=request.project_run_id,
            workspace_id=request.workspace_id,
        )
        if progress is None:
            raise ValueError("project run is absent or outside the workspace")
        burndown = await self._surface.cost_burndown(
            project_run_id=request.project_run_id,
            workspace_id=request.workspace_id,
        )
        health = await self._surface.verification_health(
            project_run_id=request.project_run_id,
            workspace_id=request.workspace_id,
        )
        coverage = await self._surface.coverage_confidence(
            project_run_id=request.project_run_id,
            workspace_id=request.workspace_id,
        )

        async with self._conn_factory() as conn:
            owner = (
                await conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM execution
                        WHERE id = :execution_id
                          AND workspace_id = :workspace_id
                          AND project_run_id = :project_run_id
                        """
                    ),
                    request.model_dump(include={"execution_id", "workspace_id", "project_run_id"}),
                )
            ).one_or_none()
            if owner is None:
                raise ValueError("execution does not own the requested run/workspace context")
            fleet_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT status, count(*) AS count,
                                   count(*) FILTER (
                                       WHERE status IN ('queued', 'claimed')
                                         AND updated_at <= now()
                                             - make_interval(secs => :stalled_after_s)
                                   ) AS stalled,
                                   array_agg(dedup_key ORDER BY priority, enqueue_seq)
                                       FILTER (WHERE status = 'failed') AS failed_refs
                            FROM fleet_task
                            WHERE kind = 'account_job' AND work_id = :project_run_id
                            GROUP BY status
                            """
                        ),
                        {
                            "project_run_id": request.project_run_id,
                            "stalled_after_s": self._stalled_after_s,
                        },
                    )
                )
                .mappings()
                .all()
            )
            coverage_row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                (SELECT count(*) FROM coverage_attempt
                                 WHERE workspace_id = :workspace_id
                                   AND project_run_id = :project_run_id) AS attempts,
                                (SELECT count(*) FROM coverage_attempt
                                 WHERE workspace_id = :workspace_id
                                   AND project_run_id = :project_run_id
                                   AND outcome IN (
                                       'no_hit', 'blocked', 'failed'
                                   )) AS empty_attempts,
                                (SELECT count(*) FROM coverage_decision
                                 WHERE workspace_id = :workspace_id
                                   AND project_run_id = :project_run_id
                                   AND terminal_status = 'unfilled_terminal') AS terminal_empty
                            """
                        ),
                        {
                            "workspace_id": request.workspace_id,
                            "project_run_id": request.project_run_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            source_rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT source_key,
                                   count(*) AS attempts,
                                   count(*) FILTER (WHERE outcome = 'failed') AS failures,
                                   count(*) FILTER (WHERE outcome = 'empty') AS empty,
                                   count(*) FILTER (WHERE outcome = 'claims_produced')
                                       AS claims_produced_calls,
                                   COALESCE(sum(claims_count), 0) AS claims_count,
                                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                                       AS p95_latency_ms,
                                   array_agg(DISTINCT account_entity_id::text)
                                       FILTER (WHERE outcome IN ('failed', 'empty'))
                                       AS affected_accounts
                            FROM source_call_observation
                            WHERE execution_id = :execution_id
                            GROUP BY source_key
                            ORDER BY source_key
                            """
                        ),
                        {"execution_id": request.execution_id},
                    )
                )
                .mappings()
                .all()
            )
            failure_row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT
                                count(*) FILTER (
                                    WHERE ev.event_type IN ('node.failed', 'execution.failed')
                                ) AS failures,
                                count(*) FILTER (WHERE ev.event_type = 'node.blocked') AS blocked
                            FROM execution e
                            JOIN execution_event ev ON ev.execution_id = e.id
                            WHERE e.id = :execution_id OR e.parent_execution_id = :execution_id
                            """
                        ),
                        {"execution_id": request.execution_id},
                    )
                )
                .mappings()
                .one()
            )

        status_counts = {str(row["status"]): int(row["count"]) for row in fleet_rows}
        failed_refs: list[str] = []
        stalled_accounts = 0
        for row in fleet_rows:
            values = row["failed_refs"]
            if isinstance(values, list):
                failed_refs.extend(str(item) for item in values)
            stalled_accounts += int(row["stalled"])
        terminal_accounts = status_counts.get("done", 0) + status_counts.get("failed", 0)
        counts = {
            "phases_total": len(progress.phases),
            "phases_completed": sum(1 for phase in progress.phases if phase.is_complete),
            "run_paused": int(progress.is_paused),
            "run_terminal": int(progress.is_terminal),
            "awaiting_input": int(progress.awaiting_input),
            "canary_accounts_terminal": terminal_accounts,
            "fleet_queued": status_counts.get("queued", 0),
            "fleet_claimed": status_counts.get("claimed", 0),
            "fleet_done": status_counts.get("done", 0),
            "fleet_failed": status_counts.get("failed", 0),
            "stalled_accounts": stalled_accounts,
            "coverage_attempts": int(coverage_row["attempts"]),
            "coverage_empty_attempts": int(coverage_row["empty_attempts"]),
            "coverage_terminal_empty": int(coverage_row["terminal_empty"]),
            "execution_failures": int(failure_row["failures"]),
            "precondition_blocks": int(failure_row["blocked"]),
            "faithfulness_total": health.faithfulness_total if health is not None else 0,
            "contact_total": health.contact_total if health is not None else 0,
            "corroboration_total": health.corroboration_total if health is not None else 0,
        }
        rates = {
            "phase_completion_fraction": (
                counts["phases_completed"] / counts["phases_total"]
                if counts["phases_total"]
                else 0.0
            ),
            "budget_fraction": (
                float(burndown.spent_cents / burndown.cap_cents)
                if burndown is not None and burndown.cap_cents > 0
                else 0.0
            ),
            "coverage_terminal_empty_rate": (
                counts["coverage_terminal_empty"] / counts["coverage_attempts"]
                if counts["coverage_attempts"]
                else 0.0
            ),
            "faithfulness_pass_share": (
                health.faithfulness_pass_share
                if health is not None and health.faithfulness_pass_share is not None
                else 1.0
            ),
            "strong_binding_share": (
                health.strong_binding_share
                if health is not None and health.strong_binding_share is not None
                else 1.0
            ),
            "corroboration_pass_rate": (
                health.corroboration_pass_rate
                if health is not None and health.corroboration_pass_rate is not None
                else 1.0
            ),
            "coverage_confidence": float(coverage.coverage_point) if coverage is not None else 0.0,
        }
        source_counts: dict[str, dict[str, int]] = {}
        source_rates: dict[str, dict[str, float]] = {}
        source_account_refs: dict[str, tuple[str, ...]] = {}
        for row in source_rows:
            source = str(row["source_key"])
            attempts = int(row["attempts"])
            source_counts[source] = {
                "attempts": attempts,
                "failures": int(row["failures"]),
                "empty": int(row["empty"]),
                "claims_produced_calls": int(row["claims_produced_calls"]),
                "claims_count": int(row["claims_count"]),
            }
            source_rates[source] = {
                "error_rate": int(row["failures"]) / attempts if attempts else 0.0,
                "empty_rate": int(row["empty"]) / attempts if attempts else 0.0,
                "p95_latency_ms": float(row["p95_latency_ms"] or 0),
            }
            affected = row["affected_accounts"]
            source_account_refs[source] = (
                tuple(sorted(str(item) for item in affected)) if isinstance(affected, list) else ()
            )
        affected_refs = set(failed_refs)
        if coverage is not None:
            affected_refs.update(channel.source_key for channel in coverage.channels_not_searched)
        for refs in source_account_refs.values():
            affected_refs.update(refs)
        return RunAggregateSnapshot(
            execution_id=request.execution_id,
            project_run_id=request.project_run_id,
            policy_version=request.policy_version,
            labels={
                "current_phase": progress.current_phase.value,
                "run_status": progress.run_status,
            },
            counts=counts,
            rates=rates,
            source_counts=source_counts,
            source_rates=source_rates,
            source_account_refs=source_account_refs,
            affected_refs=tuple(sorted(affected_refs)),
        )


_AGGREGATE_READER_IS: type[RunAggregateReader] = ApiRunAggregateReader
_CANARY_CONTROLLER_IS: type[DeepCanaryController] = ApiDeepCanaryController

__all__ = [
    "ApiRunAggregateReader",
    "ApiDeepCanaryController",
    "DeferredSupervisorActions",
    "DbSourceCallObserver",
    "RunControlledPreSpendGate",
    "RunControlAccountAdmission",
    "SupervisorActions",
    "ToolbeltSupervisorActions",
    "source_observer_for_project_run",
]
