"""Two real Head-of-ABM turns on one thread: the second continues the first (spec 2026-09-29 §3.1).

The production chain of ``test_o6_conversation_composition_db`` with one substitution, the chat
model, which here also records every request it receives. What a continued turn must send is the
previous turn's whole conversation — its tool call and tool result included — byte-identical, and
only then this turn's cards and message.
"""

from __future__ import annotations

import dataclasses
import math
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from deepagents.middleware.summarization import DEEPAGENTS_DEFAULT_SUMMARY_PROMPT
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import text

from clue_agents import AgentExecutionStatus, ScriptedAgentChatModel
from clue_agents.compaction import ClueSummarizationMiddleware
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


#: The opening of deepagents' summary prompt: a request that carries it is a compaction call.
_SUMMARY_MARKER = DEEPAGENTS_DEFAULT_SUMMARY_PROMPT[:80]
SUMMARY = "SUMMARY-OF-THE-EARLIER-CONVERSATION"


class _RecordingModel(ScriptedAgentChatModel):
    #: ``Any`` so pydantic keeps the shared lists instead of validating copies of them.
    sink: Any
    summaries: Any

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        if any(_SUMMARY_MARKER in str(message.content) for message in messages):
            # A compaction call: answered with a summary, never with the turn's script.
            self.summaries.append(list(messages))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=SUMMARY))])
        self.sink.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


class _RecordingModels:
    """Every build answers the same script and records into one shared list of requests."""

    def __init__(self) -> None:
        self.requests: list[list[BaseMessage]] = []
        self.summaries: list[list[BaseMessage]] = []
        self.build_count = 0

    def build(self, **kwargs: Any) -> ScriptedAgentChatModel:
        del kwargs
        self.build_count += 1
        # Tool-call ids are unique per build, as a real model's are: a continued conversation
        # already holds the earlier turn's calls.
        return _RecordingModel(
            responses=_responses(f"b{self.build_count}"),
            sink=self.requests,
            summaries=self.summaries,
        )


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


FIRST_MESSAGE = "Turn-one-unique: who should we target first in the GI segment?"


def test_a_thread_compacts_once_and_later_turns_build_on_the_summary(tmp_path: Path) -> None:
    """Compaction across turns (spec 2026-09-29 §3.2), with a window sized so turn 2 crosses it.

    Turn 1 runs under a huge window and its largest request is measured with the summariser's own
    counter. The window is then set just above it, so turn 2 — which carries all of turn 1 plus
    its own cards — is the first to cross the trigger. Turn 3 must build on turn 2's summary: it
    carries the summary, not turn 1's text, and does not compact again.
    """

    counts: list[int] = []
    real_count = ClueSummarizationMiddleware._count_tokens

    def counting(self: Any, *args: Any, **kwargs: Any) -> int:
        total = real_count(self, *args, **kwargs)
        counts.append(total)
        return total

    saved = {
        key: os.environ.get(key)
        for key in ("CLUE_AGENT_CONTEXT_WINDOW_TOKENS", "CLUE_AGENT_COMPACT_KEEP_FRACTION")
    }

    async def scenario() -> None:
        async with postgres_agent_checkpointer(ExecutionId(uuid4())):
            pass
        async with rollback_conn() as conn:
            workspace_id = f"cont-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="Compaction project")
            stack = await _build_stack(conn, tmp_path=tmp_path)
            models = _RecordingModels()
            stack.models = models  # type: ignore[assignment]
            stack.components = dataclasses.replace(
                stack.components, models=models, head_of_abm_continuation_enabled=True
            )
            try:
                os.environ["CLUE_AGENT_CONTEXT_WINDOW_TOKENS"] = "100000000"
                os.environ["CLUE_AGENT_COMPACT_KEEP_FRACTION"] = "0.01"
                thread_id = None
                submissions = []
                for index, body in enumerate(
                    (FIRST_MESSAGE, SECOND_MESSAGE, "Turn three: and the rest?")
                ):
                    submission = await _capture_submission(
                        conn,
                        artifacts=stack.artifacts,
                        workspace_id=workspace_id,
                        project_id=project.project_id,
                        brand_id=project.brand_id,
                        label=f"compaction-{index}",
                        thread_id=thread_id,
                        message_body=body,
                    )
                    thread_id = submission.thread_id
                    submissions.append((submission, len(models.requests)))
                    result = await _run_turn(
                        conn,
                        stack,
                        workspace_id=workspace_id,
                        submission=submission,
                        worker_id="compaction-worker",
                    )
                    assert result.outcome == AgentExecutionStatus.AWAITING_INPUT.value
                    if index == 0:
                        assert models.summaries == []
                        window = math.ceil((max(counts) + 50) / 0.9)
                        os.environ["CLUE_AGENT_CONTEXT_WINDOW_TOKENS"] = str(window)

                # Exactly one compaction across turns 2 and 3.
                assert len(models.summaries) == 1
                # The summary is built from the whole evicted part — turn 1's own words included —
                # not only its last few thousand tokens.
                assert any(FIRST_MESSAGE in str(m.content) for m in models.summaries[0])
                # Turn 3 opens on turn 2's summary, and turn 1's own words are gone from it.
                third_first = models.requests[submissions[2][1]]
                texts = [str(message.content) for message in third_first]
                assert any(SUMMARY in text for text in texts)
                assert not any(FIRST_MESSAGE in text for text in texts)
                # The evicted history was offloaded into the thread's own workspace, under work/.
                second_execution = (
                    await conn.execute(
                        text("SELECT execution_id FROM agent_turn WHERE id=:turn"),
                        {"turn": submissions[1][0].turn_id},
                    )
                ).scalar_one()
                after = stack.workspaces.reopen()
                offloaded = after.backend.read_text_sync(
                    f"work/conversation_history/{second_execution}.md"
                )
                after.release()
                assert FIRST_MESSAGE in offloaded
            finally:
                stack.workspaces.close()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ClueSummarizationMiddleware, "_count_tokens", counting)
        try:
            run_async(scenario())
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_an_unreadable_saved_conversation_opens_the_next_turn_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §3.1: a resume point whose checkpoint cannot be read means a fresh rebuild.

    Without it, the thread would fail on every later turn — the resume point never changes.
    """
    from clue_api.head_of_abm_wiring import HeadOfAbmStage0Runtime

    async def unreadable(self: Any, **kwargs: Any) -> bool:
        del self, kwargs
        raise ValueError("checkpoint could not be deserialized")

    monkeypatch.setattr(HeadOfAbmStage0Runtime, "continuation_is_settled", unreadable)

    async def check(conn: Any, last_of_a: list[BaseMessage], first_of_b: list[BaseMessage]) -> None:
        del conn
        _opens_fresh(last_of_a, first_of_b)

    _scenario(tmp_path, check)
