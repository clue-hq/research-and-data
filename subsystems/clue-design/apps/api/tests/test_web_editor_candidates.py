"""Foreign fragment classes must not become editor-only Tailwind utilities."""

from __future__ import annotations

from pathlib import Path

import pytest
from lumen_api.core import CoreClient
from lumen_api.fragments import build_fragment_artifact
from lumen_api.fragments.isolation import isolation_web_doc
from playwright.sync_api import sync_playwright
from py_lumen_config import settings

SUBSYSTEM = Path(__file__).resolve().parents[3]
WORKTREE = SUBSYSTEM.parents[1]
MARKUP = (
    '<div class="container"><div class="root container responsivegrid">'
    '<section class="hero"><div class="cards"><article class="card">'
    '<h1 id="heading">Choose cloud and AI capabilities for your team</h1>'
    "</article><aside></aside></div></section></div></div>"
)
CSS = """
* {box-sizing:border-box} body {margin:0;font:14px/1.6 Arial,sans-serif}
.hero {width:100%;max-width:1440px;padding:0 120px;margin:0 auto}
.cards {display:grid;grid-template-columns:1fr 1fr;gap:32px}
.card {padding:40px;min-height:336px}
h1 {font:40px/44px Arial,sans-serif;margin:0}
@media(max-width:600px) {
 .hero {padding:0 24px} .cards {grid-template-columns:1fr} .card {padding:24px}
}
"""


def _runtime() -> str:
    paths = (
        SUBSYSTEM / "apps/editor/public/vendor/tailwind-browser.js",
        WORKTREE / "apps/frontend/public/vendor/tailwind-browser.js",
        WORKTREE / "apps/frontend/node_modules/@tailwindcss/browser/dist/index.global.js",
    )
    for path in paths:
        if path.is_file():
            return path.read_text()
    pytest.fail("a local Tailwind browser runtime is required for this regression")


def _real_core(monkeypatch: pytest.MonkeyPatch) -> CoreClient:
    if not settings.lumen_core_helper:
        helpers = (
            SUBSYSTEM / "target/release/lumen-api-helper",
            SUBSYSTEM / "target/debug/lumen-api-helper",
        )
        helper = next((path for path in helpers if path.is_file()), None)
        assert helper is not None, "configure or build an isolated helper before this regression"
        monkeypatch.setattr(settings, "lumen_core_helper", str(helper))
    return CoreClient(repo_root=SUBSYSTEM)


def _render(core: CoreClient, mode: str, *, native_classes: str = "p-7") -> dict:
    artifact = build_fragment_artifact(html=MARKUP, css=CSS, rehosted={})
    doc = isolation_web_doc(artifact.fragment_id)
    nodes = doc["pages"][0]["nodes"]
    nodes["root"]["children"].append("native")
    nodes["native"] = {
        "id": "native",
        "kind": "section",
        "classes": native_classes,
        "anchor_id": "native",
        "children": [],
    }
    return core.web_render(
        doc,
        "home",
        mode=mode,
        fragments={artifact.fragment_id: {"html": artifact.payload["html"], "slot_kinds": {}}},
        fragment_css=artifact.payload["css"],
    )


def _measure(page) -> dict:
    return page.evaluate("""() => {
      const box = s => {const r=document.querySelector(s).getBoundingClientRect();
        return {width:r.width,height:r.height};};
      return {heading:box('#heading'),card:box('.card'),hero:box('.hero'),
        nativePadding:getComputedStyle(document.querySelector('#native')).padding};
    }""")


@pytest.mark.parametrize("width,heading_width,card_width", [(1440, 504, 584), (375, 279, 327)])
def test_editor_preserves_source_container_geometry_and_native_utilities(
    monkeypatch,
    width,
    heading_width,
    card_width,
):
    """Catch runtime scanning a foreign `container` while native p-7 must still compile."""
    core = _real_core(monkeypatch)
    editor = _render(core, "editor")["html"]
    delivery = _render(core, "delivery")["html"]
    source = f'<style>{CSS}</style>{MARKUP}<section id="native"></section>'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.route("**/*", lambda route: route.abort())
        page.set_content(source)
        source_boxes = _measure(page)
        page.set_content(delivery)
        delivered = _measure(page)
        page.set_content(
            editor.replace(
                "</head>",
                f"<script>{_runtime()}</script></head>",
                1,
            )
        )
        page.wait_for_function(
            "getComputedStyle(document.querySelector('#native')).padding === '28px'"
        )
        preview = _measure(page)
        browser.close()
    assert source_boxes["heading"]["width"] == heading_width
    assert source_boxes["card"]["width"] == card_width
    for key in ("heading", "card", "hero"):
        assert delivered[key] == source_boxes[key]
        assert preview[key] == source_boxes[key]
    assert preview["nativePadding"] == "28px"


