"""lumen_api.site_turn_ports: the site turn's capabilities (Lane B Tasks 9, 10, 12, 15)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType

import pytest

import lumen_api
from lumen_agent.site.inputs import SiteSection
from lumen_api.site_turn_ports import PlatformSiteRenderer, SiteRenderPortError


@dataclass
class RenderedPage:
    route: str
    html: str


@dataclass
class SectionModule:
    name: str
    digest: str
    module_js: str
    css: str
    props_schema: dict


@dataclass
class SiteRender:
    pages: list
    css: str
    warnings: list = field(default_factory=list)


def _fake_site_render(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    module = ModuleType("lumen_api.site_render")
    module.RenderedPage = RenderedPage
    module.SectionModule = SectionModule

    def render_site(site, brand, sections, *, base_path, routes=None, timeout_s=20.0):
        calls.append(("render_site", base_path, routes, [s.name for s in sections]))
        return SiteRender(pages=[RenderedPage(route=r, html=f"<main>{r}</main>") for r in routes or ["/"]], css="b{}", warnings=["w"])

    def capture_site_screenshot(page, css, *, width, full_page=True):
        calls.append(("capture", page.html, css, width, full_page))
        return b"png"

    module.render_site = render_site
    module.capture_site_screenshot = capture_site_screenshot
    monkeypatch.setitem(sys.modules, "lumen_api.site_render", module)
    monkeypatch.setattr(lumen_api, "site_render", module, raising=False)


def test_the_renderer_port_drives_lane_as_render_and_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _fake_site_render(monkeypatch, calls)
    section = SiteSection(name="StepsBand", digest="a" * 64, props_schema={}, module_js="export {}", css=".s{}")
    renderer = PlatformSiteRenderer()
    assert renderer.render({"pages": {}}, {"assets": {}}, [section], route="/analysis") == ("<main>/analysis</main>", "b{}", ["w"])
    assert renderer.screenshot("<main/>", "b{}", width=375) == b"png"
    assert calls == [("render_site", "", ["/analysis"], ["StepsBand"]), ("capture", "<main/>", "b{}", 375, True)]


def test_the_screenshot_gets_images_and_fonts_inlined_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lane A's screenshot runs with the network blocked, so /asset-store/ references become data:
    URIs before it (contract conflict 7)."""

    calls: list = []
    _fake_site_render(monkeypatch, calls)
    digest = "a" * 64
    renderer = PlatformSiteRenderer(read_blob=lambda d: ("image/png", b"\x89PNG"))
    renderer.screenshot(f'<img src="/asset-store/{digest}">', f"@font-face{{src:url(/asset-store/{digest})}}", width=1440)
    (_, html, css, width, _) = calls[-1]
    assert "/asset-store/" not in html and "data:image/png;base64," in html
    assert "/asset-store/" not in css and width == 1440


def test_a_route_the_renderer_did_not_return_is_a_typed_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _fake_site_render(monkeypatch, calls)
    module = sys.modules["lumen_api.site_render"]
    module.render_site = lambda *a, **k: SiteRender(pages=[], css="")
    with pytest.raises(SiteRenderPortError) as refused:
        PlatformSiteRenderer().render({}, {}, [], route="/")
    assert refused.value.code == "render.failed"
