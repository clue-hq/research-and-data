"""A site turn's working copy and its takeover (site-turn durability, Task 3), harness level.

Two attempts at one turn share ONE checkpointer (the conversation is durable) and use TWO folders
(the takeover runs on another disk). Attempt A dies with an exception the harness cannot swallow;
attempt B is handed A's last working copy and continues. A scripted model, no model spend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from lumen_agent.checkpoint import invoke_turn_graph
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.site import workspace as site_workspace
from lumen_agent.site.harness import SiteTurnResume, TurnLimitsConfig, run_site_turn
from lumen_agent.site.workspace import collect_working_copy, materialize_workspace, overlay_working_copy
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import FakeSections, ScriptedModel, call, garner_site, inputs_for

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
OLD_PROOF = "Lower medical spend for SCSD"


class WorkerDied(BaseException):
    """A worker killed mid-turn: no ``except Exception`` can swallow it."""


class Script(ScriptedModel):
    seen: list = Field(default_factory=list)
    die_at: int | None = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.die_at is not None and len(self.seen) == self.die_at:
            raise WorkerDied()
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class Copies:
    """The executor's sink, in memory: every full copy written (``rows``) and every re-stamp of the
    last one (``restamps``: a round that changed no file moves the copy's checkpoint and turn state
    on, keeping its files — the row's UPDATE)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.restamps: list[dict] = []

    def __call__(self, checkpoint_id: str, files: dict | None, turn_state: dict, files_sha256: str | None) -> None:
        if files is None:
            assert self.rows, "a re-stamp with no copy written"
            assert files_sha256 is None
            self.rows[-1] = {**self.rows[-1], "checkpoint_id": checkpoint_id, "turn_state": turn_state}
            self.restamps.append({"checkpoint_id": checkpoint_id, "turn_state": turn_state})
            return
        self.rows.append({"checkpoint_id": checkpoint_id, "files": files, "turn_state": turn_state,
                          "files_sha256": files_sha256})

    def resume(self) -> SiteTurnResume:
        last = self.rows[-1]
        return SiteTurnResume(last["checkpoint_id"], last["files"], last["turn_state"])


def _attempt(folder: Path, script: Script, saver, copies: Copies, *, resume=None, limits=TurnLimitsConfig(),
             inputs=None):
    return run_site_turn(
        "build", config=AgentRuntimeConfig.from_env(), inputs=inputs or inputs_for(), workspace=folder,
        site=garner_site(), run_id="run_takeover", checkpointer=saver, thread_id="run_takeover",
        model=script, resume=resume, working_copy_sink=copies, limits=limits,
    )


def _edit(old: str, new: str, n: int, file: str = "/page.json") -> dict:
    return call("edit_file", {"file_path": file, "old_string": old, "new_string": new}, n)


def _tool_results(messages: list) -> set[str]:
    return {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}


@needs_node
def test_a_takeover_continues_from_the_copy_and_redoes_nothing_finished(tmp_path: Path) -> None:
    saver, copies = InMemorySaver(), Copies()
    a = Script(messages=iter([
        AIMessage(content="", tool_calls=[_edit(OLD_PROOF, "Lower spend for Syracuse", 1)]),
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/plan.md", "content": "# Plan\n"}, 2)]),
        AIMessage(content="never answered"),
    ]), die_at=2)
    with pytest.raises(WorkerDied):
        _attempt(tmp_path / "disk-a" / "workspace", a, saver, copies)
    assert len(a.seen) == 2
    # One copy per round that changed files: after round 1 (the page) and after round 2 (plan.md).
    # The starting copy (round 0, before the first model call), then the round that edited.
    assert len(copies.rows) == 3 and copies.rows[0]["turn_state"]["rounds"] == 0
    assert copies.rows[-1]["files"]["plan.md"] == "# Plan\n"
    assert "Lower spend for Syracuse" in copies.rows[-1]["files"]["page.json"]
    assert copies.rows[-1]["turn_state"]["rounds"] == 2

    b = Script(messages=iter([AIMessage(content="Done: the proof heading names Syracuse.")]))
    result = _attempt(tmp_path / "disk-b" / "workspace", b, saver, copies, resume=copies.resume())
    # B's only model call already holds A's two rounds: nothing is asked again.
    assert len(b.seen) == 1
    assert {"call_1", "call_2"} <= _tool_results(b.seen[0])
    assert sum(isinstance(m, HumanMessage) for m in b.seen[0]) == 1
    assert result.status == "applied", result
    assert "Lower spend for Syracuse" in json.dumps(result.site["pages"]["/"])
    assert (tmp_path / "disk-b" / "workspace" / "plan.md").read_text() == "# Plan\n"
    # The final copy is stamped after the answer: a takeover now would make no model call at all.
    assert copies.rows[-1]["turn_state"]["rounds"] == 3


@needs_node
def test_a_takeover_after_the_last_step_makes_no_model_call(tmp_path: Path) -> None:
    saver, copies = InMemorySaver(), Copies()
    a = Script(messages=iter([
        AIMessage(content="", tool_calls=[_edit(OLD_PROOF, "Lower spend for Syracuse", 1)]),
        AIMessage(content="Done."),
    ]))
    first = _attempt(tmp_path / "a" / "workspace", a, saver, copies)
    assert first.status == "applied" and len(a.seen) == 2
    # ...and the worker dies before the save. B starts on another disk from the final copy.
    b = Script(messages=iter([]))
    result = _attempt(tmp_path / "b" / "workspace", b, saver, copies, resume=copies.resume())
    assert b.seen == []
    assert result.status == "applied" and result.site == first.site and result.site != garner_site()
    assert result.summary == "Done."


@needs_node
def test_read_only_rounds_move_the_copy_on_so_a_takeover_redoes_only_the_step_in_flight(tmp_path: Path) -> None:
    """Two rounds change files, three only read. A dies at its sixth model call. Each read-only
    round re-stamps the copy (its checkpoint and turn state; the files are not sent again), so B
    resumes at round 5's checkpoint: its first model call already holds all five rounds, and the
    round counter it restores is 5."""
    saver, copies = InMemorySaver(), Copies()
    a = Script(messages=iter([
        AIMessage(content="", tool_calls=[_edit(OLD_PROOF, "Lower spend for Syracuse", 1)]),
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/plan.md", "content": "# Plan\n"}, 2)]),
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/page.json"}, 3)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 4)]),
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/plan.md"}, 5)]),
        AIMessage(content="never answered"),
    ]), die_at=5)
    with pytest.raises(WorkerDied):
        _attempt(tmp_path / "disk-a" / "workspace", a, saver, copies)
    assert len(a.seen) == 5
    # Two full copies (the two file-changing rounds), then one re-stamp per read-only round.
    # The starting copy, the two file-changing rounds, then three re-stamps.
    assert len(copies.rows) == 3 and len(copies.restamps) == 3
    assert copies.rows[-1]["turn_state"]["rounds"] == 5
    assert copies.rows[-1]["files"]["plan.md"] == "# Plan\n"

    b = Script(messages=iter([AIMessage(content="Done: the proof heading names Syracuse.")]))
    result = _attempt(tmp_path / "disk-b" / "workspace", b, saver, copies, resume=copies.resume())
    # Exactly one model call (the step that was in flight), already holding all five rounds.
    assert len(b.seen) == 1
    assert {f"call_{n}" for n in range(1, 6)} <= _tool_results(b.seen[0])
    assert result.status == "applied", result
    assert "Lower spend for Syracuse" in json.dumps(result.site["pages"]["/"])
    assert copies.rows[-1]["turn_state"]["rounds"] == 6


def test_rounds_carry_over_so_a_takeover_cannot_buy_fresh_ones(tmp_path: Path) -> None:
    saver, copies = InMemorySaver(), Copies()
    limits = TurnLimitsConfig(max_rounds=2)
    a = Script(messages=iter([
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/notes.md", "content": "n"}, 1)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 2)]),
    ]), die_at=1)
    with pytest.raises(WorkerDied):
        _attempt(tmp_path / "a" / "workspace", a, saver, copies, limits=limits)
    assert copies.rows[-1]["turn_state"]["rounds"] == 1
    seconds_a = copies.rows[-1]["turn_state"]["seconds_used"]

    b = Script(messages=iter([AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, n)]) for n in range(5)]))
    result = _attempt(tmp_path / "b" / "workspace", b, saver, copies, resume=copies.resume(), limits=limits)
    # Round 2 is the takeover's only round: the limit counts A's round too.
    assert len(b.seen) == 1 and result.stop_reason == "round_limit"
    assert copies.rows[-1]["turn_state"]["rounds"] == 2
    assert copies.rows[-1]["turn_state"]["seconds_used"] >= seconds_a


