"""CSS variables carrying media must enter the existing bounded asset fetch list."""

from __future__ import annotations

import asyncio
import base64
import socket

import httpx
import pytest
from lumen_ingestion.capture import candidates, net
from lumen_ingestion.capture.candidates import collect_asset_candidates
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.capture.static import _collect_assets
from selectolax.parser import HTMLParser

BASE = "https://example.com/pages/customers"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    async def public_dns(*_):
        return ["93.184.216.34"]

    def deny_network(*_, **__):
        raise AssertionError("This suite only permits MockTransport; no network or DNS")

    monkeypatch.setattr(net, "_resolve_all", public_dns)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)


def _css_candidates(markup="<main></main>", sheets=()):
    return [
        item
        for item in collect_asset_candidates(HTMLParser(markup), BASE, sheets).candidates
        if item.origin == "css-url"
    ]


def test_inline_custom_properties_join_existing_properties_in_source_order():
    found = _css_candidates(
        '<main style="--figure:url(../media/first.svg);mask:url(/mask.svg);'
        '--alternate:url(../media/second.svg);cursor:url(/cursor.svg),auto"></main>'
    )
    assert [(item.url, item.detail) for item in found] == [
        ("https://example.com/media/first.svg", "inline style --figure"),
        ("https://example.com/mask.svg", "inline style mask"),
        ("https://example.com/media/second.svg", "inline style --alternate"),
        ("https://example.com/cursor.svg", "inline style cursor"),
    ]
    assert all(item.kind == "image" for item in found)


def test_stylesheets_use_their_own_base_and_keep_nested_rule_order():
    found = _css_candidates(
        sheets=[
            Stylesheet(
                url="https://cdn.example.com/css/site.css?version=1",
                text=":root{--one:url(../media/one.svg)}"
                "@media screen{@supports (display:grid){.card{--two:url(./two.svg);"
                "mask:url(/mask.svg)}}}"
                ".card{--three:url(three.svg)}",
            ),
            Stylesheet(url="inline:1", text=":root{--four:url(./four.svg)}"),
        ]
    )
    assert [item.url for item in found] == [
        "https://cdn.example.com/media/one.svg",
        "https://cdn.example.com/css/two.svg",
        "https://cdn.example.com/mask.svg",
        "https://cdn.example.com/css/three.svg",
        "https://example.com/pages/four.svg",
    ]


def test_nested_selectors_do_not_hide_following_declarations():
    found = _css_candidates(
        sheets=[
            Stylesheet(
                url="inline:0",
                text="""
            .card {
                --first: url(/first.svg);
                &:hover { --second: url(/second.svg); }
                --third: url(/third.svg);
                mask: url(/mask.svg);
            }
        """,
            )
        ]
    )
    assert [item.url for item in found] == [
        "https://example.com/first.svg",
        "https://example.com/second.svg",
        "https://example.com/third.svg",
        "https://example.com/mask.svg",
    ]


def test_css_tokens_preserve_escapes_semicolons_and_multiple_fallback_urls():
    found = _css_candidates(
        sheets=[
            Stylesheet(
                url="inline:0",
                text=r"""
            .card {
                --picture: URL("/image;{v}.svg?x=1\26 y=2");
                --fallback: var(--missing, url(/image\(2\).svg));
                --layers: image-set(url(/one.svg) 1x, url("/two.svg") 2x);
            }
        """,
            )
        ]
    )
    assert [item.url for item in found] == [
        "https://example.com/image;{v}.svg?x=1&y=2",
        "https://example.com/image(2).svg",
        "https://example.com/one.svg",
        "https://example.com/two.svg",
    ]


def test_custom_property_values_do_not_turn_prose_or_comments_into_requests():
    found = _css_candidates(
        sheets=[
            Stylesheet(
                url="inline:0",
                text="""
            .card {
                /* --ignored: url(/comment.svg); */
                --copy: "url(/prose.svg)";
                --real: url(/real.svg) /* url(/trailing-comment.svg) */;
                color: url(/not-an-asset-property.svg);
            }
        """,
            )
        ]
    )
    assert [item.url for item in found] == ["https://example.com/real.svg"]


