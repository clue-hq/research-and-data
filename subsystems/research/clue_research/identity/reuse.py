"""Cross-tenant reuse classification + the isolation helpers (M2.5).

Realize the architecture's moat safely (substrate §2): public-footprint claims about a company
amortize across clients; client-specific scoring and any client-private data stay strictly
tenant-isolated. This module is the **single point that decides reuse** — the classifier maps
``(field_key, extraction_method, source_tier) → reuse_scope`` from versioned policy
(:class:`ReusePolicy`), and the writer stamps the claim before it is persisted. No caller hardcodes
the boundary; the claim store stays config-free (it just persists the stamped fields and scopes
reads through :class:`~clue_research.claimstore.WorkspaceScope`).

The classifier is the *write*-side seam; the read-side isolation is the tenant-scoped claim read
(M1's ``current_value`` + ``WorkspaceScope``). Together they make "a private claim is never returned
to
another tenant" a property of the data model, not a caller's discipline.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Claim, CurrentValue, EntityId, ExtractionMethod, ReuseScope
from clue_research.claimstore import (
    DEFAULT_MERGE_POLICY,
    MergePolicy,
    WorkspaceScope,
    claims_for,
    current_value,
)
from clue_research.identity.policy import DEFAULT_REUSE_POLICY, ReusePolicy


def classify_reuse_scope(
    field_key: str,
    extraction_method: ExtractionMethod,
    source_tier: int,
    policy: ReusePolicy = DEFAULT_REUSE_POLICY,
    *,
    declared_scope: ReuseScope | None = None,
) -> ReuseScope:
    """Classify a claim's reuse scope from policy (the single decision point).

    ``source_tier`` is part of the signature for forward policy extension (e.g. a vertical that
    treats a tier as private), though the default rules key on method + namespace only.

    ``declared_scope`` is the field's *declared* reuse class (``FieldDef.reuse_scope`` /
    ``field_definition.reuse_scope``, M2.5/ENG-165 W1): the classifier consults it **before** the
    namespace-prefix heuristic, so a registered field's declaration is authoritative and the
    ``<pack>.*`` default-public gap is closed (a pack field declared private classifies private even
    though no prefix names it). Precedence, most-private-wins on the source axis:
    ``enabled=False`` (safe degradation) → a tenant-private *method* (``crm_import`` data is the
    client's regardless of the field) → the field's ``declared_scope`` (wins over the prefix) → the
    prefix heuristic (fallback when undeclared) → public.
    """
    if not policy.enabled:
        return ReuseScope.TENANT_PRIVATE  # reuse disabled → everything private (safe degradation)
    if extraction_method.value in policy.tenant_private_methods:
        return ReuseScope.TENANT_PRIVATE  # the source makes this claim client-private
    if declared_scope is not None:
        return declared_scope  # declared at the field — authoritative over the prefix heuristic
    if any(field_key.startswith(prefix) for prefix in policy.tenant_private_prefixes):
        return ReuseScope.TENANT_PRIVATE
    return ReuseScope.PUBLIC_FOOTPRINT


def stamp_reuse(
    claim: Claim, *, workspace_id: str | None, policy: ReusePolicy = DEFAULT_REUSE_POLICY
) -> Claim:
    """Return a copy of ``claim`` with its ``reuse_scope`` classified and ``workspace_id`` set
    accordingly — the helper every writer (resolver, scorer, synthesizer) calls before
    :func:`insert_claim`. A public-footprint claim drops the tenant (it amortizes across clients); a
    tenant-private claim binds to ``workspace_id``.

    ``workspace_id`` is optional so a caller that may produce either flavor (the M4.1 waterfall,
    which
    stamps every written claim — locked decision #6) can pass its run tenant through verbatim. But a
    claim that *classifies* as ``tenant_private`` (CRM-imported, scoring, resonance, contact /
    personal) with **no** tenant supplied is a wiring error, not a public claim: stamping it public
    would leak client-private data into the shared pool. We **fail loud** rather than silently relax
    the scope — the boundary is fail-closed (substrate §2; the model/DB CHECK is the backstop, but a
    clear error at the write site beats a CHECK violation)."""
    scope = classify_reuse_scope(
        claim.field_key, claim.extraction_method, claim.source_tier, policy
    )
    if scope is ReuseScope.TENANT_PRIVATE:
        if workspace_id is None:
            raise ValueError(
                f"claim for field {claim.field_key!r} (extraction_method "
                f"{claim.extraction_method.value!r}) classifies as tenant_private, but no "
                "workspace_id was supplied to stamp_reuse; a client-private claim must bind to a "
                "workspace — supply the run's workspace_id (never silently written public, "
                "substrate §2)"
            )
        return claim.model_copy(update={"reuse_scope": scope, "workspace_id": workspace_id})
    return claim.model_copy(update={"reuse_scope": scope, "workspace_id": None})


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
        conn, entity_id, field_key, scope=WorkspaceScope.public_only(), policy=policy
    )


async def dsar_private_claims(
    conn: AsyncConnection, entity_id: EntityId, workspace_id: str
) -> Sequence[Claim]:
    """The DSAR/erasure selector: exactly **this tenant's** tenant-private claims for an entity (the
    data subject's set for one controller), leaving shared non-personal company facts — and *other*
    tenants' private claims — intact (Doc D §4). A DSAR is always scoped to the requesting tenant;
    ``workspace_id`` is required so the selector can never return another workspace's private data.
    M2.5
    ships the selector; the tombstoning is M10.5. Includes superseded rows — erasure reaches the
    full history."""
    return await claims_for(
        conn,
        entity_id,
        include_superseded=True,
        scope=WorkspaceScope.private_for_workspace(workspace_id),
    )
