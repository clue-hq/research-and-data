"""ARV2 D2 — the display module: section recipes, prompts, and the page writer."""

from __future__ import annotations

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

__all__ = [
    "PAGES",
    "RECIPE_VERSION",
    "RESTRICTED_SECTION_KEYS",
    "SYSTEM_RECIPES",
    "SectionRecipe",
    "load_display_recipes",
    "read_recipes",
    "recipes_for",
]
