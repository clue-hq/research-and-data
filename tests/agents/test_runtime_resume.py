"""A re-claimed first turn continues its own saved conversation (spec 2026-10-14 §3.1).

The research runner opens every turn fresh. When a worker dies mid-turn and the job is claimed
again, the same turn runs again; with ``resume_saved_turn`` the runtime continues the turn's own
saved state instead of feeding the opening messages into it a second time.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from clue_agents import AgentTurnRequest, AssembledAgentContext, DeepAgentTurnRuntime
from clue_agents.model import ScriptedAgentChatModel
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.test_contracts import context_manifest
from tests.agents.test_runtime import _CaptureModelInput, _request
from tests.agents.test_runtime_continuation import (
    _CrashingModel,
    _FirstRequest,
    _Models,
    _SharedSaverExecution,
)
from tests.db.conftest import run_async

OPENING = "Research the account: resume marker 41c2."


def _run(
    request: AgentTurnRequest,
    resolved: Any,
    execution: _SharedSaverExecution,
    model: ScriptedAgentChatModel,
    messages: tuple[BaseMessage, ...],
    *,
    resume_saved_turn: bool,
    capture: _CaptureModelInput | None = None,
) -> Any:
    runtime = DeepAgentTurnRuntime(
        models=_Models(model),
        execution=execution,
        max_runtime_s=10,
        resume_saved_turn=resume_saved_turn,
    )
    tools = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    ).build()
    return run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,
            context=AssembledAgentContext(
                manifest=context_manifest().model_copy(
                    update={"execution_id": request.constitution.execution_id}
                ),
                messages=messages,
            ),
            backend=None,
            governed_tools=tools,
            callbacks=(capture,) if capture is not None else (),
        )
    )


def test_a_reclaimed_first_turn_continues_its_saved_conversation() -> None:
    request, resolved = _request()
    execution = _SharedSaverExecution(InMemorySaver())
    opening = (HumanMessage(content=OPENING),)

    crashed = _run(
        request,
        resolved,
        execution,
        _CrashingModel(responses=(AIMessage(content="never"),)),
        opening,
        resume_saved_turn=True,
    )
    assert crashed.status.value == "failed"

    capture = _FirstRequest()
    _run(
        request,
        resolved,
        execution,
        ScriptedAgentChatModel(
            responses=(AIMessage(content="Answer."), AIMessage(content="Done."))
        ),
        opening,
        resume_saved_turn=True,
        capture=capture,
    )
    sent = [str(getattr(message, "content", "")) for message in capture.messages[0]]
    assert sent.count(OPENING) == 1


def test_a_turn_with_no_saved_state_opens_with_its_messages() -> None:
    request, resolved = _request()
    execution = _SharedSaverExecution(InMemorySaver())
    capture = _FirstRequest()
    _run(
        request,
        resolved,
        execution,
        ScriptedAgentChatModel(
            responses=(AIMessage(content="Answer."), AIMessage(content="Done."))
        ),
        (HumanMessage(content=OPENING),),
        resume_saved_turn=True,
        capture=capture,
    )
    sent = [str(getattr(message, "content", "")) for message in capture.messages[0]]
    assert sent.count(OPENING) == 1
