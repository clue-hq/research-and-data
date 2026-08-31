"""Capture-time flattening of ``@layer`` structure in cloned CSS (fix for the 2026-08-29 bug).

Why this exists: the editor render wraps every fragment sheet in the platform's own
``@layer base`` block, which demotes a clone's internal layers to NESTED sub-layers — and the
cascade ranks a layer's direct rules (Tailwind's preflight reset among them) above all of its
sub-layers, specificity never consulted. A zero-specificity ``* { margin: 0 }`` therefore beat
every scoped clone rule: sections lost their centering, headings collapsed to body size
(root-caused live on the Stripe recreate; evidence in
``_memory/2026-08-29-clone-assembly-layer-cascade-bug.md``).

The fix is at the ONE-TIME capture door, like every other sanitize decision (D-F4): stored CSS
carries no ``@layer`` at all. The browser's layer ranking is emulated with plain source order —
earlier-declared layers first (they lose ties), un-layered rules last (they win ties) — so the
clone behaves inside any host layer exactly as it behaved on its origin page.

Known, deliberate approximation: order emulates layer priority only at EQUAL specificity.
A site that relies on a weak selector in a high layer beating a strong selector in a low layer
would flatten differently than it cascades natively; no harvested site has done this yet, and
the flatten note gives a human the thread to pull if one ever does.
"""

from __future__ import annotations

import hashlib

from lumen_api.fragments import fragment_wrapper_class, scope_fragment_css

FRAG_ID = "frag_0123456789abcdef"
WRAPPER = f".{fragment_wrapper_class(FRAG_ID)}"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


FONT_URL = "https://cdn.example/brand.woff2"
REHOSTED = {FONT_URL: _digest("font-bytes")}


def _scope(css: str, rehosted=None):
    return scope_fragment_css(css, fragment_id=FRAG_ID, rehosted=rehosted or {})


def test_layer_blocks_are_flattened_out_of_stored_css() -> None:
    """The live bug's exact shape: a reset layer and a base layer, Stripe-style."""
    result = _scope(
        "@layer reset, base;"
        "@layer base { .section-container { margin-inline: auto } }"
        "@layer reset { * { margin: 0; padding: 0 } }"
    )
    assert "@layer" not in result.css
    reset_at = result.css.find(f"{WRAPPER} *")
    container_at = result.css.find(f"{WRAPPER} .section-container")
    assert reset_at != -1 and container_at != -1
    # reset was the earlier-declared layer, so its rules serialize FIRST and lose ties.
    assert reset_at < container_at


def test_unlayered_rules_keep_the_last_word() -> None:
    """Un-layered rules outrank every layer natively, so they serialize last."""
    result = _scope(
        ".plain { color: red }"
        "@layer base { .plain { color: blue } }"
    )
    assert "@layer" not in result.css
    layered_at = result.css.find("blue")
    plain_at = result.css.find("red")
    assert layered_at != -1 and plain_at != -1
    assert layered_at < plain_at


def test_layer_rank_is_declaration_order_not_source_order() -> None:
    """A statement `@layer a, b;` fixes the ranking before any block appears."""
    result = _scope(
        "@layer a, b;"
        "@layer b { .x { color: blue } }"
        "@layer a { .x { color: green } }"
    )
    assert "@layer" not in result.css
    # `a` was declared first → lower priority → serializes first, despite its
    # block coming LAST in source.
    assert result.css.find("green") < result.css.find("blue")


def test_media_wrapped_layer_content_keeps_its_condition() -> None:
    result = _scope(
        "@media (min-width: 640px) { @layer base { .a { padding: 2px } } }"
        "@layer base { .a { padding: 1px } }"
    )
    assert "@layer" not in result.css
    assert result.css.count("@media") == 1
    media_at = result.css.find("@media (min-width: 640px)")
    assert media_at != -1
    # The condition still wraps its rule (the rule sits inside the media block).
    inside = result.css[media_at:]
    assert "padding: 2px" in inside[: inside.find("}") + 200]


def test_font_face_inside_a_layer_survives_flattening() -> None:
    result = _scope(
        "@layer base { @font-face { font-family: Brand; src: url("
        + FONT_URL
        + ") } .t { font-family: Brand } }",
        rehosted=REHOSTED,
    )
    assert "@layer" not in result.css
    assert result.css.count("@font-face") == 1
    assert "Brand" in result.css


def test_flattening_is_reported_in_notes() -> None:
    result = _scope("@layer reset { * { margin: 0 } } @layer base { .a { color: red } }")
    assert any("flatten" in note and "reset" in note and "base" in note for note in result.notes)


def test_a_layerless_sheet_is_untouched_and_unreported() -> None:
    result = _scope(".a { color: red } .b { color: blue }")
    assert result.css.find(".a") < result.css.find(".b")
    assert not any("flatten" in note for note in result.notes)
