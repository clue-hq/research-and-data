"""Project-scoped prior research, without treating earlier findings as verified truth.

This is a read surface over existing records, not another evidence store. Copied passages retain
their original artifact so erasure propagates through the ordinary research artifact sink.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_storage import retain_artifact


async def history_page(
    conn: AsyncConnection,
    scope: JobScope,
    *,
    kind: Literal["claims", "sources"],
    offset: int = 0,
    limit: int = 10,
    item_id: UUID | None = None,
    before: datetime | None = None,
) -> dict[str, Any]:
    """Read only research purchased by this workspace/project for this account and subject.

    Old context IDs and superseded/disputed states remain visible, explicitly labelled. Neither
    their presence nor absence grants committee membership or changes publication policy.
    """
    params = {
        "ws": scope.workspace_id,
        "project": scope.project_id,
        "account": scope.account_id,
        "person": scope.person_subject_id,
        "id": item_id,
        "before": before,
        "offset": offset,
        "limit": limit,
    }
    # A previous contact job establishes relevance to this account, not verified employment.
    subjects = """(x.{subject}=:account OR (
        (CAST(:person AS uuid) IS NULL OR x.{subject}=CAST(:person AS uuid)) AND EXISTS (
          SELECT 1 FROM arv2_research_job j JOIN arv2_research_run jr
            ON jr.run_id=j.run_id AND jr.workspace_id=j.workspace_id
          WHERE j.workspace_id=:ws AND jr.project_id=:project
            AND j.account_entity_id=:account AND j.subject_entity_id=x.{subject}
            AND COALESCE(j.input_refs->>'privacy_stopped','false')<>'true')))
    """
    live = """(a.storage_key IS NOT NULL AND a.erased_at IS NULL AND NOT a.privacy_erased
        AND (a.expires_at IS NULL OR a.expires_at>now()))"""
    if kind == "sources":
        statement = f"""
          SELECT x.source_id AS id,x.subject_id AS entity_id,x.kind,x.source_url,x.observed_at,
                 x.run_id,x.artifact_key,x.artifact_sha256,x.media_type,x.byte_size,
                 x.origin_locator,x.metadata,r.context_id,count(*) OVER () AS total
          FROM arv2_evidence_source x JOIN arv2_research_run r
            ON r.run_id=x.run_id AND r.workspace_id=x.workspace_id
          JOIN artifact a ON a.storage_key=x.artifact_key AND a.workspace_id=x.workspace_id
          WHERE x.workspace_id=:ws AND r.project_id=:project AND x.account_id=:account
            AND {subjects.format(subject="subject_id")} AND {live}
            AND EXISTS (SELECT 1 FROM arv2_research_job owner
              WHERE owner.workspace_id=:ws AND owner.job_id=x.job_id
                AND COALESCE(owner.input_refs->>'privacy_stopped','false')<>'true')
            AND (CAST(:id AS uuid) IS NULL OR x.source_id=CAST(:id AS uuid))
            AND (CAST(:before AS timestamptz) IS NULL OR x.observed_at<=:before)
          ORDER BY x.observed_at DESC,x.source_id OFFSET :offset LIMIT :limit
        """
    else:
        statement = f"""
          SELECT x.id,x.entity_id,x.field_key,x.value_json,x.source_url,x.evidence_span,
                 x.observed_at,x.collected_at,x.run_id,x.artifact_key,x.superseded_by,
                 x.write_markers,q.conclusion AS assessment,q.rationale_key,
                 x.write_markers->>'context_id' AS context_id,count(*) OVER () AS total
          FROM claim x LEFT JOIN claim_quality_current q ON q.claim_id=x.id
          LEFT JOIN artifact a ON a.storage_key=x.artifact_key AND a.workspace_id=x.workspace_id
          WHERE x.workspace_id=:ws AND {subjects.format(subject="entity_id")}
            AND EXISTS (SELECT 1 FROM arv2_research_run r WHERE r.workspace_id=:ws
              AND r.project_id=:project AND (r.run_id=x.run_id OR r.project_run_id=x.run_id))
            AND (x.artifact_key IS NULL OR {live})
            AND NOT EXISTS (SELECT 1 FROM claim_quality_support s JOIN artifact sa
              ON sa.storage_key=s.artifact_key WHERE s.assessment_id=q.assessment_id
              AND (sa.erased_at IS NOT NULL OR sa.privacy_erased OR sa.expires_at<=now()))
            AND (CAST(:id AS uuid) IS NULL OR x.id=CAST(:id AS uuid))
            AND (CAST(:before AS timestamptz) IS NULL OR x.collected_at<=:before)
          ORDER BY x.collected_at DESC,x.id OFFSET :offset LIMIT :limit
        """
    rows = (await conn.execute(text(statement), params)).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        item.pop("total")
        item["path"] = f"/research/history/{kind}/{item['id']}/0.json"
        items.append(item)
    total = int(rows[0]["total"]) if rows else 0
    return {
        "kind": "prior_research_not_fresh_verification",
        "items": items,
        "total": total,
        "next_path": f"/research/history/{kind}/{offset + limit}.json"
        if offset + limit < total
        else None,
    }


async def retain_history(
    conn: AsyncConnection, scope: JobScope, items: list[dict[str, Any]]
) -> None:
    """Link copied prior evidence to this job's existing privacy/retention machinery."""
    keys = {item["artifact_key"] for item in items if item.get("artifact_key")}
    claim_ids = [item["id"] for item in items if "field_key" in item]
    if claim_ids:
        keys.update(
            (
                await conn.execute(
                    text("""
          SELECT s.artifact_key FROM claim_quality_support s
          JOIN claim_quality_current q ON q.assessment_id=s.assessment_id
          JOIN claim c ON c.id=q.claim_id WHERE c.workspace_id=:ws AND c.id=ANY(:ids)
        """),
                    {"ws": scope.workspace_id, "ids": claim_ids},
                )
            ).scalars()
        )
    for key in sorted(keys):
        await retain_artifact(
            conn,
            workspace_id=scope.workspace_id,
            storage_key=key,
            reference_kind="research_prior_source",
            reference_id=str(scope.job_id),
        )