def _engine_html(fragment: str, *, native: str = "p-7", wrapper: str = "w-full") -> str:
    return (
        '<!doctype html><html><head><style type="text/tailwindcss">@theme {}</style>'
        "<style>/* unchanged artifact sheet */ .foreign {color:red}</style></head><body>"
        f'<section class="{native}"></section>'
        f'<div data-fragment-root="true" class="lumen-fragment {wrapper}">{fragment}</div>'
        "</body></html>"
    )


def _through_core(monkeypatch, html: str, *, mode: str = "editor") -> dict:
    core = CoreClient()
    monkeypatch.setattr(
        core,
        "_run",
        lambda request: {
            "ok": True,
            "html": html,
            "diagnostics": [{"code": "existing"}],
        },
    )
    return core.web_render({}, "home", mode=mode)


def _directives(html: str) -> str:
    return html.split('<style type="text/tailwindcss">', 1)[1].split("</style>", 1)[0]


def test_exclusion_is_deterministic_and_only_changes_compiler_input(monkeypatch):
    html = _engine_html('<img class="container p-7 w-full"><div class="zeta alpha"></div>')
    result = _through_core(monkeypatch, html)
    assert '@source not inline("alpha container zeta");' in _directives(result["html"])
    insertion = result["html"].replace(html.split("@theme", 1)[0], "", 1).split("@theme", 1)[0]
    assert result["html"].replace(insertion, "", 1) == html
    assert result["diagnostics"][0] == {"code": "existing"}
    assert any(d["code"] == "fragment.editor_shared_candidates" for d in result["diagnostics"])


def test_delivery_and_pages_without_fragments_remain_byte_identical(monkeypatch):
    html = _engine_html('<div class="container"></div>')
    assert _through_core(monkeypatch, html, mode="delivery")["html"] == html
    ordinary = html.replace('data-fragment-root="true"', 'data-ordinary="true"')
    assert _through_core(monkeypatch, ordinary)["html"] == ordinary


@pytest.mark.parametrize(
    "token",
    [
        "x&quot;y",
        "x&#39;y",
        "x\\y",
        "p-{1..999999999}",
        "&lt;/style&gt;&lt;script&gt;alert(1)&lt;/script&gt;",
        "a&#x7f;b",
    ],
)
def test_unsafe_tokens_never_enter_the_compiler_directive(monkeypatch, token):
    html = _engine_html(f'<div class="container {token}"></div>')
    result = _through_core(monkeypatch, html)
    directive = _directives(result["html"])
    assert '@source not inline("container");' in directive
    assert "<script>" not in directive and "{1.." not in directive
    assert any(d["code"] == "fragment.editor_candidate_skipped" for d in result["diagnostics"])
    assert html.split("</head>", 1)[1] == result["html"].split("</head>", 1)[1]


def test_non_ascii_whitespace_does_not_split_a_browser_class_token(monkeypatch):
    html = _engine_html('<div class="p-7&#160;container safe"></div>', native="")
    result = _through_core(monkeypatch, html)
    assert '@source not inline("safe");' in _directives(result["html"])
    assert any(d["code"] == "fragment.editor_candidate_skipped" for d in result["diagnostics"])


def test_ambiguous_or_missing_compiler_block_is_reported_without_rewriting(monkeypatch):
    html = _engine_html('<div class="container"></div>')
    for malformed in (
        html.replace('<style type="text/tailwindcss">', "<style>"),
        html.replace("</head>", '<style type="text/tailwindcss"></style></head>'),
    ):
        result = _through_core(monkeypatch, malformed)
        assert result["html"] == malformed
        assert any(d["code"] == "fragment.editor_candidate_block" for d in result["diagnostics"])


