"""C6.8 retention cleanup for agent thread workspaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_agents import AgentWorkspaceFactory
from clue_config import Settings
from clue_db import ConnFactory, transaction

__all__ = ["AgentCleanupResult", "AgentWorkspaceCleanupJob"]

_CLEANUP_NAMESPACE = UUID("8dbc9f0e-1b83-5d50-ab36-ab3aca9ffecf")

# The thread's newest turn must be durably over before its directory can go. ``awaiting_input`` is
# deliberately absent: it is live resumable state, and so is anything earlier in the lifecycle.
_TERMINAL_STATUSES = "('completed', 'failed', 'cancelled', 'abandoned', 'privacy_tombstoned')"

_SELECT_PURGEABLE_THREADS = (
    "SELECT th.id AS thread_id, th.workspace_id, th.project_id, th.status AS thread_status, "
    " newest.id AS turn_id, newest.execution_id, newest.workspace_root_id, "
    " latest.status AS latest_status "
    "FROM agent_thread th "
    # INNER LATERAL: a thread that has never taken a turn has no directory to purge.
    "JOIN LATERAL (SELECT t.id, t.execution_id, t.workspace_root_id FROM agent_turn t "
    " WHERE t.thread_id=th.id AND t.workspace_id=th.workspace_id "
    " ORDER BY t.created_at DESC, t.id LIMIT 1) newest ON true "
    "JOIN LATERAL (SELECT e.status, e.created_at FROM agent_turn_event e "
    " WHERE e.turn_id=newest.id ORDER BY e.seq DESC LIMIT 1) latest ON true "
    f"WHERE latest.status IN {_TERMINAL_STATUSES} "
    # Archiving is the human saying the thread is done, so it does not wait out the window.
    "AND (th.status='archived' OR latest.created_at <= :cutoff) "
    "AND NOT EXISTS (SELECT 1 FROM agent_workspace_cleanup_event c "
    " WHERE c.turn_id=newest.id AND c.action='thread_purge') "
    "ORDER BY latest.created_at, th.id"
)

_INSERT_CLEANUP_EVENT = (
    "INSERT INTO agent_workspace_cleanup_event "
    "(id, turn_id, execution_id, workspace_id, workspace_root_id, thread_id, action, "
    " reason_code, removed) VALUES "
    "(:id, :turn, :execution, :workspace, :root, :thread, 'thread_purge', :reason, :removed) "
    "ON CONFLICT (turn_id, action) DO NOTHING"
)


class AgentCleanupResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    considered: int = Field(ge=0)
    removed: int = Field(ge=0)
    already_absent: int = Field(ge=0)
    threads_purged: int = Field(ge=0)


class AgentWorkspaceCleanupJob:
    """Purge a thread's persistent workspace once the thread is archived or durably idle.

    The agent workspace is one directory per chat thread (its ``scratch/`` and ``reads/`` survive
    across turns), so retention is keyed to threads: a thread keeps its directory while its newest
    turn is live, and loses it when the human archives the thread or the retention window elapses
    after that newest turn went terminal.
    """

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
            result = await conn.execute(text(_SELECT_PURGEABLE_THREADS), {"cutoff": cutoff})
            rows = tuple(result.mappings())

        purged = 0
        absent = 0
        for row in rows:
            did_remove = self._workspaces.purge_thread(
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                thread_id=row["thread_id"],
            )
            purged += int(did_remove)
            absent += int(not did_remove)
            event_id = uuid5(
                _CLEANUP_NAMESPACE,
                f"{row['workspace_id']}:{row['thread_id']}:thread_purge",
            )
            async with self._conn_factory() as conn:
                await conn.execute(
                    text(_INSERT_CLEANUP_EVENT),
                    {
                        "id": event_id,
                        # The newest turn: the receipt's composite FK is NOT NULL (R4), and this is
                        # also the turn whose arrival would have kept the thread alive.
                        "turn": row["turn_id"],
                        "execution": row["execution_id"],
                        "workspace": row["workspace_id"],
                        "root": row["workspace_root_id"],
                        "thread": row["thread_id"],
                        "reason": (
                            "thread_archived"
                            if row["thread_status"] == "archived"
                            else "retention_elapsed"
                        ),
                        "removed": did_remove,
                    },
                )
        return AgentCleanupResult(
            considered=len(rows),
            removed=purged,
            already_absent=absent,
            threads_purged=purged,
        )
