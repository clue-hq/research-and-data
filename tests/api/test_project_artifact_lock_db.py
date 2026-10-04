"""Two artifact writers in one project never block each other; project erasure excludes both.

Production 2026-10-03: every research save took the project-wide advisory lock exclusively, so all
jobs in a project queued on it (waits up to 280 s). Writers now take it shared; erasure keeps it
exclusive. Real, independent, committed Postgres transactions.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.agent_turn_wiring import PROJECT_ARTIFACTS_LOCK, DurableAgentArtifactStore
from clue_db import db_lifespan
from clue_storage import artifact_key, content_address
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db, run_async  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_two_writers_share_the_project_lock_and_erasure_waits_for_both() -> None:
    async def case() -> None:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                project = await seed_project(conn, f"ws-lock-{uuid4()}", name="Lock test")
            # Only the two recording helpers are called; they never touch storage.
            store = DurableAgentArtifactStore(storage=None)  # type: ignore[arg-type]
            scope = PROJECT_ARTIFACTS_LOCK.format(
                workspace_id=project.workspace_id, project_id=project.project_id
            )

            async def bind(conn: Any, data: bytes) -> None:
                digest = content_address(data)
                key = artifact_key(project.workspace_id, digest)
                await store._record_body(
                    conn,
                    workspace_id=project.workspace_id,
                    key=key,
                    digest=digest,
                    size=len(data),
                    media_type="text/plain",
                    subject_bindings=(),
                )
                await store._bind_projects(
                    conn,
                    workspace_id=project.workspace_id,
                    key=key,
                    project_bindings=((project.project_id, "account_research_context"),),
                )

            first_bound = asyncio.Event()
            release_first = asyncio.Event()

            async def first_writer() -> None:
                async with engine.begin() as conn:
                    await bind(conn, b"first")
                    first_bound.set()
                    await release_first.wait()

            async def second_writer() -> None:
                await first_bound.wait()
                async with engine.begin() as conn:
                    await bind(conn, b"second")

            async def eraser() -> None:
                # engine.connect + explicit rollback: after the lock timeout Postgres has aborted
                # this transaction, so it must be rolled back, never committed.
                await first_bound.wait()
                async with engine.connect() as conn:
                    await conn.begin()
                    await conn.execute(text("SET LOCAL lock_timeout = '300ms'"))
                    with pytest.raises(DBAPIError):
                        await conn.execute(
                            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                            {"scope": scope},
                        )
                    await conn.rollback()

            first = asyncio.create_task(first_writer())
            # The second writer completes while the first still holds its (shared) lock.
            await asyncio.wait_for(second_writer(), timeout=5)
            # Erasure's exclusive lock cannot be taken while a writer holds the shared one.
            await asyncio.wait_for(eraser(), timeout=5)
            release_first.set()
            await asyncio.wait_for(first, timeout=5)
            # Once the writer committed, erasure gets the lock immediately.
            async with engine.begin() as conn:
                await conn.execute(text("SET LOCAL lock_timeout = '300ms'"))
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": scope},
                )

    run_async(case())
