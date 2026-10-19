"""A URL fragment selects within held bytes; it is not another fetch or permission."""

from __future__ import annotations

import hashlib
from html import escape

import pytest
import tinycss2
from lumen_api.fragments import FragmentRefused, sanitize_fragment_html, scope_fragment_css
from lumen_api.fragments.cssscope import rewrite_declaration_urls
from lumen_api.fragments.refs import resolve_asset_reference
from lumen_ingestion.sections.mint import CapturedAsset, build_reference_harvest
from selectolax.lexbor import LexborHTMLParser
from tinycss2.serializer import serialize_string_value

DIGEST = hashlib.sha256(b"held source bytes").hexdigest()
OTHER = hashlib.sha256(b"different source bytes").hexdigest()
BASE = "https://cdn.example.com/media/sprite.svg?v=1&size=2"
RAW = BASE + "#mark"
TARGET = "/asset-store/" + DIGEST


@pytest.mark.parametrize("key", [BASE, RAW, BASE + "#another"])
def test_fragment_alias_lookup_requires_the_same_exact_fetch_identity(key):
    assert resolve_asset_reference(RAW, {key: DIGEST}) == DIGEST


def test_same_bytes_under_multiple_fragment_aliases_are_unambiguous():
    assert resolve_asset_reference(RAW, {BASE: DIGEST, RAW: DIGEST, BASE + "#x": DIGEST}) == DIGEST


@pytest.mark.parametrize(
    "mapping",
    [
        {BASE: OTHER, RAW: DIGEST},
        {BASE: DIGEST, BASE + "#other": OTHER},
        {RAW: DIGEST, BASE + "#other": OTHER},
    ],
)
def test_different_bytes_under_fragment_aliases_refuse_even_with_an_exact_match(mapping):
    with pytest.raises(FragmentRefused) as error:
        resolve_asset_reference(RAW, mapping)
    assert error.value.reference == RAW


@pytest.mark.parametrize(
    "key",
    [
        "https://cdn.example.com/media/sprite.svg?size=2&v=1",
        "https://cdn.example.com/media/sprite.svg?v=2&size=2",
        "https://cdn.example.com/media/sprite.svg",
        "https://cdn.example.com/media/%73prite.svg?v=1&size=2",
    ],
)
def test_query_order_values_and_url_spelling_are_not_conflated(key):
    with pytest.raises(FragmentRefused) as error:
        resolve_asset_reference(RAW, {key: DIGEST})
    assert error.value.code == "fragment.unrehosted_reference"


@pytest.mark.parametrize(
    "markup,selector,attribute",
    [
        ('<svg><use href="{url}"></use></svg>', "use", "href"),
        ('<svg><use xlink:href="{url}"></use></svg>', "use", "xlink:href"),
        ('<video src="{url}"></video>', "video", "src"),
        ('<video><source src="{url}"></video>', "source", "src"),
        ('<video poster="{url}"></video>', "video", "poster"),
    ],
)
def test_html_byte_references_preserve_the_authored_fragment(markup, selector, attribute):
    raw = BASE.replace("sprite.svg", "clip.mp4") + "#t=0.001,3" if attribute == "src" else RAW
    result = sanitize_fragment_html(markup.format(url=escape(raw)), rehosted={raw: DIGEST})
    expected = TARGET + raw[raw.index("#") :]
    assert (
        LexborHTMLParser(result.html).css_first(selector).attributes[attribute.split(":")[-1]]
        == expected
    )
    assert result.asset_digests == (DIGEST,)
    assert sanitize_fragment_html(result.html, rehosted={}) == result


def test_srcset_preserves_a_distinct_fragment_on_each_candidate():
    result = sanitize_fragment_html(
        f'<img srcset="{escape(BASE)}#one 1x, {escape(BASE)}#two 2x">',
        rehosted={BASE + "#one": DIGEST, BASE + "#two": DIGEST},
    )
    assert f"{TARGET}#one 1x, {TARGET}#two 2x" in result.html
    assert result.asset_digests == (DIGEST,)


@pytest.mark.parametrize(
    "value",
    [
        'url("{raw}")',
        "url({raw})",
        'image-set("{raw}" 1x, url("{raw}") 2x)',
    ],
)
def test_css_url_forms_preserve_fragment_and_remain_idempotent(value):
    rewritten, digests = rewrite_declaration_urls(
        "mask-image:" + value.format(raw=RAW), {RAW: DIGEST}
    )
    assert TARGET + "#mark" in rewritten
    assert BASE not in rewritten
    assert digests == (DIGEST,)
    assert rewrite_declaration_urls(rewritten, {}) == (rewritten, digests)
    scoped = scope_fragment_css(
        ".art{" + rewritten + "}", fragment_id="frag_0123456789abcdef", rehosted={}
    )
    assert TARGET + "#mark" in scoped.css


def test_same_document_references_do_not_acquire_or_rewrite_bytes():
    result = sanitize_fragment_html(
        '<svg><use href="#shape"></use></svg><div style="filter:url(\'#filter\')"></div>',
        rehosted={"#shape": OTHER, "#filter": OTHER},
    )
    assert 'href="#shape"' in result.html
    assert "#filter" in result.html
    assert result.asset_digests == ()


