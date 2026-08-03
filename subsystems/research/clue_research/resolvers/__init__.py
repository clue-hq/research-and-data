"""`clue_research.resolvers` — Source Layer — concrete deterministic resolvers (M4.4 / ENG-122).

The tier-1 deterministic providers that produce the *trustworthy base* of the subsystem — real,
verifiable data with zero LLM (substrate §11 step 3): structured-DB enrichment (Clay/Apollo/
ZoomInfo), technographics (BuiltWith), and the authoritative registries (NPI/DUNS/CIK/LEI). Each one
is the same :class:`~clue_research.resolvers.base.DeterministicResolver` over a provider-specific
:class:`~clue_research.resolvers.base.EnrichmentBackend`, reached only through the M4.1 waterfall
via its M4.2 ``source_key`` binding — nothing downstream knows a concrete provider exists.

The package owns the one-directional binding half of the seam: resolvers register *themselves* into
the source registry via :func:`~clue_research.sources.bind_resolver` (``resolvers → sources``), and
``sources → resolvers`` is import-forbidden (Rule 3c) so the registry never learns a provider name.
Provider SDKs (none are needed here — the transport is generic HTTP) live only inside a provider
sub-package (Rule 4). Resolvers never import one another (Rule 3).

The shared HTTP/SDK client wrapper, the ``auth_ref`` → credential resolver, and the
:class:`~clue_core.RetryableResolverError` taxonomy are built **once** (M4 kickoff decision
3b) — in :mod:`clue_research.resolvers.http` / :mod:`clue_research.resolvers.live` / ``core`` so no
provider re-implements HTTP, retry, or auth.
"""

from __future__ import annotations

from clue_core import ResolverError, RetryableResolverError
from clue_research.resolvers import (
    apollo,
    builtwith,
    clay,
    crm,
    exa,
    firecrawl,
    parallel,
    registries,
    sumble,
    zoominfo,
)
from clue_research.resolvers.base import (
    DeterministicResolver,
    EnrichmentBackend,
    ResolvedField,
    build_claim,
    normalize_record,
    resolved_field,
)
from clue_research.resolvers.crm import (
    CRM_RELATIONSHIP_FIELD,
    CrmAccountRecord,
    CRMConnector,
    CrmContactRecord,
    CrmRelationship,
    CrmResolver,
    CrmSeed,
    lookalike_seeds,
    register_crm_resolver,
    resolve_crm_seeds,
)
from clue_research.resolvers.exa import (
    DEFAULT_EXA_CONFIG,
    ExaDeepConfig,
    register_exa_deep_resolver,
)
from clue_research.resolvers.firecrawl import (
    ScrapePolicy,
    ScrapeResolver,
    default_surfaces,
    register_scrape_resolver,
)
from clue_research.resolvers.grounded import (
    GroundedSynthesisResolver,
    HttpSynthesisBackend,
    SynthesisBackend,
    SynthesisResult,
    SynthesizedField,
    register_synthesis_resolver,
)
from clue_research.resolvers.http import (
    CredentialError,
    ProviderResponseError,
    classify_status,
    get_json,
    resolve_credential,
)
from clue_research.resolvers.live import (
    AccountLookup,
    HttpEnrichmentBackend,
    HttpRequest,
    fetch_via_http,
)
from clue_research.resolvers.parallel import (
    DEFAULT_PARALLEL_CONFIG,
    ParallelTaskConfig,
    register_parallel_task_resolver,
)
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY as SUMBLE_JOBS_SOURCE_KEY,
)
from clue_research.resolvers.sumble import (
    ORGANIZATIONS_SOURCE_KEY as SUMBLE_ORGANIZATIONS_SOURCE_KEY,
)
from clue_research.resolvers.sumble import (
    SUMBLE_API_VERSION,
    SUMBLE_SOURCE_KEYS,
    MappingSumbleSnapshotLookup,
    SumbleClient,
    SumbleContractError,
    SumbleCreditBudget,
    SumbleCreditContractViolation,
    SumbleCreditLimitExceeded,
    SumbleSnapshot,
    SumbleSnapshotLookup,
    SumbleSnapshotResolver,
    SumbleSpendOutcomeUnknown,
    SumbleUnboundedCreditRisk,
    build_sumble_resolvers,
    register_sumble_resolvers,
)
from clue_research.resolvers.sumble import (
    TECH_STACK_SOURCE_KEY as SUMBLE_TECH_STACK_SOURCE_KEY,
)
from clue_research.sources import SEED_MANIFESTS, bind_resolver

# The enrichment provider modules (each a single-module sub-package) and the registry family. The
# registry keys map to the config-driven specs in the ``registries`` family.
_ENRICHMENT_MODULES = (clay, apollo, zoominfo, builtwith)
_REGISTRY_KEYS = ("npi", "duns", "cik", "lei")


