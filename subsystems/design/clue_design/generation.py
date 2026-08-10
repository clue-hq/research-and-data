"""Generation-result ledger DAL (Part II slice D6 Round C).

The home the generation cache was always owed. ``lumen_api.image_cache`` mapped a normalized
generation request (prompt + model + constraints + reference/source digests) to the asset record
it produced, so an identical repeat re-places the same image instead of re-paying the model — but
it persisted that map as a *mutable JSON sidecar* under the engine materialization cache
(``{engine_cache_root}/{workspace_id}/.generation-cache.json``). Its own docstring named this
round as the fix, and it is a fix for three separate defects, not one:

* **It was not durable.** The engine cache is a wipeable mirror by construction (D4), so the
  index that decides whether we pay a provider lived in the one tree the system is allowed to
  delete.
* **It was last-writer-wins across processes.** Two API workers (or the API and a fleet worker)
  pointed at the same directory raced on a whole-file rewrite; a lost write is a silent
  double-spend.
* **It could serve a deleted asset.** Nothing tied a sidecar entry to the asset row it named, so
  a hard-deleted asset stayed cached forever. The ledger's composite FK
  (``ON DELETE CASCADE``) makes that unrepresentable — deleting the asset deletes its ledger
  entry, and the next identical request regenerates honestly.

``generation_key`` is unchanged (:func:`lumen_api.image_cache.generation_key` still computes it);
only its storage moves. The AGENT-RUNTIME half of the cache deliberately stays on the file
sidecar — see that module's docstring — because the design agent runtime holds no database
handle; unifying it is Part-III work.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing here
commits.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, load_json
from clue_design.assets import create_asset_record

__all__ = ["get_generation_result", "record_generation_result"]


async def get_generation_result(
    conn: AsyncConnection, *, workspace_id: str, generation_key: str
) -> JsonObject | None:
    """The pre-spend probe: the asset an identical earlier request produced, or ``None``.

    Returns the LIVE asset record (joined from ``design_asset``), not the snapshot the ledger
    row carries — a description edit or a re-registration must be visible to a cache hit, and the
    cascade guarantees the join always resolves.
    """
    row = (
        await conn.execute(
            text(
                "SELECT a.record_json AS record_json, g.asset_id AS asset_id"
                " FROM design_generation_result g"
                " JOIN design_asset a"
                "   ON a.asset_id = g.asset_id AND a.workspace_id = g.workspace_id"
                " WHERE g.workspace_id = :w AND g.generation_key = :k"
            ),
            {"w": workspace_id, "k": generation_key},
        )
    ).first()
    if row is None:
        return None
    return {"asset_id": row.asset_id, "asset": load_json(row.record_json)}


async def record_generation_result(
    conn: AsyncConnection, *, workspace_id: str, generation_key: str, record: JsonObject
) -> JsonObject:
    """Register a freshly generated asset AND claim the ledger key — one transaction.

    Consults the ledger *inside the write*: a key that is already claimed returns the claimed
    asset and registers nothing, so the tool is genuinely domain-idempotent on
    ``(workspace, generation_key)`` even when two identical requests raced past the route's
    pre-spend probe. ``created`` tells the caller which of the two happened.
    """
    existing = await get_generation_result(
        conn, workspace_id=workspace_id, generation_key=generation_key
    )
    if existing is not None:
        return {**existing, "created": False}

    stored = await create_asset_record(conn, workspace_id=workspace_id, record=record)
    asset_id = str(record["id"])
    await conn.execute(
        text(
            """
            INSERT INTO design_generation_result (
              workspace_id, generation_key, asset_id, record_json
            )
            VALUES (:w, :k, :a, CAST(:record AS jsonb))
            ON CONFLICT (workspace_id, generation_key) DO NOTHING
            """
        ),
        {"w": workspace_id, "k": generation_key, "a": asset_id, "record": dump_json(record)},
    )
    winner = await get_generation_result(
        conn, workspace_id=workspace_id, generation_key=generation_key
    )
    if winner is None:  # pragma: no cover - the insert above either landed or found a claim
        raise RuntimeError(f"generation key {generation_key!r} vanished after being claimed")
    if winner["asset_id"] != asset_id:
        # A concurrent identical generation claimed the key first. Its asset is the answer;
        # ours is already registered (content-addressed bytes, harmless) but unreferenced.
        return {**winner, "created": False}
    return {"asset_id": asset_id, "asset": stored["asset"], "created": True}
