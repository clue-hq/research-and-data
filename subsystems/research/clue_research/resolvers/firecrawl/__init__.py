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
    default_scrape_backend,
    register_adapter,
    run_chain,
)
from clue_research.resolvers.live import AccountLookup
from clue_research.sources import SEED_MANIFESTS, RegistrySourceManifest, bind_resolver
from clue_storage import SnapshotSink

SOURCE_KEY = "firecrawl_site"
AUTH_REF = "CLUE_FIRECRAWL_API_KEY"
# The M4.3 adapter key the firecrawl_site manifest declares (``requires_adapter``); ``run_chain``
# dispatches through it, so register_scrape_resolver registers a FirecrawlHtmlAdapter under it.
ADAPTER_KEY = "firecrawl_html"

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
        # The shared per-run evidence-snapshot sink (PB-B2.3): ``run_chain`` captures the fetched
        # page into it, and the waterfall (which holds the same instance) flushes before insert.
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
                snapshots=self._snapshots,
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
) -> None:
    """Wire the firecrawl scrape source: register its M4.3 ``firecrawl_html`` adapter (the
    HTML→markdown normalizer via ``scraper``) and bind the tier-2 :class:`ScrapeResolver` (holding
    the field ``extractor``) to ``firecrawl_site``. The M6/M8 orchestrator calls this with the live
    Firecrawl-backed ``ScrapeBackend`` and a field-specific extractor; tests inject doubles.
    Idempotent (last write wins for both the adapter key and the resolver binding).

    When no ``scraper`` is injected, the backend is **settings-selected** (PB-B2.4):
    ``CLUE_SCRAPE_BACKEND=firecrawl`` (default, paid API) or ``scrapling`` (local, credit-free) —
    the backend swap the M4.5 seam promised, now a config knob."""
    register_adapter(
        ADAPTER_KEY,
        FirecrawlHtmlAdapter(scraper=scraper if scraper is not None else default_scrape_backend()),
    )
    bind_resolver(
        SOURCE_KEY,
        ScrapeResolver(
            _seed_manifest(),
            accounts,
            extractor=extractor,
            policy=policy,
            surface_builder=surface_builder,
            snapshots=snapshots,
        ),
    )


def _seed_manifest() -> RegistrySourceManifest:
    """The firecrawl_site seed manifest (the in-memory source of truth for tier/cost/adapter — the
    same pattern ``register_deterministic_resolvers`` uses for per-call cost)."""
    return next(m for m in SEED_MANIFESTS if m.source_key == SOURCE_KEY)