def register_deterministic_resolvers(*, accounts: AccountLookup | None = None) -> None:
    """Bind every M4.4 tier-1 resolver to its ``source_key`` (the in-process dispatch the waterfall
    uses). Idempotent (last-write-wins per key). The per-call ``cost_cents`` each resolver stamps is
    read from the **seed manifests** — the single source of truth for a source's price — so the
    realized cost can never silently drift from the registered manifest the waterfall budgets.

    ``accounts`` is the :class:`AccountLookup` the live backends use to turn an ``entity_id``
    into the account's lookup keys; the M6/M7 orchestrator supplies one. It is unused by the
    doubles-driven tests (which bind backend doubles), so it defaults to ``None``.
    """
    cost_for = {m.source_key: m.cost_cents for m in SEED_MANIFESTS}
    for module in _ENRICHMENT_MODULES:
        bind_resolver(
            module.SOURCE_KEY,
            module.make_resolver(accounts=accounts, cost_cents=cost_for[module.SOURCE_KEY]),
        )
    for source_key in _REGISTRY_KEYS:
        bind_resolver(
            source_key,
            registries.make_resolver(
                source_key, accounts=accounts, cost_cents=cost_for[source_key]
            ),
        )


__all__ = [
    # registration entry points (bind resolvers to their source_keys)
    "register_deterministic_resolvers",  # M4.4 tier-1 deterministic providers
    "register_crm_resolver",  # M4.5 CRM (tier-1, tenant-private)
    "register_scrape_resolver",  # M4.5 Firecrawl official-site scrape (tier-2)
    "register_exa_deep_resolver",  # M11.1 Exa Deep (tier-4 grounded synthesis)
    "register_parallel_task_resolver",  # M11.2 Parallel Task (tier-4 grounded synthesis)
    # provider sub-packages (referenced by tier_plan source_keys; never branched on by name)
    "clay",
    "apollo",
    "zoominfo",
    "builtwith",
    "registries",
    "crm",
    "firecrawl",
    "exa",
    "parallel",
    "sumble",
    # M4.5 CRM seam (the connector + records are config; nothing downstream knows the vendor)
    "CRMConnector",
    "CrmResolver",
    "CrmAccountRecord",
    "CrmContactRecord",
    "CrmRelationship",
    "CrmSeed",
    "CRM_RELATIONSHIP_FIELD",
    "resolve_crm_seeds",
    "lookalike_seeds",
    # M4.5 Firecrawl scrape seam
    "ScrapeResolver",
    "ScrapePolicy",
    "default_surfaces",
    # the shared resolver substrate (the seam concrete backends/tests build on)
    "DeterministicResolver",
    "EnrichmentBackend",
    "ResolvedField",
    "resolved_field",
    "normalize_record",
    "build_claim",
    # M11.1/M11.2 tier-4 grounded-synthesis substrate (Exa Deep / Parallel Task build on this)
    "GroundedSynthesisResolver",
    "SynthesisBackend",
    "SynthesisResult",
    "SynthesizedField",
    "HttpSynthesisBackend",
    "register_synthesis_resolver",
    "ExaDeepConfig",
    "DEFAULT_EXA_CONFIG",
    "ParallelTaskConfig",
    "DEFAULT_PARALLEL_CONFIG",
    # Sumble v9 acquisition + durable-snapshot resolver seam
    "SUMBLE_API_VERSION",
    "SUMBLE_SOURCE_KEYS",
    "SUMBLE_ORGANIZATIONS_SOURCE_KEY",
    "SUMBLE_JOBS_SOURCE_KEY",
    "SUMBLE_TECH_STACK_SOURCE_KEY",
    "SumbleClient",
    "SumbleCreditBudget",
    "SumbleSnapshot",
    "SumbleSnapshotLookup",
    "MappingSumbleSnapshotLookup",
    "SumbleSnapshotResolver",
    "SumbleContractError",
    "SumbleCreditLimitExceeded",
    "SumbleUnboundedCreditRisk",
    "SumbleSpendOutcomeUnknown",
    "SumbleCreditContractViolation",
    "build_sumble_resolvers",
    "register_sumble_resolvers",
    # live transport seam (HTTP backend template + the account-key lookup)
    "AccountLookup",
    "HttpEnrichmentBackend",
    "HttpRequest",
    "fetch_via_http",
    # shared HTTP/credential helpers (decision 3b — built once)
    "get_json",
    "classify_status",
    "resolve_credential",
    # the source-layer fault taxonomy (re-exported from core for the resolver-facing API)
    "ResolverError",
    "RetryableResolverError",
    "ProviderResponseError",
    "CredentialError",
]
