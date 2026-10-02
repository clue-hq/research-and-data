"""Rename and archive on the design DAL (artifacts-page spec §3.3–§3.4).

Two library marks a human puts on a document without editing it:

* **rename** — the row's ``title`` and the document JSON's own title move together, under a
  version bump, so the next save from an open editor cannot revert the new name.
* **archive** — a gallery state independent of publish, converging on re-run, and deliberately
  NOT a version bump or an ``updated_at`` touch (archiving is not an edit).

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import documents as design_documents
from tests.design.conftest import run_async


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_marks_{uuid4().hex[:12]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


def _scene(doc_id: str, title: str = "Before") -> dict[str, Any]:
    return {"meta": {"id": doc_id, "title": title, "status": {"kind": "draft"}}, "nodes": []}


def test_rename_updates_row_and_scene_title_and_bumps_the_version(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            created = await design_documents.create_document(
                conn, workspace_id=ws, scene=_scene(doc_id)
            )
            before = created["current_version"]
            renamed = await design_documents.rename_document(
                conn, workspace_id=ws, document_id=doc_id, title="  After  "
            )
            assert renamed["title"] == "After"
            assert renamed["scene"]["meta"]["title"] == "After"
            assert renamed["current_version"] == before + 1
            with pytest.raises(ValueError):
                await design_documents.rename_document(
                    conn, workspace_id=ws, document_id=doc_id, title="   "
                )
            await txn.rollback()

    run_async(_check())


def test_archive_sets_and_clears_without_touching_the_version(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            created = await design_documents.create_document(
                conn, workspace_id=ws, scene=_scene(doc_id)
            )
            assert created["archived_at"] is None
            archived = await design_documents.set_document_archived(
                conn, workspace_id=ws, document_id=doc_id, enabled=True
            )
            assert archived["archived_at"] is not None
            again = await design_documents.set_document_archived(
                conn, workspace_id=ws, document_id=doc_id, enabled=True
            )
            assert again["archived_at"] == archived["archived_at"]  # converges
            assert again["current_version"] == created["current_version"]
            assert again["updated_at"] == created["updated_at"]
            restored = await design_documents.set_document_archived(
                conn, workspace_id=ws, document_id=doc_id, enabled=False
            )
            assert restored["archived_at"] is None
            await txn.rollback()

    run_async(_check())
