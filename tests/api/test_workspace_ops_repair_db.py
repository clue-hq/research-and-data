"""Workspace repair, plan and apply, end to end over real rows (spec 2026-10-25 §3.4, §10).

The Illumio replay: an onboarding whose ICP turn failed on a disabled OpenRouter key, a brand kit
whose descriptions all failed, a harvest with ads and no card. The dry run plans exactly that; the
apply writes one repair run, one ``kit_repair`` job, their fleet tasks and one audit row, all in
one transaction; a second apply finds nothing to do.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.workspace_ops.operators import Operator, OpsRefused
from clue_api.workspace_ops.repair import apply_repair, plan_repair
from clue_db import db_lifespan
from clue_design import assets as design_assets
from clue_design import brand as design_brand
from clue_design import ingestion as design_ingestion
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.auth.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


async def _illumio(conn: AsyncConnection, *, failed_assets: int = 4) -> tuple[str, Operator, dict]:
    ws = f"ws-ops-repair-{uuid4().hex[:8]}"
    project = await seed_project(conn, ws, name="Illumio")
    user = f"usr_ops_repair_{uuid4().hex[:8]}"
    await seed_principal(conn, workspace_id=ws, user_id=user)
    email = f"ops.{uuid4().hex[:6]}@cluehq.ai"
    await conn.execute(
        text("UPDATE platform_user SET email = :e WHERE user_id = :u"), {"e": email, "u": user}
    )
    run_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain,"
            " requested_by_user_id, requested_at, status, finished_at) VALUES (:r, :w, :b,"
            " 'illumio.com', :u, :at, 'completed_with_gaps', :fin)"
        ),
        {
            "r": run_id,
            "w": ws,
            "b": project.brand_id,
            "u": user,
            "at": _T0,
            "fin": _T0 + timedelta(minutes=9),
        },
    )
    for offset, (kind, status, code) in enumerate(
        (
            ("overview", "completed", None),
            ("lineup", "completed", None),
            ("synthesis", "failed", "provider_refused:openrouter:auth_invalid"),
        )
    ):
        await conn.execute(
            text(
                "INSERT INTO onboarding_step (step_id, run_id, workspace_id, kind, phase, status,"
                " started_at, finished_at, failure_code) VALUES (:s, :r, :w, :k, 'fast', :st,"
                " :at, :at, :code)"
            ),
            {
                "s": uuid4(),
                "r": run_id,
                "w": ws,
                "k": kind,
                "st": status,
                "at": _T0 + timedelta(seconds=offset),
                "code": code,
            },
        )
    asset_ids = []
    for _ in range(failed_assets):
        asset_id = f"asset_ops_{uuid4().hex[:12]}"
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
                    "filename": "a.png",
                    "digest": {"algorithm": "sha256", "value": digest},
                    "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest}"},
                },
            },
        )
        await conn.execute(
            text(
                "INSERT INTO design_asset_description (workspace_id, asset_id, origin,"
                " analysis_status) VALUES (:w, :a, 'human', 'failed')"
            ),
            {"w": ws, "a": asset_id},
        )
        asset_ids.append(asset_id)
    kit_id = f"brand_kit_ops_{uuid4().hex[:8]}"
    await design_brand.create_brand_kit(
        conn,
        workspace_id=ws,
        brand_kit={
            "id": kit_id,
            "version": 1,
            "name": "Illumio",
            "approval_status": "approved",
            "assets": {
                "images": {
                    f"img.{n}": {"asset_id": aid, "role": "photo"}
                    for n, aid in enumerate(asset_ids)
                }
            },
        },
        brand_summary={"product_ready": False},
        diagnostics=[],
        source="website",
    )
    jobs = {}
    for kind, request, evidence, kit in (
        ("website", {"url": "https://illumio.com"}, {"gaps": [{"area": "descriptions"}]}, kit_id),
        ("ad_assets", {"phase": "harvest"}, {"outcome": {"creatives_custodied": 6}}, None),
    ):
        job = await design_ingestion.create_job(conn, workspace_id=ws, kind=kind, request=request)
        await conn.execute(
            text(
                "UPDATE design_ingestion_job SET status = 'succeeded_with_gaps',"
                " brand_kit_id = :k, brand_kit_version = :v, evidence_json = CAST(:e AS jsonb),"
                " created_at = clock_timestamp() WHERE job_id = :j"
            ),
            {"k": kit, "v": 1 if kit else None, "e": json.dumps(evidence), "j": job["job_id"]},
        )
        jobs[kind] = job["job_id"]
    return (
        ws,
        Operator(user_id=user, email=email),
        {"assets": sorted(asset_ids), "kit": kit_id, "harvest": jobs["ad_assets"]},
    )


async def _count(conn: AsyncConnection, sql: str, ws: str) -> int:
    return int((await conn.execute(text(sql), {"w": ws})).scalar_one())


def test_illumio_replay_dry_run_then_apply_then_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, operator, facts = await _illumio(conn)
            plan = await plan_repair(conn, workspace_id=ws)
            assert [(s.kind, s.subject_ref) for s in plan.onboarding.steps] == [("synthesis", None)]
            assert plan.kit.describe == tuple(facts["assets"])
            assert plan.kit.republish_brand_kit_id == facts["kit"]
            assert plan.kit.offer_card_for_harvest == facts["harvest"]
            assert plan.estimated_cost_usd > 0
            # A dry run writes nothing.
            assert (
                await _count(
                    conn,
                    "SELECT count(*) FROM onboarding_run WHERE"
                    " workspace_id = :w AND kind = 'repair'",
                    ws,
                )
                == 0
            )

            result = await apply_repair(
                conn,
                workspace_id=ws,
                plan_digest=plan.plan_digest,
                operator=operator,
                reason="2026-10-23 outage",
            )

            run = (
                await conn.execute(
                    text(
                        "SELECT run_id, kind, planned_steps, requested_by_user_id FROM onboarding_run"
                        " WHERE workspace_id = :w AND kind = 'repair'"
                    ),
                    {"w": ws},
                )
            ).one()
            assert run.planned_steps == [{"kind": "synthesis", "subject_ref": None}]
            assert run.requested_by_user_id == operator.user_id
            assert str(run.run_id) == result["onboarding_run_id"]
            task = (
                await conn.execute(
                    text(
                        "SELECT payload_json FROM fleet_task WHERE kind = 'onboarding_run'"
                        " AND dedup_key = :d"
                    ),
                    {"d": f"onboarding-run:{run.run_id}"},
                )
            ).scalar_one()
            assert task["kind"] == "repair" and task["planned_steps"] == run.planned_steps
            [job_id] = result["design_job_ids"]
            job = await design_ingestion.get_job(conn, workspace_id=ws, job_id=job_id)
            assert job["kind"] == "kit_repair" and job["status"] == "queued"
            assert sorted(job["request"]["targets"]) == facts["assets"]
            assert job["request"]["republish_brand_kit_id"] == facts["kit"]
            assert job["request"]["offer_card"] is True
            audit = (
                await conn.execute(
                    text(
                        "SELECT actor, reason, onboarding_run_id, design_job_ids, estimated_cost_usd"
                        " FROM workspace_operation WHERE workspace_id = :w"
                    ),
                    {"w": ws},
                )
            ).one()
            assert audit.actor == f"operator:{operator.email}"
            assert audit.reason == "2026-10-23 outage"
            assert (audit.onboarding_run_id, audit.design_job_ids) == (run.run_id, [job_id])
            assert audit.estimated_cost_usd == plan.estimated_cost_usd

            again = await plan_repair(conn, workspace_id=ws)
            with pytest.raises(OpsRefused) as refused:
                await apply_repair(
                    conn,
                    workspace_id=ws,
                    plan_digest=again.plan_digest,
                    operator=operator,
                    reason="again",
                )
            assert (refused.value.status, refused.value.code) == (409, "nothing_to_repair")

    run_async(scenario())


def test_apply_with_a_stale_digest_is_plan_changed() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, operator, facts = await _illumio(conn)
            plan = await plan_repair(conn, workspace_id=ws)
            await conn.execute(
                text(
                    "UPDATE design_asset_description SET analysis_status = 'ready',"
                    " title = 'Healed' WHERE workspace_id = :w AND asset_id = :a"
                ),
                {"w": ws, "a": facts["assets"][0]},
            )
            with pytest.raises(OpsRefused) as refused:
                await apply_repair(
                    conn,
                    workspace_id=ws,
                    plan_digest=plan.plan_digest,
                    operator=operator,
                    reason="outage",
                )
            assert (refused.value.status, refused.value.code) == (409, "plan_changed")
            assert len(refused.value.detail["plan"]["kit"]["describe"]) == 3

    run_async(scenario())


def test_a_blank_reason_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, operator, _ = await _illumio(conn)
            plan = await plan_repair(conn, workspace_id=ws)
            with pytest.raises(OpsRefused) as refused:
                await apply_repair(
                    conn,
                    workspace_id=ws,
                    plan_digest=plan.plan_digest,
                    operator=operator,
                    reason="  ",
                )
            assert (refused.value.status, refused.value.code) == (422, "reason_required")

    run_async(scenario())


def test_two_applies_race_and_exactly_one_wins() -> None:
    """Review Focus 1: two operators apply the same plan at the same moment, on two connections.
    The per-workspace lock serializes them; the second re-plans, finds the first's work in
    flight, and refuses."""

    async def scenario() -> list[Any]:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                ws, operator, _ = await _illumio(conn, failed_assets=2)
                digest = (await plan_repair(conn, workspace_id=ws)).plan_digest

            async def apply() -> Any:
                async with engine.begin() as conn:
                    try:
                        return await apply_repair(
                            conn,
                            workspace_id=ws,
                            plan_digest=digest,
                            operator=operator,
                            reason="race",
                        )
                    except OpsRefused as refused:
                        return refused

            return list(await asyncio.gather(apply(), apply()))

    outcomes = run_async(scenario())
    refused = [o for o in outcomes if isinstance(o, OpsRefused)]
    applied = [o for o in outcomes if not isinstance(o, OpsRefused)]
    assert len(applied) == 1 and len(refused) == 1
    assert refused[0].code in ("nothing_to_repair", "plan_changed")
