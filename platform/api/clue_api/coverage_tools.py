"""Lane-local construction of the C1 ``research_account_gaps`` tool.

Central toolbelt registration intentionally remains an integration-branch responsibility.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import Field, model_validator

from clue_api.composition import build_pre_spend_gate
from clue_api.locks import lazy_account_lock_factory
from clue_api.tool_outputs import (
    EvaluatorAdviceOutput,
    ResearchAccountGapsOutput,
    ResearchAccountGapsV2Output,
)
from clue_config import DEFAULT_GATEWAY_CONFIG
from clue_config.coverage import DEFAULT_RESEARCH_LOOP_POLICY, ResearchLoopPolicy
from clue_core import (
    BudgetEngine as BudgetEngineContract,
)
from clue_core import (
    EntityId,
    EntityScope,
    FieldDef,
    LLMGateway,
    PreSpendGate,
    ProjectRunId,
    ResearchMode,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import get_field
from clue_research.coverage import (
    COVERAGE_EVALUATOR_OWNER,
    CoverageController,
    CoverageEvaluatorAdvice,
    GoalJudge,
    list_decisions,
)
from clue_research.durable import (
    BudgetEngine,
    DbBudgetStore,
    LockFactory,
    get_project_run,
    list_account_runs,
)
from clue_research.icp import get_icp_version
from clue_research.identity import get_account
from clue_research.sources import plan_sources
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)


class ResearchAccountGapsInput(ToolInput):
    project_run_id: str
    account_entity_id: str
    tier: str
    gap_fields: list[str]
    strategy_hint: str | None = None


class ResearchAccountGapsV2Input(ToolInput):
    project_run_id: str
    account_entity_id: str
    tier: str
    round: int = Field(ge=1)
    gap_fields: list[str] = Field(min_length=1)
    strategy_hint: str | None = None
    propose_stop: bool = False

    @model_validator(mode="after")
    def stop_has_no_strategy(self) -> ResearchAccountGapsV2Input:
        if self.propose_stop and self.strategy_hint is not None:
            raise ValueError("a stop proposal cannot also select a source strategy")
        return self


def build_c1_coverage_evaluator(gateway: LLMGateway, *, model: str) -> GoalJudge:
    """Construct the one independent C1 evaluator at its explicit composition owner."""

    return GoalJudge(gateway, model=model)


def coverage_evaluator_owner() -> str:
    return COVERAGE_EVALUATOR_OWNER


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
    input_model: ClassVar[type[ToolInput]] = ResearchAccountGapsInput
    output_model: ClassVar[type[ToolOutput]] = ResearchAccountGapsOutput

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
        assert isinstance(inputs, (ResearchAccountGapsInput, ResearchAccountGapsV2Input))
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
            if isinstance(inputs, ResearchAccountGapsV2Input):
                decisions = await list_decisions(
                    conn,
                    workspace_id=ctx.workspace_id,
                    run_id=account_run.id,
                    entity_id=account.id,
                )
                terminal = {
                    item.field_key for item in decisions if item.terminal_status is not None
                }
                already_terminal = sorted(set(inputs.gap_fields) & terminal)
                if already_terminal:
                    return _fail(
                        "terminal_gap_fields",
                        "gap fields already have engine-terminal coverage decisions: "
                        f"{already_terminal}",
                    )
        if self._gateway is None:
            return _fail(
                "gateway_required",
                "research gap evaluation requires a configured LLM gateway",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, (ResearchAccountGapsInput, ResearchAccountGapsV2Input))
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={
                "basis": "controller_pre_spend_source_manifest_sum",
                "gap_count": len(inputs.gap_fields),
            },
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, (ResearchAccountGapsInput, ResearchAccountGapsV2Input))
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
            spec = await get_icp_version(
                conn,
                ctx.workspace_id,
                run.icp_key,
                run.icp_version,
            )
            if spec is None:
                raise RuntimeError("account research run lost its pinned ICP version")
            effective_source_plans = {}
            for field in defs:
                source_plan = await plan_sources(
                    conn,
                    spec=spec,
                    entity=account.as_entity(),
                    field=str(field.field_key),
                    mode=ResearchMode.ACCOUNT_PROFILING,
                    entity_tier=inputs.tier,
                    entity_scope=EntityScope.ACCOUNT,
                )
                if source_plan.effective_source_plan is None:
                    raise RuntimeError("source planner did not return exact field authority")
                effective_source_plans[str(field.field_key)] = (
                    source_plan.effective_source_plan
                )
            remaining = (
                None
                if run.budget_cap_cents is None
                else max(Decimal(0), run.budget_cap_cents - run.spent_cents)
            )
            controller = CoverageController(
                policy=self._policy,
                judge=build_c1_coverage_evaluator(self._gateway, model=self._judge_model),
                budget=self._budget,
                pre_spend_gate=self._pre_spend_gate,
            )
            if isinstance(inputs, ResearchAccountGapsV2Input) and inputs.propose_stop:
                advice = await controller.assess_stop_proposal(
                    conn,
                    workspace_id=ctx.workspace_id,
                    run_id=account_run.id,
                    project_run_id=project_run_id,
                    entity=account.as_entity(),
                    tier=inputs.tier,
                    field_defs=defs,
                    requested_round=inputs.round,
                    remaining_budget_cents=remaining,
                )
                return ToolResult(
                    tool=self.name,
                    version=self.version,
                    references={
                        "project_run_id": inputs.project_run_id,
                        "account_entity_id": inputs.account_entity_id,
                        "round": inputs.round,
                        "coverage_decision_ids": [],
                        "attempt_ids": [],
                        "claim_refs": [],
                        "remaining_gap_count": len(defs),
                        "terminal": False,
                        "evaluator_advice": _advice_output(advice).model_dump(mode="json"),
                        "stop_proposal": True,
                    },
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
                requested_round=(
                    inputs.round if isinstance(inputs, ResearchAccountGapsV2Input) else None
                ),
                effective_source_plans=effective_source_plans,
            )
        references: dict[str, object] = {
            "project_run_id": inputs.project_run_id,
            "account_entity_id": inputs.account_entity_id,
            "round": result.round,
            "coverage_decision_ids": [str(item) for item in result.decision_ids],
            "attempt_ids": [str(item) for item in result.attempt_ids],
            "claim_refs": [str(item) for item in result.claim_refs],
            "remaining_gap_count": result.remaining_gap_count,
            "terminal": result.terminal,
        }
        if isinstance(inputs, ResearchAccountGapsV2Input):
            if result.evaluator_advice_id is None or result.evaluator_valid is None:
                raise RuntimeError("C6.7 round completed without evaluator advice")
            references.update(
                {
                    "evaluator_advice": EvaluatorAdviceOutput(
                        evaluator_advice_id=str(result.evaluator_advice_id),
                        valid=result.evaluator_valid,
                        proposal_kind="round_boundary",
                        sufficient_for_goal=result.evaluator_sufficient_for_goal,
                        recommendations=[item.value for item in result.evaluator_recommendations],
                        warning_codes=[item.value for item in result.evaluator_warnings],
                    ).model_dump(mode="json"),
                    "stop_proposal": False,
                }
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=references,
        )


class ResearchAccountGapsV2Tool(ResearchAccountGapsTool):
    """Replay-certified agent surface over the same C1 controller and evaluator."""

    version = "2"
    input_model = ResearchAccountGapsV2Input
    output_model = ResearchAccountGapsV2Output
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity=(
            "tool_invocation.operation_id plus append-only "
            "(run_id,entity_id,tier,round,field,strategy) coverage identities"
        ),
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
        notes=(
            "A crash before the invocation receipt may repeat an external resolver or evaluator "
            "call; coverage rows and budget records converge on durable identities."
        ),
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_run_id",
            "account_entity_id",
            "tier",
            "round",
            "propose_stop",
        )
    )
    pin_requirements = (
        "project_run",
        "account",
        "field_registry",
        "source_registry",
        "coverage_policy",
    )


def _advice_output(advice: CoverageEvaluatorAdvice) -> EvaluatorAdviceOutput:
    assessments = advice.result.assessments if advice.result is not None else ()
    return EvaluatorAdviceOutput(
        evaluator_advice_id=str(advice.id),
        valid=advice.valid,
        proposal_kind=advice.proposal_kind.value,
        sufficient_for_goal=(
            advice.result.sufficient_for_goal if advice.result is not None else None
        ),
        recommendations=[item.recommendation.value for item in assessments],
        warning_codes=[warning.value for item in assessments for warning in item.warning_codes],
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


def build_research_account_gaps_v2_tool(
    *,
    gateway: LLMGateway | None,
    conn_factory: ConnFactory = transaction,
    budget: BudgetEngineContract | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    lock_factory: LockFactory | None = None,
    policy: ResearchLoopPolicy = DEFAULT_RESEARCH_LOOP_POLICY,
    judge_model: str = DEFAULT_GATEWAY_CONFIG.judge_model,
) -> ResearchAccountGapsV2Tool:
    return ResearchAccountGapsV2Tool(
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
    "ResearchAccountGapsV2Input",
    "ResearchAccountGapsTool",
    "ResearchAccountGapsV2Tool",
    "build_c1_coverage_evaluator",
    "build_research_account_gaps_tool",
    "build_research_account_gaps_v2_tool",
    "coverage_evaluator_owner",
]
