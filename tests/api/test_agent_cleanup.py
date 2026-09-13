from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid5

from clue_api.agent_cleanup import _CLEANUP_NAMESPACE, AgentWorkspaceCleanupJob
from clue_config import Settings
from tests.db.conftest import run_async


class _Result:
    def __init__(self, rows: tuple[dict[str, object], ...] = ()) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def __iter__(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, rows: tuple[dict[str, object], ...]) -> None:
        self.rows = rows
        self.inserts: list[dict[str, object]] = []
        self.cutoff: datetime | None = None
        self.select_sql: str | None = None

    async def execute(self, statement: object, params: dict[str, object]) -> _Result:
        sql = str(statement)
        if "FROM agent_thread" in sql:
            self.select_sql = sql
            self.cutoff = cast(datetime, params["cutoff"])
            return _Result(self.rows)
        self.inserts.append(params)
        return _Result()


class _Workspaces:
    def __init__(self, *, removed: bool) -> None:
        self.removed = removed
        self.calls: list[tuple[str, str, str]] = []

    def purge_thread(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
    ) -> bool:
        self.calls.append((workspace_id, project_id, thread_id))
        return self.removed


_TURN_ID = UUID("00000000-0000-0000-0000-000000000682")
_EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000681")
_NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _row(
    *,
    thread_id: str,
    thread_status: str = "active",
    latest_status: str = "completed",
) -> dict[str, object]:
    return {
        "thread_id": thread_id,
        "workspace_id": "ws-c68",
        "project_id": "project-c68",
        "thread_status": thread_status,
        "turn_id": _TURN_ID,
        "execution_id": _EXECUTION_ID,
        "workspace_root_id": "opaque-root-id",
        "latest_status": latest_status,
    }


async def _run(
    conn: _Conn,
    workspaces: _Workspaces,
    *,
    now: datetime = _NOW,
):
    @asynccontextmanager
    async def factory():
        yield cast(Any, conn)

    return await AgentWorkspaceCleanupJob(
        settings=Settings(_env_file=None, agent_workspace_retention_s=3600),
        workspaces=cast(Any, workspaces),
        conn_factory=cast(Any, factory),
    ).run_once(now=now)


def test_retention_elapsed_thread_is_purged_and_receipted_on_its_newest_turn() -> None:
    async def scenario() -> None:
        conn = _Conn((_row(thread_id="thread-c68"),))
        workspaces = _Workspaces(removed=True)

        result = await _run(conn, workspaces)

        assert result.considered == 1
        assert result.removed == 1
        assert result.threads_purged == 1
        assert result.already_absent == 0
        assert workspaces.calls == [("ws-c68", "project-c68", "thread-c68")]
        assert conn.cutoff == datetime(2026, 7, 26, 23, tzinfo=UTC)
        assert conn.select_sql is not None
        # ``awaiting_input`` is live resumable state: it must never be a terminal status here.
        assert "'awaiting_input'" not in conn.select_sql
        assert len(conn.inserts) == 1
        insert = conn.inserts[0]
        assert insert["turn"] == _TURN_ID
        assert insert["execution"] == _EXECUTION_ID
        assert insert["workspace"] == "ws-c68"
        assert insert["root"] == "opaque-root-id"
        assert insert["thread"] == "thread-c68"
        assert insert["reason"] == "retention_elapsed"
        assert insert["removed"] is True

    run_async(scenario())


def test_archived_thread_is_purged_with_the_archived_reason_code() -> None:
    async def scenario() -> None:
        # The row the query returns for an archived thread; the archive alone makes it
        # eligible, and the reason code must say so rather than blaming the clock.
        conn = _Conn((_row(thread_id="thread-archived", thread_status="archived"),))
        workspaces = _Workspaces(removed=True)

        result = await _run(conn, workspaces)

        assert result.threads_purged == 1
        assert workspaces.calls == [("ws-c68", "project-c68", "thread-archived")]
        assert conn.inserts[0]["reason"] == "thread_archived"
        assert conn.inserts[0]["thread"] == "thread-archived"

    run_async(scenario())


def test_cleanup_event_id_is_the_uuid5_of_workspace_thread_and_action() -> None:
    async def scenario() -> None:
        conn = _Conn((_row(thread_id="thread-c68"),))
        workspaces = _Workspaces(removed=True)

        await _run(conn, workspaces)

        assert conn.inserts[0]["id"] == uuid5(_CLEANUP_NAMESPACE, "ws-c68:thread-c68:thread_purge")

    run_async(scenario())


def test_a_thread_directory_already_gone_is_counted_absent_and_still_receipted() -> None:
    async def scenario() -> None:
        conn = _Conn((_row(thread_id="thread-c68"),))
        workspaces = _Workspaces(removed=False)

        result = await _run(conn, workspaces)

        assert result.considered == 1
        assert result.removed == 0
        assert result.threads_purged == 0
        assert result.already_absent == 1
        assert conn.inserts[0]["removed"] is False

    run_async(scenario())