def test_a_section_written_and_an_image_found_before_the_death_survive_the_takeover(tmp_path: Path) -> None:
    from site_fixtures import FakeAssets, png

    saver, copies = InMemorySaver(), Copies()
    assets = FakeAssets()

    class Generated:
        image_bytes, mime_type, model, width, height = png("teal"), "image/png", "fake", 32, 18

    inputs = inputs_for(sections=FakeSections(), assets=assets,
                        image_generate=lambda **kwargs: Generated())
    a = Script(messages=iter([
        AIMessage(content="", tool_calls=[
            call("write_section", {"name": "QuoteBand", "code": "export function render() {}"}, 1),
            call("generate_image", {"prompt": "a classroom", "aspect_ratio": "16:9"}, 2),
        ]),
        AIMessage(content="never answered"),
    ]), die_at=1)
    with pytest.raises(WorkerDied):
        _attempt(tmp_path / "a" / "workspace", a, saver, copies, inputs=inputs)
    state = copies.rows[-1]["turn_state"]
    assert set(state["sections"]) == {"QuoteBand"} and len(state["assets"]) == 1

    b = Script(messages=iter([AIMessage(content="Done.")]))
    seen_by_b: dict = {}
    original = run_site_turn.__globals__["build_site_agent"]

    def spy(tools, **kwargs):
        built = original(tools, **kwargs)
        seen_by_b["tools"] = tools
        return built

    run_site_turn.__globals__["build_site_agent"] = spy
    try:
        _attempt(tmp_path / "b" / "workspace", b, saver, copies, resume=copies.resume(), inputs=inputs)
    finally:
        run_site_turn.__globals__["build_site_agent"] = original
    tools = seen_by_b["tools"]
    assert tools.sections["QuoteBand"].digest == "e" * 64
    generated = next(iter(state["assets"].values()))
    assert tools.brand["assets"][next(iter(state["assets"]))] == generated
    assert "## QuoteBand" in (tmp_path / "b" / "workspace" / "catalog" / "seller-components.md").read_text()


