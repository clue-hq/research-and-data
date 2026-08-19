"""Slice 4: the generation CONSUMES the kit's Creative Brief.

Three seams, all offline:

1. `build_brand_card(..., include_brief=True)` — the web card gains the
   `BrandBrief@1` projection plus the kit's measured geometry, under D2's
   6,000-token cap with honest truncation.
2. `render_brand_card_text` — the injected form: the card's JSON as today, the
   brief's prose spliced in beside it (never `\\n`-escaped inside the JSON).
3. `build_web_reviewer_prompt(brief=...)` — the reviewer's review-relevant
   subset (characterization, constraints, background rhythm), which is what
   wakes slice 1's dormant `review-website` hooks.

The two invariants that must never move: D4 (web only — the SCENE card is
byte-untouched) and back-compat (a kit with no brief renders exactly today's
card and today's reviewer prompt, byte for byte).
"""

from __future__ import annotations

import json

import pytest

from lumen_agent.brand_brief import (
    BRAND_BRIEF_TOKEN_BUDGET,
    estimate_tokens,
    read_brief,
    render_brand_grammar,
    render_reviewer_brief,
)
from lumen_agent.brand_card import build_brand_card, render_brand_card_text
from lumen_agent.prompts_web import build_web_reviewer_prompt


# --- fixtures ------------------------------------------------------------------


def _number(value: float) -> dict:
    return {"kind": "number", "value": float(value), "unit": "px"}


def _token(value: dict, source: str) -> dict:
    return {"value": {"default": value, "modes": {}}, "provenance": {"source": source}}


#: The measured/derived MIX slice 2 really emits (Stripe v4, verbatim shapes).
GEOMETRY = {
    "radii": {
        "radius.button": _token(
            _number(4), "website:https://stripe.com/in :: button border-radius"
        ),
        "radius.card": _token(
            _number(6), "website:https://stripe.com/in :: card border-radius"
        ),
        "radius.lg": _token(_number(12), "derived:radius-scale"),
    },
    "stroke_widths": {
        "stroke.width.focus": _token(
            _number(3), "website:https://stripe.com/in :: focus ring outline-width"
        ),
        "stroke.width.firm": _token(_number(2), "derived:stroke-scale"),
    },
    "spacing": {
        "space.section": _token(
            _number(96), "website:https://stripe.com/in :: section rhythm"
        ),
        "space.xl": _token(_number(24), "derived:spacing-scale"),
    },
    "shadows": {
        "shadow.brand": _token(
            {"x": 0.0, "y": 15.93, "blur": 31.86, "spread": -8.0, "color": "#32325D1F"},
            "website:https://stripe.com/in :: chip box-shadow",
        ),
    },
}


def _brief(**overrides) -> dict:
    brief = {
        "schema_version": 1,
        "characterization": {
            "words": ["precise", "expansive", "iridescent"],
            "support": "Dense product surfaces on a white canvas, cut by one violet moment.",
            "confidence": "high",
        },
        "chromatic_moment": {
            "element": "The primary CTA row",
            "token": "surface.brand",
            "surrounding": "Everything around it stays white.",
            "quiet": False,
            "confidence": "high",
        },
        "signature_compositions": [
            {
                "name": "Four-up stat backbone",
                "structure": "Oversized numerals over muted captions on navy.",
                "strength": "STRONG",
                "confidence": "high",
            }
        ],
        "palette_application": [
            {
                "token": "surface.brand",
                "scope": "accent-punctuation",
                "evidence": "Only ever a button fill or a small chip.",
                "confidence": "high",
            }
        ],
        "background_rhythm": {
            "bands": [
                {"index": 0, "token": "surface.page", "note": "hero"},
                {"index": 1, "token": None, "note": "deep navy statement band"},
            ],
            "ratio_summary": "Six white bands to one navy",
            "differentiation": "chromatic",
            "confidence": "high",
        },
        "typographic_posture": {
            "case_posture": "sentence case throughout",
            "scale_temperament": "substantial",
            "signature_moves": ["An accent-colored numeral in every stat row"],
            "tokens": ["type.display"],
            "confidence": "medium",
        },
        "imagery_posture": {
            "diet": "product-ui-led",
            "slots": ["Capability mosaic beside the fold"],
            "absences": ["No lifestyle photography anywhere"],
            "confidence": "high",
        },
        "constraints": [
            {
                "rule": "Button radius is radius.button (4px), never pill",
                "scope": "component geometry",
                "confidence": "high",
            },
            {
                "rule": "surface.brand violet is the sole solid saturated CTA fill",
                "scope": "buttons",
                "confidence": "high",
            },
        ],
        "component_recipes": [
            {
                "component": "button",
                "variant": "solid.primary",
                "radius": "radius.button",
                "padding": "space.md",
                "background": "surface.brand",
                "text": "text.inverse",
                "unmapped": [],
                "confidence": "high",
            }
        ],
        "diagnostics": [
            {
                "observation": "Navy #0D1738 statement bands",
                "reason": "no kit token carries this navy",
            }
        ],
    }
    brief.update(overrides)
    return brief


