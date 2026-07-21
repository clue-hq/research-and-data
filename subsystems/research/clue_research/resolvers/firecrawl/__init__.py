"""The Firecrawl official-site scrape resolver — the canonical tier-2 source (M4.5 / ENG-126).

When tier-1 deterministic APIs miss, the waterfall consults the **entity's own official surface**
*before* any third-party or synthesis source (substrate §4/§12): the company site, careers page,
SEC/filings, the verified LinkedIn company page. This resolver is that tier-2 layer. It does **not**
hand-roll fetch/parse — it runs the source through the M4.3 modality-adapter framework
(``adapters.run_chain`` → the registered ``firecrawl_html`` HTML→markdown adapter), so the scrape
backend (Firecrawl → any crawler) is a config/adapter swap behind the ``Resolver`` seam, and the
returned claims carry the exact ``evidence_span`` and the official ``source_url`` (substrate §4).

This is the one place a resolver reaches into the adapter framework — the M4.5 import carve-out
(``resolvers -> adapters``, import-linter Rule 3a): the ``Resolver`` protocol is synchronous and
connection-less, but the adapter *chain* (fetch/adapt/extract) is sync, so ``run_chain`` runs it
from inside ``resolve`` (over the seed manifest) and hands the materialized-but-unwritten claims
back to the waterfall, which persists them and stamps the run provenance.

Two anti-drift / governance guards live here, where the fetch happens:

* **Target-lock** (staged-flow §5): the resolver only scrapes the resolved entity's *own* domain.
  Given the resolved account, it builds official-surface URLs from ``primary_domain`` and
  **refuses** any off-domain URL — a tier-2 scrape never drifts to a similarly-named org.
* **Exclusion + rate-limit** (M4.2 / D8): a :class:`ScrapePolicy` (per-host / per-jurisdiction ToS
  and robots exclusion) skips a disallowed surface *without scraping it*; the manifest's
  ``rate_limit`` is surfaced to the transport (hard throttling is the M7 scheduler's job).
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_core import (
    AccountEntity,
    Claim,
    Entity,
    EntityType,
    FieldDef,
    ResearchMode,
    ResolverError,
    new_run_id,
    normalize_host,
)
from clue_research.adapters import (
    ClaimExtractor,
    FirecrawlHtmlAdapter,
    ScrapeBackend,
    ScraplingScrapeBackend,
    default_scrape_backend,
    register_adapter,
    run_chain,
)
from clue_research.resolvers.live import AccountLookup
from clue_research.sources import SEED_MANIFESTS, RegistrySourceManifest, bind_resolver
from clue_storage import SnapshotSink, current_snapshot_sink

SOURCE_KEY = "firecrawl_site"
# The credit-free sibling source (PB-B2.4): same trust tier and adapter contract, its own
# manifest (cost 0, provider scrapling) so a free local scrape is never budgeted/attributed as
# paid Firecrawl (audit finding 6). ``register_scrape_resolver`` binds exactly one of the two.
SCRAPLING_SOURCE_KEY = "scrapling_site"
AUTH_REF = "CLUE_FIRECRAWL_API_KEY"
# The M4.3 adapter key each manifest declares (``requires_adapter``); ``run_chain`` dispatches
# through it, so register_scrape_resolver registers the HTML→markdown adapter under the selected
# manifest's key.
ADAPTER_KEY = "firecrawl_html"
SCRAPLING_ADAPTER_KEY = "scrapling_html"

# Build the official surfaces to scrape from a resolved account. The default is the canonical
# homepage on the apex domain; the orchestrator (M6/M8) can inject a richer builder (careers /
# filings / verified LinkedIn). Every URL it returns is target-locked to the entity's own domain.
SurfaceBuilder = Callable[[AccountEntity], list[str]]


def default_surfaces(account: AccountEntity) -> list[str]:
    """The canonical official surface: the account's own homepage (apex domain). A richer set
    (careers / SEC filings / verified LinkedIn) is an injectable :class:`SurfaceBuilder`; all of
    them stay target-locked to ``primary_domain`` (the resolver refuses any off-domain URL)."""
    domain = _registrable_host(account.primary_domain) if account.primary_domain else None
    return [f"https://{domain}"] if domain else []


def _registrable_host(value: str | None) -> str | None:
    """The lower-cased host of a bare domain or a URL, minus a leading ``www.`` — the target-lock
    comparison key. Returns ``None`` when ``value`` has no host. Delegates to the shared
    :func:`clue_core.normalize_host` fold (M9.4 DRY consolidation)."""
    if not value:
        return None
    return normalize_host(value) or None


def _account_country(account: AccountEntity) -> str | None:
    """The account's HQ country (lower-cased) for the per-jurisdiction exclusion, if known."""
    geo = account.hq_geo or {}
    for key in ("country", "country_code", "Country"):
        value = geo.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


