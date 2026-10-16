"""A site turn asked to drain stops at the next step boundary (site-turn durability, Task 4).

When a worker's drain bound passes, the design job handler drains its :class:`DrainScope`. A site
turn running in that scope stops at its next step boundary, stamps its working copy at that step's
checkpoint, and raises :class:`TurnDrained` (never a crashed result). The worker that takes the run
over continues from the copy and is asked for nothing the drained attempt had finished. Harness
level: one shared checkpointer (the conversation is durable), two folders, a scripted model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.drain import DrainScope, TurnDrained, drain_scope
from lumen_agent.site.harness import SiteTurnResume, run_site_turn
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import ScriptedModel, call, garner_site, inputs_for

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
OLD_PROOF = "Lower medical spend for SCSD"
NEW_PROOF = "Lower spend for Syracuse"
THREAD = "run_drain"


class Script(ScriptedModel):
    """``hooks`` maps a call number (0-based) to a callable run before that call answers."""

    seen: list = Field(default_factory=list)
    hooks: dict = Field(default_factory=dict)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        hook = self.hooks.get(len(self.seen))
        self.seen.append(list(messages))
        if hook is not None:
            hook()
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class Copies:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def __call__(self, checkpoint_id: str, files: dict | None, turn_state: dict, files_sha256: str | None) -> None:
        if files is None:  # a re-stamp: the copy's files stay, its checkpoint and state move on
            self.rows[-1] = {**self.rows[-1], "checkpoint_id": checkpoint_id, "turn_state": turn_state}
            return
        self.rows.append({"checkpoint_id": checkpoint_id, "files": files, "turn_state": turn_state})

    def resume(self) -> SiteTurnResume:
        last = self.rows[-1]
        return SiteTurnResume(last["checkpoint_id"], last["files"], last["turn_state"])


def _attempt(folder: Path, script: Script, saver, copies: Copies | None, *, resume=None):
    return run_site_turn(
        "build", config=AgentRuntimeConfig.from_env(), inputs=inputs_for(), workspace=folder, site=garner_site(),
        run_id=THREAD, checkpointer=saver, thread_id=THREAD, model=script, resume=resume, working_copy_sink=copies,
    )


def _latest_checkpoint_id(saver) -> str:
    return saver.get_tuple({"configurable": {"thread_id": THREAD}}).config["configurable"]["checkpoint_id"]


def _tool_results(messages: list) -> set[str]:
    return {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}


@needs_node
def test_a_drained_turn_stops_at_the_next_step_and_its_takeover_redoes_nothing(tmp_path: Path) -> None:
    saver, copies, scope = InMemorySaver(), Copies(), DrainScope()
    plan = call("write_file", {"file_path": "/plan.md", "content": "# Plan\n"}, 2)
    a = Script(
        messages=iter([
            AIMessage(content="", tool_calls=[call("edit_file", {"file_path": "/page.json", "old_string": OLD_PROOF,
                                                                 "new_string": NEW_PROOF}, 1)]),
            # The bound passes while this answer is produced: the answer stands, its tools wait.
            AIMessage(content="", tool_calls=[plan]),
            AIMessage(content="never answered"),
        ]),
        hooks={1: lambda: scope.request_drain("the worker is shutting down")},
    )
    with drain_scope(scope), pytest.raises(TurnDrained) as drained:
        _attempt(tmp_path / "disk-a" / "workspace", a, saver, copies)
    assert drained.value.reason == "the worker is shutting down"
    assert len(a.seen) == 2
    # The copy is stamped at the step the turn stopped on: round 1's edit, not yet round 2's file.
    final = copies.rows[-1]
    assert final["checkpoint_id"] == _latest_checkpoint_id(saver)
    assert NEW_PROOF in final["files"]["page.json"] and "plan.md" not in final["files"]

    b = Script(messages=iter([AIMessage(content="Done: the proof heading names Syracuse.")]))
    result = _attempt(tmp_path / "disk-b" / "workspace", b, saver, copies, resume=copies.resume())
    # Round 2's tools ran on the takeover without asking the model again; B answered once.
    assert len(b.seen) == 1
    assert {"call_1", "call_2"} <= _tool_results(b.seen[0])
    assert sum(isinstance(m, HumanMessage) for m in b.seen[0]) == 1
    assert result.status == "applied", result
    assert NEW_PROOF in json.dumps(result.site["pages"]["/"])
    assert (tmp_path / "disk-b" / "workspace" / "plan.md").read_text() == "# Plan\n"


@needs_node
def test_a_turn_that_starts_after_the_drain_stops_before_its_first_model_call(tmp_path: Path) -> None:
    saver, copies, scope = InMemorySaver(), Copies(), DrainScope()
    scope.request_drain("the worker is shutting down")
    a = Script(messages=iter([AIMessage(content="never answered")]))
    with drain_scope(scope), pytest.raises(TurnDrained):
        _attempt(tmp_path / "a" / "workspace", a, saver, copies)
    assert a.seen == []


@needs_node
def test_a_turn_outside_any_scope_or_without_a_working_copy_is_never_drained(tmp_path: Path) -> None:
    """With no scope selected nothing can reach the turn; without a working copy a drained turn could
    not be continued, so it is not registered and runs to its end."""
    scope = DrainScope()
    scope.request_drain("the worker is shutting down")
    outside = Script(messages=iter([AIMessage(content="Done.")]))
    assert _attempt(tmp_path / "a" / "workspace", outside, InMemorySaver(), Copies()).status == "applied"
    no_copy = Script(messages=iter([AIMessage(content="Done.")]))
    with drain_scope(scope):
        assert _attempt(tmp_path / "b" / "workspace", no_copy, InMemorySaver(), None).status == "applied"
