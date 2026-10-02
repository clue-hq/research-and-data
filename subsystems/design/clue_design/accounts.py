"""Web-personalization accounts + batches DAL (Part II slice D2.4) — the port of the design
API's ``web_accounts`` / ``web_batches`` domain.

Faithful port of ``lumen_api.database.Repository``'s web-account and web-batch methods onto
``design_account`` + ``design_web_batch`` (PD contract §5 rows 19–20), with the D1/D2 upgrades
the contract mandates:

* **Fail-closed tenancy.** Every function takes ``workspace_id`` and locates rows by
  ``(…, workspace_id)``; a foreign-workspace id raises the same :class:`DesignNotFoundError`
  an absent id does (``get_web_account`` keeps its optional ``None`` shape for the
  create-endpoint's duplicate probe, which must not raise). Account ids are importable/
  client-suppliable, which is why migration ``7a9881f9717a`` made the key
  ``(account_id, workspace_id)``.
* **Real FKs where SQLite validated by convention.** ``logo_asset_id`` now references
  ``design_asset (asset_id, workspace_id)`` ``ON DELETE SET NULL``: the endpoint's write-time
  resolution check stays, and deleting the asset DETACHES the logo instead of leaving a
  dangling pointer. ``design_web_batch.template_document_id`` references
  ``design_document (id, workspace_id)`` (NO ACTION — a batch pins its template's provenance).
  Batch **manifests** carry account ids inside jsonb and are deliberately NOT constrained
  (ported as-is): a manifest is a historical record of what a run did, not a live join.
* **The O1 account-spine join (D3).** ``create_web_account`` / ``update_web_account`` stamp
  ``account_entity_id`` from the account's DOMAIN via :mod:`clue_design.joins` (resolve-or-
  create; a domain-less account stays NULL), and every read surfaces it. Still nullable — see
  ``joins``' docstring for the deferred NOT NULL promotion.
* **``counts`` stay derived.** ``design_web_batch`` stores no counts column — the API computes
  them from ``manifest_json`` at read time, exactly as the SQLite original did.

An account IS the web-mode binding set, but the ``account_values`` projection (the flat
``account.*`` namespace the derive consumes) stays in ``lumen_api``: it is engine-shaped value
marshalling, not storage.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``web_account_from_row`` / ``web_batch_from_row`` exactly, with
ISO-string timestamps.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError, DesignVersionConflictError
from clue_design.joins import normalize_domain, resolve_account_entity_id


def _web_account_from_row(row: Any) -> JsonObject:
    return {
        "account_id": row.account_id,
        # D3: the O1 account-spine join, surfaced (NULL for a domain-less account).
        "account_entity_id": (
            None if row.account_entity_id is None else str(row.account_entity_id)
        ),
        "name": row.name,
        "domain": row.domain,
        "logo_asset_id": row.logo_asset_id,
        "data": load_json(row.data_json),
        "notes": row.notes,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _web_batch_from_row(row: Any) -> JsonObject:
    return {
        "batch_id": row.batch_id,
        "template_document_id": row.template_document_id,
        "template_doc_version": row.template_doc_version,
        "status": row.status,
        "account_ids": load_json(row.account_ids_json),
        "publish": bool(row.publish),
        "slug_base": row.slug_base,
        "cursor": row.cursor,
        "manifest": load_json(row.manifest_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


# --- accounts --------------------------------------------------------------------------------


async def get_web_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, for_update: bool = False
) -> JsonObject | None:
    """The optional read (the create endpoint's duplicate probe): ``None``, never a raise."""
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT * FROM design_account WHERE account_id = :a AND workspace_id = :w{suffix}"
            ),
            {"a": account_id, "w": workspace_id},
        )
    ).first()
    return None if row is None else _web_account_from_row(row)


async def require_web_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: str
) -> JsonObject:
    """Fetch or raise — the fail-closed read every account-scoped endpoint gates on."""
    account = await get_web_account(conn, workspace_id=workspace_id, account_id=account_id)
    if account is None:
        raise DesignNotFoundError("web_account", account_id)
    return account


