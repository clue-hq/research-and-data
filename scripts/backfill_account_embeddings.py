#!/usr/bin/env python3
"""Backfill name embeddings for accounts that have none (FI-2 slice 0, spec §1.2-H1).

Until the admission/disposition new-entity path embedded, every discovery-created ``account_entity``
was minted **without** an ``account_entity_embedding`` row. Such an account is invisible to the
resolver's pgvector-ANN arm, so a later name-only encounter of the same company scores with the
cosine arm zeroed, drops below the 0.70 review floor, and silently mints a duplicate. The code path
is fixed going forward; this is the one-shot repair for the rows already at rest.

Idempotent and safe to re-run: only accounts *missing* an embedding are selected, so a re-embed
under a new model version stays an explicit, separate act. Merged losers are skipped (a redirect,
never a candidate). Prints the counts as JSON.

    uv run python scripts/backfill_account_embeddings.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:5432/clue

Add ``--workspace-id`` to repair one tenant, ``--dry-run`` to count without writing.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from clue_db import db_lifespan, transaction
from clue_research.identity import backfill_account_embeddings


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Embed every live account_entity that has no account_entity_embedding row "
            "(FI-2 §1.2-H1 one-shot repair). Idempotent."
        )
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help=(
            "SQLAlchemy async Postgres URL for the database to repair. Required — this command "
            "writes, so it must never fall through to whatever CLUE_DATABASE_URL happens to point "
            "at (same rule as scripts/08_seed_discovery_fixture.py)."
        ),
    )
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Repair only this workspace's accounts (default: every workspace).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows embedded per query batch (default: 500).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many accounts are missing an embedding and write nothing.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    # No SQL here on purpose: the dry run is the *same* function under ``dry_run=True``, so the
    # preview and the real pass share one predicate and the preview cannot under-report.
    async with db_lifespan(args.database_url), transaction() as conn:
        report = await backfill_account_embeddings(
            conn,
            workspace_id=args.workspace_id,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        return {"dry_run": args.dry_run, **report.model_dump()}


def main() -> None:
    args = _args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
