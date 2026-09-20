"""The fragment artifact's three write-time primitives (clone-fidelity F1.2).

A cloned section becomes a document node only after its markup has been through the ONE-TIME
sanitizer, its CSS through the scoper, and its editable spots through the slot annotator. Every
guarantee downstream (F1.3 render, F1.4 derive, F1.5 export) rests on those three having run
exactly once, at creation — so this file is where the D-F4 ruling is actually pinned.

No database and no byte store: these are pure functions over text. The registry rows and blobs
they feed are ``test_web_fragments.py``'s business.
"""

from __future__ import annotations

import hashlib

import pytest

from lumen_api.fragments import (
    FragmentRefused,
    SlotSpec,
    annotate_fragment_slots,
    build_fragment_artifact,
    fragment_wrapper_class,
    sanitize_fragment_html,
    scope_fragment_css,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


LOGO_URL = "https://cdn.example/logo.png"
LOGO_DIGEST = _digest("logo-bytes")
HERO_URL = "https://cdn.example/hero.jpg"
HERO_DIGEST = _digest("hero-bytes")
REHOSTED = {LOGO_URL: LOGO_DIGEST, HERO_URL: HERO_DIGEST}


# --------------------------------------------------------------------------- #
# D-F4 — the sanitizer's red cases. Phase F1's hard exit gate.
# --------------------------------------------------------------------------- #


def test_a_script_tag_is_dropped_with_its_content_and_reported() -> None:
    result = sanitize_fragment_html(
        "<section><h1>Hi</h1><script>steal(document.cookie)</script></section>",
        rehosted={},
    )
    assert "script" not in result.html
    assert "steal" not in result.html
    assert "<h1>Hi</h1>" in result.html
    assert any("script" in note for note in result.notes)


def test_an_onclick_handler_is_stripped_and_its_element_survives() -> None:
    result = sanitize_fragment_html(
        '<section><button onclick="pwn()" class="cta">Book</button></section>', rehosted={}
    )
    assert "onclick" not in result.html
    assert "pwn" not in result.html
    assert 'class="cta"' in result.html
    assert any("onclick" in note for note in result.notes)


def test_every_on_star_handler_goes_not_just_the_ones_we_thought_of() -> None:
    result = sanitize_fragment_html(
        '<section><div onmouseover="a()" ONLOAD="b()" onfocusin="c()">x</div></section>',
        rehosted={},
    )
    for banned in ("onmouseover", "onload", "onfocusin", "a()", "b()", "c()"):
        assert banned not in result.html.lower(), banned


def test_a_remote_image_that_was_never_rehosted_refuses_the_whole_fragment() -> None:
    """Fail-closed, and LOUD: the refusal names the reference that could not be resolved.

    Silently dropping it would produce a fragment that looks complete and renders a hole; the
    plan's D-F4 ruling is that an unrehostable reference is a refusal, not a best-effort.
    """
    with pytest.raises(FragmentRefused) as excinfo:
        sanitize_fragment_html(f'<section><img src="{LOGO_URL}"></section>', rehosted={})
    assert excinfo.value.reference == LOGO_URL
    assert LOGO_URL in str(excinfo.value)


def test_a_rehosted_image_is_rewritten_to_its_digest_and_recorded() -> None:
    result = sanitize_fragment_html(
        f'<section><img src="{LOGO_URL}" alt="Logo"></section>', rehosted=REHOSTED
    )
    assert f'src="/asset-store/{LOGO_DIGEST}"' in result.html
    assert LOGO_URL not in result.html
    assert result.asset_digests == (LOGO_DIGEST,)


def test_an_already_rehosted_reference_needs_no_map_entry() -> None:
    """Sanitizing markup that a producer already rewrote is not a second, harder problem."""
    result = sanitize_fragment_html(
        f'<section><img src="/asset-store/{HERO_DIGEST}"></section>', rehosted={}
    )
    assert result.asset_digests == (HERO_DIGEST,)


def test_every_srcset_candidate_must_resolve_and_all_of_them_are_rewritten() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        sanitize_fragment_html(
            f'<section><img src="{LOGO_URL}" srcset="{LOGO_URL} 1x, {HERO_URL} 2x"></section>',
            rehosted={LOGO_URL: LOGO_DIGEST},
        )
    assert excinfo.value.reference == HERO_URL

    result = sanitize_fragment_html(
        f'<section><img src="{LOGO_URL}" srcset="{LOGO_URL} 1x, {HERO_URL} 2x"></section>',
        rehosted=REHOSTED,
    )
    assert f"/asset-store/{LOGO_DIGEST} 1x" in result.html
    assert f"/asset-store/{HERO_DIGEST} 2x" in result.html
    assert result.asset_digests == tuple(sorted((LOGO_DIGEST, HERO_DIGEST)))


def test_an_inline_style_background_is_an_asset_reference_like_any_other() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        sanitize_fragment_html(
            f'<section style="background-image:url({HERO_URL})"></section>', rehosted={}
        )
    assert excinfo.value.reference == HERO_URL

    result = sanitize_fragment_html(
        f'<section style="background-image:url({HERO_URL})"></section>', rehosted=REHOSTED
    )
    assert f"/asset-store/{HERO_DIGEST}" in result.html
    assert result.asset_digests == (HERO_DIGEST,)


def test_a_form_is_dropped_with_everything_inside_it() -> None:
    result = sanitize_fragment_html(
        '<section><h1>Hi</h1><form action="/subscribe"><input name="email"></form></section>',
        rehosted={},
    )
    assert "form" not in result.html
    assert "input" not in result.html
    assert "<h1>Hi</h1>" in result.html
    assert any("form" in note for note in result.notes)


@pytest.mark.parametrize("tag", ["iframe", "object", "form", "style", "noscript"])
def test_the_banned_container_elements_are_dropped_with_their_subtrees(tag: str) -> None:
    result = sanitize_fragment_html(
        f'<section><h1>Hi</h1><{tag} data-x="1">inner</{tag}></section>', rehosted={}
    )
    assert f"<{tag}" not in result.html
    assert "inner" not in result.html
    assert "<h1>Hi</h1>" in result.html
    assert any(tag in note for note in result.notes), result.notes


@pytest.mark.parametrize("tag", ["embed", "meta", "base", "link"])
def test_the_banned_void_elements_are_dropped(tag: str) -> None:
    """These four are void, so there is no subtree to take — only the element itself."""
    result = sanitize_fragment_html(
        f'<section><h1>Hi</h1><{tag} data-x="1"></section>', rehosted={}
    )
    assert f"<{tag}" not in result.html
    assert "<h1>Hi</h1>" in result.html
    assert any(tag in note for note in result.notes), result.notes


@pytest.mark.parametrize(
    "href", ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<b>x</b>", " javascript:x"]
)
def test_a_javascript_or_data_href_is_removed_and_its_link_goes_inert(href: str) -> None:
    result = sanitize_fragment_html(
        f'<section><a href="{href}" class="cta">Go</a></section>', rehosted={}
    )
    assert "href" not in result.html
    assert "javascript" not in result.html.lower()
    assert "data:" not in result.html
    assert ">Go</a>" in result.html
    assert any("href" in note for note in result.notes)


def test_an_ordinary_link_keeps_its_href() -> None:
    result = sanitize_fragment_html(
        '<section><a href="https://example.com/pricing">Pricing</a>'
        '<a href="#features">Features</a><a href="mailto:x@example.com">Mail</a></section>',
        rehosted={},
    )
    assert 'href="https://example.com/pricing"' in result.html
    assert 'href="#features"' in result.html
    assert 'href="mailto:x@example.com"' in result.html


def test_inline_svg_survives_but_its_script_and_handlers_do_not() -> None:
    """Inline SVG is section artwork — preserving it is the point of a verbatim clone."""
    result = sanitize_fragment_html(
        "<section><svg viewBox=\"0 0 10 10\">"
        '<script>pwn()</script><circle cx="5" cy="5" r="4" onclick="pwn()" fill="#f00"></circle>'
        "</svg></section>",
        rehosted={},
    )
    assert "<svg" in result.html
    assert "<circle" in result.html
    assert 'fill="#f00"' in result.html
    assert "pwn" not in result.html
    assert "onclick" not in result.html
    assert "<script" not in result.html


def test_an_svg_use_reference_out_of_the_fragment_is_refused() -> None:
    """``<use href>`` fetches bytes exactly like ``<img src>``; the same gate applies."""
    with pytest.raises(FragmentRefused) as excinfo:
        sanitize_fragment_html(
            f'<section><svg><use href="{LOGO_URL}#icon"></use></svg></section>', rehosted={}
        )
    assert excinfo.value.reference == f"{LOGO_URL}#icon"


def test_an_svg_use_reference_inside_the_fragment_is_left_alone() -> None:
    result = sanitize_fragment_html(
        '<section><svg><symbol id="i"></symbol><use href="#i"></use></svg></section>',
        rehosted={},
    )
    assert 'href="#i"' in result.html


def test_sanitizing_twice_changes_nothing_the_second_time() -> None:
    """Sanitization happens exactly once, but it had better be a fixed point when it doesn't."""
    once = sanitize_fragment_html(
        f'<section><img src="{LOGO_URL}"><script>x()</script></section>', rehosted=REHOSTED
    )
    twice = sanitize_fragment_html(once.html, rehosted={})
    assert twice.html == once.html
    assert twice.asset_digests == once.asset_digests


# --------------------------------------------------------------------------- #
# The CSS scoper
# --------------------------------------------------------------------------- #

FRAG_ID = "frag_0123456789abcdef"
WRAPPER = fragment_wrapper_class(FRAG_ID)


def _scope(css: str, rehosted: dict[str, str] | None = None) -> str:
    return scope_fragment_css(css, fragment_id=FRAG_ID, rehosted=rehosted or {}).css


def test_the_wrapper_class_is_derived_from_the_id_and_is_a_legal_class_name() -> None:
    assert WRAPPER == "lumen-frag-0123456789abcdef"
    assert fragment_wrapper_class(FRAG_ID) == WRAPPER


def test_a_bare_selector_is_prefixed_with_the_wrapper() -> None:
    out = _scope(".btn { color: red }")
    assert f".{WRAPPER} .btn" in out
    assert "color: red" in out


def test_every_selector_in_a_list_is_prefixed_not_just_the_first() -> None:
    out = _scope(".a, .b > span { color: red }")
    assert f".{WRAPPER} .a" in out
    assert f".{WRAPPER} .b > span" in out


def test_pseudo_classes_and_elements_stay_attached_to_their_selector() -> None:
    out = _scope(".btn:hover, .btn::after { color: red }")
    assert f".{WRAPPER} .btn:hover" in out
    assert f".{WRAPPER} .btn::after" in out


def test_a_media_query_survives_and_its_inner_selectors_are_scoped() -> None:
    out = _scope("@media (max-width: 600px) { .btn { color: red } }")
    assert "@media (max-width: 600px)" in out
    assert f".{WRAPPER} .btn" in out


def test_a_supports_block_is_recursed_into_like_a_media_query() -> None:
    out = _scope("@supports (display: grid) { .grid { display: grid } }")
    assert "@supports" in out
    assert f".{WRAPPER} .grid" in out


def test_an_import_is_stripped_loudly_never_silently() -> None:
    result = scope_fragment_css(
        '@import url("https://evil.example/x.css"); .btn { color: red }',
        fragment_id=FRAG_ID,
        rehosted={},
    )
    assert "@import" not in result.css
    assert "evil.example" not in result.css
    assert f".{WRAPPER} .btn" in result.css
    assert any("@import" in note for note in result.notes)


def test_a_font_face_passes_through_unscoped() -> None:
    """``@font-face`` is global by nature — a scoped one would simply never define the family."""
    out = _scope(
        "@font-face { font-family: Brand; src: url(/asset-store/%s) } .h { font-family: Brand }"
        % HERO_DIGEST
    )
    assert "@font-face" in out
    assert f".{WRAPPER} @font-face" not in out
    assert "font-family: Brand" in out
    assert f".{WRAPPER} .h" in out


def test_keyframes_are_namespaced_and_their_users_follow() -> None:
    """Two fragments both animating ``fade`` must not overwrite each other's timeline."""
    result = scope_fragment_css(
        "@keyframes fade { from { opacity: 0 } to { opacity: 1 } }"
        " .a { animation: fade 1s ease-in }"
        " .b { animation-name: fade }",
        fragment_id=FRAG_ID,
        rehosted={},
    )
    namespaced = f"fade--{WRAPPER}"
    assert f"@keyframes {namespaced}" in result.css
    assert f"animation: {namespaced} 1s ease-in" in result.css
    assert f"animation-name: {namespaced}" in result.css
    # The bare name is gone everywhere, so nothing can bind to a neighbour's timeline.
    assert "fade " not in result.css.replace(namespaced, "")


def test_an_animation_name_that_matches_no_local_keyframe_is_left_alone() -> None:
    out = _scope(".a { animation: spin 1s }")
    assert "animation: spin 1s" in out


def test_document_level_selectors_become_the_wrapper_so_custom_properties_survive() -> None:
    """``:root`` is where a modern section keeps its variables; prefixing it kills the section."""
    result = scope_fragment_css(
        ":root { --brand: #f00 } body { margin: 0 } .h { color: var(--brand) }",
        fragment_id=FRAG_ID,
        rehosted={},
    )
    assert f".{WRAPPER} {{ --brand: #f00 }}".replace(" ", "") in result.css.replace(" ", "")
    assert f".{WRAPPER} :root" not in result.css
    assert any("root" in note or "body" in note for note in result.notes)


def test_a_css_url_must_resolve_to_a_rehosted_digest_too() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        _scope(f".hero {{ background-image: url({HERO_URL}) }}")
    assert excinfo.value.reference == HERO_URL

    result = scope_fragment_css(
        f".hero {{ background-image: url({HERO_URL}) }}", fragment_id=FRAG_ID, rehosted=REHOSTED
    )
    assert f"/asset-store/{HERO_DIGEST}" in result.css
    assert result.asset_digests == (HERO_DIGEST,)


def test_a_css_url_inside_a_media_query_is_gated_at_the_same_depth() -> None:
    with pytest.raises(FragmentRefused):
        _scope(f"@media (min-width: 40em) {{ .hero {{ background: url({HERO_URL}) }} }}")


# --------------------------------------------------------------------------- #
# Review round 1 — the scoper's markup-breakout and reference-gate holes
# --------------------------------------------------------------------------- #


def test_a_string_token_cannot_close_the_style_element_it_will_be_written_into(
) -> None:
    """CRITICAL: stored CSS is written RAW into a ``<style>`` element by render and export.

    A CSS string is raw text to the HTML tokenizer, so ``content: "</style><script>…"`` ends the
    style element and everything after it becomes live markup — with the published CSP permitting
    inline script. Sanitize-once means stored bytes are trusted absolutely downstream, so this is
    THIS module's problem, not the renderer's.
    """
    result = scope_fragment_css(
        '.a { content: "</style><script>alert(1)</script>" }',
        fragment_id=FRAG_ID,
        rehosted={},
    )
    assert "</" not in result.css
    assert "<script" not in result.css
    # Escaped, not destroyed: the section still says what it said.
    assert "3c" in result.css.lower()


def test_a_comment_cannot_close_the_style_element_either() -> None:
    """Comments are dropped at parse, so this one never reaches the last gate — but it must not
    reach the OUTPUT either, and that is what is actually being asserted."""
    out = _scope(".a { color: red /* </style><script>alert(1)</script> */ }")
    assert "</" not in out
    assert "script" not in out
    assert f".{WRAPPER} .a" in out


def test_the_last_gate_is_a_whole_output_check_not_a_token_walk() -> None:
    """The ``</`` refusal runs on the FINAL text, so it covers constructs nobody enumerated.

    Asserted directly rather than only through the constructs that happen to reach it today: the
    guarantee is "no stored fragment css contains ``</``", and a token walk can always be
    outflanked by a shape that was not on its list.
    """
    from lumen_api.fragments.cssscope import _refuse_markup_breakout

    _refuse_markup_breakout(".a { color: red }")  # does not raise
    with pytest.raises(FragmentRefused) as excinfo:
        _refuse_markup_breakout(".a { color: red } </style><script>alert(1)</script>")
    assert excinfo.value.code == "fragment.css_markup_breakout"


def test_a_selector_cannot_close_the_style_element_either() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        _scope('[data-x="</style><script>alert(1)</script>"] { color: red }')
    assert excinfo.value.code == "fragment.css_markup_breakout"


def test_a_media_range_query_keeps_its_less_than_sign() -> None:
    """The refusal is on ``</``, not on ``<`` — modern media range syntax is legitimate CSS."""
    out = _scope("@media (400px <= width <= 700px) { .a { color: red } }")
    assert "<=" in out
    assert f".{WRAPPER} .a" in out


def test_an_unreadable_url_is_refused_not_serialized_as_garbage() -> None:
    """``url(var(--x))`` is a tinycss2 bad-url token; serializing it stores ``url([bad url]))``."""
    with pytest.raises(FragmentRefused) as excinfo:
        _scope(".a { background: url(var(--brand-image)) }")
    assert excinfo.value.code == "fragment.unreadable_reference"


def test_an_unterminated_string_is_refused() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        _scope('.a { content: "unterminated\n }')
    assert excinfo.value.code == "fragment.unreadable_reference"


@pytest.mark.parametrize("function", ["image-set", "-webkit-image-set"])
def test_an_image_set_candidate_is_gated_like_any_other_reference(function: str) -> None:
    """``image-set("x.png" 1x)`` loads bytes through a bare STRING, not through ``url()``."""
    with pytest.raises(FragmentRefused) as excinfo:
        _scope(f'.hero {{ background: {function}("{HERO_URL}" 1x, url({LOGO_URL}) 2x) }}')
    assert excinfo.value.reference == HERO_URL

    result = scope_fragment_css(
        f'.hero {{ background: {function}("{HERO_URL}" 1x, url({LOGO_URL}) 2x) }}',
        fragment_id=FRAG_ID,
        rehosted=REHOSTED,
    )
    assert f"/asset-store/{HERO_DIGEST}" in result.css
    assert f"/asset-store/{LOGO_DIGEST}" in result.css
    assert result.asset_digests == tuple(sorted((HERO_DIGEST, LOGO_DIGEST)))


# --------------------------------------------------------------------------- #
# Review round 2 — preludes and selectors were outside the reference machinery
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "css",
    [
        "@supports (background: url(var(--x))) { .a { color: red } }",
        "@media screen and (background: url(var(--x))) { .a { color: red } }",
        "@layer url(var(--x));",
        ".a[x=url(var(--y))] { color: red }",
    ],
)
def test_an_unreadable_reference_in_a_prelude_or_selector_is_refused(css: str) -> None:
    """IMPORTANT: preludes and selectors were serialized straight out, skipping the gate.

    The stored result was `url([bad url]))` — corrupted, with an unbalanced `)` that swallows
    every rule the at-rule wraps. Silently, immutably, and only at render. Loud-never-silent says
    the fragment refuses at creation instead.
    """
    with pytest.raises(FragmentRefused) as excinfo:
        _scope(css)
    assert excinfo.value.code == "fragment.unreadable_reference"


