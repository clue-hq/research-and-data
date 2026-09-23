"""Typed root completion and measured coverage, checked before durable finalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_relationships import COMMITTEE, SELECTION


class ResearchUnitReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["research-unit-v1"] = "research-unit-v1"
    context_id: UUID
    job_id: UUID
    summary: str = Field(min_length=1, max_length=6000)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=5000)
    committee_assessment_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    pending_person_job_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    gaps: tuple[str, ...] = Field(default=(), max_length=100)
    unprocessed_source_ids: tuple[UUID, ...] = Field(default=(), max_length=5000)


async def validate_report(
    conn: AsyncConnection, scope: JobScope, context_id: UUID, report: ResearchUnitReport
) -> None:
    if (report.context_id, report.job_id) != (context_id, scope.job_id):
        raise ValueError("research output differs from its pinned task")
    ids = set(report.claim_ids) | set(report.committee_assessment_ids)
    rows = (
        (
            await conn.execute(
                text("""SELECT c.id,c.field_key FROM claim c
        JOIN claim_quality_current q ON q.claim_id=c.id
        WHERE c.workspace_id=:ws AND c.entity_id=:subject
          AND q.context_id=:context AND c.id=ANY(:ids)"""),
                {
                    "ws": scope.workspace_id,
                    "subject": scope.person_subject_id or scope.account_id,
                    "context": context_id,
                    "ids": sorted(ids),
                },
            )
        ).all()
        if ids
        else []
    )
    if {row.id for row in rows} != ids or any(
        row.field_key not in (COMMITTEE, SELECTION)
        for row in rows
        if row.id in report.committee_assessment_ids
    ):
        raise ValueError("output claim references are unavailable or outside this task context")
    if report.pending_person_job_ids:
        jobs = (
            (
                await conn.execute(
                    text("""SELECT job_id FROM arv2_research_job
            WHERE workspace_id=:ws AND run_id=:run AND account_entity_id=:account
              AND subject_type='person' AND input_refs->>'parent_job_id'=:parent
              AND job_id=ANY(:ids)"""),
                    {
                        "ws": scope.workspace_id,
                        "run": scope.run_id,
                        "account": scope.account_id,
                        "parent": str(scope.job_id),
                        "ids": list(report.pending_person_job_ids),
                    },
                )
            )
            .scalars()
            .all()
        )
        if set(jobs) != set(report.pending_person_job_ids):
            raise ValueError("output names person work not created by this account")
    if report.unprocessed_source_ids:
        sources = (
            (
                await conn.execute(
                    text("""SELECT source_id FROM arv2_evidence_source
            WHERE workspace_id=:ws AND run_id=:run
              AND account_id=:account AND source_id=ANY(:ids)"""),
                    {
                        "ws": scope.workspace_id,
                        "run": scope.run_id,
                        "account": scope.account_id,
                        "ids": list(report.unprocessed_source_ids),
                    },
                )
            )
            .scalars()
            .all()
        )
        if set(sources) != set(report.unprocessed_source_ids):
            raise ValueError("output names an unavailable original")


# The ARV2 lane receives this seam from the API composition root; it never imports another
# agent runtime implementation or constructs an independent model/provider client.

if TYPE_CHECKING:
    from clue_api.arv2.account_research_tools import ToolRuntime


@dataclass(frozen=True)
class QualityJobOutcome:
    execution_id: UUID
    status: str
    finalization_key: str | None
    report: ResearchUnitReport | None
    failure_code: str | None


class QualityJobRunner(Protocol):
    async def __call__(
        self,
        *,
        scope: JobScope,
        context_id: UUID,
        runtime: ToolRuntime,
        objective: str,
        model_id: str,
        unit_key: str | None = None,
    ) -> QualityJobOutcome: ...
