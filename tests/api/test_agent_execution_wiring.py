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
from clue_api.agent_execution_wiring import C5AgentExecutionAdapter, _trusted_tool_arguments
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
    def __init__(
        self,
        *,
        allowed: tuple[str, ...],
        dynamic_pin_kinds: tuple[str, ...] = (),
    ) -> None:
        self.allowed = allowed
        self.dynamic_pin_kinds = dynamic_pin_kinds
        self.appended: list[dict[str, Any]] = []
        self.effect_count = 0

    async def inspect_interaction_slot(self, **kwargs: Any) -> InteractionSlotView:
        return InteractionSlotView(
            execution_id=kwargs["execution_id"],
            workspace_id=kwargs["workspace_id"],
            slot_key=kwargs["slot_key"],
            tool_allowlist=self.allowed,
            dynamic_pin_kinds=self.dynamic_pin_kinds,
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


class _PinProvider:
    async def pins_for(self, step: object, *, ctx: ToolContext) -> tuple[PinRequest, ...]:
        del step, ctx
        return (
            PinRequest(
                kind="project",
                key="project-1",
                version="3",
                digest="a" * 64,
            ),
        )


class _OtherTool(_Tool):
    """A second registered tool, so a profile can pin something the plan does not call."""

    name = "write_note"


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
    pin_provider: object | None = None,
    dynamic_pin_kinds: tuple[str, ...] = (),
    tool: Tool | None = None,
    profile_pins_other_tool: bool = False,
):
    registry = ToolRegistry()
    registry.register(tool if tool is not None else _Tool(), make_default=True)
    descriptor = registry.descriptor("read_project", "1")
    pin = ToolPin(
        name=descriptor.name,
        version=descriptor.version,
        input_schema_sha256=descriptor.input_schema_sha256,
        output_schema_sha256=descriptor.output_schema_sha256,
    )
    if profile_pins_other_tool:
        # The C5 slot allowlist and the profile's effective tool set are two independent
        # authorities. Pinning the profile to a *different* registered tool produces the one
        # combination neither test above covers: allowlisted by the slot, absent from the profile.
        registry.register(_OtherTool(), make_default=True)
        other = registry.descriptor("write_note", "1")
        runtime_profile = _profile(
            ToolPin(
                name=other.name,
                version=other.version,
                input_schema_sha256=other.input_schema_sha256,
                output_schema_sha256=other.output_schema_sha256,
            )
        )
    else:
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
    executor = _Executor(
        allowed=allowed,
        dynamic_pin_kinds=dynamic_pin_kinds,
    )
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
        pin_provider=cast(Any, pin_provider),
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


def test_agent_path_resolves_and_forwards_the_same_dynamic_resource_pins_as_recipe0() -> None:
    adapter, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        pin_provider=_PinProvider(),
        dynamic_pin_kinds=("project",),
    )

    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    progress = run_async(_collect(adapter.execute(plan=validated)))

    assert progress[-1].status == "completed"
    assert executor.appended[0]["pin_requests"] == (
        PinRequest(
            kind="project",
            key="project-1",
            version="3",
            digest="a" * 64,
        ),
    )


def test_agent_path_rejects_resource_pins_outside_the_recipe0_slot_contract() -> None:
    adapter, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        pin_provider=_PinProvider(),
    )

    with pytest.raises(AgentPlanRejected, match="c5_pin_kind_not_allowed"):
        run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    assert executor.appended == []