@pytest.mark.parametrize(
    "css",
    [
        "@supports (background: url(hero.png)) { .a { color: red } }",
        "@media (min-width: 40em) and (background: url(hero.png)) { .a { color: red } }",
        '.a[data-bg=url("hero.png")] { color: red }',
    ],
)
def test_even_a_readable_reference_in_a_prelude_or_selector_is_refused(css: str) -> None:
    """A URL in a prelude or a selector is never a URL we can rehost — nothing fetches it, and
    nothing would know where to point it. Refusing names it; rewriting it would be a lie."""
    with pytest.raises(FragmentRefused) as excinfo:
        _scope(css, {"hero.png": HERO_DIGEST})
    assert excinfo.value.code == "fragment.reference_in_prelude"


def test_the_refusal_names_the_rule_it_came_from() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        _scope("@supports (background: url(var(--x))) { .a { color: red } }")
    assert "supports" in str(excinfo.value)


def test_an_import_is_still_stripped_rather_than_refused() -> None:
    """``@import``'s prelude is a url by definition. It is handled BEFORE the prelude gate, so
    the round-1 behaviour (strip + loud note) survives this round's refusal."""
    result = scope_fragment_css(
        '@import url("https://evil.example/x.css"); .btn { color: red }',
        fragment_id=FRAG_ID,
        rehosted={},
    )
    assert "@import" not in result.css
    assert f".{WRAPPER} .btn" in result.css
    assert any("@import" in note for note in result.notes)


