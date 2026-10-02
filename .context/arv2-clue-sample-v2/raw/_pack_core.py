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

from clue_core import (
    EntityType,
    FieldDef,
    PassKind,
    ResearchScope,
    ResearchSectionKind,
    ReuseScope,
)
from clue_research.claimstore.registry import register_field
from clue_research.claimstore.research_view_routes import (
    ResearchRouteContext,
    ResearchRouteProductMode,
    ResearchViewFieldRoute,
    register_research_view_route,
)


@dataclass(frozen=True)
class SeedField:
    """One field definition plus the registry extras not carried on :class:`FieldDef`."""

    field_def: FieldDef
    value_schema: dict[str, Any] | None = None
    corroboration_min: int = 1
    # M9.2 corroboration config (conventions §2 — policy is data). ``single_source_sufficient`` lets
    # a tier-1 deterministic claim verify alone (e.g. a registry ID); ``equality_mode`` picks how
    # corroborator decides two values agree. Defaults match the field_definition column defaults, so
    # a pack that does not care about corroboration declares nothing new.
    single_source_sufficient: bool = False
    equality_mode: str = "exact"
    description: str | None = None
    pack: str | None = None
    research_view_route: ResearchViewFieldRoute | None = None
    research_view_additional_routes: tuple[ResearchViewFieldRoute, ...] = ()


def _account_route(
    field_key: str,
    section_kind: ResearchSectionKind,
    *,
    context_scope: ResearchRouteContext = "subject_current",
    product_mode: ResearchRouteProductMode = "neutral_or_exact",
    ordinal: int = 0,
) -> ResearchViewFieldRoute:
    """Declare presentation-neutral account placement beside the field definition."""

    return ResearchViewFieldRoute(
        field_key=field_key,
        entity_type=EntityType.ACCOUNT,
        section_kind=section_kind,
        context_scope=context_scope,
        product_mode=product_mode,
        ordinal=ordinal,
    )


def _contact_route(
    field_key: str,
    section_kind: ResearchSectionKind,
    *,
    ordinal: int = 0,
) -> ResearchViewFieldRoute:
    return ResearchViewFieldRoute(
        field_key=field_key,
        entity_type=EntityType.CONTACT,
        section_kind=section_kind,
        ordinal=ordinal,
    )


def _seed(
    field_key: str,
    value_type: str,
    pass_kind: PassKind,
    *,
    tier_plan: tuple[str, ...] = (),
    freshness_ttl: timedelta | None = None,
    gate: str | None = None,
    reuse_scope: ReuseScope | None = None,
    research_scope: ResearchScope | None = None,
    value_schema: dict[str, Any] | None = None,
    corroboration_min: int = 1,
    single_source_sufficient: bool = False,
    equality_mode: str = "exact",
    description: str | None = None,
    pack: str | None = None,
    research_view_route: ResearchViewFieldRoute | None = None,
    research_view_additional_routes: tuple[ResearchViewFieldRoute, ...] = (),
) -> SeedField:
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
        single_source_sufficient=single_source_sufficient,
        equality_mode=equality_mode,
        description=description,
        pack=pack,
        research_view_route=research_view_route,
        research_view_additional_routes=research_view_additional_routes,
    )


