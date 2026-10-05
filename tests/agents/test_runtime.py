from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain.tools import tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
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
    ExactAgentToolSurfaceMiddleware,
    GovernedOperationReceipt,
    ProjectContextArtifact,
    ScriptedAgentChatModel,
    SpecialistTaskEnvelope,
    ValidatedOperation,
    ValidatedPlan,
    VersionedWriteOutcome,
    WorkspaceEntry,
    operation_id_for_plan_node,
)
from clue_agents.compaction import CompactionSettings
from clue_agents.contracts import PlanDelegationStep
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


class _NeverRespondingModel(ScriptedAgentChatModel):
    async def _agenerate(self, *args: Any, **kwargs: Any):
        del args, kwargs
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _NeverRespondingModels:
    def build(self, **kwargs: Any) -> _NeverRespondingModel:
        del kwargs
        return _NeverRespondingModel(responses=(AIMessage(content="unreachable"),))


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
        self.recover_calls = 0

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
        self.recover_calls += 1
        return self.recovered


class _ReadinessResponseExecution(_Execution):
    """Exact fake receipt + captured finalization for the Stage-0 terminology regression."""

    def __init__(self) -> None:
        super().__init__()
        self.envelope: object | None = None

    async def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        operation = plan.operations[0]
        receipt = GovernedOperationReceipt(
            node_key=operation.node_key,
            operation_id=operation.operation_id,
            kind="tool",
            address=operation.address,
            status=AgentExecutionStatus.COMPLETED,
            reference_values={
                "readiness_decision_id": "00000000-0000-4000-8000-000000000811",
                "gate": "icp_synthesis",
                "verdict": "ready",
                "coverage_ratio": 7 / 9,
                "verified_claims": 0,
                "available_field_keys": ["client.product"],
                "reason_codes": [],
                "readiness_policy_version": 1,
            },
        )
        self.recovered = {"operation_receipts": (receipt,)}
        yield ExecutionProgress(
            execution_id=plan.execution_id,
            status="completed",
            completed_node_keys=(operation.node_key,),
        )

    async def finalize(self, *, envelope: object) -> ArtifactRef:
        self.envelope = envelope
        ref = artifact("stage0-terminology-finalization.json")
        self.recovered.update(
            {
                "finalization_status": "completed",
                "finalization_ref": ref,
            }
        )
        return ref


class _DelegationExecution(_Execution):
    async def validate_plan(
        self,
        *,
        plan: AgentPlan,
        constitution: object,
    ) -> ValidatedPlan:
        del constitution
        self.validated_plans.append(plan)
        step = plan.steps[0]
        assert isinstance(step, PlanDelegationStep)
        operation_id = operation_id_for_plan_node(plan.execution_id, step.node_key)
        operation = ValidatedOperation(
            node_key=step.node_key,
            operation_id=operation_id,
            kind="delegation",
            address=step.role.value,
            depends_on=(),
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
            kind="delegation",
            address=operation.address,
            status=AgentExecutionStatus.COMPLETED,
            artifact_refs=(artifact("specialist-output.md"),),
        )
        self.recovered = {"operation_receipts": (receipt,)}
        yield ExecutionProgress(
            execution_id=plan.execution_id,
            status="completed",
            completed_node_keys=(operation.node_key,),
        )


class _DelegationArtifacts:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def persist_body(
        self,
        *,
        workspace_id: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactRef:
        digest = hashlib.sha256(data).hexdigest()
        ref = ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=f"{workspace_id}/{digest}",
            sha256=digest,
            media_type=media_type,
            byte_count=len(data),
        )
        self.data[ref.artifact_key] = data
        return ref

    async def read(self, ref: ArtifactRef) -> bytes:
        return self.data[ref.artifact_key]


class _DelegationBackend:
    _BODIES = {
        "context/account.md": "Canonical account evidence.",
        "context/project/account-deep-steering.json": (
            '{"card_kind":"account_deep_steering","launch_state":"not_launched"}'
        ),
        "context/project/research-directive.json": (
            '{"directive_ref":"research-directive:directive-1:v1"}'
        ),
    }

    async def stat_entry(self, path: str) -> WorkspaceEntry:
        body = self._BODIES[path].encode()
        return WorkspaceEntry(
            path=path,
            kind="file",
            byte_count=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            read_only=True,
        )

    async def read_text(self, path: str) -> str:
        return self._BODIES[path]