async def create_web_account(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: str,
    name: str,
    domain: str | None,
    logo_asset_id: str | None,
    data: JsonObject,
    notes: str | None,
) -> JsonObject:
    """Insert one ABM target-company row.

    D3 stamps ``account_entity_id`` (the O1 join onto the platform account spine) here: the
    account's domain resolves-or-creates the workspace's ``account_entity`` — see
    :func:`clue_design.joins.resolve_account_entity_id`. A domain-less account stays NULL
    (name-only matching is identity resolution's job and is never faked here).
    A ``logo_asset_id`` that names no asset in this workspace is now refused by
    ``design_account_logo_fk`` — the endpoint's 422 resolution check runs first, so the FK is
    the structural backstop rather than the primary error surface.
    """
    entity_id = await resolve_account_entity_id(
        conn, workspace_id=workspace_id, domain=domain, name=name
    )
    await conn.execute(
        text(
            """
            INSERT INTO design_account (
              account_id, workspace_id, account_entity_id, name, domain, logo_asset_id,
              data_json, notes
            )
            VALUES (:a, :w, CAST(:entity AS uuid), :name, :domain, :logo,
                    CAST(:data AS jsonb), :notes)
            """
        ),
        {
            "a": account_id,
            "w": workspace_id,
            "entity": entity_id,
            "name": name,
            "domain": domain,
            "logo": logo_asset_id,
            "data": dump_json(data or {}),
            "notes": notes,
        },
    )
    return await require_web_account(conn, workspace_id=workspace_id, account_id=account_id)


async def ensure_web_account_for_entity(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_entity_id: str,
    name: str,
    domain: str | None,
) -> str:
    """The design account that projects onto ``account_entity_id`` — found, or born here.

    Spec 2026-09-19 §3.6: a document born for a research account must carry a design-plane
    account (``design_document.account_id`` references ``design_account``). This is the inverse
    direction of :func:`clue_design.joins.resolve_account_entity_id`: the entity is known, the
    design row is derived. Idempotent — one design account per entity per workspace; a second
    call returns the first row's id.
    """
    found = (
        await conn.execute(
            text(
                "SELECT account_id FROM design_account "
                "WHERE workspace_id = :w AND account_entity_id = CAST(:e AS uuid) "
                "ORDER BY created_at ASC, account_id ASC LIMIT 1"
            ),
            {"w": workspace_id, "e": account_entity_id},
        )
    ).first()
    if found is not None:
        return str(found.account_id)
    account_id = "acc_" + uuid4().hex
    await conn.execute(
        text(
            "INSERT INTO design_account "
            "(account_id, workspace_id, account_entity_id, name, domain, logo_asset_id, "
            " data_json, notes) "
            "VALUES (:a, :w, CAST(:e AS uuid), :name, :domain, NULL, '{}'::jsonb, NULL)"
        ),
        {
            "a": account_id,
            "w": workspace_id,
            "e": account_entity_id,
            "name": name,
            "domain": normalize_domain(domain),
        },
    )
    return account_id


async def list_web_accounts(conn: AsyncConnection, *, workspace_id: str) -> list[JsonObject]:
    """Ported ordering: name case-insensitively (SQLite ``COLLATE NOCASE``), then account id."""
    rows = await conn.execute(
        text(
            "SELECT * FROM design_account WHERE workspace_id = :w"
            " ORDER BY lower(name) ASC, account_id ASC"
        ),
        {"w": workspace_id},
    )
    return [_web_account_from_row(row) for row in rows]


async def update_web_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, patch: JsonObject
) -> JsonObject:
    """Partial update: only keys present in ``patch`` are written (the endpoint validates them
    first); ``data`` replaces the map wholesale when present. Row-locked read-modify-write.

    D3 keeps the O1 account-spine stamp in step with the domain: a CHANGED domain re-resolves
    (resolve-or-create) onto the entity that domain names, a CLEARED domain NULLs the stamp,
    and an unchanged domain leaves it exactly as it was (a pre-D3 row keeps its NULL until its
    domain is next written — a backfill is Part III's, not this write path's).
    """
    account = await get_web_account(
        conn, workspace_id=workspace_id, account_id=account_id, for_update=True
    )
    if account is None:
        raise DesignNotFoundError("web_account", account_id)
    name = patch["name"] if "name" in patch else account["name"]
    domain = patch["domain"] if "domain" in patch else account["domain"]
    entity_id = account["account_entity_id"]
    if "domain" in patch and normalize_domain(domain) != normalize_domain(account["domain"]):
        entity_id = await resolve_account_entity_id(
            conn, workspace_id=workspace_id, domain=domain, name=name
        )
    await conn.execute(
        text(
            """
            UPDATE design_account
            SET name = :name, domain = :domain, logo_asset_id = :logo,
                account_entity_id = CAST(:entity AS uuid),
                data_json = CAST(:data AS jsonb), notes = :notes, updated_at = now()
            WHERE account_id = :a AND workspace_id = :w
            """
        ),
        {
            "name": name,
            "domain": domain,
            "entity": entity_id,
            "logo": patch["logo_asset_id"]
            if "logo_asset_id" in patch
            else account["logo_asset_id"],
            "data": dump_json(patch["data"] if "data" in patch else account["data"]),
            "notes": patch["notes"] if "notes" in patch else account["notes"],
            "a": account_id,
            "w": workspace_id,
        },
    )
    return await require_web_account(conn, workspace_id=workspace_id, account_id=account_id)


