"""The existing-customers backfill, against real rows (spec 2026-10-16 §4.4).

A brand onboarded before the customers step existed has no ``proof/customers.md``. The script
plans one ``customers`` run per such brand (dry run by default) and, when applied, creates the run
and offers its fleet task. It never touches a brand that already has the page or that has a run in
flight.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from scripts.backfill_existing_customers import apply_backfill, plan_backfill
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

USER = "usr_customers_backfill"


class _Enqueuer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue_customers(self, **kwargs: Any) -> bool:
        self.calls.append(kwargs)
        return True


async def _onboarded_brand(
    conn: AsyncConnection, workspace_id: str, *, domain: str, status: str = "completed"
) -> str:
    project = await seed_project(conn, workspace_id, name=f"Backfill {domain}")
    await seed_principal(conn, workspace_id=workspace_id, user_id=USER)
    finished = None if status in ("queued", "running") else datetime(2026, 9, 1, tzinfo=UTC)
    await conn.execute(
        text(
            "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain, "
            " requested_by_user_id, status, finished_at) "
            "VALUES (:run, :ws, :brand, :domain, :user, :status, :finished)"
        ),
        {
            "run": uuid4(),
            "ws": workspace_id,
            "brand": project.brand_id,
            "domain": domain,
            "user": USER,
            "status": status,
            "finished": finished,
        },
    )
    return project.brand_id


async def _customers_page(conn: AsyncConnection, workspace_id: str, brand_id: str) -> None:
    """A page being written counts as the brand having one: the backfill must not start another."""
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            " path, kind, status, version) "
            "VALUES (:id, :ws, :brand, 'proof', 'proof/customers.md', 'existing-customers', "
            " 'running', 1)"
        ),
        {"id": uuid4(), "ws": workspace_id, "brand": brand_id},
    )


def test_dry_run_lists_brands_without_a_customers_page_and_writes_nothing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws_customers_backfill_dry"
            missing = await _onboarded_brand(conn, ws, domain="conduit.ai")
            has_page = await _onboarded_brand(conn, ws, domain="altcarbon.com")
            await _customers_page(conn, ws, has_page)

            plan = await plan_backfill(conn, workspace_id=ws)

            assert [(row.brand_id, row.company_domain) for row in plan] == [(missing, "conduit.ai")]
            assert plan[0].requested_by_user_id == USER
            runs = await conn.scalar(
                text(
                    "SELECT count(*) FROM onboarding_run WHERE workspace_id = :ws "
                    "AND kind = 'customers'"
                ),
                {"ws": ws},
            )
            assert runs == 0

    run_async(scenario())


def test_apply_creates_one_customers_run_per_brand_and_skips_brands_with_an_open_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws_customers_backfill_apply"
            brand = await _onboarded_brand(conn, ws, domain="conduit.ai")
            busy = await _onboarded_brand(conn, ws, domain="busy.example")
            await conn.execute(
                text(
                    "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain, "
                    " requested_by_user_id, status) "
                    "VALUES (:run, :ws, :brand, 'busy.example', :user, 'running')"
                ),
                {"run": uuid4(), "ws": ws, "brand": busy, "user": USER},
            )
            enqueuer = _Enqueuer()

            plan = await plan_backfill(conn, workspace_id=ws)
            created = await apply_backfill(conn, plan, enqueuer=enqueuer)

            assert [row.brand_id for row in plan] == [brand]
            (run_id,) = created
            row = (
                await conn.execute(
                    text(
                        "SELECT kind, status, company_domain FROM onboarding_run "
                        "WHERE run_id = :run"
                    ),
                    {"run": run_id},
                )
            ).one()
            assert tuple(row) == ("customers", "queued", "conduit.ai")
            (call,) = enqueuer.calls
            assert call["run_id"] == run_id and call["brand_id"] == brand
            assert call["company_domain"] == "conduit.ai"
            assert isinstance(call["company_name"], str) and call["company_name"]
            # A second pass finds the run in flight and plans nothing.
            assert await plan_backfill(conn, workspace_id=ws) == []
            assert isinstance(run_id, UUID)

    run_async(scenario())
