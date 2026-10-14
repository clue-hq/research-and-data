"""Resume or restart a stopped ARV2 research job.

Spec: docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md. One identity function
(§3.2), one restart signal, and one audited resume operation (§3.5) that the developer script
(§3.6) and the admin endpoints (§3.7) share.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_store import refresh_run_status
from clue_api.arv2.fleet_task import (
    ARV2_ACCOUNT_DEDUP_PREFIX,
    ARV2_ACCOUNT_TASK_PRIORITY,
    arv2_account_work_id,
)
from clue_core import ProjectRunId
from clue_fleet import FleetTaskKind
from clue_fleet.queue import enqueue_task

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


#: The default for a resume without a top-up (``TopUp`` is frozen, so one instance is shared).
NO_TOP_UP = TopUp()


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


_MESSAGES: dict[str, str] = {
    "job_not_found": "No research job with that id in this workspace.",
    "job_completed": "The job completed; there is nothing to resume.",
    "job_not_started": "The job has not started; it is waiting for its turn, not stuck.",
    "job_already_queued": "The job is already queued or running.",
    "privacy_stopped": "Research on this subject was stopped for privacy.",
    "research_stopped": "Research on this account was stopped; resume the account first.",
    "outputs_frozen": (
        "This job's outputs were frozen by the pre-fix finalize bug and it cannot be resumed."
    ),
    "reason_required": "Say why this job is being resumed.",
}


class ResumeRefused(Exception):
    """A named reason a job cannot be resumed (spec §3.5)."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or _MESSAGES.get(code, code)
        super().__init__(f"{code}: {self.message}")


@dataclass(frozen=True)
class StuckJob:
    job_id: UUID
    run_id: UUID
    workspace_id: str
    subject_type: str
    account_id: UUID
    account_name: str | None
    person_id: UUID | None
    person_name: str | None
    state: Literal["failed", "stalled"]
    status: str
    failure_code: str | None
    failure_message: str | None
    rounds: int
    tool_calls: int
    cost_usd: Decimal
    stopped_at: datetime
    restart_count: int
    resumable: bool
    refusal: str | None

    def as_json(self) -> dict[str, Any]:
        body = asdict(self)
        for key in ("job_id", "run_id", "account_id", "person_id"):
            body[key] = str(body[key]) if body[key] is not None else None
        body["cost_usd"] = str(self.cost_usd)
        body["stopped_at"] = self.stopped_at.isoformat()
        return body


@dataclass(frozen=True)
class ResumeResult:
    job_id: UUID
    status: str
    attempt: int
    restarted: bool
    top_up_applied: TopUp

    def as_json(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "status": self.status,
            "attempt": self.attempt,
            "restarted": self.restarted,
            "top_up_applied": asdict(self.top_up_applied),
        }


_JOBS = """
SELECT j.job_id, j.run_id, j.workspace_id, j.subject_type, j.status, j.attempt,
  j.account_entity_id, a.canonical_name AS account_name,
  j.subject_entity_id, c.full_name AS person_name,
  j.failure_code, j.failure_message, j.model_rounds, j.tool_calls, j.cost_usd,
  COALESCE(j.finished_at, j.updated_at) AS stopped_at, j.restart_count,
  (COALESCE(j.input_refs->>'privacy_stopped', 'false') = 'true' OR EXISTS (
     SELECT 1 FROM arv2_account_research_generation g
     WHERE g.workspace_id = j.workspace_id AND g.run_id = j.run_id
       AND g.account_id = j.account_entity_id AND g.state = 'privacy_stopped'))
    AS privacy_stopped,
  EXISTS (
     SELECT 1 FROM arv2_account_research_generation g
     WHERE g.workspace_id = j.workspace_id AND g.run_id = j.run_id
       AND g.account_id = j.account_entity_id AND g.state = 'suspended') AS research_stopped,
  EXISTS (
     SELECT 1 FROM fleet_task t
     WHERE t.kind = CAST(:kind AS fleet_task_kind) AND t.work_id = j.job_id
       AND t.status IN ('queued', 'claimed')) AS queued
FROM arv2_research_job j
LEFT JOIN account_entity a ON a.id = j.account_entity_id
LEFT JOIN contact_entity c ON c.id = j.subject_entity_id
"""


def _refusal(row: Any) -> str | None:
    """Why this job cannot be resumed, or ``None`` when it can."""
    if row.status == "completed":
        return "job_completed"
    if row.status == "not_started":
        return "job_not_started"
    if row.queued:
        return "job_already_queued"
    if row.privacy_stopped:
        return "privacy_stopped"
    if row.research_stopped:
        return "research_stopped"
    if row.failure_code == "workspace_conflict":
        return "outputs_frozen"
    return None


def _stuck(row: Any) -> StuckJob:
    refusal = _refusal(row)
    return StuckJob(
        job_id=row.job_id,
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        subject_type=row.subject_type,
        account_id=row.account_entity_id,
        account_name=row.account_name,
        person_id=row.subject_entity_id,
        person_name=row.person_name,
        state="failed" if row.status == "needs_review" else "stalled",
        status=row.status,
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        rounds=row.model_rounds,
        tool_calls=row.tool_calls,
        cost_usd=row.cost_usd,
        stopped_at=row.stopped_at,
        restart_count=row.restart_count,
        resumable=refusal is None,
        refusal=refusal,
    )


