"""Bring accounts into the store, capped (Scenario B — import + identity resolution).

Resolves up to --max-accounts companies into account_entity rows and prints their ids,
so the profiling scripts (04/05/06) have real accounts to work on.

    uv run python scripts/03_find_accounts.py --client-id acme --max-accounts 5
    uv run python scripts/03_find_accounts.py --max-accounts 2 \
        --account "Globex:globex.example" --account "Initech:initech.example"

With no --account, a built-in demo list is used (with a unique per-run suffix so repeated
runs always create fresh accounts). An explicit --account already present is skipped, not
re-inserted. Live web discovery (Scenario A) is `discover()` in
clue_research/discovery_scoring/discovery/orchestrator.py — it needs provider keys and
discovery channels, so it can't produce candidates offline; this import path is the
offline-runnable way to populate accounts. The cap is applied to the company list.
"""

import argparse
import asyncio
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from clue_research.db import db_lifespan, transaction
from clue_research.identity import insert_account_entity

_DEFAULT_NAMES = ["Acme Robotics", "Globex", "Initech", "Umbrella Health", "Stark Industries"]


async def main(client_id: str, max_accounts: int, companies: list[tuple[str, str | None]]) -> None:
    capped = companies[:max_accounts]
    created: list[tuple[str, str, str | None]] = []
    skipped: list[tuple[str, str | None]] = []

    async with db_lifespan():
        for name, domain in capped:
            try:
                # Each import in its own transaction so a duplicate skips just that row.
                async with transaction() as conn:
                    account_id = await insert_account_entity(
                        conn, canonical_name=name, primary_domain=domain
                    )
                created.append((str(account_id), name, domain))
            except IntegrityError:
                skipped.append((name, domain))

    print(f"\n=== accounts resolved (cap={max_accounts}, tenant={client_id}) ===")
    for account_id, name, domain in created:
        print(f"  {account_id}  {name} ({domain})")
    for name, domain in skipped:
        print(f"  (already present, skipped) {name} ({domain})")
    if created:
        print(
            "\nNext: scripts/04_account_profiling.py "
            f"--client-id {client_id} --account-id {created[0][0]} --tier high"
        )


def _parse_company(raw: str) -> tuple[str, str | None]:
    name, _, domain = raw.partition(":")
    return name.strip(), (domain.strip() or None)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Resolve a capped list of accounts into the store")
    p.add_argument("--client-id", default="acme")
    p.add_argument("--max-accounts", type=int, default=5)
    p.add_argument(
        "--account",
        action="append",
        default=[],
        metavar="NAME:DOMAIN",
        help='repeatable, e.g. --account "Globex:globex.example"',
    )
    args = p.parse_args()
    if args.account:
        companies = [_parse_company(a) for a in args.account]
    else:
        # Built-in demo list with a unique per-run suffix so re-runs don't collide on domain.
        tag = uuid4().hex[:6]
        companies = [
            (f"{name} {tag}", f"{name.lower().replace(' ', '-')}-{tag}.example")
            for name in _DEFAULT_NAMES
        ]
    asyncio.run(main(args.client_id, args.max_accounts, companies))
