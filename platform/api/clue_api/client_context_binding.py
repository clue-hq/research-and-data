"""Canonical customer/client identity inherited by every project in a workspace.

Project-scoped onboarding inputs remain immutable evidence about a particular conversation. They
are not the authority for which customer the workspace represents. Trusted onboarding recon binds
that identity once here; every production project turn reads the same binding.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityId, ReconRunId


class WorkspaceClientBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str = Field(min_length=1)
    client_entity_id: EntityId
    source_recon_run_id: ReconRunId | None = None
    created_at: datetime


class WorkspaceClientBindingConflict(ValueError):
    """An ordinary flow attempted to repoint an already-bound customer workspace."""


_SELECT = "workspace_id, client_entity_id, source_recon_run_id, created_at"


def _binding(row: RowMapping) -> WorkspaceClientBinding:
    return WorkspaceClientBinding.model_validate(dict(row))


async def bind_workspace_client(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    source_recon_run_id: ReconRunId | None = None,
) -> WorkspaceClientBinding:
    """Insert once, replay the same identity, and refuse a silent customer repoint."""

    if not workspace_id:
        raise ValueError("workspace client binding requires a workspace id")

    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"workspace-client-binding:{workspace_id}"},
    )
    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO workspace_client_binding ("
                    "workspace_id, client_entity_id, source_recon_run_id"
                    ") VALUES (:workspace_id, :client_entity_id, :source_recon_run_id) "
                    "ON CONFLICT (workspace_id) DO NOTHING "
                    f"RETURNING {_SELECT}"
                ),
                {
                    "workspace_id": workspace_id,
                    "client_entity_id": client_entity_id,
                    "source_recon_run_id": source_recon_run_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        return _binding(inserted)
    existing = (
        (
            await conn.execute(
                text(
                    f"SELECT {_SELECT} FROM workspace_client_binding "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
        )
        .mappings()
        .one()
    )
    binding = _binding(existing)
    if binding.client_entity_id != client_entity_id:
        raise WorkspaceClientBindingConflict(
            "workspace already belongs to a different canonical client entity"
        )
    return binding


async def get_workspace_client_binding(
    conn: AsyncConnection, *, workspace_id: str
) -> WorkspaceClientBinding | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_SELECT} FROM workspace_client_binding "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _binding(row)


async def workspace_client_entity_id(
    conn: AsyncConnection, *, workspace_id: str
) -> EntityId | None:
    binding = await get_workspace_client_binding(conn, workspace_id=workspace_id)
    return None if binding is None else binding.client_entity_id


__all__ = [
    "WorkspaceClientBinding",
    "WorkspaceClientBindingConflict",
    "bind_workspace_client",
    "get_workspace_client_binding",
    "workspace_client_entity_id",
]