def test_the_copy_holds_the_turns_work_and_never_its_inputs(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs_for(), site=garner_site())
    (workspace / "plan.md").write_text("plan")
    (workspace / "fetched" / "page.md").write_text("evidence")
    (workspace / "work" / "conversation_history").mkdir(parents=True)
    (workspace / "work" / "conversation_history" / "h.md").write_text("history")
    (workspace / "binary.bin").write_bytes(b"\xff\xfe\x00")
    os.symlink(workspace / "plan.md", workspace / "link.md")
    offloads = workspace / "large_tool_results"
    offloads.mkdir()
    for n in range(3):
        (offloads / f"r{n}").write_text("x" * 100)
        os.utime(offloads / f"r{n}", (1000 + n, 1000 + n))

    files, notes = collect_working_copy(workspace)
    assert {"page.json", "shell.json", "pages/analysis.json", "plan.md", "fetched/page.md",
            "work/conversation_history/h.md", "large_tool_results/r0"} <= set(files)
    assert not [key for key in files if key.split("/")[0] in ("brief.md", "catalog", "brand", "skills", "research")]
    assert notes == {"skipped": ["binary.bin", "link.md"], "dropped": []}

    # Over budget, the oldest offloads go first, and the copy says which.
    size = sum(len(text.encode()) for text in files.values())
    monkeypatch.setattr(site_workspace, "WORKING_COPY_MAX_BYTES", size - 150)
    files, notes = collect_working_copy(workspace)
    assert notes["dropped"] == ["large_tool_results/r0", "large_tool_results/r1"]
    assert "large_tool_results/r2" in files

    # Laid over a fresh folder, the site files are exactly the copy's: a removed page stays removed.
    files.pop("pages/analysis.json")
    fresh = tmp_path / "fresh"
    materialize_workspace(fresh, inputs_for(), site=garner_site())
    overlay_working_copy(fresh, files)
    assert not (fresh / "pages" / "analysis.json").exists()
    assert (fresh / "plan.md").read_text() == "plan" and (fresh / "fetched" / "page.md").read_text() == "evidence"


class _Agent:
    def __init__(self, last_run: str | None) -> None:
        self.last_run = last_run
        self.calls: list = []

    def get_state(self, config):
        class Snapshot:
            created_at = "2026-10-16T00:00:00Z"
            values = {"messages": [HumanMessage(content="x", additional_kwargs={"lumen_run_id": self.last_run})]}

        return Snapshot()

    def invoke(self, state, config=None, **kwargs):
        self.calls.append((state, config["configurable"], kwargs))
        return {}


def test_a_site_turn_resumes_at_its_copys_checkpoint_and_never_at_the_latest() -> None:
    config = {"recursion_limit": 10, "configurable": {"thread_id": "run_x"}}
    initial = {"messages": [HumanMessage(content="go")]}

    at = _Agent("run_x")
    invoke_turn_graph(at, initial, invoke_config=config, checkpointer=object(), thread_id="run_x", run_id="run_x",
                      resume_checkpoint_id="cp-7", resume_latest=False, durability="sync")
    assert at.calls == [(None, {"thread_id": "run_x", "checkpoint_id": "cp-7"}, {"durability": "sync"})]

    latest = _Agent("run_x")
    with pytest.raises(RuntimeError, match="would lose its file work"):
        invoke_turn_graph(latest, initial, invoke_config=config, checkpointer=object(), thread_id="run_x",
                          run_id="run_x", resume_latest=False, durability="sync")
    assert latest.calls == []
