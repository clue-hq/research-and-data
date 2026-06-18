"""Seed field pack + the idempotent pack loader (M1.3).

A *pack* is a versioned set of field definitions (the field-set half of staged-flow §9's two-part
pack; the source-profile half is M4). :func:`load_pack` registers a pack's fields idempotently and
namespaced, so loading twice is a no-op and two packs with disjoint namespaces never collide. The
**core pack** (:data:`CORE_PACK`) seeds the commodity ``core.*`` / ``account.*`` fields the docs
cite (substrate §3 worked example) plus one ``account.resonance.*`` and one ``contact.facet.*`` row
to prove the governed deep/tier-4 field-class machinery (Doc C §2) — giving M3's compiler and M4's
resolvers a real target and M1.2 real freshness TTLs to read.

These are *defaults as config* (D7): TTLs, tier plans, and gates are starting points to confirm
against real campaigns, not hardcoded policy — they live as data here and can be re-tuned per pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore.registry import register_field
from clue_research.core import FieldDef, PassKind


@dataclass(frozen=True)
class SeedField:
    """One field definition plus the registry extras not carried on :class:`FieldDef`."""

    field_def: FieldDef
    value_schema: dict[str, Any] | None = None
    corroboration_min: int = 1
    description: str | None = None
    pack: str | None = None


def _seed(
    field_key: str,
    value_type: str,
    pass_kind: PassKind,
    *,
    tier_plan: tuple[str, ...] = (),
    freshness_ttl: timedelta | None = None,
    gate: str | None = None,
    value_schema: dict[str, Any] | None = None,
    corroboration_min: int = 1,
    description: str | None = None,
    pack: str | None = None,
) -> SeedField:
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            tier_plan=tier_plan,
            freshness_ttl=freshness_ttl,
            pass_kind=pass_kind,
            gate=gate,
        ),
        value_schema=value_schema,
        corroboration_min=corroboration_min,
        description=description,
        pack=pack,
    )


# ~90-day default freshness; signal/personal fields refresh faster (substrate §6).
CORE_PACK: tuple[SeedField, ...] = (
    _seed(
        "core.employee_count",
        "int",
        PassKind.SCORING,
        tier_plan=("clay", "apollo"),
        freshness_ttl=timedelta(days=90),
        value_schema={"type": "integer"},
        description="Total headcount.",
    ),
    _seed(
        "core.primary_domain",
        "str",
        PassKind.SCORING,
        tier_plan=("registry", "clearbit"),
        freshness_ttl=timedelta(days=180),
        value_schema={"type": "string"},
        description="Primary web domain.",
    ),
    _seed(
        "core.work_email",
        "str",
        PassKind.SCORING,
        tier_plan=("apollo", "clay"),
        freshness_ttl=timedelta(days=30),
        value_schema={"type": "string"},
        description="Work email address.",
    ),
    _seed(
        "core.primary_tech_stack",
        "list[str]",
        PassKind.SCORING,
        tier_plan=("builtwith",),
        freshness_ttl=timedelta(days=90),
        value_schema={"type": "array", "items": {"type": "string"}},
        description="Detected primary technologies.",
    ),
    _seed(
        "account.recent_funding",
        "object",
        PassKind.SCORING,
        tier_plan=("apollo", "exa"),
        freshness_ttl=timedelta(days=90),
        value_schema={
            "type": "object",
            "required": ["amount_usd"],
            "properties": {"amount_usd": {"type": "number"}, "round": {"type": "string"}},
        },
        description="Most recent funding round.",
    ),
    # substrate §3 worked example: a deep-pass signal field with a gate and a tier plan.
    _seed(
        "account.hiring_velocity_eng",
        "number",
        PassKind.DEEP,
        tier_plan=("linkedin_jobs", "exa"),
        freshness_ttl=timedelta(days=30),
        gate="tier>=3",
        value_schema={"type": "number"},
        corroboration_min=2,
        description="Engineering hiring velocity (signal field; substrate §3 example).",
    ),
    _seed(
        "account.operational_pain",
        "str",
        PassKind.DEEP,
        tier_plan=("exa", "parallel"),
        freshness_ttl=timedelta(days=90),
        gate="deep-pass",
        value_schema={"type": "string"},
        corroboration_min=2,
        description="Synthesized operational pain.",
    ),
    _seed(
        "account.strategic_moves",
        "str",
        PassKind.DEEP,
        tier_plan=("exa", "parallel"),
        freshness_ttl=timedelta(days=90),
        gate="deep-pass",
        value_schema={"type": "string"},
        corroboration_min=2,
        description="Strategic moves / initiatives.",
    ),
    # Governed field-classes (Doc C §2): deep pass, tier-4 synthesis, governed by M10. The
    # governed/deep/tier-4 nature is carried by field_class (resonance / facet) + pass='deep'.
    _seed(
        "account.resonance.culture",
        "str",
        PassKind.DEEP,
        tier_plan=("exa_deep", "parallel_task"),
        freshness_ttl=timedelta(days=60),
        gate="deep-pass",
        value_schema={"type": "string"},
        description="Cultural resonance signal (Doc C §2; tier-4, governed).",
    ),
    _seed(
        "contact.facet.recent_post",
        "str",
        PassKind.DEEP,
        tier_plan=("exa", "firecrawl"),
        freshness_ttl=timedelta(days=14),
        gate="committee-gated",
        value_schema={"type": "string"},
        description="Recent public post (personal hook; Doc C §2; governed by M10).",
    ),
)


async def load_pack(conn: AsyncConnection, fields: tuple[SeedField, ...]) -> None:
    """Register every field in ``fields`` (idempotent; re-loading is a no-op). Additive and
    namespaced, so two packs with disjoint namespaces never collide."""
    for seed in fields:
        await register_field(
            conn,
            seed.field_def,
            value_schema=seed.value_schema,
            corroboration_min=seed.corroboration_min,
            description=seed.description,
            pack=seed.pack,
        )


async def load_core_pack(conn: AsyncConnection) -> None:
    """Register the seed core pack (idempotent)."""
    await load_pack(conn, CORE_PACK)
