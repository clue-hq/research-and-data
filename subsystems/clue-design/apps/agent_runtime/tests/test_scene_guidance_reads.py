"""Selected guidance pagination through the real SDK and offline agent graphs."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agent_fixtures import FakeCoreClient
from deepagents import FilesystemPermission
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from lumen_agent import harness
from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.guidance_reads import SceneGuidanceReadMiddleware
from lumen_agent.workspace import initial_turn_state
from test_scene_catalog_runtime import ScriptedModel, call
from test_scene_skill_family import candidate_config


class GuidanceModel(ScriptedModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # The SDK's async fallback supplies positional stop/run_manager values.
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def sdk_reader(tmp_path, *, token_limit=20000, permissions=None):
    backend = AgentWorkspaceBackend(tmp_path, active_run_id="run_active")
    reader = FilesystemMiddleware(
        backend=backend,
        tool_token_limit_before_evict=token_limit,
        _permissions=permissions,
    )._create_read_file_tool()
    middleware = SceneGuidanceReadMiddleware(backend)

    def read(args, *, asynchronous=False, after_read=None):
        request = SimpleNamespace(tool_call={"name": "read_file", "args": args, "id": "read"})
        runtime = SimpleNamespace(tool_call_id="read")
        original = None

        def handler(_):
            nonlocal original
            original = reader.func(runtime=runtime, **args)
            if after_read:
                after_read()
            return original

        async def ahandler(_):
            nonlocal original
            original = await reader.coroutine(runtime=runtime, **args)
            if after_read:
                after_read()
            return original

        result = (
            asyncio.run(middleware.awrap_tool_call(request, ahandler))
            if asynchronous
            else middleware.wrap_tool_call(request, handler)
        )
        return original, result

    return read


def resource(tmp_path, content, key="knowledge_docs/knowledge/scene/review.md"):
    path = tmp_path / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "args,end,next_offset,eof,whole",
    [
        ({}, 100, 100, False, False),
        ({"limit": 80}, 80, 80, False, False),
        ({"offset": 80, "limit": 200}, 136, None, True, False),
        ({"limit": 136}, 136, None, True, True),
    ],
)
def test_sdk_slice_is_unchanged_and_range_notice_is_outside_numbered_source(
    tmp_path,
    asynchronous,
    args,
    end,
    next_offset,
    eof,
    whole,
):
    resource(tmp_path, "".join(f"source line {number}\n" for number in range(1, 137)))
    original, result = sdk_reader(tmp_path)(
        {"file_path": "/knowledge_docs/knowledge/scene/review.md", **args},
        asynchronous=asynchronous,
    )
    notice, body = result.content.split("\n\n", 1)
    assert body == original.content
    assert not notice[0].isdigit() and "\t" not in notice
    metadata = result.additional_kwargs["guidance_read"]
    assert metadata["source_lines"] == 136
    assert metadata["end_line"] == end
    assert metadata["next_offset"] == next_offset
    assert metadata["reaches_eof"] is eof
    assert metadata["whole_resource"] is whole


@pytest.mark.parametrize("alias", ["virtual", "host", "legacy", "repo"])
def test_guidance_aliases_share_the_canonical_range(tmp_path, alias):
    path = resource(tmp_path, "first\nsecond\nthird")
    key = {
        "virtual": "/knowledge_docs/knowledge/scene/review.md",
        "host": str(path),
        "legacy": "/.lumen-runs/knowledge_docs/knowledge/scene/review.md",
        "repo": "/apps/agent_runtime/knowledge_docs/knowledge/scene/review.md",
    }[alias]
    original, result = sdk_reader(tmp_path)({"file_path": key, "offset": 1, "limit": 1})
    assert result.content.endswith(original.content)
    assert (
        result.additional_kwargs["guidance_read"]["path"]
        == "/knowledge_docs/knowledge/scene/review.md"
    )
    assert result.additional_kwargs["guidance_read"]["next_offset"] == 2


@pytest.mark.parametrize(
    "case",
    [
        "ordinary",
        "missing",
        "binary",
        "sibling",
        "symlink",
        "permission",
        "offset",
        "zero",
        "negative",
    ],
)
def test_non_guidance_errors_denials_and_invalid_slices_keep_stock_response(tmp_path, case):
    path = resource(tmp_path, "first\nsecond\n")
    key = "/knowledge_docs/knowledge/scene/review.md"
    args, permissions = {}, None
    if case == "ordinary":
        resource(tmp_path, "first\nsecond\n", "run_active/workspace/critique.md")
        key = "/run_active/workspace/critique.md"
    elif case == "missing":
        path.unlink()
    elif case == "binary":
        resource(tmp_path, "image bytes", "knowledge_docs/preview.png")
        key = "/knowledge_docs/preview.png"
    elif case in {"sibling", "symlink"}:
        target = resource(tmp_path, "PRIVATE", "run_sibling/workspace/secret.md")
        key = "/run_sibling/workspace/secret.md"
        if case == "symlink":
            path.unlink()
            path.symlink_to(target)
            key = "/knowledge_docs/knowledge/scene/review.md"
    elif case == "permission":
        permissions = [FilesystemPermission(operations=["read"], paths=[key], mode="deny")]
    else:
        args = {"offset": 10} if case == "offset" else {"limit": 0 if case == "zero" else -1}
    original, result = sdk_reader(tmp_path, permissions=permissions)({"file_path": key, **args})
    assert result == original
    assert "PRIVATE" not in str(result.content)


@pytest.mark.parametrize("content", ["", " \n \n"])
def test_empty_guidance_preserves_warning_without_claiming_instruction_coverage(tmp_path, content):
    resource(tmp_path, content)
    original, result = sdk_reader(tmp_path)(
        {"file_path": "/knowledge_docs/knowledge/scene/review.md"}
    )
    assert result.content.endswith(original.content)
    metadata = result.additional_kwargs["guidance_read"]
    assert metadata["status"] == "empty"
    assert "whole_resource" not in metadata and "reaches_eof" not in metadata


def test_size_truncation_does_not_claim_the_requested_window_or_eof(tmp_path):
    resource(tmp_path, "long line " * 12000)
    original, result = sdk_reader(tmp_path)(
        {"file_path": "/knowledge_docs/knowledge/scene/review.md"}
    )
    assert "Output was truncated" in original.content
    assert result.content.endswith(original.content)
    metadata = result.additional_kwargs["guidance_read"]
    assert metadata["status"] == "truncated"
    assert not {"end_line", "next_offset", "whole_resource", "reaches_eof"} & metadata.keys()


@pytest.mark.parametrize("replacement", ["different\nlonger\nresource\n", ""])
def test_changed_resource_cannot_certify_the_returned_excerpt(tmp_path, replacement):
    path = resource(tmp_path, "before\n")
    original, result = sdk_reader(tmp_path)(
        {"file_path": "/knowledge_docs/knowledge/scene/review.md"},
        after_read=lambda: path.write_text(replacement),
    )
    assert result.content.endswith(original.content)
    assert result.additional_kwargs["guidance_read"]["status"] == "unavailable"
    assert "whole_resource" not in result.additional_kwargs["guidance_read"]


def test_long_wrapped_source_lines_keep_their_source_line_count(tmp_path):
    resource(tmp_path, "a" * 6000 + "\nlast\n")
    original, result = sdk_reader(tmp_path)(
        {"file_path": "/knowledge_docs/knowledge/scene/review.md", "limit": 1}
    )
    assert "1.1\t" in original.content
    assert result.content.endswith(original.content)
    metadata = result.additional_kwargs["guidance_read"]
    assert metadata["source_lines"] == 2 and metadata["next_offset"] == 1


def test_concurrent_guidance_reads_have_independent_metadata(tmp_path):
    resource(tmp_path, "a\nb\nc\n")
    resource(tmp_path, "one\ntwo\n", ".deepagent/skills/example/SKILL.md")
    read = sdk_reader(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            read, {"file_path": "/knowledge_docs/knowledge/scene/review.md", "limit": 1}
        )
        second = pool.submit(
            read, {"file_path": "/.deepagent/skills/example/SKILL.md", "offset": 1}
        )
        first_metadata = first.result()[1].additional_kwargs["guidance_read"]
        second_metadata = second.result()[1].additional_kwargs["guidance_read"]
    assert first_metadata["source_lines"] == 3 and first_metadata["next_offset"] == 1
    assert second_metadata["source_lines"] == 2 and second_metadata["reaches_eof"] is True


@pytest.mark.parametrize("solo", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_selected_guidance_continuation_reaches_model_without_loading_other_bodies(
    tmp_path,
    monkeypatch,
    solo,
    asynchronous,
):
    """A selected review's missing tail must be visible, including after delegation."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.assert_model_supports_image_input", lambda *a, **k: None)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda *a: None
    )
    # The production async budget callback lacks run_inline; this test isolates
    # read middleware, not model-spend callbacks. Sync/async SDK reads stay real.
    monkeypatch.setattr(harness, "attach_budget_callback", lambda model, *a: model)
    review_path = "/knowledge_docs/knowledge/scene/review.md"
    responses = [
        call("read_file", {"file_path": "/.deepagent/skills/visual-review/SKILL.md"}, "skill"),
        call("read_file", {"file_path": review_path, "limit": 80}, "first"),
        call("read_file", {"file_path": review_path, "offset": 80, "limit": 1000}, "tail"),
        AIMessage(content="The requested excerpts were returned."),
    ]
    reader = GuidanceModel(responses=responses)
    director = (
        reader
        if solo
        else GuidanceModel(
            responses=[
                call("read_file", {"file_path": review_path, "limit": 80}, "director-read"),
                call(
                    "task",
                    {
                        "subagent_type": "lumen-dsl-author",
                        "description": "Read the selected review guide.",
                    },
                    "delegate",
                ),
                AIMessage(content="Read complete."),
            ]
        )
    )
    models = iter(
        [director]
        if solo
        else [director, reader, GuidanceModel(responses=[AIMessage(content="unused")])]
    )
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: next(models))
    config = replace(candidate_config(tmp_path), scene_solo=solo)
    graph, tools = harness.create_design_deepagent(
        "Review this creative", config, checkpointer=InMemorySaver()
    )
    invocation = {"configurable": {"thread_id": "guidance"}, "recursion_limit": 30}
    state = initial_turn_state(tools, "Read the selected review guide.")
    if asynchronous:
        asyncio.run(graph.ainvoke(state, invocation))
    else:
        graph.invoke(state, invocation)
    messages = {
        message.tool_call_id: message
        for turn in reader.seen
        for message in turn
        if isinstance(message, ToolMessage)
    }
    first, tail = messages["first"], messages["tail"]
    assert first.status == tail.status == "success"
    assert "Readability status is" not in first.content
    assert "Readability status is" in tail.content
    first_window = first.additional_kwargs.get("guidance_read")
    assert first_window is not None, (
        "A successful partial guidance read must expose its missing tail"
    )
    assert first_window["next_offset"] == 80
    assert first_window["reaches_eof"] is False
    assert "offset=80" in first.content
    tail_window = tail.additional_kwargs["guidance_read"]
    assert tail_window["reaches_eof"] is True
    assert tail_window["whole_resource"] is False
    assert "excerpt" in tail.content.lower()
    assert "end of resource" in tail.content.lower()
    if not solo:
        director_read = next(
            message
            for turn in director.seen
            for message in turn
            if isinstance(message, ToolMessage) and message.tool_call_id == "director-read"
        )
        assert director_read.additional_kwargs["guidance_read"]["next_offset"] == 80
    # The graph exposes only explicitly selected bodies; discovery stays metadata-only.
    unselected = (
        tools.config.workspace_root / ".deepagent/skills/event-webinar/SKILL.md"
    ).read_text()
    for model in (director, reader):
        for turn in model.seen:
            assert unselected not in str(turn)
            assert "## When to use" not in str(turn[0].content)


