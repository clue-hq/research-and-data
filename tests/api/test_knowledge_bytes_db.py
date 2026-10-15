"""Brand-context documents are fetched together and cached by content, never served unchecked.

The Stripe workspace's Brand context took 8.7 s to list 37 documents because each one was fetched
from object storage in turn (2026-10-15). These tests pin the fix: one page's documents are
fetched concurrently, a second read of the same bytes does not touch storage, and the database
check (the row is live in this workspace, the bytes match their digest) runs on every read, cache
hit or not.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from clue_api.frontend_read.brand_knowledge import read_knowledge_tree
from clue_api.knowledge_bytes import clear_knowledge_byte_cache
from clue_api.product_management import list_brand_products
from tests.api.test_product_management_db import _Brand
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _SlowStorage:
    """The test storage, with a delay per fetch and a record of how many fetches overlap."""

    def __init__(self, inner, delay: float = 0.05) -> None:  # noqa: ANN001
        self.inner = inner
        self.delay = delay
        self.gets = 0
        self.in_flight = 0
        self.peak = 0

    async def get(self, key: str) -> bytes:
        self.gets += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return await self.inner.get(key)
        finally:
            self.in_flight -= 1

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(self.inner, name)


NAMES = [f"Product {n}" for n in range(12)]


def test_a_pages_documents_are_fetched_together_and_a_reload_skips_storage() -> None:
    async def scenario() -> None:
        clear_knowledge_byte_cache()
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-kb-parallel").seed(NAMES)
            slow = _SlowStorage(brand.storage)
            tree = await read_knowledge_tree(
                conn, workspace_id=brand.ws, brand_id=brand.brand, storage=slow
            )
            listed = sum(len(folder.documents) for folder in tree.folders)
            assert listed == len(NAMES) + 1  # every page and the catalog
            assert slow.gets == listed
            assert slow.peak > 1  # fetched together, not one after another
            titles = {d.title for f in tree.folders for d in f.documents}
            assert "Product 3" in titles

            slow.gets = 0
            again = await read_knowledge_tree(
                conn, workspace_id=brand.ws, brand_id=brand.brand, storage=slow
            )
            assert again == tree
            assert slow.gets == 0  # the same bytes, served from the cache
            products = await list_brand_products(
                conn, slow, workspace_id=brand.ws, brand_id=brand.brand
            )
            assert len(products) == len(NAMES)
            assert slow.gets == 0

    run_async(scenario())


def test_an_erased_document_is_never_served_from_the_cache() -> None:
    async def scenario() -> None:
        clear_knowledge_byte_cache()
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-kb-erased").seed(["Proxon"])
            tree = await read_knowledge_tree(
                conn, workspace_id=brand.ws, brand_id=brand.brand, storage=brand.storage
            )
            page = next(
                d for f in tree.folders for d in f.documents if d.path == "product/proxon.md"
            )
            assert page.title == "Proxon"
            await conn.execute(
                text(
                    "UPDATE artifact SET erased_at = now() WHERE storage_key = (SELECT "
                    "artifact_key FROM brand_knowledge_document WHERE document_id = :id)"
                ),
                {"id": page.id},
            )
            after = await read_knowledge_tree(
                conn, workspace_id=brand.ws, brand_id=brand.brand, storage=brand.storage
            )
            gone = next(
                d for f in after.folders for d in f.documents if d.path == "product/proxon.md"
            )
            # Listed by its file name, its bytes refused — exactly what an unreadable blob does.
            assert gone.title == "proxon"
            assert gone.product_id is None

    run_async(scenario())
