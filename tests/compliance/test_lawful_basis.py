"""M10.5 — lawful-basis recording (Doc D §4): tests, one per acceptance criterion.

Pure tests (no DB) cover the derivation matrix, the retention horizon, the Art. 14 third-party
default, the personal-shorter-than-firmographic config invariant, and the migration CHECK drift
guard; DB-gated tests cover recording (professional → legitimate_interest + LIA; sensitive → none),
the use-class-required guard, the UPSERT idempotency, and the third-party notice report. DB tests
``pytest.skip`` without a reachable database (``make check`` stays green without one).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.compliance import (
    LawfulBasis,
    derive_lawful_basis,
    is_third_party_collected,
    load_lawful_basis,
    record_lawful_basis,
    retention_horizon_for,
    third_party_notice_report,
)
from clue_research.config import (
    FreshnessTtls,
    Jurisdiction,
    LawfulBasisDefaults,
    RetentionTtls,
)
from clue_research.core import (
    AccountStatus,
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    new_run_id,
)
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse

from .conftest import rollback_conn, run_async

_CLIENT = "client-lawful"
_PRO = UseClass.PROFESSIONAL_PUBLIC
_PERSONAL = UseClass.PERSONAL_PUBLIC_NON_SENSITIVE
_SENSITIVE = UseClass.SENSITIVE


# --- pure tests -------------------------------------------------------------


def test_derive_lawful_basis_matrix() -> None:
    """professional/personal → legitimate_interest (+ the client's LIA ref); sensitive → none."""
    defaults = LawfulBasisDefaults(lia_ref="https://client.example/lia/v1")
    assert derive_lawful_basis(_PRO, defaults) == (
        LawfulBasis.LEGITIMATE_INTEREST,
        "https://client.example/lia/v1",
    )
    assert derive_lawful_basis(_PERSONAL, defaults) == (
        LawfulBasis.LEGITIMATE_INTEREST,
        "https://client.example/lia/v1",
    )
    # sensitive → none for outreach (Art. 9), no LIA — reinforces the M10.3 hard floor.
    assert derive_lawful_basis(_SENSITIVE, defaults) == (LawfulBasis.NONE, None)


def test_sensitive_basis_floor_is_in_code_not_config() -> None:
    """The Art. 9 floor is enforced in code: a misconfigured/typo'd ``sensitive_basis`` cannot make
    a special-category claim record legitimate_interest (mirrors the M10.3 gate's in-code floor)."""
    misconfigured = LawfulBasisDefaults(sensitive_basis="legitimate_interest", lia_ref="lia://oops")
    assert derive_lawful_basis(_SENSITIVE, misconfigured) == (LawfulBasis.NONE, None)


def test_derive_lawful_basis_default_has_no_lia() -> None:
    """The platform default carries no LIA ref (the client supplies one) — basis still set."""
    basis, lia = derive_lawful_basis(_PRO, LawfulBasisDefaults())
    assert basis is LawfulBasis.LEGITIMATE_INTEREST
    assert lia is None


def test_derive_lawful_basis_unknown_basis_fails_loud() -> None:
    """A configured basis string that is not a LawfulBasis raises (a policy typo must surface)."""
    bad = LawfulBasisDefaults(professional_public_basis="legit_interest_typo")
    with pytest.raises(ValueError, match="not a recognised LawfulBasis"):
        derive_lawful_basis(_PRO, bad)


def test_derive_lawful_basis_consent_is_recognised() -> None:
    """A client that configures consent (e.g. they hold it) derives CONSENT, with no LIA ref."""
    basis, lia = derive_lawful_basis(
        _PERSONAL, LawfulBasisDefaults(personal_public_basis="consent")
    )
    assert basis is LawfulBasis.CONSENT
    assert lia is None  # the LIA pointer attaches only to legitimate interest


def test_retention_horizon_orders_sensitive_shortest() -> None:
    """Sensitive is aged out fastest; professional held longest (Doc D §4 minimization)."""
    ttls = RetentionTtls()
    sensitive = retention_horizon_for(_SENSITIVE, ttls)
    personal = retention_horizon_for(_PERSONAL, ttls)
    professional = retention_horizon_for(_PRO, ttls)
    assert sensitive == ttls.sensitive_claim_ttl
    assert personal == ttls.personal_claim_ttl
    assert professional == ttls.professional_claim_ttl
    assert sensitive is not None and personal is not None and professional is not None
    assert sensitive < personal < professional


def test_personal_retention_shorter_than_firmographic() -> None:
    """AC: personal-field TTLs are strictly shorter than firmographic TTLs (config invariant).

    Two surfaces encode it: **every** personal retention horizon (RetentionTtls — sensitive,
    personal, AND professional) is strictly shorter than the firmographic *freshness* TTL
    (FreshnessTtls core = 365d firmographic), and the personal *field* freshness TTL (contact.facet)
    is shorter than the firmographic field TTL (core). Professional-public is the longest-held
    personal class but is still strictly < firmographic (Doc D §4 minimization holds for all
    three)."""
    retention = RetentionTtls()
    fresh = FreshnessTtls().by_field_class
    firmographic_ttl = fresh["core"]
    assert retention.sensitive_claim_ttl < firmographic_ttl
    assert retention.personal_claim_ttl < firmographic_ttl
    assert (
        retention.professional_claim_ttl < firmographic_ttl
    )  # the dominant class, no longer == 365d
    # the personal field-class freshness TTL is also strictly shorter than the firmographic one
    assert fresh["contact.facet"] < fresh["core"]
    assert fresh["contact"] <= fresh["core"]


def test_is_third_party_collected() -> None:
    """Web/API/synthesis sources are third-party (Art. 14); human/CRM values are not."""
    assert is_third_party_collected(_make_facet(EntityId("00000000-0000-0000-0000-0000000000aa")))
    human = _make_facet(
        EntityId("00000000-0000-0000-0000-0000000000bb"),
        method=ExtractionMethod.HUMAN,
        source_url=None,
    )
    assert not is_third_party_collected(human)


def test_lawful_basis_check_matches_enum() -> None:
    """Pure no-DB drift guard: the migration CHECK value set equals the LawfulBasis enum values."""
    module = _load_migration()
    assert tuple(b.value for b in LawfulBasis) == module._LAWFUL_BASIS


# --- DB-gated tests ---------------------------------------------------------


@pytest.mark.usefixtures("require_compliance_db")
def test_record_lawful_basis_professional() -> None:  # AC1
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            defaults = LawfulBasisDefaults(lia_ref="lia://v1")
            record = await record_lawful_basis(
                conn, claim, regime=Jurisdiction.GDPR, defaults=defaults
            )
            assert record.lawful_basis is LawfulBasis.LEGITIMATE_INTEREST
            assert record.lia_ref == "lia://v1"
            assert record.third_party_collected is True  # scraped (Art. 14)
            assert record.retention_until is not None
            assert record.regime is Jurisdiction.GDPR
            loaded = await load_lawful_basis(conn, claim.id)
            assert loaded == record

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_retention_until_uses_observed_at() -> None:
    """retention_until is computed from observed_at (when set), matching the moment the M9.5
    retention
    sweep ages the claim out — so the recorded/disclosed erasure deadline does not overstate it."""

    async def _run() -> None:
        from datetime import UTC, datetime, timedelta

        async with rollback_conn() as conn:
            contact = await _contact(conn)
            observed = datetime(2026, 1, 1, tzinfo=UTC)  # published well before it was scraped
            claim = _make_facet(contact, use_class=_PRO)
            claim = claim.model_copy(update={"observed_at": observed})
            await _insert_claim(conn, claim)
            record = await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)
            # professional horizon = 300d, anchored on observed_at (not collected_at = now)
            assert record.retention_until == observed + timedelta(days=300)

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_record_lawful_basis_sensitive_is_none() -> None:  # AC1
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_SENSITIVE)
            record = await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)
            assert record.lawful_basis is LawfulBasis.NONE
            assert record.lia_ref is None

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_record_lawful_basis_requires_use_class() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = await _account(conn)
            # an account (non-personal) claim carries no use_class → recording raises
            claim = Claim(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="account.hq_location",
                value_json={"country": "DE"},
                source_url="https://acme.de",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
            )
            with pytest.raises(ValueError, match="use_class is None"):
                await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_record_lawful_basis_idempotent_upsert() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)
            # re-record under a re-resolved regime → one row, UPSERT-refreshed (post-insert)
            await record_lawful_basis(conn, claim, regime=Jurisdiction.US_STATE)
            rows = (
                await conn.execute(
                    text("SELECT regime FROM lawful_basis_record WHERE claim_id = :c"),
                    {"c": str(claim.id)},
                )
            ).all()
            assert len(rows) == 1
            assert rows[0][0] == Jurisdiction.US_STATE.value

    run_async(_run())


