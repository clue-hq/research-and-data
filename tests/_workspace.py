"""Shared test helpers for workspace-owned accounts and project-run context.

Accounts/contacts are workspace-local ([B3×research]; founder ruling 2026-07-22), so
``insert_account_entity`` / ``resolve`` / ``disposition`` / ``admit`` all require a ``workspace_id``
and ``account_entity.workspace_id`` FKs to ``workspace``. Any DB test that creates an account must
first seed the workspace it stamps. This is the single, idempotent seed helper every suite imports
(DRY — one place, not re-implemented per conftest). Project runs additionally require a project
whose sender brand belongs to the same workspace; ``seed_project`` creates that valid pair.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import Project, create_brand, create_project

# The conventional test workspace id (matches the in-memory ``ICPSpec.workspace_id="acme"`` many
# suites already use), so a single seed satisfies both the account FK and the spec's workspace.
DEFAULT_TEST_WORKSPACE = "acme"


async def seed_workspace(conn: AsyncConnection, workspace_id: str = DEFAULT_TEST_WORKSPACE) -> str:
    """Insert a ``workspace`` row (idempotent) so the account-entity workspace FK is satisfiable.

    Returns ``workspace_id`` so callers can inline ``ws = await seed_workspace(conn, ...)``.
    """
    await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w) "
            "ON CONFLICT (workspace_id) DO NOTHING"
        ),
        {"w": workspace_id},
    )
    return workspace_id


async def seed_project(
    conn: AsyncConnection,
    workspace_id: str = DEFAULT_TEST_WORKSPACE,
    *,
    name: str = "Test project",
) -> Project:
    """Create a same-workspace brand + project for project-run tests."""
    await seed_workspace(conn, workspace_id)
    brand = await create_brand(conn, workspace_id=workspace_id, name=f"{name} brand")
    return await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name=name,
    )
