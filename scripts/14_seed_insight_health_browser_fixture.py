#!/usr/bin/env python3
"""Provision an authenticated Insight Health browser user at the Stage-0 boundary."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from clue_api.trial.browser_fixture import (
    seed_insight_health_browser_fixture,
    seed_insight_health_browser_onboarding_result,
)
from clue_db import db_lifespan, transaction
from clue_storage import FsStorage


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy async URL for the migrated browser-acceptance database.",
    )
    parser.add_argument(
        "--provider-subject",
        required=True,
        help="The verified Clerk user id from the browser session.",
    )
    parser.add_argument(
        "--display-name",
        default="Insight Health GTM Lead",
        help="Internal display name used only when this subject is first provisioned.",
    )
    parser.add_argument(
        "--project-id",
        help=(
            "Optional existing Home project to bind to the Insight Health client/Aura product "
            "and materialize the recorded official-site Client KB onboarding result."
        ),
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(".context/lane-f-e2e/artifacts"),
        help="Filesystem artifact root used by the browser-acceptance API.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with db_lifespan(args.database_url), transaction() as conn:
        if args.project_id:
            result = await seed_insight_health_browser_onboarding_result(
                conn,
                provider_subject=args.provider_subject,
                display_name=args.display_name,
                project_id=args.project_id,
                storage=FsStorage(args.storage_root),
            )
        else:
            result = await seed_insight_health_browser_fixture(
                conn,
                provider_subject=args.provider_subject,
                display_name=args.display_name,
            )
    return result.model_dump(mode="json")


def main() -> None:
    print(json.dumps(asyncio.run(_run(_args())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
