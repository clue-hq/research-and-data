"""Claimstore-owned current selection for C7 production research views."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimFlavor,
    CurrentValue,
    EntityId,
    EqualityMode,
    VerificationStatus,
)
from clue_research.claimstore.claims import (
    _SELECT_COLUMNS,
    _retention_eligible_sql,
    _row_to_claim,
)
from clue_research.claimstore.merge import MergePolicy, active_merge_policy, merge_claims
from clue_research.claimstore.research_view_routes import ResearchViewFieldRoute
from clue_research.claimstore.tenancy import WorkspaceScope


@dataclass(frozen=True)
class ResolvedCurrentClaim:
    """One routed winning field claim plus the merge state that selected it."""

    route: ResearchViewFieldRoute
    claim: Claim
    current: CurrentValue


def _coerce_mode(raw: object) -> EqualityMode:
    try:
        return EqualityMode(str(raw))
    except ValueError:
        return EqualityMode.EXACT


def _product_pool(
    claims: Sequence[Claim],
    *,
    product_mode: str,
    product_id: str | None,
) -> list[Claim]:
    neutral = [claim for claim in claims if claim.product_id is None]
    if product_mode == "neutral_only":
        return neutral
    if product_mode == "exact_required":
        return (
            [claim for claim in claims if claim.product_id == product_id]
            if product_id is not None
            else []
        )
    if product_id is None:
        return neutral
    exact = [claim for claim in claims if claim.product_id == product_id]
    # Product-specific truth outranks neutral truth before normal merge ranking. If exact rows are
    # all unpromotable, merge returns None and the caller may safely fall back to neutral.
    return exact or neutral


async def _load_product_claims_and_metadata(
    conn: AsyncConnection,
    *,
    entity_ids: Sequence[EntityId],
    field_keys: Sequence[str],
    scope: WorkspaceScope,
    product_id: str | None,
) -> tuple[tuple[Claim, ...], dict[str, tuple[timedelta | None, EqualityMode]]]:
    """Load one retention-safe neutral/exact product candidate set and its field merge metadata."""

    entities = tuple(dict.fromkeys(entity_ids))
    fields = tuple(dict.fromkeys(field_keys))
    if not entities or not fields:
        return (), {}
    scope_sql, scope_params = scope.predicate()
    retention_sql = _retention_eligible_sql()
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM claim
        WHERE entity_id IN :entity_ids
          AND field_key IN :field_keys
          AND claim_flavor = 'field_claim'
          AND superseded_by IS NULL
          AND {retention_sql}
          AND {scope_sql}
          AND (product_id IS NULL OR product_id = :product_id)
        ORDER BY entity_id, field_key, collected_at DESC, id
        """
    ).bindparams(
        bindparam("entity_ids", expanding=True),
        bindparam("field_keys", expanding=True),
    )
    rows = (
        await conn.execute(
            stmt,
            {
                "entity_ids": list(entities),
                "field_keys": list(fields),
                "product_id": product_id,
                "retention_at": datetime.now(UTC),
                **scope_params,
            },
        )
    ).mappings()
    claims = tuple(_row_to_claim(dict(row)) for row in rows)
    meta_rows = (
        await conn.execute(
            text(
                "SELECT field_key, freshness_ttl, equality_mode "
                "FROM field_definition WHERE field_key IN :field_keys"
            ).bindparams(bindparam("field_keys", expanding=True)),
            {"field_keys": list(fields)},
        )
    ).all()
    metadata = {str(row[0]): (row[1], _coerce_mode(row[2])) for row in meta_rows}
    return claims, metadata


def _merge_product_candidates(
    claims: Sequence[Claim],
    *,
    product_mode: str,
    product_id: str | None,
    freshness_ttl: timedelta | None,
    equality_mode: EqualityMode,
    policy: MergePolicy,
    now: datetime,
) -> tuple[CurrentValue | None, list[Claim]]:
    pool = _product_pool(
        claims,
        product_mode=product_mode,
        product_id=product_id,
    )
    current = merge_claims(pool, freshness_ttl, policy, now, equality_mode)
    if current is None and product_mode == "neutral_or_exact" and product_id is not None:
        pool = [claim for claim in claims if claim.product_id is None]
        current = merge_claims(pool, freshness_ttl, policy, now, equality_mode)
    return current, pool


async def current_values_resolved_for_product(
    conn: AsyncConnection,
    *,
    entity_ids: Sequence[EntityId],
    field_keys: Sequence[str],
    scope: WorkspaceScope,
    product_id: str | None,
    policy: MergePolicy | None = None,
) -> dict[tuple[EntityId, str], CurrentValue]:
    """Resolve current neutral-or-exact truth without allowing another product to contend.

    Product-specific truth wins before normal merge ranking. Neutral truth is the fail-safe
    fallback when the requested product has no promotable candidate. The result is grouped per
    exact entity/field, unlike the canonical-member route reader which intentionally merges member
    identities into one routed subject. ``policy=None`` resolves to :func:`active_merge_policy`
    (the verification-toggle-aware effective default).
    """

    if policy is None:
        policy = active_merge_policy()
    claims, metadata = await _load_product_claims_and_metadata(
        conn,
        entity_ids=entity_ids,
        field_keys=field_keys,
        scope=scope,
        product_id=product_id,
    )
    grouped: dict[tuple[EntityId, str], list[Claim]] = defaultdict(list)
    for claim in claims:
        grouped[(claim.entity_id, str(claim.field_key))].append(claim)
    now = datetime.now(UTC)
    resolved: dict[tuple[EntityId, str], CurrentValue] = {}
    for key, candidates in grouped.items():
        ttl, equality = metadata.get(key[1], (None, EqualityMode.EXACT))
        current, _pool = _merge_product_candidates(
            candidates,
            product_mode="neutral_or_exact",
            product_id=product_id,
            freshness_ttl=ttl,
            equality_mode=equality,
            policy=policy,
            now=now,
        )
        if current is not None:
            resolved[key] = current
    return resolved


