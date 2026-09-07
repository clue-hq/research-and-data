"""The versioned project product set (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.2; rulings P1/P2)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import (
    confirm_project_product_set,
    create_brand,
    create_product,
    create_project,
    create_workspace,
    current_project_product_set,
    list_project_product_sets,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")

USER_ID = "usr_o1_product_set"


async def _seed(conn: AsyncConnection) -> tuple[str, str, str, list[str]]:
    ws = await create_workspace(conn, name="Insight")
    brand = await create_brand(conn, workspace_id=ws.workspace_id, name="Insight Health")
    project = await create_project(
        conn, workspace_id=ws.workspace_id, brand_id=brand.brand_id, name="Q4 GI outreach"
    )
    await conn.execute(
        text(
            "INSERT INTO platform_user (user_id, display_name) VALUES (:id, :name) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"id": USER_ID, "name": "O1 product set"},
    )
    products = [
        await create_product(conn, brand_id=brand.brand_id, workspace_id=ws.workspace_id, name=n)
        for n in ("Aura AI Scribe", "Phone Triage AI Agent", "MagicFlow")
    ]
    return ws.workspace_id, brand.brand_id, project.project_id, [p.product_id for p in products]


def test_confirming_a_set_mints_version_one_and_the_current_set_reads_it_back() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id, project_id, ids = await _seed(conn)
            gate_id = uuid4()
            confirmed = await confirm_project_product_set(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_ids=[ids[0], ids[1], ids[0]],  # a repeat collapses, order kept
                gate_id=gate_id,
                confirmed_by_user_id=USER_ID,
            )
            assert confirmed is not None
            assert confirmed.selection_version == 1
            assert confirmed.product_ids == (ids[0], ids[1])
            assert confirmed.brand_id == brand_id
            assert confirmed.gate_id == gate_id
            assert (
                await current_project_product_set(
                    conn, workspace_id=workspace_id, project_id=project_id
                )
                == confirmed
            )

    run_async(scenario())


def test_a_second_confirmation_is_a_new_version_and_the_old_one_survives() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, ids = await _seed(conn)
            first = await confirm_project_product_set(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_ids=[ids[0]],
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            second = await confirm_project_product_set(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_ids=[ids[2], ids[1]],
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            assert first is not None and second is not None
            assert (first.selection_version, second.selection_version) == (1, 2)
            history = await list_project_product_sets(
                conn, workspace_id=workspace_id, project_id=project_id
            )
            assert [s.selection_version for s in history] == [1, 2]
            assert history[0].product_ids == (ids[0],)
            assert history[1].product_ids == (ids[2], ids[1])
            current = await current_project_product_set(
                conn, workspace_id=workspace_id, project_id=project_id
            )
            assert current == second

    run_async(scenario())


def test_no_set_yet_reads_as_none_and_an_empty_set_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, _ = await _seed(conn)
            assert (
                await current_project_product_set(
                    conn, workspace_id=workspace_id, project_id=project_id
                )
                is None
            )
            with pytest.raises(ValueError):
                await confirm_project_product_set(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    product_ids=[],
                    gate_id=uuid4(),
                    confirmed_by_user_id=USER_ID,
                )

    run_async(scenario())


def test_a_product_of_another_brand_or_workspace_returns_none_without_a_partial_write() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, ids = await _seed(conn)
            other_ws = await create_workspace(conn, name="Other")
            other_brand = await create_brand(conn, workspace_id=other_ws.workspace_id, name="Other")
            foreign = await create_product(
                conn,
                brand_id=other_brand.brand_id,
                workspace_id=other_ws.workspace_id,
                name="Foreign",
            )
            result = await confirm_project_product_set(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_ids=[ids[0], foreign.product_id],
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            assert result is None
            assert (
                await list_project_product_sets(
                    conn, workspace_id=workspace_id, project_id=project_id
                )
                == []
            )
            # An absent project is the same honest None.
            assert (
                await confirm_project_product_set(
                    conn,
                    workspace_id=workspace_id,
                    project_id="prj_missing",
                    product_ids=[ids[0]],
                    gate_id=uuid4(),
                    confirmed_by_user_id=USER_ID,
                )
                is None
            )

    run_async(scenario())


def test_rows_are_append_only() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, _, project_id, ids = await _seed(conn)
            await confirm_project_product_set(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                product_ids=[ids[0]],
                gate_id=uuid4(),
                confirmed_by_user_id=USER_ID,
            )
            for statement in (
                "UPDATE project_product SET selection_version = 9 WHERE project_id = :p",
                "DELETE FROM project_product WHERE project_id = :p",
            ):
                with pytest.raises(DBAPIError):
                    async with conn.begin_nested():
                        await conn.execute(text(statement), {"p": project_id})

    run_async(scenario())


def test_the_composite_fks_rely_on_the_spines_existing_anchors() -> None:
    """No `*_identity_triple` index is minted: PostgreSQL matches an FK's referenced columns as a
    set, so `product_context_anchor` / `project_run_context_anchor` already back both composite FKs
    (fix round 1 — the redundant unique indexes were dropped)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _seed(conn)
            constraints = (
                (
                    await conn.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conname IN "
                            "('project_product_product_fk', 'project_product_project_fk')"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(constraints) == [
                "project_product_product_fk",
                "project_product_project_fk",
            ]
            leftovers = (
                (
                    await conn.execute(
                        text(
                            "SELECT indexname FROM pg_indexes WHERE indexname IN "
                            "('product_identity_triple', 'project_identity_triple')"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert list(leftovers) == []

    run_async(scenario())
