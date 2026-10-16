"""lumen_api.site_turn_ports: the site turn's capabilities (Lane B Tasks 9, 10, 12, 15)."""

from __future__ import annotations

import base64
import hashlib
import io
import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

import lumen_api
from conftest import make_blob_store
from lumen_agent.site.inputs import SiteSection
from lumen_api.asset_custody import write_cache_blob
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.site_turn_ports import (
    SCHEMA_UNREADABLE,
    DurableSiteAssetPort,
    DurableSiteSectionPort,
    DurableSiteVersionPort,
    PlatformSiteRenderer,
    SiteAssetError,
    SiteRenderPortError,
)
from lumen_api.toolbelt.site_sections import SiteSectionRefused


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

    def render_site(site, brand, sections, *, base_path, routes=None, live=False, timeout_s=20.0):
        assert live is False
        calls.append(("render_site", base_path, routes, [s.name for s in sections]))
        return SiteRender(pages=[RenderedPage(route=r, html=f"<main>{r}</main>") for r in routes or ["/"]], css="b{}", warnings=["w"])

    def capture_site_screenshot(page, css, *, width, full_page=True, clip_selector=None, live_document=None):
        assert live_document is None
        calls.append(("capture", page.html, css, width, full_page, clip_selector))
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
    assert calls == [("render_site", "", ["/analysis"], ["StepsBand"]), ("capture", "<main/>", "b{}", 375, True, None)]


def test_a_section_only_screenshot_is_cut_to_the_brand_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """view_clone and compare_section draw one section alone on a shell-less scratch site: its
    picture is an element shot of site-kit's .brand-root, not the page padded to the viewport."""

    calls: list = []
    _fake_site_render(monkeypatch, calls)
    renderer = PlatformSiteRenderer()
    renderer.screenshot("<main/>", "b{}", width=1440, section_only=True)
    renderer.screenshot("<main/>", "b{}", width=375)
    assert [call[5] for call in calls] == [".brand-root", None]


def test_a_real_section_only_shot_is_the_section_and_a_full_page_shot_fills_the_viewport() -> None:
    """Lane A's real renderer and Chromium: one CtaBand on the Garner brand with no shell."""

    from io import BytesIO

    from PIL import Image

    from site_kit_support import chromium_available, ensure_site_kit_dist, garner_brand

    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    site = {"id": "doc_scratch", "title": "scratch", "theme": {}, "shell": None, "agent_sections": {},
            "pages": {"/": {"root": {"props": {"title": "scratch"}}, "content": [{"type": "CtaBand", "props": {
                "id": "c", "surface": "brand", "heading": "Hello", "buttonLabel": "Book a demo",
                "buttonHref": "https://seller.example/demo"}}]}}}
    renderer = PlatformSiteRenderer()
    html, css, _warnings = renderer.render(site, garner_brand(), [], route="/")
    section = Image.open(BytesIO(renderer.screenshot(html, css, width=1440, section_only=True)))
    page = Image.open(BytesIO(renderer.screenshot(html, css, width=1440)))
    assert 0 < section.height < 900 and section.width <= 1440
    assert page.height >= 900


def test_the_screenshot_gets_images_and_fonts_inlined_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lane A's screenshot runs with the network blocked, so /asset-store/ references become data:
    URIs before it (contract conflict 7)."""

    calls: list = []
    _fake_site_render(monkeypatch, calls)
    digest = "a" * 64
    renderer = PlatformSiteRenderer(read_blob=lambda d: ("image/png", b"\x89PNG"))
    renderer.screenshot(f'<img src="/asset-store/{digest}">', f"@font-face{{src:url(/asset-store/{digest})}}", width=1440)
    (_, html, css, width, _, _) = calls[-1]
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


def test_a_live_renderer_shows_the_page_after_its_effects_ran() -> None:
    """Publishing live sites, Task 11: in a live workspace the agent's screenshot is the page after
    it has come alive (JavaScript on, network still blocked), so an effect's result is in the PNG."""

    from site_kit_support import chromium_available, ensure_site_kit_dist, garner_brand, site_with_agent_section

    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    # A hand-written compiled module that never passes the section check, so an inline style is fine:
    # it paints a tall black block only once its effect has run in the browser.
    module_js = (
        'import { jsx } from "react/jsx-runtime";\nimport { useEffect, useState } from "react";\nimport { z } from "zod";\n'
        'export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n'
        'function Late() { const [on, setOn] = useState(false); useEffect(() => setOn(true), []);\n'
        '  return jsx("div", { style: { height: 600, background: on ? "#000" : "#fff" } }); }\n'
        'export function render() { return jsx(Late, {}); }\n'
    )
    site, sections = site_with_agent_section("Late", module_js)
    live = PlatformSiteRenderer(live=True)
    html, css, _warnings = live.render(site, garner_brand(), sections, route="/")
    dark_live = _dark_share(live.screenshot(html, css, width=1440))
    still = PlatformSiteRenderer(live=False)
    html_s, css_s, _ = still.render(site, garner_brand(), sections, route="/")
    dark_static = _dark_share(still.screenshot(html_s, css_s, width=1440))
    assert dark_live > dark_static + 0.02, (dark_live, dark_static)


