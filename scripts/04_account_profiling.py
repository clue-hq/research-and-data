"""Run M2 — deep account profiling for one account (profile_account).

Plans the deep account-axis gap fields, fans out aspect workers in parallel, and writes
claims (or leaves fields empty/flagged). Pass --account-id from script 03, or omit it to
seed a fresh demo account first.

    uv run python scripts/04_account_profiling.py --account-id <UUID> --tier high
    uv run python scripts/04_account_profiling.py --tier high      # seeds a demo account

Offline the deep fields resolve through the source waterfall with no live resolver bound,
so workers run but most fields come back empty (an empty, flagged field is a correct
output here). The result still shows the planned gap set, the per-aspect coverage, and
the converge status — i.e. the orchestrator/worker actually ran.
"""

import argparse
import asyncio
from uuid import UUID, uuid4

import clue_obs
from clue_core import ICPCreatedFrom, ICPSpec
from clue_db import db_lifespan, transaction
from clue_research.api.composition import load_research_packs
from clue_research.config import GatewayConfig
from clue_research.gateway import build_gateway
from clue_research.identity import insert_account_entity
from clue_research.profiling import profile_account


async def main(
    client_id: str, icp_key: str, icp_version: int, tier: str, account_id: str | None
) -> None:
    gateway = build_gateway(GatewayConfig(), api_key=None)  # stub
    spec = ICPSpec(
        client_id=client_id,
        icp_key=icp_key,
        created_from=ICPCreatedFrom.SYNTHESIS,
        version=icp_version,
    )

    async with db_lifespan():
        # Pack registration + the (optional) seed must be committed before profile_account,
        # which opens its own sessions.
        async with transaction() as conn:
            await load_research_packs(conn)
            if account_id is None:
                tag = uuid4().hex[:8]  # unique per run so re-runs don't collide on domain
                seeded = await insert_account_entity(
                    conn,
                    canonical_name=f"Acme Robotics {tag}",
                    primary_domain=f"acme-{tag}.example",
                )
                account_id = str(seeded)
                print(f"seeded demo account: {account_id}")

        result = await profile_account(
            account_entity_id=UUID(account_id),
            spec=spec,
            tier=tier,
            tenant_id=client_id,
            gateway=gateway,
        )

    print("\n=== M2 account profiling ===")
    print(f"account_entity_id : {result.account_entity_id}")
    print(f"status            : {result.status}")
    print(f"gap fields planned: {result.gap_field_count}")
    print(f"claims written    : {len(result.claim_refs)}")
    print(f"cost_cents        : {result.cost_cents}")
    if result.dropped_aspects:
        print(f"dropped aspects   : {', '.join(result.dropped_aspects)}")
    for cov in result.aspects:
        print(f"  aspect {cov.aspect}: filled={cov.fields_filled}")


if __name__ == "__main__":
    clue_obs.setup()
    p = argparse.ArgumentParser(description="M2 deep account profiling")
    p.add_argument("--client-id", default="acme")
    p.add_argument("--icp-key", default="default")
    p.add_argument("--icp-version", type=int, default=1)
    p.add_argument("--tier", default="high")
    p.add_argument("--account-id", default=None, help="UUID from script 03 (seeds one if omitted)")
    args = p.parse_args()
    asyncio.run(main(args.client_id, args.icp_key, args.icp_version, args.tier, args.account_id))
