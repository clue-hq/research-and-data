"""W4 — the brand's published-ad styles, described, in the turn's opening context.

The card is resolved by the API from the ad-assets lane and handed to the runtime BY VALUE, the
same rule `brand_kit` and `reference_assets` follow. Here we only care about the runtime half:
it is rendered as ADVISORY prose next to the brand card, it is bounded to what the API sent, and
a turn without one composes byte-identically to a pre-W4 turn.
"""

from __future__ import annotations

from dataclasses import replace

import lumen_agent.frame as frame_mod
from lumen_agent.tools.substrate import LumenDesignTools

from test_fast_loop import (  # noqa: F401 - reuse the §5.1 fixtures rather than fork them
    BRAND_KIT,
    _install_deepagents_stub,
    _subagents,
    fast_config,
)
from lumen_agent.harness import create_design_deepagent
from agent_fixtures import FakeCoreClient

PROSE = (
    "These ads are one flat deep-green field with a heavy headline on the left. "
    "A lime accent shows up once, on the call to action, and nowhere else."
)
AD_DNA_CARD = {
    "schema_version": 2,
    "prose": PROSE,
    "style_groups": [
        {"name": "Deep Field", "creative_ids": ["adcre_a"]},
        {"name": "Photo Poster", "creative_ids": ["adcre_b"]},
    ],
}


def _tools(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = fast_config(
        tmp_path, brand_kit=BRAND_KIT, brand_kit_source="document", **overrides
    )
    return LumenDesignTools(config, "A LinkedIn square ad")


def test_the_described_styles_ride_the_frame_payload_next_to_the_brand_card(
    tmp_path, monkeypatch
) -> None:
    payload = frame_mod.build_frame_payload(_tools(tmp_path, monkeypatch, ad_dna_card=AD_DNA_CARD))

    assert "## THE BRAND'S PUBLISHED-AD STYLES, DESCRIBED (advisory)" in payload
    assert PROSE in payload
    assert "The looks named in that description: Deep Field, Photo Poster." in payload
    # Next to, never instead of: the brand card is still the thing carrying the rules.
    assert payload.index("## BRAND CARD") < payload.index("## THE BRAND'S PUBLISHED-AD STYLES")


def test_the_description_says_in_words_that_it_is_not_a_rule(tmp_path, monkeypatch) -> None:
    """RED CASE for ruling D5. The card is an OBSERVATION about ads this brand already
    published. If the text does not say so, an author reads a description as a specification
    and the brand kit quietly loses every argument with it."""
    text = frame_mod.render_ad_dna_card_text(AD_DNA_CARD)

    assert "It is context, not a rule." in text
    assert "Where the description and the brand card disagree, the brand card wins." in text
    for gate_word in ("must", "required", "refuse"):
        assert gate_word not in text.lower().replace("nothing here overrides", "")


def test_a_card_with_no_named_looks_still_renders_its_description(tmp_path, monkeypatch) -> None:
    """A brand whose ads are all one look honestly names no group; the description is the
    thing that matters and must not be withheld for want of a list."""
    text = frame_mod.render_ad_dna_card_text({"prose": PROSE, "style_groups": []})
    assert PROSE in text
    assert "The looks named" not in text


def test_a_turn_with_no_ad_lane_composes_byte_identically(tmp_path, monkeypatch) -> None:
    """RED CASE. The section must be ABSENT — not present-and-empty — on every turn of every
    workspace that never onboarded ads, which is almost all of them."""
    # ONE tools object, so the only variable is the card (a fresh one would carry a fresh
    # run id and the comparison would be meaningless).
    tools = _tools(tmp_path, monkeypatch)
    without = frame_mod.build_frame_payload(tools)
    assert "PUBLISHED-AD STYLES" not in without

    tools.config = replace(tools.config, ad_dna_card=AD_DNA_CARD)
    with_card = frame_mod.build_frame_payload(tools)
    assert with_card != without
    # And the difference is EXACTLY the one added section: nothing else moved.
    added = "\n\n## THE BRAND'S PUBLISHED-AD STYLES, DESCRIBED (advisory)\n\n" + (
        frame_mod.render_ad_dna_card_text(AD_DNA_CARD)
    )
    assert with_card.replace(added, "") == without


def test_the_card_reaches_the_authors_system_prompt(tmp_path, monkeypatch) -> None:
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent(
        "A LinkedIn square ad",
        fast_config(
            tmp_path,
            brand_kit=BRAND_KIT,
            brand_kit_source="document",
            ad_dna_card=AD_DNA_CARD,
        ),
    )

    assert PROSE in _subagents(capture)["lumen-dsl-author"]["system_prompt"]


def test_the_default_config_carries_no_card(tmp_path) -> None:
    """The by-value seam's own no-op guarantee, at the config."""
    from lumen_agent.config import AgentRuntimeConfig

    config = AgentRuntimeConfig.from_env(tmp_path)
    assert config.ad_dna_card is None
    assert replace(config, ad_dna_card=AD_DNA_CARD).ad_dna_card == AD_DNA_CARD
