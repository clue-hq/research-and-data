"""S4 CONTENT — the section recipes: which field keys feed which section of which page.

Owned by Shashank after D2 (ARV2-WORK-SPLIT.md §1.1). Recipes are config: the system rows here
are upserted into ``display_section_recipe`` with ``workspace_id = ''``; a workspace row with the
same ``(page, section_key)`` overrides the system row for that workspace. A custom variable is one
more key appended to a recipe. Machinery lives in the sibling modules, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Page = Literal["overview", "insights", "contact"]
PAGES: tuple[Page, ...] = ("overview", "insights", "contact")
RECIPE_VERSION = 1
RESTRICTED_SECTION_KEYS = frozenset({"context-only", "watch-outs", "do-not-mention"})
# Additive sections must not invalidate a saved/in-flight narrative from before their rollout.
OPTIONAL_SECTION_KEYS = frozenset({"miscellaneous"})

#: Which subject kind each page is about. A contact page about an account is a caller bug.
#: It lives here rather than beside the page machinery because it is pure data about the page
#: grammar, and a shared section has to know whose page its owner is before anything is read.
PAGE_SUBJECT_KIND: dict[str, Literal["account", "contact"]] = {
    "overview": "account",
    "insights": "account",
    "contact": "contact",
}


@dataclass(frozen=True)
class SectionRecipe:
    page: Page
    section_key: str
    h1: str
    position: int
    allowed_field_keys: tuple[str, ...]
    restricted: bool = False
    default_open: bool = False
    instruction_version: str = "v1"
    narrative: bool = False  # code-side: prose goes to intro[] (what-they-do, why-they-fit)
    workspace_id: str = ""
    #: Spec 2026-09-12 §3: ``(page, section_key)`` of the recipe whose stored block this section
    #: renders under its own ``h1``/``position``/``default_open``. A recipe with ``shared_from``
    #: owns no block, is never gathered, never written and never scanned for staleness of its own;
    #: it is stale when its owner is. ``allowed_field_keys`` are documentary (the owner's).
    shared_from: tuple[Page, str] | None = None


_UNSAFE_CONTEXT = ("account.reputation_risk", "account.resonance.attrition_signal")

SYSTEM_RECIPES: tuple[SectionRecipe, ...] = (
    # ---- insights -----------------------------------------------------------------------------
    SectionRecipe(
        "insights",
        "buying-signals",
        "Buying signals",
        0,
        (
            "account.open_requisitions",
            "account.hiring_velocity",
            "account.abm_program_maturity",
            "account.strategic_moves",
            "account.operational_pain",
            "account.resonance.buying_culture",
        ),
        default_open=True,
    ),
    SectionRecipe(
        "insights",
        "money-and-momentum",
        "Money & momentum",
        1,
        (
            "account.recent_funding",
            "account.total_funding",
            "core.annual_revenue",
            "core.revenue_band",
        ),
    ),
    SectionRecipe(
        "insights",
        "tools-they-already-use",
        "Tools they already use",
        2,
        (
            "account.gtm_tooling_stack",
            "core.primary_tech_stack",
            "core.tech_stack_categorised",
            "contact.facet.publications",
        ),
    ),
    SectionRecipe(
        "insights",
        "how-they-sell",
        "How they sell, and who they win",
        3,
        (
            "account.named_customers",
            "account.claimed_customer_logos",
            "account.claimed_outcomes_metrics",
            "account.resonance.public_frustrations",
            "account.resonance.eng_blog_tone",
        ),
    ),
    SectionRecipe(
        "insights",
        "context-only",
        "Context only",
        4,
        _UNSAFE_CONTEXT,
        restricted=True,
        shared_from=("overview", "watch-outs"),
    ),
    SectionRecipe(
        "insights",
        "miscellaneous",
        "Miscellaneous",
        5,
        ("account.product_packaging", "core.founded_year", "account.strategic_moves"),
    ),
    # ---- overview -----------------------------------------------------------------------------
    SectionRecipe(
        "overview",
        "what-they-do",
        "What they do",
        0,
        (
            "core.company_about",
            "account.product_packaging",
            "account.claimed_outcomes_metrics",
            "account.named_customers",
            "core.founded_year",
            "core.hq_location",
            "core.employee_count",
            "core.industry",
            "account.total_funding",
            "account.recent_funding",
        ),
        default_open=True,
        narrative=True,
    ),
    SectionRecipe(
        "overview",
        "why-they-fit",
        "Why they fit",
        1,
        (
            "core.hq_location",
            "account.recent_funding",
            "account.total_funding",
            "account.open_requisitions",
            "account.hiring_velocity",
            "account.abm_program_maturity",
            "account.gtm_tooling_stack",
            "account.named_customers",
            "account.operational_pain",
            "core.employee_count",
            "contact.current_title",
        ),
        default_open=True,
        narrative=True,
    ),
    SectionRecipe(
        "overview",
        "why-now",
        "Why now",
        2,
        (
            "account.open_requisitions",
            "account.hiring_velocity",
            "account.strategic_moves",
            "account.recent_funding",
            "account.abm_program_maturity",
        ),
    ),
    SectionRecipe(
        "overview",
        "buying-committee",
        "Buying committee",
        3,
        (
            "contact.persona",
            "contact.role_on_committee",
            "contact.current_title",
            "contact.facet.certifications",
            "contact.facet.career_history",
            "contact.network_statistics",
        ),
    ),
    SectionRecipe(
        "overview",
        "how-to-approach",
        "How to approach",
        4,
        (
            "contact.persona",
            "contact.role_on_committee",
            "contact.current_title",
            "contact.facet.certifications",
            "account.gtm_tooling_stack",
            "account.abm_program_maturity",
            "account.claimed_outcomes_metrics",
            "account.named_customers",
            "account.open_requisitions",
            "account.hiring_velocity",
            "account.resonance.buying_culture",
        ),
    ),
    SectionRecipe("overview", "watch-outs", "Watch-outs", 5, _UNSAFE_CONTEXT, restricted=True),
    # ---- contact ------------------------------------------------------------------------------
    SectionRecipe(
        "contact",
        "why-this-person",
        "Why this person",
        0,
        (
            "contact.current_title",
            "contact.persona",
            "contact.role_on_committee",
            "contact.headline",
            "contact.job_function",
            "contact.job_level",
            "contact.facet.career_history",
            "contact.facet.publications",
            "contact.facet.self_summary",
            "account.open_requisitions",
            "account.abm_program_maturity",
        ),
        default_open=True,
    ),
    SectionRecipe(
        "contact",
        "problem-right-now",
        "Their problem right now",
        1,
        (
            "account.abm_program_maturity",
            "account.hiring_velocity",
            "account.open_requisitions",
            "account.gtm_tooling_stack",
            "account.operational_pain",
            "contact.facet.recent_post",
            "contact.facet.publications",
        ),
        default_open=True,
    ),
    SectionRecipe(
        "contact",
        "openers",
        "Openers",
        2,
        (
            "contact.facet.hobby",
            "contact.facet.voice_quote",
            "contact.facet.recent_post",
            "contact.facet.publications",
            "contact.facet.career_history",
            "contact.facet.hooks",
            "contact.facet.openers",
            "contact.member_badges",
            "account.abm_program_maturity",
        ),
        default_open=True,
    ),
    SectionRecipe(
        "contact",
        "angles",
        "Angles",
        3,
        (
            "contact.facet.publications",
            "contact.facet.voice_quote",
            "contact.facet.recent_post",
            "contact.facet.stated_interests",
            "contact.facet.communication_style",
            "contact.facet.conference_talk",
            "contact.facet.public_appearances",
            "contact.facet.hooks",
            "account.claimed_outcomes_metrics",
            "account.gtm_tooling_stack",
            "account.operational_pain",
            "account.open_requisitions",
        ),
    ),
    SectionRecipe(
        "contact",
        "do-not-mention",
        "Do not mention",
        4,
        _UNSAFE_CONTEXT,
        restricted=True,
        default_open=True,
    ),
    SectionRecipe(
        "contact",
        "miscellaneous",
        "Miscellaneous",
        5,
        ("contact.facet.career_history", "contact.facet.publications", "contact.facet.hobby"),
    ),
)


def recipes_for(page: str) -> tuple[SectionRecipe, ...]:
    """The system recipes of ``page``, in position order."""
    rows = [recipe for recipe in SYSTEM_RECIPES if recipe.page == page]
    return tuple(sorted(rows, key=lambda recipe: recipe.position))


_UPSERT = text(
    """
    INSERT INTO display_section_recipe
        (page, section_key, workspace_id, h1, position, allowed_field_keys,
         restricted, default_open, instruction_version,
         shared_from_page, shared_from_section_key)
    VALUES
        (:page, :section_key, '', :h1, :position, :allowed_field_keys,
         :restricted, :default_open, :instruction_version,
         :shared_from_page, :shared_from_section_key)
    ON CONFLICT (page, section_key, workspace_id) DO UPDATE SET
        h1 = EXCLUDED.h1,
        position = EXCLUDED.position,
        allowed_field_keys = EXCLUDED.allowed_field_keys,
        restricted = EXCLUDED.restricted,
        default_open = EXCLUDED.default_open,
        instruction_version = EXCLUDED.instruction_version,
        shared_from_page = EXCLUDED.shared_from_page,
        shared_from_section_key = EXCLUDED.shared_from_section_key
    """
)

_SELECT = text(
    """
    SELECT page, section_key, workspace_id, h1, position, allowed_field_keys,
           restricted, default_open, instruction_version,
           shared_from_page, shared_from_section_key
    FROM display_section_recipe
    WHERE page = :page AND workspace_id IN ('', :workspace_id)
    """
)


async def load_display_recipes(conn: AsyncConnection) -> None:
    """Upsert every system recipe (``workspace_id = ''``); safe to run repeatedly."""
    for recipe in SYSTEM_RECIPES:
        await conn.execute(
            _UPSERT,
            {
                "page": recipe.page,
                "section_key": recipe.section_key,
                "h1": recipe.h1,
                "position": recipe.position,
                "allowed_field_keys": list(recipe.allowed_field_keys),
                "restricted": recipe.restricted,
                "default_open": recipe.default_open,
                "instruction_version": recipe.instruction_version,
                "shared_from_page": recipe.shared_from[0] if recipe.shared_from else None,
                "shared_from_section_key": recipe.shared_from[1] if recipe.shared_from else None,
            },
        )


async def read_recipes(
    conn: AsyncConnection, page: str, *, workspace_id: str
) -> tuple[SectionRecipe, ...]:
    """The recipes ``workspace_id`` sees for ``page``: system rows, overridden by its own.

    A workspace row whose ``section_key`` has no system row is ignored — the page grammar is
    fixed. ``narrative`` is code-side, so it is carried over from the system recipe by
    ``section_key`` rather than read from the table.
    """
    narrative_by_key = {
        recipe.section_key: recipe.narrative for recipe in SYSTEM_RECIPES if recipe.page == page
    }
    rows = (await conn.execute(_SELECT, {"page": page, "workspace_id": workspace_id})).mappings()
    by_key: dict[str, SectionRecipe] = {}
    overridden: set[str] = set()
    for row in rows:
        section_key = row["section_key"]
        if section_key not in narrative_by_key:
            continue  # a workspace row for a section the page grammar does not have
        is_override = row["workspace_id"] != ""
        if not is_override and section_key in overridden:
            continue
        if is_override:
            overridden.add(section_key)
        by_key[section_key] = SectionRecipe(
            page=cast(Page, row["page"]),
            section_key=section_key,
            h1=row["h1"],
            position=row["position"],
            allowed_field_keys=tuple(row["allowed_field_keys"]),
            restricted=row["restricted"],
            default_open=row["default_open"],
            instruction_version=row["instruction_version"],
            narrative=narrative_by_key[section_key],
            workspace_id=row["workspace_id"],
            shared_from=(
                (cast(Page, row["shared_from_page"]), row["shared_from_section_key"])
                if row["shared_from_page"]
                else None
            ),
        )
    return tuple(sorted(by_key.values(), key=lambda recipe: (recipe.position, recipe.section_key)))
