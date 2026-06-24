"""The ``claim_support`` side table — a narrative claim's two-sided provenance (M12.1).

A value-narrative claim is grounded on **both** sides: the verified account claims it argues from
and the Client-Knowledge-Base passages it draws on (overview §3
``supporting{account_evidence_ids[], client_knowledge_ids[]}``; Output 4). Per the phase-3
pre-flight PF-2 decision, that linkage is a **side table keyed on the narrative ``claim_id``** —
never extra columns on ``claim`` (so no branch ALTERs the append-only ``claim`` or its immutable
guard). It is the exact M9 side-table pattern (``faithfulness_verdict`` /
``identity_binding_eval``): no FK to ``claim(id)`` (the link survives supersession), one row per
narrative ``claim_id``.

M12.1 (the positioner) writes it atomically with the narrative claim; M12.2 (the assembler) reads
it to populate :class:`clue_research.core.handoff.NarrativeSupport` and the provenance index, so
"every narrative line is sourced on both sides" is a queryable property, not a promise.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import ClaimId


class ClaimSupport(BaseModel):
    """The two-sided evidence behind one narrative claim (the ``claim_support`` row).

    ``account_evidence_ids`` are verified account ``claim`` ids; ``client_knowledge_ids`` are
    durable ids into the Client Knowledge Base (the ``client_knowledge_id`` the retriever
    returned).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    account_evidence_ids: tuple[ClaimId, ...] = ()
    client_knowledge_ids: tuple[str, ...] = ()


def _decode_list(raw: object) -> list[object]:
    """Decode a JSONB array column to a Python list (asyncpg returns it already decoded; a raw
    ``bytes`` / ``str`` is parsed defensively). A non-array decodes to the empty list.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return list(raw) if isinstance(raw, list) else []


async def write_claim_support(
    conn: AsyncConnection,
    claim_id: ClaimId,
    *,
    account_evidence_ids: Sequence[ClaimId],
    client_knowledge_ids: Sequence[str],
) -> None:
    """Write the ``claim_support`` row for a narrative claim (idempotent on ``claim_id``).

    Stored as JSONB arrays (the codebase convention for id collections — e.g.
    ``gate_decision.reasons``). ``ON CONFLICT (claim_id) DO NOTHING`` makes a re-attempt for the
    same claim a no-op (each re-synthesis mints a NEW claim id, so this is purely a safety net,
    never an update path).
    """
    await conn.execute(
        text(
            """
            INSERT INTO claim_support (claim_id, account_evidence_ids, client_knowledge_ids)
            VALUES (:claim_id, CAST(:account_ids AS jsonb), CAST(:client_ids AS jsonb))
            ON CONFLICT (claim_id) DO NOTHING
            """
        ),
        {
            "claim_id": str(claim_id),
            "account_ids": json.dumps([str(cid) for cid in account_evidence_ids]),
            "client_ids": json.dumps([str(ckid) for ckid in client_knowledge_ids]),
        },
    )


async def read_claim_support(conn: AsyncConnection, claim_id: ClaimId) -> ClaimSupport | None:
    """Read the ``claim_support`` row for a narrative ``claim_id``, or ``None`` if absent."""
    row = (
        await conn.execute(
            text(
                "SELECT account_evidence_ids, client_knowledge_ids FROM claim_support "
                "WHERE claim_id = :claim_id"
            ),
            {"claim_id": str(claim_id)},
        )
    ).first()
    if row is None:
        return None
    account_ids = tuple(ClaimId(UUID(str(x))) for x in _decode_list(row[0]))
    client_ids = tuple(str(x) for x in _decode_list(row[1]))
    return ClaimSupport(
        claim_id=claim_id,
        account_evidence_ids=account_ids,
        client_knowledge_ids=client_ids,
    )
