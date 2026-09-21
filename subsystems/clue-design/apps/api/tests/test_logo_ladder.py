"""The logo ladder's guards, one test per lesson the pilot paid for.

Every case here corresponds to a documented way the pilot returned a
confidently wrong answer. They are regression pins, not coverage.
"""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
from lumen_ingestion import logo_ladder as ladder

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _png(width: int, height: int, color=(20, 30, 40, 255)) -> bytes:
    from PIL import Image

    image = Image.new("RGBA", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _svg(body: str, width: int = 120, height: int = 32) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>'
    ).encode()


def _wordmark_svg(width: int = 160, height: int = 32, fill: str = "#101820") -> bytes:
    # Four evenly-spaced bars: a wordmark's letter gaps are small and uniform.
    bars = "".join(
        f'<rect x="{x}" y="6" width="24" height="20" fill="{fill}"/>'
        for x in (4, 34, 64, 94)
    )
    return _svg(bars, width, height)


def _lockup_svg(width: int = 200, height: int = 40, fill: str = "#101820") -> bytes:
    # A square symbol, one dominant gap, then evenly-spaced text bars.
    symbol = f'<rect x="0" y="0" width="40" height="40" fill="{fill}"/>'
    text = "".join(
        f'<rect x="{x}" y="12" width="20" height="16" fill="{fill}"/>'
        for x in (80, 106, 132, 158)
    )
    return _svg(symbol + text, width, height)


def _resolve(html: str, fetched: dict, *, domain="acme.com", title="Acme Robotics", **kw):
    page_url = f"https://{domain}/"
    candidates = ladder.harvest(html, page_url, kw.pop("stylesheets", None))
    ladder.attach_bytes(candidates, fetched)
    meta = {
        "homepage_url": page_url,
        "page_title": title,
        "jsonld_org_names": kw.pop("org_names", []),
        **kw.pop("meta", {}),
    }
    return candidates, ladder.resolve(candidates, meta, domain, kw.pop("company_name", None))


# ---------------------------------------------------------------------------
# lesson 1 — serializing an inline <svg> through an HTML parser corrupts it
# ---------------------------------------------------------------------------


def test_inline_svg_round_trip_keeps_viewbox_camelcase():
    """bs4 lowercased `viewBox` to `viewbox` and every strict renderer rejected
    the file — it downloaded "successfully" and was silently unusable."""
    html = (
        '<header><a href="/"><svg viewBox="0 0 100 24" preserveAspectRatio="xMidYMid meet">'
        '<linearGradient id="g"/><path d="M0 0h10"/></svg></a></header>'
    )
    [candidate] = [c for c in ladder.harvest(html, "https://acme.com/") if c.inline_svg_text]
    ladder.attach_bytes([candidate], {})
    markup = candidate.body.decode()

    assert 'viewBox="0 0 100 24"' in markup
    assert "viewbox=" not in markup
    assert "preserveAspectRatio" in markup
    assert "<linearGradient" in markup


def test_repair_svg_case_restores_a_lowercased_viewbox():
    """The repair also runs on markup that reaches us from elsewhere — a
    browser's outerHTML, a fixture, a hand-written snippet."""
    repaired = ladder.repair_svg_case('<svg viewbox="0 0 64 16"><path d="M0 0h4"/></svg>')

    assert 'viewBox="0 0 64 16"' in repaired
    # viewBox alone gives the renderer no intrinsic size, so both are injected.
    assert 'width="64"' in repaired and 'height="16"' in repaired
    assert "xmlns=" in repaired


def test_repair_svg_case_never_duplicates_an_existing_dimension():
    """Anthropic's mark carries height but no width; injecting both produced a
    duplicate-attribute ParseError — the same silently broken file, new flavour."""
    repaired = ladder.repair_svg_case('<svg height="16" viewBox="0 0 143 16"><path d="M0 0h4"/></svg>')

    assert repaired.count("height=") == 1
    assert 'width="143"' in repaired


# ---------------------------------------------------------------------------
# lesson 2 — "links home" must be scoped to the first-party domain
# ---------------------------------------------------------------------------


def test_links_home_rejects_another_company_root():
    """`urlsplit(href).path in ("", "/")` is true for other people's domains too,
    which floated every external link-out arrow on anthropic.com to the top."""
    assert ladder._links_home("/", "anthropic.com") is True
    assert ladder._links_home("https://www.anthropic.com/", "anthropic.com") is True
    assert ladder._links_home("https://academy.claude.com/", "anthropic.com") is False
    assert ladder._links_home("https://acme.com/", "anthropic.com") is False
    assert ladder._links_home("/pricing", "anthropic.com") is False
    assert ladder._links_home("#main", "anthropic.com") is False
    assert ladder._links_home(None, "anthropic.com") is False


def test_links_home_follows_the_registrable_domain_not_the_host():
    assert ladder._links_home("https://acme.co.uk/", "www.acme.co.uk") is True
    # Two sites under a hosting suffix are NOT the same organisation.
    assert ladder._links_home("https://them.github.io/", "us.github.io") is False


# ---------------------------------------------------------------------------
# lesson 3 — token matching must be boundary-anchored
# ---------------------------------------------------------------------------


def test_token_matching_is_boundary_anchored():
    """Substring matching makes "search" fire on "research" and "mark" on
    "marketing" — that is how a hamburger icon won the mark slot."""
    research = ladder._normalize_hay("Research Institute logo")
    assert ladder._has_token(research, "research") is True
    assert ladder._has_token(research, "search") is False

    marketing = ladder._normalize_hay("marketing-banner.png")
    assert ladder._has_token(marketing, "mark") is False
    assert ladder._has_token(ladder._normalize_hay("acme-logomark.svg"), "logomark") is True


