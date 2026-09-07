"""Lineup entries → product rows through the artifact-keyed lineage (catalog contract §5)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_lineage import CatalogProduct, synchronize_catalog
from clue_api.arv2.onboarding_store import create_run, mark_run_running, open_document, start_step
from clue_spine import create_product, list_products
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")
USER = "usr_o3_lineage"


async def _catalog_document(conn: AsyncConnection, ws: str) -> tuple[str, UUID]:
    project = await seed_project(conn, ws, name="O3 lineage")
    await seed_principal(conn, workspace_id=ws, user_id=USER)
    run_id, step_id, doc_id = uuid4(), uuid4(), uuid4()
    await create_run(
        conn,
        run_id=run_id,
        workspace_id=ws,
        brand_id=project.brand_id,
        company_domain="insighthealth.ai",
        requested_by_user_id=USER,
    )
    await mark_run_running(conn, run_id=run_id)
    await start_step(
        conn, step_id=step_id, run_id=run_id, workspace_id=ws, kind="lineup", phase="fast"
    )
    await open_document(
        conn,
        document_id=doc_id,
        workspace_id=ws,
        brand_id=project.brand_id,
        folder="product",
        path="product/catalog.md",
        kind="product-catalog",
        step_id=step_id,
    )
    return project.brand_id, doc_id


def test_new_entries_create_products_and_lineage_and_replay_reuses_them() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-new"
            brand_id, doc_id = await _catalog_document(conn, ws)
            entries = [
                CatalogProduct(
                    name="Aura AI Scribe", short_description="Ambient documentation.", aliases=()
                ),
                CatalogProduct(
                    name="MagicFlow", short_description="Workflow orchestration.", aliases=()
                ),
            ]
            links = await synchronize_catalog(
                conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries
            )
            assert [link.resolution_state for link in links] == ["created", "created"]
            assert all(link.product_id and link.product_id.startswith("prd_") for link in links)
            assert {p.name for p in await list_products(conn, brand_id)} == {
                "Aura AI Scribe",
                "MagicFlow",
            }

            again = await synchronize_catalog(
                conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries
            )
            assert [link.resolution_state for link in again] == [
                link.resolution_state for link in links
            ]
            assert [link.product_id for link in again] == [link.product_id for link in links]
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM onboarding_product_lineage WHERE document_id = :d"),
                    {"d": doc_id},
                )
            ).scalar_one()
            assert count == 2

    run_async(scenario())


def test_an_existing_alias_or_name_hit_is_reused_and_ambiguity_is_left_open() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-alias"
            brand_id, doc_id = await _catalog_document(conn, ws)
            existing = await create_product(
                conn,
                brand_id=brand_id,
                workspace_id=ws,
                name="Aura",
                aliases=("Aura AI Scribe",),
            )
            await create_product(
                conn,
                brand_id=brand_id,
                workspace_id=ws,
                name="Phone Triage",
                aliases=("Triage",),
            )
            await create_product(
                conn,
                brand_id=brand_id,
                workspace_id=ws,
                name="Triage Agent",
                aliases=("Triage",),
            )
            links = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=[
                    CatalogProduct(name="Aura AI Scribe", short_description="x", aliases=()),
                    CatalogProduct(name="Triage", short_description="y", aliases=()),
                ],
            )
            assert (links[0].resolution_state, links[0].product_id) == (
                "alias_reused",
                existing.product_id,
            )
            assert (
                links[1].resolution_state,
                links[1].product_id,
                links[1].candidate_count,
            ) == ("unresolved_ambiguous", None, 2)

    run_async(scenario())


def test_a_second_document_creates_its_own_lineage_but_reuses_products_by_name() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-v2"
            brand_id, doc1 = await _catalog_document(conn, ws)
            first = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc1,
                products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
            )
            doc2 = uuid4()
            step2 = uuid4()
            run_id = (
                await conn.execute(
                    text("SELECT run_id FROM onboarding_run WHERE workspace_id = :ws"), {"ws": ws}
                )
            ).scalar_one()
            await start_step(
                conn, step_id=step2, run_id=run_id, workspace_id=ws, kind="reviews", phase="fast"
            )
            await open_document(
                conn,
                document_id=doc2,
                workspace_id=ws,
                brand_id=brand_id,
                folder="product",
                path="product/catalog.md",
                kind="product-catalog",
                step_id=step2,
            )
            second = await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc2,
                products=[CatalogProduct("MagicFlow", "Orchestration, revised.", ())],
            )
            assert second[0].product_id == first[0].product_id
            assert second[0].resolution_state == "alias_reused"

    run_async(scenario())


def test_a_changed_entry_under_the_same_document_is_refused() -> None:
    """A document version is immutable, so an ordinal whose content changed means a *different*
    catalog was re-published under the same document id. The append-only row cannot be corrected,
    so the synchronizer fails loud rather than return a link for the wrong entry."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-changed"
            brand_id, doc_id = await _catalog_document(conn, ws)
            await synchronize_catalog(
                conn,
                workspace_id=ws,
                brand_id=brand_id,
                document_id=doc_id,
                products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
            )
            with pytest.raises(ValueError, match="changed under its lineage"):
                await synchronize_catalog(
                    conn,
                    workspace_id=ws,
                    brand_id=brand_id,
                    document_id=doc_id,
                    products=[CatalogProduct("Aura AI Scribe", "Ambient documentation.", ())],
                )
            rows = (
                await conn.execute(
                    text("SELECT count(*) FROM onboarding_product_lineage WHERE document_id = :d"),
                    {"d": doc_id},
                )
            ).scalar_one()
            assert rows == 1

    run_async(scenario())


