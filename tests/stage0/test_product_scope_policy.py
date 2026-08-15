"""Release-closure R1: company/product scope is a shared claim-store invariant."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    ProductScopePolicy,
    ResearchMode,
    ReuseScope,
    RunId,
    new_run_id,
    resolve_product_scope,
)
from clue_research.claimstore import (
    ProductScopeError,
    get_field,
    insert_claim,
    record_run_lineage,
)
from clue_research.identity import insert_account_entity
from clue_research.stage0 import (
    CLIENT_KB_VERSION,
    CLIENT_PRODUCT_CAPABILITY,
    CLIENT_PRODUCT_OVERVIEW,
    PRODUCT_KNOWLEDGE_FIELDS,
    ClientInput,
    VolunteeredMaterial,
    current_kb_version,
    read_client_kb_claims,
    reverse_profile,
)
from clue_research.stage0.fields import CLIENT_VALUE_PROP
from clue_spine import create_brand, create_product

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")


def _claim(
    *,
    entity_id: EntityId,
    workspace_id: str,
    run_id: RunId,
    field_key: str,
    value: object,
    product_id: str | None,
) -> Claim:
    return Claim(
        entity_id=entity_id,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,
        source_url="https://scope-policy.example/evidence",
        evidence_span="bounded evidence",
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=workspace_id,
        product_id=product_id,
    )


async def _scope(conn: AsyncConnection, workspace_id: str) -> tuple[EntityId, str]:
    brand = await create_brand(conn, workspace_id=workspace_id, name="Scope Policy Brand")
    product = await create_product(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name="Scope Policy Product",
    )
    client = await insert_account_entity(
        conn,
        canonical_name="Scope Policy Client",
        primary_domain=f"{workspace_id}.example",
        workspace_id=workspace_id,
        status=AccountStatus.ACTIVE,
    )
    return client, product.product_id


def test_client_pack_declares_company_product_and_dual_marker_policies() -> None:
    async def scenario() -> None:
        workspace_id = f"product-scope-contract-{uuid4().hex[:10]}"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            company = await get_field(conn, CLIENT_VALUE_PROP)
            product = await get_field(conn, CLIENT_PRODUCT_CAPABILITY)
            marker = await get_field(conn, CLIENT_KB_VERSION)
            assert company is not None and product is not None and marker is not None
            assert resolve_product_scope(company) is ProductScopePolicy.FORBIDDEN
            assert resolve_product_scope(product) is ProductScopePolicy.REQUIRED
            assert resolve_product_scope(marker) is ProductScopePolicy.OPTIONAL
            for field_key in PRODUCT_KNOWLEDGE_FIELDS:
                definition = await get_field(conn, field_key)
                assert definition is not None
                assert resolve_product_scope(definition) is ProductScopePolicy.REQUIRED

    run_async(scenario())


def test_application_and_database_refuse_cross_scope_claim_writes() -> None:
    async def scenario() -> None:
        workspace_id = f"product-scope-writes-{uuid4().hex[:10]}"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            client, product_id = await _scope(conn, workspace_id)
            run_id = new_run_id()
            await record_run_lineage(conn, run_id=run_id, workspace_id=workspace_id, kind="stage0")

            product_without_product = _claim(
                entity_id=client,
                workspace_id=workspace_id,
                run_id=run_id,
                field_key=CLIENT_PRODUCT_CAPABILITY,
                value={},
                product_id=None,
            )
            company_with_product = _claim(
                entity_id=client,
                workspace_id=workspace_id,
                run_id=run_id,
                field_key=CLIENT_VALUE_PROP,
                value="company value",
                product_id=product_id,
            )
            with pytest.raises(ProductScopeError, match="requires product_id"):
                await insert_claim(conn, product_without_product)
            with pytest.raises(ProductScopeError, match="forbids product_id"):
                await insert_claim(conn, company_with_product)

            # Bypass Python registry validation deliberately: the database trigger remains the
            # cross-process/direct-SQL backstop.
            with pytest.raises(IntegrityError, match="field requires product_id"):
                async with conn.begin_nested():
                    await insert_claim(conn, product_without_product, validate_field=False)
            with pytest.raises(IntegrityError, match="field forbids product_id"):
                async with conn.begin_nested():
                    await insert_claim(conn, company_with_product, validate_field=False)

    run_async(scenario())


def test_valid_company_product_and_both_marker_forms_remain_writable() -> None:
    async def scenario() -> None:
        workspace_id = f"product-scope-valid-{uuid4().hex[:10]}"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            client, product_id = await _scope(conn, workspace_id)
            run_id = new_run_id()
            await record_run_lineage(conn, run_id=run_id, workspace_id=workspace_id, kind="stage0")
            claims = (
                _claim(
                    entity_id=client,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    field_key=CLIENT_VALUE_PROP,
                    value="company value",
                    product_id=None,
                ),
                _claim(
                    entity_id=client,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    field_key=CLIENT_PRODUCT_CAPABILITY,
                    value={},
                    product_id=product_id,
                ),
                _claim(
                    entity_id=client,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    field_key=CLIENT_KB_VERSION,
                    value={"version": 1, "run_id": str(run_id)},
                    product_id=None,
                ),
                _claim(
                    entity_id=client,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    field_key=CLIENT_KB_VERSION,
                    value={"version": 1, "run_id": str(run_id)},
                    product_id=product_id,
                ),
            )
            inserted = [await insert_claim(conn, claim) for claim in claims]
            assert len(set(inserted)) == 4

    run_async(scenario())


def test_reverse_profile_does_not_turn_company_recon_into_product_recon() -> None:
    async def scenario() -> None:
        workspace_id = f"product-scope-company-recon-{uuid4().hex[:10]}"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            _, product_id = await _scope(conn, workspace_id)
            result = await reverse_profile(
                conn,
                ClientInput(
                    name="Scope Policy Client",
                    website=f"https://{workspace_id}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="onboarding",
                            label="mixed ambient project context",
                            asserted_fields={
                                CLIENT_VALUE_PROP: "account-wide value",
                                CLIENT_PRODUCT_OVERVIEW: "must not cross into product scope",
                            },
                        ),
                    ),
                ),
                workspace_id=workspace_id,
                product_id=product_id,
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            assert result.ref.product_id is None
            assert result.coverage.filled_fields == (CLIENT_VALUE_PROP,)
            assert (
                await current_kb_version(
                    conn,
                    result.ref.client_entity_id,
                    workspace_id=workspace_id,
                    product_id=None,
                )
                == 1
            )
            assert (
                await current_kb_version(
                    conn,
                    result.ref.client_entity_id,
                    workspace_id=workspace_id,
                    product_id=product_id,
                )
                is None
            )

    run_async(scenario())


def test_reverse_profile_requires_explicit_product_scope_for_product_recon() -> None:
    async def scenario() -> None:
        workspace_id = f"product-scope-explicit-recon-{uuid4().hex[:10]}"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            _, product_id = await _scope(conn, workspace_id)
            result = await reverse_profile(
                conn,
                ClientInput(
                    name="Scope Policy Client",
                    website=f"https://{workspace_id}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="product_recon",
                            label="selected product facts",
                            asserted_fields={
                                CLIENT_PRODUCT_OVERVIEW: "selected product overview",
                                CLIENT_VALUE_PROP: "must not cross into company scope",
                            },
                        ),
                    ),
                ),
                workspace_id=workspace_id,
                product_id=product_id,
                knowledge_scope="product",
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            assert result.ref.product_id == product_id
            assert result.coverage.filled_fields == (CLIENT_PRODUCT_OVERVIEW,)
            assert result.coverage.surfaces == ()
            claims = await read_client_kb_claims(
                conn,
                result.ref.client_entity_id,
                workspace_id=workspace_id,
                version=1,
                product_id=product_id,
            )
            assert set(claims) == {CLIENT_PRODUCT_OVERVIEW}

    run_async(scenario())


def test_historical_mis_scoped_claim_is_audited_and_not_served() -> None:
    async def scenario() -> None:
        workspace_id = f"product-scope-history-{uuid4().hex[:10]}"
        async with rollback_conn(workspace_id=workspace_id) as conn:
            client, _product_id = await _scope(conn, workspace_id)
            run_id = new_run_id()
            await record_run_lineage(conn, run_id=run_id, workspace_id=workspace_id, kind="stage0")

            # Simulate an immutable pre-R1 row by temporarily applying the historical optional
            # policy inside this rolled-back fixture. The production migration never rewrites it.
            await conn.execute(
                text(
                    "UPDATE field_definition SET product_scope='optional' "
                    "WHERE field_key=:field_key"
                ),
                {"field_key": CLIENT_PRODUCT_CAPABILITY},
            )
            legacy_id = await insert_claim(
                conn,
                _claim(
                    entity_id=client,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    field_key=CLIENT_PRODUCT_CAPABILITY,
                    value={},
                    product_id=None,
                ),
                validate_field=False,
            )
            await conn.execute(
                text(
                    "UPDATE field_definition SET product_scope='required' "
                    "WHERE field_key=:field_key"
                ),
                {"field_key": CLIENT_PRODUCT_CAPABILITY},
            )
            await insert_claim(
                conn,
                _claim(
                    entity_id=client,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    field_key=CLIENT_KB_VERSION,
                    value={"version": 1, "run_id": str(run_id)},
                    product_id=None,
                ),
            )

            audited = (
                (
                    await conn.execute(
                        text(
                            "SELECT claim_id FROM claim_product_scope_violation "
                            "WHERE workspace_id=:workspace"
                        ),
                        {"workspace": workspace_id},
                    )
                )
                .scalars()
                .all()
            )
            assert audited == [legacy_id]
            company = await read_client_kb_claims(
                conn,
                client,
                workspace_id=workspace_id,
                version=1,
                product_id=None,
            )
            assert CLIENT_PRODUCT_CAPABILITY not in company

    run_async(scenario())
