"""render_page (Lane B Task 9): Lane A's renderer through the render port, no dev server."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import FakeAssets, FakeRenderer, garner_site, inputs_for, png

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
HELD = "a" * 64


def _tools(tmp_path: Path, renderer: FakeRenderer, assets: FakeAssets | None = None) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(renderer=renderer, assets=assets or FakeAssets(blobs={HELD: ("image/png", png())}))
    materialize_workspace(workspace, inputs, site=garner_site())
    return SiteTools(workspace=workspace, inputs=inputs, base_site=garner_site(), retry_delay_s=0)


@needs_node
def test_render_page_refuses_an_unknown_page(tmp_path: Path) -> None:
    result = _tools(tmp_path, FakeRenderer()).render_page("/pricing")
    assert isinstance(result, str) and "no page /pricing" in result and "/analysis" in result


@needs_node
def test_render_page_refuses_an_invalid_page(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakeRenderer())
    page = json.loads((tools.workspace / "page.json").read_text())
    next(i for i in page["content"] if i["props"]["id"] == "proof")["props"]["surface"] = "green"
    (tools.workspace / "page.json").write_text(json.dumps(page))
    result = tools.render_page()
    assert isinstance(result, str) and result.startswith("NOT RENDERED: the site is invalid.")


@needs_node
def test_render_page_returns_desktop_and_mobile_pictures_with_facts(tmp_path: Path) -> None:
    renderer = FakeRenderer(html=f'<img src="/asset-store/{HELD}"><img src="/asset-store/{"b" * 64}">')
    blocks = _tools(tmp_path, renderer).render_page("/analysis")
    texts = [b["text"] for b in blocks if b.get("type") == "text"]
    images = [b for b in blocks if b.get("type") == "image"]
    assert texts[0].startswith("1440 wide: page height 2000px, broken images: 1, horizontal overflow: no. Shown at")
    assert "console" not in " ".join(texts)  # founder 2026-10-12: no fact that can never change
    assert texts[1].startswith("375 wide: page height 2000px, broken images: 1")
    assert "top to bottom" in texts[0] and len(images) >= 3  # tall pages arrive in parts
    widths = {base64.b64decode(b["data"])[16:20] for b in images}
    assert len(widths) == 2  # 720 (desktop at half size) and 375 (mobile at full size)
    assert renderer.calls[0] == ("render", "/analysis", [])


@needs_node
def test_overflow_render_notes_and_a_failing_renderer_are_reported(tmp_path: Path) -> None:
    wide = FakeRenderer(shot=png("white", (2000, 400)), warnings=["clone frag_x has no CSS"])
    text = _tools(tmp_path / "a", wide).render_page()[0]["text"]
    assert "horizontal overflow: yes" in text and text.endswith(" Render notes: clone frag_x has no CSS.")
    failing = _tools(tmp_path / "b", FakeRenderer(fail_code="render.timeout")).render_page()
    assert failing == ("NOT RENDERED: the page could not be drawn (render.timeout). Validate it and try again; "
                       "if this repeats, say so in your report.")
