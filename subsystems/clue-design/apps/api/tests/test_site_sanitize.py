"""The published-site cleaner (Wave 2 Contract 3): strip, never refuse — the master plan's Review focus 7."""

from __future__ import annotations

from lumen_api.site_sanitize import asset_reference_allowed, sanitize_site_html

DIGEST = "a" * 64


def test_scripts_frames_forms_and_document_elements_go_with_their_content() -> None:
    out = sanitize_site_html(
        '<!doctype html><html><head><title>T</title><meta http-equiv="refresh" content="0;url=https://evil.example">'
        '<link rel="stylesheet" href="https://evil.example/x.css"><base href="https://evil.example/"></head>'
        '<body><p>keep</p><script>steal()</script><iframe src="https://evil.example"></iframe><object data="x"></object>'
        '<embed src="x"><form action="https://evil.example"><input name="q"></form><noscript><img src="https://evil.example/n.gif"></noscript>'
        '<svg><foreignObject><div>x</div></foreignObject><set attributeName="href" to="javascript:alert(1)"/></svg></body></html>'
    )
    lowered = out.html.lower()
    for gone in ("<script", "<iframe", "<object", "<embed", "<form", "<meta", "<link", "<base", "<noscript", "foreignobject", "<set", "evil.example"):
        assert gone not in lowered, gone
    assert "<p>keep</p>" in out.html and "<title>T</title>" in out.html
    assert out.html.startswith("<!DOCTYPE html>")
    assert "stripped <script> and its content" in out.removed


def test_handlers_pings_and_script_links_go_and_real_links_stay() -> None:
    out = sanitize_site_html(
        '<html><body><a href="javascript:steal()" onclick="steal()" ping="https://evil.example/p">x</a>'
        '<a href="https://example.com/cta">cta</a><a href="/acme/analysis">next</a><a href="mailto:a@example.com">m</a>'
        '<a href="java\tscript:alert(1)">t</a><div onmouseover="x()" ONLOAD="y()">d</div></body></html>'
    )
    html = out.html.lower()
    assert 'href="https://example.com/cta"' in html and 'href="/acme/analysis"' in html and 'href="mailto:a@example.com"' in html
    for gone in ("javascript", "onclick", "ping=", "onmouseover", "onload", "java\tscript"):
        assert gone not in html, gone


def test_only_asset_store_site_paths_fragments_and_data_urls_load_bytes() -> None:
    out = sanitize_site_html(
        f'<html><body><img src="/asset-store/{DIGEST}"><img src="https://collector.example/p.gif">'
        '<img src="//cdn.example/x.png"><img src="/\\evil.example/x.png"><img src="data:image/png;base64,iVBOR">'
        f'<video poster="https://evil.example/p.png" src="/asset-store/{DIGEST}"></video>'
        f'<img srcset="/asset-store/{DIGEST} 1x, https://evil.example/2x.png 2x">'
        f'<svg><use href="https://evil.example/sprite.svg#i"></use><use href="#local"></use><image href="/asset-store/{DIGEST}"></image></svg>'
        "</body></html>"
    )
    html = out.html
    assert html.count(f"/asset-store/{DIGEST}") == 4
    for gone in ("collector.example", "cdn.example", "evil.example"):
        assert gone not in html, gone
    assert 'src="data:image/png;base64,iVBOR"' in html and 'href="#local"' in html
    assert f'srcset="/asset-store/{DIGEST} 1x"' in html


def test_css_urls_in_style_elements_and_attributes_are_neutralised() -> None:
    out = sanitize_site_html(
        "<html><head><style>@import url(https://evil.example/x.css);"
        ".a{background:url(https://evil.example/bg.png) no-repeat}"
        f'.b{{background:url("/asset-store/{DIGEST}")}}'
        "@font-face{font-family:X;src:url(https://evil.example/f.woff2)}"
        "@media (min-width:1px){.c{background-image:url(//evil.example/c.png)}}"
        '.d{background:image-set("https://evil.example/i.png" 1x)}</style></head>'
        '<body><div style="background:url(https://evil.example/s.png);color:red">s</div>'
        f'<div style="background:url(/asset-store/{DIGEST})">t</div></body></html>'
    )
    assert "evil.example" not in out.html
    assert out.html.count(f"/asset-store/{DIGEST}") == 2
    assert "color:red" in out.html.replace(" ", "")
    assert "stripped @import" in out.removed


def test_cleaning_twice_changes_nothing() -> None:
    once = sanitize_site_html(f'<html><body><a href="javascript:x()" onclick="y()">a</a><img src="/asset-store/{DIGEST}"></body></html>')
    twice = sanitize_site_html(once.html)
    assert twice.html == once.html and twice.removed == ()


def test_the_reference_rule() -> None:
    for kept in (f"/asset-store/{DIGEST}", "/analysis", "#grad", "data:image/png;base64,x", ""):
        assert asset_reference_allowed(kept), kept
    for refused in ("https://example.com/x.png", "//cdn.example/x.png", "/\\evil.example/x.png", "file:///etc/passwd", "javascript:x()"):
        assert not asset_reference_allowed(refused), refused
