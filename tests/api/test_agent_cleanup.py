from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from clue_api.agent_cleanup import AgentWorkspaceCleanupJob
from clue_config import Settings
from clue_core import ExecutionId
from tests.db.conftest import run_async


class _Result:
    def __init__(self, rows: tuple[dict[str, object], ...] = ()) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def __iter__(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.inserts: list[dict[str, object]] = []
        self.cutoff: datetime | None = None
        self.select_sql: str | None = None

    async def execute(self, statement: object, params: dict[str, object]) -> _Result:
        sql = str(statement)
        if "SELECT t.id" in sql:
            self.select_sql = sql
            self.cutoff = cast(datetime, params["cutoff"])
            return _Result((self.row,))
        self.inserts.append(params)
        return _Result()


class _Workspaces:
    def __init__(self, *, removed: bool) -> None:
        self.removed = removed
        self.calls: list[tuple[str, str, ExecutionId]] = []

    def purge_terminal(
        self,
        *,
        workspace_id: str,
        project_id: str,
        execution_id: ExecutionId,
    ) -> bool:
        self.calls.append((workspace_id, project_id, execution_id))
        return self.removed


def test_terminal_workspace_cleanup_is_identity_scoped_and_receipted() -> None:
    async def scenario() -> None:
        execution_id = UUID("00000000-0000-0000-0000-000000000681")
        turn_id = UUID("00000000-0000-0000-0000-000000000682")
        row: dict[str, object] = {
            "id": turn_id,
            "execution_id": execution_id,
            "workspace_id": "ws-c68",
            "project_id": "project-c68",
            "workspace_root_id": "opaque-root-id",
            "status": "completed",
            "created_at": datetime(2026, 7, 26, tzinfo=UTC),
        }
        conn = _Conn(row)

        @asynccontextmanager
        async def factory():
            yield cast(Any, conn)

        workspaces = _Workspaces(removed=True)
        now = datetime(2026, 7, 27, tzinfo=UTC)
        result = await AgentWorkspaceCleanupJob(
            settings=Settings(
                _env_file=None,
                agent_workspace_retention_s=3600,
            ),
            workspaces=cast(Any, workspaces),
            conn_factory=cast(Any, factory),
        ).run_once(now=now)

        assert result.considered == 1
        assert result.removed == 1
        assert result.already_absent == 0
        assert workspaces.calls == [("ws-c68", "project-c68", ExecutionId(execution_id))]
        assert conn.cutoff == datetime(2026, 7, 26, 23, tzinfo=UTC)
        assert conn.select_sql is not None
        assert "'awaiting_input'" not in conn.select_sql
        assert len(conn.inserts) == 1
        assert conn.inserts[0]["turn"] == turn_id
        assert conn.inserts[0]["root"] == "opaque-root-id"
        assert conn.inserts[0]["removed"] is True

    run_async(scenario())
