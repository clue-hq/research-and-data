"""Asset-registry DAL (Part II slice D2.3) — the port of the design API's asset domain.

Faithful port of ``lumen_api.database.Repository``'s asset methods onto ``design_asset`` (PD
contract §5 rows 9–10), with the D1/D2 upgrades the contract mandates:

* **Registry only, never bytes.** ``record_json`` is the canonical engine ``AssetRecord``; the
  scalar columns are query projections of it. Bytes stay in the API-local content-addressed
  store until D4 moves them to platform storage.
* **Fail-closed tenancy.** Every function takes ``workspace_id`` and locates rows by
  ``(asset_id, workspace_id)``; a foreign-workspace id raises the same
  :class:`DesignNotFoundError` an absent id does — including on the upsert path, whose
  ``ON CONFLICT`` target is the composite key, so one tenant can never overwrite another's row.
  (Asset ids are content-derived — ``asset_ing_<sha>``, ``asset_font_lib_…<digest>`` — which is
  why migration ``cf4f80537c8e`` made them workspace-local.)

:data:`_ASSET_COLUMNS` / :func:`_asset_row_params` are the ONE column list + row builder both
write paths (:func:`create_asset_record`'s canonical upsert and :func:`register_scene_assets`'s
scene promotion) write through, so a schema addition cannot silently diverge between them — the
ported ``ASSET_ROW_COLUMNS``/``asset_row_values`` discipline.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``asset_record_from_row`` exactly, with ISO-string timestamps.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError
from clue_design.storage import location_digest

_ASSET_COLUMNS = (
    "asset_id, workspace_id, label, kind, status, mime_type, digest_algorithm,"
    " digest_value, byte_length, filename, tags_json, record_json"
)
_ASSET_VALUES = (
    ":asset_id, :w, :label, :kind, :status, :mime_type, :digest_algorithm,"
    " :digest_value, :byte_length, :filename, CAST(:tags AS jsonb), CAST(:record AS jsonb)"
)


def _asset_row_params(record: JsonObject, workspace_id: str) -> dict[str, Any]:
    """The ported ``asset_row_values`` projection: scalar columns derived from the record."""
    media = record.get("media") or {}
    digest = media.get("digest") or {}
    return {
        "asset_id": record["id"],
        "w": workspace_id,
        "label": record.get("label") or "",
        "kind": record.get("kind") or "other",
        "status": record.get("status") or "ready",
        "mime_type": media.get("mime_type"),
        "digest_algorithm": digest.get("algorithm"),
        "digest_value": digest.get("value"),
        "byte_length": media.get("byte_length"),
        "filename": media.get("filename"),
        "tags": dump_json(record.get("tags") or []),
        "record": dump_json(record),
    }


def _asset_record_from_row(row: Any) -> JsonObject:
    return {
        "asset": load_json(row.record_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def get_asset_record(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    for_update: bool = False,
) -> JsonObject:
    """The ``require_asset_record`` port: fetch or raise, optionally locking the row."""
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        await conn.execute(
            text(f"SELECT * FROM design_asset WHERE asset_id = :a AND workspace_id = :w{suffix}"),
            {"a": asset_id, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("asset", asset_id)
    return _asset_record_from_row(row)


async def get_asset_records(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_ids: list[str] | tuple[str, ...],
) -> dict[str, JsonObject]:
    """Batch workspace-scoped asset records, omitting ids that are not visible.

    This is the read-side companion to :func:`get_asset_record`: callers that need every
    requested id still fail closed by comparing the returned keys, while transcript projections
    can preserve a truthful generic fallback for a historical ref whose registry row was erased.
    One statement serves the whole bounded set, so message history never becomes an N+1 read.
    """

    if not asset_ids:
        return {}
    rows = (
        await conn.execute(
            text(
                "SELECT * FROM design_asset "
                "WHERE workspace_id = :w AND asset_id = ANY(CAST(:asset_ids AS text[]))"
            ),
            {"w": workspace_id, "asset_ids": list(asset_ids)},
        )
    ).all()
    return {str(row.asset_id): _asset_record_from_row(row) for row in rows}


async def create_asset_record(
    conn: AsyncConnection, *, workspace_id: str, record: JsonObject
) -> JsonObject:
    """The canonical upsert (ported ``ON CONFLICT DO UPDATE``): re-registering an asset id
    replaces every projected column AND the record, curated fields included — this is the
    explicit "here is the record" write, unlike the curation-safe scene promotion below."""
    await conn.execute(
        text(
            f"""
            INSERT INTO design_asset ({_ASSET_COLUMNS})
            VALUES ({_ASSET_VALUES})
            ON CONFLICT (asset_id, workspace_id) DO UPDATE SET
              label = excluded.label,
              kind = excluded.kind,
              status = excluded.status,
              mime_type = excluded.mime_type,
              digest_algorithm = excluded.digest_algorithm,
              digest_value = excluded.digest_value,
              byte_length = excluded.byte_length,
              filename = excluded.filename,
              tags_json = excluded.tags_json,
              record_json = excluded.record_json,
              updated_at = now()
            """  # noqa: S608 - the column list is a module constant, never caller input
        ),
        _asset_row_params(record, workspace_id),
    )
    return await get_asset_record(conn, workspace_id=workspace_id, asset_id=str(record["id"]))


async def list_asset_records(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    kind: str | None = None,
    q: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[JsonObject]:
    """The library listing (ported filters + ordering), workspace-scoped."""
    clauses = ["workspace_id = :w"]
    params: dict[str, Any] = {"w": workspace_id, "limit": limit, "offset": offset}
    if not include_archived:
        clauses.append("status != 'archived'")
    if kind:
        clauses.append("kind = :kind")
        params["kind"] = kind
    if q:
        clauses.append(
            "(LOWER(label) LIKE :like OR LOWER(COALESCE(filename, '')) LIKE :like"
            " OR LOWER(tags_json::text) LIKE :like)"
        )
        params["like"] = f"%{q.lower()}%"
    where = " AND ".join(clauses)
    rows = await conn.execute(
        text(
            f"SELECT * FROM design_asset WHERE {where}"  # noqa: S608 - clauses are literals
            " ORDER BY updated_at DESC, asset_id LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [_asset_record_from_row(row) for row in rows]


async def update_asset_status(
    conn: AsyncConnection, *, workspace_id: str, asset_id: str, status: str
) -> JsonObject:
    """Archive/restore: the status column AND the mirrored ``record_json.status``."""
    stored = await get_asset_record(
        conn, workspace_id=workspace_id, asset_id=asset_id, for_update=True
    )
    record = stored["asset"]
    record["status"] = status
    await conn.execute(
        text(
            "UPDATE design_asset SET status = :status, record_json = CAST(:record AS jsonb),"
            " updated_at = now() WHERE asset_id = :a AND workspace_id = :w"
        ),
        {"status": status, "record": dump_json(record), "a": asset_id, "w": workspace_id},
    )
    return await get_asset_record(conn, workspace_id=workspace_id, asset_id=asset_id)


async def delete_asset_record(conn: AsyncConnection, *, workspace_id: str, asset_id: str) -> None:
    """Hard delete (the caller's reference checks gate it); an absent id raises."""
    await get_asset_record(conn, workspace_id=workspace_id, asset_id=asset_id)
    await conn.execute(
        text("DELETE FROM design_asset WHERE asset_id = :a AND workspace_id = :w"),
        {"a": asset_id, "w": workspace_id},
    )


async def count_assets_with_digest(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    digest_value: str,
    exclude_asset_id: str | None = None,
) -> int:
    """The byte-GC gate's record-reference count (now workspace-scoped).

    ``record_json`` LIKE keeps thumbnail digests visible too: any record whose canonical JSON
    mentions the digest still references it.
    """
    params: dict[str, Any] = {"w": workspace_id, "needle": f"%{digest_value}%"}
    clause = "workspace_id = :w AND record_json::text LIKE :needle"
    if exclude_asset_id:
        clause += " AND asset_id != :x"
        params["x"] = exclude_asset_id
    row = await conn.execute(
        text(f"SELECT count(*) FROM design_asset WHERE {clause}"),  # noqa: S608 - literals
        params,
    )
    return int(row.scalar_one())


async def register_scene_assets(
    conn: AsyncConnection, *, workspace_id: str, scene: JsonObject
) -> int:
    """Registry promotion for every locally stored asset the scene carries.

    Every scene-persist path funnels through this, so an asset any producer put into a scene
    (the deepagent's generated imagery, edits, QR codes) is servable through the registry-backed
    endpoints and visible in the asset library.

    Two write modes, both curation-safe:

    * UNSEEN asset id → insert the full row.
    * EXISTING id whose scene digest DIFFERS → refresh only the byte-identity columns
      (mime/digest/length/filename and the record's ``media`` block), so regenerate-in-place
      keeps the registry serving the CURRENT pixels. Curated columns (label, kind, status,
      tags) are never touched by a scene write.

    Returns the number of rows written. Since D2.3 this runs INSIDE the document write's
    transaction (the SQLite-era post-commit seam is closed) — promotion and the scene that
    carries it now land or roll back together.
    """
    assets = scene.get("assets")
    if not isinstance(assets, dict) or not assets:
        return 0
    candidates: dict[str, JsonObject] = {}
    for asset_id, record in assets.items():
        if not isinstance(record, dict):
            continue
        # Engine invariant: scene.assets keys by the record's own id. A mismatched entry is
        # malformed — never fabricate a registry row under a key the record does not claim.
        if record.get("id") != asset_id:
            continue
        media = record.get("media") or {}
        # D4: promotion is gated on the location RESOLVING TO A DIGEST, not on one provider
        # label. A record's provider becomes `clue-storage` once its bytes are registered
        # durably and stays `local-store`/`opaque_asset_store` on everything written before the
        # move — matching only the legacy label would silently stop promoting every asset a
        # D4-era producer puts into a scene. The digest test keeps the property the label was
        # standing in for: a location we can actually serve bytes for. A record pointing at some
        # other system's opaque handle still resolves to nothing and is still skipped.
        if location_digest(media.get("location")) is None:
            continue
        candidates[str(asset_id)] = record
    if not candidates:
        return 0
    # One bound-array lookup: PG has no host-parameter ceiling to chunk around.
    existing: dict[str, tuple[str | None, Any]] = {
        row.asset_id: (row.digest_value, row.record_json)
        for row in await conn.execute(
            text(
                "SELECT asset_id, digest_value, record_json FROM design_asset"
                " WHERE workspace_id = :w AND asset_id = ANY(:ids)"
            ),
            {"w": workspace_id, "ids": list(candidates)},
        )
    }
    written = 0
    for asset_id, record in candidates.items():
        media = record.get("media") or {}
        digest = media.get("digest") or {}
        if asset_id not in existing:
            result = await conn.execute(
                text(
                    f"INSERT INTO design_asset ({_ASSET_COLUMNS}) VALUES ({_ASSET_VALUES})"
                    " ON CONFLICT (asset_id, workspace_id) DO NOTHING"  # noqa: S608 - literals
                ),
                _asset_row_params(record, workspace_id),
            )
            written += max(result.rowcount, 0)
            continue
        stored_digest, stored_record_json = existing[asset_id]
        new_digest = digest.get("value")
        if not new_digest or new_digest == stored_digest:
            continue
        # Regenerate-in-place: refresh byte identity, preserve curation. record_json is
        # PATCHED (media block only), not replaced — the stored record may carry curated
        # fields a scene write must not clobber.
        stored_record = load_json(stored_record_json)
        stored_record["media"] = media
        result = await conn.execute(
            text(
                """
                UPDATE design_asset
                SET mime_type = :mime_type, digest_algorithm = :digest_algorithm,
                    digest_value = :digest_value, byte_length = :byte_length,
                    filename = :filename, record_json = CAST(:record AS jsonb),
                    updated_at = now()
                WHERE asset_id = :a AND workspace_id = :w
                """
            ),
            {
                "mime_type": media.get("mime_type"),
                "digest_algorithm": digest.get("algorithm"),
                "digest_value": new_digest,
                "byte_length": media.get("byte_length"),
                "filename": media.get("filename"),
                "record": dump_json(stored_record),
                "a": asset_id,
                "w": workspace_id,
            },
        )
        written += max(result.rowcount, 0)
    return written