def test_an_ordinary_media_prelude_is_untouched_by_the_new_gate() -> None:
    out = _scope("@media screen and (max-width: 600px) { .btn:hover { color: red } }")
    assert "@media screen and (max-width: 600px)" in out
    assert f".{WRAPPER} .btn:hover" in out


# --------------------------------------------------------------------------- #
# Review round 1 — the sanitizer's three escape hatches
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tag", ["animate", "set", "animateTransform", "animateMotion", "discard"])
def test_smil_animation_cannot_smuggle_a_javascript_href_into_preserved_svg(tag: str) -> None:
    """CRITICAL: SMIL rewrites an attribute at runtime, so it walks straight past an
    attribute-time href gate — ``<set attributeName="href" to="javascript:…">``."""
    result = sanitize_fragment_html(
        f'<section><svg><a href="#x">'
        f'<{tag} attributeName="href" to="javascript:alert(1)"></{tag}>'
        f"<circle></circle></a></svg></section>",
        rehosted={},
    )
    assert "javascript" not in result.html.lower()
    assert tag.lower() not in result.html.lower()
    # The artwork around it survives.
    assert "<circle" in result.html
    assert any(tag.lower() in note.lower() for note in result.notes)


def test_an_animate_values_list_cannot_smuggle_one_either() -> None:
    result = sanitize_fragment_html(
        '<section><svg><a href="#x">'
        '<animate attributeName="href" values="javascript:alert(1)" dur="1s"></animate>'
        "</a></svg></section>",
        rehosted={},
    )
    assert "javascript" not in result.html.lower()


