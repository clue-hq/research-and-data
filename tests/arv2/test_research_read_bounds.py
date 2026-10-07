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
