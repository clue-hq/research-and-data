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
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    FinalizeStatus,
)
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory, ModelFinalizeRequest
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.conftest import NOW, artifact, constitution
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


def _run(responses: tuple[AIMessage, ...]) -> tuple[Any, _FinalizingExecutionAdapter, Any]:
    execution = _FinalizingExecutionAdapter()
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


def test_two_invalid_finalizations_still_fail_closed() -> None:
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
        )
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "missing_finalize"
    assert outcome.finalization_ref is None
    assert execution.envelopes == []
    # Exactly one bounded corrective retry: the model is not asked a third time.
    assert len(calls.batches) == 2
