"""One ``workspace_operation`` row per applied operator operation (spec 2026-10-25 §6).

Dry runs write nothing. The row says who (the self-declared actor), why, what was planned or
created, what it was estimated to cost, and what it started.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Operation = Literal["add_workspace", "start_onboarding", "repair"]


async def record_operation(
    conn: AsyncConnection,
    *,
    operation: Operation,
    workspace_id: str,
    actor: str,
    reason: str | None,
    plan: dict[str, Any],
    estimated_cost_usd: Decimal,
    onboarding_run_id: UUID | None,
    design_job_ids: Sequence[str],
    operation_id: UUID | None = None,
) -> UUID:
    operation_id = operation_id or uuid4()
    await conn.execute(
        text(
            "INSERT INTO workspace_operation (operation_id, operation, workspace_id, actor,"
            " reason, plan_json, estimated_cost_usd, onboarding_run_id, design_job_ids)"
            " VALUES (:id, :op, :ws, :actor, :reason, CAST(:plan AS jsonb), :cost, :run, :jobs)"
        ),
        {
            "id": operation_id,
            "op": operation,
            "ws": workspace_id,
            "actor": actor,
            "reason": reason.strip() if reason and reason.strip() else None,
            "plan": json.dumps(plan, sort_keys=True, default=str),
            "cost": estimated_cost_usd,
            "run": onboarding_run_id,
            "jobs": list(design_job_ids),
        },
    )
    return operation_id
