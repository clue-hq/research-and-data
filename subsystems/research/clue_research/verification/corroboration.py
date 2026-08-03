"""M9.2 — corroboration rules: ≥N independent tier≤3 sources promote a claim (ENG-134).

Provenance (an evidence span) proves a single source *said* something; it does not prove the fact is
*true*. For fields that load-bear on scoring or content, the substrate requires **independent
corroboration** before a claim is promoted to ``verified`` (substrate §6(2)): ≥N independent tier≤3
sources agreeing, with conflicts between authoritative (tier≤2) sources surfaced as a *flag* rather
than silently resolved (substrate §1). This is the *structural* verification layer — it "falls out
of the claim store" and is **deterministic, not an agent** (substrate §6(2)).

:class:`Corroborator` is the M9-internal seam (there is no ``core`` protocol for it — corroboration
is a standalone pass M9 runs, not a gate other milestones call). ``evaluate(entity, field)``:

1. reads the non-superseded *field* claims for the ``(entity, field)`` (the merge layer's
   ``claims_for`` — same data ``current_value`` reads; M9.2 *complements* merge, it does not rank);
2. groups them by *agreement* on ``value_json`` under the field's configured
   :class:`EqualityMode` (exact / numeric-tolerance / semantic — type-aware equality);
3. counts the **independent** tier≤3 sources backing each value-group (distinct ``source_url`` host
   *and* distinct resolver/``source_key`` — same vendor or same domain counts once) and writes it to
   each claim's ``corroborations``;
4. promotes a claim's ``verification_status`` to ``verified`` when its group clears the field's
   ``corroboration_min`` independent sources (or a tier-1 deterministic claim on a
   ``single_source_sufficient`` field) — unless an authoritative conflict is open, in which case it
   raises a ``conflict_flag`` for the review queue (M13.1) and promotes nothing (never auto-picks).

The promotion verdict rides the **already-mutable** ``claim.verification_status`` /
``claim.corroborations`` columns via :func:`clue_research.claimstore.record_verification` — no
trigger change, no ``claim`` ALTER (the 0002/0004/0008 allow-list already permits them). The
per-field config (``corroboration_min``, ``single_source_sufficient``, ``equality_mode``) is
versioned data in ``field_definition`` (conventions §2 — policy is data), read via
:func:`clue_research.claimstore.get_corroboration_config`; changing it changes promotion with no
code change. The equality function and the independence rule are pluggable behind
:class:`CorroborationPolicy`, so a per-vertical pack can demand a stricter rule without touching the
evaluator (swap note, M09 §M9.2).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimFlavor,
    ClaimId,
    EntityId,
    EntityType,
    EqualityMode,
    VerificationStatus,
    can_be_promoted,
    normalize_host,
    serialize_value_json,
)
from clue_core import values_agree as _core_values_agree
from clue_core.field import FieldKey
from clue_db import ConnFactory, transaction
from clue_obs.otel import (
    ATTR_ENTITY_ID,
    ATTR_ENTITY_TYPE,
    ATTR_FIELD_KEY,
    ATTR_N_CLAIMS,
    ATTR_N_SOURCES,
    SPAN_VERIFICATION_CORROBORATION,
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    claims_for,
    get_corroboration_config,
    record_verification,
)

# Verification-health metrics (Doc C §6). M9-local metric name strings (the shared sink accepts any
# string), defined here so M9.2 stays self-contained and never edits the shared obs/metrics.py.
METRIC_CORROBORATION_EVALUATIONS = "research.verification.corroboration.evaluations"
METRIC_CORROBORATION_PROMOTED = "research.verification.corroboration.promoted"
METRIC_CORROBORATION_CONFLICTS = "research.verification.corroboration.conflicts"

# M9-local span attribute keys (plain strings; the shared ATTR_* cover entity/field/counts).
ATTR_CONFLICT = "verification.conflict"
ATTR_N_VALUE_GROUPS = "verification.corroboration.value_groups"
ATTR_N_PROMOTED = "verification.corroboration.promoted"


class CorroborationPolicy(BaseModel):
    """The corroboration rules as data (policy-as-data, conventions §2). The per-field *threshold* N
    lives on ``field_definition`` (``corroboration_min``); these are the cross-field knobs the
    evaluator reads — the tier bands and the equality tolerances — so a stricter regime is a config
    change, not a fork (swap note, M09 §M9.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # A claim counts toward *corroboration* only if its tier is at or below this (substrate §6(2):
    # "≥N independent tier≤3 sources"). Tier-4 (LLM synthesis) is never a corroborating source — it
    # is gated by the faithfulness judge (M9.3) instead.
    corroboration_tier_ceiling: int = 3
    # Two sources at or below this tier disagreeing raises a conflict flag (substrate §1:
    # "conflicting tier≤2 sources surface as a flag"). A tier≤2 vs tier-4 disagreement is not a
    # conflict. Mirrors the merge layer's ``MergePolicy.conflict_tier_threshold`` default.
    conflict_tier_threshold: int = 2
    # NUMERIC_TOL: two numbers agree if |a-b| <= abs_tol, or <= rel_tol * max(|a|,|b|).
    numeric_rel_tolerance: float = 0.05
    numeric_abs_tolerance: float = 0.0
    # SEMANTIC: beyond token-set containment, two texts agree if their token-set Jaccard >= this.
    semantic_jaccard_threshold: float = 0.5


DEFAULT_CORROBORATION_POLICY = CorroborationPolicy()


class ValueGroup(BaseModel):
    """One agreement group within an ``(entity, field)``: the claims whose ``value_json`` agree by
    the field's equality mode, with the count of independent tier≤3 sources backing them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    representative_value: JsonValue
    claim_ids: tuple[ClaimId, ...]
    independent_sources: int  # independent tier≤3, non-rejected, promotable sources in this group
    meets_threshold: bool  # independent_sources >= the field's corroboration_min
    promoted: bool  # at least one claim in the group ended this eval as ``verified``


class CorroborationResult(BaseModel):
    """The deterministic, idempotent outcome of :meth:`Corroborator.evaluate` for one ``(entity,
    field)`` — the value-groups, the promoted (now-``verified``) claim ids, and the authoritative
    conflict (if any). The promotion is surfaced as the ``verification_status`` transition the merge
    view honours; ``conflict`` mirrors the ``conflict_flag`` row written for the review queue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: FieldKey
    value_groups: tuple[ValueGroup, ...] = ()
    promoted_claim_ids: tuple[ClaimId, ...] = ()
    conflict: bool = False
    conflicting_claim_ids: tuple[ClaimId, ...] = ()


# --- equality / grouping / independence (DB-free, unit-testable) -------------
# Value agreement is the substrate's shared :func:`core.values_agree` — the merge layer's conflict /
# distinctness check uses the *same* predicate under the field's ``equality_mode``, so "same value"
# is decided identically on both surfaces (DRY; one seam). This thin adapter binds the cross-field
# tolerances carried on the :class:`CorroborationPolicy`; the merge passes its ``MergePolicy``'s
# tolerances to the same core function (a no-DB drift guard asserts the two default-align).


def values_agree(
    a: JsonValue, b: JsonValue, *, mode: EqualityMode, policy: CorroborationPolicy
) -> bool:
    """Whether two ``value_json`` payloads *agree* under ``mode`` — the corroboration equality,
    delegating to :func:`core.values_agree` with this policy's tolerances (the one equality contract
    the merge conflict check shares)."""
    return _core_values_agree(
        a,
        b,
        mode=mode,
        numeric_rel_tolerance=policy.numeric_rel_tolerance,
        numeric_abs_tolerance=policy.numeric_abs_tolerance,
        semantic_jaccard_threshold=policy.semantic_jaccard_threshold,
    )


def group_by_agreement(
    claims: Sequence[Claim], *, mode: EqualityMode, policy: CorroborationPolicy
) -> list[list[Claim]]:
    """Greedily group ``claims`` (pre-sorted deterministically by the caller) by agreement on
    ``value_json``. Each claim joins the first existing group whose representative it agrees with,
    else opens a new group — so grouping is deterministic even when agreement is non-transitive
    (numeric tolerance / semantic overlap), and the first (lowest-tier, earliest) claim anchors its
    group's representative value."""
    groups: list[list[Claim]] = []
    representatives: list[Claim] = []
    for claim in claims:
        for index, rep in enumerate(representatives):
            if values_agree(claim.value_json, rep.value_json, mode=mode, policy=policy):
                groups[index].append(claim)
                break
        else:
            representatives.append(claim)
            groups.append([claim])
    return groups


def _host(source_url: str | None) -> str | None:
    """The registrable host of a ``source_url`` (lowercased, ``www.`` stripped), or ``None`` for an
    absent / host-less URL. Two claims sharing a host are not independent.

    Delegates to the shared :func:`clue_core.normalize_host` fold (M9.4 DRY consolidation — one
    host normalizer with the identity-binding ``normalize_url`` and the resolver target-lock),
    which uses ``hostname`` (userinfo/port/IPv6-bracket safe) and re-parses a scheme-less but real
    authority (``"acme.com/x"``) with a ``//`` prefix so it is recognised, not treated as
    host-less."""
    if not source_url:
        return None
    return normalize_host(source_url) or None


def independent_source_count(claims: Sequence[Claim]) -> int:
    """The number of **independent** sources among ``claims`` (substrate §6(2)).

    Two claims are *not* independent if they share a (non-empty) ``source_url`` host **or** a
    (non-empty) ``source_key`` — "two claims from the same vendor or the same domain count once".
    Independence is computed as connected components over those two shared-attribute edges (a group
    linked by any chain of shared host/vendor counts once) — the conservative anti-gaming reading,
    so one vendor or one domain can never masquerade as N corroborations. Claims with neither a host
    nor a source_key (no identifiable origin) collapse into a single component (they cannot *prove*
    independence); in practice resolver claims always carry a ``source_key``.
    """
    n = len(claims)
    if n == 0:
        return 0
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    host_of: dict[str, int] = {}
    key_of: dict[str, int] = {}
    anon: int | None = None
    for i, claim in enumerate(claims):
        host = _host(claim.source_url)
        key = claim.source_key
        if host is not None:
            if host in host_of:
                union(i, host_of[host])
            else:
                host_of[host] = i
        if key:
            if key in key_of:
                union(i, key_of[key])
            else:
                key_of[key] = i
        if host is None and not key:
            if anon is None:
                anon = i
            else:
                union(i, anon)
    return len({find(i) for i in range(n)})


# --- the Corroborator -------------------------------------------------------


# A claim whose verification_status is one of these is not a usable corroborating/conflict source:
# REJECTED is known-bad, FLAGGED is pending human review — neither may silently verify a neighbour.
_NON_SOURCE_STATUSES = (VerificationStatus.REJECTED, VerificationStatus.FLAGGED)


def _is_counting(claim: Claim, policy: CorroborationPolicy) -> bool:
    """Whether a claim may *count* as a corroborating source: tier within the ceiling, not
    rejected/flagged, and structurally promotable (a span-less tier-4 or weak-binding contact claim
    is not a source — it can never be the field's truth, so it must not corroborate one)."""
    return (
        claim.source_tier <= policy.corroboration_tier_ceiling
        and claim.verification_status not in _NON_SOURCE_STATUSES
        and can_be_promoted(claim)
    )


def _is_authoritative(claim: Claim, policy: CorroborationPolicy) -> bool:
    """Whether a claim is an *authoritative* source whose disagreement raises a conflict flag
    (tier≤threshold, not rejected/flagged, promotable). Shares the tier band, the equality predicate
    (``core.values_agree``) and the pairwise check with the merge layer's ``_conflict``, but is
    **stricter on status**: it also excludes ``FLAGGED`` (via ``_NON_SOURCE_STATUSES``), where the
    merge's ``_is_eligible`` still admits a FLAGGED tier≤2 claim. The merge over-flags toward
    review; this ``conflict_flag`` is the authoritative signal M13.1 consumes."""
    return (
        claim.source_tier <= policy.conflict_tier_threshold
        and claim.verification_status not in _NON_SOURCE_STATUSES
        and can_be_promoted(claim)
    )


class Corroborator:
    """The M9.2 corroboration engine — deterministic, idempotent promotion + conflict detection.

    Constructed with the :class:`CorroborationPolicy`, a connection factory (defaults to a committed
    transaction per ``evaluate``), and an optional metric sink. Injected at the ``api`` composition
    root; the per-field threshold/equality config is read per call from ``field_definition``.
    """

    def __init__(
        self,
        *,
        policy: CorroborationPolicy = DEFAULT_CORROBORATION_POLICY,
        conn_factory: ConnFactory = transaction,
        record_conflicts: bool = True,
        sink: MetricSink | None = None,
    ) -> None:
        self._policy = policy
        self._conn_factory = conn_factory
        self._record_conflicts = record_conflicts
        self._sink = sink

    async def evaluate(
        self,
        entity_id: EntityId,
        field_key: FieldKey | str,
        *,
        scope: WorkspaceScope,
        entity_type: EntityType | None = None,
    ) -> CorroborationResult:
        """Corroborate one ``(entity, field)``: group, count, promote, flag. Deterministic and
        idempotent — re-running with the same claims yields the same verdicts and writes no new rows
        (in-place verdict UPDATEs + one upserted open conflict_flag).

        ``scope`` is **required** (M2.5 — fail-closed): corroboration runs within the tenant view it
        is given (public-footprint ∪ that tenant's private), so a private field is corroborated only
        against claims that tenant can see. ``entity_type`` is for the trace span only.
        """
        field_key_s = str(field_key)
        attrs: dict[str, object] = {
            ATTR_ENTITY_ID: str(entity_id),
            ATTR_FIELD_KEY: field_key_s,
        }
        if entity_type is not None:
            attrs[ATTR_ENTITY_TYPE] = entity_type.value
        with traced_step(SPAN_VERIFICATION_CORROBORATION, **attrs) as span:
            async with self._conn_factory() as conn:
                result = await self._evaluate(conn, entity_id, field_key_s, scope)
            apply_attributes(
                span,
                {
                    ATTR_N_CLAIMS: sum(len(g.claim_ids) for g in result.value_groups),
                    ATTR_N_VALUE_GROUPS: len(result.value_groups),
                    ATTR_N_SOURCES: max(
                        (g.independent_sources for g in result.value_groups), default=0
                    ),
                    ATTR_N_PROMOTED: len(result.promoted_claim_ids),
                    ATTR_CONFLICT: result.conflict,
                },
            )
            self._emit_metrics(result)
            return result

    async def _evaluate(
        self, conn: AsyncConnection, entity_id: EntityId, field_key: str, scope: WorkspaceScope
    ) -> CorroborationResult:
        cfg = await get_corroboration_config(
            conn,
            field_key,
            scope=(
                FieldRegistryScope.for_workspace(scope.workspace_id)
                if scope.workspace_id is not None
                else FieldRegistryScope.global_only()
            ),
        )
        mode = EqualityMode(cfg.equality_mode) if cfg is not None else EqualityMode.EXACT
        threshold = cfg.corroboration_min if cfg is not None else 1
        single_source_sufficient = cfg.single_source_sufficient if cfg is not None else False

        claims = [
            c
            for c in await claims_for(conn, entity_id, field_key, scope=scope)
            if c.claim_flavor is ClaimFlavor.FIELD_CLAIM
        ]
        if not claims:
            return CorroborationResult(entity_id=entity_id, field_key=field_key)

        # Deterministic order: lowest tier, then earliest, then id — so grouping/representatives are
        # stable across runs (idempotency).
        ordered = sorted(claims, key=lambda c: (c.source_tier, c.collected_at, str(c.id)))
        groups = group_by_agreement(ordered, mode=mode, policy=self._policy)

        independent = [
            independent_source_count([c for c in group if _is_counting(c, self._policy)])
            for group in groups
        ]

        # Conflict: two authoritative (tier≤conflict_tier_threshold) sources *disagree* under the
        # field's equality mode. Checked pairwise over the authoritative claims rather than by
        # counting value-groups, so non-transitive modes (numeric tolerance / semantic) cannot mask
        # a genuine conflict behind a bridging group anchor (e.g. 960 / 1000 / 1040 at rel-tol 0.05
        # all join 1000's group, yet 960 and 1040 disagree). Each authoritative claim that disagrees
        # with any other is surfaced in the flag (the agreeing middle value is not).
        authoritative = [c for c in ordered if _is_authoritative(c, self._policy)]
        conflicting_claim_ids = tuple(
            c.id
            for c in authoritative
            if any(
                o.id != c.id
                and not values_agree(c.value_json, o.value_json, mode=mode, policy=self._policy)
                for o in authoritative
            )
        )
        conflict = bool(conflicting_claim_ids)

        # Decide each claim's target (status, corroborations); apply only real changes (idempotent).
        promoted_ids: list[ClaimId] = []
        group_promoted: list[bool] = []
        for group, indep in zip(groups, independent, strict=True):
            group_meets = indep >= threshold
            promoted_in_group = False
            for claim in group:
                target_corr = indep
                target_status = claim.verification_status
                # Only tier≤3, non-rejected/non-flagged claims have their accuracy verdict driven by
                # corroboration; tier-4 is the judge's (M9.3), and rejected/flagged are left as-is.
                if (
                    claim.source_tier <= self._policy.corroboration_tier_ceiling
                    and claim.verification_status
                    not in (VerificationStatus.REJECTED, VerificationStatus.FLAGGED)
                ):
                    promote = (
                        can_be_promoted(claim)
                        and not conflict
                        and (group_meets or (single_source_sufficient and claim.source_tier == 1))
                    )
                    target_status = (
                        VerificationStatus.VERIFIED if promote else VerificationStatus.UNVERIFIED
                    )
                if (
                    target_status != claim.verification_status
                    or target_corr != claim.corroborations
                ):
                    await record_verification(
                        conn, claim.id, status=target_status, corroborations=target_corr
                    )
                if target_status is VerificationStatus.VERIFIED:
                    promoted_ids.append(claim.id)
                    promoted_in_group = True
            group_promoted.append(promoted_in_group)

        if conflict and self._record_conflicts:
            await self._raise_conflict_flag(conn, entity_id, field_key, conflicting_claim_ids)

        value_groups = tuple(
            ValueGroup(
                representative_value=group[0].value_json,
                claim_ids=tuple(c.id for c in group),
                independent_sources=indep,
                meets_threshold=indep >= threshold,
                promoted=promoted,
            )
            for group, indep, promoted in zip(groups, independent, group_promoted, strict=True)
        )
        return CorroborationResult(
            entity_id=entity_id,
            field_key=field_key,
            value_groups=value_groups,
            promoted_claim_ids=tuple(promoted_ids),
            conflict=conflict,
            conflicting_claim_ids=conflicting_claim_ids,
        )

    async def _raise_conflict_flag(
        self,
        conn: AsyncConnection,
        entity_id: EntityId,
        field_key: str,
        conflicting_claim_ids: Sequence[ClaimId],
    ) -> None:
        """Upsert the single *open* conflict_flag for this ``(entity, field)`` (the partial unique
        index keeps it idempotent — re-evaluation refreshes the contender ids, never accumulates
        rows, and never changes ``raised_at``). M9.2 only *raises*; resolving (``resolved_by``) is
        M13.1's human-review / re-research job."""
        await conn.execute(
            text(
                """
                INSERT INTO conflict_flag (entity_id, field_key, conflicting_claim_ids)
                VALUES (:entity_id, :field_key, CAST(:ids AS jsonb))
                ON CONFLICT (entity_id, field_key) WHERE resolved_by IS NULL
                DO UPDATE SET conflicting_claim_ids = EXCLUDED.conflicting_claim_ids
                """
            ),
            {
                "entity_id": str(entity_id),
                "field_key": field_key,
                "ids": serialize_value_json([str(cid) for cid in conflicting_claim_ids]),
            },
        )

    def _emit_metrics(self, result: CorroborationResult) -> None:
        sink = self._sink or get_metric_sink()
        labels = {"field_key": str(result.field_key)}
        sink.add(METRIC_CORROBORATION_EVALUATIONS, 1, labels)
        if result.conflict:
            sink.add(METRIC_CORROBORATION_CONFLICTS, 1, labels)
        # Per-(field) promotion count — the "claims that survived" precision signal (staged-flow
        # §7e, Doc C §6). The per-(ICP, source) breakdown is added when the ICP/source labels are
        # threaded in at the api composition root (the request carries neither today).
        if result.promoted_claim_ids:
            sink.add(METRIC_CORROBORATION_PROMOTED, len(result.promoted_claim_ids), labels)
