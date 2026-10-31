"""D2.3 acceptance tests: the ingestion-job + asset-description DAL port (PD contract §7).

Covers the ported semantics that matter most:

* ingestion jobs: the full lifecycle (create → running → stage → complete) against a REAL
  brand-kit pointer (the composite result FK the SQLite table only back-linked by convention),
  the failure path, and ``list_recent`` ordering/limit.
* fail-closed tenancy: ``require_job`` refuses a foreign-workspace job with the same
  :class:`DesignNotFoundError` an absent id gets, and ``get_job`` returns ``None`` for it.
* descriptions: the HUMAN-WINS conditional upsert asserted at row level (ai → human → ai leaves
  the human row untouched, ``model`` still NULL), and ``get_many`` returning only the caller's
  workspace rows.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import assets as design_assets
from clue_design import brand as design_brand
from clue_design import descriptions as design_descriptions
from clue_design import ingestion as design_ingestion
from clue_design.errors import DesignNotFoundError
from tests.design.conftest import run_async


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_ingest_{uuid4().hex[:12]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _seed_kit(conn: AsyncConnection, ws: str, version: int = 1) -> tuple[str, int]:
    kit_id = f"kit_{uuid4().hex[:10]}"
    await design_brand.create_brand_kit(
        conn,
        workspace_id=ws,
        brand_kit={
            "id": kit_id,
            "version": version,
            "name": "Ingested kit",
            "approval_status": "draft",
        },
        brand_summary={"product_ready": False},
        diagnostics=[],
        source="website",
    )
    return kit_id, version


async def _seed_asset(conn: AsyncConnection, ws: str) -> str:
    asset_id = f"asset_ing_{uuid4().hex[:16]}"
    digest = uuid4().hex + uuid4().hex
    await design_assets.create_asset_record(
        conn,
        workspace_id=ws,
        record={
            "id": asset_id,
            "label": "Logo",
            "kind": "image",
            "status": "ready",
            "tags": [],
            "media": {
                "mime_type": "image/png",
                "byte_length": 64,
                "filename": f"{asset_id}.png",
                "digest": {"algorithm": "sha256", "value": digest},
                "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest}"},
            },
        },
    )
    return asset_id


async def _description_row(conn: AsyncConnection, ws: str, asset_id: str) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT * FROM design_asset_description WHERE asset_id = :a AND workspace_id = :w"
            ),
            {"a": asset_id, "w": ws},
        )
    ).first()


def test_ingestion_job_lifecycle_create_running_stage_complete(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            kit_id, version = await _seed_kit(conn, ws)
            job = await design_ingestion.create_job(
                conn,
                workspace_id=ws,
                kind="website",
                request={"url": "https://insighthealth.example"},
            )
            assert job["job_id"].startswith("ingest_")
            assert job["status"] == "queued"
            assert job["stage"] is None
            assert job["progress"] == 0
            assert job["request"] == {"url": "https://insighthealth.example"}
            assert job["evidence"] is None and job["error"] is None
            assert isinstance(job["created_at"], str)  # ISO parity with the SQLite API
            job_id = job["job_id"]

            updated = await design_ingestion.update_request(
                conn,
                workspace_id=ws,
                job_id=job_id,
                request={"url": "https://insighthealth.example", "tmp_path": "/tmp/x.pdf"},
            )
            assert updated["request"]["tmp_path"] == "/tmp/x.pdf"
            assert updated["status"] == "queued"  # terminal columns untouched

            running = await design_ingestion.set_running(conn, workspace_id=ws, job_id=job_id)
            assert running["status"] == "running"

            staged = await design_ingestion.set_stage(
                conn, workspace_id=ws, job_id=job_id, stage="Visiting your website…", progress=0.4
            )
            assert staged["stage"] == "Visiting your website…"
            assert staged["progress"] == pytest.approx(0.4)

            done = await design_ingestion.complete(
                conn,
                workspace_id=ws,
                job_id=job_id,
                brand_kit_id=kit_id,
                version=version,
                evidence_json='{"schema_version": 1}',
            )
            assert done["status"] == "succeeded"
            assert done["progress"] == 1
            assert done["brand_kit_id"] == kit_id
            assert done["brand_kit_version"] == version
            assert done["evidence"] == {"schema_version": 1}
            assert done["error"] is None
            await txn.rollback()

    run_async(_check())


def test_ingestion_job_fail_path_records_the_error(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            job = await design_ingestion.create_job(
                conn, workspace_id=ws, kind="pdf", request={"filename": "brand.pdf"}
            )
            failed = await design_ingestion.fail(
                conn,
                workspace_id=ws,
                job_id=job["job_id"],
                error={"code": "LUMI0401", "message": "RuntimeError: capture exploded"},
            )
            assert failed["status"] == "failed"
            assert failed["error"]["code"] == "LUMI0401"
            assert "capture exploded" in failed["error"]["message"]
            assert failed["brand_kit_id"] is None
            await txn.rollback()

    run_async(_check())


def test_list_recent_orders_newest_first_and_honours_the_limit(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            other_ws = await _seed_ws(conn)
            ids = [
                (
                    await design_ingestion.create_job(
                        conn, workspace_id=ws, kind="asset_upload", request={"n": n}
                    )
                )["job_id"]
                for n in range(3)
            ]
            await design_ingestion.create_job(
                conn, workspace_id=other_ws, kind="website", request={"url": "https://y.example"}
            )
            listed = await design_ingestion.list_recent(conn, workspace_id=ws)
            # All three rows share the transaction's now(), so the ported job_id DESC tiebreak
            # decides the order — and the other workspace's job never appears.
            assert [row["job_id"] for row in listed] == sorted(ids, reverse=True)
            capped = await design_ingestion.list_recent(conn, workspace_id=ws, limit=2)
            assert [row["job_id"] for row in capped] == sorted(ids, reverse=True)[:2]
            await txn.rollback()

    run_async(_check())


def test_list_recent_can_be_narrowed_to_named_kinds(require_design_db: None) -> None:
    """An ad harvest is an ingestion job but builds no kit, so the kit-side readers ask by kind."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            website = await design_ingestion.create_job(
                conn, workspace_id=ws, kind="website", request={"url": "https://x.example"}
            )
            ad = await design_ingestion.create_job(
                conn, workspace_id=ws, kind="ad_assets", request={"phase": "harvest"}
            )
            kit_side = await design_ingestion.list_recent(
                conn, workspace_id=ws, kinds=("website", "pdf", "asset_upload")
            )
            assert [row["job_id"] for row in kit_side] == [website["job_id"]]
            ads = await design_ingestion.list_recent(conn, workspace_id=ws, kinds=("ad_assets",))
            assert [row["job_id"] for row in ads] == [ad["job_id"]]
            # No filter is every kind, exactly as before.
            everything = await design_ingestion.list_recent(conn, workspace_id=ws)
            assert {row["job_id"] for row in everything} == {website["job_id"], ad["job_id"]}
            await txn.rollback()

    run_async(_check())