def _kit(*, brief: dict | None = None, geometry: bool = True) -> dict:
    kit = {
        "id": "brand_kit_stripe",
        "version": 4,
        "name": "Stripe",
        "tokens": {"colors": {}, "typography": {}},
        "assets": {"fonts": {}, "logos": {}, "images": {}},
        "constraints": {"tone": ["precise"]},
    }
    if geometry:
        kit["tokens"].update(json.loads(json.dumps(GEOMETRY)))
    if brief is not None:
        kit["brief"] = brief
    return kit


# --- back-compat: no brief is byte-stable ---------------------------------------


def test_a_kit_without_a_brief_builds_todays_card_byte_for_byte() -> None:
    kit = _kit()
    assert build_brand_card(kit, include_brief=True) == build_brand_card(kit)
    assert "creative_brief" not in build_brand_card(kit, include_brief=True)


def test_a_kit_without_a_brief_injects_todays_card_text_byte_for_byte() -> None:
    """The injected form of a briefless card is EXACTLY the old json.dumps."""
    card = build_brand_card(_kit(), include_brief=True)
    assert card is not None
    assert render_brand_card_text(card) == json.dumps(card, indent=2)


def test_a_malformed_brief_is_ignored_rather_than_half_rendered() -> None:
    """Envelope strict: an unknown schema_version, a non-dict, or a brief with
    no characterization is NOT a BrandBrief@1 — the card falls back to today's."""
    baseline = build_brand_card(_kit())
    for payload in (
        _brief(schema_version=2),
        "not a brief",
        {"schema_version": 1},
        _brief(characterization={"words": [], "support": "x"}),
    ):
        card = build_brand_card(_kit(brief=payload), include_brief=True)
        assert read_brief(_kit(brief=payload)) is None
        assert card == baseline


# --- D4: the scene path is untouched --------------------------------------------


def test_the_scene_card_is_byte_untouched_by_a_brief_bearing_kit() -> None:
    """D4 — web documents only in v1. `include_brief` defaults False, which is
    what the scene substrate calls, so a briefed kit yields the old card."""
    kit = _kit(brief=_brief())
    assert build_brand_card(kit) == build_brand_card(_kit())


# --- the web card carries the brief ---------------------------------------------


def test_the_web_card_renders_the_brief_sections_to_prose() -> None:
    card = build_brand_card(_kit(brief=_brief()), include_brief=True)
    assert card is not None
    block = card["creative_brief"]
    assert block["schema"] == "BrandBrief@1"
    assert block["truncated"] is False
    assert block["omitted_sections"] == []
    assert block["token_budget"] == BRAND_BRIEF_TOKEN_BUDGET

    rendered = block["rendered"]
    for heading in (
        "## Characterization",
        "## Chromatic moment",
        "## Signature compositions",
        "## Palette application",
        "## Background rhythm",
        "## Typographic posture",
        "## Imagery posture",
        "## Constraints",
        "## Component recipes",
        "## Observations with no token",
    ):
        assert heading in rendered, heading
    assert "**precise, expansive, iridescent**" in rendered
    assert "surface.brand violet is the sole solid saturated CTA fill" in rendered
    assert "radius **radius.button**" in rendered
    assert "Band 2: **no kit token**" in rendered


def test_the_web_card_renders_the_measured_geometry_with_its_provenance() -> None:
    card = build_brand_card(_kit(brief=_brief()), include_brief=True)
    rendered = card["creative_brief"]["rendered"]
    assert "## Measured geometry" in rendered
    assert "**radius.button** = 4px" in rendered
    assert "website:https://stripe.com/in :: button border-radius" in rendered
    # The shadow's whole measured shape, not just its name.
    assert "**shadow.brand** = 0 15.93px 31.86px -8px #32325D1F" in rendered