def test_a_research_logo_is_not_junk_flagged_as_a_search_icon():
    candidate = ladder.LadderCandidate(
        url="https://acme.com/img/research-logo.svg", rung="HEADER", fmt="svg",
        width=180, height=40, byte_len=2048,
    )
    _, hits = ladder.junk_assessment(candidate)

    assert hits == []


def test_junk_matches_the_asset_name_not_the_dom_role_label():
    """`div[role=banner]` is this harvester's own label, and matching it made the
    "banner" junk token disqualify insighthealth.ai's real header logo."""
    candidate = ladder.LadderCandidate(
        url="https://acme.com/brand/logo.svg", rung="HEADER", fmt="svg",
        dom_role="div[role=banner] <img>", width=180, height=40, byte_len=2048,
    )
    _, hits = ladder.junk_assessment(candidate)

    assert hits == []


# ---------------------------------------------------------------------------
# lesson 4 — synthetic URLs contribute zero name evidence
# ---------------------------------------------------------------------------


def test_a_synthetic_inline_svg_url_carries_no_brand_evidence():
    """An inline <svg> gets a URL built from the PAGE, so the company domain
    appeared in every one of them and made a close-button look brand-named."""
    close_button = ladder.LadderCandidate(
        url="https://workspan.com/platform/workspan-ai#inline-svg-693",
        rung="INLINE_SVG", fmt="svg",
    )
    tokens = ladder.company_tokens("workspan.com")

    assert ladder._asset_hay(close_button) == "--"
    assert ladder._brand_named(close_button, tokens) == []

    real_file = ladder.LadderCandidate(url="https://workspan.com/x/workspan-symbol.svg")
    assert ladder._brand_named(real_file, tokens) == ["workspan"]


def test_an_unlabelled_inline_svg_is_pushed_down_the_ladder():
    html = (
        '<header><svg viewBox="0 0 24 24"><path d="M4 4l16 16M20 4L4 20"/></svg>'
        '<a href="/"><img src="/brand/acme-logo.svg" alt="Acme" width="160" height="32"></a>'
        "</header>"
    )
    fetched = {"https://acme.com/brand/acme-logo.svg": (_wordmark_svg(), "image/svg+xml")}
    _, resolution = _resolve(html, fetched)

    assert resolution.slots["light"] is not None
    assert resolution.slots["light"].candidate.url.endswith("acme-logo.svg")


# ---------------------------------------------------------------------------
# lesson 5 — squareness alone does not identify a symbol mark
# ---------------------------------------------------------------------------


def test_a_square_icon_with_no_brand_evidence_is_not_a_mark():
    """A 24x24 hamburger won the mark slot on the first run."""
    hamburger = ladder.LadderCandidate(
        url="https://acme.com/ui/icon.svg", rung="HEADER", fmt="svg", width=24, height=24,
    )
    marked, why = ladder.is_mark(hamburger, 4.0, ladder.company_tokens("acme.com"))

    assert marked is False
    assert "no brand evidence" in why


def test_a_square_asset_earns_the_mark_slot_on_evidence():
    named = ladder.LadderCandidate(
        url="https://acme.com/brand/logomark.svg", rung="HEADER", fmt="svg",
        width=48, height=48,
    )
    assert ladder.is_mark(named, 4.0, ladder.company_tokens("acme.com"))[0] is True

    icon_rung = ladder.LadderCandidate(
        url="https://acme.com/touch.png", rung="APPLE_TOUCH", fmt="png", width=180, height=180,
    )
    assert ladder.is_mark(icon_rung, 4.0, ladder.company_tokens("acme.com"))[0] is True

    brand_named = ladder.LadderCandidate(
        url="https://acme.com/assets/acme-bug.png", rung="HEADER", fmt="png",
        width=64, height=64,
    )
    assert ladder.is_mark(brand_named, 4.0, ladder.company_tokens("acme.com"))[0] is True


# ---------------------------------------------------------------------------
# lesson 6 — chrome-zone detection must go beyond tag names
# ---------------------------------------------------------------------------


def test_a_drupal_region_header_is_found_without_a_header_tag():
    """mngi.com (Drupal, `region-header`) harvested 4 candidates and missed its
    own header entirely when zones were detected by tag name."""
    html = (
        '<div class="region region-header"><a href="/">'
        '<img src="/sites/default/logo.png" alt="MNGI" width="200" height="48"></a></div>'
        '<div id="page-footer"><img src="/f.png" alt="MNGI" width="120" height="30"></div>'
    )
    candidates = ladder.harvest(html, "https://mngi.com/")
    rungs = {c.rung for c in candidates}

    assert "HEADER" in rungs
    assert "FOOTER" in rungs


def test_aria_landmarks_are_chrome_zones_too():
    html = (
        '<div role="banner"><img src="/logo.svg" alt="Acme" width="160" height="32"></div>'
        '<div role="contentinfo"><img src="/foot.svg" alt="Acme" width="160" height="32"></div>'
    )
    by_rung = {c.rung for c in ladder.harvest(html, "https://acme.com/")}

    assert {"HEADER", "FOOTER"} <= by_rung


# ---------------------------------------------------------------------------
# lesson 6b — the ladder reads a CSS url() the same way everything else does
#
# The F0 fix wave replaced three hand-rolled `url()` regexes with one shared
# escape-aware reader (`capture.cssurl.iter_css_urls`) and deliberately left the
# ladder's own copy alone. That copy carried BOTH defects the wave killed: the
# unquoted branch (`[^'\")]+`) stopped dead at the backslash-escaped `)` Webflow
# writes into a Designer-uploaded filename and never unescaped it, and the
# `['\"]?` "quoted" branch was decorative — the character class ended the token at
# the first space or paren INSIDE the quotes. On this path a mangled url is not a
# lost decoration: it is the brand's own logo, enumerated under a URL its CDN
# answers 403 to, so the mark is silently missing from the ladder.
# ---------------------------------------------------------------------------


