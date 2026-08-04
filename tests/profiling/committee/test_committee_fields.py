"""M8.3 committee field pack — ``contact.role_on_committee`` + ``contact.persona`` (DB-gated).

The two committee fields register as deep, tenant-private, enum-validated ``contact.*`` rows,
loadable idempotently and separate from the frozen tiny-seed pack.
"""

from __future__ import annotations

import pytest

from clue_core import (
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    ExtractionMethod,
    FieldClass,
    IdentityBinding,
    PassKind,
    Persona,
    ResearchMode,
    ReuseScope,
    UseClass,
    classify_field_key,
    contact_claim,
    new_entity_id,
    new_run_id,
    resolve_reuse_scope,
)
from clue_research.claimstore import (
    ValueSchemaError,
    WorkspaceScope,
    current_value,
    get_field,
    insert_claim,
    validate_value,
)
from clue_research.identity import stamp_reuse
from clue_research.profiling.committee import (
    COMMITTEE_FIELD_KEYS,
    CONTACT_CLASS,
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
)

from ..conftest import rollback_conn, run_async


def test_committee_and_professional_fields_are_plain_contact_not_facet() -> None:
    # Pure: role/persona are plain contact.* (no facet governance CHECK applies to them).
    assert classify_field_key(ROLE_ON_COMMITTEE) is FieldClass.CONTACT
    assert classify_field_key(PERSONA) is FieldClass.CONTACT
    assert classify_field_key(CONTACT_CLASS) is FieldClass.CONTACT
    assert all(
        classify_field_key(field_key) is FieldClass.CONTACT
        for field_key in CONTACT_PROFESSIONAL_FIELD_KEYS
    )
    assert set(COMMITTEE_FIELD_KEYS) == {
        ROLE_ON_COMMITTEE,
        PERSONA,
        CONTACT_CLASS,
        *CONTACT_PROFESSIONAL_FIELD_KEYS,
    }


def test_pack_registers_deep_tenant_private_fields(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            for key in COMMITTEE_FIELD_KEYS:
                field = await get_field(conn, key)
                assert field is not None, f"{key} not registered"
                assert field.pass_kind is PassKind.DEEP
                assert field.tier_plan == ()  # produced by M3, not waterfall-filled
                # contact.* inherits the class default TENANT_PRIVATE.
                assert resolve_reuse_scope(field) is ReuseScope.TENANT_PRIVATE
                if key in CONTACT_PROFESSIONAL_FIELD_KEYS:
                    assert field.freshness_ttl is not None
                    assert field.freshness_ttl.days == 30

    run_async(scenario())


def test_pack_load_is_idempotent(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await load_committee_pack(conn)  # second load is a no-op, not an error
            assert await get_field(conn, PERSONA) is not None

    run_async(scenario())


def test_persona_value_schema_is_closed_enum(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await validate_value(conn, PERSONA, "economic_buyer")  # ok
            with pytest.raises(ValueSchemaError):
                await validate_value(conn, PERSONA, "ceo")  # not a committee persona

    run_async(scenario())


def test_role_value_schema_requires_role_enum(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await validate_value(
                conn, ROLE_ON_COMMITTEE, {"role": "champion", "confidence": 0.8, "plausible": True}
            )
            with pytest.raises(ValueSchemaError):
                await validate_value(conn, ROLE_ON_COMMITTEE, {"role": "intern"})  # invalid role

    run_async(scenario())


def test_contact_class_is_open_vocabulary_not_a_persona_enum(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await validate_value(conn, CONTACT_CLASS, "clinical")
            await validate_value(conn, CONTACT_CLASS, "business")
            await validate_value(conn, CONTACT_CLASS, "workspace_custom_class")

    run_async(scenario())


def test_missing_contact_class_stays_unknown_and_written_value_has_provenance(
    require_profiling_db: None,
) -> None:
    """Persona does not imply contact class; only an explicit class claim supplies the value."""

    async def scenario() -> None:
        workspace_id = "workspace-contact-class"
        scope = WorkspaceScope.for_workspace(workspace_id)
        contact_id = new_entity_id()
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            persona = stamp_reuse(
                contact_claim(
                    entity_id=contact_id,
                    field_key=PERSONA,
                    value_json=Persona.ECONOMIC_BUYER.value,
                    source_tier=2,
                    extraction_method=ExtractionMethod.SCRAPE,
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PROFESSIONAL_PUBLIC,
                    source_url="https://example.test/team",
                ),
                workspace_id=workspace_id,
            )
            await insert_claim(conn, persona)
            assert await current_value(conn, contact_id, CONTACT_CLASS, scope=scope) is None

            contact_class = stamp_reuse(
                contact_claim(
                    entity_id=contact_id,
                    field_key=CONTACT_CLASS,
                    value_json="clinical",
                    source_tier=2,
                    extraction_method=ExtractionMethod.SCRAPE,
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.COMMITTEE_DISCOVERY,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PROFESSIONAL_PUBLIC,
                    source_url="https://example.test/team",
                ),
                workspace_id=workspace_id,
            )
            await insert_claim(conn, contact_class)
            resolved = await current_value(conn, contact_id, CONTACT_CLASS, scope=scope)
            assert resolved is not None
            assert resolved.value_json == "clinical"
            assert resolved.provenance.claim_id == contact_class.id

    run_async(scenario())