async def list_stuck_jobs(conn: AsyncConnection, *, workspace_id: str | None) -> list[StuckJob]:
    """Failed jobs, and started jobs nothing is queued to continue, newest first.

    ``workspace_id=None`` lists every workspace (the developer script only).
    """
    rows = (
        await conn.execute(
            text(
                _JOBS + " WHERE (CAST(:ws AS text) IS NULL OR j.workspace_id = :ws)"
                " AND j.status IN ('needs_review', 'suspended', 'in_progress')"
                " ORDER BY stopped_at DESC, j.job_id"
            ),
            {"ws": workspace_id, "kind": FleetTaskKind.ARV2_ACCOUNT_RESEARCH.value},
        )
    ).all()
    return [_stuck(row) for row in rows if row.status == "needs_review" or not row.queued]


async def offer_research_job(
    conn: AsyncConnection, *, job_id: UUID, run_id: UUID, workspace_id: str
) -> bool:
    """Offer a research job to the fleet the way its launch does; re-opens a closed task."""
    return await enqueue_task(
        conn,
        kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH,
        project_run_id=ProjectRunId(arv2_account_work_id(job_id)),
        dedup_key=f"{ARV2_ACCOUNT_DEDUP_PREFIX}{job_id}",
        priority=ARV2_ACCOUNT_TASK_PRIORITY,
        payload={"job_id": str(job_id), "run_id": str(run_id), "workspace_id": workspace_id},
        reopen_terminal=True,
    )


async def _apply_top_up(
    conn: AsyncConnection, *, workspace_id: str, job_id: UUID, top_up: TopUp
) -> None:
    allowance = (
        await conn.execute(
            text(
                "SELECT max_runtime_ms FROM arv2_quality_allowance "
                "WHERE job_id=:job AND workspace_id=:ws FOR NO KEY UPDATE"
            ),
            {"job": job_id, "ws": workspace_id},
        )
    ).one_or_none()
    if allowance is None:
        raise ResumeRefused(
            "invalid_top_up", "This job has no allowance yet; resume it without a top-up."
        )
    if top_up.runtime_minutes and allowance.max_runtime_ms == 0:
        raise ResumeRefused(
            "invalid_top_up", "This job's runtime is unlimited; drop the runtime top-up."
        )
    await conn.execute(
        text("""
      UPDATE arv2_quality_allowance SET max_model_calls=max_model_calls+:model,
        max_tool_calls=max_tool_calls+:tool, max_delegations=max_delegations+:delegation,
        max_runtime_ms=max_runtime_ms+:runtime
      WHERE job_id=:job AND workspace_id=:ws
    """),
        {
            "model": top_up.model_calls,
            "tool": top_up.tool_calls,
            "delegation": top_up.delegations,
            "runtime": top_up.runtime_minutes * 60_000,
            "job": job_id,
            "ws": workspace_id,
        },
    )


async def resume_research_job(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: UUID,
    actor: str,
    reason: str,
    top_up: TopUp = NO_TOP_UP,
    restart_fresh: bool = False,
) -> ResumeResult:
    """Take a stopped job back into the queue, audited (spec §3.5). One transaction: the
    caller's. Raises :class:`ResumeRefused` with a named code and writes nothing on refusal."""
    if not reason.strip():
        raise ResumeRefused("reason_required")
    if min(top_up.model_calls, top_up.tool_calls, top_up.delegations, top_up.runtime_minutes) < 0:
        raise ResumeRefused("invalid_top_up", "Top-ups are whole numbers, zero or more.")
    row = (
        await conn.execute(
            text(_JOBS + " WHERE j.job_id = :job AND j.workspace_id = :ws FOR UPDATE OF j"),
            {"job": job_id, "ws": workspace_id, "kind": FleetTaskKind.ARV2_ACCOUNT_RESEARCH.value},
        )
    ).one_or_none()
    if row is None:
        raise ResumeRefused("job_not_found")
    refusal = _refusal(row)
    if refusal is not None:
        raise ResumeRefused(refusal)
    if not top_up.is_empty():
        await _apply_top_up(conn, workspace_id=workspace_id, job_id=job_id, top_up=top_up)
    await conn.execute(
        text("""
      UPDATE arv2_research_job SET status='suspended', failure_code=NULL, failure_message=NULL,
        finished_at=NULL, updated_at=now(),
        restart_count=restart_count + CASE WHEN :restart THEN 1 ELSE 0 END
      WHERE job_id=:job AND workspace_id=:ws
    """),
        {"job": job_id, "ws": workspace_id, "restart": restart_fresh},
    )
    await offer_research_job(conn, job_id=job_id, run_id=row.run_id, workspace_id=workspace_id)
    await refresh_run_status(conn, run_id=row.run_id)
    await _audit(
        conn,
        workspace_id=workspace_id,
        job_id=job_id,
        attempt_before=row.attempt,
        actor=actor,
        reason=reason.strip(),
        top_up=top_up,
        restarted=restart_fresh,
    )
    return ResumeResult(
        job_id=job_id,
        status="suspended",
        attempt=row.attempt,
        restarted=restart_fresh,
        top_up_applied=top_up,
    )
