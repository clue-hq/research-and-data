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


def test_zero_job_timeout_is_explicitly_supported():
    assert Settings(arv2_account_max_runtime_s=0).arv2_account_max_runtime_s == 0
