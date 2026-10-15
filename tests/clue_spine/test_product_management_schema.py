"""The schema behind product management (spec 2026-10-15 §3): merged products, the change log and
where a project's product-set version came from. The constraints are the enforcement, so they are
asserted as raw ``IntegrityError`` from the database."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import create_brand, create_product, create_project, create_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")

USER_ID = "usr_product_management_schema"


async def _seed(conn: AsyncConnection) -> tuple[str, str, str]:
    ws = await create_workspace(conn, name="Proxon")
    brand = await create_brand(conn, workspace_id=ws.workspace_id, name="Proxon")
    project = await create_project(
        conn, workspace_id=ws.workspace_id, brand_id=brand.brand_id, name="AI workforce"
    )
    await conn.execute(
        text(
            "INSERT INTO platform_user (user_id, display_name) VALUES (:id, 'Schema') "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"id": USER_ID},
    )
    return ws.workspace_id, brand.brand_id, project.project_id


def test_merged_needs_a_target_and_a_name_is_unique_only_among_active_products() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, _ = await _seed(conn)
            a = await create_product(conn, brand_id=brand, workspace_id=ws, name="A")
            b = await create_product(conn, brand_id=brand, workspace_id=ws, name="B")
            with pytest.raises(IntegrityError, match="product_merged_into_state"):
                async with conn.begin_nested():
                    await conn.execute(
                        text("UPDATE product SET status = 'merged' WHERE product_id = :p"),
                        {"p": a.product_id},
                    )
            with pytest.raises(IntegrityError, match="product_merged_into_not_self"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE product SET status = 'merged', merged_into = product_id "
                            "WHERE product_id = :p"
                        ),
                        {"p": a.product_id},
                    )
            await conn.execute(
                text(
                    "UPDATE product SET status = 'merged', merged_into = :b WHERE product_id = :a"
                ),
                {"a": a.product_id, "b": b.product_id},
            )
            # The merged row no longer holds its name, so a new active "A" is allowed ...
            await create_product(conn, brand_id=brand, workspace_id=ws, name="A")
            # ... while two active products still cannot share one.
            with pytest.raises(IntegrityError, match="product_name_per_brand"):
                await create_product(conn, brand_id=brand, workspace_id=ws, name="B")

    run_async(scenario())


async def _change(conn: AsyncConnection, ws: str, brand: str, product_id: str) -> str:
    change_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO product_change (change_id, workspace_id, brand_id, kind, product_id, "
            " actor_user_id) VALUES (:id, :ws, :brand, 'merge', :product, :user)"
        ),
        {"id": change_id, "ws": ws, "brand": brand, "product": product_id, "user": USER_ID},
    )
    return str(change_id)


def test_the_change_log_is_append_only_and_a_set_version_has_exactly_one_source() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, project = await _seed(conn)
            product = await create_product(conn, brand_id=brand, workspace_id=ws, name="Proxon")
            change_id = await _change(conn, ws, brand, product.product_id)
            with pytest.raises(Exception, match="append"):
                async with conn.begin_nested():
                    await conn.execute(
                        text("UPDATE product_change SET kind = 'add' WHERE change_id = :id"),
                        {"id": change_id},
                    )
            insert = text(
                "INSERT INTO project_product (workspace_id, project_id, brand_id, product_id, "
                " selection_version, gate_id, confirmed_by_user_id, confirmation_turn_id, "
                " product_change_id) VALUES (:ws, :project, :brand, :product, :version, NULL, "
                " :user, NULL, :change)"
            )
            params = {
                "ws": ws,
                "project": project,
                "brand": brand,
                "product": product.product_id,
                "user": USER_ID,
            }
            with pytest.raises(IntegrityError, match="project_product_confirmation_source"):
                async with conn.begin_nested():
                    await conn.execute(insert, {**params, "version": 1, "change": None})
            await conn.execute(insert, {**params, "version": 1, "change": change_id})

    run_async(scenario())


def test_a_project_outcome_carries_a_version_exactly_when_it_wrote_one() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, project = await _seed(conn)
            product = await create_product(conn, brand_id=brand, workspace_id=ws, name="Proxon")
            change_id = await _change(conn, ws, brand, product.product_id)
            with pytest.raises(IntegrityError, match="product_change_project_version"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO product_change_project (change_id, project_id, "
                            " workspace_id, outcome) VALUES (:c, :p, :ws, 'updated')"
                        ),
                        {"c": change_id, "p": project, "ws": ws},
                    )
            await conn.execute(
                text(
                    "INSERT INTO product_change_project (change_id, project_id, workspace_id, "
                    " outcome) VALUES (:c, :p, :ws, 'needs_choice')"
                ),
                {"c": change_id, "p": project, "ws": ws},
            )

    run_async(scenario())
