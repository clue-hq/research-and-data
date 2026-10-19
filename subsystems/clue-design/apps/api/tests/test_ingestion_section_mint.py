"""The pure halves of fragment minting (clone-fidelity F2.2).

Task 11 says WHERE a page's sections are; this is what turns one of those records into the
material a fragment artifact is built from — the rules that style it, the spots inside it a
document may re-fill, the map from the tokens it writes to the bytes we hold, and the crop of
F0's screenshot that shows it. No database, no byte store, no browser: every function here is
text and geometry in, text and geometry out. The durable half — registry rows, blobs, the kit
approval cascade — is ``test_ingestion_fragment_pipeline.py``'s business.
"""

from __future__ import annotations

import hashlib

import pytest

from lumen_ingestion.sections import mint as mint_module
from lumen_ingestion.sections import budget as budget_module
from lumen_ingestion.sections.budget import MINT_BUDGET_CODE, PageWeight
from lumen_ingestion.sections.cssmatch import MatchedCss, rules_for_subtree
from lumen_ingestion.sections.segment import segment_page

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


class _Sheet:
    """The ``LoadedStylesheet`` shape, duck-typed (url + text) like everything in F2."""

    def __init__(self, url: str, text: str) -> None:
        self.url = url
        self.text = text


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


HERO_HTML = (
    '<section class="hero_wrap" id="hero">'
    '<h1 class="heading-xl">Ship faster</h1>'
    '<p class="body-copy">We help teams ship.</p>'
    '<a class="button is-primary" href="/demo"><span class="button_label">Book a demo</span></a>'
    "</section>"
)


# --------------------------------------------------------------------------- #
# CSS rule matching — which of the page's rules belong to this subtree
# --------------------------------------------------------------------------- #


def test_a_rule_whose_rightmost_compound_lives_in_the_subtree_is_kept() -> None:
    sheets = [
        _Sheet(
            "https://site.example/main.css",
            ".heading-xl { font-size: 4rem }\n.footer_link { color: grey }",
        )
    ]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert ".heading-xl" in matched.css
    assert ".footer_link" not in matched.css
    assert matched.rules_considered == 2
    assert matched.rules_kept == 1


def test_a_descendant_selector_is_judged_on_its_rightmost_compound_only() -> None:
    """``.page-wrapper .hero_wrap .body-copy`` styles this subtree even though neither
    ancestor is inside it — the ancestors are context the page supplies, and re-checking them
    against a subtree that by construction does not contain its own ancestors would drop every
    real page's rules."""
    sheets = [_Sheet("s.css", ".page-wrapper .hero_wrap .body-copy { line-height: 1.6 }")]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert ".body-copy" in matched.css


def test_a_selector_list_is_kept_when_any_one_of_its_parts_matches() -> None:
    sheets = [_Sheet("s.css", "h1, h2, .nav_link { margin: 0 }")]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert "h1" in matched.css


def test_a_tag_selector_matches_only_tags_the_subtree_actually_has() -> None:
    sheets = [_Sheet("s.css", "h1 { margin: 0 }\ntable { border: 0 }")]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert "h1" in matched.css
    assert "table" not in matched.css


def test_a_compound_needs_every_one_of_its_classes_present() -> None:
    sheets = [
        _Sheet("s.css", "a.button.is-primary { color: white }\na.button.is-ghost { color: blue }")
    ]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert "is-primary" in matched.css
    assert "is-ghost" not in matched.css


def test_pseudo_classes_and_attribute_selectors_are_ignored_rather_than_guessed_at() -> None:
    """Over-inclusion is the safe direction: a hover rule we keep costs bytes, one we drop
    breaks the section's behaviour and nobody can see why."""
    sheets = [_Sheet("s.css", '.button:hover::after { content: "" }\na[href^="/demo"] { x: 1 }')]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert ".button:hover::after" in matched.css
    assert 'a[href^="/demo"]' in matched.css


def test_a_functional_pseudo_carrying_a_selector_list_is_kept_unconditionally() -> None:
    sheets = [_Sheet("s.css", ".wrap :is(h1, h2) { margin: 0 }")]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert ":is(" in matched.css


def test_document_level_rules_are_kept_because_the_scoper_re_anchors_them() -> None:
    """``:root`` holds a modern section's custom properties. Dropping it here — the subtree
    contains no ``<html>`` — would strip the section's entire colour scheme before the scoper
    ever got the chance to rewrite it onto the wrapper."""
    sheets = [_Sheet("s.css", ":root { --brand: #0af }\nhtml { font-size: 16px }")]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert "--brand" in matched.css
    assert "font-size: 16px" in matched.css


def test_a_media_query_is_kept_with_only_the_rules_inside_it_that_match() -> None:
    sheets = [
        _Sheet(
            "s.css",
            "@media (max-width: 40em) { .heading-xl { font-size: 2rem } "
            ".footer_link { color: red } }",
        )
    ]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert "@media (max-width: 40em)" in matched.css
    assert "font-size: 2rem" in matched.css
    assert ".footer_link" not in matched.css


def test_a_media_query_none_of_whose_rules_match_is_dropped_whole() -> None:
    sheets = [_Sheet("s.css", "@media print { .footer_link { color: red } }")]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert "@media" not in matched.css


def test_font_faces_and_keyframes_ride_along_because_they_are_global_by_nature() -> None:
    """A face the section's rules ask for must be defined, and a keyframe name they animate
    must exist. Neither has a selector to match, so neither can be matched — they are kept."""
    sheets = [
        _Sheet(
            "s.css",
            "@font-face { font-family: Inter; src: url(inter.woff2) }\n"
            "@keyframes fade { from { opacity: 0 } }\n"
            ".heading-xl { animation: fade 1s }",
        )
    ]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert "@font-face" in matched.css
    assert "@keyframes fade" in matched.css


def test_every_stylesheet_is_read_in_order_so_the_cascade_survives() -> None:
    sheets = [
        _Sheet("a.css", ".heading-xl { color: red }"),
        _Sheet("b.css", ".heading-xl { color: blue }"),
    ]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert matched.css.index("red") < matched.css.index("blue")
    assert matched.sheets_read == 2


def test_matching_the_same_subtree_twice_produces_the_same_bytes() -> None:
    sheets = [_Sheet("s.css", ".heading-xl { color: red }\n@media print { h1 { color: blue } }")]
    first = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    second = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert first.css == second.css


def test_an_unparseable_sheet_costs_a_note_and_not_the_section() -> None:
    sheets = [_Sheet("s.css", ".heading-xl { color: red } @@@ broken")]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert ".heading-xl" in matched.css
    assert isinstance(matched, MatchedCss)


def test_a_section_that_matches_nothing_yields_empty_css_rather_than_everything() -> None:
    sheets = [_Sheet("s.css", ".footer_link { color: grey }")]
    matched = rules_for_subtree(sheets, subtree_html="<section><p>x</p></section>")
    assert matched.css.strip() == ""
    assert matched.rules_kept == 0


def test_the_matcher_reads_the_subtree_the_segmenter_actually_hands_it() -> None:
    """End to end with Task 11's own output, so the two halves cannot drift apart on what a
    section's markup is."""
    page = f'<html><body><nav class="nav_component"><a href="/">Home</a></nav>{HERO_HTML}</body></html>'
    segmentation = segment_page(page, page_url="https://site.example/")
    hero = segmentation.by_role("hero")[0]
    from lumen_ingestion.sections.segment import resolve_section

    node = resolve_section(page, hero)
    assert node is not None
    sheets = [_Sheet("s.css", ".heading-xl { color: red }\n.nav_component { display: flex }")]
    matched = rules_for_subtree(sheets, subtree_html=node.html or "")
    assert ".heading-xl" in matched.css
    assert ".nav_component" not in matched.css


# --------------------------------------------------------------------------- #
# Slot detection — Ploy's shallow refactor, done mechanically
# --------------------------------------------------------------------------- #

from lumen_api.fragments import annotate_fragment_slots, sanitize_fragment_html  # noqa: E402
from lumen_ingestion.sections.slotdetect import detect_slots  # noqa: E402


def _keys(html: str) -> dict[str, str]:
    """``{slot key: kind}`` for one piece of already-sanitized markup."""
    return {spec.key: spec.kind for spec in detect_slots(html).specs}


def test_the_dominant_heading_becomes_the_headline_slot() -> None:
    assert _keys(HERO_HTML)["headline"] == "text"


def test_card_headings_are_independently_editable_without_consuming_ctas_or_images() -> None:
    html = (
        '<section><h2>Source features</h2><article><h3>First feature</h3><p>First copy</p>'
        '<a class="button" href="/one"><span>First action</span></a></article>'
        '<article><h3>Second feature</h3><p>Second copy</p>'
        '<a class="button" href="/two"><span>Second action</span></a></article></section>'
    )
    annotated = annotate_fragment_slots(html, detect_slots(html).specs)
    values = {key: spec["fallback"] for key, spec in annotated.slot_manifest.items()}
    assert values["headline"] == "Source features"
    assert values["headline_2"] == "First feature"
    assert values["headline_3"] == "Second feature"
    assert values["cta_href"] == "/one"
    assert values["cta_href_2"] == "/two"
    assert values["cta_label_2"] == "Second action"
    assert values["body_2"] == "Second copy"


@pytest.mark.parametrize("contents", [
    'Book a demo<svg><title>Arrow</title></svg>',
    '<span>Book a demo<svg><title>Arrow</title></svg></span>',
    'Book <span>a demo</span>',
])
def test_cta_label_detection_does_not_consume_an_icon_or_a_partial_label(contents) -> None:
    html = f'<section><a class="button" href="/demo">{contents}</a></section>'
    assert "cta_href" in _keys(html)
    assert "cta_label" not in _keys(html)


