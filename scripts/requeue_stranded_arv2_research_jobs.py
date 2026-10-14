#!/usr/bin/env python3
"""Offer ARV2 research jobs that were left with no fleet task back to the fleet (one-off repair).

    set -a; source .env; set +a
    uv run python scripts/requeue_stranded_arv2_research_jobs.py            # plan only
    uv run python scripts/requeue_stranded_arv2_research_jobs.py --apply    # re-offer them

Until 2026-10-05 a job could end up ``suspended`` (or ``in_progress``) while its fleet task was
already closed: a worker froze past its lease, the re-offered task found the job ``in_progress``
and closed itself as a no-op, and the frozen worker then parked the job. Nothing ever offered it
again, and the research card read "paused". The driver now takes such a job over and fences the
old worker's writes, so no new job strands this way; this script repairs the ones that already did.

A job is **stranded** when it has been started (``suspended`` or ``in_progress``) and no task for
it is open (``queued`` or ``claimed``). ``not_started`` jobs are left alone: a person job may be
held back on purpose until its account is ready to release it. Re-offering re-opens the job's own
closed task (same dedup key), exactly as the launch offers it; the next worker to claim it takes
the job over. Idempotent: once re-offered, a job has an open task and is no longer planned.

**Dry run by default.** Without ``--apply`` it prints the plan and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.job_resume import offer_research_job
from clue_db import db_lifespan, transaction
from clue_fleet import FleetTaskKind

_STRANDED = text(
    """
    SELECT j.job_id, j.run_id, j.workspace_id, j.subject_type, j.status, j.updated_at
    FROM arv2_research_job j
    WHERE j.status IN ('suspended', 'in_progress')
      AND NOT EXISTS (
            SELECT 1 FROM fleet_task t
            WHERE t.kind = CAST(:kind AS fleet_task_kind)
              AND t.work_id = j.job_id
              AND t.status IN ('queued', 'claimed'))
    ORDER BY j.updated_at
    """
)


@dataclass(frozen=True)
class StrandedJob:
    job_id: UUID
    run_id: UUID
    workspace_id: str
    subject_type: str
    status: str


async def plan_requeue(conn: AsyncConnection) -> tuple[StrandedJob, ...]:
    """The stranded jobs, oldest first. Reads only."""
    rows = (
        (await conn.execute(_STRANDED, {"kind": FleetTaskKind.ARV2_ACCOUNT_RESEARCH.value}))
        .mappings()
        .all()
    )
    return tuple(
        StrandedJob(
            job_id=row["job_id"],
            run_id=row["run_id"],
            workspace_id=row["workspace_id"],
            subject_type=row["subject_type"],
            status=row["status"],
        )
        for row in rows
    )


async def apply_requeue(conn: AsyncConnection, plan: Sequence[StrandedJob]) -> int:
    """Re-offer each planned job the way the launch offers it; returns how many were offered."""
    offered = 0
    for job in plan:
        offered += await offer_research_job(
            conn, job_id=job.job_id, run_id=job.run_id, workspace_id=job.workspace_id
        )
    return offered


async def _run(*, apply: bool) -> None:
    async with db_lifespan(), transaction() as conn:
        plan = await plan_requeue(conn)
        for job in plan:
            print(f"{job.workspace_id}  {job.subject_type:7}  {job.status:11}  job {job.job_id}")
        if not apply:
            print(f"planned {len(plan)} stranded jobs (dry-run; pass --apply to re-offer)")
            return
        print(f"re-offered {await apply_requeue(conn, plan)} of {len(plan)} stranded jobs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Re-offer the jobs. Without it the plan is printed and nothing is written.",
    )
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    main()
