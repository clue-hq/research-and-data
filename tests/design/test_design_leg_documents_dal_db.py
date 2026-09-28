"""Spec §3.2 — one leg, many documents, position-ordered; design_leg.document_id stays position 0.

Mirrors its neighbour ``test_design_leg_dal_db``: a session-migrated DB, every write inside a
transaction that is rolled back, and a graceful skip when no database is reachable.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import legs as design_legs
from clue_design.legs import LegDocumentSpec
from tests._workspace import seed_project
from tests.design.conftest import run_async
from tests.design.test_design_leg_dal_db import _seed_thread_and_execution  # ws, thread, execution


async def _seed_scene_document(conn: AsyncConnection, *, workspace_id: str, title: str) -> str:
    document_id = f"doc_{uuid4().hex}"
    scene = json.dumps(
        {
            "schema_version": 1,
            "meta": {"id": document_id, "title": title},
            "pages": {},
            "nodes": {},
        }
    )
    await conn.execute(
        text(
            "INSERT INTO design_document (id, workspace_id, title, status, doc_kind, "
            "current_scene_json, current_version) VALUES (:id, :w, :t, 'draft', 'scene', "
            "CAST(:scene AS jsonb), 0)"
        ),
        {"id": document_id, "w": workspace_id, "t": title, "scene": scene},
    )
    return document_id


def test_leg_documents_list_in_position_order_with_document_facts(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed_thread_and_execution(conn)
            ws = seeds["ws"]
            first = await _seed_scene_document(conn, workspace_id=ws, title="Apollo ad")
            second = await _seed_scene_document(conn, workspace_id=ws, title="Mercy ad")
            leg = await design_legs.open_leg(
                conn,
                workspace_id=ws,
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
                document_id=first,
                document_version_guard=0,
            )
            await design_legs.add_leg_documents(
                conn,
                workspace_id=ws,
                leg_id=leg["id"],
                documents=[
                    LegDocumentSpec(first, 0, "for Apollo"),
                    LegDocumentSpec(second, 1, "for Mercy"),
                ],
            )
            rows = await design_legs.list_leg_documents(conn, workspace_id=ws, leg_id=leg["id"])
            assert [
                (r["position"], r["document_id"], r["note"], r["title"], r["doc_kind"])
                for r in rows
            ] == [
                (0, first, "for Apollo", "Apollo ad", "scene"),
                (1, second, "for Mercy", "Mercy ad", "scene"),
            ]
            assert rows[0]["current_version"] == 0
            assert rows[0]["account_id"] is None
            # A duplicate position, or the same document twice, is refused by the schema.
            with pytest.raises(IntegrityError, match="design_leg_document_pkey"):
                async with conn.begin_nested():
                    await design_legs.add_leg_documents(
                        conn,
                        workspace_id=ws,
                        leg_id=leg["id"],
                        documents=[LegDocumentSpec(second, 0)],
                    )
            await txn.rollback()

    run_async(scenario())


def test_a_foreign_workspace_document_cannot_join_a_leg(migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
            seeds = await _seed_thread_and_execution(conn)
            other = await seed_project(conn, f"ws_other_{uuid4().hex[:8]}", name="other")
            foreign = await _seed_scene_document(conn, workspace_id=other.workspace_id, title="x")
            leg = await design_legs.open_leg(
                conn,
                workspace_id=seeds["ws"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
            )
            with pytest.raises(IntegrityError, match="design_leg_document_document_fk"):
                await design_legs.add_leg_documents(
                    conn,
                    workspace_id=seeds["ws"],
                    leg_id=leg["id"],
                    documents=[LegDocumentSpec(foreign, 0)],
                )

    run_async(scenario())