def test_cta_label_detection_ignores_icon_titles_beside_a_real_label() -> None:
    html = '<section><a class="button" href="/demo"><svg><title>Arrow</title></svg><span>Book a demo</span></a></section>'
    annotated = annotate_fragment_slots(html, detect_slots(html).specs)
    assert annotated.slot_manifest["cta_label"]["fallback"] == "Book a demo"


def test_a_section_with_no_h1_falls_back_to_its_strongest_heading() -> None:
    keys = _keys('<section><h2 class="t">Proof</h2><p>Copy</p></section>')
    assert keys["headline"] == "text"
    detected = detect_slots('<section><h2 class="t">Proof</h2><p>Copy</p></section>')
    headline = next(spec for spec in detected.specs if spec.key == "headline")
    annotated = annotate_fragment_slots(
        '<section><h2 class="t">Proof</h2><p>Copy</p></section>', [headline]
    )
    assert annotated.slot_manifest["headline"]["fallback"] == "Proof"


def test_paragraphs_become_numbered_body_slots_in_document_order() -> None:
    keys = _keys("<section><p>One</p><p>Two</p><p>Three</p></section>")
    assert keys["body"] == "text"
    assert keys["body_2"] == "text"
    assert keys["body_3"] == "text"


def test_an_empty_paragraph_is_not_an_editable_spot() -> None:
    assert "body_2" not in _keys("<section><p>One</p><p>   </p></section>")


def test_rehosted_images_become_numbered_image_slots() -> None:
    digest = _digest("img")
    html = (
        f'<section><img src="/asset-store/{digest}">'
        f'<img src="/asset-store/{_digest("img2")}"></section>'
    )
    keys = _keys(html)
    assert keys["image"] == "image"
    assert keys["image_2"] == "image"


def test_an_image_with_no_rehosted_src_is_skipped_rather_than_refused() -> None:
    """The annotator REFUSES an image slot whose element has no resolvable fallback. Detection
    must therefore not offer one — a section with a decorative inline SVG is still a section."""
    html = '<section><svg><circle></circle></svg><p>Copy</p></section>'
    assert "image" not in _keys(html)
    assert "body" in _keys(html)


def test_a_call_to_action_yields_its_target_and_its_label() -> None:
    keys = _keys(HERO_HTML)
    assert keys["cta_href"] == "href"
    assert keys["cta_label"] == "text"


def test_the_cta_target_and_its_label_never_land_on_the_same_element() -> None:
    """One element holds one marker (``data-lumen-slot`` is a single attribute), so the href
    goes on the anchor and the label on the element inside it that carries the words."""
    specs = {spec.key: spec.selector for spec in detect_slots(HERO_HTML).specs}
    assert specs["cta_href"] != specs["cta_label"]
    annotated = annotate_fragment_slots(HERO_HTML, detect_slots(HERO_HTML).specs)
    assert annotated.slot_manifest["cta_href"]["fallback"] == "/demo"
    assert annotated.slot_manifest["cta_label"]["fallback"] == "Book a demo"


def test_an_anchor_whose_words_are_its_own_text_yields_the_target_only() -> None:
    """No inner element means no second marker is available. The href is the half that MUST be
    editable — a cloned CTA pointing at the site it was cloned from is not shippable — so the
    href takes the anchor and the label is reported as unavailable rather than silently absent."""
    html = '<section><a class="button" href="/demo">Book a demo</a></section>'
    detected = detect_slots(html)
    keys = {spec.key for spec in detected.specs}
    assert "cta_href" in keys
    assert "cta_label" not in keys
    assert any("cta_label" in note for note in detected.notes)


def test_a_plain_navigation_link_is_not_a_call_to_action() -> None:
    html = '<nav><a href="/pricing">Pricing</a><a href="/docs">Docs</a></nav>'
    assert "cta_href" not in _keys(html)


def test_the_whole_section_gets_a_visibility_slot() -> None:
    assert _keys(HERO_HTML)["visible"] == "visibility"


def test_no_slot_is_minted_inside_another_slot_that_would_consume_it() -> None:
    """LUMW0417: a marker inside a slot whose bound value REPLACES the subtree can never be
    applied. A text slot replaces its content, so an image inside the headline is not offered.
    (An href slot rewrites an attribute and consumes nothing, which is why ``cta_label`` inside
    ``cta_href``'s anchor is legal — and why the check is about consumption, not nesting.)"""
    digest = _digest("inline")
    html = f'<section><h1>Ship <img src="/asset-store/{digest}"> faster</h1></section>'
    keys = _keys(html)
    assert keys["headline"] == "text"
    assert "image" not in keys


def test_every_detected_slot_actually_resolves_in_the_markup_it_was_read_from() -> None:
    """The generated selectors are the contract with the annotator. If one of them missed, the
    annotator would refuse the fragment — so this is the test that keeps minting alive."""
    detected = detect_slots(HERO_HTML)
    annotated = annotate_fragment_slots(HERO_HTML, detected.specs)
    assert set(annotated.slot_manifest) == {spec.key for spec in detected.specs}


def test_detection_survives_two_sections_that_look_alike() -> None:
    html = (
        "<section><div><p>First</p></div><div><p>Second</p></div></section>"
    )
    detected = detect_slots(html)
    annotated = annotate_fragment_slots(html, detected.specs)
    assert annotated.slot_manifest["body"]["fallback"] == "First"
    assert annotated.slot_manifest["body_2"]["fallback"] == "Second"


def test_a_section_with_nothing_editable_yields_no_slots_and_that_is_legal() -> None:
    detected = detect_slots("<section><hr></section>")
    assert [spec.key for spec in detected.specs] == ["visible"]


def test_detection_is_deterministic() -> None:
    first = [(s.key, s.kind, s.selector) for s in detect_slots(HERO_HTML).specs]
    second = [(s.key, s.kind, s.selector) for s in detect_slots(HERO_HTML).specs]
    assert first == second


def test_slot_count_is_bounded_far_below_the_engine_cap() -> None:
    html = "<section>" + "".join(f"<p>Para {n}</p>" for n in range(50)) + "</section>"
    detected = detect_slots(html)
    assert len(detected.specs) <= 64
    assert any("capped" in note or "more" in note for note in detected.notes)


def test_every_minted_key_obeys_the_engine_grammar() -> None:
    from lumen_api.fragments import slot_key_is_valid

    html = "<section>" + "".join(f"<p>Para {n}</p>" for n in range(5)) + "</section>"
    assert all(slot_key_is_valid(spec.key) for spec in detect_slots(html).specs)


def test_detection_runs_on_sanitized_markup_so_a_dropped_element_is_never_slotted() -> None:
    sanitized = sanitize_fragment_html(
        "<section><h1>Hi</h1><form><p>inside a form</p></form><p>Real</p></section>",
        rehosted={},
    )
    annotated = annotate_fragment_slots(sanitized.html, detect_slots(sanitized.html).specs)
    assert annotated.slot_manifest["body"]["fallback"] == "Real"


# --------------------------------------------------------------------------- #
# The reference harvest — raw token → the bytes we hold
# --------------------------------------------------------------------------- #

from lumen_ingestion.sections.mint import (  # noqa: E402
    SECTION_MINT_CAP,
    CapturedAsset,
    build_reference_harvest,
    captured_assets,
    crop_extent,
    crop_preview,
    mint_sections,
)

PAGE_URL = "https://site.example/pricing"
HERO_JPG = "https://site.example/img/hero.jpg"
SPRITE_PNG = "https://cdn.example/assets/sprite.png"


def test_a_relative_src_is_keyed_on_the_token_the_page_actually_wrote() -> None:
    """EXACT-MATCH is the reference gate's contract: the key is the spelling the source used,
    not a canonicalised URL, because normalising here would mean guessing which of two
    spellings the rehoster meant. Resolution happens only to FIND the bytes."""
    harvest = build_reference_harvest(
        subtree_html='<section><img src="/img/hero.jpg"></section>',
        page_url=PAGE_URL,
        css_blocks=(),
        captured={HERO_JPG: CapturedAsset(url=HERO_JPG, data=b"jpg", content_type="image/jpeg")},
    )
    assert harvest.resolved == {"/img/hero.jpg": HERO_JPG}
    assert harvest.missing == ()


def test_a_css_url_resolves_against_its_own_stylesheet_not_the_page() -> None:
    """``/assets/sprite.png`` in a sheet served from a CDN is a CDN url. Resolving it against
    the page would look up bytes nobody fetched and refuse a section that is perfectly fine."""
    harvest = build_reference_harvest(
        subtree_html="<section></section>",
        page_url=PAGE_URL,
        css_blocks=(("https://cdn.example/site.css", ".a { background: url(/assets/sprite.png) }"),),
        captured={
            SPRITE_PNG: CapturedAsset(url=SPRITE_PNG, data=b"png", content_type="image/png")
        },
    )
    assert harvest.resolved == {"/assets/sprite.png": SPRITE_PNG}


def test_a_relative_stylesheet_url_is_itself_resolved_against_the_page_first() -> None:
    """A capture records a sheet's url as the page wrote it, so ``<link href="/s.css">`` arrives
    here as ``/s.css``. Using that raw as a base makes every reference inside the sheet resolve
    to nothing, and every section that cites a webfont refuses."""
    harvest = build_reference_harvest(
        subtree_html="<section></section>",
        page_url=PAGE_URL,
        css_blocks=(("/s.css", "@font-face { src: url(/fonts/inter.woff2) }"),),
        captured={
            "https://site.example/fonts/inter.woff2": CapturedAsset(
                url="https://site.example/fonts/inter.woff2", data=b"woff2", content_type=None
            )
        },
    )
    assert harvest.resolved == {"/fonts/inter.woff2": "https://site.example/fonts/inter.woff2"}


