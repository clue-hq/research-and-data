"""Body-free C7 research-view list/status projections."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_db import ConnFactory, transaction


class ResearchViewStatus(BaseModel):
    """Small list-safe state for one account or contact research view."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_entity_id: UUID
    subject_entity_type: str
    product_id: str | None
    available: bool
    latest_snapshot_id: UUID | None
    source_state_sha256: str | None
    composition_sha256: str | None
    stale_section_count: int = Field(ge=0)
    coverage_availability: str | None
    coverage_item_count: int = Field(ge=0)
    latest_recheck_report_id: UUID | None
    latest_recheck_at: datetime | None
    recheck_changed: bool | None


class ResearchViewStatusPage(BaseModel):
    """Deterministically ordered projection page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[ResearchViewStatus, ...]
    next_cursor: int | None = Field(default=None, ge=0)


async def research_view_statuses(
    *,
    workspace_id: str,
    project_id: str,
    subject_entity_type: str | None = None,
    cursor: int = 0,
    limit: int = 50,
    conn_factory: ConnFactory = transaction,
) -> ResearchViewStatusPage:
    """Read latest snapshot/re-check state without resolving any research value."""

    bounded_limit = min(max(limit, 1), 100)
    bounded_cursor = max(cursor, 0)
    if subject_entity_type not in {None, "account", "contact"}:
        raise ValueError("subject_entity_type must be account or contact")
    async with conn_factory() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    WITH latest AS (
                        SELECT DISTINCT ON (
                            s.subject_entity_type, s.subject_entity_id, s.product_id
                        )
                               s.*
                        FROM research_view_snapshot s
                        WHERE s.workspace_id = :workspace_id
                          AND s.project_id = :project_id
                          AND (
                              CAST(:subject_entity_type AS text) IS NULL
                              OR s.subject_entity_type::text = :subject_entity_type
                          )
                        ORDER BY s.subject_entity_type, s.subject_entity_id, s.product_id,
                                 s.created_at DESC, s.snapshot_id DESC
                    )
                    SELECT l.subject_entity_id, l.subject_entity_type::text, l.product_id,
                           l.snapshot_id, l.source_state_sha256, l.composition_sha256,
                           COALESCE(stale.stale_count, 0),
                           coverage.availability, COALESCE(coverage.item_count, 0),
                           report.report_id, report.created_at,
                           CASE
                               WHEN report.report_id IS NULL THEN NULL
                               ELSE report.old_source_state_sha256
                                    <> report.new_source_state_sha256
                                    OR report.old_composition_sha256
                                    <> report.new_composition_sha256
                           END AS recheck_changed
                    FROM latest l
                    LEFT JOIN LATERAL (
                        SELECT COUNT(DISTINCT section_ordinal)::integer AS stale_count
                        FROM research_view_section_staleness
                        WHERE workspace_id = l.workspace_id
                          AND snapshot_id = l.snapshot_id
                    ) stale ON true
                    LEFT JOIN LATERAL (
                        SELECT sec.availability, COUNT(item.ordinal)::integer AS item_count
                        FROM research_view_snapshot_section sec
                        LEFT JOIN research_view_snapshot_item item
                          ON item.snapshot_id = sec.snapshot_id
                         AND item.section_ordinal = sec.ordinal
                        WHERE sec.snapshot_id = l.snapshot_id
                          AND sec.section_kind = 'coverage_gaps'
                        GROUP BY sec.availability
                    ) coverage ON true
                    LEFT JOIN LATERAL (
                        SELECT r.report_id, r.created_at,
                               r.old_source_state_sha256, r.new_source_state_sha256,
                               r.old_composition_sha256, r.new_composition_sha256
                        FROM research_view_change_report r
                        WHERE r.workspace_id = l.workspace_id
                          AND r.project_id = l.project_id
                          AND r.subject_entity_id = l.subject_entity_id
                        ORDER BY r.created_at DESC, r.report_id DESC
                        LIMIT 1
                    ) report ON true
                    ORDER BY l.subject_entity_type, l.subject_entity_id, l.product_id NULLS FIRST
                    OFFSET :cursor
                    LIMIT :fetch_limit
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "subject_entity_type": subject_entity_type,
                    "cursor": bounded_cursor,
                    "fetch_limit": bounded_limit + 1,
                },
            )
        ).all()
    visible = rows[:bounded_limit]
    items = tuple(
        ResearchViewStatus(
            subject_entity_id=row[0],
            subject_entity_type=str(row[1]),
            product_id=row[2],
            available=True,
            latest_snapshot_id=row[3],
            source_state_sha256=str(row[4]),
            composition_sha256=str(row[5]),
            stale_section_count=int(row[6]),
            coverage_availability=row[7],
            coverage_item_count=int(row[8]),
            latest_recheck_report_id=row[9],
            latest_recheck_at=row[10],
            recheck_changed=row[11],
        )
        for row in visible
    )
    return ResearchViewStatusPage(
        items=items,
        next_cursor=(bounded_cursor + bounded_limit if len(rows) > bounded_limit else None),
    )
