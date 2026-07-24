"""Lane-local construction of the C1 ``research_account_gaps`` tool.

Central toolbelt registration intentionally remains an integration-branch responsibility.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from uuid import UUID

from clue_api.composition import build_pre_spend_gate
from clue_api.locks import lazy_account_lock_factory
from clue_config import DEFAULT_GATEWAY_CONFIG
from clue_config.coverage import DEFAULT_RESEARCH_LOOP_POLICY, ResearchLoopPolicy
from clue_core import (
    BudgetEngine as BudgetEngineContract,
)
from clue_core import (
    EntityId,
    FieldDef,
    LLMGateway,
    PreSpendGate,
    ProjectRunId,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import get_field
from clue_research.coverage import CoverageController, GoalJudge
from clue_research.durable import (
    BudgetEngine,
    DbBudgetStore,
    LockFactory,
    get_project_run,
    list_account_runs,
)
from clue_research.identity import get_account
from clue_toolbelt import (
    PreconditionFailure,
    Tool,
    ToolContext,
    ToolEstimate,
    ToolInput,
    ToolResult,
)


class ResearchAccountGapsInput(ToolInput):
    project_run_id: str
    account_entity_id: str
    tier: str
    gap_fields: list[str]
    strategy_hint: str | None = None


def _uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except (TypeError, ValueError, AttributeError):
        return None


def _fail(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


def _planned_field_keys(plan_json: Mapping[str, object]) -> set[str]:
    raw_aspects = plan_json.get("aspects")
    if not isinstance(raw_aspects, list):
        return set()
    keys: set[str] = set()
    for aspect in raw_aspects:
        if not isinstance(aspect, dict):
            continue
        raw_keys = aspect.get("field_keys")
        if isinstance(raw_keys, list):
            keys.update(key for key in raw_keys if isinstance(key, str))
    return keys


class ResearchAccountGapsTool(Tool):
    name = "research_account_gaps"
    version = "1"
    input_model = ResearchAccountGapsInput

    def __init__(
        self,
        *,
        gateway: LLMGateway | None,
        conn_factory: ConnFactory = transaction,
        budget: BudgetEngineContract,
        pre_spend_gate: PreSpendGate,
        lock_factory: LockFactory,
        policy: ResearchLoopPolicy = DEFAULT_RESEARCH_LOOP_POLICY,
        judge_model: str = DEFAULT_GATEWAY_CONFIG.judge_model,
    ) -> None:
        self._gateway = gateway
        self._conn_factory = conn_factory
        self._budget = budget
        self._pre_spend_gate = pre_spend_gate
        self._lock_factory = lock_factory
        self._policy = policy
        self._judge_model = judge_model

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ResearchAccountGapsInput)
        project_uuid = _uuid(inputs.project_run_id)
        account_uuid = _uuid(inputs.account_entity_id)
        if project_uuid is None:
            return _fail("run_not_found", "no such project run")
        if account_uuid is None:
            return _fail("account_not_found", "no such account entity")
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, ProjectRunId(project_uuid))
            if run is None or run.workspace_id != ctx.workspace_id:
                return _fail("run_not_found", "no such project run")
            account = await get_account(conn, EntityId(account_uuid))
            if account is None or account.workspace_id != ctx.workspace_id:
                return _fail("account_not_found", "no such account entity")
            account_runs = await list_account_runs(conn, run.id)
            matching_runs = [row for row in account_runs if row.entity_id == account.id]
            account_run = max(matching_runs, key=lambda row: row.updated_at, default=None)
            if account_run is None:
                return _fail(
                    "account_run_not_found",
                    "the account has no research run under this project run",
                )
            if account_run.tier != inputs.tier:
                return _fail("tier_mismatch", "tier does not match the durable account run")
            planned = _planned_field_keys(account_run.plan_json)
            invalid = [
                key
                for key in inputs.gap_fields
                if key not in planned or await get_field(conn, key) is None
            ]
            if invalid:
                return _fail(
                    "unplanned_gap_fields",
                    f"gap fields are not registered in the durable account plan: {sorted(invalid)}",
                )
        if self._gateway is None:
            return _fail(
                "gateway_required",
                "research gap evaluation requires a configured LLM gateway",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, ResearchAccountGapsInput)
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={
                "basis": "controller_pre_spend_source_manifest_sum",
                "gap_count": len(inputs.gap_fields),
            },
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ResearchAccountGapsInput)
        if self._gateway is None:
            raise RuntimeError("research_account_gaps invoked without a configured LLM gateway")
        project_run_id = ProjectRunId(UUID(inputs.project_run_id))
        account_id = EntityId(UUID(inputs.account_entity_id))
        async with self._lock_factory(account_id), self._conn_factory() as conn:
            run = await get_project_run(conn, project_run_id)
            account = await get_account(conn, account_id)
            assert run is not None and account is not None
            account_runs = await list_account_runs(conn, project_run_id)
            account_run = max(
                (row for row in account_runs if row.entity_id == account_id),
                key=lambda row: row.updated_at,
            )
            loaded_defs: list[FieldDef] = []
            for key in inputs.gap_fields:
                field = await get_field(conn, key)
                if field is not None:
                    loaded_defs.append(field)
            defs = tuple(loaded_defs)
            remaining = (
                None
                if run.budget_cap_cents is None
                else max(Decimal(0), run.budget_cap_cents - run.spent_cents)
            )
            controller = CoverageController(
                policy=self._policy,
                judge=GoalJudge(self._gateway, model=self._judge_model),
                budget=self._budget,
                pre_spend_gate=self._pre_spend_gate,
            )
            result = await controller.run_round(
                conn,
                workspace_id=ctx.workspace_id,
                run_id=account_run.id,
                project_run_id=project_run_id,
                entity=account.as_entity(),
                tier=inputs.tier,
                field_defs=defs,
                strategy_hint=inputs.strategy_hint,
                quality_mode=ctx.quality_mode,
                remaining_budget_cents=remaining,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "project_run_id": inputs.project_run_id,
                "account_entity_id": inputs.account_entity_id,
                "round": result.round,
                "coverage_decision_ids": [str(item) for item in result.decision_ids],
                "attempt_ids": [str(item) for item in result.attempt_ids],
                "claim_refs": [str(item) for item in result.claim_refs],
                "remaining_gap_count": result.remaining_gap_count,
                "terminal": result.terminal,
            },
        )


def build_research_account_gaps_tool(
    *,
    gateway: LLMGateway | None,
    conn_factory: ConnFactory = transaction,
    budget: BudgetEngineContract | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    lock_factory: LockFactory | None = None,
    policy: ResearchLoopPolicy = DEFAULT_RESEARCH_LOOP_POLICY,
    judge_model: str = DEFAULT_GATEWAY_CONFIG.judge_model,
) -> ResearchAccountGapsTool:
    return ResearchAccountGapsTool(
        gateway=gateway,
        conn_factory=conn_factory,
        budget=budget or BudgetEngine(store=DbBudgetStore(conn_factory=conn_factory)),
        pre_spend_gate=pre_spend_gate or build_pre_spend_gate(conn_factory=conn_factory),
        lock_factory=lock_factory or lazy_account_lock_factory(),
        policy=policy,
        judge_model=judge_model,
    )


__all__ = [
    "ResearchAccountGapsInput",
    "ResearchAccountGapsTool",
    "build_research_account_gaps_tool",
]
