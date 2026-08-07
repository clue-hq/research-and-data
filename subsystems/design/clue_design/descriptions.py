"""Asset-description DAL (Part II slice D2.3) — the port of the design API's description domain.

Faithful port of ``lumen_ingestion.describe.DescriptionStore`` onto ``design_asset_description``
(PD contract §5 row 11; O3 preserved this table expressly, with its full behavior), with the
D1/D2 upgrades the contract mandates:

* **Human curation wins, in SQL.** :func:`put_ai` is a CONDITIONAL upsert — its
  ``ON CONFLICT (asset_id, workspace_id) DO UPDATE`` carries
  ``WHERE design_asset_description.origin != 'human'``, so an AI caption can never overwrite a
  human-authored row (and the write is a silent no-op when it tries, exactly as before).
  :func:`put_human` is unconditional: a human always wins, over AI *and* over another human.
* **Fail-closed tenancy.** Every function takes ``workspace_id``; reads and the upsert conflict
  target are both keyed on ``(asset_id, workspace_id)`` (migration ``cf4f80537c8e``), so one
  tenant's description can never be read by, or overwritten from, another workspace.
* **The 1:1 registry FK is real now** (SQLite deliberately omitted it): a description may only
  be written for an asset that exists in the same workspace, and it cascades on asset delete.
* **``origin`` is an enum column** (``design_description_origin``), not free text.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. The mapper reproduces ``describe._row_to_dict`` exactly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json_opt

_UPSERT_COLUMNS = "asset_id, workspace_id, title, description, usage, tags_json, origin, model"


def _description_from_row(row: Any) -> JsonObject:
    return {
        "asset_id": row.asset_id,
        "title": row.title,
        "description": row.description,
        "usage": row.usage,
        "tags": load_json_opt(row.tags_json) or [],
        "origin": row.origin,
        "model": row.model,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def get_many(
    conn: AsyncConnection, *, workspace_id: str, asset_ids: list[str]
) -> dict[str, JsonObject]:
    """The cache read: ``asset_id -> description`` for the caller's workspace only.

    One bound array (``= ANY(:ids)``) rather than the ported N placeholders — PG has no host
    parameter ceiling to chunk around.
    """
    if not asset_ids:
        return {}
    rows = await conn.execute(
        text(
            "SELECT * FROM design_asset_description"
            " WHERE workspace_id = :w AND asset_id = ANY(:ids)"
        ),
        {"w": workspace_id, "ids": list(asset_ids)},
    )
    return {row.asset_id: _description_from_row(row) for row in rows}


async def put_ai(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    title: str,
    description: str,
    usage: str,
    tags: list[str],
    model: str,
) -> None:
    """Persist one AI caption — never overwriting a human-authored row (the ported guard)."""
    await conn.execute(
        text(
            f"""
            INSERT INTO design_asset_description ({_UPSERT_COLUMNS})
            VALUES (:a, :w, :title, :description, :usage, CAST(:tags AS jsonb),
                    CAST('ai' AS design_description_origin), :model)
            ON CONFLICT (asset_id, workspace_id) DO UPDATE SET
              title = excluded.title,
              description = excluded.description,
              usage = excluded.usage,
              tags_json = excluded.tags_json,
              origin = CAST('ai' AS design_description_origin),
              model = excluded.model,
              updated_at = now()
            WHERE design_asset_description.origin != 'human'
            """  # noqa: S608 - the column list is a module constant, never caller input
        ),
        {
            "a": asset_id,
            "w": workspace_id,
            "title": title,
            "description": description,
            "usage": usage,
            "tags": dump_json(list(tags)),
            "model": model,
        },
    )


async def put_human(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    title: str | None,
    description: str | None,
    usage: str | None,
    tags: list[str],
) -> None:
    """Persist one human-authored description — unconditional, and it clears ``model``."""
    await conn.execute(
        text(
            f"""
            INSERT INTO design_asset_description ({_UPSERT_COLUMNS})
            VALUES (:a, :w, :title, :description, :usage, CAST(:tags AS jsonb),
                    CAST('human' AS design_description_origin), NULL)
            ON CONFLICT (asset_id, workspace_id) DO UPDATE SET
              title = excluded.title,
              description = excluded.description,
              usage = excluded.usage,
              tags_json = excluded.tags_json,
              origin = CAST('human' AS design_description_origin),
              model = NULL,
              updated_at = now()
            """  # noqa: S608 - the column list is a module constant, never caller input
        ),
        {
            "a": asset_id,
            "w": workspace_id,
            "title": title,
            "description": description,
            "usage": usage,
            "tags": dump_json(list(tags)),
        },
    )
