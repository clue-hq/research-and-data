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
    # Founder ruling 2026-10-30: no group names reach the agent, even from an older card.
    assert "Deep Field" not in payload and "The looks named" not in payload
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


# --- W5/R2-D: the pre-generated grounds are NAMED, not merely present ---------------------------
#
# The W5 Ramp turn held twelve of these and referenced none of them: no view, no placement, not
# one listing. The ids were viewable and placeable the whole time — nothing in the turn ever said
# they existed. These tests pin the saying.

PREGENERATED = [
    {"asset_id": "asset_gen_aaaa1111", "style_group": "Deep Field", "shape": "wide ground"},
    {"asset_id": "asset_gen_bbbb2222", "style_group": "Deep Field", "shape": "square ground"},
    {"asset_id": "asset_gen_cccc3333", "style_group": "Photo Poster", "shape": "square ground"},
]

#: A stand-in for the turn's library manifest — only the ids matter to the renderer.
LIBRARY = {entry["asset_id"]: {"record": {}} for entry in PREGENERATED}


def test_the_pregenerated_grounds_are_named_in_the_opening_context(
    tmp_path, monkeypatch
) -> None:
    """RED CASE. Before this the ids appeared nowhere the author reads."""
    payload = frame_mod.build_frame_payload(
        _tools(
            tmp_path,
            monkeypatch,
            ad_dna_card=AD_DNA_CARD,
            ad_pregenerated_assets=PREGENERATED,
            asset_library=LIBRARY,
        )
    )

    assert "## BACKGROUNDS ALREADY MADE FOR THIS BRAND (advisory)" in payload
    for entry in PREGENERATED:
        assert entry["asset_id"] in payload, "the id itself is the thing that was missing"
    # id, style-group name and shape, so the author can choose between them rather than
    # guessing which of three squares is which.
    assert "`asset_gen_bbbb2222` — square ground" in payload
    assert "`asset_gen_cccc3333` — square ground" in payload
    assert "Photo Poster" not in payload
    # It sits with the description it was generated from, not in some new place.
    assert payload.index("## THE BRAND'S PUBLISHED-AD STYLES") < payload.index(
        "## BACKGROUNDS ALREADY MADE"
    )


def test_the_listing_says_in_words_that_using_one_is_optional(tmp_path, monkeypatch) -> None:
    """RED CASE for ruling D5, the same one the description block answers.

    A list of assets with no posture reads as a checklist. This one has to say outright that
    ignoring it is a fine answer, or it becomes the gate the ruling forbids.
    """
    text = frame_mod.render_pregenerated_assets_text(PREGENERATED, LIBRARY)

    assert "Using one is optional." in text
    assert "Making your own ground instead is fine" in text
    for gate_word in ("must", "required", "refuse"):
        assert gate_word not in text.lower()


def test_an_id_this_turn_cannot_open_is_not_advertised(tmp_path, monkeypatch) -> None:
    """Naming an unreachable id would be a worse failure than the silence it replaces.

    The library manifest is what `view` and placement resolve against, so an entry outside it
    would send the author to a guaranteed `asset_unavailable`.
    """
    reachable = {PREGENERATED[0]["asset_id"]: {"record": {}}}
    text = frame_mod.render_pregenerated_assets_text(PREGENERATED, reachable)

    assert PREGENERATED[0]["asset_id"] in text
    assert PREGENERATED[1]["asset_id"] not in text
    assert PREGENERATED[2]["asset_id"] not in text

    # And when NONE of them is reachable, nothing is composed at all.
    assert frame_mod.render_pregenerated_assets_text(PREGENERATED, {}) == ""


def test_a_turn_with_no_pregenerated_imagery_composes_byte_identically(
    tmp_path, monkeypatch
) -> None:
    """RED CASE. Flag off, lane empty, or nothing pre-generated → the section is ABSENT.

    Same one-tools-object discipline as the card's own byte-identity test: a fresh tools object
    would carry a fresh run id and the comparison would prove nothing.
    """
    tools = _tools(tmp_path, monkeypatch, ad_dna_card=AD_DNA_CARD, asset_library=LIBRARY)
    without = frame_mod.build_frame_payload(tools)
    assert "BACKGROUNDS ALREADY MADE" not in without

    tools.config = replace(tools.config, ad_pregenerated_assets=PREGENERATED)
    with_assets = frame_mod.build_frame_payload(tools)
    assert with_assets != without

    added = "\n\n## BACKGROUNDS ALREADY MADE FOR THIS BRAND (advisory)\n\n" + (
        frame_mod.render_pregenerated_assets_text(PREGENERATED, LIBRARY)
    )
    assert with_assets.replace(added, "") == without


