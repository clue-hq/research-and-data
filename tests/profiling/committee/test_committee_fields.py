"""M8.3 committee field pack — ``contact.role_on_committee`` + ``contact.persona`` (DB-gated).

The two committee fields register as deep, tenant-private, enum-validated ``contact.*`` rows,
loadable idempotently and separate from the frozen tiny-seed pack.
"""

from __future__ import annotations

import pytest

from clue_research.claimstore import ValueSchemaError, get_field, validate_value
from clue_research.core import (
    FieldClass,
    PassKind,
    ReuseScope,
    classify_field_key,
    resolve_reuse_scope,
)
from clue_research.profiling.committee import (
    COMMITTEE_FIELD_KEYS,
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
)

from ..conftest import rollback_conn, run_async


def test_committee_fields_are_plain_contact_not_facet() -> None:
    # Pure: role/persona are plain contact.* (no facet governance CHECK applies to them).
    assert classify_field_key(ROLE_ON_COMMITTEE) is FieldClass.CONTACT
    assert classify_field_key(PERSONA) is FieldClass.CONTACT
    assert set(COMMITTEE_FIELD_KEYS) == {ROLE_ON_COMMITTEE, PERSONA}


def test_pack_registers_deep_tenant_private_fields(require_profiling_db: None) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            for key in (ROLE_ON_COMMITTEE, PERSONA):
                field = await get_field(conn, key)
                assert field is not None, f"{key} not registered"
                assert field.pass_kind is PassKind.DEEP
                assert field.tier_plan == ()  # produced by M3, not waterfall-filled
                # contact.* inherits the class default TENANT_PRIVATE.
                assert resolve_reuse_scope(field) is ReuseScope.TENANT_PRIVATE

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
