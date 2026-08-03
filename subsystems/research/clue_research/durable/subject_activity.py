"""Reference-only, exact-subject research/execution activity authority."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId, EntityType, ProjectRunId, RunId


class SubjectActivityRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    activity_id: UUID
    workspace_id: str
    project_id: str
    project_run_id: ProjectRunId
    account_run_id: RunId
    subject_entity_id: EntityId
    subject_entity_type: EntityType
    product_id: str | None
    owner_event_ref: str
    event_kind: str
    actor_category: str | None
    occurred_at: datetime


async def append_subject_activity(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    project_run_id: ProjectRunId,
    account_run_id: RunId,
    subject_entity_id: EntityId,
    subject_entity_type: EntityType,
    product_id: str | None,
    owner_event_ref: str,
    event_kind: str,
    occurred_at: datetime,
    actor_category: str | None = None,
) -> None:
    """Idempotently append one mechanically scoped owner reference without copying its body."""

    await conn.execute(
        text(
            """
            INSERT INTO research_subject_activity (
                workspace_id, project_id, project_run_id, account_run_id,
                subject_entity_id, subject_entity_type, product_id,
                owner_event_ref, event_kind, actor_category, occurred_at
            ) VALUES (
                :workspace_id, :project_id, :project_run_id, :account_run_id,
                :subject_entity_id, CAST(:subject_entity_type AS entity_type), :product_id,
                :owner_event_ref, :event_kind, :actor_category, :occurred_at
            )
            ON CONFLICT (workspace_id, owner_event_ref, subject_entity_id) DO NOTHING
            """
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "project_run_id": project_run_id,
            "account_run_id": account_run_id,
            "subject_entity_id": subject_entity_id,
            "subject_entity_type": subject_entity_type.value,
            "product_id": product_id,
            "owner_event_ref": owner_event_ref,
            "event_kind": event_kind,
            "actor_category": actor_category,
            "occurred_at": occurred_at,
        },
    )


async def list_subject_activity(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    project_run_id: ProjectRunId,
    account_run_id: RunId,
    subject_entity_id: EntityId,
    subject_entity_type: EntityType,
    product_id: str | None,
    limit: int = 50,
) -> tuple[SubjectActivityRow, ...]:
    """Read only the exact subject/run/product activity scope in stable newest-first order."""

    rows = (
        await conn.execute(
            text(
                """
                SELECT activity_id, workspace_id, project_id, project_run_id, account_run_id,
                       subject_entity_id, subject_entity_type, product_id, owner_event_ref,
                       event_kind, actor_category, occurred_at
                FROM research_subject_activity
                WHERE workspace_id = :workspace_id
                  AND project_id = :project_id
                  AND project_run_id = :project_run_id
                  AND account_run_id = :account_run_id
                  AND subject_entity_id = :subject_entity_id
                  AND subject_entity_type = CAST(:subject_entity_type AS entity_type)
                  AND product_id IS NOT DISTINCT FROM :product_id
                ORDER BY occurred_at DESC, activity_id DESC
                LIMIT :limit
                """
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "project_run_id": project_run_id,
                "account_run_id": account_run_id,
                "subject_entity_id": subject_entity_id,
                "subject_entity_type": subject_entity_type.value,
                "product_id": product_id,
                "limit": min(max(limit, 1), 100),
            },
        )
    ).mappings()
    return tuple(SubjectActivityRow.model_validate(dict(row)) for row in rows)


__all__ = [
    "SubjectActivityRow",
    "append_subject_activity",
    "list_subject_activity",
]