class ScrapePolicy(BaseModel):
    """Per-host / per-jurisdiction scrape exclusion (M4.2 / D8) — **policy is data** (conventions
    §2): a disallowed surface is skipped *without scraping it*, never hardcoded in the resolver.
    Designed for the strict (GDPR-grade) case and relaxed per client (Doc D §1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    excluded_hosts: frozenset[str] = frozenset()
    excluded_jurisdictions: frozenset[str] = frozenset()  # lower-cased country codes/names

    def allows(self, host: str, account: AccountEntity) -> bool:
        """True if ``host`` may be scraped for ``account`` (not on a ToS/robots blocklist and the
        account's jurisdiction is not excluded)."""
        if host in self.excluded_hosts:
            return False
        country = _account_country(account)
        return not (country is not None and country in self.excluded_jurisdictions)


class ScrapeResolver:
    """A tier-2 ``Resolver`` (M0.2): scrape the resolved entity's official surface via the M4.3
    adapter, target-locked to its own domain. ``extraction_method='scrape'`` and ``source_tier=2``
    are stamped by ``run_chain`` from the manifest (adaptation never upgrades trust). It holds the
    field ``extractor`` and passes it per-call into ``run_chain`` (the adapter is a pure normalizer;
    extraction is the injected seam). A hard miss (no resolved domain, every surface off-domain or
    excluded, or the extractor finds nothing) is an empty list — a correct flagged-empty output,
    never fabricated."""

    tier: int = 2

    def __init__(
        self,
        manifest: RegistrySourceManifest,
        accounts: AccountLookup | None = None,
        *,
        extractor: ClaimExtractor,
        policy: ScrapePolicy | None = None,
        surface_builder: SurfaceBuilder = default_surfaces,
        snapshots: SnapshotSink | None = None,
    ) -> None:
        self._manifest = manifest
        self._accounts = accounts
        self._extractor = extractor
        self._policy = policy or ScrapePolicy()
        self._surface_builder = surface_builder
        # An OPTIONAL constructor-bound snapshot sink — for a caller that owns both this resolver
        # instance and the sink's lifetime (tests). The registered/production resolver must leave
        # this ``None``: the instance lives in the process-global registry, but a sink is per-run
        # and workspace-bound, so ``resolve`` reads the run-scoped ambient binding
        # (``clue_storage.bind_snapshots``) instead — concurrent runs each capture into their own
        # sink (PB-B2 audit finding 5).
        self._snapshots = snapshots

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if entity.entity_type is not EntityType.ACCOUNT:
            return []  # firecrawl_site is account-scoped (the manifest yields ``account``)
        if self._accounts is None:
            raise ResolverError(
                f"{SOURCE_KEY!r} scrape resolver requires an AccountLookup (wired by the M6/M7 "
                "orchestrator) to target-lock the fetch to the resolved entity's domain"
            )
        account = self._accounts.key_for(entity.entity_id)
        if account is None:
            return []
        domain = _registrable_host(account.primary_domain)
        if domain is None:
            return []  # no resolved domain → target-lock unsatisfiable → hard miss (never guess)
        for url in self._surface_builder(account):
            if _registrable_host(url) != domain:
                # Target-lock (staged-flow §5): refuse an off-domain surface — never scrape a
                # similarly-named org. Skip without fetching.
                continue
            if not self._policy.allows(domain, account):
                # ToS / robots / jurisdiction exclusion (D8): disallowed → skip, do not scrape.
                continue
            params: dict[str, JsonValue] = {"primary_domain": domain}
            if self._manifest.rate_limit is not None:
                # Surface the manifest's rate limit to the transport (M7 enforces; M4.5 honors).
                params["rate_limit"] = dict(self._manifest.rate_limit)
            return run_chain(
                self._manifest,
                url,
                entity,
                field,
                run_id=new_run_id(),  # placeholder — the waterfall restamps the run's id/mode
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                extractor=self._extractor,
                params=params,
                # Constructor-bound sink (a caller-owned instance) wins; else the run-scoped
                # ambient binding — the waterfall re-binds its resolved sink around this call,
                # so capture and flush always share one sink.
                snapshots=self._snapshots
                if self._snapshots is not None
                else current_snapshot_sink(),
            )
        return []  # no allowed, on-domain surface → nothing scraped, a correct empty


def register_scrape_resolver(
    *,
    extractor: ClaimExtractor,
    accounts: AccountLookup | None = None,
    scraper: ScrapeBackend | None = None,
    policy: ScrapePolicy | None = None,
    surface_builder: SurfaceBuilder = default_surfaces,
    snapshots: SnapshotSink | None = None,
) -> str:
    """Wire the official-site scrape source: register the M4.3 HTML→markdown adapter (via
    ``scraper``) under the selected manifest's ``requires_adapter`` key and bind the tier-2
    :class:`ScrapeResolver` (holding the field ``extractor``) to that manifest's source key. The
    M6/M8 orchestrator calls this with the live ``ScrapeBackend`` and a field-specific extractor;
    tests inject doubles. Idempotent (last write wins for the adapter key and the resolver
    binding). Returns the bound source key.

    When no ``scraper`` is injected, the backend is **settings-selected** (PB-B2.4):
    ``CLUE_SCRAPE_BACKEND=firecrawl`` (default, paid API) or ``scrapling`` (local, credit-free).
    The selection also picks the **source manifest** — ``firecrawl_site`` (cost 1¢, provider
    firecrawl) vs ``scrapling_site`` (cost 0, provider scrapling) — so estimates, realized claim
    cost, budget spend, and per-provider economics always attribute the scrape truthfully (audit
    finding 6); a scrapling scrape can never consume Firecrawl budget. The unselected key stays
    registered-but-unbound: a tier plan listing both walks past it at zero spend.

    ``snapshots`` here is for a caller that owns both the registration and the sink's lifetime
    (tests). **Production registration must not pass it** — the resolver lands in the
    process-global registry while a sink is per-run and workspace-bound; the run owner binds the
    per-run sink with ``clue_storage.bind_snapshots`` around the run instead (audit finding 5)."""
    backend = scraper if scraper is not None else default_scrape_backend()
    # The backend's identity decides the economics: an (injected or settings-selected) scrapling
    # backend binds the credit-free manifest; anything else binds the paid firecrawl one.
    source_key = SCRAPLING_SOURCE_KEY if isinstance(backend, ScraplingScrapeBackend) else SOURCE_KEY
    manifest = _seed_manifest(source_key)
    adapter_key = manifest.requires_adapter or ADAPTER_KEY
    register_adapter(adapter_key, FirecrawlHtmlAdapter(scraper=backend))
    bind_resolver(
        source_key,
        ScrapeResolver(
            manifest,
            accounts,
            extractor=extractor,
            policy=policy,
            surface_builder=surface_builder,
            snapshots=snapshots,
        ),
    )
    return source_key


def _seed_manifest(source_key: str = SOURCE_KEY) -> RegistrySourceManifest:
    """The seed manifest for ``source_key`` (the in-memory source of truth for tier/cost/adapter —
    the same pattern ``register_deterministic_resolvers`` uses for per-call cost)."""
    return next(m for m in SEED_MANIFESTS if m.source_key == source_key)
