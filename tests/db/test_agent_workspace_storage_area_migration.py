"""F3 Phase 2 (spec WS-30/AW-26, plan Task 1): a chat's snapshot files get their own storage
area, so expiring one can never reach an upload, a Gallery artifact or a research output.

``artifact_key_encodes_scope`` must admit the third shape ``{workspace|public}/agent-workspace/
{sha256}`` and nothing else new: an invented namespace is still an integrity error.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
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


async def _insert(conn: AsyncConnection, storage_key: str, *, sha: str = _SHA) -> None:
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, 'ws_x', :sha, 'application/octet-stream', 7)"
        ),
        {"key": storage_key, "sha": sha},
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


_STORAGE_AREA = "22172f5ba3cb_agent_workspace_storage_area.py"
_OPERATION_INDEX = "3f0b61c7a2d4_execution_node_operation_index.py"


def _load(filename: str) -> ModuleType:
    """One revision file as a module, so its ``upgrade``/``downgrade`` can be driven directly."""

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"_migration_{filename[:12]}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(conn: AsyncConnection, step: Callable[[], None]) -> None:
    """Run one migration function on ``conn`` with Alembic's real ``op`` bound to it."""

    def run(sync_conn: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_conn)):
            step()

    await conn.run_sync(run)


def _migration(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, _RecordingOp]:
    module = _load(_OPERATION_INDEX)
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


# --- The two revisions' downgrades, driven directly (review area 1, T4) --------------------------
#
# ``tests/db/test_db_migrations.py``'s whole-chain up/down/up cannot run on this test database for
# a reason older than these revisions, so each downgrade is run here on its own, against the live
# schema, through Alembic's real ``op``.

_AREA_KEY = f"ws_x/agent-workspace/{_SHA}"


@pytest.mark.usefixtures("require_db")
def test_the_storage_area_downgrade_refuses_while_an_area_row_exists() -> None:
    """Those keys cannot be written under the two-shape constraint, so the downgrade must stop
    before it touches the constraint — not fail half-way on the constraint's own check."""

    module = _load(_STORAGE_AREA)

    async def body(conn: AsyncConnection) -> None:
        await _insert(conn, _AREA_KEY)
        with pytest.raises(RuntimeError, match="agent-workspace area exist"):
            await _run(conn, module.downgrade)
        # Nothing was changed: the area's shape is still accepted.
        other = "cd" * 32
        await _insert(conn, f"ws_x/agent-workspace/{other}", sha=other)

    run_async(_with_rollback(body))


@pytest.mark.usefixtures("require_db")
def test_the_storage_area_downgrade_restores_the_two_shapes_once_the_area_is_empty() -> None:
    """With no area row, the downgrade puts back exactly the two older shapes — bare and design
    keys accepted, area keys refused — and the upgrade then admits the area again. Rows other
    tests left in the area are removed inside this test's transaction and come back with its
    rollback."""

    module = _load(_STORAGE_AREA)

    async def body(conn: AsyncConnection) -> None:
        area = "storage_key LIKE '%/agent-workspace/%'"
        await conn.execute(text(f"DELETE FROM artifact_reference WHERE {area}"))
        await conn.execute(text(f"DELETE FROM artifact WHERE {area}"))

        await _run(conn, module.downgrade)

        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await _insert(conn, _AREA_KEY)
        await _insert(conn, f"ws_x/{_SHA}")
        await _insert(conn, f"ws_x/design/{_SHA}")

        await _run(conn, module.upgrade)
        await _insert(conn, _AREA_KEY)

    run_async(_with_rollback(body))


async def _operation_index(conn: AsyncConnection) -> tuple[str, bool] | None:
    """``(indexdef, valid)`` of the operation index, or ``None`` when there is none."""

    row = (
        await conn.execute(
            text(
                "SELECT pg_indexes.indexdef, pg_index.indisvalid FROM pg_indexes "
                "JOIN pg_class ON pg_class.relname = pg_indexes.indexname "
                "JOIN pg_index ON pg_index.indexrelid = pg_class.oid "
                "WHERE pg_indexes.tablename = 'execution_node' "
                "AND pg_indexes.indexname = 'execution_node_operation'"
            )
        )
    ).first()
    return None if row is None else (str(row[0]), bool(row[1]))


@pytest.mark.usefixtures("require_db")
def test_the_operation_index_downgrade_then_upgrade_leaves_a_valid_index() -> None:
    """Built and dropped ``CONCURRENTLY``, so this runs outside any transaction, for real; the
    upgrade runs in a ``finally`` so a failing assertion never leaves the test DB without it."""

    module = _load(_OPERATION_INDEX)

    async def body() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            try:
                await _run(conn, module.downgrade)
                assert await _operation_index(conn) is None
            finally:
                # The read above opened a transaction, and CONCURRENTLY may not run inside one.
                await conn.rollback()
                await _run(conn, module.upgrade)
            index = await _operation_index(conn)
            assert index is not None, "the upgrade did not build the index"
            definition, valid = index
            assert valid
            assert definition.endswith("USING btree (operation_id)")

    run_async(body())