def test_an_escaped_paren_in_a_background_url_survives_enumeration():
    """Webflow escapes the parens in `Logo (1).svg`. The old reader returned
    `https://cdn/Logo%20\\(1\\` — a 403."""
    css = r".logo{background-image:url(https://cdn/Logo%20\(1\).svg)}"

    images, _ = ladder._parse_css(css, "https://acme.com/")

    assert [url for _, url in images] == ["https://cdn/Logo%20(1).svg"]


def test_a_quoted_background_url_containing_spaces_and_parens_is_not_truncated():
    """The old reader returned `https://cdn/Logo (2` for both quote styles."""
    double = r'.logo{background-image:url("https://cdn/Logo (2).svg")}'
    single = r".logo{background-image:url('https://cdn/Logo (2).svg')}"

    for css in (double, single):
        images, _ = ladder._parse_css(css, "https://acme.com/")
        assert [url for _, url in images] == ["https://cdn/Logo (2).svg"]


def test_every_layer_of_a_multi_image_background_is_enumerated():
    """The greedy `[^;}]*` hop in the old reader skipped to the LAST `url(` in a
    declaration, so the first of two stacked background layers vanished — the
    exact shape of the insighthealth.ai hero."""
    css = ".hero-logo{background-image:url(/mark.svg), url(/glow.png)}"

    images, _ = ladder._parse_css(css, "https://acme.com/")

    assert [url for _, url in images] == [
        "https://acme.com/mark.svg",
        "https://acme.com/glow.png",
    ]


def test_a_webflow_escaped_header_background_reaches_the_css_bg_rung():
    """End to end: the candidate the ladder ranks carries the real URL."""
    html = (
        "<style>.header-logo{background-image:"
        r"url(https://cdn.acme.com/Acme%20Logo%20\(1\).svg)}"
        '</style><div class="header-logo"></div>'
    )

    urls = {c.url for c in ladder.harvest(html, "https://acme.com/") if c.rung == "CSS_BG"}

    assert urls == {"https://cdn.acme.com/Acme%20Logo%20(1).svg"}


# ---------------------------------------------------------------------------
# guard 1 — asset-level identity (the AWS incident)
# ---------------------------------------------------------------------------


def test_a_partner_logo_on_our_own_cdn_never_becomes_our_counterpart():
    """WorkSpan reported `resolved` at 0.88 with THE AWS LOGO as its light-mode
    logo: `aws-black.svg` matched on aspect and filename, was served from
    WorkSpan's own Webflow CDN, and the page-level identity check passed
    correctly because the PAGE really was WorkSpan's."""
    primary = ladder.LadderCandidate(
        url="https://cdn.workspan.com/workspan-symbol.svg", fmt="svg", width=46, height=26,
    )
    aws = ladder.LadderCandidate(
        url="https://cdn.workspan.com/aws-black.svg", fmt="svg", width=66, height=40,
    )
    tokens = ladder.company_tokens("workspan.com")

    ok, why = ladder._counterpart_plausible(aws, primary, tokens)

    assert ok is False
    assert "different company's asset" in why


# ---------------------------------------------------------------------------
# guard 1b — identity anchoring (the apollo.io / OpenAI incident, 2026-08-26)
#
# apollo.io shipped an ad carrying OPENAI'S logomark as apollo's own reversed
# logo. A 19x19 partner glyph, inline on a #000000 panel, beat apollo's real
# 303x303 asterisk for the `dark` slot because the only evidence anyone checked
# was the luminance of the surface behind it. The deeper defect is that a third
# party's mark was ever a CANDIDATE for a brand slot: ingestion harvests every
# image in the page chrome, and the ladder classified from that raw pool.
# ---------------------------------------------------------------------------


def _apollo_pool():
    """The three assets apollo.io really produced (W5 forensic, §R2.6)."""
    wordmark = ladder.LadderCandidate(
        url="https://www.apollo.io/#inline-svg-0", source_domain="www.apollo.io",
        rung="INLINE_SVG", fmt="svg", width=152, height=26,
        link_destination="/", dom_index=0, inline_svg_text="<svg/>", sha256="a" * 64,
        body=_svg('<path d="M4 6h24v20H4zM34 6h24v20H34zM64 6h24v20H64z" fill="#1F1F1E"/>', 152, 26),
        content_type="image/svg+xml",
    )
    asterisk = ladder.LadderCandidate(
        url="https://www.apollo.io/assets/apollo-logo-mark.svg", source_domain="www.apollo.io",
        rung="PAGE_LOGO_NAMED", fmt="svg", width=303, height=303, alt_text="Apollo",
        sha256="b" * 64,
        body=_svg('<path d="M151 20L180 120L280 151L180 182L151 282L20 151Z" fill="#1F1F1E"/>', 303, 303),
        content_type="image/svg+xml",
    )
    openai = ladder.LadderCandidate(
        url="https://www.apollo.io/#inline-svg-7", source_domain="www.apollo.io",
        rung="INLINE_SVG", fmt="svg", width=19, height=19, dom_index=1,
        background_context="#000000", background_source="static",
        inline_svg_text="<svg/>", sha256="c" * 64,
        body=_svg(
            '<path d="M9.5 0.7c-1.9 0-3.6 1.1-4.4 2.8-1.9 0.2-3.5 1.5-4.1 3.3" fill="#FFFFFF"/>'
            '<path d="M14 3.5c1.8 0.6 3.1 2.2 3.3 4.1 1.1 1.5 1.3 3.5 0.5 5.2" fill="#FFFFFF"/>',
            19, 19,
        ),
        content_type="image/svg+xml",
    )
    return wordmark, asterisk, openai


def _apollo_resolution():
    pool = list(_apollo_pool())
    meta = {"homepage_url": "https://www.apollo.io/", "page_title": "Apollo.io",
            "jsonld_org_names": []}
    return pool, ladder.resolve(pool, meta, "apollo.io", "Apollo")


