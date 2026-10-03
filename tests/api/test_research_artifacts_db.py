"""ResearchArtifacts.persist_body: upload before the project lock, one derivation statement.

Production 2026-10-03: every research save took the project lock, uploaded to R2 inside it and
inserted one derivation row per evidence source, holding the lock 3-18 s.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import event, text

from clue_api.agent_turn_wiring import PROJECT_ARTIFACTS_LOCK
from clue_api.quality_research_artifacts import ResearchArtifacts
from clue_storage import StorageError
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

_HELD_LOCK = (
    "SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' "
    "AND (classid::bigint<<32 | objid::bigint)=hashtextextended(:s,0)"
)


class _LockProbeStorage:
    """Delegates to FsStorage; at put time records whether this backend holds the project lock."""

    def __init__(self, inner: FsStorage, conn: Any, scope: str, *, fail: bool = False) -> None:
        self._inner, self._conn, self._scope, self._fail = inner, conn, scope, fail
        self.lock_held_at_put: list[bool] = []

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        modes = (await self._conn.execute(text(_HELD_LOCK), {"s": self._scope})).scalars().all()
        self.lock_held_at_put.append(bool(modes))
        if self._fail:
            raise StorageError("simulated upload failure")
        await self._inner.put(key, data, media_type=media_type)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _borrowed(conn: Any) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield conn

    return factory


def _sink(conn: Any, storage: Any, job: Any, cid: Any) -> ResearchArtifacts:
    sink = ResearchArtifacts(storage=storage, conn_factory=_borrowed(conn))
    sink.scope = job
    sink.context_id = cid
    return sink


def _scope(job: Any) -> str:
    return PROJECT_ARTIFACTS_LOCK.format(workspace_id=job.workspace_id, project_id=job.project_id)


def test_upload_happens_before_the_project_lock_and_the_lock_is_shared_after(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            _op, job, cid = await setup(conn, fs)
            # Earlier saves in this same transaction may already hold the lock; measure from a
            # savepoint-free fresh state by checking the probe only for this save's upload.
            probe = _LockProbeStorage(fs, conn, _scope(job))
            held_before = (await conn.execute(text(_HELD_LOCK), {"s": _scope(job)})).scalars().all()
            await _sink(conn, probe, job, cid).persist_body(
                workspace_id=job.workspace_id, data=b'{"x":1}', media_type="application/json"
            )
            if not held_before:
                assert probe.lock_held_at_put == [False]
            after = (await conn.execute(text(_HELD_LOCK), {"s": _scope(job)})).scalars().all()
            assert after and set(after) == {"ShareLock"}

    run_async(case())


def test_derivation_edges_are_one_statement_with_the_same_rows(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            for i in range(25):
                await save(conn, fs, op, f"Source body number {i}.", url=f"https://e.test/{i}")
            parents = set(
                (
                    await conn.execute(
                        text(
                            "SELECT artifact_key FROM arv2_evidence_source "
                            "WHERE workspace_id=:ws AND run_id=:run AND account_id=:account"
                        ),
                        {"ws": op.workspace_id, "run": op.run_id, "account": op.account_id},
                    )
                ).scalars()
            )
            statements: list[str] = []

            def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
                if "INSERT INTO artifact_derivation" in statement:
                    statements.append(statement)

            event.listen(conn.sync_connection, "before_cursor_execute", count)
            try:
                ref = await _sink(conn, fs, job, cid).persist_body(
                    workspace_id=job.workspace_id, data=b'{"y":2}', media_type="application/json"
                )
            finally:
                event.remove(conn.sync_connection, "before_cursor_execute", count)
            assert len(statements) == 1
            linked = set(
                (
                    await conn.execute(
                        text(
                            "SELECT parent_key FROM artifact_derivation "
                            "WHERE workspace_id=:ws AND child_key=:key"
                        ),
                        {"ws": job.workspace_id, "key": ref.artifact_key},
                    )
                ).scalars()
            )
            assert len(parents) >= 25
            assert parents <= linked

    run_async(case())


def test_a_failed_upload_leaves_no_binding_or_derivation(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            await save(conn, fs, op, "Only source.", url="https://e.test/only")

            async def counts() -> tuple[int, int]:
                bound = (
                    await conn.execute(
                        text("SELECT count(*) FROM agent_artifact_project WHERE workspace_id=:ws"),
                        {"ws": job.workspace_id},
                    )
                ).scalar_one()
                derived = (
                    await conn.execute(
                        text("SELECT count(*) FROM artifact_derivation WHERE workspace_id=:ws"),
                        {"ws": job.workspace_id},
                    )
                ).scalar_one()
                return bound, derived

            before = await counts()
            sink = _sink(conn, _LockProbeStorage(fs, conn, _scope(job), fail=True), job, cid)
            savepoint = await conn.begin_nested()
            with pytest.raises(StorageError):
                await sink.persist_body(
                    workspace_id=job.workspace_id, data=b'{"z":3}', media_type="application/json"
                )
            await savepoint.rollback()
            assert await counts() == before

    run_async(case())
