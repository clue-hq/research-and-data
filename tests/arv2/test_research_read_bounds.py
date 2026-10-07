"""Whole research views remain accessible without compulsory nested pagination."""

import json

from clue_api.arv2.quality_views import _passage
from clue_api.arv2.quality_workspace import render_view
from clue_config import Settings


def test_full_document_and_default_or_zero_line_limit():
    body = "Full source passage. " * 1000
    view = _passage(body, 0, "documents/example")
    assert view["next_path"] is None
    assert "".join(s["text"] for s in view["text_segments"]) == body
    value = {"rows": list(range(3000))}
    for limit in (0, 2000, 5000):
        result = render_view(value, offset=0, limit=limit)
        assert json.loads(result.file_data["content"]) == value
    focused = render_view(value, offset=3, limit=7)
    assert len(focused.file_data["content"].splitlines()) == 7


def test_a_read_without_a_window_returns_the_whole_view_at_the_libraries_real_default():
    # Production 2026-10-06: deepagents 0.6.12 fills an omitted `limit` with 100, not the 2000
    # this view assumed, so "read the whole file" returned 100 lines and the research agent paged
    # 700-line operation results 80 lines at a time (~330 extra reads across 12 jobs).
    from deepagents.middleware.filesystem import DEFAULT_READ_LIMIT

    value = {"rows": list(range(3000))}
    result = render_view(value, offset=0, limit=DEFAULT_READ_LIMIT)
    assert json.loads(result.file_data["content"]) == value


def test_zero_job_timeout_is_explicitly_supported():
    assert Settings(arv2_account_max_runtime_s=0).arv2_account_max_runtime_s == 0


def _read_all(render, path="/research/operations/x/0.json"):
    """Read a file through deepagents' real read_file tool, following continuation notes."""
    import asyncio
    import re

    from deepagents.backends.protocol import BackendProtocol
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from langchain.tools import ToolRuntime

    from clue_agents.tool_result_clearing import strip_read_gutter

    class Backend(BackendProtocol):
        async def aread(self, file_path, offset=0, limit=2000):
            return render(offset=offset, limit=limit)

    tool = next(t for t in FilesystemMiddleware(backend=Backend()).tools if t.name == "read_file")
    runtime = ToolRuntime(
        state={},
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="c",
        store=None,
    )
    parts, offset = [], 0
    while True:
        args = {"file_path": path, "runtime": runtime}
        if offset:
            args["offset"] = offset
        content = asyncio.run(tool.coroutine(**args)).content
        assert "truncated" not in content and len(content) < 80_000
        # What a recipe-26 research agent sees: the line-number column is stripped.
        content = strip_read_gutter(content)
        note = re.search(
            r"\n\[This file continues\. Read it again with offset=(\d+) to see the rest\.\]$",
            content,
        )
        if note is None:
            parts.append(content)
            return parts
        parts.append(content[: note.start()])
        offset = int(note[1])


def test_a_long_view_comes_back_in_parts_that_are_never_cut():
    """Review I4: deepagents cuts any read over 80,000 characters (its 20k-token limit) and
    points at a tool the research agent lacks. A long view comes in parts, each under the
    limit, each ending with the offset to read next; together they are the whole view."""
    value = {"rows": [{"title": "x" * 40, "text": "y" * 120, "i": i} for i in range(1500)]}
    whole = json.dumps(value, ensure_ascii=False, indent=2)
    parts = _read_all(lambda offset, limit: render_view(value, offset=offset, limit=limit))
    assert len(parts) > 1
    assert "\n".join(parts) == whole


def test_a_long_plain_text_file_comes_back_in_parts_too():
    from clue_api.arv2.quality_workspace import render_text

    body = "\n".join(f"Line {i}: " + "z" * 150 for i in range(1200))
    parts = _read_all(
        lambda offset, limit: render_text("# /evidence/a.json", body, offset=offset, limit=limit)
    )
    assert len(parts) > 1
    assert "\n".join(parts) == "# /evidence/a.json\n" + body


def test_a_short_view_has_no_continuation_note():
    parts = _read_all(lambda offset, limit: render_view({"a": 1}, offset=offset, limit=limit))
    assert parts == [json.dumps({"a": 1}, indent=2)]


def test_grep_searches_the_whole_file_not_just_its_first_part():
    import asyncio
    from types import SimpleNamespace

    from clue_api.arv2.quality_views import ResearchViewMount

    value = {"rows": [{"text": "y" * 120, "tag": f"row-{i}"} for i in range(1500)]}
    mount = ResearchViewMount.__new__(ResearchViewMount)
    mount._scope = SimpleNamespace(input_refs={"quality_recipe_version": 26})

    async def aread(file_path, offset=0, limit=2000):
        return render_view(value, offset=offset, limit=limit)

    mount.aread = aread
    found = asyncio.run(mount.agrep("row-1499", "/operations/x/0.json"))
    assert [m["text"].strip() for m in found.matches] == ['"tag": "row-1499"']
