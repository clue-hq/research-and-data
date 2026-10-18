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

from trials_puck_agent.harness import build_agent, clear_superseded_results
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
    (ws / ".run.json").write_text(
        json.dumps({"brand": "garner", "site": "agent-test", "route": "/"})
    )
    return ws


def run(ws: Path, script: list[AIMessage], *, safety_stop: int = 40):
    tools = PageTools(
        workspace=ws, spike_root=SPIKE, base_url="http://localhost:3047", retry_delay_s=0
    )
    agent, recorder = build_agent(
        tools, model=ScriptedModel(messages=iter(script)), safety_stop=safety_stop
    )
    recorder.start_turn("build")
    state = agent.invoke(
        {"messages": [{"role": "user", "content": "build"}]}, {"configurable": {"thread_id": "t"}}
    )
    return state["messages"], recorder


def tool_results(messages: list) -> dict[str, str]:
    return {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}


def test_a_scripted_build_reads_a_skill_writes_the_page_and_validates(workspace: Path) -> None:
    page = json.dumps(SITE["pages"]["/"])
    shell = json.dumps(SITE["shell"])
    messages, recorder = run(
        workspace,
        [
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "read_file",
                        {"file_path": "/skills/building-with-puck/SKILL.md", "limit": 1000},
                        1,
                    )
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    call("write_file", {"file_path": "/page.json", "content": page}, 2),
                    call("write_file", {"file_path": "/shell.json", "content": shell}, 3),
                    call(
                        "write_file",
                        {
                            "file_path": "/pages/analysis.json",
                            "content": json.dumps(SITE["pages"]["/analysis"]),
                        },
                        5,
                    ),
                    call("validate_page", {}, 4),
                ],
            ),
            AIMessage(content="Built the page."),
        ],
    )
    results = tool_results(messages)
    assert "Reuse first" in results["call_1"]
    assert results["call_4"].startswith("VALID"), results["call_4"]
    assert recorder.turn.status == "completed"
    assert recorder.prompt_size["tools"] == sorted(
        recorder.prompt_size["tools"], key=recorder.prompt_size["tools"].index
    )
    assert {"validate_page", "render_page", "read_file", "write_file", "edit_file"} <= set(
        recorder.prompt_size["tools"]
    )
    assert (
        "task" not in recorder.prompt_size["tools"]
        and "write_todos" not in recorder.prompt_size["tools"]
    )


def test_the_agent_cannot_write_its_inputs(workspace: Path) -> None:
    messages, _ = run(
        workspace,
        [
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "edit_file",
                        {"file_path": "/brief.md", "old_string": "1:1", "new_string": "x"},
                        1,
                    )
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    call("write_file", {"file_path": "/skills/new/SKILL.md", "content": "x"}, 2)
                ],
            ),
            AIMessage(content="Done."),
            AIMessage(content="Done."),
            AIMessage(content="Done."),
        ],
    )
    results = tool_results(messages)
    assert "1:1" in (workspace / "brief.md").read_text()
    assert not (workspace / "skills" / "new").exists()
    assert "denied" in results["call_1"].lower() or "permission" in results["call_1"].lower()


def test_tool_calls_run_in_the_order_the_model_wrote_them(workspace: Path) -> None:
    page = SITE["pages"]["/"]
    broken = json.loads(json.dumps(page))
    next(i for i in broken["content"] if i["props"]["id"] == "proof")["props"]["surface"] = "green"
    messages, _ = run(
        workspace,
        [
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "write_file",
                        {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])},
                        1,
                    ),
                    call(
                        "write_file", {"file_path": "/page.json", "content": json.dumps(broken)}, 2
                    ),
                    call("validate_page", {}, 3),
                ],
            ),
            AIMessage(content="Done."),
            AIMessage(content="Done."),
            AIMessage(content="Done."),
        ],
    )
    # validate saw the broken page (not "page.json does not exist yet"), so both writes landed first
    result = tool_results(messages)["call_3"]
    assert "content.3(proof).surface" in result and "does not exist" not in result


def test_a_turn_cannot_finish_on_an_invalid_page(workspace: Path) -> None:
    (workspace / "page.json").write_text(
        json.dumps(
            {
                "root": {"props": {"title": "x"}},
                "content": [{"type": "NoSuchSection", "props": {"id": "a"}}],
            }
        )
    )
    messages, recorder = run(
        workspace,
        [
            AIMessage(content="All done."),
            AIMessage(content="All done."),
            AIMessage(content="All done, but the page is not finished."),
        ],
    )
    reminders = [
        m for m in messages if isinstance(m, HumanMessage) and "still invalid" in m.content
    ]
    assert len(reminders) == 2
    assert "shell.json: does not exist yet" in reminders[0].content
    assert recorder.turn.status == "completed with errors"


def test_a_turn_with_no_page_yet_finishes_without_reminders(workspace: Path) -> None:
    """A turn that only builds components (no page asked for yet) is not pushed to make one."""
    messages, recorder = run(workspace, [AIMessage(content="Rebuilt the hero as a component.")])
    assert not [m for m in messages if isinstance(m, HumanMessage) and "still invalid" in m.content]
    assert recorder.turn.status == "completed (no page yet)"


