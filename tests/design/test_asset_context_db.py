from __future__ import annotations

from clue_db import db_lifespan
from clue_design import descriptions
from tests.design.conftest import run_async
from tests.design.test_asset_context import analysis
from tests.design.test_ingestion_descriptions_dal_db import _seed_asset, _seed_ws


def test_analysis_edit_cache_reset_and_superseded_write(require_design_db):
    async def check():
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            asset = await _seed_asset(conn, ws)
            inputs = {"model": "test/model", "prompt_version": "v1", "source_occurrences": []}
            prepared = await descriptions.prepare_analysis(
                conn, workspace_id=ws, asset_id=asset, analysis_input=inputs
            )
            assert await descriptions.begin_analysis(
                conn,
                workspace_id=ws,
                asset_id=asset,
                input_fingerprint=prepared["input_fingerprint"],
                token="first",
            )
            await descriptions.patch_overrides(
                conn,
                workspace_id=ws,
                asset_id=asset,
                values={"title": "Human title", "creative_type": "logo"},
            )
            assert await descriptions.finish_analysis(
                conn, workspace_id=ws, asset_id=asset, token="first", analysis=analysis()
            )
            row = (await descriptions.get_many(conn, workspace_id=ws, asset_ids=[asset]))[asset]
            assert row["title"] == "Human title" and row["creative_type"] == "logo"
            assert row["description"] == analysis()["description"] and row["status"] == "ready"
            assert (
                await descriptions.get_many(
                    conn, workspace_id=await _seed_ws(conn), asset_ids=[asset]
                )
                == {}
            )
            cached = await descriptions.prepare_analysis(
                conn, workspace_id=ws, asset_id=asset, analysis_input=inputs
            )
            assert cached["status"] == "ready"
            await descriptions.patch_overrides(
                conn, workspace_id=ws, asset_id=asset, values={}, reset_fields=["creative_type"]
            )
            row = (await descriptions.get_many(conn, workspace_id=ws, asset_ids=[asset]))[asset]
            assert row["creative_type"] == "product_screenshot" and row["title"] == "Human title"
            changed = await descriptions.prepare_analysis(
                conn,
                workspace_id=ws,
                asset_id=asset,
                analysis_input={**inputs, "prompt_version": "v2"},
            )
            assert changed["status"] == "queued"
            assert not await descriptions.finish_analysis(
                conn, workspace_id=ws, asset_id=asset, token="first", analysis=analysis("Stale")
            )
            await txn.rollback()

    run_async(check())
