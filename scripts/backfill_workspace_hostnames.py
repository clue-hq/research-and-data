#!/usr/bin/env python3
"""Backfill system hostnames for workspaces created before the registry existed (spec §4.1, §11).

    uv run python scripts/backfill_workspace_hostnames.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:5432/clue \
        [--suffix pages.localhost] [--dry-run]

The suffix defaults to CLUE_PAGES_SYSTEM_SUFFIX. Idempotent: a workspace that already has a system
row is skipped. Prints the counts as JSON and warns when existing rows sit under another suffix.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from clue_config import Settings
from clue_db import db_lifespan, transaction
from clue_spine.hostnames import backfill_system_hostnames


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Allocate missing <label>.<suffix> system hostnames."
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="Async Postgres URL to repair (required; never falls through to CLUE_DATABASE_URL).",
    )
    parser.add_argument(
        "--suffix", default=None, help="System suffix (default: CLUE_PAGES_SYSTEM_SUFFIX)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, int]:
    suffix = args.suffix or Settings().pages_system_suffix
    # One `with`, entered left to right: the engine is live before ``transaction()`` is called.
    async with db_lifespan(args.database_url), transaction() as conn:
        return await backfill_system_hostnames(conn, suffix=suffix, dry_run=args.dry_run)


def main() -> None:
    args = _args()
    counts = asyncio.run(_run(args))
    print(json.dumps(counts))
    if counts["off_suffix"]:
        print(
            f"WARNING: {counts['off_suffix']} system hostname(s) do not end in the configured "
            "suffix (a copied database under a different CLUE_PAGES_SYSTEM_SUFFIX?)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
