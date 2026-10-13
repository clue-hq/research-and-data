"""The site agent's harness (Lane B Task 7), driven by a scripted model (no model spend)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.site import harness
from lumen_agent.site.harness import (
    CANCELLED_SUMMARY,
    CLEAR_FROM_TOKENS,
    CRASHED_SUMMARY,
    ROUND_LIMIT_NOTE,
    SupersededResults,
    TurnLimitsConfig,
    build_site_agent,
    clear_superseded_results,
    run_site_turn,
    system_prompt_with_skills,
)
from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import ScriptedModel, call, garner_site, inputs_for, read_fixture

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
SITE = read_fixture("garner-syracuse.json")


def _empty_site() -> dict:
    return {"id": "doc_new", "title": "New", "theme": {}, "pages": {"/": {"root": {"props": {"title": "New"}}, "content": []}},
            "shell": None, "agent_sections": {}}


def _run(tmp_path: Path, script: list, *, site: dict | None = None, **kwargs):
    return run_site_turn(
        "build", config=AgentRuntimeConfig.from_env(), inputs=inputs_for(), workspace=tmp_path / "workspace",
        site=site or garner_site(), run_id="run_test", model=ScriptedModel(messages=iter(script)), **kwargs,
    )


def _agent(tmp_path: Path, script: list, *, site: dict | None = None, limits: TurnLimitsConfig = TurnLimitsConfig()):
    workspace = tmp_path / "workspace"
    inputs = inputs_for()
    site = site or garner_site()
    materialize_workspace(workspace, inputs, site=site)
    tools = SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)
    agent, guard, limits_mw = build_site_agent(
        tools, model=ScriptedModel(messages=iter(script)), model_id="openai:x-ai/grok-4.6", limits=limits)
    return agent, guard, limits_mw, tools


def _invoke(agent) -> list:
    state = agent.invoke({"messages": [{"role": "user", "content": "build"}]},
                         {"configurable": {"thread_id": "t"}, "recursion_limit": 200})
    return state["messages"]


def _results(messages: list) -> dict[str, str]:
    return {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}


@needs_node
def test_a_scripted_build_reads_a_skill_edits_the_page_and_validates(tmp_path: Path) -> None:
    content = json.dumps(SITE["pages"]["/"]["content"])
    agent, guard, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/skills/building-with-puck/SKILL.md", "limit": 1000}, 1)]),
        AIMessage(content="", tool_calls=[
            call("edit_file", {"file_path": "/page.json", "old_string": '"content": []', "new_string": f'"content": {content}'}, 2),
            call("write_file", {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])}, 3),
            call("write_file", {"file_path": "/pages/analysis.json", "content": json.dumps(SITE["pages"]["/analysis"])}, 4),
            call("validate_page", {}, 5),
        ]),
        AIMessage(content="Built the page."),
    ], site=_empty_site())
    results = _results(_invoke(agent))
    assert "Reuse first" in results["call_1"]
    assert results["call_5"] == "VALID.", results["call_5"]
    assert guard.status == "completed"


def test_the_agent_cannot_write_its_inputs(tmp_path: Path) -> None:
    agent, _, _, tools = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("edit_file", {"file_path": "/brief.md", "old_string": "For", "new_string": "x"}, 1)]),
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/skills/new/SKILL.md", "content": "x"}, 2)]),
        AIMessage(content="Done."),
    ])
    results = _results(_invoke(agent))
    assert (tools.workspace / "brief.md").read_text().startswith("For")
    assert not (tools.workspace / "skills" / "new").exists()
    assert "denied" in results["call_1"].lower() or "permission" in results["call_1"].lower()


@needs_node
def test_tool_calls_run_in_the_order_the_model_wrote_them(tmp_path: Path) -> None:
    broken = {"root": {"props": {"title": "x"}}, "content": [{"type": "CtaBand", "props": {
        "id": "cta", "surface": "green", "heading": "H", "body": "B", "buttonLabel": "Go", "buttonHref": "https://x.example"}}]}
    agent, _, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[
            call("write_file", {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])}, 1),
            call("write_file", {"file_path": "/pages/analysis.json", "content": json.dumps(broken)}, 2),
            call("validate_page", {}, 3),
        ]),
        AIMessage(content="Done."), AIMessage(content="Done."), AIMessage(content="Done."),
    ], site=_empty_site())
    result = _results(_invoke(agent))["call_3"]
    assert "content.0(cta).surface" in result and "does not exist" not in result


@needs_node
def test_a_turn_cannot_finish_on_an_invalid_page(tmp_path: Path) -> None:
    broken = {"root": {"props": {"title": "x"}}, "content": [{"type": "NoSuchSection", "props": {"id": "a"}}]}
    agent, guard, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/pages/broken.json", "content": json.dumps(broken)}, 1)]),
        AIMessage(content="All done."), AIMessage(content="All done."),
        AIMessage(content="All done, but the page is not finished."),
    ], site=_empty_site())
    messages = _invoke(agent)
    reminders = [m for m in messages if isinstance(m, HumanMessage) and "still invalid" in m.content]
    assert len(reminders) == 2 and "shell.json: does not exist yet" in reminders[0].content
    assert guard.status == "completed with errors"


def test_a_turn_that_leaves_the_site_alone_is_not_pushed(tmp_path: Path) -> None:
    """A turn that only builds a component (or only answers) is not pushed to make a page."""

    agent, guard, _, _ = _agent(tmp_path, [AIMessage(content="Rebuilt the hero as a component.")], site=_empty_site())
    messages = _invoke(agent)
    assert not [m for m in messages if isinstance(m, HumanMessage) and "still invalid" in m.content]
    assert guard.status == "completed (site unchanged)"


def test_the_round_limit_ends_a_runaway_request(tmp_path: Path) -> None:
    script = [AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, n)]) for n in range(10)]
    agent, _, limits_mw, _ = _agent(tmp_path, script, limits=TurnLimitsConfig(max_rounds=3))
    messages = _invoke(agent)
    assert limits_mw.rounds == 3 and limits_mw.stop_reason == "round_limit"
    assert messages[-1].content == ROUND_LIMIT_NOTE.format(limit=3)


def test_one_response_runs_at_most_its_per_round_limit(tmp_path: Path) -> None:
    agent, _, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 1), call("ls", {"path": "/"}, 2)]),
        AIMessage(content="Done."),
    ], limits=TurnLimitsConfig(max_calls_per_round=1))
    results = _results(_invoke(agent))
    assert not results["call_1"].startswith("Not run")
    assert results["call_2"].startswith("Not run: this was call 2 in one response, and only the first 1 run.")


def test_the_time_limit_stops_before_a_model_call(tmp_path: Path) -> None:
    result = _run(tmp_path, [], limits=TurnLimitsConfig(max_seconds=0.0))
    assert result.model_calls == [] and result.stop_reason == "time_limit"
    assert result.status == "applied" and result.site == garner_site()  # nothing changed, nothing lost


@needs_node
def test_a_valid_change_stands_when_the_round_limit_stops_the_request(tmp_path: Path) -> None:
    """Open question 3 (a): valid work done before the limit is saved, and the stop is reported."""

    result = _run(tmp_path, [
        AIMessage(content="", tool_calls=[call("edit_file", {
            "file_path": "/page.json", "old_string": "Lower medical spend for SCSD",
            "new_string": "Lower medical spend for Syracuse"}, 1)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 2)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 3)]),
    ], limits=TurnLimitsConfig(max_rounds=2))
    assert result.status == "applied" and result.stop_reason == "round_limit"
    assert "Lower medical spend for Syracuse" in json.dumps(result.site["pages"]["/"])


def test_a_validator_that_cannot_run_at_the_finish_leaves_the_verdict_to_the_save(tmp_path: Path, monkeypatch) -> None:
    """BV1a fix round 1 (DEFECT 2): a site-kit validator that cannot run is not an invalid page. The
    finish sends no reminder and does not end site_invalid; the site goes back as edited, and the
    executor's save (design_write_site's own check) gives the verdict."""

    from lumen_agent.site import tools as site_tools
    from lumen_api.site_kit_cli import SiteKitCliError

    def bundle_missing(*args, **kwargs):
        raise SiteKitCliError("site_kit.validator_unavailable", "site-kit validator bundle missing")

    monkeypatch.setattr(site_tools, "validate_site_files", bundle_missing)
    result = _run(tmp_path, [
        AIMessage(content="", tool_calls=[call("edit_file", {
            "file_path": "/page.json", "old_string": "Lower medical spend for SCSD",
            "new_string": "Lower medical spend for Syracuse"}, 1)]),
        AIMessage(content="Changed the heading."),
    ])
    # Two model calls and no third: a reminder would have asked the model again.
    assert len(result.model_calls) == 2
    assert result.status == "applied" and result.stop_reason is None and result.errors == []
    assert result.summary == "Changed the heading."
    assert "Lower medical spend for Syracuse" in json.dumps(result.site["pages"]["/"])


def test_a_limit_stop_while_the_validator_cannot_run_leaves_the_verdict_to_the_save(tmp_path: Path, monkeypatch) -> None:
    """BV1a fix round 2: the round limit stops an edited request while the site-kit validator
    cannot run. That is no verdict on the page, so the request is not site_invalid: the edited site
    goes back with the limit's stop reason and the executor's save decides."""

    from lumen_agent.site import tools as site_tools
    from lumen_api.site_kit_cli import SiteKitCliError

    def bundle_missing(*args, **kwargs):
        raise SiteKitCliError("site_kit.validator_unavailable", "site-kit validator bundle missing")

    monkeypatch.setattr(site_tools, "validate_site_files", bundle_missing)
    result = _run(tmp_path, [
        AIMessage(content="", tool_calls=[call("edit_file", {
            "file_path": "/page.json", "old_string": "Lower medical spend for SCSD",
            "new_string": "Lower medical spend for Syracuse"}, 1)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 2)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 3)]),
    ], limits=TurnLimitsConfig(max_rounds=2))
    assert result.status == "applied" and result.stop_reason == "round_limit" and result.errors == []
    assert "Lower medical spend for Syracuse" in json.dumps(result.site["pages"]["/"])


def test_a_cancelled_request_never_calls_the_model(tmp_path: Path) -> None:
    result = _run(tmp_path, [], cancel_requested=lambda: True)
    assert result.status == "failed" and result.stop_reason == "cancelled_by_request"
    assert result.summary == CANCELLED_SUMMARY and result.model_calls == []


def test_a_workspace_that_cannot_be_written_returns_the_crash_result(tmp_path: Path, monkeypatch) -> None:
    def disk_full(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(harness, "materialize_workspace", disk_full)
    result = _run(tmp_path, [])
    assert result.status == "failed" and result.stop_reason == "crashed"
    assert result.summary == CRASHED_SUMMARY and result.model_calls == []


def test_an_agent_that_cannot_be_built_returns_the_crash_result(tmp_path: Path, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("no agent")

    monkeypatch.setattr(harness, "build_site_agent", broken)
    result = _run(tmp_path, [])
    assert result.status == "failed" and result.stop_reason == "crashed"
    assert result.summary == CRASHED_SUMMARY and result.model_calls == []


def test_the_requests_model_calls_ride_back_and_an_untouched_site_is_returned_as_stored(tmp_path: Path) -> None:
    result = _run(tmp_path, [
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 1)]),
        AIMessage(content="Looked around; nothing to change."),
    ])
    assert len(result.model_calls) == 2
    assert result.status == "applied" and result.summary == "Looked around; nothing to change."
    assert result.site == garner_site()


def test_compaction_is_the_platforms_sized_from_the_model(tmp_path: Path, monkeypatch) -> None:
    from clue_agents import compaction_config
    from clue_agents.compaction import CompactionSettings

    asked: list[str] = []

    def recording(model_id: str) -> CompactionSettings:
        asked.append(model_id)
        return CompactionSettings.fallback()

    monkeypatch.setattr(compaction_config, "compaction_for", recording)
    _agent(tmp_path, [AIMessage(content="ok")])
    assert asked == ["openai:x-ai/grok-4.6"]


def _ai(calls: list[dict]) -> AIMessage:
    return AIMessage(content="", tool_calls=calls)


def _result(name: str, n: str, content) -> ToolMessage:
    return ToolMessage(name=name, tool_call_id=n, content=content)


def _render(n: str) -> ToolMessage:
    return _result("render_page", n, [{"type": "text", "text": f"1440 wide: render {n}"},
                                      {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": "AAAA"}])


def test_only_the_newest_render_keeps_its_screenshots() -> None:
    messages = [HumanMessage(content="build"), _ai([call("render_page", {}, 1)]), _render("call_1"),
                _ai([call("render_page", {}, 2)]), _render("call_2")]
    cleared = clear_superseded_results(messages)
    assert isinstance(cleared[2].content, str) and "render call_1" in cleared[2].content
    assert cleared[4] is messages[4]
    assert clear_superseded_results(cleared)[2].content == cleared[2].content


def test_only_the_newest_comparison_keeps_its_pictures() -> None:
    picture = {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": "AAAA"}
    messages = [HumanMessage(content="rebuild"),
                _ai([call("view_clone", {"fragment_id": "f"}, 1)]),
                _result("view_clone", "call_1", [{"type": "text", "text": "card"}, picture]),
                _ai([call("compare_section", {"name": "Hero"}, 2)]),
                _result("compare_section", "call_2", [{"type": "text", "text": "1440 wide: 31% differs"}, picture]),
                _ai([call("compare_section", {"name": "Hero"}, 3)]),
                _result("compare_section", "call_3", [{"type": "text", "text": "1440 wide: 12% differs"}, picture])]
    cleared = clear_superseded_results(messages)
    assert isinstance(cleared[2].content, str) and "card" in cleared[2].content
    assert isinstance(cleared[4].content, str) and "31% differs" in cleared[4].content
    assert cleared[6] is messages[6]


def test_planning_reads_clear_once_the_plan_is_written_and_building_starts() -> None:
    reads = [_ai([call("read_file", {"file_path": "/research/overview.md"}, 1),
                  call("read_file", {"file_path": "/skills/page-review/SKILL.md"}, 2),
                  call("fetch_page", {"url": "https://x.example/a"}, 3)]),
             _result("read_file", "call_1", "research text " * 50),
             _result("read_file", "call_2", "skill text"),
             _result("fetch_page", "call_3", "Saved to fetched/x-a.md (status 200).\n\npage text")]
    plan = [_ai([call("write_file", {"file_path": "/plan.md", "content": "p"}, 4)]), _result("write_file", "call_4", "ok")]
    build = [_ai([call("write_file", {"file_path": "/page.json", "content": "{}"}, 5)]), _result("write_file", "call_5", "ok")]
    before = clear_superseded_results([HumanMessage(content="build"), *reads, *plan])
    assert before[2].content.startswith("research text")  # the plan alone does not end planning
    after = clear_superseded_results([HumanMessage(content="build"), *reads, *plan, *build])
    assert after[2].content.startswith("[cleared to save context: read_file(/research/overview.md)")
    assert after[3].content == "skill text"  # skills stay
    assert "Saved to fetched/x-a.md." in after[4].content  # the stub says where the page was saved


def test_an_old_read_of_a_site_file_clears_only_after_a_newer_render() -> None:
    read = [_ai([call("read_file", {"file_path": "/page.json"}, 1)]), _result("read_file", "call_1", "old page")]
    edit = [_ai([call("edit_file", {"file_path": "/page.json", "old_string": "a", "new_string": "b"}, 2)]),
            _result("edit_file", "call_2", "ok")]
    render = [_ai([call("render_page", {}, 3)]), _render("call_3")]
    no_render = clear_superseded_results([HumanMessage(content="edit"), *read, *edit])
    assert no_render[2].content == "old page"  # unchanged until a render: the prefix stays stable
    with_render = clear_superseded_results([HumanMessage(content="edit"), *read, *edit, *render])
    assert "an older read of /page.json" in with_render[2].content


def test_clearing_waits_until_the_session_passes_the_threshold() -> None:
    messages = [HumanMessage(content="build"), _ai([call("render_page", {}, 1)]), _render("call_1"),
                _ai([call("render_page", {}, 2)]), _render("call_2")]
    small = list(messages)
    SupersededResults().apply(small, count_tokens=lambda m: CLEAR_FROM_TOKENS - 1)
    assert small[2].content == messages[2].content
    large = list(messages)
    SupersededResults().apply(large, count_tokens=lambda m: CLEAR_FROM_TOKENS)
    assert isinstance(large[2].content, str) and "cleared" in large[2].content


def test_the_skills_ride_in_the_system_prompt_with_the_e5_skills_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs_for(), site=garner_site())
    prompt = system_prompt_with_skills(workspace)
    assert "## Your skills" in prompt and "### Skill: building-with-puck" in prompt and "Reuse first" in prompt
    assert "### Skill: images-and-logos" in prompt and "Generate only a scene or a mood" in prompt
    assert "### Skill: writing-a-section" in prompt and "### Skill: rebuilding-a-section" in prompt
    assert "### Skill: writing-a-section" not in system_prompt_with_skills(workspace, allow_new_sections=False)


def test_the_prompt_names_the_claims_file_only_when_the_workspace_has_one(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs_for(), site=garner_site())
    without = system_prompt_with_skills(workspace)
    assert "research/claims.md" not in without and "[c4, c9]" not in without
    (workspace / "research" / "claims.md").write_text("# Claims\n")
    with_claims = system_prompt_with_skills(workspace)
    assert "`research/claims.md` lists each claim with what it" in with_claims
    assert "check its claim in `research/claims.md`" in with_claims


def test_a_read_without_a_limit_gets_the_whole_file(tmp_path: Path) -> None:
    agent, _, _, tools = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/research/long.md"}, 1)]),
        AIMessage(content="Done."),
    ])
    (tools.workspace / "research" / "long.md").write_text("\n".join(f"line {n}" for n in range(1, 251)))
    assert "line 250" in _results(_invoke(agent))["call_1"]
