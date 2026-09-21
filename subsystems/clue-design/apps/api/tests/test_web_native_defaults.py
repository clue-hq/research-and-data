"""Source UA defaults survive delivery; native/placeholder styling still applies."""
from pathlib import Path

import pytest
from lumen_api.core import CoreClient
from lumen_api.fragments import build_fragment_artifact
from lumen_api.fragments.isolation import isolation_web_doc
from playwright.sync_api import sync_playwright

SUBSYSTEM = Path(__file__).resolve().parents[3]
HTML = '''<div class="source"><img id="source-image" width="80" height="80" alt="sample">
<div id="source-box">Box</div><h3>Title</h3><button>Action</button></div>'''
CSS = '''.source {font:14px/1.6 Arial,sans-serif;text-align:center}
.source img {width:80px;height:80px}
#source-box {width:100px;padding:20px;border:10px solid black}
#source-box::before {content:"before";width:10px;padding:2px;display:block}'''


def _render(*, missing=False, custom_css=""):
    artifact = build_fragment_artifact(html=HTML, css=CSS, rehosted={})
    doc = isolation_web_doc(artifact.fragment_id)
    # An ordinary authored native class must not claim a clone boundary.
    doc["pages"][0]["nodes"]["sec_isolation"]["classes"] = "lumen-fragment"
    doc["custom_css"] = custom_css
    result = CoreClient(repo_root=SUBSYSTEM).web_render(
        doc, "home", mode="delivery",
        fragments={} if missing else {
            artifact.fragment_id: {"html": artifact.payload["html"], "slot_kinds": {}}
        },
        fragment_css=artifact.payload["css"],
    )
    return result["html"], artifact


def _measure(page):
    return page.evaluate('''() => {
      const s = getComputedStyle(document.querySelector('#source-image'));
      const box = document.querySelector('#source-box');
      return {imageDisplay:s.display,imageMaxWidth:s.maxWidth,
        imageX:document.querySelector('#source-image').getBoundingClientRect().x,
        boxWidth:box.getBoundingClientRect().width,boxSizing:getComputedStyle(box).boxSizing,
        pseudoSizing:getComputedStyle(box,'::before').boxSizing};
    }''')


def test_delivery_preserves_source_browser_defaults():
    html, artifact = _render()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 800, "height": 600})
        page.route("**/*", lambda route: route.abort())
        page.set_content(f'<!doctype html><style>body{{margin:0}}{CSS}</style>{HTML}')
        source = _measure(page)
        page.set_content(html)
        delivered = _measure(page)
        browser.close()
    assert source["imageDisplay"] == "inline"
    assert source["boxWidth"] == 160
    assert delivered == source
    assert artifact.payload["css"] in html  # No rewrite of captured stylesheet.
    assert 'data-fragment-root=' not in html  # Editor instrumentation remains editor-only.


@pytest.mark.parametrize("missing", [False, True])
def test_native_defaults_do_not_confuse_placeholders_or_authored_classes(missing):
    html, _ = _render(missing=missing)
    native = '''<div class="lumen-fragment"><img id="native-image" alt="native">
<p id="native-body" data-tv="body">Native</p></div>'''
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(html.replace("</body>", native + "</body>"))
        result = page.evaluate('''() => ({
          image:getComputedStyle(document.querySelector('#native-image')).display,
          sizing:getComputedStyle(document.querySelector('#native-body')).boxSizing,
          margin:getComputedStyle(document.querySelector('#native-body')).marginTop,
          placeholder:document.querySelector('[data-fragment-placeholder] span')
            ? getComputedStyle(document.querySelector('[data-fragment-placeholder] span')).boxSizing
            : null,
          boundaries:document.querySelectorAll('[data-lumen-fragment="true"]').length
        })''')
        browser.close()
    assert result == {"image":"block", "sizing":"border-box", "margin":"0px",
                      "placeholder":"border-box" if missing else None,
                      "boundaries":0 if missing else 1}


@pytest.mark.parametrize("custom", [
    'img {display:inline;max-width:none}',
    'img {display:inline !important;max-width:none !important}',
])
def test_zero_specificity_guard_keeps_native_equal_specificity_overrides(custom):
    html, _ = _render(custom_css=custom)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(html.replace("</body>", '<img id="native-image" alt="native"></body>'))
        result = page.evaluate('''() => {
          const s=getComputedStyle(document.querySelector('#native-image'));
          return [s.display,s.maxWidth];
        }''')
        browser.close()
    assert result == ["inline", "none"]
