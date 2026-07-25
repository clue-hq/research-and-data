"""Run Stage 0 — client onboarding / reverse-profiling (M5.1).

Takes a client (worst case: just a name + website) and builds the versioned Client
Knowledge Base, then prints the client_entity_id + kb_version that the ICP-synthesis
script (02) needs.

    uv run python scripts/01_stage0_onboarding.py \
        --name "Acme Robotics" --website "https://acme.example" --workspace-id acme

Offline (no CLUE_FIRECRAWL_API_KEY) the web waterfall has no live source, so few/no
client.* fields fill — but the client entity + KB version marker are still written, which
is all the next stage needs. Set the provider keys for real field fills.
"""

import argparse
import asyncio
from uuid import uuid4

from script_support import ensure_script_workspace

import clue_obs
from clue_api.composition import load_research_packs
from clue_db import db_lifespan, transaction
from clue_research.stage0 import ClientInput, reverse_profile


async def main(name: str, website: str, workspace_id: str) -> None:
    async with db_lifespan(), transaction() as conn:
        await ensure_script_workspace(conn, workspace_id)
        await load_research_packs(conn)  # register field packs (idempotent)
        result = await reverse_profile(
            conn,
            ClientInput(name=name, website=website),
            workspace_id=workspace_id,
        )

    print("\n=== Stage 0: client knowledge base ===")
    print(f"client_entity_id : {result.ref.client_entity_id}")
    print(f"kb_version       : {result.ref.client_kb_version}")
    print(f"fields_resolved  : {result.fields_resolved}")
    print(f"filled fields    : {len(result.coverage.filled_fields)}")
    print(f"empty fields     : {len(result.coverage.empty_fields)}")
    print(f"cost_cents       : {result.cost_cents}")
    print(
        "\nNext: scripts/02_icp_synthesis.py "
        f"--workspace-id {workspace_id} --client-entity-id {result.ref.client_entity_id} "
        f"--kb-version {result.ref.client_kb_version}"
    )


if __name__ == "__main__":
    clue_obs.setup()
    # Demo defaults carry a per-invocation tag (like scripts 04-06) so seeded rows never collide
    # with the test suite's fixed-name fixtures on a shared DB — the chain still works because
    # every `Next:` hint passes the ids explicitly.
    _tag = uuid4().hex[:8]
    p = argparse.ArgumentParser(description="Stage 0 client reverse-profiling")
    p.add_argument("--name", default=f"Acme Robotics {_tag}")
    p.add_argument("--website", default=f"https://acme-{_tag}.example")
    p.add_argument("--workspace-id", default=f"acme-{_tag}")
    args = p.parse_args()
    asyncio.run(main(args.name, args.website, args.workspace_id))
