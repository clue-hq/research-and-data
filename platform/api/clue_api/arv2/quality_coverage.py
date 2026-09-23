"""Measured activity for completion and recovery; never inferred from a model's final prose."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_policy import advisory_research


async def coverage(conn: AsyncConnection, scope: JobScope, context_id: UUID) -> dict[str, object]:
    params = {
        "ws": scope.workspace_id,
        "job": scope.job_id,
        "context": context_id,
        "subject": scope.person_subject_id or scope.account_id,
        "account": scope.account_id,
        "run": scope.run_id,
    }
    source_rows = (
        await conn.execute(
            text("""SELECT s.source_id,s.kind,
        count(d.disposition_id) AS units,
        count(d.disposition_id) FILTER
          (WHERE d.decision IN ('gap','unprocessed','conflict')) AS gaps
        FROM arv2_evidence_source s LEFT JOIN arv2_evidence_disposition d
          ON d.source_id=s.source_id AND d.workspace_id=s.workspace_id
        WHERE s.workspace_id=:ws AND s.job_id=:job GROUP BY s.source_id,s.kind
        ORDER BY s.source_id"""),
            params,
        )
    ).all()
    media = (
        (
            await conn.execute(
                text("""SELECT kind,outcome,count(*) AS count
        FROM arv2_media_attempt WHERE workspace_id=:ws AND job_id=:job
        GROUP BY kind,outcome ORDER BY kind,outcome"""),
                params,
            )
        )
        .mappings()
        .all()
    )
    proposals = (
        (
            await conn.execute(
                text("""SELECT status,count(*) AS count
        FROM arv2_quality_proposal WHERE workspace_id=:ws AND job_id=:job
        GROUP BY status ORDER BY status"""),
                params,
            )
        )
        .mappings()
        .all()
    )
    operations = (
        (
            await conn.execute(
                text("""SELECT kind,state,error_code,count(*) AS count
        FROM arv2_research_operation WHERE workspace_id=:ws AND job_id=:job
          AND kind LIKE 'quality_tool:%' GROUP BY kind,state,error_code
          ORDER BY kind,state,error_code"""),
                params,
            )
        )
        .mappings()
        .all()
    )
    pointers = (
        await conn.execute(
            text("""SELECT p.page,p.dependency_sha256
        FROM arv2_research_page_current p
        JOIN arv2_account_research_generation g ON g.generation_id=p.generation_id
        WHERE p.workspace_id=:ws AND p.context_id=:context AND p.subject_id=:subject
          AND g.run_id=:run"""),
            params,
        )
    ).all()
    from clue_api.arv2.quality_page_inputs import page_inputs

    pages = set()
    for pointer in pointers:
        try:
            inputs = await page_inputs(conn, scope, context_id=context_id, page=pointer.page)
        except ValueError:
            continue
        if advisory_research(scope) or inputs.sha256 == pointer.dependency_sha256:
            pages.add(pointer.page)
    required = {"contact"} if scope.person_subject_id else {"overview", "insights"}
    unprocessed = [
        str(r.source_id) for r in source_rows if r.units == 0 and r.kind != "acquisition_gap"
    ]
    missing = sorted(required - pages)
    claims = (
        (
            await conn.execute(
                text("""SELECT q.conclusion,count(*) AS count FROM claim c
        JOIN claim_quality_current q ON q.claim_id=c.id
        WHERE c.workspace_id=:ws AND c.entity_id=:subject AND q.context_id=:context
          AND c.superseded_by IS NULL GROUP BY q.conclusion ORDER BY q.conclusion"""),
                params,
            )
        )
        .mappings()
        .all()
    )
    return {
        "schema_version": "research-coverage-v1",
        "source_count": len(source_rows),
        "processed_units": sum(r.units for r in source_rows),
        "unprocessed_source_ids": unprocessed,
        "unresolved_units": sum(r.gaps for r in source_rows),
        "media_activity": [dict(r) for r in media],
        "acquisition_activity": [dict(r) for r in operations],
        "proposal_outcomes": [dict(r) for r in proposals],
        "claim_quality": [dict(r) for r in claims],
        "published_pages": sorted(pages),
        "missing_pages": missing,
        "needs_review": bool(missing or (unprocessed and not advisory_research(scope))),
        "limitations": [
            "Processed units do not prove exhaustive source coverage.",
            "Discovered media candidates are not consumed transcripts.",
        ],
    }
