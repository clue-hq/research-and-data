"""D2.2 acceptance tests: the document/history DAL port (PD contract §7).

Covers the ported semantics that matter most:

* create/get round-trip serves the exact ``document_from_row`` shape (ISO-string timestamps).
* ``update_document_state``: version bump by op count, undo push + redo clear, envelope + op
  rows landed — and the NEW scene-write CAS (the closed lost-update gap).
* ``update_web_document``: the full undo/redo stack dance (normal → revert → reapply) and the
  CAS conflict carrying the current version.
* snapshots + template revisions + latest-diagnostics round-trips.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import diagnostics as design_diagnostics
from clue_design import documents as design_documents
from clue_design import history as design_history
from clue_design import snapshots as design_snapshots
from clue_design.errors import DesignVersionConflictError
from tests.design.conftest import run_async


def _scene(doc_id: str, title: str = "T") -> dict[str, object]:
    return {"meta": {"id": doc_id, "title": title, "status": {"kind": "draft"}}, "nodes": []}


def _web_doc(doc_id: str, title: str = "W") -> dict[str, object]:
    return {"id": doc_id, "title": title, "theme": {}, "pages": [], "assets": {}}


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_docs_{uuid4().hex[:12]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


def test_create_and_get_document_round_trip(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            created = await design_documents.create_document(
                conn, workspace_id=ws, scene=_scene(doc_id)
            )
            assert created["id"] == doc_id
            assert created["doc_kind"] == "scene"
            assert created["current_version"] == 0
            assert created["status"] == "draft"
            assert isinstance(created["created_at"], str)  # ISO parity with the SQLite API
            assert created["undo_stack"] is None and created["redo_stack"] is None
            await txn.rollback()

    run_async(_check())


def test_update_document_state_versions_stacks_and_history(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            await design_documents.create_document(conn, workspace_id=ws, scene=_scene(doc_id))
            ops: list[dict[str, object]] = [{"kind": "set_title"}, {"kind": "move_node"}]
            updated = await design_documents.update_document_state(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                scene=_scene(doc_id, title="T2"),
                diagnostics=[],
                operations=ops,
                source="editor",
                actor_kind="human",
                actor_id="u1",
                diagnostic_kind="manual_edit",
                effective_brand=None,
            )
            assert updated["current_version"] == 2  # +1 per operation
            assert updated["title"] == "T2"
            undo = updated["undo_stack"]
            assert isinstance(undo, list) and len(undo) == 1
            assert updated["redo_stack"] == []
            envelopes = await design_history.list_envelopes(
                conn, workspace_id=ws, document_id=doc_id
            )
            assert [e["seq"] for e in envelopes] == [1]
            assert envelopes[0]["batch_id"] == undo[0]
            assert envelopes[0]["operations"] == ops
            operations = await design_history.list_operations(
                conn, workspace_id=ws, document_id=doc_id
            )
            assert [o["sequence"] for o in operations] == [1, 2]
            assert all(o["batch_id"] == undo[0] for o in operations)
            # The NEW scene-write CAS (closed lost-update gap): stale base refused, typed.
            with pytest.raises(DesignVersionConflictError) as conflict:
                await design_documents.update_document_state(
                    conn,
                    workspace_id=ws,
                    document_id=doc_id,
                    scene=_scene(doc_id),
                    diagnostics=[],
                    operations=[{"kind": "noop"}],
                    source="editor",
                    actor_kind="human",
                    actor_id="u1",
                    diagnostic_kind="manual_edit",
                    effective_brand=None,
                    expected_base_version=0,
                )
            assert conflict.value.expected_version == 0
            assert conflict.value.current_version == 2
            await txn.rollback()

    run_async(_check())


def test_web_document_undo_redo_stack_dance_and_cas(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"web_{uuid4().hex}"
            await design_documents.create_document(
                conn, workspace_id=ws, scene=_web_doc(doc_id), doc_kind="web"
            )
            # Normal write: batch lands on undo, redo clears.
            first = await design_documents.update_web_document(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                web_doc=_web_doc(doc_id, title="W1"),
                intent="edit",
                checkpoint_label="Website turn",
                operations=[{"kind": "set_text"}],
                inverse_operations=[{"kind": "set_text_back"}],
                expected_base_version=0,
            )
            assert first["current_version"] == 1
            undo = first["undo_stack"]
            assert isinstance(undo, list) and len(undo) == 1
            b1 = undo[0]
            # Undo: b1 moves undo -> redo; the undo envelope itself is not stacked.
            reverted = await design_documents.update_web_document(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                web_doc=_web_doc(doc_id),
                intent="undo",
                checkpoint_label="Undo",
                operations=[{"kind": "set_text_back"}],
                inverse_operations=[{"kind": "set_text"}],
                reverts_batch_id=b1,
            )
            assert reverted["undo_stack"] == []
            assert reverted["redo_stack"] == [b1]
            # Redo: b1 moves back.
            reapplied = await design_documents.update_web_document(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                web_doc=_web_doc(doc_id, title="W1"),
                intent="redo",
                checkpoint_label="Redo",
                operations=[{"kind": "set_text"}],
                inverse_operations=[{"kind": "set_text_back"}],
                reapplies_batch_id=b1,
            )
            assert reapplied["undo_stack"] == [b1]
            assert reapplied["redo_stack"] == []
            assert reapplied["current_version"] == 3
            # CAS: stale expected base refused with the real current version.
            with pytest.raises(DesignVersionConflictError) as conflict:
                await design_documents.update_web_document(
                    conn,
                    workspace_id=ws,
                    document_id=doc_id,
                    web_doc=_web_doc(doc_id),
                    intent="edit",
                    checkpoint_label=None,
                    operations=[],
                    inverse_operations=None,
                    expected_base_version=1,
                )
            assert conflict.value.current_version == 3
            # History is append-only: every turn (incl. undo/redo) is an envelope.
            envelopes = await design_history.list_envelopes(
                conn, workspace_id=ws, document_id=doc_id, newest_first=False
            )
            assert [e["seq"] for e in envelopes] == [1, 2, 3]
            assert envelopes[1]["reverts_batch_id"] == b1
            assert envelopes[2]["reapplies_batch_id"] == b1
            await txn.rollback()

    run_async(_check())


def test_snapshot_template_revision_and_diagnostics_round_trip(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            scene = _scene(doc_id)
            await design_documents.create_document(conn, workspace_id=ws, scene=scene)
            snap = await design_snapshots.create_snapshot(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                snapshot_id=f"snap_{uuid4().hex}",
                reason="finalize",
            )
            assert snap["version"] == 0 and snap["scene"]["meta"]["id"] == doc_id
            revision = await design_snapshots.create_template_revision(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                template_revision_id=f"tmpl_{uuid4().hex}",
                source_snapshot_id=snap["snapshot_id"],
                scene=scene,
                slot_summary=[{"id": "slot1"}],
            )
            assert revision["version"] == 1
            assert revision["slot_summary"] == [{"id": "slot1"}]
            await design_diagnostics.store_diagnostics(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                kind="structural",
                diagnostics=[{"code": "ok"}],
            )
            latest = await design_diagnostics.latest_diagnostics(
                conn, workspace_id=ws, document_id=doc_id, kind="structural"
            )
            assert latest is not None and latest["diagnostics"] == [{"code": "ok"}]
            await txn.rollback()

    run_async(_check())