def test_an_inline_stylesheet_resolves_against_the_page() -> None:
    harvest = build_reference_harvest(
        subtree_html="<section></section>",
        page_url=PAGE_URL,
        css_blocks=(("inline:0", ".a { background: url(/img/hero.jpg) }"),),
        captured={HERO_JPG: CapturedAsset(url=HERO_JPG, data=b"jpg", content_type="image/jpeg")},
    )
    assert harvest.resolved == {"/img/hero.jpg": HERO_JPG}


def test_every_srcset_rung_is_harvested_not_just_the_first() -> None:
    two_x = "https://site.example/img/hero@2x.jpg"
    harvest = build_reference_harvest(
        subtree_html='<section><img srcset="/img/hero.jpg 1x, /img/hero@2x.jpg 2x"></section>',
        page_url=PAGE_URL,
        css_blocks=(),
        captured={
            HERO_JPG: CapturedAsset(url=HERO_JPG, data=b"a", content_type=None),
            two_x: CapturedAsset(url=two_x, data=b"b", content_type=None),
        },
    )
    assert set(harvest.resolved) == {"/img/hero.jpg", "/img/hero@2x.jpg"}


def test_an_inline_style_background_is_harvested_like_any_other_reference() -> None:
    harvest = build_reference_harvest(
        subtree_html='<section style="background-image:url(/img/hero.jpg)"></section>',
        page_url=PAGE_URL,
        css_blocks=(),
        captured={HERO_JPG: CapturedAsset(url=HERO_JPG, data=b"a", content_type=None)},
    )
    assert "/img/hero.jpg" in harvest.resolved


def test_a_data_uri_is_carried_as_bytes_to_rehost_rather_than_refused() -> None:
    """The sanitizer fails closed on a ``data:`` src — self-contained bytes that dodged custody
    are still bytes we do not hold. F1 recorded the fix as F2's: rehost them at mint time.
    Webflow and Next put an LQIP placeholder on every image, so this is not an edge case."""
    uri = "data:image/png;base64,iVBORw0KGgo="
    harvest = build_reference_harvest(
        subtree_html=f'<section><img src="{uri}"></section>',
        page_url=PAGE_URL,
        css_blocks=(),
        captured={},
    )
    assert uri in harvest.inline
    payload, media_type = harvest.inline[uri]
    assert payload == b"\x89PNG\r\n\x1a\n"
    assert media_type == "image/png"
    assert harvest.missing == ()


def test_a_reference_nothing_was_captured_for_is_named_not_swallowed() -> None:
    harvest = build_reference_harvest(
        subtree_html='<section><img src="/img/never-fetched.png"></section>',
        page_url=PAGE_URL,
        css_blocks=(),
        captured={},
    )
    assert harvest.missing == ("/img/never-fetched.png",)


def test_a_same_document_fragment_reference_is_not_a_byte_reference() -> None:
    harvest = build_reference_harvest(
        subtree_html='<section><svg><use href="#icon"></use></svg></section>',
        page_url=PAGE_URL,
        css_blocks=(),
        captured={},
    )
    assert harvest.missing == ()
    assert harvest.resolved == {}


def test_an_already_rehosted_reference_needs_no_map_entry() -> None:
    harvest = build_reference_harvest(
        subtree_html=f'<section><img src="/asset-store/{_digest("x")}"></section>',
        page_url=PAGE_URL,
        css_blocks=(),
        captured={},
    )
    assert harvest.missing == ()
    assert harvest.resolved == {}


def test_one_token_that_would_resolve_two_ways_is_dropped_rather_than_guessed() -> None:
    """The same spelling in the page and in a CDN stylesheet are two different files. The
    rehost map is flat by contract, so a token with two answers gets no answer — which makes
    the fragment refuse loudly instead of serving one file's bytes under the other's name."""
    page_side = "https://site.example/shared.png"
    sheet_side = "https://cdn.example/shared.png"
    harvest = build_reference_harvest(
        subtree_html='<section><img src="/shared.png"></section>',
        page_url=PAGE_URL,
        css_blocks=(("https://cdn.example/site.css", ".a { background: url(/shared.png) }"),),
        captured={
            page_side: CapturedAsset(url=page_side, data=b"a", content_type=None),
            sheet_side: CapturedAsset(url=sheet_side, data=b"b", content_type=None),
        },
    )
    assert harvest.conflicts == ("/shared.png",)
    assert "/shared.png" not in harvest.resolved


def test_captured_assets_reads_a_snapshot_and_leaves_the_screenshot_out_of_it() -> None:
    class _Download:
        def __init__(self, url, kind, data, content_type=None):
            import base64

            self.url = url
            self.kind = kind
            self.bytes_b64 = base64.b64encode(data).decode("ascii")
            self.content_type = content_type

    class _Snapshot:
        downloads = [
            _Download(HERO_JPG, "image", b"jpg", "image/jpeg"),
            _Download("https://site.example/shot.png", "screenshot", b"png", "image/png"),
        ]

    assets = captured_assets(_Snapshot())
    assert set(assets) == {HERO_JPG}
    assert assets[HERO_JPG].data == b"jpg"


# --------------------------------------------------------------------------- #
# Preview crops
# --------------------------------------------------------------------------- #


