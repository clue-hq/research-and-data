"""Two real Head-of-ABM turns on one thread: the second continues the first (spec 2026-09-29 §3.1).

The production chain of ``test_o6_conversation_composition_db`` with one substitution, the chat
model, which here also records every request it receives. What a continued turn must send is the
previous turn's whole conversation — its tool call and tool result included — byte-identical, and
only then this turn's cards and message.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage
from sqlalchemy import text

from clue_agents import AgentExecutionStatus, ScriptedAgentChatModel
from clue_api.agent_execution_wiring import postgres_agent_checkpointer
from clue_core import ExecutionId
from tests._workspace import seed_project
from tests.api.test_o6_conversation_composition_db import (
    _build_stack,
    _capture_submission,
    _run_turn,
    _Stack,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

SECOND_MESSAGE = "Actually, start with the ambulatory centers."


class _RecordingModel(ScriptedAgentChatModel):
    #: ``Any`` so pydantic keeps the shared list instead of validating a copy of it.
    sink: Any

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.sink.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


class _RecordingModels:
    """Every build answers the same script and records into one shared list of requests."""

    def __init__(self) -> None:
        self.requests: list[list[BaseMessage]] = []
        self.build_count = 0

    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        self.build_count += 1
        # Tool-call ids are unique per build, as a real model's are: a continued conversation
        # already holds the earlier turn's calls.
        return _RecordingModel(responses=_responses(f"b{self.build_count}"), sink=self.requests)


def _responses(tag: str) -> tuple[AIMessage, ...]:
    """Read this turn's message (a real tool call and result), then ask the human something."""
    return (
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"file_path": "/inputs/user-message.txt"},
                    "id": f"continuation-read-{tag}",
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
                        "status": "awaiting_input",
                        "user_message": "Shall we start with the GI groups?",
                    },
                    "id": f"continuation-finalize-{tag}",
                    "type": "tool_call",
                }
            ],
        ),
    )


def _wire(message: BaseMessage) -> tuple[Any, ...]:
    """What the provider is sent for one message (ids are local bookkeeping, not sent)."""
    return (
        message.type,
        message.content,
        tuple(
            (call["name"], tuple(sorted(call["args"].items())), call["id"])
            for call in getattr(message, "tool_calls", ()) or ()
        ),
        getattr(message, "tool_call_id", None),
    )


