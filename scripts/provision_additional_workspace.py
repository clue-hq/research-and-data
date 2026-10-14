#!/usr/bin/env python3
"""Give an existing Clue user one more workspace they own, then print the link that onboards it.

    python scripts/provision_additional_workspace.py --email shank@cluehq.ai \
        --website https://acme.com [--company-name "Acme"] [--app-origin https://app.cluehq.ai] \
        [--apply]

**Dry run by default.** Without ``--apply`` it creates everything inside a transaction, prints
what it would create, and rolls back. With ``--apply`` it commits.

Run it where the app settings point at the target database (a production worker container has
them). It creates the workspace, its one brand and an owner membership
(``clue_auth.provision_additional_workspace``); it starts nothing and spends nothing. Onboarding
starts when the user, signed in, opens the printed link: the setting-up screen selects the new
workspace (membership re-checked server-side) and starts the normal onboarding run, which also
starts brand-kit ingestion on the platform API.
"""

from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlencode

from clue_auth import provision_additional_workspace
from clue_config import Settings
from clue_db import db_lifespan, transaction


class _DryRun(Exception):
    """Raised inside the transaction so a dry run rolls everything back."""


def operator_setup_url(app_origin: str, workspace_id: str, website: str) -> str:
    query = urlencode({"workspace": workspace_id, "website": website})
    return f"{app_origin.rstrip('/')}/onboarding/setting-up?{query}"


async def _run(
    *, email: str, website: str, company_name: str | None, app_origin: str | None, apply: bool
) -> None:
    settings = Settings()
    origin = app_origin or settings.app_origin
    try:
        async with db_lifespan(), transaction() as conn:
            result = await provision_additional_workspace(
                conn,
                email=email,
                company_website=website,
                company_name=company_name,
                pages_system_suffix=settings.pages_system_suffix,
            )
            link = operator_setup_url(origin, result.workspace.workspace_id, result.company_website)
            print(f"user       {result.user.user_id} ({email.strip().casefold()})")
            print(f"workspace  {result.workspace.workspace_id}  {result.workspace.name!r}")
            print(f"brand      {result.brand.brand_id}")
            print(f"membership {result.membership.membership_id}  owner, active")
            print(f"onboarding {link}")
            if not apply:
                raise _DryRun
    except _DryRun:
        print("DRY RUN: rolled back, nothing written (pass --apply to commit)")
        return
    print("COMMITTED. Sign in as the user and open the onboarding link above.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--website", required=True)
    parser.add_argument("--company-name")
    parser.add_argument("--app-origin", help="defaults to the app_origin setting")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        _run(
            email=args.email,
            website=args.website,
            company_name=args.company_name,
            app_origin=args.app_origin,
            apply=args.apply,
        )
    )


if __name__ == "__main__":
    main()
