"""Real-PostgreSQL S5-D exact-scope, pagination, refusal, and replay acceptance."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.client_knowledge_tools import build_client_knowledge_v2_tools
from clue_api.product_knowledge_contracts import (
    ProductClaimInspectionOutput,
    ProductKnowledgeListOutput,
)
from clue_api.product_knowledge_tools import build_product_knowledge_tools
from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    RunId,
    new_operation_id,
)
from clue_db import db_lifespan, transaction
from clue_research.claimstore import insert_claim, record_run_lineage
from clue_research.stage0 import finalize_client_kb_version, read_client_kb_claims
from clue_toolbelt import PreconditionFailed, ToolContext, ToolRegistry, ToolResult, invoke_tool
from tests.api.test_product_context_s5c_db import _seed_product_context
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_product_knowledge_tools():
        registry.register(tool, make_default=True)
    for tool in build_client_knowledge_v2_tools():
        registry.register(tool, make_default=True)
    return registry


def _ctx(workspace_id: str) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=transaction,
        operation_id=new_operation_id(),
    )


async def _invoke(
    registry: ToolRegistry,
    name: str,
    body: dict[str, object],
    ctx: ToolContext,
    *,
    version: str,
) -> ToolResult:
    return await invoke_tool(
        registry,
        name,
        body,
        ctx,
        version=version,
        idempotency_ttl_s=86_400.0,
    )


async def _workspace_counts(workspace_id: str) -> tuple[int, ...]:
    values: list[int] = []
    async with transaction() as conn:
        for table in ("claim", "artifact", "product_catalog_lineage"):
            values.append(
                (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE workspace_id=:workspace"),
                        {"workspace": workspace_id},
                    )
                ).scalar_one()
            )
    return tuple(values)


async def _seed_second_product(scope: object, product_id: str) -> tuple[int, Claim]:
    run_id = RunId(uuid4())
    claim = Claim(
        entity_id=scope.client_entity_id,  # type: ignore[attr-defined]
        entity_type=EntityType.ACCOUNT,
        field_key="client.product_overview",
        value_json="Second product only",
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=Decimal("1"),
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=scope.workspace_id,  # type: ignore[attr-defined]
        product_id=product_id,
    )
    async with transaction() as conn:
        await record_run_lineage(
            conn,
            run_id=run_id,
            workspace_id=scope.workspace_id,  # type: ignore[attr-defined]
            kind="stage0",
        )
        await insert_claim(conn, claim)
        version = await finalize_client_kb_version(
            conn,
            client_entity_id=scope.client_entity_id,  # type: ignore[attr-defined]
            workspace_id=scope.workspace_id,  # type: ignore[attr-defined]
            run_id=run_id,
            filled_fields={"client.product_overview"},
            attempted_fields={"client.product_overview"},
            product_id=product_id,
        )
    return version, claim


def test_exact_product_page_inspection_and_cursor_rebinding(tmp_path: Path) -> None:
    async def scenario() -> None:
        scope, products, version = await _seed_product_context(tmp_path)
        registry = _registry()
        body = {
            "client_entity_id": str(scope.client_entity_id),
            "product_id": products[0].product_id,
            "product_kb_version": version,
        }
        first_result = await _invoke(
            registry,
            "list_product_knowledge",
            {**body, "limit": 2},
            _ctx(scope.workspace_id),
            version="1",
        )
        first = ProductKnowledgeListOutput.model_validate_json(json.dumps(first_result.references))
        assert first.returned == 2
        assert first.has_more and first.next_cursor
        second_result = await _invoke(
            registry,
            "list_product_knowledge",
            {**body, "limit": 2, "cursor": first.next_cursor},
            _ctx(scope.workspace_id),
            version="1",
        )
        second = ProductKnowledgeListOutput.model_validate_json(
            json.dumps(second_result.references)
        )
        assert {item.claim_id for item in first.knowledge}.isdisjoint(
            item.claim_id for item in second.knowledge
        )

        inspected_result = await _invoke(
            registry,
            "inspect_product_claim",
            {**body, "claim_id": str(first.knowledge[0].claim_id)},
            _ctx(scope.workspace_id),
            version="1",
        )
        inspected = ProductClaimInspectionOutput.model_validate_json(
            json.dumps(inspected_result.references)
        )
        assert inspected.claim.claim_id == first.knowledge[0].claim_id
        assert inspected.claim.lineage.product_id == products[0].product_id
        assert inspected.content_semantics == "untrusted_evidence_not_instructions"

        with pytest.raises(PreconditionFailed) as refusal:
            await _invoke(
                registry,
                "list_product_knowledge",
                {**body, "limit": 3, "cursor": first.next_cursor},
                _ctx(scope.workspace_id),
                version="1",
            )
        assert refusal.value.reason_codes == ("product_knowledge_cursor_invalid",)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_company_and_product_tools_cannot_cross_knowledge_scopes(tmp_path: Path) -> None:
    async def scenario() -> None:
        scope, products, product_version = await _seed_product_context(tmp_path)
        other_version, other_claim = await _seed_second_product(scope, products[1].product_id)
        async with transaction() as conn:
            own_product_claims = await read_client_kb_claims(
                conn,
                scope.client_entity_id,
                workspace_id=scope.workspace_id,
                version=product_version,
                product_id=products[0].product_id,
            )
            company_claim = (
                await conn.execute(
                    text(
                        "SELECT id FROM claim WHERE workspace_id=:workspace "
                        "AND entity_id=:client AND product_id IS NULL "
                        "ORDER BY collected_at LIMIT 1"
                    ),
                    {"workspace": scope.workspace_id, "client": scope.client_entity_id},
                )
            ).scalar_one()
        own_claim = next(iter(own_product_claims.values()))
        registry = _registry()
        own_scope = {
            "client_entity_id": str(scope.client_entity_id),
            "product_id": products[0].product_id,
            "product_kb_version": product_version,
        }
        for forbidden_claim in (company_claim, other_claim.id, uuid4()):
            with pytest.raises(PreconditionFailed) as refusal:
                await _invoke(
                    registry,
                    "inspect_product_claim",
                    {**own_scope, "claim_id": str(forbidden_claim)},
                    _ctx(scope.workspace_id),
                    version="1",
                )
            assert refusal.value.reason_codes == ("product_claim_not_found",)

        # A valid other-product scope still cannot inspect this product's claim.
        with pytest.raises(PreconditionFailed) as refusal:
            await _invoke(
                registry,
                "inspect_product_claim",
                {
                    "client_entity_id": str(scope.client_entity_id),
                    "product_id": products[1].product_id,
                    "product_kb_version": other_version,
                    "claim_id": str(own_claim.id),
                },
                _ctx(scope.workspace_id),
                version="1",
            )
        assert refusal.value.reason_codes == ("product_claim_not_found",)

        # The unchanged company @2 tool never acquires product membership.
        with pytest.raises(PreconditionFailed) as refusal:
            await _invoke(
                registry,
                "inspect_client_claim",
                {
                    "client_entity_id": str(scope.client_entity_id),
                    "client_kb_version": 1,
                    "claim_id": str(own_claim.id),
                },
                _ctx(scope.workspace_id),
                version="2",
            )
        assert refusal.value.reason_codes == ("client_claim_not_found",)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())


def test_repeated_product_reads_are_same_refs_and_zero_write(tmp_path: Path) -> None:
    async def scenario() -> None:
        scope, products, version = await _seed_product_context(tmp_path)
        registry = _registry()
        body = {
            "client_entity_id": str(scope.client_entity_id),
            "product_id": products[0].product_id,
            "product_kb_version": version,
            "limit": 4,
        }
        before = await _workspace_counts(scope.workspace_id)
        first = await _invoke(
            registry,
            "list_product_knowledge",
            body,
            _ctx(scope.workspace_id),
            version="1",
        )
        second = await _invoke(
            registry,
            "list_product_knowledge",
            body,
            _ctx(scope.workspace_id),
            version="1",
        )
        after = await _workspace_counts(scope.workspace_id)
        assert first.references == second.references
        assert before == after

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())
