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
the relevant pack is loaded (the core pack for the ``core.*``/``account.*`` keys here).
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
            "account.total_funding",
            "account.recent_funding",
        ),
        provider="exa",
        auth_ref="CLUE_EXA_API_KEY",
        freshness_profile="operation_window",
        version=3,
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
        yields=(
            "core.employee_count",
            "core.primary_domain",
            "core.industry",
            "core.hq_location",
        ),
        provider="sumble",
        auth_ref="CLUE_SUMBLE_API_KEY",
        rate_limit={"requests_per_second": 10},
        freshness_profile="daily",
        version=2,
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
    # Tier-2 official-source scrape (Firecrawl) — normalized via the M4.3 HTML→markdown adapter.
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
    # Tier-4 research-product placeholders — REGISTERED but resolver-ABSENT until M11. Proves a
    # tier-4 source can be named in a tier_plan before its resolver exists (get_resolver raises).
    _entry(
        "exa_deep",
        modality=Modality.TEXT,
        entity_scope=EntityScope.BOTH,
        tier=4,
        yields=("account", "account.resonance", "contact.facet"),
        provider="exa",
        cost_cents=Decimal(10),
        auth_ref="CLUE_EXA_API_KEY",
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
    (e.g. ``load_core_pack``) so the ``yields`` validation resolves."""
    for entry in SEED_MANIFESTS:
        await register_source(conn, entry)
