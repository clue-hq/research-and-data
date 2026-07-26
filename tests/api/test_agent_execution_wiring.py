from __future__ import annotations

import hashlib
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from clue_agents import (
    AgentPlan,
    AgentPlanPolicy,
    AgentPlanRejected,
    AgentProfile,
    AgentResourceRef,
    AgentRole,
    ArtifactRef,
    ModelPolicy,
    ResolvedAgentProfile,
    ResourceKind,
    ToolPin,
    WorkspacePolicy,
)
from clue_agents.contracts import PlanToolStep
from clue_api.agent_execution_wiring import C5AgentExecutionAdapter
from clue_core import ExecutionId
from clue_execution import InteractionAppend, InteractionSlotView, PinRequest
from clue_toolbelt import (
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolRegistry,
    ToolResult,
)
from tests.agents.conftest import NOW, SHA_A, artifact, constitution
from tests.db.conftest import run_async


class _Input(ToolInput):
    query: str


class _Output(ToolOutput):
    object_ref: str


class _Tool(Tool):
    name = "read_project"
    version = "1"
    input_model = _Input
    output_model = _Output
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="project projection",
    )

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate(cost_cents=Decimal("0.5"))

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        del inputs, ctx
        raise AssertionError("the C5 executor fake owns invocation in this test")


class _Artifacts:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def persist_body(
        self,
        *,
        workspace_id: str,
        data: bytes,
        media_type: str,
        **kwargs: Any,
    ) -> ArtifactRef:
        del kwargs
        digest = hashlib.sha256(data).hexdigest()
        key = f"{workspace_id}/{digest}"
        self.data[key] = data
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=key,
            sha256=digest,
            media_type=media_type,
            byte_count=len(data),
        )

    async def read(self, ref: ArtifactRef) -> bytes:
        return self.data[ref.artifact_key]


class _Journal:
    def __init__(self) -> None:
        self.validated = []
        self.results = []
        self.events = []

    async def record_validated(self, **kwargs: Any) -> None:
        self.validated.append(kwargs)

    async def event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    async def record_tool_result(self, **kwargs: Any) -> None:
        self.results.append(kwargs)

    async def load_receipts(self, **kwargs: Any) -> tuple[object, ...]:
        del kwargs
        return ()


class _Executor:
    def __init__(self, *, allowed: tuple[str, ...]) -> None:
        self.allowed = allowed
        self.appended: list[dict[str, Any]] = []
        self.effect_count = 0

    async def inspect_interaction_slot(self, **kwargs: Any) -> InteractionSlotView:
        return InteractionSlotView(
            execution_id=kwargs["execution_id"],
            workspace_id=kwargs["workspace_id"],
            slot_key=kwargs["slot_key"],
            tool_allowlist=self.allowed,
            dynamic_pin_kinds=(),
            requirements=(PinRequest(kind="tool", key="read_project", version="1"),),
            max_children=8,
            child_count=0,
            max_nodes=16,
            node_count=2,
        )

    async def append_interaction_tool(self, **kwargs: Any) -> InteractionAppend:
        self.appended.append(kwargs)
        return InteractionAppend(
            execution_id=kwargs["execution_id"],
            node_id=UUID("00000000-0000-0000-0000-000000000643"),
            operation_id=UUID("00000000-0000-0000-0000-000000000644"),
            node_key=kwargs["node_key"],
            created=True,
        )

    async def invoke_interaction_tool(
        self,
        append: InteractionAppend,
        **kwargs: Any,
    ) -> ToolResult:
        del append, kwargs
        replayed = self.effect_count > 0
        if not replayed:
            self.effect_count += 1
        return ToolResult(
            tool="read_project",
            version="1",
            references={"object_ref": "project-1"},
            replayed=replayed,
        )


def _profile(pin: ToolPin) -> AgentProfile:
    return AgentProfile(
        name="head-of-abm",
        version="1.0.0",
        role=AgentRole.HEAD_OF_ABM,
        prompt=AgentResourceRef(
            kind=ResourceKind.PROMPT,
            name="head-of-abm",
            version="1.0.0",
            sha256=SHA_A,
        ),
        skills=(),
        tools=(pin,),
        model=ModelPolicy(
            model_id="test/model",
            timeout_s=5,
            max_retries=0,
            max_output_tokens=100,
            temperature=0,
        ),
        workspace=WorkspacePolicy(
            max_total_bytes=10_000,
            max_file_bytes=5_000,
            max_file_count=10,
            allowed_extensions=(".json", ".md"),
            readable_prefixes=("context", "work", "outputs"),
            writable_prefixes=("work", "outputs"),
            retention_class="test",
        ),
        max_delegation_depth=0,
        max_delegations=0,
        max_plan_nodes=8,
    )


