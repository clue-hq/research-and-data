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

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.settings import Settings, load_settings
from clue_core import (
    DEFAULT_NUMERIC_ABS_TOLERANCE,
    DEFAULT_NUMERIC_REL_TOLERANCE,
    DEFAULT_SEMANTIC_JACCARD_THRESHOLD,
    Claim,
    ClaimFlavor,
    ClaimId,
    CurrentValue,
    EntityId,
    EntityType,
    EqualityMode,
    FreshnessState,
    IdentityBinding,
    VerificationStatus,
    WinningProvenance,
    reference_time,
    values_agree,
)
from clue_core.field import FieldKey
from clue_research.claimstore.claims import (
    _SELECT_COLUMNS,
    _quality_eligible_sql,
    _retention_eligible_sql,
    _row_to_claim,
)
from clue_research.claimstore.registry import FieldRegistryScope, get_effective_field
from clue_research.claimstore.tenancy import WorkspaceScope

# ``EqualityMode`` / ``values_agree`` come from ``core`` (the substrate's one equality contract):
# the merge's conflict / distinctness check and the M9.2 corroborator's grouping share them, so
# "same value" is decided identically on both surfaces under the field's ``equality_mode`` (DRY).
# ``canonical_json`` likewise moved to ``core``; it is re-exported by ``claimstore`` (the package).


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
    # Equality tolerances for the mode-aware conflict check (default from the shared core constants
    # so they stay aligned with the M9.2 corroborator — a no-DB drift guard asserts it). Used only
    # when the field declares a NUMERIC_TOL / SEMANTIC ``equality_mode``; EXACT ignores them.
    numeric_rel_tolerance: float = DEFAULT_NUMERIC_REL_TOLERANCE
    numeric_abs_tolerance: float = DEFAULT_NUMERIC_ABS_TOLERANCE
    semantic_jaccard_threshold: float = DEFAULT_SEMANTIC_JACCARD_THRESHOLD


DEFAULT_MERGE_POLICY = MergePolicy()

# The one deviation disabled-mode verification makes to the read side (FI-M12 toggle compat §3-B):
# the tier-4 verified-only gate drops; REJECTED and weak-binding exclusions stay on in both modes
# (identity protection is not verification), and there is still no unpromotable fallback.
_VERIFICATION_DISABLED_MERGE_POLICY = MergePolicy(require_verified_tier4=False)


def active_merge_policy(settings: Settings | None = None) -> MergePolicy:
    """The effective default merge policy for production reads (FI-M12 toggle compat §3-B).

    ``require_verified_tier4`` follows the temporary runtime verification toggle
    (``CLUE_VERIFICATION_ENABLED``): with verification disabled the M9.3 judge never runs, so no
    tier-4 claim can ever become VERIFIED and the verified-only gate would blank the whole tier-4
    layer (M11 synthesis, the M12 narrative). Disabled mode therefore serves unverified tier-4
    claims as current truth — globally, founder-ratified — with the claim's durable
    ``verification_status ≠ VERIFIED`` remaining the queryable marker of its basis. The default
    (enabled) returns :data:`DEFAULT_MERGE_POLICY` unchanged, preserving every existing behavior.

    Every defaulted claimstore read resolves through this accessor, so all call sites flip
    together; a caller that passes an explicit :class:`MergePolicy` is untouched. (This bypasses
    the dormant ``clue_config.schema.MergePolicy`` seam — acknowledged debt riding the existing
    [M9.2×M0.4] backlog item.)
    """
    resolved = settings if settings is not None else load_settings()
    if resolved.verification_enabled:
        return DEFAULT_MERGE_POLICY
    return _VERIFICATION_DISABLED_MERGE_POLICY


def _is_fresh(claim: Claim, freshness_ttl: timedelta | None, now: datetime) -> bool:
    """Whether ``claim`` is within its field's TTL (measured from the shared
    :func:`clue_core.reference_time` — observed, else collected — M9.5 DRY consolidation, so the
    merge view and the freshness engine can never disagree on a claim's age). No TTL declared ⇒
    always fresh."""
    if freshness_ttl is None:
        return True
    return (now - reference_time(claim)) <= freshness_ttl