@pytest.mark.usefixtures("require_compliance_db")
def test_third_party_notice_report() -> None:  # AC6
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)
            report = await third_party_notice_report(conn, tenant_id=_CLIENT)
            assert report.third_party_claims >= 1
            assert report.third_party_contacts >= 1
            # a different tenant sees none of this controller's third-party claims
            other = await third_party_notice_report(conn, tenant_id="someone-else")
            assert other.third_party_claims == 0


@pytest.mark.usefixtures("require_compliance_db")
def test_third_party_notice_report_excludes_superseded() -> None:  # AC6 — live filter
    async def _run() -> None:
        from clue_research.claimstore import supersede_claim

        async with rollback_conn() as conn:
            contact = await _contact(conn)
            claim = await _insert_facet(conn, contact, use_class=_PRO)
            await record_lawful_basis(conn, claim, regime=Jurisdiction.GDPR)
            assert (
                await third_party_notice_report(conn, tenant_id=_CLIENT)
            ).third_party_claims == 1
            # supersede the claim (as erasure/rectify would): its lawful_basis_record survives, but
            # the report counts only live claims, so the now-superseded claim drops out
            newer = _make_facet(contact, use_class=_PRO)
            await supersede_claim(conn, claim.id, stamp_reuse(newer, tenant_id=_CLIENT))
            assert (
                await third_party_notice_report(conn, tenant_id=_CLIENT)
            ).third_party_claims == 0

    run_async(_run())