async def _no_crash(point: str, **kwargs: Any) -> None:
    del point, kwargs


class _CrashOnce:
    def __init__(self, point: str) -> None:
        self.point = point
        self.raised = False

    async def __call__(self, point: str, **kwargs: Any) -> None:
        del kwargs
        if point == self.point and not self.raised:
            self.raised = True
            raise RuntimeError(f"crash:{point}")


def _adapter(
    *,
    allowed: tuple[str, ...],
    budget: int = 10_000,
    crash_hook: Any = _no_crash,
):
    registry = ToolRegistry()
    registry.register(_Tool(), make_default=True)
    descriptor = registry.descriptor("read_project", "1")
    pin = ToolPin(
        name=descriptor.name,
        version=descriptor.version,
        input_schema_sha256=descriptor.input_schema_sha256,
        output_schema_sha256=descriptor.output_schema_sha256,
    )
    runtime_profile = _profile(pin)
    profile_ref = AgentResourceRef(
        kind=ResourceKind.PROFILE,
        name=runtime_profile.name,
        version=runtime_profile.version,
        sha256=SHA_A,
    )
    trusted = constitution(profile_ref=profile_ref)
    resolved = cast(
        ResolvedAgentProfile,
        SimpleNamespace(
            profile=runtime_profile,
            profile_ref=profile_ref,
        ),
    )
    artifacts = _Artifacts()
    journal = _Journal()
    executor = _Executor(allowed=allowed)
    adapter = C5AgentExecutionAdapter(
        turn_id=UUID("00000000-0000-0000-0000-000000000645"),
        constitution=trusted,
        resolved_profile=resolved,
        policy=AgentPlanPolicy.from_profile(
            runtime_profile,
            budget_limit_millicents=budget,
            max_fanout=4,
            max_parallelism=4,
        ),
        slot_key="agent_slot",
        tools=registry,
        tool_invoker=cast(Any, object()),
        executor=cast(Any, executor),
        artifacts=cast(Any, artifacts),
        journal=cast(Any, journal),
        checkpointer_factory=cast(Any, lambda _: None),
        crash_hook=crash_hook,
    )
    return adapter, trusted, pin, executor, journal


def _plan(pin: ToolPin) -> AgentPlan:
    return AgentPlan(
        plan_id=UUID("00000000-0000-0000-0000-000000000646"),
        execution_id=ExecutionId(UUID("00000000-0000-0000-0000-000000000601")),
        role=AgentRole.HEAD_OF_ABM,
        goal_ref=artifact("goal.json"),
        steps=(
            PlanToolStep(
                node_key="read",
                tool=pin,
                arguments={"query": "current project"},
                purpose="Read the current project.",
            ),
        ),
        proposed_at=NOW,
    )


def test_compiler_validates_whole_c5_graph_then_routes_effect_through_dynamic_node() -> None:
    adapter, trusted, pin, executor, journal = _adapter(
        allowed=("read_project@1",),
    )
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    assert validated.estimated_cost_millicents == 500
    assert validated.operations[0].operation_id == validated.operations[0].operation_id
    progress = run_async(_collect(adapter.execute(plan=validated)))

    assert progress[-1].status == "completed"
    assert executor.appended[0]["actor"] == "agent"
    assert executor.appended[0]["inputs"] == {"query": "current project"}
    assert len(journal.results) == 1


def test_compiler_rejects_c5_slot_and_budget_bypass_before_any_dynamic_append() -> None:
    missing, trusted, pin, executor, _ = _adapter(allowed=())
    with pytest.raises(AgentPlanRejected, match="c5_tool_not_allowed"):
        run_async(missing.validate_plan(plan=_plan(pin), constitution=trusted))
    assert executor.appended == []

    over_budget, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        budget=499,
    )
    with pytest.raises(AgentPlanRejected, match="budget_ceiling"):
        run_async(over_budget.validate_plan(plan=_plan(pin), constitution=trusted))
    assert executor.appended == []


@pytest.mark.parametrize(
    ("crash_point", "effects_after_crash"),
    [("plan_append", 0), ("post_tool_complete", 1)],
)
def test_agent_boundaries_retry_through_c5_without_duplicate_domain_effect(
    crash_point: str,
    effects_after_crash: int,
) -> None:
    adapter, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        crash_hook=_CrashOnce(crash_point),
    )
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    first = run_async(_collect(adapter.execute(plan=validated)))
    assert first[-1].status == "failed"
    assert executor.effect_count == effects_after_crash

    recovered = run_async(_collect(adapter.execute(plan=validated)))
    assert recovered[-1].status == "completed"
    assert executor.effect_count == 1


async def _collect(iterator: Any) -> list[Any]:
    return [item async for item in iterator]
