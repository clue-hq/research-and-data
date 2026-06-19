"""M1.4 (ENG-123) — the provenance flavors against live Postgres: columns, CHECKs, indexes, and the
weak-binding ↔ merge coordination with M1.2."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.exc import DBAPIError

from clue_research.claimstore import ALL_TENANTS, claims_for, current_value, insert_claim
from clue_research.core import (
    Claim,
    ClaimFlavor,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    contact_field_claim,
    discovery_claim,
    new_entity_id,
    new_run_id,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _discovery_account() -> Claim:
    entity = new_entity_id()
    run = new_run_id()
    return discovery_claim(
        entity_id=entity,
        entity_type=EntityType.ACCOUNT,
        field_key="account.recent_funding",
        value_json={"amount_usd": 1},
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        source_url="https://exa.example/r",
        confidence=0.7,
        run_id=run,
        research_mode=ResearchMode.ACCOUNT_DISCOVERY,
        found_via="exa_search",
        matched_signal="Series B SaaS",
        discovery_confidence=0.82,
    )


def _weak_contact(entity_id, *, binding: IdentityBinding) -> Claim:  # type: ignore[no-untyped-def]
    return contact_field_claim(
        entity_id=entity_id,
        field_key="contact.facet.recent_post",
        value_json="spoke at KubeCon",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        source_url="https://li.example/post",
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=binding,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )


def test_flavor_columns_present() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            cols = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'claim'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {"identity_binding", "use_class", "discovery_provenance", "claim_flavor"} <= cols

    run_async(_run())


def test_flavor_enums_match_core() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT t.typname, e.enumlabel FROM pg_type t "
                        "JOIN pg_enum e ON e.enumtypid = t.oid "
                        "WHERE t.typname IN ('identity_binding','use_class','claim_flavor')"
                    )
                )
            ).all()
        by_type: dict[str, set[str]] = {}
        for typname, label in rows:
            by_type.setdefault(typname, set()).add(label)
        assert by_type["identity_binding"] == {m.value for m in IdentityBinding}
        assert by_type["use_class"] == {m.value for m in UseClass}
        assert by_type["claim_flavor"] == {m.value for m in ClaimFlavor}

    run_async(_run())


def test_discovery_claim_roundtrips() -> None:
    """A discovery claim inserts (skipping field validation) and round-trips its envelope."""

    async def _run() -> None:
        claim = _discovery_account()
        async with rollback_conn() as conn:
            await insert_claim(conn, claim)
            (stored,) = await claims_for(conn, claim.entity_id, scope=ALL_TENANTS)
        assert stored.claim_flavor is ClaimFlavor.DISCOVERY
        assert stored.discovery_provenance is not None
        assert stored.discovery_provenance.found_via == "exa_search"
        assert stored.discovery_provenance.matched_signal == "Series B SaaS"

    run_async(_run())


def test_contact_field_claim_governance_check() -> None:
    """The DB rejects a contact *field* claim missing identity_binding / use_class."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        """
                        INSERT INTO claim (entity_id, entity_type, field_key, value_json,
                                           source_url, source_tier, extraction_method, confidence,
                                           run_id, research_mode, claim_flavor)
                        VALUES (:e, 'contact', 'contact.facet.recent_post', '"hook"'::jsonb,
                                'https://x', 2, 'scrape', 0.8, :r, 'contact_profiling',
                                'field_claim')
                        """
                    ),
                    {"e": new_entity_id(), "r": new_run_id()},
                )

    run_async(_run())


def test_contact_fact_claim_accepted_without_governance() -> None:
    """The governance CHECK accepts a non-personal contact fact (contact.role_on_committee)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            claim_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO claim (entity_id, entity_type, field_key, value_json,
                                           source_url, source_tier, extraction_method, confidence,
                                           run_id, research_mode, claim_flavor)
                        VALUES (:e, 'contact', 'contact.role_on_committee', '"champion"'::jsonb,
                                'https://li', 2, 'scrape', 0.8, :r, 'contact_profiling',
                                'field_claim')
                        RETURNING id
                        """
                    ),
                    {"e": new_entity_id(), "r": new_run_id()},
                )
            ).scalar_one()
        assert claim_id is not None

    run_async(_run())


def test_flavor_columns_are_immutable() -> None:
    """The append-only trigger also guards the M1.4 provenance columns (not just M1.1 columns)."""

    async def _run() -> None:
        claim = _weak_contact(new_entity_id(), binding=IdentityBinding.STRONG)
        async with rollback_conn() as conn:
            claim_id = await insert_claim(conn, claim)
            for column, value in (
                ("identity_binding", "'weak'::identity_binding"),
                ("use_class", "'sensitive'::use_class"),
                ("claim_flavor", "'discovery'::claim_flavor"),
                ("discovery_provenance", "'{}'::jsonb"),
            ):
                trans = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await conn.execute(
                        text(f"UPDATE claim SET {column} = {value} WHERE id = :id"),
                        {"id": claim_id},
                    )
                await trans.rollback()

    run_async(_run())


def test_discovery_db_checks() -> None:
    """The DB rejects a discovery claim with no envelope, or with a non-discovery research_mode."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            for params_sql in (
                # discovery flavor, null discovery_provenance
                "VALUES (:e,'account','account.recent_funding','{}'::jsonb,'https://x',2,"
                "'scrape',0.8,:r,'account_discovery','discovery',NULL)",
                # discovery flavor, non-discovery research_mode (provenance present)
                "VALUES (:e,'account','account.recent_funding','{}'::jsonb,'https://x',2,"
                "'scrape',0.8,:r,'account_profiling','discovery','{}'::jsonb)",
            ):
                trans = await conn.begin_nested()
                with pytest.raises(DBAPIError):
                    await conn.execute(
                        text(
                            "INSERT INTO claim (entity_id, entity_type, field_key, value_json, "
                            "source_url, source_tier, extraction_method, confidence, run_id, "
                            "research_mode, claim_flavor, discovery_provenance) " + params_sql
                        ),
                        {"e": new_entity_id(), "r": new_run_id()},
                    )
                await trans.rollback()

    run_async(_run())