def test_a_foreign_glyph_on_a_dark_panel_fills_no_brand_slot():
    """THE red case. Before identity anchoring this exact pool put the 19x19
    OpenAI glyph in the `dark` slot, and the ad shipped with it."""
    _, resolution = _apollo_resolution()

    filled = {
        name: (slot.candidate.width, slot.candidate.height)
        for name, slot in resolution.slots.items() if slot is not None
    }
    assert (19, 19) not in filled.values(), f"the foreign glyph took a slot: {filled}"
    # apollo's own marks are untouched — this is exclusion, not scorched earth.
    assert filled["light"] == (152, 26)
    assert filled["mark"] == (303, 303)
    # An empty reversed slot is the CORRECT output: apollo ships no dark variant.
    assert resolution.slots["dark"] is None


def test_the_glyph_was_a_live_candidate_and_was_excluded_on_identity():
    """It is not filtered as junk, nor as a partner link, nor as third-party —
    it scores, it is first-party, it survives every pre-existing gate. Identity
    anchoring is the only thing standing between it and a brand slot."""
    (wordmark, asterisk, openai), resolution = _apollo_resolution()

    assert openai.first_party is True
    assert openai.score > 0
    assert not openai.junk_hits
    assert openai.identity_anchored is False
    assert openai.identity_anchor == []

    # Apollo's own two marks anchor on different evidence.
    assert wordmark.identity_anchored is True
    assert "wrapped in a link to the site root" in wordmark.identity_anchor
    assert asterisk.identity_anchored is True
    assert any("declared by the site" in r for r in asterisk.identity_anchor)
    assert resolution.counts["identity_anchored"] == 2


def test_a_site_that_anchors_nothing_returns_empty_slots_and_says_why():
    """The cost of the rule, stated. If NOTHING on the page evidences the
    brand's own mark, every slot is empty and needs_review — and the note
    distinguishes 'nothing scored' from 'nothing was ours', because an operator
    reading 'survived scoring' about candidates that scored fine is misled."""
    anonymous = [
        ladder.LadderCandidate(
            url=f"https://acme.com/#inline-svg-{i}", source_domain="acme.com",
            rung=rung, fmt="svg", width=160, height=32, dom_index=i,
            sha256=chr(97 + i) * 64,
            body=_svg(f'<path d="M{4 + i} 6h24v20H4zM34 6h24v20H34z" fill="#101820"/>', 160, 32),
            content_type="image/svg+xml",
        )
        for i, rung in enumerate(("INLINE_SVG", "FOOTER"))
    ]
    meta = {"homepage_url": "https://acme.com/", "page_title": "Acme", "jsonld_org_names": []}

    resolution = ladder.resolve(anonymous, meta, "acme.com", "Acme")

    assert resolution.status == "needs_review"
    assert all(slot is None for slot in resolution.slots.values())
    assert resolution.counts["viable_first_party"] == 2
    assert resolution.counts["identity_anchored"] == 0
    assert any("being THIS brand's mark" in note for note in resolution.notes)


def test_a_favicon_anchors_identity_with_no_name_and_no_link():
    """A brand whose header logo is an anonymous inline <svg> still has an
    identity: the site DECLARES its own icon in machine-readable markup, and a
    partner glyph can never be your favicon."""
    favicon = ladder.LadderCandidate(url="https://acme.com/assets/f0e1.png", rung="FAVICON")
    anonymous = ladder.LadderCandidate(url="https://acme.com/#inline-svg-3", rung="INLINE_SVG")
    tokens = ladder.company_tokens("acme.com")

    assert ladder.identity_anchor(favicon, tokens, "acme.com")
    assert ladder.identity_anchor(anonymous, tokens, "acme.com") == []


def test_identity_propagates_through_identical_vector_artwork():
    """The footer recolour of an anchored header logo carries no name and no
    link of its own — but it is provably the same artwork, so it is ours."""
    header = ladder.LadderCandidate(
        url="https://acme.com/acme-logo.svg", rung="HEADER", fmt="svg",
        body=_svg('<path d="M4 6h24v20H4zM34 6h24v20H34z" fill="#101820"/>'),
    )
    footer = ladder.LadderCandidate(
        url="https://acme.com/f2.svg", rung="FOOTER", fmt="svg",
        body=_svg('<path d="M4 6h24v20H4zM34 6h24v20H34z" fill="#ffffff"/>'),
    )
    ladder._link_render_observations([header, footer])
    ladder.anchor_identity([header, footer], ladder.company_tokens("acme.com"), "acme.com")

    assert header.identity_anchored is True
    assert footer.identity_anchored is True
    assert "same vector artwork" in footer.identity_anchor[0]


# --- the second net: size sanity on the counterpart slots ------------------


def test_an_icon_sized_counterpart_is_rejected_even_when_placement_says_dark():
    """Placement earns the right to ignore lockup SHAPE, never the right to hand
    a primary slot to art that is not primary-sized."""
    # Both are inline <svg>, so neither carries a filename — exactly apollo's
    # shape, and the reason the brand-name guard could not save it.
    primary = ladder.LadderCandidate(
        url="https://apollo.io/#inline-svg-0", rung="INLINE_SVG", fmt="svg",
        width=152, height=26,
    )
    glyph = ladder.LadderCandidate(
        url="https://apollo.io/#inline-svg-7", rung="INLINE_SVG", fmt="svg",
        width=19, height=19,
        background_context="#000000", background_source="static",
    )
    glyph.variant, glyph.variant_basis, glyph.variant_basis_rank = ladder.classify_variant(glyph)
    # rank 3 is placement — the rank that used to short-circuit every other check
    assert glyph.variant_basis_rank == 3

    ok, why = ladder._counterpart_plausible(glyph, primary, ladder.company_tokens("apollo.io"))

    assert ok is False
    assert "icon-sized" in why


