#!/usr/bin/env python3
"""Load the ARV2 answer keys (Zafran + the ten people) into one database.

    uv run python scripts/load_arv2_answer_key.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue

--database-url is required so this command can never fall through to whatever CLUE_DATABASE_URL
points at (same rule as scripts/backfill_fi2_slice0.py). --dry-run runs the whole load in one
transaction, prints the report and rolls back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from clue_api.arv2.answer_key_loader import load_answer_key
from clue_config import Settings
from clue_db import db_lifespan
from clue_storage.fs import FsStorage


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy async Postgres URL for the database to load. Required — this command "
        "writes, so it must never fall through to CLUE_DATABASE_URL.",
    )
    parser.add_argument(
        "--context-root",
        default=".context",
        help="Where the two answer-key directories live (default: .context).",
    )
    parser.add_argument(
        "--storage-root",
        default=".artifacts/answer-key",
        help="Where the transcript blobs are written (default: .artifacts/answer-key).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the whole load in one transaction, print the report, and roll it back.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with db_lifespan(args.database_url) as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            report = await load_answer_key(
                conn,
                storage=FsStorage(Path(args.storage_root)),
                context_root=Path(args.context_root),
                settings=Settings(),
            )
            if args.dry_run:
                await trans.rollback()
            else:
                await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
        finally:
            await conn.close()
    return {"dry_run": args.dry_run, **asdict(report)}


def main() -> None:
    print(json.dumps(asyncio.run(_run(_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
