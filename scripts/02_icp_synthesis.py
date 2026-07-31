"""Run ICP synthesis + confirm (M5.2).

Reads the Client Knowledge Base written by script 01, synthesizes one or more ICP
proposals, confirms the first into a versioned ICP spec, and prints the icp_key +
icp_version the discovery / profiling scripts use.

    uv run python scripts/02_icp_synthesis.py \
        --workspace-id acme --client-entity-id <UUID from script 01> --kb-version 1

Offline (no CLUE_OPENROUTER_API_KEY) the gateway runs in deterministic stub mode, so
synthesis returns its deterministic floor proposal instead of an LLM-shaped one.
"""

import argparse
import asyncio
from uuid import UUID

import clue_obs
from clue_api.composition import load_research_packs
from clue_config import GatewayConfig, load_settings
from clue_db import db_lifespan, transaction
from clue_gateway import build_gateway
from clue_research.stage0 import (
    ClientKnowledgeBaseRef,
    ICPSynthesisStatus,
    confirm_icp,
    synthesize_icps,
)


async def main(workspace_id: str, client_entity_id: str, kb_version: int) -> None:
    gateway = build_gateway(GatewayConfig(), api_key=None)  # stub: no key -> no live LLM
    ref = ClientKnowledgeBaseRef(
        client_entity_id=UUID(client_entity_id),
        client_kb_version=kb_version,
    )

    async with db_lifespan(), transaction() as conn:
        await load_research_packs(conn)
        result = await synthesize_icps(
            conn,
            ref,
            workspace_id=workspace_id,
            gateway=gateway,
            synthesis_model=load_settings().synthesis_model,
        )
        proposals = result.proposals
        if result.status is not ICPSynthesisStatus.GROUNDED:
            print(f"ICP synthesis is not ready: {', '.join(result.reason_codes)}")
            return
        confirmation = await confirm_icp(
            conn,
            proposals[0],
            workspace_id=workspace_id,
            client_entity_id=UUID(client_entity_id),
        )

    print("\n=== ICP synthesis ===")
    print(f"proposals        : {len(proposals)}")
    for prop in proposals:
        print(f"  - {prop.icp_key}: {prop.label or '(no label)'}")
    print("\n=== confirmed ICP spec ===")
    print(f"workspace_id        : {confirmation.ref.workspace_id}")
    print(f"icp_key          : {confirmation.ref.icp_key}")
    print(f"icp_version      : {confirmation.ref.icp_version}")
    print(f"est. deep accts  : {confirmation.estimate.projected_deep_count}")
    print(f"est. cost_cents  : {confirmation.estimate.estimated_cost_cents}")
    print(f"\nNext: scripts/03_find_accounts.py --workspace-id {workspace_id} --max-accounts 5")


if __name__ == "__main__":
    clue_obs.setup()
    p = argparse.ArgumentParser(description="ICP synthesis + confirm")
    # Required (not defaulted): 02 can only continue a script-01 chain, and a fixed default here
    # silently confirms the ICP under a different workspace than the KB it reads (review finding).
    p.add_argument("--workspace-id", required=True, help="workspace id printed by script 01")
    p.add_argument("--client-entity-id", required=True, help="UUID printed by script 01")
    p.add_argument("--kb-version", type=int, default=1)
    args = p.parse_args()
    asyncio.run(main(args.workspace_id, args.client_entity_id, args.kb_version))
