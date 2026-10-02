"""D2.4 acceptance tests: the personalization + web account/batch DAL port (PD contract §7).

Covers the ported semantics that matter most:

* binding sets: upsert round-trip (re-authoring replaces the payload, never duplicates).
* instances: the DETERMINISTIC id means a second derivation of the same (revision, binding)
  refreshes ONE row.
* instance batches: create + chunked progress/cursor update.
* the repair queue: re-detecting the same overflow upserts the SAME open row (status is not
  re-opened, the ported behaviour).
* web accounts: CRUD, the partial patch, and fail-closed cross-workspace ``require``.
* the re-added ``design_document_account_fk``: deleting an account SET-NULLs a document's
  ``account_id`` stamp instead of leaving it dangling (migration ``cf7dd82cf683``).
* web batches: create + manifest/cursor progress round-trip.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import accounts as design_accounts
from clue_design import documents as design_documents
from clue_design import personalization as design_personalization
from clue_design import snapshots as design_snapshots
from clue_design.errors import DesignNotFoundError
from tests.design.conftest import run_async


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_pers_{uuid4().hex[:12]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


def _scene(doc_id: str, title: str = "T") -> dict[str, Any]:
    return {"meta": {"id": doc_id, "title": title, "status": {"kind": "draft"}}, "nodes": []}


async def _seed_revision(conn: AsyncConnection, ws: str) -> str:
    """A frozen template revision — the anchor every personalization row FKs onto."""
    doc_id = f"doc_{uuid4().hex}"
    await design_documents.create_document(conn, workspace_id=ws, scene=_scene(doc_id))
    revision_id = f"rev_{uuid4().hex[:12]}"
    await design_snapshots.create_template_revision(
        conn,
        workspace_id=ws,
        document_id=doc_id,
        template_revision_id=revision_id,
        source_snapshot_id=None,
        scene=_scene(doc_id),
        slot_summary=[],
    )
    return revision_id


def _binding(binding_set_id: str, revision_id: str, value: str) -> dict[str, Any]:
    return {
        "binding_set_id": binding_set_id,
        "template_revision_id": revision_id,
        "values": {"headline": {"kind": "text", "value": value}},
    }


def _instance(
    instance_id: str, revision_id: str, binding_set_id: str, **over: Any
) -> dict[str, Any]:
    instance: dict[str, Any] = {
        "instance_id": instance_id,
        "template_revision_id": revision_id,
        "binding_set_id": binding_set_id,
        "batch_id": None,
        "status": "derived",
        "fit_status": "fits",
        "derived_scene": {"meta": {"id": instance_id}, "nodes": []},
        "diagnostics": [],
        "audit": [],
        "fit_report": {},
        "artifacts": [],
        "generated_assets": {},
    }
    instance.update(over)
    return instance


def test_binding_set_upsert_round_trip(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            revision_id = await _seed_revision(conn, ws)
            binding_set_id = f"bind_{uuid4().hex[:12]}"
            stored = await design_personalization.upsert_binding_set(
                conn,
                workspace_id=ws,
                binding=_binding(binding_set_id, revision_id, "Hello"),
                status="valid",
                diagnostics=[],
            )
            assert stored["binding_set_id"] == binding_set_id
            assert stored["template_revision_id"] == revision_id
            assert stored["status"] == "valid"
            assert stored["binding_set"]["values"]["headline"]["value"] == "Hello"
            assert isinstance(stored["created_at"], str)  # ISO parity with the SQLite API
            # Re-authoring the SAME id replaces payload/status/diagnostics in place.
            again = await design_personalization.upsert_binding_set(
                conn,
                workspace_id=ws,
                binding=_binding(binding_set_id, revision_id, "Bonjour"),
                status="invalid",
                diagnostics=[{"code": "LUMG0001"}],
            )
            assert again["binding_set"]["values"]["headline"]["value"] == "Bonjour"
            assert again["status"] == "invalid"
            assert again["diagnostics"] == [{"code": "LUMG0001"}]
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_binding_set WHERE workspace_id = :w"),
                    {"w": ws},
                )
            ).scalar_one()
            assert count == 1  # upsert, never a second row
            listed = await design_personalization.list_binding_sets(
                conn, workspace_id=ws, template_revision_id=revision_id
            )
            assert [row["binding_set_id"] for row in listed] == [binding_set_id]
            # Fail-closed: another workspace's id is as absent as a made-up one — and (since
            # migration cf7dd82cf683) the id is workspace-LOCAL, so the second tenant may hold
            # it without colliding and without touching the first tenant's row.
            other_ws = await _seed_ws(conn)
            with pytest.raises(DesignNotFoundError):
                await design_personalization.get_binding_set(
                    conn, workspace_id=other_ws, binding_set_id=binding_set_id
                )
            other_revision_id = await _seed_revision(conn, other_ws)
            twin = await design_personalization.upsert_binding_set(
                conn,
                workspace_id=other_ws,
                binding=_binding(binding_set_id, other_revision_id, "Hola"),
                status="valid",
                diagnostics=[],
            )
            assert twin["template_revision_id"] == other_revision_id
            mine = await design_personalization.get_binding_set(
                conn, workspace_id=ws, binding_set_id=binding_set_id
            )
            assert mine["template_revision_id"] == revision_id  # untouched
            assert mine["binding_set"]["values"]["headline"]["value"] == "Bonjour"
            await design_personalization.delete_binding_set(
                conn, workspace_id=ws, binding_set_id=binding_set_id
            )
            assert await design_personalization.list_binding_sets(conn, workspace_id=ws) == []
            await txn.rollback()

    run_async(_check())


def test_instance_upsert_is_idempotent_on_the_deterministic_id(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            revision_id = await _seed_revision(conn, ws)
            binding_set_id = f"bind_{uuid4().hex[:12]}"
            await design_personalization.upsert_binding_set(
                conn,
                workspace_id=ws,
                binding=_binding(binding_set_id, revision_id, "Hello"),
                status="valid",
                diagnostics=[],
            )
            instance_id = f"inst_{uuid4().hex[:12]}"
            first = await design_personalization.upsert_instance(
                conn,
                workspace_id=ws,
                instance=_instance(instance_id, revision_id, binding_set_id),
            )
            assert first["status"] == "derived"
            assert first["fit_status"] == "fits"
            assert first["batch_id"] is None
            # The SAME deterministic id re-derived: one row, refreshed.
            second = await design_personalization.upsert_instance(
                conn,
                workspace_id=ws,
                instance=_instance(
                    instance_id,
                    revision_id,
                    binding_set_id,
                    status="failed",
                    fit_status="overflow",
                    diagnostics=[{"code": "LUMG0321"}],
                    artifacts=[{"format": "png"}],
                ),
            )
            assert second["status"] == "failed"
            assert second["fit_status"] == "overflow"
            assert second["diagnostics"] == [{"code": "LUMG0321"}]
            assert second["artifacts"] == [{"format": "png"}]
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_instance WHERE workspace_id = :w"),
                    {"w": ws},
                )
            ).scalar_one()
            assert count == 1
            assert (
                len(
                    await design_personalization.list_instances(
                        conn, workspace_id=ws, template_revision_id=revision_id
                    )
                )
                == 1
            )
            assert (
                await design_personalization.list_instances(
                    conn, workspace_id=ws, batch_id="batch_absent"
                )
                == []
            )
            await txn.rollback()

    run_async(_check())


def test_instance_batch_create_and_progress_update(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            revision_id = await _seed_revision(conn, ws)
            batch_id = f"batch_{uuid4().hex[:12]}"
            created = await design_personalization.create_instance_batch(
                conn,
                workspace_id=ws,
                batch={
                    "batch_id": batch_id,
                    "template_revision_id": revision_id,
                    "status": "running",
                    "binding_set_ids": ["bind_a", "bind_b"],
                    "export_formats": ["png"],
                    "chunk_size": 1,
                    "cursor": 0,
                },
            )
            assert created["status"] == "running"
            assert created["binding_set_ids"] == ["bind_a", "bind_b"]
            assert created["export_profile"] is None  # nullable column, ported as optional
            assert created["counts"] == {} and created["manifest"] == []
            updated = await design_personalization.update_instance_batch_progress(
                conn,
                workspace_id=ws,
                batch_id=batch_id,
                cursor=1,
                status="partial",
                counts={"total": 2, "derived": 1},
                manifest=[{"binding_set_id": "bind_a", "status": "derived"}],
                diagnostics=[{"code": "LUMG0001"}],
            )
            assert updated["cursor"] == 1
            assert updated["status"] == "partial"
            assert updated["counts"] == {"total": 2, "derived": 1}
            assert updated["manifest"] == [{"binding_set_id": "bind_a", "status": "derived"}]
            assert updated["diagnostics"] == [{"code": "LUMG0001"}]
            with pytest.raises(DesignNotFoundError):
                await design_personalization.get_instance_batch(
                    conn, workspace_id=ws, batch_id="batch_absent"
                )
            await txn.rollback()

    run_async(_check())


def test_repair_request_re_detection_updates_the_same_open_row(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            revision_id = await _seed_revision(conn, ws)
            binding_set_id = f"bind_{uuid4().hex[:12]}"
            await design_personalization.upsert_binding_set(
                conn,
                workspace_id=ws,
                binding=_binding(binding_set_id, revision_id, "Hello"),
                status="valid",
                diagnostics=[],
            )
            repair_id = f"rep_{uuid4().hex[:12]}"
            repair = {
                "repair_id": repair_id,
                "template_revision_id": revision_id,
                "slot_key": "headline",
                "node_id": "node_1",
                "binding_set_id": binding_set_id,
                "instance_id": None,
                "reason": "text overflows the slot",
            }
            first = await design_personalization.upsert_repair_request(
                conn, workspace_id=ws, repair=repair
            )
            assert first["status"] == "open"
            assert first["instance_id"] is None
            # The same overflow re-detected, now attributed to a concrete instance.
            instance_id = f"inst_{uuid4().hex[:12]}"
            await design_personalization.upsert_instance(
                conn,
                workspace_id=ws,
                instance=_instance(instance_id, revision_id, binding_set_id),
            )
            second = await design_personalization.upsert_repair_request(
                conn,
                workspace_id=ws,
                repair={**repair, "instance_id": instance_id, "reason": "still overflows"},
            )
            assert second["repair_id"] == repair_id  # SAME row
            assert second["instance_id"] == instance_id
            assert second["reason"] == "still overflows"
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_repair_request WHERE workspace_id = :w"),
                    {"w": ws},
                )
            ).scalar_one()
            assert count == 1
            queue = await design_personalization.list_repair_queue(
                conn, workspace_id=ws, template_revision_id=revision_id, status="open"
            )
            assert [row["repair_id"] for row in queue] == [repair_id]
            assert (
                await design_personalization.list_repair_queue(
                    conn, workspace_id=ws, template_revision_id=revision_id, status="resolved"
                )
                == []
            )
            await txn.rollback()

    run_async(_check())


def test_web_account_crud_and_fail_closed_cross_workspace_require(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            other_ws = await _seed_ws(conn)
            account_id = f"acc_{uuid4().hex[:12]}"
            created = await design_accounts.create_web_account(
                conn,
                workspace_id=ws,
                account_id=account_id,
                name="Privia Health",
                domain="privia.com",
                logo_asset_id=None,
                data={"segment": "health"},
                notes="agent-only context",
            )
            assert created["name"] == "Privia Health"
            assert created["data"] == {"segment": "health"}
            assert created["notes"] == "agent-only context"
            assert isinstance(created["created_at"], str)  # ISO parity with the SQLite API
            # A second account, to pin the case-insensitive name ordering.
            await design_accounts.create_web_account(
                conn,
                workspace_id=ws,
                account_id=f"acc_{uuid4().hex[:12]}",
                name="acme care",
                domain=None,
                logo_asset_id=None,
                data={},
                notes=None,
            )
            listed = await design_accounts.list_web_accounts(conn, workspace_id=ws)
            assert [row["name"] for row in listed] == ["acme care", "Privia Health"]
            # Partial patch: untouched keys keep their stored values.
            patched = await design_accounts.update_web_account(
                conn,
                workspace_id=ws,
                account_id=account_id,
                patch={"name": "Privia Health Group", "data": {"segment": "payer"}},
            )
            assert patched["name"] == "Privia Health Group"
            assert patched["data"] == {"segment": "payer"}
            assert patched["domain"] == "privia.com"  # not in the patch → unchanged
            assert patched["notes"] == "agent-only context"
            # Fail-closed tenancy: the other workspace sees neither the row nor its existence.
            assert (
                await design_accounts.get_web_account(
                    conn, workspace_id=other_ws, account_id=account_id
                )
                is None
            )
            with pytest.raises(DesignNotFoundError):
                await design_accounts.require_web_account(
                    conn, workspace_id=other_ws, account_id=account_id
                )
            assert await design_accounts.list_web_accounts(conn, workspace_id=other_ws) == []
            await design_accounts.delete_web_account(conn, workspace_id=ws, account_id=account_id)
            with pytest.raises(DesignNotFoundError):
                await design_accounts.require_web_account(
                    conn, workspace_id=ws, account_id=account_id
                )
            await txn.rollback()

    run_async(_check())


def test_deleting_an_account_set_nulls_a_documents_account_stamp(
    require_design_db: None,
) -> None:
    """The re-added ``design_document_account_fk`` (migration ``cf7dd82cf683``)."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            account_id = f"acc_{uuid4().hex[:12]}"
            await design_accounts.create_web_account(
                conn,
                workspace_id=ws,
                account_id=account_id,
                name="Gamma Clinics",
                domain=None,
                logo_asset_id=None,
                data={},
                notes=None,
            )
            doc_id = f"doc_{uuid4().hex}"
            await design_documents.create_document(conn, workspace_id=ws, scene=_scene(doc_id))
            stamped = await design_documents.set_document_account(
                conn, workspace_id=ws, document_id=doc_id, account_id=account_id
            )
            assert stamped["account_id"] == account_id
            await design_accounts.delete_web_account(conn, workspace_id=ws, account_id=account_id)
            detached = await design_documents.get_document(
                conn, workspace_id=ws, document_id=doc_id
            )
            assert detached["account_id"] is None  # SET NULL, never a dangling string
            await txn.rollback()

    run_async(_check())