class _FinalizingExecution:
    def __init__(self) -> None:
        self.envelope: object | None = None

    async def check_finalizable(self, *, status: object) -> None:
        del status

    async def finalize(self, *, envelope: object) -> ArtifactRef:
        self.envelope = envelope
        return artifact("finalization-envelope.json")


class _EmptyOutputBackend:
    """A turn that froze nothing and wrote no document — the empty case of both finalize reads."""

    written_documents: tuple[VersionedWriteOutcome, ...] = ()

    async def snapshot_outputs(self, *, empty_after: bool = False) -> tuple[ArtifactRef, ...]:
        del empty_after
        return ()


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
        models=_Models(
            (
                AIMessage(content="A polished but uncommitted answer."),
                AIMessage(content="I still refuse to invoke the required finalizer."),
            )
        ),
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


def test_compaction_settings_are_read_off_the_event_loop() -> None:
    """2026-10-05: ``compaction_for`` reads the model catalogue over the network. Called on the
    event loop it froze a fleet worker for 105 s, long enough to lose every lease it held, so the
    runtime reads it in a thread."""
    request, resolved = _request()
    execution = _Execution()
    read_on: list[int] = []

    def compaction_for(model_id: str) -> CompactionSettings:
        del model_id
        read_on.append(threading.get_ident())
        return CompactionSettings.fallback()

    runtime = DeepAgentTurnRuntime(
        models=_Models((AIMessage(content="No finalizer."), AIMessage(content="Still none."))),
        execution=execution,
        max_runtime_s=5,
        compaction_for=compaction_for,
    )
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    loop_thread: list[int] = []

    async def run() -> Any:
        loop_thread.append(threading.get_ident())
        return await runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(), messages=(HumanMessage(content="Do the work."),)
            ),
            backend=None,
            governed_tools=factory.build(),
        )

    run_async(run())

    assert read_on, "the runtime read its compaction settings"
    assert loop_thread[0] not in read_on


def test_real_deepagent_timeout_recovers_and_never_manufactures_finalization() -> None:
    request, resolved = _request()
    execution = _Execution()
    runtime = DeepAgentTurnRuntime(
        models=cast(Any, _NeverRespondingModels()),
        execution=execution,
        max_runtime_s=0.01,
    )
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content="Wait indefinitely."),),
            ),
            backend=None,
            governed_tools=factory.build(),
        )
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "agent_timeout"
    assert outcome.finalization_ref is None
    assert execution.recover_calls == 1


def test_exact_tool_surface_requires_a_tool_call_until_governed_finalize() -> None:
    request, resolved = _request()
    execution = _Execution()
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    framework_tools = [
        {"name": name}
        for name in (
            "compact_conversation",
            "edit_file",
            "glob",
            "grep",
            "ls",
            "read_file",
            "write_file",
            "write_todos",
        )
    ]
    governed_tools = factory.build()
    effective_names = {tool.name for tool in governed_tools}
    assert "finalize_turn" in effective_names
    assert {"list_product_knowledge", "inspect_product_claim"}.isdisjoint(effective_names)
    model_request = ModelRequest(
        model=ScriptedAgentChatModel(responses=(AIMessage(content="unused"),)),
        messages=[HumanMessage(content="Ask the next useful question.")],
        system_message=SystemMessage(content="Base prompt."),
        tools=[*governed_tools, *framework_tools],
    )
    observed: dict[str, object] = {}

    async def handler(value: ModelRequest) -> ModelResponse[None]:
        def name(item: object) -> str:
            if isinstance(item, dict):
                return str(item["name"])
            return str(cast(Any, item).name)

        calls = observed.setdefault("calls", [])
        assert isinstance(calls, list)
        calls.append(
            {
                "tool_choice": value.tool_choice,
                "tool_names": tuple(name(tool) for tool in value.tools),
                "messages": tuple(value.messages),
            }
        )
        if len(calls) == 1:
            return ModelResponse(result=[AIMessage(content="What problem does the product solve?")])
        return ModelResponse(
            result=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finalize_turn",
                            "args": {
                                "status": "awaiting_input",
                                "user_message": "What problem does the product solve?",
                            },
                            "id": "finalize-recovery",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        )

    run_async(
        ExactAgentToolSurfaceMiddleware(
            profile=resolved,
            effective_governed_tool_names=effective_names,
        ).awrap_model_call(model_request, handler)
    )

    calls = observed["calls"]
    assert isinstance(calls, list)
    assert calls[0]["tool_choice"] == "required"
    assert "finalize_turn" in calls[0]["tool_names"]
    assert calls[1]["tool_choice"] == "finalize_turn"
    assert calls[1]["tool_names"] == ("finalize_turn",)
    assert "What problem does the product solve?" in str(calls[1]["messages"])


