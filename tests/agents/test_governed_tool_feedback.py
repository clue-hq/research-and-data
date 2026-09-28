"""A refused governed invocation is model-visible feedback, not a killed turn.

The live Stage-0 defect (F7 in ``_memory/2026-07-31-stage0-structured-output-failure-chain.md``):
Terra routed a product fact through ``record_interview_answer@1`` but paraphrased one claim value,
so ``clue_research.stage0.interview._exact_quote`` correctly refused it — "claim value is not
textually entailed by the exact interview quote". That refusal is right and stays. What was wrong
is what happened next: ``GovernedAgentToolFactory``'s wrapper turned the non-completed execution
into a bare ``RuntimeError`` (and let ``AgentPlanRejected`` propagate raw), the exception escaped
the LangChain ``StructuredTool`` coroutine, LangGraph died, and the turn ended ``runtime_error``
with **zero** feedback to the model — which could have fixed a single quoted string.

These tests pin the same shape task 3 gave ``finalize_turn``: the refusal comes back as a readable
tool result, the model repairs it, the corrected call commits, and a model that keeps failing is
bounded and fails the turn closed with nothing recorded.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from clue_agents import (
    AgentExecutionStatus,
    AgentPlanIssue,
    AgentPlanRejected,
    AgentPlanReview,
    AgentRole,
    AgentTurnRequest,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    FinalizeStatus,
    GovernedOperationReceipt,
    ValidatedPlan,
)
from clue_agents.ports import ExecutionProgress, OperationFailure
from clue_api import agent_runtime_wiring as wiring_module
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.conftest import NOW, artifact, constitution
from tests.agents.test_contracts import context_manifest
from tests.agents.test_finalize_contract import (
    _CountModelCalls,
    _finalize_call,
    _FinalizingExecutionAdapter,
)
from tests.agents.test_runtime import (
    _DelegationArtifacts,
    _EmptyOutputBackend,
    _Models,
)
from tests.db.conftest import run_async

_ANSWER = "We sell an AI scheduling assistant to specialist healthcare practices."
_QUESTION = "Which specialist practices should this project prioritize first?"
# The exact sentence ``interview._check_value_entailment`` refused on the live run.
_VERIFIER_REFUSAL = "claim value is not textually entailed by the exact interview quote"


class _RefusingExecution(_FinalizingExecutionAdapter):
    """Governed execution that refuses the first ``refusals`` operations, then commits.

    The refusal shape is the one the real ``C5AgentExecutionAdapter`` produces for a tool that
    raises: a ``failed`` progress carrying the operation's own reason (pinned against the real
    adapter in ``tests/api/test_agent_execution_wiring.py``).
    """

    def __init__(self, *, refusals: int = 1, reject_plans: int = 0) -> None:
        super().__init__()
        self.refusals = refusals
        self.reject_plans = reject_plans
        self.executed: list[ValidatedPlan] = []
        self.rejected = 0

    async def validate_plan(self, *, plan: Any, constitution: Any) -> ValidatedPlan:
        if self.rejected < self.reject_plans:
            self.rejected += 1
            raise AgentPlanRejected(
                AgentPlanReview(
                    proposal_sha256="e" * 64,
                    issues=(
                        AgentPlanIssue(
                            code="tool_input_invalid",
                            location="plan.steps[0].arguments",
                            message=(
                                "statements[0].quote was not found in the captured user message"
                            ),
                        ),
                    ),
                    dependency_depth=1,
                    maximum_fanout=1,
                )
            )
        return await super().validate_plan(plan=plan, constitution=constitution)

    async def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        self.executed.append(plan)
        operation = plan.operations[0]
        if len(self.executed) <= self.refusals:
            yield ExecutionProgress(
                execution_id=plan.execution_id,
                status="failed",
                failed_node_keys=(operation.node_key,),
                failures=(
                    OperationFailure(
                        node_key=operation.node_key,
                        address=operation.address,
                        error_type="ValueError",
                        message=_VERIFIER_REFUSAL,
                    ),
                ),
            )
            return
        receipt = GovernedOperationReceipt(
            node_key=operation.node_key,
            operation_id=operation.operation_id,
            kind="tool",
            address=operation.address,
            status=AgentExecutionStatus.COMPLETED,
            reference_values={"statement_count": 1},
        )
        self.recovered = {"operation_receipts": (receipt,)}
        yield ExecutionProgress(
            execution_id=plan.execution_id,
            status="completed",
            completed_node_keys=(operation.node_key,),
        )


def _route_call(call_id: str, *, quote: str = _ANSWER[:41]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "record_interview_answer",
                # No turn identity, no answer body, and no project scope: PC-C8 §6a moved all of
                # them behind the execution seam (the turn's from its capture record, the brand
                # and client from the constitution), and this schema now refuses them outright
                # ("extra inputs are not permitted"). PC-C8 §6c-a then took the offsets too: the
                # model sends routing plus the span it copied, and the engine locates it.
                "args": {
                    "statements": [
                        {
                            "route": "project_state",
                            "route_key": "target_segment",
                            "quote": quote,
                        }
                    ],
                },
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def _run(
    responses: tuple[AIMessage, ...],
    *,
    execution: _RefusingExecution,
) -> tuple[Any, _CountModelCalls]:
    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    request = AgentTurnRequest(
        turn_id=UUID("00000000-0000-0000-0000-0000000006f7"),
        thread_id="thread-governed-tool-feedback",
        constitution=constitution(
            profile_ref=resolved.profile_ref,
            resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
        ),
        user_message_artifact_ref=artifact("user-message.json"),
        requested_at=NOW,
    )
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, SimpleNamespace(backend=_EmptyOutputBackend())),
        artifacts=cast(Any, _DelegationArtifacts()),
    )
    runtime = DeepAgentTurnRuntime(
        models=_Models(responses),
        execution=cast(Any, execution),
        max_runtime_s=10,
    )
    calls = _CountModelCalls()
    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content=_ANSWER),),
            ),
            backend=None,
            governed_tools=factory.build(),
            callbacks=(calls,),
        )
    )
    return outcome, calls


def test_a_refused_operation_is_repaired_from_visible_tool_feedback() -> None:
    execution = _RefusingExecution(refusals=1)
    outcome, calls = _run(
        (
            _route_call("route-paraphrased"),
            _route_call("route-corrected", quote=_ANSWER),
            _finalize_call("finalize", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )

    # The refusal reached the model, in the verifier's own words, and said plainly that the
    # operation did not happen.
    assert len(calls.batches) == 3
    feedback = str(calls.batches[1][-1].content)
    assert _VERIFIER_REFUSAL in feedback
    assert '"recorded":false' in feedback
    assert "operation_failed" in feedback
    # ... the model corrected its arguments, the second attempt committed, and the turn finished.
    assert len(execution.executed) == 2
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert outcome.finalization_ref is not None
    assert [envelope.status for envelope in execution.envelopes] == [FinalizeStatus.AWAITING_INPUT]


def test_a_rejected_plan_is_visible_instead_of_propagating_raw() -> None:
    """``AgentPlanRejected`` used to escape the tool coroutine and kill the graph.

    It carries exactly what a model needs — the rejection code and the location it applies to —
    so it is the cheapest repairable failure in the system and was the most expensive to hit.
    """

    execution = _RefusingExecution(refusals=0, reject_plans=1)
    outcome, calls = _run(
        (
            _route_call("route-invalid-shape"),
            _route_call("route-corrected", quote=_ANSWER),
            _finalize_call("finalize", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )

    assert len(calls.batches) == 3
    feedback = str(calls.batches[1][-1].content)
    assert "tool_input_invalid" in feedback
    assert "plan.steps[0].arguments" in feedback
    assert "quote was not found in the captured user message" in feedback
    assert '"recorded":false' in feedback
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert [envelope.status for envelope in execution.envelopes] == [FinalizeStatus.AWAITING_INPUT]


def test_a_retry_is_a_new_operation_and_cannot_collide_with_the_refused_one() -> None:
    """Every attempt carries a fresh ``tool_call_id``, so nothing is replayed onto a dead key.

    ``node_key`` is derived from the model's ``tool_call_id``, ``plan_id`` from
    ``(execution_id, node_key)``, and the A9 ``operation_id`` from ``(execution_id, node_key)`` —
    so a corrective retry is a *new* logical operation end to end. It cannot inherit the failed
    attempt's idempotency identity, and the failed attempt's durable record stands untouched.
    """

    execution = _RefusingExecution(refusals=1)
    outcome, _ = _run(
        (
            _route_call("route-paraphrased"),
            _route_call("route-corrected", quote=_ANSWER),
            _finalize_call("finalize", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )

    proposed = list(execution.validated_plans)
    assert len(proposed) == 2
    assert proposed[0].steps[0].node_key != proposed[1].steps[0].node_key
    assert proposed[0].plan_id != proposed[1].plan_id
    operations = [plan.operations[0].operation_id for plan in execution.executed]
    assert len(set(operations)) == 2
    # Only the corrected operation committed.
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT


def test_an_eleventh_refusal_fails_the_turn_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The complete eleventh failed batch stops the next model call.

    ``DeepAgentTurnRuntime`` already caps the graph at ``max_rounds * 2 + 4`` supersteps, so this
    budget is not what makes the loop terminate — it is what stops the turn paying for ~24 further
    model calls once the model has stopped converging.
    """

    emitted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        wiring_module,
        "log",
        SimpleNamespace(warning=lambda event, **fields: emitted.append((event, fields))),
    )
    execution = _RefusingExecution(refusals=11)
    outcome, calls = _run(
        tuple(_route_call(f"route-{ordinal}") for ordinal in range(11)),
        execution=execution,
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "runtime_error"
    assert outcome.finalization_ref is None
    assert execution.envelopes == []
    # Ten corrective rounds are allowed; the eleventh failed batch exhausts them.
    assert len(calls.batches) == 11
    assert [event for event, _ in emitted] == ["agent.tool_repair"] * 11
    assert [fields["attempt"] for _, fields in emitted] == list(range(1, 12))
    assert [fields["exhausted"] for _, fields in emitted] == [False] * 10 + [True]
    # W10 spares only an effect-free read refused by precondition; a write refused on its value
    # still pays, so every one of these eleven spends the budget.
    assert [fields["budgeted"] for _, fields in emitted] == [True] * 11
    assert emitted[0][1]["error_type"] == "ValueError"
    assert emitted[0][1]["reasons"] == [f"ValueError: {_VERIFIER_REFUSAL}"]


def test_every_converted_refusal_is_operator_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal the model repairs must still reach the operator, or the diagnosis is lost."""

    emitted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        wiring_module,
        "log",
        SimpleNamespace(warning=lambda event, **fields: emitted.append((event, fields))),
    )
    execution = _RefusingExecution(refusals=0, reject_plans=1)
    _run(
        (
            _route_call("route-invalid-shape"),
            _route_call("route-corrected", quote=_ANSWER),
            _finalize_call("finalize", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )

    assert [event for event, _ in emitted] == ["agent.tool_repair"]
    event, fields = emitted[0]
    assert fields["error"] == "plan_rejected"
    assert fields["error_type"] == "AgentPlanRejected"
    assert fields["address"] == "record_interview_answer@1"
    assert fields["attempt"] == 1
    assert fields["exhausted"] is False
    assert fields["budgeted"] is True


def _read_call(call_id: str) -> AIMessage:
    """A model turn that calls an effect-free read (the shape of the 2026-09-13 fan-out)."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": call_id,
                "name": "read_project_accounts",
                # ``project_id`` is trusted authority: ``_with_trusted_runtime`` strips it from
                # the model-visible schema, so a model that sent one would get an ordinary
                # validation error instead of ever reaching the governed wrapper.
                "args": {"limit": 25, "offset": 0},
                "type": "tool_call",
            }
        ],
    )