def test_compiler_refuses_a_slot_allowlisted_tool_the_profile_does_not_make_effective() -> None:
    """A not-effective step is refused *by this loop*, not left half-processed for a later lookup.

    The C5 slot allowlist and the profile's effective tool set are independent authorities, so a
    step can satisfy one and not the other. That branch used to ``continue`` without recording an
    issue of its own: the step stayed in ``plan.steps`` but never got a ``trusted_arguments``
    entry, and the two later unguarded lookups (graph compilation and cost estimation) would
    ``KeyError`` on its node key. Today the shape is caught upstream by ``review_agent_plan``
    (``tool_not_allowed``), which is what keeps the KeyError latent rather than live — but that
    is an accident of a second, independently-editable authority agreeing. This loop must state
    its own precondition, so the ``trusted_arguments`` invariant ("every retained tool step has an
    entry") holds locally instead of being inherited.
    """

    adapter, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        profile_pins_other_tool=True,
    )

    with pytest.raises(AgentPlanRejected) as rejected:
        run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    codes = [issue.code for issue in rejected.value.review.issues]
    assert "tool_not_effective" in codes
    assert [
        issue.location
        for issue in rejected.value.review.issues
        if issue.code == "tool_not_effective"
    ] == ["plan.steps[0].tool"]
    # The upstream profile review still fires; the new issue is an added local guarantee.
    assert "tool_not_allowed" in codes
    assert executor.appended == []


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


class _AuthorityInput(ToolInput):
    """A tool body that legitimately needs authority it may never be *told* by the model."""

    query: str
    project_id: str | None = None
    workspace_id: str | None = None


class _AuthorityTool(_Tool):
    input_model = _AuthorityInput


def test_declared_authority_is_served_from_the_constitution_not_the_model() -> None:
    adapter, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        tool=_AuthorityTool(),
    )

    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    progress = run_async(_collect(adapter.execute(plan=validated)))

    assert progress[-1].status == "completed"
    # The model proposed only ``query``; the executed body carries the trusted values.
    assert executor.appended[0]["inputs"] == {
        "query": "current project",
        "project_id": trusted.project_id,
        "workspace_id": trusted.workspace_id,
    }


def test_declared_authority_cannot_be_anything_but_the_constitution_value() -> None:
    adapter, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        tool=_AuthorityTool(),
    )
    other = constitution(profile_ref=trusted.profile_ref, project_id="project-attacker")
    assert other != trusted

    # A plan offered under any other constitution is refused outright, so the executed authority
    # can only ever be the bound constitution's.
    with pytest.raises(ValueError, match="different constitution"):
        run_async(adapter.validate_plan(plan=_plan(pin), constitution=other))
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    run_async(_collect(adapter.execute(plan=validated)))
    assert executor.appended[0]["inputs"]["project_id"] == trusted.project_id
    assert executor.appended[0]["inputs"]["project_id"] != other.project_id
    # The merge reads the constitution it is handed and nothing else.
    assert _trusted_tool_arguments(
        arguments={"query": "current project"},
        input_model=_AuthorityInput,
        constitution=other,
    ) == {
        "query": "current project",
        "project_id": other.project_id,
        "workspace_id": other.workspace_id,
    }


def test_tools_that_declare_no_authority_are_untouched() -> None:
    adapter, trusted, pin, executor, _ = _adapter(allowed=("read_project@1",))

    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    run_async(_collect(adapter.execute(plan=validated)))

    assert executor.appended[0]["inputs"] == {"query": "current project"}


def test_authority_merge_refuses_plan_arguments_that_already_carry_authority() -> None:
    # Defence in depth: PlanToolStep refuses these keys, so reaching the merge with one means a
    # caller bypassed the contract — that must fail loudly, never be silently overwritten.
    trusted = constitution()
    with pytest.raises(ValueError, match="trusted authority"):
        _trusted_tool_arguments(
            arguments={"query": "x", "project_id": "project-attacker"},
            input_model=_AuthorityInput,
            constitution=trusted,
        )


def test_authority_the_constitution_does_not_carry_is_not_synthesized() -> None:
    class _OperationInput(ToolInput):
        query: str
        operation_id: str | None = None

    merged = _trusted_tool_arguments(
        arguments={"query": "x"},
        input_model=_OperationInput,
        constitution=constitution(),
    )

    assert merged == {"query": "x"}
