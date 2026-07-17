"""M9.5 — the freshness TTL engine + re-research cadence (ENG-149).

"The master database is a myth": the workforce and tech stack churn constantly, so **freshness is a
first-class signal**, not an afterthought (substrate §6 / Doc C §1). Every claim has ``observed_at``
+ a field-level TTL; the merge view treats a stale claim as refresh-eligible, scoring discounts it,
and re-research runs on a cadence (~90-day default; signal fields faster; personal fields shorter —
Doc D §4). This module computes staleness per claim, exposes it as a queryable signal, and emits the
re-research candidates the M7 durable executor schedules.

:class:`FreshnessImpl` implements the Beat-0 :class:`clue_core.verification.Freshness`
protocol, so callers in other milestone packages (M6.3 scoring discounts stale signals; M7.5's
scheduler asks for re-research candidates) depend only on the ``core`` seam; the concrete engine is
injected at the ``api`` composition root.

**The load-bearing constraint — ``freshness_state`` is a DERIVED disposition, not a claim column.**
The M09 spec's "writes ``claim.freshness_state``" predates the implemented substrate, which models
freshness as a *derived* property: the M1.2 merge view already computes ``FRESH``/``STALE`` onto
``CurrentValue.freshness_state`` from ``observed_at|collected_at`` vs the field TTL — never onto the
immutable, append-only ``claim`` row (the 0004 trigger allow-list is only ``superseded_by/
verification_status/corroborations``; there is no ``freshness_state`` column or enum anywhere in the
schema). M9.5 follows that pattern (same resolution as M9.4's immutable ``identity_binding``):

* :meth:`FreshnessImpl.evaluate` returns the per-claim verdict as the *computed*
  :class:`~clue_core.verification.Staleness` (``FRESH``/``STALE``/``EXPIRED``) — the
  queryable signal scoring and the merge read; nothing is written to the claim.
* ``EXPIRED`` is the *retention age-out* disposition (Doc D §4): a personal claim past its retention
  horizon. M9.5 *detects and surfaces* these to M10.5 for age-out
  (:meth:`FreshnessImpl.due_for_age_out`); M10.5 owns the lawful-retention/erasure machinery (M9.5
  never erases). For a claim past its **freshness TTL** (the ``STALE`` case), the existing
  ``TTL_GATES_ELIGIBILITY`` merge already prefers ``FRESH`` and only falls back to a past-TTL claim
  when nothing fresh exists — so a stale claim never wins over a fresh one with no merge change.
  ``EXPIRED`` (retention age-out), however, is **not** implied by past-TTL: a retention horizon may
  be *shorter* than the field TTL (``sensitive`` data is intentionally erased at 30d though its
  ``contact.facet`` TTL is 90d — aggressive minimization, Doc D §4), so the TTL-only merge does not
  know such a claim is expired and can still serve it until M10.5 tombstones it. Hard exclusion of
  an expired-but-within-TTL claim from the merge is therefore owned by M10.5's erasure (a
  retention-aware merge is a tracked M1.2/M10.5 follow-up); M9.5's contract is detect + surface.

The engine is **policy-as-data** (conventions §2): the per-field-class ``ttl`` (staleness threshold)
and ``refresh_cadence`` (re-research spacing) are versioned :class:`CadencePolicy` rows in
``cadence_policy`` (per-client overridable; read via :func:`load_cadence_policy`), defaulting from
the shared :class:`~clue_config.schema.FreshnessTtls`. The personal-claim **retention
horizon** is *referenced* from :class:`~clue_config.policy.RetentionTtls` (the M10.5-owned
placeholder), not redefined here. Re-research *execution* lives entirely behind the
``re_research_candidate`` row seam — M7 schedules and runs; M9.5 only emits — so the executor swap
(Postgres state machine -> Temporal) never touches the freshness engine.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from opentelemetry.trace import Span
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.policy import RetentionTtls
from clue_config.schema import FreshnessTtls
from clue_core import (
    AgeOutCandidate,
    Claim,
    ClaimId,
    EntityId,
    FieldClass,
    FreshnessState,
    ReResearchCandidate,
    Staleness,
    UseClass,
    classify_field_key,
)
from clue_core.field import FieldKey
from clue_db import ConnFactory, transaction
from clue_obs.otel import (
    SPAN_VERIFICATION_FRESHNESS,
    MetricSink,
    apply_attributes,
    get_metric_sink,
    traced_step,
)
from clue_research.claimstore import ALL_TENANTS, TenantScope

# Verification-health metrics (Doc C §6 — freshness is a verification-health number). M9-local
# metric name strings (the shared sink accepts any string), defined here so M9.5 stays self-
# contained and never edits the shared obs/metrics.py. Emitted by the scan operations
# (due_for_refresh / due_for_age_out), not by the pure per-claim ``evaluate`` (a hot, pure fn).
METRIC_FRESHNESS_SCANNED = "research.verification.freshness.scanned"
METRIC_FRESHNESS_STALE = "research.verification.freshness.stale"
METRIC_FRESHNESS_EXPIRED = "research.verification.freshness.expired"
METRIC_FRESHNESS_DUE = "research.verification.freshness.due"

# M9-local span attribute keys (plain strings; the scan emits aggregate counts, never a raw id —
# short ints pass the obs redaction value-shape heuristic, and a candidate is linked precisely via
# its emitted entity_id/field_key, not the span). ``op`` distinguishes the two scan operations so
# the shared ``due`` count (refresh-due vs age-out-due) is never conflated.
ATTR_FRESHNESS_OP = "verification.freshness.op"
ATTR_FRESHNESS_SCANNED = "verification.freshness.scanned"
ATTR_FRESHNESS_STALE = "verification.freshness.stale"
ATTR_FRESHNESS_EXPIRED = "verification.freshness.expired"
ATTR_FRESHNESS_DUE = "verification.freshness.due"

# The two scan operations (the ``op`` label on the span + metrics): refresh-candidate detection vs
# retention age-out detection. They share the ``verification.freshness`` span and the metric names,
# so the label keeps their ``due`` counts as distinct series (a dashboard must not sum them).
_OP_REFRESH = "refresh"
_OP_AGE_OUT = "age_out"

# The field-classes whose claims are *personal* and therefore age out at a retention horizon
# (Doc D §4). Non-personal classes (core/account firmographics, resonance) never go ``EXPIRED`` —
# they only go ``STALE`` and get refreshed; there is no lawful-retention age-out for a public fact.
_PERSONAL_FIELD_CLASSES: frozenset[FieldClass] = frozenset(
    {FieldClass.CONTACT, FieldClass.CONTACT_FACET}
)

_DEFAULT_RE_RESEARCH_TTL_DAYS = 90  # spec ~90-day re-research default (unlisted/pack classes)


# --- pure helpers (DB-free, unit-testable) ----------------------------------


def reference_time(claim: Claim) -> datetime:
    """The time a claim's freshness is measured from: when the source was observed, else when it was
    collected (mirrors ``claimstore.merge._reference_time`` exactly, so the freshness engine and the
    merge view never disagree on a claim's age). DRY note: consolidating both onto one shared helper
    is a backlog item."""
    return claim.observed_at or claim.collected_at


def staleness(
    *,
    claim_id: ClaimId,
    reference_time: datetime,
    now: datetime,
    ttl: timedelta | None,
    retention_horizon: timedelta | None = None,
) -> Staleness:
    """The pure staleness verdict for one claim (the heart of :meth:`FreshnessImpl.evaluate`).

    ``EXPIRED`` (checked first) when a ``retention_horizon`` is given and the age exceeds it (the
    personal-claim age-out, Doc D §4); else ``STALE`` when a ``ttl`` is given and the age exceeds
    it; else ``FRESH``. ``EXPIRED`` is independent of the TTL: a retention horizon can be *shorter*
    than the TTL (``sensitive`` data ages out at 30d though its field TTL is 90d), so an expired
    claim is not necessarily stale — the merge (TTL-only) may still serve it until M10.5 erases it
    (see the module docstring; hard merge-exclusion of expired claims is an M1.2/M10.5 follow-up).

    Age is clamped at 0 (a future-dated ``observed_at`` from clock skew reads as 0 days old, fresh).
    Deterministic given a fixed ``now`` (re-evaluation is idempotent — M09 §M9.5 acceptance)."""
    age = now - reference_time
    age_days = max(0.0, age.total_seconds() / 86400.0)
    ttl_days = ttl.total_seconds() / 86400.0 if ttl is not None else None
    if retention_horizon is not None and age > retention_horizon:
        state = FreshnessState.EXPIRED
    elif ttl is not None and age > ttl:
        state = FreshnessState.STALE
    else:
        state = FreshnessState.FRESH
    return Staleness(
        claim_id=claim_id,
        state=state,
        age_days=round(age_days, 6),
        ttl_days=ttl_days,
    )


def retention_horizon_for(
    field_class: FieldClass, use_class: UseClass | None, retention: RetentionTtls
) -> timedelta | None:
    """The retention horizon a claim ages out (``EXPIRED``) past, or ``None`` when it never does.

    Only *personal* claims (``contact.*`` / ``contact.facet.*``) carry a retention horizon (Doc D
    §4 — minimize retained personal data; a public firmographic fact has none). The horizon is
    keyed on the claim's **stamped ``use_class``** (read from the M10.5-owned
    :class:`~clue_config.policy.RetentionTtls` placeholder, ``sensitive`` shortest):
    ``SENSITIVE`` -> ``sensitive_claim_ttl``; ``PROFESSIONAL_PUBLIC`` -> ``professional_claim_ttl``;
    ``PERSONAL_PUBLIC_NON_SENSITIVE`` -> ``personal_claim_ttl``.

    A claim whose ``use_class`` is **unstamped (``None``)** carries **no** retention horizon and so
    never ages out: the horizon is use-class-specific and we will not guess one for an unclassified
    claim (a plain ``contact.role_on_committee`` may be born with ``use_class=None`` — only
    ``contact.facet.*`` *requires* it). The use-class is stamped at extraction (M10.2); once
    stamped, the claim ages out at its class-appropriate horizon. Erring toward not-erasing an
    unclassified structural fact is the safe direction; M10.5 owns the actual erasure regardless."""
    if field_class not in _PERSONAL_FIELD_CLASSES or use_class is None:
        return None
    if use_class is UseClass.SENSITIVE:
        return retention.sensitive_claim_ttl
    if use_class is UseClass.PROFESSIONAL_PUBLIC:
        return retention.professional_claim_ttl
    return retention.personal_claim_ttl


# --- policy-as-data ---------------------------------------------------------


def _default_ttl_by_field_class() -> dict[str, timedelta]:
    """The field-class TTL defaults, sourced from the shared :class:`FreshnessTtls` shape (M0.4) so
    the merge view and the freshness engine read one definition, not two drifting copies."""
    return dict(FreshnessTtls().by_field_class)


class CadencePolicy(BaseModel):
    """The freshness/refresh config as data (policy-as-data, conventions §2). Persisted as
    per-field-class ``cadence_policy`` rows (per-client overridable); the engine reads it at
    construction. Changing a class's TTL or cadence is a config change, regression-checked by M9.6.

    * ``ttl_by_field_class`` — the fresh->stale threshold per field-class. Defaults from
      :class:`FreshnessTtls` (core 365d / account 180d / account.resonance 90d / contact 180d /
      contact.facet 90d), so a signal-bearing ``account.*`` field is already staler-sooner than a
      ``core.*`` firmographic, and a ``contact.facet.*`` personal field staler-sooner than an
      account firmographic (M09 §M9.5 AC). A per-field ``field_definition.freshness_ttl`` override
      (read by the scan) can make a specific signal field shorter still.
    * ``cadence_by_field_class`` — the re-research spacing (``due_at = reference_time + cadence``).
      Empty entries fall back to that class's ``ttl`` (so a claim is due for refresh exactly when it
      goes stale, the natural default); set a *shorter* cadence to refresh a hot signal proactively.
    * ``default_ttl`` — the ~90-day re-research default for an unlisted class (e.g. a ``pack``).
    * ``retention`` — the personal-claim retention horizons (``EXPIRED``), *referenced* from the
      M10.5-owned :class:`RetentionTtls`, never redefined here.
    * ``version`` — recorded for observability (which policy version produced these candidates).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ttl_by_field_class: dict[str, timedelta] = Field(default_factory=_default_ttl_by_field_class)
    cadence_by_field_class: dict[str, timedelta] = Field(default_factory=dict)
    default_ttl: timedelta = timedelta(days=_DEFAULT_RE_RESEARCH_TTL_DAYS)
    retention: RetentionTtls = RetentionTtls()
    version: int = Field(default=1, ge=1)

    def ttl_for(self, field_class: FieldClass) -> timedelta:
        """The staleness TTL for a field-class (its configured TTL, else the ~90-day default)."""
        return self.ttl_by_field_class.get(str(field_class), self.default_ttl)

    def cadence_for(self, field_class: FieldClass) -> timedelta:
        """The class-level re-research cadence (its configured cadence, else its class TTL).

        NOTE the engine's scan layers a per-field ``field_definition.freshness_ttl`` override on
        top by taking the *sooner* of this class cadence and the field's own effective TTL, so a
        short-lived field always refreshes at its own (shorter) rate even when a class cadence row
        exists (this accessor is the class-only view; the scan owns the per-field combination)."""
        return self.cadence_by_field_class.get(str(field_class), self.ttl_for(field_class))


