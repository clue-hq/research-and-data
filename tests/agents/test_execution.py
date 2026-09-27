from __future__ import annotations

from uuid import UUID

import pytest

from clue_agents.contracts import (
    AgentPlan,
    AgentRole,
    PlanDelegationStep,
    PlanToolStep,
)
from clue_agents.execution import (
    AgentExecutionStatus,
    AgentPlanPolicy,
    GovernedOperationReceipt,
    authority_sha256,
    operation_id_for_plan_node,
    review_agent_plan,
)
from tests.agents.conftest import EXECUTION_ID, NOW, artifact, constitution, domain_ref
from tests.agents.test_contracts import profile, tool_pin


def _plan(*steps: PlanToolStep | PlanDelegationStep) -> AgentPlan:
    return AgentPlan(
        plan_id=UUID("00000000-0000-0000-0000-000000000641"),
        execution_id=EXECUTION_ID,
        role=AgentRole.HEAD_OF_ABM,
        goal_ref=artifact("goal.json"),
        steps=steps,
        proposed_at=NOW,
    )


def _policy(**updates: int) -> AgentPlanPolicy:
    values = {
        "max_nodes": 24,
        "max_dependency_depth": 8,
        "max_fanout": 4,
        "max_parallelism": 4,
        "max_rounds": 12,
        "max_delegations": 4,
        "max_delegation_depth": 1,
        "budget_limit_millicents": 10_000,
    }
    values.update(updates)
    return AgentPlanPolicy(**values)


def test_authorized_500_round_allowance_has_a_finite_runtime_ceiling() -> None:
    from clue_agents.runtime import DeepAgentTurnRuntime, superstep_ceiling

    assert _policy(max_rounds=500).max_rounds == 500
    runtime = DeepAgentTurnRuntime(models=None, execution=None, max_rounds=500)  # type: ignore[arg-type]
    assert runtime._recursion_limit == superstep_ceiling(500)
    with pytest.raises(ValueError):
        _policy(max_rounds=501)
    with pytest.raises(ValueError, match="round ceiling"):
        DeepAgentTurnRuntime(models=None, execution=None, max_rounds=501)  # type: ignore[arg-type]


def test_operation_and_authority_identities_are_stable_and_authority_sensitive() -> None:
    runtime_profile = profile()
    trusted = constitution()

    first = operation_id_for_plan_node(EXECUTION_ID, "collect")
    assert first == operation_id_for_plan_node(EXECUTION_ID, "collect")
    assert first != operation_id_for_plan_node(EXECUTION_ID, "verify")

    digest = authority_sha256(
        constitution=trusted,
        profile=runtime_profile,
        node_key="collect",
        address=runtime_profile.tools[0].address,
    )
    assert digest == authority_sha256(
        constitution=trusted,
        profile=runtime_profile,
        node_key="collect",
        address=runtime_profile.tools[0].address,
    )
    assert digest != authority_sha256(
        constitution=trusted.model_copy(update={"actor_id": "another-user"}),
        profile=runtime_profile,
        node_key="collect",
        address=runtime_profile.tools[0].address,
    )


def test_plan_review_accepts_exact_tools_and_bounded_fresh_wake_delegation() -> None:
    runtime_profile = profile()
    plan = _plan(
        PlanToolStep(
            node_key="read",
            tool=runtime_profile.tools[0],
            arguments={"query": "project"},
            purpose="Read the governed project projection.",
        ),
        PlanDelegationStep(
            node_key="research",
            depends_on=("read",),
            role=AgentRole.RESEARCH,
            task_artifact_ref=artifact("task.json"),
            granted_paths=("context", "work"),
            domain_refs=(domain_ref("account-1"),),
            purpose="Wake a research specialist with explicit references.",
        ),
    )

    review = review_agent_plan(
        plan=plan,
        constitution=constitution(),
        profile=runtime_profile,
        policy=_policy(),
    )

    assert review.valid
    assert review.dependency_depth == 2
    assert review.maximum_fanout == 1


def test_plan_review_rejects_authority_scope_and_all_hard_envelope_bypasses() -> None:
    runtime_profile = profile()
    plan = _plan(
        PlanToolStep(
            node_key="unknown",
            tool=tool_pin("not_allowed"),
            purpose="Attempt an unavailable capability.",
        ),
        PlanDelegationStep(
            node_key="wrong_child",
            role=AgentRole.REVIEWER,
            task_artifact_ref=artifact("task.json"),
            granted_paths=("outputs",),
            purpose="Attempt an ungranted child role.",
        ),
        PlanToolStep(
            node_key="wide_a",
            tool=runtime_profile.tools[0],
            purpose="Exceed fanout.",
        ),
        PlanToolStep(
            node_key="wide_b",
            tool=runtime_profile.tools[0],
            purpose="Exceed fanout.",
        ),
    )
    review = review_agent_plan(
        plan=plan,
        constitution=constitution(),
        profile=runtime_profile,
        policy=_policy(max_nodes=3, max_fanout=2, max_delegations=0),
    )

    assert not review.valid
    assert {
        "tool_not_allowed",
        "delegation_not_allowed",
        "node_ceiling",
        "fanout_ceiling",
        "delegation_ceiling",
    } <= {issue.code for issue in review.issues}


def test_bounded_receipts_require_durable_delegation_output_and_reject_blob_sized_values() -> None:
    operation_id = operation_id_for_plan_node(EXECUTION_ID, "delegate")
    with pytest.raises(ValueError, match="durable reference"):
        GovernedOperationReceipt(
            node_key="delegate",
            operation_id=operation_id,
            kind="delegation",
            address="research",
            status=AgentExecutionStatus.COMPLETED,
        )
    with pytest.raises(ValueError, match="16 KiB"):
        GovernedOperationReceipt(
            node_key="tool",
            operation_id=operation_id,
            kind="tool",
            address="read_project@1",
            status=AgentExecutionStatus.COMPLETED,
            reference_values={"forbidden_blob": "x" * 20_000},
        )