# ~90-day default freshness; signal/personal fields refresh faster (substrate §6).
CORE_PACK: tuple[SeedField, ...] = (
    _seed(
        "core.account_name",
        "str",
        PassKind.SCORING,
        tier_plan=("registry", "sumble_organizations", "exa_websets"),
        freshness_ttl=timedelta(days=180),
        value_schema={"type": "string"},
        description="Evidence-bearing canonical account name observation.",
        research_view_route=_account_route(
            "core.account_name", ResearchSectionKind.ABOUT, ordinal=1
        ),
    ),
    _seed(
        "core.employee_count",
        "int",
        PassKind.SCORING,
        tier_plan=("clay", "apollo", "sumble_organizations"),
        freshness_ttl=timedelta(days=90),
        value_schema={"type": "integer"},
        description="Total headcount.",
        research_view_route=_account_route(
            "core.employee_count", ResearchSectionKind.ABOUT, ordinal=10
        ),
    ),
    _seed(
        "core.primary_domain",
        "str",
        PassKind.SCORING,
        tier_plan=("registry", "clearbit", "sumble_organizations"),
        freshness_ttl=timedelta(days=180),
        value_schema={"type": "string"},
        description="Primary web domain.",
    ),
    _seed(
        "core.company_linkedin_url",
        "str",
        PassKind.SCORING,
        tier_plan=("sumble_organizations", "apollo", "exa"),
        freshness_ttl=timedelta(days=90),
        value_schema={"type": "string"},
        description="Canonical public LinkedIn company page URL.",
        research_view_route=_account_route(
            "core.company_linkedin_url", ResearchSectionKind.ABOUT, ordinal=5
        ),
    ),
    _seed(
        "core.industry",
        "str",
        PassKind.SCORING,
        # ``exa_deep`` closes the §3.1 row-2 fallback: Sumble Organizations answers it first (tier
        # 1), Exa Deep is the contract's second owner. Without the declaration the Exa account
        # action refuses the field outright (it requires its own source key in the tier plan).
        tier_plan=("sumble_organizations", "apollo", "exa", "exa_deep"),
        freshness_ttl=timedelta(days=90),
        value_schema={"type": "string"},
        description="Primary industry classification returned with account evidence.",
        research_view_route=_account_route("core.industry", ResearchSectionKind.ABOUT, ordinal=15),
    ),
    _seed(
        "core.company_about",
        "str",
        PassKind.SCORING,
        # §3.1 row 3 owners: Exa Deep and Sumble Organizations. Tier discipline keeps the tier-1
        # structured source first; ``exa_deep`` is the qualitative last resort it names.
        tier_plan=("sumble_organizations", "exa_websets", "exa_deep"),
        freshness_ttl=timedelta(days=90),
        value_schema={"type": "string"},
        description="Provider-sourced public company description/about text.",
        research_view_route=_account_route(
            "core.company_about", ResearchSectionKind.ABOUT, ordinal=16
        ),
    ),
    _seed(
        "core.employee_range",
        "object",
        PassKind.SCORING,
        tier_plan=("sumble_organizations", "apollo", "exa"),
        freshness_ttl=timedelta(days=90),
        value_schema={
            "type": "object",
            "required": ["label"],
            "properties": {
                "label": {"type": "string"},
                "min": {"type": "integer"},
                "max": {"type": "integer"},
            },
        },
        description="Evidence-backed employee range used only when exact headcount is unavailable.",
        research_view_route=_account_route(
            "core.employee_range", ResearchSectionKind.ABOUT, ordinal=11
        ),
    ),
    _seed(
        "core.hq_location",
        "object",
        PassKind.SCORING,
        tier_plan=("sumble_organizations", "apollo", "exa"),
        freshness_ttl=timedelta(days=180),
        value_schema={
            "type": "object",
            "required": ["raw"],
            "properties": {
                "raw": {"type": "string"},
                "city": {"type": "string"},
                "region": {"type": "string"},
                "country": {"type": "string"},
                "country_code": {"type": "string"},
            },
        },
        description="Normalized headquarters or primary location plus the source's raw value.",
        research_view_route=_account_route(
            "core.hq_location", ResearchSectionKind.ABOUT, ordinal=12
        ),
    ),
    _seed(
        "core.annual_revenue",
        "object",
        PassKind.SCORING,
        # §3.1 row 7: among the four permitted account sources only Exa Deep can answer revenue
        # (the pinned Sumble organization attributes carry no revenue figure).
        tier_plan=("apollo", "sumble_organizations", "exa", "exa_deep"),
        freshness_ttl=timedelta(days=365),
        value_schema={
            "type": "object",
            "required": ["amount", "currency", "as_of", "estimate_kind"],
            "properties": {
                "amount": {"type": "number"},
                "currency": {"type": "string"},
                "as_of": {"type": "string"},
                "estimate_kind": {
                    "type": "string",
                    "enum": ["reported", "provider_estimate", "third_party_estimate"],
                },
            },
        },
        description=(
            "Annual revenue with currency, as-of date, and explicit reported/estimate semantics."
        ),
        research_view_route=_account_route(
            "core.annual_revenue", ResearchSectionKind.ABOUT, ordinal=18
        ),
    ),
    _seed(
        "core.revenue_band",
        "enum:under_1m|1m_10m|10m_50m|50m_100m|100m_500m|500m_1b|1b_plus",
        PassKind.SCORING,
        tier_plan=("apollo", "sumble_organizations", "exa"),
        freshness_ttl=timedelta(days=365),
        value_schema={
            "type": "string",
            "enum": [
                "under_1m",
                "1m_10m",
                "10m_50m",
                "50m_100m",
                "100m_500m",
                "500m_1b",
                "1b_plus",
            ],
        },
        description="Bounded revenue band used only when exact sourced annual revenue is absent.",
        research_view_route=_account_route(
            "core.revenue_band", ResearchSectionKind.ABOUT, ordinal=19
        ),
    ),
    _seed(
        "core.company_email",
        "str",
        PassKind.SCORING,
        tier_plan=("exa",),
        freshness_ttl=timedelta(days=30),
        value_schema={"type": "string"},
        description="Public general company contact email; not a person's work email.",
    ),
    _seed(
        "core.company_phone",
        "str",
        PassKind.SCORING,
        tier_plan=("exa",),
        freshness_ttl=timedelta(days=30),
        value_schema={"type": "string"},
        description="Public general company contact phone; not a person's direct number.",
    ),
    _seed(
        "core.work_email",
        "str",
        PassKind.DEEP,
        tier_plan=("exa_websets",),
        freshness_ttl=timedelta(days=30),
        gate="selected-contact-channel",
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        value_schema={"type": "string"},
        description=(
            "Selected contact's observed work email. It is delivery data until independent "
            "corroboration, reachability, use permission, and optional identity promotion pass."
        ),
    ),
    _seed(
        "core.direct_phone",
        "str",
        PassKind.DEEP,
        tier_plan=("exa_websets",),
        freshness_ttl=timedelta(days=30),
        gate="selected-contact-channel",
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        value_schema={"type": "string"},
        description=(
            "Selected contact's observed direct phone. It remains delivery data and never becomes "
            "an identity key."
        ),
    ),
    _seed(
        "core.primary_tech_stack",
        "list[str]",
        PassKind.SCORING,
        tier_plan=("builtwith", "sumble_tech_stack"),
        freshness_ttl=timedelta(days=90),
        value_schema={"type": "array", "items": {"type": "string"}},
        description="Detected primary technologies.",
        research_view_route=_account_route(
            "core.primary_tech_stack", ResearchSectionKind.ABOUT, ordinal=20
        ),
    ),
    _seed(
        "account.recent_funding",
        "object",
        PassKind.SCORING,
        # §3.1 row 12: grounded Exa Deep research is the permitted owner that can actually be
        # dispatched today (the pinned Sumble v9 organization action cannot request funding).
        tier_plan=("apollo", "exa", "exa_deep"),
        freshness_ttl=timedelta(days=90),
        value_schema={
            "type": "object",
            "required": ["amount_usd"],
            "properties": {"amount_usd": {"type": "number"}, "round": {"type": "string"}},
        },
        description="Most recent funding round.",
        research_view_route=_account_route(
            "account.recent_funding", ResearchSectionKind.INSIGHTS, ordinal=10
        ),
    ),
    _seed(
        "account.total_funding",
        "object",
        PassKind.SCORING,
        # §3.1 row 11, same reasoning as ``account.recent_funding``.
        tier_plan=("apollo", "exa_websets", "exa_deep"),
        freshness_ttl=timedelta(days=90),
        value_schema={
            "type": "object",
            "required": ["amount_usd", "estimate_kind"],
            "properties": {
                "amount_usd": {"type": "number"},
                "estimate_kind": {
                    "type": "string",
                    "enum": ["reported", "provider_estimate", "third_party_estimate"],
                },
            },
        },
        description="Total funding in USD with explicit estimate semantics.",
        research_view_route=_account_route(
            "account.total_funding", ResearchSectionKind.INSIGHTS, ordinal=9
        ),
    ),
    # The CRM resolver's "already a customer / already in pipeline" flag (M4.5; substrate §4) — a
    # tier-1 ``crm`` field. Its ``crm_import`` extraction_method makes every claim TENANT_PRIVATE at
    # write (the engine's reuse stamping), so this client-asserted relationship never amortizes
    # across tenants. The closed set mirrors ``resolvers.crm.CrmRelationship`` (drift-guarded).
    _seed(
        "account.crm_relationship_status",
        "str",
        PassKind.SCORING,
        tier_plan=("crm",),
        freshness_ttl=timedelta(days=30),
        value_schema={
            "type": "string",
            "enum": ["customer", "open_opportunity", "prospect", "former_customer", "none"],
        },
        description="Client-CRM relationship (already a customer / open opportunity / …); M4.5.",
    ),
    # M6 Pass-A score outputs (ENG-165 W4): the decomposed fit / intent scores M6.3 writes per
    # account. Reserved here as registered fields with reuse_scope=tenant_private so a client-tuned
    # score is *always* tenant-isolated — closing the "ReusePolicy names account.scoring. but no
    # field reserves it" gap (M2.5). M6 writes value_json={"value": <0..1>, "components": [...],
    # "rubric_version": <int>, ...} and stamps workspace_id=workspace_id; the write boundary is
    # fail-closed (a public stamp on these is refused). No resolver/tier_plan — the value is
    # computed by M6.3's pure scorer over current_value (extraction_method is the scorer's).
    _seed(
        "account.scoring.fit",
        "object",
        PassKind.SCORING,
        freshness_ttl=timedelta(days=30),
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        research_scope=ResearchScope.PROJECT_RELATIVE,
        value_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "number"}},
        },
        description="Decomposed ICP fit score (Output 1; M6.3). Tenant-private (per-client ICP).",
    ),
    _seed(
        "account.scoring.intent",
        "object",
        PassKind.SCORING,
        freshness_ttl=timedelta(days=30),
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        research_scope=ResearchScope.PROJECT_RELATIVE,
        value_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "number"}},
        },
        description="Decomposed buying-intent score (Output 1; M6.3). Tenant-private (per-client).",
    ),
    # M6.4 tier decision (ENG-146): the per-account tier the human checkpoint approved against
    # versioned cutoffs. Reserved in the same tenant-private `account.scoring.*` family as fit/
    # intent (so the reuse policy classifies it private — a tier is a per-client/ICP scoring
    # decision, never amortized) with the same fail-closed write boundary. M6.4 writes value_json=
    # {"tier": <str>, "cutoff_version": <str>, "fit_score": <0..1>, "intent_score": <0..1>,
    # "icp_key": …, "icp_version": …, "project_id": …, …} and stamps the run's workspace_id; the
    # value is the human-approved decision at the checkpoint (extraction_method=human), not a
    # resolver fact — so there is no tier_plan. `project_id` (FI-2 §6.4) is the project whose
    # checkpoint approved the tier: it rides value_json because the claim row has no project column,
    # and it is the project leg of the supersede key, so a second project's tier coexists with the
    # first's instead of destroying it. Optional — absent on unstamped tier claims, an *open*
    # class (any writer that omits it), not just pre-§6.4 history.
    _seed(
        "account.scoring.tier",
        "object",
        PassKind.SCORING,
        freshness_ttl=timedelta(days=30),
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        research_scope=ResearchScope.PROJECT_RELATIVE,
        value_schema={
            "type": "object",
            "required": ["tier", "cutoff_version"],
            "properties": {
                "tier": {"type": "string"},
                "cutoff_version": {"type": "string"},
                "project_id": {"type": "string"},
            },
        },
        description="Approved tier assignment + cutoff version (Output 1 tiering; M6.4). "
        "Tenant-private (per-client/ICP decision).",
    ),
    # substrate §3 worked example: a deep-pass signal field with a gate and a tier plan.
    _seed(
        "account.hiring_velocity_eng",
        "number",
        PassKind.DEEP,
        tier_plan=("sumble_jobs", "linkedin_jobs", "exa_deep"),
        freshness_ttl=timedelta(days=30),
        gate="tier>=3",
        value_schema={"type": "number"},
        corroboration_min=2,
        description="Engineering hiring velocity (signal field; substrate §3 example).",
        research_view_route=_account_route(
            "account.hiring_velocity_eng", ResearchSectionKind.INSIGHTS, ordinal=20
        ),
    ),
    _seed(
        "account.operational_pain",
        "str",
        PassKind.DEEP,
        tier_plan=("exa_deep", "parallel_task"),
        freshness_ttl=timedelta(days=90),
        gate="deep-pass",
        value_schema={"type": "string"},
        corroboration_min=2,
        description="Synthesized operational pain.",
        research_view_route=_account_route(
            "account.operational_pain", ResearchSectionKind.INSIGHTS, ordinal=30
        ),
    ),
    _seed(
        "account.strategic_moves",
        "str",
        PassKind.DEEP,
        tier_plan=("exa_deep", "parallel_task"),
        freshness_ttl=timedelta(days=90),
        gate="deep-pass",
        value_schema={"type": "string"},
        corroboration_min=2,
        description="Strategic moves / initiatives.",
        research_view_route=_account_route(
            "account.strategic_moves", ResearchSectionKind.INSIGHTS, ordinal=40
        ),
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
        research_view_route=_account_route(
            "account.resonance.culture", ResearchSectionKind.INSIGHTS, ordinal=50
        ),
    ),
    _seed(
        "contact.facet.recent_post",
        "str",
        PassKind.DEEP,
        tier_plan=("exa_deep", "firecrawl"),
        freshness_ttl=timedelta(days=14),
        gate="committee-gated",
        value_schema={"type": "string"},
        description="Recent public post (personal hook; Doc C §2; governed by M10).",
        research_view_route=_contact_route(
            "contact.facet.recent_post", ResearchSectionKind.QUOTES, ordinal=10
        ),
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
            single_source_sufficient=seed.single_source_sufficient,
            equality_mode=seed.equality_mode,
            description=seed.description,
            pack=seed.pack,
        )
        if seed.research_view_route is not None:
            if seed.research_view_route.field_key != str(seed.field_def.field_key):
                raise ValueError("a research-view route must match its SeedField field_key")
            await register_research_view_route(conn, seed.research_view_route)
        for route in seed.research_view_additional_routes:
            if route.field_key != str(seed.field_def.field_key):
                raise ValueError("a research-view route must match its SeedField field_key")
            await register_research_view_route(conn, route)


async def load_core_pack(conn: AsyncConnection) -> None:
    """Register the seed core pack (idempotent)."""
    await load_pack(conn, CORE_PACK)