def test_the_safety_stop_ends_a_runaway_turn(workspace: Path) -> None:
    script = [AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, n)]) for n in range(10)]
    messages, recorder = run(workspace, script, safety_stop=3)
    assert len(recorder.turn.calls) == 3
    assert recorder.turn.status == "stopped by the safety stop"
    assert "safety stop" in messages[-1].content


def _ai(calls: list[dict]) -> AIMessage:
    return AIMessage(content="", tool_calls=calls)


def _result(name: str, n: str, content) -> ToolMessage:
    return ToolMessage(name=name, tool_call_id=n, content=content)


def _render(n: str) -> ToolMessage:
    return _result(
        "render_page",
        n,
        [
            {"type": "text", "text": f"1440 wide: render {n}"},
            {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": "AAAA"},
        ],
    )


def test_only_the_newest_render_keeps_its_screenshots() -> None:
    messages = [
        HumanMessage(content="build"),
        _ai([call("render_page", {}, 1)]),
        _render("call_1"),
        _ai([call("render_page", {}, 2)]),
        _render("call_2"),
    ]
    cleared = clear_superseded_results(messages)
    assert isinstance(cleared[2].content, str) and "render call_1" in cleared[2].content
    assert cleared[4] is messages[4]
    assert (
        clear_superseded_results(cleared)[2].content == cleared[2].content
    )  # stable: the cache holds
    assert messages[2].content[1]["type"] == "image"  # the saved history keeps everything


def test_only_the_newest_comparison_keeps_its_pictures() -> None:
    picture = {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": "AAAA"}
    messages = [
        HumanMessage(content="rebuild"),
        _ai([call("view_clone", {"fragment_id": "f"}, 1)]),
        _result("view_clone", "call_1", [{"type": "text", "text": "card"}, picture]),
        _ai([call("compare_section", {"name": "Hero"}, 2)]),
        _result(
            "compare_section",
            "call_2",
            [{"type": "text", "text": "1440 wide: 31% differs"}, picture],
        ),
        _ai([call("compare_section", {"name": "Hero"}, 3)]),
        _result(
            "compare_section",
            "call_3",
            [{"type": "text", "text": "1440 wide: 12% differs"}, picture],
        ),
    ]
    cleared = clear_superseded_results(messages)
    assert isinstance(cleared[2].content, str) and "card" in cleared[2].content
    assert isinstance(cleared[4].content, str) and "31% differs" in cleared[4].content
    assert cleared[6] is messages[6]


def test_planning_reads_clear_once_the_plan_is_written_and_building_starts() -> None:
    reads = [
        _ai(
            [
                call("read_file", {"file_path": "/research/overview.md"}, 1),
                call("read_file", {"file_path": "/skills/page-review/SKILL.md"}, 2),
                call("fetch_page", {"url": "https://x.example/a"}, 3),
            ]
        ),
        _result("read_file", "call_1", "research text " * 50),
        _result("read_file", "call_2", "skill text"),
        _result("fetch_page", "call_3", "Saved to fetched/x-a.md (status 200).\n\npage text"),
    ]
    plan = [
        _ai([call("write_file", {"file_path": "/plan.md", "content": "p"}, 4)]),
        _result("write_file", "call_4", "ok"),
    ]
    build = [
        _ai([call("write_file", {"file_path": "/page.json", "content": "{}"}, 5)]),
        _result("write_file", "call_5", "ok"),
    ]
    before = clear_superseded_results([HumanMessage(content="build"), *reads, *plan])
    assert before[2].content.startswith("research text")  # the plan alone does not end planning
    after = clear_superseded_results([HumanMessage(content="build"), *reads, *plan, *build])
    assert after[2].content.startswith("[cleared to save context: read_file(/research/overview.md)")
    assert after[3].content == "skill text"  # skills stay
    assert "Saved to fetched/x-a.md." in after[4].content  # the stub says where the page was saved


def test_an_old_read_of_a_site_file_clears_only_after_a_newer_render() -> None:
    read = [
        _ai([call("read_file", {"file_path": "/page.json"}, 1)]),
        _result("read_file", "call_1", "old page"),
    ]
    edit = [
        _ai(
            [
                call(
                    "edit_file",
                    {"file_path": "/page.json", "old_string": "a", "new_string": "b"},
                    2,
                )
            ]
        ),
        _result("edit_file", "call_2", "ok"),
    ]
    render = [_ai([call("render_page", {}, 3)]), _render("call_3")]
    no_render = clear_superseded_results([HumanMessage(content="edit"), *read, *edit])
    assert no_render[2].content == "old page"  # unchanged until a render: the prefix stays stable
    with_render = clear_superseded_results([HumanMessage(content="edit"), *read, *edit, *render])
    assert "an older read of /page.json" in with_render[2].content


def test_a_validate_written_before_the_writes_runs_before_them(workspace: Path) -> None:
    messages, _ = run(
        workspace,
        [
            AIMessage(
                content="",
                tool_calls=[
                    call("validate_page", {}, 1),
                    call(
                        "write_file",
                        {"file_path": "/page.json", "content": json.dumps(SITE["pages"]["/"])},
                        2,
                    ),
                    call(
                        "write_file",
                        {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])},
                        3,
                    ),
                    call(
                        "write_file",
                        {
                            "file_path": "/pages/analysis.json",
                            "content": json.dumps(SITE["pages"]["/analysis"]),
                        },
                        4,
                    ),
                ],
            ),
            AIMessage(content="Done."),
        ],
    )
    assert "does not exist yet" in tool_results(messages)["call_1"]