def test_a_counterpart_far_smaller_than_the_primary_is_not_the_same_mark():
    primary = ladder.LadderCandidate(url="https://acme.com/acme-logo.svg", fmt="svg",
                                     width=400, height=64)
    sprite = ladder.LadderCandidate(url="https://acme.com/acme-sprite.svg", fmt="svg",
                                    width=32, height=32)

    ok, why = ladder._counterpart_plausible(sprite, primary, ladder.company_tokens("acme.com"))

    assert ok is False
    assert "smaller than the primary" in why


# --- the happy path these nets must not cost -------------------------------


def test_a_bigger_footer_lockup_is_still_a_legitimate_counterpart():
    """workspan.com's regression pin, restated. Its footer shows the full
    203x32 lockup against a 46x26 header symbol: growth is normal for an
    alternate lockup, and placement must still outrank the aspect veto."""
    primary = ladder.LadderCandidate(
        url="https://workspan.com/workspan-symbol.svg", fmt="svg", width=46, height=26,
    )
    footer = ladder.LadderCandidate(
        url="https://workspan.com/workspan-lockup.svg", rung="FOOTER", fmt="svg",
        width=203, height=32,
        background_context="rgb(255, 255, 255)",
        background_source="rendered:computed-behind-asset",
    )
    footer.variant, footer.variant_basis, footer.variant_basis_rank = ladder.classify_variant(footer)
    assert footer.variant_basis_rank == 3

    ok, why = ladder._counterpart_plausible(footer, primary, ladder.company_tokens("workspan.com"))

    assert ok is True
    assert "placement-classified" in why


def test_the_same_artwork_recoloured_is_admitted_on_geometry_alone():
    """The positive identity signal. Same paths, different fill, and dimensions
    that would otherwise trip the size floor — geometry proves it is ours."""
    primary = ladder.LadderCandidate(
        url="https://acme.com/acme-logo.svg", fmt="svg", width=160, height=32,
        body=_svg('<path d="M4 6h24v20H4zM34 6h24v20H34z" fill="#101820"/>'),
    )
    reversed_ = ladder.LadderCandidate(
        url="https://acme.com/f2.svg", fmt="svg", width=20, height=20,
        body=_svg('<path d="M4 6h24v20H4zM34 6h24v20H34z" fill="#ffffff"/>'),
    )
    ladder._link_render_observations([primary, reversed_])

    ok, why = ladder._counterpart_plausible(reversed_, primary, ladder.company_tokens("acme.com"))

    assert ok is True
    assert "identical vector path geometry" in why


def test_a_mark_linking_into_partners_is_rejected():
    """B2B mega-menus are full of partner logos served first-party; the tell is
    the link — a partner logo links to /use-case/..., never to /."""
    primary = ladder.LadderCandidate(url="https://acme.com/acme-logo.svg", fmt="svg",
                                     width=160, height=32)
    partner = ladder.LadderCandidate(
        url="https://acme.com/cdn/acme-alliance-logo.svg", fmt="svg", width=150, height=30,
        link_destination="/use-case/aws-partnership",
    )
    ok, why = ladder._counterpart_plausible(
        partner, primary, ladder.company_tokens("acme.com")
    )

    assert ok is False
    assert "partner or customer logo" in why


def test_identity_failure_is_fail_closed_with_the_candidates_preserved():
    """Asked to resolve one company's evidence as a different company, the
    ladder returns zero winners and keeps every candidate."""
    # A page served from globex.io whose every human-readable name says Acme:
    # nothing on it is evidence that these assets belong to Globex.
    html = (
        '<header><a href="/"><img src="/acme-logo.svg" alt="Acme" width="160" height="32">'
        "</a></header>"
    )
    fetched = {
        "https://globex.io/acme-logo.svg": (_wordmark_svg(), "image/svg+xml"),
        "https://globex.io/favicon.ico": _png(32, 32),
    }
    _, hostile = _resolve(html, fetched, domain="globex.io", title="Acme Robotics")

    assert hostile.identity["passed"] is False
    assert hostile.status == "needs_review"
    assert all(slot is None for slot in hostile.slots.values())
    assert hostile.ranked, "the full candidate list must survive a fail-closed identity check"
    assert any("IDENTITY CHECK FAILED" in n for n in hostile.notes)

    # The same evidence resolved against its real owner passes.
    _, honest = _resolve(html, {"https://acme.com/acme-logo.svg": (_wordmark_svg(), "image/svg+xml")})
    assert honest.identity["passed"] is True


def test_the_primary_slot_is_gated_on_asset_level_brand_evidence():
    """Preferring the fullest lockup bypassed the asset-level identity check and
    the Palo Alto Networks partner logo took workspan.com's primary slot."""
    # Mirrors workspan.com: a compact 46x26 first-party symbol against a
    # 320x60 partner lockup served from the same CDN.
    html = (
        '<header>'
        '<a href="/"><img src="/acme-symbol.svg" alt="Acme" width="46" height="26"></a>'
        '<a href="/partners/pan"><img src="/cdn/PaloAltoNetworks-Logo.svg" '
        'alt="Palo Alto Networks" width="320" height="60"></a>'
        "</header>"
    )
    fetched = {
        "https://acme.com/acme-symbol.svg": (
            _svg('<rect width="46" height="26" fill="#123"/>', 46, 26), "image/svg+xml"
        ),
        "https://acme.com/cdn/PaloAltoNetworks-Logo.svg": (_lockup_svg(320, 60), "image/svg+xml"),
    }
    _, resolution = _resolve(html, fetched)

    winner = resolution.slots["light"] or resolution.slots["dark"]
    assert winner is not None
    assert "acme-symbol" in winner.candidate.url, (
        "the wider, first-party, full_lockup partner asset must not steal the primary slot"
    )