def _is_eligible(claim: Claim, policy: MergePolicy) -> bool:
    """Whether a claim may *win* the merge (be emitted as current truth)."""
    # Discovery-provenance claims record where/why an entity was admitted — admission evidence, not
    # a field value — so they are never the "current truth" of a field (staged-flow §9).
    if claim.claim_flavor is not ClaimFlavor.FIELD_CLAIM:
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


def _conflict(
    live: Sequence[Claim], policy: MergePolicy, equality_mode: EqualityMode
) -> tuple[bool, tuple[ClaimId, ...]]:
    """Conflict flag + the disagreeing contender ids: two non-superseded tier≤threshold claims that
    *disagree* under the field's ``equality_mode`` (substrate §1). A tier≤2 vs tier-4 disagreement
    is *not* a conflict.

    Contenders are drawn from the same population the *winner* is — only claims that pass
    :func:`_is_eligible` (the merge's "may be current truth" gate). A conflict is "two tier≤2
    *sources* disagree", so claims that can never be a field's truth — discovery-provenance
    (admission evidence) and weak-binding contact claims (someone else's fact) — must not count as
    disagreeing sources and raise a spurious flag (staged-flow §6/§9).

    Agreement is the shared :func:`core.values_agree` under the field's ``equality_mode`` — so a
    ``numeric_tol`` / ``semantic`` field's two authoritative sources that *agree* (headcount 1000 vs
    1024; "Snowflake" vs "uses Snowflake") no longer raise a spurious conflict. The merge now shares
    its **equality predicate** and **pairwise** detection with the M9.2 corroborator (a claim
    conflicts if it disagrees with *any* other contender, not by counting value-groups), so a
    non-transitive mode (960/1000/1040 at rel-tol 0.05, where 1000 bridges 960↔1040 yet 960 and 1040
    disagree) cannot mask a genuine conflict behind a bridging anchor; the agreeing middle value is
    not surfaced. For ``EXACT`` this is identical to the prior distinct-value check on the common
    two-source case.

    The two surfaces do NOT share the exact contender *population*: merge contenders come from
    :func:`_is_eligible` (which still admits a ``FLAGGED`` tier≤2 claim), whereas the corroborator's
    ``_is_authoritative`` additionally excludes ``FLAGGED``. The divergence is intentional and safe
    (merge over-flags toward review); ``conflict_flag`` — the FLAGGED-excluding, mode-aware signal —
    is what M13.1 consumes, not ``CurrentValue.conflict``."""
    contenders = sorted(
        (
            c
            for c in live
            if _is_eligible(c, policy) and c.source_tier <= policy.conflict_tier_threshold
        ),
        key=lambda c: (c.source_tier, c.collected_at.timestamp(), str(c.id)),
    )
    conflicting = tuple(
        c.id
        for c in contenders
        if any(
            o.id != c.id
            and not values_agree(
                c.value_json,
                o.value_json,
                mode=equality_mode,
                numeric_rel_tolerance=policy.numeric_rel_tolerance,
                numeric_abs_tolerance=policy.numeric_abs_tolerance,
                semantic_jaccard_threshold=policy.semantic_jaccard_threshold,
            )
            for o in contenders
        )
    )
    return bool(conflicting), conflicting


