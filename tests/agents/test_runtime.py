from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, cast
from uuid import UUID

from langchain.tools import tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from clue_agents import (
    AgentExecutionStatus,
    AgentPlan,
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    DelegationRequest,
    DelegationResult,
    GovernedOperationReceipt,
    ScriptedAgentChatModel,
    ValidatedOperation,
    ValidatedPlan,
    operation_id_for_plan_node,
)
from clue_agents.ports import AgentExecutionAdapter, ExecutionProgress
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.toolbelt_wiring import build_toolbelt
from clue_core import ExecutionId
from tests.agents.conftest import EXECUTION_ID, NOW, artifact, constitution
from tests.agents.test_contracts import context_manifest
from tests.db.conftest import run_async


class _Models:
    def __init__(self, response: AIMessage | Sequence[AIMessage]) -> None:
        self._responses = (response,) if isinstance(response, AIMessage) else tuple(response)

    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        return ScriptedAgentChatModel(responses=self._responses)


class _CaptureModelInput(BaseCallbackHandler):
    def __init__(self) -> None:
        self.messages: list[list[object]] = []

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[object]],
        **kwargs: Any,
    ) -> None:
        del serialized, kwargs
        self.messages = messages


class _Execution(AgentExecutionAdapter):
    def __init__(self) -> None:
        self.recovered: dict[str, object] = {}
        self.validated_plans: list[AgentPlan] = []

    async def validate_plan(
        self,
        *,
        plan: AgentPlan,
        constitution: object,
    ) -> ValidatedPlan:
        del constitution
        self.validated_plans.append(plan)
        operation_id = operation_id_for_plan_node(plan.execution_id, plan.steps[0].node_key)
        operation = ValidatedOperation(
            node_key=plan.steps[0].node_key,
            operation_id=operation_id,
            kind="tool",
            address=plan.steps[0].tool.address,  # type: ignore[union-attr]
            depends_on=plan.steps[0].depends_on,
            parameter_artifact_ref=artifact(f"{operation_id}.json"),
            parameter_sha256="a" * 64,
            estimated_cost_millicents=0,
            authority_sha256="b" * 64,
        )
        return ValidatedPlan(
            plan_id=plan.plan_id,
            execution_id=plan.execution_id,
            validated_plan_artifact_ref=artifact(f"{plan.plan_id}.json"),
            proposal_sha256="c" * 64,
            resource_manifest_sha256="d" * 64,
            operations=(operation,),
            max_parallelism=1,
            estimated_cost_millicents=0,
            budget_limit_millicents=0,
            validated_at=plan.proposed_at,
        )

    async def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        operation = plan.operations[0]
        receipt = GovernedOperationReceipt(
            node_key=operation.node_key,
            operation_id=operation.operation_id,
            kind="tool",
            address=operation.address,
            status=AgentExecutionStatus.COMPLETED,
            reference_values={"project_run_id": "run-42"},
        )
        self.recovered = {"operation_receipts": (receipt,)}
        yield ExecutionProgress(
            execution_id=plan.execution_id,
            status="completed",
            completed_node_keys=(operation.node_key,),
        )

    async def delegate(self, *, request: DelegationRequest) -> DelegationResult:
        del request
        raise NotImplementedError

    async def finalize(self, *, envelope: object) -> ArtifactRef:
        del envelope
        raise NotImplementedError

    def checkpointer(
        self,
        *,
        execution_id: ExecutionId,
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str]]:
        assert execution_id == EXECUTION_ID

        @asynccontextmanager
        async def opened() -> AsyncIterator[BaseCheckpointSaver[str]]:
            yield InMemorySaver()

        return opened()

    async def recover(self, *, execution_id: ExecutionId) -> Mapping[str, object]:
        assert execution_id == EXECUTION_ID
        return self.recovered


def _request() -> tuple[AgentTurnRequest, object]:
    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    trusted = constitution(
        profile_ref=resolved.profile_ref,
        resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
    )
    request = AgentTurnRequest(
        turn_id=UUID("00000000-0000-0000-0000-000000000642"),
        thread_id="thread-c64-runtime",
        constitution=trusted,
        user_message_artifact_ref=artifact("user-message.json"),
        requested_at=NOW,
    )
    return request, resolved