def test_a_junk_flagged_asset_can_never_fill_a_slot():
    """mngi.com's mark became `MNGI_Scheduling_BTN_SQUARE.jpg`. Junk tokens
    penalised its score but did not make it ineligible."""
    html = (
        '<header>'
        '<a href="/"><img src="/mngi-logo.svg" alt="MNGI" width="180" height="40"></a>'
        '<img src="/MNGI_Scheduling_BTN_SQUARE.png" alt="MNGI Scheduling" width="120" height="120">'
        "</header>"
    )
    fetched = {
        "https://mngi.com/mngi-logo.svg": (_wordmark_svg(180, 40), "image/svg+xml"),
        "https://mngi.com/MNGI_Scheduling_BTN_SQUARE.png": (_png(120, 120), "image/png"),
    }
    _, resolution = _resolve(html, fetched, domain="mngi.com", title="MNGI Digestive Health")

    filled = [s.candidate.url for s in resolution.slots.values() if s]
    assert not any("BTN_SQUARE" in url for url in filled)


# ---------------------------------------------------------------------------
# guard 2 — never synthesize
# ---------------------------------------------------------------------------


def test_a_brand_with_no_dark_asset_reports_dark_absent():
    """Absence is a real answer. Four of the pilot's seven brands publish no
    dark-mode logo anywhere reachable."""
    html = '<header><a href="/"><img src="/acme-logo.svg" alt="Acme" width="160" height="32"></a></header>'
    fetched = {"https://acme.com/acme-logo.svg": (_wordmark_svg(), "image/svg+xml")}
    _, resolution = _resolve(html, fetched)

    assert resolution.slots["light"] is not None
    assert resolution.slots["dark"] is None
    assert any("NOT synthesized" in note for note in resolution.notes)


def test_an_adaptive_asset_with_no_observed_ink_is_never_materialized():
    """anthropic.com's A-mark is adaptive but was never seen being painted, so
    its dark slot stays absent. An ink that was never observed is never
    invented."""
    adaptive = _svg('<path d="M0 0h40v32H0z" fill="currentColor"/>', 160, 32)
    html = '<header><a href="/"><img src="/acme-logo.svg" alt="Acme" width="160" height="32"></a></header>'
    _, resolution = _resolve(html, {"https://acme.com/acme-logo.svg": (adaptive, "image/svg+xml")})

    light = resolution.slots["light"]
    assert light is not None and light.provenance == "genuine"
    assert resolution.slots["dark"] is None
    assert light.candidate.appearance["verdict"] == "adaptive"


def test_an_adaptive_asset_is_materialized_only_in_an_observed_ink():
    """linear.app's dark slot is its own currentColor asset exported at
    #f7f8f8 — the value read off its #08090a surface, not chosen."""
    adaptive = _svg('<path d="M0 0h40v32H0z" fill="currentColor"/>', 160, 32)
    html = '<header><a href="/"><img src="/acme-logo.svg" alt="Acme" width="160" height="32"></a></header>'
    page_url = "https://acme.com/"
    candidates = ladder.harvest(html, page_url)
    ladder.attach_bytes(candidates, {"https://acme.com/acme-logo.svg": (adaptive, "image/svg+xml")})
    for candidate in candidates:
        if candidate.url.endswith("acme-logo.svg"):
            candidate.render_key = "svg:abc"
    meta = {
        "homepage_url": page_url, "page_title": "Acme Robotics", "jsonld_org_names": [],
        "render_styles": {
            "status": "ok",
            "ink_observations": {
                "svg:abc": [
                    {"scheme": "light", "state": "scroll_top", "ink": "rgb(247, 248, 248)",
                     "bg": "rgb(8, 9, 10)"},
                ]
            },
        },
    }
    resolution = ladder.resolve(candidates, meta, "acme.com")

    dark = resolution.slots["dark"]
    assert dark is not None
    assert dark.provenance == "materialized-adaptive"
    assert dark.ink == "#f7f8f8"
    assert b"currentColor" not in dark.body and b"#f7f8f8" in dark.body
    # and the light slot keeps the canonical adaptive file
    assert resolution.slots["light"].provenance in ("genuine", "materialized-adaptive")


def test_materialization_never_beats_a_genuine_published_asset():
    adaptive = ladder.LadderCandidate(
        url="https://acme.com/acme-logo.svg", fmt="svg",
        body=_svg('<path d="M0 0h4" fill="currentColor"/>'),
    )
    result = ladder.materialize_adaptive(adaptive, {"render_styles": {"ink_observations": {}}})

    assert result is None, "no observation means no materialization"


# ---------------------------------------------------------------------------
# the fetch-everything invariant
# ---------------------------------------------------------------------------


def test_a_failed_fetch_is_recorded_and_the_candidate_survives():
    """A candidate is never silently dropped. The bytes arriving as junk, or not
    arriving at all, must both be visible in the ranked list."""
    html = (
        '<header><a href="/"><img src="/acme-logo.svg" alt="Acme" width="160" height="32"></a>'
        '<img src="/gone.png" alt="Acme secondary" width="80" height="80"></header>'
    )
    fetched = {
        "https://acme.com/acme-logo.svg": (_wordmark_svg(), "image/svg+xml"),
        "https://acme.com/gone.png": "HTTP 404",
        "https://acme.com/favicon.ico": _png(32, 32),
    }
    candidates, resolution = _resolve(html, fetched)

    missing = [c for c in resolution.ranked if c.url.endswith("gone.png")]
    assert len(missing) == 1
    assert missing[0].fetch_error == "HTTP 404"
    assert resolution.counts["fetch_errors"] == 1
    assert resolution.counts["harvested"] == len(candidates)
    # It is ranked, but it can never win — a byteless asset is unusable.
    assert all(
        (slot is None or not slot.candidate.fetch_error) for slot in resolution.slots.values()
    )


