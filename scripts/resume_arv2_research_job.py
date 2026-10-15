#!/usr/bin/env python3
"""List stuck ARV2 research jobs, and resume one (spec 2026-10-14 §3.6).

    set -a; source .env; set +a
    uv run python scripts/resume_arv2_research_job.py                         # list every workspace
    uv run python scripts/resume_arv2_research_job.py --workspace ws_...      # list one workspace
    uv run python scripts/resume_arv2_research_job.py --job <id> --reason "deadlock fixed"
    uv run python scripts/resume_arv2_research_job.py --job <id> --reason "..." \\
        --top-up-tool-calls 50 --apply

**Dry run by default.** Without ``--apply`` it prints what it would do and writes nothing. Add
``--restart-fresh`` to give the job a new conversation instead of continuing its saved one. In
production, run it from a worker container, which carries the database settings.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2.job_resume import (
    ResumeRefused,
    StuckJob,
    TopUp,
    list_stuck_jobs,
    resume_research_job,
)
from clue_db import ConnFactory, db_lifespan, transaction


class _DryRun(Exception):
    """Raised inside the transaction so a planned resume rolls back."""


def _line(job: StuckJob) -> str:
    who = job.person_name or job.account_name or str(job.account_id)
    can = "resumable" if job.resumable else f"not resumable ({job.refusal})"
    return (
        f"{job.workspace_id}  {job.state:7}  {job.subject_type:7}  {who}  "
        f"{job.failure_code or '-'}  rounds {job.rounds}  ${job.cost_usd}  "
        f"job {job.job_id}  {can}"
    )


async def run(
    *,
    connect: ConnFactory,
    workspace_id: str | None,
    job_id: UUID | None,
    reason: str,
    top_up: TopUp,
    restart_fresh: bool,
    apply: bool,
    actor: str,
) -> list[str]:
    lines: list[str] = []
    try:
        async with connect() as conn:
            if job_id is None:
                jobs = await list_stuck_jobs(conn, workspace_id=workspace_id)
                lines.extend(_line(job) for job in jobs)
                lines.append(f"{len(jobs)} stuck jobs")
                return lines
            owner = (
                await conn.execute(
                    text("SELECT workspace_id FROM arv2_research_job WHERE job_id=:job"),
                    {"job": job_id},
                )
            ).scalar_one_or_none()
            try:
                result = await resume_research_job(
                    conn,
                    workspace_id=owner or "",
                    job_id=job_id,
                    actor=actor,
                    reason=reason,
                    top_up=top_up,
                    restart_fresh=restart_fresh,
                )
            except ResumeRefused as refused:
                return [f"refused: {refused.code}: {refused.message}"]
            lines.append(
                f"resumed job {job_id} in {owner}: attempt {result.attempt}, "
                f"restarted {result.restarted}, top-up {result.top_up_applied}"
            )
            if not apply:
                raise _DryRun
    except _DryRun:
        lines.append("dry run: nothing written; pass --apply to resume")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="List only this workspace's stuck jobs.")
    parser.add_argument("--job", type=UUID, help="The job to resume.")
    parser.add_argument("--reason", default="", help="Why the job is being resumed (required).")
    parser.add_argument("--restart-fresh", action="store_true")
    parser.add_argument("--top-up-model-calls", type=int, default=0)
    parser.add_argument("--top-up-tool-calls", type=int, default=0)
    parser.add_argument("--top-up-delegations", type=int, default=0)
    parser.add_argument("--top-up-runtime-minutes", type=int, default=0)
    parser.add_argument("--apply", action="store_true", help="Write. Without it, nothing is.")
    args = parser.parse_args()
    top_up = TopUp(
        model_calls=args.top_up_model_calls,
        tool_calls=args.top_up_tool_calls,
        delegations=args.top_up_delegations,
        runtime_minutes=args.top_up_runtime_minutes,
    )

    async def go() -> None:
        async with db_lifespan():
            for line in await run(
                connect=transaction,
                workspace_id=args.workspace,
                job_id=args.job,
                reason=args.reason,
                top_up=top_up,
                restart_fresh=args.restart_fresh,
                apply=args.apply,
                actor=f"operator:{getpass.getuser()}",
            ):
                print(line)

    asyncio.run(go())


if __name__ == "__main__":
    main()
