"""ARV2 D2 — the display module: section recipes, prompts, and the page writer."""

from __future__ import annotations

from clue_api.arv2.display.prompts import (
    FIXED_LINES,
    PROMPT_VERSION,
    RESPONSE_FORMAT,
    SECTION_INSTRUCTIONS,
    SYSTEM_PROMPT,
    build_messages,
    prefix_of,
    section_descriptor,
)
from clue_api.arv2.display.recipes import (
    PAGES,
    RECIPE_VERSION,
    RESTRICTED_SECTION_KEYS,
    SYSTEM_RECIPES,
    SectionRecipe,
    load_display_recipes,
    read_recipes,
    recipes_for,
)
from clue_api.arv2.display.render import (
    MAX_VALUE_CHARS,
    DisplayClaim,
    alias_table,
    dedupe_near_duplicates,
    display_claim,
    render_value_text,
)

__all__ = [
    "FIXED_LINES",
    "MAX_VALUE_CHARS",
    "PAGES",
    "PROMPT_VERSION",
    "RECIPE_VERSION",
    "RESPONSE_FORMAT",
    "RESTRICTED_SECTION_KEYS",
    "SECTION_INSTRUCTIONS",
    "SYSTEM_PROMPT",
    "SYSTEM_RECIPES",
    "DisplayClaim",
    "SectionRecipe",
    "alias_table",
    "build_messages",
    "dedupe_near_duplicates",
    "display_claim",
    "load_display_recipes",
    "prefix_of",
    "read_recipes",
    "recipes_for",
    "render_value_text",
    "section_descriptor",
]
