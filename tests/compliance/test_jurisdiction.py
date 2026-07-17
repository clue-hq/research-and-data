"""M10.1 (jurisdiction resolution) — one test per §M10.1 acceptance criterion.

The pure helpers (region extraction, region→regime mapping, confidence ordering) run without a
database (in ``make check``); :class:`JurisdictionResolverImpl.resolve` is exercised against a live
Postgres (skips without one, like the M9 suites) because it reads the resolved contact/account
entities + location claims via the claim store and writes the ``contact.jurisdiction`` claim.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import (
    DEFAULT_REGIME_MAPPING,
    STRICT_DEFAULT_REGIME,
    Jurisdiction,
    JurisdictionPolicy,
    RegimeMapping,
)
from clue_core import (
    AccountStatus,
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import SPAN_COMPLIANCE_JURISDICTION, InMemorySink, collect_spans
from clue_research.claimstore import current_value, insert_claim
from clue_research.claimstore.registry import _validate_payload
from clue_research.claimstore.tenancy import TenantScope
from clue_research.compliance import (
    COMPLIANCE_PACK,
    DerivedFrom,
    JurisdictionResolution,
    JurisdictionResolverImpl,
    extract_region,
    region_from_value,
    region_to_regime,
)
from clue_research.compliance.jurisdiction import (
    METRIC_JURISDICTION_RESOLVED,
    METRIC_JURISDICTION_UNKNOWN,
    _confidence,
)
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse

from .conftest import rollback_conn, run_async

# =====================================================================================
# Pure helpers (no DB)
# =====================================================================================


def test_extract_region_key_precedence_and_case() -> None:
    assert extract_region({"country": "de"}, ("country", "region")) == "DE"
    # case-insensitive key match; first key wins
    assert extract_region({"Country": "FR", "region": "GB"}, ("country", "region")) == "FR"
    assert extract_region({"region": "us"}, ("country", "region")) == "US"
    assert extract_region(None, ("country",)) is None
    assert extract_region({}, ("country",)) is None
    assert extract_region({"city": "Berlin"}, ("country", "region")) is None  # no matching key
    assert extract_region({"country": "  "}, ("country",)) is None  # blank value


def test_region_from_value_string_or_dict() -> None:
    assert region_from_value("de", ("country",)) == "DE"
    assert region_from_value({"country": "FR"}, ("country",)) == "FR"
    assert region_from_value("", ("country",)) is None
    assert region_from_value(123, ("country",)) is None  # non-str/dict
    assert region_from_value(None, ("country",)) is None


def test_region_to_regime_uses_config_mapping() -> None:
    m = DEFAULT_REGIME_MAPPING
    assert region_to_regime("DE", m) is Jurisdiction.GDPR
    assert region_to_regime("de", m) is Jurisdiction.GDPR  # normalised
    assert region_to_regime("GB", m) is Jurisdiction.UK_GDPR
    assert region_to_regime("US", m) is Jurisdiction.US_STATE
    assert region_to_regime("ZZ", m) is None  # unmapped → resolver fails closed to strict
    assert region_to_regime(None, m) is None


def test_regime_for_handles_full_country_names() -> None:
    # scraped geo dicts often carry a country NAME, not an ISO code — the resolver must map common
    # names; an UNKNOWN name fails closed to strict (returns None → resolver uses STRICT_DEFAULT).
    m = DEFAULT_REGIME_MAPPING
    assert region_to_regime("Germany", m) is Jurisdiction.GDPR
    assert region_to_regime("United States", m) is Jurisdiction.US_STATE
    assert region_to_regime("United Kingdom", m) is Jurisdiction.UK_GDPR
    assert region_to_regime("the netherlands", m) is Jurisdiction.GDPR  # case + article
    assert region_to_regime("Wakanda", m) is None  # unknown name → fail closed
    assert region_to_regime("Atlantis", m) is None


def test_value_json_validates_against_registered_schema() -> None:
    # Guards the critical-bug class in `make check` WITHOUT a DB: the persisted value_json must pass
    # the substrate validator for BOTH a resolved region (string) and the strict-default (region
    # omitted). A list-typed value_schema would crash this; an always-present None region would too.
    resolver = JurisdictionResolverImpl("c", new_run_id(), persist=False)
    schema = COMPLIANCE_PACK[0].value_schema
    assert schema is not None
    resolved = JurisdictionResolution(
        contact_entity_id=new_entity_id(),
        regime=Jurisdiction.GDPR,
        region="DE",
        confidence=0.85,
        derived_from=DerivedFrom.CONTACT_LOCATION,
    )
    _validate_payload(resolver._value_json(resolved), schema)  # must not raise

    strict = JurisdictionResolution(
        contact_entity_id=new_entity_id(),
        regime=Jurisdiction.GDPR,
        region=None,
        confidence=0.0,
        derived_from=DerivedFrom.STRICT_DEFAULT,
        jurisdiction_unknown=True,
    )
    payload = resolver._value_json(strict)
    assert "region" not in payload  # omitted when None (so a plain-string schema validates)
    _validate_payload(payload, schema)  # must not raise


def test_config_only_mapping_change_zero_code(  # AC5 (pure half)
) -> None:
    # Adding/altering a region row changes resolution with no code change — region_to_regime reads
    # the mapping it is handed, never a hardcoded table.
    custom = RegimeMapping(mapping={"ZZ": Jurisdiction.US_STATE})
    assert region_to_regime("ZZ", custom) is Jurisdiction.US_STATE
    assert region_to_regime("ZZ", DEFAULT_REGIME_MAPPING) is None
    # an EU member is GDPR under the default but absent (→ None) under a stripped custom map
    assert region_to_regime("DE", DEFAULT_REGIME_MAPPING) is Jurisdiction.GDPR
    assert region_to_regime("DE", custom) is None


def test_default_mapping_covers_eu_uk_us() -> None:
    m = DEFAULT_REGIME_MAPPING.mapping
    assert m["FR"] is Jurisdiction.GDPR
    assert m["IE"] is Jurisdiction.GDPR
    assert m["NO"] is Jurisdiction.GDPR  # EEA
    assert m["GB"] is Jurisdiction.UK_GDPR
    assert m["US"] is Jurisdiction.US_STATE


def test_strict_default_is_gdpr_grade() -> None:
    assert STRICT_DEFAULT_REGIME is Jurisdiction.GDPR


def test_confidence_strictly_orders_sources() -> None:
    # contact claim (any tier) > contact geo column > account claim (any tier) > account hq column >
    # strict default — so a stronger source always wins a re-resolution comparison.
    contact_claim_worst = _confidence("contact_claim", tier=4)
    contact_geo = _confidence("contact_geo")
    account_claim_best = _confidence("account_claim", tier=1)
    account_hq = _confidence("account_hq")
    strict = _confidence("strict_default")
    assert contact_claim_worst > contact_geo > account_claim_best > account_hq > strict
    # tier bonus monotonic within a source
    assert _confidence("contact_claim", tier=1) > _confidence("contact_claim", tier=4)
    assert 0.0 <= strict <= 1.0 and 0.0 <= _confidence("contact_claim", tier=1) <= 1.0


# =====================================================================================
# DB-gated behaviour (one per acceptance criterion)
# =====================================================================================

_CLIENT = "client-m10-test"


def _resolver(
    conn: AsyncConnection,
    *,
    client_id: str = _CLIENT,
    policy: JurisdictionPolicy | None = None,
    persist: bool = True,
    sink: InMemorySink | None = None,
) -> JurisdictionResolverImpl:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    resolved_policy = policy if policy is not None else JurisdictionPolicy()
    return JurisdictionResolverImpl(
        client_id,
        new_run_id(),
        policy_getter=lambda _cid: resolved_policy,
        conn_factory=factory,
        persist=persist,
        sink=sink,
    )


async def _account(conn: AsyncConnection, *, hq_geo: dict[str, object] | None = None) -> EntityId:
    return await insert_account_entity(
        conn,
        canonical_name="Acme GmbH",
        primary_domain="acme.de",
        hq_geo=hq_geo,
        status=AccountStatus.ACTIVE,
    )


async def _contact(
    conn: AsyncConnection, account_id: EntityId, *, geo: dict[str, object] | None = None
) -> EntityId:
    return await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name="Jana Doe",
        geo=geo,
        status=AccountStatus.ACTIVE,
    )


async def _write_location_claim(
    conn: AsyncConnection,
    contact_id: EntityId,
    region: str,
    *,
    client_id: str = _CLIENT,
    tier: int = 2,
) -> None:
    claim = Claim(
        entity_id=contact_id,
        entity_type=EntityType.CONTACT,
        field_key="contact.location",
        value_json={"country": region},
        source_url="https://example.com/profile",
        source_tier=tier,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
    )
    await insert_claim(conn, stamp_reuse(claim, tenant_id=client_id))


async def _jurisdiction_value(conn: AsyncConnection, contact_id: EntityId) -> dict[str, object]:
    cv = await current_value(
        conn, contact_id, "contact.jurisdiction", scope=TenantScope.for_tenant(_CLIENT)
    )
    assert cv is not None
    assert isinstance(cv.value_json, dict)
    return cv.value_json


async def _live_jurisdiction_count(conn: AsyncConnection, contact_id: EntityId) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM claim WHERE entity_id = :e "
                    "AND field_key = 'contact.jurisdiction' AND superseded_by IS NULL"
                ),
                {"e": contact_id},
            )
        ).scalar_one()
    )


@pytest.mark.usefixtures("require_compliance_db")
def test_contact_location_claim_resolves_with_provenance() -> None:  # AC1, AC6
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_location_claim(conn, contact, "DE", tier=2)

            resolution = await _resolver(conn).resolve(contact)

            assert resolution.regime is Jurisdiction.GDPR
            assert resolution.derived_from is DerivedFrom.CONTACT_LOCATION
            assert resolution.region == "DE"
            assert resolution.jurisdiction_unknown is False
            # AC6: a claim-derived resolution carries provenance claim ids
            assert len(resolution.provenance_claim_ids) == 1
            # the resolution is persisted as a contact.jurisdiction claim, read via current_value
            value = await _jurisdiction_value(conn, contact)
            assert value["regime"] == "gdpr"
            assert value["derived_from"] == "contact_location"

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_stored_jurisdiction_claim_is_tenant_private() -> None:  # tenant isolation
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_location_claim(conn, contact, "DE")
            await _resolver(conn).resolve(contact)

            row = (
                await conn.execute(
                    text(
                        "SELECT reuse_scope, tenant_id FROM claim "
                        "WHERE entity_id = :e AND field_key = 'contact.jurisdiction' "
                        "AND superseded_by IS NULL"
                    ),
                    {"e": contact},
                )
            ).first()
            assert row is not None
            assert row[0] == "tenant_private"
            assert row[1] == _CLIENT

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_account_hq_fallback_below_contact_confidence() -> None:  # AC2
    async def _run() -> None:
        async with rollback_conn() as conn:
            # contact with NO location claim and NO geo column; parent account HQ is in the EU
            account = await _account(conn, hq_geo={"country": "DE"})
            contact = await _contact(conn, account)

            fallback = await _resolver(conn, persist=False).resolve(contact)
            assert fallback.regime is Jurisdiction.GDPR
            assert fallback.derived_from is DerivedFrom.ACCOUNT_HQ
            assert fallback.provenance_claim_ids == ()  # column-derived → no backing claim

            # a contact-location resolution must be strictly more confident than the account-HQ one
            await _write_location_claim(conn, contact, "FR", tier=2)
            contact_level = await _resolver(conn, persist=False).resolve(contact)
            assert contact_level.derived_from is DerivedFrom.CONTACT_LOCATION
            assert fallback.confidence < contact_level.confidence

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_account_location_claim_path() -> None:  # waterfall step 3 (account location claim)
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            # an account location *claim* (public-footprint firmographic HQ), no contact location
            claim = Claim(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.hq_location",
                value_json={"country": "GB"},
                source_url="https://registry.example/acme",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            )
            await insert_claim(conn, stamp_reuse(claim, tenant_id=None))

            resolution = await _resolver(conn, persist=False).resolve(contact)
            assert resolution.regime is Jurisdiction.UK_GDPR
            assert resolution.derived_from is DerivedFrom.ACCOUNT_HQ
            assert len(resolution.provenance_claim_ids) == 1
            # the account-claim path (source-string wiring, not just the pure helper): tier-2 band
            assert 0.40 < resolution.confidence <= 0.55
            # and it is strictly below a contact-location resolution for the same contact
            await _write_location_claim(conn, contact, "DE", tier=2)
            contact_level = await _resolver(conn, persist=False).resolve(contact)
            assert contact_level.derived_from is DerivedFrom.CONTACT_LOCATION
            assert resolution.confidence < contact_level.confidence

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_store_supersedes_all_live_priors() -> None:  # _store collapses a multi-live set to one
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, geo={"country": "DE"})  # resolves to GDPR

            # plant two live contact.jurisdiction claims (the concurrency / stray-sibling case the
            # ≤1-live invariant must survive)
            for regime_val in ("us_state", "uk_gdpr"):
                planted = Claim(
                    entity_id=contact,
                    entity_type=EntityType.CONTACT,
                    field_key="contact.jurisdiction",
                    value_json={
                        "regime": regime_val,
                        "confidence": 0.4,
                        "derived_from": "account_hq",
                        "jurisdiction_unknown": False,
                    },
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=0.4,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                )
                await insert_claim(conn, stamp_reuse(planted, tenant_id=_CLIENT))
            assert await _live_jurisdiction_count(conn, contact) == 2

            await _resolver(conn).resolve(contact)

            # every prior is superseded; exactly one live claim remains, carrying the new regime
            assert await _live_jurisdiction_count(conn, contact) == 1
            value = await _jurisdiction_value(conn, contact)
            assert value["regime"] == "gdpr"

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_contact_geo_column_path() -> None:  # waterfall step 2 (contact geo column)
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account, geo={"country": "IT"})
            resolution = await _resolver(conn, persist=False).resolve(contact)
            assert resolution.regime is Jurisdiction.GDPR
            assert resolution.derived_from is DerivedFrom.CONTACT_LOCATION
            assert resolution.provenance_claim_ids == ()  # column, not a claim

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_no_evidence_resolves_strict_default_unknown() -> None:  # AC3
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)  # no hq_geo
            contact = await _contact(conn, account)  # no geo, no location claim
            sink = InMemorySink()
            with collect_spans() as exporter:
                resolution = await _resolver(conn, sink=sink).resolve(contact)

            assert resolution.regime is STRICT_DEFAULT_REGIME
            assert resolution.derived_from is DerivedFrom.STRICT_DEFAULT
            assert resolution.jurisdiction_unknown is True
            assert resolution.region is None
            assert resolution.provenance_claim_ids == ()
            # observability: the jurisdiction span fired and the unknown metric incremented
            assert any(
                s.name == SPAN_COMPLIANCE_JURISDICTION for s in exporter.get_finished_spans()
            )
            assert sink.counter(METRIC_JURISDICTION_UNKNOWN) == 1.0
            assert (
                sink.counter(
                    METRIC_JURISDICTION_RESOLVED,
                    regime=STRICT_DEFAULT_REGIME.value,
                    derived_from=DerivedFrom.STRICT_DEFAULT.value,
                )
                == 1.0
            )

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_higher_tier_location_supersedes_and_reresolves() -> None:  # AC4
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn, hq_geo={"country": "US"})
            contact = await _contact(conn, account)

            # first resolve: only the US account HQ is known → US_STATE, persisted
            first = await _resolver(conn).resolve(contact)
            assert first.regime is Jurisdiction.US_STATE
            old_row = (
                await conn.execute(
                    text(
                        "SELECT id FROM claim WHERE entity_id = :e "
                        "AND field_key = 'contact.jurisdiction' AND superseded_by IS NULL"
                    ),
                    {"e": contact},
                )
            ).first()
            assert old_row is not None
            old_id = old_row[0]

            # a later, higher-signal contact location claim lands → re-resolve changes the regime
            await _write_location_claim(conn, contact, "DE", tier=2)
            second = await _resolver(conn).resolve(contact)
            assert second.regime is Jurisdiction.GDPR
            assert second.derived_from is DerivedFrom.CONTACT_LOCATION

            # the prior jurisdiction claim is superseded (append-only — no UPDATE in place)
            superseded = (
                await conn.execute(
                    text("SELECT superseded_by FROM claim WHERE id = :id"), {"id": old_id}
                )
            ).scalar_one()
            assert superseded is not None
            # current_value deterministically reflects the new regime
            value = await _jurisdiction_value(conn, contact)
            assert value["regime"] == "gdpr"

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_config_only_regime_change_end_to_end() -> None:  # AC5 (DB half)
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            contact = await _contact(conn, account)
            await _write_location_claim(conn, contact, "DE", tier=2)

            # a client policy whose mapping reclassifies DE → US_STATE: resolution follows config,
            # not code — no resolver change.
            custom_policy = JurisdictionPolicy(
                regime_mapping=RegimeMapping(mapping={"DE": Jurisdiction.US_STATE})
            )
            resolution = await _resolver(conn, policy=custom_policy, persist=False).resolve(contact)
            assert resolution.regime is Jurisdiction.US_STATE

    run_async(_run())
