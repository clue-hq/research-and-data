"""The model-facing finalize contract is at least as strict as the durable envelope.

``ModelFinalizeRequest`` is what the model fills in; :class:`AgentFinalizeEnvelope` is what the
platform durably commits. When the model-facing shape is *looser*, a model proposal passes the
tool boundary and then dies inside envelope construction — the live Stage-0 defect, where Terra
finalized ``status=awaiting_input`` with a ``failure_code`` and the turn ended ``missing_finalize``
with no feedback the model could act on. These tests pin both halves of the repair: the model
boundary rejects exactly what the envelope rejects, and a rejection is a *visible* tool error with
one bounded corrective retry before the turn fails closed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from clue_agents import (
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    FinalizeStatus,
    WorkspaceEntry,
)
from clue_agents import runtime as runtime_module
from clue_agents.contracts import ReasonCode
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory, ModelFinalizeRequest
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.conftest import EXECUTION_ID, NOW, artifact, constitution
from tests.agents.test_contracts import context_manifest
from tests.agents.test_runtime import (
    _DelegationArtifacts,
    _EmptyOutputBackend,
    _Execution,
    _Models,
)
from tests.db.conftest import run_async

_QUESTION = "Which specialist healthcare practices should this project prioritize?"
_LIVE_FAILURE_CODE = "interview_routing_validation_failed"


# --- the validator: every status x failure_code combination -------------------------------


@pytest.mark.parametrize(
    ("status", "failure_code", "accepted"),
    [
        ("completed", None, True),
        ("completed", "interview_routing_validation_failed", False),
        ("awaiting_input", None, True),
        ("awaiting_input", "interview_routing_validation_failed", False),
        ("blocked", None, True),
        ("blocked", "interview_routing_validation_failed", False),
        ("failed", None, False),
        ("failed", "interview_routing_validation_failed", True),
    ],
)
def test_failure_code_is_required_exactly_for_failed(
    status: str,
    failure_code: str | None,
    accepted: bool,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "user_message": _QUESTION,
        "failure_code": failure_code,
    }
    if accepted:
        assert ModelFinalizeRequest.model_validate(payload).failure_code == failure_code
        return
    with pytest.raises(ValidationError):
        ModelFinalizeRequest.model_validate(payload)


def test_the_exact_live_stage0_proposal_is_refused_at_the_model_boundary() -> None:
    with pytest.raises(ValidationError, match="failure_code"):
        ModelFinalizeRequest.model_validate(
            {
                "status": "awaiting_input",
                "user_message": _QUESTION,
                "failure_code": _LIVE_FAILURE_CODE,
            }
        )


def test_completed_requires_the_user_message_the_envelope_demands() -> None:
    with pytest.raises(ValidationError, match="user_message"):
        ModelFinalizeRequest.model_validate({"status": "completed"})


def test_non_terminal_status_must_identify_what_it_is_waiting_for() -> None:
    with pytest.raises(ValidationError, match="next_actions"):
        ModelFinalizeRequest.model_validate({"status": "awaiting_input"})
    with pytest.raises(ValidationError, match="next_actions"):
        ModelFinalizeRequest.model_validate({"status": "blocked"})


def test_non_terminal_status_accepts_an_explicit_next_action_without_a_message() -> None:
    request = ModelFinalizeRequest.model_validate(
        {"status": "awaiting_input", "next_actions": ["Answer the ICP question."]}
    )
    assert request.next_actions == ("Answer the ICP question.",)


def test_failed_needs_no_user_message_because_the_envelope_does_not() -> None:
    request = ModelFinalizeRequest.model_validate(
        {"status": "failed", "failure_code": _LIVE_FAILURE_CODE}
    )
    assert request.status is FinalizeStatus.FAILED


# --- the failure_code *value* shape, not just its presence ---------------------------------


def _envelope(failure_code: str) -> AgentFinalizeEnvelope:
    return AgentFinalizeEnvelope(
        finalization_id=UUID("00000000-0000-0000-0000-0000000006f0"),
        execution_id=EXECUTION_ID,
        status=FinalizeStatus.FAILED,
        failure_code=failure_code,
        finalized_at=NOW,
    )


def test_the_model_field_reuses_the_envelope_type_instead_of_copying_its_pattern() -> None:
    # A hand-copied ``StringConstraints`` is how a boundary silently drifts loose again. Pin that
    # both sides resolve to the *same* annotated type, so tightening one tightens the other.
    model_field = ModelFinalizeRequest.model_fields["failure_code"]
    envelope_field = AgentFinalizeEnvelope.model_fields["failure_code"]

    assert model_field.annotation == envelope_field.annotation
    assert model_field.annotation == (ReasonCode | None)


@pytest.mark.parametrize(
    "failure_code",
    [
        "interview_routing_validation_failed",
        "interview_routing.validation_failed",
        "routing-failed",
        "9_failed",
        "a" * 128,
        "Interview_Failed",
        "interview routing failed",
        "interview_routing_validation_failed!",
        "a" * 129,
        "",
    ],
)
def test_the_model_boundary_and_the_envelope_agree_on_every_failure_code(
    failure_code: str,
) -> None:
    """Whatever the envelope refuses, the model boundary must refuse too — and vice versa.

    Presence parity is not enough: a ``failed`` turn whose ``failure_code`` passes the model
    boundary and then dies in envelope construction is the same defect on the same field.
    """

    try:
        _envelope(failure_code)
    except ValidationError:
        envelope_accepts = False
    else:
        envelope_accepts = True

    try:
        ModelFinalizeRequest.model_validate({"status": "failed", "failure_code": failure_code})
    except ValidationError:
        model_accepts = False
    else:
        model_accepts = True

    assert model_accepts == envelope_accepts


# --- parity: whatever the model boundary accepts, the durable envelope also accepts --------


def _factory(execution: object) -> GovernedAgentToolFactory:
    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    request = AgentTurnRequest(
        turn_id=UUID("00000000-0000-0000-0000-000000000644"),
        thread_id="thread-finalize-contract",
        constitution=constitution(
            profile_ref=resolved.profile_ref,
            resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
        ),
        user_message_artifact_ref=artifact("user-message.json"),
        requested_at=NOW,
    )
    return GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, SimpleNamespace(backend=_EmptyOutputBackend())),
        artifacts=cast(Any, _DelegationArtifacts()),
    )


class _RecordingFinalization:
    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    async def finalize(self, *, envelope: Any) -> ArtifactRef:
        self.envelopes.append(envelope)
        return artifact("finalization-envelope.json")

    async def check_finalizable(self, *, status: Any) -> None:
        del status


def test_the_model_is_told_the_status_contract_it_will_be_held_to() -> None:
    # A plain object schema cannot express "failure_code iff status='failed'", so the only place
    # the model can learn the rule before proposing is the tool description.
    description = _factory(_RecordingFinalization()).build()[-1].description

    assert "failure_code" in description
    assert "'failed'" in description
    assert "user_message" in description
    assert "next_actions" in description


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "completed", "user_message": _QUESTION},
        {"status": "awaiting_input", "user_message": _QUESTION},
        {"status": "awaiting_input", "next_actions": ["Answer the ICP question."]},
        {"status": "blocked", "user_message": _QUESTION},
        {"status": "failed", "failure_code": _LIVE_FAILURE_CODE},
    ],
)
def test_every_accepted_model_proposal_builds_a_durable_envelope(payload: dict[str, Any]) -> None:
    execution = _RecordingFinalization()
    finalizer = _factory(execution).build()[-1]
    coroutine = finalizer.coroutine
    assert coroutine is not None

    run_async(coroutine(runtime=cast(Any, object()), **payload))

    envelope = execution.envelopes[0]
    assert envelope.status.value == payload["status"]


# --- model-visible feedback with one bounded corrective retry ------------------------------


class _FinalizingExecutionAdapter(_Execution):
    """Adapter fake whose committed finalization is what the runtime recovers."""

    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[Any] = []

    async def finalize(self, *, envelope: Any) -> ArtifactRef:
        self.envelopes.append(envelope)
        ref = artifact(f"finalization-{len(self.envelopes)}.json")
        self.recovered = {
            "finalization_status": envelope.status.value,
            "finalization_ref": ref,
        }
        return ref


class _CountModelCalls(BaseCallbackHandler):
    def __init__(self) -> None:
        self.batches: list[list[Any]] = []

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        del serialized, kwargs
        self.batches.append(messages[0])


def _finalize_call(call_id: str, **args: Any) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "finalize_turn",
                "args": args,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


class _EmptyRequiredOutputBackend(_EmptyOutputBackend):
    """Workspace whose required role output exists but is empty.

    Drives ``_finalize_tool``'s own ``ValueError`` guard — a refusal raised *inside* the tool
    coroutine, not by the args schema, so it exercises the exception arm of ``_bounded_finalize``.
    """

    async def stat_entry(self, path: str) -> WorkspaceEntry:
        return WorkspaceEntry(path=path, kind="file", byte_count=0, sha256=None, read_only=False)


def _run(
    responses: tuple[AIMessage, ...],
    *,
    required_output_path: str | None = None,
    backend: object | None = None,
    completion_guard: Any | None = None,
    execution: _FinalizingExecutionAdapter | None = None,
) -> tuple[Any, _FinalizingExecutionAdapter, Any]:
    execution = execution if execution is not None else _FinalizingExecutionAdapter()
    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    request = AgentTurnRequest(
        turn_id=UUID("00000000-0000-0000-0000-000000000645"),
        thread_id="thread-finalize-feedback",
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
        lease=cast(Any, SimpleNamespace(backend=backend or _EmptyOutputBackend())),
        artifacts=cast(Any, _DelegationArtifacts()),
        required_output_path=required_output_path,
        completion_guard=completion_guard,
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
                messages=(HumanMessage(content="Ask the next useful question."),),
            ),
            backend=None,
            governed_tools=factory.build(),
            callbacks=(calls,),
        )
    )
    return outcome, execution, calls


def test_an_invalid_finalization_is_repaired_from_visible_tool_feedback() -> None:
    outcome, execution, calls = _run(
        (
            _finalize_call(
                "finalize-invalid",
                status="awaiting_input",
                user_message=_QUESTION,
                failure_code=_LIVE_FAILURE_CODE,
            ),
            _finalize_call(
                "finalize-valid",
                status="awaiting_input",
                user_message=_QUESTION,
            ),
        )
    )

    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert outcome.finalization_ref is not None
    assert [envelope.status for envelope in execution.envelopes] == [FinalizeStatus.AWAITING_INPUT]
    # The rejected proposal came back to the model as a tool error it could read and repair.
    assert len(calls.batches) == 2
    feedback = str(calls.batches[1][-1].content)
    assert "failure_code" in feedback


def test_a_shape_rejection_and_a_guard_rejection_share_one_budget_and_still_commit() -> None:
    """The two independent finalize rejectors must not be able to starve each other.

    A Stage-0 turn can be refused twice for genuinely different, both-repairable reasons: once by
    the finalize *shape* contract (``ModelFinalizeRequest``) and once by the surface's
    ``CompletionGuard`` (the routing-receipt guard). With a single shared repair the model spent
    its only attempt on the shape error and the honest, guard-corrected finalization never got a
    turn — the turn died ``missing_finalize`` even though the model was converging.
    """

    guard_refusals: list[FinalizeStatus] = []

    async def routing_receipt_guard(model_input: ModelFinalizeRequest) -> None:
        # Refuse only the first guarded proposal, as the real receipt guard does once the model
        # routes the input on its next attempt.
        if not guard_refusals:
            guard_refusals.append(model_input.status)
            raise ValueError("route the human's message before reporting this turn as done")

    outcome, execution, calls = _run(
        (
            _finalize_call(
                "finalize-shape-invalid",
                status="awaiting_input",
                user_message=_QUESTION,
                failure_code=_LIVE_FAILURE_CODE,
            ),
            _finalize_call(
                "finalize-guard-refused",
                status="awaiting_input",
                user_message=_QUESTION,
            ),
            _finalize_call(
                "finalize-valid",
                status="awaiting_input",
                user_message=_QUESTION,
            ),
        ),
        completion_guard=routing_receipt_guard,
    )

    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert outcome.finalization_ref is not None
    assert [envelope.status for envelope in execution.envelopes] == [FinalizeStatus.AWAITING_INPUT]
    assert guard_refusals == [FinalizeStatus.AWAITING_INPUT]
    # Both rejectors were seen and repaired inside one turn: three model calls, one commit.
    assert len(calls.batches) == 3
    assert "failure_code" in str(calls.batches[1][-1].content)
    assert "route the human's message" in str(calls.batches[2][-1].content)


def test_three_invalid_finalizations_still_fail_closed() -> None:
    outcome, execution, calls = _run(
        (
            _finalize_call(
                "finalize-invalid-1",
                status="awaiting_input",
                user_message=_QUESTION,
                failure_code=_LIVE_FAILURE_CODE,
            ),
            _finalize_call(
                "finalize-invalid-2",
                status="completed",
                user_message=_QUESTION,
                failure_code=_LIVE_FAILURE_CODE,
            ),
            _finalize_call(
                "finalize-invalid-3",
                status="blocked",
                user_message=_QUESTION,
                failure_code=_LIVE_FAILURE_CODE,
            ),
        )
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "missing_finalize"
    assert outcome.finalization_ref is None
    assert execution.envelopes == []
    # Two bounded corrective retries — one per independent rejector — and no more: a model that
    # proposes a dishonest terminal shape a third time is refusing the contract, not misreading it.
    assert len(calls.batches) == 3


# --- refusals raised *inside* the finalize coroutine (the broad ValueError arm) -------------


def test_a_guard_raised_inside_the_finalize_tool_reaches_the_model_and_the_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain ``ValueError`` from a finalize guard is model feedback *and* an operator signal.

    ``ModelFinalizeRequest`` accepts this payload, so the refusal happens in the coroutine, past
    the args schema. Without the exception arm it crashes the graph unseen; with it, the turn now
    ends ``missing_finalize`` instead of surfacing the guard's own exception — so the swallowed
    error must be logged, or the diagnosis is lost.
    """

    emitted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        runtime_module,
        "log",
        SimpleNamespace(warning=lambda event, **fields: emitted.append((event, fields))),
    )
    outcome, execution, calls = _run(
        (
            _finalize_call("finalize-guard-1", status="completed", user_message=_QUESTION),
            _finalize_call("finalize-guard-2", status="completed", user_message=_QUESTION),
            _finalize_call("finalize-guard-3", status="completed", user_message=_QUESTION),
        ),
        required_output_path="outputs/review-verdict.md",
        backend=_EmptyRequiredOutputBackend(),
    )

    # The guard's own words reached the model, which got its two bounded corrective attempts.
    assert len(calls.batches) == 3
    feedback = str(calls.batches[1][-1].content)
    assert "non-empty role output file" in feedback
    # ... and the same error is on the operator's side, not only in the model transcript.
    assert [event for event, _ in emitted] == ["agent.finalize_refused"] * 3
    assert emitted[0][1]["error_type"] == "ValueError"
    assert "non-empty role output file" in emitted[0][1]["error"]
    assert [fields["rejection"] for _, fields in emitted] == [1, 2, 3]
    # Fail-closed is unchanged: nothing committed, one stable code.
    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "missing_finalize"
    assert execution.envelopes == []


