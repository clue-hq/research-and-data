"""M4.5 acceptance: the Firecrawl official-site scrape resolver (tier-2), via the real waterfall.

One test per acceptance criterion (ENG-126): a tier-2 ``scrape`` claim normalized through the M4.3
HTML→markdown adapter (not a hand-rolled fetch) carrying a non-null, *grounded* ``evidence_span``
and the official ``source_url``; **target-lock** (given two similar companies, only the entity's own
domain is scraped and an off-domain surface is refused); a per-host / per-jurisdiction exclusion
that skips a disallowed surface *without scraping it*; the manifest's ``rate_limit`` surfaced to the
transport; and the waterfall ordering (CRM/tier-1 before Firecrawl/tier-2 before any tier-3 source).

The scrape backend is a **double** (no live crawl, no credential) — the adapter seam is what's
proven. Official-site facts are public-footprint, so these resolves need no tenant_id.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_core import (
    AccountEntity,
    Claim,
    ClaimDraft,
    Entity,
    EntityId,
    EntityScope,
    ExtractionMethod,
    FieldDef,
    Modality,
    NormalizedText,
    PassKind,
    RawArtifact,
    ResearchMode,
    Resolver,
    SourceManifest,
    new_entity_id,
    new_run_id,
)
from clue_research.adapters import (
    CallableClaimExtractor,
    FirecrawlHtmlAdapter,
    register_adapter,
    span_for,
)
from clue_research.resolvers import ScrapePolicy, ScrapeResolver, register_scrape_resolver
from clue_research.sources import (
    SEED_MANIFESTS,
    RegistrySourceManifest,
    StopReason,
    bind_resolver,
    register_source,
    resolve_field,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_MODE = ResearchMode.ACCOUNT_PROFILING
_FIELD_KEY = (
    "account.strategic_moves"  # an account str field in the core pack (value_schema string)
)
_FACT = "Acme is expanding into the EMEA market in 2026"
_MARKDOWN = f"# About Acme\n\nWe build data tools. {_FACT}. Careers are booming.\n"


class _Accounts:
    def __init__(self, account: AccountEntity) -> None:
        self._account = account

    def key_for(self, entity_id: EntityId) -> AccountEntity | None:
        return self._account


class _RecordingScraper:
    """A ``ScrapeBackend`` double: returns preset markdown and records every (ref, ctx) it scraped
    — so a test can assert *what* was scraped (target-lock) and that nothing was (exclusion)."""

    def __init__(self, markdown: str = _MARKDOWN) -> None:
        self._markdown = markdown
        self.calls: list[tuple[str, object]] = []

    def scrape(self, ref: str, ctx: object) -> RawArtifact:
        self.calls.append((ref, ctx))
        return RawArtifact(
            ref=ref,
            media_type="text/markdown",
            content=self._markdown.encode("utf-8"),
            metadata={"backend": "fake"},
        )


def _strategic_moves_extractor(
    normalized: NormalizedText, entity: Entity, field: FieldDef
) -> list[ClaimDraft]:
    """Pull the strategic-move sentence out of the scraped markdown, grounded by ``span_for``."""
    if _FACT in normalized.text:
        return [
            ClaimDraft(
                field_key=field.field_key,
                value=_FACT,
                evidence_span=span_for(normalized.text, _FACT),
                confidence=0.85,  # clears the account-class threshold (≈0.75)
            )
        ]
    return []


def _extractor() -> CallableClaimExtractor:
    return CallableClaimExtractor(_strategic_moves_extractor)


def _account(domain: str = "acme.com") -> AccountEntity:
    return AccountEntity(id=new_entity_id(), canonical_name="Acme Corp", primary_domain=domain)


def _field() -> FieldDef:
    return FieldDef(
        field_key=_FIELD_KEY,
        value_type="str",
        tier_plan=("firecrawl_site",),
        pass_kind=PassKind.DEEP,
    )


# --- AC: tier-2 scrape via the M4.3 adapter; grounded span + official source_url --------------


def test_scrape_resolver_conforms_to_protocol_at_tier_2() -> None:
    resolver = ScrapeResolver(_seed_manifest(), _Accounts(_account()), extractor=_extractor())
    assert isinstance(resolver, Resolver)
    assert resolver.tier == 2


def test_scrape_writes_grounded_tier2_claim_with_official_source_url() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            scraper = _RecordingScraper()
            register_scrape_resolver(
                extractor=_extractor(), accounts=_Accounts(account), scraper=scraper
            )
            entity = account.as_entity()
            run_id = new_run_id()
            result = await resolve_field(conn, entity, _field(), mode=_MODE, run_id=run_id)
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            (claim,) = await claims_for_field(conn, entity.entity_id, _FIELD_KEY)
            assert claim.source_tier == 2
            assert claim.extraction_method is ExtractionMethod.SCRAPE
            assert claim.source_key == "firecrawl_site"  # engine-stamped
            # the engine clobbers run_chain's placeholder run_id/mode with the run's real values.
            assert claim.run_id == run_id and claim.research_mode is _MODE
            assert claim.value_json == _FACT
            assert claim.evidence_span and claim.evidence_span in _MARKDOWN  # grounded, non-null
            assert claim.source_url == "https://acme.com"  # the official surface, on-domain
            # It was normalized THROUGH the adapter (markdown), not a hand-rolled fetch.
            assert scraper.calls and scraper.calls[0][0] == "https://acme.com"


def test_scrape_paid_miss_records_manifest_cost_and_no_claim() -> None:
    # A scrape that fetches+adapts but whose extractor finds nothing is a PAID MISS: the costly
    # fetch still cost the manifest's per-call price, but nothing is fabricated. (The Clay
    # tier-1 equivalent is test_paid_call_that_misses_still_records_its_cost; this is tier-2.)
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account()
            scraper = _RecordingScraper()
            register_scrape_resolver(
                extractor=CallableClaimExtractor(
                    lambda n, e, f: []
                ),  # markdown fetched, nothing found
                accounts=_Accounts(account),
                scraper=scraper,
            )
            result = await resolve_field(
                conn, account.as_entity(), _field(), mode=_MODE, run_id=new_run_id()
            )
            assert len(scraper.calls) == 1  # the page WAS scraped (a real, paid fetch)
            assert result.claim_refs == ()  # but nothing extracted → nothing written
            assert result.per_tier[0].n_claims == 0
            # firecrawl_site's seeded manifest cost is 1¢ — the paid miss records it, not 0.
            assert result.per_tier[0].cost_cents == Decimal(1)
            assert result.total_cost_cents == Decimal(1)

    run_async(_run())


# --- AC: target-lock — only the entity's own domain; refuse an off-domain surface -----------------


def test_target_lock_scrapes_only_the_entitys_own_domain() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account("acme.com")
            scraper = _RecordingScraper()
            register_scrape_resolver(
                extractor=_extractor(), accounts=_Accounts(account), scraper=scraper
            )
            await resolve_field(
                conn, account.as_entity(), _field(), mode=_MODE, run_id=new_run_id()
            )
            # The scraped host is the entity's own domain — never a similarly-named org.
            assert [ref for ref, _ in scraper.calls] == ["https://acme.com"]

    run_async(_run())


def test_target_lock_refuses_an_off_domain_surface_for_a_similar_company() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account("acme.com")
            scraper = _RecordingScraper()
            # A misconfigured/adversarial builder points at a *similarly-named* company's domain.
            register_scrape_resolver(
                extractor=_extractor(),
                accounts=_Accounts(account),
                scraper=scraper,
                surface_builder=lambda acct: ["https://acme-corp.com/about"],
            )
            result = await resolve_field(
                conn, account.as_entity(), _field(), mode=_MODE, run_id=new_run_id()
            )
            assert scraper.calls == []  # refused — never scraped the off-domain org
            assert result.claim_refs == ()  # nothing written (no drift to acme-corp.com)

    run_async(_run())


# --- AC: ToS / jurisdiction exclusion — disallowed surface is skipped, not scraped ----------------


def test_excluded_host_is_skipped_not_scraped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account("acme.com")
            scraper = _RecordingScraper()
            register_scrape_resolver(
                extractor=_extractor(),
                accounts=_Accounts(account),
                scraper=scraper,
                policy=ScrapePolicy(excluded_hosts=frozenset({"acme.com"})),
            )
            result = await resolve_field(
                conn, account.as_entity(), _field(), mode=_MODE, run_id=new_run_id()
            )
            assert scraper.calls == []  # disallowed → skipped, NOT scraped
            assert result.claim_refs == ()

    run_async(_run())


def test_excluded_jurisdiction_is_skipped() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = AccountEntity(
                id=new_entity_id(),
                canonical_name="Acme GmbH",
                primary_domain="acme.de",
                hq_geo={"country": "DE"},
            )
            scraper = _RecordingScraper()
            register_scrape_resolver(
                extractor=_extractor(),
                accounts=_Accounts(account),
                scraper=scraper,
                policy=ScrapePolicy(excluded_jurisdictions=frozenset({"de"})),
            )
            result = await resolve_field(
                conn, account.as_entity(), _field(), mode=_MODE, run_id=new_run_id()
            )
            assert scraper.calls == []
            assert result.claim_refs == ()

    run_async(_run())


def test_manifest_rate_limit_is_surfaced_to_the_transport() -> None:
    # The resolver SURFACES the manifest's rate_limit into the fetch context's params, where the
    # transport seam can read it. This proves the plumbing only — M4.5 does NOT enforce a throttle
    # (the live FirecrawlScrapeBackend ignores it today); hard rate-limiting is M7's Redis bucket.
    account = _account("acme.com")
    scraper = _RecordingScraper()
    register_adapter("firecrawl_html", FirecrawlHtmlAdapter(scraper=scraper))
    manifest = _seed_manifest().model_copy(update={"rate_limit": {"rpm": 30}})
    resolver = ScrapeResolver(manifest, _Accounts(account), extractor=_extractor())
    claims = resolver.resolve(account.as_entity(), _field())
    assert len(claims) == 1  # the resolve() path is pure/sync — no DB needed
    assert scraper.calls, "the on-domain surface was scraped"
    _, ctx = scraper.calls[0]
    assert getattr(ctx, "params", {}).get("rate_limit") == {"rpm": 30}


# --- AC: the waterfall consults CRM/tier-1 before Firecrawl/tier-2 before any tier-3 --------------


class _CountingResolver:
    tier = 3

    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        self.calls += 1
        return []


def test_waterfall_consults_crm_then_firecrawl_then_tier3() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account("acme.com")
            scraper = _RecordingScraper()
            register_scrape_resolver(
                extractor=_extractor(), accounts=_Accounts(account), scraper=scraper
            )
            # A tier-1 crm that MISSES this field + a registered tier-3 source bound to a counter.
            from clue_research.resolvers import register_crm_resolver
            from tests.resolvers.test_crm import _Connector  # a CRM double (returns None → miss)

            register_crm_resolver(_Connector(account=None), accounts=_Accounts(account))
            await register_source(
                conn,
                RegistrySourceManifest(
                    manifest=SourceManifest(
                        source_key="news_t3",
                        modality=Modality.TEXT,
                        entity_scope=EntityScope.ACCOUNT,
                        yields=("account",),
                        tier=3,
                    )
                ),
            )
            tier3 = _CountingResolver()
            bind_resolver("news_t3", tier3)

            field = FieldDef(
                field_key=_FIELD_KEY,
                value_type="str",
                tier_plan=("crm", "firecrawl_site", "news_t3"),
                pass_kind=PassKind.DEEP,
            )
            result = await resolve_field(
                conn, account.as_entity(), field, mode=_MODE, run_id=new_run_id()
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            # crm (tier-1) ran and missed; firecrawl (tier-2) ran and hit; tier-3 was NEVER reached.
            outcomes = {s.source_key: s for s in result.per_tier}
            assert outcomes["crm"].n_claims == 0
            assert outcomes["firecrawl_site"].confident
            assert "news_t3" not in outcomes  # the walk stopped before tier-3
            assert tier3.calls == 0 and len(scraper.calls) == 1

    run_async(_run())


# --- helpers ----------------------------------------------------------------


def _seed_manifest() -> RegistrySourceManifest:
    return next(m for m in SEED_MANIFESTS if m.source_key == "firecrawl_site")


async def claims_for_field(conn: object, entity_id: EntityId, field_key: str) -> list[Claim]:
    from clue_research.claimstore import ALL_TENANTS, claims_for

    return list(await claims_for(conn, entity_id, field_key, scope=ALL_TENANTS))  # type: ignore[arg-type]