def test_native_shared_container_is_still_generated(monkeypatch):
    core = _real_core(monkeypatch)
    response = _render(core, "editor", native_classes="container p-7")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/*", lambda route: route.abort())
        page.set_content(
            response["html"].replace(
                "</head>",
                f"<script>{_runtime()}</script></head>",
                1,
            )
        )
        page.wait_for_function(
            "getComputedStyle(document.querySelector('#native')).padding==='28px'"
        )
        assert page.eval_on_selector("#native", "e=>getComputedStyle(e).maxWidth") == "1280px"
        browser.close()
    assert any(d["code"] == "fragment.editor_shared_candidates" for d in response["diagnostics"])


@pytest.mark.parametrize(
    "tokens",
    [
        [f"class-{i:05d}" for i in range(5000)],
        [f"class-{i:04d}-" + "x" * 180 for i in range(2000)],
    ],
)
def test_large_candidate_sets_are_bounded_and_partial_isolation_is_named(monkeypatch, tokens):
    html = _engine_html('<div class="' + " ".join(tokens) + '"></div>')
    result = _through_core(monkeypatch, html)
    directives = _directives(result["html"])
    assert len(directives.encode()) <= 128 * 1024 + len("@theme {}")
    assert len(directives.split()) < len(tokens)
    assert any(d["code"] == "fragment.editor_candidate_limited" for d in result["diagnostics"])


def test_oversized_render_is_not_partially_scanned(monkeypatch):
    html = _engine_html('<div class="container">' + "x" * (17 * 1024 * 1024) + "</div>")
    result = _through_core(monkeypatch, html)
    assert result["html"] == html
    assert any(d["code"] == "fragment.editor_candidate_limited" for d in result["diagnostics"])


def test_hostile_class_strings_cannot_escape_or_expand_compiler_input(monkeypatch):
    fragment = (
        '<div id="foreign" class="container p-{1..999999999} '
        "x&quot;);&lt;/style&gt;&lt;script&gt;window.__injected=1;&lt;/script&gt; "
        'x&#39;y x\\y"></div>'
    )
    response = _through_core(monkeypatch, _engine_html(fragment))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda route: route.abort())
        page.set_content(
            response["html"].replace(
                "</head>",
                f"<script>{_runtime()}</script></head>",
                1,
            )
        )
        page.wait_for_function(
            "getComputedStyle(document.querySelector('section')).padding==='28px'"
        )
        assert page.eval_on_selector("#foreign", "e=>getComputedStyle(e).maxWidth") == "none"
        assert page.evaluate("window.__injected") is None
        assert errors == []
        browser.close()


def test_inert_template_classes_do_not_suppress_foreign_exclusion(monkeypatch):
    html = _engine_html('<div class="container"></div>')
    html = html.replace("</body>", '<template><div class="container"></div></template></body>')
    result = _through_core(monkeypatch, html)
    assert '@source not inline("container");' in _directives(result["html"])


def test_scan_node_limit_cannot_hide_a_later_native_use(monkeypatch):
    from lumen_api.fragments import editor_candidates

    monkeypatch.setattr(editor_candidates, "MAX_SCAN_NODES", 4)
    html = _engine_html('<div class="container"></div>', native="")
    html = html.replace("</body>", '<div class="container"></div></body>')
    result = _through_core(monkeypatch, html)
    assert result["html"] == html
    assert any(d["code"] == "fragment.editor_candidate_limited" for d in result["diagnostics"])


def test_distinct_token_limit_cannot_hide_a_later_native_use(monkeypatch):
    from lumen_api.fragments import editor_candidates

    monkeypatch.setattr(editor_candidates, "MAX_DISTINCT_TOKENS", 4)
    html = _engine_html('<div class="alpha beta container"></div>')
    html = html.replace("</body>", '<div class="container"></div></body>')
    result = _through_core(monkeypatch, html)
    assert result["html"] == html
    assert any(d["code"] == "fragment.editor_candidate_limited" for d in result["diagnostics"])


def test_large_stylesheet_does_not_prevent_bounded_body_candidate_scan(monkeypatch):
    html = _engine_html('<div class="container"></div>')
    html = html.replace("</head>", "<style>/*" + "x" * (17 * 1024 * 1024) + "*/</style></head>")
    response = _through_core(monkeypatch, html)
    assert '@source not inline("container");' in _directives(response["html"])
    assert html.split("</style>", 1)[1] == response["html"].split("</style>", 1)[1]