def test_a_document_belonging_to_another_brand_is_refused_before_anything_is_written() -> None:
    """The lineage's ``document_id`` FK is single-column, so nothing structurally ties a lineage
    row's ``(workspace_id, brand_id)`` to its document's. The synchronizer checks it itself, and
    refuses *before* a product is minted or a lineage row is written."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-scope"
            brand_id, _ = await _catalog_document(conn, ws)
            other = await seed_project(conn, ws, name="O3 lineage other brand")
            step_id, doc_id = uuid4(), uuid4()
            run_id = (
                await conn.execute(
                    text("SELECT run_id FROM onboarding_run WHERE workspace_id = :ws"), {"ws": ws}
                )
            ).scalar_one()
            await start_step(
                conn,
                step_id=step_id,
                run_id=run_id,
                workspace_id=ws,
                kind="catalog_sync",
                phase="fast",
            )
            await open_document(
                conn,
                document_id=doc_id,
                workspace_id=ws,
                brand_id=other.brand_id,
                folder="product",
                path="product/catalog.md",
                kind="product-catalog",
                step_id=step_id,
            )

            with pytest.raises(ValueError, match="not in this workspace/brand"):
                await synchronize_catalog(
                    conn,
                    workspace_id=ws,
                    brand_id=brand_id,
                    document_id=doc_id,
                    products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
                )

            assert await list_products(conn, brand_id) == []
            assert await list_products(conn, other.brand_id) == []
            lineage = (
                await conn.execute(
                    text("SELECT count(*) FROM onboarding_product_lineage WHERE workspace_id = :w"),
                    {"w": ws},
                )
            ).scalar_one()
            assert lineage == 0

    run_async(scenario())


def test_an_unknown_document_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-lineage-missing"
            brand_id, _ = await _catalog_document(conn, ws)
            with pytest.raises(ValueError, match="not in this workspace/brand"):
                await synchronize_catalog(
                    conn,
                    workspace_id=ws,
                    brand_id=brand_id,
                    document_id=uuid4(),
                    products=[CatalogProduct("MagicFlow", "Orchestration.", ())],
                )

    run_async(scenario())
