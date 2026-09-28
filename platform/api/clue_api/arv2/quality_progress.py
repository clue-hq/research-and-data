"""Read-only, batched projection of researcher milestones for product progress.

This never changes execution status or decides research quality. Narrative publication is
already guarded by the dossier importer and page writer; progress reads their durable outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

DOSSIER_PROGRESS_KIND = "research_dossier_progress"


@dataclass(frozen=True)
class DeliveryProgress:
    stage: str
    ready: bool
    ready_at: datetime | None
    subject_name: str | None


async def delivery_progress(
    conn: AsyncConnection, *, workspace_id: str, job_ids: list[UUID]
) -> dict[UUID, DeliveryProgress]:
    if not job_ids:
        return {}
    rows = (
        (
            await conn.execute(
                text("""
    SELECT j.job_id,j.subject_type,j.input_refs,j.status,c.full_name AS person_name,
      d.reference_id AS dossier_marker,d.created_at AS dossier_at,d.available AS dossier_available,
      t.tool_name,t.created_at AS tool_at,p.pages,p.ready_at
    FROM arv2_research_job j
    JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
    LEFT JOIN contact_entity c ON c.id=j.subject_entity_id AND c.workspace_id=j.workspace_id
    LEFT JOIN LATERAL (
      SELECT ref.reference_id,ref.created_at,
        (a.erased_at IS NULL AND NOT a.privacy_erased
          AND (a.expires_at IS NULL OR a.expires_at>now())) AS available
      FROM artifact_reference ref
      JOIN artifact a ON a.storage_key=ref.storage_key AND a.workspace_id=ref.workspace_id
      WHERE ref.workspace_id=j.workspace_id AND ref.reference_kind=:kind
        AND ref.reference_id LIKE j.job_id::text || ':%'
      ORDER BY ref.reference_id DESC LIMIT 1
    ) d ON true
    LEFT JOIN LATERAL (
      SELECT n.tool_name,n.created_at FROM arv2_quality_execution q
      JOIN execution_node n ON n.execution_id=q.execution_id
      WHERE q.workspace_id=j.workspace_id AND q.job_id=j.job_id
        AND q.parent_execution_id IS NULL
        AND n.tool_name IN ('save_dossier_section','update_dossier_findings',
          'finish_dossier','read_narrative_inputs','write_research_narrative')
      ORDER BY n.created_at DESC,n.id DESC LIMIT 1
    ) t ON true
    LEFT JOIN LATERAL (
      SELECT array_agg(v.page) AS pages,max(v.generated_at) AS ready_at FROM (
        SELECT p.page,max(b.generated_at) AS generated_at
        FROM arv2_research_page_current p
        JOIN arv2_account_research_generation g ON g.generation_id=p.generation_id
          AND g.workspace_id=p.workspace_id AND g.run_id=j.run_id
          AND g.account_id=j.account_entity_id AND g.context_id=r.context_id
        JOIN display_block b ON b.workspace_id=p.workspace_id AND b.context_id=p.context_id
          AND b.project_id=p.project_id AND b.generation_id=p.generation_id
          AND b.subject_id=p.subject_id AND b.page=p.page AND b.superseded_at IS NULL
        JOIN artifact a ON a.storage_key=b.output_artifact_key AND a.workspace_id=b.workspace_id
        WHERE p.workspace_id=j.workspace_id AND p.project_id=r.project_id
          AND p.context_id=r.context_id
          AND p.subject_id=COALESCE(j.subject_entity_id,j.account_entity_id)
          AND g.state NOT IN ('privacy_stopped','suspended')
        GROUP BY p.page
        HAVING bool_and(a.erased_at IS NULL AND NOT a.privacy_erased
          AND (a.expires_at IS NULL OR a.expires_at>now()))
          AND (d.created_at IS NULL OR min(b.generated_at)>=d.created_at)
      ) v
    ) p ON true
    WHERE j.workspace_id=:ws AND j.job_id=ANY(:jobs)
    """),
                {"ws": workspace_id, "jobs": job_ids, "kind": DOSSIER_PROGRESS_KIND},
            )
        )
        .mappings()
        .all()
    )
    result = {}
    for row in rows:
        refs = row["input_refs"] or {}
        if (
            not row["tool_name"]
            and not row["dossier_marker"]
            and int(refs.get("quality_recipe_version", 0)) < 20
        ):
            continue
        marker_state = (row["dossier_marker"] or "").rsplit(":", 1)[-1]
        required = {"contact"} if row["subject_type"] == "person" else {"overview", "insights"}
        ready = required <= set(row["pages"] or []) and marker_state in ("", "complete")
        ready = (
            ready
            and row["dossier_available"] is not False
            and refs.get("privacy_stopped") not in (True, "true")
        )
        tool = row["tool_name"]
        stage = "researching"
        if row["dossier_marker"] or tool in ("save_dossier_section", "update_dossier_findings"):
            stage = "compiling_findings"
        if tool == "finish_dossier" or marker_state == "import_pending":
            stage = "storing_claims"
        if tool in ("read_narrative_inputs", "write_research_narrative") or (
            marker_state == "complete"
            and (row["tool_at"] is None or row["dossier_at"] >= row["tool_at"])
        ):
            stage = "writing_narrative"
        result[row["job_id"]] = DeliveryProgress(
            "completed" if ready else stage,
            ready,
            row["ready_at"] if ready else None,
            row["person_name"] if row["subject_type"] == "person" else None,
        )
    return result