def test_custom_data_local_fragments_and_nonfetchable_schemes_match_css_policy():
    found = _css_candidates(
        '<main style="--data:url(data:image/svg+xml;base64,AA==);'
        "--local:url(#shape);--blob:url(blob:example);--script:url(javascript:x);"
        '--external:url(/sprite.svg#shape);mask:url(#mask)"></main>'
    )
    # An external fragment remains in CSS reference identity; this change does not
    # alter the separate acquisition/reference fragment policy.
    assert [item.url for item in found] == ["https://example.com/sprite.svg#shape"]


def test_exact_queries_are_distinct_and_duplicate_url_keeps_first_provenance():
    found = _css_candidates(
        '<main style="--one:url(/image.svg?size=1&amp;v=2);'
        "--repeat:url(/image.svg?size=1&amp;v=2);"
        '--two:url(/image.svg?size=2&amp;v=2)"></main>',
        [Stylesheet(url="inline:0", text=".x{--copy:url(/image.svg?size=1&v=2)}")],
    )
    assert [(item.url, item.detail) for item in found] == [
        ("https://example.com/image.svg?size=1&v=2", "inline style --one"),
        ("https://example.com/image.svg?size=2&v=2", "inline style --two"),
    ]


def test_custom_media_use_existing_count_budget_after_identity_assets(monkeypatch):
    monkeypatch.setattr(candidates, "MAX_ASSET_COUNT", 3)
    harvest = collect_asset_candidates(
        HTMLParser(
            '<img src="/photo.png"><main style="--first:url(/one.svg);'
            '--second:url(/two.svg);--third:url(/three.svg)"></main>'
        ),
        BASE,
        [],
    )
    assert harvest.urls == [
        "https://example.com/favicon.ico",
        "https://example.com/photo.png",
        "https://example.com/one.svg",
    ]
    assert len(harvest.diagnostics) == 1
    assert harvest.diagnostics[0]["code"] == "LUMI0514"
    assert harvest.diagnostics[0]["dropped"] == [
        "https://example.com/two.svg",
        "https://example.com/three.svg",
    ]


def test_custom_media_are_downloaded_and_failed_requests_remain_diagnostic():
    body = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1"/></svg>'
    seen = []

    def respond(request):
        seen.append(str(request.url))
        if request.url.path == "/available.svg":
            return httpx.Response(200, content=body, headers={"content-type": "image/svg+xml"})
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await _collect_assets(
                HTMLParser('<main style="--image:url(/available.svg)"></main>'),
                net.BoundedFetcher(client),
                BASE,
                [Stylesheet(url="inline:0", text=".x{--other:url(/missing.svg)}")],
            )

    downloads, diagnostics = asyncio.run(run())
    assert "https://example.com/available.svg" in seen
    assert "https://example.com/missing.svg" in seen
    assert [(item.url, item.origin) for item in downloads] == [
        ("https://example.com/available.svg", "css-url")
    ]
    assert base64.b64decode(downloads[0].bytes_b64) == body
    assert any(
        item["code"] == "LUMI0503" and "https://example.com/missing.svg" in item["message"]
        for item in diagnostics
    )


def test_escaped_url_function_identifier_is_a_real_custom_media_token():
    found = _css_candidates(
        sheets=[Stylesheet(url="inline:0", text=r".x{--image:u\72l(/escaped.svg)}")]
    )
    assert [item.url for item in found] == ["https://example.com/escaped.svg"]


def test_registered_custom_property_initial_value_is_scoped_to_its_registration():
    found = _css_candidates(
        sheets=[
            Stylesheet(
                url="https://cdn.example.com/css/site.css",
                text="""
            @property --image {
                syntax: "<image>";
                inherits: false;
                initial-value: url(../media/default.svg);
            }
            @media screen {
                @property --alternate { initial-value: url(../media/alternate.svg); }
            }
            .card { initial-value: url(/unrelated.svg); }
            @property invalid { initial-value: url(/not-custom.svg); }
        """,
            )
        ]
    )
    assert [item.url for item in found] == [
        "https://cdn.example.com/media/default.svg",
        "https://cdn.example.com/media/alternate.svg",
    ]


def test_malformed_custom_url_does_not_discard_valid_neighbour():
    found = _css_candidates(
        sheets=[
            Stylesheet(
                url="inline:0",
                text="""
            .card { --broken: url("https://[bad/image.svg"); --valid: url(/valid.svg); }
        """,
            )
        ]
    )
    assert [item.url for item in found] == ["https://example.com/valid.svg"]
