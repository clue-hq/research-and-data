"""``current_value`` — the deterministic merge policy, the "current truth" everything reads (M1.2).

Merge is a **pure policy over source tiers, not an agent** (substrate §1). This is the direct fix
for the prototype's worst bug ("bad base facts never overwritten"): a tier-4 synthesized value can
never outrank a tier-1–3 fact, conflicts between authoritative sources surface as a *flag* for
review instead of being silently resolved, and staleness is queryable. Everything that consumes
"the value of field X for entity Y" — Pass A scoring (M6), deep-profiling gap detection (M8), the
handoff ``provenance_index`` (M12), the review surface (M13) — reads through this seam and nothing
else, so the merge algorithm can evolve without touching callers.

Tier ranking: source tiers run 1 (deterministic API, *most* trusted) → 4 (LLM synthesis, *least*).
Substrate §1's "highest source_tier" means highest **trust** = numerically **lowest** tier (the
tier table where 1 is most trusted; a tier-4 value must never outrank a tier-1 fact). So the winner
is the lowest-tier eligible claim, tie-broken by corroborations desc → confidence desc →
collected_at desc.

**Why a Python merge, not a SQL view.** The spec allows "a view *or* a table-valued function" and
requires the policy to be *versioned config, not hardcoded* (conventions §2 — policy is data) and
the implementation to stay behind a function seam so it can later become a materialized view or an
incremental merge service. A frozen SQL view cannot carry swappable policy; so the merge is a pure
function (:func:`merge_claims`) reading a :class:`MergePolicy`, fed by a thin *indexed* live-claims
fetch (the M1.1 ``claim_live_entity_field`` partial index). :func:`current_value` /
:func:`current_values` are the seam; the algorithm is fully hidden behind them.

The under-specified freshness question (substrate §1 "highest tier *that satisfies* the TTL" vs §6
"stale claims are not dropped, just discountable") is resolved as **documented, versioned policy**
(D7), not scattered code: see :class:`FreshnessMode`. The default never drops a stale claim from the
readable set — a stale winner is returned with ``freshness_state='stale'``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore.claims import _SELECT_COLUMNS, _row_to_claim, claims_for
from clue_research.claimstore.tenancy import TenantScope
from clue_research.core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    CurrentValue,
    EntityId,
    EntityType,
    FreshnessState,
    IdentityBinding,
    VerificationStatus,
    WinningProvenance,
)
from clue_research.core.field import FieldKey


class FreshnessMode(StrEnum):
    """How the field-level freshness TTL participates in winner selection (the D7 decision).

    * ``TTL_GATES_ELIGIBILITY`` (default) — substrate §1's literal reading: among eligible claims,
      *fresh* ones win; a stale claim wins only as a fallback when no fresh claim exists (and is
      then flagged ``stale``). So a fresh lower-trust claim beats a stale higher-trust one.
    * ``TRUST_FIRST`` — the highest-trust eligible claim wins even if stale (flagged ``stale``);
      freshness only discounts downstream. So a stale higher-trust claim beats a fresh lower-trust
      one.

    Neither §1 nor §6 states the edge case outright, so it is config, not a hardcoded default; a
    caller flips ``MergePolicy.freshness_mode`` without any code change.
    """

    TTL_GATES_ELIGIBILITY = "ttl_gates_eligibility"
    TRUST_FIRST = "trust_first"


class MergePolicy(BaseModel):
    """Versioned merge-policy data (conventions §2 — policy is data, not code). Swapping a rule
    (freshness mode, conflict scope, tier-4 / weak-binding handling) is a config edit, not a fork.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    freshness_mode: FreshnessMode = FreshnessMode.TTL_GATES_ELIGIBILITY
    conflict_tier_threshold: int = 2  # only tier <= this raises a conflict (substrate §1)
    require_verified_tier4: bool = True  # an unverified tier-4 claim never wins (M1.2 default)
    exclude_weak_binding: bool = True  # a weak-binding contact claim never wins (M1.4 / staged §6)
    exclude_rejected: bool = True  # a rejected claim never wins
    fallback_to_unpromotable: bool = False  # if set, return the best un-promotable claim, flagged


DEFAULT_MERGE_POLICY = MergePolicy()


def canonical_json(value: JsonValue) -> str:
    """A canonical string for value equality / distinctness (order-independent for objects).

    The one place exact ``value_json`` equality is decided in the substrate — the merge layer's
    conflict/distinctness check and the M9.2 corroborator's exact-equality mode both call this, so
    "same value" means the same thing on both surfaces (it is NOT
    :func:`core.serialize_value_json`, whose Pydantic dump does not sort object keys)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _reference_time(claim: Claim) -> datetime:
    """Time a claim's freshness is measured from: when the source was observed, else collected."""
    return claim.observed_at or claim.collected_at