def test_candidate_asset_urls_lists_every_fetchable_rung():
    """The scorer must never rank a candidate whose bytes were never downloaded,
    because a byteless winner is silently dropped downstream."""
    html = """
    <head>
      <link rel="apple-touch-icon" href="/touch.png">
      <link rel="icon" href="/fav.ico">
      <meta property="og:logo" content="/og-logo.png">
      <script type="application/ld+json">
        {"@type": "Organization", "name": "Acme", "logo": "/jsonld-logo.png"}
      </script>
    </head>
    <header><a href="/"><img src="/acme-logo.svg" alt="Acme"></a></header>
    <footer><img src="/acme-logo-white.svg" alt="Acme"></footer>
    """
    urls = ladder.candidate_asset_urls(html, "https://acme.com/")

    for expected in (
        "/acme-logo.svg", "/acme-logo-white.svg", "/touch.png", "/fav.ico",
        "/og-logo.png", "/jsonld-logo.png",
    ):
        assert f"https://acme.com{expected}" in urls, expected


# ---------------------------------------------------------------------------
# variant ordering
# ---------------------------------------------------------------------------


def test_adaptive_detection_outranks_placement():
    """Making placement authoritative first broke linear.app: its site is
    uniformly #08090a, so its currentColor header logo was classified `dark` and
    the light slot vanished. Placement describes the PAGE, not the ASSET."""
    candidate = ladder.LadderCandidate(
        url="https://linear.app/logo.svg", rung="HEADER", fmt="svg",
        background_context="rgb(8, 9, 10)", background_source="rendered:computed-behind-asset",
        appearance={"verdict": "adaptive", "detail": "currentColor present among 2 fills"},
    )
    variant, basis, rank = ladder.classify_variant(candidate)

    assert variant == "adaptive"
    assert rank == 2
    assert "placement describes the page" in basis


def test_a_baked_colour_mark_on_a_contrasting_footer_is_the_opposite_variant():
    """The footer-as-oracle rule, narrowed: it holds for a mark with baked-in
    colour, and only ranks below adaptive detection."""
    candidate = ladder.LadderCandidate(
        url="https://acme.com/logo-footer.svg", rung="FOOTER", fmt="svg",
        background_context="rgb(1, 15, 48)", background_source="rendered:computed-behind-asset",
        appearance={"verdict": "unknown"},
    )
    variant, _, rank = ladder.classify_variant(candidate)

    assert variant == "dark"
    assert rank == 3


def test_an_explicit_prefers_color_scheme_source_wins_outright():
    html = (
        "<header><picture>"
        '<source media="(prefers-color-scheme: dark)" srcset="/acme-logo-white.svg">'
        '<img src="/acme-logo.svg" alt="Acme" width="160" height="32">'
        "</picture></header>"
    )
    candidates = ladder.harvest(html, "https://acme.com/")
    dark = [c for c in candidates if c.theme_signal == "prefers-dark-source"]

    assert len(dark) == 1
    assert dark[0].url.endswith("acme-logo-white.svg")
    assert ladder.classify_variant(dark[0])[0] == "dark"


def test_a_named_reversed_asset_fills_the_dark_slot():
    html = (
        '<header><a href="/"><img src="/acme-logo.svg" alt="Acme" width="160" height="32"></a></header>'
        '<footer><img src="/acme-logo-white.svg" alt="Acme" width="160" height="32"></footer>'
    )
    fetched = {
        "https://acme.com/acme-logo.svg": (_wordmark_svg(fill="#101820"), "image/svg+xml"),
        "https://acme.com/acme-logo-white.svg": (_wordmark_svg(fill="#ffffff"), "image/svg+xml"),
    }
    _, resolution = _resolve(html, fetched)

    assert resolution.slots["dark"] is not None
    assert resolution.slots["dark"].candidate.url.endswith("acme-logo-white.svg")
    assert resolution.slots["dark"].provenance == "genuine"
    assert resolution.slots["light"].candidate.url.endswith("acme-logo.svg")


# ---------------------------------------------------------------------------
# lockup classification
# ---------------------------------------------------------------------------


def test_a_symbol_plus_text_gap_classifies_as_a_full_lockup():
    candidate = ladder.LadderCandidate(
        url="https://acme.com/acme-logo.svg", fmt="svg", width=200, height=40,
        body=_lockup_svg(),
    )
    verdict, evidence = ladder.analyze_lockup(candidate)

    assert verdict == "full_lockup"
    assert evidence["biggest_gap"] > evidence["median_other_gap"]


def test_uniform_letter_gaps_classify_as_a_wordmark():
    candidate = ladder.LadderCandidate(
        url="https://acme.com/acme-logo.svg", fmt="svg", width=160, height=32,
        body=_wordmark_svg(),
    )
    assert ladder.analyze_lockup(candidate)[0] == "wordmark"


def test_the_declared_box_wins_when_the_rasterizer_disagrees_by_more_than_2x():
    """Anthropic's 143x16 full wordmark rasterized to an ink aspect of 1.40 and
    was classified a "symbol", putting the full wordmark in the mark slot."""
    # A 143x16 declared box holding a single small square of ink.
    candidate = ladder.LadderCandidate(
        url="https://anthropic.com/wordmark.svg", fmt="svg", width=143, height=16,
        body=_svg('<rect x="0" y="0" width="16" height="16" fill="#141413"/>', 143, 16),
    )
    verdict, evidence = ladder.analyze_lockup(candidate)

    assert evidence["effective_aspect_source"] == "browser/declared box (rasterizer disagreed)"
    assert verdict != "symbol"


def test_aspect_plausibility_measures_ink_not_the_padded_box():
    """linear.app's real lockup ships in a 400x22 SVG whose artwork is only
    ~88px wide; the padded box reads as aspect 18 and disqualified it."""
    candidate = ladder.LadderCandidate(
        url="https://linear.app/logo.svg", rung="HEADER", fmt="svg",
        width=400, height=22, byte_len=4096,
        body=_svg('<rect x="0" y="0" width="88" height="22" fill="#101820"/>', 400, 22),
    )
    candidate.lockup, candidate.lockup_evidence = ladder.analyze_lockup(candidate)
    _, hits = ladder.junk_assessment(candidate)

    assert not any("implausible" in hit for hit in hits)


