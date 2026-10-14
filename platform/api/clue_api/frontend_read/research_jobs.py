"""Admin endpoints over stuck ARV2 research jobs (spec 2026-10-14 §3.7).

Both require ``research.approve_spend`` (workspace owners and admins): a resume may top up the
job's allowance, which approves more spend.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from clue_api.arv2.job_resume import ResumeRefused, TopUp, list_stuck_jobs, resume_research_job
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.settings_authority import lock_manager, principal_for, refused
from clue_auth.policy import Permission
from clue_db import ConnFactory

PERMISSION: Permission = "research.approve_spend"
#: Refusal codes that are not 409. A job in another workspace is indistinguishable from none.
_STATUS = {"job_not_found": 404}


class TopUpBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(0, ge=0)
    tool_calls: int = Field(0, ge=0)
    delegations: int = Field(0, ge=0)
    runtime_minutes: int = Field(0, ge=0)


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    restart_fresh: bool = False
    top_up: TopUpBody = Field(default_factory=TopUpBody)


def register_research_job_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    @router.get("/research/jobs/stuck")
    async def stuck_jobs(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal_for(request, workspace_id, permission=PERMISSION)
        async with conn_factory() as conn:
            jobs = await list_stuck_jobs(conn, workspace_id=workspace_id)
        return {"jobs": [job.as_json() for job in jobs]}

    @router.post("/research/jobs/{job_id}/resume")
    async def resume_job(
        job_id: UUID, body: ResumeBody, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission=PERMISSION)
        try:
            async with conn_factory() as conn:
                await lock_manager(conn, principal, PERMISSION)
                result = await resume_research_job(
                    conn,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    actor=f"human:{principal.user_id}",
                    reason=body.reason,
                    top_up=TopUp(**body.top_up.model_dump()),
                    restart_fresh=body.restart_fresh,
                )
        except ResumeRefused as error:
            raise refused(_STATUS.get(error.code, 409), error.code, error.message) from error
        return result.as_json()
