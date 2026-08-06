#!/usr/bin/env python3
"""Materialize D3-terminal Exa artifacts into D4 accounts and claims, without provider I/O."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from clue_api.exa_websets_materialization import ExaWebsetsD4Materializer
from clue_api.trial.discovery_fixture import WORKSPACE_ID
from clue_core import DiscoveryBatchId
from clue_db import db_lifespan, transaction
from clue_research.durable import get_discovery_batch
from clue_storage import FsStorage


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run or replay D4 over an existing D3-terminal Exa discovery batch. This command "
            "constructs no Exa client, reads no API key, and cannot make a provider request."
        )
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--batch-id", type=UUID, required=True)
    parser.add_argument("--workspace-id", default=WORKSPACE_ID)
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(".context/discovery-fixtures/insight-health-aura/artifacts"),
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    batch_id = DiscoveryBatchId(args.batch_id)
    result = await ExaWebsetsD4Materializer(storage=FsStorage(args.storage_root)).materialize(
        workspace_id=args.workspace_id,
        batch_id=batch_id,
    )
    async with transaction() as conn:
        batch = await get_discovery_batch(
            conn,
            workspace_id=args.workspace_id,
            batch_id=batch_id,
        )
        if batch is None:
            raise RuntimeError(f"D4 batch {batch_id} disappeared")
        admissions = Counter(
            str(value)
            for value in (
                await conn.execute(
                    text(
                        "SELECT admission_status::text FROM discovery_candidate_link "
                        "WHERE workspace_id = :workspace_id AND batch_id = :batch_id"
                    ),
                    {"workspace_id": args.workspace_id, "batch_id": batch_id},
                )
            ).scalars()
        )
        resolutions = Counter(
            str(value)
            for value in (
                await conn.execute(
                    text(
                        "SELECT state::text FROM discovery_field_resolution "
                        "WHERE workspace_id = :workspace_id AND batch_id = :batch_id"
                    ),
                    {"workspace_id": args.workspace_id, "batch_id": batch_id},
                )
            ).scalars()
        )
        account_count = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(DISTINCT survivor_entity_id) "
                        "FROM discovery_candidate_link "
                        "WHERE workspace_id = :workspace_id AND batch_id = :batch_id "
                        "AND survivor_entity_id IS NOT NULL"
                    ),
                    {"workspace_id": args.workspace_id, "batch_id": batch_id},
                )
            ).scalar_one()
        )
        batch_claim_count = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(DISTINCT claim_id) FROM discovery_field_claim field_claim "
                        "JOIN discovery_field_resolution resolution "
                        "ON resolution.id = field_claim.resolution_id "
                        "AND resolution.workspace_id = field_claim.workspace_id "
                        "WHERE resolution.workspace_id = :workspace_id "
                        "AND resolution.batch_id = :batch_id"
                    ),
                    {"workspace_id": args.workspace_id, "batch_id": batch_id},
                )
            ).scalar_one()
        )
    return {
        **result.model_dump(mode="json"),
        "durable_batch_state": batch.state.value,
        "durable_account_count": account_count,
        "durable_field_claim_count": batch_claim_count,
        "admission_summary": dict(sorted(admissions.items())),
        "field_resolution_summary": dict(sorted(resolutions.items())),
        "provider_calls_this_process": 0,
    }


async def _entry(args: argparse.Namespace) -> dict[str, object]:
    async with db_lifespan(args.database_url):
        return await _run(args)


def main() -> None:
    print(json.dumps(asyncio.run(_entry(_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
