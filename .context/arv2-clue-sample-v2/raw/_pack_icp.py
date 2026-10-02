"""Worked starter industry packs as data (M3.3 / ENG-115).

The three packs staged-flow §7c names — ``frontier_ai``, ``healthcare_practice``, ``data_infra`` —
authored as pure data to prove vertical pluggability end to end (substrate §3 payoff 1) and to seed
M3.2's compiler tests. Each carries staged-flow §9's *two prior sets*: a ``<pack>.*`` field set
and a source profile whose weight orderings reproduce §7c verbatim ("arXiv high … Glassdoor low";
"NPI/CMS high … journals low"; "job-posting tech mentions high, BuiltWith high, eng blogs medium").

These are *priors/defaults as config* (D7): starting weights to confirm against real campaigns and
reweight via M13's learning loop — not hardcoded policy. ``source_key``s are string references into
M4's ``source_manifest`` namespace (the resolvers are M4's; this file names none of them as code).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldClass, FieldDef, PassKind, ResearchScope, ReuseScope
from clue_research.claimstore import SeedField
from clue_research.icp.catalog import Pack, PackSourceSlot, register_pack_catalog
from clue_research.icp.source_profile import SourceWeight, WeightedSource

# Convenience high/medium/low aliases for terse, readable authoring.
_HI = SourceWeight.HIGH
_MED = SourceWeight.MEDIUM
_LO = SourceWeight.LOW


def _field(
    field_key: str,
    value_type: str,
    pass_kind: PassKind,
    *,
    pack: str | None,
    tier_plan: tuple[str, ...] = (),
    freshness_ttl: timedelta | None = None,
    gate: str | None = None,
    reuse_scope: ReuseScope | None = None,
    research_scope: ResearchScope | None = None,
    value_schema: dict[str, Any] | None = None,
    corroboration_min: int = 1,
    description: str | None = None,
) -> SeedField:
    """Author one pack field. ``pack`` is the field-key namespace for a ``<pack>.*`` field, or
    ``None`` for a shared canonical contribution (e.g. an ``account.resonance.*`` field; Doc C §2).

    A ``<pack>.*`` field MUST set ``reuse_scope`` (no safe default; ENG-165 W5 — enforced at
    authoring) and ``research_scope`` (no ratified species default; FI-2 P3 — enforced by
    ``register_field``). A canonical contribution (``pack=None``) may leave both ``None`` and
    inherit the class/ratified defaults (e.g. an ``account.resonance.*`` field resolves to
    tenant_private and project_neutral).
    """
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            tier_plan=tier_plan,
            freshness_ttl=freshness_ttl,
            pass_kind=pass_kind,
            gate=gate,
            reuse_scope=reuse_scope,
            research_scope=research_scope,
        ),
        value_schema=value_schema,
        corroboration_min=corroboration_min,
        description=description,
        pack=pack,
    )


def _slot(
    *pairs: tuple[str, SourceWeight], field_class: FieldClass | None = None
) -> PackSourceSlot:
    """Build a source-profile slot from ``(source_key, weight)`` pairs in priority order; ``rank``
    is the 1-based position so the Source Planner gets an explicit consult order."""
    return PackSourceSlot(
        field_class=field_class,
        sources=tuple(
            WeightedSource(source_key=key, weight=weight, rank=index + 1)
            for index, (key, weight) in enumerate(pairs)
        ),
    )


# --- frontier_ai -----------------------------------------------------------
FRONTIER_AI = Pack(
    pack_key="frontier_ai",
    namespace="frontier_ai",
    title="Frontier AI labs & research-driven companies",
    description="Research-output-heavy AI companies; signal is in publications/code, not reviews.",
    field_set=(
        _field(
            "frontier_ai.arxiv_activity",
            "int",
            PassKind.SCORING,
            pack="frontier_ai",
            tier_plan=("arxiv", "semantic_scholar"),
            freshness_ttl=timedelta(days=30),
            # Public research footprint about the company (arXiv volume) — amortizes across clients.
            reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
            # A world-fact about the company's research output — neutral (FI-2 §5.2).
            research_scope=ResearchScope.PROJECT_NEUTRAL,
            value_schema={"type": "integer"},
            description="Recent research-paper volume on arXiv / Semantic Scholar (intent proxy).",
        ),
        # A pack-contributed resonance field-class (Doc C §2): registered, not enumerated. Shared
        # canonical row (pack=None), authored by this pack.
        _field(
            "account.resonance.research_prestige",
            "str",
            PassKind.DEEP,
            pack=None,
            tier_plan=("exa_deep", "parallel_task"),
            freshness_ttl=timedelta(days=60),
            gate="deep-pass",
            value_schema={"type": "string"},
            description="Perceived research prestige/culture (resonance; Doc C §2; M10-governed).",
        ),
    ),
    # staged-flow §7c: arXiv high, Semantic Scholar high, GitHub high, research-X high,
    # press releases medium, Glassdoor low.
    source_profile=(
        _slot(
            ("arxiv", _HI),
            ("semantic_scholar", _HI),
            ("github", _HI),
            ("research_x", _HI),
            ("press_releases", _MED),
            ("glassdoor", _LO),
        ),
    ),
)


# --- healthcare_practice ---------------------------------------------------
HEALTHCARE_PRACTICE = Pack(
    pack_key="healthcare_practice",
    namespace="healthcare",
    title="Healthcare practices & providers",
    description="Provider/practice accounts; deterministic registry IDs (NPI/CMS) are the hook.",
    field_set=(
        _field(
            "healthcare.npi",
            "str",
            PassKind.SCORING,
            pack="healthcare",
            # tier-1 deterministic registries (substrate §3: NPI registry resolver for healthcare).
            tier_plan=("npi", "cms"),
            freshness_ttl=timedelta(days=180),
            # A public registry identifier (NPI) — a public-footprint fact about the provider.
            reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
            # A public registry identifier — a world-fact; neutral (FI-2 §5.2).
            research_scope=ResearchScope.PROJECT_NEUTRAL,
            value_schema={"type": "string"},
            description="National Provider Identifier (deterministic registry id; tier-1).",
        ),
    ),
    # staged-flow §7c: NPI high, CMS high, Google/Places high, job boards high, journals low.
    source_profile=(
        _slot(
            ("npi", _HI),
            ("cms", _HI),
            ("google_places", _HI),
            ("job_boards", _HI),
            ("journals", _LO),
        ),
    ),
)


# --- data_infra ------------------------------------------------------------
DATA_INFRA = Pack(
    pack_key="data_infra",
    namespace="data_infra",
    title="Data infrastructure & developer-tooling companies",
    description="Technographic-heavy accounts; tech stack & migration signals are the hook.",
    field_set=(
        _field(
            "data_infra.migration_signal",
            "str",
            PassKind.DEEP,
            pack="data_infra",
            tier_plan=("engineering_blogs", "exa"),
            freshness_ttl=timedelta(days=60),
            gate="deep-pass",
            # A technographic signal about the company's public engineering footprint — public.
            reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
            # A technographic world-fact about the company — neutral (FI-2 §5.2).
            research_scope=ResearchScope.PROJECT_NEUTRAL,
            value_schema={"type": "string"},
            description="Synthesized infra migration/architecture signal (technographic).",
        ),
    ),
    # staged-flow §7c: job-posting tech mentions high, BuiltWith high, engineering blogs medium.
    source_profile=(
        _slot(
            ("job_postings", _HI),
            ("builtwith", _HI),
            ("engineering_blogs", _MED),
        ),
    ),
)


STARTER_PACKS: tuple[Pack, ...] = (FRONTIER_AI, HEALTHCARE_PRACTICE, DATA_INFRA)


async def load_starter_packs(conn: AsyncConnection) -> None:
    """Register the three worked starter packs (idempotent; re-loading is a no-op)."""
    for pack in STARTER_PACKS:
        await register_pack_catalog(conn, pack)