def _png(width: int, height: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


BANDED_PAGE = (
    "<html><body>"
    '<header class="nav_component"><a href="/">Home</a><a href="/x">X</a></header>'
    '<main><section class="section_home-hero"><h1>Ship</h1><p>Copy</p></section>'
    '<section class="section_proof"><p>Trusted by</p></section></main>'
    '<footer class="footer_component"><p>&copy; 2026 Example</p></footer>'
    "</body></html>"
)


#: The probe records DOCUMENT-absolute tops (`rect.top + scrollY`), and it roots at `<main>` —
#: so on this semantic page the hero starts below the unmeasured nav, exactly as it does live.
_BANDS = [
    {"index": 0, "tag": "section", "id": "", "classes": "section_home-hero", "top": 80.0,
     "height": 600.0, "bgImage": False},
    {"index": 1, "tag": "section", "id": "", "classes": "section_proof", "top": 680.0,
     "height": 300.0, "bgImage": False},
]


def _banded_segmentation():
    bands = _BANDS
    from lumen_ingestion.sections.bands import measured_bands

    return segment_page(
        BANDED_PAGE,
        page_url=PAGE_URL,
        bands=measured_bands({"bands": bands}),
        viewport_width=1200,
    )


def test_a_measured_section_crops_at_the_extent_the_browser_reported() -> None:
    segmentation = _banded_segmentation()
    hero = segmentation.by_role("hero")[0]
    extent = crop_extent(segmentation, hero)
    assert extent is not None
    assert (extent.top_px, extent.bottom_px) == (80.0, 680.0)
    assert extent.basis == "measured"


def test_a_nav_with_no_measured_geometry_is_inferred_above_the_first_band() -> None:
    """LUMI0524, Task 11's carry: the capture probe roots at ``<main>``, so on a semantic page
    the two most-cloned sections of all — the nav and the footer — are never measured. A
    fragment with no preview is a fragment nobody picks, so the extent is inferred and the
    basis says so rather than pretending it was measured."""
    segmentation = _banded_segmentation()
    nav = segmentation.by_role("nav")[0]
    assert nav.geometry is None
    extent = crop_extent(segmentation, nav)
    assert extent is not None
    assert (extent.top_px, extent.bottom_px) == (0.0, 80.0)
    assert extent.basis == "inferred-above-first-band"


def test_a_footer_with_no_measured_geometry_runs_to_the_bottom_of_the_page() -> None:
    segmentation = _banded_segmentation()
    footer = segmentation.by_role("footer")[0]
    extent = crop_extent(segmentation, footer)
    assert extent is not None
    assert extent.top_px == 980.0
    assert extent.bottom_px is None  # "to the end of the screenshot"
    assert extent.basis == "inferred-below-last-band"


def test_an_unmeasured_middle_section_has_no_derivable_crop() -> None:
    """Guessing a middle section's extent would produce a preview of the wrong section, which
    is worse than no preview: the picker would show a lie."""
    segmentation = segment_page(BANDED_PAGE, page_url=PAGE_URL, viewport_width=1200)
    proof = [s for s in segmentation.sections if s.role not in ("nav", "footer")][-1]
    assert crop_extent(segmentation, proof) is None


def test_the_crop_scales_the_shot_to_the_width_the_page_was_measured_at() -> None:
    from io import BytesIO

    from PIL import Image
    from lumen_ingestion.sections.mint import CropExtent

    shot = _png(2400, 1800)  # a 2x device-pixel-ratio full-page screenshot
    cropped = crop_preview(
        shot, CropExtent(top_px=0.0, bottom_px=600.0, basis="measured"), viewport_width=1200
    )
    assert cropped is not None
    image = Image.open(BytesIO(cropped))
    assert image.width / image.height == pytest.approx(2400 / 1200, rel=0.05)


def test_a_crop_that_falls_outside_the_screenshot_yields_nothing_rather_than_a_stripe() -> None:
    from lumen_ingestion.sections.mint import CropExtent

    shot = _png(1200, 400)
    assert (
        crop_preview(
            shot, CropExtent(top_px=900.0, bottom_px=1200.0, basis="measured"), viewport_width=1200
        )
        is None
    )


def test_a_tall_crop_is_scaled_down_so_a_preview_is_a_preview() -> None:
    from io import BytesIO

    from PIL import Image
    from lumen_ingestion.sections.mint import MAX_PREVIEW_WIDTH, CropExtent

    shot = _png(3000, 2000)
    cropped = crop_preview(
        shot, CropExtent(top_px=0.0, bottom_px=1000.0, basis="measured"), viewport_width=1500
    )
    assert cropped is not None
    assert Image.open(BytesIO(cropped)).width <= MAX_PREVIEW_WIDTH


# --------------------------------------------------------------------------- #
# The driver — every stage, with the durable seams injected
# --------------------------------------------------------------------------- #


class _Recorder:
    """Stands in for the F1 creation seam and the design byte store."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.registered: dict[str, bytes] = {}

    def register_bytes(self, data: bytes, media_type: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        self.registered[digest] = data
        return digest

    def create_fragment(self, **kwargs):
        from lumen_api.fragments import build_fragment_artifact

        preview = kwargs.get("preview")
        preview_digest = None if preview is None else self.register_bytes(preview, "image/png")
        artifact = build_fragment_artifact(
            html=kwargs["html"],
            css=kwargs["css"],
            rehosted=kwargs["rehosted"],
            slots=kwargs["slots"],
            preview_digest=preview_digest,
            prelude_reference=kwargs["prelude_reference"],
        )
        row = {
            "fragment_id": artifact.fragment_id,
            "status": "draft",
            "label": kwargs.get("label"),
            "provenance": dict(kwargs.get("provenance") or {}),
            "preview_digest": preview_digest,
            "payload_digest": artifact.payload_digest,
            "source_kit_id": kwargs.get("source_kit_id"),
            "source_kit_version": kwargs.get("source_kit_version"),
        }
        self.created.append({**kwargs, "row": row})
        return row, artifact


def _mint(html: str, *, screenshot: bytes | None = None, recorder=None, **overrides):
    recorder = recorder or _Recorder()
    from lumen_ingestion.sections.bands import measured_bands

    bands = measured_bands({"bands": overrides["bands"]}) if "bands" in overrides else ()
    segmentation = segment_page(html, page_url=PAGE_URL, viewport_width=1200, bands=bands)
    outcome = mint_sections(
        segmentation,
        html=html,
        stylesheets=overrides.get("stylesheets", []),
        captured=overrides.get("captured", {}),
        screenshot=screenshot,
        source_kit_id=overrides.get("source_kit_id", "brand_kit_x"),
        source_kit_version=overrides.get("source_kit_version", 1),
        register_bytes=recorder.register_bytes,
        create_fragment=recorder.create_fragment,
        limit=overrides.get("limit", SECTION_MINT_CAP),
        weight=overrides.get("weight"),
    )
    return outcome, recorder


def test_every_section_of_a_page_becomes_a_fragment_bound_to_the_kit() -> None:
    outcome, recorder = _mint(
        BANDED_PAGE, stylesheets=[_Sheet("s.css", ".section_home-hero { padding: 4rem }")]
    )
    assert [minted.role for minted in outcome.minted] == ["nav", "hero", "proof", "footer"]
    assert all(call["source_kit_id"] == "brand_kit_x" for call in recorder.created)
    assert all(call["source_kit_version"] == 1 for call in recorder.created)


def test_a_minted_fragment_carries_its_provenance_back_to_the_page_it_came_from() -> None:
    outcome, recorder = _mint(BANDED_PAGE)
    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    provenance = hero["provenance"]
    assert provenance["page_url"] == PAGE_URL
    assert provenance["dom_path"]
    assert provenance["confidence"] > 0
    assert provenance["evidence"]
    assert hero["source_url"] == PAGE_URL


def test_a_minted_fragment_is_born_a_draft_and_says_which_section_it_is() -> None:
    outcome, _ = _mint(BANDED_PAGE)
    hero = next(minted for minted in outcome.minted if minted.role == "hero")
    assert hero.status == "draft"
    assert "Ship" in hero.label


def test_one_unmintable_section_costs_that_section_and_no_other() -> None:
    """Fail-closed per section, never per job: a page with one section whose background image
    was never captured still yields the other three."""
    html = BANDED_PAGE.replace(
        '<section class="section_proof">',
        '<section class="section_proof" style="background-image:url(/never.png)">',
    )
    outcome, _ = _mint(html)
    roles = [minted.role for minted in outcome.minted]
    assert "proof" not in roles
    assert {"nav", "hero", "footer"} <= set(roles)
    assert any(diag["code"] == "LUMI0530" for diag in outcome.diagnostics)
    assert any("never.png" in str(diag) for diag in outcome.diagnostics)


def test_a_data_uri_placeholder_is_rehosted_and_the_section_mints() -> None:
    html = BANDED_PAGE.replace(
        "<h1>Ship</h1>", '<img src="data:image/png;base64,iVBORw0KGgo="><h1>Ship</h1>'
    )
    outcome, recorder = _mint(html)
    assert "hero" in [minted.role for minted in outcome.minted]
    assert any(data == b"\x89PNG\r\n\x1a\n" for data in recorder.registered.values())


def test_the_bytes_a_fragment_cites_are_put_in_custody_before_the_row_is_written() -> None:
    html = BANDED_PAGE.replace("<h1>Ship</h1>", '<img src="/img/hero.jpg"><h1>Ship</h1>')
    outcome, recorder = _mint(
        html,
        captured={HERO_JPG: CapturedAsset(url=HERO_JPG, data=b"jpg-bytes", content_type="image/jpeg")},
    )
    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    digest = hashlib.sha256(b"jpg-bytes").hexdigest()
    assert hero["rehosted"]["/img/hero.jpg"] == digest
    assert recorder.registered[digest] == b"jpg-bytes"


def test_a_preview_is_cropped_from_the_screenshot_the_capture_already_took() -> None:
    outcome, recorder = _mint(BANDED_PAGE, screenshot=_png(1200, 1400), bands=_BANDS)
    by_role = {minted.role: minted for minted in outcome.minted}
    assert by_role["hero"].preview_digest is not None
    assert by_role["hero"].preview_basis == "measured"
    # And the two sections the probe never measured still get one, from the inferred extents.
    assert by_role["nav"].preview_basis == "inferred-above-first-band"
    assert by_role["nav"].preview_digest is not None
    assert by_role["footer"].preview_basis == "inferred-below-last-band"
    assert by_role["footer"].preview_digest is not None


def test_a_section_with_no_derivable_crop_gets_a_null_preview_and_says_so() -> None:
    """F1 allows a NULL preview_digest. What it does not allow is a silent one."""
    outcome, _ = _mint(BANDED_PAGE, screenshot=None)
    assert all(minted.preview_digest is None for minted in outcome.minted)
    assert any(diag["code"] == "LUMI0531" for diag in outcome.diagnostics)


def test_the_number_of_sections_one_ingest_mints_is_capped_and_summarized() -> None:
    body = "".join(
        f'<section class="section_{n}"><h1>H{n}</h1><p>P{n}</p></section>' for n in range(20)
    )
    outcome, _ = _mint(f"<html><body><main>{body}</main></body></html>", limit=3)
    assert len(outcome.minted) == 3
    capped = [diag for diag in outcome.diagnostics if diag["code"] == "LUMI0532"]
    assert capped and "17" in capped[0]["message"]


def test_minting_the_same_page_twice_converges_on_the_same_fragments() -> None:
    first, _ = _mint(BANDED_PAGE, stylesheets=[_Sheet("s.css", ".section_proof { color: red }")])
    second, _ = _mint(BANDED_PAGE, stylesheets=[_Sheet("s.css", ".section_proof { color: red }")])
    assert [m.fragment_id for m in first.minted] == [m.fragment_id for m in second.minted]


def test_a_section_that_drifted_out_of_the_html_refuses_rather_than_minting_a_neighbour() -> None:
    segmentation = segment_page(BANDED_PAGE, page_url=PAGE_URL, viewport_width=1200)
    drifted = BANDED_PAGE.replace("<main>", '<main><section class="intruder"><p>New</p></section>')
    recorder = _Recorder()
    outcome = mint_sections(
        segmentation,
        html=drifted,
        stylesheets=[],
        captured={},
        screenshot=None,
        source_kit_id=None,
        source_kit_version=None,
        register_bytes=recorder.register_bytes,
        create_fragment=recorder.create_fragment,
    )
    assert any(
        diag["code"] == "LUMI0530" and "could not be re-found" in diag["message"]
        for diag in outcome.diagnostics
    )


def test_a_fragment_carries_the_slots_detection_found() -> None:
    outcome, recorder = _mint(BANDED_PAGE)
    hero = next(minted for minted in outcome.minted if minted.role == "hero")
    assert "headline" in hero.slot_keys
    assert "body" in hero.slot_keys
    assert "visible" in hero.slot_keys


# --------------------------------------------------------------------------- #
# Fix round 1
# --------------------------------------------------------------------------- #


TAILWIND_HTML = (
    '<section class="hero md:flex w-1/2">'
    '<h1 class="text-4xl">Ship</h1><p class="lg:mt-8">Copy</p></section>'
)


def test_an_escaped_class_selector_is_read_as_the_class_it_names() -> None:
    """I1. Tailwind writes ``.md\\:flex`` and ``.w-1\\/2`` — the backslash is a CSS identifier
    escape, and the character after it is part of the NAME. Reading the escaped ``:`` as a
    pseudo-class start silently dropped every responsive and fractional utility a real page has:
    invisible under-inclusion, which is the one failure this module exists to prevent."""
    sheets = [
        _Sheet(
            "s.css",
            ".md\\:flex { display: flex }\n"
            ".w-1\\/2 { width: 50% }\n"
            ".text-4xl { font-size: 2.25rem }\n"
            ".xl\\:hidden { display: none }\n",
        )
    ]
    matched = rules_for_subtree(sheets, subtree_html=TAILWIND_HTML)
    assert ".md\\:flex" in matched.css
    assert ".w-1\\/2" in matched.css
    assert ".text-4xl" in matched.css
    assert ".xl\\:hidden" not in matched.css
    assert matched.rules_kept == 3


def test_an_escaped_class_still_honours_a_real_pseudo_beside_it() -> None:
    sheets = [_Sheet("s.css", ".md\\:flex:hover { color: red }\n.nope\\:x:hover { color: blue }")]
    matched = rules_for_subtree(sheets, subtree_html=TAILWIND_HTML)
    assert ".md\\:flex:hover" in matched.css
    assert ".nope\\:x:hover" not in matched.css


def test_a_hex_escape_in_a_class_name_is_decoded_before_matching() -> None:
    """``.\\32 xl\\:flex`` is how a name that starts with a digit is written."""
    sheets = [_Sheet("s.css", ".\\32 xl\\:flex { display: flex }")]
    matched = rules_for_subtree(
        sheets, subtree_html='<section class="2xl:flex"><p>x</p></section>'
    )
    assert matched.rules_kept == 1


def test_an_escaped_comma_does_not_split_a_selector_list() -> None:
    sheets = [_Sheet("s.css", ".a\\,b { color: red }")]
    matched = rules_for_subtree(sheets, subtree_html='<section class="a,b"></section>')
    assert matched.rules_kept == 1


def test_a_font_face_keeps_the_double_spaces_inside_its_own_strings() -> None:
    """M5. ``local("My  Font")`` names a font whose family really has two spaces in it.
    Collapsing them rewrites the stylesheet's meaning to tidy up our own serialization."""
    sheets = [
        _Sheet("s.css", '@font-face { font-family: X; src: local("My  Font"), url(x.woff2) }')
    ]
    matched = rules_for_subtree(sheets, subtree_html=HERO_HTML)
    assert 'local("My  Font")' in matched.css


def test_a_consuming_slot_is_not_minted_over_slots_already_inside_it() -> None:
    """I2 (reviewer probe). The ancestry check ran one way only, so a paragraph detected LAST
    could be slotted as the PARENT of an image and a CTA already marked inside it. Binding the
    body then replaces the subtree and both inner values are discarded — LUMW0417, the exact
    class the check exists to prevent, arriving from the other direction."""
    digest = _digest("inline")
    html = (
        "<section><p>Look <img src=\"/asset-store/"
        + digest
        + '"> and <a class="btn" href="/d"><span>Go</span></a></p></section>'
    )
    detected = detect_slots(html)
    keys = {spec.key for spec in detected.specs}
    assert "image" in keys
    assert "cta_label" in keys
    assert "body" not in keys
    assert any("body" in note for note in detected.notes)


def test_a_paragraph_that_contains_nothing_slotted_is_still_body_copy() -> None:
    """The guard must discriminate, not blanket-refuse: an ordinary paragraph beside a slotted
    image is still editable copy."""
    digest = _digest("inline")
    html = f'<section><img src="/asset-store/{digest}"><p>Real copy</p></section>'
    keys = {spec.key for spec in detect_slots(html).specs}
    assert {"image", "body"} <= keys


def test_a_non_consuming_slot_may_still_sit_over_one_that_consumes() -> None:
    """An href slot rewrites one attribute and swallows nothing, so ``cta_href`` on the anchor
    and ``cta_label`` on its span remain the ruled, correct shape."""
    specs = {spec.key for spec in detect_slots(HERO_HTML).specs}
    assert {"cta_href", "cta_label"} <= specs


def test_the_whole_section_visibility_slot_survives_the_containment_guard() -> None:
    """The section root contains every other slot by definition. It is the one exception, and
    it costs nothing: its fallback is shown, so it consumes nothing until a human hides it."""
    assert "visible" in {spec.key for spec in detect_slots(HERO_HTML).specs}


def test_a_bidirectionally_guarded_section_still_annotates_cleanly() -> None:
    digest = _digest("inline")
    html = (
        "<section><h1>Ship</h1><p>Look <img src=\"/asset-store/"
        + digest
        + '"></p><p>Plain copy</p></section>'
    )
    detected = detect_slots(html)
    annotated = annotate_fragment_slots(html, detected.specs)
    assert set(annotated.slot_manifest) == {spec.key for spec in detected.specs}
    assert annotated.slot_manifest["body"]["fallback"] == "Plain copy"


def test_a_long_page_mints_every_section_it_honestly_offers() -> None:
    """FOUNDER RULING 2026-08-27: the acceptance's "at least five" is a FLOOR. The budget is a
    runaway backstop, not a working limit, so a page with more sections than the old default
    (12) now yields all of them — extraction is never the layer that decides a real page had
    fewer sections than it did."""
    body = "".join(
        f'<section class="section_{n}"><h1>H{n}</h1><p>P{n}</p></section>' for n in range(18)
    )
    outcome, _ = _mint(f"<html><body><main>{body}</main></body></html>")
    assert len(outcome.minted) == 18
    assert not [d for d in outcome.diagnostics if d["code"] == "LUMI0532"]


def test_the_backstop_is_the_capture_probes_own_section_ceiling() -> None:
    """One ceiling, not two: minting must not be able to truncate a page the capture layer was
    willing to measure in full."""
    from lumen_ingestion.sections.bands import MAX_PERSISTED_BANDS

    assert SECTION_MINT_CAP == MAX_PERSISTED_BANDS == 40


# --------------------------------------------------------------------------- #
# F2 fix wave — W2 (@font-face degradation), W4 (empty shells), W6 (leading compound)
# --------------------------------------------------------------------------- #

from lumen_api.fragments import fragment_wrapper_class  # noqa: E402

FRAG_ID = "frag_0123456789abcdef"
WRAPPER = fragment_wrapper_class(FRAG_ID)


def test_a_font_file_we_never_fetched_costs_the_face_and_not_the_section() -> None:
    """W2 (RULED). One `@media`-wrapped `@font-face` in stripe.com's global stylesheet, whose
    file the capture layer never fetched, refused EVERY section of the site on the F2 acceptance
    walk. A font is not a hole: the face falls back to the next family in the stack and the
    section still renders. So an unrehostable `src` degrades; every other unrehosted reference
    keeps the hard refusal."""
    from lumen_api.fragments import scope_fragment_css

    result = scope_fragment_css(
        "@font-face { font-family: sohne; src: url(/Sohne.woff2) format('woff2') }\n"
        ".btn { color: red }",
        fragment_id=FRAG_ID,
        rehosted={},
    )
    assert "Sohne.woff2" not in result.css
    assert "@font-face" not in result.css
    assert f".{WRAPPER} .btn" in result.css
    assert any("@font-face" in note for note in result.notes)


def test_a_rehostable_font_still_travels_with_the_fragment() -> None:
    from lumen_api.fragments import scope_fragment_css

    digest = _digest("woff2-bytes")
    result = scope_fragment_css(
        "@font-face { font-family: sohne; src: url(/Sohne.woff2) }",
        fragment_id=FRAG_ID,
        rehosted={"/Sohne.woff2": digest},
    )
    assert f"/asset-store/{digest}" in result.css
    assert result.asset_digests == (digest,)


def test_an_unrehosted_image_is_still_a_hard_refusal() -> None:
    """The degradation is font-shaped and stays font-shaped: an `<img>` we cannot serve is a
    hole in the section, which is the one thing a clone can least afford."""
    from lumen_api.fragments import FragmentRefused, scope_fragment_css

    with pytest.raises(FragmentRefused) as excinfo:
        scope_fragment_css(
            ".hero { background-image: url(/never.png) }", fragment_id=FRAG_ID, rehosted={}
        )
    assert excinfo.value.code == "fragment.unrehosted_reference"


def test_a_root_qualified_rule_keeps_its_qualifier_in_front_of_the_wrapper() -> None:
    """W6. `.lumen-frag-x html.w-mod-js [data-w-id]` is an `<html>` INSIDE the wrapper, which can
    never match — the F2 walk found Webflow's whole interaction layer dead that way. The leading
    compound addresses the page's state; the wrapper belongs where the section begins."""
    from lumen_api.fragments import scope_fragment_css

    result = scope_fragment_css(
        "html.w-mod-js:not(.w-mod-ix) [data-w-id] { opacity: 0 }",
        fragment_id=FRAG_ID,
        rehosted={},
    )
    assert result.css.startswith("html.w-mod-js:not(.w-mod-ix) ")
    assert f".{WRAPPER} [data-w-id]" in result.css


def test_a_bare_document_selector_still_becomes_the_wrapper() -> None:
    from lumen_api.fragments import scope_fragment_css

    result = scope_fragment_css(":root { --brand: #0af }", fragment_id=FRAG_ID, rehosted={})
    assert result.css.startswith(f".{WRAPPER} {{")


def test_an_ordinary_selector_is_untouched_by_the_leading_compound_rule() -> None:
    from lumen_api.fragments import scope_fragment_css

    result = scope_fragment_css(".card .btn:hover { color: red }", fragment_id=FRAG_ID, rehosted={})
    assert result.css == f".{WRAPPER} .card .btn:hover {{ color: red }}"


def test_a_section_that_shows_nothing_after_sanitizing_is_refused() -> None:
    """W4. The F2 walk offered four empty shells — `<script>`/`<style>`/iframe embeds that
    sanitize down to a bare `<div>` — as approved, reusable clones, each a row in a human's
    picker and ~28 KB of CSS at rest. A fragment that renders nothing is not a faithful copy of
    a section; it is the absence of one."""
    html = (
        '<html><body><main>'
        '<div class="w-embed w-script"><script>pwn()</script></div>'
        '<section class="real"><h1>Real</h1><p>Copy.</p></section>'
        '<section class="tail"><p>Tail.</p></section>'
        "</main></body></html>"
    )
    segmentation = segment_page(html, page_url=PAGE_URL, viewport_width=1200)
    recorder = _Recorder()
    outcome = mint_sections(
        segmentation,
        html=html,
        stylesheets=[],
        captured={},
        screenshot=None,
        source_kit_id=None,
        source_kit_version=None,
        register_bytes=recorder.register_bytes,
        create_fragment=recorder.create_fragment,
    )
    assert "Real" in " ".join(minted.label for minted in outcome.minted)
    assert not [call for call in recorder.created if "w-script" in call["html"]]


def test_an_image_only_section_is_not_mistaken_for_an_empty_shell() -> None:
    """A logo wall or a bare hero image is a real section with no prose in it at all."""
    from lumen_ingestion.sections.mint import _shows_anything

    assert _shows_anything(f'<section><img src="/asset-store/{_digest("x")}"></section>')
    assert _shows_anything("<section><svg><circle></circle></svg></section>")
    assert not _shows_anything('<section><div class="w-embed"></div></section>')
    assert not _shows_anything("")


def test_a_chain_of_document_compounds_all_stays_outside_the_wrapper() -> None:
    """Splitting only the FIRST compound left `body` inside the wrapper for `html > body .y` —
    an element that can never appear there, which is the same dead-rule shape the leading-compound
    rewrite exists to prevent, one compound further along."""
    from lumen_api.fragments import scope_fragment_css

    result = scope_fragment_css("html > body .y { color: red }", fragment_id=FRAG_ID, rehosted={})
    assert result.css.startswith("html > body ")
    assert f"html > body .{WRAPPER} .y" in result.css


def test_a_child_combinator_on_the_document_root_re_anchors_onto_the_wrapper() -> None:
    from lumen_api.fragments import scope_fragment_css

    result = scope_fragment_css("body > .x { color: red }", fragment_id=FRAG_ID, rehosted={})
    assert f"body .{WRAPPER} > .x" in result.css


def test_a_dropped_font_descriptor_leaves_no_digest_behind() -> None:
    """A `src` listing two rungs resolves the first and then refuses on the second. Writing
    straight into the shared digest set left the first rung behind on a descriptor that was then
    dropped — so the artifact claimed to display bytes its stored CSS no longer names, and a
    delivery build would ship a font file nothing references."""
    from lumen_api.fragments import scope_fragment_css

    digest = _digest("woff2-bytes")
    result = scope_fragment_css(
        "@font-face { font-family: s; src: url(/ok.woff2), url(/never.woff2) }",
        fragment_id=FRAG_ID,
        rehosted={"/ok.woff2": digest},
    )
    assert result.asset_digests == ()
    assert "@font-face" not in result.css


def test_a_font_descriptor_that_fully_resolves_still_reports_its_digests() -> None:
    from lumen_api.fragments import scope_fragment_css

    digest = _digest("woff2-bytes")
    result = scope_fragment_css(
        "@font-face { font-family: s; src: url(/ok.woff2) }",
        fragment_id=FRAG_ID,
        rehosted={"/ok.woff2": digest},
    )
    assert result.asset_digests == (digest,)


# --------------------------------------------------------------------------- #
# F3.4 — the byte budgets: loud, never silent, and explicit about the outcome
# --------------------------------------------------------------------------- #


def _noisy_png(width: int, height: int) -> bytes:
    """A PNG that does NOT compress — a flat colour encodes to a couple of kilobytes however
    large it is, and a byte budget cannot be exercised with an image that has no bytes."""
    import os
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


def _budget_lines(outcome, budget: str) -> list[dict]:
    return [
        diagnostic
        for diagnostic in outcome.diagnostics
        if diagnostic["code"] == MINT_BUDGET_CODE and diagnostic["budget"] == budget
    ]


def test_a_fragment_over_the_css_budget_is_reported_with_its_number_and_minted_in_full() -> None:
    """Warned about, never truncated: a stylesheet with rules missing renders the section subtly
    wrong and says nothing, which is the silent cap the register forbids."""
    sheet = _Sheet("s.css", ".section_home-hero { padding: 4rem; " + "margin: 0; " * 40 + "}")
    outcome, recorder = _mint(
        BANDED_PAGE, stylesheets=[sheet], weight=PageWeight(fragment_css_limit=200)
    )

    lines = _budget_lines(outcome, "fragment scoped CSS bytes")
    assert len(lines) == 1
    assert lines[0]["outcome"] == "warned"
    assert lines[0]["limit"] == 200
    assert lines[0]["measured"] > 200
    assert str(lines[0]["measured"]) in lines[0]["message"]
    # …and the hero still carries every rule that matched it.
    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    assert hero["css"].count("margin: 0") == 40


def test_a_page_over_the_css_budget_says_so_once_however_many_sections_follow() -> None:
    """The stripe shape: no single fragment is remarkable and the page is heavy everywhere. A
    per-fragment budget alone would have stayed silent about it forever."""
    sheet = _Sheet(
        "s.css",
        ".section_home-hero { padding: 4rem }\n"
        ".section_proof { padding: 2rem }\n"
        ".nav_component { display: flex }\n"
        ".footer_component { display: grid }\n",
    )
    outcome, _ = _mint(
        BANDED_PAGE, stylesheets=[sheet], weight=PageWeight(page_css_limit=100)
    )

    lines = _budget_lines(outcome, "page scoped CSS bytes")
    assert len(lines) == 1
    assert lines[0]["outcome"] == "warned"
    assert lines[0]["measured"] > 100
    # Every section is still minted: the budget reports, it does not refuse.
    assert len(outcome.minted) == 4


def test_an_over_budget_preview_is_made_smaller_rather_than_dropped() -> None:
    """A preview is a thumbnail, so the first answer to "too many bytes" is fewer pixels."""
    from io import BytesIO

    from PIL import Image

    outcome, recorder = _mint(
        BANDED_PAGE,
        screenshot=_noisy_png(1200, 1400),
        bands=_BANDS,
        weight=PageWeight(preview_limit=400_000),
    )

    lines = _budget_lines(outcome, "preview bytes")
    assert lines and all(line["outcome"] == "degraded" for line in lines)
    hero_line = next(line for line in lines if line["role"] == "hero")
    assert hero_line["encoded_width"] < 1200
    assert hero_line["stored"] <= 400_000
    assert hero_line["measured"] > 400_000
    # The picture is still a picture, and it is the one that was stored.
    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    assert len(hero["preview"]) <= 400_000
    assert Image.open(BytesIO(hero["preview"])).width == hero_line["encoded_width"]


def test_a_preview_that_will_not_fit_even_at_the_floor_width_is_dropped_and_says_so() -> None:
    outcome, recorder = _mint(
        BANDED_PAGE,
        screenshot=_noisy_png(1200, 1400),
        bands=_BANDS,
        weight=PageWeight(preview_limit=10_000),
    )

    lines = _budget_lines(outcome, "preview bytes")
    assert lines and all(line["outcome"] == "refused" for line in lines)
    assert lines[0]["encoded_width"] == mint_module.MIN_PREVIEW_WIDTH
    assert "even re-encoded at 320px wide" in lines[0]["message"]
    assert "isolation render" in lines[0]["message"]
    # Minted in full, without a picture — never refused for want of a thumbnail.
    assert len(outcome.minted) == 4
    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    assert hero["preview"] is None


def test_a_page_that_fills_its_preview_budget_still_mints_the_rest_of_its_sections() -> None:
    """The per-page budget is a different fact from the per-preview one: a picture that fits
    perfectly well can still be the one that takes the page over."""
    outcome, recorder = _mint(
        BANDED_PAGE,
        screenshot=_noisy_png(1200, 1400),
        bands=_BANDS,
        weight=PageWeight(page_preview_limit=400_000),
    )

    lines = _budget_lines(outcome, "page preview bytes")
    assert lines and all(line["outcome"] == "refused" for line in lines)
    assert lines[0]["limit"] == 400_000
    assert lines[0]["measured"] > 400_000
    assert len(outcome.minted) == 4
    stored = [call for call in recorder.created if call["preview"] is not None]
    assert stored, "the previews that fit before the budget ran out were kept"
    assert sum(len(call["preview"]) for call in stored) <= 400_000


def test_the_shipped_budgets_are_the_founder_ruling_and_no_real_page_can_reach_them() -> None:
    """FOUNDER RULING 2026-08-28: every byte budget is 5 GiB, because storage of high-quality
    images and assets is not a concern and quality is what matters. This test pins the POLICY,
    not an engineering estimate — and the second half is the point of the first: the heaviest
    capture this project has taken is four orders of magnitude under the ceiling, so nothing a
    real page produces is refused or degraded on byte grounds.

    The measurements, from the F2 acceptance re-walk: stripe.com's heaviest cloned section carried
    172,197 bytes of scoped CSS and its whole homepage 1,353,811 across ten fragments;
    insighthealth's 417,586 across nine; the largest single preview crops were 1,036,801
    (insighthealth) and 1,921,123 (stripe), and whole pages 2,832,312 and 5,981,943.
    """
    ruling = 5 * 1024**3
    assert budget_module.MAX_FRAGMENT_CSS_BYTES == ruling
    assert budget_module.MAX_PAGE_CSS_BYTES == ruling
    assert budget_module.MAX_PREVIEW_BYTES == ruling
    assert budget_module.MAX_PAGE_PREVIEW_BYTES == ruling

    # Every measurement this project has, under every ceiling that governs it — with the whole
    # mint cap's worth of the heaviest page still not reaching the page budgets.
    weight = PageWeight()
    assert weight.fragment_css_fits(172_197)
    assert weight.fragment_css_limit > 172_197 * SECTION_MINT_CAP
    assert weight.page_css_limit > 1_353_811 * SECTION_MINT_CAP
    assert weight.preview_fits(1_921_123)
    assert weight.page_preview_limit > 5_981_943 * SECTION_MINT_CAP


def test_a_real_pages_heaviest_measurements_trip_no_budget_at_all() -> None:
    """The ruling's requirement 3, as behaviour rather than arithmetic: drive the mint at the
    production ceilings over the heaviest shapes this project has measured and assert that not
    one budget line is emitted, nothing is degraded, nothing is refused, and the dead-height
    check still runs."""
    outcome, recorder = _mint(BANDED_PAGE, screenshot=_noisy_png(1200, 1400), bands=_BANDS)

    assert [
        diagnostic
        for diagnostic in outcome.diagnostics
        if diagnostic["code"] == MINT_BUDGET_CODE
    ] == []
    # No check was stopped BY A BUDGET. (Since final-review X2, LUMI0538 also reports checks
    # skipped for non-budget reasons — an inferred nav/footer crop — which is honesty about
    # coverage, not a budget trip; those lines carry no `budget` key.)
    assert [
        diagnostic
        for diagnostic in outcome.diagnostics
        if diagnostic["code"] == mint_module.MINT_CHECK_NOT_RUN_CODE
        and "budget" in diagnostic
    ] == []
    # Every section keeps the crop it was given, at the size it was taken — including the two
    # over a megabyte, which an earlier draft of this module would have re-encoded smaller.
    assert all(call["preview"] is not None for call in recorder.created)
    assert max(len(call["preview"]) for call in recorder.created) > 1_000_000
    # The two bands the browser actually measured were judged; the nav and footer were not, and
    # say so — for their own reason, which is not a budget. That is the provenance distinction
    # doing its job on the ordinary path.
    judged = [
        call
        for call in recorder.created
        if call["section_role"] in ("hero", "proof")
    ]
    assert judged and all(
        call["provenance"]["dead_height_check"] is None for call in judged
    )
    unjudged = [
        call["provenance"]["dead_height_check"]
        for call in recorder.created
        if call["section_role"] in ("nav", "footer")
    ]
    assert unjudged and all(
        note is not None and note["because"] == "crop_not_measured" for note in unjudged
    )


def test_a_section_that_is_refused_never_spends_the_pages_css_budget() -> None:
    """The budget is about bytes AT REST. An embed shell that matches a megabyte of rules and is
    then refused for showing nothing must not spend the page's budget on a fragment that does not
    exist."""
    page = (
        "<html><body><main>"
        '<section class="section_shell">'
        '<iframe src="https://player.example/x"></iframe></section>'
        '<section class="section_home-hero"><h1>Ship</h1><p>Copy</p></section>'
        "</main></body></html>"
    )
    sheet = _Sheet(
        "s.css",
        ".section_shell { padding: 4rem; " + "margin: 0; " * 40 + "}\n"
        ".section_home-hero { padding: 1rem }\n",
    )
    outcome, _ = _mint(page, stylesheets=[sheet], weight=PageWeight(page_css_limit=100))

    # The shell was refused…
    assert [minted.role for minted in outcome.minted] == ["hero"]
    assert any(
        diagnostic.get("reason") == "empty_after_sanitize"
        for diagnostic in outcome.diagnostics
    )
    # …so the only CSS charged is the hero's, which is nowhere near the budget.
    assert _budget_lines(outcome, "page scoped CSS bytes") == []
    assert _budget_lines(outcome, "fragment scoped CSS bytes") == []


def test_a_budget_refused_preview_says_the_dead_height_check_did_not_run() -> None:
    """Ruling R20-3. The byte budget is loud about the BYTES; the knock-on was silent. The
    dead-height check reads the preview crop, so a refused crop switches it off — and the section
    is then written `degraded=False`, which is indistinguishable from a band somebody looked at
    and found sound. A dead-height finding is the repair ladder's entry condition, so a silent
    clean bill here is a broken clone nobody is ever told about."""
    outcome, recorder = _mint(
        BANDED_PAGE,
        screenshot=_noisy_png(1200, 1400),
        bands=_BANDS,
        weight=PageWeight(preview_limit=10_000),
    )

    assert _budget_lines(outcome, "preview bytes")  # the bytes were refused, loudly
    not_run = [
        diagnostic
        for diagnostic in outcome.diagnostics
        if diagnostic["code"] == mint_module.MINT_CHECK_NOT_RUN_CODE
    ]
    assert not_run, "a disabled check has to say so"
    assert all(line["check"] == "dead_height" for line in not_run)
    assert all(line["budget"] == "preview bytes" for line in not_run)
    assert all(line["because"] == "no_preview" for line in not_run)
    assert "not marked degraded because nobody looked at it" in not_run[0]["message"]
    # …and the row's own provenance keeps the distinction, so it survives the diagnostics.
    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    assert hero["provenance"]["degraded"] is None
    # `refused_by` discriminates this shape from a capture that never had a screenshot (wave
    # round 2, M2) — both share `because: no_preview`, and only the budget refusal carries it.
    assert hero["provenance"]["dead_height_check"] == {
        "assessed": False,
        "because": "no_preview",
        "refused_by": "preview bytes",
    }


def test_a_page_budget_refusal_names_the_page_budget_as_what_stopped_the_check() -> None:
    outcome, _ = _mint(
        BANDED_PAGE,
        screenshot=_noisy_png(1200, 1400),
        bands=_BANDS,
        weight=PageWeight(page_preview_limit=400_000),
    )

    not_run = [
        diagnostic
        for diagnostic in outcome.diagnostics
        if diagnostic["code"] == mint_module.MINT_CHECK_NOT_RUN_CODE
        and "budget" in diagnostic
    ]
    assert not_run
    assert {line["budget"] for line in not_run} == {"page preview bytes"}


def test_a_section_the_check_did_run_on_carries_no_not_assessed_note() -> None:
    """The other half of the distinction: `degraded: null` with nothing beside it means looked
    at and sound."""
    outcome, recorder = _mint(BANDED_PAGE, screenshot=_png(1200, 1400), bands=_BANDS)

    hero = next(call for call in recorder.created if call["section_role"] == "hero")
    hero_index = hero["provenance"]["section_index"]
    # The hero's check RAN, so no not-run note names it. (Other sections — an inferred
    # nav/footer crop — may honestly carry one since final-review X2.)
    assert [
        diagnostic
        for diagnostic in outcome.diagnostics
        if diagnostic["code"] == mint_module.MINT_CHECK_NOT_RUN_CODE
        and diagnostic.get("section_index") == hero_index
    ] == []
    assert hero["provenance"]["dead_height_check"] is None


def test_the_budget_diagnostics_report_the_limit_they_actually_enforced() -> None:
    """F-4. `PageWeight` carries its limits so a caller can hand it different ones; a diagnostic
    that reported the module constant instead would name a number that decided nothing."""
    weight = PageWeight(page_css_limit=10)
    diagnostics: list[dict] = []
    segmentation = _banded_segmentation()
    record = segmentation.sections[1]
    mint_module._charge_css("x" * 50, segmentation, record, weight, diagnostics)

    (page_line,) = [
        line for line in diagnostics if line["budget"] == "page scoped CSS bytes"
    ]
    assert page_line["limit"] == 10
    assert "10-byte per-page budget" in page_line["message"]


def test_react_comment_boundaries_do_not_shift_detected_slot_targets() -> None:
    """React suspense markers are comments, not CSS :nth-child elements."""
    digest = "a" * 64
    html = (
        '<section><!--$--><h2>Customer results</h2><!--/$-->'
        '<div><!--$--><img src="/asset-store/' + digest + '">'
        '<!--/$--><p>A verified customer story.</p>'
        '<!--$--><a class="button" href="/customers"><span>Read the story</span></a>'
        '<!--/$--></div></section>'
    )
    sanitized = sanitize_fragment_html(html, rehosted={})
    detected = detect_slots(sanitized.html)
    annotated = annotate_fragment_slots(sanitized.html, detected.specs)
    assert annotated.slot_manifest["headline"]["fallback"] == "Customer results"
    assert annotated.slot_manifest["image"]["fallback"] == digest
    assert annotated.slot_manifest["body"]["fallback"] == "A verified customer story."
    assert annotated.slot_manifest["cta_href"]["fallback"] == "/customers"
    assert annotated.slot_manifest["cta_label"]["fallback"] == "Read the story"


# A missing dependency in a framework page wrapper must not lose independent sections.
RECOVERY_PAGE = """
<html><body>
<header><a href="/">Home</a></header>
<c-wiz class="page-shell"><div class="layout"><div class="content">
<section id="first"><h1>Original headline</h1><p>Original body.</p></section>
<section id="product"><h2>Product</h2><section><h3>Nested detail</h3></section></section>
<section id="closing"><h2>Closing</h2><video src="/missing.webm"></video></section>
</div><div class="decoration"></div></div><c-data></c-data></c-wiz>
<footer><p>Original footer.</p></footer>
</body></html>
"""


def test_refused_framework_wrapper_recovers_independent_authored_sections():
    outcome, recorder = _mint(RECOVERY_PAGE)
    recovered = [call for call in recorder.created if call["provenance"].get("recovery")]
    assert len(recovered) == 2
    assert [call["provenance"]["element_id"] for call in recovered] == ["first", "product"]
    assert "Nested detail" in recovered[1]["html"]
    assert all(call["provenance"]["geometry"] is None for call in recovered)
    assert all(call["preview"] is None for call in recovered)
    assert all(call["provenance"]["recovery"]["fidelity_verified"] is False for call in recovered)
    assert all(call["provenance"]["recovery"]["parent_dom_path"] for call in recovered)
    assert any(d.get("reference") == "/missing.webm" for d in outcome.diagnostics)
    recovery = next(d for d in outcome.diagnostics if d["code"] == "LUMI0539")
    assert recovery["parts"] == 3
    assert recovery["wrapper_layout_preserved"] is False
    # Retain source handles, including comment/metadata siblings, rather than reparsing a crop.
    from lumen_ingestion.sections.segment import recovery_sections, resolve_section
    from selectolax.parser import HTMLParser
    segmentation = segment_page(RECOVERY_PAGE, page_url=PAGE_URL)
    parent = next(r for r in segmentation.sections if r.tag == "c-wiz")
    children = recovery_sections(HTMLParser(RECOVERY_PAGE), parent, start_index=10)
    assert [resolve_section(RECOVERY_PAGE, r).attributes.get("id") for r in children] == [
        "first", "product", "closing"
    ]


def test_healthy_wrapper_is_never_replaced_or_duplicated_by_recovery():
    html = RECOVERY_PAGE.replace('<video src="/missing.webm"></video>', '<p>Contact us</p>')
    outcome, recorder = _mint(html)
    assert len(outcome.minted) == 3
    assert not any(call["provenance"].get("recovery") for call in recorder.created)
    assert not any(d["code"] == "LUMI0539" for d in outcome.diagnostics)


def test_recovery_respects_mint_budget_and_reserves_capacity_for_descendants():
    from lumen_ingestion.sections.mint import visible_mint_capacity
    segmentation = segment_page(RECOVERY_PAGE, page_url=PAGE_URL)
    assert visible_mint_capacity(segmentation, RECOVERY_PAGE) == 5
    outcome, recorder = _mint(RECOVERY_PAGE, limit=2)
    assert len(recorder.created) == 2
    assert len(outcome.minted) == 2
    capped = next(d for d in outcome.diagnostics if d["code"] == "LUMI0532")
    assert capped["remaining"] == 3


def test_recovery_does_not_split_semantic_sections_or_enter_hidden_content():
    from lumen_ingestion.sections.segment import recovery_sections
    from selectolax.parser import HTMLParser
    html = RECOVERY_PAGE.replace('<div class="decoration"></div>',
        '<div hidden><section id="secret"><h2>Hidden variant</h2></section></div>'
        '<article><section id="card"><h2>Card</h2></section></article>')
    segmentation = segment_page(html, page_url=PAGE_URL)
    parent = next(r for r in segmentation.sections if r.tag == "c-wiz")
    children = recovery_sections(HTMLParser(html), parent, start_index=10)
    assert [r.element_id for r in children] == ["first", "product", "closing"]
    assert recovery_sections(HTMLParser(html), children[1], start_index=20) == ()


def test_recovery_does_not_bypass_missing_shared_css_dependencies():
    outcome, recorder = _mint(RECOVERY_PAGE, stylesheets=[_Sheet(
        "s.css", "section { background: url(/also-missing.png) }"
    )])
    assert not any(call["provenance"].get("recovery") for call in recorder.created)
    assert any(d.get("reference") == "/also-missing.png" for d in outcome.diagnostics)


@pytest.mark.parametrize("reason", ["fragment.invalid_html", "fragment.slot_selector_unmatched"])
def test_recovery_never_bypasses_non_dependency_refusals(reason):
    from lumen_api.fragments import FragmentRefused

    class RefusingRecorder(_Recorder):
        def create_fragment(self, **kwargs):
            raise FragmentRefused(reason, "original refusal")

    html = RECOVERY_PAGE.replace('<video src="/missing.webm"></video>', '<p>Contact us</p>')
    outcome, _ = _mint(html, recorder=RefusingRecorder())
    assert not outcome.minted
    assert not any(d["code"] == "LUMI0539" for d in outcome.diagnostics)
    assert all(d.get("reason") != "unexpected_error" for d in outcome.diagnostics)


def test_pipeline_reserves_recovery_slots_and_keeps_partial_capture_status(monkeypatch):
    from types import SimpleNamespace

    from lumen_ingestion.pipeline import _mint_page_fragments

    recorder = _Recorder()
    monkeypatch.setattr(mint_module, "make_asset_rehoster", lambda _: recorder.register_bytes)
    monkeypatch.setattr(
        mint_module, "make_fragment_writer", lambda *a, **kw: recorder.create_fragment
    )
    monkeypatch.setattr(mint_module, "make_degraded_marker", lambda **kw: None)
    page = {"url": PAGE_URL, "role": "homepage", "status": "partial"}
    outcome = SimpleNamespace(
        snapshots=[SimpleNamespace(html=RECOVERY_PAGE, requested_url=PAGE_URL, stylesheets=[])],
        library_capture=True,
        page_coverage=[page],
    )
    refs, diagnostics = _mint_page_fragments(
        outcome,
        repo=SimpleNamespace(workspace_id="ws_capture_test"),
        blobs=SimpleNamespace(storage=None),
        brand_kit_id="brand_kit_x",
        brand_kit_version=1,
        snapshot_refs=[],
    )
    assert len(refs) == 4
    assert page["fragments"]["visible_budget"] == 5
    assert page["fragments"]["status"] == "partial"
    assert any(d["code"] == "LUMI0539" for d in diagnostics)


def test_recovery_attempts_have_a_reported_per_wrapper_backstop(monkeypatch):
    monkeypatch.setattr(mint_module, "SECTION_MINT_CAP", 2)
    outcome, recorder = _mint(RECOVERY_PAGE)
    recovery = next(d for d in outcome.diagnostics if d["code"] == "LUMI0539")
    assert recovery["parts"] == 2
    assert recovery["omitted_parts"] == 1
    assert len([c for c in recorder.created if c["provenance"].get("recovery")]) == 2
    assert any(d.get("reason") == "recovery_candidate_cap" for d in outcome.diagnostics)


def test_recovered_footer_hint_cannot_borrow_the_original_page_footer_crop():
    from dataclasses import replace

    segmentation = _banded_segmentation()
    original_footer = segmentation.by_role("footer")[0]
    recovered = replace(original_footer, index=20, dom_path=(1, 1, 2, 0))
    assert crop_extent(segmentation, recovered) is None


def test_source_root_font_variable_class_is_preserved_without_its_layout():
    sheets = [_Sheet("s.css", '''
        .font_variable { --font-body-family: "Body Font"; min-height: 100vh }
        html { font-family: var(--font-body-family), serif }
    ''')]
    matched = rules_for_subtree(
        sheets, subtree_html=HERO_HTML, source_root_classes=("font_variable",)
    )
    assert ':root {--font-body-family: "Body Font";}' in matched.css
    assert "100vh" not in matched.css
    assert matched.root_variable_rules == 1
    assert matched.rules_kept == 2


def test_root_variable_alias_preserves_layer_media_importance_and_source_order():
    matched = rules_for_subtree([_Sheet("s.css", '''
        @layer fonts { .font_variable { --type: Wide !important } }
        @media (max-width: 40em) { .font_variable { --type: Compact } }
    ''')], subtree_html=HERO_HTML, source_root_classes=("font_variable",))
    assert "@layer fonts" in matched.css and "@media (max-width: 40em)" in matched.css
    assert "--type: Wide !important" in matched.css
    assert matched.css.index("Wide") < matched.css.index("Compact")
    assert matched.root_variable_rules == 2


@pytest.mark.parametrize("selector", [".other", ".font_variable:hover", ".font_variable .child"])
def test_root_variable_alias_does_not_guess_other_classes_or_state(selector):
    matched = rules_for_subtree(
        [_Sheet("s.css", selector + " { --font-body: Unknown }")],
        subtree_html=HERO_HTML, source_root_classes=("font_variable",)
    )
    assert ":root" not in matched.css
    assert matched.root_variable_rules == 0


def test_mint_supplies_captured_root_classes_and_rehosts_their_variable_assets():
    html = BANDED_PAGE.replace('<html>', '<html class="font_variable">')
    outcome, recorder = _mint(html, stylesheets=[_Sheet("https://cdn.example/s.css", '''
        .font_variable { --font-body: Brand; --texture: url(texture.png) }
        html { font-family: var(--font-body) }
    ''')], captured={"https://cdn.example/texture.png": CapturedAsset(
        url="https://cdn.example/texture.png", data=b"texture", content_type="image/png"
    )})
    assert len(outcome.minted) == 4
    call = recorder.created[0]
    assert "--font-body: Brand" in call["css"]
    assert "texture.png" in call["rehosted"]
    assert call["provenance"]["css"]["root_variable_rules"] == 1


def test_missing_source_root_variable_asset_still_refuses_custody():
    html = BANDED_PAGE.replace('<html>', '<html class="font_variable">')
    outcome, _ = _mint(html, stylesheets=[_Sheet("s.css", '''
        .font_variable { --texture: url(/missing.png) }
    ''')])
    assert not outcome.minted
    assert any(d.get("reference") == "/missing.png" for d in outcome.diagnostics)