def test_real_deepagent_normal_stop_is_failed_without_finalize_authority() -> None:
    request, resolved = _request()
    execution = _Execution()
    runtime = DeepAgentTurnRuntime(
        models=_Models(AIMessage(content="A polished but uncommitted answer.")),
        execution=execution,
        max_runtime_s=5,
    )
    context = AssembledAgentContext(
        manifest=context_manifest(),
        messages=(HumanMessage(content="Do the work."),),
    )
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    capture = _CaptureModelInput()

    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=context,
            backend=None,
            governed_tools=factory.build(),
            callbacks=(capture,),
        )
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "missing_finalize"
    assert outcome.finalization_ref is None
    system = next(
        message for message in capture.messages[0] if getattr(message, "type", None) == "system"
    )
    assert str(system.content).endswith("## End resolved resource and capability map")


def test_real_deepagent_accepts_only_adapter_recovered_durable_finalize() -> None:
    request, resolved = _request()
    execution = _Execution()
    finalization_ref = artifact("finalization.json")

    @tool(return_direct=True)
    async def finalize_turn() -> str:
        """Commit the deterministic test finalization through the injected adapter fake."""

        execution.recovered = {
            "finalization_status": "completed",
            "finalization_ref": finalization_ref,
        }
        return finalization_ref.model_dump_json()

    runtime = DeepAgentTurnRuntime(
        models=_Models(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "finalize_turn",
                        "args": {},
                        "id": "finalize-c64",
                        "type": "tool_call",
                    }
                ],
            )
        ),
        execution=execution,
        max_runtime_s=5,
    )
    context = AssembledAgentContext(
        manifest=context_manifest(),
        messages=(HumanMessage(content="Do and finalize the work."),),
    )
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    governed = factory.build()

    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=context,
            backend=None,
            governed_tools=(*governed[:-1], finalize_turn),
        )
    )

    assert outcome.status is AgentExecutionStatus.COMPLETED
    assert outcome.finalization_ref == finalization_ref


def test_c65_filters_default_general_subagent_and_rejects_fabricated_task_call() -> None:
    request, resolved = _request()
    execution = _Execution()
    finalization_ref = artifact("c65-task-filter-finalization.json")

    @tool(return_direct=True)
    async def finalize_turn() -> str:
        """Commit the deterministic test finalization through the injected adapter fake."""

        execution.recovered = {
            "finalization_status": "awaiting_input",
            "finalization_ref": finalization_ref,
        }
        return finalization_ref.model_dump_json()

    runtime = DeepAgentTurnRuntime(
        models=_Models(
            (
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {
                                "description": "Try to bypass C6.5 role activation.",
                                "prompt": "Use unavailable specialist authority.",
                                "subagent_type": "general-purpose",
                            },
                            "id": "fabricated-task-c65",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finalize_turn",
                            "args": {},
                            "id": "finalize-task-filter-c65",
                            "type": "tool_call",
                        }
                    ],
                ),
            )
        ),
        execution=execution,
        max_runtime_s=5,
    )
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    governed = factory.build()
    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content="Use a specialist."),),
            ),
            backend=None,
            governed_tools=(*governed[:-1], finalize_turn),
        )
    )

    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert outcome.finalization_ref == finalization_ref
    assert execution.validated_plans == []


def test_real_deepagent_tool_call_uses_exact_governed_descriptor_wrapper() -> None:
    request, resolved = _request()
    registry = build_toolbelt(storage=None, gateway=None)
    execution = _Execution()
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=registry,
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    runtime = DeepAgentTurnRuntime(
        models=_Models(
            (
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "synthesize_icps",
                            "args": {
                                "client_entity_id": ("00000000-0000-0000-0000-000000000999"),
                            },
                            "id": "synthesize-stage0-c65",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Tool completed, but I did not finalize."),
            )
        ),
        execution=execution,
        max_runtime_s=5,
    )
    context = AssembledAgentContext(
        manifest=context_manifest(),
        messages=(HumanMessage(content="Synthesize the ICP."),),
    )

    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=context,
            backend=None,
            governed_tools=factory.build(),
        )
    )

    assert outcome.failure_code == "missing_finalize"
    assert len(execution.validated_plans) == 1
    proposed = execution.validated_plans[0].steps[0]
    assert proposed.tool.address == "synthesize_icps@1"  # type: ignore[union-attr]
    assert proposed.arguments == {  # type: ignore[union-attr]
        "client_entity_id": "00000000-0000-0000-0000-000000000999",
        "kb_version": None,
        "product_id": None,
    }
