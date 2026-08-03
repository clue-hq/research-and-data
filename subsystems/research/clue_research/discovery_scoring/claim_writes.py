"""The shared "one live winner per ICP" substrate-write protocol for M6's reserved score fields.

Both the Pass-A score object (M6.3, ``account.scoring.fit`` / ``.intent``) and the tier decision
(M6.4, ``account.scoring.tier``) persist a tenant-private claim on a reserved ``account.scoring.*``
field with the *same* discipline: idempotent on the deterministic ``run_id`` and ICP-scoped on
supersession (one live claim per ICP, append-only history kept). That write protocol lives **here,
once** (conventions §2 / CLAUDE.md DRY — the claim-write protocol is never written twice); each
caller builds only its own ``value_json`` + ``stamp_reuse``-stamped claim and delegates the
read → replay-check → supersede-by-icp-key → insert sequence to :func:`write_icp_scoped_claim`.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Claim, ClaimId, RunId
from clue_research.claimstore import (
    WorkspaceScope,
    claims_for,
    insert_claim,
    supersede_claims,
)


def claim_icp_key(claim: Claim) -> str | None:
    """The ICP key a score-family claim was written under (stored in its ``value_json``), or
    ``None``. The ICP discriminator for the per-ICP supersede (a score/tier for one ICP never
    supersedes another's on the same shared field — D5)."""
    value_json = claim.value_json
    if isinstance(value_json, dict):
        key = value_json.get("icp_key")
        if isinstance(key, str):
            return key
    return None


def claim_project_run_id(claim: Claim) -> str | None:
    """The owning project-run stamp for a score claim, absent on legacy/tiering claims."""

    value_json = claim.value_json
    if isinstance(value_json, dict):
        value = value_json.get("project_run_id")
        if isinstance(value, str):
            return value
    return None


async def write_icp_scoped_claim(
    conn: AsyncConnection,
    claim: Claim,
    *,
    run_id: RunId,
    icp_key: str,
    scope: WorkspaceScope,
) -> tuple[ClaimId, bool]:
    """Persist a stamped score-family ``claim`` idempotently + ICP-scoped → ``(claim_id, written)``.

    Idempotency on the deterministic ``run_id`` and exact ``product_id``: an existing live claim
    for that pair is reused (``written=False`` — no new row, no double-charge). A live claim from a
    *different* run of the same ``(ICP, product)`` is **superseded** so the merged truth keeps one
    live winner for that scope (append-only history preserved). A claim from another ICP or product
    is left untouched (D5 / C7.1 per-product fit). The caller supplies the already-
    ``stamp_reuse``-stamped ``claim`` and the read ``scope``; this owns only the read →
    replay-check → scoped supersede → insert sequence (the shared protocol)."""
    # Serialize writers in the exact score family before reading the live set. Without this lock,
    # two concurrent retries can both observe no predecessor and leave two live exact-scope rows.
    lock_key = ":".join(
        (
            "score",
            claim.workspace_id or "",
            str(claim.entity_id),
            str(claim.field_key),
            icp_key,
            claim.product_id or "",
            claim_project_run_id(claim) or "",
        )
    )
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )
    existing = await claims_for(conn, claim.entity_id, claim.field_key, scope=scope)
    for prior in existing:
        if prior.run_id == run_id and prior.product_id == claim.product_id:
            return prior.id, False
    predecessors = [
        prior.id
        for prior in existing
        if claim_icp_key(prior) == icp_key
        and prior.product_id == claim.product_id
        and claim_project_run_id(prior) == claim_project_run_id(claim)
    ]
    if predecessors:
        return await supersede_claims(conn, predecessors, claim), True
    return await insert_claim(conn, claim), True


__all__ = ["claim_icp_key", "claim_project_run_id", "write_icp_scoped_claim"]
