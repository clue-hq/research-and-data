"""Document store DAL (Part II slice D2.2) — the port of the design API's document domain.

Faithful port of ``lumen_api.database.Repository``'s document methods onto ``design_document``
(PD contract §5 row 1), with the two D1/D2 upgrades the contract mandates:

* **Row-lock serialization + CAS on every state write.** The SQLite layer's read-modify-write
  (stacks, version bump) was safe only single-writer; here every write path reads the document
  ``FOR UPDATE``, and both the web AND scene write paths accept ``expected_base_version``
  (scene writes previously had no CAS at all — the ported lost-update gap, closed).
* **Fail-closed tenancy.** Every function takes ``workspace_id`` and locates rows by
  ``(id, workspace_id)``; a foreign-workspace id raises the same ``DesignNotFoundError`` an
  absent id does.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Scene-asset registry promotion (``register_scene_assets``) and custom-component
reference validation are NOT here — they live in the still-SQLite domains until D2.3/D2.4 and
are sequenced by the ``lumen_api`` bridge around these calls.

Undo/redo model (ported verbatim): ``undo_stack``/``redo_stack`` on the document row are the
authoritative active path; envelopes are append-only history. A normal write pushes its batch
onto undo (web writes cap at :data:`WEB_UNDO_STACK_CAP`, oldest dropped) and clears redo; an
undo (``reverts_batch_id``) moves the reverted batch undo→redo (the undo envelope itself is
never stacked — undoing an undo is redo); a redo (``reapplies_batch_id``) moves it back.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design import diagnostics as _diagnostics
from clue_design import history as _history
from clue_design._codec import (
    JsonObject,
    dump_json,
    dump_json_opt,
    iso,
    load_json,
    load_json_opt,
)
from clue_design.errors import DesignNotFoundError, DesignVersionConflictError

WEB_UNDO_STACK_CAP = 50

#: effective-brand sources whose kit persists onto the row's denormalized brand_kit_json
#: (ported set, incl. the K0.5 scene_ref convergence rule).
_BRAND_PERSIST_SOURCES = {
    "request",
    "document",
    "generated_default",
    "brand_kit_library",
    "scene_ref",
}


def scene_status(scene: JsonObject) -> str:
    status = scene.get("meta", {}).get("status", {})
    if isinstance(status, dict):
        return str(status.get("kind", "draft"))
    return str(status)


def _document_from_row(row: Any) -> JsonObject:
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "doc_kind": row.doc_kind,
        "current_version": row.current_version,
        "scene": load_json(row.current_scene_json),
        "effective_brand_kit_source": row.effective_brand_kit_source,
        "effective_brand_kit_id": row.effective_brand_kit_id,
        "effective_brand_kit_version": row.effective_brand_kit_version,
        "effective_brand_mode": load_json_opt(row.effective_brand_mode_json),
        "brand_kit": load_json_opt(row.brand_kit_json),
        "undo_stack": load_json_opt(row.undo_stack_json),
        "redo_stack": load_json_opt(row.redo_stack_json),
        "agent_instructions": row.agent_instructions,
        "layout_managed_editing": bool(row.layout_managed_editing),
        "is_template": bool(row.is_template),
        "template_document_id": row.template_document_id,
        "template_doc_version": row.template_doc_version,
        "account_id": row.account_id,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def get_document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    for_update: bool = False,
) -> JsonObject:
    """The ``require_document`` port: fetch or raise, optionally locking the row."""
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(f"SELECT * FROM design_document WHERE id = :d AND workspace_id = :w{suffix}"),
            {"d": document_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("document", document_id)
    return _document_from_row(row)


async def create_document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    scene: JsonObject,
    brand_kit: JsonObject | None = None,
    effective_brand_source: str | None = None,
    effective_brand_mode: JsonObject | None = None,
    doc_kind: str = "scene",
    template_document_id: str | None = None,
    template_doc_version: int | None = None,
    account_id: str | None = None,
) -> JsonObject:
    if doc_kind == "web":
        document_id = str(scene["id"])
        title = str(scene["title"])
        status = "draft"
        brand_ref = (scene.get("theme") or {}).get("brand_kit")
    else:
        document_id = str(scene["meta"]["id"])
        title = str(scene["meta"]["title"])
        status = scene_status(scene)
        brand_ref = scene["meta"].get("brand_kit")
    effective_source = effective_brand_source
    effective_id = brand_ref["id"] if brand_ref else None
    effective_version = brand_ref["version"] if brand_ref else None
    if brand_kit is not None:
        effective_source = effective_source or "document"
        effective_id = brand_kit.get("id")
        effective_version = brand_kit.get("version")
    await conn.execute(
        text(
            """
            INSERT INTO design_document (
              id, workspace_id, title, status, doc_kind, current_scene_json,
              current_version, effective_brand_kit_source, effective_brand_kit_id,
              effective_brand_kit_version, effective_brand_mode_json, brand_kit_json,
              template_document_id, template_doc_version, account_id
            )
            VALUES (:id, :w, :title, :status, :doc_kind, CAST(:scene AS jsonb), 0,
                    :eff_source, :eff_id, :eff_version, CAST(:eff_mode AS jsonb),
                    CAST(:brand_kit AS jsonb), :tpl_doc, :tpl_version, :account_id)
            """
        ),
        {
            "id": document_id,
            "w": workspace_id,
            "title": title,
            "status": status,
            "doc_kind": doc_kind,
            "scene": dump_json(scene),
            "eff_source": effective_source,
            "eff_id": effective_id,
            "eff_version": effective_version,
            "eff_mode": dump_json_opt(effective_brand_mode),
            "brand_kit": dump_json_opt(brand_kit),
            "tpl_doc": template_document_id,
            "tpl_version": template_doc_version,
            "account_id": account_id,
        },
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def create_web_template(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    web_doc: JsonObject,
    account_id: str | None = None,
) -> JsonObject:
    """Insert a NEW web document row as a template (fresh stacks, version 0, is_template)."""
    brand_ref = (web_doc.get("theme") or {}).get("brand_kit")
    await conn.execute(
        text(
            """
            INSERT INTO design_document (
              id, workspace_id, title, status, doc_kind, current_scene_json,
              current_version, effective_brand_kit_id, effective_brand_kit_version,
              is_template, account_id
            )
            VALUES (:id, :w, :title, 'draft', 'web', CAST(:doc AS jsonb), 0,
                    :eff_id, :eff_version, true, :account_id)
            """
        ),
        {
            "id": str(web_doc["id"]),
            "w": workspace_id,
            "title": str(web_doc["title"]),
            "doc": dump_json(web_doc),
            "eff_id": brand_ref["id"] if brand_ref else None,
            "eff_version": brand_ref["version"] if brand_ref else None,
            "account_id": account_id,
        },
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=str(web_doc["id"]))


async def list_web_templates(conn: AsyncConnection, *, workspace_id: str) -> list[JsonObject]:
    rows = await conn.execute(
        text(
            "SELECT * FROM design_document"
            " WHERE workspace_id = :w AND doc_kind = 'web' AND is_template"
            " ORDER BY updated_at DESC, id ASC"
        ),
        {"w": workspace_id},
    )
    return [_document_from_row(row) for row in rows]


async def set_agent_instructions(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    instructions: str | None,
) -> JsonObject:
    await get_document(conn, workspace_id=workspace_id, document_id=document_id, for_update=True)
    await conn.execute(
        text(
            "UPDATE design_document SET agent_instructions = :i, updated_at = now()"
            " WHERE id = :d AND workspace_id = :w"
        ),
        {"i": instructions, "d": document_id, "w": workspace_id},
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def set_layout_managed_editing(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, enabled: bool
) -> JsonObject:
    await get_document(conn, workspace_id=workspace_id, document_id=document_id, for_update=True)
    await conn.execute(
        text(
            "UPDATE design_document SET layout_managed_editing = :e, updated_at = now()"
            " WHERE id = :d AND workspace_id = :w"
        ),
        {"e": enabled, "d": document_id, "w": workspace_id},
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def replace_scene(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    scene: JsonObject,
    diagnostics: list[JsonObject],
    expected_base_version: int | None = None,
) -> JsonObject:
    """Whole-scene replace: version+1 under the row lock (+ optional CAS)."""
    document = await get_document(
        conn, workspace_id=workspace_id, document_id=document_id, for_update=True
    )
    _check_cas(document, document_id, expected_base_version)
    await conn.execute(
        text(
            """
            UPDATE design_document
            SET title = :title, status = :status,
                current_scene_json = CAST(:scene AS jsonb),
                current_version = :version, updated_at = now()
            WHERE id = :d AND workspace_id = :w
            """
        ),
        {
            "title": scene["meta"]["title"],
            "status": scene_status(scene),
            "scene": dump_json(scene),
            "version": document["current_version"] + 1,
            "d": document_id,
            "w": workspace_id,
        },
    )
    await _diagnostics.store_diagnostics(
        conn,
        workspace_id=workspace_id,
        document_id=document_id,
        kind="structural",
        diagnostics=diagnostics,
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


def _check_cas(document: JsonObject, document_id: str, expected_base_version: int | None) -> None:
    if expected_base_version is not None and document["current_version"] != expected_base_version:
        raise DesignVersionConflictError(
            "document", document_id, expected_base_version, document["current_version"]
        )


async def update_document_state(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    scene: JsonObject,
    diagnostics: list[JsonObject],
    operations: Iterable[JsonObject],
    source: str,
    actor_kind: str,
    actor_id: str | None,
    diagnostic_kind: str,
    effective_brand: tuple[str, JsonObject | None, JsonObject | None] | None,
    envelope: JsonObject | None = None,
    expected_base_version: int | None = None,
) -> JsonObject:
    """The scene-mode state write (ported verbatim), now row-locked + optionally CAS'd."""
    ops = list(operations)
    document = await get_document(
        conn, workspace_id=workspace_id, document_id=document_id, for_update=True
    )
    _check_cas(document, document_id, expected_base_version)
    base_revision = document["current_version"]
    version = base_revision + len(ops) if ops else base_revision

    brand_source = document.get("effective_brand_kit_source")
    brand_id = document.get("effective_brand_kit_id")
    brand_version = document.get("effective_brand_kit_version")
    brand_mode = document.get("effective_brand_mode")
    brand_json = document.get("brand_kit")
    if effective_brand is not None:
        brand_source, brand_kit, brand_mode = effective_brand
        brand_id = brand_kit.get("id") if brand_kit else None
        brand_version = brand_kit.get("version") if brand_kit else None
        if brand_source in _BRAND_PERSIST_SOURCES and brand_kit:
            brand_json = brand_kit

    batch_id: str | None = None
    batch: JsonObject | None = None
    undo_stack = list(document.get("undo_stack") or [])
    redo_stack = list(document.get("redo_stack") or [])
    if ops:
        batch = dict(envelope or {})
        batch_id = batch.get("batch_id") or _history.new_batch_id()
        batch["batch_id"] = batch_id
        batch.setdefault("intent", diagnostic_kind)
        batch.setdefault("base_revision", base_revision)
        batch["operations"] = ops
        reverts = batch.get("reverts_batch_id")
        reapplies = batch.get("reapplies_batch_id")
        if reverts:
            # Undo: the reverted batch leaves the undo stack and becomes redoable; the
            # undo envelope itself is not stacked (undoing an undo is redo).
            if reverts in undo_stack:
                undo_stack.remove(reverts)
            redo_stack.append(reverts)
        elif reapplies:
            if reapplies in redo_stack:
                redo_stack.remove(reapplies)
            undo_stack.append(reapplies)
        else:
            undo_stack.append(batch_id)
            redo_stack = []

    await conn.execute(
        text(
            """
            UPDATE design_document
            SET title = :title, status = :status,
                current_scene_json = CAST(:scene AS jsonb), current_version = :version,
                effective_brand_kit_source = :b_source, effective_brand_kit_id = :b_id,
                effective_brand_kit_version = :b_version,
                effective_brand_mode_json = CAST(:b_mode AS jsonb),
                brand_kit_json = CAST(:b_json AS jsonb),
                undo_stack_json = CAST(:undo AS jsonb),
                redo_stack_json = CAST(:redo AS jsonb), updated_at = now()
            WHERE id = :d AND workspace_id = :w
            """
        ),
        {
            "title": scene["meta"]["title"],
            "status": scene_status(scene),
            "scene": dump_json(scene),
            "version": version,
            "b_source": brand_source,
            "b_id": brand_id,
            "b_version": brand_version,
            "b_mode": dump_json_opt(brand_mode),
            "b_json": dump_json_opt(brand_json),
            "undo": dump_json(undo_stack),
            "redo": dump_json(redo_stack),
            "d": document_id,
            "w": workspace_id,
        },
    )
    if batch is not None:
        await _history.append_envelope(
            conn,
            workspace_id=workspace_id,
            document_id=document_id,
            envelope=batch,
            source=source,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )
    await _history.append_operations(
        conn,
        workspace_id=workspace_id,
        document_id=document_id,
        operations=ops,
        source=source,
        actor_kind=actor_kind,
        actor_id=actor_id,
        diagnostics=diagnostics,
        batch_id=batch_id,
    )
    await _diagnostics.store_diagnostics(
        conn,
        workspace_id=workspace_id,
        document_id=document_id,
        kind=diagnostic_kind,
        diagnostics=diagnostics,
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def update_web_document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    web_doc: JsonObject,
    intent: str | None,
    checkpoint_label: str | None,
    operations: list[JsonObject],
    inverse_operations: list[JsonObject] | None,
    actor_kind: str = "agent",
    source: str = "agent",
    push_undo: bool = True,
    reverts_batch_id: str | None = None,
    reapplies_batch_id: str | None = None,
    expected_base_version: int | None = None,
) -> JsonObject:
    """The website-mode state write (ported verbatim; see the module docstring's undo model).

    The row lock serializes concurrent writers; the CAS predicate is kept as well so an
    explicit ``expected_base_version`` mismatch surfaces as the typed conflict rather than a
    silent overwrite — same double guard as the SQLite layer's version predicate.
    """
    document = await get_document(
        conn, workspace_id=workspace_id, document_id=document_id, for_update=True
    )
    base_revision = document["current_version"]
    if expected_base_version is not None and base_revision != expected_base_version:
        raise DesignVersionConflictError(
            "document", document_id, expected_base_version, base_revision
        )
    version = base_revision + 1
    batch_id = _history.new_batch_id()
    undo_stack = list(document.get("undo_stack") or [])
    redo_stack = list(document.get("redo_stack") or [])
    if reverts_batch_id:
        if reverts_batch_id in undo_stack:
            undo_stack.remove(reverts_batch_id)
        redo_stack.append(reverts_batch_id)
    elif reapplies_batch_id:
        if reapplies_batch_id in redo_stack:
            redo_stack.remove(reapplies_batch_id)
        undo_stack.append(reapplies_batch_id)
    elif push_undo:
        undo_stack.append(batch_id)
        if len(undo_stack) > WEB_UNDO_STACK_CAP:
            undo_stack = undo_stack[-WEB_UNDO_STACK_CAP:]
        redo_stack = []
    envelope = {
        "batch_id": batch_id,
        "base_revision": base_revision,
        "intent": intent,
        "checkpoint_label": checkpoint_label,
        "operations": operations,
        "inverse_operations": inverse_operations,
        "reverts_batch_id": reverts_batch_id,
        "reapplies_batch_id": reapplies_batch_id,
    }
    result = await conn.execute(
        text(
            """
            UPDATE design_document
            SET title = :title, current_scene_json = CAST(:doc AS jsonb),
                current_version = :version, undo_stack_json = CAST(:undo AS jsonb),
                redo_stack_json = CAST(:redo AS jsonb), updated_at = now()
            WHERE id = :d AND workspace_id = :w AND current_version = :base
            """
        ),
        {
            "title": web_doc["title"],
            "doc": dump_json(web_doc),
            "version": version,
            "undo": dump_json(undo_stack),
            "redo": dump_json(redo_stack),
            "d": document_id,
            "w": workspace_id,
            "base": base_revision,
        },
    )
    if result.rowcount != 1:
        current = (await get_document(conn, workspace_id=workspace_id, document_id=document_id))[
            "current_version"
        ]
        raise DesignVersionConflictError(
            "document",
            document_id,
            expected_base_version if expected_base_version is not None else base_revision,
            current,
        )
    await _history.append_envelope(
        conn,
        workspace_id=workspace_id,
        document_id=document_id,
        envelope=envelope,
        source=source,
        actor_kind=actor_kind,
        actor_id=None,
    )
    await _history.append_operations(
        conn,
        workspace_id=workspace_id,
        document_id=document_id,
        operations=operations,
        source=source,
        actor_kind=actor_kind,
        actor_id=None,
        diagnostics=[],
        batch_id=batch_id,
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def set_document_account(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document_id: str,
    account_id: str | None,
) -> JsonObject:
    """Stamp the ABM account a derived document personalizes for (the D2.4 derive path's
    write; advisory string until D2.4 re-adds the account FK — see migration 7a9881f9717a)."""
    await get_document(conn, workspace_id=workspace_id, document_id=document_id, for_update=True)
    await conn.execute(
        text(
            "UPDATE design_document SET account_id = :a, updated_at = now()"
            " WHERE id = :d AND workspace_id = :w"
        ),
        {"a": account_id, "d": document_id, "w": workspace_id},
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def list_web_documents_for_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: str
) -> list[JsonObject]:
    """The component-usage scan's document feed.

    The SQL account predicate is the tenancy boundary; the caller does the exact node walk.
    """
    rows = await conn.execute(
        text(
            "SELECT id, title, current_version, current_scene_json FROM design_document"
            " WHERE workspace_id = :w AND doc_kind = 'web' AND account_id = :a"
            " ORDER BY updated_at DESC, id ASC"
        ),
        {"w": workspace_id, "a": account_id},
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "current_version": row.current_version,
            "scene": load_json(row.current_scene_json),
        }
        for row in rows
    ]


async def count_documents_referencing(
    conn: AsyncConnection, *, workspace_id: str, needle: str
) -> int:
    """The asset-GC gate's document-reference count (now workspace-scoped)."""
    row = await conn.execute(
        text(
            "SELECT count(*) FROM design_document"
            " WHERE workspace_id = :w AND current_scene_json::text LIKE :needle"
        ),
        {"w": workspace_id, "needle": f"%{needle}%"},
    )
    return int(row.scalar_one())
