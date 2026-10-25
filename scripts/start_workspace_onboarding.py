#!/usr/bin/env python3
"""Start onboarding for a workspace, as an operator (spec 2026-10-25 §3.2).

    python scripts/start_workspace_onboarding.py --workspace ws_… --domain acme.com \
        --operator-email you@cluehq.ai [--company-name "Acme"] [--apply]

**Dry run by default**: runs the provider pre-flight (one ~half-cent Exa probe) and prints
whether onboarding would start. ``--apply`` starts it through the same function as
``POST /onboarding`` and ``POST /ops/v1/workspaces/{id}/onboarding``, and audits it.

**Run it on platform-api** (``railway ssh``): starting onboarding also asks the design API for the
brand-kit ingestion over HTTP, and the design API is reachable only on Railway's private network.
From anywhere else the brand-kit half is skipped (logged) and the pre-flight refuses
``design_api``. Runbook: ``scripts/workspace_onboarding_operations.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal

from clue_api.brand_kit_ingestion import build_brand_kit_ingestion_trigger
from clue_api.onboarding_routes import DbOnboardingEnqueuer
from clue_api.workspace_ops.audit import record_operation
from clue_api.workspace_ops.onboarding_start import start_onboarding
from clue_api.workspace_ops.operators import OpsRefused, resolve_operator
from clue_api.workspace_ops.preflight import build_preflight
from clue_config import Secrets, Settings
from clue_db import db_lifespan, transaction


def _print_report(report: object) -> None:
    for result in report.results:  # type: ignore[attr-defined]
        flag = "BLOCKS" if result in report.blocking else "  ok  "  # type: ignore[attr-defined]
        print(f"{flag} {result.provider:<20} {result.outcome:<15} {result.detail}")


async def _run(args: argparse.Namespace) -> int:
    settings, secrets = Settings(), Secrets()
    preflight = build_preflight(settings, secrets, transaction)
    async with db_lifespan():
        try:
            async with transaction() as conn:
                operator = await resolve_operator(conn, args.operator_email)
            if not args.apply:
                report = await preflight(args.workspace)
                _print_report(report)
                print("DRY RUN: would start" if not report.blocking else "DRY RUN: would REFUSE")
                return 0 if not report.blocking else 1
            run_id = await start_onboarding(
                transaction,
                workspace_id=args.workspace,
                domain=args.domain,
                brand_id=None,
                company_name=args.company_name,
                requested_by_user_id=operator.user_id,
                enqueuer=DbOnboardingEnqueuer(),
                brand_kit_ingestion=build_brand_kit_ingestion_trigger(
                    settings=settings, conn_factory=transaction
                ),
                preflight=preflight,
            )
            async with transaction() as conn:
                await record_operation(
                    conn,
                    operation="start_onboarding",
                    workspace_id=args.workspace,
                    actor=operator.actor,
                    reason=None,
                    plan={"domain": args.domain},
                    estimated_cost_usd=Decimal("2.00"),
                    onboarding_run_id=run_id,
                    design_job_ids=(),
                )
        except OpsRefused as refused:
            print(f"REFUSED {refused.code}: {refused.message}")
            for provider in refused.detail.get("providers", []):
                print(f"  {provider['provider']}: {provider['outcome']} — {provider['detail']}")
            return 1
    print(f"STARTED onboarding run {run_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--operator-email", required=True)
    parser.add_argument("--company-name")
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