def test_the_listing_reaches_the_authors_system_prompt(tmp_path, monkeypatch) -> None:
    """The whole point: it has to arrive where the author actually reads."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent(
        "A LinkedIn square ad",
        fast_config(
            tmp_path,
            brand_kit=BRAND_KIT,
            brand_kit_source="document",
            ad_dna_card=AD_DNA_CARD,
            ad_pregenerated_assets=PREGENERATED,
            asset_library=LIBRARY,
        ),
    )

    prompt = _subagents(capture)["lumen-dsl-author"]["system_prompt"]
    assert "asset_gen_aaaa1111" in prompt


def test_the_default_config_carries_no_pregenerated_imagery(tmp_path) -> None:
    """The by-value seam's own no-op guarantee, at the config."""
    from lumen_agent.config import AgentRuntimeConfig

    config = AgentRuntimeConfig.from_env(tmp_path)
    assert config.ad_pregenerated_assets is None
    assert (
        replace(config, ad_pregenerated_assets=PREGENERATED).ad_pregenerated_assets
        == PREGENERATED
    )


# --- the brand's ad list (spec 2026-10-30, reference ads §5.5; founder-approved heading) ------

AD_ROWS = [
    {"asset_id": "a1", "from": "linkedin_ad", "headline": "Spend | less\nnow",
     "commentary": "x" * 250, "title": "Teal card", "description": "One. Two. Three.",
     "width": 1200, "height": 628, "created_at": "2026-10-02"},
    {"asset_id": "a2", "from": "marked_by_person", "headline": None, "commentary": None,
     "title": None, "description": None, "width": None, "height": None, "created_at": None},
    {"asset_id": "a_missing", "from": "linkedin_ad", "headline": "H", "commentary": None,
     "title": None, "description": None, "width": None, "height": None, "created_at": None},
]
AD_LIBRARY = {aid: {"record": {"id": aid, "status": "ready"}} for aid in ("a1", "a2")}


def test_the_list_opens_with_the_approved_heading_and_counts_only_rendered_rows() -> None:
    text = frame_mod.render_brand_ads_text(AD_ROWS, AD_LIBRARY)
    assert text.startswith(
        "## The brand's ads\n"
        "These are the brand's own published ads and any images the team marked as ads — 2 in all.\n"
        "Open any of them with `view(\"asset:<id>\")` to see the picture and its full description\n"
        "(layout, text, typography, hierarchy). Look through several before you design, and pick\n"
        "ones that fit this request; you don't need to use the same ones as last time.\n"
    )
    assert "| asset id | from | headline | post copy | title | short description | size |" in text
    assert "a_missing" not in text


def test_each_row_says_where_the_ad_came_from_and_what_it_looks_like() -> None:
    text = frame_mod.render_brand_ads_text(AD_ROWS, AD_LIBRARY)
    row = next(line for line in text.splitlines() if line.startswith("| `a1`"))
    assert "| LinkedIn ad |" in row and "| One. Two. |" in row and "| 1200×628 |" in row
    assert "x" * 200 in row and "x" * 201 not in row
    other = next(line for line in text.splitlines() if line.startswith("| `a2`"))
    assert "| marked as an ad |" in other and "no description yet" in other


def test_pipes_and_newlines_cannot_break_the_table() -> None:
    row = next(
        line for line in frame_mod.render_brand_ads_text(AD_ROWS, AD_LIBRARY).splitlines()
        if line.startswith("| `a1`")
    )
    assert "Spend \\| less now" in row
    assert row.count(" | ") == 6  # seven cells, no extra columns


def test_nothing_openable_renders_nothing() -> None:
    assert frame_mod.render_brand_ads_text(AD_ROWS, {}) == ""
    assert frame_mod.render_brand_ads_text([], AD_LIBRARY) == ""


def test_short_description_keeps_two_sentences() -> None:
    assert frame_mod.short_description("One. Two. Three.") == "One. Two."
    assert frame_mod.short_description(None) == ""
    assert len(frame_mod.short_description("y" * 500)) == 300
