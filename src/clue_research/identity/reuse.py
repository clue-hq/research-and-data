"""Cross-tenant reuse classification + the isolation helpers (M2.5).

Realize the architecture's moat safely (substrate §2): public-footprint claims about a company
amortize across clients; client-specific scoring and any client-private data stay strictly
tenant-isolated. This module is the **single point that decides reuse** — the classifier maps
``(field_key, extraction_method, source_tier) → reuse_scope`` from versioned policy
(:class:`ReusePolicy`), and the writer stamps the claim before it is persisted. No caller hardcodes
the boundary; the claim store stays config-free (it just persists the stamped fields and scopes
reads through :class:`~clue_research.claimstore.TenantScope`).

The classifier is the *write*-side seam; the read-side isolation is the tenant-scoped claim read
(M1's ``current_value`` + ``TenantScope``). Together they make "a private claim is never returned to
another tenant" a property of the data model, not a caller's discipline.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    DEFAULT_MERGE_POLICY,
    MergePolicy,
    TenantScope,
    claims_for,
    current_value,
)
from clue_research.core import Claim, CurrentValue, EntityId, ExtractionMethod, ReuseScope
from clue_research.identity.policy import DEFAULT_REUSE_POLICY, ReusePolicy


def classify_reuse_scope(
    field_key: str,
    extraction_method: ExtractionMethod,
    source_tier: int,
    policy: ReusePolicy = DEFAULT_REUSE_POLICY,
) -> ReuseScope:
    """Classify a claim's reuse scope from policy (the single decision point).

    ``source_tier`` is part of the signature for forward policy extension (e.g. a vertical that
    treats a tier as private), though the default rules key on method + namespace only.
    """
    if not policy.enabled:
        return ReuseScope.TENANT_PRIVATE  # reuse disabled → everything private (safe degradation)
    if extraction_method.value in policy.tenant_private_methods:
        return ReuseScope.TENANT_PRIVATE
    if any(field_key.startswith(prefix) for prefix in policy.tenant_private_prefixes):
        return ReuseScope.TENANT_PRIVATE
    return ReuseScope.PUBLIC_FOOTPRINT


def stamp_reuse(
    claim: Claim, *, tenant_id: str, policy: ReusePolicy = DEFAULT_REUSE_POLICY
) -> Claim:
    """Return a copy of ``claim`` with its ``reuse_scope`` classified and ``tenant_id`` set
    accordingly — the helper every writer (resolver, scorer, synthesizer) calls before
    :func:`insert_claim`. A public-footprint claim drops the tenant (it amortizes across clients); a
    tenant-private claim binds to ``tenant_id`` (which is therefore required for the private case).
    """
    scope = classify_reuse_scope(
        claim.field_key, claim.extraction_method, claim.source_tier, policy
    )
    if scope is ReuseScope.TENANT_PRIVATE:
        return claim.model_copy(update={"reuse_scope": scope, "tenant_id": tenant_id})
    return claim.model_copy(update={"reuse_scope": scope, "tenant_id": None})


async def reusable_public_value(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: str,
    *,
    policy: MergePolicy = DEFAULT_MERGE_POLICY,
) -> CurrentValue | None:
    """The current **public-footprint** truth for a field, if any — the amortization hook (M2.5).

    A resolver (M4) checks this before spending: if a fresh public-footprint claim already satisfies
    the field (``freshness_state == FRESH``), it reuses it instead of re-fetching — the "cheaper per
    account as more clients touch the same entity" payoff. Returns ``None`` when no public claim
    exists (the resolver must then fetch).
    """
    return await current_value(
        conn, entity_id, field_key, scope=TenantScope.public_only(), policy=policy
    )


async def dsar_private_claims(conn: AsyncConnection, entity_id: EntityId) -> Sequence[Claim]:
    """The DSAR/erasure selector: exactly the tenant-private claims for an entity (the data
    subject's set), leaving shared non-personal company facts intact (Doc D §4). M2.5 ships it; the
    actual tombstoning is M10.5. Includes superseded rows — erasure must reach the full history."""
    return await claims_for(
        conn, entity_id, include_superseded=True, scope=TenantScope.private_only()
    )
