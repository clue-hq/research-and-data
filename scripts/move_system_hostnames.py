#!/usr/bin/env python3
"""Move every system hostname to the published pages' own domain (Wave 2 Contract 9).

    uv run python scripts/move_system_hostnames.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:5432/clue \
        --to-suffix <the new CLUE_PAGES_SYSTEM_SUFFIX> [--from-suffix pages.cluehq.ai] [--apply]

A DRY RUN unless --apply: it prints how many rows would move, the first five moves and any
collisions, and writes nothing. With --apply it rewrites `<label>.<from>` to `<label>.<to>` for
every system row in one transaction, or refuses (exit 1) when a new hostname is already taken.
Run it after the new domain's DNS, certificate and edge redirect are live
(docs/specs/pages-hosting-runbook.md §8).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from clue_db import db_lifespan, transaction
from clue_spine.hostnames import move_system_hostnames


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite <label>.<from> system hostnames to <label>.<to>."
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="Async Postgres URL (required; never falls through to CLUE_DATABASE_URL).",
    )
    parser.add_argument(
        "--to-suffix",
        required=True,
        help="The new system suffix (the published pages' own domain).",
    )
    parser.add_argument(
        "--from-suffix",
        default="pages.cluehq.ai",
        help="The suffix rows end in today (default: pages.cluehq.ai).",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write the move; without it the script only reports."
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with db_lifespan(args.database_url), transaction() as conn:
        return await move_system_hostnames(
            conn, from_suffix=args.from_suffix, to_suffix=args.to_suffix, apply=args.apply
        )


def main() -> None:
    args = _args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2))
    if result["collisions"]:
        print(
            f"REFUSED: {len(result['collisions'])} new hostname(s) are already taken; "
            "nothing moved.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.apply:
        print("dry run: nothing written (pass --apply to move)", file=sys.stderr)


if __name__ == "__main__":
    main()
