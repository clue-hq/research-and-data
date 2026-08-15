"""Trusted Stage-0 project scope derived from durable execution state.

The Slice-1 Stage-0 tools intentionally expose no workspace/project/product/client fields to the
model.  A governed invocation already carries an ``execution_id`` in :class:`ToolContext`; the
execution row pins the project, and the project plus its append-only onboarding captures pin the
remaining Stage-0 lineage.  This module is the single resolver used by both tool execution and C5
pin materialization so those two authority checks cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId, ExecutionId
from clue_research.stage0 import current_kb_version

__all__ = [
    "Stage0ProjectScope",
    "resolve_stage0_project_scope",
    "resolve_stage0_project_scope_for_project",
]


@dataclass(frozen=True, slots=True)
class Stage0ProjectScope:
    workspace_id: str
    execution_id: ExecutionId | None
    project_id: str
    brand_id: str
    product_id: str | None
    client_entity_id: EntityId | None
    client_kb_version: int | None


async def resolve_stage0_project_scope(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    execution_id: ExecutionId | None,
) -> Stage0ProjectScope | None:
    """Resolve the exact Stage-0 lineage for one governed execution, or return ``None``.

    The client identity is discovered only from this project's own onboarding captures. A client
    from another project in the same workspace therefore cannot leak into readiness or synthesis.
    The Client-KB version is the account-wide company lineage; the project's confirmed product is
    an independent trusted coordinate whose Product-KB version may legitimately differ.
    """

    if execution_id is None:
        return None
    project_id = (
        await conn.execute(
            text(
                """
                    SELECT e.project_id
                    FROM execution e
                    WHERE e.id = :execution_id
                      AND e.workspace_id = :workspace_id
                    """
            ),
            {"execution_id": execution_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    if project_id is None:
        return None
    return await resolve_stage0_project_scope_for_project(
        conn,
        workspace_id=workspace_id,
        project_id=str(project_id),
        execution_id=execution_id,
    )


async def resolve_stage0_project_scope_for_project(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    execution_id: ExecutionId | None = None,
) -> Stage0ProjectScope | None:
    """Resolve trusted Stage-0 scope when the authenticated route already proved the project."""

    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT p.project_id, p.brand_id, p.product_id,
                           (
                               SELECT i.client_entity_id
                               FROM onboarding_input i
                               WHERE i.workspace_id = p.workspace_id
                                 AND i.project_id = p.project_id
                                 AND i.client_entity_id IS NOT NULL
                               ORDER BY i.created_at DESC, i.id DESC
                               LIMIT 1
                           ) AS client_entity_id
                    FROM project p
                    WHERE p.project_id = :project_id
                      AND p.workspace_id = :workspace_id
                    """
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    client_entity_id = (
        None if row["client_entity_id"] is None else EntityId(row["client_entity_id"])
    )
    product_id = None if row["product_id"] is None else str(row["product_id"])
    # ``client_kb_version`` is the account-wide company lineage.  The selected product is a
    # separate trusted pin on the project; product-specific knowledge has its own version and must
    # never replace the company lineage used by ICP readiness/synthesis.
    client_kb_version = (
        None
        if client_entity_id is None
        else await current_kb_version(
            conn,
            client_entity_id,
            workspace_id=workspace_id,
            product_id=None,
        )
    )
    return Stage0ProjectScope(
        workspace_id=workspace_id,
        execution_id=execution_id,
        project_id=str(row["project_id"]),
        brand_id=str(row["brand_id"]),
        product_id=product_id,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
    )
