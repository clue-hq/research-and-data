"""The retention query itself, against the real schema.

The sibling ``test_agent_cleanup.py`` drives the job with a fake connection, so it proves what the
job *does* with a selected row but nothing about which rows Postgres actually hands it. This file
runs the real SQL over seeded threads: the selection rules (newest turn, terminal-only, retention
window, archived-immediately, already-purged) are the part a fake cannot check.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_cleanup import AgentWorkspaceCleanupJob
from clue_config import Settings
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

_SHA = "0" * 64
_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
_OLD = _NOW - timedelta(days=3)
_RECENT = _NOW - timedelta(minutes=5)


@pytest.fixture
def require_cleanup_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


class _Workspaces:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def purge_thread(self, *, workspace_id: str, project_id: str, thread_id: str) -> bool:
        self.calls.append((workspace_id, project_id, thread_id))
        return True


def _mine(workspaces: _Workspaces, workspace_id: str) -> list[tuple[str, str, str]]:
    return [call for call in workspaces.calls if call[0] == workspace_id]


async def _seed_thread(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    status: str = "active",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, status) "
            "VALUES (:id, :workspace, :project, :status)"
        ),
        {"id": thread_id, "workspace": workspace_id, "project": project_id, "status": status},
    )


async def _seed_turn(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    created_at: datetime,
    event_status: str,
    event_at: datetime,
) -> UUID:
    turn_id = uuid4()
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, pin_manifest_hash)"
            " VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {"id": execution_id, "workspace": workspace_id, "project": project_id, "hash": _SHA},
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at, created_at) "
            "VALUES (:id, :execution, :workspace, :project, :thread, 'human', 'head_of_abm', "
            " :root, 'head-of-abm', 'v51', :hash, :key, :hash, :hash, 'standard', "
            " :created_at, :created_at)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project_id,
            "thread": thread_id,
            "root": f"root-{thread_id}",
            "hash": _SHA,
            "key": f"{workspace_id}/{_SHA}",
            "created_at": created_at,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn_event (event_id, turn_id, workspace_id, status, created_at) "
            "VALUES (:event, :turn, :workspace, :status, :created_at)"
        ),
        {
            "event": uuid4(),
            "turn": turn_id,
            "workspace": workspace_id,
            "status": event_status,
            "created_at": event_at,
        },
    )
    return turn_id


def test_the_retention_query_selects_only_purgeable_threads_and_dedupes(
    require_cleanup_db: None,
) -> None:
    del require_cleanup_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-cleanup", name="Cleanup retention")
            workspace_id = project.workspace_id
            project_id = project.project_id
            await conn.execute(
                text(
                    "INSERT INTO artifact "
                    "(storage_key, workspace_id, content_sha256, media_type, size_bytes) "
                    "VALUES (:key, :workspace, :sha, 'text/plain', 1)"
                ),
                {"key": f"{workspace_id}/{_SHA}", "workspace": workspace_id, "sha": _SHA},
            )

            common = {"workspace_id": workspace_id, "project_id": project_id}
            # A: one old, completed turn — retention has elapsed.
            await _seed_thread(conn, thread_id="thread-a", **common)
            await _seed_turn(
                conn,
                thread_id="thread-a",
                created_at=_OLD,
                event_status="completed",
                event_at=_OLD,
                **common,
            )
            # B: an old completed turn, then a newer running one — the thread is alive.
            await _seed_thread(conn, thread_id="thread-b", **common)
            await _seed_turn(
                conn,
                thread_id="thread-b",
                created_at=_OLD,
                event_status="completed",
                event_at=_OLD,
                **common,
            )
            await _seed_turn(
                conn,
                thread_id="thread-b",
                created_at=_RECENT,
                event_status="running",
                event_at=_RECENT,
                **common,
            )
            # C: archived, so a recent terminal turn is purged without waiting out retention.
            await _seed_thread(conn, thread_id="thread-c", status="archived", **common)
            await _seed_turn(
                conn,
                thread_id="thread-c",
                created_at=_RECENT,
                event_status="completed",
                event_at=_RECENT,
                **common,
            )
            # D: no turns at all — no directory was ever created, so there is nothing to purge.
            await _seed_thread(conn, thread_id="thread-d", status="archived", **common)

            workspaces = _Workspaces()
            job = AgentWorkspaceCleanupJob(
                settings=Settings(_env_file=None, agent_workspace_retention_s=3600),
                workspaces=cast(Any, workspaces),
                conn_factory=cast(Any, conn_session_factory(conn)),
            )

            first = await job.run_once(now=_NOW)

            # The sweep is global and a shared development database carries other workspaces'
            # threads, so the assertions are scoped to the workspace this test seeded. Order
            # within the scope is the query's order (oldest terminal turn first).
            assert _mine(workspaces, workspace_id) == [
                (workspace_id, project_id, "thread-a"),
                (workspace_id, project_id, "thread-c"),
            ]
            assert first.considered >= 2
            assert first.threads_purged == first.removed == first.considered
            assert first.already_absent == 0

            reasons = tuple(
                (row["thread_id"], row["reason_code"])
                for row in (
                    await conn.execute(
                        text(
                            "SELECT thread_id, reason_code FROM agent_workspace_cleanup_event "
                            "WHERE action='thread_purge' AND workspace_id=:workspace "
                            "ORDER BY thread_id"
                        ),
                        {"workspace": workspace_id},
                    )
                ).mappings()
            )
            assert reasons == (
                ("thread-a", "retention_elapsed"),
                ("thread-c", "thread_archived"),
            )

            # The receipts exclude their own threads from the next sweep.
            second = await job.run_once(now=_NOW)
            assert second.considered == 0
            assert second.threads_purged == 0
            assert len(_mine(workspaces, workspace_id)) == 2

    run_async(scenario())
