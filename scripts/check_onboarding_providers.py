#!/usr/bin/env python3
"""Check the providers onboarding needs, for one workspace (spec 2026-10-25 §3.3).

    python scripts/check_onboarding_providers.py --workspace ws_…

Prints one line per provider; exits 1 when a required one would block onboarding. Free apart from
one ~half-cent Exa search, ledgered to the workspace. From the worker VM the ``design_api`` line
reads ``unreachable`` by design (the design API is on Railway's private network). Same function
as ``GET /ops/v1/workspaces/{id}/preflight``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from clue_api.workspace_ops.preflight import build_preflight
from clue_config import Secrets, Settings
from clue_db import db_lifespan, transaction


async def _run(args: argparse.Namespace) -> int:
    preflight = build_preflight(Settings(), Secrets(), transaction)
    async with db_lifespan():
        report = await preflight(args.workspace)
    for result in report.results:
        flag = "BLOCKS" if result in report.blocking else "  ok  "
        print(f"{flag} {result.provider:<20} {result.outcome:<15} {result.detail}")
    return 1 if report.blocking else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workspace", required=True)
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