# --- helpers ----------------------------------------------------------------


def _load_migration() -> object:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/b56207f907f2_m10_5_lawful_basis_record_dsar_.py"
    )
    spec = importlib.util.spec_from_file_location("_m105_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_facet(
    contact: EntityId,
    *,
    use_class: UseClass = _PRO,
    method: ExtractionMethod = ExtractionMethod.SCRAPE,
    source_url: str | None = "https://www.linkedin.com/in/jana",
) -> Claim:
    return Claim(
        entity_id=contact,
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.test_hook",
        value_json="runs the Berlin marathon",
        source_url=source_url,
        evidence_span="Jana Doe ran the Berlin marathon in 2025.",
        source_tier=2,
        extraction_method=method,
        identity_binding=IdentityBinding.STRONG,
        use_class=use_class,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
    )


async def _account(conn: AsyncConnection) -> EntityId:
    return await insert_account_entity(
        conn, canonical_name="Acme GmbH", primary_domain="acme.de", status=AccountStatus.ACTIVE
    )


async def _contact(conn: AsyncConnection) -> EntityId:
    account = await _account(conn)
    return await insert_contact_entity(
        conn, account_entity_id=account, full_name="Jana Doe", status=AccountStatus.ACTIVE
    )


async def _insert_facet(conn: AsyncConnection, contact: EntityId, *, use_class: UseClass) -> Claim:
    return await _insert_claim(conn, _make_facet(contact, use_class=use_class))


async def _insert_claim(conn: AsyncConnection, claim: Claim) -> Claim:
    from clue_research.claimstore import insert_claim

    await insert_claim(conn, stamp_reuse(claim, tenant_id=_CLIENT))
    return claim