def test_research_mode_enum_rejects_invalid() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "INSERT INTO claim (entity_id, entity_type, field_key, value_json, "
                        "source_url, source_tier, extraction_method, confidence, run_id, "
                        "research_mode) VALUES (:e,'account','account.recent_funding','{}'::jsonb,"
                        "'https://x',1,'api',0.9,:r, CAST('bogus' AS research_mode))"
                    ),
                    {"e": new_entity_id(), "r": new_run_id()},
                )

    run_async(_run())


def test_weak_binding_contact_claim_excluded_from_current_value() -> None:
    """A weak-binding contact claim is stored but never the current_value; a strong one is."""

    async def _run() -> None:
        weak_entity = new_entity_id()
        strong_entity = new_entity_id()
        async with rollback_conn() as conn:
            await insert_claim(conn, _weak_contact(weak_entity, binding=IdentityBinding.WEAK))
            await insert_claim(conn, _weak_contact(strong_entity, binding=IdentityBinding.STRONG))

            weak_cv = await current_value(
                conn, weak_entity, "contact.facet.recent_post", scope=ALL_TENANTS
            )
            strong_cv = await current_value(
                conn, strong_entity, "contact.facet.recent_post", scope=ALL_TENANTS
            )

            # the weak claim is still stored / queryable, just not the current truth
            weak_rows = await claims_for(conn, weak_entity, scope=ALL_TENANTS)
        assert weak_cv is None
        assert strong_cv is not None and strong_cv.value_json == "spoke at KubeCon"
        assert len(weak_rows) == 1 and weak_rows[0].identity_binding is IdentityBinding.WEAK

    run_async(_run())


def test_flavor_indexes_present() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            names = set(
                (
                    await conn.execute(
                        text("SELECT indexname FROM pg_indexes WHERE tablename = 'claim'")
                    )
                )
                .scalars()
                .all()
            )
        assert {
            "claim_research_mode",
            "claim_weak_binding",
            "claim_discovery_provenance_gin",
        } <= names

    run_async(_run())


def test_all_four_modes_persist(make_account: Callable[..., Claim]) -> None:
    """One claim for each research mode / flavor inserts and reads back with the right typing."""

    async def _run() -> None:
        contact_entity = new_entity_id()
        m1 = _discovery_account()  # mode M1 — account discovery
        m2 = make_account(
            research_mode=ResearchMode.ACCOUNT_PROFILING
        )  # mode M2 — account profiling
        m3 = discovery_claim(  # mode M3 — committee discovery
            entity_id=contact_entity,
            entity_type=EntityType.CONTACT,
            field_key="contact.role_on_committee",
            value_json="champion",
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            source_url="https://li.example/p",
            confidence=0.6,
            run_id=new_run_id(),
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            found_via="linkedin",
            matched_signal="VP Eng at target",
            discovery_confidence=0.7,
        )
        m4 = _weak_contact(
            contact_entity, binding=IdentityBinding.STRONG
        )  # mode M4 — contact prof.
        async with rollback_conn() as conn:
            for claim in (m1, m2, m3, m4):
                await insert_claim(conn, claim)
            modes = (
                (
                    await conn.execute(
                        text("SELECT research_mode FROM claim WHERE run_id IN :runs").bindparams(
                            bindparam("runs", expanding=True)
                        ),
                        {"runs": [m1.run_id, m2.run_id, m3.run_id, m4.run_id]},
                    )
                )
                .scalars()
                .all()
            )
        assert set(modes) == {
            "account_discovery",
            "account_profiling",
            "committee_discovery",
            "contact_profiling",
        }

    run_async(_run())