def test_asset_scheme_still_needs_its_exact_explicit_custody_mapping():
    raw = "asset://source-id#mark"
    for mapping in ({}, {"asset://source-id": DIGEST}, {"asset://" + DIGEST: DIGEST}):
        with pytest.raises(FragmentRefused):
            resolve_asset_reference(raw, mapping)
    result = sanitize_fragment_html(f'<img src="{raw}">', rehosted={raw: DIGEST})
    assert TARGET + "#mark" in result.html


def test_rewritten_css_suffix_cannot_break_out_of_its_string_or_style_element():
    suffix = '#symbol";color:red;/*\\\n</style><script>x</script>'
    raw = BASE + suffix
    css = 'mask:url("' + serialize_string_value(raw) + '")'
    result, digests = rewrite_declaration_urls(css, {raw: DIGEST})
    assert "</" not in result
    declarations = tinycss2.parse_declaration_list(result, skip_comments=True, skip_whitespace=True)
    assert len(declarations) == 1 and declarations[0].name == "mask"
    function = next(token for token in declarations[0].value if token.type == "function")
    assert function.arguments[0].value == TARGET + suffix
    assert digests == (DIGEST,)


# Parent wires the shared lookup into mint.py after concurrent source-context work releases it.
@pytest.mark.parametrize("stored", [BASE, RAW, BASE + "#previous"])
def test_harvest_uses_captured_fragment_equivalent_bytes_without_losing_raw_key(stored):
    asset = CapturedAsset(stored, b"source", "image/svg+xml")
    harvest = build_reference_harvest(
        subtree_html=f'<svg><use href="{escape(RAW)}"></use></svg>',
        page_url="https://example.com/",
        css_blocks=[],
        captured={stored: asset},
    )
    assert harvest.resolved == {RAW: stored}
    assert harvest.missing == () and harvest.conflicts == ()


def test_harvest_refuses_different_bytes_even_if_exact_capture_exists():
    harvest = build_reference_harvest(
        subtree_html=f'<svg><use href="{escape(RAW)}"></use></svg>',
        page_url="https://example.com/",
        css_blocks=[],
        captured={BASE: CapturedAsset(BASE, b"a"), RAW: CapturedAsset(RAW, b"b")},
    )
    assert harvest.conflicts == (RAW,)
    assert RAW not in harvest.resolved


def test_harvest_fragment_lookup_does_not_cross_query_identity():
    other = BASE.replace("v=1", "v=2")
    harvest = build_reference_harvest(
        subtree_html=f'<video src="{escape(RAW)}"></video>',
        page_url="https://example.com/",
        css_blocks=[],
        captured={other: CapturedAsset(other, b"source")},
    )
    assert harvest.resolved == {} and harvest.missing == (RAW,)


def test_reference_index_checks_each_content_group_once_without_rehashing_payloads():
    from lumen_api.fragments.reference_identity import ReferenceIndex

    class Held:
        data = b"large-video-payload" * 100_000

    reads = []

    def held_bytes(asset):
        reads.append(asset)
        return asset.data

    assets = {BASE + "#one": Held(), BASE + "#two": Held()}
    index = ReferenceIndex(assets, identity=held_bytes)
    for number in range(100):
        assert index.lookup_key(BASE + f"#symbol-{number}") == BASE + "#one"
    assert len(reads) == 2


def test_distinct_query_variant_with_different_bytes_does_not_poison_exact_match():
    assert resolve_asset_reference(RAW, {RAW: DIGEST, RAW.replace("v=1", "v=2"): OTHER}) == DIGEST


def test_missing_fragment_resource_still_refuses_in_html_and_css():
    raw = "https://cdn.example.com/clip.mp4#t=0.001"
    with pytest.raises(FragmentRefused, match="never rehosted"):
        sanitize_fragment_html(f'<video src="{raw}"></video>', rehosted={})
    with pytest.raises(FragmentRefused, match="never rehosted"):
        rewrite_declaration_urls(f'mask:url("{RAW}")', {})
    with pytest.raises(FragmentRefused, match="never rehosted"):
        resolve_asset_reference("asset://" + DIGEST + "#mark", {})


def test_external_svg_symbol_renders_after_base_only_custody_lookup():
    from playwright.sync_api import sync_playwright

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<symbol id="mark" viewBox="0 0 30 20">'
        '<rect width="30" height="20" fill="red"/></symbol></svg>'
    )
    digest = hashlib.sha256(svg.encode()).hexdigest()
    sanitized = sanitize_fragment_html(
        '<svg width="60" height="40"><use href="/sprite.svg#mark" '
        'width="30" height="20"></use></svg>',
        rehosted={"/sprite.svg": digest},
    )
    origin = "https://offline.example"
    requested = []
    unexpected = []

    def serve(route):
        url = route.request.url
        requested.append(url)
        if url == origin + "/fixture":
            route.fulfill(status=200, content_type="text/html", body=sanitized.html)
        elif url == origin + "/asset-store/" + digest:
            route.fulfill(status=200, content_type="image/svg+xml", body=svg)
        else:
            unexpected.append(url)
            route.abort()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block")
            context.route("**/*", serve)
            page = context.new_page()
            page.goto(origin + "/fixture", wait_until="load")
            page.wait_for_function(
                "() => document.querySelector('use').getBBox().width > 0", timeout=3000
            )
            box = page.locator("use").evaluate(
                "node => { const box = node.getBBox(); return [box.width, box.height]; }"
            )
            assert box == [30, 20]
            assert requested == [origin + "/fixture", origin + "/asset-store/" + digest]
            assert unexpected == []
        finally:
            browser.close()