def _is_fresh(claim: Claim, freshness_ttl: timedelta | None, now: datetime) -> bool:
    """Whether ``claim`` is within its field's TTL. No TTL declared ⇒ always fresh."""
    if freshness_ttl is None:
        return True
    return (now - _reference_time(claim)) <= freshness_ttl


def _is_eligible(claim: Claim, policy: MergePolicy) -> bool:
    """Whether a claim may *win* the merge (be emitted as current truth)."""
    # Discovery-provenance claims record where/why an entity was admitted — admission evidence, not
    # a field value — so they are never the "current truth" of a field (staged-flow §9).
    if claim.claim_flavor is ClaimFlavor.DISCOVERY:
        return False
    if policy.exclude_rejected and claim.verification_status is VerificationStatus.REJECTED:
        return False
    if (
        policy.require_verified_tier4
        and claim.source_tier == 4
        and claim.verification_status is not VerificationStatus.VERIFIED
    ):
        return False
    return not (
        policy.exclude_weak_binding
        and claim.entity_type is EntityType.CONTACT
        and claim.identity_binding is IdentityBinding.WEAK
    )


def _winner(claims: Sequence[Claim]) -> Claim:
    """The most-trusted claim: lowest tier, then corroborations / confidence / recency desc."""
    return min(
        claims,
        key=lambda c: (
            c.source_tier,
            -c.corroborations,
            -c.confidence,
            -c.collected_at.timestamp(),
        ),
    )


def _conflict(live: Sequence[Claim], policy: MergePolicy) -> tuple[bool, tuple[ClaimId, ...]]:
    """Conflict flag + the disagreeing contender ids: two non-superseded tier≤threshold claims with
    different values (substrate §1). A tier≤2 vs tier-4 disagreement is *not* a conflict.

    Contenders are drawn from the same population the *winner* is — only claims that pass
    :func:`_is_eligible` (the merge's "may be current truth" gate). A conflict is "two tier≤2
    *sources* disagree", so claims that can never be a field's truth — discovery-provenance
    (admission evidence) and weak-binding contact claims (someone else's fact) — must not count as
    disagreeing sources and raise a spurious flag (staged-flow §6/§9)."""
    contenders = [
        c
        for c in live
        if _is_eligible(c, policy) and c.source_tier <= policy.conflict_tier_threshold
    ]
    representative: dict[str, ClaimId] = {}
    for claim in sorted(contenders, key=lambda c: (c.source_tier, c.collected_at.timestamp())):
        representative.setdefault(canonical_json(claim.value_json), claim.id)
    if len(representative) >= 2:
        return True, tuple(representative.values())
    return False, ()


def _build(
    winner: Claim, live: Sequence[Claim], policy: MergePolicy, *, fresh: bool, flagged: bool
) -> CurrentValue:
    conflict, conflicting_ids = _conflict(live, policy)
    return CurrentValue(
        entity_id=winner.entity_id,
        field_key=winner.field_key,
        value_json=winner.value_json,
        provenance=WinningProvenance(
            claim_id=winner.id,
            source_url=winner.source_url,
            source_tier=winner.source_tier,
            evidence_span=winner.evidence_span,
            confidence=winner.confidence,
            collected_at=winner.collected_at,
            corroborations=winner.corroborations,
        ),
        freshness_state=FreshnessState.FRESH if fresh else FreshnessState.STALE,
        conflict=conflict or flagged,
        conflicting_claim_ids=conflicting_ids,
    )


def merge_claims(
    claims: Sequence[Claim],
    freshness_ttl: timedelta | None,
    policy: MergePolicy,
    now: datetime,
) -> CurrentValue | None:
    """The pure deterministic merge for one ``(entity, field)``.

    Returns the current truth, or ``None`` when no eligible claim exists (an empty field is a
    correct output — conventions §5; the un-promotable claim, if any, stays visible via
    :func:`claims_for` for review). This function is DB-free and fully unit-testable.
    """
    live = [c for c in claims if c.superseded_by is None]
    eligible = [c for c in live if _is_eligible(c, policy)]

    if not eligible:
        if not policy.fallback_to_unpromotable:
            return None  # empty + (implicitly) flagged: never emit untrusted data as truth
        pool = [
            c
            for c in live
            if not (
                policy.exclude_rejected and c.verification_status is VerificationStatus.REJECTED
            )
        ]
        if not pool:
            return None
        winner = _winner(pool)
        return _build(
            winner, live, policy, fresh=_is_fresh(winner, freshness_ttl, now), flagged=True
        )

    if policy.freshness_mode is FreshnessMode.TTL_GATES_ELIGIBILITY:
        fresh_claims = [c for c in eligible if _is_fresh(c, freshness_ttl, now)]
        pool = fresh_claims or eligible  # stale fallback — never drop stale from the readable set
    else:  # TRUST_FIRST
        pool = eligible

    winner = _winner(pool)
    return _build(winner, live, policy, fresh=_is_fresh(winner, freshness_ttl, now), flagged=False)


