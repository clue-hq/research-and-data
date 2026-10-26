"""The brand-kit half of a workspace repair plan (spec 2026-10-25 §3.4 B).

Read-only: what a workspace's brand kit is missing after an outage, and what is already in
flight. Every scenario seeds real rows inside a rolled-back transaction.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import assets as design_assets
from clue_design import brand as design_brand
from clue_design import ingestion as design_ingestion
from clue_design.kit_repair import KitRepairPlan, plan_kit_repair
from tests.design.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_design_db")


async def _ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_kitplan_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _asset(conn: AsyncConnection, ws: str, status: str | None, *, text_: bool = False) -> str:
    asset_id = f"asset_kp_{uuid4().hex[:12]}"
    digest = uuid4().hex + uuid4().hex
    await design_assets.create_asset_record(
        conn,
        workspace_id=ws,
        record={
            "id": asset_id,
            "label": "Image",
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
    if status is not None:
        await conn.execute(
            text(
                "INSERT INTO design_asset_description (workspace_id, asset_id, origin, title,"
                " description, model, analysis_status) VALUES (:w, :a, 'ai', :t, :d, 'm', :s)"
            ),
            {
                "w": ws,
                "a": asset_id,
                "s": status,
                "t": "Title" if text_ else None,
                "d": "Described." if text_ else None,
            },
        )
    return asset_id


async def _kit(
    conn: AsyncConnection, ws: str, asset_ids: list[str], *, stamped: bool = False
) -> str:
    kit_id = f"kit_kp_{uuid4().hex[:10]}"
    images = {
        f"img.{n}": {
            "asset_id": aid,
            "role": "photo",
            **({"description": "Described."} if stamped else {}),
        }
        for n, aid in enumerate(asset_ids)
    }
    await design_brand.create_brand_kit(
        conn,
        workspace_id=ws,
        brand_kit={
            "id": kit_id,
            "version": 1,
            "name": "Kit",
            "approval_status": "approved",
            "assets": {"images": images},
        },
        brand_summary={"product_ready": False},
        diagnostics=[],
        source="website",
    )
    return kit_id


async def _job(
    conn: AsyncConnection,
    ws: str,
    kind: str,
    status: str,
    *,
    request: dict | None = None,
    kit_id: str | None = None,
    evidence: dict | None = None,
) -> str:
    job = await design_ingestion.create_job(
        conn, workspace_id=ws, kind=kind, request=request or {"url": "https://acme.com"}
    )
    await conn.execute(
        text(
            "UPDATE design_ingestion_job SET status = CAST(:s AS design_ingestion_status),"
            " brand_kit_id = :k, brand_kit_version = :v, evidence_json = CAST(:e AS jsonb),"
            # One transaction shares one now(); the planner reads newest-first, so each seeded
            # job gets its own moment, in seeding order.
            " created_at = clock_timestamp()"
            " WHERE job_id = :j"
        ),
        {
            "s": status,
            "k": kit_id,
            "v": 1 if kit_id else None,
            "e": json.dumps(evidence) if evidence is not None else None,
            "j": job["job_id"],
        },
    )
    return str(job["job_id"])


async def _harvest(conn: AsyncConnection, ws: str) -> str:
    return await _job(
        conn,
        ws,
        "ad_assets",
        "succeeded",
        request={"phase": "harvest", "company_domain": "acme.com"},
        evidence={"outcome": {"creatives_custodied": 4}},
    )


def _plan(seed: Any) -> tuple[KitRepairPlan, dict]:
    async def scenario() -> tuple[KitRepairPlan, dict]:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws, facts = await seed(conn)
                return await plan_kit_repair(conn, workspace_id=ws), facts
            finally:
                await trans.rollback()

    return run_async(scenario())


def test_illumio_shape_plans_descriptions_republish_and_card() -> None:
    async def seed(conn: AsyncConnection) -> tuple[str, dict]:
        ws = await _ws(conn)
        failed = [await _asset(conn, ws, "failed") for _ in range(3)]
        ready_unstamped = await _asset(conn, ws, "ready", text_=True)
        unsupported = await _asset(conn, ws, "unsupported")
        kit_id = await _kit(conn, ws, [*failed, ready_unstamped, unsupported])
        await _job(conn, ws, "website", "succeeded_with_gaps", kit_id=kit_id)
        harvest = await _harvest(conn, ws)
        return ws, {"failed": failed, "unsupported": unsupported, "kit": kit_id, "harvest": harvest}

    plan, facts = _plan(seed)
    assert plan.describe == tuple(sorted(facts["failed"]))
    assert plan.unsupported == (facts["unsupported"],)
    assert plan.republish_brand_kit_id == facts["kit"]
    assert plan.offer_card_for_harvest == facts["harvest"]
    assert plan.capture_website is None
    assert plan.in_flight == ()


def test_running_kit_job_means_everything_in_flight() -> None:
    async def seed(conn: AsyncConnection) -> tuple[str, dict]:
        ws = await _ws(conn)
        failed = await _asset(conn, ws, "failed")
        kit_id = await _kit(conn, ws, [failed])
        await _job(conn, ws, "website", "succeeded_with_gaps", kit_id=kit_id)
        await _job(conn, ws, "website", "running")
        return ws, {}

    plan, _ = _plan(seed)
    assert plan.describe == () and plan.republish_brand_kit_id is None
    assert plan.offer_card_for_harvest is None and plan.capture_website is None
    assert plan.in_flight and "running" in plan.in_flight[0]


def test_an_open_kit_repair_job_means_everything_in_flight() -> None:
    async def seed(conn: AsyncConnection) -> tuple[str, dict]:
        ws = await _ws(conn)
        failed = await _asset(conn, ws, "failed")
        kit_id = await _kit(conn, ws, [failed])
        await _job(conn, ws, "website", "succeeded", kit_id=kit_id)
        await _job(conn, ws, "kit_repair", "queued", request={"targets": {failed: {}}})
        return ws, {}

    plan, _ = _plan(seed)
    assert plan.describe == () and plan.in_flight


def test_no_kit_and_failed_capture_plans_only_capture() -> None:
    async def seed(conn: AsyncConnection) -> tuple[str, dict]:
        ws = await _ws(conn)
        await _asset(conn, ws, "failed")
        await _job(conn, ws, "website", "failed", request={"url": "https://acme.com"})
        return ws, {}

    plan, _ = _plan(seed)
    assert plan.capture_website == "https://acme.com"
    assert plan.describe == () and plan.republish_brand_kit_id is None


def test_complete_workspace_plans_nothing() -> None:
    async def seed(conn: AsyncConnection) -> tuple[str, dict]:
        ws = await _ws(conn)
        ready = await _asset(conn, ws, "ready", text_=True)
        kit_id = await _kit(conn, ws, [ready], stamped=True)
        await _job(conn, ws, "website", "succeeded", kit_id=kit_id)
        return ws, {}

    plan, _ = _plan(seed)
    assert plan.is_empty
    assert plan == KitRepairPlan()


def test_a_harvest_with_a_card_or_an_open_card_job_plans_no_card() -> None:
    async def seed(conn: AsyncConnection) -> tuple[str, dict]:
        ws = await _ws(conn)
        ready = await _asset(conn, ws, "ready", text_=True)
        kit_id = await _kit(conn, ws, [ready], stamped=True)
        await _job(conn, ws, "website", "succeeded", kit_id=kit_id)
        harvest = await _harvest(conn, ws)
        await _job(
            conn, ws, "ad_assets", "queued", request={"phase": "card", "harvest_job_id": harvest}
        )
        return ws, {}

    plan, _ = _plan(seed)
    assert plan.offer_card_for_harvest is None


def test_sixty_retry_jobs_above_the_kit_job_do_not_hide_the_kit_or_the_harvest() -> None:
    """Final review #1: Illumio's recovered descriptions came through one ``asset_enrichment``
    job per asset. A planner that windowed the newest 50 jobs of ANY kind saw only those and
    planned nothing for the kit or the card."""

    async def seed(conn: AsyncConnection) -> tuple[str, dict]:
        ws = await _ws(conn)
        failed = [await _asset(conn, ws, "failed") for _ in range(2)]
        kit_id = await _kit(conn, ws, failed)
        await _job(conn, ws, "website", "succeeded_with_gaps", kit_id=kit_id)
        harvest = await _harvest(conn, ws)
        for _ in range(60):
            await _job(conn, ws, "asset_enrichment", "succeeded", request={"targets": {}})
        return ws, {"failed": failed, "kit": kit_id, "harvest": harvest}

    plan, facts = _plan(seed)
    assert plan.describe == tuple(sorted(facts["failed"]))
    assert plan.republish_brand_kit_id == facts["kit"]
    assert plan.offer_card_for_harvest == facts["harvest"]