def test_template_content_is_not_a_blind_spot(
) -> None:
    """CRITICAL: lexbor keeps ``<template>`` content off the element walk but SERIALIZES it.

    So a template round-tripped unchanged: stored script text, and an un-rehosted remote
    reference sailing past a gate that is supposed to be fail-closed.
    """
    result = sanitize_fragment_html(
        "<section><h1>Hi</h1><template>"
        '<script>steal()</script><img src="https://evil.example/x.png">'
        "</template></section>",
        rehosted={},
    )
    assert "template" not in result.html
    assert "steal" not in result.html
    assert "evil.example" not in result.html
    assert "<h1>Hi</h1>" in result.html
    assert any("template" in note for note in result.notes)


def test_a_source_planted_slot_marker_is_stripped_so_only_we_mint_them() -> None:
    """A cloned page may already carry ``data-lumen-slot``. If it survived, a source-chosen key
    could collide with an annotator-minted one and F1.4 would write tenant content into markup
    the attacker positioned."""
    result = sanitize_fragment_html(
        '<section><h1 data-lumen-slot="headline" data-lumen-anything="x" data-ok="keep">Hi</h1>'
        "</section>",
        rehosted={},
    )
    assert "data-lumen-slot" not in result.html
    assert "data-lumen-anything" not in result.html
    assert 'data-ok="keep"' in result.html
    assert any("data-lumen" in note for note in result.notes)


