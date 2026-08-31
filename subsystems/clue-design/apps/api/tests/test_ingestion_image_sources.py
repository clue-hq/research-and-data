"""Highest-quality image-source selection (founder order, 2026-08-20).

Website ingestion used to enqueue exactly ``<img src>`` and cap the harvest at 12, so a
brand on an image CDN handed us its *thumbnail*: the live Stripe kit stored thirteen
296px-wide renditions because every ``src`` carried ``?w=296``, while the one URL with no
width param came back 2048x1024. These assets are reused directly in generated microsites
and later as reference images for the image-generation tool, so the thumbnail is not a
cosmetic loss.

The coupling this file exists to pin: ``capture.static._collect_assets`` decides which URLs
are DOWNLOADED and ``capture.parse._parse_images`` looks bytes up BY URL. If the two ever
disagree about which URL represents an ``<img>``, every image loses its bytes and the kit
ends up with zero images (``evidence_builder.queue`` drops an asset with no sha). Both sides
therefore walk ONE shared ladder — :func:`lumen_ingestion.capture.imgsrc.image_source_ladder`.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import httpx
import pytest
from selectolax.parser import HTMLParser

from lumen_ingestion.capture import CaptureOutcome, capture_website
from lumen_ingestion.capture.budget import MAX_ASSET_COUNT
from lumen_ingestion.capture.imgsrc import (
    MAX_CANDIDATES_PER_IMAGE,
    TARGET_IMAGE_WIDTH,
    background_image_urls,
    image_source_ladder,
    upgrade_width_params,
)
from lumen_ingestion.capture.parse import parse_site
from lumen_ingestion.capture.snapshot import SiteSnapshot, load_snapshot

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "snapshots"

BASE = "https://example.com/page/"

# 1x1 PNG — every mock asset response body.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _noop(stage: str, progress: float) -> None:
    return None


def _img(html: str):
    tree = HTMLParser(html)
    node = tree.css_first("img")
    assert node is not None
    return node


def _ladder(html: str) -> list[str]:
    return image_source_ladder(_img(html), BASE)


# --------------------------------------------------------------------------- #
# The ladder itself
# --------------------------------------------------------------------------- #


def test_plain_src_behaves_exactly_as_today() -> None:
    """No srcset, no width param → the ladder is the single URL the old code enqueued."""
    assert _ladder('<img src="/media/hero.png">') == ["https://example.com/media/hero.png"]


def test_widest_w_descriptor_wins_over_the_bare_src() -> None:
    ladder = _ladder(
        '<img src="/i/small.png" '
        'srcset="/i/small.png 400w, /i/large.png 1600w, /i/mid.png 800w">'
    )
    assert ladder[0] == "https://example.com/i/large.png"
    # the bare src is ALWAYS the last rung: we can never do worse than today
    assert ladder[-1] == "https://example.com/i/small.png"


def test_x_descriptor_srcset_takes_the_highest_density() -> None:
    ladder = _ladder('<img src="/i/1x.png" srcset="/i/2x.png 2x, /i/3x.png 3x, /i/1x.png 1x">')
    assert ladder[0] == "https://example.com/i/3x.png"
    assert ladder[-1] == "https://example.com/i/1x.png"


def test_picture_source_candidates_are_considered() -> None:
    ladder = _ladder(
        "<picture>"
        '<source srcset="/i/wide-2400.avif 2400w, /i/wide-800.avif 800w" type="image/avif">'
        '<img src="/i/fallback.png">'
        "</picture>"
    )
    assert ladder[0] == "https://example.com/i/wide-2400.avif"
    assert ladder[-1] == "https://example.com/i/fallback.png"


def test_cdn_width_param_upgrade_preserves_every_other_param() -> None:
    """The live Stripe shape: ``?w=296&q=90`` is a thumbnail request, not a thumbnail asset."""
    upgraded = upgrade_width_params(
        "https://images.stripeassets.com/a/b/platform-graphic-background_2x.png?w=296&q=90"
    )
    assert upgraded == (
        "https://images.stripeassets.com/a/b/platform-graphic-background_2x.png"
        f"?w={TARGET_IMAGE_WIDTH}&q=90"
    )


def test_cdn_width_upgrade_scales_an_explicit_height_with_it() -> None:
    upgraded = upgrade_width_params("https://cdn.example.com/x.jpg?width=512&height=256&fit=crop")
    assert upgraded == (
        f"https://cdn.example.com/x.jpg?width={TARGET_IMAGE_WIDTH}"
        f"&height={TARGET_IMAGE_WIDTH // 2}&fit=crop"
    )


def test_cdn_width_upgrade_never_downgrades_or_invents_a_param() -> None:
    assert upgrade_width_params("https://cdn.example.com/x.jpg?w=4000") is None
    assert upgrade_width_params("https://cdn.example.com/x.jpg?q=80") is None
    assert upgrade_width_params("https://cdn.example.com/x.jpg") is None


def test_the_upgraded_url_leads_the_ladder_and_the_thumbnail_still_backs_it() -> None:
    ladder = _ladder('<img src="https://images.example.com/hero.png?w=296&q=90">')
    assert ladder == [
        f"https://images.example.com/hero.png?w={TARGET_IMAGE_WIDTH}&q=90",
        "https://images.example.com/hero.png?w=296&q=90",
    ]


def test_the_ladder_is_bounded_and_deduped() -> None:
    ladder = _ladder(
        '<img src="/i/a.png?w=100" srcset="/i/a.png?w=100 100w, /i/b.png?w=200 200w, '
        '/i/c.png?w=300 300w, /i/d.png?w=400 400w">'
    )
    assert len(ladder) == len(set(ladder))
    assert len(ladder) <= MAX_CANDIDATES_PER_IMAGE
    assert ladder[-1] == "https://example.com/i/a.png?w=100"


# --------------------------------------------------------------------------- #
# CSS background-image
# --------------------------------------------------------------------------- #


def test_background_images_come_from_inline_style_and_stylesheets_but_not_font_faces() -> None:
    from lumen_ingestion.capture.snapshot import Stylesheet

    tree = HTMLParser(
        '<html><body><div style="background-image:url(\'/bg/inline-gradient.png\')"></div>'
        "</body></html>"
    )
    sheets = [
        Stylesheet(
            url="https://example.com/assets/site.css",
            text=(
                "@font-face{font-family:Brand;src:url(brand.woff2) format('woff2')}"
                ".hero{background-image:url(../bg/hero-art.png)}"
                ".card{background:#fff url(\"/bg/card.svg\") no-repeat}"
                ".grad{background-image:linear-gradient(#000,#fff)}"
                ".inlined{background-image:url(data:image/png;base64,AAAA)}"
            ),
        )
    ]
    urls = background_image_urls(tree, sheets, BASE)
    assert "https://example.com/bg/inline-gradient.png" in urls
    assert "https://example.com/bg/hero-art.png" in urls  # resolved against the SHEET url
    assert "https://example.com/bg/card.svg" in urls
    # @font-face is the font path's business, and a data: URI has no bytes to fetch
    assert not any(u.endswith("brand.woff2") for u in urls)
    assert not any(u.startswith("data:") for u in urls)


def test_background_images_reach_the_parsed_images_with_their_bytes() -> None:
    outcome = _capture(
        page_html=(
            "<html><head><title>T</title>"
            '<link rel="stylesheet" href="/site.css"></head><body>'
            '<div class="hero"></div><p>hello world here is some prose</p>'
            "</body></html>"
        ),
        css=".hero{background-image:url('/bg/hero-art.png')}",
    )
    parsed = parse_site(outcome.snapshot)
    hero = [i for i in parsed.images if i.source_url == "https://example.com/bg/hero-art.png"]
    assert hero, [i.source_url for i in parsed.images]
    assert hero[0].sha256 is not None
    assert "css" in hero[0].locator


# --------------------------------------------------------------------------- #
# Favicon
# --------------------------------------------------------------------------- #


def test_favicon_is_fetched_and_surfaced_as_a_mark() -> None:
    outcome = _capture(
        page_html=(
            "<html><head><title>T</title>"
            '<link rel="icon" href="/favicon.png">'
            "</head><body><p>hello world here is some prose</p></body></html>"
        )
    )
    assert any(d.url == "https://example.com/favicon.png" for d in outcome.snapshot.downloads)
    parsed = parse_site(outcome.snapshot)
    favicons = [l for l in parsed.logos if l.source_url == "https://example.com/favicon.png"]
    assert favicons and favicons[0].usage_hint == "mark"
    assert favicons[0].sha256 is not None


def test_apple_touch_icon_still_outranks_the_favicon_for_the_mark_slot() -> None:
    outcome = _capture(
        page_html=(
            "<html><head><title>T</title>"
            '<link rel="icon" href="/favicon.png">'
            '<link rel="apple-touch-icon" href="/touch.png">'
            "</head><body><p>hello world here is some prose</p></body></html>"
        )
    )
    parsed = parse_site(outcome.snapshot)
    marks = [l.source_url for l in parsed.logos if l.usage_hint == "mark"]
    assert marks[0] == "https://example.com/touch.png", marks


# --------------------------------------------------------------------------- #
# THE coupling test: the collector and the parser must choose the same URL
# --------------------------------------------------------------------------- #


def _capture(*, page_html: str, css: str = "body{color:#123456}", missing: set[str] | None = None):
    """Drive a real static capture over MockTransport; ``missing`` 404s those paths."""
    missing = missing or set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = request.url.query.decode() if request.url.query else ""
        target = f"{path}?{query}" if query else path
        if target in missing or path in missing:
            return httpx.Response(404)
        if path in ("/", "/page/", "/index.html"):
            return httpx.Response(200, html=page_html)
        if path.endswith(".css"):
            return httpx.Response(200, text=css)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)

    async def run() -> CaptureOutcome:
        async with httpx.AsyncClient(transport=transport) as client:
            return await capture_website(
                "https://example.com/",
                reporter=_noop,
                render_available=False,
                http_client=client,
            )

    return asyncio.run(asyncio.wait_for(run(), timeout=15.0))


def test_the_collector_and_the_parser_agree_on_every_image_url() -> None:
    """The wave's most important test.

    If ``_collect_assets`` downloaded the widest srcset URL while ``_parse_images`` still
    resolved the bare ``src`` (or vice versa), EVERY image would come back with ``sha256 is
    None`` and be dropped at ``evidence_builder.queue``. This asserts the invariant directly:
    every parsed image carries bytes, and the URL it carries is one the snapshot downloaded.
    """
    outcome = _capture(
        page_html=(
            "<html><head><title>T</title></head><body>"
            '<img src="/i/thumb.png?w=296&q=90" width="600" height="400">'
            '<img src="/i/small.png" srcset="/i/small.png 400w, /i/huge.png 2000w" '
            'width="600" height="400">'
            "<picture>"
            '<source srcset="/i/wide.avif 2400w">'
            '<img src="/i/fallback.png" width="600" height="400">'
            "</picture>"
            "<p>hello world here is some prose to keep the gate quiet</p>"
            "</body></html>"
        )
    )
    parsed = parse_site(outcome.snapshot)
    downloaded = {d.url for d in outcome.snapshot.downloads}

    images = [i for i in parsed.images if i.kind_hint != "og_image"]
    assert len(images) == 3, [i.source_url for i in images]
    for image in images:
        assert image.sha256 is not None, image.source_url
        assert image.source_url in downloaded, image.source_url

    chosen = {i.source_url for i in images}
    assert f"https://example.com/i/thumb.png?w={TARGET_IMAGE_WIDTH}&q=90" in chosen
    assert "https://example.com/i/huge.png" in chosen
    assert "https://example.com/i/wide.avif" in chosen


def test_the_collector_and_the_parser_call_the_same_chooser() -> None:
    """Structural pin: two copies of this logic is the one way to lose every image.

    The collector moved out of ``static`` into ``capture.candidates`` at clone-fidelity F0.2
    (one shared enumeration feeding both the fetch list and every scorer), so the identity to
    pin is candidates↔parse. ``static`` no longer chooses anything — it fetches the
    collector's list — which is itself pinned by
    ``test_ingestion_asset_slurp.py::test_the_collector_is_the_one_list_the_fetcher_walks``.
    """
    from lumen_ingestion.capture import candidates, imgsrc, parse, static

    assert candidates.image_source_ladder is imgsrc.image_source_ladder
    assert parse.image_source_ladder is imgsrc.image_source_ladder
    assert parse.background_image_urls is imgsrc.background_image_urls
    assert static.collect_asset_candidates is candidates.collect_asset_candidates


def test_when_the_upgraded_url_yields_no_bytes_the_original_src_still_wins() -> None:
    """A CDN that refuses the widened request must cost us nothing at all."""
    outcome = _capture(
        page_html=(
            "<html><head><title>T</title></head><body>"
            '<img src="/i/thumb.png?w=296&q=90" width="600" height="400">'
            "<p>hello world here is some prose to keep the gate quiet</p>"
            "</body></html>"
        ),
        missing={f"/i/thumb.png?w={TARGET_IMAGE_WIDTH}&q=90"},
    )
    parsed = parse_site(outcome.snapshot)
    images = [i for i in parsed.images if i.kind_hint != "og_image"]
    assert len(images) == 1
    assert images[0].source_url == "https://example.com/i/thumb.png?w=296&q=90"
    assert images[0].sha256 is not None


# --------------------------------------------------------------------------- #
# The budget that replaced the caps (clone-fidelity F0.2)
# --------------------------------------------------------------------------- #


def test_the_image_ceiling_is_the_shared_budget_and_overflow_names_what_it_dropped() -> None:
    """The old hard cap of 50 whispered a ``LUMI0504`` at ``info`` and named nothing.

    It is now the shared asset budget with a LOUD ``LUMI0514`` carrying every dropped URL —
    an image the kit does not carry is an image the F2 clone cannot rehost.
    """
    snapshot = load_snapshot(FIXTURES / "insight_static.json")

    def parse_with(count: int):
        extra = "".join(
            f'<img src="/img/x{i}.png" width="{100 + i}" height="{100 + i}">'
            for i in range(count)
        )
        html = snapshot.html.replace("</main>", extra + "</main>")
        return parse_site(SiteSnapshot(**{**snapshot.model_dump(), "html": html}))

    def non_og(parsed) -> int:
        return len([i for i in parsed.images if i.kind_hint != "og_image"])

    baseline = non_og(parse_with(0))
    fill = MAX_ASSET_COUNT - baseline

    at_budget = parse_with(fill)
    assert non_og(at_budget) == MAX_ASSET_COUNT
    assert not any(d["code"] == "LUMI0514" for d in at_budget.diagnostics)

    over = parse_with(fill + 1)
    assert non_og(over) == MAX_ASSET_COUNT
    dropped = [d for d in over.diagnostics if d["code"] == "LUMI0514"]
    assert len(dropped) == 1
    assert dropped[0]["severity"] == "warning"
    assert len(dropped[0]["dropped"]) == 1
    assert dropped[0]["dropped"][0].endswith(".png")


def test_the_old_silent_css_background_cap_is_gone() -> None:
    """RED CASE: ``background_image_urls`` used to truncate at 40 and tell nobody."""
    from lumen_ingestion.capture import imgsrc

    assert not hasattr(imgsrc, "MAX_BACKGROUND_IMAGES")
    assert not hasattr(imgsrc, "IMAGE_CANDIDATE_CAP")

    css = "".join(f".s{i}{{background-image:url(/bg/{i}.png)}}" for i in range(60))
    urls = background_image_urls(
        HTMLParser("<html><body></body></html>"),
        [type("S", (), {"url": "https://example.com/a.css", "text": css})()],
        BASE,
    )
    assert len(urls) == 60


@pytest.mark.parametrize(
    "html",
    [
        '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="1" height="1">',
        '<img src="">',
    ],
)
def test_degenerate_sources_never_crash_the_ladder(html: str) -> None:
    image_source_ladder(_img(html), BASE)
