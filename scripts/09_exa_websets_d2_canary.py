#!/usr/bin/env python3
"""Run or replay the bounded live D2 Exa Websets submit against the Stage-0 fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from clue_api.exa_websets_submit import DurableExaWebsetSubmitter
from clue_api.trial.discovery_fixture import (
    ICP_KEY,
    PROJECT_ID,
    PROJECT_RUN_ID,
    WORKSPACE_ID,
)
from clue_config import Secrets
from clue_core import (
    DiscoveryBatchId,
    DiscoveryCriterionPlan,
    DiscoveryEntityKind,
    DiscoveryPlan,
    DiscoveryPlanId,
    DiscoverySearchPlan,
)
from clue_db import db_lifespan, transaction
from clue_obs.otel import collect_spans
from clue_research.adapters.exa_websets import (
    EXA_WEBSETS_CONTRACT_VERSION,
    ExaWebsetsClient,
)
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.durable import (
    create_discovery_batch,
    find_reusable_discovery_operation,
    get_discovery_batch,
    put_discovery_plan,
)
from clue_research.icp import get_active_icp
from clue_storage import FsStorage

SEARCH_KEY = "aura-neurosurgery-account-discovery-d2"
PROVIDER_POLICY_VERSION = "exa-websets-public-credit-policy-2026-08-02"
EXPECTED_MAX_CREDITS = 20


class _FixtureStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    requested_count: int = Field(ge=1)
    entity_type: DiscoveryEntityKind
    query: str = Field(min_length=1)
    must_have_criteria: tuple[str, ...] = Field(min_length=1, max_length=5)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Submit or replay the exact two-company Exa Webset compiled from the Insight Health/"
            "Aura Stage-0 fixture. The target database must already contain that fixture and be "
            "migrated to head."
        )
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="Explicit SQLAlchemy async URL for the named discovery fixture database.",
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(".context/discovery-fixtures/insight-health-aura/artifacts"),
    )
    parser.add_argument(
        "--observation-window",
        required=True,
        help="Stable paid-operation window, for example 2026-08-02-d2-live-v1.",
    )
    parser.add_argument(
        "--generation",
        type=int,
        default=1,
        help="Positive discovery-batch generation; increment only for a separately approved run.",
    )
    parser.add_argument(
        "--allow-live-create",
        action="store_true",
        help=(
            "Permit the bounded 20-credit create when no durable operation exists. Without this "
            "flag the command is replay-only and exits before provider I/O."
        ),
    )
    return parser.parse_args()


def _stable_uuid(kind: str, observation_window: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        (
            f"clue://d2-live/{WORKSPACE_ID}/{PROJECT_RUN_ID}/{kind}/"
            f"{EXA_WEBSETS_CONTRACT_VERSION}/{observation_window}"
        ),
    )


async def _ensure_plan_and_batch(
    observation_window: str,
    generation: int,
) -> tuple[DiscoveryPlan, DiscoveryBatchId]:
    if generation < 1:
        raise ValueError("generation must be positive")
    async with transaction() as conn:
        icp = await get_active_icp(conn, WORKSPACE_ID, ICP_KEY)
        if icp is None:
            raise RuntimeError("Insight Health/Aura fixture ICP is missing")
        if icp.version != 1:
            raise RuntimeError(f"fixture ICP version changed: expected 1, found {icp.version}")
        strategy = _FixtureStrategy.model_validate(icp.discovery_strategy)
        if strategy.requested_count != 2 or strategy.entity_type is not DiscoveryEntityKind.COMPANY:
            raise RuntimeError("fixture strategy is not the approved two-company D2 workload")

        plan = DiscoveryPlan(
            discovery_plan_id=DiscoveryPlanId(_stable_uuid("plan", observation_window)),
            plan_version=generation,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            project_run_id=PROJECT_RUN_ID,
            icp_key=icp.icp_key,
            icp_version=icp.version,
            provider_policy_version=PROVIDER_POLICY_VERSION,
            field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
            provider_contract_version=EXA_WEBSETS_CONTRACT_VERSION,
            channels=("exa_websets",),
            searches=(
                DiscoverySearchPlan(
                    search_key=SEARCH_KEY,
                    channel_key="exa_websets",
                    normalized_query=strategy.query,
                    entity_type=strategy.entity_type,
                    requested_count=strategy.requested_count,
                    criteria=tuple(
                        DiscoveryCriterionPlan(description=value)
                        for value in strategy.must_have_criteria
                    ),
                ),
            ),
            required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
            optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
            provider_credit_cap=EXPECTED_MAX_CREDITS,
            money_budget_cap_cents=Decimal("100"),
            stopping_policy={"requested_count": 2, "closed_batch": True},
            snapshot_reuse_policy="same_observation_window",
        )
        await put_discovery_plan(conn, workspace_id=WORKSPACE_ID, plan=plan)
        proposed_batch_id = DiscoveryBatchId(
            _stable_uuid(f"batch-{generation}", observation_window)
        )
        batch = await create_discovery_batch(
            conn,
            workspace_id=WORKSPACE_ID,
            batch_id=proposed_batch_id,
            plan_id=plan.discovery_plan_id,
            generation=generation,
        )
        return plan, batch.id


async def _run(args: argparse.Namespace) -> dict[str, object]:
    secrets = Secrets()
    if secrets.exa_api_key is None:
        raise RuntimeError("CLUE_EXA_API_KEY is unset")
    storage = FsStorage(args.storage_root)
    plan, batch_id = await _ensure_plan_and_batch(args.observation_window, args.generation)

    # Replay-only mode proves the operator cannot accidentally mint a paid request merely by
    # inspecting a prior acceptance run.
    async with transaction() as conn:
        from clue_api.exa_websets_submit import (
            build_exa_create_request,
        )

        fingerprint, _ = build_exa_create_request(
            plan=plan,
            search=plan.searches[0],
            observation_window=args.observation_window,
        )
        existing = await find_reusable_discovery_operation(
            conn,
            workspace_id=WORKSPACE_ID,
            source_key="exa_websets",
            request_fingerprint=fingerprint,
            observation_window=args.observation_window,
        )
    if existing is None and not args.allow_live_create:
        raise RuntimeError(
            "no durable D2 operation exists; rerun with --allow-live-create only after approving "
            f"the bounded {EXPECTED_MAX_CREDITS}-credit workload"
        )

    async with ExaWebsetsClient(api_key=secrets.exa_api_key) as client:
        submitter = DurableExaWebsetSubmitter(transport=client, storage=storage)
        with collect_spans() as exporter:
            result = await submitter.submit(
                workspace_id=WORKSPACE_ID,
                batch_id=batch_id,
                search_key=SEARCH_KEY,
                observation_window=args.observation_window,
            )
        span_names = tuple(span.name for span in exporter.get_finished_spans())

    async with transaction() as conn:
        batch = await get_discovery_batch(
            conn,
            workspace_id=WORKSPACE_ID,
            batch_id=batch_id,
        )
    if batch is None:
        raise RuntimeError("D2 batch disappeared after submit")
    operation = result.operation
    return {
        "outcome": result.outcome.value,
        "workspace_id": WORKSPACE_ID,
        "project_run_id": str(PROJECT_RUN_ID),
        "discovery_plan_id": str(plan.discovery_plan_id),
        "discovery_batch_id": str(batch_id),
        "operation_id": str(operation.operation_id),
        "request_fingerprint": operation.request_fingerprint,
        "provider_external_id": operation.provider_external_id,
        "provider_operation_id": operation.provider_operation_id,
        "provider_request_id": result.provider_request_id,
        "provider_status": result.provider_status,
        "dashboard_url": result.dashboard_url,
        "raw_request_artifact_key": operation.raw_request_artifact_key,
        "submitted_receipt_ref": operation.submitted_receipt_ref,
        "provider_units_reserved": str(operation.provider_units_reserved),
        "provider_units_realized": str(operation.provider_units_charged),
        "cost_cents_realized": str(operation.cost_cents_charged),
        "spend_outcome": operation.spend_outcome.value,
        "operation_state": operation.state.value,
        "batch_state": batch.state.value,
        "batch_provider_units_reserved": str(batch.provider_units_reserved),
        "batch_provider_units_realized": str(batch.provider_units_charged),
        "create_calls_this_process": result.create_calls,
        "lookup_calls_this_process": result.lookup_calls,
        "trace_span_names": span_names,
    }


async def _entry(args: argparse.Namespace) -> dict[str, object]:
    async with db_lifespan(args.database_url):
        return await _run(args)


def main() -> None:
    args = _args()
    result = asyncio.run(_entry(args))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