def test_a_live_screenshot_of_a_page_with_two_different_agent_sections_is_drawn() -> None:
    """The live preview page forbids eval. A screenshot wait written as a bare expression is run
    through eval and fails whenever the page has not come alive by Playwright's first check — which
    two different section modules (imported one after the other) make certain. The agent then got
    NOT RENDERED for every such page (lane run run_site_590eb594523c, 2026-10-16: 10 of 16 renders).
    The wait is a function, so a page with two sections is shot like any other."""

    from site_kit_support import chromium_available, ensure_site_kit_dist, garner_brand, garner_site

    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    from lumen_api.site_render import SectionModule

    def module(name: str, text: str) -> SectionModule:
        js = (
            'import { jsx } from "react/jsx-runtime";\nimport { useEffect, useState } from "react";\nimport { z } from "zod";\n'
            'export const schema = z.object({ id: z.string(), surface: z.string() }).strict();\n'
            f'function {name}() {{ const [on, setOn] = useState(false); useEffect(() => setOn(true), []);\n'
            f'  return jsx("p", {{ children: on ? "{text} alive" : "{text}" }}); }}\n'
            f'export function render() {{ return jsx({name}, {{}}); }}\n'
        )
        return SectionModule(name=name, digest=hashlib.sha256(js.encode("utf-8")).hexdigest(), module_js=js, css="", props_schema={})

    first, second = module("Quote", "quote"), module("Faq", "faq")
    site = garner_site("doc_two_sections")
    site["pages"]["/"]["content"] += [
        {"type": "Quote", "props": {"id": "quote", "surface": "page"}},
        {"type": "Faq", "props": {"id": "faq", "surface": "page"}},
    ]
    site["agent_sections"] = {"Quote": first.digest, "Faq": second.digest}
    live = PlatformSiteRenderer(live=True)
    html, css, _warnings = live.render(site, garner_brand(), [first, second], route="/")
    for _ in range(3):
        png = live.screenshot(html, css, width=1440)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def _dark_share(png: bytes) -> float:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("L")
    pixels = list(image.getdata())
    return sum(1 for p in pixels if p < 20) / len(pixels)


def test_the_live_preview_is_one_self_contained_document() -> None:
    """The preview carries its own CSP, the CSS inline, and the shims, the sections and the runtime
    as data: modules. The runtime is never inlined: its text could end an inline script early."""

    from lumen_api.site_live import LiveRuntime, live_preview_document
    from lumen_api.site_render import RenderedPage as Page, SectionModule as Module

    runtime = LiveRuntime(runtime_js=b'console.log("</script>"); window.__clueHydrated = true;',
                          shims={"react": b"export default 1;", "react/jsx-runtime": b"export {};", "zod": b"export {};"})
    page = Page(route="/", html='<html><head><title>t</title></head><body><div id="clue-site"></div></body></html>',
                data={"route": "/"})
    module = Module(name="Late", digest="a" * 64, module_js="export const x = 1;", css="", props_schema={})
    document = live_preview_document(page, "b{color:red}", [module], runtime)
    assert '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\' data:;' in document
    assert document.index("Content-Security-Policy") < document.index('<script type="importmap">')
    assert "b{color:red}" in document and "data:text/javascript;charset=utf-8,export%20default%201%3B" in document
    assert '"Late":"data:text/javascript;charset=utf-8,export%20const%20x%20%3D%201%3B"' in document
    runtime_text = runtime.runtime_js.decode("utf-8")
    assert runtime_text[:200] not in document and "<\\/script>" not in document
    assert '<script type="module" src="data:text/javascript;charset=utf-8,console.log%28%22%3C/script%3E%22%29' in document
    assert document.count("</script>") == 3  # import map, page data, runtime


