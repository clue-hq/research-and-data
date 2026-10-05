"""The website agent's context clearing rule (founder decisions 2026-10-06).

Old screenshots go once a newer preview round exists; planning results (section searches,
inspections, section pictures) go once plan.md exists. Each becomes a stub that says what it
was and how to get it back. The rule depends only on the message list, so the cleared set
changes only when a new round lands or the plan is first written — that keeps the cache.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from lumen_agent.context_clearing import CLEARED_MARKER, clear_superseded_tool_results

_IMAGE = [{"type": "text", "text": "{\"tile\": 0}"},
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]


def _call(call_id: str, name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _result(call_id: str, name: str, content="ok", status="success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=name, status=status)


def _cleared(message) -> bool:
    return bool(message.response_metadata.get(CLEARED_MARKER, {}).get("cleared"))


def _history_with_two_rounds():
    return [
        HumanMessage(content="brief"),
        _call("r1", "render_web_preview"), _result("r1", "render_web_preview"),
        _call("v1", "view", target="preview:1440:tile:0"), _result("v1", "view", _IMAGE),
        _call("a1", "view", target="asset:asset_x"), _result("a1", "view", _IMAGE),
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview"),
        _call("v2", "view", target="preview:1440:tile:0"), _result("v2", "view", _IMAGE),
    ]


def test_screenshots_from_an_earlier_round_become_stubs_and_the_latest_round_stays() -> None:
    out = clear_superseded_tool_results(_history_with_two_rounds())
    old, latest = out[4], out[10]
    assert _cleared(old) and isinstance(old.content, str)
    assert "view('preview:1440:tile:0')" in old.content and "render_web_preview" in old.content
    assert old.artifact is None
    assert not _cleared(latest) and latest.content == _IMAGE
    # The renders themselves and asset views are never cleared.
    assert not _cleared(out[2]) and not _cleared(out[8])
    assert not _cleared(out[6])


def test_a_failed_render_does_not_start_a_new_round() -> None:
    history = _history_with_two_rounds()[:7] + [
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview", "boom", "error"),
    ]
    out = clear_superseded_tool_results(history)
    assert not _cleared(out[4])  # the round-1 screenshot is still the current one


def _planning_history(plan_tool: str = "write_file", plan_path: str = "/sessions/s/workspace/plan.md"):
    return [
        HumanMessage(content="brief"),
        _call("s1", "search_cloned_sections", query="hero"), _result("s1", "search_cloned_sections", "x" * 400),
        _call("i1", "inspect_cloned_section", fragment_id="frag_a"), _result("i1", "inspect_cloned_section", "y" * 400),
        _call("c1", "view", target="cloned_section:frag_a"), _result("c1", "view", _IMAGE),
        _call("p1", plan_tool, file_path=plan_path), _result("p1", plan_tool),
        _call("i2", "inspect_cloned_section", fragment_id="frag_b"), _result("i2", "inspect_cloned_section", "z" * 400),
    ]


def test_planning_results_stay_until_the_plan_is_written() -> None:
    history = _planning_history()[:7]
    out = clear_superseded_tool_results(history)
    assert not any(_cleared(m) for m in out if isinstance(m, ToolMessage))


def test_planning_results_before_the_plan_become_stubs_after_it_is_written() -> None:
    out = clear_superseded_tool_results(_planning_history())
    for index, tool, key in ((2, "search_cloned_sections", "hero"),
                             (4, "inspect_cloned_section", "frag_a"),
                             (6, "view", "cloned_section:frag_a")):
        assert _cleared(out[index]), index
        assert tool in out[index].content and key in out[index].content
        assert "plan.md" in out[index].content
    assert not _cleared(out[8])   # the plan write's own result
    assert not _cleared(out[10])  # an inspection after the plan stays


def test_the_plan_counts_when_edited_or_written_to_a_relative_path_but_not_a_lookalike() -> None:
    assert _cleared(clear_superseded_tool_results(_planning_history("edit_file"))[2])
    assert _cleared(clear_superseded_tool_results(_planning_history(plan_path="workspace/plan.md"))[2])
    assert not _cleared(clear_superseded_tool_results(_planning_history(plan_path="workspace/review-plan.md"))[2])
    assert not _cleared(clear_superseded_tool_results(_planning_history(plan_path="workspace/plan.md.bak"))[2])


def test_parallel_calls_in_one_message_are_matched_by_call_id() -> None:
    both = AIMessage(content="", tool_calls=[
        {"id": "va", "name": "view", "args": {"target": "asset:asset_y"}},
        {"id": "vb", "name": "view", "args": {"target": "preview:768"}},
    ])
    history = [
        _call("r1", "render_web_preview"), _result("r1", "render_web_preview"),
        both, _result("va", "view", _IMAGE), _result("vb", "view", _IMAGE),
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview"),
    ]
    out = clear_superseded_tool_results(history)
    assert not _cleared(out[3])  # asset view kept
    assert _cleared(out[4])      # preview view from round 1 cleared


def test_a_view_without_a_target_is_left_untouched() -> None:
    history = [
        _call("r1", "render_web_preview"), _result("r1", "render_web_preview"),
        _call("v1", "view"), _result("v1", "view", _IMAGE),
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview"),
    ]
    assert not _cleared(clear_superseded_tool_results(history)[3])


def test_the_rule_is_idempotent_and_does_not_mutate_its_input() -> None:
    history = _history_with_two_rounds()
    snapshot = [m.model_copy(deep=True) for m in history]
    once = clear_superseded_tool_results(history)
    twice = clear_superseded_tool_results(once)
    assert [m.model_dump() for m in once] == [m.model_dump() for m in twice]
    assert [m.model_dump() for m in history] == [m.model_dump() for m in snapshot]


def test_the_cleared_prefix_is_stable_between_boundaries() -> None:
    """Cache safety: with no new render and no first plan write in between, a longer history
    clears exactly the same earlier messages as the shorter one."""
    history = _history_with_two_rounds() + [
        _call("v3", "view", target="layout:1440"), _result("v3", "view", "{}"),
    ]
    short = clear_superseded_tool_results(history[:11])
    long = clear_superseded_tool_results(history)
    assert [m.model_dump() for m in long[:11]] == [m.model_dump() for m in short]


def test_the_edit_runs_through_langchains_real_middleware_and_leaves_saved_history_alone() -> None:
    """The adapter must fit ContextEditingMiddleware's real call shape: the model sees stubs,
    the request's own message list (the saved history) keeps the originals."""
    import asyncio

    from langchain.agents.middleware import ContextEditingMiddleware
    from langchain.agents.middleware.types import ModelRequest
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

    from lumen_agent.context_clearing import SupersededToolResultsEdit

    history = _history_with_two_rounds()
    request = ModelRequest(model=FakeMessagesListChatModel(responses=[AIMessage(content="x")]),
                           messages=history)
    middleware = ContextEditingMiddleware(edits=[SupersededToolResultsEdit()])
    seen: list = []

    def handler(req):
        seen.append(req.messages)
        return AIMessage(content="done")

    middleware.wrap_model_call(request, handler)

    async def ahandler(req):
        seen.append(req.messages)
        return AIMessage(content="done")

    asyncio.run(middleware.awrap_model_call(request, ahandler))
    for sent in seen:
        assert _cleared(sent[4]) and not _cleared(sent[10])
    assert not _cleared(history[4]) and history[4].content == _IMAGE