def test_legacy_scene_read_response_remains_identical_to_stock_sdk(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda *a: None
    )
    key = "/knowledge_docs/skills/visual-review/SKILL.md"
    reader = GuidanceModel(
        responses=[
            call("read_file", {"file_path": key, "limit": 3}, "control"),
            AIMessage(content="Control read returned."),
        ]
    )
    models = iter(
        [
            reader,
            GuidanceModel(responses=[AIMessage(content="unused")]),
            GuidanceModel(responses=[AIMessage(content="unused")]),
        ]
    )
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: next(models))
    config = replace(candidate_config(tmp_path), scene_skill_bundle="legacy", fast_loop=False)
    graph, tools = harness.create_design_deepagent("Read the existing guide", config)
    graph.invoke(initial_turn_state(tools, "Read the existing guide"))
    returned = next(
        message
        for turn in reader.seen
        for message in turn
        if isinstance(message, ToolMessage) and message.tool_call_id == "control"
    )
    stock = FilesystemMiddleware(backend=AgentWorkspaceBackend(tools.config.workspace_root))
    expected = stock._create_read_file_tool().func(
        file_path=key,
        limit=3,
        runtime=SimpleNamespace(tool_call_id="control"),
    )
    assert returned.content == expected.content
    assert returned.additional_kwargs == expected.additional_kwargs == {}
