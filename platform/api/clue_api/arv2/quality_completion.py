"""Build research completion from durable deliverables, not model-copied bookkeeping.

The researcher owns summary and gaps. The platform owns identity, import receipts,
delegation references and publication state. No provider calls or claim mutations occur here.
"""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_coverage import coverage
from clue_api.arv2.quality_json_dossier import read_json_dossier
from clue_api.arv2.quality_policy import writes_pages_separately
from clue_api.arv2.quality_results import ResearchUnitReport, committee_references, validate_report
from clue_storage import StorageBackend

COMPLETION_INSTRUCTIONS = (
    "Completion contract: after the dossier import and your owned narrative are saved, "
    "call finalize_turn with your summary. You may save /outputs/research.json containing "
    "summary, gaps, and specific unprocessed_source_ids first. The backend supplies job/context "
    "IDs, imported claim IDs, committee references, delegated job IDs, and delivery receipts. "
    "You do not need to copy those IDs into a completion report. Existing report bookkeeping "
    "is rebuilt from storage. If finalization reports missing work, correct only that stage "
    "using saved results; do not repeat acquisition or import already-completed research."
)


class CompletionNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=6000)
    gaps: tuple[str, ...] = Field(default=(), max_length=100)
    unprocessed_source_ids: tuple[UUID, ...] = Field(default=(), max_length=5000)


def completion_notes(raw: str | None, summary: str | None) -> CompletionNotes:
    """Retain human-meaningful notes from legacy reports; ignore their mechanical IDs."""
    try:
        payload = json.loads(raw) if raw is not None else {"summary": summary}
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
        for field in ResearchUnitReport.model_fields.keys() - CompletionNotes.model_fields.keys():
            payload.pop(field, None)
        return CompletionNotes.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        raise ValueError(
            "/outputs/research.json: provide a non-empty summary, gaps as a list of strings, "
            "and optional unprocessed_source_ids from the evidence index. Correct this notes "
            "file before retrying finalize_turn. Saved dossiers, claims and pages remain stored. "
            f"Details: {exc}"
        ) from exc


async def build_completion_report(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    notes: CompletionNotes,
) -> ResearchUnitReport:
    saved = await read_json_dossier(conn, storage, scope, context_id)
    if saved["state"] != "complete" or not saved.get("receipt", {}).get("complete"):
        raise ValueError(
            "Research dossier import is incomplete. Read /research/dossier/latest.json, "
            "finish or repair its existing draft and call finish_dossier, then retry "
            "finalize_turn. Reuse saved evidence; continue only genuinely unfinished research. "
            "Do not restart acquisition merely to repair completion bookkeeping."
        )
    claim_ids = tuple(UUID(e["claim_id"]) for e in saved["receipt"]["entries"])
    measured = await coverage(conn, scope, context_id)
    # Recipes 20-24: the researcher writes its own pages before finishing. From 25 the driver's
    # page writer writes them after this report, so missing pages are expected here.
    if (
        measured["missing_pages"]
        and int((scope.input_refs or {}).get("quality_recipe_version", 0)) >= 20
        and not writes_pages_separately(scope)
    ):
        missing = ", ".join(cast(list[str], measured["missing_pages"]))
        raise ValueError(
            f"Research import is already stored; narrative publication is incomplete ({missing}). "
            "Call read_narrative_inputs, then write_research_narrative for those owned pages "
            "using its dossier versions. Inspect the receipt and retry finalize_turn. "
            "Do not repeat the research or claim import."
        )
    children: tuple[UUID, ...] = ()
    if not scope.person_subject_id:
        children = tuple(
            (
                await conn.execute(
                    text("""SELECT j.job_id FROM arv2_research_job j
                    WHERE j.workspace_id=:ws AND j.run_id=:run AND j.account_entity_id=:account
                      AND j.subject_type='person' AND (
                        j.input_refs->>'parent_job_id'=:parent OR EXISTS (
                          SELECT 1 FROM arv2_generation_child c
                          JOIN arv2_account_research_generation g
                            ON g.generation_id=c.generation_id AND g.workspace_id=c.workspace_id
                          WHERE c.workspace_id=j.workspace_id AND c.job_id=j.job_id
                            AND g.run_id=j.run_id AND g.account_id=j.account_entity_id
                            AND g.context_id=:context AND g.initial_job_id=CAST(:parent AS uuid)))
                    ORDER BY j.job_id"""),
                    {
                        "ws": scope.workspace_id,
                        "run": scope.run_id,
                        "account": scope.account_id,
                        "parent": str(scope.job_id),
                        "context": context_id,
                    },
                )
            ).scalars()
        )
    pages = (
        (
            await conn.execute(
                text("""SELECT DISTINCT p.page,b.output_artifact_key AS artifact_key
                FROM arv2_research_page_current p
                JOIN arv2_account_research_generation g ON g.generation_id=p.generation_id
                JOIN display_block b ON b.workspace_id=p.workspace_id AND b.context_id=p.context_id
                  AND b.subject_id=p.subject_id AND b.page=p.page
                  AND b.generation_id=p.generation_id AND b.superseded_at IS NULL
                WHERE p.workspace_id=:ws AND p.context_id=:context AND p.subject_id=:subject
                  AND g.run_id=:run ORDER BY p.page"""),
                {
                    "ws": scope.workspace_id,
                    "context": context_id,
                    "run": scope.run_id,
                    "subject": scope.person_subject_id or scope.account_id,
                },
            )
        )
        .mappings()
        .all()
    )
    report = ResearchUnitReport(
        context_id=context_id,
        job_id=scope.job_id,
        **notes.model_dump(),
        claim_ids=claim_ids,
        committee_assessment_ids=await committee_references(conn, scope, context_id),
        pending_person_job_ids=children,
        delivery={
            "dossier_saved": True,
            "claims_imported": True,
            "dossier_version": saved["version"],
            "dossier_artifact_key": saved["artifact_key"],
            "imported_findings": len(claim_ids),
            "narrative_published": not measured["missing_pages"],
            "narrative_pages": [dict(p) for p in pages],
        },
    )
    await validate_report(conn, scope, context_id, report)
    return report
