"""``GET /frontend/v1/projects/{project_id}/research/progress`` — the pinned card (spec 2026-09-12).

Loads every job of the project's runs that are not all terminal, plus runs whose last job finished
within the linger window, and folds them with ``arv2.research_progress.fold_progress``. ARV2 tables
only (ruling 2026-09-09): the run and job rows are the whole truth, and every number and string on
the wire comes out of the pure fold — this module invents no display text of its own.

The wire models live here rather than in ``contract_v1``: that module's ``V1Model`` base is
camelCase-on-the-wire (``alias_generator=to_camel``) while this document is snake_case by spec, so
it carries the same frozen/extra-forbid discipline without the aliasing — exactly as
``discovery_status`` does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from clue_api.arv2.account_research_store import JobStage, JobSubject
from clue_api.arv2.research_progress import (
    ATTENTION_LINGER_S,
    LINGER_S,
    ProgressJob,
    fold_progress,
)
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.v1_shared import iso_utc
from clue_db import ConnFactory

__all__ = [
    "ResearchProgressAgentV1",
    "ResearchProgressAttentionV1",
    "ResearchProgressResponseV1",
    "ResearchProgressV1",
    "register_research_progress_route",
]


class ResearchProgressAgentV1(BaseModel):
    """One job the fleet is running right now — an "agent" row on the card."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str
    stage: str
    subject: Literal["account", "person"]


class ResearchProgressAttentionV1(BaseModel):
    """One job a human has to look at, with the driver's own reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str
    reason: str


class ResearchProgressV1(BaseModel):
    """The pinned research progress card (spec 2026-09-12 §2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_accounts: int
    queued: int
    running: int
    finished: int
    progress_pct: int
    pill: Literal["running", "completed", "needs_attention"]
    last_finished_at: str | None
    agents: list[ResearchProgressAgentV1]
    attention: list[ResearchProgressAttentionV1]


class ResearchProgressResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: ResearchProgressV1 | None


#: Every job of every run the card still has something to say about. A run qualifies when it has a
#: job that is not finished, a recent job that wants a human, a run-level suspension, or a last job
#: that finished inside the linger window (the fold decides what the card then *says*; the linger
#: bound is repeated here only so a long-finished run is not loaded at all).
#:
#: Ruling R11 (provisional, 2026-09-12) — the ATTENTION clause is time-bounded. Nothing in the
#: system moves a job out of ``needs_review`` (``begin_job`` re-claims only ``not_started`` and
#: ``suspended``) and the card has no dismiss control, so an unbounded clause would pin "Needs
#: attention" above a project's composer forever and dilute every later run's percentage. A job
#: that wants a human keeps its run loaded for ``ATTENTION_LINGER_S``, measured from when it
#: finished; a ``suspended`` job has no ``finished_at`` by construction (the row CHECK) and counts
#: as happening NOW, so a genuinely paused run is never hidden while it waits for a worker.
#: ``max(COALESCE(...))`` rather than ``COALESCE(max(...))`` on purpose: it makes a *single*
#: still-paused job keep the run, and it stays NULL (→ not qualifying) when the run has no such
#: job at all.
_JOBS = text(
    """
    WITH runs AS (
        SELECT r.run_id, r.status
        FROM arv2_research_run r
        WHERE r.workspace_id = :workspace_id AND r.project_id = :project_id
          AND (
            EXISTS (SELECT 1 FROM arv2_research_job j WHERE j.run_id = r.run_id
                     AND j.status NOT IN ('completed', 'needs_review', 'suspended'))
            OR (SELECT max(COALESCE(j.finished_at, now())) FROM arv2_research_job j
                 WHERE j.run_id = r.run_id AND j.status IN ('needs_review', 'suspended'))
               > now() - make_interval(secs => :attention_linger_s)
            OR r.status = 'suspended'
            OR (SELECT max(j.finished_at) FROM arv2_research_job j WHERE j.run_id = r.run_id)
               > now() - make_interval(secs => :linger_s)
          )
    )
    SELECT j.run_id, runs.status AS run_status, j.job_id, j.account_entity_id,
           a.canonical_name, j.subject_type, j.status, j.stage, j.started_at, j.finished_at,
           j.failure_message
    FROM arv2_research_job j
    JOIN runs ON runs.run_id = j.run_id
    JOIN account_entity a
      ON a.id = j.account_entity_id AND a.workspace_id = j.workspace_id
    ORDER BY j.started_at NULLS LAST, j.job_id
    """
)


def register_research_progress_route(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    """Register the research-progress poll on the workspace-scoped ``/frontend/v1`` router."""

    @router.get(
        "/projects/{project_id}/research/progress", response_model=ResearchProgressResponseV1
    )
    async def get_research_progress(
        project_id: str, workspace_id: WorkspaceDep
    ) -> ResearchProgressResponseV1:
        async with conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        _JOBS,
                        {
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "linger_s": LINGER_S,
                            "attention_linger_s": ATTENTION_LINGER_S,
                        },
                    )
                )
                .mappings()
                .all()
            )
        jobs = [
            ProgressJob(
                run_id=row["run_id"],
                job_id=row["job_id"],
                account_entity_id=row["account_entity_id"],
                account_name=str(row["canonical_name"]),
                # Both columns carry the store's own vocabulary, held to it by the
                # ``arv2_research_job_subject_type`` / ``_stage`` CHECKs.
                subject_type=cast(JobSubject, row["subject_type"]),
                status=str(row["status"]),
                stage=cast("JobStage | None", row["stage"]),
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                failure_message=row["failure_message"],
            )
            for row in rows
        ]
        run_statuses = {row["run_id"]: str(row["run_status"]) for row in rows}
        card = fold_progress(
            jobs, run_statuses=run_statuses, now=datetime.now(UTC), linger_s=LINGER_S
        )
        if card is None:
            return ResearchProgressResponseV1(data=None)
        return ResearchProgressResponseV1(
            data=ResearchProgressV1(
                requested_accounts=card.requested_accounts,
                queued=card.queued,
                running=card.running,
                finished=card.finished,
                progress_pct=card.progress_pct,
                pill=card.pill,
                last_finished_at=(
                    iso_utc(card.last_finished_at) if card.last_finished_at is not None else None
                ),
                agents=[
                    ResearchProgressAgentV1(
                        account_name=agent.account_name,
                        stage=agent.stage,
                        subject=agent.subject,
                    )
                    for agent in card.agents
                ],
                attention=[
                    ResearchProgressAttentionV1(account_name=item.account_name, reason=item.reason)
                    for item in card.attention
                ],
            )
        )
