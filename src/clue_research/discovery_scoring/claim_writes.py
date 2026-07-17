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

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Claim, ClaimId, RunId
from clue_research.claimstore import (
    TenantScope,
    claims_for,
    insert_claim,
    supersede_claim,
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


async def write_icp_scoped_claim(
    conn: AsyncConnection,
    claim: Claim,
    *,
    run_id: RunId,
    icp_key: str,
    scope: TenantScope,
) -> tuple[ClaimId, bool]:
    """Persist a stamped score-family ``claim`` idempotently + ICP-scoped → ``(claim_id, written)``.

    Idempotency on the deterministic ``run_id``: an existing live claim for this run is reused
    (``written=False`` — no new row, no double-charge). A live claim from a *different* run of the
    **same ICP** is **superseded** so the merged truth keeps one live winner per ICP (append-only
    history preserved); a claim from a *different* ICP is left untouched (D5). The caller supplies
    the already-``stamp_reuse``-stamped ``claim`` and the read ``scope``; this owns only the
    read → replay-check → supersede-by-icp-key → insert sequence (the shared protocol)."""
    existing = await claims_for(conn, claim.entity_id, claim.field_key, scope=scope)
    for prior in existing:
        if prior.run_id == run_id:
            return prior.id, False
    # `existing` is collected_at-desc; supersede the latest live claim for THIS ICP (a re-write
    # replaces its predecessor), leaving any other ICP's claim for this entity intact.
    for prior in existing:
        if claim_icp_key(prior) == icp_key:
            return await supersede_claim(conn, prior.id, claim), True
    return await insert_claim(conn, claim), True


__all__ = ["claim_icp_key", "write_icp_scoped_claim"]