def _build(
    winner: Claim,
    live: Sequence[Claim],
    policy: MergePolicy,
    equality_mode: EqualityMode,
    *,
    fresh: bool,
    flagged: bool,
) -> CurrentValue:
    conflict, conflicting_ids = _conflict(live, policy, equality_mode)
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
    equality_mode: EqualityMode = EqualityMode.EXACT,
) -> CurrentValue | None:
    """The pure deterministic merge for one ``(entity, field)``.

    Returns the current truth, or ``None`` when no eligible claim exists (an empty field is a
    correct output — conventions §5; the un-promotable claim, if any, stays visible via
    :func:`claims_for` for review). This function is DB-free and fully unit-testable.

    ``equality_mode`` is the field's declared agreement mode (``field_definition.equality_mode``),
    threaded the same way ``freshness_ttl`` is — a param read from the registry at the seam, kept
    off the pure function. It governs the conflict check only (the winner ranking is
    value-agnostic); defaulting to ``EXACT`` keeps every pure caller's behaviour unchanged.
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
            winner,
            live,
            policy,
            equality_mode,
            fresh=_is_fresh(winner, freshness_ttl, now),
            flagged=True,
        )

    if policy.freshness_mode is FreshnessMode.TTL_GATES_ELIGIBILITY:
        fresh_claims = [c for c in eligible if _is_fresh(c, freshness_ttl, now)]
        pool = fresh_claims or eligible  # stale fallback — never drop stale from the readable set
    else:  # TRUST_FIRST
        pool = eligible

    winner = _winner(pool)
    return _build(
        winner,
        live,
        policy,
        equality_mode,
        fresh=_is_fresh(winner, freshness_ttl, now),
        flagged=False,
    )


# --- DB readers (the seam) --------------------------------------------------
def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_mode(raw: object) -> EqualityMode:
    """Map the ``field_definition.equality_mode`` DB string to the enum (defaulting to ``EXACT`` for
    a NULL / absent / unrecognised value — the safe over-flagging direction)."""
    if not isinstance(raw, str):
        return EqualityMode.EXACT
    try:
        return EqualityMode(raw)
    except ValueError:
        return EqualityMode.EXACT


async def _freshness_ttl(
    conn: AsyncConnection, field_key: str, *, workspace_id: str | None
) -> tuple[timedelta | None, EqualityMode]:
    """The field's freshness TTL **and** equality mode (one read of the two merge-config columns,
    keeping the ``field_definition`` SQL in the merge seam — as the registry's
    ``get_corroboration_config`` does for the corroboration columns)."""
    definition = await get_effective_field(
        conn,
        scope=(
            FieldRegistryScope.for_workspace(workspace_id)
            if workspace_id is not None
            else FieldRegistryScope.global_only()
        ),
        field_key=field_key,
    )
    if definition is None:
        return None, EqualityMode.EXACT
    return definition.field_def.freshness_ttl, _coerce_mode(definition.equality_mode)


async def _freshness_ttls(
    conn: AsyncConnection, field_keys: Sequence[str], *, workspace_id: str | None
) -> dict[str, tuple[timedelta | None, EqualityMode]]:
    local_sql = ""
    params: dict[str, object] = {"fkeys": list(field_keys)}
    if workspace_id is not None:
        local_sql = """
            UNION ALL
            SELECT w.field_key, w.freshness_ttl, w.equality_mode
            FROM workspace_field_definition w
            LEFT JOIN workspace_field_retirement r
              ON r.workspace_id = w.workspace_id AND r.field_key = w.field_key
            WHERE w.workspace_id = :registry_workspace
              AND w.field_key IN :fkeys
              AND w.active
              AND r.field_key IS NULL
        """
        params["registry_workspace"] = workspace_id
    stmt = text(
        "SELECT field_key, freshness_ttl, equality_mode "
        "FROM field_definition WHERE field_key IN :fkeys " + local_sql
    ).bindparams(bindparam("fkeys", expanding=True))
    rows = await conn.execute(stmt, params)
    meta: dict[str, tuple[timedelta | None, EqualityMode]] = {}
    for field_key, ttl, mode in rows.all():
        meta[field_key] = (ttl, _coerce_mode(mode))
    return meta


async def current_value(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: FieldKey | str,
    *,
    scope: WorkspaceScope,
    policy: MergePolicy | None = None,
) -> CurrentValue | None:
    """The current truth for one ``(entity, field)``, or ``None`` if there is no eligible claim.

    ``policy=None`` (the production default) resolves to :func:`active_merge_policy` — the
    verification-toggle-aware effective default; pass an explicit policy to pin behavior.

    ``scope`` is **required** (M2.5 — fail-closed): the caller must state whose view this is — a
    workspace (:meth:`WorkspaceScope.for_workspace`, returning public ∪ that workspace's private),
    the shared
    public base (:meth:`WorkspaceScope.public_only`), or the operator
    (``WorkspaceScope.all_workspaces``).
    A tenant scope never returns another tenant's private claim.
    """
    if policy is None:
        policy = active_merge_policy()
    now = _now()
    scope_sql, scope_params = scope.predicate()
    retention_sql = _retention_eligible_sql()
    rows = (
        await conn.execute(
            text(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM claim
                WHERE entity_id = :entity_id
                  AND field_key = :field_key
                  AND superseded_by IS NULL
                  AND {retention_sql} AND {_quality_eligible_sql()}
                  AND {scope_sql}
                ORDER BY collected_at DESC, id
                """
            ),
            {
                "entity_id": entity_id,
                "field_key": field_key,
                "retention_at": now,
                **scope_params,
            },
        )
    ).mappings()
    claims = [_row_to_claim(dict(row)) for row in rows.all()]
    ttl, equality_mode = await _freshness_ttl(conn, str(field_key), workspace_id=scope.workspace_id)
    return merge_claims(claims, ttl, policy, now, equality_mode)


