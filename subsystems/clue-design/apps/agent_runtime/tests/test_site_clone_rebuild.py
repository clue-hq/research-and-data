"""R2 (Lane B Task 18): look at a seller's section alone, and compare a rebuilt one with it."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from lumen_agent.site.inputs import SiteSection
from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from site_fixtures import garner_brand, garner_site, inputs_for

SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}, "heading": {"type": "string"}}}


@dataclass
class DrawingRenderer:
    """Draws a scratch site's one section: a clone as its stored HTML, an agent section as its
    heading. The picture is grey for a clone and white for a rebuilt section."""

    brand: dict
    calls: list = field(default_factory=list)

    def render(self, site, brand, sections, *, route):
        (item,) = site["pages"][route]["content"]
        self.calls.append(("render", item["type"], site.get("shell"), [s.name for s in sections]))
        if item["type"] == "ClonedSection":
            return f"<main>{self.brand['clones'][item['props']['fragmentId']]['html']}</main>", "", []
        return f"<main><h2>{item['props'].get('heading', '')}</h2></main>", "", []

    def screenshot(self, html, css, *, width):
        buffer = io.BytesIO()
        Image.new("RGB", (width, 400), "grey" if "<h2>" not in html else "white").save(buffer, format="PNG")
        return buffer.getvalue()


def _tools(tmp_path: Path, renderer) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(renderer=renderer, agent_sections={
        "HeroRebuilt": SiteSection(name="HeroRebuilt", digest="e" * 64, props_schema=SCHEMA, module_js="export {}", css="")})
    site = garner_site()
    materialize_workspace(workspace, inputs, site=site)
    return SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)


def _clone_id() -> str:
    return next(iter(garner_brand()["clones"]))


def test_view_clone_draws_the_section_alone_at_both_widths(tmp_path: Path) -> None:
    renderer = DrawingRenderer(garner_brand())
    blocks = _tools(tmp_path, renderer).view_clone(_clone_id())
    texts = [block["text"] for block in blocks if block["type"] == "text"]
    assert texts[1].startswith("The original at 1440 wide, in 1 part(s)") and texts[2].startswith("The original at 375 wide")
    assert [call[:3] for call in renderer.calls] == [("render", "ClonedSection", None)]
    assert sum(1 for block in blocks if block["type"] == "image") == 2


def test_view_clone_names_a_clone_that_does_not_exist(tmp_path: Path) -> None:
    assert _tools(tmp_path, DrawingRenderer(garner_brand())).view_clone("frag_nope") == "No clone frag_nope; see catalog/index.md."


def test_compare_section_scores_the_difference_and_lists_missing_words(tmp_path: Path) -> None:
    renderer = DrawingRenderer(garner_brand())
    blocks = _tools(tmp_path, renderer).compare_section("HeroRebuilt", _clone_id(), {"heading": "Something else entirely"})
    summary = blocks[0]["text"]
    assert summary.startswith("1440 wide: 100% of the area differs; heights 400px (original) and 400px (yours).")
    assert "Words of the original missing from yours: " in summary and "375 wide:" in summary
    rebuilt = [call for call in renderer.calls if call[1] == "HeroRebuilt"]
    assert rebuilt and rebuilt[0][3] == ["HeroRebuilt"]


def test_compare_section_needs_a_written_component(tmp_path: Path) -> None:
    result = _tools(tmp_path, DrawingRenderer(garner_brand())).compare_section("NotWritten", _clone_id(), {})
    assert result == "No component NotWritten on this site yet; write it with write_section first."


def test_a_render_that_fails_reads_as_the_spikes_sentence(tmp_path: Path) -> None:
    class Failing(DrawingRenderer):
        def render(self, site, brand, sections, *, route):
            raise RuntimeError("render.failed")

    tools = _tools(tmp_path, Failing(garner_brand()))
    assert tools.view_clone(_clone_id()) == f"Could not show {_clone_id()} (the preview did not render)."
    assert tools.compare_section("HeroRebuilt", _clone_id(), {}) == (
        "Could not compare: the preview did not show both sections. Check that the props fit "
        "HeroRebuilt's schema (catalog/seller-components.md)."
    )
