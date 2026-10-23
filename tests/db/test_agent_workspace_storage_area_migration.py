"""F3 Phase 2 (spec WS-30/AW-26, plan Task 1): a chat's snapshot files get their own storage
area, so expiring one can never reach an upload, a Gallery artifact or a research output.

``artifact_key_encodes_scope`` must admit the third shape ``{workspace|public}/agent-workspace/
{sha256}`` and nothing else new: an invented namespace is still an integrity error.
"""

from __future__ import annotations

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