def test_web_batch_create_and_manifest_progress_round_trip(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            doc_id = f"doc_{uuid4().hex}"
            template = await design_documents.create_document(
                conn, workspace_id=ws, scene=_scene(doc_id)
            )
            batch_id = f"wbatch_{uuid4().hex[:12]}"
            created = await design_accounts.create_web_batch(
                conn,
                workspace_id=ws,
                batch={
                    "batch_id": batch_id,
                    "template_document_id": doc_id,
                    "template_doc_version": template["current_version"],
                    "status": "running",
                    # Manifests/account id lists carry account ids with NO FK (ported as-is):
                    # a batch is a historical record of a run, not a live join.
                    "account_ids": ["acc_absent_one", "acc_absent_two"],
                    "publish": True,
                    "slug_base": "acme-site",
                },
            )
            assert created["publish"] is True
            assert created["cursor"] == 0 and created["manifest"] == []
            assert created["account_ids"] == ["acc_absent_one", "acc_absent_two"]
            manifest = [
                {"account_id": "acc_absent_one", "status": "published", "slug": "acme-site-1"}
            ]
            updated = await design_accounts.update_web_batch_progress(
                conn,
                workspace_id=ws,
                batch_id=batch_id,
                cursor=1,
                status="partial",
                manifest=manifest,
            )
            assert updated["cursor"] == 1
            assert updated["status"] == "partial"
            assert updated["manifest"] == manifest
            # counts are DERIVED from the manifest by the API — never a stored column.
            assert "counts" not in updated
            with pytest.raises(DesignNotFoundError):
                await design_accounts.require_web_batch(
                    conn, workspace_id=ws, batch_id="wbatch_absent"
                )
            await txn.rollback()

    run_async(_check())


def test_ensure_web_account_for_entity_reuses_the_entitys_row_and_mints_once(
    require_design_db: None,
) -> None:
    """The inverse of the D3 domain join: the research entity is known, the design row derived.

    Spec 2026-09-19 §3.6 — a document born for a research account needs a design-plane account,
    and a second document for the SAME account must reuse it rather than mint a twin.
    """

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            entity_id = (
                await conn.execute(
                    text(
                        "INSERT INTO account_entity "
                        "(canonical_name, primary_domain, status, workspace_id) "
                        "VALUES ('Apollo Clinics', 'apollo.example', 'candidate', :w) "
                        "RETURNING id"
                    ),
                    {"w": ws},
                )
            ).scalar_one()
            first = await design_accounts.ensure_web_account_for_entity(
                conn,
                workspace_id=ws,
                account_entity_id=str(entity_id),
                name="Apollo Clinics",
                domain="apollo.example",
            )
            again = await design_accounts.ensure_web_account_for_entity(
                conn,
                workspace_id=ws,
                account_entity_id=str(entity_id),
                name="Apollo Clinics",
                domain="apollo.example",
            )
            assert first == again
            row = await design_accounts.require_web_account(conn, workspace_id=ws, account_id=first)
            assert row["account_entity_id"] == str(entity_id)
            assert row["name"] == "Apollo Clinics"
            assert row["domain"] == "apollo.example"
            await txn.rollback()

    run_async(_check())
