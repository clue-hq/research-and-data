#!/usr/bin/env python3
"""Seed the Insight Health/Aura Stage-0 handoff into an isolated migrated database."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from clue_api.trial.discovery_fixture import (
    load_firecrawl_search_pages,
    seed_insight_health_discovery_fixture,
)
from clue_db import db_lifespan, transaction
from clue_storage import FsStorage


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed a replay-safe Insight Health/Aura Stage-0 fixture and stop the durable project "
            "run at account discovery. The target database must already exist and be migrated."
        )
    )
    parser.add_argument(
        "--aura-search-json",
        type=Path,
        default=Path(".firecrawl/search-insight-health-aura.json"),
        help=(
            "Firecrawl search --scrape JSON containing the home, Ambient, and Aura Anywhere pages."
        ),
    )
    parser.add_argument(
        "--neurosurgery-search-json",
        type=Path,
        default=Path(".firecrawl/search-insight-health-aura-neurosurgery.json"),
        help="Firecrawl search --scrape JSON containing the neurosurgery case-study page.",
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help=(
            "SQLAlchemy async Postgres URL for a dedicated, already-created and migrated fixture "
            "database. Required so the command cannot silently seed the default/shared database."
        ),
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(".context/discovery-fixtures/insight-health-aura/artifacts"),
        help="Local content-addressed artifact root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".context/discovery-fixtures/insight-health-aura/fixture.json"),
        help="Non-authoritative convenience copy of the persisted fixture references.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    pages = load_firecrawl_search_pages((args.aura_search_json, args.neurosurgery_search_json))
    storage = FsStorage(args.storage_root)
    async with db_lifespan(args.database_url), transaction() as conn:
        result = await seed_insight_health_discovery_fixture(
            conn,
            pages=pages,
            storage=storage,
        )
    return result.model_dump(mode="json")


def main() -> None:
    args = _args()
    result = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