def test_derived_tokens_are_labelled_platform_defaults_never_brand_facts() -> None:
    """Provenance discipline (the brief agent's own rule, held here): a
    `derived:` token is an engine scale step. It may be shown, but never in the
    measured list and never with a brand-fact claim behind it."""
    card = build_brand_card(_kit(brief=_brief()), include_brief=True)
    rendered = card["creative_brief"]["rendered"]
    measured, _, defaults = rendered.partition("Platform defaults")
    assert "radius.lg" not in measured
    assert "stroke.width.firm" not in measured
    assert "radius.lg = 12px" in defaults
    assert "NOT brand facts" in rendered
    # A derived token never carries a website pointer.
    for line in rendered.splitlines():
        if "derived:" in line:
            pytest.fail(f"a derived provenance pointer leaked into the card: {line}")


def test_a_kit_with_no_measured_geometry_omits_the_geometry_section() -> None:
    """Absence is a finding, not a stub: nothing measured, nothing claimed."""
    card = build_brand_card(_kit(brief=_brief(), geometry=False), include_brief=True)
    assert "## Measured geometry" not in card["creative_brief"]["rendered"]


def test_the_injected_text_splices_the_brief_beside_the_json_not_inside_it() -> None:
    card = build_brand_card(_kit(brief=_brief()), include_brief=True)
    text = render_brand_card_text(card)
    head, _, tail = text.partition("## Characterization")
    # The JSON half parses on its own and carries no rendered prose.
    parsed = json.loads(head.split("\n\nCREATIVE BRIEF")[0])
    assert parsed["kit"]["id"] == "brand_kit_stripe"
    assert "creative_brief" not in parsed
    assert "\\n" not in tail  # real newlines, not JSON escapes
    assert "**precise, expansive, iridescent**" in tail


def test_building_the_card_never_mutates_the_stored_brief() -> None:
    kit = _kit(brief=_brief())
    before = json.dumps(kit, sort_keys=True)
    build_brand_card(kit, include_brief=True)
    assert json.dumps(kit, sort_keys=True) == before


# --- D2: the 6k cap on the injected form ----------------------------------------


def _huge_brief() -> dict:
    return _brief(
        constraints=[
            {"rule": "R" * 780, "scope": "everywhere", "confidence": "high"}
            for _ in range(40)
        ]
    )


def test_the_injected_brief_is_hard_capped_at_the_d2_token_budget() -> None:
    card = build_brand_card(_kit(brief=_huge_brief()), include_brief=True)
    block = card["creative_brief"]
    assert block["truncated"] is True
    assert block["estimated_tokens"] <= BRAND_BRIEF_TOKEN_BUDGET
    assert estimate_tokens(block["rendered"]) <= BRAND_BRIEF_TOKEN_BUDGET


def test_truncation_is_honest_about_what_it_dropped() -> None:
    card = build_brand_card(_kit(brief=_huge_brief()), include_brief=True)
    block = card["creative_brief"]
    rendered = block["rendered"]
    assert block["omitted_sections"]
    assert "truncated" in rendered.lower()
    for heading in block["omitted_sections"]:
        assert heading in rendered  # named, not silently dropped


def test_the_structured_brief_at_rest_is_never_truncated() -> None:
    kit = _kit(brief=_huge_brief())
    build_brand_card(kit, include_brief=True)
    assert len(kit["brief"]["constraints"]) == 40


def test_the_geometry_survives_truncation_it_is_rendered_first() -> None:
    """Order is a budget decision: the measured shape is what makes a generated
    button the brand's button, so it is never the thing that gets cut."""
    card = build_brand_card(_kit(brief=_huge_brief()), include_brief=True)
    rendered = card["creative_brief"]["rendered"]
    assert "**radius.button** = 4px" in rendered
    assert "Measured geometry" not in card["creative_brief"]["omitted_sections"]


# --- the reviewer's subset --------------------------------------------------------


def test_the_reviewer_subset_carries_the_three_review_relevant_sections() -> None:
    subset = render_reviewer_brief(_brief())
    assert subset is not None
    assert "**precise, expansive, iridescent**" in subset
    assert "Button radius is radius.button (4px), never pill" in subset
    assert "Six white bands to one navy" in subset
    assert "Band 2: **no kit token**" in subset