# ---------------------------------------------------------------------------
# registrable domains
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.acme.com/x", "acme.com"),
        ("cdn.assets.acme.com", "acme.com"),
        ("acme.co.uk", "acme.co.uk"),
        ("https://cdn.acme.co.uk/logo.svg", "acme.co.uk"),
        ("us.github.io", "us.github.io"),
        ("goodmancampbell.com", "goodmancampbell.com"),
        ("https://www.insighthealth.ai/", "insighthealth.ai"),
        ("", ""),
    ],
)
def test_registrable_domain(value, expected):
    assert ladder.registrable_domain(value) == expected


def test_company_tokens_read_the_organisation_label():
    assert "acme" in ladder.company_tokens("www.acme.co.uk")
    assert "goodmancampbell" in ladder.company_tokens("goodmancampbell.com")
    assert {"goodman", "campbell"} <= ladder.company_tokens(
        "goodmancampbell.com", "Goodman Campbell Brain and Spine"
    )


# ---------------------------------------------------------------------------
# optional brand pages must not discard logos harvested from a successful page
# ---------------------------------------------------------------------------


def _fetch_static_site(monkeypatch, responses, requested):
    """Keep the real fetcher and SSRF guard; substitute DNS and HTTP transport only."""
    from lumen_ingestion.capture import net

    async def public_dns(host, port):
        return ["93.184.216.34"]

    def respond(request):
        url = str(request.url)
        requested.append(url)
        response = responses.get(url, httpx.Response(404))
        if isinstance(response, Exception):
            raise response
        return response

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await ladder.fetch_logo_family(
                "https://acme.com/", company_name="Acme Robotics", client=client,
            )

    monkeypatch.setattr(net, "_resolve_all", public_dns)
    return asyncio.run(run())


@pytest.mark.parametrize("redirected", [False, True])
@pytest.mark.parametrize("optional_failure", ["not_found", "timeout"])
def test_homepage_logo_survives_optional_page_fetch_failures(
    monkeypatch, redirected, optional_failure,
):
    logo_url = "https://assets.example.net/acme-logo.svg"
    final_url = "https://acme.com/overview/default.aspx" if redirected else "https://acme.com/"
    responses = {
        final_url: httpx.Response(200, text=(
            '<title>Acme Robotics</title><header><a href="/">'
            '<img src="//assets.example.net/acme-logo.svg" alt="Acme Robotics">'
            '</a></header>'
        )),
        logo_url: httpx.Response(
            200, content=_wordmark_svg(), headers={"content-type": "image/svg+xml"},
        ),
    }
    if redirected:
        responses["https://acme.com/"] = httpx.Response(
            302, headers={"location": "/overview/default.aspx"},
        )
    if optional_failure == "timeout":
        responses["https://acme.com/brand"] = httpx.ReadTimeout("fixture " * 1000)
    requested = []

    result = _fetch_static_site(monkeypatch, responses, requested)

    assert result.status == "resolved"
    assert result.slots["light"].candidate.url == logo_url
    assert result.slots["light"].body == _wordmark_svg()
    assert "https://acme.com/press" in requested
    notes = [note for note in result.notes if "optional brand page" in note]
    assert len(notes) == 2
    assert all(len(note) <= 240 for note in notes)
    assert all("fixture" not in note for note in notes)


def test_later_optional_page_can_supply_a_logo_after_an_earlier_404(monkeypatch):
    requested = []
    result = _fetch_static_site(monkeypatch, {
        "https://acme.com/": httpx.Response(200, text="<title>Acme Robotics</title>"),
        "https://acme.com/press": httpx.Response(200, text=(
            '<header><img src="/acme-logo.svg" alt="Acme Robotics"></header>'
        )),
        "https://acme.com/acme-logo.svg": httpx.Response(
            200, content=_wordmark_svg(), headers={"content-type": "image/svg+xml"},
        ),
    }, requested)

    assert result.status == "resolved"
    assert result.slots["light"].candidate.url == "https://acme.com/acme-logo.svg"
    assert result.slots["light"].candidate.rung == "BRAND_PAGE"
    assert requested.index("https://acme.com/brand") < requested.index("https://acme.com/press")


def test_initial_page_failure_still_aborts_logo_discovery(monkeypatch):
    from lumen_ingestion.capture.net import CaptureError

    requested = []
    with pytest.raises(CaptureError) as failure:
        _fetch_static_site(monkeypatch, {}, requested)

    assert failure.value.code == "LUMI0503"
    assert requested == ["https://acme.com/"]


def test_optional_page_redirect_to_private_address_still_fails_closed(monkeypatch):
    from lumen_ingestion.capture.net import CaptureError

    requested = []
    with pytest.raises(CaptureError) as failure:
        _fetch_static_site(monkeypatch, {
            "https://acme.com/": httpx.Response(200, text="<title>Acme Robotics</title>"),
            "https://acme.com/brand": httpx.Response(
                302, headers={"location": "http://127.0.0.1/internal"},
            ),
        }, requested)

    assert failure.value.code == "LUMI0501"
    assert requested == ["https://acme.com/", "https://acme.com/brand"]


def test_optional_page_size_limit_still_fails_closed(monkeypatch):
    from lumen_ingestion.capture import net

    monkeypatch.setattr(net, "PAGE_MAX_BYTES", 100)
    with pytest.raises(net.CaptureError) as failure:
        _fetch_static_site(monkeypatch, {
            "https://acme.com/": httpx.Response(200, text="<title>Acme Robotics</title>"),
            "https://acme.com/brand": httpx.Response(200, content=b"x" * 101),
        }, [])

    assert failure.value.code == "LUMI0507"
