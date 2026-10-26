"""Repair a workspace: plan only what is missing, then apply exactly that plan (spec 2026-10-25).

**Plan** (a dry run, writes nothing) has two halves:

- *onboarding* — failed research steps and the ICP turn, re-run as one small ``repair`` run
  (:mod:`clue_api.workspace_ops.onboarding_plan`);
- *brand kit* — failed descriptions as ONE batch job, the kit republished with them stamped, a
  missing ad-DNA card rebuilt from the existing harvest (:mod:`clue_design.kit_repair`).

It carries an estimated cost and a ``plan_digest``: a hash of the planned items only.

**Apply** takes that digest. Under a per-workspace lock it plans again and refuses unless the plan
is unchanged, so it runs exactly the plan that was shown. Then, in the caller's one transaction:
the repair run and its fleet task, the ``kit_repair`` (or website capture) design job and its
fleet task, and one ``workspace_operation`` audit row. A second apply finds that work in flight
and refuses ``nothing_to_repair``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_driver import ONBOARDING_DEDUP_PREFIX, onboarding_work_id
from clue_api.arv2.onboarding_store import create_repair_run
from clue_api.workspace_ops.audit import record_operation
from clue_api.workspace_ops.kit_offer import offer_design_job
from clue_api.workspace_ops.onboarding_plan import (
    DESCRIPTION_ESTIMATE_USD,
    OnboardingRepairPlan,
    plan_onboarding_repair,
)
from clue_api.workspace_ops.operators import Operator, OpsRefused
from clue_config import Settings
from clue_core import ProjectRunId
from clue_design.kit_repair import KitRepairPlan, plan_kit_repair
from clue_fleet import FleetTaskKind
from clue_fleet.queue import enqueue_task

#: The ad-DNA distil (one vision call over the harvest) and a website re-capture (capture,
#: descriptions, brief); fixed estimates like the onboarding ones.
CARD_ESTIMATE_USD = Decimal("0.05")
CAPTURE_ESTIMATE_USD = Decimal("1.00")
#: Same priority as an onboarding start (``onboarding_routes.ONBOARDING_TASK_PRIORITY``).
REPAIR_TASK_PRIORITY = -150

_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")


@dataclass(frozen=True)
class RepairPlan:
    workspace_id: str
    onboarding: OnboardingRepairPlan
    kit: KitRepairPlan
    estimated_cost_usd: Decimal
    plan_digest: str

    @property
    def is_empty(self) -> bool:
        return not self.onboarding.steps and self.kit.is_empty

    def as_json(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "onboarding": self.onboarding.as_json(),
            "kit": self.kit.as_json(),
            "estimated_cost_usd": str(self.estimated_cost_usd),
            "estimate_note": "an estimate from fixed per-item figures, not a quote",
            "plan_digest": self.plan_digest,
            "nothing_to_repair": self.is_empty,
        }


async def plan_repair(
    conn: AsyncConnection, *, workspace_id: str, settings: Settings | None = None
) -> RepairPlan:
    onboarding = await plan_onboarding_repair(conn, workspace_id=workspace_id, settings=settings)
    kit = await plan_kit_repair(conn, workspace_id=workspace_id)
    estimate = sum((step.estimate_usd for step in onboarding.steps), Decimal(0))
    estimate += DESCRIPTION_ESTIMATE_USD * len(kit.describe)
    estimate += CARD_ESTIMATE_USD if kit.offer_card_for_harvest else Decimal(0)
    estimate += CAPTURE_ESTIMATE_USD if kit.capture_website else Decimal(0)
    planned = {
        "steps": [[step.kind, step.subject_ref] for step in onboarding.steps],
        "capture_website": kit.capture_website,
        "describe": list(kit.describe),
        "republish_brand_kit_id": kit.republish_brand_kit_id,
        "offer_card_for_harvest": kit.offer_card_for_harvest,
    }
    digest = hashlib.sha256(json.dumps(planned, sort_keys=True).encode()).hexdigest()
    return RepairPlan(workspace_id, onboarding, kit, estimate, digest)


async def apply_repair(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    plan_digest: str,
    operator: Operator,
    reason: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if not reason or not reason.strip():
        raise OpsRefused(422, "reason_required", "a repair needs a reason for the audit trail")
    # One repair decision per workspace at a time; the onboarding-start lock is taken too, so a
    # start and a repair cannot both see "no run open" and both begin one.
    await conn.execute(_LOCK_SQL, {"key": f"ops-repair:{workspace_id}"})
    await conn.execute(_LOCK_SQL, {"key": f"onboarding-start:{workspace_id}"})
    # Never two at once (spec §3.4 A): while a full onboarding is open neither half of a repair
    # runs — the walk may fix what is missing, and its documents and kit would race the repair's.
    open_full = (
        await conn.execute(
            text(
                "SELECT run_id FROM onboarding_run WHERE workspace_id = :w AND kind = 'full'"
                " AND status IN ('queued', 'running') LIMIT 1"
            ),
            {"w": workspace_id},
        )
    ).scalar_one_or_none()
    if open_full is not None:
        raise OpsRefused(409, "onboarding_in_progress", str(open_full))
    plan = await plan_repair(conn, workspace_id=workspace_id, settings=settings)
    if plan.is_empty:
        raise OpsRefused(
            409,
            "nothing_to_repair",
            "nothing is missing that a repair can fix",
            detail={"plan": plan.as_json()},
        )
    if plan.plan_digest != plan_digest:
        raise OpsRefused(
            409,
            "plan_changed",
            "the workspace changed since that plan was made",
            detail={"plan": plan.as_json()},
        )

    operation_id = uuid4()
    run_id = await _offer_onboarding_repair(conn, plan, operator) if plan.onboarding.steps else None
    design_job_ids = await _offer_kit_repair(
        conn, plan.kit, workspace_id, operator, reason, operation_id
    )
    await record_operation(
        conn,
        operation="repair",
        workspace_id=workspace_id,
        actor=operator.actor,
        reason=reason,
        plan=plan.as_json(),
        estimated_cost_usd=plan.estimated_cost_usd,
        onboarding_run_id=run_id,
        design_job_ids=design_job_ids,
        operation_id=operation_id,
    )
    return {
        "operation_id": str(operation_id),
        "onboarding_run_id": None if run_id is None else str(run_id),
        "design_job_ids": design_job_ids,
        "plan": plan.as_json(),
    }


async def _offer_onboarding_repair(
    conn: AsyncConnection, plan: RepairPlan, operator: Operator
) -> UUID:
    onboarding = plan.onboarding
    assert onboarding.brand_id and onboarding.company_domain  # a plan with steps has a full run
    run_id = uuid4()
    planned = [{"kind": step.kind, "subject_ref": step.subject_ref} for step in onboarding.steps]
    await create_repair_run(
        conn,
        run_id=run_id,
        workspace_id=plan.workspace_id,
        brand_id=onboarding.brand_id,
        company_domain=onboarding.company_domain,
        requested_by_user_id=operator.user_id,
        planned_steps=planned,
    )
    # On this connection, not through a separate queue transaction: the run and its task land
    # together or not at all, so a repair can never leave a run nothing will drive.
    await enqueue_task(
        conn,
        kind=FleetTaskKind.ONBOARDING_RUN,
        project_run_id=ProjectRunId(onboarding_work_id(run_id)),
        dedup_key=f"{ONBOARDING_DEDUP_PREFIX}{run_id}",
        priority=REPAIR_TASK_PRIORITY,
        payload={
            "run_id": str(run_id),
            "workspace_id": plan.workspace_id,
            "brand_id": onboarding.brand_id,
            "company_domain": onboarding.company_domain,
            "company_name": onboarding.company_name or onboarding.company_domain,
            "kind": "repair",
            "planned_steps": planned,
        },
        reopen_terminal=False,
    )
    return run_id


async def _offer_kit_repair(
    conn: AsyncConnection,
    kit: KitRepairPlan,
    workspace_id: str,
    operator: Operator,
    reason: str,
    operation_id: UUID,
) -> list[str]:
    if kit.capture_website:
        # The same request the design API's website route stores (its defaults made explicit).
        request = {
            "url": kit.capture_website,
            "page_urls": [],
            "discover_pages": True,
            "name": None,
            "brand_kit_id": None,
            "force_render": False,
        }
        return [
            await offer_design_job(conn, workspace_id=workspace_id, kind="website", request=request)
        ]
    if kit.is_empty:
        return []
    request = {
        "targets": {asset_id: {} for asset_id in kit.describe},
        "republish_brand_kit_id": kit.republish_brand_kit_id,
        "offer_card": kit.offer_card_for_harvest is not None,
        "actor": operator.actor,
        "reason": reason.strip(),
        "operation_id": str(operation_id),
    }
    return [
        await offer_design_job(conn, workspace_id=workspace_id, kind="kit_repair", request=request)
    ]