DEFAULT_CADENCE_POLICY = CadencePolicy()


# ``AgeOutCandidate`` now lives in ``core.verification`` (phase-3 pre-flight contract-delta): it is
# the M9.5↔M10.5 seam, so M10.5 (``compliance``, which may not import ``verification``) reads it via
# ``core``. Imported above; this package's ``__init__`` re-exports it for back-compat.


# --- internal scan row ------------------------------------------------------


class _ScanRow(NamedTuple):
    """One live field-claim with its computed staleness + the moment it is due for refresh."""

    claim_id: object
    entity_id: object
    field_key: str
    source_tier: int
    due_at: datetime
    staleness: Staleness
    retention_horizon: timedelta | None  # the age-out horizon (None when the claim never ages out)


# --- the Freshness engine ---------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FreshnessImpl:
    """The M9.5 freshness engine (implements :class:`clue_core.verification.Freshness`).

    Constructed with the resolved :class:`CadencePolicy`, a :class:`TenantScope` for the scan
    (defaults to :data:`ALL_TENANTS` — re-research is an operator maintenance scan; the emitted
    candidates carry claim/entity *ids*, never values, so the cross-tenant scan leaks no tenant's
    data), a connection factory (defaults to a committed transaction per scan), and an optional
    metric sink. Injected at the ``api`` composition root; per-client policy is loaded via
    :func:`load_cadence_policy`."""

    def __init__(
        self,
        *,
        policy: CadencePolicy = DEFAULT_CADENCE_POLICY,
        scope: TenantScope = ALL_TENANTS,
        conn_factory: ConnFactory = transaction,
        sink: MetricSink | None = None,
    ) -> None:
        self._policy = policy
        self._scope = scope
        self._conn_factory = conn_factory
        self._sink = sink

    @property
    def policy(self) -> CadencePolicy:
        """The resolved cadence policy this engine reads (so a caller — e.g. the M9.6 eval config
        snapshot — can record its ``version`` for regression traceability)."""
        return self._policy

    def evaluate(self, claim: Claim, *, now: datetime, ttl: timedelta | None = None) -> Staleness:
        """The pure staleness verdict for one claim (``FRESH``/``STALE``/``EXPIRED``), DB-free and
        side-effect-free (no span, no metric — it is a hot function the merge/scoring read).

        ``ttl`` is an override: given (the caller already read the field's
        ``field_definition.freshness_ttl``, so the verdict matches the merge view exactly) it is
        used directly; ``None`` falls back to this engine's in-memory cadence TTL for the claim's
        field-class. The retention horizon (``EXPIRED``) is resolved from the policy by field-class
        and the claim's ``use_class``. Deterministic given a fixed ``now`` (M09 §M9.5)."""
        field_class = classify_field_key(claim.field_key)
        resolved_ttl = ttl if ttl is not None else self._policy.ttl_for(field_class)
        retention = retention_horizon_for(field_class, claim.use_class, self._policy.retention)
        return staleness(
            claim_id=claim.id,
            reference_time=reference_time(claim),
            now=now,
            ttl=resolved_ttl,
            retention_horizon=retention,
        )

    async def due_for_refresh(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[FieldKey, ...] | None = None,
        now: datetime | None = None,
    ) -> tuple[ReResearchCandidate, ...]:
        """Scan the live field claims in scope and return the ``(entity, field)`` re-research
        candidates that are **due** (``now >= reference_time + refresh_cadence``) and not expired,
        ranked by ``(priority asc, due_at asc, entity, field)`` — most-trusted (lowest-tier)
        stale claim first. It **returns candidates; it does not fetch or refresh** (M7 schedules and
        runs). Emits the ``verification.freshness`` span + the freshness-health metrics.

        ``now`` defaults to the current UTC time; pass a fixed ``now`` for deterministic tests. The
        optional ``entity_ids``/``field_keys`` bound the scan (a per-account or per-field refresh
        scope); omitted, it scans the whole store in scope (an operator batch)."""
        now = now or _utcnow()
        with traced_step(SPAN_VERIFICATION_FRESHNESS) as span:
            rows = await self._scan(entity_ids, field_keys, now)
            candidates = self._group_refresh(rows, now)
            self._emit_scan(span, rows, due=len(candidates), op=_OP_REFRESH)
            return candidates

    async def due_for_age_out(
        self,
        *,
        entity_ids: tuple[EntityId, ...] | None = None,
        field_keys: tuple[FieldKey, ...] | None = None,
        now: datetime | None = None,
    ) -> tuple[AgeOutCandidate, ...]:
        """Scan the live field claims in scope and return the **personal claims past their retention
        horizon** (``EXPIRED``), surfaced to M10.5 for age-out/erasure (the M9.5<->M10.5 seam — M9.5
        detects, M10.5 erases). One per expired claim, sorted ``(entity, field, claim)``. Emits the
        ``verification.freshness`` span + the freshness-health metrics. Like
        :meth:`due_for_refresh`, it returns candidates; it never erases."""
        now = now or _utcnow()
        with traced_step(SPAN_VERIFICATION_FRESHNESS) as span:
            rows = await self._scan(entity_ids, field_keys, now)
            out = [
                AgeOutCandidate(
                    claim_id=r.claim_id,  # type: ignore[arg-type]
                    entity_id=r.entity_id,  # type: ignore[arg-type]
                    field_key=r.field_key,
                    age_days=r.staleness.age_days,
                    # the actual retention horizon it aged out past (the use-class-keyed horizon —
                    # NOT the freshness TTL ``staleness.ttl_days``, which is a different quantity).
                    retention_days=(
                        r.retention_horizon.total_seconds() / 86400.0
                        if r.retention_horizon is not None
                        else None
                    ),
                )
                for r in rows
                if r.staleness.state is FreshnessState.EXPIRED
            ]
            out.sort(key=lambda c: (str(c.entity_id), c.field_key, str(c.claim_id)))
            self._emit_scan(span, rows, due=len(out), op=_OP_AGE_OUT)
            return tuple(out)

    async def record_re_research_candidates(
        self, conn: AsyncConnection, candidates: Iterable[ReResearchCandidate]
    ) -> int:
        """Persist re-research candidates to the ``re_research_candidate`` emission queue M7 drains,
        returning the count of *newly* inserted rows. Idempotent: ``ON CONFLICT (entity_id,
        field_key, due_at) DO NOTHING`` makes re-emitting the same due window a no-op, so a re-run
        of :meth:`due_for_refresh` -> ``record_re_research_candidates`` adds nothing. Detection (the
        scan) is kept a pure read; this explicit write is the emit path the composition root / M7
        calls."""
        inserted = 0
        for candidate in candidates:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO re_research_candidate
                        (entity_id, field_key, stale_claim_ids, due_at, priority)
                    VALUES
                        (:entity_id, :field_key, :stale_claim_ids, :due_at, :priority)
                    ON CONFLICT (entity_id, field_key, due_at) DO NOTHING
                    """
                ),
                {
                    "entity_id": str(candidate.entity_id),
                    "field_key": str(candidate.field_key),
                    # asyncpg encodes a Python list of uuid strings into the uuid[] column directly
                    # (the param type is inferred from the column — no CAST needed; a text-array
                    # literal is rejected as "a sized iterable container expected").
                    "stale_claim_ids": [str(claim_id) for claim_id in candidate.stale_claim_ids],
                    "due_at": candidate.due_at,
                    "priority": candidate.priority,
                },
            )
            inserted += result.rowcount or 0
        return inserted

    # --- internals ----------------------------------------------------------

    def _group_refresh(
        self, rows: Sequence[_ScanRow], now: datetime
    ) -> tuple[ReResearchCandidate, ...]:
        """Group due, non-expired rows into one :class:`ReResearchCandidate` per
        ``(entity, field)``, ranked deterministically. ``priority`` is the most-trusted (lowest)
        tier among the due claims (refresh the load-bearing facts soonest); ``due_at`` is the
        earliest among them; expired rows are excluded (they go to age-out, not refresh)."""
        groups: dict[tuple[object, str], list[_ScanRow]] = defaultdict(list)
        for row in rows:
            if row.staleness.state is FreshnessState.EXPIRED:
                continue
            if now >= row.due_at:
                groups[(row.entity_id, row.field_key)].append(row)

        candidates: list[ReResearchCandidate] = []
        for (entity_id, field_key), group in groups.items():
            ordered = sorted(group, key=lambda r: (r.due_at, str(r.claim_id)))
            candidates.append(
                ReResearchCandidate(
                    entity_id=entity_id,  # type: ignore[arg-type]
                    field_key=field_key,
                    stale_claim_ids=tuple(r.claim_id for r in ordered),  # type: ignore[misc]
                    due_at=min(r.due_at for r in group),
                    priority=min(r.source_tier for r in group),
                )
            )
        candidates.sort(key=lambda c: (c.priority, c.due_at, str(c.entity_id), str(c.field_key)))
        return tuple(candidates)

    async def _scan(
        self,
        entity_ids: tuple[EntityId, ...] | None,
        field_keys: tuple[FieldKey, ...] | None,
        now: datetime,
    ) -> list[_ScanRow]:
        """Fetch the live field claims in scope (tenant-scoped, discovery claims excluded) and
        compute each one's staleness + due time. One claim query + one TTL query, like the merge
        view; no claimstore internals are imported (raw column reads, mirroring
        ``identity_binding._source_prior`` / ``pre_spend._covered_tiers``)."""
        scope_sql, scope_params = self._scope.predicate()
        clauses = ["superseded_by IS NULL", "claim_flavor = 'field_claim'", scope_sql]
        params: dict[str, object] = dict(scope_params)
        binds: list[Any] = []
        if entity_ids:
            clauses.append("entity_id IN :eids")
            params["eids"] = [str(e) for e in entity_ids]
            binds.append(bindparam("eids", expanding=True))
        if field_keys:
            clauses.append("field_key IN :fkeys")
            params["fkeys"] = [str(f) for f in field_keys]
            binds.append(bindparam("fkeys", expanding=True))
        stmt = text(
            "SELECT id, entity_id, field_key, source_tier, observed_at, collected_at, use_class "
            f"FROM claim WHERE {' AND '.join(clauses)}"
        )
        if binds:
            stmt = stmt.bindparams(*binds)

        async with self._conn_factory() as conn:
            rows = (await conn.execute(stmt, params)).all()
            field_ttls = await self._field_ttls(conn, {row[2] for row in rows})

        scanned: list[_ScanRow] = []
        for cid, eid, field_key, tier, observed_at, collected_at, raw_use in rows:
            field_class = classify_field_key(field_key)
            ref = observed_at or collected_at
            # the staleness threshold: the per-field freshness_ttl override (the same TTL the merge
            # reads) wins; else the cadence policy's class TTL.
            effective_ttl = field_ttls.get(field_key) or self._policy.ttl_for(field_class)
            # the refresh due spacing: refresh at the *sooner* of the configured class cadence and
            # the field's own effective TTL. Taking the min means a short per-field freshness_ttl
            # override always shortens the cadence (a field is never stale-but-never-due, even with
            # a class cadence row — load_cadence_policy populates cadence for every loaded
            # class), while an explicit *faster* class cadence still refreshes proactively. (A class
            # cadence longer than a field's TTL would only serve stale data unrefreshed, so it is
            # intentionally not honored past the field's TTL.)
            explicit_cadence = self._policy.cadence_by_field_class.get(str(field_class))
            cadence = (
                min(explicit_cadence, effective_ttl)
                if explicit_cadence is not None
                else effective_ttl
            )
            use_class = UseClass(raw_use) if raw_use is not None else None
            retention = retention_horizon_for(field_class, use_class, self._policy.retention)
            scanned.append(
                _ScanRow(
                    claim_id=cid,
                    entity_id=eid,
                    field_key=field_key,
                    source_tier=int(tier),
                    due_at=ref + cadence,
                    staleness=staleness(
                        claim_id=cid,
                        reference_time=ref,
                        now=now,
                        ttl=effective_ttl,
                        retention_horizon=retention,
                    ),
                    retention_horizon=retention,
                )
            )
        return scanned

    async def _field_ttls(
        self, conn: AsyncConnection, field_keys: set[str]
    ) -> dict[str, timedelta]:
        """The per-field ``field_definition.freshness_ttl`` overrides for the scanned fields (the
        same TTL the merge view reads), so the scan's staleness aligns with the merge. A field with
        no declared TTL is absent here and falls back to the cadence field-class TTL."""
        if not field_keys:
            return {}
        stmt = text(
            "SELECT field_key, freshness_ttl FROM field_definition WHERE field_key IN :fkeys"
        ).bindparams(bindparam("fkeys", expanding=True))
        rows = await conn.execute(stmt, {"fkeys": list(field_keys)})
        return {field_key: ttl for field_key, ttl in rows.all() if ttl is not None}

    def _emit_scan(self, span: Span, rows: Sequence[_ScanRow], *, due: int, op: str) -> None:
        """Apply the scan's aggregate counts to the span and the freshness-health metrics, labelled
        by ``op`` (``refresh`` / ``age_out``) so the two scans' shared ``due`` count is never
        conflated by a consumer summing the series."""
        counts = Counter(row.staleness.state for row in rows)
        scanned = len(rows)
        stale = counts[FreshnessState.STALE]
        expired = counts[FreshnessState.EXPIRED]
        apply_attributes(
            span,
            {
                ATTR_FRESHNESS_OP: op,
                ATTR_FRESHNESS_SCANNED: scanned,
                ATTR_FRESHNESS_STALE: stale,
                ATTR_FRESHNESS_EXPIRED: expired,
                ATTR_FRESHNESS_DUE: due,
            },
        )
        sink = self._sink or get_metric_sink()
        labels: Mapping[str, str] = {"op": op}
        sink.add(METRIC_FRESHNESS_SCANNED, scanned, labels)
        if stale:
            sink.add(METRIC_FRESHNESS_STALE, stale, labels)
        if expired:
            sink.add(METRIC_FRESHNESS_EXPIRED, expired, labels)
        if due:
            sink.add(METRIC_FRESHNESS_DUE, due, labels)


async def load_cadence_policy(
    conn: AsyncConnection, *, client_id: str | None = None
) -> CadencePolicy:
    """Load the most-specific :class:`CadencePolicy` for a scope: per-client rows -> global rows ->
    :data:`DEFAULT_CADENCE_POLICY`. The first scope that has *any* ``cadence_policy`` row wins
    (per-client beats global); within it, the latest ``version`` per field-class is taken (with a
    deterministic ``created_at``/``policy_id`` tie-break, so duplicate same-version rows can never
    resolve non-deterministically). Field-classes without a row keep the :class:`FreshnessTtls`
    default; the retention horizon always comes from :class:`RetentionTtls` (not the table).

    Returns the built-in default when no row matches (policy-as-data; fail-soft)."""
    candidates: list[str | None] = []
    if client_id is not None:
        candidates.append(client_id)
    candidates.append(None)  # the global default rows

    for scope_client in candidates:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (field_class)
                        field_class, ttl, refresh_cadence, version
                    FROM cadence_policy
                    WHERE client_id IS NOT DISTINCT FROM :client_id
                    ORDER BY field_class, version DESC, created_at DESC, policy_id DESC
                    """
                ),
                {"client_id": scope_client},
            )
        ).all()
        if not rows:
            continue
        ttl_by_class = _default_ttl_by_field_class()
        cadence_by_class: dict[str, timedelta] = {}
        max_version = 1
        for field_class, ttl, refresh_cadence, version in rows:
            ttl_by_class[str(field_class)] = ttl
            cadence_by_class[str(field_class)] = refresh_cadence
            max_version = max(max_version, int(version))
        return CadencePolicy(
            ttl_by_field_class=ttl_by_class,
            cadence_by_field_class=cadence_by_class,
            version=max_version,
        )
    return DEFAULT_CADENCE_POLICY