# --- refusals before outputs are frozen (McKee, production 2026-10-03) --------------------------


class _RefuseOnceExecutionAdapter(_FinalizingExecutionAdapter):
    """Refuses the first completed finalize the way the executor does for unresolved failures."""

    def __init__(self) -> None:
        super().__init__()
        self.checks = 0

    async def check_finalizable(self, *, status: FinalizeStatus) -> None:
        self.checks += 1
        if status is FinalizeStatus.COMPLETED and self.checks == 1:
            raise ValueError(
                "Unresolved failed tool attempts remain: agent_search_evidence_1. "
                "Correct using retry_of, or finalize with an honest blocked status."
            )


class _FreezingBackend(_EmptyOutputBackend):
    """Counts snapshots of outputs/."""

    def __init__(self) -> None:
        self.snapshots = 0

    async def snapshot_outputs(self, *, empty_after: bool = False) -> tuple[ArtifactRef, ...]:
        del empty_after
        self.snapshots += 1
        return ()


def test_a_refused_finalize_freezes_nothing_and_the_repaired_finalize_completes() -> None:
    backend = _FreezingBackend()
    guard_calls: list[FinalizeStatus] = []

    async def writes_outputs_guard(model_input: ModelFinalizeRequest) -> None:
        # The real research guard writes outputs/research.json; after a snapshot that write
        # raises WorkspaceConflict (a RuntimeError the repair loop cannot recover from).
        from clue_agents.workspace_policy import WorkspaceConflict

        if backend.snapshots:
            raise WorkspaceConflict("snapshotted outputs are immutable")
        guard_calls.append(model_input.status)

    execution = _RefuseOnceExecutionAdapter()
    outcome, recorded, _calls = _run(
        (
            _finalize_call("finalize-refused", status="completed", user_message="Done."),
            _finalize_call("finalize-repaired", status="completed", user_message="Done."),
        ),
        backend=backend,
        completion_guard=writes_outputs_guard,
        execution=execution,
    )
    assert outcome.status is AgentExecutionStatus.COMPLETED
    assert recorded is execution
    assert execution.checks == 2
    assert backend.snapshots == 1
    assert guard_calls == [FinalizeStatus.COMPLETED]
    assert [e.status for e in execution.envelopes] == [FinalizeStatus.COMPLETED]
