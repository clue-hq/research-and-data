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
# The exact sentence ``interview._exact_quote`` refused on the live run.
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
                            message="statements[0].quote_end exceeds the answer length",
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


def _route_call(call_id: str, *, quote_end: int = 41) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "record_interview_answer",
                # No turn identity, no answer body, and no project scope: PC-C8 §6a moved all of
                # them behind the execution seam (the turn's from its capture record, the brand
                # and client from the constitution), and this schema now refuses them outright
                # ("extra inputs are not permitted"). The model sends routing plus offsets into a
                # message the platform loads.
                "args": {
                    "statements": [
                        {
                            "route": "project_state",
                            "route_key": "target_segment",
                            "quote_start": 0,
                            "quote_end": quote_end,
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
            _route_call("route-corrected", quote_end=len(_ANSWER)),
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
            _route_call("route-corrected", quote_end=len(_ANSWER)),
            _finalize_call("finalize", status="awaiting_input", user_message=_QUESTION),
        ),
        execution=execution,
    )

    assert len(calls.batches) == 3
    feedback = str(calls.batches[1][-1].content)
    assert "tool_input_invalid" in feedback
    assert "plan.steps[0].arguments" in feedback
    assert "quote_end exceeds the answer length" in feedback
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
            _route_call("route-corrected", quote_end=len(_ANSWER)),
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


def test_a_fourth_refusal_fails_the_turn_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repair budget is spent, and then the wrapper raises exactly as it always did.

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
    execution = _RefusingExecution(refusals=9)
    outcome, calls = _run(
        tuple(_route_call(f"route-{ordinal}") for ordinal in range(4)),
        execution=execution,
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "runtime_error"
    assert outcome.finalization_ref is None
    assert execution.envelopes == []
    # Three visible repairs, then the fourth refusal ends the turn: four model calls, no more.
    assert len(calls.batches) == 4
    assert [event for event, _ in emitted] == ["agent.tool_repair"] * 4
    assert [fields["attempt"] for _, fields in emitted] == [1, 2, 3, 4]
    assert [fields["exhausted"] for _, fields in emitted] == [False, False, False, True]
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
            _route_call("route-corrected", quote_end=len(_ANSWER)),
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
