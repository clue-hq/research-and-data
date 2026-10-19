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
here commits. Since D2.3 the scene write paths call :func:`clue_design.assets.register_scene_assets`
IN-TRANSACTION, so registry promotion and the scene that carries it land or roll back together
(the SQLite-era post-commit seam is closed). Custom-component reference validation is still NOT
here — it lives in the SQLite domain until D2.4 and is sequenced by the ``lumen_api`` bridge
before these calls.

Undo/redo model (ported verbatim): ``undo_stack``/``redo_stack`` on the document row are the
authoritative active path; envelopes are append-only history. A normal write pushes its batch
onto undo (web writes cap at :data:`WEB_UNDO_STACK_CAP`, oldest dropped) and clears redo; an
undo (``reverts_batch_id``) moves the reverted batch undo→redo (the undo envelope itself is
never stacked — undoing an undo is redo); a redo (``reapplies_batch_id``) moves it back.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design import assets as _assets
from clue_design import brand as _brand
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


async def _stamp_approved_brand_kit_at_birth(
    conn: AsyncConnection, *, workspace_id: str, web_doc: JsonObject
) -> JsonObject:
    """Default a NEW WebDoc to the workspace brand's latest approved kit.

    This is deliberately a create-time operation. Reads/renders never infer a kit for an existing
    document, so approving a kit cannot retroactively change documents that were already born.
    The caller's explicit ``theme.brand_kit`` is authoritative, including a ref to a different
    kit/version.
    """
    theme = web_doc.get("theme")
    if theme is not None and not isinstance(theme, dict):
        # The engine-produced creation paths always carry an object here. Do not silently repair
        # a malformed tool input by replacing caller data while choosing its brand identity.
        return web_doc
    if isinstance(theme, dict) and theme.get("brand_kit") is not None:
        return web_doc
    brand_kit_ref = await _brand.latest_approved_brand_kit_ref(conn, workspace_id=workspace_id)
    if brand_kit_ref is None:
        return web_doc
    stamped = copy.deepcopy(web_doc)
    stamped.setdefault("theme", {})["brand_kit"] = brand_kit_ref
    return stamped


async def _stamp_approved_brand_kit_at_scene_birth(
    conn: AsyncConnection, *, workspace_id: str, scene: JsonObject
) -> JsonObject:
    """Default a NEW scene (ad) document to the workspace brand's latest approved kit.

    The scene mirror of ``_stamp_approved_brand_kit_at_birth``: create-time only, the
    caller's explicit ``meta.brand_kit`` is authoritative, and no approved kit (or the
    fail-closed multi-brand case inside ``latest_approved_brand_kit_ref``) leaves the
    scene untouched — un-branded, honestly. Ratified 2026-08-23 (genad ruling 1).
    """
    meta = scene.get("meta")
    if not isinstance(meta, dict):
        return scene
    if meta.get("brand_kit") is not None:
        return scene
    brand_kit_ref = await _brand.latest_approved_brand_kit_ref(conn, workspace_id=workspace_id)
    if brand_kit_ref is None:
        return scene
    stamped = copy.deepcopy(scene)
    stamped["meta"]["brand_kit"] = brand_kit_ref
    return stamped


def scene_status(scene: JsonObject) -> str:
    status = scene.get("meta", {}).get("status", {})
    if isinstance(status, dict):
        return str(status.get("kind", "draft"))
    return str(status)


def is_finalized_document(document: JsonObject) -> bool:
    """Is this document frozen against mutation?

    The platform-side mirror of the design API's own predicate
    (``lumen_api.main.is_finalized_document``), kept semantically identical so one document
    cannot be finalized to the design route and editable to a platform caller: the row says
    ``finalized``, OR the scene carries a finalized status. Note what is deliberately absent —
    ``published`` is NOT finalized. A draft whose older version is currently published stays
    editable (founder ruling G1, 2026-08-19), and publishing writes ``design_web_publish``
    rather than the document row anyway.
    """
    if document.get("status") == "finalized":
        return True
    return scene_status(document.get("scene") or {}) == "finalized"