async def current_values(
    conn: AsyncConnection,
    entity_ids: Iterable[EntityId],
    field_keys: Iterable[FieldKey | str],
    *,
    scope: WorkspaceScope,
    policy: MergePolicy | None = None,
) -> dict[tuple[EntityId, str], CurrentValue]:
    """Batch merge over the ``entity_ids × field_keys`` cross-product in a single live-claims query.

    Returns a dict keyed by ``(entity_id, field_key)`` containing only the pairs with a current
    truth — identical to calling :func:`current_value` per pair (the empty pairs are omitted). One
    query for the claims and one for the TTLs, so it scales to Pass A's 1k–10k accounts. ``scope``
    is required and applied in the live-claims query (M2.5). ``policy=None`` resolves to
    :func:`active_merge_policy` (the toggle-aware effective default).
    """
    if policy is None:
        policy = active_merge_policy()
    entities = list(entity_ids)
    fields = [str(f) for f in field_keys]
    if not entities or not fields:
        return {}

    now = _now()
    scope_sql, scope_params = scope.predicate()
    retention_sql = _retention_eligible_sql()
    stmt = text(
        f"""
        SELECT {_SELECT_COLUMNS} FROM claim
        WHERE entity_id IN :eids AND field_key IN :fkeys AND superseded_by IS NULL
          AND {retention_sql} AND {_quality_eligible_sql()}
          AND {scope_sql}
        """
    ).bindparams(bindparam("eids", expanding=True), bindparam("fkeys", expanding=True))
    rows = (
        (
            await conn.execute(
                stmt,
                {
                    "eids": entities,
                    "fkeys": fields,
                    "retention_at": now,
                    **scope_params,
                },
            )
        )
        .mappings()
        .all()
    )

    grouped: dict[tuple[EntityId, str], list[Claim]] = defaultdict(list)
    for row in rows:
        claim = _row_to_claim(dict(row))
        grouped[(EntityId(row["entity_id"]), row["field_key"])].append(claim)

    meta = await _freshness_ttls(conn, fields, workspace_id=scope.workspace_id)
    result: dict[tuple[EntityId, str], CurrentValue] = {}
    for (entity_id, field_key), claim_list in grouped.items():
        ttl, equality_mode = meta.get(field_key, (None, EqualityMode.EXACT))
        merged = merge_claims(claim_list, ttl, policy, now, equality_mode)
        if merged is not None:
            result[(entity_id, field_key)] = merged
    return result


async def provenance_index(
    conn: AsyncConnection,
    entity_id: EntityId,
    *,
    scope: WorkspaceScope,
    policy: MergePolicy | None = None,
) -> dict[str, WinningProvenance]:
    """The winning provenance per field for an entity — ``{field_key: winning_provenance}``
    (overview §3). Present for every field with at least one eligible claim; absent otherwise.
    ``scope`` is required and applied to both the field discovery and the merge (M2.5);
    ``policy=None`` resolves to :func:`active_merge_policy` (delegated to ``current_values``)."""
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
