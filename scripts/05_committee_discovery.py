"""Run M3 — buying-committee discovery for one account (discover_committee).

Enumerates candidate people from a people-source, existence-gates each through identity
resolution, infers + plausibility-gates a committee role, and writes discovery/role/persona
claims. Pass --account-id from script 03, or omit it to seed a fresh demo account.

    uv run python scripts/05_committee_discovery.py --account-id <UUID> --tier high
    uv run python scripts/05_committee_discovery.py --tier high     # seeds a demo account

discover_committee requires at least one `sources` provider (Apollo/ZoomInfo in prod). No
such provider runs offline, so this script supplies a small inline demo source with a couple
of canned candidates — the rest of the pipeline (existence gate, role inference via the stub
gateway, claim writes) is the real thing.
"""

import argparse
import asyncio
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID, uuid4

import clue_obs
from clue_config import GatewayConfig
from clue_core import AccountEntity, new_run_id
from clue_db import db_lifespan, transaction
from clue_gateway import build_gateway
from clue_research.api.composition import load_research_packs
from clue_research.identity import insert_account_entity
from clue_research.profiling import discover_committee
from clue_research.profiling.committee.sources import CommitteePersonCandidate


class DemoPeopleSource:
    """A stand-in for a real people source (Apollo/ZoomInfo): returns canned candidates."""

    source_key = "apollo_people"
    tier = 2

    def __init__(self, candidates: list[CommitteePersonCandidate]) -> None:
        self._candidates = candidates

    async def find_candidates(
        self, account: AccountEntity, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]:
        return self._candidates[:limit]


_DEMO_CANDIDATES = [
    CommitteePersonCandidate(
        source_key="apollo_people",
        full_name="Jane Okafor",
        title="Chief Financial Officer",
        linkedin_url="https://linkedin.com/in/jane-okafor",
        source_url="https://acme.example/leadership",
        matched_signal="leadership page",
        discovery_confidence=0.8,
        cost_cents=Decimal(0),
    ),
    CommitteePersonCandidate(
        source_key="apollo_people",
        full_name="Raj Mehta",
        title="VP of Engineering",
        linkedin_url="https://linkedin.com/in/raj-mehta",
        source_url="https://acme.example/leadership",
        matched_signal="leadership page",
        discovery_confidence=0.8,
        cost_cents=Decimal(0),
    ),
]


async def main(workspace_id: str, tier: str, account_id: str | None) -> None:
    gateway = build_gateway(GatewayConfig(), api_key=None)  # stub role inference
    source = DemoPeopleSource(_DEMO_CANDIDATES)

    async with db_lifespan(), transaction() as conn:
        await load_research_packs(conn)
        if account_id is None:
            tag = uuid4().hex[:8]  # unique per run so re-runs don't collide on domain
            seeded = await insert_account_entity(
                conn, canonical_name=f"Acme Robotics {tag}", primary_domain=f"acme-{tag}.example"
            )
            account_id = str(seeded)
            print(f"seeded demo account: {account_id}")

        result = await discover_committee(
            conn,
            account_entity_id=UUID(account_id),
            run_id=new_run_id(),
            workspace_id=workspace_id,
            sources=[source],
            gateway=gateway,
            role_model="openai/gpt-4o-mini",  # model id is config; the stub ignores it
        )

    print("\n=== M3 committee discovery ===")
    print(f"account_entity_id : {result.account_entity_id}")
    print(f"admitted          : {result.admitted}")
    print(f"needs_review      : {result.needs_review}")
    print(f"dropped           : {result.dropped}")
    print(f"cost_cents        : {result.cost_cents}")
    for member in result.members:
        print(f"  {member.persona:16} contact={member.contact_entity_id}")
    if result.members:
        print(
            "\nNext: scripts/06_contact_profiling.py "
            f"--workspace-id {workspace_id} --account-id {result.account_entity_id} "
            f"--contact-id {result.members[0].contact_entity_id} --tier {tier}"
        )


if __name__ == "__main__":
    clue_obs.setup()
    p = argparse.ArgumentParser(description="M3 committee discovery")
    p.add_argument("--workspace-id", default="acme")
    p.add_argument("--tier", default="high")
    p.add_argument("--account-id", default=None, help="UUID from script 03 (seeds one if omitted)")
    args = p.parse_args()
    asyncio.run(main(args.workspace_id, args.tier, args.account_id))
