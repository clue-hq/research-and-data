"""Shared batch current-use and standing-objection reads."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ClaimId, EntityId, UseDecision, UseReason


async def latest_use_decisions(
    conn: AsyncConnection,
    claim_ids: Sequence[ClaimId],
) -> dict[ClaimId, UseDecision]:
    """Return the latest durable decision for each claim in one query."""

    ids = tuple(dict.fromkeys(claim_ids))
    if not ids:
        return {}
    stmt = text(
        """
        SELECT DISTINCT ON (claim_id)
               claim_id, usable_for_outreach, reason, policy_version
        FROM use_decision
        WHERE claim_id IN :claim_ids
        ORDER BY claim_id, policy_version DESC, evaluated_at DESC, id DESC
        """
    ).bindparams(bindparam("claim_ids", expanding=True))
    rows = (await conn.execute(stmt, {"claim_ids": list(ids)})).all()
    return {
        ClaimId(row[0]): UseDecision(
            claim_id=ClaimId(row[0]),
            usable_for_outreach=bool(row[1]),
            reason=UseReason(str(row[2])),
            policy_version=int(row[3]),
        )
        for row in rows
    }


async def standing_objections(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    contact_entity_ids: Sequence[EntityId],
) -> frozenset[EntityId]:
    """Return contacts with a current standing objection in this workspace."""

    ids = tuple(dict.fromkeys(contact_entity_ids))
    if not ids:
        return frozenset()
    stmt = text(
        """
        SELECT contact_entity_id
        FROM outreach_objected
        WHERE workspace_id = :workspace_id
          AND contact_entity_id IN :contact_entity_ids
        """
    ).bindparams(bindparam("contact_entity_ids", expanding=True))
    values = (
        await conn.execute(
            stmt,
            {"workspace_id": workspace_id, "contact_entity_ids": list(ids)},
        )
    ).scalars()
    return frozenset(EntityId(value) for value in values)


__all__ = ["latest_use_decisions", "standing_objections"]
