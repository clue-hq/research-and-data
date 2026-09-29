"""``GET /frontend/v1/projects/{project_id}/research/progress`` — the pinned card (spec 2026-09-12).

Loads every job of the project's runs that are not all terminal, plus runs whose last job finished
within the linger window, and folds them with ``arv2.research_progress.fold_progress``. ARV2 tables
and persisted dossier/page milestones are projected together. Execution status is preserved;
the pure fold determines the product-facing progress and completion state.

The wire models live here rather than in ``contract_v1``: that module's ``V1Model`` base is
camelCase-on-the-wire (``alias_generator=to_camel``) while this document is snake_case by spec, so
it carries the same frozen/extra-forbid discipline without the aliasing — exactly as
``discovery_status`` does.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from clue_api.arv2.account_research_store import JobStage, JobSubject
from clue_api.arv2.quality_progress import delivery_progress
from clue_api.arv2.research_progress import (
    ATTENTION_LINGER_S,
    LINGER_S,
    ProgressJob,
    fold_progress,
)
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.v1_shared import iso_utc
from clue_api.provider_incidents import open_incidents, provider_display, reason_words
from clue_core.provider_failures import parse_failure_code
from clue_db import ConnFactory

__all__ = [
    "ResearchProgressAgentV1",
    "ResearchProgressAttentionV1",
    "ResearchProgressIncidentV1",
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
    subject_name: str | None = None


class ResearchProgressAttentionV1(BaseModel):
    """One job a human has to look at, with the driver's own reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_name: str
    reason: str


class ResearchProgressIncidentV1(BaseModel):
    """The open provider incident behind the card's attention rows, when there is one.

    Read from ``provider_incident`` for the provider named by the most recent job whose
    ``failure_code`` parses — the card says *why* the work stopped rather than only that it did.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_label: str
    reason_label: str
    since: str
    affected: int
    notified: bool


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
    incident: ResearchProgressIncidentV1 | None = None


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
           j.failure_message, j.failure_code
    FROM arv2_research_job j
    JOIN runs ON runs.run_id = j.run_id
    JOIN account_entity a
      ON a.id = j.account_entity_id AND a.workspace_id = j.workspace_id
    ORDER BY j.started_at NULLS LAST, j.job_id
    """
)


def _notified(reason: str, incident: ResearchProgressIncidentV1 | None) -> str:
    """The fold's sentence, with the "Clue has been notified." clause when Sentry was told.

    The fold is pure and cannot know whether the incident carries a Sentry event id, so it never
    claims we were told. Only a row the fold wrote from THIS incident is rewritten — it must start
    with the incident's own provider label and end on the sentence's full stop — so a plain
    failure message that happens to sit next to a provider incident is left alone.
    """
    if incident is None or not incident.notified:
        return reason
    if not reason.startswith(incident.provider_label) or not reason.endswith("."):
        return reason
    return reason + " Clue has been notified."


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
            deliveries = await delivery_progress(
                conn, workspace_id=workspace_id, job_ids=[row["job_id"] for row in rows]
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
                failure_code=row["failure_code"],
            )
            for row in rows
        ]
        jobs = [
            replace(
                j,
                delivery_stage=d.stage,
                deliverables_ready=d.ready,
                delivered_at=d.ready_at,
                subject_name=d.subject_name,
            )
            if (d := deliveries.get(j.job_id)) is not None
            else j
            for j in jobs
        ]
        run_statuses = {row["run_id"]: str(row["run_status"]) for row in rows}
        card = fold_progress(
            jobs, run_statuses=run_statuses, now=datetime.now(UTC), linger_s=LINGER_S
        )
        if card is None:
            return ResearchProgressResponseV1(data=None)
        # The provider named by the most recently finished job whose code parses decides which
        # incident the card shows; a second connection because the fold runs outside the first.
        newest: datetime | None = None
        provider: str | None = None
        for job in jobs:
            parsed = parse_failure_code(job.failure_code)
            if parsed is None or job.finished_at is None or job.deliverables_ready:
                continue
            if newest is None or job.finished_at > newest:
                newest, provider = job.finished_at, parsed[0]
        incident: ResearchProgressIncidentV1 | None = None
        if provider is not None:
            async with conn_factory() as conn:
                live = await open_incidents(conn, providers=[provider])
            if live:
                incident = ResearchProgressIncidentV1(
                    provider_label=provider_display(live[0].provider),
                    reason_label=reason_words(live[0].reason),
                    since=iso_utc(live[0].opened_at),
                    affected=live[0].failure_count,
                    notified=live[0].notified,
                )
        attention = [
            ResearchProgressAttentionV1(
                account_name=item.account_name,
                reason=_notified(item.reason, incident),
            )
            for item in card.attention
        ]
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
                        subject_name=agent.subject_name,
                    )
                    for agent in card.agents
                ],
                attention=attention,
                incident=incident,
            )
        )