def test_the_annotator_still_mints_a_marker_on_scrubbed_markup() -> None:
    """The strip is of SOURCE markers only — ours are stamped after sanitization, and survive."""
    sanitized = sanitize_fragment_html(
        '<section><h1 class="head" data-lumen-slot="evil">Hi</h1></section>', rehosted={}
    )
    annotated = annotate_fragment_slots(
        sanitized.html, [SlotSpec(selector=".head", key="headline", kind="text")]
    )
    assert 'data-lumen-slot="headline"' in annotated.html
    assert "evil" not in annotated.html


# --------------------------------------------------------------------------- #
# The slot-marker annotator
# --------------------------------------------------------------------------- #

SLOT_HTML = (
    '<section><h1 class="head">Book a call</h1>'
    f'<img class="logo" src="/asset-store/{LOGO_DIGEST}" alt="Logo">'
    '<a class="cta" href="https://example.com/demo">Demo</a>'
    '<div class="badge">New</div></section>'
)


def test_a_marked_element_carries_its_key_and_the_manifest_carries_its_fallback() -> None:
    result = annotate_fragment_slots(
        SLOT_HTML,
        [
            SlotSpec(selector=".head", key="headline", kind="text"),
            SlotSpec(selector=".logo", key="logo", kind="image"),
            SlotSpec(selector=".cta", key="cta_href", kind="href"),
            SlotSpec(selector=".badge", key="badge-visible", kind="visibility"),
        ],
    )
    assert 'data-lumen-slot="headline"' in result.html
    assert 'data-lumen-slot="logo"' in result.html
    assert result.slot_manifest == {
        "headline": {"kind": "text", "fallback": "Book a call"},
        "logo": {"kind": "image", "fallback": LOGO_DIGEST},
        "cta_href": {"kind": "href", "fallback": "https://example.com/demo"},
        "badge-visible": {"kind": "visibility", "fallback": True},
    }


