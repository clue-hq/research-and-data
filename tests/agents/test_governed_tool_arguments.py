"""Governed tool arguments reach the durable plan as JSON, never as live Python objects.

``StructuredTool`` hands a tool coroutine *validated* kwargs — nested models stay model
instances, enums stay enum members, ``UUID``/``Decimal``/``datetime`` stay their rich Python
types. :class:`~clue_agents.contracts.PlanToolStep.arguments` admits JSON values only, so the
governed wrapper must normalize at that seam or every governed tool with a nested model dies
with ``input was not a valid JSON value`` on a semantically correct model call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from langchain.tools import ToolRuntime
from pydantic import BaseModel, ConfigDict
from pydantic_core import PydanticSerializationError

from clue_agents import AgentRole, AgentTurnRequest
from clue_agents.contracts import PlanToolStep, ToolPin
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.stage0_tools import RecordInterviewAnswerInput
from clue_api.toolbelt_wiring import build_toolbelt
from clue_research.stage0.interview import InterviewRoute, InterviewStatement
from clue_toolbelt import (
    Tool,
    ToolContext,
    ToolInput,
    ToolRegistry,
    ToolResult,
)
from tests.agents.conftest import NOW, artifact, constitution
from tests.agents.test_runtime import _Execution
from tests.db.conftest import run_async


def _runtime(tool_call_id: str) -> ToolRuntime:
    return ToolRuntime(
        state=cast(Any, None),
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id=tool_call_id,
        store=None,
    )


def _turn_request(resolved: object) -> AgentTurnRequest:
    profile = cast(Any, resolved)
    trusted = constitution(
        profile_ref=profile.profile_ref,
        resource_manifest_sha256=profile.resource_manifest.aggregate_sha256,
    )
    return AgentTurnRequest(
        turn_id=UUID("00000000-0000-0000-0000-000000000643"),
        thread_id="thread-governed-arguments",
        constitution=trusted,
        user_message_artifact_ref=artifact("user-message.json"),
        requested_at=NOW,
    )


def _invoke(tool: Any, *, args: Mapping[str, Any], tool_call_id: str) -> str:
    """Drive the real ``StructuredTool`` path, including the injected trusted runtime."""

    return cast(
        str,
        run_async(
            tool.ainvoke(
                {
                    "args": {**args, "runtime": _runtime(tool_call_id)},
                    "id": tool_call_id,
                    "type": "tool_call",
                    "name": tool.name,
                }
            )
        ),
    )


def _plan_arguments(execution: _Execution) -> dict[str, Any]:
    step = execution.validated_plans[0].steps[0]
    assert isinstance(step, PlanToolStep)
    return dict(step.arguments)


# --- the exact production failure: real Stage-0 tool, real nested statements ----------------


def _record_interview_answer_tool() -> tuple[Any, _Execution]:
    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    execution = _Execution()
    factory = GovernedAgentToolFactory(
        request=_turn_request(resolved),
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    tool = next(item for item in factory.build() if item.name == "record_interview_answer")
    return tool, execution


_INTERVIEW_ARGS: dict[str, Any] = {
    "brand_id": "brand-1",
    "onboarding_input_id": "onboarding-input-1",
    "artifact_key": "ws-1/interview-answer.md",
    "answer": "We sell surgical planning software to neurosurgery departments.",
    "client_entity_id": "entity-client-1",
    "statements": [
        {
            "route": "project_state",
            "route_key": "product.category",
            "quote_start": 0,
            "quote_end": 26,
        },
        {
            "route": "memory",
            "route_key": "tone.preference",
            "quote_start": 27,
            "quote_end": 61,
            "memory_type": "preference",
            "memory_scope_type": "brand",
            "memory_scope_id": "brand-1",
        },
    ],
}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "defect 2b: LangChain materializes every defaulted field, so the tool input model's "
        "own project_id=None reaches PlanToolStep and trips the forbidden-authority guard"
    ),
)
def test_record_interview_answer_statements_reach_the_plan_as_json() -> None:
    tool, execution = _record_interview_answer_tool()

    _invoke(tool, args=_INTERVIEW_ARGS, tool_call_id="call-interview-1")

    arguments = _plan_arguments(execution)
    # Plan arguments are pure JSON: they survive a byte-level round trip unchanged.
    assert json.loads(json.dumps(arguments)) == arguments
    assert arguments["statements"] == [
        {
            "route": "project_state",
            "route_key": "product.category",
            "quote_start": 0,
            "quote_end": 26,
            "entity_id": None,
            "entity_type": None,
            "field_key": None,
            "value": None,
            "route_ref": None,
            "correction_of_statement_id": None,
            "correction_of_claim_id": None,
            "memory_type": None,
            "memory_scope_type": None,
            "memory_scope_id": None,
            "identity_binding": None,
            "use_class": None,
        },
        {
            "route": "memory",
            "route_key": "tone.preference",
            "quote_start": 27,
            "quote_end": 61,
            "entity_id": None,
            "entity_type": None,
            "field_key": None,
            "value": None,
            "route_ref": None,
            "correction_of_statement_id": None,
            "correction_of_claim_id": None,
            "memory_type": "preference",
            "memory_scope_type": "brand",
            "memory_scope_id": "brand-1",
            "identity_binding": None,
            "use_class": None,
        },
    ]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "defect 2b: LangChain materializes every defaulted field, so the tool input model's "
        "own project_id=None reaches PlanToolStep and trips the forbidden-authority guard"
    ),
)
def test_record_interview_answer_plan_arguments_revalidate_for_the_executor() -> None:
    tool, execution = _record_interview_answer_tool()

    _invoke(tool, args=_INTERVIEW_ARGS, tool_call_id="call-interview-2")

    # The executor re-validates the durable arguments into the tool's own input model; the
    # normalized JSON must produce exactly the values the model proposed.
    replayed = RecordInterviewAnswerInput.model_validate(_plan_arguments(execution))
    assert replayed == RecordInterviewAnswerInput.model_validate(_INTERVIEW_ARGS)
    assert replayed.statements == [
        InterviewStatement(
            route=InterviewRoute.PROJECT_STATE,
            route_key="product.category",
            quote_start=0,
            quote_end=26,
        ),
        InterviewStatement.model_validate(_INTERVIEW_ARGS["statements"][1]),
    ]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "defect 2b: LangChain materializes every defaulted field, so the tool input model's "
        "own project_id=None reaches PlanToolStep and trips the forbidden-authority guard"
    ),
)
def test_governed_plan_arguments_exclude_the_injected_trusted_runtime() -> None:
    tool, execution = _record_interview_answer_tool()

    _invoke(tool, args=_INTERVIEW_ARGS, tool_call_id="call-interview-3")

    arguments = _plan_arguments(execution)
    assert "runtime" not in arguments
    assert set(arguments) == set(RecordInterviewAnswerInput.model_fields)


# --- the type matrix: nested models, nested enums, UUID, Decimal, datetime ------------------


class _MatrixMode(StrEnum):
    FAST = "fast"
    THOROUGH = "thorough"


class _MatrixLeg(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: _MatrixMode
    weight: Decimal


class _MatrixInput(ToolInput):
    label: str
    legs: list[_MatrixLeg]
    mode: _MatrixMode
    run_id: UUID
    budget_cents: Decimal
    scheduled_for: datetime


class _MatrixTool(Tool):
    name = "matrix_probe"
    version = "1"
    input_model = _MatrixInput

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("the governed wrapper never reaches the tool body in this test")


class _ArbitraryHandle:
    """A deliberately unserializable value; no JSON representation exists."""


class _UnserializableInput(ToolInput):
    # ``Any`` keeps the model-facing JSON schema generatable while still letting a non-JSON
    # Python object reach the wrapper — the shape a sloppy future tool could produce.
    handle: Any


class _UnserializableTool(Tool):
    name = "unserializable_probe"
    version = "1"
    input_model = _UnserializableInput

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("the governed wrapper never reaches the tool body in this test")


def _probe_tool(tool: Tool) -> tuple[Any, _Execution]:
    registry = ToolRegistry()
    registry.register(tool, make_default=True)
    descriptor = tool.descriptor
    pin = ToolPin(
        name=descriptor.name,
        version=descriptor.version,
        input_schema_sha256=descriptor.input_schema_sha256,
        output_schema_sha256=descriptor.output_schema_sha256,
    )
    profiles = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = profiles.resolve(AgentRole.HEAD_OF_ABM)
    probe_profile = SimpleNamespace(
        profile_ref=resolved.profile_ref,
        resource_manifest=resolved.resource_manifest,
        profile=SimpleNamespace(tools=(pin,), delegation_roles=()),
    )
    execution = _Execution()
    factory = GovernedAgentToolFactory(
        request=_turn_request(probe_profile),
        resolved_profile=cast(Any, probe_profile),
        registry=registry,
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    )
    built = next(item for item in factory.build() if item.name == descriptor.name)
    return built, execution


_MATRIX_ARGS: dict[str, Any] = {
    "label": "matrix",
    "legs": [
        {"mode": "fast", "weight": "0.25"},
        {"mode": "thorough", "weight": "0.75"},
    ],
    "mode": "thorough",
    "run_id": "3f0f8e2e-0e8a-4b7a-9c6d-2b1f0a9c7d55",
    "budget_cents": "1234.56",
    "scheduled_for": "2026-07-31T09:30:00Z",
}


def test_rich_python_types_are_normalized_into_json_plan_arguments() -> None:
    tool, execution = _probe_tool(_MatrixTool())

    _invoke(tool, args=_MATRIX_ARGS, tool_call_id="call-matrix-1")

    arguments = _plan_arguments(execution)
    assert json.loads(json.dumps(arguments)) == arguments
    assert arguments["legs"] == [
        {"mode": "fast", "weight": "0.25"},
        {"mode": "thorough", "weight": "0.75"},
    ]
    assert arguments["mode"] == "thorough"
    assert arguments["run_id"] == "3f0f8e2e-0e8a-4b7a-9c6d-2b1f0a9c7d55"
    assert arguments["budget_cents"] == "1234.56"
    assert arguments["scheduled_for"].startswith("2026-07-31T09:30:00")


def test_matrix_plan_arguments_revalidate_into_equivalent_values() -> None:
    tool, execution = _probe_tool(_MatrixTool())

    _invoke(tool, args=_MATRIX_ARGS, tool_call_id="call-matrix-2")

    replayed = _MatrixInput.model_validate(_plan_arguments(execution))
    assert replayed == _MatrixInput.model_validate(_MATRIX_ARGS)
    assert replayed.legs == [
        _MatrixLeg(mode=_MatrixMode.FAST, weight=Decimal("0.25")),
        _MatrixLeg(mode=_MatrixMode.THOROUGH, weight=Decimal("0.75")),
    ]
    assert replayed.mode is _MatrixMode.THOROUGH
    assert replayed.run_id == UUID("3f0f8e2e-0e8a-4b7a-9c6d-2b1f0a9c7d55")
    assert replayed.budget_cents == Decimal("1234.56")
    assert replayed.scheduled_for == datetime(2026, 7, 31, 9, 30, tzinfo=UTC)


def test_normalization_fails_loudly_on_an_argument_with_no_json_representation() -> None:
    tool, execution = _probe_tool(_UnserializableTool())

    with pytest.raises(PydanticSerializationError):
        _invoke(
            tool,
            args={"handle": _ArbitraryHandle()},
            tool_call_id="call-unserializable-1",
        )

    # Fail-closed: nothing was proposed to the governed executor.
    assert execution.validated_plans == []


def test_a_semantically_invalid_argument_is_still_refused_before_the_plan() -> None:
    tool, execution = _probe_tool(_MatrixTool())

    with pytest.raises(Exception) as failure:
        _invoke(
            tool,
            args={**_MATRIX_ARGS, "mode": "reckless"},
            tool_call_id="call-matrix-invalid",
        )

    assert "reckless" in str(failure.value)
    assert execution.validated_plans == []


def test_forbidden_trusted_authority_arguments_are_still_rejected() -> None:
    # Normalization must not become a laundering step for authority keys the model may not set.
    with pytest.raises(ValueError, match="trusted authority"):
        PlanToolStep(
            node_key="agent_probe",
            tool=ToolPin(
                name="matrix_probe",
                version="1",
                input_schema_sha256="a" * 64,
                output_schema_sha256="b" * 64,
            ),
            arguments=cast(Any, {"workspace_id": "ws-2"}),
            purpose="probe",
        )