async def current_field_claims_resolved_for_product(
    conn: AsyncConnection,
    *,
    member_entity_ids: Sequence[EntityId],
    routes: Sequence[ResearchViewFieldRoute],
    scope: WorkspaceScope,
    product_id: str | None,
    allowed_run_ids: Sequence[str] = (),
    policy: MergePolicy | None = None,
) -> tuple[ResolvedCurrentClaim, ...]:
    """Select one current direct claim per explicit route after product filtering.

    ``policy=None`` resolves to :func:`active_merge_policy` (the toggle-aware effective default).
    """

    if policy is None:
        policy = active_merge_policy()
    members = tuple(dict.fromkeys(member_entity_ids))
    # Personalization-candidate routes are derived-only by contract; a raw fact can remain in its
    # semantic display section but can never become outreach copy merely because it is public.
    active_routes = tuple(route for route in routes if route.purpose == "display")
    fields = tuple(dict.fromkeys(route.field_key for route in active_routes))
    if not members or not fields:
        return ()
    claims, metadata = await _load_product_claims_and_metadata(
        conn,
        entity_ids=members,
        field_keys=fields,
        scope=scope,
        product_id=product_id,
    )
    grouped: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        grouped[str(claim.field_key)].append(claim)

    now = datetime.now(UTC)
    resolved: list[ResolvedCurrentClaim] = []
    for route in active_routes:
        route_claims = grouped.get(route.field_key, ())
        if route.context_scope == "project_run_pinned":
            route_claims = [
                claim
                for claim in route_claims
                if allowed_run_ids and str(claim.run_id) in allowed_run_ids
            ]
        ttl, equality = metadata.get(route.field_key, (None, EqualityMode.EXACT))
        current, pool = _merge_product_candidates(
            route_claims,
            product_mode=route.product_mode,
            product_id=product_id,
            freshness_ttl=ttl,
            equality_mode=equality,
            policy=policy,
            now=now,
        )
        if current is None:
            continue
        winner = next(
            (claim for claim in pool if claim.id == current.provenance.claim_id),
            None,
        )
        if winner is None:  # pragma: no cover - merge provenance always comes from its input
            raise RuntimeError("current claim merge returned an unknown winner")
        resolved.append(ResolvedCurrentClaim(route=route, claim=winner, current=current))
    return tuple(
        sorted(
            resolved,
            key=lambda item: (
                item.route.section_kind.value,
                item.route.ordinal,
                item.route.field_key,
                str(item.claim.id),
            ),
        )
    )


async def live_derived_claims_for_research_view(
    conn: AsyncConnection,
    *,
    member_entity_ids: Sequence[EntityId],
    routes: Sequence[ResearchViewFieldRoute],
    scope: WorkspaceScope,
    product_id: str | None,
    allowed_run_ids: Sequence[str] = (),
) -> tuple[tuple[ResearchViewFieldRoute, Claim], ...]:
    """List live routed derived roots under product/context policy in one query."""

    members = tuple(dict.fromkeys(member_entity_ids))
    routes_by_field: dict[str, list[ResearchViewFieldRoute]] = defaultdict(list)
    for route in routes:
        routes_by_field[route.field_key].append(route)
    if not members or not routes_by_field:
        return ()
    scope_sql, scope_params = scope.predicate()
    retention_sql = _retention_eligible_sql()
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM claim
        WHERE entity_id IN :entity_ids
          AND field_key IN :field_keys
          AND claim_flavor = 'derived'
          AND verification_status IN ('verified', 'flagged')
          AND superseded_by IS NULL
          AND {retention_sql}
          AND {scope_sql}
          AND (product_id IS NULL OR product_id = :product_id)
        ORDER BY field_key, collected_at DESC, id
        """
    ).bindparams(
        bindparam("entity_ids", expanding=True),
        bindparam("field_keys", expanding=True),
    )
    rows = (
        await conn.execute(
            stmt,
            {
                "entity_ids": list(members),
                "field_keys": list(routes_by_field),
                "product_id": product_id,
                "retention_at": datetime.now(UTC),
                **scope_params,
            },
        )
    ).mappings()
    by_field: dict[str, list[Claim]] = defaultdict(list)
    for row in rows:
        claim = _row_to_claim(dict(row))
        field_routes = routes_by_field[str(claim.field_key)]
        if (
            allowed_run_ids
            and any(route.context_scope == "project_run_pinned" for route in field_routes)
            and str(claim.run_id) not in allowed_run_ids
        ):
            continue
        by_field[str(claim.field_key)].append(claim)

    selected: list[tuple[ResearchViewFieldRoute, Claim]] = []
    for field_key, claims in by_field.items():
        for route in routes_by_field[field_key]:
            selected.extend(
                (route, claim)
                for claim in _product_pool(
                    claims,
                    product_mode=route.product_mode,
                    product_id=product_id,
                )
                if claim.claim_flavor is ClaimFlavor.DERIVED
                and claim.verification_status
                in {VerificationStatus.VERIFIED, VerificationStatus.FLAGGED}
            )
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                item[0].section_kind.value,
                item[0].ordinal,
                item[0].field_key,
                str(item[1].id),
            ),
        )
    )


__all__ = [
    "ResolvedCurrentClaim",
    "current_field_claims_resolved_for_product",
    "current_values_resolved_for_product",
    "live_derived_claims_for_research_view",
]