def test_a_read_without_a_limit_gets_the_whole_file(workspace: Path) -> None:
    (workspace / "research" / "long.md").write_text("\n".join(f"line {n}" for n in range(1, 251)))
    messages, _ = run(
        workspace,
        [
            AIMessage(
                content="", tool_calls=[call("read_file", {"file_path": "/research/long.md"}, 1)]
            ),
            AIMessage(content="Done."),
            AIMessage(content="Done."),
            AIMessage(content="Done."),
        ],
    )
    assert "line 250" in tool_results(messages)["call_1"]


def test_view_asset_shows_a_brand_image_with_its_description(workspace: Path) -> None:
    assets = json.loads((SPIKE / "data" / "brands" / "garner" / "assets.json").read_text())
    file = next(
        a["file"] for a in assets.values() if a["file"].endswith(".png") and a.get("description")
    )
    tools = PageTools(workspace=workspace, spike_root=SPIKE, base_url="http://localhost:3047")
    blocks = tools.view_asset([file, "/brands/garner/assets/nope.png"])
    assert any(b.get("type") == "image" for b in blocks)
    texts = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    assert file in texts and "not one of this site's images" in texts


def test_compaction_is_set_by_tokens_only(workspace: Path) -> None:
    from langchain.agents.middleware import SummarizationMiddleware

    tools = PageTools(workspace=workspace, spike_root=SPIKE, base_url="http://localhost:3047")
    agent, _ = build_agent(tools, model=ScriptedModel(messages=iter([AIMessage(content="ok")])))
    from trials_puck_agent import harness

    assert harness.COMPACT_AT_TOKENS >= 175_000
    middleware = SummarizationMiddleware(
        ScriptedModel(messages=iter([])),
        trigger=("tokens", harness.COMPACT_AT_TOKENS),
        keep=("tokens", harness.COMPACT_KEEP_TOKENS),
    )
    assert middleware.keep == ("tokens", harness.COMPACT_KEEP_TOKENS)


def test_clearing_waits_until_the_session_passes_the_threshold() -> None:
    from trials_puck_agent.harness import CLEAR_FROM_TOKENS, SupersededResults

    messages = [
        HumanMessage(content="build"),
        _ai([call("render_page", {}, 1)]),
        _render("call_1"),
        _ai([call("render_page", {}, 2)]),
        _render("call_2"),
    ]
    small = list(messages)
    SupersededResults().apply(small, count_tokens=lambda m: CLEAR_FROM_TOKENS - 1)
    assert small[2].content == messages[2].content  # a short session keeps everything (cache holds)
    large = list(messages)
    SupersededResults().apply(large, count_tokens=lambda m: CLEAR_FROM_TOKENS)
    assert isinstance(large[2].content, str) and "cleared" in large[2].content


def test_the_skills_ride_in_the_system_prompt(workspace: Path) -> None:
    from trials_puck_agent.harness import system_prompt_with_skills

    prompt = system_prompt_with_skills(workspace)
    assert (
        "## Your skills" in prompt
        and "### Skill: building-with-puck" in prompt
        and "Reuse first" in prompt
    )
    assert "writing-a-section" not in prompt  # the E5 skill only when new sections are allowed


def test_the_prompt_names_the_claims_file_only_when_the_workspace_has_one(workspace: Path) -> None:
    from trials_puck_agent.harness import system_prompt_with_skills

    without = system_prompt_with_skills(workspace)
    assert "research/claims.md" not in without and "[c4, c9]" not in without
    assert (
        "- `research/`: what we know about the account (its overview and insights). The" in without
    )
    assert "never put them on the page." in without  # the background sections are named either way
    assert (
        "- The brief sets the goal, the reader and the offer. Keep to those." in without
    )  # the brief rule stays

    (workspace / "research").mkdir(exist_ok=True)
    (workspace / "research" / "claims.md").write_text("# Claims\n")
    with_claims = system_prompt_with_skills(workspace)
    assert "`research/claims.md` lists each claim with what it" in with_claims
    assert "check its claim in `research/claims.md`" in with_claims


def test_the_images_skill_and_generate_image_reach_the_agent(workspace: Path) -> None:
    from trials_puck_agent.harness import system_prompt_with_skills

    prompt = system_prompt_with_skills(workspace)
    assert "### Skill: images-and-logos" in prompt and "Generate only a scene or a mood" in prompt
    assert "- `generate_image`:" in prompt and "- `view_asset`: shows you one image." in prompt
    assert "Your four skills" in prompt