def test_the_manifest_kinds_map_onto_the_engines_tagged_slot_values() -> None:
    """F1.4 binds these; the mapping is data here so it cannot be re-derived differently there.

    ``href`` and ``text`` deliberately share the engine's ``text`` tag — an href IS a string to
    the node — which is exactly why the manifest kind has to survive: it is the only record that
    a slot is a link target rather than copy.
    """
    from lumen_api.fragments.slots import SLOT_KIND_TO_NODE_TAG, SLOT_KINDS

    assert set(SLOT_KIND_TO_NODE_TAG) == set(SLOT_KINDS)
    assert SLOT_KIND_TO_NODE_TAG == {
        "text": "text",
        "image": "asset",
        "href": "text",
        "visibility": "visible",
    }


@pytest.mark.parametrize(
    "key", ["Headline", "head line", "head.line", "héadline", "", "x" * 65, "head/line", 'a"b']
)
def test_a_key_outside_the_engine_grammar_is_refused(key: str) -> None:
    """The engine refuses anything but ``[a-z0-9_-]``; minting one here would be a stored trap."""
    with pytest.raises(FragmentRefused) as excinfo:
        annotate_fragment_slots(SLOT_HTML, [SlotSpec(selector=".head", key=key, kind="text")])
    assert excinfo.value.code == "fragment.slot_key_invalid"


def test_the_longest_legal_key_is_accepted() -> None:
    key = "a" * 64
    result = annotate_fragment_slots(
        SLOT_HTML, [SlotSpec(selector=".head", key=key, kind="text")]
    )
    assert key in result.slot_manifest


def test_a_duplicate_key_is_refused() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        annotate_fragment_slots(
            SLOT_HTML,
            [
                SlotSpec(selector=".head", key="headline", kind="text"),
                SlotSpec(selector=".badge", key="headline", kind="text"),
            ],
        )
    assert excinfo.value.code == "fragment.slot_key_duplicate"


def test_two_slots_on_one_element_are_refused() -> None:
    """``data-lumen-slot`` holds one key; a second marker would silently overwrite the first."""
    with pytest.raises(FragmentRefused) as excinfo:
        annotate_fragment_slots(
            SLOT_HTML,
            [
                SlotSpec(selector=".head", key="headline", kind="text"),
                SlotSpec(selector=".head", key="headline_two", kind="text"),
            ],
        )
    assert excinfo.value.code == "fragment.slot_element_taken"


def test_more_than_sixty_four_slots_is_refused_because_the_node_could_never_hold_them() -> None:
    html = "<section>" + "".join(f'<p class="p{i}">{i}</p>' for i in range(70)) + "</section>"
    specs = [SlotSpec(selector=f".p{i}", key=f"k{i}", kind="text") for i in range(65)]
    with pytest.raises(FragmentRefused) as excinfo:
        annotate_fragment_slots(html, specs)
    assert excinfo.value.code == "fragment.slot_limit"
    # Sixty-four exactly is fine.
    assert len(annotate_fragment_slots(html, specs[:64]).slot_manifest) == 64


def test_a_selector_that_matches_nothing_is_refused_not_skipped() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        annotate_fragment_slots(
            SLOT_HTML, [SlotSpec(selector=".nope", key="headline", kind="text")]
        )
    assert excinfo.value.code == "fragment.slot_selector_unmatched"


def test_an_unknown_slot_kind_is_refused() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        annotate_fragment_slots(
            SLOT_HTML, [SlotSpec(selector=".head", key="headline", kind="colour")]
        )
    assert excinfo.value.code == "fragment.slot_kind_invalid"


def test_an_image_slot_on_an_element_with_no_resolvable_digest_is_refused() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        annotate_fragment_slots(
            "<section><div class=\"logo\"></div></section>",
            [SlotSpec(selector=".logo", key="logo", kind="image")],
        )
    assert excinfo.value.code == "fragment.slot_fallback_missing"


