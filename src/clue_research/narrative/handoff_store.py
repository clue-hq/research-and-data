"""The ``account_handoff`` materialization — write-on-assembly, recompute-on-supersede (M12.2).

``assemble`` (``narrative.handoff``) is a *pure read* of the claim store; this module caches its
result so M12.3 serves a stable object with a precomputed provenance index, Postgres stays the only
source of truth, and a re-assembly after a claim is superseded simply replaces the row (overview §3
recommended persistence; AC8). The whole :class:`~clue_research.narrative.handoff.AssembledHandoff`
(the frozen ``AccountHandoff`` contract object + the M12.2 extras) is stored as a JSONB ``payload``;
the scope key columns ``(client_id, account_entity_id, icp_spec_version)`` make a client's view
fetchable and tenant-isolated (substrate §2 — the same public account researched by two clients
keeps two handoffs).

This is a *read-projection* of the claim store, never a write-back path (conventions §6 / substrate
§5c): the only writer is the assembler caching its own read.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import EntityId
from clue_research.narrative.handoff import AssembledHandoff


async def write_handoff(
    conn: AsyncConnection, assembled: AssembledHandoff, *, client_id: str, icp_key: str = ""
) -> None:
    """Materialise ``assembled`` for ``(client_id, icp_key)`` (UPSERT on the ``(client_id,
    account_entity_id, icp_spec_version, icp_key)`` scope key — a re-assembly after supersession
    replaces the payload + ``assembled_at``, never duplicating). ``icp_key`` is the ICP segment
    (D5: ``icp_spec_version`` restarts at 1 per ``icp_key``, so two segments must not clobber each
    other's materialised handoff); it defaults to ``""`` for a single-segment account. The full
    ``AssembledHandoff`` is stored as JSONB so the serve path reconstructs it without re-reading the
    claim store."""
    h = assembled.handoff
    payload = assembled.model_dump(mode="json")
    await conn.execute(
        text(
            """
            INSERT INTO account_handoff
                (client_id, account_entity_id, icp_spec_version, icp_key, campaign_run_id,
                 assembled_at, payload)
            VALUES
                (:client_id, :account_entity_id, :icp_spec_version, :icp_key, :campaign_run_id,
                 :assembled_at, CAST(:payload AS jsonb))
            ON CONFLICT (client_id, account_entity_id, icp_spec_version, icp_key) DO UPDATE SET
                campaign_run_id = EXCLUDED.campaign_run_id,
                assembled_at    = EXCLUDED.assembled_at,
                payload         = EXCLUDED.payload
            """
        ),
        {
            "client_id": client_id,
            "account_entity_id": str(h.account_entity_id),
            "icp_spec_version": h.icp_spec_version,
            "icp_key": icp_key,
            "campaign_run_id": str(h.campaign_run_id) if h.campaign_run_id is not None else None,
            "assembled_at": h.assembled_at,
            "payload": json.dumps(payload),
        },
    )


async def read_handoff(
    conn: AsyncConnection,
    *,
    client_id: str,
    account_entity_id: EntityId,
    icp_spec_version: int,
    icp_key: str = "",
) -> AssembledHandoff | None:
    """Read the materialised :class:`AssembledHandoff` for ``(client_id, account_entity_id,
    icp_spec_version, icp_key)``, or ``None`` if it has not been assembled. Tenant-scoped on
    ``client_id`` so a client never reads another client's assembled handoff (substrate §2);
    ``icp_key`` (default ``""``) selects the ICP segment (D5)."""
    row = (
        await conn.execute(
            text(
                "SELECT payload FROM account_handoff WHERE client_id = :client_id "
                "AND account_entity_id = :account_entity_id "
                "AND icp_spec_version = :icp_spec_version AND icp_key = :icp_key"
            ),
            {
                "client_id": client_id,
                "account_entity_id": str(account_entity_id),
                "icp_spec_version": icp_spec_version,
                "icp_key": icp_key,
            },
        )
    ).first()
    if row is None:
        return None
    raw = row[0]
    payload = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
    return AssembledHandoff.model_validate(payload)
