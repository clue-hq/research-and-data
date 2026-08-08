#!/usr/bin/env python3
"""Backfill the FI-2 project lens on a pre-slice-0 database (spec §2/§3 backfill paragraphs).

Slice 0 taught every live account-entry and run-minting site to record ``project_account``
membership and ``run_lineage`` attribution. Rows already at rest predate those writers, so on an
existing dev database a project's account list is empty and its claim lens resolves no runs. This
one-shot repair reconstructs both spines from the durable execution records that do exist —
discovery candidate links, research directives, project runs, M8D research runs, and M7 account
runs. Dev-data-only by intent (the B3 synthetic-data ruling); no migration.

Idempotent and safe to re-run: rows already present are skipped, so a live writer's row is never
rewritten and a second pass reports zero written. Prints the counts as JSON.

    uv run python scripts/backfill_fi2_slice0.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:5432/clue

Add ``--workspace-id`` to repair one tenant, ``--dry-run`` to preview without writing.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from clue_db import db_lifespan, transaction
from clue_research.project_lens_backfill import backfill_project_lens


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct project_account membership and run_lineage attribution from the durable "
            "execution records (FI-2 slice 0 one-shot repair). Idempotent."
        )
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help=(
            "SQLAlchemy async Postgres URL for the database to repair. Required — this command "
            "writes, so it must never fall through to whatever CLUE_DATABASE_URL happens to point "
            "at (same rule as scripts/backfill_account_embeddings.py)."
        ),
    )
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Repair only this workspace (default: every workspace).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what a real pass would write, and write nothing.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    # No SQL here on purpose: the dry run is the *same* function under ``dry_run=True``, so the
    # preview and the real pass share one plan and the preview cannot under-report. One
    # transaction, so the whole repair commits or rolls back as a unit.
    async with db_lifespan(args.database_url), transaction() as conn:
        report = await backfill_project_lens(
            conn,
            workspace_id=args.workspace_id,
            dry_run=args.dry_run,
        )
        return {"dry_run": args.dry_run, **report.model_dump()}


def main() -> None:
    args = _args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
