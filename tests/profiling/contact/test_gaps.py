"""M8.4 contact gap-field computation (DB-gated).

The gap set is the deep contact/facet fields with a tier_plan that lack a fresh value; role/persona
(no tier_plan) are excluded, and a freshly-filled field drops out of the gap set.
"""

from __future__ import annotations

from uuid import UUID

from clue_core import (
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    contact_claim,
)
from clue_research.claimstore import insert_claim
from clue_research.identity import stamp_reuse
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE
from clue_research.profiling.contact import compute_contact_gap_fields
from clue_research.profiling.fields import FACET_FIELD_KEYS, FACET_NICKNAME

from ..conftest import (
    insert_test_account,
    insert_test_contact,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("44444444-4444-4444-4444-444444444444")
_TENANT = "acme"


def test_gaps_are_facet_fields_excluding_role_persona(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            gaps = await compute_contact_gap_fields(conn, contact.id, tenant_id=_TENANT)
            keys = {g.field_key for g in gaps}
            assert set(FACET_FIELD_KEYS).issubset(keys)  # all seeded facets are gaps
            assert ROLE_ON_COMMITTEE not in keys  # no tier_plan → not fillable → not a gap
            assert PERSONA not in keys

    run_async(scenario())


def test_field_keys_filter_narrows_gaps(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            gaps = await compute_contact_gap_fields(
                conn, contact.id, tenant_id=_TENANT, field_keys=[FACET_NICKNAME]
            )
            assert {g.field_key for g in gaps} == {FACET_NICKNAME}

    run_async(scenario())


def test_fresh_field_is_not_a_gap(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            claim = contact_claim(
                entity_id=contact.id,
                field_key=FACET_NICKNAME,
                value_json="Janie",
                source_tier=2,
                extraction_method=ExtractionMethod.SCRAPE,
                confidence=0.9,
                run_id=_RUN,
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                source_url="https://linkedin.com/in/jane-cfo",
                evidence_span="Known as Janie.",
            )
            await insert_claim(conn, stamp_reuse(claim, tenant_id=_TENANT))
            gaps = await compute_contact_gap_fields(conn, contact.id, tenant_id=_TENANT)
            assert FACET_NICKNAME not in {g.field_key for g in gaps}

    run_async(scenario())
