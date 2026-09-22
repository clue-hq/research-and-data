"""Upload recovery is one transaction, tested through the actual synchronous composition."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from lumen_api import asset_enrichment as uploads
from lumen_api.design_store import DesignStoreBridge
from sqlalchemy import text

from clue_db import db_lifespan
from clue_design import runs
from tests.design.conftest import run_async
from tests.design.test_ingestion_descriptions_dal_db import _seed_ws


def test_upload_response_loss_parallel_retry_and_atomic_offer(require_design_db, monkeypatch):
    async def seed():
        async with db_lifespan() as engine, engine.begin() as conn:
            return await _seed_ws(conn)

    ws = run_async(seed())
    bridge = DesignStoreBridge(ws)
    record = {
        "id": f"asset_{uuid4().hex}",
        "kind": "raster_image",
        "status": "ready",
        "media": {
            "mime_type": "image/png",
            "byte_length": 1,
            "digest": {"algorithm": "sha256", "value": "a" * 64},
        },
    }
    request = {
        "idempotency_key": "same-file",
        "request_digest": "same-bytes-and-metadata",
        "overrides": {"creative_type": "logo", "user_note": "Customer mark"},
    }
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda i: uploads.register_upload(
                        ws, {**record, "id": record["id"] + str(i)}, request
                    ),
                    range(2),
                )
            )
        assert results[0]["asset"]["id"] == results[1]["asset"]["id"]

        async def counts(conn):
            return [
                (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE workspace_id = :w"), {"w": ws}
                    )
                ).scalar_one()
                for table in ("design_asset", "design_ingestion_job", "design_asset_upload_request")
            ]

        assert bridge._run(counts) == [1, 1, 1]
        with pytest.raises(uploads.UploadKeyConflict):
            uploads.register_upload(ws, record, {**request, "request_digest": "different-bytes"})

        async def fail_offer(*args, **kwargs):
            raise RuntimeError("fleet write refused")

        monkeypatch.setattr(uploads, "create_and_offer", fail_offer)
        with pytest.raises(RuntimeError, match="fleet write refused"):
            uploads.register_upload(ws, record, {**request, "idempotency_key": "new-file"})
        assert bridge._run(counts) == [1, 1, 1]
    finally:

        async def cleanup(conn):
            await conn.execute(
                text(
                    "DELETE FROM fleet_task WHERE work_id IN"
                    " (SELECT work_id FROM design_ingestion_job WHERE workspace_id = :w)"
                ),
                {"w": ws},
            )
            await conn.execute(text("DELETE FROM design_asset WHERE workspace_id = :w"), {"w": ws})
            await conn.execute(
                text("DELETE FROM design_ingestion_job WHERE workspace_id = :w"), {"w": ws}
            )
            await conn.execute(text("DELETE FROM workspace WHERE workspace_id = :w"), {"w": ws})

        bridge._run(cleanup)


def test_run_context_snapshot_is_frozen_and_workspace_bound(require_design_db):
    async def check():
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            run_id = f"run_{uuid4().hex}"
            await runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=None)
            first = {"asset_a": {"revision": 3, "asset_context": {"description": "Pinned"}}}
            assert (
                await runs.pin_asset_context_snapshot(
                    conn, workspace_id=ws, run_id=run_id, snapshot=first
                )
                == first
            )
            assert (
                await runs.pin_asset_context_snapshot(
                    conn, workspace_id=ws, run_id=run_id, snapshot={"new": {}}
                )
                == first
            )
            assert await runs.asset_context_snapshot(conn, workspace_id=ws, run_id=run_id) == first
            from clue_design.errors import DesignNotFoundError

            with pytest.raises(DesignNotFoundError):
                await runs.asset_context_snapshot(
                    conn, workspace_id=await _seed_ws(conn), run_id=run_id
                )
            await txn.rollback()

    run_async(check())