class FakeCore:
    """The engine's ingest, minus the engine: writes the cache blob and returns a record."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    def ingest_asset(self, *, store_root, bytes_base64, asset_id, label, declared_mime_type, kind, license,
                     provenance, source, raise_on_error):
        if not self.ok:
            return {"ok": False, "error": {"message": "not an image"}}
        data = base64.b64decode(bytes_base64)
        digest = hashlib.sha256(data).hexdigest()
        write_cache_blob(store_root, digest, data)
        return {"ok": True, "asset": {"record": {
            "id": asset_id, "kind": kind, "label": label, "status": "ready", "source": source, "provenance": provenance,
            "media": {"mime_type": declared_mime_type, "digest": {"algorithm": "sha256", "value": digest},
                      "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest[:2]}/{digest}"}}}}}


class RecordingInvocations:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def invoke(self, name, body, *, workspace_id, actor, actor_id=None):
        self.calls.append((name, body, workspace_id, actor, actor_id))


def test_a_generated_image_becomes_durable_bytes_and_an_ai_generated_library_row(tmp_path, design_storage) -> None:
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    invocations = RecordingInvocations()
    port = DurableSiteAssetPort(blobs=blobs, cache_dir=tmp_path / "cache", core=FakeCore(),
                                invocations=invocations, run_id="run_site_1")
    image = b"\x89PNG\r\n\x1a\nfake image"
    stored = port.register_generated(image_bytes=image, mime_type="image/png", prompt="A calm classroom",
                                     model="m", license=None, provenance={"source": "test"})
    digest = hashlib.sha256(image).hexdigest()
    assert stored["digest"] == digest and stored["file"] == f"/asset-store/{digest}"
    assert stored["asset_id"].startswith("asset_gen_")
    assert port.read(digest) == ("image/png", image) and port.exists(digest) and not port.exists("0" * 64)
    [(name, body, workspace_id, actor, actor_id)] = invocations.calls
    assert (name, workspace_id, actor, actor_id) == ("design_register_asset_record", blobs.workspace_id, "agent", "run_site_1")
    assert body["record"]["source"]["kind"] == "generated" and body["record"]["label"] == "A calm classroom"
    assert body["record"]["media"]["location"]["provider"] == "clue-storage"


def test_an_image_the_engine_refuses_is_a_typed_error(tmp_path, design_storage) -> None:
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    port = DurableSiteAssetPort(blobs=blobs, cache_dir=tmp_path / "cache", core=FakeCore(ok=False),
                                invocations=RecordingInvocations(), run_id="run_site_1")
    with pytest.raises(SiteAssetError) as refused:
        port.register_generated(image_bytes=b"x", mime_type="image/png", prompt="p", model=None, license=None, provenance={})
    assert refused.value.code == "site_asset.ingest_failed"


def test_reading_a_digest_the_workspace_lacks_is_not_found(tmp_path, design_storage) -> None:
    """The renderer's image inlining leaves a NotFoundError digest broken; any other error would
    fail the whole render (Task 9's PlatformSiteRenderer reads blobs through this port)."""

    from lumen_api.database import NotFoundError

    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    port = DurableSiteAssetPort(blobs=blobs, cache_dir=tmp_path / "cache", core=FakeCore(),
                                invocations=RecordingInvocations(), run_id="run_site_1")
    with pytest.raises(NotFoundError):
        port.read("0" * 64)


def _site(doc_id: str, heading: str) -> dict:
    return {"id": doc_id, "title": "S", "theme": {}, "shell": None, "agent_sections": {},
            "pages": {"/": {"root": {"props": {"title": "S"}}, "content": [{"type": "CtaBand", "props": {"id": "c", "heading": heading}}]}}}


def test_saved_versions_are_read_from_the_documents_history() -> None:
    store = HybridRepository()
    doc_id = f"doc_site_{uuid4().hex[:10]}"
    born = store.create_document(_site(doc_id, "v0"), doc_kind="site")
    previous = born["scene"]
    # design_op_source has no "human": a person's save is sourced from the editor.
    for heading, actor, source in (("v1", "agent", "agent"), ("v2", "human", "editor")):
        new = _site(doc_id, heading)
        store.update_site_document(doc_id, new, intent=f"make {heading}", checkpoint_label=None,
                                   operations=[{"kind": "replace_site", "site": new}],
                                   inverse_operations=[{"kind": "replace_site", "site": previous}],
                                   actor_kind=actor, source=source)
        previous = new
    port = DurableSiteVersionPort(store, doc_id)
    assert [(v["version"], v["actor"], v["intent"]) for v in port.list_versions(10)] == [
        (2, "human", "make v2"), (1, "agent", "make v1")]
    assert port.site_at(1)["pages"]["/"]["content"][0]["props"]["heading"] == "v1"
    assert port.site_at(9) is None


SECTION_SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


class _SectionStore:
    workspace_id = "ws_sections"

    def get_site_sections(self, digests):
        return [{"digest": d, "name": "StepsBand", "props_schema": SECTION_SCHEMA} for d in digests]


class _SectionInvocations:
    def __init__(self, refuse: bool = False) -> None:
        self.calls: list[tuple] = []
        self.refuse = refuse

    def invoke(self, name, body, *, workspace_id, actor, actor_id=None):
        self.calls.append((name, body, workspace_id, actor, actor_id))
        if self.refuse:
            raise SiteSectionRefused("render.failed", "the props need \"surface\"")
        return SimpleNamespace(references={"digest": "d" * 64, "name": body["name"]})


def _compiled(monkeypatch: pytest.MonkeyPatch, answer: dict) -> list:
    from lumen_api import site_turn_ports

    seen: list = []
    monkeypatch.setattr(site_turn_ports, "compile_section_source", lambda **kw: seen.append(kw) or answer)
    monkeypatch.setattr(
        site_turn_ports, "compile_tailwind_css",
        lambda html, input_css, node_bin, timeout_seconds=120: f"/* {input_css.splitlines()[0]} */.px-6{{}}",
    )
    return seen


def test_the_section_port_compiles_records_and_answers_with_the_section(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _compiled(monkeypatch, {"ok": True, "name": "StepsBand", "moduleJs": "export {};", "tailwindTheme": "@theme inline {}"})
    invocations = _SectionInvocations()
    port = DurableSiteSectionPort(store=_SectionStore(), invocations=invocations, run_id="run_s1", brand={"assets": {}})
    answer = port.compile(name="StepsBand", source="SRC")
    assert answer["ok"] is True
    section = answer["section"]
    assert (section.name, section.digest, section.props_schema) == ("StepsBand", "d" * 64, SECTION_SCHEMA)
    assert section.module_js == "export {};" and section.css == '/* @import "tailwindcss"; */.px-6{}'
    assert seen == [{"name": "StepsBand", "source": "SRC", "brand": {"assets": {}}, "interactive": False}]
    assert invocations.calls == [(
        "design_record_site_section",
        {"name": "StepsBand", "source": "SRC", "module_js": "export {};", "css": '/* @import "tailwindcss"; */.px-6{}'},
        "ws_sections", "agent", "run_s1",
    )]


def test_a_live_workspace_compiles_its_sections_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _compiled(monkeypatch, {"ok": False, "name": "StepsBand", "errors": ["x"]})
    port = DurableSiteSectionPort(store=_SectionStore(), invocations=_SectionInvocations(), run_id="r", brand={}, interactive=True)
    port.compile(name="StepsBand", source="SRC")
    assert seen == [{"name": "StepsBand", "source": "SRC", "brand": {}, "interactive": True}]


def test_check_errors_pass_through_and_nothing_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    _compiled(monkeypatch, {"ok": False, "name": "StepsBand", "errors": ["type error: (3,7): bad"]})
    invocations = _SectionInvocations()
    port = DurableSiteSectionPort(store=_SectionStore(), invocations=invocations, run_id="r", brand={})
    assert port.compile(name="StepsBand", source="SRC") == {"ok": False, "errors": ["type error: (3,7): bad"]}
    assert invocations.calls == []


def test_a_schema_the_render_page_cannot_read_is_one_error_to_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    _compiled(monkeypatch, {"ok": True, "name": "StepsBand", "moduleJs": "export {};", "tailwindTheme": ""})
    port = DurableSiteSectionPort(store=_SectionStore(), invocations=_SectionInvocations(refuse=True), run_id="r", brand={})
    assert port.compile(name="StepsBand", source="SRC") == {
        "ok": False,
        "errors": [SCHEMA_UNREADABLE.format(code="render.failed", message='the props need "surface"')],
    }
