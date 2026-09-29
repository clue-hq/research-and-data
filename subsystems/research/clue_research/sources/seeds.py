"""Seed source manifests — a real registry for the waterfall/planner to dispatch through (M4.2).

Every source this milestone ships is registered here so M4.1's waterfall and M4.6's planner have a
populated registry: the tier-1 deterministic providers (Clay/Apollo/ZoomInfo/BuiltWith + the
authoritative registries NPI/DUNS/CIK/LEI), the tier-1 CRM (strong identity binding), the tier-2
Firecrawl official-site scrape, and the **resolver-absent tier-4 placeholders** Exa Deep /
Parallel Task — proving a tier-4 source can be *named* in a ``tier_plan`` before its resolver exists
(its resolver lands in M11; ``get_resolver`` raises ``NoResolverBoundError`` until then).

``cost_cents`` and ``geo_coverage`` are D7/D8 config placeholders (re-tunable per the Clay note's
per-field economics). ``auth_ref`` is a credential-store **reference** (an env-var name), never a
secret. ``yields`` reference field-keys/classes from the M1.3 registry — so seeding must run after
the relevant packs are loaded: the **core** pack for the ``core.*``/``account.*`` keys, and (since
slice 3's tier-3 ``exa_search`` entry) the **client-knowledge** pack for the two ``client.*`` keys.
Seeding before either is a loud ``SourceYieldError``, not a silent partial registry.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityScope, IdentityBinding, Modality, SourceManifest
from clue_research.sources.manifest import RegistrySourceManifest
from clue_research.sources.registry import register_source


def _entry(
    source_key: str,
    *,
    modality: Modality,
    entity_scope: EntityScope,
    tier: int,
    yields: tuple[str, ...],
    provider: str,
    cost_cents: Decimal = Decimal(0),
    identity_binding: IdentityBinding | None = None,
    auth_ref: str | None = None,
    rate_limit: dict[str, Any] | None = None,
    requires_adapter: str | None = None,
    geo_coverage: tuple[str, ...] = (),
    freshness_profile: str | None = None,
    version: int = 1,
) -> RegistrySourceManifest:
    return RegistrySourceManifest(
        manifest=SourceManifest(
            source_key=source_key,
            modality=modality,
            entity_scope=entity_scope,
            yields=yields,
            tier=tier,
            cost_cents=cost_cents,
            geo_coverage=geo_coverage,
            freshness_profile=freshness_profile,
            identity_binding_strength=identity_binding,
        ),
        provider=provider,
        auth_ref=auth_ref,
        rate_limit=rate_limit,
        requires_adapter=requires_adapter,
        version=version,
    )


# Tier-1 deterministic structured providers (substrate §4/§12; "real verifiable data, zero LLM").
SEED_MANIFESTS: tuple[RegistrySourceManifest, ...] = (
    # Exa Websets is a structured API transport over Exa's web verification/research system. The
    # API transport does not make every returned web fact tier 1: field materialization chooses the
    # claim tier from its references. The manifest tier is the conservative discovery-provenance
    # default only (discovery claims never win current-value merge).
    _entry(
        "exa_websets",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.BOTH,
        tier=2,
        yields=(
            "core.account_name",
            "core.primary_domain",
            "core.employee_count",
            "core.industry",
            "core.company_about",
            "core.hq_location",
            "core.annual_revenue",
            "core.revenue_band",
            "core.company_linkedin_url",
            "core.company_email",
            "core.company_phone",
            "core.work_email",
            "core.direct_phone",
            "core.primary_tech_stack",
            "core.logo_url",
            "account.total_funding",
            "account.recent_funding",
        ),
        provider="exa",
        auth_ref="CLUE_EXA_API_KEY",
        freshness_profile="operation_window",
        # v4 (2026-09-11): yields ``core.logo_url`` — the LinkedIn company mark Websets returns.
        version=4,
    ),
    _entry(
        "clay",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.BOTH,
        tier=1,
        yields=("core.employee_count", "core.work_email"),
        provider="clay",
        cost_cents=Decimal(5),
        auth_ref="CLUE_CLAY_API_KEY",
        freshness_profile="daily",
    ),
    _entry(
        "apollo",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.BOTH,
        tier=1,
        yields=("core.work_email", "core.employee_count", "account.recent_funding", "contact"),
        provider="apollo",
        cost_cents=Decimal(3),
        identity_binding=IdentityBinding.WEAK,
        auth_ref="CLUE_APOLLO_API_KEY",
        freshness_profile="daily",
    ),
    _entry(
        "zoominfo",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.BOTH,
        tier=1,
        yields=("core.work_email", "contact"),
        provider="zoominfo",
        cost_cents=Decimal(4),
        identity_binding=IdentityBinding.WEAK,
        auth_ref="CLUE_ZOOMINFO_API_KEY",
        freshness_profile="daily",
    ),
    _entry(
        "channel_validator",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.CONTACT,
        tier=1,
        yields=("core.work_email", "core.direct_phone"),
        provider="channel-validator",
        # The concrete independent validator is selected and injected at composition time. This
        # provider-neutral seam must not invent an unresolvable credential reference.
        auth_ref=None,
        freshness_profile="operation_window",
        version=1,
    ),
    _entry(
        "builtwith",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("core.primary_tech_stack",),
        provider="builtwith",
        cost_cents=Decimal(2),
        auth_ref="CLUE_BUILTWITH_API_KEY",
        freshness_profile="weekly",
    ),
    # Sumble's v9 core-data surfaces. Their provider cost is variable and reported as credits on
    # each response, so ``cost_cents`` stays zero here: the Sumble acquisition receipt records the
    # exact provider credits and an optional configured money conversion before the snapshot-backed
    # resolver runs. A fixed manifest price would double-charge multi-field organization snapshots.
    _entry(
        "sumble_organizations",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        # The comprehensive account contract (§3.1) makes this the structured owner of the
        # firmographic identity rows and the two funding rows; the organization snapshot carries
        # them, so the manifest must declare them or the launcher's per-field plan is empty and
        # research is refused. Deliberately absent: ``core.annual_revenue`` — Sumble's pinned v9
        # organization attributes carry no revenue figure, so §3.1 gives that row to Exa Deep alone.
        yields=(
            "core.employee_count",
            "core.primary_domain",
            "core.industry",
            "core.hq_location",
            "core.company_about",
            "core.company_linkedin_url",
            "account.total_funding",
            "account.recent_funding",
        ),
        provider="sumble",
        auth_ref="CLUE_SUMBLE_API_KEY",
        rate_limit={"requests_per_second": 10},
        freshness_profile="daily",
        version=3,
    ),
    _entry(
        "sumble_jobs",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("account.hiring_velocity_eng",),
        provider="sumble",
        auth_ref="CLUE_SUMBLE_API_KEY",
        rate_limit={"requests_per_second": 10},
        freshness_profile="daily",
    ),
    _entry(
        "sumble_tech_stack",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("core.primary_tech_stack",),
        provider="sumble",
        auth_ref="CLUE_SUMBLE_API_KEY",
        rate_limit={"requests_per_second": 10},
        freshness_profile="daily",
    ),
    # S2 bounded organization-map / committee enumeration. These are not waterfall field
    # resolvers, but they still need registry identities so the shared pre-spend gate can validate
    # the exact source key instead of accepting an arbitrary tier-1 people provider. Provider
    # credits are settled by the durable committee-acquisition receipt, so manifest cost is zero.
    _entry(
        "sumble_teams",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("contact",),
        provider="sumble",
        cost_cents=Decimal(0),
        identity_binding=IdentityBinding.WEAK,
        auth_ref="CLUE_SUMBLE_API_KEY",
        rate_limit={"requests_per_second": 10},
        freshness_profile="daily",
    ),
    _entry(
        "sumble_people",
        modality=Modality.STRUCTURED,
        # Committee enumeration is account-scoped; the same exact-person match endpoint can emit a
        # target-locked Contact email observation, so the manifest truthfully covers both.
        entity_scope=EntityScope.BOTH,
        tier=1,
        # The same People endpoint also supports an explicitly selected, paid work-email reveal in
        # exact-person match mode. Committee enumeration remains no-reveal by request contract;
        # declaring the additional yield does not widen that adapter's select list.
        yields=("contact", "core.work_email"),
        provider="sumble",
        cost_cents=Decimal(0),
        identity_binding=IdentityBinding.WEAK,
        auth_ref="CLUE_SUMBLE_API_KEY",
        rate_limit={"requests_per_second": 10},
        freshness_profile="daily",
        version=2,
    ),
    _entry(
        "ai_ark_people",
        modality=Modality.STRUCTURED,
        # The Contacts-table email lookup (founder ruling 2026-09-29): AI Ark's
        # ``/v1/people/export/single`` for one exact LinkedIn-identified person, the same export
        # the ARV2 research agents use. It answers the address with its own mailbox verdict.
        entity_scope=EntityScope.CONTACT,
        tier=1,
        yields=("core.work_email",),
        provider="ai_ark",
        cost_cents=Decimal(0),
        identity_binding=IdentityBinding.STRONG,
        auth_ref="CLUE_AI_ARK_API_KEY",
        rate_limit={"requests_per_second": 0.1},
        freshness_profile="daily",
    ),
    # Authoritative registries — deterministic, tier-1, vertical/jurisdiction-flavored. They yield
    # account-level authoritative facts; finer per-vertical field yields (e.g. healthcare.npi) are
    # added when that vertical pack loads. NPI/CIK/EDGAR are public (no auth_ref).
    _entry(
        "npi",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("account",),
        provider="cms_npi",
        geo_coverage=("US",),
        freshness_profile="monthly",
    ),
    _entry(
        "duns",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("account",),
        provider="dun_and_bradstreet",
        cost_cents=Decimal(1),
        auth_ref="CLUE_DUNS_API_KEY",
        freshness_profile="quarterly",
    ),
    _entry(
        "cik",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("account",),
        provider="sec_edgar",
        geo_coverage=("US",),
        freshness_profile="quarterly",
    ),
    _entry(
        "lei",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.ACCOUNT,
        tier=1,
        yields=("account",),
        provider="gleif",
        freshness_profile="quarterly",
    ),
    # CRM (substrate §4 "worth calling out"): the client's own data, tier-1, strong binding.
    _entry(
        "crm",
        modality=Modality.STRUCTURED,
        entity_scope=EntityScope.BOTH,
        tier=1,
        yields=("account", "contact"),
        provider="crm",
        identity_binding=IdentityBinding.STRONG,
        auth_ref="CLUE_CRM_API_KEY",
        freshness_profile="realtime",
    ),
    # Provider-neutral owned-site evidence emitted by the durable crawl materializer. Provider
    # acquisition cost lives on official_site_fetch_attempt; copying it onto each derived claim
    # would multiply one page cost by the number of fields extracted from it. There is deliberately
    # no resolver binding here: C7 materializes one immutable corpus checkpoint through the normal
    # claim-validation path.
    _entry(
        "official_site",
        modality=Modality.TEXT,
        entity_scope=EntityScope.ACCOUNT,
        tier=2,
        yields=("account",),
        provider="clue",
        cost_cents=Decimal(0),
        freshness_profile="livecrawl",
    ),
    # Historical tier-2 provider-named sources remain immutable/queryable during additive cutover.
    # Firecrawl is normalized via the M4.3 HTML→markdown adapter.
    _entry(
        "firecrawl_site",
        modality=Modality.TEXT,
        entity_scope=EntityScope.ACCOUNT,
        tier=2,
        yields=("account",),
        provider="firecrawl",
        cost_cents=Decimal(1),
        auth_ref="CLUE_FIRECRAWL_API_KEY",
        requires_adapter="firecrawl_html",
        freshness_profile="livecrawl",
    ),
    # Tier-2 official-source scrape via **scrapling** (PB-B2.4) — the credit-free sibling of
    # firecrawl_site (same trust tier, same target-lock, same adapter contract). A DISTINCT
    # source, not a transport swap hidden under firecrawl's manifest: cost_cents=0 and
    # provider="scrapling" so budgets, estimates, and per-provider yield/economics attribute a
    # free local scrape truthfully (audit finding 6). ``register_scrape_resolver`` binds the
    # resolver to exactly one of the two keys per the selected backend; the other stays a
    # registered-but-unbound step the waterfall walks past (NO_RESOLVER, zero spend).
    _entry(
        "scrapling_site",
        modality=Modality.TEXT,
        entity_scope=EntityScope.ACCOUNT,
        tier=2,
        yields=("account",),
        provider="scrapling",
        cost_cents=Decimal(0),
        requires_adapter="scrapling_html",
        freshness_profile="livecrawl",
    ),
    # Tier-3 open-web search (slice 3) — the ONLY source for the two Client-KB fields the client's
    # own surfaces cannot honestly answer: who the market compares them against, and who buys.
    # ``yields`` names the two concrete keys rather than the whole ``client`` namespace because the
    # resolver answers exactly these two (it has a query for nothing else), and the M4.6 planner
    # reads ``yields`` to propose sources for a field — a namespace claim would offer this source
    # for every owned-surface client field it cannot fill. Naming client keys makes the client
    # knowledge pack a boot-order prerequisite of seeding (``yields`` validate against the field
    # registry), which is why every ``seed_source_manifests`` caller loads that pack first.
    # Tier 3 is load-bearing: the Stage-0 fast lane caps at ``max_source_tier=2`` and walks past
    # this at zero spend, so only the background lane ever pays for it.
    _entry(
        "exa_search",
        modality=Modality.TEXT,
        entity_scope=EntityScope.ACCOUNT,
        tier=3,
        yields=("client.competitor", "client.buyer_profile"),
        provider="exa",
        cost_cents=Decimal(1),
        # An open third-party page is never strong personal identity evidence by source prior alone.
        identity_binding=IdentityBinding.WEAK,
        auth_ref="CLUE_EXA_API_KEY",
        freshness_profile="snapshot",
    ),
    # Tier-4 research-product placeholders — REGISTERED but resolver-ABSENT until M11. Proves a
    # tier-4 source can be named in a tier_plan before its resolver exists (get_resolver raises).
    _entry(
        "exa_deep",
        modality=Modality.TEXT,
        entity_scope=EntityScope.BOTH,
        tier=4,
        # §3.1 ownership, stated as the concrete account rows Exa Deep owns rather than the whole
        # ``account`` class. The class token claimed *every* account field — including
        # ``account.hiring_velocity_eng``, which §3.1 gives to Sumble Jobs alone — so a planned
        # field carried two authorized sources and the deep lane could buy a second provider for a
        # row it was never granted. The two class tokens that remain are whole-class ownership:
        # §3.1 gives Exa Deep all six ``account.resonance.*`` rows and §7.1 all nine
        # ``contact.facet.*`` rows.
        yields=(
            "core.company_about",
            "core.industry",
            "core.annual_revenue",
            "account.total_funding",
            "account.recent_funding",
            "account.operational_pain",
            "account.strategic_moves",
            "account.resonance",
            "contact.facet",
        ),
        provider="exa",
        cost_cents=Decimal(10),
        auth_ref="CLUE_EXA_API_KEY",
        version=2,
    ),
    _entry(
        "parallel_task",
        modality=Modality.TEXT,
        entity_scope=EntityScope.BOTH,
        tier=4,
        yields=("account", "account.resonance"),
        provider="parallel",
        cost_cents=Decimal(10),
        auth_ref="CLUE_PARALLEL_API_KEY",
    ),
    # Internal, governed LLM source used only after person admission to classify an already known
    # contact's committee role. It is not a people-discovery source or waterfall resolver;
    # registration gives the exact-source pre-spend gate a real authority row. Gateway receipts
    # own the model cost, so the manifest stays zero-cost to avoid double counting.
    _entry(
        "llm_role_inference",
        modality=Modality.CONVERSATION,
        entity_scope=EntityScope.CONTACT,
        tier=4,
        yields=("contact",),
        provider="llm_gateway",
        cost_cents=Decimal(0),
        freshness_profile="operation_window",
    ),
)


async def seed_source_manifests(conn: AsyncConnection) -> None:
    """Register every seed manifest (idempotent). Run after the referenced fields are registered
    (``load_core_pack`` **and** ``load_client_knowledge_pack``) so the ``yields`` validation
    resolves."""
    for entry in SEED_MANIFESTS:
        await register_source(conn, entry)
