"""Recipe 26 research views are the document itself, not escaped 256-character segments.

Production 2026-10-06: an operation result reached the agent as compact JSON cut into
256-character segments (splitting keys and UUIDs), escaped, inside indented JSON; 20% of the
tokens the research agent read were formatting (75,750 -> 60,755 over 80 real reads).
"""

import json

from deepagents.middleware.filesystem import DEFAULT_READ_LIMIT

from clue_api.arv2.quality_recipe import RECIPE_26, at_least, recipe_of
from clue_api.arv2.quality_views import PlainView, passage_view
from clue_api.arv2.quality_workspace import plain_source, render_text


class _Scope:
    def __init__(self, version):
        self.input_refs = {"quality_recipe_version": version}


def test_recipe_helpers_read_the_pinned_version():
    assert recipe_of(_Scope(26)) == 26 and at_least(_Scope(26), RECIPE_26)
    assert not at_least(_Scope(25), RECIPE_26)
    assert recipe_of(_Scope(None)) == 0


def test_plain_text_view_is_header_plus_body_with_no_escaping():
    body = json.dumps({"report": "Dialpad's CMO left in Sept 2025.", "n": 3})
    result = render_text(
        "# /research/operations/x/0.json", body, offset=0, limit=DEFAULT_READ_LIMIT
    )
    content = result.file_data["content"]
    assert content.splitlines()[0] == "# /research/operations/x/0.json"
    assert json.loads(content.split("\n", 1)[1]) == {
        "report": "Dialpad's CMO left in Sept 2025.",
        "n": 3,
    }
    assert '\\"' not in content and "text_segments" not in content


def test_recipe_26_passage_is_plain_and_recipe_25_keeps_segments():
    body = "x" * 1000
    new = passage_view(body, 0, "documents/a", recipe=26)
    old = passage_view(body, 0, "documents/a", recipe=25)
    assert isinstance(new, PlainView) and isinstance(new, str) and new.endswith(body)
    assert new.header.startswith("# /research/documents/a/0.json")
    assert old["text_segments"][0]["text"] == "x" * 256  # recipe 25 unchanged


def test_plain_view_honours_an_explicit_window_and_a_nonzero_start():
    body = "\n".join(f"line {i}" for i in range(500))
    window = render_text("# h", body, offset=10, limit=5).file_data["content"].splitlines()
    assert window == [f"line {i}" for i in range(9, 14)]  # the header is line 0
    assert passage_view(body, 7, "documents/a", recipe=26).endswith(body[7:])


def test_a_long_view_read_without_a_window_is_whole():
    body = "\n".join(f"line {i}" for i in range(3000))
    content = render_text("# h", body, offset=0, limit=DEFAULT_READ_LIMIT).file_data["content"]
    assert content == "# h\n" + body


def test_an_evidence_source_is_metadata_lines_then_its_text():
    source = {
        "path": "/evidence/0377-emily-wall.json",
        "kind": "web_snapshot",
        "source_url": "https://www.linkedin.com/in/emilywall",
        "metadata": {"title": "Emily Wall"},
        "text": "Emily Wall leads field marketing.\nSecond line.",
    }
    header, text = plain_source(source)
    assert header.splitlines()[0] == "# /evidence/0377-emily-wall.json"
    assert "source_url: https://www.linkedin.com/in/emilywall" in header
    assert "title: Emily Wall" in header
    assert text == "Emily Wall leads field marketing.\nSecond line."
