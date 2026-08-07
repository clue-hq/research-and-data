"""Brand-kit DAL (Part II slice D2.3) — the port of the design API's brand domain.

Faithful port of ``lumen_api.database.Repository``'s brand methods onto ``design_brand_kit`` +
``design_brand_compat_report`` (PD contract §5 rows 7–8), with the D1/D2 upgrades the contract
mandates:

* **Fail-closed tenancy.** Every function takes ``workspace_id`` and locates rows by
  ``(…, workspace_id)``; a foreign-workspace id raises the same :class:`DesignNotFoundError`
  an absent id does. Kit ids are client-suppliable (the payload carries its own ``id``), which
  is why migration ``7a9881f9717a`` made the key ``(brand_kit_id, version, workspace_id)``.
* **Closed vocabularies are enum columns**, not free text: ``approval_status`` and ``source``
  are cast to ``design_brand_approval_status`` / ``design_brand_kit_source``, so the SQLite
  CHECK that guarded ``source`` is now a type.

Versions are immutable-by-convention: a new version is a NEW row, never an in-place rewrite of
``brand_kit_json``. The single exception is the ported approval flip, which deliberately writes
BOTH the ``approval_status`` column and the mirrored ``brand_kit_json.approval_status`` so the
persisted kit JSON never disagrees with its row (the SQLite behavior, preserved verbatim).

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``brand_kit_from_row`` / ``brand_compatibility_report_from_row``
exactly, with ISO-string timestamps.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError


def _brand_kit_from_row(row: Any) -> JsonObject:
    return {
        "brand_kit_id": row.brand_kit_id,
        "version": row.version,
        "name": row.name,
        "approval_status": row.approval_status,
        "product_ready": bool(row.product_ready),
        "source": row.source,
        "brand_kit": load_json(row.brand_kit_json),
        "brand_summary": load_json(row.brand_summary_json),
        "diagnostics": load_json(row.diagnostics_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _compat_report_from_row(row: Any) -> JsonObject:
    return {
        "report_id": row.report_id,
        "from_ref": {"id": row.from_brand_kit_id, "version": row.from_version},
        "to_ref": {"id": row.to_brand_kit_id, "version": row.to_version},
        "report": load_json(row.report_json),
        "diagnostics": load_json(row.diagnostics_json),
        "created_at": iso(row.created_at),
    }


async def get_brand_kit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_kit_id: str,
    version: int | None = None,
    for_update: bool = False,
) -> JsonObject:
    """The ``require_brand_kit`` port: an explicit version, else the latest one."""
    suffix = " FOR UPDATE" if for_update else ""
    params: dict[str, object] = {"b": brand_kit_id, "w": workspace_id}
    if version is None:
        query = (
            "SELECT * FROM design_brand_kit WHERE brand_kit_id = :b AND workspace_id = :w"
            f" ORDER BY version DESC LIMIT 1{suffix}"
        )
    else:
        query = (
            "SELECT * FROM design_brand_kit"
            f" WHERE brand_kit_id = :b AND workspace_id = :w AND version = :v{suffix}"
        )
        params["v"] = version
    row = (await conn.execute(text(query), params)).first()
    if row is None:
        raise DesignNotFoundError("brand_kit", brand_kit_id)
    return _brand_kit_from_row(row)


async def create_brand_kit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_kit: JsonObject,
    brand_summary: JsonObject,
    diagnostics: list[JsonObject],
    source: str,
) -> JsonObject:
    """Publish one kit VERSION (the id/version come from the kit payload itself)."""
    brand_kit_id = str(brand_kit["id"])
    version = int(brand_kit["version"])
    await conn.execute(
        text(
            """
            INSERT INTO design_brand_kit (
              brand_kit_id, version, workspace_id, name, approval_status, product_ready,
              source, brand_kit_json, brand_summary_json, diagnostics_json
            )
            VALUES (:b, :v, :w, :name, CAST(:approval AS design_brand_approval_status),
                    :product_ready, CAST(:source AS design_brand_kit_source),
                    CAST(:kit AS jsonb), CAST(:summary AS jsonb), CAST(:diagnostics AS jsonb))
            """
        ),
        {
            "b": brand_kit_id,
            "v": version,
            "w": workspace_id,
            "name": brand_kit["name"],
            "approval": brand_kit.get("approval_status"),
            "product_ready": bool(brand_summary.get("product_ready")),
            "source": source,
            "kit": dump_json(brand_kit),
            "summary": dump_json(brand_summary),
            "diagnostics": dump_json(diagnostics),
        },
    )
    return await get_brand_kit(
        conn, workspace_id=workspace_id, brand_kit_id=brand_kit_id, version=version
    )


async def list_brand_kits(
    conn: AsyncConnection, *, workspace_id: str, all_versions: bool = False
) -> list[JsonObject]:
    """Every version, or (default) the latest version of each kit — ported ordering."""
    if all_versions:
        query = (
            "SELECT * FROM design_brand_kit WHERE workspace_id = :w"
            " ORDER BY brand_kit_id ASC, version DESC"
        )
    else:
        # DISTINCT ON is the PG-native form of the SQLite MAX(version) self-join.
        query = (
            "SELECT DISTINCT ON (brand_kit_id) * FROM design_brand_kit WHERE workspace_id = :w"
            " ORDER BY brand_kit_id ASC, version DESC"
        )
    rows = await conn.execute(text(query), {"w": workspace_id})
    return [_brand_kit_from_row(row) for row in rows]


async def update_brand_kit_approval(
    conn: AsyncConnection, *, workspace_id: str, brand_kit_id: str, approval_status: str
) -> JsonObject:
    """Set the approval state on the LATEST version of a kit (row-locked).

    Writes BOTH the ``approval_status`` column and the mirrored
    ``brand_kit_json.approval_status`` so the persisted kit JSON stays consistent with its row.
    An unknown kit raises :class:`DesignNotFoundError`.
    """
    record = await get_brand_kit(
        conn, workspace_id=workspace_id, brand_kit_id=brand_kit_id, for_update=True
    )
    version = int(record["version"])
    brand_kit = record["brand_kit"]
    brand_kit["approval_status"] = approval_status
    await conn.execute(
        text(
            """
            UPDATE design_brand_kit
            SET approval_status = CAST(:approval AS design_brand_approval_status),
                brand_kit_json = CAST(:kit AS jsonb), updated_at = now()
            WHERE brand_kit_id = :b AND version = :v AND workspace_id = :w
            """
        ),
        {
            "approval": approval_status,
            "kit": dump_json(brand_kit),
            "b": brand_kit_id,
            "v": version,
            "w": workspace_id,
        },
    )
    return await get_brand_kit(
        conn, workspace_id=workspace_id, brand_kit_id=brand_kit_id, version=version
    )


async def create_brand_compat_report(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    report_id: str,
    from_brand_kit: JsonObject,
    to_brand_kit: JsonObject,
    report: JsonObject,
    diagnostics: list[JsonObject],
) -> JsonObject:
    """Persist one cross-version compatibility diff (both endpoints are same-workspace kits —
    the composite FKs enforce that structurally, not by convention)."""
    await conn.execute(
        text(
            """
            INSERT INTO design_brand_compat_report (
              report_id, workspace_id, from_brand_kit_id, from_version,
              to_brand_kit_id, to_version, report_json, diagnostics_json
            )
            VALUES (:r, :w, :from_id, :from_v, :to_id, :to_v,
                    CAST(:report AS jsonb), CAST(:diagnostics AS jsonb))
            """
        ),
        {
            "r": report_id,
            "w": workspace_id,
            "from_id": from_brand_kit["id"],
            "from_v": int(from_brand_kit["version"]),
            "to_id": to_brand_kit["id"],
            "to_v": int(to_brand_kit["version"]),
            "report": dump_json(report),
            "diagnostics": dump_json(diagnostics),
        },
    )
    return await get_brand_compat_report(conn, workspace_id=workspace_id, report_id=report_id)


async def get_brand_compat_report(
    conn: AsyncConnection, *, workspace_id: str, report_id: str
) -> JsonObject:
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_brand_compat_report"
                " WHERE report_id = :r AND workspace_id = :w"
            ),
            {"r": report_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("brand_compatibility_report", report_id)
    return _compat_report_from_row(row)