def test_governed_surface_uses_tool_specific_model_guidance_without_moving_schema_pins() -> None:
    request, resolved = _request()
    toolbelt = build_toolbelt(storage=None, gateway=None)
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=toolbelt,
        execution=cast(Any, _Execution()),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    built = {tool.name: tool for tool in factory.build()}

    # M8D R10: the retired account-deep launch is exact-replay-only — no active role builds it —
    # while its registry descriptor (and therefore its historical schema pin) must not move.
    assert "launch_account_deep" not in built
    # head-of-abm v68 dropped the retired directive lane; no active role builds its draft tool.
    assert "draft_account_research_directive" not in built
    assert toolbelt.descriptor("launch_account_deep").input_schema_sha256 == (
        "ccb1246db77aeac6810baab769838993cc132fec9217eaecf07da9cc207d650f"
    )


def test_finalize_turn_derives_missing_next_action_from_exact_awaiting_input_message() -> None:
    request, resolved = _request()
    execution = _FinalizingExecution()
    artifacts = _DelegationArtifacts()
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, SimpleNamespace(backend=_EmptyOutputBackend())),
        artifacts=cast(Any, artifacts),
    )
    finalizer = factory.build()[-1]
    assert isinstance(finalizer, StructuredTool)
    coroutine = finalizer.coroutine
    assert coroutine is not None
    message = "Which specialist healthcare practices should this project prioritize?"

    run_async(
        coroutine(
            runtime=cast(Any, object()),
            status="awaiting_input",
            user_message=message,
            domain_refs=[],
            open_gate_refs=[],
            assumptions=[],
            next_actions=[],
            failure_code=None,
        )
    )

    envelope = cast(Any, execution.envelope)
    assert envelope.status.value == "awaiting_input"
    assert envelope.next_action_refs == (envelope.user_message_artifact_ref,)
    assert artifacts.data[envelope.next_action_refs[0].artifact_key] == message.encode()


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
                            "name": "configure_project_targeting",
                            # The property under test is the wrapper: the model sends only its
                            # own field, the wrapper defaults the optional one, and the trusted
                            # turn reference is filled in by the seam, never by the model. This
                            # tool replaced the product-set gate when automatic targeting retired
                            # the gates (0bdac1757, 2026-09-21); ARV2 onboarding O6 had earlier
                            # replaced `synthesize_icps@3` here.
                            "args": {"icp_key": "core-icp"},
                            "id": "configure-project-targeting-c65",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Tool completed, but I did not finalize."),
                AIMessage(content="I still did not finalize after the bounded recovery."),
            )
        ),
        execution=execution,
        max_runtime_s=5,
    )
    context = AssembledAgentContext(
        manifest=context_manifest(),
        messages=(HumanMessage(content="Target this project at our core ICP."),),
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
    assert proposed.tool.address == "configure_project_targeting@1"  # type: ignore[union-attr]
    # The model's field as sent, the optional product list defaulted by the wrapper, and no trusted
    # turn reference: that is authority the seam fills in.
    assert proposed.arguments == {"icp_key": "core-icp", "product_ids": None}  # type: ignore[union-attr]


def test_stage0_final_response_reports_the_targeting_receipt_and_claims_nothing_else() -> None:
    """Retargeted twice without changing what it protects: the agent's prose reports what a
    receipt shows and claims nothing a receipt does not.

    v20 protected readiness terminology; ARV2 onboarding O6 moved it onto the gates ("a gate
    receipt is the only authority"). Automatic project targeting (0bdac1757, 2026-09-21) retired
    the gates: ICP and product confirmation is now the `configure_project_targeting` receipt, and
    the Stage-0 skill states the same discipline as "the tool's receipt is the only proof" and
    "Report receipts, never claim capture."
    """

    request, resolved = _request()
    stage0_skill = next(  # type: ignore[union-attr]
        skill.ref.address
        for skill in resolved.skills  # type: ignore[union-attr]
        if skill.ref.name == "stage0-interview"
    )
    body = resolved.open_skill(stage0_skill)  # type: ignore[union-attr]
    assert "the tool's receipt is the only proof that anything was recorded" in body
    assert "Report receipts, never claim capture." in body

    execution = _ReadinessResponseExecution()
    artifacts = _DelegationArtifacts()
    response = (
        "Targeting is set from this turn's receipt: the project now uses the core ICP and the "
        "product set the receipt names."
    )
    runtime = DeepAgentTurnRuntime(
        models=_Models(
            (
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "configure_project_targeting",
                            "args": {"icp_key": "core-icp"},
                            "id": "stage0-targeting-receipt",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finalize_turn",
                            "args": {
                                "status": "completed",
                                "user_message": response,
                                "domain_refs": [],
                                "open_gate_refs": [],
                                "assumptions": [],
                                "next_actions": [],
                                "failure_code": None,
                            },
                            "id": "stage0-readiness-finalize",
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
        execution=execution,
        lease=cast(Any, SimpleNamespace(backend=_EmptyOutputBackend())),
        artifacts=artifacts,
    )

    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content="Target this project at our core ICP."),),
            ),
            backend=None,
            governed_tools=factory.build(),
        )
    )

    assert outcome.status is AgentExecutionStatus.COMPLETED
    envelope = cast(Any, execution.envelope)
    persisted_response = artifacts.data[envelope.user_message_artifact_ref.artifact_key].decode()
    assert persisted_response == response
    assert "receipt" in persisted_response


