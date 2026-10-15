"""Renaming, merging, archiving and restoring products (spec 2026-10-15 §3)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import (
    add_product_aliases,
    archive_product,
    confirm_project_product_set,
    create_brand,
    create_product,
    create_project,
    create_workspace,
    get_product,
    merge_products,
    remove_product_aliases,
    rename_product,
    resolve_current_product,
    restore_product,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")

USER_ID = "usr_product_lifecycle"


async def _brand(conn: AsyncConnection) -> tuple[str, str]:
    ws = await create_workspace(conn, name="Proxon")
    brand = await create_brand(conn, workspace_id=ws.workspace_id, name="Proxon")
    return ws.workspace_id, brand.brand_id


async def _products(conn: AsyncConnection, ws: str, brand: str, *names: str) -> list[str]:
    return [
        (await create_product(conn, brand_id=brand, workspace_id=ws, name=n)).product_id
        for n in names
    ]


def test_rename_keeps_the_old_name_as_an_alias_and_refuses_a_clash() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand = await _brand(conn)
            a, _ = await _products(conn, ws, brand, "Proxon Observer", "Proxon Levels")
            await add_product_aliases(conn, product_id=a, workspace_id=ws, aliases=["Proxon AI"])
            renamed = await rename_product(conn, product_id=a, workspace_id=ws, name="Proxon AI")
            assert renamed.name == "Proxon AI"
            # The old name is kept; the alias that now IS the name is dropped.
            assert renamed.aliases == ("Proxon Observer",)
            with pytest.raises(IntegrityError, match="product_name_per_brand"):
                async with conn.begin_nested():
                    await rename_product(conn, product_id=a, workspace_id=ws, name="Proxon Levels")
            with pytest.raises(ValueError, match="not in this workspace"):
                await rename_product(conn, product_id=a, workspace_id="ws_other", name="X")

    run_async(scenario())


def test_merge_points_members_at_the_survivor_and_collapses_chains() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand = await _brand(conn)
            old, a, b, survivor = await _products(conn, ws, brand, "Old", "A", "B", "Proxon")
            await add_product_aliases(conn, product_id=b, workspace_id=ws, aliases=["Bee"])
            await merge_products(conn, product_ids=[old], into_product_id=a, workspace_id=ws)
            refreshed, added = await merge_products(
                conn, product_ids=[a, b], into_product_id=survivor, workspace_id=ws
            )
            assert added == ("A", "Old", "B", "Bee")
            assert refreshed.aliases == ("A", "Old", "B", "Bee")
            for member in (a, b):
                row = await get_product(conn, member)
                assert row is not None
                assert (row.status, row.merged_into) == ("merged", survivor)
            # The product merged into A earlier now points straight at the survivor.
            older = await get_product(conn, old)
            assert older is not None and older.merged_into == survivor
            current = await resolve_current_product(conn, old)
            assert current is not None and current.product_id == survivor

    run_async(scenario())


def test_merge_refuses_inactive_foreign_and_self_members() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand = await _brand(conn)
            a, b, c = await _products(conn, ws, brand, "A", "B", "C")
            other_brand = await create_brand(conn, workspace_id=ws, name="Other")
            (foreign,) = await _products(conn, ws, other_brand.brand_id, "F")
            await archive_product(conn, product_id=c, workspace_id=ws)
            with pytest.raises(ValueError, match="not active"):
                await merge_products(conn, product_ids=[c], into_product_id=a, workspace_id=ws)
            with pytest.raises(ValueError, match="same brand"):
                await merge_products(
                    conn, product_ids=[foreign], into_product_id=a, workspace_id=ws
                )
            with pytest.raises(ValueError, match="into itself"):
                await merge_products(conn, product_ids=[a, b], into_product_id=a, workspace_id=ws)
            with pytest.raises(ValueError, match="at least one"):
                await merge_products(conn, product_ids=[], into_product_id=a, workspace_id=ws)

    run_async(scenario())


def test_archive_and_restore_round_trip_and_restore_clears_merged_into() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand = await _brand(conn)
            a, b, survivor = await _products(conn, ws, brand, "A", "B", "Proxon")
            archived = await archive_product(conn, product_id=a, workspace_id=ws)
            assert archived.status == "archived"
            with pytest.raises(ValueError, match="not active"):
                await archive_product(conn, product_id=a, workspace_id=ws)
            assert (await restore_product(conn, product_id=a, workspace_id=ws)).status == "active"
            await merge_products(conn, product_ids=[b], into_product_id=survivor, workspace_id=ws)
            restored = await restore_product(conn, product_id=b, workspace_id=ws)
            assert (restored.status, restored.merged_into) == ("active", None)
            trimmed = await remove_product_aliases(
                conn, product_id=survivor, workspace_id=ws, aliases=["b"]
            )
            assert trimmed.aliases == ()

    run_async(scenario())


def test_a_new_product_may_take_a_name_only_an_archived_product_held() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand = await _brand(conn)
            (a,) = await _products(conn, ws, brand, "Proxon")
            await archive_product(conn, product_id=a, workspace_id=ws)
            await create_product(conn, brand_id=brand, workspace_id=ws, name="Proxon")
            # Restoring the archived one would give the brand two active "Proxon" rows.
            with pytest.raises(IntegrityError, match="product_name_per_brand"):
                await restore_product(conn, product_id=a, workspace_id=ws)

    run_async(scenario())


def test_a_set_version_can_come_from_a_product_change() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand = await _brand(conn)
            project = await create_project(conn, workspace_id=ws, brand_id=brand, name="AI")
            await conn.execute(
                text(
                    "INSERT INTO platform_user (user_id, display_name) VALUES (:id, 'L') "
                    "ON CONFLICT (user_id) DO NOTHING"
                ),
                {"id": USER_ID},
            )
            (a,) = await _products(conn, ws, brand, "Proxon")
            change_id = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO product_change (change_id, workspace_id, brand_id, kind, "
                    " product_id, actor_user_id) VALUES (:id, :ws, :brand, 'merge', :p, :u)"
                ),
                {"id": change_id, "ws": ws, "brand": brand, "p": a, "u": USER_ID},
            )
            written = await confirm_project_product_set(
                conn,
                workspace_id=ws,
                project_id=project.project_id,
                product_ids=[a],
                gate_id=None,
                confirmed_by_user_id=USER_ID,
                product_change_id=change_id,
            )
            assert written is not None and written.product_change_id == change_id
            with pytest.raises(ValueError, match="exactly one"):
                await confirm_project_product_set(
                    conn,
                    workspace_id=ws,
                    project_id=project.project_id,
                    product_ids=[a],
                    gate_id=uuid4(),
                    confirmed_by_user_id=USER_ID,
                    product_change_id=change_id,
                )

    run_async(scenario())
