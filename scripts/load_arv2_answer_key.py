#!/usr/bin/env python3
"""Load the ARV2 answer keys (Zafran + the ten people) into one database.

    uv run python scripts/load_arv2_answer_key.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue

--database-url is required so this command can never fall through to whatever CLUE_DATABASE_URL
points at (same rule as scripts/backfill_fi2_slice0.py). --dry-run runs the whole load in one
transaction, prints the report and rolls back.

--repair-emails runs no load at all: it supersedes the already-loaded core.work_email claims that
still hold a bare address string with the {address, status, checked_at} value ARV2 D4-b's field
registry declares, taking the verdict from the answer key's own AI Ark verification block. It is
idempotent — a second run finds no bare strings and repairs nothing.

--repair-research-rows also runs no load: it writes the ARV2 arv2_research_run + arv2_research_job
pair a fresh load now writes, for a database loaded back when D1 wrote the old lane's terminal
entity_research_* rows instead (those are left exactly as they are — dead data the Phase-6 PR
drops). Idempotent on the deterministic run and job ids: a second run creates nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from clue_api.arv2.answer_key_loader import (
    EmailRepairReport,
    LoadReport,
    ResearchRowsReport,
    load_answer_key,
    repair_email_claims,
    repair_research_rows,
)
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
        "--repair-emails",
        action="store_true",
        help="Do not load. Supersede the loaded work-email claims that still hold a bare address "
        "string with the verdict-carrying value (idempotent).",
    )
    parser.add_argument(
        "--repair-research-rows",
        action="store_true",
        help="Do not load. Write the ARV2 research run and job for the loaded answer key's Zafran "
        "account if they are absent (idempotent; the legacy rows are left alone).",
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
            storage = FsStorage(Path(args.storage_root))
            report: EmailRepairReport | LoadReport | ResearchRowsReport
            if args.repair_emails:
                report = await repair_email_claims(
                    conn,
                    context_root=Path(args.context_root),
                    settings=Settings(),
                )
            elif args.repair_research_rows:
                report = await repair_research_rows(conn, storage=storage)
            else:
                report = await load_answer_key(
                    conn,
                    storage=storage,
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
    mode = (
        "repair_emails"
        if args.repair_emails
        else "repair_research_rows"
        if args.repair_research_rows
        else "load"
    )
    return {"dry_run": args.dry_run, "mode": mode, **asdict(report)}


def main() -> None:
    print(json.dumps(asyncio.run(_run(_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
