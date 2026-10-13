"""Typed root completion and measured coverage, checked before durable finalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol
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
    # Backend-generated delivery evidence; old saved reports remain readable.
    delivery: dict[str, object] = Field(default_factory=dict)


async def committee_references(
    conn: AsyncConnection, scope: JobScope, context_id: UUID
) -> tuple[UUID, ...]:
    """Account-owned contextual references, restricted to this person when applicable."""
    return tuple(
        (
            await conn.execute(
                text("""SELECT c.id FROM claim c
                JOIN claim_quality_current q ON q.claim_id=c.id
                WHERE c.workspace_id=:ws AND c.entity_id=:account AND q.context_id=:context
                  AND c.field_key IN (:committee,:selection)
                  AND (CAST(:contact AS text) IS NULL OR c.value_json->>'contact_id'=:contact)
                ORDER BY c.id"""),
                {
                    "ws": scope.workspace_id,
                    "account": scope.account_id,
                    "context": context_id,
                    "contact": str(scope.person_subject_id) if scope.person_subject_id else None,
                    "committee": COMMITTEE,
                    "selection": SELECTION,
                },
            )
        ).scalars()
    )


def report_error(field: str, ids: set[UUID], instruction: str) -> ValueError:
    examples = ", ".join(str(i) for i in sorted(ids)[:5])
    return ValueError(
        f"/outputs/research.json: invalid {field} [{examples}]. {instruction} "
        "Correct the saved report before retrying finalize_turn; changing its user_message "
        "does not change the report. Previously saved research remains stored."
    )


async def validate_report(
    conn: AsyncConnection, scope: JobScope, context_id: UUID, report: ResearchUnitReport
) -> None:
    if (report.context_id, report.job_id) != (context_id, scope.job_id):
        raise ValueError("research output differs from its pinned task")
    ids = set(report.claim_ids)
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
    invalid = ids - {row.id for row in rows}
    if invalid:
        raise report_error(
            "claim_ids",
            invalid,
            "Use only this subject's imported claim IDs. Account-owned committee evidence "
            "belongs in committee_assessment_ids, not person claim_ids.",
        )
    invalid = set(report.committee_assessment_ids) - set(
        await committee_references(conn, scope, context_id)
    )
    if invalid:
        raise report_error(
            "committee_assessment_ids",
            invalid,
            "Use committee selection/assessment claims owned by this account in this context; "
            "a person report may reference only assessments about that same person.",
        )
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
            raise report_error(
                "pending_person_job_ids",
                set(report.pending_person_job_ids) - set(jobs),
                "Use only this account job's delegated person-job IDs. A person job has no "
                "delegated person jobs. If listed IDs are correct, the stored delegation "
                "needs backend repair; do not invent replacements.",
            )
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
            raise report_error(
                "unprocessed_source_ids",
                set(report.unprocessed_source_ids) - set(sources),
                "Copy source UUIDs from /evidence/index.json in this run, or remove an "
                "incorrect reference. Do not substitute a URL or evidence path.",
            )


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
    reconciliation_reply: dict[str, Any] | None = None
    #: Recipe 26+: pages left for the account's final page step (a person's ``contact`` page
    #: while the account has not imported yet). Coverage does not count them as missing.
    deferred_pages: tuple[str, ...] = ()


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
        reconciliation: dict[str, Any] | None = None,
    ) -> QualityJobOutcome: ...
