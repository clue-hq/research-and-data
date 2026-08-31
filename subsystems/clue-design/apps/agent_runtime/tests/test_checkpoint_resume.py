"""The D5 Round B durable-graph seam: what resuming a design turn's thread actually does.

`checkpoint.invoke_turn_graph` is small, but it encodes a decision worth pinning: the design
harness ships **resume-as-restart**, not true mid-turn resume, because the tool substrate
(`LumenDesignTools`) mints a fresh run id and trace dir on every construction and the turn's real
state — scene, operations ledger, `final.json` — lives there rather than in the LangGraph
checkpoint. Continuing a checkpointed message history against an empty substrate would fabricate
a continuation, which is exactly what this harness refuses to do everywhere else.

So: a thread that already carries state is cleared and re-invoked from the top. These tests are
what would fail if someone later "optimized" that into a silent resume.
"""

from __future__ import annotations

import inspect
from typing import Any

from lumen_agent.checkpoint import invoke_turn_graph
from lumen_agent.harness import create_design_deepagent, run_deepagent_turn
from lumen_agent.harness_web import create_web_deepagent, run_deepagent_web_turn


class _Snapshot:
    def __init__(self, created_at: Any) -> None:
        self.created_at = created_at


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
    def __init__(self, *, delete_raises: bool = False) -> None:
        self.deleted: list[str] = []
        self._delete_raises = delete_raises

    def delete_thread(self, thread_id: str) -> None:
        if self._delete_raises:
            raise RuntimeError("delete failed")
        self.deleted.append(thread_id)


def _config(thread_id: str) -> dict:
    return {"recursion_limit": 200, "configurable": {"thread_id": thread_id}}


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


def test_a_thread_that_already_ran_is_cleared_and_restarted_from_the_top() -> None:
    # THE decision under test. A prior attempt's graph state is deleted and the SAME frozen turn
    # is re-invoked with its full initial state — never continued with input None.
    agent = _FakeAgent(snapshot=_Snapshot("2026-01-01T00:00:00Z"))
    saver = _FakeSaver()
    initial = {"messages": [{"role": "user", "content": "make a poster"}]}
    invoke_turn_graph(
        agent, initial, invoke_config=_config("run_c"), checkpointer=saver, thread_id="run_c"
    )
    assert saver.deleted == ["run_c"], "the stale thread must be cleared before the restart"
    assert agent.invocations == [(initial, "run_c")]


def test_checkpoint_bookkeeping_never_fails_a_runnable_turn() -> None:
    # A saver that cannot report or clear its own state is an observability problem, not a reason
    # to refuse work the agent could otherwise do.
    unreadable = _FakeAgent(state_raises=True)
    invoke_turn_graph(
        unreadable,
        {"messages": []},
        invoke_config=_config("run_d"),
        checkpointer=_FakeSaver(),
        thread_id="run_d",
    )
    assert [thread for _, thread in unreadable.invocations] == ["run_d"]

    undeletable = _FakeAgent(snapshot=_Snapshot("2026-01-01"))
    invoke_turn_graph(
        undeletable,
        {"messages": []},
        invoke_config=_config("run_e"),
        checkpointer=_FakeSaver(delete_raises=True),
        thread_id="run_e",
    )
    assert [thread for _, thread in undeletable.invocations] == ["run_e"]


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