async def _two_turns(
    conn: Any, stack: _Stack, workspace_id: str, project: Any, *, between: Any = None
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Run two turns on one thread; return turn A's last request and turn B's first."""
    first = await _capture_submission(
        conn,
        artifacts=stack.artifacts,
        workspace_id=workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        label="continuation-one",
    )
    result = await _run_turn(
        conn, stack, workspace_id=workspace_id, submission=first, worker_id="continuation-worker"
    )
    assert result.outcome == AgentExecutionStatus.AWAITING_INPUT.value
    models = stack.models
    assert isinstance(models, _RecordingModels)
    last_of_a = models.requests[-1]
    seen = len(models.requests)
    if between is not None:
        await between(first)
    second = await _capture_submission(
        conn,
        artifacts=stack.artifacts,
        workspace_id=workspace_id,
        project_id=project.project_id,
        brand_id=project.brand_id,
        label="continuation-two",
        thread_id=first.thread_id,
        message_body=SECOND_MESSAGE,
    )
    result = await _run_turn(
        conn, stack, workspace_id=workspace_id, submission=second, worker_id="continuation-worker"
    )
    assert result.outcome == AgentExecutionStatus.AWAITING_INPUT.value
    return last_of_a, models.requests[seen]


def _scenario(
    tmp_path: Path, check: Any, *, continuation: bool = True, between: Any = None
) -> None:
    async def scenario() -> None:
        # LangGraph installs a concurrent index; do it before the rollback fixture's transaction.
        async with postgres_agent_checkpointer(ExecutionId(uuid4())):
            pass
        async with rollback_conn() as conn:
            workspace_id = f"cont-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="Continuation project")
            stack = await _build_stack(conn, tmp_path=tmp_path)
            stack.models = _RecordingModels()
            stack.components = dataclasses.replace(
                stack.components,
                models=stack.models,
                head_of_abm_continuation_enabled=continuation,
            )
            try:
                bound = (lambda first: between(conn, first)) if between is not None else None
                last_of_a, first_of_b = await _two_turns(
                    conn, stack, workspace_id, project, between=bound
                )
                await check(conn, last_of_a, first_of_b)
            finally:
                stack.workspaces.close()

    run_async(scenario())


def _reads_of_the_first_message(request: list[BaseMessage]) -> int:
    """How often the first turn's own ``read_file`` call (built first: ``b1``) appears."""
    return sum(
        1
        for message in request
        for call in getattr(message, "tool_calls", ()) or ()
        if call["id"] == "continuation-read-b1"
    )


def test_the_second_turn_opens_with_the_first_turns_whole_conversation(tmp_path: Path) -> None:
    async def check(conn: Any, last_of_a: list[BaseMessage], first_of_b: list[BaseMessage]) -> None:
        del conn
        # Byte-identical prefix: everything turn A last sent is turn B's opening, unchanged.
        assert [_wire(m) for m in first_of_b[: len(last_of_a)]] == [_wire(m) for m in last_of_a]
        # Then A's closing tool call and its result, carried whole (Claude-Code-faithful).
        closing = first_of_b[len(last_of_a)]
        assert [call["name"] for call in closing.tool_calls] == ["finalize_turn"]  # type: ignore[attr-defined]
        assert first_of_b[len(last_of_a) + 1].type == "tool"
        # A's tool call and result are in B's opening exactly once — and B's message is last.
        assert _reads_of_the_first_message(first_of_b) == 1
        assert first_of_b[-1].type == "human"
        assert SECOND_MESSAGE in str(first_of_b[-1].content)
        # The system prompt is not sent a second time.
        system = [_wire(m) for m in first_of_b if m.type == "system"]
        assert system == [_wire(m) for m in last_of_a if m.type == "system"] + [
            _wire(m) for m in first_of_b[len(last_of_a) + 2 :] if m.type == "system"
        ]

    _scenario(tmp_path, check)


def _opens_fresh(last_of_a: list[BaseMessage], first_of_b: list[BaseMessage]) -> None:
    # A fresh turn carries the thread's messages, never an earlier turn's tool calls.
    assert _reads_of_the_first_message(first_of_b) == 0
    assert [_wire(m) for m in first_of_b[: len(last_of_a)]] != [_wire(m) for m in last_of_a]
    assert SECOND_MESSAGE in str(first_of_b[-1].content)


def test_a_changed_profile_opens_the_next_turn_fresh(tmp_path: Path) -> None:
    async def ran_under_another_profile(conn: Any, first: Any) -> None:
        # The first turn's saved conversation carries its own (now different) system prompt.
        # `agent_turn` is append-only; the rewrite happens inside the test's rolled-back
        # transaction only, standing in for a turn that ran before a profile promotion.
        await conn.execute(text("ALTER TABLE agent_turn DISABLE TRIGGER USER"))
        await conn.execute(
            text("UPDATE agent_turn SET profile_version='v0' WHERE id=:turn"),
            {"turn": first.turn_id},
        )
        await conn.execute(text("ALTER TABLE agent_turn ENABLE TRIGGER USER"))

    async def check(conn: Any, last_of_a: list[BaseMessage], first_of_b: list[BaseMessage]) -> None:
        del conn
        _opens_fresh(last_of_a, first_of_b)

    _scenario(tmp_path, check, between=ran_under_another_profile)


def test_continuation_off_opens_every_turn_fresh(tmp_path: Path) -> None:
    async def check(conn: Any, last_of_a: list[BaseMessage], first_of_b: list[BaseMessage]) -> None:
        del conn
        _opens_fresh(last_of_a, first_of_b)

    _scenario(tmp_path, check, continuation=False)
