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
* **The O2 brand-spine join (D3).** ``create_brand_kit`` stamps ``brand_id`` via
  :mod:`clue_design.joins` (explicit id wins; else resolve-or-create the workspace's brand;
  NULL when the workspace is multi-brand), and every read surfaces it. Still nullable — see
  ``joins``' docstring for the deferred NOT NULL promotion.

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

from clue_design import web_fragments as _web_fragments
from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError, DesignVersionConflictError
from clue_design.joins import resolve_brand_id


def _brand_kit_from_row(row: Any) -> JsonObject:
    return {
        "brand_kit_id": row.brand_kit_id,
        "version": row.version,
        # D3: the O2 brand-spine join, surfaced (NULL when the workspace is multi-brand).
        "brand_id": row.brand_id,
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
    brand_id: str | None = None,
) -> JsonObject:
    """Publish one kit VERSION (the id/version come from the kit payload itself).

    D3 stamps the O2 brand-spine join here: an explicit ``brand_id`` wins (a foreign-workspace
    one is refused structurally by ``design_brand_kit_brand_fk``); otherwise the workspace's
    brand is resolved-or-created — see :func:`clue_design.joins.resolve_brand_id` for the
    one/none/several rules and why a multi-brand workspace stamps NULL.
    """
    brand_kit_id = str(brand_kit["id"])
    version = int(brand_kit["version"])
    resolved_brand_id = await resolve_brand_id(conn, workspace_id=workspace_id, brand_id=brand_id)
    await conn.execute(
        text(
            """
            INSERT INTO design_brand_kit (
              brand_kit_id, version, workspace_id, brand_id, name, approval_status,
              product_ready, source, brand_kit_json, brand_summary_json, diagnostics_json
            )
            VALUES (:b, :v, :w, :brand, :name, CAST(:approval AS design_brand_approval_status),
                    :product_ready, CAST(:source AS design_brand_kit_source),
                    CAST(:kit AS jsonb), CAST(:summary AS jsonb), CAST(:diagnostics AS jsonb))
            """
        ),
        {
            "b": brand_kit_id,
            "v": version,
            "w": workspace_id,
            "brand": resolved_brand_id,
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


async def publish_next_brand_kit_version(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_kit: JsonObject,
    brand_summary: JsonObject,
    diagnostics: list[JsonObject],
    source: str,
    expected_base_version: int,
    brand_id: str | None = None,
) -> JsonObject:
    """Allocate this kit's NEXT version under a lock and publish it (Part II slice D6 Round C).

    The two human-curation routes (``POST /brand-kits/{id}/logo``,
    ``POST /brand-kits/{id}/describe-assets``) read the latest version, mutate the kit JSON,
    compute ``version + 1`` **in Python**, and insert. Two concurrent curations therefore both
    computed the same next version and the loser died on the composite primary key — a raw
    ``IntegrityError`` surfacing as a duplicate-kit 409 that named the wrong cause, or (worse) a
    silent lost update if the versions happened not to collide.

    This closes it with two mechanisms, both required:

    * **Serialized allocation.** The lock is taken on the kit's *lowest-version* row, not its
      latest. A ``SELECT … ORDER BY version DESC LIMIT 1 FOR UPDATE`` would be useless here:
      under READ COMMITTED the blocked allocator re-checks only the row it already locked, and a
      competitor's new version arrives as an INSERT (a phantom) that its ``ORDER BY … LIMIT 1``
      never re-evaluates — so both would allocate the same number. The anchor row is the one row
      of the lineage that no publish can insert around, so every allocator serializes on the same
      physical row and the ``MAX(version)`` read *after* the lock sees every committed sibling.
    * **A compare-and-set on the content's base.** The caller built its kit JSON from the version
      it read; if another curation landed in between, publishing on top of it would silently
      discard that curation's edits. ``expected_base_version`` makes that a typed
      :class:`DesignVersionConflictError` (the route's 409) instead of a lost update.

    The allocated number is stamped into ``brand_kit["version"]`` before the insert, so the row
    and the persisted kit JSON can never disagree about which version this is.

    **The brand join is INHERITED, not re-resolved (brand-kit slice 4, 2026-08-18).** Without an
    explicit ``brand_id`` this used to fall through to :func:`clue_design.joins.resolve_brand_id`
    like a fresh kit, so publishing a new version of an ALREADY-LINKED kit into a workspace that
    had since grown a second brand stamped NULL — silently unlinking a kit whose brand was never
    in doubt. The heuristic answers "which brand does this NEW kit belong to?"; a later version
    of an existing lineage has already been answered, at birth. So the current version's
    ``brand_id`` is read under the same lock and passed as the explicit id. An explicit caller id
    still wins, and a lineage that is genuinely unlinked (born NULL in a multi-brand workspace)
    inherits nothing and resolves exactly as before.
    """
    brand_kit_id = str(brand_kit["id"])
    anchor = (
        await conn.execute(
            text(
                "SELECT version FROM design_brand_kit"
                " WHERE brand_kit_id = :b AND workspace_id = :w"
                " ORDER BY version ASC LIMIT 1 FOR UPDATE"
            ),
            {"b": brand_kit_id, "w": workspace_id},
        )
    ).first()
    if anchor is None:
        raise DesignNotFoundError("brand_kit", brand_kit_id)
    # The lineage's current head: its number (the CAS base and the allocation seed) and its brand
    # (the stamp the new version inherits). Safe as one ``ORDER BY … LIMIT 1`` — unlike the
    # allocation lock above, this runs with the anchor row already held, so no phantom can land
    # between it and the insert.
    head = (
        await conn.execute(
            text(
                "SELECT version, brand_id FROM design_brand_kit"
                " WHERE brand_kit_id = :b AND workspace_id = :w"
                " ORDER BY version DESC LIMIT 1"
            ),
            {"b": brand_kit_id, "w": workspace_id},
        )
    ).one()
    current = int(head.version)
    if current != expected_base_version:
        raise DesignVersionConflictError("brand_kit", brand_kit_id, expected_base_version, current)
    published = dict(brand_kit)
    published["version"] = current + 1
    return await create_brand_kit(
        conn,
        workspace_id=workspace_id,
        brand_kit=published,
        brand_summary=brand_summary,
        diagnostics=diagnostics,
        source=source,
        brand_id=brand_id if brand_id is not None else head.brand_id,
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


async def latest_approved_brand_kit_ref(
    conn: AsyncConnection, *, workspace_id: str
) -> JsonObject | None:
    """Return the newest approved kit ref for the workspace's unambiguous brand.

    A document-create request currently carries a workspace but no platform ``brand_id``. In a
    one-brand workspace that is sufficient context; in a multi-brand workspace it is not, and
    guessing would stamp the wrong client's identity onto a durable document. The query therefore
    fails closed unless the workspace owns exactly one brand. An explicit ref on the WebDoc is
    handled by the document DAL and always wins over this default.

    Approval is version-specific. A newer draft does not shadow an older approved version: the
    newest *approved* row is selected by its store recency, with deterministic tie-breakers.
    """
    row = (
        await conn.execute(
            text(
                """
                WITH workspace_brand AS (
                  SELECT min(brand_id) AS brand_id, count(*) AS brand_count
                  FROM brand
                  WHERE workspace_id = :w
                )
                SELECT kit.brand_kit_id, kit.version
                FROM design_brand_kit AS kit
                JOIN workspace_brand AS workspace_brand
                  ON workspace_brand.brand_count = 1
                 AND kit.brand_id = workspace_brand.brand_id
                WHERE kit.workspace_id = :w
                  AND kit.approval_status = 'approved'
                ORDER BY kit.updated_at DESC, kit.created_at DESC,
                         kit.version DESC, kit.brand_kit_id ASC
                LIMIT 1
                """
            ),
            {"w": workspace_id},
        )
    ).first()
    if row is None:
        return None
    return {"id": str(row.brand_kit_id), "version": int(row.version)}


async def approved_brand_mark_sha256(conn: AsyncConnection, *, workspace_id: str) -> str | None:
    """The digest of the workspace's brand mark (``assets.logos.mark``, first variant), or None.

    The mark is what website ingestion's logo ladder took from the client's own site — its
    manifest / apple-touch / favicon icon — so it is the page origin's default ``/favicon.ico``
    when no admin uploaded one. Same unambiguity rule as :func:`latest_approved_brand_kit_ref`
    (one brand, its newest approved kit): a multi-brand workspace gets None, never a guess.
    """
    ref = await latest_approved_brand_kit_ref(conn, workspace_id=workspace_id)
    if ref is None:
        return None
    row = (
        await conn.execute(
            text(
                "SELECT asset.digest_value FROM design_brand_kit AS kit"
                " JOIN design_asset AS asset ON asset.workspace_id = kit.workspace_id"
                " AND asset.asset_id ="
                " kit.brand_kit_json #>> '{assets,logos,mark,variants,0,asset_id}'"
                " AND asset.digest_algorithm = 'sha256'"
                " WHERE kit.workspace_id = :w AND kit.brand_kit_id = :b AND kit.version = :v"
            ),
            {"w": workspace_id, "b": ref["id"], "v": ref["version"]},
        )
    ).first()
    return str(row[0]) if row is not None and row[0] else None


async def update_brand_kit_approval(
    conn: AsyncConnection, *, workspace_id: str, brand_kit_id: str, approval_status: str
) -> JsonObject:
    """Set the approval state on the LATEST version of a kit (row-locked).

    Writes BOTH the ``approval_status`` column and the mirrored
    ``brand_kit_json.approval_status`` so the persisted kit JSON stays consistent with its row.
    An unknown kit raises :class:`DesignNotFoundError`.

    **The cloned sections ride along** (clone-fidelity F2.2). Website ingestion mints a
    ``design_web_fragment`` per section it captured, bound to the kit version it published and
    born ``draft``; this flip is the human gate that releases them. Same transaction, because a
    kit that says "approved" while the sections cloned out of the same capture still say "draft"
    is a state nobody asked for and everybody would have to reason about.
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
    await _web_fragments.sync_kit_fragment_approval(
        conn,
        workspace_id=workspace_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version=version,
        approved=approval_status == "approved",
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
