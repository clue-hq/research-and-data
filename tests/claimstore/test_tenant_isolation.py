"""M2.5 (ENG-124) — tenant isolation at the claim-store layer (live Postgres).

The security-sensitive seam: the ``reuse_scope`` / ``tenant_id`` columns, the scope↔tenant CHECK,
the append-only guard extension, and the tenant-scoped read predicate. The isolation guarantee — a
tenant-private claim is never returned to another tenant under any read path — is asserted directly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from clue_research.claimstore import (
    ALL_TENANTS,
    TenantScope,
    claims_for,
    current_value,
    current_values,
    insert_claim,
    provenance_index,
)
from clue_research.core import (
    Claim,
    ExtractionMethod,
    ReuseScope,
    account_claim,
    new_entity_id,
    new_run_id,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _claim(entity_id: object, field: str, value: object, **over: object) -> Claim:
    base = account_claim(
        entity_id=entity_id,  # type: ignore[arg-type]
        field_key=field,
        value_json=value,  # type: ignore[arg-type]
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        source_url="https://api.example.com",
        confidence=0.9,
        run_id=new_run_id(),
        research_mode="account_profiling",  # type: ignore[arg-type]
    )
    return base.model_copy(update=over) if over else base


def _private(claim: Claim, tenant: str) -> Claim:
    return claim.model_copy(update={"reuse_scope": ReuseScope.TENANT_PRIVATE, "tenant_id": tenant})


def test_db_enum_matches_core_reuse_scope() -> None:
    """The migration's reuse_scope labels stay in lock-step with core.ReuseScope (drift guard)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            labels = {
                r[0]
                for r in (
                    await conn.execute(
                        text(
                            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e "
                            "ON e.enumtypid = t.oid WHERE t.typname = 'reuse_scope'"
                        )
                    )
                ).all()
            }
            assert labels == {m.value for m in ReuseScope}

    run_async(_run())


def test_public_footprint_claim_is_visible_across_tenants() -> None:
    """A public-footprint claim written for an entity is returned under any tenant's scope."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            await insert_claim(
                conn, _claim(entity, "core.employee_count", 250), validate_field=False
            )
            for scope in (
                TenantScope.for_tenant("tenant-a"),
                TenantScope.for_tenant("tenant-b"),
                TenantScope.public_only(),
            ):
                cv = await current_value(conn, entity, "core.employee_count", scope=scope)
                assert cv is not None and cv.value_json == 250

    run_async(_run())


def test_tenant_private_claim_never_leaks_to_another_tenant() -> None:
    """A tenant-private claim written by tenant A is NEVER returned to tenant B (the core isolation
    guarantee) — and is invisible under the public-only scope — but A sees it."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            private = _private(_claim(entity, "account.scoring_fit", {"score": 0.8}), "tenant-a")
            await insert_claim(conn, private, validate_field=False)

            # Tenant B: zero cross-tenant private leakage, on EVERY read path (each is a distinct
            # SQL builder — current_value, current_values, provenance_index, claims_for).
            b = TenantScope.for_tenant("tenant-b")
            assert await current_value(conn, entity, "account.scoring_fit", scope=b) is None
            assert await current_values(conn, [entity], ["account.scoring_fit"], scope=b) == {}
            assert await provenance_index(conn, entity, scope=b) == {}
            assert list(await claims_for(conn, entity, scope=b)) == []
            assert list(await claims_for(conn, entity, scope=TenantScope.public_only())) == []

            # Tenant A (and the operator) sees it.
            a = TenantScope.for_tenant("tenant-a")
            assert await current_value(conn, entity, "account.scoring_fit", scope=a) is not None
            assert len(list(await claims_for(conn, entity, scope=ALL_TENANTS))) == 1

    run_async(_run())


def test_check_rejects_inconsistent_scope_and_tenant() -> None:
    """The CHECK forbids a public claim with a tenant_id and a private claim without one."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            base = {
                "entity_id": new_entity_id(),
                "run_id": new_run_id(),
                "value": "1",
            }
            insert = text(
                """
                INSERT INTO claim (entity_id, entity_type, field_key, value_json, source_tier,
                                   extraction_method, confidence, run_id, research_mode,
                                   reuse_scope, tenant_id)
                VALUES (:entity_id, 'account', 'core.employee_count', CAST(:value AS jsonb), 1,
                        'api', 0.9, :run_id, 'account_profiling',
                        CAST(:reuse_scope AS reuse_scope), :tenant_id)
                """
            )
            # public_footprint must not carry a tenant_id.
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    insert, {**base, "reuse_scope": "public_footprint", "tenant_id": "tenant-a"}
                )
            await trans.rollback()
            # tenant_private must carry a tenant_id.
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    insert, {**base, "reuse_scope": "tenant_private", "tenant_id": None}
                )
            await trans.rollback()

    run_async(_run())


def test_append_only_guard_covers_reuse_scope_and_tenant_id() -> None:
    """tenant_id and reuse_scope are immutable provenance — the append-only guard rejects UPDATEs
    (the M1.4 'silently mutable new column' gotcha, guarded here)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            entity = new_entity_id()
            claim_id = await insert_claim(
                conn, _claim(entity, "core.employee_count", 1), validate_field=False
            )
            for column, value in (
                ("reuse_scope", "CAST('tenant_private' AS reuse_scope)"),
                ("tenant_id", "'tenant-x'"),
            ):
                trans = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await conn.execute(
                        text(f"UPDATE claim SET {column} = {value} WHERE id = :id"),
                        {"id": claim_id},
                    )
                await trans.rollback()

    run_async(_run())


def test_claim_model_rejects_inconsistent_scope_and_tenant() -> None:
    """The core.Claim validator mirrors the DB CHECK (no DB needed)."""
    with pytest.raises(ValueError, match="tenant_private claim must carry a tenant_id"):
        _claim(new_entity_id(), "x.y", 1).model_validate(
            {
                **_claim(new_entity_id(), "x.y", 1).model_dump(),
                "reuse_scope": ReuseScope.TENANT_PRIVATE,
                "tenant_id": None,
            }
        )
    with pytest.raises(ValueError, match="public_footprint claim must not carry a tenant_id"):
        Claim.model_validate(
            {
                **_claim(new_entity_id(), "x.y", 1).model_dump(),
                "reuse_scope": ReuseScope.PUBLIC_FOOTPRINT,
                "tenant_id": "tenant-a",
                "cost_cents": Decimal(0),
            }
        )
