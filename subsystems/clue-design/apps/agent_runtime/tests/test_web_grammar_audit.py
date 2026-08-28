"""The Brand Grammar Audit reaches a web turn (clone-fidelity F2.4).

The extraction half lives on the ingestion side (`lumen_ingestion.grammar_audit`,
covered by `apps/api/tests/test_ingestion_grammar_audit.py`). This is the
CONSUMPTION half: the kit section becomes one bounded prompt block on the brand
card, so the director and the author read the brand's own law before they compose
a section that never existed on the client's site.

Four things are tested rather than trusted:

* **the token law, and its one agent-side divergence** — the stored audit speaks
  `radius.button`; the injected prose renders the web class beside it, exactly as
  `render_brand_grammar` already does for a component recipe.
* **provenance discipline** — a rule the engine computed, or a house default, is
  never rendered as something this brand does.
* **bounded means bounded** — past the char budget whole rules are dropped, the
  drop is announced, and no rule is ever cut in half.
* **the F2.3 seam** — this block governs sections the agent COMPOSES. The reuse
  ladder owns cloned bands, and this must not say a second, different thing.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lumen_agent import brand_brief
from lumen_agent.brand_brief import (
    GRAMMAR_AUDIT_CHAR_BUDGET,
    GRAMMAR_AUDIT_SCHEMA_VERSION,
    read_grammar_audit,
    render_grammar_audit,
)
from lumen_agent.brand_card import build_brand_card, render_brand_card_text
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.prompts_web import build_web_author_prompt, build_web_orchestrator_prompt

REPO_ROOT = Path(__file__).resolve().parents[3]


# --- fixtures ------------------------------------------------------------------


def _rule(text: str, basis: str = "measured", evidence: str = "measured on the site") -> dict:
    return {"rule": text, "evidence": evidence, "basis": basis}


def _audit(**overrides) -> dict:
    audit = {
        "schema_version": 1,
        "type_treatment": {
            "rules": [
                _rule("`type.headline` (the page's `<h1>`) is Aeonik / 48px / weight 600."),
                _rule(
                    "`type.display` (the display line) is Aeonik / 77px — computed, not observed.",
                    basis="derived",
                    evidence="nothing on the site anchored this role",
                ),
            ],
            "absent": None,
        },
        "cadence": {
            "rules": [
                _rule("The site's own band sequence: light, light, dark, light."),
                _rule("Band rhythm is 96px (`space.section`)."),
            ],
            "absent": None,
        },
        "color_frequency": {
            "rules": [_rule("`#FFFFFF` carries 5 of 8 measured bands.")],
            "absent": None,
        },
        "surface_language": {
            "rules": [_rule("Corners: `radius.button` 4px, `radius.card` 6px.")],
            "absent": None,
        },
        "anti_patterns": {
            "rules": [
                _rule("No extra dark sections: 2 of 8 measured bands is dark."),
                _rule(
                    "No decorative blobs or orbs unless the brand's presence uses them.",
                    basis="default",
                    evidence="house default from the lane's design guidance",
                ),
            ],
            "absent": None,
        },
    }
    audit.update(overrides)
    return audit


def _kit(*, audit: dict | None = None, brief: dict | None = None) -> dict:
    kit = {
        "id": "kit_audit",
        "version": 4,
        "name": "Stripe",
        "tokens": {
            "colors": {
                "surface.page": {"value": {"default": {"kind": "hex", "value": "#FFFFFF"}}},
                "text.primary": {"value": {"default": {"kind": "hex", "value": "#0D1738"}}},
            }
        },
        "assets": {},
        "constraints": {},
    }
    if audit is not None:
        kit["grammar_audit"] = audit
    if brief is not None:
        kit["brief"] = brief
    return kit


def _fat_audit(*, rules_per_field: int = 14, length: int = 320) -> dict:
    """An audit far past the budget, with every rule long enough to matter."""
    audit = {"schema_version": 1}
    for index, name in enumerate(
        ("type_treatment", "cadence", "color_frequency", "surface_language", "anti_patterns")
    ):
        audit[name] = {
            "rules": [
                _rule(f"{name} rule {position} " + "x" * length)
                for position in range(rules_per_field)
            ],
            "absent": None,
        }
    return audit


# --- reading the section ---------------------------------------------------------


def test_a_kit_with_no_audit_reads_as_none() -> None:
    assert read_grammar_audit(_kit()) is None


@pytest.mark.parametrize(
    "payload",
    [
        "not an object",
        {"schema_version": 2, "type_treatment": {"rules": []}},
        {"type_treatment": {"rules": []}},
        {},
    ],
)
def test_an_envelope_this_build_does_not_understand_is_ignored_outright(payload) -> None:
    assert read_grammar_audit(_kit(audit=payload)) is None


def test_a_well_formed_audit_reads_back() -> None:
    audit = read_grammar_audit(_kit(audit=_audit()))
    assert audit is not None
    assert audit["schema_version"] == GRAMMAR_AUDIT_SCHEMA_VERSION


# --- the rendered block ----------------------------------------------------------


def test_the_block_carries_all_five_fields_in_order() -> None:
    render = render_grammar_audit(_audit())
    headings = [line for line in render.markdown.splitlines() if line.startswith("## ")]
    assert len(headings) == 5
    assert "Type treatment" in headings[0]
    assert "Cadence" in headings[1]
    assert "Color frequency" in headings[2]
    assert "Surface language" in headings[3]
    assert "Never" in headings[4]


def test_a_geometry_token_renders_with_the_class_that_deploys_it() -> None:
    """The one deliberate agent-side divergence, same as a component recipe:
    the kit section stores the token, the prompt shows the class beside it."""
    markdown = render_grammar_audit(_audit()).markdown
    assert "`py-section` (space.section)" in markdown
    assert "`rounded-button` (radius.button)" in markdown
    assert "`rounded-card` (radius.card)" in markdown


def test_a_computed_rule_is_never_rendered_as_a_brand_fact() -> None:
    markdown = render_grammar_audit(_audit()).markdown
    display_line = next(line for line in markdown.splitlines() if "type.display" in line)
    assert "engine default" in display_line
    headline_line = next(line for line in markdown.splitlines() if "type.headline" in line)
    assert "engine default" not in headline_line and "house default" not in headline_line


def test_a_house_default_says_it_is_a_house_default() -> None:
    markdown = render_grammar_audit(_audit()).markdown
    slop = next(line for line in markdown.splitlines() if "blobs" in line)
    assert "house default" in slop


def test_an_absent_field_says_it_is_not_known_and_states_no_rule() -> None:
    audit = _audit(
        cadence={"rules": [], "absent": "the capture measured no band sequence for this site."}
    )
    markdown = render_grammar_audit(audit).markdown
    body = markdown.split("## Cadence", 1)[1].split("## ", 1)[0]
    assert "NOT KNOWN" in body
    assert "no band sequence" in body
    assert "- " not in body


def test_the_same_audit_renders_identically_twice() -> None:
    first = render_grammar_audit(_audit())
    second = render_grammar_audit(_audit())
    assert first.markdown == second.markdown


# --- the budget ------------------------------------------------------------------


def test_a_fat_audit_is_cut_to_the_budget() -> None:
    render = render_grammar_audit(_fat_audit())
    assert render.truncated
    assert len(render.markdown) <= GRAMMAR_AUDIT_CHAR_BUDGET


def test_the_cut_drops_whole_rules_and_never_half_of_one() -> None:
    audit = _fat_audit()
    render = render_grammar_audit(audit)
    stated = {
        rule["rule"]
        for name in ("type_treatment", "cadence", "color_frequency", "surface_language", "anti_patterns")
        for rule in audit[name]["rules"]
    }
    for line in render.markdown.splitlines():
        if not line.startswith("- "):
            continue
        assert any(line[2:].startswith(rule) for rule in stated), line


def test_a_drop_is_announced_with_its_count_and_its_fields() -> None:
    render = render_grammar_audit(_fat_audit())
    assert render.dropped_rules > 0
    note = render.markdown.split("## This audit is truncated", 1)[1]
    assert str(render.dropped_rules) in note
    assert render.dropped_from
    for field in render.dropped_from:
        assert field in note
    assert "unknown rather than absent" in note


def test_the_cut_takes_the_tail_of_a_field_before_the_head_of_another() -> None:
    """Lowest-value first: every field keeps its strongest rule while any field
    still holds a later one, so a whole field never vanishes to feed another."""
    render = render_grammar_audit(_fat_audit())
    for name in ("type_treatment", "cadence", "color_frequency", "surface_language", "anti_patterns"):
        assert f"{name} rule 0 " in render.markdown


def test_a_budget_too_small_for_any_rule_says_so_instead_of_lying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor case. Dropping every rule must not read as "this brand has no
    cadence" — the kit knows, this rendering does not, and it says which."""
    monkeypatch.setattr(brand_brief, "GRAMMAR_AUDIT_CHAR_BUDGET", 400)
    render = brand_brief.render_grammar_audit(_audit())
    assert render.dropped_rules == 8
    sections = "## " + render.markdown.split("## ", 1)[1]
    assert "NOT KNOWN" not in sections
    assert sections.count("dropped to fit the budget") == 5
    # Never half a rule, even here.
    assert not [line for line in render.markdown.splitlines() if line.startswith("- ")]


