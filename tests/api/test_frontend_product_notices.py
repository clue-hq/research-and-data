"""The project chat's product-change notices (spec 2026-10-15 §7)."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.product_management import (
    ProductActor,
    merge_products_action,
    remove_product_action,
)
from tests.api.test_frontend_read_brand_knowledge import _app
from tests.api.test_product_management_db import USER, _Brand
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _call(brand: _Brand, method: str, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(brand.conn, brand.storage)), base_url="http://notices"
    ) as client:
        return await client.request(
            method, f"{FRONTEND_READ_PREFIX}{path}", headers={"X-Workspace-Id": brand.ws}
        )


def test_a_moved_project_shows_a_notice_until_it_is_dismissed() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            brand = await _Brand(conn, "ws-notices").seed(["A", "B", "Proxon"])
            moved = await brand.project(["A", "Proxon"])
            only_b = await brand.project(["B"])
            untouched = brand.projects[0]
            await merge_products_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ProductActor(USER),
                product_ids=[brand.products["A"]],
                into_product_id=brand.products["Proxon"],
                page_markdown="Proxon.",
            )
            await remove_product_action(
                conn,
                brand.storage,
                workspace_id=brand.ws,
                brand_id=brand.brand,
                actor=ProductActor(USER),
                product_id=brand.products["B"],
            )
            notices = (await _call(brand, "GET", f"/projects/{moved}/product-notices")).json()
            (notice,) = notices["notices"]
            assert notice["outcome"] == "updated"
            assert notice["text"].startswith("Products changed on ")
            assert notice["text"].endswith(": A merged into Proxon.")
            choose = (await _call(brand, "GET", f"/projects/{only_b}/product-notices")).json()
            assert choose["notices"][0]["outcome"] == "needs_choice"
            assert "Choose its products in chat." in choose["notices"][0]["text"]
            assert (await _call(brand, "GET", f"/projects/{untouched}/product-notices")).json() == {
                "notices": []
            }

            dismissed = await _call(
                brand,
                "POST",
                f"/projects/{moved}/product-notices/{notice['changeId']}/dismiss",
            )
            assert dismissed.status_code == 204
            assert (await _call(brand, "GET", f"/projects/{moved}/product-notices")).json() == {
                "notices": []
            }
            again = await _call(
                brand,
                "POST",
                f"/projects/{moved}/product-notices/{notice['changeId']}/dismiss",
            )
            assert again.status_code == 204
            unknown = await _call(
                brand,
                "POST",
                f"/projects/{untouched}/product-notices/{notice['changeId']}/dismiss",
            )
            assert unknown.status_code == 404

    run_async(scenario())
