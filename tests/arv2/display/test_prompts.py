"""S4 exit gate: the section prompts carry the master plan's §7 rules and cache a stable prefix."""

from __future__ import annotations

from clue_api.arv2.display.prompts import (
    FIXED_LINES,
    PROMPT_VERSION,
    SECTION_INSTRUCTIONS,
    SYSTEM_PROMPT,
    build_messages,
    prefix_of,
)
from clue_api.arv2.display.recipes import SYSTEM_RECIPES, recipes_for

CLIENT = {"name": "Clue", "what_we_sell": "AI-native ABM"}
SUBJECT = {
    "kind": "contact",
    "name": "Nick Fisher",
    "persona": "economic_buyer",
    "account": "Zafran Security",
}
ROWS = [
    {
        "id": "c1",
        "fieldKey": "contact.facet.hobby",
        "value": "cocktail YouTuber",
        "priority": 1,
        "outreachSafe": True,
    }
]


def test_the_three_fixed_lines_are_in_the_system_prompt() -> None:
    assert len(FIXED_LINES) == 3
    for line in FIXED_LINES:
        assert line in SYSTEM_PROMPT
    assert "17 June 2026" in SYSTEM_PROMPT
    assert "at most once per page" in SYSTEM_PROMPT.lower() or "at most once" in SYSTEM_PROMPT
    assert "never" in SYSTEM_PROMPT.lower() and "url" in SYSTEM_PROMPT.lower()
    assert PROMPT_VERSION == "display-v1"


def test_every_recipe_has_an_instruction() -> None:
    assert {(r.page, r.section_key) for r in SYSTEM_RECIPES} == set(SECTION_INSTRUCTIONS)
    for (page, key), instruction in SECTION_INSTRUCTIONS.items():
        assert len(instruction) > 40, (page, key)
        if page == "contact" and key not in {"do-not-mention"}:
            assert "sendLine" in instruction, (page, key)
        if key == "why-they-fit":
            assert "fitDisposition" in instruction
        if key in {"what-they-do", "why-they-fit"}:
            assert "intro" in instruction


def test_prefix_is_identical_across_sections_and_only_the_suffix_changes() -> None:
    recipes = recipes_for("contact")
    a = build_messages(
        page="contact",
        subject=SUBJECT,
        client=CLIENT,
        recipes=recipes,
        target=recipes[0],
        claim_rows=ROWS,
    )
    b = build_messages(
        page="contact",
        subject=SUBJECT,
        client=CLIENT,
        recipes=recipes,
        target=recipes[2],
        claim_rows=ROWS,
    )
    assert a[0] == b[0] and a[0]["role"] == "system"
    assert prefix_of(a) == prefix_of(b)
    assert a[1]["content"] != b[1]["content"]
    assert "# WRITE ONLY THIS SECTION NOW: openers" in b[1]["content"]
    assert "http" not in a[1]["content"].lower()


def test_regenerate_line_names_the_forbidden_aliases() -> None:
    recipes = recipes_for("contact")
    m = build_messages(
        page="contact",
        subject=SUBJECT,
        client=CLIENT,
        recipes=recipes,
        target=recipes[2],
        claim_rows=ROWS,
        forbidden_aliases=["c7", "c9"],
    )
    assert "c7, c9" in m[1]["content"] and "must not appear" in m[1]["content"]
