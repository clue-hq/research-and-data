#!/usr/bin/env python3
"""Repair a workspace: plan only what is missing, then apply exactly that plan (spec 2026-10-25).

    python scripts/repair_workspace.py --workspace ws_… --operator-email you@cluehq.ai \
        [--reason "why"] [--apply]

**Dry run by default**: prints the plan — failed onboarding steps to re-run, asset descriptions
to redo as one batch, the kit republish, a missing ad-DNA card — with an estimated cost, and
writes nothing. ``--apply`` (needs ``--reason``) plans again in the same transaction and applies
that plan: one repair onboarding run, one ``kit_repair`` design job, one audit row. A second
``--apply`` finds the work in flight and refuses ``nothing_to_repair``.

Runs from a worker container (``vm-batch1-1``) or platform-api: both halves are database writes,
the design API is not needed. Same functions as ``/ops/v1/workspaces/{id}/repair-plan`` and
``/repair``. Runbook: ``scripts/workspace_onboarding_operations.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from clue_api.workspace_ops.operators import OpsRefused, resolve_operator
from clue_api.workspace_ops.repair import apply_repair, plan_repair
from clue_db import db_lifespan, transaction


def _print_plan(plan: dict) -> None:
    onboarding, kit = plan["onboarding"], plan["kit"]
    print(f"workspace {plan['workspace_id']}")
    for step in onboarding["steps"]:
        print(f"  re-run   {step['kind']:<16} ${step['estimate_usd']:<6} {step['reason']}")
    if kit["capture_website"]:
        print(f"  capture  {kit['capture_website']} (no brand kit exists)")
    if kit["describe"]:
        print(f"  describe {len(kit['describe'])} assets as one batch")
    if kit["unsupported"]:
        print(f"  skip     {len(kit['unsupported'])} unsupported assets (cannot be described)")
    if kit["republish_brand_kit_id"]:
        print(f"  republish {kit['republish_brand_kit_id']} with descriptions stamped")
    if kit["offer_card_for_harvest"]:
        print(f"  card     rebuild from harvest {kit['offer_card_for_harvest']}")
    for note in [*onboarding["in_flight"], *kit["in_flight"]]:
        print(f"  waiting  {note}")
    print(f"estimate  ${plan['estimated_cost_usd']} ({plan['estimate_note']})")
    print(f"digest    {plan['plan_digest']}")


async def _run(args: argparse.Namespace) -> int:
    async with db_lifespan():
        try:
            async with transaction() as conn:
                operator = await resolve_operator(conn, args.operator_email)
                plan = await plan_repair(conn, workspace_id=args.workspace)
                _print_plan(plan.as_json())
                if not args.apply:
                    print("DRY RUN: nothing written (pass --apply --reason '…' to repair)")
                    return 0
                result = await apply_repair(
                    conn,
                    workspace_id=args.workspace,
                    plan_digest=plan.plan_digest,
                    operator=operator,
                    reason=args.reason or "",
                )
        except OpsRefused as refused:
            print(f"REFUSED {refused.code}: {refused.message}")
            return 1
    print(
        "APPLIED "
        + json.dumps(
            {k: result[k] for k in ("operation_id", "onboarding_run_id", "design_job_ids")}
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--operator-email", required=True)
    parser.add_argument("--reason")
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
