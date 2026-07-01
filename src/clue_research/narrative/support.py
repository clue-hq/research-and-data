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

from clue_research.core import ClaimId, decode_jsonb


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
    ``bytes`` / ``str`` is parsed defensively through ``core.decode_jsonb``). Malformed JSON or a
    non-array decodes to the empty list — fail-soft, a stale row never raises mid-assembly.
    """
    try:
        decoded = decode_jsonb(raw)
    except ValueError:
        return []
    return list(decoded) if isinstance(decoded, list) else []


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


class FaithfulnessCitation(BaseModel):
    """The faithfulness-judge citation behind a verified value-narrative claim — "judged faithful by
    ``<answering_model>@<prompt_version>``" (M12.2 provenance; substrate §6(3) / Doc C §6).

    ``answering_model`` is the gateway model that *actually* produced the verdict (it differs from
    the requested ``judge_model`` only on an OpenRouter fallback; backfilled to ``judge_model`` for
    pre-column rows). M12.2 cites it so the handoff names the model that did the judging — not a
    requested id that a fallback bypassed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    verdict: str
    score: float
    judge_model: str  # the requested id (the cache key)
    answering_model: str  # the id that actually answered (cited)
    prompt_version: str


async def read_faithfulness_citation(
    conn: AsyncConnection, claim_id: ClaimId
) -> FaithfulnessCitation | None:
    """Read the latest M9.3 ``faithfulness_verdict`` for ``claim_id``, or ``None`` if the claim was
    never judged.

    Reads the verification-layer side table directly (the shared claim-store substrate — the same
    way the assembler reads any claim/side-table row), NOT by importing the ``verification`` package
    (the import-linter independence contract forbids ``narrative → verification``). One row per
    ``(claim_id, judge_model, prompt_version)``; the most recently judged wins (a re-judge under a
    new prompt mints a fresh row). ``answering_model`` falls back to ``judge_model`` if a legacy row
    predates the column (the migration backfills it, so this is belt-and-braces)."""
    row = (
        await conn.execute(
            text(
                "SELECT verdict, score, judge_model, answering_model, prompt_version "
                "FROM faithfulness_verdict WHERE claim_id = :claim_id "
                "ORDER BY judged_at DESC, judge_model DESC LIMIT 1"
            ),
            {"claim_id": str(claim_id)},
        )
    ).first()
    if row is None:
        return None
    judge_model = str(row[2])
    answering_model = str(row[3]) if row[3] is not None else judge_model
    return FaithfulnessCitation(
        claim_id=claim_id,
        verdict=str(row[0]),
        score=float(row[1]),
        judge_model=judge_model,
        answering_model=answering_model,
        prompt_version=str(row[4]),
    )
