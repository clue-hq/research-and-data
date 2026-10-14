"""The Brand-context product routes and the document product link (spec 2026-10-15 §10)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from clue_api.frontend_read import brand_products
from tests.api.test_frontend_read_brand_knowledge import _BASE, _app, _document
from tests.api.test_product_management_db import _Brand
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


class _Offers:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, queue: Any, **kwargs: Any) -> bool:
        # The route hands every change to the offer; only a pending page is a real offer.
        del queue
        if kwargs["result"].page_pending:
            self.calls.append(kwargs)
        return True


@pytest.fixture
def offers(monkeypatch: pytest.MonkeyPatch) -> _Offers:
    recorder = _Offers()
    monkeypatch.setattr(brand_products, "offer_product_page", recorder)
    return recorder


async def _call(
    brand: _Brand, method: str, path: str, json: dict[str, Any] | None = None
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(brand.conn, brand.storage)), base_url="http://products"
    ) as client:
        return await client.request(
            method, f"{_BASE}{path}", headers={"X-Workspace-Id": brand.ws}, json=json
        )


def test_the_product_folder_actions_end_to_end(offers: _Offers) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-bp-routes").seed(
                ["Proxon Observer", "Proxon Levels", "Proxon"]
            )
            listed = (await _call(brand, "GET", "/products")).json()
            assert [p["name"] for p in listed["products"]] == [
                "Proxon",
                "Proxon Levels",
                "Proxon Observer",
            ]
            assert listed["recentChanges"] == []

            merged = await _call(
                brand,
                "POST",
                "/products/merge",
                {
                    "productIds": [
                        brand.products["Proxon Observer"],
                        brand.products["Proxon Levels"],
                    ],
                    "intoProductId": brand.products["Proxon"],
                },
            )
            assert merged.status_code == 200, merged.text
            body = merged.json()
            assert body["text"] == "2 products merged into Proxon"
            assert body["pagePending"] is True
            assert body["projectsUpdated"] == 0
            # An app merge offers the background page writer, once, after the commit.
            assert len(offers.calls) == 1
            assert offers.calls[0]["result"].page_pending

            renamed = await _call(
                brand, "POST", f"/products/{brand.products['Proxon']}/rename", {"name": "Proxon AI"}
            )
            assert renamed.status_code == 200 and renamed.json()["productName"] == "Proxon AI"

            taken = await _call(brand, "POST", "/products", {"name": "proxon ai"})
            assert taken.status_code == 409
            assert taken.json()["error"]["code"] == "PRODUCT_NAME_TAKEN"

            added = await _call(brand, "POST", "/products", {"name": "Proxon Agents"})
            assert added.status_code == 200 and added.json()["pagePending"] is True
            assert len(offers.calls) == 2

            removed = await _call(brand, "POST", f"/products/{added.json()['productId']}/remove")
            assert removed.status_code == 200
            again = await _call(brand, "POST", f"/products/{added.json()['productId']}/remove")
            assert again.status_code == 409

            listed = (await _call(brand, "GET", "/products")).json()
            assert [p["name"] for p in listed["products"]] == ["Proxon AI"]
            kinds = [c["kind"] for c in listed["recentChanges"]]
            assert kinds == ["remove", "add", "rename", "merge"]
            merge_line = listed["recentChanges"][-1]
            assert merge_line["undoable"] is True

            undone = await _call(brand, "POST", f"/product-changes/{merge_line['changeId']}/undo")
            assert undone.status_code == 200, undone.text
            listed = (await _call(brand, "GET", "/products")).json()
            assert {p["name"] for p in listed["products"]} == {
                "Proxon AI",
                "Proxon Levels",
                "Proxon Observer",
            }
            bad = await _call(brand, "POST", "/products/merge", {"productIds": ["x"]})
            assert bad.status_code == 422

    run_async(scenario())


def test_a_document_names_its_products_through_the_picker_and_the_catalog_is_read_only(
    offers: _Offers,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-bp-link").seed(["Proxon", "Proxon Levels"])
            # A merge regenerates the catalog, which is then marked generated.
            await _call(
                brand,
                "POST",
                "/products/merge",
                {
                    "productIds": [brand.products["Proxon Levels"]],
                    "intoProductId": brand.products["Proxon"],
                },
            )
            tree = (await _call(brand, "GET", "/knowledge")).json()
            product_docs = {d["path"]: d for d in tree["folders"][1]["documents"]}
            catalog = product_docs["product/catalog.md"]
            assert catalog["generated"] is True
            refused = await _call(
                brand,
                "PUT",
                f"/knowledge/documents/{catalog['id']}",
                {"body": "# hand edit", "expectedRevision": catalog["version"]},
            )
            assert refused.status_code == 409
            assert refused.json()["error"]["code"] == "CATALOG_IS_GENERATED"

            page = product_docs["product/proxon.md"]
            assert page["productIds"] == [brand.products["Proxon"]]
            # While the merged product's fresh page is being written, its old version is not
            # editable — the pending row is the newest version of that path.
            busy = await _call(
                brand,
                "PUT",
                f"/knowledge/documents/{page['id']}",
                {"body": "# edit", "expectedRevision": page["version"]},
            )
            assert busy.status_code == 409

            await _document(
                conn,
                brand.artifacts,
                ws=brand.ws,
                brand_id=brand.brand,
                folder="audience",
                path="audience/notes.md",
                kind="note",
                version=1,
                status="ready",
                body="---\nkind: note\n---\n\n# Notes\n\nWho buys.\n",
            )
            tree = (await _call(brand, "GET", "/knowledge")).json()
            note = tree["folders"][2]["documents"][0]
            assert note["productIds"] == []
            body = "# Notes\n\nWho buys.\n"
            foreign = await _call(
                brand,
                "PUT",
                f"/knowledge/documents/{note['id']}",
                {
                    "body": body,
                    "expectedRevision": 1,
                    "productIds": [brand.products["Proxon Levels"]],
                },
            )
            assert foreign.status_code == 422  # merged away: not on the list any more
            linked = await _call(
                brand,
                "PUT",
                f"/knowledge/documents/{note['id']}",
                {"body": body, "expectedRevision": 1, "productIds": [brand.products["Proxon"]]},
            )
            assert linked.status_code == 200, linked.text
            # Only the link changed, and that alone is a new version.
            assert linked.json()["version"] == 2
            assert linked.json()["productIds"] == [brand.products["Proxon"]]
            assert linked.json()["frontMatter"]["product_ids"] == [brand.products["Proxon"]]
            again = await _call(
                brand,
                "PUT",
                f"/knowledge/documents/{linked.json()['id']}",
                {
                    "body": linked.json()["markdown"],
                    "expectedRevision": 2,
                    "productIds": [brand.products["Proxon"], brand.products["Proxon"]],
                },
            )
            assert again.status_code == 200 and again.json()["version"] == 2  # nothing changed

    run_async(scenario())
