#!/usr/bin/env python3
"""Research the existing customers of brands onboarded before that step existed.

    set -a; source .env; set +a
    uv run python scripts/backfill_existing_customers.py                       # plan only
    uv run python scripts/backfill_existing_customers.py --workspace ws_...    # one workspace
    uv run python scripts/backfill_existing_customers.py --apply               # create the runs

Onboarding writes ``proof/customers.md`` (spec 2026-10-16-discovery-excludes-seller-customers
§4.4): the companies that already buy from the seller, which the Head of ABM leaves out of account
discovery. A brand onboarded earlier has no such page. For each one, this creates a ``customers``
onboarding run — only that step — and offers its fleet task; a worker then does the research.

A brand is planned when its latest whole-brand onboarding completed, it has no live
``proof/customers.md``, and no onboarding run of any kind is in flight for it. Each run is one
Exa Agent call at ``CLUE_ONBOARDING_CUSTOMERS_EFFORT`` (about $1 at ``xhigh``) plus one homepage
check per customer domain.

**Dry run by default.** Without ``--apply`` it prints the plan and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_store import create_customers_run
from clue_db import db_lifespan, transaction

_PLAN = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (r.brand_id) r.workspace_id, r.brand_id, r.company_domain,
               r.requested_by_user_id
        FROM onboarding_run r
        WHERE r.kind = 'full' AND r.status IN ('completed', 'completed_with_gaps')
          AND (CAST(:workspace_id AS text) IS NULL OR r.workspace_id = :workspace_id)
        ORDER BY r.brand_id, r.requested_at DESC
    )
    SELECT l.workspace_id, l.brand_id, b.name AS brand_name, l.company_domain,
           l.requested_by_user_id
    FROM latest l
    JOIN brand b ON b.brand_id = l.brand_id AND b.workspace_id = l.workspace_id
    WHERE NOT EXISTS (
        SELECT 1 FROM brand_knowledge_document d
        WHERE d.workspace_id = l.workspace_id AND d.brand_id = l.brand_id
          AND d.path = 'proof/customers.md' AND d.status NOT IN ('superseded', 'failed')
    )
    AND NOT EXISTS (
        SELECT 1 FROM onboarding_run o
        WHERE o.workspace_id = l.workspace_id AND o.brand_id = l.brand_id
          AND o.status IN ('queued', 'running')
    )
    ORDER BY l.workspace_id, b.name
    """
)


@dataclass(frozen=True)
class PlannedBrand:
    workspace_id: str
    brand_id: str
    brand_name: str
    company_domain: str
    requested_by_user_id: str


class CustomersEnqueuer(Protocol):
    async def enqueue_customers(
        self,
        *,
        run_id: UUID,
        workspace_id: str,
        brand_id: str,
        company_domain: str,
        company_name: str,
    ) -> bool: ...


async def plan_backfill(
    conn: AsyncConnection, *, workspace_id: str | None = None
) -> list[PlannedBrand]:
    rows = (await conn.execute(_PLAN, {"workspace_id": workspace_id})).mappings().all()
    return [
        PlannedBrand(
            workspace_id=row["workspace_id"],
            brand_id=row["brand_id"],
            brand_name=row["brand_name"],
            company_domain=row["company_domain"],
            requested_by_user_id=row["requested_by_user_id"],
        )
        for row in rows
    ]


async def create_runs(
    conn: AsyncConnection, plan: Sequence[PlannedBrand]
) -> list[tuple[PlannedBrand, UUID]]:
    created: list[tuple[PlannedBrand, UUID]] = []
    for brand in plan:
        run_id = uuid4()
        await create_customers_run(
            conn,
            run_id=run_id,
            workspace_id=brand.workspace_id,
            brand_id=brand.brand_id,
            company_domain=brand.company_domain,
            requested_by_user_id=brand.requested_by_user_id,
        )
        created.append((brand, run_id))
    return created


async def offer_runs(
    enqueuer: CustomersEnqueuer, created: Sequence[tuple[PlannedBrand, UUID]]
) -> None:
    for brand, run_id in created:
        await enqueuer.enqueue_customers(
            run_id=run_id,
            workspace_id=brand.workspace_id,
            brand_id=brand.brand_id,
            company_domain=brand.company_domain,
            company_name=brand.brand_name,
        )


async def apply_backfill(
    conn: AsyncConnection, plan: Sequence[PlannedBrand], *, enqueuer: CustomersEnqueuer
) -> list[UUID]:
    """Create and offer every planned run on ``conn``. The CLI instead commits the runs before
    offering their tasks, so a worker never takes a task whose run row it cannot yet see."""
    created = await create_runs(conn, plan)
    await offer_runs(enqueuer, created)
    return [run_id for _brand, run_id in created]


async def _run(*, apply: bool, workspace_id: str | None) -> None:
    from clue_api.onboarding_routes import DbOnboardingEnqueuer

    async with db_lifespan():
        async with transaction() as conn:
            plan = await plan_backfill(conn, workspace_id=workspace_id)
            for brand in plan:
                print(f"{brand.workspace_id}  {brand.brand_name}  {brand.company_domain}  (~$1)")
            print(f"{len(plan)} brand(s) without proof/customers.md")
            if not apply or not plan:
                print("dry run: nothing written" if not apply else "nothing to do")
                return
            created = await create_runs(conn, plan)
        await offer_runs(DbOnboardingEnqueuer(), created)
        print(f"created and offered {len(created)} customers run(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create and offer the runs")
    parser.add_argument("--workspace", default=None, help="only this workspace id")
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply, workspace_id=args.workspace))


if __name__ == "__main__":
    main()
