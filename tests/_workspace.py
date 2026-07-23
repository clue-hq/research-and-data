"""Shared test helper: seed a ``workspace`` row so the account-entity workspace FK is satisfiable.

Accounts/contacts are workspace-local ([B3×research]; founder ruling 2026-07-22), so
``insert_account_entity`` / ``resolve`` / ``disposition`` / ``admit`` all require a ``workspace_id``
and ``account_entity.workspace_id`` FKs to ``workspace``. Any DB test that creates an account must
first seed the workspace it stamps. This is the single, idempotent seed helper every suite imports
(DRY — one place, not re-implemented per conftest).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

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
