"""Scene-mode personalization DAL (Part II slice D2.4) — the port of the design API's
binding-set / instance / batch / repair-queue domain.

Faithful port of ``lumen_api.database.Repository``'s personalization methods onto
``design_binding_set``, ``design_instance_batch``, ``design_instance`` and
``design_repair_request`` (PD contract §5 rows 12–15), with the D1/D2 upgrades the contract
mandates:

* **Fail-closed tenancy.** Every function takes ``workspace_id`` and locates rows by
  ``(…, workspace_id)``; a foreign-workspace id raises the same :class:`DesignNotFoundError`
  an absent id does.
* **Real composite FKs.** The SQLite tables carried none: an instance now structurally belongs
  to a same-workspace ``design_template_revision`` + ``design_binding_set``, and a repair
  request to the revision/binding/instance it names. A dangling reference is an
  ``IntegrityError`` at the write, not a silent orphan discovered at read.
* **Deterministic ids stay deterministic.** ``instance_id`` (``inst_<rev>_<bind>``) and
  ``repair_id`` (``rep_<rev>_<slot>_<bind>``) are computed by the caller exactly as before, and
  the upserts remain upserts — re-deriving the same instance, or re-detecting the same slot
  overflow, refreshes ONE row rather than accumulating duplicates.

**Workspace-local ids.** Binding-set ids are client-supplied and instance/repair ids are
derived from them, so migration ``cf7dd82cf683`` re-keyed those three PKs to
``(…, workspace_id)`` (the ``7a9881f9717a`` ruling, applied to the namespaces D1d created
before it). Every upsert therefore arbitrates on ``(id, workspace_id)``: two tenants may hold
the same binding id, and neither can overwrite the other's row. ``design_instance_batch`` ids
are server-minted uuids and stay global — nothing to squat.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``binding_set_from_row`` / ``instance_from_row`` /
``batch_from_row`` / ``repair_from_row`` exactly, with ISO-string timestamps.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, dump_json_opt, iso, load_json, load_json_opt
from clue_design.errors import DesignNotFoundError


def _binding_set_from_row(row: Any) -> JsonObject:
    return {
        "binding_set_id": row.binding_set_id,
        "template_revision_id": row.template_revision_id,
        "binding_set": load_json(row.binding_json),
        "status": row.status,
        "diagnostics": load_json(row.diagnostics_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _instance_from_row(row: Any) -> JsonObject:
    return {
        "instance_id": row.instance_id,
        "template_revision_id": row.template_revision_id,
        "binding_set_id": row.binding_set_id,
        "batch_id": row.batch_id,
        "status": row.status,
        "fit_status": row.fit_status,
        "derived_scene": load_json(row.derived_scene_json),
        "diagnostics": load_json(row.diagnostics_json),
        "audit": load_json(row.audit_json),
        "fit_report": load_json(row.fit_report_json),
        "artifacts": load_json(row.artifacts_json),
        "generated_assets": load_json(row.generated_assets_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _batch_from_row(row: Any) -> JsonObject:
    return {
        "batch_id": row.batch_id,
        "template_revision_id": row.template_revision_id,
        "status": row.status,
        "binding_set_ids": load_json(row.binding_set_ids_json),
        "export_formats": load_json(row.export_formats_json),
        "export_profile": load_json_opt(row.export_profile_json),
        "chunk_size": row.chunk_size,
        "cursor": row.cursor,
        "counts": load_json(row.counts_json),
        "manifest": load_json(row.manifest_json),
        "diagnostics": load_json(row.diagnostics_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _repair_from_row(row: Any) -> JsonObject:
    return {
        "repair_id": row.repair_id,
        "template_revision_id": row.template_revision_id,
        "slot_key": row.slot_key,
        "node_id": row.node_id,
        "binding_set_id": row.binding_set_id,
        "instance_id": row.instance_id,
        "reason": row.reason,
        "status": row.status,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


# --- binding sets ----------------------------------------------------------------------------


async def get_binding_set(
    conn: AsyncConnection, *, workspace_id: str, binding_set_id: str
) -> JsonObject:
    """The ``require_binding_set`` port: fetch or raise."""
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_binding_set WHERE binding_set_id = :b AND workspace_id = :w"
            ),
            {"b": binding_set_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("binding_set", binding_set_id)
    return _binding_set_from_row(row)


async def upsert_binding_set(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    binding: JsonObject,
    status: str,
    diagnostics: list[JsonObject],
) -> JsonObject:
    """Re-authoring a binding set replaces its payload/status/diagnostics in place (the ported
    ``ON CONFLICT DO UPDATE``) — ids are client-supplied and stable per template slot map."""
    binding_set_id = str(binding["binding_set_id"])
    await conn.execute(
        text(
            """
            INSERT INTO design_binding_set (
              binding_set_id, workspace_id, template_revision_id, binding_json,
              status, diagnostics_json
            )
            VALUES (:b, :w, :r, CAST(:binding AS jsonb), :status,
                    CAST(:diagnostics AS jsonb))
            ON CONFLICT (binding_set_id, workspace_id) DO UPDATE SET
              template_revision_id = excluded.template_revision_id,
              binding_json = excluded.binding_json,
              status = excluded.status,
              diagnostics_json = excluded.diagnostics_json,
              updated_at = now()
            """
        ),
        {
            "b": binding_set_id,
            "w": workspace_id,
            "r": binding["template_revision_id"],
            "binding": dump_json(binding),
            "status": status,
            "diagnostics": dump_json(diagnostics),
        },
    )
    return await get_binding_set(conn, workspace_id=workspace_id, binding_set_id=binding_set_id)


async def list_binding_sets(
    conn: AsyncConnection, *, workspace_id: str, template_revision_id: str | None = None
) -> list[JsonObject]:
    """Every binding set in the workspace, or only those against one revision (ported order)."""
    params: dict[str, Any] = {"w": workspace_id}
    clause = ""
    if template_revision_id is not None:
        clause = " AND template_revision_id = :r"
        params["r"] = template_revision_id
    rows = await conn.execute(
        text(
            f"SELECT * FROM design_binding_set WHERE workspace_id = :w{clause}"  # noqa: S608
            " ORDER BY binding_set_id"
        ),
        params,
    )
    return [_binding_set_from_row(row) for row in rows]


async def delete_binding_set(
    conn: AsyncConnection, *, workspace_id: str, binding_set_id: str
) -> None:
    """Hard delete; an absent (or foreign-workspace) id raises.

    Instances and repair requests against the set cascade — an instance without its binding is
    meaningless (migration ``47d2e1ca25f1``). The SQLite original left them orphaned.
    """
    await get_binding_set(conn, workspace_id=workspace_id, binding_set_id=binding_set_id)
    await conn.execute(
        text("DELETE FROM design_binding_set WHERE binding_set_id = :b AND workspace_id = :w"),
        {"b": binding_set_id, "w": workspace_id},
    )


# --- instances -------------------------------------------------------------------------------


async def get_instance(conn: AsyncConnection, *, workspace_id: str, instance_id: str) -> JsonObject:
    """The ``require_instance`` port: fetch or raise."""
    row = (
        await conn.execute(
            text("SELECT * FROM design_instance WHERE instance_id = :i AND workspace_id = :w"),
            {"i": instance_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("instance", instance_id)
    return _instance_from_row(row)


async def upsert_instance(
    conn: AsyncConnection, *, workspace_id: str, instance: JsonObject
) -> JsonObject:
    """Idempotent derivation: the deterministic ``instance_id`` means re-deriving the same
    (revision, binding) pair REFRESHES one row rather than appending a second.

    The conflict clause deliberately leaves ``template_revision_id``/``binding_set_id`` alone
    (the ported behavior): they are the very inputs the id is derived from, so they cannot
    legitimately change for a given id.
    """
    instance_id = str(instance["instance_id"])
    await conn.execute(
        text(
            """
            INSERT INTO design_instance (
              instance_id, workspace_id, template_revision_id, binding_set_id, batch_id,
              status, fit_status, derived_scene_json, diagnostics_json, audit_json,
              fit_report_json, artifacts_json, generated_assets_json
            )
            VALUES (:i, :w, :r, :b, :batch, :status, :fit_status,
                    CAST(:scene AS jsonb), CAST(:diagnostics AS jsonb), CAST(:audit AS jsonb),
                    CAST(:fit_report AS jsonb), CAST(:artifacts AS jsonb),
                    CAST(:generated AS jsonb))
            ON CONFLICT (instance_id, workspace_id) DO UPDATE SET
              batch_id = excluded.batch_id,
              status = excluded.status,
              fit_status = excluded.fit_status,
              derived_scene_json = excluded.derived_scene_json,
              diagnostics_json = excluded.diagnostics_json,
              audit_json = excluded.audit_json,
              fit_report_json = excluded.fit_report_json,
              artifacts_json = excluded.artifacts_json,
              generated_assets_json = excluded.generated_assets_json,
              updated_at = now()
            """
        ),
        {
            "i": instance_id,
            "w": workspace_id,
            "r": instance["template_revision_id"],
            "b": instance["binding_set_id"],
            "batch": instance.get("batch_id"),
            "status": instance["status"],
            "fit_status": instance["fit_status"],
            "scene": dump_json(instance["derived_scene"]),
            "diagnostics": dump_json(instance.get("diagnostics", [])),
            "audit": dump_json(instance.get("audit", [])),
            "fit_report": dump_json(instance.get("fit_report", {})),
            "artifacts": dump_json(instance.get("artifacts", [])),
            "generated": dump_json(instance.get("generated_assets", {})),
        },
    )
    return await get_instance(conn, workspace_id=workspace_id, instance_id=instance_id)


async def list_instances(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    template_revision_id: str | None = None,
    batch_id: str | None = None,
) -> list[JsonObject]:
    """Ported filters (revision and/or batch) and ordering."""
    clauses = ["workspace_id = :w"]
    params: dict[str, Any] = {"w": workspace_id}
    if template_revision_id is not None:
        clauses.append("template_revision_id = :r")
        params["r"] = template_revision_id
    if batch_id is not None:
        clauses.append("batch_id = :batch")
        params["batch"] = batch_id
    where = " AND ".join(clauses)
    rows = await conn.execute(
        text(
            f"SELECT * FROM design_instance WHERE {where}"  # noqa: S608 - clauses are literals
            " ORDER BY instance_id"
        ),
        params,
    )
    return [_instance_from_row(row) for row in rows]


# --- instance batches ------------------------------------------------------------------------


async def get_instance_batch(
    conn: AsyncConnection, *, workspace_id: str, batch_id: str, for_update: bool = False
) -> JsonObject:
    """The ``require_batch`` port: fetch or raise, optionally locking the row."""
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_instance_batch"
                f" WHERE batch_id = :b AND workspace_id = :w{suffix}"
            ),
            {"b": batch_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("instance_batch", batch_id)
    return _batch_from_row(row)


async def create_instance_batch(
    conn: AsyncConnection, *, workspace_id: str, batch: JsonObject
) -> JsonObject:
    """Insert one chunked bulk-derivation batch (``cursor`` is the resume seam, ported as-is)."""
    batch_id = str(batch["batch_id"])
    await conn.execute(
        text(
            """
            INSERT INTO design_instance_batch (
              batch_id, workspace_id, template_revision_id, status, binding_set_ids_json,
              export_formats_json, export_profile_json, chunk_size, cursor, counts_json,
              manifest_json, diagnostics_json
            )
            VALUES (:b, :w, :r, :status, CAST(:binding_ids AS jsonb),
                    CAST(:formats AS jsonb), CAST(:profile AS jsonb), :chunk_size, :cursor,
                    CAST(:counts AS jsonb), CAST(:manifest AS jsonb),
                    CAST(:diagnostics AS jsonb))
            """
        ),
        {
            "b": batch_id,
            "w": workspace_id,
            "r": batch["template_revision_id"],
            "status": batch["status"],
            "binding_ids": dump_json(batch["binding_set_ids"]),
            "formats": dump_json(batch["export_formats"]),
            "profile": dump_json_opt(batch.get("export_profile")),
            "chunk_size": batch["chunk_size"],
            "cursor": batch["cursor"],
            "counts": dump_json(batch.get("counts", {})),
            "manifest": dump_json(batch.get("manifest", [])),
            "diagnostics": dump_json(batch.get("diagnostics", [])),
        },
    )
    return await get_instance_batch(conn, workspace_id=workspace_id, batch_id=batch_id)


async def update_instance_batch_progress(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    batch_id: str,
    cursor: int,
    status: str,
    counts: JsonObject,
    manifest: list[JsonObject],
    diagnostics: list[JsonObject],
) -> JsonObject:
    """Persist one chunk's progress (row-locked; the SQLite original raised the same
    not-found afterwards, on its read-back)."""
    await get_instance_batch(conn, workspace_id=workspace_id, batch_id=batch_id, for_update=True)
    await conn.execute(
        text(
            """
            UPDATE design_instance_batch
            SET cursor = :cursor, status = :status, counts_json = CAST(:counts AS jsonb),
                manifest_json = CAST(:manifest AS jsonb),
                diagnostics_json = CAST(:diagnostics AS jsonb), updated_at = now()
            WHERE batch_id = :b AND workspace_id = :w
            """
        ),
        {
            "cursor": cursor,
            "status": status,
            "counts": dump_json(counts),
            "manifest": dump_json(manifest),
            "diagnostics": dump_json(diagnostics),
            "b": batch_id,
            "w": workspace_id,
        },
    )
    return await get_instance_batch(conn, workspace_id=workspace_id, batch_id=batch_id)


# --- repair queue ----------------------------------------------------------------------------


async def upsert_repair_request(
    conn: AsyncConnection, *, workspace_id: str, repair: JsonObject
) -> JsonObject:
    """Re-detecting the same slot overflow updates ONE open row (deterministic ``repair_id``).

    ``status`` is written on insert only — the ported behavior: an operator who resolved a
    repair is not re-opened by the next derive that still sees the overflow.
    """
    repair_id = str(repair["repair_id"])
    await conn.execute(
        text(
            """
            INSERT INTO design_repair_request (
              repair_id, workspace_id, template_revision_id, slot_key, node_id,
              binding_set_id, instance_id, reason, status
            )
            VALUES (:r, :w, :rev, :slot, :node, :binding, :instance, :reason, :status)
            ON CONFLICT (repair_id, workspace_id) DO UPDATE SET
              instance_id = excluded.instance_id,
              reason = excluded.reason,
              updated_at = now()
            """
        ),
        {
            "r": repair_id,
            "w": workspace_id,
            "rev": repair["template_revision_id"],
            "slot": repair["slot_key"],
            "node": repair["node_id"],
            "binding": repair["binding_set_id"],
            "instance": repair.get("instance_id"),
            "reason": repair["reason"],
            "status": repair.get("status", "open"),
        },
    )
    return await get_repair_request(conn, workspace_id=workspace_id, repair_id=repair_id)


async def get_repair_request(
    conn: AsyncConnection, *, workspace_id: str, repair_id: str
) -> JsonObject:
    row = (
        await conn.execute(
            text("SELECT * FROM design_repair_request WHERE repair_id = :r AND workspace_id = :w"),
            {"r": repair_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("repair_request", repair_id)
    return _repair_from_row(row)


async def list_repair_queue(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    template_revision_id: str,
    status: str | None = None,
) -> list[JsonObject]:
    """The queue for one revision, optionally filtered by status (ported order)."""
    params: dict[str, Any] = {"w": workspace_id, "r": template_revision_id}
    clause = ""
    if status is not None:
        clause = " AND status = :status"
        params["status"] = status
    rows = await conn.execute(
        text(
            "SELECT * FROM design_repair_request"  # noqa: S608 - clause is a literal
            f" WHERE workspace_id = :w AND template_revision_id = :r{clause}"
            " ORDER BY repair_id"
        ),
        params,
    )
    return [_repair_from_row(row) for row in rows]