class _RefusingReadExecution(_RefusingExecution):
    """Refuses with the read tools' own error type."""

    async def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        self.executed.append(plan)
        operation = plan.operations[0]
        if len(self.executed) <= self.refusals:
            yield ExecutionProgress(
                execution_id=plan.execution_id,
                status="failed",
                failed_node_keys=(operation.node_key,),
                failures=(
                    OperationFailure(
                        node_key=operation.node_key,
                        address=operation.address,
                        error_type="PreconditionFailed",
                        message="tool preconditions unmet: overview_not_written",
                    ),
                ),
            )
            return
        async for progress in super().execute(plan=plan):  # the committing path
            yield progress


def test_honest_read_refusals_do_not_spend_the_repair_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W10: five parallel account reads answered ``overview_not_written`` killed a live turn.

    A ``PreconditionFailed`` from an effect-free read is information, not a misread contract.
    """

    emitted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        wiring_module,
        "log",
        SimpleNamespace(warning=lambda event, **fields: emitted.append((event, fields))),
    )
    execution = _RefusingReadExecution(refusals=5)
    outcome, calls = _run(
        (
            *(_read_call(f"read-{ordinal}") for ordinal in range(5)),
            _finalize_call("finalize", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )

    assert outcome.status is not AgentExecutionStatus.FAILED
    assert [fields["budgeted"] for _, fields in emitted] == [False] * 5
    assert all(fields["exhausted"] is False for _, fields in emitted)
    assert len(calls.batches) == 6


def test_seven_parallel_refusals_all_reach_the_next_model_round() -> None:
    execution = _RefusingExecution(refusals=7)
    batch = AIMessage(
        content="", tool_calls=[_route_call(f"bad-{i}").tool_calls[0] for i in range(7)]
    )
    outcome, calls = _run(
        (
            batch,
            _route_call("corrected", quote=_ANSWER),
            _finalize_call("final", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert len(execution.executed) == 8
    assert len(calls.batches) == 3
    feedback = [m for m in calls.batches[1] if getattr(m, "type", None) == "tool"]
    assert len(feedback) == 7
    assert all(_VERIFIER_REFUSAL in str(m.content) for m in feedback)


def test_failed_batch_preserves_successful_sibling_without_repeating_it() -> None:
    execution = _RefusingExecution(refusals=7)
    batch = AIMessage(
        content="", tool_calls=[_route_call(f"sibling-{i}").tool_calls[0] for i in range(8)]
    )
    outcome, calls = _run(
        (
            batch,
            _route_call("repair-only", quote=_ANSWER),
            _finalize_call("final", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert len(execution.executed) == 9
    feedback = [m for m in calls.batches[1] if getattr(m, "type", None) == "tool"]
    assert len(feedback) == 8
    assert sum(_VERIFIER_REFUSAL in str(m.content) for m in feedback) == 7


def test_repair_round_state_survives_compaction_and_does_not_count_batch_twice() -> None:
    from langchain_core.messages import ToolMessage

    from clue_agents.tool_recovery import ToolRepairRoundsMiddleware

    async def case():
        middleware = ToolRepairRoundsMiddleware()
        batch = _route_call("after-compaction")
        state = {
            "messages": [
                batch,
                ToolMessage(
                    content='{"governed_repair_budgeted":true}', tool_call_id="after-compaction"
                ),
            ],
            "tool_repair_turn": "None",
            "tool_repair_rounds": 2,
            "tool_repair_batch": ["archived-batch"],
        }
        update = await middleware.abefore_model(state, None)
        assert update["tool_repair_rounds"] == 3
        state.update(update)
        assert await middleware.abefore_model(state, None) is None

    run_async(case())


def test_finalize_waits_for_sibling_results_instead_of_committing_mid_batch():
    execution = _RefusingExecution(refusals=0)
    batch = AIMessage(
        content="",
        tool_calls=[
            _route_call("successful-work", quote=_ANSWER).tool_calls[0],
            _finalize_call("premature", status="awaiting_input", user_message=_QUESTION).tool_calls[
                0
            ],
        ],
    )
    outcome, calls = _run(
        (batch, _finalize_call("settled", status="awaiting_input", user_message=_QUESTION)),
        execution=execution,
    )
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert len(execution.executed) == 1
    assert len(execution.envelopes) == 1
    assert len(calls.batches) == 2
    assert "Call finalize_turn alone" in str(calls.batches[1][-1].content)


def test_the_tenth_corrective_round_can_succeed() -> None:
    execution = _RefusingExecution(refusals=10)
    outcome, calls = _run(
        (
            *(_route_call(f"failed-{i}") for i in range(10)),
            _route_call("tenth-correction", quote=_ANSWER),
            _finalize_call("final", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert len(execution.executed) == 11
    assert len(calls.batches) == 12
