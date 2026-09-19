"""``design_logo_family`` DAL — the durable target-logo family cache (vendor-first logo family,
Task 7).

Keyed ``(workspace_id, registrable_domain)``; workspace-scoped by the row itself, so a foreign
workspace's read is an ordinary miss. No TTL: overwrite (``force_refresh``) stamps
``refreshed_at``.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. jsonb travels the module family's established way: ``dump_json`` in with an
explicit ``CAST(… AS jsonb)``, ``load_json`` tolerantly out.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json


async def get_logo_family(
    conn: AsyncConnection, *, workspace_id: str, registrable_domain: str
) -> JsonObject | None:
    """The cached family for one domain, or ``None`` — a miss, never a raise (this is a cache)."""
    row = (
        await conn.execute(
            text(
                "SELECT family, fetched_at, refreshed_at FROM design_logo_family "
                "WHERE workspace_id = :w AND registrable_domain = :d"
            ),
            {"w": workspace_id, "d": registrable_domain},
        )
    ).first()
    if row is None:
        return None
    return {
        "family": load_json(row.family),
        "fetched_at": iso(row.fetched_at),
        "refreshed_at": iso(row.refreshed_at),
    }


async def upsert_logo_family(
    conn: AsyncConnection, *, workspace_id: str, registrable_domain: str, family: JsonObject
) -> None:
    """Write (or overwrite) one domain's family. Converges: re-putting the same family is a
    no-op in content, and the ``force_refresh`` overwrite path stamps ``refreshed_at`` while
    ``fetched_at`` keeps the first capture."""
    await conn.execute(
        text(
            "INSERT INTO design_logo_family (workspace_id, registrable_domain, family) "
            "VALUES (:w, :d, CAST(:f AS jsonb)) "
            "ON CONFLICT (workspace_id, registrable_domain) "
            "DO UPDATE SET family = EXCLUDED.family, refreshed_at = now()"
        ),
        {"w": workspace_id, "d": registrable_domain, "f": dump_json(family)},
    )