def test_a_field_that_arrives_with_neither_rules_nor_a_reason_still_says_not_known() -> None:
    """Defence against a hand-built or future payload the extractor's own XOR
    would have refused: absence is reported, never silently skipped."""
    markdown = render_grammar_audit(_audit(cadence={"rules": [], "absent": None})).markdown
    body = markdown.split("## Cadence", 1)[1].split("## ", 1)[0]
    assert "NOT KNOWN" in body


def test_the_type_law_survives_a_budget_that_drops_a_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The extractor emits a field's LAW first, so the drop — which walks a
    field's tail — takes a role listing before it takes "never restate the ramp".
    A field-1 section that keeps six listings and loses its instruction has kept
    the footnotes and dropped the law."""
    law = _rule(
        "Headings land on the theme's type ramp. Never restate size, weight, leading or "
        "tracking on a heading: a raw `text-5xl font-bold` replaces the treatment below "
        "with a generic one.",
        basis="default",
        evidence="house rule",
    )
    audit = _audit(
        type_treatment={
            "rules": [law]
            + [_rule(f"`type.role{index}` is Aeonik / " + "x" * 200) for index in range(6)],
            "absent": None,
        }
    )
    monkeypatch.setattr(brand_brief, "GRAMMAR_AUDIT_CHAR_BUDGET", 1400)
    render = brand_brief.render_grammar_audit(audit)

    assert "never restate size, weight, leading or tracking" in render.markdown.lower()
    assert render.dropped_rules > 0
    assert "Type treatment" in render.dropped_from
    # Whole rules only, even under the tighter budget.
    for line in render.markdown.splitlines():
        if line.startswith("- ") and "type.role" in line:
            assert line.rstrip().endswith("x")

    # And the ordering is what saves it, not luck: the same rules with the law
    # LAST — where the extractor used to put it — lose exactly that line.
    trailing = _audit(
        type_treatment={
            "rules": [_rule(f"`type.role{index}` is Aeonik / " + "x" * 200) for index in range(6)]
            + [law],
            "absent": None,
        }
    )
    assert (
        "never restate size, weight, leading or tracking"
        not in brand_brief.render_grammar_audit(trailing).markdown.lower()
    )


def test_an_audit_that_fits_is_not_marked_truncated() -> None:
    render = render_grammar_audit(_audit())
    assert not render.truncated
    assert render.dropped_rules == 0
    assert "truncated" not in render.markdown


# --- the F2.3 seam ---------------------------------------------------------------


def test_the_block_points_at_the_reuse_ladder_instead_of_relegislating_it() -> None:
    markdown = render_grammar_audit(_audit()).markdown.lower()
    assert "compose" in markdown
    assert "cloned section" in markdown
    for forbidden in ("insert_cloned_section", "search_cloned_sections", "slot"):
        assert forbidden not in markdown


# --- the brand card --------------------------------------------------------------


def test_the_card_carries_the_audit_when_the_lane_asks_for_it() -> None:
    card = build_brand_card(_kit(audit=_audit()), include_grammar_audit=True)
    block = card["grammar_audit"]
    assert block["schema"] == "BrandGrammarAudit@1"
    assert "## Cadence" in block["rendered"]
    assert block["char_budget"] == GRAMMAR_AUDIT_CHAR_BUDGET
    assert block["truncated"] is False


def test_a_card_that_did_not_ask_for_the_audit_is_byte_identical() -> None:
    """The scene/ad lane's card must not move; this is a web-lane switch."""
    kit = _kit(audit=_audit())
    assert build_brand_card(kit) == build_brand_card(_kit())