def test_c66_delegation_tool_freezes_exact_task_files_and_refs_before_child_wake() -> None:
    request, resolved = _request()
    execution = _DelegationExecution()
    artifacts = _DelegationArtifacts()
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, SimpleNamespace(backend=_DelegationBackend())),
        artifacts=cast(Any, artifacts),
    )
    runtime = DeepAgentTurnRuntime(
        models=_Models(
            (
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "delegate_specialist",
                            "args": {
                                "role": "reviewer",
                                "goal": "Review the exemplar.",
                                "instructions": "Check grounding and the slot contract.",
                                "verbatim_context": ["The human asked for a strict review."],
                                "canonical_paths": ["context/account.md"],
                                "domain_refs": [
                                    {
                                        "object_type": "account",
                                        "object_id": "account-42",
                                        "version": 3,
                                    }
                                ],
                            },
                            "id": "delegate-review-c66",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Delegation returned; parent intentionally did not finalize."),
                AIMessage(content="Parent still did not finalize after the bounded recovery."),
            )
        ),
        execution=execution,
        max_runtime_s=5,
    )

    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content="Review the exemplar."),),
            ),
            backend=None,
            governed_tools=factory.build(),
        )
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "missing_finalize"
    assert len(execution.validated_plans) == 1
    step = execution.validated_plans[0].steps[0]
    assert isinstance(step, PlanDelegationStep)
    assert step.role is AgentRole.REVIEWER
    assert step.granted_paths == ("context/delegated/00-account.md",)
    task = SpecialistTaskEnvelope.model_validate_json(
        artifacts.data[step.task_artifact_ref.artifact_key]
    )
    assert task.verbatim_context == ("The human asked for a strict review.",)
    assert task.file_grants[0].source_path == "context/account.md"
    assert (
        task.file_grants[0].artifact_ref.sha256
        == hashlib.sha256(b"Canonical account evidence.").hexdigest()
    )
    assert task.domain_refs[0].workspace_id == request.constitution.workspace_id
    assert task.required_output_path == "outputs/review-verdict.md"


