"""``manage_products@1``: the Head of ABM changes the product list for the person."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from clue_api.product_management_tools import (
    ManageProductsInput,
    ManageProductsTool,
    ProductsRefused,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_spine import archive_product, create_product, get_product
from tests.api.test_icp_artifact_gate_db import _ctx, _seed_icp
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires isolated migrated Postgres")


def _input(f: Any, **kwargs: Any) -> ManageProductsInput:
    return ManageProductsInput(source_turn_ref=derive_turn_action_ref(f.seeded.turn_id), **kwargs)


async def _codes(tool: ManageProductsTool, f: Any, **kwargs: Any) -> list[str]:
    return [
        failure.reason_code for failure in await tool.preconditions(_input(f, **kwargs), _ctx(f))
    ]


def test_the_agent_merges_features_into_one_product_and_writes_its_page(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            f = await _seed_icp(
                conn, tmp_path, workspace_id="ws-tool-merge", label="toolmerge", with_document=False
            )
            ws = f.seeded.workspace_id
            feature = await create_product(
                conn, brand_id=f.brand_id, workspace_id=ws, name="Aura Notes"
            )
            tool = ManageProductsTool(conn_factory=f.conn_factory, storage=f.storage)
            call = {
                "action": "merge",
                "product_ids": (feature.product_id,),
                "into_product_id": f.product.product_id,
                "page_markdown": "## Overview\n\nOne scribe; Notes is a part of it.",
            }
            assert await _codes(tool, f, **call) == []
            first = await tool.invoke(_input(f, **call), _ctx(f))
            refs = first.references
            assert refs["summary"] == "Aura Notes merged into Aura AI Scribe"
            assert refs["aliases"] == ("Aura Notes",)
            assert refs["page_document_id"] is not None
            merged = await get_product(conn, feature.product_id)
            assert merged is not None and merged.merged_into == f.product.product_id
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT actor_user_id, actor_turn_id FROM product_change "
                            "WHERE change_id = :id"
                        ),
                        {"id": refs["change_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert str(row["actor_turn_id"]) == str(f.seeded.turn_id)
            assert row["actor_user_id"]
            status = await conn.scalar(
                text("SELECT status FROM brand_knowledge_document WHERE document_id = :id"),
                {"id": refs["page_document_id"]},
            )
            assert status == "ready"  # written in the turn: nothing is left pending
            # The same call in the same turn is the same change.
            replay = await tool.invoke(_input(f, **call), _ctx(f))
            assert replay.references["change_id"] == refs["change_id"]

    run_async(scenario())


def test_preconditions_name_what_is_missing_before_anything_is_written(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            f = await _seed_icp(
                conn, tmp_path, workspace_id="ws-tool-pre", label="toolpre", with_document=False
            )
            ws = f.seeded.workspace_id
            tool = ManageProductsTool(conn_factory=f.conn_factory, storage=f.storage)
            gone = await create_product(conn, brand_id=f.brand_id, workspace_id=ws, name="Gone")
            await archive_product(conn, product_id=gone.product_id, workspace_id=ws)
            assert await _codes(tool, f, action="rename", name="X") == ["products_input_invalid"]
            assert await _codes(tool, f, action="add", name="Aura Agents") == [
                "products_page_required"
            ]
            assert await _codes(
                tool, f, action="merge", product_ids=(gone.product_id,), name="X", page_markdown="p"
            ) == ["product_not_active"]
            assert await _codes(tool, f, action="remove", product_id="prd_missing") == [
                "product_not_found"
            ]
            bad_turn = ManageProductsInput(
                action="remove", product_id=f.product.product_id, source_turn_ref="turn-action:x"
            )
            assert [p.reason_code for p in await tool.preconditions(bad_turn, _ctx(f))] == [
                "products_turn_unavailable"
            ]
            other = await create_product(conn, brand_id=f.brand_id, workspace_id=ws, name="Other")
            with pytest.raises(ProductsRefused) as taken:
                await tool.invoke(
                    _input(f, action="rename", product_id=other.product_id, name="aura ai scribe"),
                    _ctx(f),
                )
            assert taken.value.code == "product_name_taken"
            no_storage = ManageProductsTool(conn_factory=f.conn_factory, storage=None)
            assert [
                p.reason_code
                for p in await no_storage.preconditions(
                    _input(f, action="remove", product_id=f.product.product_id), _ctx(f)
                )
            ] == ["products_storage_unavailable"]

    run_async(scenario())
