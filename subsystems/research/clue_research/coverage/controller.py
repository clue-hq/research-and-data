"""One-round coverage engine; callers plan, the evaluator advises, and policy disposes."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.coverage import DEFAULT_RESEARCH_LOOP_POLICY, ResearchLoopPolicy
from clue_core import (
    BudgetEngine,
    BudgetScope,
    BudgetVerdict,
    ClaimTagger,
    EffectiveFieldSourcePlan,
    Entity,
    EntityType,
    FieldDef,
    PreSpendGate,
    PreSpendRequest,
    PreSpendVerdict,
    ProjectRunId,
    ResearchAttemptOutcome,
    ResearchMode,
    ResearchTerminalStatus,
    RunId,
    SourceGate,
    SourceManifest,
    coverage_evaluator_advice_id,
    new_coverage_attempt_id,
    new_coverage_decision_id,
)
from clue_core.enums import Modality
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.coverage.judge import GoalJudge
from clue_research.coverage.models import (
    CoverageAttempt,
    CoverageDecision,
    CoverageEvaluatorAdvice,
    EvaluatorProposalKind,
    GoalJudgeCall,
    GoalJudgeRecommendation,
    ResearchStrategy,
    RoundResult,
)
from clue_research.coverage.repository import (
    get_evaluator_advice,
    list_attempts,
    list_decisions,
    record_attempt,
    record_decision,
    record_evaluator_advice,
)
from clue_research.sources import (
    NoResolverBoundError,
    StepOutcome,
    StopReason,
    WaterfallResult,
    get_resolver,
    get_source,
    resolve_field,
)

DEFAULT_STRATEGIES = (
    ResearchStrategy(
        key="deterministic_exact",
        source_family="deterministic",
        source_tiers=frozenset({1}),
        modalities=frozenset({Modality.STRUCTURED.value}),
        query_scope="exact",
    ),
    ResearchStrategy(
        key="official_site_exact",
        source_family="official_site",
        source_tiers=frozenset({2}),
        modalities=frozenset({Modality.TEXT.value, Modality.PDF.value}),
        query_scope="exact",
    ),
    ResearchStrategy(
        key="tier3_web_widened",
        source_family="third_party_web",
        source_tiers=frozenset({3}),
        query_scope="widened",
    ),
    ResearchStrategy(
        key="tier4_research_product",
        source_family="research_product",
        source_tiers=frozenset({4}),
        query_scope="target_locked",
    ),
)


class CoveragePolicyError(ValueError):
    pass


class CoverageController:
    def __init__(
        self,
        *,
        policy: ResearchLoopPolicy = DEFAULT_RESEARCH_LOOP_POLICY,
        strategies: tuple[ResearchStrategy, ...] = DEFAULT_STRATEGIES,
        judge: GoalJudge | None = None,
        budget: BudgetEngine | None = None,
        pre_spend_gate: PreSpendGate | None = None,
    ) -> None:
        self._policy = policy
        self._strategies = {item.key: item for item in strategies}
        self._policy.validate_strategy_catalog(frozenset(self._strategies))
        self._judge = judge
        self._budget = budget
        self._pre_spend_gate = pre_spend_gate
        self._first_strategy = strategies[0].key

    async def run_round(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        run_id: RunId,
        project_run_id: ProjectRunId | None,
        entity: Entity,
        tier: str,
        field_defs: tuple[FieldDef, ...],
        strategy_hint: str | None = None,
        quality_mode: str | None = None,
        claim_tagger: ClaimTagger | None = None,
        remaining_budget_cents: Decimal | None = None,
        requested_round: int | None = None,
        effective_source_plans: Mapping[str, EffectiveFieldSourcePlan] | None = None,
    ) -> RoundResult:
        fields = field_defs[: self._policy.max_gap_fields_per_round]
        if not fields:
            return RoundResult(round=1, terminal=True)
        if entity.entity_type is EntityType.CONTACT and claim_tagger is None:
            raise CoveragePolicyError(
                "contact coverage retries require a born-governance ClaimTagger"
            )
        previous_attempts = await list_attempts(
            conn, workspace_id=workspace_id, run_id=run_id, entity_id=entity.entity_id
        )
        previous_decisions = await list_decisions(
            conn, workspace_id=workspace_id, run_id=run_id, entity_id=entity.entity_id
        )
        latest_round = max((item.round for item in previous_attempts), default=0)
        round_number = requested_round if requested_round is not None else latest_round + 1
        if round_number < 1:
            raise CoveragePolicyError("requested round must be positive")
        completed = [item for item in previous_attempts if item.round == round_number]
        if completed:
            decisions = [item for item in previous_decisions if item.round == round_number]
            advice = await get_evaluator_advice(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                entity_id=entity.entity_id,
                tier=tier,
                round=round_number,
                proposal_kind=EvaluatorProposalKind.ROUND_BOUNDARY,
            )
            return _attach_advice(
                RoundResult(
                    round=round_number,
                    attempt_ids=tuple(item.id for item in completed),
                    decision_ids=tuple(item.id for item in decisions),
                    claim_refs=tuple(ref for item in completed for ref in item.claim_refs),
                    remaining_gap_count=sum(item.terminal_status is None for item in decisions),
                    terminal=bool(decisions)
                    and all(item.terminal_status is not None for item in decisions),
                    replayed=True,
                ),
                advice,
            )
        if requested_round is not None and requested_round != latest_round + 1:
            raise CoveragePolicyError(
                f"requested round {requested_round} is not the next durable round "
                f"{latest_round + 1}"
            )

        terminal_fields = {
            item.field_key for item in previous_decisions if item.terminal_status is not None
        }
        active = tuple(field for field in fields if field.field_key not in terminal_fields)
        if not active:
            return RoundResult(round=round_number, terminal=True, replayed=True)

        latest_attempt = {item.field_key: item for item in previous_attempts}
        selected: dict[str, ResearchStrategy] = {}
        for field in active:
            previous = latest_attempt.get(field.field_key)
            permitted = (
                (self._first_strategy,)
                if previous is None
                else self._policy.strategy_transitions.get(previous.strategy_key, ())
            )
            if not permitted:
                raise CoveragePolicyError(
                    f"no permitted strategy remains for field {field.field_key!r}"
                )
            if strategy_hint is not None:
                if strategy_hint not in permitted:
                    raise CoveragePolicyError(
                        f"strategy_hint {strategy_hint!r} is not an engine-permitted strategy"
                    )
                key = strategy_hint
            else:
                key = permitted[0]
            if key not in self._strategies:
                raise CoveragePolicyError(f"no registered strategy for field {field.field_key!r}")
            if previous is not None and (
                self._strategies[key].dimensions
                == self._strategies[previous.strategy_key].dimensions
            ):
                raise CoveragePolicyError("retry must change a stable strategy dimension")
            selected[field.field_key] = self._strategies[key]

        provisional: list[tuple[FieldDef, ResearchStrategy, WaterfallResult]] = []
        for field in active:
            strategy = selected[field.field_key]
            authority = (
                effective_source_plans.get(str(field.field_key))
                if effective_source_plans is not None
                else None
            )
            planned, projected = await self._planned_field(
                conn,
                field,
                strategy,
                effective_source_plan=authority,
            )
            if not planned.tier_plan:
                result = WaterfallResult(
                    entity_id=entity.entity_id,
                    field_key=field.field_key,
                    stop_reason=StopReason.NO_RESOLVER,
                )
            elif not await self._budget_allows(project_run_id, run_id, entity, projected):
                result = WaterfallResult(
                    entity_id=entity.entity_id,
                    field_key=field.field_key,
                    stop_reason=StopReason.BUDGET_STOP,
                )
            else:
                result = await resolve_field(
                    conn,
                    entity,
                    planned,
                    mode=(
                        ResearchMode.CONTACT_PROFILING
                        if entity.entity_type is EntityType.CONTACT
                        else ResearchMode.ACCOUNT_PROFILING
                    ),
                    run_id=run_id,
                    workspace_id=workspace_id,
                    budget_envelope=remaining_budget_cents,
                    claim_tagger=claim_tagger,
                    source_gate=self._source_gate(
                        entity,
                        field,
                        run_id,
                        effective_source_plan=authority,
                    ),
                )
                if result.claim_refs:
                    claims = await claims_by_ids(
                        conn,
                        result.claim_refs,
                        scope=WorkspaceScope.for_workspace(workspace_id),
                    )
                    promotable = tuple(
                        ref
                        for ref in result.claim_refs
                        if (claim := claims.get(ref)) is not None and claim.is_promotable
                    )
                    result = result.model_copy(update={"claim_refs": promotable})
                if self._budget is not None and project_run_id is not None:
                    await self._budget.record(
                        cost_cents=result.total_cost_cents,
                        scope=BudgetScope.ACCOUNT,
                        project_run_id=project_run_id,
                        entity_id=entity.entity_id,
                        account_run_id=run_id,
                    )
            provisional.append((field, strategy, result))

        judge_call = self._judge_call(
            active, provisional, previous_attempts, remaining_budget_cents, tier
        )
        if judge_call.cost_cents > 0 and self._budget is not None and project_run_id is not None:
            await self._budget.record(
                cost_cents=judge_call.cost_cents,
                scope=BudgetScope.ACCOUNT,
                project_run_id=project_run_id,
                entity_id=entity.entity_id,
                account_run_id=run_id,
            )
        advice = await record_evaluator_advice(
            conn,
            CoverageEvaluatorAdvice(
                id=coverage_evaluator_advice_id(
                    run_id=run_id,
                    entity_id=entity.entity_id,
                    tier=tier,
                    round=round_number,
                    proposal_kind=EvaluatorProposalKind.ROUND_BOUNDARY.value,
                ),
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=project_run_id,
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                tier=tier,
                round=round_number,
                proposal_kind=EvaluatorProposalKind.ROUND_BOUNDARY,
                planned_fields=tuple(field.field_key for field in active),
                result=judge_call.result,
                valid=judge_call.valid,
                answering_model=judge_call.answering_model,
                prompt_version=judge_call.prompt_version,
                cost_cents=judge_call.cost_cents,
            ),
        )
        judge_share = (
            judge_call.cost_cents / Decimal(len(provisional)) if provisional else Decimal(0)
        )
        attempts: list[CoverageAttempt] = []
        for field, strategy, result in provisional:
            outcome = _outcome(result)
            attempts.append(
                await record_attempt(
                    conn,
                    CoverageAttempt(
                        id=new_coverage_attempt_id(),
                        workspace_id=workspace_id,
                        run_id=run_id,
                        project_run_id=project_run_id,
                        entity_id=entity.entity_id,
                        entity_type=entity.entity_type,
                        field_key=field.field_key,
                        tier=tier,
                        round=round_number,
                        strategy_key=strategy.key,
                        source_family=strategy.source_family,
                        outcome=outcome,
                        stop_reason=result.stop_reason.value,
                        reason_detail=_attempt_detail(outcome),
                        cost_cents=result.total_cost_cents + judge_share,
                        claim_refs=result.claim_refs,
                        quality_mode=quality_mode,
                    ),
                )
            )

        yield_rate = sum(bool(item.claim_refs) for item in attempts) / len(attempts)
        final_decisions: list[CoverageDecision] = []
        for attempt in attempts:
            terminal, next_key, code, detail = self._dispose(
                attempt,
                round_number=round_number,
                tier=tier,
                judge_call=judge_call,
                yield_rate=yield_rate,
            )
            final_decisions.append(
                await record_decision(
                    conn,
                    CoverageDecision(
                        id=new_coverage_decision_id(),
                        workspace_id=workspace_id,
                        run_id=run_id,
                        project_run_id=project_run_id,
                        entity_id=entity.entity_id,
                        entity_type=entity.entity_type,
                        field_key=attempt.field_key,
                        tier=tier,
                        round=round_number,
                        terminal_status=terminal,
                        next_strategy_key=next_key,
                        reason_code=code,
                        reason_detail=detail,
                        attempt_refs=(attempt.id,),
                        claim_refs=attempt.claim_refs,
                        judge_model=judge_call.answering_model,
                        judge_prompt_version=judge_call.prompt_version,
                        evaluator_advice_id=advice.id,
                    ),
                )
            )
        return _attach_advice(
            RoundResult(
                round=round_number,
                attempt_ids=tuple(item.id for item in attempts),
                decision_ids=tuple(item.id for item in final_decisions),
                claim_refs=tuple(ref for item in attempts for ref in item.claim_refs),
                remaining_gap_count=sum(item.terminal_status is None for item in final_decisions),
                terminal=all(item.terminal_status is not None for item in final_decisions),
            ),
            advice,
        )

    async def assess_stop_proposal(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        run_id: RunId,
        project_run_id: ProjectRunId | None,
        entity: Entity,
        tier: str,
        field_defs: tuple[FieldDef, ...],
        requested_round: int,
        remaining_budget_cents: Decimal | None = None,
    ) -> CoverageEvaluatorAdvice:
        """Challenge an agent stop proposal without creating attempts or terminal decisions."""

        if requested_round < 1:
            raise CoveragePolicyError("requested round must be positive")
        existing = await get_evaluator_advice(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            entity_id=entity.entity_id,
            tier=tier,
            round=requested_round,
            proposal_kind=EvaluatorProposalKind.AGENT_STOP_PROPOSAL,
        )
        if existing is not None:
            return existing
        prior = await list_attempts(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            entity_id=entity.entity_id,
        )
        latest_round = max((item.round for item in prior), default=0)
        if requested_round != latest_round + 1:
            raise CoveragePolicyError(
                f"stop proposal round {requested_round} is not the next durable round "
                f"{latest_round + 1}"
            )
        fields = field_defs[: self._policy.max_gap_fields_per_round]
        if not fields:
            raise CoveragePolicyError("a stop proposal must name at least one unresolved field")
        terminal_fields = {
            item.field_key
            for item in await list_decisions(
                conn,
                workspace_id=workspace_id,
                run_id=run_id,
                entity_id=entity.entity_id,
            )
            if item.terminal_status is not None
        }
        active = tuple(field for field in fields if field.field_key not in terminal_fields)
        if not active:
            raise CoveragePolicyError("a stop proposal cannot target only terminal fields")
        if self._judge is None:
            call = GoalJudgeCall(
                result=None,
                answering_model="unavailable",
                prompt_version="unavailable",
                valid=False,
            )
        else:
            call = self._judge.judge(
                planned_fields=[field.field_key for field in active],
                current_claim_refs={
                    field.field_key: [
                        str(ref)
                        for attempt in prior
                        if attempt.field_key == field.field_key
                        for ref in attempt.claim_refs
                    ]
                    for field in active
                },
                prior_attempts=[
                    {
                        "attempt_id": str(item.id),
                        "field_key": item.field_key,
                        "round": item.round,
                        "strategy_key": item.strategy_key,
                        "outcome": item.outcome.value,
                    }
                    for item in prior
                ],
                current_round_attempts=[],
                remaining_budget_cents=(
                    str(remaining_budget_cents) if remaining_budget_cents is not None else None
                ),
                hard_round_cap=self._policy.max_rounds_for(tier),
                agent_stop_proposal=True,
            )
        if call.cost_cents > 0 and self._budget is not None and project_run_id is not None:
            await self._budget.record(
                cost_cents=call.cost_cents,
                scope=BudgetScope.ACCOUNT,
                project_run_id=project_run_id,
                entity_id=entity.entity_id,
                account_run_id=run_id,
            )
        return await record_evaluator_advice(
            conn,
            CoverageEvaluatorAdvice(
                id=coverage_evaluator_advice_id(
                    run_id=run_id,
                    entity_id=entity.entity_id,
                    tier=tier,
                    round=requested_round,
                    proposal_kind=EvaluatorProposalKind.AGENT_STOP_PROPOSAL.value,
                ),
                workspace_id=workspace_id,
                run_id=run_id,
                project_run_id=project_run_id,
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                tier=tier,
                round=requested_round,
                proposal_kind=EvaluatorProposalKind.AGENT_STOP_PROPOSAL,
                planned_fields=tuple(field.field_key for field in active),
                result=call.result,
                valid=call.valid,
                answering_model=call.answering_model,
                prompt_version=call.prompt_version,
                cost_cents=call.cost_cents,
            ),
        )

    async def _planned_field(
        self,
        conn: AsyncConnection,
        field: FieldDef,
        strategy: ResearchStrategy,
        *,
        effective_source_plan: EffectiveFieldSourcePlan | None,
    ) -> tuple[FieldDef, Decimal]:
        keys: list[str] = []
        projected = Decimal(0)
        source_keys = (
            tuple(source.source_key for source in effective_source_plan.sources)
            if effective_source_plan is not None
            else field.tier_plan
        )
        authorized_tiers = (
            {
                source.source_key: int(source.source_tier)
                for source in effective_source_plan.sources
            }
            if effective_source_plan is not None
            else None
        )
        for key in source_keys:
            manifest = await get_source(conn, key)
            if manifest is None:
                continue
            if authorized_tiers is not None and authorized_tiers.get(key) != manifest.tier:
                continue
            if strategy.source_tiers and manifest.tier not in strategy.source_tiers:
                continue
            if strategy.modalities and manifest.modality.value not in strategy.modalities:
                continue
            keys.append(key)
            try:
                resolver = get_resolver(key)
            except NoResolverBoundError:
                resolver = None
            if resolver is not None and not getattr(resolver, "materialization_only", False):
                projected += manifest.cost_cents
        return field.model_copy(update={"tier_plan": tuple(keys)}), projected

    async def _budget_allows(
        self,
        project_run_id: ProjectRunId | None,
        run_id: RunId,
        entity: Entity,
        projected: Decimal,
    ) -> bool:
        if self._budget is None or project_run_id is None:
            return True
        for scope in (BudgetScope.ACCOUNT, BudgetScope.RUN):
            decision = await self._budget.check(
                scope=scope,
                projected_cents=projected,
                project_run_id=project_run_id,
                entity_id=entity.entity_id,
                account_run_id=run_id if scope is BudgetScope.ACCOUNT else None,
            )
            if decision.verdict is not BudgetVerdict.ALLOW:
                return False
        return True

    def _source_gate(
        self,
        entity: Entity,
        field: FieldDef,
        run_id: RunId,
        *,
        effective_source_plan: EffectiveFieldSourcePlan | None,
    ) -> SourceGate | None:
        if self._pre_spend_gate is None:
            return None
        gate = self._pre_spend_gate

        async def check(manifest: SourceManifest) -> bool:
            decision = await gate.check(
                PreSpendRequest(
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    field_key=field.field_key,
                    source_tier=manifest.tier,
                    source_key=manifest.source_key,
                    effective_source_plan=effective_source_plan,
                    run_id=run_id,
                )
            )
            return decision.verdict is not PreSpendVerdict.REJECT

        return check

    def _judge_call(
        self,
        fields: tuple[FieldDef, ...],
        results: list[tuple[FieldDef, ResearchStrategy, WaterfallResult]],
        prior: list[CoverageAttempt],
        remaining: Decimal | None,
        tier: str,
    ) -> GoalJudgeCall:
        if self._judge is None or all(
            result.stop_reason is StopReason.BUDGET_STOP for _, _, result in results
        ):
            return GoalJudgeCall(
                result=None,
                answering_model="deterministic",
                prompt_version="deterministic",
                valid=True,
            )
        return self._judge.judge(
            planned_fields=[field.field_key for field in fields],
            current_claim_refs={
                field.field_key: [str(ref) for ref in result.claim_refs]
                for field, _, result in results
            },
            prior_attempts=[
                {
                    "attempt_id": str(item.id),
                    "field_key": item.field_key,
                    "round": item.round,
                    "strategy_key": item.strategy_key,
                    "outcome": item.outcome.value,
                }
                for item in prior
            ],
            current_round_attempts=[
                {
                    "field_key": field.field_key,
                    "strategy_key": strategy.key,
                    "outcome": _outcome(result).value,
                    "stop_reason": result.stop_reason.value,
                    "claim_refs": [str(ref) for ref in result.claim_refs],
                }
                for field, strategy, result in results
            ],
            remaining_budget_cents=str(remaining) if remaining is not None else None,
            hard_round_cap=self._policy.max_rounds_for(tier),
        )

    def _dispose(
        self,
        attempt: CoverageAttempt,
        *,
        round_number: int,
        tier: str,
        judge_call: GoalJudgeCall,
        yield_rate: float,
    ) -> tuple[ResearchTerminalStatus | None, str | None, str, str]:
        if attempt.claim_refs:
            return ResearchTerminalStatus.FILLED, None, "filled", "A promotable claim was found."
        if attempt.outcome is ResearchAttemptOutcome.BUDGET_STOP:
            return (
                ResearchTerminalStatus.BUDGET_EXHAUSTED,
                None,
                "budget_exhausted",
                "Research stopped before another provider call because the budget was exhausted.",
            )
        if attempt.outcome is ResearchAttemptOutcome.BLOCKED:
            return (
                ResearchTerminalStatus.BLOCKED_BY_POLICY,
                None,
                "blocked_by_policy",
                "Research stopped because every permitted source was blocked by policy.",
            )
        if round_number >= self._policy.max_rounds_for(tier):
            return (
                ResearchTerminalStatus.UNFILLED_TERMINAL,
                None,
                "max_rounds",
                "Research stopped after the configured maximum number of rounds.",
            )
        if round_number > 1 and yield_rate < self._policy.marginal_yield_floor:
            return (
                ResearchTerminalStatus.UNFILLED_TERMINAL,
                None,
                "marginal_yield",
                "Research stopped because the latest round produced too little new evidence.",
            )
        allowed = self._policy.strategy_transitions.get(attempt.strategy_key, ())
        if not allowed:
            return (
                ResearchTerminalStatus.UNFILLED_TERMINAL,
                None,
                "strategies_exhausted",
                "Research exhausted every permitted strategy without finding evidence.",
            )
        recommendation = allowed[0]
        if (
            self._strategies[recommendation].dimensions
            == self._strategies[attempt.strategy_key].dimensions
        ):
            raise CoveragePolicyError("retry must change a stable strategy dimension")
        if not judge_call.valid:
            return (
                None,
                recommendation,
                "retry_permitted_evaluator_unavailable",
                "Another distinct strategy remains permitted; the independent coverage "
                "evaluation was unavailable.",
            )
        if judge_call.result is not None:
            assessment = next(
                (
                    item
                    for item in judge_call.result.assessments
                    if item.field_key == attempt.field_key
                ),
                None,
            )
            if (
                judge_call.result.sufficient_for_goal
                or assessment is None
                or not assessment.meaningful_gap_remaining
                or assessment.recommendation is not GoalJudgeRecommendation.CONTINUE
            ):
                return (
                    None,
                    recommendation,
                    "retry_permitted_evaluator_questions_value",
                    "Another distinct strategy remains permitted, but the independent coverage "
                    "evaluation recommends that the agent reassess whether the gap still matters.",
                )
        return None, recommendation, "retry_permitted", "Another distinct strategy is permitted."


def _outcome(result: WaterfallResult) -> ResearchAttemptOutcome:
    if result.claim_refs:
        return ResearchAttemptOutcome.CLAIMS_PRODUCED
    if result.stop_reason is StopReason.BUDGET_STOP:
        return ResearchAttemptOutcome.BUDGET_STOP
    if any(step.outcome is StepOutcome.GATE_SKIPPED for step in result.per_tier) and not any(
        step.outcome is StepOutcome.RESOLVED for step in result.per_tier
    ):
        return ResearchAttemptOutcome.BLOCKED
    return ResearchAttemptOutcome.NO_HIT


def _attempt_detail(outcome: ResearchAttemptOutcome) -> str:
    return {
        ResearchAttemptOutcome.CLAIMS_PRODUCED: "The strategy produced claim references.",
        ResearchAttemptOutcome.NO_HIT: "The strategy completed without a usable claim.",
        ResearchAttemptOutcome.BLOCKED: "Policy blocked every permitted source.",
        ResearchAttemptOutcome.BUDGET_STOP: "Budget policy stopped the strategy before spend.",
        ResearchAttemptOutcome.FAILED: "The strategy failed safely.",
    }[outcome]


def _attach_advice(
    result: RoundResult,
    advice: CoverageEvaluatorAdvice | None,
) -> RoundResult:
    if advice is None:
        return result
    assessments = advice.result.assessments if advice.result is not None else ()
    return result.model_copy(
        update={
            "evaluator_advice_id": advice.id,
            "evaluator_valid": advice.valid,
            "evaluator_sufficient_for_goal": (
                advice.result.sufficient_for_goal if advice.result is not None else None
            ),
            "evaluator_recommendations": tuple(item.recommendation for item in assessments),
            "evaluator_warnings": tuple(
                warning for item in assessments for warning in item.warning_codes
            ),
        }
    )