def test_require_job_is_fail_closed_across_workspaces(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            owner = await _seed_ws(conn)
            stranger = await _seed_ws(conn)
            job_id = (
                await design_ingestion.create_job(
                    conn, workspace_id=owner, kind="website", request={"url": "https://x.example"}
                )
            )["job_id"]
            # A foreign-workspace job id is indistinguishable from an absent one.
            with pytest.raises(DesignNotFoundError):
                await design_ingestion.require_job(conn, workspace_id=stranger, job_id=job_id)
            with pytest.raises(DesignNotFoundError):
                await design_ingestion.require_job(
                    conn, workspace_id=stranger, job_id="ingest_does_not_exist"
                )
            assert (
                await design_ingestion.get_job(conn, workspace_id=stranger, job_id=job_id)
            ) is None
            # …while the owner still sees it.
            assert (await design_ingestion.require_job(conn, workspace_id=owner, job_id=job_id))[
                "job_id"
            ] == job_id
            await txn.rollback()

    run_async(_check())


def test_put_ai_never_overwrites_a_human_description(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            asset_id = await _seed_asset(conn, ws)
            await design_descriptions.put_ai(
                conn,
                workspace_id=ws,
                asset_id=asset_id,
                title="AI first",
                description="AI caption.",
                usage="AI usage.",
                tags=["ai"],
                model="some/model",
            )
            row = await _description_row(conn, ws, asset_id)
            assert row is not None and row.origin == "ai" and row.model == "some/model"

            await design_descriptions.put_human(
                conn,
                workspace_id=ws,
                asset_id=asset_id,
                title="Human title",
                description="Human desc.",
                usage="Human usage.",
                tags=["h"],
            )
            # The AI pass runs again (a re-ingest, a backfill) and must lose.
            await design_descriptions.put_ai(
                conn,
                workspace_id=ws,
                asset_id=asset_id,
                title="AI second",
                description="AI desc.",
                usage="AI usage.",
                tags=["ai"],
                model="another/model",
            )
            row = await _description_row(conn, ws, asset_id)
            assert row is not None
            assert row.origin == "human"
            assert row.title == "Human title"
            assert row.description == "Human desc."
            assert row.usage == "Human usage."
            assert row.model is None  # the human row never took the AI attribution
            fetched = await design_descriptions.get_many(
                conn, workspace_id=ws, asset_ids=[asset_id]
            )
            assert fetched[asset_id]["title"] == "Human title"
            assert fetched[asset_id]["tags"] == ["h"]
            await txn.rollback()

    run_async(_check())


def test_get_many_returns_only_the_callers_workspace(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws_a = await _seed_ws(conn)
            ws_b = await _seed_ws(conn)
            asset_a = await _seed_asset(conn, ws_a)
            asset_b = await _seed_asset(conn, ws_b)
            await design_descriptions.put_human(
                conn,
                workspace_id=ws_a,
                asset_id=asset_a,
                title="A",
                description=None,
                usage=None,
                tags=[],
            )
            await design_descriptions.put_human(
                conn,
                workspace_id=ws_b,
                asset_id=asset_b,
                title="B",
                description=None,
                usage=None,
                tags=[],
            )
            both = [asset_a, asset_b]
            seen_a = await design_descriptions.get_many(conn, workspace_id=ws_a, asset_ids=both)
            assert list(seen_a) == [asset_a] and seen_a[asset_a]["title"] == "A"
            seen_b = await design_descriptions.get_many(conn, workspace_id=ws_b, asset_ids=both)
            assert list(seen_b) == [asset_b] and seen_b[asset_b]["title"] == "B"
            assert await design_descriptions.get_many(conn, workspace_id=ws_a, asset_ids=[]) == {}
            await txn.rollback()

    run_async(_check())


# --- harvested ads are ads at the read seam (spec 2026-10-30, reference ads §5.2) -------------


async def _harvest(conn: AsyncConnection, ws: str, asset_id: str) -> None:
    """One ``design_ad_creative`` row for ``asset_id`` — what the Adyntel harvest writes."""
    await conn.execute(
        text(
            "INSERT INTO design_ad_creative (creative_id, workspace_id, harvest_job_id, provider,"
            " ad_id, creative_url, asset_id, fetched_at, provenance_json) VALUES (:c, :w, 'job',"
            " 'adyntel', :c, 'https://example.com/ad.png', :a, now(), '{}'::jsonb)"
        ),
        {"c": f"cr_{uuid4().hex[:10]}", "w": ws, "a": asset_id},
    )


async def _describe(conn: AsyncConnection, ws: str, asset_id: str, ai_type: str) -> None:
    await design_descriptions.put_ai(
        conn, workspace_id=ws, asset_id=asset_id, title="T", description="D.", usage="U.",
        tags=[], model="some/model",
    )
    await conn.execute(
        text(
            "UPDATE design_asset_description SET analysis_json = CAST(:j AS jsonb)"
            " WHERE asset_id = :a AND workspace_id = :w"
        ),
        {"j": f'{{"creative_type": "{ai_type}"}}', "a": asset_id, "w": ws},
    )


def test_get_many_marks_harvested_assets_as_ads(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            harvested = await _seed_asset(conn, ws)
            plain = await _seed_asset(conn, ws)
            await _harvest(conn, ws, harvested)
            await _describe(conn, ws, harvested, "photo")
            await _describe(conn, ws, plain, "ad")
            rows = await design_descriptions.get_many(
                conn, workspace_id=ws, asset_ids=[harvested, plain]
            )
            assert rows[harvested]["creative_type"] == "ad"
            assert rows[plain]["creative_type"] == "other"
            await txn.rollback()

    run_async(_check())


def test_a_harvested_asset_with_no_row_appears_only_when_stubs_are_asked_for(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            harvested = await _seed_asset(conn, ws)
            undescribed = await _seed_asset(conn, ws)
            await _harvest(conn, ws, harvested)
            ids = [harvested, undescribed]
            assert await design_descriptions.get_many(conn, workspace_id=ws, asset_ids=ids) == {}
            rows = await design_descriptions.get_many(
                conn, workspace_id=ws, asset_ids=ids, harvested_stubs=True
            )
            assert list(rows) == [harvested]
            assert rows[harvested]["asset_id"] == harvested
            assert rows[harvested]["creative_type"] == "ad"
            assert rows[harvested]["status"] == "stale"
            await txn.rollback()

    run_async(_check())


def test_another_workspaces_harvest_does_not_make_an_asset_an_ad(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws_a = await _seed_ws(conn)
            ws_b = await _seed_ws(conn)
            asset_a = await _seed_asset(conn, ws_a)
            asset_b = await _seed_asset(conn, ws_b)
            await _harvest(conn, ws_b, asset_b)
            await _describe(conn, ws_a, asset_a, "photo")
            rows = await design_descriptions.get_many(
                conn, workspace_id=ws_a, asset_ids=[asset_a, asset_b], harvested_stubs=True
            )
            assert list(rows) == [asset_a] and rows[asset_a]["creative_type"] == "photo"
            await txn.rollback()

    run_async(_check())
