#!/usr/bin/env python3
"""Give an existing Clue user one more workspace they own, then print the link that onboards it.

    python scripts/provision_additional_workspace.py --email shank@cluehq.ai \
        --website https://acme.com --operator-email you@cluehq.ai [--company-name "Acme"] \
        [--app-origin https://app.cluehq.ai] [--apply]

**Dry run by default.** Without ``--apply`` it makes the writes inside a savepoint, prints what it
would create, and rolls back. With ``--apply`` it commits and writes a ``workspace_operation``
audit row naming ``--operator-email`` (an existing Clue user).

The same function serves ``POST /ops/v1/workspaces`` (``clue_api.workspace_ops.add_workspace``).
It starts nothing and spends nothing: onboarding starts from the printed link (signed in as the
owner), from ``scripts/start_workspace_onboarding.py``, or from the operator route. Runbook:
``scripts/workspace_onboarding_operations.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from clue_api.workspace_ops.add_workspace import add_workspace, operator_setup_url
from clue_api.workspace_ops.operators import OpsRefused, resolve_operator
from clue_config import Settings
from clue_db import db_lifespan, transaction

__all__ = ["main", "operator_setup_url"]


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    try:
        async with db_lifespan(), transaction() as conn:
            operator = await resolve_operator(conn, args.operator_email)
            created = await add_workspace(
                conn,
                email=args.email,
                website=args.website,
                company_name=args.company_name,
                operator=operator,
                app_origin=args.app_origin or settings.app_origin,
                pages_system_suffix=settings.pages_system_suffix,
                apply=args.apply,
            )
    except OpsRefused as refused:
        print(f"REFUSED {refused.code}: {refused.message}")
        return 1
    print(f"user       {created['user_id']} ({created['email']})")
    print(f"workspace  {created['workspace_id']}  {created['workspace_name']!r}")
    print(f"brand      {created['brand_id']}")
    print(f"membership {created['membership_id']}  owner, active")
    print(f"onboarding {created['onboarding_link']}")
    if args.apply:
        print("COMMITTED. Start onboarding next (see the runbook).")
    else:
        print("DRY RUN: rolled back, nothing written (pass --apply to commit)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--website", required=True)
    parser.add_argument("--operator-email", required=True)
    parser.add_argument("--company-name")
    parser.add_argument("--app-origin", help="defaults to the app_origin setting")
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