def test_the_reviewer_subset_leaves_the_authoring_only_sections_behind() -> None:
    """Small on purpose: the reviewer judges pixels against the brand's law, it
    does not author. Recipes, imagery slots and compositions stay with the
    director and the author."""
    subset = render_reviewer_brief(_brief())
    assert "Component recipes" not in subset
    assert "Imagery posture" not in subset
    assert "Signature compositions" not in subset
    assert "Measured geometry" not in subset


def test_the_reviewer_subset_is_capped_too() -> None:
    subset = render_reviewer_brief(_huge_brief())
    assert estimate_tokens(subset) <= BRAND_BRIEF_TOKEN_BUDGET
    assert "truncated" in subset.lower()


def test_the_reviewer_prompt_carries_the_brief_when_one_is_passed() -> None:
    prompt = build_web_reviewer_prompt(brief=render_reviewer_brief(_brief()))
    assert "CREATIVE BRIEF" in prompt
    assert "surface.brand violet is the sole solid saturated CTA fill" in prompt
    # Slice 1's dormant hook, now reachable: a constraint violation is a defect.
    assert "defect" in prompt.lower()


def test_the_reviewer_prompt_without_a_brief_is_todays_prompt_byte_for_byte() -> None:
    assert build_web_reviewer_prompt(brief=None) == build_web_reviewer_prompt()
    assert "CREATIVE BRIEF" not in build_web_reviewer_prompt()
    assert build_web_reviewer_prompt(has_account=True, brief=None) == (
        build_web_reviewer_prompt(has_account=True)
    )


def test_the_reviewer_subset_is_none_without_a_brief() -> None:
    assert render_reviewer_brief(None) is None
    assert render_reviewer_brief(read_brief(_kit())) is None


# --- the grammar renderer's own contract -----------------------------------------


def test_a_quiet_chromatic_moment_renders_as_a_rule_not_a_blank() -> None:
    brief = _brief(
        chromatic_moment={
            "element": None,
            "token": None,
            "surrounding": None,
            "quiet": True,
            "confidence": "medium",
        }
    )
    render = render_brand_grammar(_kit(brief=brief), brief)
    assert "**no chromatic peak**" in render.markdown


def test_the_web_substrate_injects_the_brief_and_the_scene_substrate_does_not(
    tmp_path,
) -> None:
    """The two live call sites, at the seam that actually reaches a model.

    The web tools' `brand_card_text` is what `build_web_orchestrator_prompt` and
    `build_web_author_prompt` interpolate; the scene tools' card is what the ad
    path injects. D4 says the brief reaches the first and not the second.
    """
    from dataclasses import replace as _replace
    from pathlib import Path

    from lumen_agent.config import AgentRuntimeConfig
    from lumen_agent.tools.substrate import LumenDesignTools
    from lumen_agent.tools.web_substrate import LumenWebTools
    from lumen_api.core import CoreClient

    repo_root = Path(__file__).resolve().parents[3]
    kit = _kit(brief=_brief())
    config = _replace(
        AgentRuntimeConfig.from_env(repo_root),
        trace_dir=tmp_path / "workspace_root",
        brand_kit=kit,
        brand_kit_source="document",
    )
    seed = CoreClient(repo_root=repo_root).web_new_doc("doc_brief_test", "Site", None)[
        "web_doc"
    ]

    web = LumenWebTools(config, "Build a page", initial_web_doc=seed)
    assert "**precise, expansive, iridescent**" in web.brand_card_text
    assert "**radius.button** = 4px" in web.brand_card_text
    assert web.reviewer_brief_text is not None
    assert "Button radius is radius.button (4px), never pill" in web.reviewer_brief_text

    scene = LumenDesignTools(config, "Make an ad")
    assert scene.brand_card is not None
    assert "creative_brief" not in scene.brand_card


def test_empty_sections_are_omitted_not_stubbed() -> None:
    brief = _brief(
        signature_compositions=[],
        palette_application=[],
        constraints=[],
        component_recipes=[],
        diagnostics=[],
    )
    render = render_brand_grammar(_kit(brief=brief), brief)
    assert "## Constraints" not in render.markdown
    assert "## Component recipes" not in render.markdown
    assert "none" not in render.markdown.lower().split("## characterization")[0]