def test_a_kit_with_no_audit_carries_no_audit_block() -> None:
    card = build_brand_card(_kit(), include_grammar_audit=True)
    assert "grammar_audit" not in card
    assert render_brand_card_text(card) == json.dumps(card, indent=2)


def test_the_injected_text_splices_the_prose_beside_the_json() -> None:
    card = build_brand_card(_kit(audit=_audit()), include_grammar_audit=True)
    text = render_brand_card_text(card)
    body, prose = text.split("\n\nBRAND GRAMMAR AUDIT", 1)
    assert "grammar_audit" not in json.loads(body)
    assert "## Cadence" in prose
    # The prose is prose: newlines are real, never JSON-escaped.
    assert "\\n" not in prose


# --- the assembled turn context ---------------------------------------------------


def _card_text(kit: dict) -> str:
    from lumen_api.core import CoreClient
    from lumen_agent.tools.web_substrate import LumenWebTools

    config = replace(AgentRuntimeConfig.from_env(REPO_ROOT), brand_kit=kit)
    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_web_audit", "Audit site", None)["web_doc"]
    return LumenWebTools(config, "Build a page", initial_web_doc=seed).brand_card_text


def test_a_real_web_turn_assembles_the_audit_into_both_role_prompts() -> None:
    card_text = _card_text(_kit(audit=_audit()))
    assert "BRAND GRAMMAR AUDIT" in card_text

    author = build_web_author_prompt(brand_card=card_text, theme_token_names="primary")
    director = build_web_orchestrator_prompt(
        doc_title="Audit site",
        has_existing_content=False,
        brand_card=card_text,
        review_cap=2,
        author_cap=3,
    )
    for prompt in (author, director):
        assert "BRAND GRAMMAR AUDIT" in prompt
        assert "## Surface language" in prompt


def test_a_kit_without_an_audit_leaves_the_turn_context_as_it_was() -> None:
    assert "BRAND GRAMMAR AUDIT" not in _card_text(_kit())
