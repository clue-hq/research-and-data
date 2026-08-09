"""The Lane E prose field pack — ``account.summary`` and ``contact.overview`` (E0).

These are the two first tenants of the on-completion prose-synthesis seam (charter
``docs/specs/FI-lane-E-on-completion-synthesis.md`` §2.4): persona-, product-, and client-KB-free
prose write-ups of the subject, composed from a completed entity-research job's verified claims
and served through the ready-made (previously route-empty) ``SUMMARY`` sections. Own module, not
``fields.py`` — the lane-demarcation registry (§2.5) keeps the M12 narrative pack and this pack
in separate files so Lane E and FI-2 never co-edit one.

The registration choices are ratified policy, not defaults:

* **``reuse_scope=TENANT_PRIVATE``, declared.** ``account.summary`` is ``FieldClass.ACCOUNT``
  whose class default is ``PUBLIC_FOOTPRINT``; post-B3 the classification is privacy-only, so
  PUBLIC buys nothing and risks a leak. The contact default is already TENANT_PRIVATE; both are
  declared so neither depends on a heuristic.
* **``research_scope=PROJECT_NEUTRAL`` (§7-D2).** One world-fact summary per entity, refreshed by
  any project's completed research, serving every project lens. The D2 amendment still carries a
  ``project_id`` slot in ``value_json`` — **always ``null`` while the fields are neutral** — so a
  future PROJECT_RELATIVE extension is a value change (start stamping real ``project_id``s and
  register the relative species), never a key migration. Flipping the species and populating
  ``project_id`` must happen in the same change (FI-2 §6.4 discipline).
* **Tier-4, judge-gated, no ``tier_plan``.** Like the M12 narrative: produced by the Lane E
  synthesis seam, never the M4 waterfall; a unique synthesis cannot be corroborated, so the M9.3
  faithfulness judge is the accuracy gate (``gate="faithfulness"``,
  ``single_source_sufficient=True``).

Wire :func:`load_prose_pack` at the ``api`` composition root via
``clue_api.narrative_wiring.register_narrative_wiring`` (PF-7) — both production processes call
it, which is what makes the route rows exist wherever a view is composed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    EntityType,
    FieldDef,
    PassKind,
    ResearchScope,
    ResearchSectionKind,
    ReuseScope,
)
from clue_research.claimstore import ResearchViewFieldRoute, SeedField, load_pack

# --- field keys (conventions §3: subject-namespaced prose outputs) ---------------------------
ACCOUNT_SUMMARY = "account.summary"
CONTACT_OVERVIEW = "contact.overview"

# Both tenants share one value shape (§2.4):
# - ``paragraphs``: the prose itself, one string per paragraph (2-4 account / 1-3 contact —
#   prompt-enforced, not schema-enforced; an empty list is a refusal and never becomes a claim);
# - ``prompt_version``: which prompt produced it (prompt-as-data, versioned);
# - ``synthesized_from_job_id``: the completed ``entity_research_job`` this prose was composed
#   from (the §2.2 idempotency subject);
# - ``research_outcome``: the §7-D1 stamp — {completed, needs_review} — so the prose is honest
#   about its basis (never synthesized on ``cancelled``);
# - ``project_id``: the §7-D2 amendment slot, ``null`` while the fields are PROJECT_NEUTRAL (see
#   the module docstring — do not "simplify" it away).
# ``additionalProperties`` is left open so the shape can grow additively without a migration.
_PROSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "paragraphs",
        "prompt_version",
        "synthesized_from_job_id",
        "research_outcome",
        "project_id",
    ],
    "properties": {
        "paragraphs": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "prompt_version": {"type": "string"},
        "synthesized_from_job_id": {"type": "string"},
        "research_outcome": {"enum": ["completed", "needs_review"]},
        "project_id": {"type": ["string", "null"]},
    },
}


def _prose_seed(field_key: str, entity_type: EntityType, description: str) -> SeedField:
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type="object",
            tier_plan=(),  # produced by the Lane E synthesis seam, not the M4 waterfall
            pass_kind=PassKind.DEEP,
            freshness_ttl=timedelta(days=90),
            gate="faithfulness",  # promoted by the M9.3 judge, not corroboration
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            research_scope=ResearchScope.PROJECT_NEUTRAL,
        ),
        value_schema=_PROSE_SCHEMA,
        single_source_sufficient=True,
        corroboration_min=1,
        description=description,
        research_view_route=ResearchViewFieldRoute(
            field_key=field_key,
            entity_type=entity_type,
            section_kind=ResearchSectionKind.SUMMARY,
            # Deliberately the opposite of the narrative's pinned/exact route (§2.4): neutral
            # world-fact prose reads from the subject's current truth in every project lens.
            context_scope="subject_current",
            product_mode="neutral_or_exact",
        ),
    )


PROSE_PACK: tuple[SeedField, ...] = (
    _prose_seed(
        ACCOUNT_SUMMARY,
        EntityType.ACCOUNT,
        "Neutral account prose summary (Lane E E1) — a tier-4 llm_synthesis claim composed from "
        "the account's verified claims on research completion; frontend summaryParagraphs.",
    ),
    _prose_seed(
        CONTACT_OVERVIEW,
        EntityType.CONTACT,
        "Neutral contact prose overview (Lane E E2) — a tier-4 llm_synthesis claim composed from "
        "the contact's eligible claims on research completion; frontend overviewParagraphs.",
    ),
)

# The field keys this pack registers (for consumers/tests that need the set without re-deriving it).
PROSE_FIELD_KEYS: tuple[str, ...] = tuple(seed.field_def.field_key for seed in PROSE_PACK)


async def load_prose_pack(conn: AsyncConnection) -> None:
    """Register the Lane E prose fields + SUMMARY routes (idempotent; re-loading is a no-op).

    Additive and namespaced — never collides with ``CORE_PACK`` / ``NARRATIVE_PACK`` / the
    committee or icp packs. Wire at the ``api`` composition root via
    :func:`clue_api.narrative_wiring.register_narrative_wiring` (appended to
    ``RESEARCH_PACK_LOADERS``).
    """
    await load_pack(conn, PROSE_PACK)
