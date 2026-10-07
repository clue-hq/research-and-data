"""T3: the harness, driven by a scripted fake model (no model spend).

Run from the repo root:
    .venv/bin/python -m pytest trials/puck-spike/agent/tests -q
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from trials_puck_agent.harness import build_agent, clear_old_renders
from trials_puck_agent.tools import PageTools

SPIKE = Path(__file__).resolve().parents[2]
AGENT = SPIKE / "agent"
SITE = json.loads((SPIKE / "data" / "sites" / "garner-syracuse.json").read_text())


class ScriptedModel(GenericFakeChatModel):
    """Answers with the next scripted message; tools are accepted and ignored."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name: str, args: dict, n: int) -> dict:
    return {"name": name, "args": args, "id": f"call_{n}", "type": "tool_call"}


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    shutil.copytree(AGENT / "skills", ws / "skills")
    (ws / "research").mkdir()
    (ws / "research" / "evidence.md").write_text(
        "Healthcare increase of $4.2 million in the 2025-26 budget. 7.4% lower medical spend and "
        "$345 lower PMPY in the Aon study, published March 31, 2026 (2020 to 2024). 30-minute review."
    )
    (ws / "brief.md").write_text("For the page\n- A 1:1 page for Syracuse City School District.\n")
    (ws / ".run.json").write_text(json.dumps({"brand": "garner", "site": "agent-test", "route": "/"}))
    return ws


def run(ws: Path, script: list[AIMessage], *, safety_stop: int = 40):
    tools = PageTools(workspace=ws, spike_root=SPIKE, base_url="http://localhost:3047", retry_delay_s=0)
    agent, recorder = build_agent(tools, model=ScriptedModel(messages=iter(script)), safety_stop=safety_stop)
    recorder.start_turn("build")
    state = agent.invoke({"messages": [{"role": "user", "content": "build"}]}, {"configurable": {"thread_id": "t"}})
    return state["messages"], recorder


def tool_results(messages: list) -> dict[str, str]:
    return {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}


def test_a_scripted_build_reads_a_skill_writes_the_page_and_validates(workspace: Path) -> None:
    page = json.dumps(SITE["pages"]["/"])
    shell = json.dumps(SITE["shell"])
    messages, recorder = run(workspace, [
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/skills/building-with-puck/SKILL.md", "limit": 1000}, 1)]),
        AIMessage(content="", tool_calls=[
            call("write_file", {"file_path": "/page.json", "content": page}, 2),
            call("write_file", {"file_path": "/shell.json", "content": shell}, 3),
            call("validate_page", {}, 4),
        ]),
        AIMessage(content="Built the page."),
    ])
    results = tool_results(messages)
    assert "Reuse first" in results["call_1"]
    assert results["call_4"].startswith("VALID"), results["call_4"]
    assert recorder.turn.status == "completed"
    assert recorder.prompt_size["tools"] == sorted(recorder.prompt_size["tools"], key=recorder.prompt_size["tools"].index)
    assert {"validate_page", "render_page", "read_file", "write_file", "edit_file"} <= set(recorder.prompt_size["tools"])
    assert "task" not in recorder.prompt_size["tools"] and "write_todos" not in recorder.prompt_size["tools"]


def test_the_agent_cannot_write_its_inputs(workspace: Path) -> None:
    messages, _ = run(workspace, [
        AIMessage(content="", tool_calls=[call("edit_file", {"file_path": "/brief.md", "old_string": "1:1", "new_string": "x"}, 1)]),
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/skills/new/SKILL.md", "content": "x"}, 2)]),
        AIMessage(content="Done."), AIMessage(content="Done."), AIMessage(content="Done."),
    ])
    results = tool_results(messages)
    assert "1:1" in (workspace / "brief.md").read_text()
    assert not (workspace / "skills" / "new").exists()
    assert "denied" in results["call_1"].lower() or "permission" in results["call_1"].lower()


def test_tool_calls_run_in_the_order_the_model_wrote_them(workspace: Path) -> None:
    page = SITE["pages"]["/"]
    broken = json.loads(json.dumps(page))
    next(i for i in broken["content"] if i["props"]["id"] == "proof")["props"]["surface"] = "green"
    messages, _ = run(workspace, [
        AIMessage(content="", tool_calls=[
            call("write_file", {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])}, 1),
            call("write_file", {"file_path": "/page.json", "content": json.dumps(broken)}, 2),
            call("validate_page", {}, 3),
        ]),
        AIMessage(content="Done."), AIMessage(content="Done."), AIMessage(content="Done."),
    ])
    # validate saw the broken page (not "page.json does not exist yet"), so both writes landed first
    result = tool_results(messages)["call_3"]
    assert "content.3(proof).surface" in result and "does not exist" not in result


def test_a_turn_cannot_finish_on_an_invalid_page(workspace: Path) -> None:
    messages, recorder = run(workspace, [
        AIMessage(content="All done."),
        AIMessage(content="All done."),
        AIMessage(content="All done, but the page is not finished."),
    ])
    reminders = [m for m in messages if isinstance(m, HumanMessage) and "still invalid" in m.content]
    assert len(reminders) == 2
    assert "page.json: does not exist yet" in reminders[0].content
    assert recorder.turn.status == "completed with errors"


def test_the_safety_stop_ends_a_runaway_turn(workspace: Path) -> None:
    script = [AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, n)]) for n in range(10)]
    messages, recorder = run(workspace, script, safety_stop=3)
    assert len(recorder.turn.calls) == 3
    assert recorder.turn.status == "stopped by the safety stop"
    assert "safety stop" in messages[-1].content


def test_only_the_newest_render_keeps_its_screenshots() -> None:
    def render(n: int) -> ToolMessage:
        return ToolMessage(
            name="render_page", tool_call_id=f"r{n}",
            content=[{"type": "text", "text": f"1440 wide: render {n}"},
                     {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": "AAAA"}],
        )

    messages = [HumanMessage(content="build"), render(1), AIMessage(content="fixing"), render(2)]
    cleared = clear_old_renders(messages)
    assert isinstance(cleared[1].content, str) and "render 1" in cleared[1].content
    assert cleared[3] is messages[3]
    assert clear_old_renders(cleared)[1].content == cleared[1].content  # stable: the cache holds
    assert messages[1].content[1]["type"] == "image"  # the saved history keeps everything


def test_a_validate_written_before_the_writes_runs_before_them(workspace: Path) -> None:
    messages, _ = run(workspace, [
        AIMessage(content="", tool_calls=[
            call("validate_page", {}, 1),
            call("write_file", {"file_path": "/page.json", "content": json.dumps(SITE["pages"]["/"])}, 2),
            call("write_file", {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])}, 3),
        ]),
        AIMessage(content="Done."),
    ])
    assert "does not exist yet" in tool_results(messages)["call_1"]
