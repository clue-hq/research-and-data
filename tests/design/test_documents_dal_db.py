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

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import brand as design_brand
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


def _site_doc(doc_id: str, title: str = "S") -> dict[str, object]:
    return {
        "id": doc_id,
        "title": title,
        "theme": {},
        "pages": {"/": {"root": {"props": {"title": title}}, "content": []}},
        "shell": None,
        "agent_sections": {},
    }


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_docs_{uuid4().hex[:12]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _seed_brand_kit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    version: int,
    approval_status: str,
) -> dict[str, object]:
    return await design_brand.create_brand_kit(
        conn,
        workspace_id=workspace_id,
        brand_kit={
            "id": "kit_workspace_brand",
            "version": version,
            "name": "Workspace brand",
            "approval_status": approval_status,
        },
        brand_summary={"product_ready": False},
        diagnostics=[],
        source="website",
    )


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


def test_web_documents_stamp_only_the_latest_approved_kit_at_birth(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _seed_brand_kit(conn, workspace_id=ws, version=1, approval_status="draft")

            before_id = f"web_before_{uuid4().hex}"
            before = await design_documents.create_document(
                conn, workspace_id=ws, scene=_web_doc(before_id), doc_kind="web"
            )
            assert before["scene"]["theme"].get("brand_kit") is None

            await design_brand.update_brand_kit_approval(
                conn,
                workspace_id=ws,
                brand_kit_id="kit_workspace_brand",
                approval_status="approved",
            )

            # Approval never re-stamps a document that already exists.
            unchanged = await design_documents.get_document(
                conn, workspace_id=ws, document_id=before_id
            )
            assert unchanged["scene"]["theme"].get("brand_kit") is None

            after = await design_documents.create_document(
                conn,
                workspace_id=ws,
                scene=_web_doc(f"web_after_{uuid4().hex}"),
                doc_kind="web",
            )
            assert after["scene"]["theme"]["brand_kit"] == {
                "id": "kit_workspace_brand",
                "version": 1,
            }

            # Saving an old unthemed document as a new template is another document birth and
            # passes through the second durable insert seam.
            template_doc = _web_doc(f"web_template_{uuid4().hex}")
            template = await design_documents.create_web_template(
                conn, workspace_id=ws, web_doc=template_doc
            )
            assert template["scene"]["theme"]["brand_kit"] == {
                "id": "kit_workspace_brand",
                "version": 1,
            }

            # A newer draft does not shadow the newest approved version.
            await _seed_brand_kit(conn, workspace_id=ws, version=2, approval_status="draft")
            latest_approved = await design_documents.create_document(
                conn,
                workspace_id=ws,
                scene=_web_doc(f"web_latest_approved_{uuid4().hex}"),
                doc_kind="web",
            )
            assert latest_approved["scene"]["theme"]["brand_kit"] == {
                "id": "kit_workspace_brand",
                "version": 1,
            }

            explicit_ref = {"id": "kit_explicit", "version": 7}
            explicit_doc = _web_doc(f"web_explicit_{uuid4().hex}")
            explicit_doc["theme"] = {"brand_kit": explicit_ref}
            explicit = await design_documents.create_document(
                conn, workspace_id=ws, scene=explicit_doc, doc_kind="web"
            )
            assert explicit["scene"]["theme"]["brand_kit"] == explicit_ref
            await txn.rollback()

    run_async(_check())


def test_site_documents_are_born_like_web_documents(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _seed_brand_kit(conn, workspace_id=ws, version=1, approval_status="approved")
            doc_id = f"site_{uuid4().hex}"
            born = await design_documents.create_document(
                conn, workspace_id=ws, scene=_site_doc(doc_id), doc_kind="site"
            )
            assert born["doc_kind"] == "site"
            assert born["title"] == "S"
            assert born["scene"]["theme"]["brand_kit"] == {
                "id": "kit_workspace_brand",
                "version": 1,
            }
            renamed = await design_documents.rename_document(
                conn, workspace_id=ws, document_id=doc_id, title="Renamed"
            )
            assert renamed["scene"]["title"] == "Renamed"  # top-level title, not meta.title
            updated = await design_documents.update_web_document(
                conn,
                workspace_id=ws,
                document_id=doc_id,
                web_doc={**renamed["scene"], "shell": {"header": {}}},
                intent="site_write",
                checkpoint_label=None,
                operations=[{"op": "replace_site"}],
                inverse_operations=[{"op": "replace_site", "site": renamed["scene"]}],
                expected_base_version=renamed["current_version"],
            )
            assert updated["current_version"] == renamed["current_version"] + 1
            await txn.rollback()

    run_async(_check())


def test_web_document_default_fails_closed_for_a_multi_brand_workspace(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _seed_brand_kit(conn, workspace_id=ws, version=1, approval_status="approved")
            await conn.execute(
                text(
                    "INSERT INTO brand (brand_id, workspace_id, name) "
                    "VALUES (:brand_id, :workspace_id, 'Second brand')"
                ),
                {"brand_id": f"brd_{uuid4().hex}", "workspace_id": ws},
            )

            created = await design_documents.create_document(
                conn,
                workspace_id=ws,
                scene=_web_doc(f"web_ambiguous_{uuid4().hex}"),
                doc_kind="web",
            )
            assert created["scene"]["theme"].get("brand_kit") is None
            await txn.rollback()

    run_async(_check())


def test_scene_birth_stamps_the_latest_approved_kit(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _seed_brand_kit(conn, workspace_id=ws, version=1, approval_status="approved")

            scene = _scene(f"doc_stamp_scene_1_{uuid4().hex}", title="Ad")
            doc = await design_documents.create_document(
                conn, workspace_id=ws, scene=scene, doc_kind="scene"
            )
            assert doc["scene"]["meta"]["brand_kit"] == {
                "id": "kit_workspace_brand",
                "version": 1,
            }
            assert doc["effective_brand_kit_id"] == "kit_workspace_brand"
            assert doc["effective_brand_kit_version"] == 1
            await txn.rollback()

    run_async(_check())


def test_scene_birth_respects_an_explicit_caller_kit(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _seed_brand_kit(conn, workspace_id=ws, version=1, approval_status="approved")

            scene = _scene(f"doc_stamp_scene_2_{uuid4().hex}", title="Ad")
            scene["meta"]["brand_kit"] = {"id": "brand_kit_other", "version": 3}  # type: ignore[index]
            doc = await design_documents.create_document(
                conn, workspace_id=ws, scene=scene, doc_kind="scene"
            )
            assert doc["scene"]["meta"]["brand_kit"] == {"id": "brand_kit_other", "version": 3}
            await txn.rollback()

    run_async(_check())


def test_scene_birth_without_an_approved_kit_stays_unbranded(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)

            scene = _scene(f"doc_stamp_scene_3_{uuid4().hex}", title="Ad")
            doc = await design_documents.create_document(
                conn, workspace_id=ws, scene=scene, doc_kind="scene"
            )
            assert doc["scene"]["meta"].get("brand_kit") is None
            assert doc["effective_brand_kit_id"] is None
            await txn.rollback()

    run_async(_check())


def test_every_new_website_document_is_born_noindex_and_a_scene_is_not(
    require_design_db: None,
) -> None:
    """Founder ruling 2026-10-16: every NEW web or site document is born with the durable
    ``web_noindex``, whichever insert births it (a plain document, a derivation, a template); a
    scene has no publish surface and stays false. A document that already exists keeps what it
    holds — nothing here rewrites a row — and only an explicit clear makes a page indexable."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)

            # A document from before the ruling: an indexable web row, as every old one was born.
            existing_id = f"web_existing_{uuid4().hex}"
            await conn.execute(
                text(
                    "INSERT INTO design_document (id, workspace_id, title, status, doc_kind,"
                    " current_scene_json, current_version, web_noindex)"
                    " VALUES (:d, :w, 'Old', 'draft', 'web', CAST(:s AS jsonb), 0, false)"
                ),
                {"d": existing_id, "w": ws, "s": json.dumps(_web_doc(existing_id))},
            )

            web = await design_documents.create_document(
                conn, workspace_id=ws, scene=_web_doc(f"web_{uuid4().hex}"), doc_kind="web"
            )
            site = await design_documents.create_document(
                conn, workspace_id=ws, scene=_site_doc(f"site_{uuid4().hex}"), doc_kind="site"
            )
            derived = await design_documents.create_document(
                conn,
                workspace_id=ws,
                scene=_web_doc(f"web_derived_{uuid4().hex}"),
                doc_kind="web",
                template_document_id=str(web["id"]),
                template_doc_version=0,
            )
            template = await design_documents.create_web_template(
                conn, workspace_id=ws, web_doc=_web_doc(f"web_template_{uuid4().hex}")
            )
            scene = await design_documents.create_document(
                conn, workspace_id=ws, scene=_scene(f"doc_{uuid4().hex}")
            )
            assert [d["web_noindex"] for d in (web, site, derived, template)] == [True] * 4
            assert scene["web_noindex"] is False

            # The births touched no other row.
            old = await design_documents.get_document(
                conn, workspace_id=ws, document_id=existing_id
            )
            assert old["web_noindex"] is False

            # "Allow indexing" is the explicit clear, and it holds.
            cleared = await design_documents.set_web_noindex(
                conn, workspace_id=ws, document_id=str(web["id"]), enabled=False
            )
            assert cleared["web_noindex"] is False
            again = await design_documents.get_document(
                conn, workspace_id=ws, document_id=str(web["id"])
            )
            assert again["web_noindex"] is False
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
