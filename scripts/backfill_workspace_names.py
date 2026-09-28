#!/usr/bin/env python3
"""Give legacy self-serve workspaces the display name their website already implies.

    set -a; source .env; set +a
    uv run python scripts/backfill_workspace_names.py            # plan only, writes nothing
    uv run python scripts/backfill_workspace_names.py --apply    # rename them

A self-serve workspace used to be born named after its own id, so every marketer provisioned
before the display-name work sees ``ws_01J…`` wherever the product says "workspace". The website
they typed at onboarding is still on their ``self_serve_provisioning`` row, and
``canonical_workspace_name`` — the same fold a new workspace is named by — turns it into the name
they should have had all along (``https://www.acme-health.com`` → ``Acme Health``).

Only a workspace **still named as its own id** is touched: a name someone has typed is theirs, and
a workspace that never came through self-serve has no website to be named from. It is idempotent
for the same reason — once renamed, a workspace no longer matches ``name = workspace_id``, so a
second pass plans nothing. A website that names nothing (an IP literal, a dotless host) is dropped
from the plan rather than guessed at.

**Dry run by default.** Without ``--apply`` it prints the plan and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core.normalize import canonical_workspace_name
from clue_db import db_lifespan, transaction
from clue_spine import rename_workspace

#: Every workspace still wearing its own id as a name that has a website to be named from. Ordered
#: oldest first so the printed plan reads in the order the workspaces were provisioned.
_LEGACY_WORKSPACES = text(
    """
    SELECT w.workspace_id, w.name, p.company_website
    FROM workspace w JOIN self_serve_provisioning p USING (workspace_id)
    WHERE w.name = w.workspace_id AND p.company_website IS NOT NULL
    ORDER BY w.created_at
    """
)


@dataclass(frozen=True)
class Rename:
    """One planned rename, carrying the website it was derived from so the plan is auditable."""

    workspace_id: str
    old_name: str
    new_name: str
    website: str


async def plan_backfill(conn: AsyncConnection) -> tuple[Rename, ...]:
    """The renames this backfill would make, in provisioning order. Reads only."""
    rows = (await conn.execute(_LEGACY_WORKSPACES)).mappings().all()
    plan = []
    for row in rows:
        website = row["company_website"]
        new_name = canonical_workspace_name(website)
        if new_name is None:
            # The website names nothing an operator would recognise. Leaving the id in place is
            # honest; inventing a name is not.
            continue
        plan.append(
            Rename(
                workspace_id=row["workspace_id"],
                old_name=row["name"],
                new_name=new_name,
                website=website,
            )
        )
    return tuple(plan)


async def apply_backfill(conn: AsyncConnection, plan: Sequence[Rename]) -> int:
    """Write the planned renames through the spine's own writer; returns how many were renamed."""
    for rename in plan:
        await rename_workspace(conn, rename.workspace_id, rename.new_name)
    return len(plan)


async def _run(*, apply: bool) -> None:
    async with db_lifespan(), transaction() as conn:
        plan = await plan_backfill(conn)
        for rename in plan:
            print(
                f"{rename.workspace_id}  {rename.old_name}  ->  {rename.new_name}   "
                f"({rename.website})"
            )
        if not apply:
            print(f"planned {len(plan)} renames (dry-run; pass --apply to write)")
            return
        print(f"renamed {await apply_backfill(conn, plan)} workspaces")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the renames. Without it the plan is printed and nothing is written.",
    )
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    main()
