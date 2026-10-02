from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from clue_agents import (
    AgentExecutionStatus,
    AgentPlan,
    AgentPlanPolicy,
    AgentPlanRejected,
    AgentProfile,
    AgentResourceRef,
    AgentRole,
    ArtifactRef,
    GovernedOperationReceipt,
    ModelPolicy,
    ResolvedAgentProfile,
    ResourceKind,
    ToolPin,
    WorkspacePolicy,
)
from clue_agents.contracts import PlanToolStep
from clue_agents.execution import RECEIPT_REFERENCE_VALUES_MAX_BYTES
from clue_api.agent_execution_wiring import (
    _FAILURE_MESSAGE_LIMIT,
    C5AgentExecutionAdapter,
    _trusted_tool_arguments,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import ExecutionId
from clue_execution import InteractionAppend, InteractionSlotView, PinRequest
from clue_toolbelt import (
    PreconditionFailed,
    PreconditionFailure,
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


class _StrictJsonOutput(ToolOutput):
    object_id: UUID
    related_ids: tuple[UUID, ...]


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
        return tuple(
            GovernedOperationReceipt(
                node_key=item["operation"].node_key,
                operation_id=item["operation"].operation_id,
                kind="tool",
                address=item["operation"].address,
                status=AgentExecutionStatus.COMPLETED,
                replayed=item["result"].replayed,
                artifact_refs=(item["result_ref"],),
            )
            for item in self.results
        )


class _NoFinalizationResult:
    def mappings(self) -> _NoFinalizationResult:
        return self

    def one_or_none(self) -> None:
        return None


class _NoFinalizationConn:
    async def execute(self, *_args: Any, **_kwargs: Any) -> _NoFinalizationResult:
        return _NoFinalizationResult()


@asynccontextmanager
async def _no_finalization_conn() -> AsyncIterator[_NoFinalizationConn]:
    yield _NoFinalizationConn()


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
        self.invoked: list[dict[str, Any]] = []
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
        del append
        self.invoked.append(kwargs)
        replayed = self.effect_count > 0
        if not replayed:
            self.effect_count += 1
        return ToolResult(
            tool="read_project",
            version="1",
            references={"object_ref": "project-1"},
            replayed=replayed,
        )


class _RefusingExecutor(_Executor):
    """Executor whose tool refuses the way a real governed tool refuses: by raising.

    The live F7 case: ``record_interview_answer`` raised a domain ``ValueError`` from the
    interview verifier. The exception is gathered away inside :meth:`execute` (a failed operation
    must not abort its siblings), so the *reason* has to ride the progress stream or the caller has
    nothing to hand the model.
    """

    def __init__(self, *, error: BaseException, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.error = error

    async def invoke_interaction_tool(
        self,
        append: InteractionAppend,
        **kwargs: Any,
    ) -> ToolResult:
        del append, kwargs
        self.effect_count += 1
        raise self.error


class _StrictJsonExecutor(_Executor):
    async def invoke_interaction_tool(
        self,
        append: InteractionAppend,
        **kwargs: Any,
    ) -> ToolResult:
        del append
        self.invoked.append(kwargs)
        self.effect_count += 1
        # This is the shape returned by a real durable ToolInvoker boundary: UUIDs are JSON strings
        # and tuples are JSON arrays. Strict output models must accept that canonical wire form.
        return ToolResult(
            tool="read_project",
            version="1",
            references={
                "object_id": "11111111-1111-4111-8111-111111111111",
                "related_ids": ["22222222-2222-4222-8222-222222222222"],
            },
        )


class _PinProvider:
    def __init__(self) -> None:
        self.contexts: list[ToolContext] = []

    async def pins_for(self, step: object, *, ctx: ToolContext) -> tuple[PinRequest, ...]:
        del step
        self.contexts.append(ctx)
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
    executor: _Executor | None = None,
    spill_sink: Any = None,
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
    if executor is None:
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
        spill_sink=spill_sink,
        crash_hook=crash_hook,
        conn_factory=cast(Any, _no_finalization_conn),
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


def test_agent_path_revalidates_strict_tool_output_in_json_mode() -> None:
    class _StrictJsonTool(_Tool):
        output_model = _StrictJsonOutput

    executor = _StrictJsonExecutor(allowed=("read_project@1",))
    adapter, trusted, pin, _, journal = _adapter(
        allowed=("read_project@1",),
        tool=_StrictJsonTool(),
        executor=executor,
    )
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    progress = run_async(_collect(adapter.execute(plan=validated)))

    assert progress[-1].status == "completed"
    assert journal.results[0]["result"].references == {
        "object_id": "11111111-1111-4111-8111-111111111111",
        "related_ids": ["22222222-2222-4222-8222-222222222222"],
    }


def test_recovery_restores_reference_only_tool_projection_from_exact_artifact() -> None:
    adapter, trusted, pin, _, _ = _adapter(allowed=("read_project@1",))
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    progress = run_async(_collect(adapter.execute(plan=validated)))
    assert progress[-1].status == "completed"

    recovered = run_async(adapter.recover(execution_id=validated.execution_id))
    receipts = recovered["operation_receipts"]
    assert isinstance(receipts, tuple)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert isinstance(receipt, GovernedOperationReceipt)
    assert receipt.reference_values == {"object_ref": "project-1"}


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


@pytest.mark.parametrize(
    ("error", "expected_type", "expected_fragment"),
    [
        (
            ValueError("claim value is not textually entailed by the exact interview quote"),
            "ValueError",
            "not textually entailed",
        ),
        (
            PreconditionFailed(
                (
                    PreconditionFailure(
                        reason_code="no_active_icp",
                        message="confirm an ICP before importing accounts",
                    ),
                )
            ),
            "PreconditionFailed",
            "no_active_icp: confirm an ICP before importing accounts",
        ),
    ],
)
def test_a_failed_operation_carries_its_reason_on_the_progress_stream(
    error: BaseException,
    expected_type: str,
    expected_fragment: str,
) -> None:
    """The durable record of a failure is a code; the sentence that repairs it is the exception.

    ``execute`` deliberately gathers operation exceptions away — one failed node must not abort its
    siblings — so before this the reason existed only in the log. The caller (the governed tool
    wrapper) then had nothing to tell the model beyond "it failed", which is exactly the live F7
    dead end.
    """

    adapter, trusted, pin, executor, journal = _adapter(
        allowed=("read_project@1",),
        executor=_RefusingExecutor(error=error, allowed=("read_project@1",)),
    )
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    progress = run_async(_collect(adapter.execute(plan=validated)))

    assert progress[-1].status == "failed"
    assert progress[-1].failed_node_keys == ("read",)
    failure = progress[-1].failures[0]
    assert failure.node_key == "read"
    assert failure.address == "read_project@1"
    assert failure.error_type == expected_type
    assert expected_fragment in failure.message
    # The durable side is untouched: the failure event stands, no result row was written.
    assert journal.results == []
    assert journal.events[-1] == {
        "plan_id": validated.plan_id,
        "workspace_id": trusted.workspace_id,
        "status": "failed",
        "reason_code": "operation_failed",
    }
    assert executor.effect_count == 1


def test_a_failure_message_is_bounded_for_the_next_model_call() -> None:
    adapter, trusted, pin, _, _ = _adapter(
        allowed=("read_project@1",),
        executor=_RefusingExecutor(
            error=ValueError("refused\n" + "x" * 5_000),
            allowed=("read_project@1",),
        ),
    )
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    progress = run_async(_collect(adapter.execute(plan=validated)))

    message = progress[-1].failures[0].message
    assert message.startswith("refused x")
    assert len(message) == _FAILURE_MESSAGE_LIMIT + 1  # the truncation ellipsis


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


def test_every_agent_tool_context_carries_the_turns_actor_and_derived_receipt() -> None:
    """Lane D D1 §3-P2 × Lane B §7: ambient identity is derived from the bound turn, at both seams.

    ``actor_id`` comes from the trusted constitution and ``action_ref`` from this turn's canonical
    ``turn-action:<turn_id>``; neither is a plan argument, a model-visible field, or a caller
    parameter. Deriving the ref here (rather than accepting one) is what makes a human gate's
    receipt un-forgeable: the only ref that can reach a tool is the one for the turn actually
    executing.

    The two seams answer differently on *who invoked*, and that is the Lane B join rather than an
    inconsistency. The executor seam still receives the turn's ``actor_id`` as data (the executor
    decides per node whether that is the invoker or whether the worker's service identity is —
    ``tests/execution/test_executor.py`` owns that). **Pin resolution** has no such choice: it is
    the execution service's own read while it validates a plan the model proposed, performed before
    any node runs and on nobody's behalf. So it runs as ``svc_agent_execution`` — carrying the
    turn's receipt as evidence, because a pin derived for a gated step must see it, but never
    wearing the user's id (Lane B ruling 8).
    """

    pins = _PinProvider()
    adapter, trusted, pin, executor, _ = _adapter(
        allowed=("read_project@1",),
        pin_provider=pins,
        dynamic_pin_kinds=("project",),
    )
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    progress = run_async(_collect(adapter.execute(plan=validated)))
    assert progress[-1].status == "completed"

    expected_ref = derive_turn_action_ref(UUID("00000000-0000-0000-0000-000000000645"))
    assert executor.invoked == [
        {
            "inputs": {"query": "current project"},
            "actor": "agent",
            "actor_id": trusted.actor_id,
            "action_ref": expected_ref,
        }
    ]
    assert [
        (ctx.principal_kind, ctx.actor_id, ctx.membership_id, ctx.action_ref)
        for ctx in pins.contexts
    ] == [("service", "svc_agent_execution", None, expected_ref)]


class _BulkOutput(ToolOutput):
    summary: str
    claims: tuple[str, ...]


class _BulkTool(_Tool):
    """A read whose honest answer is simply larger than a receipt: an account's claim list."""

    output_model = _BulkOutput


class _BulkExecutor(_Executor):
    def __init__(self, *, claim_count: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.claim_count = claim_count
        self.references: dict[str, Any] = {
            "summary": "Acme Robotics: " + "funding and hiring evidence, " * 20,
            "claims": [f"claim-{index:04d}-" + "e" * 48 for index in range(claim_count)],
        }

    async def invoke_interaction_tool(
        self,
        append: InteractionAppend,
        **kwargs: Any,
    ) -> ToolResult:
        del append
        self.invoked.append(kwargs)
        self.effect_count += 1
        return ToolResult(tool="read_project", version="1", references=self.references)


class _RecordingSpillSink:
    """Stands in for the thread workspace: it takes the bytes and names where they landed."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []

    def write_spill(self, operation_id: str, data: bytes) -> str:
        self.writes.append((operation_id, data))
        return f"reads/{operation_id}.json"


def _bulk_adapter(*, sink: Any, claim_count: int = 400):
    executor = _BulkExecutor(claim_count=claim_count, allowed=("read_project@1",))
    return _adapter(
        allowed=("read_project@1",),
        tool=_BulkTool(),
        executor=executor,
        spill_sink=sink,
    )


def test_a_result_too_large_for_its_receipt_spills_instead_of_failing_the_read() -> None:
    """The 2026-09-13 defect, inverted: the read runs, so it must also be *delivered*.

    The receipt bound is a refusal that arrives after the tool has already run and spent, so a
    72-claim account read came back as "the agent cannot read this account". With a sink the same
    oversized result lands in ``reads/`` and the operation completes.
    """

    sink = _RecordingSpillSink()
    adapter, trusted, pin, executor, journal = _bulk_adapter(sink=sink)
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    progress = run_async(_collect(adapter.execute(plan=validated)))

    assert progress[-1].status == "completed"
    assert len(sink.writes) == 1
    operation_id, data = sink.writes[0]
    assert operation_id == str(validated.operations[0].operation_id)
    # The file holds the whole result, canonically — it is the thing the model will open.
    assert len(data) > 12 * 1024
    assert json.loads(data) == executor.references
    # …and the durable spine is untouched: the full result was journaled before any of this.
    assert journal.results[0]["result"].references == executor.references
    assert journal.results[0]["result_ref"].media_type == (
        "application/vnd.clue.agent-tool-result+json"
    )


def test_a_spilled_receipt_carries_a_pointer_and_a_count_rather_than_the_payload() -> None:
    """What the model is handed instead: where the bytes are, how many rows, and a sliver of
    prose, all of it inside the bound the un-spilled result blew through."""

    sink = _RecordingSpillSink()
    adapter, trusted, pin, executor, _ = _bulk_adapter(sink=sink)
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    operation = validated.operations[0]

    receipt = run_async(
        adapter._execute_operation(
            plan=validated,
            operation=operation,
            step=_plan(pin).steps[0],
            completed=set(),
            operation_by_key={operation.node_key: operation},
        )
    )

    assert receipt.status == AgentExecutionStatus.COMPLETED
    assert receipt.reference_values == {
        "spilled_to": f"reads/{operation.operation_id}.json",
        "count": 400,
        "summary": executor.references["summary"][:300],
        "tool": "read_project@1",
    }
    # The result itself is still one hop away, on the receipt that has always carried it.
    assert receipt.artifact_refs[0].media_type == "application/vnd.clue.agent-tool-result+json"
    assert len(json.dumps(receipt.reference_values).encode()) < RECEIPT_REFERENCE_VALUES_MAX_BYTES


def test_an_oversized_result_with_no_sink_keeps_todays_refusal() -> None:
    """A composition root that holds no workspace lease cannot spill, and must not pretend to."""

    adapter, trusted, pin, _, _ = _bulk_adapter(sink=None)
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))

    progress = run_async(_collect(adapter.execute(plan=validated)))

    assert progress[-1].status == "failed"
    assert "16 KiB" in progress[-1].failures[0].message


def test_a_result_inside_the_budget_is_never_spilled() -> None:
    """The sink is for the overflow only. A read that fits still rides inside its own receipt."""

    sink = _RecordingSpillSink()
    adapter, trusted, pin, executor, _ = _bulk_adapter(sink=sink, claim_count=4)
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    operation = validated.operations[0]

    receipt = run_async(
        adapter._execute_operation(
            plan=validated,
            operation=operation,
            step=_plan(pin).steps[0],
            completed=set(),
            operation_by_key={operation.node_key: operation},
        )
    )

    assert sink.writes == []
    assert receipt.reference_values == executor.references


def test_the_receipt_the_model_reads_carries_the_stub_not_the_payload() -> None:
    """The public path, end to end. ``execute`` drops the receipt it builds; the model is handed
    the one ``recover`` rebuilds from the result artifact. If hydration restored the full
    references the threshold would be a rule the model never actually sees, and the oversized
    payload would reach its context anyway — the defect, moved rather than fixed."""

    sink = _RecordingSpillSink()
    adapter, trusted, pin, executor, _ = _bulk_adapter(sink=sink)
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    progress = run_async(_collect(adapter.execute(plan=validated)))
    assert progress[-1].status == "completed"

    recovered = run_async(adapter.recover(execution_id=validated.execution_id))
    receipts = recovered["operation_receipts"]
    assert isinstance(receipts, tuple)
    receipt = receipts[0]
    assert isinstance(receipt, GovernedOperationReceipt)

    operation_id = validated.operations[0].operation_id
    assert receipt.reference_values == {
        "spilled_to": f"reads/{operation_id}.json",
        "count": 400,
        "summary": executor.references["summary"][:300],
        "tool": "read_project@1",
    }
    # Hydration re-spills the same operation to the same name — a rewrite, not a second file —
    # and the bytes behind the pointer are still the whole result.
    assert {name for name, _ in sink.writes} == {str(operation_id)}
    assert json.loads(sink.writes[-1][1]) == executor.references


def test_the_recovered_receipt_keeps_the_full_references_when_they_fit() -> None:
    """The rebuilt receipt is only a stub when the result earned one."""

    sink = _RecordingSpillSink()
    adapter, trusted, pin, executor, _ = _bulk_adapter(sink=sink, claim_count=4)
    validated = run_async(adapter.validate_plan(plan=_plan(pin), constitution=trusted))
    run_async(_collect(adapter.execute(plan=validated)))

    recovered = run_async(adapter.recover(execution_id=validated.execution_id))
    receipts = recovered["operation_receipts"]
    assert isinstance(receipts, tuple)
    receipt = receipts[0]
    assert isinstance(receipt, GovernedOperationReceipt)

    assert receipt.reference_values == executor.references
    assert sink.writes == []
