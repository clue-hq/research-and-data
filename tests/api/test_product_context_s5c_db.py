"""S5-C exact product readers and deterministic card compiler acceptance."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from clue_api.client_context_binding import bind_workspace_client
from clue_api.product_catalog_sync import ProductCatalogSynchronizer
from clue_api.product_context_compiler import (
    ProductContextScopeError,
    compile_client_knowledge_card_v2,
    compile_product_knowledge_card,
    compile_product_profile_card,
    read_client_product_catalog_page,
)
from clue_api.product_knowledge_reader import load_pinned_product_knowledge
from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    RunId,
)
from clue_db import db_lifespan, transaction
from clue_projections import (
    CLIENT_KNOWLEDGE_CARD_V2_POLICY,
    PRODUCT_KNOWLEDGE_CARD_POLICY_V1,
    ProductKnowledgeCard,
)
from clue_research.claimstore import insert_claim, record_run_lineage
from clue_research.stage0 import PRODUCT_KNOWLEDGE_FIELDS, finalize_client_kb_version
from clue_spine import create_product
from clue_storage import FsStorage
from tests.db.conftest import run_async
from tests.official_site.test_materialization_c7_db import _request, _seed_scope

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _seed_product_context(tmp_path: Path):
    scope = await _seed_scope(FsStorage(tmp_path / "s5c"))
    async with transaction() as conn:
        await bind_workspace_client(
            conn,
            workspace_id=scope.workspace_id,
            client_entity_id=scope.client_entity_id,
            source_recon_run_id=scope.recon_run_id,
        )
        products = []
        for ordinal in range(3):
            products.append(
                await create_product(
                    conn,
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    name=f"Product {ordinal + 1}",
                    aliases=(f"Catalog Alias {ordinal + 1}",),
                )
            )
        catalog = Claim(
            entity_id=scope.client_entity_id,
            entity_type=EntityType.ACCOUNT,
            field_key="client.product_catalog",
            value_json=[
                {
                    "name": f"Catalog Alias {ordinal + 1}",
                    "short_description": f"Grounded product {ordinal + 1}",
                    "aliases": [],
                }
                for ordinal in range(3)
            ],
            source_tier=2,
            source_url="https://example.com/products",
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.9,
            run_id=RunId(scope.claim_run_id),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id=scope.workspace_id,
        )
        await insert_claim(conn, catalog)

        product_run = RunId(uuid4())
        await record_run_lineage(
            conn,
            run_id=product_run,
            workspace_id=scope.workspace_id,
            kind="stage0",
        )
        for field_key in PRODUCT_KNOWLEDGE_FIELDS:
            value: object = (
                {"name": field_key, "detail": "Grounded product fact"}
                if field_key
                in {
                    "client.product_capability",
                    "client.product_use_case",
                    "client.product_pricing",
                    "client.product_integration",
                    "client.product_competitor",
                    "client.product_customer_evidence",
                }
                else f"Grounded {field_key}"
            )
            await insert_claim(
                conn,
                Claim(
                    entity_id=scope.client_entity_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key=field_key,
                    value_json=value,  # type: ignore[arg-type]
                    source_tier=1,
                    extraction_method=ExtractionMethod.HUMAN,
                    confidence=Decimal("1"),
                    run_id=product_run,
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=scope.workspace_id,
                    product_id=products[0].product_id,
                ),
            )
        product_version = await finalize_client_kb_version(
            conn,
            client_entity_id=scope.client_entity_id,
            workspace_id=scope.workspace_id,
            run_id=product_run,
            filled_fields=set(PRODUCT_KNOWLEDGE_FIELDS),
            attempted_fields=set(PRODUCT_KNOWLEDGE_FIELDS),
            product_id=products[0].product_id,
        )
    await ProductCatalogSynchronizer(transaction).synchronize(
        _request(scope),
        company_client_kb_version=1,
    )
    return scope, tuple(products), product_version


def test_v2_company_catalog_profile_and_product_card_are_separate_and_exact(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        scope, products, product_version = await _seed_product_context(tmp_path)
        company = await compile_client_knowledge_card_v2(
            workspace_id=scope.workspace_id,
            client_entity_id=scope.client_entity_id,
            company_client_kb_version=1,
            policy=CLIENT_KNOWLEDGE_CARD_V2_POLICY.model_copy(update={"max_catalog_entries": 1}),
        )
        assert len(company.product_catalog.entries) == 1
        assert company.product_catalog.entries[0].product_id == products[0].product_id
        assert company.product_catalog.entries[0].product_knowledge_available is True
        assert all(item["field_key"] != "client.product_catalog" for item in company.known_fields)
        assert company.product_catalog.omissions[0].count == 2
        next_page = await read_client_product_catalog_page(
            workspace_id=scope.workspace_id,
            client_entity_id=scope.client_entity_id,
            company_client_kb_version=1,
            cursor=company.product_catalog.omissions[0].cursor,
            limit=1,
        )
        assert next_page.entries[0].product_id == products[1].product_id
        assert next_page.omissions[0].count == 1

        profile = await compile_product_profile_card(
            workspace_id=scope.workspace_id,
            brand_id=scope.brand_id,
            product_id=products[0].product_id,
        )
        knowledge = await compile_product_knowledge_card(
            workspace_id=scope.workspace_id,
            client_entity_id=scope.client_entity_id,
            product_id=products[0].product_id,
            product_kb_version=product_version,
        )
        assert profile.product_id == products[0].product_id
        assert knowledge.product_kb_version == product_version
        assert len(knowledge.known_fields) == len(PRODUCT_KNOWLEDGE_FIELDS)
        assert not knowledge.open_gaps
        assert "product_id" not in ProductKnowledgeCard.model_fields

        async with transaction() as conn:
            assert (
                await load_pinned_product_knowledge(
                    conn,
                    workspace_id=scope.workspace_id,
                    client_entity_id=scope.client_entity_id,
                    product_id=products[1].product_id,
                    product_kb_version=product_version,
                )
                is None
            )
        with pytest.raises(ProductContextScopeError):
            await compile_product_knowledge_card(
                workspace_id=scope.workspace_id,
                client_entity_id=scope.client_entity_id,
                product_id=products[1].product_id,
                product_kb_version=product_version,
            )

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_product_card_cap_emits_tool_compatible_exact_cursor(tmp_path: Path) -> None:
    async def scenario() -> None:
        scope, products, product_version = await _seed_product_context(tmp_path)
        card = await compile_product_knowledge_card(
            workspace_id=scope.workspace_id,
            client_entity_id=scope.client_entity_id,
            product_id=products[0].product_id,
            product_kb_version=product_version,
            policy=PRODUCT_KNOWLEDGE_CARD_POLICY_V1.model_copy(
                update={"max_known_fields_bytes": 500}
            ),
        )
        assert card.known_fields
        assert card.omissions
        assert card.omissions[0].count == len(PRODUCT_KNOWLEDGE_FIELDS) - len(card.known_fields)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())
