"""The open ``/ops/v1`` operator routes (spec 2026-10-25 §8 D1).

Founder ruling 2026-10-25: anyone may call these, with no sign-in, for now. They carry no
principal, membership or permission check, take the workspace in the path, and name the caller by
a self-declared ``operator_email`` that must belong to an existing Clue user. ``CLUE_OPS_ROUTES_
ENABLED=false`` unmounts them (every path a 404) with an env change, no code change.

Each route calls the same function its script does (``scripts/workspace_onboarding_operations.md``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_api.workspace_ops.add_workspace import add_workspace
from clue_api.workspace_ops.audit import record_operation
from clue_api.workspace_ops.onboarding_start import Preflight, start_onboarding
from clue_api.workspace_ops.operators import OpsRefused, resolve_operator
from clue_api.workspace_ops.repair import apply_repair, plan_repair
from clue_config import Settings
from clue_db import ConnFactory

PREFIX = "/ops/v1"
#: The audit row's estimate for a full onboarding walk (the spec's "~$2").
_ONBOARDING_ESTIMATE_USD = Decimal("2.00")


class AddWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3)
    website: str = Field(min_length=4)
    company_name: str | None = None
    operator_email: str = Field(min_length=3)
    apply: bool = False


class StartOnboardingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=253)
    company_name: str | None = Field(default=None, max_length=200)
    operator_email: str = Field(min_length=3)
    apply: bool = False


class RepairBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_digest: str = Field(min_length=1)
    reason: str
    operator_email: str = Field(min_length=3)


def _refused(error: OpsRefused) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.as_detail())


def create_ops_router(
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    enqueuer: object,
    brand_kit_ingestion: object | None,
    preflight: Preflight,
) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["ops"])

    async def _require_workspace(conn: Any, workspace_id: str) -> None:
        found = (
            await conn.execute(
                text("SELECT 1 FROM workspace WHERE workspace_id = :w"), {"w": workspace_id}
            )
        ).scalar_one_or_none()
        if found is None:
            raise OpsRefused(404, "workspace_not_found", f"no workspace {workspace_id!r}")

    @router.post("/workspaces")
    async def add(body: AddWorkspaceBody) -> dict[str, Any]:
        try:
            async with conn_factory() as conn:
                operator = await resolve_operator(conn, body.operator_email)
                return await add_workspace(
                    conn,
                    email=body.email,
                    website=body.website,
                    company_name=body.company_name,
                    operator=operator,
                    app_origin=settings.app_origin,
                    pages_system_suffix=settings.pages_system_suffix,
                    apply=body.apply,
                )
        except OpsRefused as error:
            raise _refused(error) from error

    @router.get("/workspaces/{workspace_id}/preflight")
    async def check(workspace_id: str) -> dict[str, Any]:
        try:
            async with conn_factory() as conn:
                await _require_workspace(conn, workspace_id)
        except OpsRefused as error:
            raise _refused(error) from error
        return (await preflight(workspace_id)).as_json()

    @router.post("/workspaces/{workspace_id}/onboarding")
    async def start(workspace_id: str, body: StartOnboardingBody) -> dict[str, Any]:
        try:
            async with conn_factory() as conn:
                await _require_workspace(conn, workspace_id)
                operator = await resolve_operator(conn, body.operator_email)
            if not body.apply:
                report = await preflight(workspace_id)
                return {"preflight": report.as_json(), "would_start": not report.blocking}
            run_id = await start_onboarding(
                conn_factory,
                workspace_id=workspace_id,
                domain=body.domain,
                brand_id=None,
                company_name=body.company_name,
                requested_by_user_id=operator.user_id,
                enqueuer=enqueuer,
                brand_kit_ingestion=brand_kit_ingestion,
                preflight=preflight,
            )
            async with conn_factory() as conn:
                await record_operation(
                    conn,
                    operation="start_onboarding",
                    workspace_id=workspace_id,
                    actor=operator.actor,
                    reason=None,
                    plan={"domain": body.domain},
                    estimated_cost_usd=_ONBOARDING_ESTIMATE_USD,
                    onboarding_run_id=run_id,
                    design_job_ids=(),
                )
        except OpsRefused as error:
            raise _refused(error) from error
        return {"run_id": str(run_id)}

    @router.get("/workspaces/{workspace_id}/repair-plan")
    async def repair_plan(workspace_id: str) -> dict[str, Any]:
        try:
            async with conn_factory() as conn:
                await _require_workspace(conn, workspace_id)
                return (await plan_repair(conn, workspace_id=workspace_id)).as_json()
        except OpsRefused as error:
            raise _refused(error) from error

    @router.post("/workspaces/{workspace_id}/repair")
    async def repair(workspace_id: str, body: RepairBody) -> dict[str, Any]:
        try:
            async with conn_factory() as conn:
                await _require_workspace(conn, workspace_id)
                operator = await resolve_operator(conn, body.operator_email)
                return await apply_repair(
                    conn,
                    workspace_id=workspace_id,
                    plan_digest=body.plan_digest,
                    operator=operator,
                    reason=body.reason,
                )
        except OpsRefused as error:
            raise _refused(error) from error

    return router


def install_ops_routes(
    app: FastAPI,
    *,
    settings: Settings,
    conn_factory: ConnFactory,
    enqueuer: object,
    brand_kit_ingestion: object | None,
    preflight: Preflight,
) -> None:
    """Mount the router, unless ``CLUE_OPS_ROUTES_ENABLED`` is off."""
    if not settings.ops_routes_enabled:
        return
    app.include_router(
        create_ops_router(
            settings=settings,
            conn_factory=conn_factory,
            enqueuer=enqueuer,
            brand_kit_ingestion=brand_kit_ingestion,
            preflight=preflight,
        )
    )