def test_a_fallback_too_large_for_a_node_slot_is_flagged_loudly_but_not_refused() -> None:
    """The fallback lives in the ARTIFACT (no 8 KB bound); the node's slot value has one.

    A marker whose fallback could never fit the node it will be bound to is a trap for F1.4, so
    it is reported at creation — but it is not illegal, so it is not a refusal.
    """
    long_text = "x" * 9000
    result = annotate_fragment_slots(
        f'<section><p class="p">{long_text}</p></section>',
        [SlotSpec(selector=".p", key="body", kind="text")],
    )
    assert result.slot_manifest["body"]["fallback"] == long_text
    assert any("body" in note and "8192" in note for note in result.notes)


# --------------------------------------------------------------------------- #
# Content addressing — the id IS the payload
# --------------------------------------------------------------------------- #


def _artifact(html: str = "<section><h1>Hi</h1></section>", css: str = ".h { color: red }"):
    return build_fragment_artifact(html=html, css=css, rehosted={}, slots=())


def test_the_id_has_the_shape_the_engine_refuses_anything_else_for() -> None:
    artifact = _artifact()
    assert artifact.fragment_id.startswith("frag_")
    hex_part = artifact.fragment_id[len("frag_") :]
    assert len(hex_part) == 16
    assert all(char in "0123456789abcdef" for char in hex_part)


def test_the_same_payload_is_the_same_fragment() -> None:
    assert _artifact().fragment_id == _artifact().fragment_id
    assert _artifact().payload_bytes == _artifact().payload_bytes


def test_one_changed_byte_is_a_different_fragment() -> None:
    base = _artifact()
    assert _artifact(html="<section><h1>Ho</h1></section>").fragment_id != base.fragment_id
    assert _artifact(css=".h { color: blue }").fragment_id != base.fragment_id


def test_the_payload_carries_the_scoped_css_and_its_own_id() -> None:
    artifact = _artifact()
    assert artifact.payload["fragment_id"] == artifact.fragment_id
    assert f".{fragment_wrapper_class(artifact.fragment_id)} .h" in artifact.payload["css"]
    assert artifact.payload["html"] == "<section><h1>Hi</h1></section>"
    assert artifact.payload["asset_digests"] == []
    assert artifact.payload["slot_manifest"] == {}
    assert artifact.payload["preview_digest"] is None


def test_the_payload_bytes_are_canonical_so_the_id_never_depends_on_key_order() -> None:
    artifact = _artifact()
    assert artifact.payload_bytes == build_fragment_artifact(
        html="<section><h1>Hi</h1></section>", css=".h { color: red }", rehosted={}, slots=()
    ).payload_bytes


def test_building_an_artifact_runs_all_three_primitives() -> None:
    artifact = build_fragment_artifact(
        html=(
            f'<section><h1 class="head">Book</h1><script>x()</script>'
            f'<img class="logo" src="{LOGO_URL}"></section>'
        ),
        css=".head { color: red }",
        rehosted=REHOSTED,
        slots=(SlotSpec(selector=".head", key="headline", kind="text"),),
    )
    assert "script" not in artifact.payload["html"]
    assert 'data-lumen-slot="headline"' in artifact.payload["html"]
    assert artifact.payload["asset_digests"] == [LOGO_DIGEST]
    assert artifact.payload["slot_manifest"]["headline"] == {
        "kind": "text",
        "fallback": "Book",
    }
    assert f".{fragment_wrapper_class(artifact.fragment_id)} .head" in artifact.payload["css"]


def test_a_refusal_anywhere_produces_no_partial_artifact() -> None:
    with pytest.raises(FragmentRefused):
        build_fragment_artifact(
            html=f'<section><img src="{LOGO_URL}"></section>', css="", rehosted={}, slots=()
        )


# --------------------------------------------------------------------------- #
# F2.2 ruled amendments — the two F1 carries the minting task closes.
# --------------------------------------------------------------------------- #


def test_a_srcset_url_containing_a_comma_is_read_as_one_candidate() -> None:
    """The F1 minor, closed: splitting on a bare comma cut a legal URL in half.

    ``x.png?a=1,2`` is one reference. The old split produced ``x.png?a=1`` and ``2`` — two
    strings no rehost map contains — so a real page's CDN URL refused the whole fragment. That
    errs closed, which is why it shipped, but on real pages it would starve minting.
    """
    comma_url = "https://cdn.example/hero.jpg?fit=crop&rect=0,0,100,100"
    comma_digest = _digest("comma-bytes")
    result = sanitize_fragment_html(
        f'<section><img src="{LOGO_URL}" srcset="{comma_url} 2x"></section>',
        rehosted={LOGO_URL: LOGO_DIGEST, comma_url: comma_digest},
    )
    assert f"/asset-store/{comma_digest} 2x" in result.html
    assert comma_digest in result.asset_digests