def test_research_delegation_virtual_views_are_recoverable_without_file_access() -> None:
    import json
    from dataclasses import replace

    request, resolved = _request()
    resolved = cast(Any, resolved)
    resolved = replace(
        resolved,
        profile=resolved.profile.model_copy(
            update={
                "delegation_roles": (AgentRole.RESEARCH_CLAIMS,),
            }
        ),
    )
    execution = _DelegationExecution()
    artifacts = _DelegationArtifacts()

    class NoFiles:
        async def stat_entry(self, path):
            raise AssertionError("Virtual views must not reach the physical workspace")

    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, SimpleNamespace(backend=NoFiles())),
        artifacts=cast(Any, artifacts),
    )

    async def case():
        tool = factory._delegation_tool()
        args = {
            "role": "research_claims",
            "goal": "Process evidence",
            "instructions": "Read originals",
        }
        refused = json.loads(
            await tool.coroutine(
                runtime=SimpleNamespace(tool_call_id="wrong-copy", state={}),
                canonical_paths=["research/context.json", "evidence/index/0.json"],
                **args,
            )
        )
        assert refused["error"] == "plan_rejected"
        assert "canonical_paths=[]" in refused["reasons"][0]
        assert not execution.validated_plans
        assert not artifacts.data
        await tool.coroutine(
            runtime=SimpleNamespace(tool_call_id="corrected-copy"), canonical_paths=[], **args
        )
        assert len(execution.validated_plans) == 1
        step = execution.validated_plans[0].steps[0]
        assert step.granted_paths == ()

    run_async(case())


def test_o3_research_delegation_carries_frozen_steering_and_directive_files_and_refs() -> None:
    request, resolved = _request()
    steering_ref = request.constitution.focus_refs[0].model_copy(
        update={
            "object_type": "project_run",
            "object_id": "project-run-1",
            "version": None,
        }
    )
    directive_ref = request.constitution.focus_refs[0].model_copy(
        update={
            "object_type": "research_directive",
            "object_id": "directive-1",
            "version": 1,
        }
    )
    request = request.model_copy(
        update={
            "constitution": request.constitution.model_copy(
                update={
                    "project_context_artifacts": (
                        ProjectContextArtifact(
                            name="account-deep-steering",
                            artifact_ref=artifact("account-deep-steering.json"),
                            domain_ref=steering_ref,
                        ),
                        ProjectContextArtifact(
                            name="research-directive",
                            artifact_ref=artifact("research-directive.json"),
                            domain_ref=directive_ref,
                        ),
                    )
                }
            )
        }
    )
    execution = _DelegationExecution()
    artifacts = _DelegationArtifacts()
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,  # type: ignore[arg-type]
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, SimpleNamespace(backend=_DelegationBackend())),
        artifacts=cast(Any, artifacts),
    )
    runtime = DeepAgentTurnRuntime(
        models=_Models(
            (
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "delegate_specialist",
                            "args": {
                                "role": "research",
                                "goal": "Research this account under confirmed direction.",
                                "instructions": "Use only the governed directive.",
                                "verbatim_context": [],
                                "canonical_paths": [],
                                "domain_refs": [],
                            },
                            "id": "delegate-research-a2",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Parent intentionally did not finalize."),
                AIMessage(content="Parent still did not finalize."),
            )
        ),
        execution=execution,
        max_runtime_s=5,
    )

    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,  # type: ignore[arg-type]
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content="Delegate the governed research."),),
            ),
            backend=None,
            governed_tools=factory.build(),
        )
    )

    assert outcome.failure_code == "missing_finalize"
    step = execution.validated_plans[0].steps[0]
    assert isinstance(step, PlanDelegationStep)
    assert step.granted_paths == (
        "context/delegated/00-account-deep-steering.json",
        "context/delegated/01-research-directive.json",
    )
    assert step.domain_refs == (steering_ref, directive_ref)
    task = SpecialistTaskEnvelope.model_validate_json(
        artifacts.data[step.task_artifact_ref.artifact_key]
    )
    assert tuple(item.source_path for item in task.file_grants) == (
        "context/project/account-deep-steering.json",
        "context/project/research-directive.json",
    )
    assert task.domain_refs == (steering_ref, directive_ref)