async def delete_web_account(conn: AsyncConnection, *, workspace_id: str, account_id: str) -> None:
    """Hard delete; an absent (or foreign-workspace) id raises.

    A derived document's ``account_id`` stamp is SET NULL by ``design_document_account_fk``
    (re-added in D2.4) rather than dangling — the SQLite era kept the orphaned string.
    """
    await require_web_account(conn, workspace_id=workspace_id, account_id=account_id)
    await conn.execute(
        text("DELETE FROM design_account WHERE account_id = :a AND workspace_id = :w"),
        {"a": account_id, "w": workspace_id},
    )


# --- web batches -----------------------------------------------------------------------------


async def require_web_batch(
    conn: AsyncConnection, *, workspace_id: str, batch_id: str, for_update: bool = False
) -> JsonObject:
    """The ``require_web_batch`` port: fetch or raise, optionally locking the row."""
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                f"SELECT * FROM design_web_batch WHERE batch_id = :b AND workspace_id = :w{suffix}"
            ),
            {"b": batch_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("web_batch", batch_id)
    return _web_batch_from_row(row)


async def create_web_batch(
    conn: AsyncConnection, *, workspace_id: str, batch: JsonObject
) -> JsonObject:
    """Insert a new bulk derive/publish batch.

    ``cursor`` persists per chunk so an interrupted batch resumes exactly where it stopped;
    per-account results live in ``manifest_json`` and counts are computed from it on read —
    nothing to keep in sync here.
    """
    batch_id = str(batch["batch_id"])
    await conn.execute(
        text(
            """
            INSERT INTO design_web_batch (
              batch_id, workspace_id, template_document_id, template_doc_version, status,
              account_ids_json, publish, slug_base, cursor, manifest_json
            )
            VALUES (:b, :w, :doc, :doc_version, :status, CAST(:account_ids AS jsonb),
                    :publish, :slug_base, :cursor, CAST(:manifest AS jsonb))
            """
        ),
        {
            "b": batch_id,
            "w": workspace_id,
            "doc": batch["template_document_id"],
            "doc_version": batch["template_doc_version"],
            "status": batch["status"],
            "account_ids": dump_json(batch["account_ids"]),
            "publish": bool(batch.get("publish", True)),
            "slug_base": batch.get("slug_base"),
            "cursor": batch.get("cursor", 0),
            "manifest": dump_json(batch.get("manifest", [])),
        },
    )
    return await require_web_batch(conn, workspace_id=workspace_id, batch_id=batch_id)


async def update_web_batch_progress(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: str,
    cursor: int,
    status: str,
    manifest: list[JsonObject],
    expected_cursor: int | None = None,
) -> JsonObject:
    """Persist one chunk's progress (row-locked; the SQLite original raised the same
    not-found afterwards, on its read-back).

    ``expected_cursor`` (Part II slice D6 Round C) is the batch single-flight — see
    :func:`clue_design.personalization.update_instance_batch_progress` for the full reasoning.
    It matters more here than on the instance side: a duplicate instance derivation converges
    (``inst_<rev>_<bind>`` is deterministic and the write is an upsert), but a duplicate web
    derivation mints a fresh ``doc_`` id and may publish a second slug, so an un-fenced double
    resume left real garbage behind.
    """
    current = await require_web_batch(
        conn, workspace_id=workspace_id, batch_id=batch_id, for_update=True
    )
    if expected_cursor is not None and int(current["cursor"]) != expected_cursor:
        raise DesignVersionConflictError(
            "web_batch", batch_id, expected_cursor, int(current["cursor"])
        )
    await conn.execute(
        text(
            """
            UPDATE design_web_batch
            SET cursor = :cursor, status = :status,
                manifest_json = CAST(:manifest AS jsonb), updated_at = now()
            WHERE batch_id = :b AND workspace_id = :w
            """
        ),
        {
            "cursor": cursor,
            "status": status,
            "manifest": dump_json(manifest),
            "b": batch_id,
            "w": workspace_id,
        },
    )
    return await require_web_batch(conn, workspace_id=workspace_id, batch_id=batch_id)
