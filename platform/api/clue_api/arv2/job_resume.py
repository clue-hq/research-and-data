"""Resume or restart a stopped ARV2 research job.

Spec: docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md. One identity function
(§3.2), one restart signal, and one audited resume operation (§3.5) that the developer script
(§3.6) and the admin endpoints (§3.7) share.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

RestartReason = Literal["instructions_changed", "context_changed_before_start"]


def research_execution_id(
    job_id: UUID, restart_count: int = 0, unit_key: str | None = None
) -> UUID:
    """The execution a research job's conversation runs under.

    Restart 0 is the id every job had before restarts existed, so existing jobs keep their saved
    state. A reconciliation unit keeps its own id whatever the restart count: only the job's main
    conversation moves on a restart.
    """
    if restart_count < 0:
        raise ValueError("a restart count is never negative")
    if unit_key:
        return uuid5(NAMESPACE_URL, f"research-quality:{job_id}:{unit_key}")
    if restart_count == 0:
        return uuid5(NAMESPACE_URL, f"research-quality:{job_id}")
    return uuid5(NAMESPACE_URL, f"research-quality:{job_id}:restart:{restart_count}")


class ResearchRestartRequired(RuntimeError):
    """The job's saved conversation cannot be continued; the driver gives it a fresh one."""

    def __init__(self, reason: RestartReason) -> None:
        super().__init__(f"research job needs a fresh conversation: {reason}")
        self.reason: RestartReason = reason


_RESTART_REASONS: dict[str, str] = {
    "instructions_changed": "The agent's instructions changed since this job's last attempt.",
    "context_changed_before_start": (
        "The job's opening context changed before its first step ran."
    ),
}


@dataclass(frozen=True)
class TopUp:
    """An admin's explicit addition to a job's allowance limits (spec §3.5)."""

    model_calls: int = 0
    tool_calls: int = 0
    delegations: int = 0
    runtime_minutes: int = 0

    def is_empty(self) -> bool:
        return not (self.model_calls or self.tool_calls or self.delegations or self.runtime_minutes)


async def _audit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: UUID,
    attempt_before: int,
    actor: str,
    reason: str,
    top_up: TopUp,
    restarted: bool,
) -> None:
    await conn.execute(
        text("""
      INSERT INTO arv2_research_job_resume(
        resume_id,workspace_id,job_id,attempt_before,actor,reason,restarted,
        top_up_model_calls,top_up_tool_calls,top_up_delegations,top_up_runtime_ms)
      VALUES (:id,:ws,:job,:attempt,:actor,:reason,:restarted,:model,:tool,:delegation,:runtime)
    """),
        {
            "id": uuid4(),
            "ws": workspace_id,
            "job": job_id,
            "attempt": attempt_before,
            "actor": actor,
            "reason": reason,
            "restarted": restarted,
            "model": top_up.model_calls,
            "tool": top_up.tool_calls,
            "delegation": top_up.delegations,
            "runtime": top_up.runtime_minutes * 60_000,
        },
    )


async def restart_on_claim(
    conn: AsyncConnection, *, job_id: UUID, attempt: int, reason: RestartReason
) -> bool:
    """Give this attempt's job a fresh conversation and park it for requeue (spec §3.2).

    Fenced like ``suspend_job``: only the attempt that claimed the job, and only while it is
    ``in_progress``. Returns whether it restarted.
    """
    row = (
        await conn.execute(
            text("""
      UPDATE arv2_research_job SET restart_count=restart_count+1, status='suspended',
        updated_at=now()
      WHERE job_id=:job AND attempt=:attempt AND status='in_progress'
      RETURNING workspace_id
    """),
            {"job": job_id, "attempt": attempt},
        )
    ).one_or_none()
    if row is None:
        return False
    await _audit(
        conn,
        workspace_id=row.workspace_id,
        job_id=job_id,
        attempt_before=attempt,
        actor=f"system:{reason}",
        reason=_RESTART_REASONS[reason],
        top_up=TopUp(),
        restarted=True,
    )
    return True
