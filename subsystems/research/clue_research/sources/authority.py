"""Durable exact-source authority for one pinned ICP field.

The source planner may narrow or reorder execution for budget, modality and model advice, but it
may never widen this frozen set.  The pre-spend gate owns first-write acceptance; subsequent
planners load the same row so a later source-profile or registry change cannot silently alter an
already-pinned ICP version.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EffectiveFieldSourcePlan, serialize_value_json


class EffectiveSourcePlanConflict(RuntimeError):
    """A different exact-source authority is already frozen for these ICP coordinates."""


async def load_effective_source_plan(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    icp_key: str,
    icp_version: int,
    field_key: str,
) -> EffectiveFieldSourcePlan | None:
    row = (
        await conn.execute(
            text(
                "SELECT plan_json FROM effective_field_source_plan "
                "WHERE workspace_id=:workspace_id AND icp_key=:icp_key "
                "AND icp_version=:icp_version AND field_key=:field_key"
            ),
            {
                "workspace_id": workspace_id,
                "icp_key": icp_key,
                "icp_version": icp_version,
                "field_key": field_key,
            },
        )
    ).scalar_one_or_none()
    return None if row is None else EffectiveFieldSourcePlan.model_validate(row)


async def freeze_effective_source_plan(
    conn: AsyncConnection,
    plan: EffectiveFieldSourcePlan,
    *,
    source_profile_ref: Mapping[str, JsonValue],
) -> EffectiveFieldSourcePlan:
    """Insert once, then return the coordinate's canonical row or fail on conflicting content."""

    await conn.execute(
        text(
            "INSERT INTO effective_field_source_plan "
            "(workspace_id, icp_key, icp_version, field_key, plan_sha256, plan_json, "
            " source_profile_ref) VALUES "
            "(:workspace_id, :icp_key, :icp_version, :field_key, :plan_sha256, "
            " CAST(:plan_json AS jsonb), CAST(:source_profile_ref AS jsonb)) "
            "ON CONFLICT (workspace_id, icp_key, icp_version, field_key) DO NOTHING"
        ),
        {
            "workspace_id": plan.workspace_id,
            "icp_key": plan.icp_key,
            "icp_version": plan.icp_version,
            "field_key": str(plan.field_key),
            "plan_sha256": plan.plan_sha256,
            "plan_json": serialize_value_json(plan.model_dump(mode="json")),
            "source_profile_ref": serialize_value_json(dict(source_profile_ref)),
        },
    )
    frozen = await load_effective_source_plan(
        conn,
        workspace_id=plan.workspace_id,
        icp_key=plan.icp_key,
        icp_version=plan.icp_version,
        field_key=str(plan.field_key),
    )
    assert frozen is not None
    if frozen != plan:
        raise EffectiveSourcePlanConflict(
            "a different effective source plan is already frozen for "
            f"{plan.workspace_id}/{plan.icp_key}@{plan.icp_version}:{plan.field_key}"
        )
    return frozen


__all__ = [
    "EffectiveSourcePlanConflict",
    "freeze_effective_source_plan",
    "load_effective_source_plan",
]
