"""F3 Phase 2 (spec WS-30/AW-26, plan Task 1): a chat's snapshot files get their own storage
area, so expiring one can never reach an upload, a Gallery artifact or a research output.

``artifact_key_encodes_scope`` must admit the third shape ``{workspace|public}/agent-workspace/
{sha256}`` and nothing else new: an invented namespace is still an integrity error.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan

from .conftest import run_async

_SHA = "ab" * 32


async def _with_rollback(body) -> None:  # type: ignore[no-untyped-def]
    async with db_lifespan() as engine, engine.connect() as conn:
        tx = await conn.begin()
        try:
            await body(conn)
        finally:
            await tx.rollback()


async def _insert(conn: AsyncConnection, storage_key: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, 'ws_x', :sha, 'application/octet-stream', 7)"
        ),
        {"key": storage_key, "sha": _SHA},
    )


@pytest.mark.usefixtures("require_db")
def test_the_artifact_table_accepts_the_agent_workspace_shape() -> None:
    async def body(conn: AsyncConnection) -> None:
        await _insert(conn, f"ws_x/agent-workspace/{_SHA}")

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
@pytest.mark.parametrize(
    "storage_key",
    [f"ws_x/other/{_SHA}", f"ws_y/agent-workspace/{_SHA}"],
)
def test_the_artifact_table_still_refuses_any_other_shape(storage_key: str) -> None:
    async def body(conn: AsyncConnection) -> None:
        with pytest.raises(IntegrityError):
            await _insert(conn, storage_key)

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
def test_the_two_older_shapes_still_pass() -> None:
    async def body(conn: AsyncConnection) -> None:
        await _insert(conn, f"ws_x/{_SHA}")
        await _insert(conn, f"ws_x/design/{_SHA}")

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
def test_a_receipt_lookup_by_operation_id_has_an_index() -> None:
    """Final review I5: the receipt read runs per saved file, inside the turn's save.

    ``execution_node``'s other indexes both lead with ``execution_id``, so without this one a
    lookup by operation id alone is a sequential scan of the execution journal.
    """

    async def body(conn: AsyncConnection) -> None:
        indexed = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'execution_node' AND indexname = 'execution_node_operation'"
                )
            )
        ).scalar_one_or_none()
        assert indexed is not None, "no index serves execution_node (operation_id)"
        assert "(operation_id)" in indexed

    run_async(_with_rollback(body))


class _RecordingOp:
    """Alembic's ``op``, recording each statement and whether it ran in the autocommit block."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, bool]] = []
        self._autocommit = False

    def execute(self, statement: str) -> None:
        self.statements.append((" ".join(statement.split()), self._autocommit))

    def get_context(self) -> _RecordingOp:
        return self

    @contextmanager
    def autocommit_block(self) -> Iterator[None]:
        self._autocommit = True
        try:
            yield
        finally:
            self._autocommit = False


def _migration(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, _RecordingOp]:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "3f0b61c7a2d4_execution_node_operation_index.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_3f0b61c7a2d4", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)
    return module, recorder


def test_the_operation_index_is_built_without_blocking_journal_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix pass 1, review A1-I1: a plain ``CREATE INDEX`` takes a SHARE lock and blocks every
    write to ``execution_node`` for the whole build — every agent turn and research run stalls
    during the deploy. Built ``CONCURRENTLY`` in the autocommit block, as the repo's other index
    migrations are, dropping an INVALID leftover of an interrupted build first."""

    module, recorder = _migration(monkeypatch)
    module.upgrade()
    assert recorder.statements == [
        ("DROP INDEX CONCURRENTLY IF EXISTS execution_node_operation", True),
        (
            "CREATE INDEX CONCURRENTLY execution_node_operation ON execution_node (operation_id)",
            True,
        ),
    ]

    recorder.statements.clear()
    module.downgrade()
    assert recorder.statements == [
        ("DROP INDEX CONCURRENTLY IF EXISTS execution_node_operation", True),
    ]
