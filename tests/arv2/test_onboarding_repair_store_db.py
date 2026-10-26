"""The store reads and writes a repair run needs (spec 2026-10-25 §3.4 A)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_store import (
    create_repair_run,
    current_brand_icps,
    product_links,
    researched_product_ids,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _seed(conn: AsyncConnection) -> tuple[str, str, str]:
    ws = f"ws-repair-store-{uuid4().hex[:6]}"
    project = await seed_project(conn, ws, name="Repair store")
    user = f"usr_repair_store_{uuid4().hex[:6]}"
    await seed_principal(conn, workspace_id=ws, user_id=user)
    return ws, project.brand_id, user


def test_create_repair_run_carries_its_planned_steps() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, user = await _seed(conn)
            run_id = uuid4()
            planned = [{"kind": "synthesis", "subject_ref": None}]
            await create_repair_run(
                conn,
                run_id=run_id,
                workspace_id=ws,
                brand_id=brand,
                company_domain="illumio.com",
                requested_by_user_id=user,
                planned_steps=planned,
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT kind, status, planned_steps FROM onboarding_run WHERE run_id = :r"
                    ),
                    {"r": run_id},
                )
            ).one()
            assert (row.kind, row.status, row.planned_steps) == ("repair", "queued", planned)

    run_async(scenario())


def test_product_reads_and_current_icps() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws, brand, user = await _seed(conn)
            for pid, name in (("prd_a", "Alpha"), ("prd_b", "Beta")):
                await conn.execute(
                    text(
                        "INSERT INTO product (product_id, brand_id, workspace_id, name, aliases)"
                        " VALUES (:p, :b, :w, :n, '[]'::jsonb)"
                    ),
                    {"p": pid, "b": brand, "w": ws, "n": name},
                )
            run_id = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain,"
                    " requested_by_user_id) VALUES (:r, :w, :b, 'a.com', :u)"
                ),
                {"r": run_id, "w": ws, "b": brand, "u": user},
            )
            await conn.execute(
                text(
                    "INSERT INTO onboarding_step (step_id, run_id, workspace_id, kind, subject_ref,"
                    " phase, status, finished_at) VALUES (:s, :r, :w, 'product_research', 'prd_a',"
                    " 'background', 'completed', now())"
                ),
                {"s": uuid4(), "r": run_id, "w": ws},
            )
            for version, status in ((1, "superseded"), (2, "proposed")):
                await conn.execute(
                    text(
                        "INSERT INTO brand_knowledge_document (document_id, workspace_id,"
                        " brand_id, folder, path, kind, version, status, artifact_key,"
                        " artifact_sha256) VALUES (:d, :w, :b, 'audience',"
                        " 'audience/icp-enterprise.md', 'icp', :v, :s, 'k', :sha)"
                    ),
                    {"d": uuid4(), "w": ws, "b": brand, "v": version, "s": status, "sha": "a" * 64},
                )

            assert await researched_product_ids(conn, workspace_id=ws, brand_id=brand) == {"prd_a"}
            links = await product_links(conn, workspace_id=ws, product_ids=["prd_b", "prd_x"])
            assert [(link.product_id, link.name) for link in links] == [("prd_b", "Beta")]
            icps = await current_brand_icps(
                conn, workspace_id=ws, brand_id=brand, icp_keys=["enterprise", "missing"]
            )
            assert [(icp.icp_key, icp.version, icp.project_id) for icp in icps] == [
                ("enterprise", 2, None)
            ]

    run_async(scenario())
