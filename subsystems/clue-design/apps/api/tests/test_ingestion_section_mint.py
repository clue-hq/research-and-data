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
