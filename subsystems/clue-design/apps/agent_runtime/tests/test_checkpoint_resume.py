"""The durable-graph seam: what a second turn on a design document's thread actually does.

Design session continuity (founder ruling 2026-09-18) replaced D5's resume-as-restart. The
thread is the document's SESSION, not one turn's scratch space, so a thread that already carries
state is the normal case: a NEW run appends its user message and the graph continues with every
earlier tool call, result and critique still in the window, while a RETRIED run — the same run id
as the thread's newest user message — resumes from the last checkpoint with input ``None``.

These tests are what would fail if someone reinstated the delete-and-restart, or let a retry
re-send its own message and pay for the whole turn twice.
"""

from __future__ import annotations

import inspect
from typing import Any

from langchain_core.messages import HumanMessage
from lumen_agent.checkpoint import invoke_turn_graph
from lumen_agent.harness import create_design_deepagent, run_deepagent_turn
from lumen_agent.harness_web import create_web_deepagent, run_deepagent_web_turn


class _Snapshot:
    def __init__(self, created_at: Any, values: dict | None = None) -> None:
        self.created_at = created_at
        self.values = {"messages": []} if values is None else values


class _FakeAgent:
    """Records the thread each invoke ran on, and what state the caller asked it to start from."""

    def __init__(self, snapshot: Any = None, *, state_raises: bool = False) -> None:
        self._snapshot = snapshot
        self._state_raises = state_raises
        self.invocations: list[tuple[Any, str]] = []
        self.state_lookups = 0

    def get_state(self, config: dict) -> Any:
        self.state_lookups += 1
        if self._state_raises:
            raise RuntimeError("checkpointer is unreachable")
        return self._snapshot

    def invoke(self, state: Any, config: dict | None = None) -> str:
        assert config is not None
        self.invocations.append((state, config["configurable"]["thread_id"]))
        return "invoked"


class _FakeSaver:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


def _config(thread_id: str) -> dict:
    return {"recursion_limit": 200, "configurable": {"thread_id": thread_id}}


def _snapshot_with_last_human(run_id: str | None):
    msg = HumanMessage(
        content="make a poster",
        additional_kwargs={} if run_id is None else {"lumen_run_id": run_id},
    )
    return _Snapshot("2026-01-01T00:00:00Z", values={"messages": [msg]})


def test_without_a_checkpointer_the_turn_invokes_exactly_as_before() -> None:
    # Every CLI / fixture / offline caller takes this path; it must not gain a state lookup.
    agent = _FakeAgent(snapshot=_Snapshot("2026-01-01"))
    result = invoke_turn_graph(agent, {"messages": []}, invoke_config=_config("run_a"))
    assert result == "invoked"
    assert agent.state_lookups == 0
    assert agent.invocations == [({"messages": []}, "run_a")]


def test_a_fresh_thread_is_invoked_once_and_nothing_is_cleared() -> None:
    agent = _FakeAgent(snapshot=_Snapshot(None))
    saver = _FakeSaver()
    invoke_turn_graph(
        agent,
        {"messages": []},
        invoke_config=_config("run_b"),
        checkpointer=saver,
        thread_id="run_b",
    )
    assert saver.deleted == []
    assert [thread for _, thread in agent.invocations] == ["run_b"]


def test_a_thread_with_earlier_turns_is_continued_with_the_new_message() -> None:
    # Design session continuity (2026-09-18): the thread is the document's session. A NEW run on
    # it appends its message; nothing is deleted.
    agent = _FakeAgent(snapshot=_snapshot_with_last_human("run_old"))
    saver = _FakeSaver()
    initial = {
        "messages": [
            HumanMessage(content="now make it red", additional_kwargs={"lumen_run_id": "run_new"})
        ]
    }
    invoke_turn_graph(
        agent,
        initial,
        invoke_config=_config("dsess_1"),
        checkpointer=saver,
        thread_id="dsess_1",
        run_id="run_new",
    )
    assert saver.deleted == []
    assert agent.invocations == [(initial, "dsess_1")]


def test_the_same_run_retried_resumes_without_re_sending_its_message() -> None:
    agent = _FakeAgent(snapshot=_snapshot_with_last_human("run_same"))
    initial = {
        "messages": [
            HumanMessage(content="make a poster", additional_kwargs={"lumen_run_id": "run_same"})
        ]
    }
    invoke_turn_graph(
        agent,
        initial,
        invoke_config=_config("dsess_2"),
        checkpointer=_FakeSaver(),
        thread_id="dsess_2",
        run_id="run_same",
    )
    assert agent.invocations == [(None, "dsess_2")]


def test_checkpoint_bookkeeping_never_fails_a_runnable_turn() -> None:
    # A saver that cannot report its own state is an observability problem, not a reason to
    # refuse work the agent could otherwise do: the turn runs, from its own initial state.
    unreadable = _FakeAgent(state_raises=True)
    initial = {"messages": [HumanMessage(content="make a poster")]}
    invoke_turn_graph(
        unreadable,
        initial,
        invoke_config=_config("run_d"),
        checkpointer=_FakeSaver(),
        thread_id="run_d",
        run_id="run_d",
    )
    assert unreadable.invocations == [(initial, "run_d")]


def test_both_harnesses_expose_the_durable_seam() -> None:
    # The fleet handler supplies these by name; a rename would otherwise fail only at runtime,
    # inside a worker thread, on a real turn.
    for runner in (run_deepagent_turn, run_deepagent_web_turn):
        parameters = inspect.signature(runner).parameters
        assert "checkpointer" in parameters, runner
        assert "thread_id" in parameters, runner
        assert parameters["checkpointer"].default is None
        assert parameters["thread_id"].default is None
    for factory in (create_design_deepagent, create_web_deepagent):
        assert "checkpointer" in inspect.signature(factory).parameters, factory
