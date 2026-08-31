#!/usr/bin/env python3
"""Inspect and safely recover one C8 official-site crawl without reading content bodies.

Every command requires an explicit database URL, workspace, and crawl run. ``inspect`` is read
only. Mutations additionally require exact-id confirmation; neither mutation calls a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from clue_db import db_lifespan, transaction
from clue_research.official_site import PostgresOfficialSiteOperations


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        required=True,
        help="Explicit SQLAlchemy async PostgreSQL URL; never inferred for operator actions.",
    )
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--crawl-run-id", required=True, type=UUID)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect", help="Print body-free row/event/recovery truth.")

    reclaim = commands.add_parser(
        "reclaim-expired",
        help="Requeue pre-dispatch leases and route ambiguous dispatches to reconciliation.",
    )
    reclaim.add_argument(
        "--confirm-crawl-run-id",
        required=True,
        type=UUID,
        help="Must exactly equal --crawl-run-id.",
    )

    quarantine = commands.add_parser(
        "quarantine-spend-unknown",
        help="Explicitly quarantine one unleased ambiguous attempt; never retries the provider.",
    )
    quarantine.add_argument("--fetch-attempt-id", required=True, type=UUID)
    quarantine.add_argument("--expected-lease-generation", required=True, type=int)
    quarantine.add_argument("--confirm-fetch-attempt-id", required=True, type=UUID)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "reclaim-expired" and args.confirm_crawl_run_id != args.crawl_run_id:
        raise ValueError("--confirm-crawl-run-id must exactly match --crawl-run-id")
    if args.command == "quarantine-spend-unknown" and (
        args.confirm_fetch_attempt_id != args.fetch_attempt_id
    ):
        raise ValueError("--confirm-fetch-attempt-id must exactly match --fetch-attempt-id")
    async with db_lifespan(args.database_url):
        operations = PostgresOfficialSiteOperations(conn_factory=transaction)
        if args.command == "reclaim-expired":
            result = await operations.reclaim_expired_leases(
                workspace_id=args.workspace_id,
                crawl_run_id=args.crawl_run_id,
            )
            action: dict[str, object] = {
                "command": args.command,
                **result.model_dump(mode="json"),
            }
        elif args.command == "quarantine-spend-unknown":
            changed = await operations.quarantine_spend_unknown(
                workspace_id=args.workspace_id,
                crawl_run_id=args.crawl_run_id,
                fetch_attempt_id=args.fetch_attempt_id,
                expected_lease_generation=args.expected_lease_generation,
            )
            action = {
                "command": args.command,
                "fetch_attempt_id": str(args.fetch_attempt_id),
                "changed": changed,
                "provider_called": False,
            }
        else:
            action = {"command": "inspect"}
        report = await operations.read_report(
            workspace_id=args.workspace_id,
            crawl_run_id=args.crawl_run_id,
        )
        return {
            "action": action,
            "progress": report.progress.model_dump(mode="json"),
            "recovery_items": [item.model_dump(mode="json") for item in report.recovery_items],
            "privacy": {
                "contains_page_bodies": False,
                "contains_urls": False,
                "contains_provider_receipts": False,
            },
        }


def main() -> None:
    print(json.dumps(asyncio.run(_run(_args())), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