def test_a_srcset_candidate_may_end_at_a_comma_with_no_descriptor() -> None:
    """The other half of the real grammar: a candidate with no descriptor ends AT the comma,
    and the comma belongs to the separator, not to the URL."""
    result = sanitize_fragment_html(
        f'<section><img srcset="{LOGO_URL}, {HERO_URL} 2x"></section>', rehosted=REHOSTED
    )
    assert f"/asset-store/{LOGO_DIGEST}, /asset-store/{HERO_DIGEST} 2x" in result.html


def test_a_srcset_descriptor_may_itself_contain_a_comma_in_parentheses() -> None:
    result = sanitize_fragment_html(
        f'<section><img srcset="{LOGO_URL} 100w, {HERO_URL} 200w"></section>', rehosted=REHOSTED
    )
    assert f"/asset-store/{LOGO_DIGEST} 100w" in result.html
    assert f"/asset-store/{HERO_DIGEST} 200w" in result.html


def test_the_minting_path_strips_an_at_rule_whose_prelude_probes_a_url() -> None:
    """RULED (F2.2): ``@supports (background-image: url(x))`` is a legitimate feature probe.

    Refusing the whole fragment for it — round 2's recorded false positive — costs a real
    section over syntax that fetches nothing. On the minting path the at-rule is STRIPPED
    WHOLE with a loud note, exactly as ``@import`` is; the security refusals are unchanged.
    """
    result = scope_fragment_css(
        "@supports (background-image: url(hero.png)) { .a { color: red } }\n.b { color: blue }",
        fragment_id=FRAG_ID,
        rehosted={"hero.png": HERO_DIGEST},
        prelude_reference="strip",
    )
    assert "@supports" not in result.css
    assert "hero.png" not in result.css
    assert f".{WRAPPER} .b" in result.css
    assert any("supports" in note for note in result.notes)


def test_stripping_a_probing_prelude_does_not_relax_the_unreadable_refusal() -> None:
    """bad-url / bad-string stay refusals in BOTH modes: security is not what was amended."""
    with pytest.raises(FragmentRefused) as excinfo:
        scope_fragment_css(
            "@supports (background: url(var(--x))) { .a { color: red } }",
            fragment_id=FRAG_ID,
            rehosted={},
            prelude_reference="strip",
        )
    assert excinfo.value.code == "fragment.unreadable_reference"


def test_a_selector_reference_still_refuses_even_on_the_minting_path() -> None:
    """The amendment names AT-RULES. A selector cannot be 'stripped whole' without silently
    dropping a rule that styles the section, so it stays a refusal the producer can read."""
    with pytest.raises(FragmentRefused) as excinfo:
        scope_fragment_css(
            '.a[data-bg=url("hero.png")] { color: red }',
            fragment_id=FRAG_ID,
            rehosted={"hero.png": HERO_DIGEST},
            prelude_reference="strip",
        )
    assert excinfo.value.code == "fragment.reference_in_prelude"


def test_refusing_is_still_the_default_for_every_caller_that_does_not_ask() -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        scope_fragment_css(
            "@supports (background-image: url(hero.png)) { .a { color: red } }",
            fragment_id=FRAG_ID,
            rehosted={"hero.png": HERO_DIGEST},
        )
    assert excinfo.value.code == "fragment.reference_in_prelude"


@pytest.mark.parametrize(
    "reference",
    ['url("#icon_linear_gradient_q")', "url('#paint0_linear_3029_1053')", 'url(#gradient)'],
)
def test_svg_local_paint_references_survive_css_scoping(reference: str) -> None:
    result = scope_fragment_css(
        f'.art {{ fill: {reference}; filter: url("#soft-shadow"); }}',
        fragment_id=FRAG_ID,
        rehosted={},
    )
    assert reference.replace("'", '"') in result.css
    assert 'url("#soft-shadow")' in result.css
    assert not result.asset_digests


def test_inline_svg_local_reference_and_external_asset_keep_separate_custody() -> None:
    result = sanitize_fragment_html(
        '<section><svg><defs><linearGradient id="paint">'
        '<stop offset="0" stop-color="red" /></linearGradient></defs>'
        '<path style="fill: url(&quot;#paint&quot;)" d="M0 0h20v20H0z" /></svg>'
        f'<div style="background: url(&quot;{HERO_URL}&quot;)"></div></section>',
        rehosted=REHOSTED,
    )
    assert '#paint' in result.html
    assert 'linearGradient' in result.html or 'lineargradient' in result.html
    assert f'/asset-store/{HERO_DIGEST}' in result.html
    assert set(result.asset_digests) == {HERO_DIGEST}


@pytest.mark.parametrize(
    "reference",
    [
        'url("https://missing.example/a.svg#paint")',
        'url("#paint" "https://missing.example/a.svg")',
        'url("")',
    ],
)
def test_quoted_svg_fix_does_not_allow_uncaptured_or_malformed_urls(reference: str) -> None:
    with pytest.raises(FragmentRefused):
        scope_fragment_css(f".art {{ fill: {reference}; }}", fragment_id=FRAG_ID, rehosted={})