#: The kinds of document a person publishes as a website.
_WEBSITE_DOC_KINDS = ("web", "site")


def _born_noindex(doc_kind: str) -> bool:
    """The one birth rule for the durable ``web_noindex`` (founder ruling 2026-10-16).

    Every NEW website document — web or site, whichever route creates it (a plain document, a
    derivation, a template, a chat-born page) — is born kept out of search indexes. A person
    makes it indexable by ticking "Allow indexing" in Share, which clears the flag through
    :func:`set_web_noindex`. A scene has no publish surface and is born false. Only the two
    inserts below call this; nothing rewrites a document that already exists.
    """
    return doc_kind in _WEBSITE_DOC_KINDS


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
        # Clone-fidelity F4.3, FOUNDER RULING R-F1: `noindex` is a DURABLE property of a web
        # page, not an argument one caller happens to pass. Every publish path ORs it with
        # whatever the request asked for, so a plain republish of an ABM account page cannot
        # quietly re-index it. Every new website document is born true (`_born_noindex`).
        # Meaningless on a scene document, and false there.
        "web_noindex": bool(row.web_noindex),
        "is_template": bool(row.is_template),
        "template_document_id": row.template_document_id,
        "template_doc_version": row.template_doc_version,
        "account_id": row.account_id,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
        # Artifacts-page spec §3.4: the library's archive state; None when live.
        "archived_at": None if row.archived_at is None else iso(row.archived_at),
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
    if doc_kind in _WEBSITE_DOC_KINDS:
        scene = await _stamp_approved_brand_kit_at_birth(
            conn, workspace_id=workspace_id, web_doc=scene
        )
        document_id = str(scene["id"])
        title = str(scene["title"])
        status = "draft"
        brand_ref = (scene.get("theme") or {}).get("brand_kit")
    else:
        scene = await _stamp_approved_brand_kit_at_scene_birth(
            conn, workspace_id=workspace_id, scene=scene
        )
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
              template_document_id, template_doc_version, account_id, web_noindex
            )
            VALUES (:id, :w, :title, :status, :doc_kind, CAST(:scene AS jsonb), 0,
                    :eff_source, :eff_id, :eff_version, CAST(:eff_mode AS jsonb),
                    CAST(:brand_kit AS jsonb), :tpl_doc, :tpl_version, :account_id,
                    :web_noindex)
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
            "web_noindex": _born_noindex(doc_kind),
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
    web_doc = await _stamp_approved_brand_kit_at_birth(
        conn, workspace_id=workspace_id, web_doc=web_doc
    )
    brand_ref = (web_doc.get("theme") or {}).get("brand_kit")
    await conn.execute(
        text(
            """
            INSERT INTO design_document (
              id, workspace_id, title, status, doc_kind, current_scene_json,
              current_version, effective_brand_kit_id, effective_brand_kit_version,
              is_template, account_id, web_noindex
            )
            VALUES (:id, :w, :title, 'draft', 'web', CAST(:doc AS jsonb), 0,
                    :eff_id, :eff_version, true, :account_id, :web_noindex)
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
            "web_noindex": _born_noindex("web"),
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


async def set_web_noindex(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, enabled: bool
) -> JsonObject:
    """Stamp (or explicitly clear) a web document's durable ``noindex`` (ruling R-F1).

    The sibling of :func:`set_layout_managed_editing`, and deliberately shaped like it: an
    assignment of a named value to one document, converging on re-run. What makes it different
    is the direction that is NOT reachable any other way — CLEARING. Every publish path ORs this
    flag with its own request, so a publish can only ever add the robots meta; the only thing in
    the system that can take it off a page is a caller that names ``enabled=False`` here.
    """
    await get_document(conn, workspace_id=workspace_id, document_id=document_id, for_update=True)
    await conn.execute(
        text(
            "UPDATE design_document SET web_noindex = :e, updated_at = now()"
            " WHERE id = :d AND workspace_id = :w"
        ),
        {"e": enabled, "d": document_id, "w": workspace_id},
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def rename_document(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, title: str
) -> JsonObject:
    """Rename one document: the row's ``title`` AND the document JSON's own title, together.

    Every state write (``replace_scene``, ``update_document_state``, ``update_web_document``)
    rewrites the column from the JSON, so a column-only rename would be reverted by the next
    save; and a JSON edit without a version bump would be overwritten by an editor holding the
    old title. So this bumps ``current_version`` under the row lock: an open editor's next
    write fails its compare-and-set and takes its quiet-reload path (``replace_scene`` already
    bumps without a history row — not a new pattern).
    """
    clean = title.strip()
    if not clean:
        raise ValueError("title must not be blank")
    document = await get_document(
        conn, workspace_id=workspace_id, document_id=document_id, for_update=True
    )
    # The jsonb path to the document's own title: a web or site doc carries it at the top level, a
    # scene under ``meta``. Passed as a list, not the ``{a,b}`` literal — the driver binds a
    # text[] argument from a sized iterable and refuses a string.
    path = ["title"] if document["doc_kind"] in ("web", "site") else ["meta", "title"]
    await conn.execute(
        text(
            "UPDATE design_document"
            " SET title = :title,"
            "     current_scene_json = jsonb_set(current_scene_json, CAST(:path AS text[]),"
            "         to_jsonb(CAST(:title AS text)), true),"
            "     current_version = current_version + 1, updated_at = now()"
            " WHERE id = :d AND workspace_id = :w"
        ),
        {"title": clean, "path": path, "d": document_id, "w": workspace_id},
    )
    return await get_document(conn, workspace_id=workspace_id, document_id=document_id)


async def set_document_archived(
    conn: AsyncConnection, *, workspace_id: str, document_id: str, enabled: bool
) -> JsonObject:
    """Archive (or restore) one document — a gallery/library state, independent of publish.

    Converges: archiving twice keeps the first timestamp. No version bump and no ``updated_at``
    touch: archiving is not an edit, and the library's "last edited" must stay honest.
    """
    await get_document(conn, workspace_id=workspace_id, document_id=document_id, for_update=True)
    await conn.execute(
        text(
            "UPDATE design_document"
            " SET archived_at = CASE WHEN :e THEN COALESCE(archived_at, now()) ELSE NULL END"
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
    await _assets.register_scene_assets(conn, workspace_id=workspace_id, scene=scene)
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
    await _assets.register_scene_assets(conn, workspace_id=workspace_id, scene=scene)
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
    actor_id: str | None = None,
) -> JsonObject:
    """The website-mode state write (ported verbatim; see the module docstring's undo model).

    The row lock serializes concurrent writers; the CAS predicate is kept as well so an
    explicit ``expected_base_version`` mismatch surfaces as the typed conflict rather than a
    silent overwrite — same double guard as the SQLite layer's version predicate.

    ``actor_id`` is stamped on the history rows. An agent-run site save passes its run id, which
    is how :func:`clue_design.runs.hold_run_for_save` knows the run has already saved.
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
        actor_id=actor_id,
    )
    await _history.append_operations(
        conn,
        workspace_id=workspace_id,
        document_id=document_id,
        operations=operations,
        source=source,
        actor_kind=actor_kind,
        actor_id=actor_id,
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
    """Stamp the ABM account a derived document personalizes for (the derive path's write).

    Since D2.4 the stamp is FK-backed (``design_document_account_fk``, re-added by migration
    ``cf7dd82cf683``): the account must exist in this workspace, and deleting it SET-NULLs
    the stamp instead of leaving a dangling string.
    """
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