# --- DB readers (the seam) --------------------------------------------------
def _now() -> datetime:
    return datetime.now(UTC)


async def _freshness_ttl(conn: AsyncConnection, field_key: str) -> timedelta | None:
    row = await conn.execute(
        text("SELECT freshness_ttl FROM field_definition WHERE field_key = :k"),
        {"k": field_key},
    )
    found = row.first()
    return found[0] if found is not None else None


async def _freshness_ttls(
    conn: AsyncConnection, field_keys: Sequence[str]
) -> dict[str, timedelta | None]:
    stmt = text(
        "SELECT field_key, freshness_ttl FROM field_definition WHERE field_key IN :fkeys"
    ).bindparams(bindparam("fkeys", expanding=True))
    rows = await conn.execute(stmt, {"fkeys": list(field_keys)})
    ttls: dict[str, timedelta | None] = {}
    for field_key, ttl in rows.all():
        ttls[field_key] = ttl
    return ttls


async def current_value(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: FieldKey | str,
    *,
    scope: TenantScope,
    policy: MergePolicy = DEFAULT_MERGE_POLICY,
) -> CurrentValue | None:
    """The current truth for one ``(entity, field)``, or ``None`` if there is no eligible claim.

    ``scope`` is **required** (M2.5 — fail-closed): the caller must state whose view this is — a
    tenant (:meth:`TenantScope.for_tenant`, returning public ∪ that tenant's private), the shared
    public base (:meth:`TenantScope.public_only`), or the operator (``TenantScope.all_tenants``).
    A tenant scope never returns another tenant's private claim.
    """
    claims = await claims_for(conn, entity_id, field_key, scope=scope)
    ttl = await _freshness_ttl(conn, str(field_key))
    return merge_claims(list(claims), ttl, policy, _now())


async def current_values(
    conn: AsyncConnection,
    entity_ids: Iterable[EntityId],
    field_keys: Iterable[FieldKey | str],
    *,
    scope: TenantScope,
    policy: MergePolicy = DEFAULT_MERGE_POLICY,
) -> dict[tuple[EntityId, str], CurrentValue]:
    """Batch merge over the ``entity_ids × field_keys`` cross-product in a single live-claims query.

    Returns a dict keyed by ``(entity_id, field_key)`` containing only the pairs with a current
    truth — identical to calling :func:`current_value` per pair (the empty pairs are omitted). One
    query for the claims and one for the TTLs, so it scales to Pass A's 1k–10k accounts. ``scope``
    is required and applied in the live-claims query (M2.5).
    """
    entities = list(entity_ids)
    fields = [str(f) for f in field_keys]
    if not entities or not fields:
        return {}

    scope_sql, scope_params = scope.predicate()
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS} FROM claim
        WHERE entity_id IN :eids AND field_key IN :fkeys AND superseded_by IS NULL
          AND {scope_sql}
        """
    ).bindparams(bindparam("eids", expanding=True), bindparam("fkeys", expanding=True))
    rows = (
        (await conn.execute(stmt, {"eids": entities, "fkeys": fields, **scope_params}))
        .mappings()
        .all()
    )

    grouped: dict[tuple[EntityId, str], list[Claim]] = defaultdict(list)
    for row in rows:
        claim = _row_to_claim(dict(row))
        grouped[(EntityId(row["entity_id"]), row["field_key"])].append(claim)

    ttls = await _freshness_ttls(conn, fields)
    now = _now()
    result: dict[tuple[EntityId, str], CurrentValue] = {}
    for (entity_id, field_key), claim_list in grouped.items():
        merged = merge_claims(claim_list, ttls.get(field_key), policy, now)
        if merged is not None:
            result[(entity_id, field_key)] = merged
    return result


async def provenance_index(
    conn: AsyncConnection,
    entity_id: EntityId,
    *,
    scope: TenantScope,
    policy: MergePolicy = DEFAULT_MERGE_POLICY,
) -> dict[str, WinningProvenance]:
    """The winning provenance per field for an entity — ``{field_key: winning_provenance}``
    (overview §3). Present for every field with at least one eligible claim; absent otherwise.
    ``scope`` is required and applied to both the field discovery and the merge (M2.5)."""
    scope_sql, scope_params = scope.predicate()
    field_rows = await conn.execute(
        text(
            "SELECT DISTINCT field_key FROM claim "
            f"WHERE entity_id = :e AND superseded_by IS NULL AND {scope_sql}"
        ),
        {"e": entity_id, **scope_params},
    )
    fields = list(field_rows.scalars().all())
    if not fields:
        return {}
    merged = await current_values(conn, [entity_id], fields, scope=scope, policy=policy)
    return {field_key: cv.provenance for (_entity, field_key), cv in merged.items()}
