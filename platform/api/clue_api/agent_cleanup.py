"""C6.8 retention cleanup for terminal isolated agent workspaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_agents import AgentWorkspaceFactory
from clue_config import Settings
from clue_core import ExecutionId
from clue_db import ConnFactory, transaction

__all__ = ["AgentCleanupResult", "AgentWorkspaceCleanupJob"]

_CLEANUP_NAMESPACE = UUID("8dbc9f0e-1b83-5d50-ab36-ab3aca9ffecf")


class AgentCleanupResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    considered: int = Field(ge=0)
    removed: int = Field(ge=0)
    already_absent: int = Field(ge=0)


class AgentWorkspaceCleanupJob:
    """Purge only durably terminal roots older than the configured inspection window."""

    def __init__(
        self,
        *,
        settings: Settings,
        workspaces: AgentWorkspaceFactory,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._workspaces = workspaces
        self._conn_factory = conn_factory

    async def run_once(self, *, now: datetime | None = None) -> AgentCleanupResult:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(seconds=self._settings.agent_workspace_retention_s)
        async with self._conn_factory() as conn:
            # ``awaiting_input`` is live resumable state and is intentionally not eligible.
            result = await conn.execute(
                text(
                    "SELECT t.id, t.execution_id, t.workspace_id, t.project_id, "
                    "t.workspace_root_id, latest.status, latest.created_at "
                    "FROM agent_turn t "
                    "JOIN LATERAL (SELECT status, created_at FROM agent_turn_event "
                    " WHERE turn_id=t.id ORDER BY seq DESC LIMIT 1) latest ON true "
                    "WHERE latest.status IN "
                    "('completed', 'failed', 'abandoned', 'privacy_tombstoned') "
                    "AND latest.created_at <= :cutoff "
                    "AND NOT EXISTS (SELECT 1 FROM agent_workspace_cleanup_event c "
                    " WHERE c.turn_id=t.id AND c.action='terminal_retention_purge') "
                    "ORDER BY latest.created_at, t.id"
                ),
                {"cutoff": cutoff},
            )
            rows = tuple(result.mappings())

        removed = 0
        absent = 0
        for row in rows:
            did_remove = self._workspaces.purge_terminal(
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                execution_id=ExecutionId(row["execution_id"]),
            )
            removed += int(did_remove)
            absent += int(not did_remove)
            event_id = uuid5(
                _CLEANUP_NAMESPACE,
                f"{row['workspace_id']}:{row['id']}:terminal_retention_purge",
            )
            async with self._conn_factory() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO agent_workspace_cleanup_event "
                        "(id, turn_id, execution_id, workspace_id, workspace_root_id, action, "
                        " reason_code, removed) VALUES "
                        "(:id, :turn, :execution, :workspace, :root, "
                        "'terminal_retention_purge', 'retention_elapsed', :removed) "
                        "ON CONFLICT (turn_id, action) DO NOTHING"
                    ),
                    {
                        "id": event_id,
                        "turn": row["id"],
                        "execution": row["execution_id"],
                        "workspace": row["workspace_id"],
                        "root": row["workspace_root_id"],
                        "removed": did_remove,
                    },
                )
        return AgentCleanupResult(
            considered=len(rows),
            removed=removed,
            already_absent=absent,
        )
